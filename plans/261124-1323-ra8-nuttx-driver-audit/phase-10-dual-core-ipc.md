---
phase: 10
title: "Phase 10: Dual-core IPC and CM33 image"
status: pending
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 10: Dual-core IPC (CM85 + CM33, separate matrices)

## Scope
- Modules: `ra_ipc.c`, `ra_ipc_ipcc.c`, `hardware/ra8p1/ra_ipc.h`; the CM33 start path from phase 2
- Board glue: `ra8p1_ipc.c`, `ra8p1_ipc_test.c`, `ra8p1_boot.c` (CPU1 release), `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/scripts/{cm33,cm85,common}/`
- Configs: `ipc-cm85`, `ipc-cm33`, `wdt-cm33`; PX4 `evk-ra8p1-io-cm33/nuttx-config/nsh`
- FSP: `r_ipc` from `evk_ra8p1_dual_core/RA8P1_DSP_example_cpu0` and `_cpu1`, plus their linker and memory region files and CPU1 boot code

## Tasks & Steps
1. IPC hardware: the channel and semaphore registers, the IRQ per core, and the message/ack handshake vs `r_ipc`.
2. Shared memory: `BOARD_IPC_SHMEM_BASE/SIZE` (`_sipc`/`_eipc`) in every CM85 and CM33 linker script, both NuttX and PX4. The README says 0x220D0000 and earlier history disagreed. The scripts must assert that `.ipc_shmem` is empty.
3. Coherency: CM85 D-cache maintenance on the shared region, or an MPU non-cacheable attribute. On CM33 there is no L1; check that no `ARMV8M_*CACHE` is set and that the `SCACTL.ENS` report is not presented as proof.
4. `RA_IPC_IPCC` depends on a symbol that must exist, and its source must be in both Make.defs and CMake (the historical bug).
5. CPU1 boot: who releases CPU1, its vector table address, its secure state, and the boot order relative to the CM85 IPC init.
6. Resource ownership between the cores: pins, SCI, GPT, WDT, ICU slots, DMAC channels.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-dual-core-ipc.md`
