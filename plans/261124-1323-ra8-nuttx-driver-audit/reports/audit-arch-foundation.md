# ARCH audit: RA8P1 arch foundation (Phase 2)

Date: 2026-11-24. Static, read-only audit. No builds, configures or hardware access.

## 1. Scope, cores, baseline

- **Baseline:** PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- **Cores:** CM85 (CPU0, `RA_CPU_CORE=0`) and CM33 (CPU1, `RA_CPU_CORE_CM33=y`, `RA_CPU_CORE=1`).
  - CM33 configs: `ipc-cm33`, `wdt-cm33`, PX4 `evk-ra8p1-io-cm33`.
- **Path prefixes:**
  - `A` = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`
  - `E` = `.../boards/arm/ra8/evk-ra8p1`
  - `F` = `.../boards/arm/ra8/fpb-ra8e1`
  - `R` = `refs/ra8p1`
- **Topics covered:**
  - Kconfig core choice
  - Make.defs vs CMakeLists parity, include paths
  - Clocks and MSTP
  - CM85 and CM33 startup
  - IRQ/ELC table
  - GPIO/PFS
  - Tick
  - Linker layout
  - Board bring-up glue (buttons, LEDs, console pins)
- **Out of scope:** SCI10/SCI11 ELC events.
- **Build evidence:** only `adc-b` and `adc-b-hwtrigger` (CM85) were built (`reports/artifacts/nuttx/*.config|*.nm`). Every other config's ELF layer is "not built (user declined builds)".

## 2. Trace matrices

### 2a. CM85 startup (`A/ra_start.c` `__start` → `main()` → `nx_start`)

| # | Layer | NuttX anchor | Status | FSP reference |
|---|---|---|---|---|
| 1 | Reset entry | `A/ra_start.c:880-891` `__start` → arch `main()` `:802` | OK (unusual naming, see ARCH-19) | `R/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu0/ra/fsp/src/bsp/cmsis/Device/RENESAS/Source/startup.c` `Reset_Handler` → `SystemInit` |
| 2 | CCR (I-cache, BP, LOB), M85 D-cache errata / MSCR.FORCEWT | Not done. `RA_CCR_CACHE_ENABLE` defined but unused (`A/ra_start.c:85`) | DRIFT (ARCH-08) | `.../cpu0/.../system.c:171-205` |
| 3 | FPU (CPACR) | `arm_fpuconfig()` at `A/ra_start.c:827`, after mem init and `ra_clock` | LATENT (ARCH-07) | `system.c:212` (first, before any C) |
| 4 | Vector table | `ra_cortex_m85_init` (`A/ra_start.c:765-799`): `NVIC_VECTAB=_vectors` or ramvec | OK | `system.c` VTOR |
| 5 | .bss/.data/ramfunc | `ra_mem_init_nuttx()` `A/ra_start.c:820` | OK | `system.c` `bsp_init_uninitialized_vars`/copy |
| 6 | Clock tree | `ra_clock()` `A/ra_start.c:824` → `A/hardware/ra8p1/ra_clock.c:553-641` | OK order. Values drift (ARCH-10), no warm-restart guard (ARCH-11) | `.../cpu0/ra/fsp/src/bsp/mcu/all/bsp_clocks.c:2436-2500` |
| 7 | Option bytes / OFS | Gated by `CONFIG_RA_CPU_CORE == 0` | OK | `bsp_rom_registers.c` |
| 8 | Caches | `up_enable_icache/dcache` | OK | `system.c:171` |
| 9 | PFS security (PMSAR, PSCU) | `ra_gpio_security_init()` `A/ra_start.c:839` | OK on CM85 | `system.c:384-394` |
| 10 | Early serial | `ra_earlyserialinit` | OK for SCI0. SCI4 path does not compile (ARCH-05) | n/a |
| 11 | Board init | `ra_board_initialize` → `E/src/ra8p1_bringup.c:186` `board_button_initialize` | DEFECT on buttons (ARCH-01) | `R/ek_ra8p1/_quickstart/.../ra_gen/pin_data.c:11-15` |
| 12 | SysTick | `A/ra_timerisr.c:48-49` `RA_CPUCLK_FREQUENCY/CLK_TCK` | OK on CM85 (CPUCLK = 1 GHz, reload 10M < 2^24) | FSP RTOS port uses `SystemCoreClock` |
| 13 | Linker | `E/scripts/evk-ra8p1_non_ospi.ld:64-79` (MRAM 0x02000000, SRAM 0x22000000 1664K) | OK for CPU0 | `R/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu0/Debug/*.rpd` `FLASH_CPU0_S_START=0x2000000`, `RAM_CPU0_S_START=0x22000000` |
| 14 | ELF | adc-b, adc-b-hwtrigger `.nm` (E2) | Built | n/a |

### 2b. CM33 startup (same `A/ra_start.c` path, `RA_CPU_CORE=1`)

| # | Layer | NuttX anchor | Status | FSP reference (CPU1) |
|---|---|---|---|---|
| 1 | Reset entry | Same `__start`/`main` | OK | `.../RA8P1_DSP_example_cpu1/.../startup.c` |
| 2 | SKIP_INIT model | No equivalent. Full CPU0 init path runs | DEFECT (ARCH-02) | `R/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu1/ra_cfg/fsp_cfg/bsp/bsp_mcu_family_cfg.h:18` `BSP_CFG_SKIP_INIT (1)` |
| 3 | Clock tree | `ra_clock()` unconditional (`A/ra_start.c:824`, `A/hardware/ra8p1/ra_clock.c:635-641`). Rewrites HOCOCR, PLLCCR/PLL2CCR, SCKDIVCR/2, SCKSCR, MRAM wait/PFB | DEFECT (ARCH-02) | `.../cpu1/.../system.c:276-279`: only `bsp_clock_freq_var_init()` |
| 4 | PFS security | `ra_gpio_security_init()` runs again | DRIFT (ARCH-09) | `system.c:374,384` gated `!BSP_CFG_SKIP_INIT` |
| 5 | FPU | Late, as on CM85 | LATENT (ARCH-07) | `system.c:212` |
| 6 | Caches | I/D cache off (ipc-cm33 drops `ARMV8M_*CACHE`) | OK (CM33 has no L1 D-cache) | `system.c` C-Cache enable only |
| 7 | SysTick | `RA_CPUCLK_FREQUENCY` = CPUCLK (CM85 clock, 1 GHz) | DEFECT (ARCH-04) | `.../cpu1/ra/fsp/src/bsp/mcu/all/bsp_clocks.c:999-1000` uses `SCKDIVCR2.CPUCK1` |
| 8 | Linker (NuttX configs) | `E/scripts/Make.defs:34-40` picks `evk-ra8p1_non_ospi.ld` for every core. Per-core switch commented out (`:26-32`) | DEFECT (ARCH-03) | CPU1 `.rpd`: `FLASH_CPU1_S_START=0x2080000`, `RAM_CPU1_S_START=0x220ea000` |
| 9 | Linker (PX4 io-cm33) | `boards/renesas/evk-ra8p1-io-cm33/nuttx-config/scripts/script.ld:29-43` (MRAM 0x020E6000, SRAM 0x22198000) | Inside CPU1 window; TCM aliasing not verified | same |
| 10 | IELSR | Dynamic from slot 0 (`A/ra_icu.c`) | OK (banked per core) | CPU0 and CPU1 `vector_data.c` both use slot 0 |
| 11 | MSTP DMAC bit | `A/ra_mstp.c:112-117`, `A/ra_mstp.h:42-45` (A23 for CPU1) | OK | n/a |
| 12 | ELF | not built (user declined builds) | E0/E1 | n/a |

## 3. Findings by severity

### ARCH-01: High. IRQ pinsets drive the pin as output; `ra_gpiosetevent` clears PCR instead of PDR

- **Confidence:** high. **Core:** both.
- **Failure sequence:**
  1. `board_button_initialize` calls `ra_gpioconfig(GPIO_SW1)` (`E/src/ra8p1_buttons.c:139`).
  2. `GPIO_SW1` = `GPIO_IRQ13_P009_DS` = `PORT0|PIN9|IRQ13|R_PFS_PCR|R_PFS_ISEL` (`A/hardware/ra8p1/ra_pinmap.h:1572`, `IRQ13`=13 at `:80`).
  3. `ra_gpio_get_pfs_config` copies `cfg & 0xFFFF` directly into PFS (`A/ra_gpio.c:249-251`). 13 = 0b1101, so it sets PODR=1 (bit 0), PDR=1 (bit 2) and reserved bit 3 (`A/hardware/ra8p1/ra_pfs.h:268,272`).
  4. P009 becomes an output driven high.
  5. `ra_gpiosetevent` then runs `pfs_value &= ~(1 << R_PFS_PDR)` (`A/ra_gpio.c:803`). `R_PFS_PDR` is already a mask `(1<<2)`, so this clears bit 4 (PCR, pull-up) instead of PDR.
  6. Result: the pin stays output-high with ISEL=1. Pressing SW1 shorts a driven-high pin to GND.
- **Other affected pins:**
  - SW2 IRQ12: PDR=1, output low.
  - IRQ16/IRQ22 (`0x20|n`) set bit 5 (reserved).
  - IRQ14/15 set PDR and PODR.
  - Board aliases: `E/include/board.h:365-378`.
- **Reference:** `R/ek_ra8p1/_quickstart/quickstart_ek_ra8p1_ep/e2studio/ra_gen/pin_data.c:11-15` configures P008/P009 as `IOPORT_CFG_IRQ_ENABLE | IOPORT_CFG_PORT_DIRECTION_INPUT`.
- **Affected configs:**
  - RA8P1 `nsh-leds` (`CONFIG_ARCH_BUTTONS=y`), and `wdg_test` (`E/src/ra8p1_wdg_test.c:353`).
  - **RA8E1 blast radius:** same shared `ra_gpio.c` and the same `GPIO_SW1 = GPIO_IRQ13_P009_DS` (`F/include/board.h:79`, `F/src/ra8e1_buttons.c:137-143`). Affects `nsh`, `nsh-leds`, `nsh-rust`, `spi-masterslave`, `i2c-acc`, `i2c-gy912`, `spi-gy912`, `sbus`.
- **Remediation:**
  1. Mask the IRQ-number field out before the copy: `pfs_value |= (cfg & 0xFFFF & ~GPIO_IRQ_MASK);`. The IRQ number has no PFS meaning.
  2. Fix line 803 to `pfs_value &= ~R_PFS_PDR;`.
- **Classification:** pre-existing.
- **Evidence:** E1. A bench may still "see" button edges, because a weak output gets overdriven. A board transcript of PFS for P009 is needed to close this.

### ARCH-02: High. CM33 re-runs the full CPU0 clock initialisation

- **Confidence:** high (source). **Core:** CM33.
- **Failure sequence:**
  1. The CM85 boots, sets PLLs and dividers, then releases the CM33.
  2. The CM33 runs the same `main()` and calls `ra_clock()` → `ra_clock_init()` (`A/ra_start.c:824`, `A/hardware/ra8p1/ra_clock.c:553-641`).
  3. The CM33 then:
     - unlocks PRCR
     - writes HOCOCR=0 and MOSCCR
     - rewrites PLL2CCR/PLLCCR while the PLLs are running
     - writes startup SCKDIVCR/SCKDIVCR2 and SCKSCR
     - runs `up_udelay(150)`
     - rewrites MRAM PFB and wait states
  4. This happens while the CM85 executes from MRAM and peripherals are clocked.
  5. Possible outcomes: a transient clock glitch, a CM85 MRAM fetch at the wrong wait state, and PLL CCR writes while PLLCR=0, which the HW manual forbids (FSP guards this with `if (R_SYSTEM->PLLCR)`).
  6. A CM85 Kconfig divider change also gets overwritten by the CM33's defaults if the two images differ.
- **Reference:**
  - `R/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu1/ra_cfg/fsp_cfg/bsp/bsp_mcu_family_cfg.h:18` `BSP_CFG_SKIP_INIT (1)`.
  - `.../cpu1/ra/fsp/src/bsp/cmsis/Device/RENESAS/Source/system.c:239,276-279` call only `bsp_clock_freq_var_init()`; `bsp_clock_init` (`:295`) is skipped.
- **Affected configs:** `ipc-cm33`, `wdt-cm33`, PX4 `evk-ra8p1-io-cm33`. **RA8E1 blast radius:** none (single core; gate is `RA_CPU_CORE_CM33`).
- **Remediation:** under `CONFIG_RA_CPU_CORE_CM33`, skip `ra_clock_init()` and only run `ra_update_clock_config()`, which reads back the live registers. Optionally assert that `SCKSCR` already selects the PLL.
- **Classification:** pre-existing.

### ARCH-03: High. NuttX CM33 configs link with the CPU0 memory layout

- **Confidence:** high (source), medium (runtime impact depends on the load method). **Core:** CM33.
- **Failure sequence:**
  1. `E/scripts/Make.defs:34-40` always selects `evk-ra8p1.ld` or `evk-ra8p1_non_ospi.ld`. The per-core switch to `cm33/cm33_user_defs.ld` is commented out (`:26-32`).
  2. `ipc-cm33` and `wdt-cm33` set no linker override, so they link the CM33 image at:
     - MRAM 0x02000000
     - SRAM 0x22000000 (1664K)
     - ITCM 0x0 / DTCM 0x20000000

     These are the same addresses as the CM85 image (`E/scripts/evk-ra8p1_non_ospi.ld:64-71`).
  3. Flashing `ipc-cm33` overwrites the CM85 image and its option bytes. RAM-loading it overlaps CM85 .data/.bss/heap.
  4. The `ipc-cm85` + `ipc-cm33` pair therefore cannot coexist as linked.
- **Reference:** CPU1 `R/evk_ra8p1_dual_core/RA8P1_DSP_example_cpu1/Debug/RA8P1_DSP_example_cpu1.rpd`: `FLASH_CPU1_S_START=0x2080000`, `RAM_CPU1_S_START=0x220ea000`. CPU0 uses 0x2000000/0x22000000.
- **Affected configs:** `ipc-cm33`, `wdt-cm33`. PX4 io-cm33 uses its own `script.ld` (CPU1 window), so it is not affected. **RA8E1 blast radius:** none (board script).
- **Remediation:** restore the per-core LDSCRIPT selection in `E/scripts/Make.defs` (and the CMake equivalent) for `CONFIG_RA_CPU_CORE_CM33`, with a CPU1 memory map matching the FSP split. Omit OFS sections on CPU1.
- **Classification:** pre-existing / drift. **Evidence:** E1 (no ELF built).

### ARCH-04: High. CM33 SysTick reload uses the CM85 CPU clock

- **Confidence:** high. **Core:** CM33.
- **Failure sequence:**
  1. `SYSTICK_CLOCK = RA_CPUCLK_FREQUENCY` (`A/ra_timerisr.c:48`), which is `RA_SYSTEM_CLOCK_FREQUENCY / CPUCLK_DIV` (`A/hardware/ra8p1/ra_clock.h:845`) = 1 GHz.
  2. The CM33 runs on CPUCLK1 = /4 = 250 MHz (`A/hardware/ra8p1/ra_clock.h:922-923`; quickstart `bsp_clock_cfg.h:30`).
  3. With CLKSOURCE=processor clock, reload = 10,000,000 cycles at 250 MHz, so each tick is 40 ms instead of 10 ms.
  4. All CM33 timeouts, `usleep` and watchdog kick periods run 4x slow. Exception: `up_udelay`, which is loop calibrated.
- **Reference:** `.../cpu1/ra/fsp/src/bsp/mcu/all/bsp_clocks.c:999-1000` derives `SystemCoreClock` from `SCKDIVCR2.CPUCK1` when `BSP_CFG_CPU_CORE == 1`.
- **Affected configs:** `ipc-cm33`, `wdt-cm33` (watchdog refresh timing), PX4 io-cm33 (NuttX scheduler; PX4 HRT uses GPT, phase 11). **RA8E1 blast radius:** none (no CPUCLK1).
- **Remediation:** under `CONFIG_RA_CPU_CORE_CM33`, define `SYSTICK_CLOCK` from `CONFIG_RA_CPUCLK1_DIV`, or read SCKDIVCR2.CPUCK1 at runtime.
- **Classification:** pre-existing.

### ARCH-05: Medium. SCI4 early console pin setup does not compile

- **Confidence:** high. **Core:** both.
- **Failure:** `A/ra_start.c:465-466` reads `ra_gpioconfig(GPIO_SCI4_RX); */` and `ra_gpioconfig(GPIO_SCI4_TX); */`. The stray `*/` is a syntax error whenever `CONFIG_SCI4_SERIAL_CONSOLE` is set together with `USE_EARLYSERIALINIT` (`common/arm_internal.h:58`).
- **Reference:** absent (NuttX-only code).
- **Affected configs:** none today (every RA8P1 and RA8E1 defconfig uses SCI0 or an RTT console). Latent for any SCI4 console config. **RA8E1 blast radius:** same file, also latent.
- **Remediation:** remove the two stray `*/`.
- **Classification:** pre-existing (latent build break).

### ARCH-06: Medium. The peripheral clock getter decodes `xxCKDIVCR` with the system-divider encoding

- **Confidence:** high. **Core:** both.
- **Failure sequence:**
  1. `ra_get_peripheral_clock` (`A/hardware/ra8p1/ra_clock.c:804-946`) decodes SCI/SPI/CANFD/GPT/ADC/OCTA/LCD/I3C/USB/ESW dividers with `RA_DIV_TO_DIVISOR` (`A/hardware/ra8p1/ra_clock.h:837-841`). That macro implements SCKDIVCR (0=/1, 1=/2, 2=/4, 3=/8, 8=/3, 9=/6).
  2. The peripheral registers use a different encoding: 0=/1, 1=/2, 2=/4, 3=/6, 4=/8, 5=/3, 6=/5, 7=/10, 8=/16 (`A/hardware/ra8p1/ra_clock.h:145-154`).
  3. Kconfig allows `RA_SCICLK_DIV` 0..8 (`A/Kconfig:1705-1714`).
  4. Example: SCICLK_DIV=6 (FSP quickstart /5) decodes as /64, so the SCI baud is computed from 7.5 MHz instead of 96 MHz and BRR is wrong by 12.8x. Values 0-2 coincide, so the default (2) is unaffected.
- **Callers:** `ra_serial.c:1369`, `ra_sci_i2c.c:385`, `ra_sci_spi.c:612,621,1562`, `ra_spi.c:1639`, `ra_ospi_b.c:1104`.
- **Reference:** `.../cpu0/ra/fsp/src/bsp/mcu/all/bsp_clocks.h:247-256` (peripheral encoding).
- **Affected configs:** any RA8P1 config with a peripheral divider of 3 or more. None in tree (adc-b has `SCICLK_DIV=2`). **RA8E1 blast radius:** none. The RA8E1 getter (`A/hardware/ra8e1/ra_clock.c:621-660`) does not decode the peripheral dividers.
- **Remediation:** add a peripheral-divider decode table (`{1,2,4,6,8,3,5,10,16,32}`) and use it for every `xxCKDIVCR` read.
- **Classification:** pre-existing (latent).

### ARCH-07: Medium. FPU enabled only after C initialisation

- **Confidence:** medium. **Core:** both.
- **Failure:** `arm_fpuconfig()` runs at `A/ra_start.c:827`, after `ra_mem_init_nuttx()` and `ra_clock()`, which are compiled hard-float with `-mfpu`/MVE. If GCC emits VFP/MVE instructions in them (vectorised memset/copy loops, float delay math), the core takes a UsageFault (NOCP) before the vector table and handlers are usable.
- **Reference:** `.../cpu0/.../system.c:212` writes CPACR first.
- **Affected configs:** all hard-float configs. **RA8E1 blast radius:** same file, all RA8E1 configs. adc-b boots (E2), so current codegen does not trip it.
- **Remediation:** set CPACR CP10/CP11 at the top of `ra_cortex_m85_init`, before the memory init.
- **Classification:** pre-existing (latent).

### ARCH-08: Medium. CCR and M85 D-cache errata handling missing

- **Confidence:** medium. **Core:** CM85.
- **Gap:** NuttX never writes CCR=0x000E0201 (branch prediction, LOB), and skips the MSCR.FORCEWT errata workaround applied by FSP. `RA_CCR_CACHE_ENABLE` is defined but unused (`A/ra_start.c:85`).
- **Reference:** `.../cpu0/.../system.c:171-205`.
- **Affected configs:** all CM85 configs on RA8P1 and RA8E1 (shared file). Performance impact, plus write-back D-cache errata exposure on the affected M85 revisions.
- **Remediation:** port the FSP CCR write and the FORCEWT errata block into `ra_cortex_m85_init`, gated on Cortex-M85.
- **Classification:** drift.

### ARCH-09: Medium. CM33 re-initialises PFS security attribution

- **Confidence:** high (source), low (impact). **Core:** CM33.
- **Failure:** `ra_gpio_security_init()` (`A/ra_start.c:839`) rewrites every PMSAR register and PSCU PSARB-E after the CM85 has configured pins. FSP skips this on CPU1 (`system.c:374,384` gated `!BSP_CFG_SKIP_INIT`).
- **Affected configs:** CM33 only. **RA8E1 blast radius:** none.
- **Remediation:** gate the call on `!CONFIG_RA_CPU_CORE_CM33`.
- **Classification:** pre-existing.

### ARCH-10: Medium/Low. Clock values drift from the FSP quickstart

- **Confidence:** high. **Core:** CM85.
- **Drift** (adc-b `.config` vs `R/ek_ra8p1/_quickstart/.../ra_gen/bsp_clock_cfg.h`):

  | Clock | NuttX | FSP quickstart |
  |---|---|---|
  | PLL2P | /4 = 600 MHz | /2 = 1200 MHz (`:22-23`) |
  | PLL2Q | /3 = 800 MHz | /8 = 300 MHz (`:24-25`) |
  | NPUCLK | /1 | /2 (`:31`) |
  | SCICLK | PLL2R /4 = 120 MHz | PLL2R /5 = 96 MHz (`:48-49`) |

- **Impact:** with OCTACLK sourced from PLL2Q, 800 MHz is outside the FSP-validated OSPI range. NPUCLK /1 exceeds the FSP setting.
- **Affected configs:** all RA8P1 configs using the defaults. **RA8E1 blast radius:** none (`ra8p1` profile).
- **Remediation:** align the profile defaults with the quickstart, or document the max-frequency justification.
- **Classification:** drift.

### ARCH-11: Low. No warm-restart PLL guard

- **Gap:** `A/hardware/ra8p1/ra_clock.c:553-619` writes PLLCCR unconditionally. FSP checks `if (R_SYSTEM->PLLCR)` (PLL stopped) before reconfiguring. A software reset without a clock reset (debugger reload) writes CCR while the PLL is running.
- **Affected configs:** RA8P1. **RA8E1 blast radius:** check the `ra8e1` copy (not checked).
- **Classification:** drift.

### ARCH-12: Medium. CMake source list misses Make.defs sources

- **Confidence:** high.
- **Missing from `A/CMakeLists.txt`:**
  - `ra_cac`
  - `ra_ov5640`
  - `ra_sci_i2c`
  - `ra_ospi_b`
  - `ra_agt`
  - `ra_rtc`, `ra_rtc_lowerhalf`
  - `ra_ether_phy*`, `ra_ether_rmac`
  - `ra_usbdev`
  - `ra_idle`
- **Make.defs anchors:** `A/Make.defs:47,92,107,115,125,150-151,162-183,224,229`.
- **Failure:** a CMake build of `cac`, `sci-i2c`, `ospi`, `agt`, `rtc`, `ether`, `usb` or a custom-idle config fails to link with undefined symbols. Also, `ra_idle` absent with `ARCH_IDLE_CUSTOM` set gives no `up_idle`.
- **Affected configs:** CMake builds only (`build_ra8p1.sh` uses make). **RA8E1 blast radius:** same file.
- **Remediation:** mirror the conditional blocks in CMakeLists.
- **Classification:** drift.

### ARCH-13: Low. `ra_flash.c` referenced but absent

- **Anchors:** `A/Make.defs:140`, `A/CMakeLists.txt:113-114`, `config RA_FLASH` `A/Kconfig:2628`. The file does not exist.
- **Failure:** enabling `RA_FLASH` causes a build error. No defconfig enables it.
- **RA8E1 blast radius:** yes (the CMake comment says the driver is for RA8E1 FACI).
- **Remediation:** drop the references, or hide `RA_FLASH` until the driver lands.
- **Classification:** deferral / dead reference.

### ARCH-14: Low. Make.defs lacks the `hardware/ra8p1` include dir

- **Anchors:** `A/Make.defs:30-31` lists `hardware` and `hardware/ra8e1`. CMake also has `hardware/ra8p1` (`A/CMakeLists.txt:25-27`).
- **Shadowing check:** every bare `#include "x.h"` that names an `hardware/ra8e1` header resolves first to `A/` or `A/hardware/`, which dispatch per group. So there is no RA8E1-header shadowing on RA8P1 today.
- **Risk:** a future bare include of a family-only header would silently take the RA8E1 version on make builds.
- **RA8E1 blast radius:** none.
- **Remediation:** drop the family dir from EXTRAINCDIRS, or add the matching family dir per group.
- **Classification:** drift.

### ARCH-15: Low. Duplicate `ra_sci_spi.c`

- **Anchors:** `A/Make.defs:100-102` and `:108-110`, both under `CONFIG_RA_SCI_SPI`. The object is listed twice. This is harmless in practice (the archive member is replaced), but noisy.
- **RA8E1 blast radius:** yes (shared).
- **Remediation:** delete the second block.
- **Classification:** pre-existing.

### ARCH-16: Low. Kconfig hygiene

- `ARCH_CHIP_R7JA8P1JRLSAJ` sits outside the chip choice (`A/Kconfig:281`, after `endchoice` at `:279`). It can be enabled alongside another chip and selects `RA8P1_GROUP` + `RA_HAVE_SIP_FLASH`.
- `RA_CPU_CORE` defaults to 1 for RA8E1 (`A/Kconfig:428-432`). On RA8E1 this makes `ra_mstp.c:112-117` map `RA_MSTP_DMAC` to MSTPA23 instead of A22 (`A/hardware/ra8e1/ra_mstp.h:65`).
  - DMAC start still works, because A22 resets to running.
  - `ra_mstp_stop(RA_MSTP_DMAC)` (`ra_dmac.c:909`) sets the wrong bit.
  - **RA8E1 blast radius:** this item is RA8E1 only.
- `ARCH_HAVE_DATA_FLASH` defaults to n for RA8P1 (`:648-649`), but adc-b `.config` has it `=y`, through the CM33-family select (`:683-698`).
- The CM33 `CORESIGHT` help text says "ETM-M85".
- **Classification:** pre-existing.

### ARCH-17: Low. `g_ra_clock_config` declared twice

- **Anchors:** `A/hardware/ra8p1/ra_clock.c:202` and `:648`. Both are tentative `static` definitions, which is legal C (one object), but confusing.
- **Remediation:** delete one.

### ARCH-18: Low. `ELC_EVENT_CEU_CEUI` (0x397) missing; `RA_ELC_EVENT_MAX=0x396`

- **Anchors:** `A/hardware/ra8p1/ra8p1_irq.h` vs FSP `bsp_elc.h`. The other 499 events match.
- **Failure:** `A/ra_icu.c:610` rejects the CEU event. There is no CEU driver today.
- **RA8E1 blast radius:** none.

### ARCH-19: Low. Dead or malformed macros; arch-defined `main()`

- `RA_PRV_LOOPS_CALCULATE (cycles)` is malformed but unused (`A/ra_start.c:81`).
- `RA_CCR_CACHE_ENABLE` is unused (`:85`).
- The arch defines `int main(void)` (`:802`). This collides with any app or test linking its own `main` in a flat build.
- **RA8E1 blast radius:** yes (shared).

## 4. Items checked and correct

- **System clock register offsets:** VSCR, SCKDIVCR/2, SCKSCR, PLLCR, MOSCCR, HOCOCR, OSCSF, PLL2CR, PLLCCR/2, PLL2CCR/2, PRCR, MOMCR, MOSCWTCR.
- **Peripheral clock control register offsets:** SCI/SPI/ADC/GPT/OCTA/I3C CKCR and CKDIVCR.
- Both sets match `R7KA8P1KF_core0.h` R_SYSTEM (0x4001E000). Verified by `A/hardware/ra8p1/ra_sysc.h:44-311`.
- **Clock init order** (MOSC → PLL2 → PLL1 → VSCR → PLL on → MRAM wait → dividers → SCKSCR → 150 µs → MRCPFB → SRAM wait) matches FSP. Verified by `A/hardware/ra8p1/ra_clock.c:553-619` vs `bsp_clocks.c:2436-2500`. FSP does not wait for PLL2SF at startup either, so that draft finding was dropped.
- **IICCLK returns PCLKB.** The RA8P1 core0 header has no IICCKCR, so the IICCKCR init block is dead on RA8P1. This is consistent.
- **`ra_get_peripheral_clock` covers every `RA_PCLK_*` ID used by drivers:** ADC, CANFD, ESW, ESWPHY, ETHPHY, GPT, I3C, IIC, LCD, OCTA, PCLKA, PCLKB, SCI, SPI, USB60. Verified by `A/hardware/ra8p1/ra_clock.c:815-941`.
- **`A/ra_clock.c` (36 lines)** is a family dispatcher that includes `hardware/ra8e1|ra8p1/ra_clock.c` (`A/ra_clock.c:31-36`). It is a wrapper, not a stub.
- **PRCR masks** `{0x1,0x2,0x8,0x10}` match `ra_start.h:70-73`, and the code uses `R_SYSC_PRCR_S` (0x3FA).
- **Option bytes** are gated by `CONFIG_RA_CPU_CORE == 0`.
- **IRQ table:** `NR_IRQS = 16+96` and `IELSR_SIZE=96` (`arch/arm/include/ra8/irq.h:63-73`, `A/hardware/ra8p1/ra8p1_irq.h:136-139`) match `IELSR[96]` (`R7KA8P1KF_core0.h:9474`, `core1.h:9472`).
- **ICU:** `R_ICU_BASE` 0x40006000, IELS mask 0x3ff and IR bit 16 match (`A/hardware/ra8p1/ra_icu.h:35,60,497,500`).
- **ELC event values:** 499 of 499 FSP events present in the NuttX table have identical values (scripted diff, cpu0 = cpu1).
- **IELSR banking:** dynamic IELSR allocation from slot 0 on both cores is valid, because FSP cpu0 and cpu1 both use slot 0 (banked).
- **PFS write protection:**
  - `R_PFS_PWPR` = 0x40400D14 = PWPRS (`R7KA8P1KF_core0.h:12168`).
  - Unlock order B0WI=0 → PFSWE=1 and lock order PFSWE=0 → B0WI=1 (`A/ra_gpio.c:115-119,152-156`), ref-counted.
  - `ra_gpio_pfs_write` clears PMR before writing PSEL, as FSP does (`A/ra_gpio.c:195-218`).
- **Console and LED pins vs quickstart `pin_data.c`:**
  - SCI0 console P602/P603 (`E/include/board.h:99-100` vs `pin_data.c:167-171`).
  - LEDs P600/P303/PA07 (`board.h:351-353`). P303 and PA07 are output-low at `pin_data.c:89-90,321-322`. P600 is GPT1 in the quickstart (PWM-driven LED), so NuttX GPIO use is a board choice.
- **SysTick on CM85:** 1 GHz/100 = 10M, which fits in 24 bits (`A/ra_timerisr.c:55-57`). SysTick is distinct from PX4 HRT/PWM (GPT). Ownership goes to phase 11.
- **MSTP DMAC bit:** A22 on CPU0 and A23 on CPU1 (`A/ra_mstp.h:42-45`, `A/ra_mstp.c:112-117`).
- **PX4 io-cm33 linker** sits inside the FSP CPU1 window: MRAM 0x020E6000 ⊂ [0x02080000, 0x02100000), SRAM 0x22198000 ⊂ CPU1 RAM (`boards/renesas/evk-ra8p1-io-cm33/nuttx-config/scripts/script.ld:29-43`).

## 5. Rejected, unsupported paths and dead code

- **Rejected:** "PLL2SF not awaited" (FSP behaves the same).
- **Rejected:** "Make.defs include gap shadows RA8E1 headers" (no bare family-only include exists; downgraded to ARCH-14).
- **Dead code:**
  - IICCKCR init on RA8P1
  - `RA_CCR_CACHE_ENABLE`
  - `RA_PRV_LOOPS_CALCULATE`
  - the commented-out per-core LDSCRIPT switch (`E/scripts/Make.defs:26-32`)
  - `#CONFIG_ARCH_RAMVECTORS` in the canfd defconfig (commented out)
- **Unsupported:** `RA_FLASH` (no source); `CEU` ELC event; SCI4 console with early serial init (does not compile).

## 6. Evidence tier and verdict

| Area | Tier | Verdict |
|---|---|---|
| CM85 startup | E2 (adc-b boots, `.nm`) + E1 source | Acceptable. Fix ARCH-07/08 hygiene |
| CM33 startup | E1 (source only; not built) | **Not acceptable** (ARCH-02/03/04) |
| Clocks (CPU0) | E1 + E2 `.config` | Correct order. Latent decode bug (ARCH-06), drift (ARCH-10) |
| MSTP | E1 | OK on RA8P1. RA8E1 DMAC stop bit wrong (ARCH-16) |
| IRQ/ELC | E1 (scripted diff) | OK (CEU only gap) |
| GPIO/PFS | E1 | **Defect** for IRQ pinsets (ARCH-01). Basic PFS protocol OK |
| Tick | E1 | CM85 OK, CM33 wrong (ARCH-04) |
| Build glue | E1 | Make OK. CMake parity broken (ARCH-12) |
| Board bring-up | E1 | Console/LEDs OK. Buttons defective (ARCH-01) |

No driver is promoted. No on-target (E3) evidence was gathered.

## 7. Unresolved questions

1. Does the CM85 release the CM33 before or after its own `ra_clock()` completes? This bounds the ARCH-02 race window. Belongs to the IPC phase.
2. How do `ipc-cm33` and `wdt-cm33` get loaded in practice (debugger RAM load vs flash)? This sets the real impact of ARCH-03. Is the `cm33/cm33_user_defs.ld` path still intended?
3. PX4 io-cm33 links ITCM at 0x20100000 (CM85 view). Can the CM33 execute its own TCM at that alias, or must it use 0x0? Needs an HW manual check (phase 11/PX4 board).
4. `g_ram_vectors` placement vs the bss clear in `ra_mem_init_nuttx` if `ARCH_RAMVECTORS` is ever enabled. Not checked.
5. RA8E1 `ra_get_peripheral_clock` returns ICLK for SCICLK (`A/hardware/ra8e1/ra_clock.c:633`). Is that correct for RA8E1 SCI? Out of RA8P1 scope.
6. Does the RA8E1 `ra_clock.c` have the same warm-restart gap (ARCH-11)? Not checked.
7. Which M85 silicon revision is on the EK-RA8P1 (ARCH-08 errata applicability)?
