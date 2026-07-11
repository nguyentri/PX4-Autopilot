# RDK-RZ/V2H Codebase Summary

**Date:** 2026-07-11  
**Status:** Foundational (Phase 1)

Directory-by-directory tour focused on RZ/V2H: what lives where, driver inventory, board configs, and reference sources.

---

## 1. NuttX RZ/V2H Driver Port

**Root:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`

### Architecture & Common Files

| File | Purpose |
|------|---------|
| `rzv_start.c`, `rzv_start_cm33.c` | Reset vector, CPU init, MMU/MPU setup |
| `rzv_idle.c` | Idle task (power management hook) |
| `rzv_irq.c`, `rzv_irq_cm33.c` | Interrupt vector table, handler dispatch |
| `rzv_lowputc.c` | Early serial output (bootstrap debugging) |
| `rzv_clock.c` | CPG (Clock Pulse Generator) init, divider tables |
| `rzv_memmng.c` | Memory management stubs |
| `rzv_mpu_regions.c` | MPU region setup (cache control, protection) |

### Interrupt Controller & ICU

| File | Purpose |
|------|---------|
| `rzv_icu.c` | ICU (Interrupt Control Unit) driver for GPIO/external interrupts |
| `rzv_icu_cm33.c` | ICU variant for CM33 core |
| `rzv_gic.h` (header) | GIC (Generic Interrupt Controller) register defs |

### GPIO & Pin Control

| File | Purpose |
|------|---------|
| `rzv_gpio.c` | GPIO port I/O, input/output config, interrupt wiring |
| `rzv_pinmap.h` | Pin-to-alternate-function matrix (read-only) |

### Serial (UART)

| File | Purpose |
|------|---------|
| `rzv_serial.c` | SCI (Serial Communication Interface) UART driver |
| `rzv_scif.c` | SCIF (Serial Communication Interface with FIFO) variant |

### SPI

| File | Purpose |
|------|---------|
| `rzv_spi.c` | RSPI (Renesas SPI) native SPI controller driver |
| `rzv_sci_spi.c` | SPI mode over SCI peripheral (alternative) |

### I2C

| File | Purpose |
|------|---------|
| `rzv_i2c.c` | RIIC (Renesas I2C) I2C master/slave driver |
| `rzv_sci_i2c.c` | I2C mode over SCI peripheral (alternative) |
| `rzv_sci_i2c_isr.c` | I2C interrupt handler details |
| `rzv_sci_i2c_clock.c` | I2C timing/baud rate generator |

### Timers & PWM

| File | Purpose |
|------|---------|
| `rzv_gpt.c` | GPT (General PWM Timer) 16-bit, PWM output |
| `rzv_gtm.c` | GTM (General Timer Module) 32-bit counter, HRT backing |
| `rzv_hrt.c` | High-resolution timer (GTM-based) |
| `rzv_timerisr.c` | Timer ISR registration for system tick |

### DMA

| File | Purpose |
|------|---------|
| `rzv_dmac.c` | DMAC-B (DMA Controller B) setup and transfers |

### Storage

| File | Purpose |
|------|---------|
| `rzv_sdhi.c` | SDHI (SD Host Interface) SD/eMMC driver |

### Analog

| File | Purpose |
|------|---------|
| `rzv_adc.c` | 12-bit ADC driver |

### CAN

| File | Purpose |
|------|---------|
| `rzv_canfd.c` | CAN-FD (Flexible Data Rate) dual-channel driver |

### Watchdog & Safety

| File | Purpose |
|------|---------|
| `rzv_wdt.c` | Watchdog timer |
| `rzv_poeg.c` | POEG (Port Output Enable for GPT) safety interlock |

### IPC & Multi-Core

| File | Purpose |
|------|---------|
| `rzv_ipc.c` | Legacy IPC shared memory (deprecated, see IPCC) |
| `rzv_ipc_raw.c` | Raw IPC buffer management |
| `rzv_ipc_ipcc.c` | **NuttX IPCC driver** (current standard) |
| `rzv_mhu_core.c` | MHU (Message Handling Unit) signaling for IPCC |
| `rzv_openamp.c` | OpenAMP remote processor framework |
| `rzv_rpmsg.c` | RPMsg (remote message queue) over OpenAMP |
| `rzv_rproc.c` | Remote processor lifecycle management |

### Networking

| File | Purpose |
|------|---------|
| `rzv_ether.c` | Ethernet MAC driver (GMAC) |
| `rzv_ether_phy.c` | PHY (physical layer) init and link detect |

---

## 2. NuttX Board Configurations

**Root:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/`

### Board Directory Structure

```
rdk-rzv2h/
├── configs/          (21 Kconfig profiles, one per test case)
│   ├── adc/          → ADC driver test
│   ├── canfd/        → Single CAN-FD channel
│   ├── canfd-dual/   → Dual CAN-FD channels
│   ├── ether/        → Ethernet + PHY
│   ├── gtm/          → GTM timer test
│   ├── hil-full/     → Hardware-in-loop full feature set
│   ├── hil-spi-loopback/
│   ├── hil-uart-loopback/
│   ├── ipcc/         → IPCC IPC test (CR8-0 + CR8-1)
│   ├── ipcc-multi/   → Stress test (many IPC messages)
│   ├── nsh/          → NuttX shell (basic)
│   ├── nsh-cm33/     → Shell on CM33 core
│   ├── nsh-cr8_1/    → Shell on CR8-1 core
│   ├── nsh-leds/     → LED blink test
│   ├── nsh-scif/     → Shell via SCIF UART
│   ├── pwm/          → PWM output test
│   ├── pwm-oneshot/  → PWM one-shot mode
│   ├── sci-spi-loopback/
│   ├── sdhi/         → SDHI SD card test
│   ├── spi-loopback/
│   └── wdt/          → Watchdog timer test
│
├── include/          (board-specific headers)
│   ├── board.h       (GPIO/UART/SPI assignments for this board)
│   └── ...
│
├── scripts/          (linker scripts per core)
│   ├── rdk-rzv2h_cr8_0.ld
│   ├── rdk-rzv2h_cr8_1.ld
│   ├── rdk-rzv2h_cm33.ld
│   └── ...
│
└── src/              (board initialization code)
    ├── board.c       (board_boot_config, GPIO setup)
    └── ...
```

### Config File Structure

Each config dir (e.g., `configs/ipcc/`) contains:
- `defconfig` — Kconfig symbols (CMAKE-generated)
- `Make.defs` — compiler/linker flags
- `setenv.sh` — environment setup script

---

## 3. PX4 Board & Platform Layer

### Main Board Definition

**Root:** `boards/renesas/rdk-rzv2h/`

Contains:
- `board_config.h` — GPIO/UART/SPI/I2C assignments for PX4
- `board_init.cpp` — sensor probing, HW init
- `Kconfig` — PX4 board variant selection
- `default.px4board` — default feature set
- `firmware.prototype` — binary image template
- `nuttx-config/` — overlay Kconfig/defconfig for NuttX integration
- `px4io_cr8_0/` — uORB bridge to CR8-1/CM33
- `src/` — PX4 module list, init scripts
- `init/rc.board_defaults.cmds` — startup script (MAVLink, sensors, etc.)

### Platform Abstraction

**Root:** `platforms/nuttx/src/px4/renesas/rzv/`

Contains:
- `board.cpp` — board-level init hooks
- `drivers/` — RZ/V2H-specific driver wrappers (I2C, SPI, GPIO)
- `px4_config.h` — PX4 config overrides for this platform

---

## 4. References (Source of Truth)

**Root:** `refs/`

### px4-freertos-posix-renesas-fsp

Complete FreeRTOS + POSIX + Renesas FSP reference.

**Key subdirs:**
```
refs/px4-freertos-posix-renesas-fsp/
├── docs/
│   ├── HARDWARE.md        ← Canonical hardware guide (register maps, clocks, memory)
│   └── ...
├── rzv_cfg/               ← FSP configuration files (pin_data.c source territory)
├── rzv_gen/               ← Generated headers from FSP
│   └── pin_data.c         ← Authoritative pin ownership matrix (source for pinmap.md)
├── rzv/fsp/src/           ← FSP driver implementations (reference for port)
├── script/                ← BSP build scripts
└── px4/boards/renesas/    ← Reference PX4 board layout
```

**Use:** When porting a driver, compare with `rzv/fsp/src/` implementation. Register names, bit widths, and sequences are canonical here.

### rzv2h_scripts_pinmap

Pin configuration and validation scripts.

### rzv2h_gb_ether

Ethernet + PHY reference implementation.

### SCI-B / SPI-B Samples

Four example peripheral drivers:
- `sci_b_uart_rzv2h_evk_cm33_ep/` — UART on CM33
- `sci_b_uart_rzv2h_evk_cr8_0_ep/` — UART on CR8-0
- `sci_b_uart_rzv2h_evk_cr8_1_ep/` — UART on CR8-1
- `spi_b_rzv2h_evk_cm33_ep/` — SPI on CM33

---

## 5. Plans & Historical Records

**Root:** `plans/`

### Canonical Plan (Go-Forward)

- `rzv2h_nuttx_px4_unified_port_plan.md` — master status & roadmap

### Phase-Based Plan Dirs

- `260423-1524-rzv2h-driver-review-audit/` — driver audit (historical)
- `260425-1150-rzv2h-port-v06/` — port v0.6 milestones (historical)
- `260514-2348-rzv2h-esc-pwm-motor-control-audit-fix/` — PWM audit (historical)
- `260520-0000-rzv2h-px4-intercore-board-integration/` — IPC/board integration (historical)
- `260711-0834-rzv2h-port-docs-init/` — **This Phase 1** (current)

### Loose Plans (Superseded, Reference Only)

- `px4_nuttx_rdk-rzv2h_porting_plan.md`
- `rzv2h_cr8_ipcc_ipc_openamp_impl.md`
- `rzv2h_ether_nuttx_audit_fix.md`
- `rzv2h_esc_pwm_motor_control_audit_fix.md`
- `rzv2h_startup_irq_tick_regmap_audit_fix.md`
- `rzv2h_uart_shell_gpio_audit_fix.md`
- `rzv2h_px4_intercore_board_integration.md`

**Note:** These older plans remain for historical audit trail. New work references `rzv2h_nuttx_px4_unified_port_plan.md` and documented specs in `docs/`.

---

## 6. Driver Inventory Summary

**30+ drivers ported to NuttX for RZ/V2H:**

**Core (7):** clock, IRQ, GPIO, serial, I2C, SPI, timers
**Subsystems (23+):** GTM, DMA, CAN-FD, SDHI, XSPI, ADC, watchdog, Ethernet, IPC/IPCC, MHU, OpenAMP, RPMsg, safety interlock

**Validation Status:** Compile-complete; integration tests per config (ipcc, ether, pwm, adc, canfd, sdhi, etc.)

---

## 7. Key Build Artifacts

| Target | Output | Location |
|--------|--------|----------|
| `renesas_rdk-rzv2h_default` | px4 (CR8-0 ELF) | `build/renesas_rdk-rzv2h_default/bin/px4` |
| CR8-1 firmware (if dual-core) | px4io_bridge (CR8-1 ELF) | `build/.../px4io_bridge` |
| NuttX kernel | libnuttx.a | `build/.../nuttx/libnuttx.a` |
| Combined image (XSPI) | px4.bin | `build/.../px4.bin` (1.34 MB typical) |

---

## 8. Cross-References & Related Docs

- **Project Overview:** [project-overview-pdr.md](./project-overview-pdr.md)
- **System Architecture:** [system-architecture.md](./system-architecture.md)
- **Hardware Details:** [renesas/hardware.md](./renesas/hardware.md)
- **Pinmap Authority:** [renesas/pinmap.md](./renesas/pinmap.md)
- **Canonical Plan:** [plans/rzv2h_nuttx_px4_unified_port_plan.md](../plans/rzv2h_nuttx_px4_unified_port_plan.md)

---

## 9. Discovery Tips

**Find driver source:**
```bash
find platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv -name "rzv_<driver>.c"
```

**Check NuttX board config:**
```bash
cat platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/<config>/defconfig | grep CONFIG_RZV_
```

**List PX4 board variants:**
```bash
ls -d boards/renesas/rdk-rzv2h* | xargs -I {} basename {}
```

**Grep FSP reference:**
```bash
grep -r "register\|bit\|mask" refs/px4-freertos-posix-renesas-fsp/rzv/fsp/src/ | grep <driver>
```

---

## Notes

- NuttX submodule at `platforms/nuttx/NuttX/nuttx/` tracks upstream but is RZ/V2H-patched.
- PX4 boards under `boards/renesas/` are independent of NuttX board defs; they reference NuttX via CMake includes.
- Plans folder is semi-historical; check dates and status headers. Canonical state is `rzv2h_nuttx_px4_unified_port_plan.md`.
- References in `refs/` are read-only; they are the baseline for audits and validation.
