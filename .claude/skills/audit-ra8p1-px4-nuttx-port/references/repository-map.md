# Repository map

## Source roles

| Role | Primary paths |
|---|---|
| RA8P1 device headers (CM85 core0, CM33 core1) | `refs/ra8p1/R7KA8P1KF_core0.h`, `refs/ra8p1/R7KA8P1KF_core1.h` |
| FSP single-core examples (EK-RA8P1) | `refs/ra8p1/ek_ra8p1/<example>/<example>_ek_ra8p1_ep/e2studio/` |
| FSP dual-core examples | `refs/ra8p1/evk_ra8p1_dual_core/RA8P1_DSP_example{,_cpu0,_cpu1}/` |
| FSP driver behavior | `<sample>/ra/fsp/src/r_<module>/`, `<sample>/ra/fsp/src/bsp/mcu/{all,ra8p1}/` |
| FSP instances/pins/vectors/clocks | `<sample>/ra_gen/{pin_data.c,vector_data.c,hal_data.c,bsp_clock_cfg.h}`, `<sample>/configuration.xml` |
| NuttX arch selection | `platforms/nuttx/NuttX/nuttx/arch/arm/Kconfig` (`ARCH_CHIP_RA8`), `arch/arm/src/ra8/{Kconfig,Make.defs,CMakeLists.txt,chip.h}` |
| NuttX lower-half | `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_*.c/h`, `ra8_usbdev.h` |
| NuttX register headers | `arch/arm/src/ra8/hardware/ra_{memorymap,hardware,clock,pinmap}.h`, `hardware/ra8p1/*.h`, `hardware/ra8p1/ra_clock.c` |
| NuttX IRQ numbers | `platforms/nuttx/NuttX/nuttx/arch/arm/include/ra8/{chip.h,irq.h,ra8p1_irq.h}` |
| NuttX upper-half drivers | `platforms/nuttx/NuttX/nuttx/drivers/`, `platforms/nuttx/NuttX/nuttx/include/nuttx/` |
| NuttX board glue/examples | `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/{configs,include,scripts,src}/` |
| NuttX apps | `platforms/nuttx/NuttX/apps/` (no RA8P1-specific example or test app exists) |
| PX4 HAL (linked) | `platforms/nuttx/src/px4/renesas/ra8/` (shared with `fpb-ra8e1`) |
| PX4 HAL (not linked) | `platforms/nuttx/src/px4/renesas/ra8p1/` (placeholder CMake, empty `include/`) |
| PX4 CM85 board | `boards/renesas/evk-ra8p1/` |
| PX4 CM33 IO board | `boards/renesas/evk-ra8p1-io-cm33/` (`px4io_ipc/`, `src/`, `nuttx-config/`) |
| PX4 consumers | `src/`, `platforms/common/`, `platforms/nuttx/src/` |
| History | `plans/ra8p1_*.md`, RA8 rows in `docs/renesas/port-status-*.md` |

## Source-authority gaps

- **Device headers.** `R7KA8P1KF_core0.h` (Cortex-M85 config) and
  `R7KA8P1KF_core1.h` (Cortex-M33 config) are checked in; the samples' CMSIS
  `Device/RENESAS` trees are empty. Peripheral bases match in both headers;
  core1 adds `R_CACHE_BASE` (`0x4001C000`) and the `_Pos/_Msk` bitfield macros
  core0 lacks for many registers. Core config differs: core0 has I/D cache and
  PMU, core1 has `__ICACHE_PRESENT 0`, `__DCACHE_PRESENT 0`, no PMU. Use the
  dual-core `_cpu1` sample for CM33 startup and IPC.
- **Feature and event tables.** Every sample carries a populated
  `e2studio/ra/fsp/src/bsp/mcu/ra8p1/bsp_feature.h` (`BSP_FEATURE_<IP>_*`
  channel masks and capabilities) and `bsp_elc.h` (`ELC_EVENT_*` numbers,
  `ELC_PERIPHERAL_*` ELSR indices). They are the primary source for per-unit
  features and event/ELSR numbers; see
  [hardware-fact-parity.md](hardware-fact-parity.md). Use the hardware manual
  only for facts these tables do not encode.
- **Sparse FSP modules.** Each sample carries only the modules it uses. Locate
  `r_<module>` with the collector; prefer the `e2studio/` copy and ignore
  `Debug/` build outputs. Modules with a single carrier sample (for example
  `r_canfd`, `r_i3c`, `r_rmac`, `r_mram`, `r_sdhi`, `r_spi_b`) have no second
  source to corroborate.
- **No FSP reference.** NuttX drivers such as `ra_ether` + PHY variants,
  `ra_ov5640`, `ra_sdram`, `ra_mbed_crypto` may have no matching `r_<module>`.
  Record the reference layer as unavailable instead of inventing parity.
- **Board identity.** FSP samples target `board.ra8p1ek` (EK-RA8P1). The PX4
  and NuttX `evk-ra8p1` boards are the same physical EK-RA8P1 (user-confirmed),
  so EK `pin_data.c` and `configuration.xml` are the pin authority. A
  disagreement with `evk-ra8p1/include/board.csv`, `board.h` or PX4
  `board_config.h` is a finding, not a corroboration gap.

## Build selection chain

| Layer | Fact to verify |
|---|---|
| Chip | `ARCH_CHIP_R7KA8P1KFLCAC` (boards) or `ARCH_CHIP_R7JA8P1JRLSAJ` selects `RA8P1_GROUP` |
| Core | choice `RA_CPU_CORE_CM85` (default, CPU0) or `RA_CPU_CORE_CM33` (CPU1) |
| Family | `RA8_CM85_FAMILY` -> `ARCH_CORTEXM85`; `RA8_CM33_FAMILY` -> `ARCH_CORTEXM33` |
| Derived | `RA_CPU_CORE` int (0/1) has no prompt; setting it in a defconfig does not choose the core |
| Headers | `hardware/ra_memorymap.h` switches `ra8e1/` vs `ra8p1/` on the group; `Make.defs` adds `hardware/ra8e1` to the include path unconditionally and `CMakeLists.txt` adds both `hardware/ra8e1` and `hardware/ra8p1`, so a bare include can resolve to the wrong group |
| Sources | `Make.defs` / `CMakeLists.txt` `RA8P1_GROUP` branches choose RA8P1-only files |
| PX4 HAL | `platforms/nuttx/cmake/px4_impl_os.cmake` maps the chip to `ra8`; include path from `cmake/px4_add_common_flags.cmake` |
| PX4 board | `*.px4board` (`CONFIG_BOARD_ARCHITECTURE`, modules, serial ports), `nuttx-config/nsh/defconfig`, `nuttx-config/scripts/script.ld` |

## Build entry points

- PX4: `./build.sh renesas_evk-ra8p1_{default,dshot,test}` and
  `./build.sh renesas_evk-ra8p1-io-cm33_default`; shared-code changes also need
  `renesas_fpb-ra8e1_{default,dshot,test}`.
- NuttX-only `evk-ra8p1` examples: `platforms/nuttx/NuttX/build_ra8p1.sh <config>`
  (`--list`, `--no-clean <config>`, exit 0 ok / 1 build failed / 2 bad usage).
  It distcleans, configures `evk-ra8p1:<config>`, records the stamp
  `.config-build-sh` and prints the effective core. distclean deletes
  `drivers/segger/RTT.zip`; offline hosts set `NUTTX_DOWNLOAD_CACHE` to a
  directory holding a cached `RTT.zip` (the Makefile verifies its SHA-256).
  `platforms/nuttx/NuttX/build.sh` stays fixed to `rdk-rzv2h`.

## Core boundaries

| Core | Architecture | Typical concern |
|---|---|---|
| CM85 (CPU0) | Cortex-M85, Armv8.1-M, Helium, DPFPU, I/D cache, ITCM/DTCM | PX4 flight core, HRT/PWM/sensors, cache maintenance for DMA |
| CM33 (CPU1) | Cortex-M33, Armv8-M, C-cache/S-cache, CTCM/STCM | IO core (`px4io_ipc`), separate vectors/linker/memory view |

Keep MRAM/SRAM/TCM/IPC addresses per core. The NuttX board scripts README
(`platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/scripts/README.md`)
describes MRAM `0x02000000`, SRAM `0x22000000`, IPC `0x220D0000`, OSPI `0x80000000` and
SDRAM `0x68000000`; verify any address against the actual linker scripts and
PX4 board scripts, which have diverged historically.

## Search strategy

1. Search exact public symbols and config keys across NuttX, PX4 and RA8E1.
2. Search register names and numeric IDs in implementation and device header.
3. Locate the FSP module carrier sample and read its `ra_gen/` instance data.
4. Search device path, bus number, channel and pin consumers across PX4.
5. Search historical plans for the symbol before accepting stale prose.
6. Prefer current source over plans and status tables.
