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

## 4. PX4IO Message Protocol

The [PX4IO protocol](../../boards/renesas/rdk-rzv2h/px4io_cr8_0/protocol.h)
owns message types, sizes, magic/version, sequence and CRC fields. Frames must
fit a raw entry. Its application CRC is distinct from the transport ABI;
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

The raw drivers, shared-memory ABI, bridge, and example profiles are not the
default runtime path. In particular:

- The NuttX raw CR8-0/CR8-1 link has bounded `ipctest` recover/ping/echo
  100/100 evidence in the [HIL guide](./validation/rzv2h-ipc-hil-test-guide.md). That
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
- [Validation checklist](./validation/validation-checklist.md)
- [Porting playbook](./porting-playbook.md)
