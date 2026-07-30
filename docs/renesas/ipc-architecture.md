# RZ/V2H IPC Architecture

**Updated:** 2026-07-30
**Status:** deferred multi-core milestone; source and build contracts exist, but
the default PX4 and SIH images keep IPC disabled.

This document describes the checked-in design. It is not a claim of
production readiness or end-to-end target validation.

## 1. Core Topology

| Core | Intended software | Role | Private DDR (CR8/CM33 view) |
|---|---|---|---|
| CR8-0 | NuttX/PX4 | Flight stack | `0x40800000`–`0x417fffff` |
| CR8-1 | NuttX/PX4IO | I/O relay | `0x41800000`–`0x427fffff` |
| CM33 | separate firmware | boot/safety or ESC peer | secure DDR view; firmware not in this repository |

See [multicore-memory-map.md](./multicore-memory-map.md) for the authoritative
boot, TCM, SRAM, DDR, and shared-memory map.

## 2. Transport Layers

Two different paths share the RZ/V2H MHU helpers:

1. CA55 ↔ CR8-0 uses rptun/OpenAMP/RPMsg and registers `/dev/ipcc0`.
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
the secure CR8 alias remains a target-validation decision.

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

- the CR8-1 `/dev/ipcc1` responder needed by the CR8-0 uORB bridge is not
  implemented;
- CM33 peer firmware is outside this repository;
- no current transcript proves bidirectional target traffic, CRC rejection,
  sequence-gap handling, timeout recovery, reset recovery, or cache
  coherency under load.

Therefore IPC remains a deferred final milestone. Do not enable it in a flight
image until both peer implementations, ownership, MPU/cache policy, safety
behavior, and target validation are complete.

## 6. Required Completion Evidence

Before promoting IPC from deferred to usable:

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
