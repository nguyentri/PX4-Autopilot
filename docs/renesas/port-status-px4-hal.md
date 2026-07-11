# PX4 HAL Port Status Matrix

**Date:** 2026-07-11  
**Branch:** px4_ra_rzv  
**Scope:** PX4 Hardware Abstraction Layer (HAL) surfaces for RDK-RZ/V2H; cross-referenced to NuttX driver dependencies.

---

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **functional**: Compiles; passes unit tests; integration tests pending.
- **validated**: Integration tests pass; used in application code.

---

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `src/drivers/spi/` | rzv_spi.c (RSPI) + rzv_sci_spi.c | boards/renesas/rdk-rzv2h/src/ | planned | Map PX4 SPI device numbering to /dev/spiN; DMA channel assignment |
| 2 | I2C | `src/drivers/i2c/` | rzv_i2c.c (RIIC) + rzv_sci_i2c.c | boards/renesas/rdk-rzv2h/src/ | planned | DMA optional; clock stretching; multi-master probe |
| 3 | UART/Serial | `src/drivers/serial/` | rzv_serial.c (dispatcher) + rzv_scif.c | boards/renesas/rdk-rzv2h/src/ | planned | Flow control (/dev/ttyS0–2); baud rate config |
| 4 | GPIO | `src/drivers/gpio/` | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | planned | Port I/O mapping; IRQ/edge semantics; LED control |
| 5 | PWM/ESC | `src/drivers/pwm_out/` | rzv_gpt.c (GPT) + rzv_hrt.c (HRT) | boards/renesas/rdk-rzv2h/src/ | planned | Frequency/duty cycle; multi-channel; dshot compatibility |
| 6 | ADC | `src/drivers/adc/` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | planned | Channel mux config; sample rate; sensor integration (baro, airspeed) |
| 7 | Timer/HRT | `src/drivers/timer/` | rzv_hrt.c + rzv_gpt.c | boards/renesas/rdk-rzv2h/src/ | planned | microsecond precision; latency measurement; scheduler backing |
| 8 | CAN | `src/drivers/can/` | rzv_canfd.c | boards/renesas/rdk-rzv2h/src/ | planned | CAN0/CAN1; baud rate; SLCAN over UART alt |
| 9 | Ether/MAVLink UDP | `src/modules/mavlink/` + network stack | rzv_ether.c + rzv_ether_phy.c | boards/renesas/rdk-rzv2h/src/ | planned | IP config; UDP MAVLink stream; link-up polling; LTE modem integration (TBD) |
| 10 | xSPI/LittleFS | `src/modules/fs/littlefs/` | (planned: rzv_xspi.c) | boards/renesas/rdk-rzv2h/src/ | planned | Block device abstraction; wear-leveling; parameter storage |

---

## Detailed Migration Notes by Peripheral

### SPI (Line 1)

**NuttX Foundation:** `rzv_spi.c` (RSPI native) + `rzv_sci_spi.c` (SCI as SPI fallback).

**PX4 HAL Interface:**
- Register `struct spi_dev_s` via `spi_bus_initialize()`.
- Implement `struct spi_ops_s`: select, setfrequency, setmode, send, exchange.
- DMA channel assignment (reference `boards/renesas/rdk-rzv2h/src/rzv2h_spi.c`).
- CS control: GPIO-backed (manual) or native (RSPI RSPnCS).

**Validation:** Loopback test (configs/spi-loopback) before sensor attachment.

---

### I2C (Line 2)

**NuttX Foundation:** `rzv_i2c.c` (RIIC native) + `rzv_sci_i2c.c` (SCI-B as I2C fallback).

**PX4 HAL Interface:**
- Register `struct i2c_dev_s` via `i2c_initialize()`.
- Implement `struct i2c_ops_s`: transfer, reset.
- Multi-master arbitration (address conflict handling).
- Clock stretching (timeout guard).

**Validation:** I2C probe scan; known devices (IMU, baro, mag) enumeration.

---

### UART/Serial (Line 3)

**NuttX Foundation:** `rzv_serial.c` (dispatcher) + `rzv_scif.c` (16-byte FIFO UART).

**PX4 HAL Interface:**
- Register `struct uart_dev_s` (NuttX native).
- Flow control (RTS/CTS) if available on board.
- MAVLink telemetry stream over /dev/ttyS0.
- Debug console fallback.

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
- Future: dshot protocol over SPI (external IC).

**Validation:** Servo command response time <20 ms; frequency stability ±2%.

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

**NuttX Foundation:** `rzv_hrt.c` (high-resolution timer, typically GPT up-counter).

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

**NuttX Foundation:** (planned `rzv_xspi.c` not yet ported from FreeRTOS).

**PX4 HAL Interface:**
- LittleFS mount on `/fs/microsd` (or `/fs/internal`).
- Parameter storage in LittleFS.
- ULog file recording.

**Validation:** File creation, read/write, power-loss resilience.

---

## Roadmap Link

Detailed implementation order and dependency chain: see [Project Roadmap](../project-roadmap.md).

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — driver-level completeness.
- [Code Standards](../code-standards.md) — PX4 API conventions.
- [System Architecture](../system-architecture.md) — HAL role in CR8-0/CR8-1/CM33 topology.
