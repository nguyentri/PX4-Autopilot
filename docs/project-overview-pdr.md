# RDK-RZ/V2H Port: Project Overview & PDR

**Date:** 2026-07-11  
**Status:** Foundational (Phase 1)  
**Scope:** NuttX port + PX4 HAL integration for RDK-RZ/V2H (Renesas R9A09G057H)

---

## 1. Target Hardware

**Board:** RDK-RZ/V2H (Renesas RZ/V2H Development Kit)  
**SoC:** Renesas R9A09G057H (RZ/V2H family)

### Core Configuration

| Core | Mode | RTOS | Role | Boot Vector |
|------|------|------|------|-------------|
| **CR8-0** | Cortex-R8 | NuttX | Flight stack (PX4) | 0x00000000 (SRAM/internal) |
| **CR8-1** | Cortex-R8 | NuttX | IO co-processor | 0x40000000 (shared DRAM) |
| **CM33** | Cortex-M33 | NuttX | IO co-processor (alt) | 0x40100000 (shared DRAM) |

**IPC Transport:** NuttX IPCC character device over MHU (see commit 289f3203ec6).

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
- **Timers:** GPT (16-bit), GTM (32-bit), HRT backing for high-resolution timing
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
- **Storage HAL:** LittleFS mount on XSPI flash for parameter store (`/fs/params`)
- **IMU/Barometer/Magnetometer drivers:** Via PX4 sensor driver framework

Location: `boards/renesas/rdk-rzv2h/src/`, `platforms/nuttx/src/px4/renesas/rzv/`

### PX4 Applications (Flight Stack)

- MAVLink telemetry router
- Attitude controller, position controller
- Sensor fusion (EKF2)
- RC input, actuator output

Requires: functional NuttX + HAL drivers.

---

## 4. Out of Scope (Phase 1)

- CA55 (Cortex-A55) Linux port (separate system, optional for future versions)
- RPMsg/OpenAMP bridging (Phase 2+)
- NEON/SIMD optimization
- Hardware floating-point FPU optimization (use soft-FP for now)
- FAT32/FATFS storage (use LittleFS for parameters)
- Bluetooth/wireless drivers
- Real-time video streaming (USB camera support is optional)

---

## 5. Success Criteria (Phase 1)

- [ ] All 6 foundational docs created (≤800 LOC each, cross-linked)
- [ ] 30+ NuttX drivers compile and link (clock, GPIO, UART, SPI, I2C, timers, DMA, etc.)
- [ ] PX4 `renesas_rdk-rzv2h_default` builds without errors
- [ ] NuttX shell boots on serial console (`/dev/ttyS*`)
- [ ] Pinmap authoritative matrix exists and matches `rzv_gen/pin_data.c`

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

## 7. Build & Flash Overview

**Build:**
```bash
cd /home/tringuyen/PX4-Autopilot
./build.sh renesas_rdk-rzv2h_default
```

**Flash (XSPI):**
```bash
# Via J-Link
JLinkExe -device R9A09G057H -if SWD -speed 4000 -CommandFile flash.jlink
```

**Serial Console:**
```bash
# After boot, NuttX shell on UART (default /dev/ttyS1 or /dev/ttyS4)
picocom -b 115200 /dev/ttyUSB0
```

---

## 8. Related Documentation

- **System Architecture:** [system-architecture.md](./system-architecture.md)
- **Codebase Summary:** [codebase-summary.md](./codebase-summary.md)
- **RZ/V2H Hardware Guide:** [renesas/README.md](./renesas/README.md)
- **Hardware Details:** [renesas/hardware.md](./renesas/hardware.md)
- **Pinmap Authority:** [renesas/pinmap.md](./renesas/pinmap.md)
- **Canonical Plan:** [plans/rzv2h_nuttx_px4_unified_port_plan.md](../plans/rzv2h_nuttx_px4_unified_port_plan.md)
