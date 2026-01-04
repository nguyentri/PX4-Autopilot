
# RA8P1 delivery drone software specification — R7JA8P1JSLSAJ (PLBG0303)

**Document version:** 1.0
**Date:** 01-Jan-2026
**Project:** RA8P1-based delivery drone platform
**Target platform:** Renesas R7JA8P1JSLSAJ PLBG0303 (Cortex-M85 @ 1 GHz + Cortex-M33 @ 250 MHz)
**Flight stack:** PX4 Autopilot v1.14+ on NuttX RTOS
**Classification:** Engineering reference — Implementation & architecture review

---

## Document control

| Revision | Date | Author | Changes |
|---|---:|---|---|
| 1.0 | 01-Jan-2026 | PX4/RA8P1 Integration Team | Initial specification (R7JA8P1JSLSAJ - 303-pin) |

---

## Key hardware clarifications (R7JA8P1JSLSAJ PLBG0303)

- ✅ Package: 303-pin PLBG (17 mm × 17 mm × 1.4 mm)
- ✅ SPI channels: 2 hardware SPI (SPI0, SPI1) + SCI_SPI extension
- ✅ I2C buses: I2C0, I2C1, I2C2 available
- ✅ I3C: single I3C channel (I3C0) for high-speed peripheral extension
- ✅ SiP-Flash: 8 MB on-chip code flash
- ✅ NVRAM: 1 MB internal NVRAM
- ✅ SDRAM: external SDRAM MANDATORY for AI tensor buffers
- ✅ SDHI: native SD card controller for high-speed logging

---

## Executive summary

This specification defines the complete architecture for a commercial-grade
delivery drone flight management unit (FMU) based on the Renesas RA8P1
R7JA8P1JSLSAJ dual-core microcontroller (CM85 @ 1 GHz + CM33 @ 250 MHz).
The system integrates PX4 Autopilot on NuttX RTOS with advanced capabilities:

- Dual-core architecture: CM85 handles flight control; CM33 manages I/O and
  failsafe logic.
- Edge AI processing: Ethos-U55 NPU (256 GOPS INT8) for onboard obstacle
  avoidance.
- Dual sensor redundancy: 2× IMU (BMI088 on SPI0, ICM-42688-P on SPI1),
  2× barometer (BMP390 on I2C0/I2C1), GPS, magnetometer on I2C2.
- Expansion: SCI_SPI extension (4 pins) for optional third IMU, I3C extension
  (2 pins) for high-speed peripherals.
- High-performance comms: Ethernet 100 Mbps / TSN, dual CAN-FD (5 Mbps),
  multiple UARTs, USB HS.
- Safety critical: hardware failsafes (POEG emergency kill < 10 ms),
  independent watchdog, sensor voting, IPC heartbeat monitoring.
- Storage: SDRAM for AI tensor buffers, SDHI for logging, FRAM for
  mission-critical parameter storage.

Key design philosophy: use 2 MB internal SRAM + external SDRAM for AI
vision processing, leverage 8 MB on-chip flash and 1 MB NVRAM, use both
hardware SPI channels for dual-IMU redundancy, and provide an I3C extension
for future high-speed sensors.

---

## Table of contents

1. System overview & architecture
2. Hardware platform specifications
3. Dual-core task partitioning
4. PX4 module → RA8P1 peripheral mapping
5. Sensor suite configuration
6. Extension ports & future expansion
7. Inter-core communication protocol
8. Driver architecture & APIs
9. Edge AI integration
10. Memory partitioning & linker strategy
11. Boot sequence & secure boot
12. Safety & failsafe design
13. Storage architecture
14. Performance targets & measurements
15. Testing & validation strategy
16. Build system integration
17. Companion computer interface
18. Pin mapping reference
19. Open issues & TBD items
20. Appendix: diagrams & code examples

---

## 1. System overview & architecture

### 1.1 High-level block diagram

```text
┌─────────────────────────────────────────────────────────────────┐
│                R7JA8P1JSLSAJ FMU System Architecture            │
│             (2× Hardware SPI, I2C0/I2C1/I2C2, I3C)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐          ┌──────────────────────────┐  │
│  │ Cortex-M85 @ 1GHz   │◄──IPC──►│ Cortex-M33 @ 250MHz       │  │
│  │ (Primary / FMU)     │ <1 ms   │ (Secondary / IO & Safety) │  │
│  │ • PX4 Autopilot     │  RTT    │ • RC Input Handler        │  │
│  │ • NuttX RTOS        │         │ • PWM / DShot Output      │  │
│  │ • Sensor Fusion     │         │ • Watchdog on CM85        │  │
│  │ • Navigation        │         │ • POEG Emergency Kill     │  │
│  │ • Edge AI (NPU)     │         │ • Arming Logic            │  │
│  │ • Telemetry         │         │ • Safety Interlock        │  │
│  │                     │         │ • Battery Monitoring      │  │
│  │                     │         │    (ADC, SMBus )          │  │
│  └─────────────────────┘         └───────────────────────────┘  │
│           │                                  │                  │
│           └──────────┬───────────────────────┘                  │
│                      │                                          │
│   ┌──────────────────┴────────────┬──────────────┬──────────┐   │
│   │ Sensors (Dual IMU)            │ Memory       │ NPU      │   │
│   │ • IMU1: SPI0 (BMI088)         │ • SRAM: 2MB  │ Ethos    │   │
│   │ • IMU2: SPI1 (ICM42688-P)     │ • SDRAM:32MB │ U55      │   │
│   │ • Baro1: I2C0 (BMP390)        │ • NVRAM:1MB  │ 256 GOPS │   │
│   │ • Baro2: I2C1 (BMP390)        │ • Flash: 8MB │ INT8     │   │
│   │ • Mag: I2C2 (BMM150)          │ • FRAM: 32KB │          │   │
│   │ • GPS: UART                   │ • SD: SDHI   │          │   │
│   └───────────────────────────────┴──────────────┴──────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 System characteristics

| Attribute | Specification | Notes |
|---|---|---|
| MCU | R7JA8P1JSLSAJ | 303-pin PLBG package, 17 mm × 17 mm × 1.4 mm |
| Primary core | ARM Cortex-M85 @ 1 GHz | Helium SIMD, FPU, DSP extensions |
| Secondary core | ARM Cortex-M33 @ 250 MHz | TrustZone-M, FPU |
| NPU | ARM Ethos-U55 @ 250 MHz | 256 GOPS INT8 |
| Internal SRAM | 2,048 KB | ECC protected, shared between cores |
| ITCM | 128 KB (CM85 only) | Zero-wait instruction TCM |
| DTCM | 128 KB (CM85 only) | Zero-wait data TCM |
| NVRAM | 1 MB | Bootloader + firmware |
| On-chip flash | 8 MB | XIP execute-in-place, ECC |
| External SDRAM | 32–64 MB (IS42S32160F) | MANDATORY for AI |
| FRAM | 32 KB (FM24W256-GTR) | I2C interface |
| SD card | Up to 32 GB (SDXC) | SDHI1 controller |
| SPI | 2 channels | SPI0, SPI1 |
| I2C | 3 channels | I2C0, I2C1, I2C2 |
| I3C | 1 channel | I3C0, backward compatible with I2C |
| Temp range | -40°C to +85°C | Industrial grade |

---

## 2. Hardware platform specifications

### 2.1 MCU core specifications

#### Cortex-M85 (CM85) — Primary FMU

- Clock: 1 GHz (via PLL from 24 MHz crystal)
- ISA: ARMv8.1-M with Helium vector extensions (SIMD)
- FPU: Double-precision (FP64)
- DSP: Saturating arithmetic, SIMD for sensor fusion
- Cache: ITCM/DTCM for zero-wait code/data
- MPU: 16-region MPU (optional TrustZone isolation)

#### Cortex-M33 (CM33) — Secondary I/O processor

- Clock: 250 MHz (PCLKD domain)
- ISA: ARMv8-M mainline
- FPU: Single-precision (FP32)
- TrustZone: Supported (not used in baseline)
- MPU: 8-region MPU

#### Ethos-U55 NPU

- Clock: 250 MHz (PCLKD domain)
- Performance: 256 GOPS @ INT8, 128 MACs/cycle
- Supported ops: Conv2D, depthwise conv, FC, pooling, activations
- Framework: TensorFlow Lite Micro w/ Ethos-U delegate
- Typical latency: 100–200 ms for MobileNetV2-SSD (224×224)

### 2.2 Memory resources

#### On-chip memory

| Memory | Base | Size | Speed | ECC | Purpose |
|---|---:|---:|---:|---:|---|
| ITCM  | 0x00000000 | 128 KB | 1-cycle | No | Critical ISR code (CM85) |
| DTCM  | 0x20000000 | 128 KB | 1-cycle | No | ISR data, stacks (CM85) |
| ITCM  | 0x00000000 | 64 KB | 1-cycle | No | Critical ISR code, DSHOT (CM33) |
| DTCM  | 0x20000000 | 64 KB | 1-cycle | No | ISR data, stacks (CM33) |
| SRAM  | 0x20020000 | 1664 KB | 1-cycle | Yes | Main heap, message buffers |
| NVRAM | 0x02000000 | 1 MB | ~10 cycles | Yes | Bootloader, keys, NuttX kernel |
| Flash | 0x08000000 | 8 MB | ~5 cycles | Yes | PX4 modules, AI models |

#### External memory (MANDATORY)

- SDRAM: `0x68000000`, 32–64 MB (32-bit bus @ 133 MHz) — AI tensor arena,
  video buffers, datasets.
- FRAM: FM24W256-GTR, I2C @ 400 kHz — mission-critical params.
- SD Card: SDHI1 — flight logs (ULog), terrain maps.

#### Memory utilization (summary)

- Internal SRAM: PX4 core (~832 KB), CM33 (~768 KB), IPC (~64 KB), reserved
  (~384 KB) for DMA/buffers.
- SDRAM: 20 MB for AI tensor arena, 8 MB for video buffers, 2 MB parameter
  cache, remainder for models/datasets.

### 2.3 Sensor suite (dual IMU configuration)

#### IMUs (dual redundancy)

| IMU | Model | Interface | Sample rate | Accel range | Gyro range | Notes |
|---|---|---:|---:|---:|---:|---|
| IMU1 | Bosch BMI088 | SPI0 (SPI0) | 10 Mhz | ±24 g | ±2000 °/s | Primary, high accuracy |
| IMU2 | TDK ICM-42688-P | SPI1 (SPI1) | 20 Mhz | ±16 g | ±2000 °/s | Secondary, high-rate backup |

#### Barometers

- BMP390 on I2C0 (addr 0x76), 100 Hz
- BMP390 on I2C1 (addr 0x77), 100 Hz

#### Magnetometer & GPS

- Mag: Bosch BMM150 on I2C2 (addr 0x10), 100 Hz.
- GPS: u-blox M8N/M9N on UART SCI4_C, 10 Hz, UBX protocol.

#### Camera (optional)

- MIPI-CSI2 camera 1080p @ 30 fps, 2-lane MIPI CSI-2 @ 500 Mbps/lane.

### 2.4 I/O interfaces

- UART/SCI: 9 channels (SCI0–SCI9). Used: console (SCI0_B), GPS1 (SCI4_C),
  TELEM1 (SCI5_C), TELEM2 (SCI6_A), RC input (SCI8_A). GPS2 (SCI9_B) and
  TELEM3 (SCI7_B) reserved.
- CAN-FD: 2 channels @ 5 Mbps.
- Ethernet: 10/100 Mbps RMII (ET1 MAC) with TSN.
- USB: High Speed (480 Mbps).
- PWM/DShot outputs: up to 12 channels via GPT timers (GPT3–GPT13).
- ADC: 12-bit, 24 channels.
- LEDs: 3 GPIO outputs. Safety switch: GPIO input with IRQ.
- SDHI1: native SD controller, 4-bit SD bus @ 50 MHz.

---

## 3. Dual-core task partitioning (CM85 vs CM33)

### 3.1 Core responsibilities overview

#### Cortex-M85 (CM85) — FMU

- Execute PX4 flight control stack (attitude, position, navigation).
- Sensor drivers and data fusion (EKF2).
- Communication (MAVLink, RTPS/DDS).
- Edge AI inference with Ethos-U55 using SDRAM tensor arena.
- SD logging via SDHI1. OS: NuttX.

#### Cortex-M33 (CM33) — I/O processor

- Decode RC inputs (SBUS/CRSF) < 10 ms latency.
- Generate motor PWM/DShot via GPT + DMA.
- Monitor CM85 heartbeat (watchdog).
- Execute POEG emergency motor kill and arming logic. OS: bare-metal or
  minimal RTOS.

### 3.2 CM85 tasks (examples)

- Attitude control: 1000 Hz (highest priority).
- EKF2 updates: 250–400 Hz.
- Navigation, logging, communication, AI inference (5–10 Hz).
- CPU load: idle 30–40%; hover 50–60%; AI active 70–85%; peak < 90%.

### 3.3 CM33 tasks (examples)

- RC decoding, DShot generation, watchdog, safety logic.
- CPU load: normal 10–15%; peak 20–25%.

---

## 4. PX4 module → RA8P1 peripheral mapping

> Note: Example pins are illustrative — verify final PCB pin assignments.

### 4.1 Peripheral mapping (summary)

| PX4 function | RA8P1 peripheral | Bus / pins (example) | Driver path | Notes |
|---|---|---|---|---|
| IMU1 (primary) | SPI0 (SPI0) | RSPCKA, MOSIA, MISOA, SSLA0 | arch/arm/src/ra8/ra_spi.c | BMI088 @ 10 MHz |
| IMU2 (secondary) | SPI1 (SPI1) | RSPCKB, MOSIB, MISOB, SSLB0 | arch/arm/src/ra8/ra_spi.c | ICM-42688-P @ 20 MHz, can use I3C if SPI1 is needed for another function |
| Baro1 | I2C0 | P408 (SCL) / P407 (SDA) | arch/arm/src/ra8/ra_i2c.c | BMP390 addr 0x76 |
| Baro2 | I2C1 | P512/P511 | arch/arm/src/ra8/ra_i2c.c | BMP390 addr 0x77 |
| Magnetometer | I2C2 | TBD | arch/arm/src/ra8/ra_i2c.c | BMM150 addr 0x10 |
| FRAM | I2C1 | P512 (SCL) / P511 (SDA) | arch/arm/src/ra8/ra_i2c.c | FM24W256 addr 0x50 |
| GPS1 | SCI4_C UART | P715(RX)/P714(TX) | arch/arm/src/ra8/ra_sci.c | /dev/ttyS1, u-blox |
| Console | SCI0_B UART | P602(RX)/P603(TX) | arch/arm/src/ra8/ra_sci.c | /dev/ttyS0 |
| SD Card | SDHI1 | SD0CLK, SD0CMD, SD0DAT0-3, SD0CD, SD0WP | arch/arm/src/ra8/ra_sdhi.c | native SDHI |
| Motor outputs | GPT timers | P912, P915, P903, P515 | arch/arm/src/ra8/ra_gpt.c | DShot/PWM |
| CAN | CANFD0/1 | P312/P311 / P909/P908 | arch/arm/src/ra8/ra_canfd.c | UAVCAN |
| Ethernet | ETH MAC | P307–P310, P906–P907 | arch/arm/src/ra8/ra_ether.c | 10/100 Mbps, TSN |
| USB HS | USBHS | P815/814 | arch/arm/src/ra8/ra_usbdev.c | USB 2.0 HS |
| MIPI-CSI2 | MIPI PHY | MIPI_CSI_CL / DL pins | arch/arm/src/ra8/ra_mipi_csi.c | 2-lane @ 500 Mbps |
| SDRAM | External bus | D0–D15, A0–A23, CS, RAS, CAS, WE | arch/arm/src/ra8/ra_sdram.c | MANDATORY |
| SCI_SPI ext port | SCI_X (TBD) | 4 pins: SCK/MOSI/MISO/CS | arch/arm/src/ra8/ra_sci_spi.c | optional IMU3 |
| I3C ext port | I3C0 | P400 (SCL) / P401 (SDA) | arch/arm/src/ra8/ra_i3c.c | high-speed extension |

**Key hardware facts**

- SPI: SPI0 and SPI1 only.
- I2C: I2C0, I2C1, I2C2.
- I3C: I3C0 present.

---

## 5. Sensor suite configuration (dual IMU)

### 5.1 Dual IMU setup

#### IMU specs

| IMU | Model | Interface | Rate | Accel | Gyro | Notes |
|---|---|---:|---:|---:|---:|---|
| IMU1 | BMI088 | SPI0 | 2 kHz | ±24 g | ±2000 °/s | Primary |
| IMU2 | ICM-42688-P | SPI1 | 8 kHz | ±16 g | ±2000 °/s | Secondary |

#### Physical isolation & thermal

- Separate power domains (LDO1, LDO2).
- Star grounding topology.
- Thermal stabilization: heating resistor keeps IMUs at 50°C ± 5°C.

#### Sensor voting (EKF2)

- PX4 reads both IMUs concurrently; EKF2 computes average + stddev.
- If one IMU deviates > 2σ for > 500 ms, it is voted out.
- If both IMUs fail, emergency land immediately.

#### Example PX4 parameters

```text
SENS_EN_BMI088 = 1
SENS_EN_ICM4268 = 1
COM_ARM_IMU_ACC = 0.5     # Max accel inconsistency for arming (m/s²)
COM_ARM_IMU_GYR = 0.2     # Max gyro inconsistency for arming (rad/s)
EKF2_IMU_POS_X  = 0.0
EKF2_IMU_POS_Y  = 0.0
EKF2_MULTI_IMU  = 2
```

### 5.2 Dual barometer setup

- BMP390 on I2C0 (0x76) and I2C1 (0x77), 100 Hz.
- EKF2 fuses baro readings; if divergence > 2 m for > 5 s, vote out.

### 5.3 Magnetometer & GPS

- Magnetometer: BMM150 on I2C2 (0x10), 100 Hz.
  IMPORTANT: uses I2C2.
- GPS: u-blox M8N/M9N on SCI4_C (UART), UBX binary protocol.

---

## 6. Extension ports & future expansion

### 6.1 SCI_SPI extension port

- Purpose: software SPI over an SCI channel for optional IMU3 or SPI sensors.
- Hardware: 4 pins — SCK, MOSI, MISO, CS. Connector: 2.54 mm or JST-GH.
- Max clock: ~10 MHz (software SPI, interrupt-driven).
- Supported devices: ICM-42670-P, BMI270, MS5611, PMW3901, VL53L1X.

Example (C):

```c
/* Initialize SCI3 as SPI */
struct spi_dev_s *ext_spi = ra8_sci_spi_initialize(3);
SPI_SETFREQUENCY(ext_spi, 10000000);  /* 10 MHz */
SPI_SETMODE(ext_spi, SPIDEV_MODE0);

#ifdef CONFIG_SENSORS_ICM42670P_EXT
  struct icm42670p_config_s config = {
    .spi = ext_spi,
    .spi_devid = 3,
  };
  icm42670p_register("/dev/imu2", &config);
#endif
```

### 6.2 I3C extension port

- Purpose: high-speed I3C bus (backward compatible with I2C).
- Pins: P400 (SCL), P401 (SDA). On-board pull-ups: 1 kΩ.
- Clocks: I2C up to 1 MHz; I3C SDR up to 12.5 MHz.
- Advantages: hot-join, in-band interrupts, dynamic addressing.

Example (C):

```c
/* Initialize I3C in I2C compatibility mode */
struct i2c_master_s *i3c = ra8_i3cbus_initialize(0);
i2c_setfrequency(i3c, 400000);  /* 400 kHz I2C mode */

#ifdef CONFIG_I3C_NATIVE
struct i3c_master_s *i3c_native = ra8_i3c_initialize(0);
i3c_setfrequency(i3c_native, 12500000);  /* 12.5 MHz I3C SDR mode */
#endif
```

### 6.3 Reserved UART channels

- GPS2: SCI9_B (secondary GPS) — reserved.
- TELEM3: SCI7_B (tertiary telemetry) — reserved.

PX4 example:

```bash
# Enable GPS2 in rcS
gps start -d /dev/ttyS5 -i 2 -p ubx

# Enable TELEM3
mavlink start -d /dev/ttyS6 -b 921600 -m onboard -r 100000
```

---

## 7. Inter-core communication protocol (IPC)

### 7.1 IPC architecture

- Method: shared memory mailbox + hardware interrupt signalling.
- Goals: latency < 1 ms RTT, throughput 400–1000 Hz for actuator updates.
- Reliability: CRC16 + sequence numbers.
- Failsafe: CM33 watchdog on CM85 heartbeat (< 100 ms timeout).
- Memory: 64 KB internal SRAM at `0x201A0000` for IPC.

### 7.2 IPC message specifications

| Message | Direction | Size | Rate (Hz) | Timeout | Purpose |
|---|---:|---:|---:|---:|---|
| actuator_cmd | CM85 → CM33 | 128 bytes | 400–1000 | 10 ms | Motor throttle, arm, kill |
| rc_input | CM33 → CM85 | 64 bytes | 50–100 | 100 ms | RC channel values |
| cm85_heartbeat | CM85 → CM33 | 32 bytes | 10 | 100 ms | CM85 health |
| cm33_heartbeat | CM33 → CM85 | 32 bytes | 10 | 200 ms | CM33 health |
| diagnostics | Bidirectional | 128 bytes | 1–10 | N/A | Error codes, CPU load |

Example struct (packed):

```c
typedef struct {
  uint32_t  sequence;
  uint64_t  timestamp_us;
  uint16_t  motor[8];
  uint16_t  servo[4];
  uint8_t   armed;
  uint8_t   emergency_kill;
  uint8_t   protocol;
  uint8_t   _reserved[9];
  uint16_t  crc16;
} __attribute__((packed)) ipc_actuator_cmd_t;
```

### 7.3 Failsafe logic

- CM33 watchdog monitors `cm85_heartbeat.sequence`; no update > 100 ms →
  POEG hardware kill, `emergency_kill = 1`.
- CM85 watchdog monitors CM33; no update > 200 ms → log error and enter
  emergency land.

---

## 8. Driver architecture & APIs

> Preserve code examples verbatim. Language hints provided.

### 8.1 SPI0 (hardware SPI) examples

```c
#include <nuttx/spi/spi.h>

/* Initialize SPI0 (IMU1: BMI088, pin suffix "A") */
struct spi_dev_s *spi0 = ra8_spibus_initialize(0);
SPI_SETFREQUENCY(spi0, 10000000);  /* 10 MHz for BMI088 */
SPI_SETMODE(spi0, SPIDEV_MODE3);

/* Initialize SPI1 (IMU2: ICM-42688-P, suffix "B") */
struct spi_dev_s *spi1 = ra8_spibus_initialize(1);
SPI_SETFREQUENCY(spi1, 24000000);  /* 24 MHz for ICM-42688-P */

/* DMA-accelerated transfer */
SPI_EXCHANGE(spi0, tx_buf, rx_buf, 64);
```

### 8.2 I2C examples

```c
#include <nuttx/i2c/i2c_master.h>

/* Initialize I2C0 (Baro1) - P408/P407 pins */
struct i2c_master_s *i2c0 = ra8_i2cbus_initialize(0);

/* Initialize I2C1 (Baro2, FRAM) - P512/P511 pins */
struct i2c_master_s *i2c1 = ra8_i2cbus_initialize(1);

/* Initialize I2C2 (Magnetometer) */
struct i2c_master_s *i2c2 = ra8_i2cbus_initialize(2);

/* Read BMM150 on I2C2 */
struct i2c_msg_s msg[2];
uint8_t reg = BMM150_REG_CHIPID;
uint8_t chipid;
msg[0] = { .addr = 0x10, .flags = 0, .buffer = &reg, .length = 1 };
msg[1] = { .addr = 0x10, .flags = I2C_M_READ, .buffer = &chipid, .length = 1 };
I2C_TRANSFER(i2c2, msg, 2);
```

### 8.3 I3C example

```c
#include <nuttx/i2c/i2c_master.h>

/* Initialize I3C in I2C compatibility mode */
struct i2c_master_s *i3c = ra8_i3cbus_initialize(0);
i2c_setfrequency(i3c, 400000);  /* 400 kHz I2C mode */

/* Or native I3C mode */
#ifdef CONFIG_I3C_NATIVE
struct i3c_master_s *i3c_native = ra8_i3c_initialize(0);
i3c_setfrequency(i3c_native, 12500000);  /* 12.5 MHz I3C SDR mode */
#endif
```

### 8.4 SDHI (SD card) driver

```c
#include <nuttx/sdio.h>

struct sdio_dev_s *sdio = sdio_initialize(0);  /* SDHI1 */
sdio_set_blocksize(sdio, 512);
sdio_set_frequency(sdio, 50000000);  /* 50 MHz */
```

### 8.5 FRAM (I2C) example

```c
/* FRAM via I2C1 addr 0x50 (P512/P511) - paired with Baro2 */
struct i2c_master_s *fram_i2c = ra8_i2cbus_initialize(1);

uint8_t write_data[34];  /* Address (2 bytes) + Data (32 bytes) */
write_data[0] = (addr >> 8) & 0xFF;
write_data[1] = addr & 0xFF;
memcpy(&write_data[2], data, 32);

struct i2c_msg_s msg = {
  .addr = 0x50,
  .flags = 0,
  .buffer = write_data,
  .length = 34
};
I2C_TRANSFER(fram_i2c, &msg, 1);
```

### 8.6 SDRAM example

```c
/* SDRAM initialized during boot, mapped at 0x68000000 */
#define SDRAM_BASE 0x68000000
#define SDRAM_SIZE (32 * 1024 * 1024)  /* 32 MB */

/* Direct memory access */
uint8_t *tensor_arena = (uint8_t *)(SDRAM_BASE + 0);
memset(tensor_arena, 0, 20 * 1024 * 1024);  /* Clear 20MB for AI */
```

---

## 9. Edge AI integration (Ethos-U55 NPU)

### 9.1 AI pipeline overview

Camera (30 fps) → Preprocessing (CPU) → Ethos-U55 NPU (100–200 ms)
→ uORB publish (5–10 Hz)

- Input: 224×224×3 RGB (INT8 quant).
- Model: MobileNetV2-SSD-like, 1.0–1.2 MB (INT8).
- Tensor arena: 20 MB in SDRAM (mandatory).

Example integration (TFLM + Ethos-U delegate):

```c
#include <tensorflow/lite/micro/micro_interpreter.h>
#include <ethos_u_delegate.h>

extern const uint8_t model_data[];
static uint8_t *tensor_arena = (uint8_t *)0x68000000;
static const size_t tensor_arena_size = 20 * 1024 * 1024;

int tflm_ethos_init(void) {
  const tflite::Model* model = tflite::GetModel(model_data);
  static tflite::MicroMutableOpResolver<10> resolver;
  resolver.AddConv2D();
  resolver.AddDepthwiseConv2D();

  auto delegate = ethos_u::CreateDelegate(ethos_u::GetDefaultDelegateOptions());
  static tflite::MicroInterpreter static_interpreter(
    model, resolver, tensor_arena, tensor_arena_size);
  interpreter = &static_interpreter;
  interpreter->ModifyGraphWithDelegate(delegate);
  interpreter->AllocateTensors();
  return 0;
}
```

### 9.2 Performance targets

| Metric | Target | Unit | Notes |
|---|---:|---:|---|
| Inference latency | 100–200 | ms | Ethos-U55 INT8 inference |
| Preprocessing | 10–20 | ms | CPU resize + normalize |
| End-to-end | 120–230 | ms | Frame capture → uORB publish |
| Update rate | 5–10 | Hz | Obstacle distance publish |

---

## 10. Memory partitioning & linker strategy

### 10.1 Physical memory map

| Region | Base | Size | Type | CM85 | CM33 | Purpose |
|---|---:|---:|---|:---:|:---:|---|
| CM85 ITCM | `0x00000000` | 128 KB | SRAM (0-wait) | ✓ | ✗ | Critical ISR code (CM85) |
| MRAM (flash) | `0x02000000` | 1 MB | NVRAM (XIP) | ✓ | ✓ | Bootloader, NuttX kernel, CM33 firmware |
| SiP Flash | `0x08000000` | 8 MB | NOR (XIP) | ✓ | ✓ | PX4 modules, configuration (not used on EK-RA8P1) |
| CM85 DTCM | `0x20000000` | 128 KB | SRAM (0-wait) | ✓ | ✗ | ISR data, stacks (CM85) |
| CM33 ITCM | `0x20100000` | 64 KB | SRAM (0-wait) | ✗ | ✓ | CM33 code (CM85 system view) |
| CM33 DTCM | `0x20110000` | 64 KB | SRAM (0-wait) | ✗ | ✓ | CM33 data, stacks (CM85 system view) |
| User SRAM | `0x22000000` | 1664 KB | SRAM (ECC) | ✓ | ✓ | Main heap, PX4 allocations |
| IPC Shared | `0x220E2000` | 32 KB | SRAM | ✓ | ✓ | Inter-core communication (within User SRAM) |
| Peripherals | `0x40000000` | ~512 MB | MMIO | ✓ | ✓ | Memory mapped I/O |

**Total SRAM:** 2048 KB = 256 KB (CM85 TCM) + 128 KB (CM33 TCM) + 1664 KB (User SRAM)

### 10.2 SRAM partitioning (summary)

User SRAM layout (1664 KB @ 0x22000000):
```
0x22000000: PX4 heap & data          — Dynamic allocations, message buffers, .data/.bss
0x220E2000: IPC shared memory (32 KB) — Inter-core communication buffers
0x220EA000: Reserved                  — Available for future expansion
```

CM85 TCM (256 KB):
```
0x00000000: ITCM (128 KB)  — Critical ISR code, high-speed execution
0x20000000: DTCM (128 KB)  — ISR data, sensor buffers, stacks
```

CM33 TCM (128 KB, CM85 system view):
```
0x20100000: CM33 ITCM (64 KB)  — CM33 firmware code
0x20110000: CM33 DTCM (64 KB)  — CM33 data, DShot buffers, stacks
```

### 10.3 Linker script excerpt (CM85 NuttX)

```ld
MEMORY {
  /* Internal Code MRAM - 1MB */
  flash (rx)   : ORIGIN = 0x02000000, LENGTH = 1M

  /* User SRAM - 1664KB total */
  sram (rwx)   : ORIGIN = 0x22000000, LENGTH = 1664K

  /* Tightly-Coupled Memory - CM85 (local view) */
  itcm (rwx)   : ORIGIN = 0x00000000, LENGTH = 128K
  dtcm (rwx)   : ORIGIN = 0x20000000, LENGTH = 128K

  /* Tightly-Coupled Memory - CM33 (CM85 system view for loading) */
  cm33_itcm (rwx) : ORIGIN = 0x20100000, LENGTH = 64K
  cm33_dtcm (rwx) : ORIGIN = 0x20110000, LENGTH = 64K

  /* IPC Shared Memory - 32KB within User SRAM */
  ipc_shmem (rw) : ORIGIN = 0x220E2000, LENGTH = 32K
}

SECTIONS {
  .text : { *(.vectors) *(.text*) *(.rodata*) } > flash
  .data : { *(.data*) } > sram AT > flash
  .bss : { *(.bss*) } > sram
  .ipc_shmem (NOLOAD) : { *(.ipc_shmem*) } > ipc_shmem
  .cm33_text : { KEEP(*(.cm33_vectors)) *(.cm33_text*) } > cm33_itcm AT > flash
  .cm33_data : { *(.cm33_data*) } > cm33_dtcm AT > flash
  .cm33_bss (NOLOAD) : { *(.cm33_bss*) } > cm33_dtcm
}
```

---

## 11. Boot sequence & secure boot

### 11.1 Boot flow

```
Power-On Reset
     ↓
Stage 0: ROM Bootloader
  • Verify NVRAM bootloader checksum (CRC32)
  • Optional: RSA/ECDSA signature verification
  • Load Stage 1 to SRAM
     ↓
Stage 1: NVRAM bootloader (32 KB)
  • Initialize clocks (1 GHz CM85, 250 MHz CM33)
  • Initialize SDRAM controller
  • Verify NuttX kernel SHA-256 + signature
  • Load NuttX and jump to entry
     ↓
Stage 2: NuttX kernel boot (CM85)
  • Initialize MPU, FPU, NVIC, HRT
  • Zero .bss, copy .data
  • Start CM33 (load CM33 firmware)
  • Mount filesystems
  • Start PX4 init script (/etc/init.d/rcS)
     ↓
Stage 3: PX4 initialization (rcS)
  • Load sensor drivers (IMU, baro, mag, GPS)
  • Start core modules (commander, ekf2)
  • Configure IPC with CM33
  • Start telemetry
  • Wait for arming command
     ↓
Stage 4: Ready for flight
```

**Boot time target:** < 5 seconds power-on to flight-ready.

### 11.2 Secure boot (signature verification example)

```c
#include <mbedtls/sha256.h>
#include <mbedtls/rsa.h>

int verify_firmware(const fw_header_t *hdr, const uint8_t *image, size_t len) {
  uint8_t computed_hash[32];
  mbedtls_sha256(image, len, computed_hash, 0);

  mbedtls_rsa_context rsa;
  mbedtls_rsa_init(&rsa, MBEDTLS_RSA_PKCS_V15, 0);

  if (mbedtls_rsa_pkcs1_verify(&rsa, NULL, NULL, MBEDTLS_RSA_PUBLIC,
                                MBEDTLS_MD_SHA256, 32, computed_hash,
                                hdr->signature) != 0) {
    return -1;
  }
  return 0;
}
```

---

## 12. Safety & failsafe design (dual IMU)

### 12.1 Hardware failsafes

- POEG (port output enable) for GPT: hardware shutdown of all GPT PWM
  outputs; reaction time < 1 μs. Triggered by CM33 on CM85 timeout.
- Independent watchdog (IWDT): resets CM85 if no refresh for 1–2 s.

### 12.2 Software failsafes

| Type | Trigger | Detection | Reaction | Time |
|---|---|---:|---|---|
| RC loss | No RC > 100 ms | RC timeout | Hold → RTL → land | < 200 ms |
| IMU failure | Self-test fail | Noisy / diverged data | Vote out IMU | < 500 ms |
| CM85 hang | Heartbeat timeout | No heartbeat | CM33 POEG kill | < 10 ms |
| Low battery | Voltage threshold | Battery ADC | RTL + land | < 5 s |

### 12.3 Pre-arm safety checks

- Both IMUs healthy and biases within limits.
- IMU readings consistent (accel diff < 0.5 m/s², gyro diff < 0.2 rad/s).
- At least one barometer valid.
- Magnetometer calibrated on I2C2.
- GPS lock when required.
- RC link valid for > 1 s.
- Battery voltage above minimum.
- CM33 heartbeat present.

---

## 13. Storage architecture (SDRAM, FRAM, SD card)

### 13.1 SDRAM configuration

- Hardware: IS42S32160F, 32–64 MB.
- Interface: 32-bit parallel bus @ 133 MHz.
- Usage: AI tensor arena (20 MB), video buffers (8 MB), parameter cache (2 MB).

### 13.2 FRAM configuration

- FM24W256-GTR, 32 KB, I2C1 @ 400 kHz, addr 0x50.
- Pins: P512 (SCL) / P511 (SDA) — shared with Baro2 on I2C1.
- **Rationale**: Paired with redundant Baro2 for fault isolation. If primary
  I2C0/Baro1 fails, FRAM remains accessible on secondary bus.
- Usage: PX4 params (16 KB), mission waypoints (12 KB), reserved (4 KB).

Example FRAM access:

```c
/* Write parameter */
fram_write_block(0x0000, param_data, 256);

/* Read parameter */
fram_read_block(0x0000, param_data, 256);
```

### 13.3 SD card configuration

- SDHI1 controller, 4-bit SD bus @ 50 MHz (SDR25).
- Capacity: up to 32 GB. Performance: ~25 MB/s read, ~15 MB/s write.
- Usage: ULog flight logs (~10 MB/hour), terrain maps, firmware updates.

---

## 14. Performance targets & measurements

### 14.1 Flight control timing

- Attitude control loop: 1000 Hz.
- Position control: 250 Hz.
- EKF2 update: 250–400 Hz.
- IMU sampling: IMU1 2 kHz, IMU2 8 kHz.

### 14.2 IPC performance

- Median RTT < 1.0 ms.
- 99th percentile RTT < 2.0 ms.
- Actuator update 400–1000 Hz.

### 14.3 CPU & memory

- CM85 load (idle): 30–40%.
- CM85 load (hover): 50–60%.
- CM85 load (AI active): 70–85%.
- CM33 load: 10–15% normal.
- RAM usage with AI: ~1500 KB.

---

## 15. Testing & validation strategy

### 15.1 Acceptance criteria (selected)

- Dual IMU sampling: 2–8 kHz. IMU voting detection < 500 ms.
- Magnetometer (I2C2): 100 Hz.
- I3C extension: SDR mode 12.5 MHz or I2C fallback 400 kHz.
- SDHI read speed: > 20 MB/s.
- AI latency per-frame: < 200 ms.

### 15.2 Test procedures (examples)

- Unit test dual IMU: read both, compare timestamps (< 1 ms apart).
- Integration test I3C: device detection, SDR @ 12.5 MHz.
- Flight test obstacle avoidance: obstacle at 5 m, verify detection and avoidance.

---

## 16. Build system integration

### 16.1 NuttX configuration (examples)

```bash
# I2C
CONFIG_RA8_I2C0=y  # Baro1 (P408/P407)
CONFIG_RA8_I2C1=y  # Baro2, FRAM (P512/P511)
CONFIG_RA8_I2C2=y  # Magnetometer

# I3C
CONFIG_RA8_I3C=y
CONFIG_I3C_SLAVE=y

# SPI
CONFIG_RA8_SPI0=y # IMU1
CONFIG_RA8_SPI1=y # IMU2

# SDRAM, SDHI
CONFIG_RA8_SDRAM=y
CONFIG_RA8_SDHI1=y
```

### 16.2 PX4 board configuration (excerpt)

File: `boards/renesas/evk-ra8p1j/src/board_config.h`

```c
/* Hardware SPI - IMUs */
#define BOARD_NUM_SPI_BUS     2
#define PX4_SPI_BUS_SENSORS   0   /* IMU1 on SPI0 */
#define PX4_SPI_BUS_SENSORS2  1   /* IMU2 on SPI1 */

/* I2C Configuration */
#define PX4_I2C_BUS_ONBOARD   0   /* I2C0: Baro1 (P408/P407) */
#define PX4_I2C_BUS_EXPANSION 1   /* I2C1: Baro2, FRAM (P512/P511) */
#define PX4_I2C_BUS_COMPASS   2   /* I2C2: Magnetometer */

/* I3C Expansion */
#define PX4_I3C_BUS_EXPANSION 0

/* IMU Configuration */
#define PX4_IMU1_BUS          PX4_SPI_BUS_SENSORS
#define PX4_IMU2_BUS          PX4_SPI_BUS_SENSORS2

/* Magnetometer */
#define PX4_MAG_BUS           PX4_I2C_BUS_COMPASS
#define PX4_MAG_ADDR          0x10
```

### 16.3 Build commands

```bash
# Build PX4 for FMU-RA8P1
cd PX4-Autopilot
make renesas_fmu-ra8p1_default

# Build CM33 firmware
cd cm33_firmware
make

# Flash via J-Link
JLinkExe -device R7JA8P1J -if SWD -speed 4000
> loadbin nuttx.bin 0x10000000
> r
> g
```

---

## 17. Companion computer interface

### 17.1 Communication options

| Interface | Bandwidth | Latency | Use case |
|---|---:|---:|---|
| Ethernet | 100 Mbps | < 10 ms | High-bandwidth telemetry, video, ROS 2 |
| CAN-FD | 5 Mbps | < 5 ms | Real-time control, UAVCAN |
| USB HS | 480 Mbps | < 1 ms | Firmware upload, logs |

### 17.2 Ethernet setup

PX4 configuration:

```text
MAV_2_MODE      = 2   # Ethernet (UDP)
MAV_2_REMOTE_IP = 192.168.1.10
MAV_2_UDP_PORT  = 14550
MAV_2_RATE      = 100000
```

Example ROS 2 setup:

```bash
# Run MicroXRCEDDS Agent
micro-xrce-dds-agent udp4 -p 8888
```

---

## 18. Pin mapping reference (PLBG0303)

### 18.1 Critical pin assignments (examples)

- SPI0 (IMU1): RSPCKA (SCK), MOSIA (MOSI), MISOA (MISO), SSLA0 (CS).
- SPI1 (IMU2): RSPCKB, MOSIB, MISOB, SSLB0.
- I2C0 (Baro1): P408 (SCL) / P407 (SDA) — using I2C0_B pins.
- I2C1 (Baro2, FRAM): P512 (SCL), P511 (SDA) — using I2C1_A pins.
- I2C2 (Mag): TBD — verify in final pinout.
- I3C0 (extension): P400 (SCL) / P401 (SDA) — **dedicated** for I3C use.
- SDHI1: SD0CLK, SD0CMD, SD0DAT0–3, SD0CD, SD0WP.
- SDRAM: D0–D15, A0–A23, CS, RAS, CAS, WE, CKE.

### 18.2 Pin conflict resolution

- **I3C0 vs I2C0 conflict (P400/P401) — RESOLVED:**
  - **Solution**: Move I2C0 (Baro1) to alternative pins **P408/P407** (I2C0_B).
  - P400/P401 now **dedicated to I3C0** for native I3C operation @ 12.5 MHz.
  - FRAM paired with **Baro2 on I2C1** (P512/P511) for fault isolation — if
    primary Baro1/I2C0 fails, FRAM remains accessible on redundant bus.
  - Pin P408/P407 verified from CSV: no conflict with active SCI/UART channels.

- UART allocation: SCI4_C (GPS1), SCI5_C (TELEM1), SCI6_A (TELEM2),
  SCI8_A (RC input), SCI9_B (GPS2 reserved), SCI7_B (TELEM3 reserved).

---

## 19. Open issues & TBD items

### 19.1 Hardware

- Finalize complete 303-pin PLBG mapping for all peripherals.
- Verify I2C2 routing for magnetometer.
- ✅ **RESOLVED**: I3C/I2C0 conflict — I2C0 moved to P408/P407, I3C0 dedicated
  to P400/P401.
- Decide extension port placement for J10 (SCI_SPI), J11 (I3C @ P400/P401).
- Confirm SDRAM selection (IS42S32160F or alternative).

### 19.2 Software

- Complete NuttX I3C driver implementation for RA8P1.
- Implement I3C-to-I2C fallback auto-switch.
- Tune EKF2 for dual IMU configuration.
- Complete SDRAM initialization in boot sequence.
- Finalize FRAM driver with wear leveling.

### 19.3 Testing

- Verify BMM150 on I2C2.
- Validate I3C SDR mode at 12.5 MHz.
- Benchmark SDHI performance.
- Single IMU flight test (stable flight with only one IMU).
- Profile AI latency and SDRAM access patterns.

---

## 20. Appendix: diagrams & code examples

### A. Architecture diagrams

- Final block diagram: dual IMU, I2C2 for mag, I3C extension.
- Memory partitioning diagram: SRAM (2 MB) + SDRAM allocation.
- I2C/I3C bus allocation: I2C0 (Baro1 @ P408/P407), I2C1 (Baro2/FRAM @
  P512/P511), I2C2 (Mag), I3C0 (extension @ P400/P401).
- SPI channel allocation: SPI0 (IMU1), SPI1 (IMU2), SCI_SPI (extension).

### B. Code examples (excerpts)

#### B.1 Dual IMU initialization

```c
/* Initialize BMI088 on SPI0 */
struct spi_dev_s *spi0 = ra8_spibus_initialize(0);
SPI_SETFREQUENCY(spi0, 10000000);
bmi088_init(spi0, GPIO_SPI0_CS0);

/* Initialize ICM-42688-P on SPI1 */
struct spi_dev_s *spi1 = ra8_spibus_initialize(1);
SPI_SETFREQUENCY(spi1, 24000000);
icm42688p_init(spi1, GPIO_SPI1_CS0);
```

#### B.2 I2C2 magnetometer driver

```c
struct i2c_master_s *mag_bus = ra8_i2cbus_initialize(2);  /* I2C2 */
bmm150_init(mag_bus, 0x10);
```

#### B.3 I3C extension setup

```c
/* I2C compatibility mode */
struct i2c_master_s *i3c = ra8_i3cbus_initialize(0);
i2c_setfrequency(i3c, 400000);
```

#### B.4 SDRAM tensor arena

```c
#define TENSOR_ARENA_BASE 0x68000000
#define TENSOR_ARENA_SIZE (20 * 1024 * 1024)

uint8_t *tensor_arena = (uint8_t *)TENSOR_ARENA_BASE;
memset(tensor_arena, 0, TENSOR_ARENA_SIZE);
```

#### B.5 FRAM parameter storage

```c
void save_params_to_fram(const px4_param_t *params, size_t count) {
  struct i2c_master_s *fram = ra8_i2cbus_initialize(0);

  for (size_t i = 0; i < count; i++) {
    uint16_t addr = i * sizeof(px4_param_t);
    fram_write(fram, 0x50, addr, &params[i], sizeof(px4_param_t));
  }
}
```

---

## Document summary

This software specification (v1.0) provides the verified architecture for
the R7JA8P1JSLSAJ PLBG0303 variant of the RA8P1-based delivery drone FMU.
Confirmed items:

- ✅ 303-pin PLBG package (17 mm × 17 mm × 1.4 mm)
- ✅ Only 2 hardware SPI channels (SPI0, SPI1)
- ✅ Only 3 I2C buses (I2C0, I2C1, I2C2)
- ✅ Magnetometer on I2C2
- ✅ I3C extension port available (I3C0 @ 12.5 MHz SDR)
- ✅ 8 MB internal flash (keys, config)
- ✅ 1 MB NVRAM (bootloader, Nutt Kernel)
- ✅ Dual IMU config: BMI088 (SPI0) + ICM-42688-P (SPI1)
- ✅ SDRAM mandatory (32–64 MB) for AI tensor arena
- ✅ Native SDHI controller for high-speed SD card logging
- ✅ FM24W256-GTR FRAM on I2C1 for mission-critical params
- ✅ Reserved UARTs: GPS2 (SCI9_B), TELEM3 (SCI7_B)

**Document Version:** 1.0
**Date:** 01-Jan-2026
**Status:** Ready for final PCB design, pin assignment verification,
software implementation, and system integration testing.

*Document end.*
