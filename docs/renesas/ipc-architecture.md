# RZ/V2H IPC Architecture

**Updated:** 2026-10-13
**Status:** source/build contract with bounded on-target evidence for the
dual-CR8 bridge (disarmed bench only); the standalone CR8-0 default keeps IPC
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
- A write arms its ACK (clears the MHU response, resets the ACK semaphore,
  masks the response IRQ) before it fills the slot, and rings the doorbell
  only after the tail is published. The peer may drain the ring from its
  own `poll()` or `read()` before the doorbell. Arming after publishing lost
  such early ACKs and timed the write out with the entry already consumed.
  `RECOVER` follows the same arm-before-publish order.
- `poll()` and `GET_STATS` take the receive lock, never the write lock that
  a writer holds across its ACK wait. A reader polling for data therefore
  never waits behind its own core's blocked writer.

## 4. PX4IO Message Protocol

The canonical application wire codec is defined in [`src/apps/protocol.hpp`](../../src/apps/protocol.hpp) and [`src/apps/protocol.cpp`](../../src/apps/protocol.cpp) as part of the shared `rzv2h_demo` library, mirrored by the board protocol headers ([CR8-0 protocol.h](../../boards/renesas/rdk-rzv2h/px4io_cr8_0/protocol.h), [CR8-1 protocol.h](../../boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1/protocol.h)). It owns message types, sizes, magic/version, sequence, CRC fields and little-endian serialization. Frames must
fit a raw entry. Messages are 28–52 bytes (v2) or exactly 44–64 bytes (v3), so every sender (CR8-0 bridge/producer,
CR8-1 relay/worker, CM33) zero-pads each frame to one 64-byte entry (`RZV_IPC_RAW_PAYLOAD_SIZE`). Receivers check
the CRC over the message length only. Its application CRC is distinct from the transport ABI;
OpenAMP/RPMsg does not acquire that framing merely by using the same MHU. Transport abstraction over `/dev/ipcc1` is wrapped by [`src/apps/raw-link.hpp`](../../src/apps/raw-link.hpp).

The CR8-0 uORB bridge:

- transmits actuator outputs, selected vehicle commands, vehicle status, and a
  10 Hz heartbeat on `/dev/ipcc1`. While disarmed it repeats the last
  actuator frame every 20 ms (`DISARMED_REFRESH_US`, 2/5 of the lease),
  because a sensorless or idle mixer can publish slower than the 50 ms
  lease;
- runs in the actuator-output priority band
  (`SCHED_PRIORITY_ACTUATOR_OUTPUTS`), so default-priority work such as an
  NSH command cannot preempt the lease refresh;
- publishes `px4io_status` for commander (see the I/O-core health section);
- accepts RC input, ESC status, battery status, and heartbeat frames;
- rejects bad magic, version, type, or CRC;
- counts per-topic sequence gaps;
- bounds receive draining to preserve the transmit/heartbeat schedule;
- as the `/dev/ipcc1` initiator, treats `ENOLINK`, `ETIMEDOUT` or `EPROTO`
  from a read or write as a quarantined link (`EAGAIN` is flow control). It
  then sends nothing, keeps ageing CR8-1 liveness, and retries `RECOVER` at
  most once per second. A successful `RECOVER` starts a new epoch, resets the
  RX sequence tracking and resumes transmission. Old commands are never
  replayed.

The bridge compiles only with the raw IPC initiator role
(`CONFIG_RZV_IPC_RAW`, `CONFIG_RZV_IPC_ROLE_INITIATOR`) and with
`CONFIG_RZV_IPC_RECOVERY_WAIT_MS` ≤ 100, so its `RECOVER` call stays bounded
on the flight core. These are `#error` guards in `uorb_bridge.cpp`.

## 5. Configuration and Availability

| Target/profile | IPC state | Evidence |
|---|---|---|
| PX4 default (`renesas_rdk-rzv2h_default`) | disabled | PX4/NuttX configuration |
| PX4 single-core CR8-0 profiles (`default`, `drone`, `simple`, `sih`, `dshot`) | PX4IO bridge off (`CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE` defaults to `n`; `drone`/`simple` set it explicitly) | host contract test over every `rdk-rzv2h/*.px4board` |
| PX4 dual-CR8 CR8-0 (`renesas_rdk-rzv2h_dualcr8`) | Exact-BOM sensor profile and coherent v3 `rzv2h_outputs` producer; no local motor outputs or legacy bridge; no qualified peer | [Candidate source/host/build procedure](validation/dualcr8-sensor-actuator-demo.md); earlier bridge captures remain historical |
| PX4 CR8-1 `pwm` | V3 `rzv2h_io` controller, independent output worker and reporter; hardware identity unconfigured, resources unclaimed | Candidate build/host evidence only; default retains its legacy relay |
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
  responds on `/dev/ipcc1` to the CR8-0 uORB bridge. Its threads:
  - The control loop waits on `poll()` for `/dev/ipcc1` data, bounded at
    2 ms, so CR8-0 writes are consumed and acknowledged promptly. It feeds
    each valid frame and CR8-0 heartbeat to the output lease described below.
  - An ESC worker, woken every 2.5 ms (400 Hz) by an HRT callout, sends the
    lease output to CM33 on `/dev/ipcc3` when that link opens (CM33 is
    optional). It reads a snapshot the control loop stamps; a snapshot
    older than the 50 ms lease is replaced by all-zero, disarmed outputs.
    The CM33 stop-and-wait write blocks only this thread.
  - A lower-priority reporter thread sends a heartbeat (`source_core=1`,
    loop count) and a fault status to CR8-0 at 10 Hz. It reads only values
    the control loop publishes (atomics), so a stop-and-wait report write
    never stalls the control loop. A stalled control loop shows as a frozen
    `loop_count`.

  The fault status carries `FAULT_FLAG_CR8_TIMEOUT` while no fresh FMU
  command exists, `FAULT_FLAG_FMU_HEARTBEAT` while no fresh CR8-0 heartbeat
  exists, the lease flags below, and CM33 flags only while CM33 reported
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
- Board evidence for the PX4 bridge (2026-10-13, `renesas_rdk-rzv2h_dualcr8`
  on CR8-0 with `renesas_rdk-rzv2h-io-cr8_1_default` on CR8-1, both loaded
  by `rzv2h-ipc-demo-load-both-auto.sh`; disarmed bench, no sensors, no
  motors driven):
  - the bridge starts from the drone hooks, acquires the CR8-1 heartbeat
    and sends actuator frames at about 50 Hz while disarmed; `px4io_status`
    reports `status_init_ok`, `status_fmu_ok` and `arming_io_arm_ok`;
  - CR8-1 timing from two GDB reads of its counters 18.4 s of CR8-1 ticks
    apart: the ESC worker runs at 404 Hz and the control loop at 370 Hz
    (the previous image held about 124 Hz);
  - after the ACK-ordering fix, a 5-minute run has no link drop after the
    boot-time start race;
  - `px4io_bridge stop` sets the `motors_escs` bit (256) in
    `health_report.health_error_flags` once the last `px4io_status` goes
    stale; `px4io_bridge start` reacquires the heartbeat and clears it.

  The armed and SafeFault paths are host-tested only: arming on the bench
  needs a force-arm decision this run did not take.
- Debug-probe effects on these numbers. J-Link reaches CR8 RTT only in stop
  mode: every RTT poll halts CR8-0 (about 25 % of wall time with the RTT
  bridge attached; the core tick loses that time, the GTM HRT does not).
  CR8-1 keeps running while CR8-0 is halted, so console traffic produces
  lease blips (`0x4`) and `ETIMEDOUT` link recoveries. On the same images,
  20 back-to-back `ps` runs gave 6 link recoveries and 115 lease blips with
  the RTT bridge attached and none with the probe detached. A GDB attach
  halts the attached core the same way. Measure link and lease behavior
  without a probe polling RTT.
- Known limits for the dual-CR8 milestone:
  - The CR8-0 bridge is one thread: while a write waits up to 100 ms for an
    ACK it does not read, and the TX ACK timeout exceeds the 50 ms lease.
  - CR8-0 and CR8-1 start independently; the first seconds after a
    simultaneous load show link recoveries until both sides are up.
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
arrives for `FMU_LOSS_TIMEOUT_US` (50 ms, the output lease) all outputs
become `0`. The 50 ms lease is the system-specification candidate. Its
end-to-end latency is still to be measured.

#### CR8-1 output lease

CR8-1 drives outputs through the output lease tracker (implemented in [`src/apps/actuator-lease.hpp`](../../src/apps/actuator-lease.hpp), [`src/apps/actuator-lease.cpp`](../../src/apps/actuator-lease.cpp), and legacy [output-lease.h](../../boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1/output-lease.h)),
which implements the software-specification state machine
(Unclaimed → InitializedSafe → Ready → Armed, any failure or timeout → Inhibited / SafeFault):

| State | Entered by | Outputs |
|---|---|---|
| Safe | boot; lease expiry or session change while not armed | all `0`, disarmed |
| Ready | a fresh disarmed command in the current link epoch with a fresh CR8-0 heartbeat | command forwarded, `armed=0` |
| Armed | a fresh armed command while Ready or Armed | command forwarded, armed |
| Fault | lease expiry, heartbeat loss or session change while Armed (latched) | all `0`, disarmed |

Safe is also entered from Ready on heartbeat loss.

- An armed command is refused (`FAULT_FLAG_ARM_REJECTED`) unless the current
  session saw a disarmed handshake first. Fault never goes straight to
  output: only a disarmed command in the current epoch leaves it, and
  arming again needs another command.
- The relay reads the link epoch (`RZV_IPC_RAWIOC_GET_STATS`) after every
  read. A new CR8-0 epoch (`FAULT_FLAG_PEER_SESSION`) ends the session
  before that read's command is used. If the epoch cannot be read, every
  command is refused.
- A command counts only while a CR8-0 heartbeat from the current session
  arrived within `HEARTBEAT_TIMEOUT_US` (500 ms). A command stream that
  outlives the bridge's own liveness signal therefore never drives outputs;
  commands without a fresh heartbeat are held safe and an armed one is
  reported as rejected. Heartbeat loss is reported as
  `FAULT_FLAG_FMU_HEARTBEAT` (`1 << 11`).
- Fault status adds `FAULT_FLAG_OUTPUT_SAFE_FAULT` with the latched reason
  (`FAULT_FLAG_CR8_TIMEOUT`, `FAULT_FLAG_FMU_HEARTBEAT` or
  `FAULT_FLAG_PEER_SESSION`) while in Fault.
- `GET_STATS` takes the driver's `rxlock`, not the write lock held across the
  ACK wait, so the epoch query never waits behind a blocked writer.

- CR8-1 accepts a frame only if `armed`/`safety_off` are 0 or 1 and every
  nonzero output lies in 90–2500 µs. It applies valid frames to the lease in
  order from a bounded drain (32 reads per cycle). The ESC worker sends CM33
  the lease output at 400 Hz: the fresh command in Ready or Armed, otherwise
  all-zero and disarmed.
- CM33 applies the same checks plus `output_mode == 0` (PWM only), holds the
  newest valid command and zeroes its outputs after 50 ms without one. It
  reports `FAULT_FLAG_CR8_TIMEOUT` while timed out and echoes the applied
  outputs in feedback.
- Freshness uses each core's local receive time because the cores do not
  share a timebase.
- The CR8-0 bridge sends a frame on a new actuator-output, arming or
  safety publication. While disarmed it also repeats the last frame every
  20 ms (`DISARMED_REFRESH_US`, 2/5 of the lease) so an idle disarmed mixer
  does not expire the lease. While armed it never repeats, so if the mixer
  stops publishing, the peers time out and stop outputs.

#### I/O-core health

The CR8-0 bridge publishes `px4io_status`, as PX4's `px4io` driver does, at
1 Hz and at once on any change:

| Field | Set when |
|---|---|
| `status_init_ok` | a CR8-1 heartbeat arrived within 500 ms |
| `status_fmu_ok` | the link is up, CR8-1 is alive, and neither `FAULT_FLAG_CR8_TIMEOUT` nor `FAULT_FLAG_FMU_HEARTBEAT` is reported |
| `status_failsafe` | CR8-1 reports a latched SafeFault (`FAULT_FLAG_OUTPUT_SAFE_FAULT`) |
| `status_outputs_armed` | CR8-1 is alive and reports the Armed state |
| `alarm_pwm_error` | CR8-1 reports `FAULT_FLAG_PWM_FAULT` |
| `arming_io_arm_ok` | `status_fmu_ok` and not `status_failsafe` |

The fault flags of a silent CR8-1 are not trusted. The commander check
[`px4ioCheck`](../../src/modules/commander/HealthAndArmingChecks/checks/px4ioCheck.cpp)
runs only once a `px4io_status` has been seen, so boards without an I/O
processor are never checked. It then reports one `motors_escs` health
failure for all modes, which blocks arming, in this order: no sample for
more than 2 s ("I/O processor not responding"), `status_failsafe`
("I/O processor in failsafe"), or not `status_fmu_ok` ("I/O processor not
receiving FMU outputs"). It keeps the last sample, so it still fails after
the bridge exits and the topic goes stale.

Host checks cover the bridge (including link recovery), the relay, the output
lease state machine, the CM33 rule, the CR8-1 transport and every sender's
one-entry write. The CR8-1 heartbeat reports zero CPU load
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

#### Open dual-CR8 decisions

These questions are open as of 2026-10-13 and need an owner decision; the
code keeps the behavior described above until then.

1. **Armed lease test on the board.** Lease expiry and SafeFault are covered
   by host tests only. An armed bench run (`commander arm -f`, props off,
   with approval) would prove them on target.
2. **TX ACK wait vs. lease.** The CR8-0 bridge is one thread, and a raw write
   waits up to `CONFIG_RZV_IPC_TX_TIMEOUT_MS` (100 ms in `dualcr8`) for the
   peer ACK, twice the 50 ms output lease. Options: split the send and
   receive paths, or lower the timeout for `dualcr8`.
3. **CR8-0 heartbeat freshness.** CR8-1 reuses `HEARTBEAT_TIMEOUT_US`
   (500 ms) for a 10 Hz CR8-0 heartbeat. A tighter value would detect a
   silent bridge sooner.
4. **CR8-1 thread priorities.** The ESC worker runs at
   `SCHED_PRIORITY_DEFAULT - 5` and the reporter at `- 10`, so reports to
   CR8-0 can lag by up to 100 ms. Confirm this is acceptable for the demo.
5. **`px4ioCheck` scope.** The check also runs on any board whose `px4io`
   driver publishes `px4io_status`. This fork does not target upstream, so it
   is kept as is unless that changes.

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
