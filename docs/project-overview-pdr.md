# RDK-RZ/V2H Port: Project Overview & PDR

**Date:** 2026-10-01  
**Status:** Active; CR8-0 primary, multicore IPC build-clean  
**Scope:** NuttX port + PX4 HAL integration for RDK-RZ/V2H (Renesas R9A09G057H)

---

## 1. Target Hardware

**Board:** RDK-RZ/V2H (Renesas RZ/V2H Development Kit)  
**SoC:** Renesas R9A09G057H (RZ/V2H family)

### Core Configuration

| Core | Mode | RTOS | Role | PX4 target |
|------|------|------|------|------------|
| **CR8-0** | Cortex-R8 | NuttX | Flight stack (PX4) | `renesas_rdk-rzv2h_default` |
| **CR8-1** | Cortex-R8 | NuttX | IO co-processor | `renesas_rdk-rzv2h-io-cr8_1_default` |
| **CM33** | Cortex-M33 | NuttX | IO co-processor (alt) | `renesas_rdk-rzv2h-io-cm33_default` |

Load addresses and per-core aliases: [renesas/multicore-memory-map.md](./renesas/multicore-memory-map.md) (single source of truth).

**IPC Transport:** NuttX IPCC character device (`/dev/ipccN`) over MHU doorbells + shared DDR rings; see [renesas/ipc-architecture.md](./renesas/ipc-architecture.md).

---

## 2. RTOS & Reference Source

**Primary RTOS:** NuttX (see `platforms/nuttx/NuttX/nuttx/` submodule)

**Reference Implementation:** FreeRTOS + POSIX shim + Renesas FSP  
- Located at `refs/px4-freertos-posix-renesas-fsp/`
- Source of truth for hardware register maps, driver implementations, and pinmux

**API Compatibility Layer:** PX4 POSIX shim abstracts FreeRTOS/NuttX differences

---

## 3. Port Deliverables

### NuttX Driver Port (Mandatory)

Complete driver library for CR8-0 primary core:
- **Clock/Power Management:** Clock divider initialization, CPG register truth
- **GPIO/Pinmux:** Port I/O control, alternate function routing (see `rzv_pinmap.h`)
- **Interrupt Controller:** GIC, ICU, TINT wiring and priority management
- **Serial:** SCI/SCIF UART drivers (`/dev/ttyS*`)
- **Timers:** GPT (32-bit, PWM), GTM (32-bit; GTM7 backs PX4 HRT) for high-resolution timing
- **SPI/I2C:** RSPI native SPI, RIIC (SCI-I2C), DMA integration
- **ADC/DAC:** 12-bit ADC, sensor data capture
- **CAN:** CAN-FD controller driver (supports dual CAN channels)
- **Storage:** SDHI (SD/eMMC), XSPI (flash)
- **DMA:** DMAC-B controller and TCM (tightly-coupled memory) region setup

Location: `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`

### PX4 Hardware Abstraction Layer (HAL)

Thin wrapper for PX4 modules:
- **Board Config:** `boards/renesas/rdk-rzv2h/board_config.h`, `board_init.cpp`
- **Sensor HAL:** I2C/SPI bus registration, device probing
- **Timer HAL:** GTM-backed high-resolution timer, io_timer PWM output
- **Storage HAL:** `/fs/params` on volatile TMPFS during bring-up; xSPI LittleFS disabled until flash safety is proven
- **IMU/Barometer/Magnetometer drivers:** Via PX4 sensor driver framework

Location: `boards/renesas/rdk-rzv2h/src/`, `platforms/nuttx/src/px4/renesas/rzv/`

### PX4 Applications (Flight Stack)

- MAVLink telemetry router
- Attitude controller, position controller
- Sensor fusion (EKF2)
- RC input, actuator output

Requires: functional NuttX + HAL drivers.

---

## 4. Out of Scope

- CA55 (Cortex-A55) Linux port (separate system, optional for future versions)
- RPMsg/OpenAMP to CA55 Linux
- NEON/SIMD optimization
- Hardware floating-point FPU optimization (use soft-FP for now)
- FAT32/FATFS storage (use LittleFS for parameters)
- Bluetooth/wireless drivers
- Real-time video streaming (USB camera support is optional)

---

## 5. Success Criteria

- [x] Foundational docs exist and cross-link (`docs/`, `docs/renesas/`)
- [x] PX4 `renesas_rdk-rzv2h_default` builds without errors
- [x] NuttX NSH reachable on CR8-0 (RTT and SCI4)
- [ ] Every NuttX driver reaches bounded on-target evidence (see [renesas/port-status-nuttx.md](./renesas/port-status-nuttx.md))
- [ ] Integrated PX4 image validated on target (cold boot, soak, pin safety)
- [ ] Pinmap electrical proof against `rzv_gen/pin_data.c` and board schematics

Live per-driver status: [renesas/port-status-nuttx.md](./renesas/port-status-nuttx.md), [renesas/port-status-px4-hal.md](./renesas/port-status-px4-hal.md). Milestones: [project-roadmap.md](./project-roadmap.md).

---

## 6. Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Clock/CPG truth not proven | Validate against FSP register tables; automated clock test in CI |
| IPC/IPCC flaky under load | Sequence number + CRC checks in uORB bridge; loopback test harness |
| Driver drift from FSP | Reference commit SHAs in driver comments; diff against FSP sources quarterly |
| Pinmux conflicts (shared pins) | Explicit ownership matrix; CONFIG_ guards in Kconfig |
| Memory layout mismatch (CR8-0/1/CM33) | Linker script audit phase; memory map diagram in `renesas/hardware.md` |

---

## 7. Build & Debug Overview

```bash
./build.sh renesas_rdk-rzv2h_default          # full PX4 image -> build/<target>/<target>.elf
platforms/nuttx/NuttX/build.sh nsh-rtt         # NuttX-only config -> platforms/nuttx/NuttX/nuttx/nuttx
```

Console is SEGGER RTT (JLinkExe bridge on `127.0.0.1:19021`). Load/debug via J-Link + GDB.
Full procedure: [deployment-guide.md](./deployment-guide.md). Agent quick reference: [../AGENTS.md](../AGENTS.md).

---

## 8. Related Documentation

- **System Architecture:** [system-architecture.md](./system-architecture.md)
- **Codebase Summary:** [codebase-summary.md](./codebase-summary.md)
- **RZ/V2H Hardware Guide:** [renesas/README.md](./renesas/README.md)
- **Hardware Details:** [renesas/hardware.md](./renesas/hardware.md)
- **Pinmap Authority:** [renesas/pinmap.md](./renesas/pinmap.md)
- **Active Plan:** [plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md](../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
- **Roadmap:** [project-roadmap.md](./project-roadmap.md)
