# RDK-RZ/V2H System Architecture

**Date:** 2026-07-30
**Status:** Source-backed reference; CR8-0 active, multicore deferred

This document summarizes the checked-in RZ/V2H PX4/NuttX architecture. It does
not claim production stability, cold-boot validation, or enabled multicore IPC
in the default images.

## 1. Architecture Stack

```text
PX4 modules
  -> PX4 HAL / board startup
  -> NuttX RTOS
  -> RZ/V2H board and driver layer
  -> RZ/V2H hardware
```

The CR8-0 board path is the active PX4 target. CR8-1 and CM33 remain deferred
multicore work.

## 2. Core Roles

| Core | Current role | Evidence state |
|---|---|---|
| CR8-0 | Primary flight stack, board bring-up, diagnostics | Active target |
| CR8-1 | I/O co-processor / PX4IO-style expansion | Deferred |
| CM33 | Alternate I/O or safety companion | Deferred |

The old shorthand that implied CR8-1 at `0x40000000` and CM33 at `0x40100000`
has been removed. Exact aliases and boot views belong in
[multicore-memory-map.md](./renesas/multicore-memory-map.md).

## 3. Canonical Addressing

Use [multicore-memory-map.md](./renesas/multicore-memory-map.md) for the exact CR8-0,
CR8-1, and CM33 aliases. That document is the single source of truth for:

- CR8 private TCM views.
- DDR aliases per core.
- Shared DDR carveouts.
- CM33 secure / non-secure addressing.
- Loader and boot parameter placement.

This summary only keeps the high-level contract: shared-memory and boot-address
details are not duplicated here.

## 4. IPC and Multicore Contract

IPC is deferred. The default PX4 and SIH images keep it disabled.

The source tree contains MHU/IPCC helpers and raw-link scaffolding, but those
helpers are not evidence of an enabled runtime transport. The current protocol
contract is documented in [ipc-architecture.md](./renesas/ipc-architecture.md):

- PX4IO bridge framing uses a 16-byte header with CRC32.
- Sequence numbers and magic/version checks reject stale or corrupt frames.
- Shared-memory ring bounds are checked at build time.

The obsolete "active IPCC" and CRC16 framing notes were removed from this
summary.

## 5. PX4 Board Layout

```text
boards/renesas/rdk-rzv2h/
├── src/                     board startup, pinmux, HAL glue
├── nuttx-config/            board defconfigs for named profiles
├── px4io_cr8_0/             deferred PX4IO bridge sources
├── dshot.px4board           opt-in DShot build
└── core_only.px4board       deterministic CR8-0 diagnostic image
```

Build entry points remain the checked-in board targets such as
`renesas_rdk-rzv2h_default`, `renesas_rdk-rzv2h_sih`, and
`renesas_rdk-rzv2h_core_only`.

## 6. Build Flow

1. `./build.sh <target>` selects the board definition.
2. PX4 CMake resolves the Renesas board sources.
3. The board defconfig pulls in the NuttX driver and RTOS pieces.
4. The NuttX submodule supplies the architecture drivers under
   `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`.
5. The result is a target-specific ELF/PX4 artifact.

Build success is source/build evidence only. It does not imply a cold boot, a
flash recipe, or enabled multicore traffic.

## 7. Related Documentation

- [Hardware](./renesas/hardware.md)
- [NuttX Port Status](./renesas/port-status-nuttx.md)
- [PX4 HAL Port Status](./renesas/port-status-px4-hal.md)
- [IPC Architecture](./renesas/ipc-architecture.md)
- [Multicore Memory Map](./renesas/multicore-memory-map.md)

## 8. Notes

- CR8-0 is the only active PX4 flight path in the checked-in default images.
- No production-stable claim is made for the RZ/V2H port.
- Do not treat IPC helper symbols, `/dev/ipcc*` names, or linker carveouts as
  proof of an enabled runtime link.
- The authoritative cross-core address map lives in
  [multicore-memory-map.md](./renesas/multicore-memory-map.md).
- The current bridge protocol contract lives in
  [ipc-architecture.md](./renesas/ipc-architecture.md).
