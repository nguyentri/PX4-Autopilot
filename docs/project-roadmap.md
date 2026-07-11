# RDK-RZ/V2H Port Roadmap

**Date:** 2026-07-11  
**Scope:** Milestones and dependencies for NuttX + PX4 flight-stack port to RDK-RZ/V2H.  
**Canonical Plan:** See `plans/rzv2h_nuttx_px4_unified_port_plan.md` for detailed implementation strategies and risk analysis.

---

## Milestone Overview

| Milestone | Status | Target | Key Deliverable | Blockers |
|-----------|--------|--------|-----------------|----------|
| **M0** | Done | 2026-06-01 | NuttX submodule, drivers build-clean, IPCC MHU baseline | None |
| **M1** | In Progress | 2026-07-31 | All NuttX drivers functional | Driver validation (per-driver) |
| **M2** | Planned | 2026-08-31 | PX4 HAL surfaces (SPI, I2C, UART, GPIO, PWM, ADC) | M1 completion; HAL porting |
| **M3** | Planned | 2026-09-30 | Sensor drivers (IMU, mag, baro, GPS) up and integrated | M2 completion; sensor availability |
| **M4** | Planned | 2026-10-31 | Actuator/ESC output functional | M3 completion; PWM validation |
| **M5** | Planned | 2026-11-30 | Flight-stack integration, basic hover (manual, no autonomy) | M4 completion; flight testing |
| **M6** | Planned | 2026-12-31 | MAVLink + telemetry + params, GCS connectivity | M5 completion; network integration |
| **M7** | Planned | 2027-01-31 | Autonomous flight modes (guided, auto, mission) | M6 completion; flight validation |

---

## M0: Foundational (DONE)

**Status:** Completed 2026-06-30.

**Deliverables:**

- [x] NuttX submodule synced at `platforms/nuttx/NuttX/nuttx`.
- [x] All 41 NuttX drivers compile without errors (build-clean).
- [x] IPC infrastructure in place:
  - [x] MHU register layer (rzv_mhu_core.c, rzv_mhu.h).
  - [x] IPCC character device (rzv_ipc_ipcc.c, /dev/ipcc0).
  - [x] RPMsg/OpenAMP integration (rzv_rpmsg.c, rzv_rproc.c).
  - [x] uORB bridge frame format (commit 289f3203ec6).
- [x] CR8-0 boots to NuttX shell (nsh console on SCIF0).
- [x] CR8-1 loads and synchronizes (remote processor via MHU).

**Validation:**
- [x] CR8-0 reaches prompt: `nsh>`.
- [x] CR8-1 boots without hang or reboot.
- [x] IPC loopback message exchange (cr8_0 → mhu → cr8_1, acknowledge back).

**Documentation:** See [Project Overview](project-overview-pdr.md), [System Architecture](system-architecture.md), [Codebase Summary](codebase-summary.md).

---

## M1: Driver Bring-up (IN PROGRESS)

**Target:** 2026-07-31 | **Status:** Driver validation in progress.

**Deliverables:**

- [ ] All 41 drivers in [port-status-nuttx.md](renesas/port-status-nuttx.md) reach **functional** status.
- [ ] Validation checklist completed per driver (link to [validation-checklist.md](renesas/validation-checklist.md)).
- [ ] Sample configs tested (adc, canfd, ether, sdhi, spi-loopback, uart, pwm, wdt, etc.).

**Key Driver Groups:**

### G1: Clock, Memory, IRQ (Foundation)
- [x] rzv_clock.c (CPG clock divider setup)
- [x] rzv_memmng.c (heap, page alignment)
- [x] rzv_irq.c, rzv_irq_cm33.c (GIC, NVIC vectors)
- [x] rzv_icu.c (interrupt routing)
- Status: **functional** (blocking none; enables all others)

### G2: Serial & Debug
- [ ] rzv_scif.c (UART16 FIFO — nsh-scif config)
- [ ] rzv_lowputc.c (early boot console)
- [ ] rzv_serial.c (framework dispatcher)
- Status: **functional** (CR8-0 console ready; CR8-1 todo)

### G3: GPIO & Pinmux
- [ ] rzv_gpio.c (Port 0–12, IRQ/edge control)
- [ ] rzv_pinmap.h (pin ownership database)
- Sample config: nsh-leds (blink LED0 test)
- Status: **functional** (basic I/O ready; edge timing validation pending)

### G4: Timers (HRT, GPT, GTM)
- [ ] rzv_hrt.c (high-resolution timer, system clock)
- [ ] rzv_gpt.c (16-bit general purpose timer, PWM generation)
- [ ] rzv_gtm.c (32-bit general timer)
- [ ] rzv_timerisr.c (timer ISR dispatch)
- Sample config: pwm (PWM frequency sweep test)
- Status: **functional** (timing validation in progress)

### G5: SPI & I2C
- [ ] rzv_spi.c, rzv_sci_spi.c (SPI master, DMA integration)
- [ ] rzv_i2c.c, rzv_sci_i2c.c (I2C master, RIIC + SCI fallback)
- Sample configs: spi-loopback, (i2c TBD)
- Status: **functional** (sensor attachment pending M2)

### G6: ADC
- [ ] rzv_adc.c (12-bit SAR, channel scanning)
- Sample config: adc (battery voltage, airspeed test)
- Status: **functional** (sensor integration at M3)

### G7: Storage
- [ ] rzv_sdhi.c (SD/MMC host, card-detect)
- [ ] rzv_sdhi ULog path setup
- Sample config: sdhi (file I/O stress test)
- Status: **functional** (LittleFS mount verified)

### G8: CAN
- [ ] rzv_canfd.c (CAN-FD dual channel, message filtering)
- Sample configs: canfd, canfd-dual (loopback test)
- Status: **functional** (telemetry integration at M6)

### G9: IPC & Co-processor
- [ ] rzv_ipc.c (dispatcher)
- [ ] rzv_ipc_ipcc.c (IPCC /dev/ipcc0)
- [ ] rzv_rpmsg.c (RPMsg frame layer)
- [ ] rzv_rproc.c (remote processor loader)
- Sample config: ipcc, ipcc-multi
- Status: **functional** (CR8-1 ↔ CR8-0 message validation)

### G10: Utility & Housekeeping
- [x] rzv_idle.c (CPU WFI, stub status acceptable)
- [x] rzv_start.c, rzv_start_cm33.c (bootstrap)
- [x] rzv_mpu_regions.c (ARM MPU setup)
- [x] rzv_mhu_core.c (MHU register helpers)
- [x] rzv_openamp.c (future; deprecated in current IPC path, stub status ok)

**Completion Criteria:**
- Row count in [port-status-nuttx.md](renesas/port-status-nuttx.md) ≥38 at "functional" status.
- Validation checklists linked and signed-off.
- Sample configs boot without panic.

**Documentation:** See [NuttX Port Status](renesas/port-status-nuttx.md), [Validation Checklist](renesas/validation-checklist.md), [Peripheral Specs](renesas/peripherals/).

---

## M2: PX4 HAL Port (PLANNED)

**Target:** 2026-08-31 | **Depends on:** M1 completion.

**Deliverables:**

Complete HAL drivers for:
1. **SPI** — Map PX4 device numbering to /dev/spiN; DMA channel assignment (SPI0 ch. 2, SPI1 ch. 3, etc.).
2. **I2C** — Sensor enumeration; multi-master probe (IMU, mag, baro addresses).
3. **UART/Serial** — MAVLink telemetry stream on /dev/ttyS0.
4. **GPIO** — LED control, button IRQ.
5. **PWM/ESC** — Servo output via GPT channels; frequency/duty sync.
6. **ADC** — Battery voltage monitor, airspeed differential.
7. **Timer/HRT** — System clock backing; µs-precision timestamps.
8. **CAN** — CAN0/CAN1 frame RX/TX.
9. **Ether/UDP** — MAVLink GCS link (optional; UART fallback).

**Deliverable Artifact:** [port-status-px4-hal.md](renesas/port-status-px4-hal.md) updated to **functional** for all HAL surfaces.

**Testing:** PX4 core bringup (no flight controller code yet; sensor discovery only).

**Documentation:** See [PX4 HAL Port Status](renesas/port-status-px4-hal.md).

---

## M3: Sensor Drivers (PLANNED)

**Target:** 2026-09-30 | **Depends on:** M2 completion.

**Deliverables:**

Sensor drivers integrated on CR8-1 co-processor:
- **IMU (6-axis)** — SPI/I2C attachment (MPU9250, ICM20649, or equiv); orientation calibration.
- **Magnetometer** — I2C or SPI (HMC5883L, IST8310, or equiv); declination calib.
- **Barometer** — I2C (BMP280, MS5611, or equiv); altitude reference.
- **GPS** — UART attach (u-blox, SBAS); rtcm3 input (RTK-capable variant).

**uORB Integration:**
- CR8-1 reads sensors → publishes to uORB (sensor_accel, sensor_mag, sensor_baro, sensor_gps).
- CR8-0 subscribes via IPC bridge (MHU/IPCC) → fused in extended Kalman filter.

**Completion:** CR8-1 boots, enumerates sensors, logs to uORB ringbuffer; CR8-0 receives updates.

---

## M4: Actuator Output (PLANNED)

**Target:** 2026-10-31 | **Depends on:** M3 completion.

**Deliverables:**

Servo/ESC driver stack:
- **PWM/GPIO** — 6 PWM channels (for 6-DOF multirotor or fixed-wing control surfaces).
- **Safety pin** — Disarm detect via GPIO; failsafe on pin release.
- **Failsafe** — ESC pulse to zero on loss of signal (PX4 watchdog → pwm_out driver).

**Testing:** Manual PWM command verification; no flight (manual control ground test only).

---

## M5: Flight-Stack Integration & Manual Flight (PLANNED)

**Target:** 2026-11-30 | **Depends on:** M4 completion.

**Deliverables:**

- CR8-0 PX4 flight controller app running (px4_main).
- Sensor fusion (EKF) accepting IMU/mag/baro/GPS.
- Attitude controller stabilizing roll/pitch/yaw.
- **Flight mode:** Manual (RC stick → attitude setpoint) only.
- **Failsafe:** Disarm on RC loss; return to home (GPS only).

**Milestone Test:** Hand-held hover for 30 seconds on GPS-denied area; visual stability.

---

## M6: Telemetry & Parameter System (PLANNED)

**Target:** 2026-12-31 | **Depends on:** M5 completion.

**Deliverables:**

- **MAVLink stream** — UART or Ether link to GCS (QGroundControl, Mission Planner).
- **Parameter set** — Load/save tuning params (PID gains, sensor scales, failsafe thresholds) via MAVLink.
- **GCS connectivity** — Real-time attitude, GPS, battery telemetry.
- **Flight log** — ULog recording to SD card (via SDHI0).

**Milestone Test:** GCS receives telemetry; operator can change param; log playback in Fusion Engine.

---

## M7: Autonomous Flight (PLANNED)

**Target:** 2027-01-31 | **Depends on:** M6 completion.

**Deliverables:**

- **Flight modes:**
  - **Guided** — Accept velocity/position setpoints from GCS or companion computer.
  - **Auto** — Waypoint mission (takeoff, fly to WP, land) via MAVLink mission protocol.
- **Position control** — GPS + barometer altitude hold; optical flow (optional) for indoor nav.
- **Land detector** — Disarm on landing (accel/vertical velocity signature).

**Milestone Test:** Autonomous square mission (4 waypoints) in outdoor GPS environment.

---

## Dependency Graph

```
M0 (Foundation: NuttX, IPCC, boot)
  ↓
M1 (Driver validation: 41 drivers → functional)
  ├─ G1: Clock/IRQ (blocks all)
  ├─ G2: Serial (debug, blocking none)
  ├─ G3: GPIO (blocking PWM, sensor attach)
  ├─ G4: Timers (blocking PWM, HRT)
  ├─ G5: SPI/I2C (blocking sensors, HAL)
  ├─ G6: ADC (blocking battery, airspeed)
  ├─ G7: Storage (blocking ULog)
  ├─ G8: CAN (blocking telemetry)
  └─ G9: IPC (blocking CR8-1 sensor fusion)
      ↓
M2 (HAL port: 9 surfaces → functional)
  ├─ Depends on: SPI, I2C, UART ready (G5, G2)
  ├─ Depends on: GPIO, PWM, ADC, Timer ready (G3, G4, G6)
  ├─ Depends on: CAN, Ether optional (G8)
      ↓
M3 (Sensors: IMU, mag, baro, GPS)
  ├─ Depends on: I2C/SPI HAL (M2)
  ├─ Depends on: UART HAL for GPS
      ↓
M4 (Actuator output: PWM channels, safety pin)
  ├─ Depends on: Timer/PWM HAL (M2)
      ↓
M5 (Flight-stack integration & manual flight)
  ├─ Depends on: Sensor fusion (M3), Actuator output (M4)
      ↓
M6 (Telemetry & params)
  ├─ Depends on: MAVLink, ULog (M5)
      ↓
M7 (Autonomous flight modes)
  ├─ Depends on: Guidance, position control (M6)
```

---

## Risk & Mitigation

| Risk | Probability | Mitigation |
|------|-------------|-----------|
| Driver validation delays | Medium | Prioritize G1, G4, G5 (clock, timer, SPI/I2C); others in parallel. |
| CR8-1 ↔ CR8-0 IPC sync issues | Medium | Extensive M1 testing; add seq number validation + CRC checks (commit 289f3203 done). |
| Sensor calibration drift | Low | Per-platform calibration data stored in parameter system; sensor redundancy (M3 deliverable). |
| PX4 tuning for new airframe | Medium | Retain example configs for known platforms (Quadcopter, fixed-wing). |
| Flight-test infrastructure | Low | Use manual mode first (M5) before autonomous (M7); hand-launched test possible. |

---

## Status Tracking

**Update Frequency:** Weekly during active work (M1–M2); bi-weekly thereafter.

**Measurement:**
- M1: % drivers at functional status (target ≥92% by EOJ).
- M2: % HAL surfaces functional (target 100% by EOA).
- M3–M7: Feature acceptance tests (TBD per milestone).

**Tracking Tool:** [port-status-nuttx.md](renesas/port-status-nuttx.md) + [port-status-px4-hal.md](renesas/port-status-px4-hal.md).

---

## Related Docs

- [Project Overview & PDR](project-overview-pdr.md) — Scope, boards, deliverables.
- [NuttX Port Status](renesas/port-status-nuttx.md) — Per-driver completion tracking.
- [PX4 HAL Port Status](renesas/port-status-px4-hal.md) — HAL surface tracking.
- [Canonical Plan](plans/rzv2h_nuttx_px4_unified_port_plan.md) — Detailed implementation strategies.
