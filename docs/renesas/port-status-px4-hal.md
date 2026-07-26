# PX4 HAL Port Status Matrix

**Date:** 2026-07-26
**Branch:** px4_ra_rzv  
**Scope:** PX4 Hardware Abstraction Layer (HAL) surfaces for RDK-RZ/V2H; cross-referenced to NuttX driver dependencies.

---

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **build-clean**: HAL adapter implemented and wired into its named board target; compiles/links. No on-target hardware validation yet.
- **deferred**: HAL adapter present but the feature is intentionally disabled in the default build pending hardware enablement (documented in board defconfig).
- **validated**: On-target integration tests pass; used in application code.

> Evidence note: the standalone CR8-0 `nsh-rtt` sample has on-target SCI4
> shell/IRQ and RTT diagnostic evidence. The integrated PX4 target remains
> unvalidated: no PX4 HAL surface has reached **validated** on target.
> `build-clean` is therefore the strongest integrated-HAL tier currently
> supported.

The execution authority is the
[RDK-RZV2H PX4 NuttX Port Goal Plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md).
CR8-0 is the only critical path. CR8-1, CM33, OpenAMP, and remoteproc are final
milestone work.

---

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `micro_hal/micro_hal.cpp` (`px4_spibus_initialize`) | rzv_spi.c (RSPI, hardware CS) | boards/renesas/rdk-rzv2h/src/spi.cpp | build-clean | `CONFIG_RZV_SPI=y`. MPU9250 on SPI0 (CS P93/SSLA0, DRDY P50). Board select/status hooks not used (hardware CS). On-target sensor probe pending |
| 2 | I2C | `micro_hal/micro_hal.cpp` (`px4_i2cbus_initialize`) | rzv_sci_i2c.c (`rzv_sci_i2c_initialize`, SCI-mode) | boards/renesas/rdk-rzv2h/src/i2c.cpp | deferred | BMP280 baro on SCI7 simple-I2C (P76/P77). SCI7 enablement/HW validation deferred in `nsh/defconfig` (baro init `#ifdef CONFIG_RZV_I2C`, unset). HAL I2C dispatch must target `rzv_sci_i2c_initialize`, not the RIIC path — see audit report 260720 |
| 3 | UART/Serial | NuttX serial (native) | rzv_serial.c (dispatcher) + rzv_scif.c | boards/renesas/rdk-rzv2h/ | in-progress | Explicit policy: standalone CR8-0 NuttX = SCI4 shell + RTT diagnostics; target CR8-1 = SCI5 shell + RTT diagnostics; target CM33 = SCI9 shell + RTT diagnostics; integrated PX4 CR8-0 = RTT0 console/debug with SCI4 LiDAR, SCI5 MAVLink/QGC, SCI6 RC at 100000 8E2 plus inversion, SCI9 GPS at 115200 8N1. GPS/RC framing is a G7-G9 hard gate. SCIF remains sample-only/blocked. |
| 4 | GPIO | `include/px4_arch/micro_hal.h` (macros → `rzv_gpio*`) | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | build-clean | Port I/O + IRQ/edge via rzv_gpiosetevent. On-target IRQ latency pending |
| 5 | PWM/ESC | `io_pins/io_timer.c` + `pwm_servo.c` | rzv_gpt.c (GPT) | boards/renesas/rdk-rzv2h/src/timer_config.cpp | build-clean | FSP physical mapping: GPT6A/7B/9A/10B on PA4/PA7/P96/P53. Any logical/physical remap in the PX4/NuttX path must resolve to those four instances. Waveform, safe inactive state, and failsafe validation pending. |
| 5b | DShot (GPT+DMA) | `dshot/dshot.c` + `dshot/dshot_telemetry.c` | rzv_dmac.c (HW-trigger) + rzv_gpt.c | boards/renesas/rdk-rzv2h/dshot.px4board | build-clean (opt-in) | TX-only target `renesas_rdk-rzv2h_dshot` builds and links; default remains PWM and excludes DShot. Checked-in CMSIS/FSP sources verify DMkSEL offsets, unit mapping, and GPT-overflow DMAC activation IDs. GPT buffered compare + one-shot DMA path is not hardware-validated. BDShot capture/telemetry returns `-ENOTSUP`; the pure GCR/eRPM decoder is not a functional telemetry path. Waveform, transfer ordering, repeated trigger/re-arm, and ESC tests remain pending. |
| 6 | ADC | `adc/adc.cpp` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | deferred/non-gating | Battery/airspeed ADC consumers stay disabled for G3-G9. The checked-in drone reference has no active ADC driver; ADC sample/driver work is post-G9. |
| 7 | Timer/HRT | `hrt/hrt.c` (queue mgr) → `rzv_hrt_*` | rzv_hrt.c (GTM7 free-run) | boards/renesas/rdk-rzv2h/src/ | build-clean | `CONFIG_RZV_HRT=y`. µs timebase uses GTM7 (not GPT). `board_config.h` still has a stale GTM0/120 MHz declaration that must be removed. Runtime P1CLK, monotonicity, callback, jitter, and drift validation pending. |
| 8 | CAN | `src/drivers/can/` | rzv_canfd.c | boards/renesas/rdk-rzv2h/src/ | planned | CAN0/CAN1; baud rate; SLCAN over UART alt |
| 9 | Ether/MAVLink UDP | `src/modules/mavlink/` + network stack | rzv_ether.c + rzv_ether_phy.c | boards/renesas/rdk-rzv2h/src/ | planned | IP config; UDP MAVLink stream; link-up polling; LTE modem integration (TBD) |
| 10 | xSPI/LittleFS | PX4 parameter backend + NuttX LittleFS | `rzv2h_xspi_paramfs.c` board MTD/mount path | boards/renesas/rdk-rzv2h/src/ | in-progress | Board paramfs source and Kconfig exist, but partition bounds, mount, parameter round trip, reboot persistence, and power-loss behavior need on-target evidence. Keep separate from SDHI `/dev/mmcsd0` ULog storage. |

---

## Detailed Migration Notes by Peripheral

### SPI (Line 1)

**NuttX Foundation:** `rzv_spi.c` (RSPI native) + `rzv_sci_spi.c` (SCI as SPI fallback).

**PX4 HAL Interface:**
- `px4_spibus_initialize()` → `rzv_spibus_initialize()` (`CONFIG_RZV_SPI=y`).
- Bus/device table in `boards/renesas/rdk-rzv2h/src/spi.cpp` (`px4_spi_buses`).
- CS control: native hardware chip-select (RSPI SSLA0). The STM32-style board select/status callbacks are NOT used by the RZV lower-half and have been removed from the HAL.

**Validation:** Loopback test (configs/spi-loopback) before sensor attachment.

---

### I2C (Line 2)

**NuttX Foundation:** `rzv_sci_i2c.c` (`rzv_sci_i2c_initialize`, SCI-mode simple-I2C — the BMP280 path) + `rzv_i2c.c` (RIIC native, unused on this board).

**Status — deferred:** The BMP280 barometer is wired to SCI7 simple-I2C (P76/P77). In `nsh/defconfig` this is intentionally disabled pending hardware enablement, so baro bring-up in `init.c` (`#ifdef CONFIG_RZV_I2C`) is compiled out. The HAL `px4_i2cbus_initialize()` must dispatch to `rzv_sci_i2c_initialize()` for the SCI bus — it previously referenced an undefined RIIC symbol. See audit report `plans/reports/audit-260720-...`.

**PX4 HAL Interface (target):**
- `px4_i2cbus_initialize(bus)` → `rzv_sci_i2c_initialize(channel)` for SCI-I2C buses.
- Bus/device table in `boards/renesas/rdk-rzv2h/src/i2c.cpp` (BMP280 @ 0x76, `PX4_I2C_BUS_EXPANSION=7`).

**Validation:** I2C probe scan; known devices (IMU, baro, mag) enumeration.

---

### UART/Serial (Line 3)

**NuttX Foundation:** `rzv_serial.c` (dispatcher) + `rzv_scif.c` (SCIF driver). The SCIF path is currently blocked (see [port-status-nuttx.md](port-status-nuttx.md)). Board policy is mode-specific: standalone CR8-0 NuttX uses SCI4 shell + RTT diagnostics; CR8-1 target shell is SCI5; CM33 target shell is SCI9; integrated PX4 CR8-0 keeps RTT0 for console/debug and routes SCI4/5/6/9 to LiDAR, MAVLink/QGC, RC, and GPS respectively.

**PX4 HAL Interface:**
- Register `struct uart_dev_s` (NuttX native).
- Flow control (RTS/CTS) if available on board.
- MAVLink telemetry stream over /dev/ttyS5 for QGroundControl.
- Debug console fallback via RTT0 on integrated PX4; SCI4 remains the standalone CR8-0 shell.

**Validation:** MAVLink heartbeat reception; baud rate stability (115200, 230400, 460800).

---

### GPIO (Line 4)

**NuttX Foundation:** `rzv_gpio.c` (Port 0–12).

**PX4 HAL Interface:**
- GPIO control via `px4_arch_gpioread()`, `px4_arch_gpiowrite()`.
- IRQ attachment via `px4_arch_gpioirq()` + callback.
- LED control (status, error, heartbeat LEDs on rdk-rzv2h).

**Validation:** LED blink test (configs/nsh-leds); button IRQ latency <100 µs.

---

### PWM/ESC (Line 5)

**NuttX Foundation:** `rzv_gpt.c` (16-bit GPT) + `rzv_hrt.c` (HRT backing).

**PX4 HAL Interface:**
- Register PWM devices (`/dev/pwmN`).
- Multi-channel support: up to 6 channels per GPT instance.
- Frequency/duty cycle update atomicity.

**Validation:** Servo command response time <20 ms; frequency stability ±2%.

### DShot (Line 5b)

**NuttX Foundation:** `rzv_gpt.c` buffered compare output + `rzv_dmac.c` hardware-triggered, one-shot memory-to-peripheral transfers.

**PX4 HAL Interface:**
- `renesas_rdk-rzv2h_dshot` is an opt-in TX-only build through `dshot.px4board`.
- `renesas_rdk-rzv2h_default` continues to link and start PWM output; it excludes DShot.
- Bidirectional capture is intentionally unavailable and reports `-ENOTSUP`. The decoder is retained for future capture-front-end work only.

**Validation:** Host build and artifact separation pass. Logic-analyzer waveform/ordering, repeated trigger and re-arm, multi-channel launch, cleanup paths, and ESC response remain on-target gates. See the [QA report](../../plans/reports/tester-260720-rzv2h-dshot-runtime-fixes.md) and [code review](../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md).

---

### ADC (Line 6)

**NuttX Foundation:** `rzv_adc.c` (12-bit SAR).

**PX4 HAL Interface:**
- Register ADC channels via `adc_register()`.
- Sensor calibration (baro offset, airspeed scale).
- Sample rate: min 1 kHz (for vibration filtering).

**Validation:** Noise floor <1 LSB; thermal drift <0.1%/°C.

---

### Timer/HRT (Line 7)

**NuttX Foundation:** `rzv_hrt.c` uses dedicated GTM7 in free-running mode and
derives its timebase from runtime P1CLK. GPT6/7/9/10 remain PWM resources.

**PX4 HAL Interface:**
- `px4_clock_gettime()` for µs-precision timestamps.
- Work-queue scheduling backed by HRT expiry.
- Flight-control loop clock source.

**Validation:** Jitter <100 µs; uptime >1 hour without drift >1 ppm.

---

### CAN (Line 8)

**NuttX Foundation:** `rzv_canfd.c` (CAN-FD controller; supports classical CAN 2.0B).

**PX4 HAL Interface:**
- CAN device driver (standard: `struct can_dev_s`).
- Bitrate config (250k, 500k, 1M typical for UAV).
- Telemetry (TBD: SLCAN over UART as fallback).

**Validation:** CAN frame RX/TX with known CAN analyzer; arbitration stress.

---

### Ether/MAVLink UDP (Line 9)

**NuttX Foundation:** `rzv_ether.c` (MAC) + `rzv_ether_phy.c` (PHY).

**PX4 HAL Interface:**
- Network driver registration (NuttX netdev).
- DHCP or static IP config.
- UDP MAVLink listener on port 14550.

**Validation:** Ping response; MAVLink GCS connection; latency <100 ms.

---

### xSPI/LittleFS (Line 10)

**NuttX Foundation:** board source
`platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_xspi_paramfs.c`
provides the current parameter-MTD/mount path. It is implemented in source but
not yet proven as a persistent PX4 parameter backend on target.

**PX4 HAL Interface:**
- LittleFS parameter mount under the board `/fs` contract.
- Parameter storage uses the xSPI partition only after boundary and power-cycle proof.
- ULog uses a separate SDHI-backed mount when SDHI is validated.

**Validation:** Partition-boundary audit, mount, parameter save/reboot/load,
controlled power-loss recovery, and proof that no executable/boot region is
erased.

---

## CR8-0 Goal Reconciliation

- Required first-drone HAL gates: SPI0 IMU, SCI7 I2C barometer, SCI4/5/6/9
  serial, GPS SCI9 115200 8N1, RC SCI6 100000 8E2 plus inversion, GPIO/IRQ,
  GTM7 HRT, GPT PWM, and parameter persistence.
- Post-G9/non-gating: ADC, WDT integration, and SDHI/ULog. These are not active
  in the checked-in drone reference.
- Optional: CAN, Ethernet/UDP, DShot.
- Default integrated PX4 must not fail because OpenAMP, IPCC, CR8-1, CM33, or a
  CA55 endpoint is absent.
- The integrated image uses RTT0 for text console/debug and SCI5 for binary
  MAVLink/QGroundControl traffic.

---

## Roadmap Link

Detailed implementation order and dependency chain: see [Project Roadmap](../project-roadmap.md).

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — driver-level completeness.
- [Code Standards](../code-standards.md) — PX4 API conventions.
- [System Architecture](../system-architecture.md) — HAL role in CR8-0/CR8-1/CM33 topology.
