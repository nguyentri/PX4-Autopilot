# RZ/V2H IPC Architecture

**Updated:** 2026-10-11
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
| CM33 | NuttX raw sample / PX4IO scaffold | optional safety or ESC peer | Secure SRAM image; secure-DDR shared rings |

See [multicore-memory-map.md](./multicore-memory-map.md) for the authoritative
boot, TCM, SRAM, DDR, and shared-memory map.

## 2. Transport Layers

Two different paths share the RZ/V2H MHU helpers:

1. CA55 ↔ CR8-0 uses the native rptun/OpenAMP/RPMsg implementation and
   registers `/dev/ipcc0`. This is a separate, optional later profile from the
   reference CA55 RPMsg/RPC/uXRCE application path.
2. Raw CR8/CM33 links use an MHU doorbell plus fixed DDR rings through the
   NuttX IPCC upper half.

`rzv_mhu_core.c` only provides register and IRQ helpers. It does not imply that
OpenAMP or a raw link is enabled.

The checked-in MHU aliases are:

| Access domain | MHU0 base |
|---|---:|
| non-secure | `0x10480000` |
| secure CR8 | `0x10480800` |
| secure CM33 | `0x10481000` |

The raw-link configuration currently selects the non-secure window. A move to
the secure CR8 alias is a physical target-qualification decision; it does not
change the native ABI or the current standalone memory map.

## 3. Raw MHU + Shared-Memory Links

`arch/arm/src/rzv/rzv_ipc_channels.h` is the single source of truth for these
allocations:

| Device | Link | TX/RX MHU0 NS channels | Shared memory |
|---|---|---|---:|
| `/dev/ipcc1` | CR8-0 ↔ CR8-1 | 4 / 9 | `0x43800000`, 64 KiB |
| `/dev/ipcc2` | CR8-0 ↔ CM33 | 10 / 15 | `0x43810000`, 32 KiB |
| `/dev/ipccLB` | CR8-0 loopback | 16 / 16 | `0x43818000`, 16 KiB |
| `/dev/ipcc3` | CR8-1 ↔ CM33 | 21 / 22 | `0x43820000`, 32 KiB |

All channels are checked against the RZ/V2H MHU-B-NS valid-channel mask.
Compile-time assertions also check ring sizing, channel separation, and the
`0x43800000`–`0x4383ffff` IPC carveout bounds.

Each raw ring half contains:

```text
offset 0   uint32_t head
offset 4   uint32_t tail
offset 8   uint32_t mask
offset 12  uint32_t flags (ABI version in bits 7:0)
offset 16  48-byte cache-line pad
offset 64  fixed-size entries
```

The ABI is little-endian. The producer cleans data before the MHU kick; the
consumer invalidates before reading and responds with the MHU ACK. Current raw
entries are 64 bytes.

## 4. PX4IO Message Protocol

The protocol source is
`boards/renesas/rdk-rzv2h/px4io_cr8_0/protocol.h`.

Every message starts with this packed 16-byte header:

| Field | Type | Current value or meaning |
|---|---|---|
| `magic` | `uint32_t` | `0x525a5632` (`RZV2`) |
| `version` | `uint8_t` | `0x02` |
| `msg_type` | `uint8_t` | heartbeat, actuator, status, RC, battery, or failsafe type |
| `sequence` | `uint16_t` | monotonic counter per message stream |
| `timestamp_us` | `uint32_t` | source HRT timestamp |
| `crc32` | `uint32_t` | IEEE CRC32 with this field zeroed during calculation |

This replaces the obsolete `0xaa`/CRC16 frame previously documented here.
Messages must fit one 64-byte raw-ring entry.

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

The raw drivers, shared-memory ABI, bridge, and example profiles are not the
default runtime path. In particular:

- The NuttX raw CR8-0/CR8-1 link has bounded `ipctest` recover/ping/echo
  100/100 evidence in the [HIL guide](./rzv2h-ipc-hil-test-guide.md). That
  sample result does not qualify the PX4 uORB bridge or CM33 exchange.
- The [CR8-1 PX4IO scaffold](../../boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1/px4io_cr8.cpp)
  sends placeholder commands on `/dev/ipcc3`; it is not the CR8-0 uORB
  bridge's `/dev/ipcc1` responder. That application integration remains open.
- [CM33 PX4IO sources](../../boards/renesas/rdk-rzv2h-io-cm33/px4io_m33/px4io_m33.cpp)
  and the NuttX raw sample exist in-tree; CM33 target boot/traffic and real
  actuator integration remain unproven.
- PX4 bridge CRC rejection, sequence-gap handling, timeout/reset recovery and
  cache coherency under load require their own exact-image evidence.

These are profile-selection and physical-qualification boundaries. They do not
block standalone CR8 software work. Enable a multi-core flight profile only
after the peer ownership, MPU/cache policy, safety behavior, and target
evidence below are recorded for that profile.

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
- [Validation checklist](./validation-checklist.md)
- [Porting playbook](./porting-playbook.md)
