# RZ/V2H IPC Architecture

**Updated:** 2026-10-13
**Status:** source/build contract; the standalone CR8-0 default keeps IPC
disabled, while peer integration and physical link qualification remain
optional follow-up work.

This document describes the checked-in design. It is not a claim of
production readiness or end-to-end target validation.

## 1. Core Topology

| Core | Intended software | Role | Private DDR (CR8/CM33 view) |
|---|---|---|---|
| CR8-0 | NuttX/PX4 | Flight stack | `0x40800000`–`0x417fffff` |
| CR8-1 | NuttX/PX4IO | I/O relay | `0x41800000`–`0x427fffff` |
| CM33 | NuttX raw sample / PX4IO output peer (no PWM backend) | optional safety or ESC peer | Secure SRAM image; secure-DDR shared rings |

See [multicore-memory-map.md](./multicore-memory-map.md) for the authoritative
boot, TCM, SRAM, DDR, and shared-memory map.

## 2. Transport Layers

Two different paths share the RZ/V2H MHU helpers:

1. CA55 ↔ CR8-0 uses the native rptun/OpenAMP/RPMsg implementation and
   registers `/dev/ipcc0`. This is a separate, optional later profile from the
   reference CA55 RPMsg/RPC/uXRCE application path.
2. Raw CR8/CM33 links use an MHU doorbell plus fixed DDR rings through the
   NuttX IPCC upper half.

Buffered `/dev/ipcc0` retains queued bytes on RPMsg exhaustion or temporary
endpoint absence. A low-priority worker retries one packet-sized chunk every
10 ms and wakes writers after progress. A TX mutex serializes its consumer
with direct sends and upper-half notifications; the lifetime mutex prevents
access after cleanup. These are host-tested source contracts. They do not
qualify CA55 negotiation or change raw-link acknowledgment behavior.

`rzv_mhu_core.c` only provides register and IRQ helpers. It does not imply that
OpenAMP or a raw link is enabled.

The raw profile selects the non-secure MHU window. Domain aliases belong to
[the MHU hardware header](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_mhu.h)
and [the memory map](multicore-memory-map.md). Changing access domains requires
physical qualification; it does not implicitly change the shared-memory ABI.

## 3. Raw MHU + Shared-Memory Links

The [channel contract](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_channels.h)
owns device numbers, per-core MHU routes, shared windows, ring layout and ABI
constants. Use it together with the [memory map](multicore-memory-map.md)
instead of transcribing channel or offset tables into another document.

The transport separates doorbell delivery from payload ownership. Producers
must publish cache-visible data before signaling; consumers must observe the
published data before acknowledging it. Ring bounds, channel separation and
recovery epochs are part of the transport contract, not application framing.

Raw-link semantics that callers must design around:

- `write()` takes exactly one 64-byte entry (`RZV_IPC_RAW_PAYLOAD_SIZE`);
  any other length fails with `EMSGSIZE`.
- Each write is stop-and-wait. It blocks until the peer's `read()`
  consumes and acknowledges the entry, for up to
  `CONFIG_RZV_IPC_TX_TIMEOUT_MS` (100 ms). A timeout quarantines the link:
  later reads and writes fail with `ENOLINK`. A slow reader therefore paces
  the writer's loop, and a reader that stops for longer than the timeout
  ends the stream.
- Only the initiator can end a quarantine, by republishing a fresh epoch
  through the `RECOVER` ioctl.
- A quarantined responder adopts the next fresh epoch from a plain `read()`
  or `poll()`, so a nonblocking reader such as the CR8-1 relay rejoins
  without issuing `RECOVER`. This also covers a responder that booted before
  its initiator published. Without a fresh epoch the quarantine stands.
- The CR8 cores share one GIC distributor. Each core claims only its own
  MHU interrupts, when it enables them. After an interrupt-controller
  restart, a core first ends any interrupt the previous image left active,
  so that no priority stays blocked.

## 4. PX4IO Message Protocol

The [PX4IO protocol](../../boards/renesas/rdk-rzv2h/px4io_cr8_0/protocol.h)
owns message types, sizes, magic/version, sequence and CRC fields. Frames must
fit a raw entry. Messages are 28–52 bytes, so every sender (CR8-0 bridge,
CR8-1 relay, CM33) zero-pads each frame to one 64-byte entry. Receivers check
the CRC over the message length only. Its application CRC is distinct from the transport ABI;
OpenAMP/RPMsg does not acquire that framing merely by using the same MHU.

The CR8-0 uORB bridge:

- transmits actuator outputs, selected vehicle commands, vehicle status, and a
  10 Hz heartbeat on `/dev/ipcc1`;
- accepts RC input, ESC status, battery status, and heartbeat frames;
- rejects bad magic, version, type, or CRC;
- counts per-topic sequence gaps;
- bounds receive draining to preserve the transmit/heartbeat schedule.

## 5. Configuration and Availability

| Target/profile | IPC state | Evidence |
|---|---|---|
| PX4 default (`renesas_rdk-rzv2h_default`) | disabled | PX4/NuttX configuration |
| PX4 SIH (`renesas_rdk-rzv2h_sih`) | disabled | source and post-build contracts |
| NuttX `:nsh` | disabled | defconfig |
| NuttX `:ipcc` | CA55/OpenAMP smoke profile | build/source only |
| NuttX `:ipcc-multi` | OpenAMP plus raw-link initiator profiles | build/source only |
| NuttX `:nsh-cr8_1` | standalone shell; raw links disabled | defconfig |
| PX4 CR8-1 IO (`renesas_rdk-rzv2h-io-cr8_1_default`) | `/dev/ipcc1` responder, `/dev/ipcc3` initiator; `px4io_cr8` autostarts from ROMFS | bounded on-target heartbeat/fault capture (below) |
| PX4 CM33 IO (`renesas_rdk-rzv2h-io-cm33_default`) | `/dev/ipcc3` responder | build only; low priority |

The raw drivers, shared-memory ABI, bridge, and example profiles are not the
default runtime path. In particular:

- The NuttX raw CR8-0/CR8-1 link has bounded `ipctest` recover/ping/echo
  100/100 evidence in the [HIL guide](./validation/rzv2h-ipc-hil-test-guide.md). That
  sample result does not qualify the PX4 uORB bridge or CM33 exchange.
- The [CR8-1 PX4IO relay](../../boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1/px4io_cr8.cpp)
  responds on `/dev/ipcc1` to the CR8-0 uORB bridge and relays actuator
  commands to CM33 on `/dev/ipcc3` when that link opens (CM33 is optional).
  At 10 Hz it reports a heartbeat (`source_core=1`, loop count) and a fault
  status to CR8-0. The fault status carries `FAULT_FLAG_CR8_TIMEOUT` while
  no fresh FMU command exists, plus CM33 flags only while CM33 reported
  them within 500 ms. The CR8-0 bridge accepts heartbeats from CR8-1 only
  and declares the IO core lost after 500 ms without one.
- Board evidence (2026-10-13, CR8-0 NuttX `ipcc-raw-cr8_0` as initiator,
  CR8-1 PX4 IO image):
  - `px4io_cr8` autostarts and opens `/dev/ipcc3`;
  - after `ipctest --recover -d /dev/ipcc1` from CR8-0, a quarantined CR8-1
    adopts the new epoch through its plain `read()`;
  - `hexdump /dev/ipcc1` on CR8-0 captures 20 consecutive frames: heartbeat
    and fault status alternate at about 100 ms, sequences 439–448, every
    CRC is valid, padding is zero, and fault flags are `0x4` (no FMU
    commands).

  This is not PX4-bridge evidence: no CR8-0 PX4 profile enables the bridge
  (`CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE`).
- Known limits for the dual-CR8 milestone:
  - The relay's report writes are stop-and-wait in its control loop.
    Unpaced, the loop measured about 250 Hz; a slow reader cut it to about
    93 Hz.
  - The CR8-0 bridge is the `/dev/ipcc1` initiator and has no `RECOVER`
    path, so one acknowledgment timeout ends the link until reboot.
- [CM33 PX4IO sources](../../boards/renesas/rdk-rzv2h-io-cm33/px4io_m33/px4io_m33.cpp)
  apply the peer output rule below to an output state that only feeds
  feedback and fault status. CM33 will not drive PWM. It is low priority and
  may be dropped if no customer requires it. The system specification gives
  physical output authority to CR8-1. Delivery order is the single-core
  CR8-0 drone demo first, then dual CR8.
- PX4 bridge CRC rejection, sequence-gap handling, timeout/reset recovery and
  cache coherency under load require their own exact-image evidence.

These are profile-selection and physical-qualification boundaries. They do not
block standalone CR8 software work. Enable a multi-core flight profile only
after the peer ownership, MPU/cache policy, safety behavior, and target
evidence below are recorded for that profile.

### Current application and CA55 integration gaps

The CR8-0 bridge derives `armed` and `safety_off` from uORB arming and safety
state. Like PX4's `px4io` driver, it treats mixer output as authoritative: the
mixer has already chosen the armed, disarmed or failsafe value for each
channel. The bridge forwards the first eight channels, keeps `0` as output-off,
maps non-finite values to `0`, and bounds every other value to the PX4IO pulse
range `PWM_LOWEST_MIN`..`PWM_HIGHEST_MAX` (90–2500 µs). Configured PWM limits
(800–2200 µs) pass unchanged, and one channel never invalidates the frame. Only
a count above the uORB capacity clears the outputs and disarms. `armed` is set
during flight termination (`force_failsafe`) so the peer can apply failsafe
values such as a parachute; otherwise it requires vehicle arming and
`safety_off`. Lockdown and manual lockdown always clear it, matching PX4IO
precedence. The peer rule: each received channel is driven exactly as commanded while
frames stay fresh, so `armed=0` holds the mixer's disarmed values (`0` stays
no pulse) as PX4IO does; invalid frames are ignored, and when no valid frame
arrives for `FMU_LOSS_TIMEOUT_US` (100 ms) all outputs become `0`.

- CR8-1 accepts a frame only if `armed`/`safety_off` are 0 or 1 and every
  nonzero output lies in 90–2500 µs. It keeps the newest valid frame from a
  bounded drain (32 reads per cycle) and sends CM33 one command per loop
  cycle (2.5 ms sleep): the fresh frame, or all-zero and disarmed after the
  timeout.
- CM33 applies the same checks plus `output_mode == 0` (PWM only), holds the
  newest valid command and zeroes its outputs after 100 ms without one. It
  reports `FAULT_FLAG_CR8_TIMEOUT` while timed out and echoes the applied
  outputs in feedback.
- Freshness uses each core's local receive time because the cores do not
  share a timebase.
- The CR8-0 bridge sends a frame only on a new actuator-output, arming or
  safety publication, so if the mixer stops publishing, the peers time out
  and stop outputs.

Host checks cover the bridge, the relay, the CM33 rule, the CR8-1 transport and
every sender's one-entry write. The CR8-1 heartbeat reports zero CPU load
without sampling utilization.
CM33 drives no physical PWM yet. Real output ownership and peer-loss safety
verification on target remain required before flight use.

The CA55 path still requires agreement with the Linux remoteproc device tree
on resource-table and vring addresses. Software cache cleaning remains
necessary until a non-cacheable MPU mapping is verified. Interrupt delivery
uses `RPTUN_NOTIFY_ALL`; the shared notifyid slot is currently not consumed.
Per-vqid decoding requires a matching CA55 doorbell contract. The active
board route returns an ordinary RPTUN resource table while publishing a
different table in the CA55-visible `.resource_table` section. Their entry
counts, configuration lengths and vring notify IDs differ. The local callback table and CA55-visible section serve distinct consumers;
different entry counts alone do not prove a conflict. CA55 interoperability
still requires peer agreement on the shared-memory and vring contract. The local IRQ
fallback is retained for configurations lacking the canonical IRQ macro.
Moving raw links into the secure MHU window requires explicit domain
configuration and qualification.

## 6. Required Completion Evidence

Before promoting a selected IPC profile from source/build evidence to usable
on-target behavior:

1. boot exact recorded CR8-0, CR8-1, and CM33 artifacts from a cold reset;
2. prove each link independently, including loopback and both directions;
3. inject bad magic/version/CRC and sequence gaps;
4. exercise full/empty rings, TX ACK timeout, peer reset, and restart;
5. measure cache-coherent sustained traffic and worst-case latency;
6. verify actuator outputs fail safe during peer loss;
7. record firmware hashes, commands, counters, and target transcript.

## Related Docs

- [NuttX port status](./port-status-nuttx.md)
- [Multicore memory map](./multicore-memory-map.md)
- [Validation checklist](./validation/validation-checklist.md)
- [Porting playbook](./porting-playbook.md)
