# Renesas RA8P1 FMU Hardware Specification
## R7JA8P1JSLSAJ (PLBG0303) Variant

**Document Version:** 1.0
**Issue Date:** January 2026
**Target MCU:** Renesas R7JA8P1JSLSAJ (303-pin PLBG package)
**Application:** Flight Management Unit (FMU)
**Flight Stack:** PX4 Autopilot v1.14+ on NuttX RTOS
**Classification:** Engineering Reference — Platform-Focused Hardware Design

---

## Document Control

| Revision | Date | Author | Changes |
|---|---:|---|---|
| 1.0 | 01-Jan-2026 | RA8P1 Integration Team | Initial specification for R7JA8P1JSLSAJ variant |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Core Processing and Memory Architecture](#3-core-processing-and-memory-architecture)
4. [Sensor Suite Configuration](#4-sensor-suite-configuration)
5. [Power Management System](#5-power-management-system)
6. [Pixhawk Autopilot Bus (PAB) Interface](#6-pixhawk-autopilot-bus-pab-interface)
7. [Advanced Interfaces](#7-advanced-interfaces)
8. [PCB Design Requirements](#8-pcb-design-requirements)
9. [Component Selection and BOM](#9-component-selection-and-bom)
10. [Pin Mapping Reference](#10-pin-mapping-reference)
11. [Manufacturing Requirements](#11-manufacturing-requirements)
12. [Compliance and Testing](#12-compliance-and-testing)
13. [Reference Documents](#13-reference-documents)
14. [Appendices](#14-appendices)

---

## 1. EXECUTIVE SUMMARY

### 1.1 Project Overview

This document specifies the complete hardware architecture for a delivery drone Flight Management Unit (FMU) based on the **Renesas RA8P1 R7JA8P1JSLSAJ** dual-core microcontroller. The system integrates PX4 Autopilot on NuttX RTOS with advanced edge AI capabilities for autonomous delivery operations.

### 1.2 Key Design Objectives

- **Dual-core architecture:** Cortex-M85 @ 1 GHz (flight control) + Cortex-M33 @ 250 MHz (I/O and safety)
- **Edge AI processing:** Ethos-U55 NPU (256 GOPS INT8) for onboard obstacle avoidance
- **Dual sensor redundancy:** 2× IMU (BMI088 + ICM-42688-P), 2× barometer (BMP390)
- **Expansion capability:** SCI_SPI extension port for optional third IMU, I3C extension for high-speed peripherals
- **High-performance communications:** Ethernet 100 Mbps / TSN, dual CAN-FD (5 Mbps), multiple UARTs, USB HS
- **Safety-critical design:** Hardware failsafes (POEG emergency kill < 10 ms), independent watchdog, sensor voting
- **Operating temperature range:** -40°C to +85°C (industrial grade)

### 1.3 R7JA8P1JSLSAJ Variant Characteristics

**Package:** 303-pin PLBG (17 mm × 17 mm × 1.4 mm)

**Key Features:**
- **8 MB SiP Flash** (on-chip code flash, no external OSPI flash required)
- **1 MB NVRAM** (bootloader + firmware storage)
- **2 MB internal SRAM** (ECC protected, shared between cores)
- **Native SDHI controller** for SD card high-speed logging
- **Mandatory external SDRAM** (32-64 MB) for AI tensor arena

**Available Peripherals:**
- **SPI channels:** 2 hardware SPI (SPI0, SPI1) + SCI_SPI extension
- **I2C buses:** I2C0, I2C1, I2C2
- **I3C:** Single I3C channel (I3C0) for high-speed peripheral extension
- **UART/SCI:** 9 channels (SCI0-SCI9)
- **CAN-FD:** 2 channels @ 5 Mbps
- **Ethernet:** 10/100 Mbps RMII (ET1 MAC) with TSN support
- **USB:** High Speed (480 Mbps)
- **PWM/GPT:** Up to 12 channels via GPT timers
- **ADC:** 12-bit, 24 channels

### 1.4 System Block Diagram


```text
┌─────────────────────────────────────────────────────────────────┐
│                R7JA8P1JSLSAJ FMU System Architecture            │
│             (2× Hardware SPI, I2C0/I2C1/I2C2, I3C)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐          ┌───────────────────────┐     │
│  │ Cortex-M85 @ 1GHz   │◄───IPC──►│ Cortex-M33 @ 250MHz   │     │
│  │ (Primary/FMU)       │ <1ms RTT │ (Secondary/IO)        │     │
│  │ • PX4 Autopilot     │          │ • RC Input Handler    │     │
│  │ • NuttX RTOS        │          │ • PWM/DShot Output    │     │
│  │ • Sensor Fusion     │          │ • Watchdog on CM85    │     │
│  │ • Navigation        │          │ • POEG Emergency Kill │     │
│  │ • Edge AI (NPU)     │          │ • Arming Logic        │     │
│  │ • Telemetry         │          │ • Safety Interlock    │     │
│  └─────────────────────┘          └───────────────────────┘     │
│           │                                  │                  │
│           └──────────┬───────────────────────┘                  │
│                      │                                          │
│   ┌──────────────────┴────────────┬──────────────┬──────────┐   │
│   │ Sensors (Dual IMU)            │ Memory       │ NPU      │   │
│   │ • IMU1: SPI0 (BMI088)        │ • SRAM: 2MB  │ Ethos     │   │
│   │ • IMU2: SPI1 (ICM-42688-P)   │ • SDRAM: 32MB│ U55       │   │
│   │ • Baro1: I2C0 (BMP390)        │ • NVRAM: 1MB │ 256 GOPS │   │
│   │ • Baro2: I2C1 (BMP390)        │ • Flash: 8MB │ INT8     │   │
│   │ • Mag: I2C2 (BMM150)          │ • FRAM: 32KB │          │   │
│   │ • GPS: UART                   │ • SD: SDHI   │          │   │
│   └───────────────────────────────┴──────────────┴──────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.5 Design Philosophy

**Pixhawk Ecosystem Compatibility:**
- Full compliance with Pixhawk Standards (DS-009, DS-010, DS-020 where applicable)
- Maintains interoperability with PX4-based systems
- Uses standard JST-GH connectors and pinouts
- Compatible with Pixhawk ecosystem accessories

**Advanced Robotics Enablement:**
- Leverages RA8P1's AI/ML capabilities via Ethos-U55 NPU (256 GOPS)
- Supports computer vision through MIPI-CSI2 camera interface
- Dual-core processing for real-time flight control and I/O management
- Enables advanced delivery drone applications beyond traditional flight control

**Key Differences from R7KA8P1KFLCAC Variant:**
- **No external OSPI flash required** (8 MB SiP flash integrated)
- **Native SDHI controller** for high-speed SD card logging
- **FRAM on I2C1** for mission-critical parameter storage
- **Dual IMU configuration** (BMI088 + ICM-42688-P) with optional SCI_SPI extension for third IMU
- **I3C extension port** for future high-speed sensors
- **Mandatory external SDRAM** (32-64 MB) for AI tensor arena

---

## 2. SYSTEM OVERVIEW

### 2.1 System Characteristics

| Attribute | Specification | Notes |
|---|---|---|
| **MCU** | R7JA8P1JSLSAJ | 303-pin PLBG package, 17 mm × 17 mm × 1.4 mm |
| **Primary core** | ARM Cortex-M85 @ 1 GHz | Helium SIMD, FPU, DSP extensions |
| **Secondary core** | ARM Cortex-M33 @ 250 MHz | TrustZone-M, FPU |
| **NPU** | ARM Ethos-U55 @ 250 MHz | 256 GOPS INT8 |
| **Internal SRAM** | 2,048 KB | ECC protected, shared between cores |
| **ITCM** | 128 KB (CM85 only) | Zero-wait instruction TCM |
| **DTCM** | 128 KB (CM85 only) | Zero-wait data TCM |
| **NVRAM** | 1 MB | Bootloader + firmware |
| **On-chip flash (SiP)** | 8 MB | XIP execute-in-place, ECC |
| **External SDRAM** | 32–64 MB (IS42S32160F) | MANDATORY for AI tensor arena |
| **FRAM** | 32 KB (FM24W256-GTR) | I2C interface, mission-critical params |
| **SD card** | Up to 32 GB (SDXC) | SDHI1 controller, high-speed logging |
| **SPI** | 2 hardware channels | SPI0, SPI1 |
| **I2C** | 3 channels | I2C0, I2C1, I2C2|
| **I3C** | 1 channel | I3C0, backward compatible with I2C |
| **UART/SCI** | 9 channels | SCI0-SCI9 |
| **CAN-FD** | 2 channels | Up to 5 Mbps |
| **Ethernet** | 10/100 Mbps | RMII interface, TSN support |
| **USB** | High Speed | 480 Mbps |
| **PWM/GPT** | 12 channels | GPT timers for motor control |
| **ADC** | 12-bit, 24 channels | Voltage/current monitoring |
| **Temp range** | -40°C to +85°C | Industrial grade |

### 2.2 Modular Architecture

The system implements a **two-board modular design**:

**Flight Management Unit (FMU):** Compact module (38.8mm × 31.8mm) containing:
- R7JA8P1JSLSAJ MCU
- Dual IMU sensors (BMI088 + ICM-42688-P)
- Dual barometer sensors (BMP390)
- Magnetometer (BMM150)
- External SDRAM (32-64 MB)
- FRAM (32 KB)
- Power management system
- PAB connectors (100-pin + 50-pin)

**Carrier Baseboard:** Standard-sized board (85mm × 55mm) providing:
- Pixhawk-standard JST-GH connectors
- Ethernet interface (RJ45 with magnetics)
- USB Type-C interface
- CAN-FD transceivers
- MIPI-CSI2 camera interface
- SD card slot (SDHI1)
- Power distribution and monitoring
- Advanced robotics connectivity

---

## 3. CORE PROCESSING AND MEMORY ARCHITECTURE

### 3.1 Primary Microcontroller

**Part Number:** Renesas R7JA8P1JSLSAJ
**Package:** 303-pin PLBG (17mm × 17mm × 1.4mm, 0.5mm pitch)

**Critical Requirements:**
- Dual-core operation: Cortex-M85 @ 1GHz + Cortex-M33 @ 250MHz
- All power domains properly sequenced and decoupled
- Core voltage: 1.2V ±3% (500mA maximum)
- I/O voltage: 3.3V ±5% (300mA maximum)
- Junction temperature limit: 125°C (derate from 85°C ambient)

**Pin Assignment Constraints:**
- Refer to Section 10 for complete pin mapping
- Critical peripherals must use pins with dedicated hardware support
- MIPI-CSI2 differential pairs require impedance-controlled routing
- All unused pins configured per datasheet recommendations

### 3.2 Memory Subsystem

#### 3.2.1 On-Chip Memory

| Memory | Base Address | Size | Speed | ECC | Purpose |
|---|---:|---:|---:|---:|---|
| **ITCM** | 0x0000 | 128 KB | 1-cycle | No | Critical ISR code, DSHOT (CM85) |
| **DTCM** | 0x20000 | 128 KB | 1-cycle | No | ISR data, stacks (CM85) |
| **SRAM** | 0x20020000 | 2048 KB | 1-cycle | Yes | Main heap, message buffers |
| **NVRAM** | 0x00020000 | 1 MB | ~10 cycles | Yes | Bootloader, keys, NuttX kernel |
| **SiP Flash** | 0x080000 - 0x087FFFF | 8 MB | ~5 cycles | Yes | PX4 modules, AI models, config |

#### 3.2.2 External Memory (MANDATORY)

**SDRAM Configuration:**
- **Part:** ISSI IS42S32160F-6BLI or equivalent
- **Capacity:** 32–64 MB (512Mbit minimum)
- **Interface:** 32-bit SDRAM controller @ 133 MHz
- **Package:** 54-pin TSOP-II
- **Voltage:** 3.3V ±5%
- **Base Address:** 0x680000
- **Purpose:** AI tensor arena (20 MB), video buffers (8 MB), parameter cache (2 MB)

**Design Requirements:**
- Trace length matching: ±0.5mm for SDRAM address/data groups
- Impedance: 50Ω ±10% single-ended for high-speed signals
- Decoupling: 100nF + 10µF per power pin, placed <5mm from IC
- Series termination resistors on SDRAM address lines (22-33Ω)

**FRAM Configuration:**
- **Part:** FM24W256-GTR (Cypress/Infineon)
- **Capacity:** 32 KB (256 Kbit)
- **Interface:** I2C1 @ 400 kHz, address 0x50
- **Pins:** P512 (SCL) / P511 (SDA) — shared with Baro2 on I2C1
- **Voltage:** 3.3V ±5%
- **Purpose:** PX4 params (16 KB), mission waypoints (12 KB), reserved (4 KB)
- **Rationale:** Paired with redundant Baro2 for fault isolation. If primary I2C0/Baro1 fails, FRAM remains accessible on secondary bus.

**SD Card Configuration:**
- **Interface:** SDHI1 controller (SDHI1_A pin group), 4-bit SD bus @ 50 MHz (SDR25)
- **Capacity:** Up to 32 GB (SDXC)
- **Performance:** ~25 MB/s read, ~15 MB/s write
- **Purpose:** ULog flight logs (~10 MB/hour), terrain maps, firmware updates
- **Connector:** Push-push microSD card slot with card detect

**SDHI1_A Pin Mapping (4-bit mode):**
- **SD1CLK:** P203 (clock)
- **SD1CMD:** P202 (command)
- **SD1DAT0:** P402 (data bit 0)
- **SD1DAT1:** P314 (data bit 1)
- **SD1DAT2:** P810 (data bit 2)
- **SD1DAT3:** P811 (data bit 3)
- **SD1CD:** P205 (card detect)
- **SD1WP:** P204 (write protect)

**Pin Conflict Resolution:**
- **SDHI1_A selected over SDHI0** to avoid conflicts with mandatory SDRAM pins
- **SPI0 relocated:** P203/P202 shared with SDHI1 CLK/CMD, so SPI0 uses alternative pin group (RSPI0_B or RSPI0_C)
- **No SDRAM conflicts:** SDHI1_A pins do not overlap with fixed SDRAM wiring
- **Rationale:** SDHI1_A provides clean 4-bit SD card interface without compromising SDRAM, SPI1, I2C, or other mandatory peripherals

#### 3.2.3 Memory Partitioning

**SRAM Partitioning (2048 KB total):**
```
0x20020000: CM85 heap (832 KB)     — PX4 dynamic allocations, message buffers
0x200E0000: CM33 memory (768 KB)   — CM33 firmware, DShot buffers, stacks
0x201A0000: IPC shared memory (64 KB) — Inter-core communication
0x201B0000: Reserved (384 KB)      — DMA buffers, future expansion
```

**SDRAM Partitioning (32-64 MB):**
```
0x680000: AI tensor arena (20 MB)    — TensorFlow Lite Micro workspace
0x6940000: Video buffers (8 MB)       — Camera frame buffers
0x69C0000: Parameter cache (2 MB)     — Cached PX4 parameters
0x69E0000: Reserved (2-34 MB)         — Models, datasets, expansion
```

**SiP Flash Partitioning (8 MB):**
```
0x080000: Bootloader (128 KB)        — Secure boot, signature verification
0x08020000: NuttX kernel (1.5 MB)      — Operating system
0x081A0000: PX4 modules (4 MB)         — Flight control stack
0x085A0000: AI models (1.5 MB)         — MobileNetV2-SSD INT8
0x0870000: Configuration (512 KB)     — Default params, calibration
0x08780000: Reserved (512 KB)          — Future expansion
```

### 3.3 Dual-Core Task Partitioning

#### 3.3.1 Cortex-M85 (CM85) — Primary FMU

**Responsibilities:**
- Execute PX4 flight control stack (attitude, position, navigation)
- Sensor drivers and data fusion (EKF2)
- Communication (MAVLink, RTPS/DDS)
- Edge AI inference with Ethos-U55 using SDRAM tensor arena
- SD logging via SDHI1
- Operating System: NuttX RTOS

**Task Examples:**
- Attitude control: 1000 Hz (highest priority)
- EKF2 updates: 250–400 Hz
- Navigation, logging, communication: 10-50 Hz
- AI inference: 5–10 Hz

**CPU Load:**
- Idle: 30–40%
- Hover: 50–60%
- AI active: 70–85%
- Peak: < 90%

#### 3.3.2 Cortex-M33 (CM33) — Secondary I/O Processor

**Responsibilities:**
- Decode RC inputs (SBUS/CRSF) < 10 ms latency
- Generate motor PWM/DShot via GPT + DMA
- Monitor CM85 heartbeat (watchdog)
- Execute POEG emergency motor kill
- Arming logic and safety interlock
- Operating System: Bare-metal or minimal RTOS

**Task Examples:**
- RC decoding: 50-100 Hz
- DShot generation: 400-1000 Hz
- Watchdog monitoring: 10 Hz
- Safety logic: 10 Hz

**CPU Load:**
- Normal: 10–15%
- Peak: 20–25%

#### 3.3.3 Inter-Core Communication (IPC)

**Architecture:**
- Method: Shared memory mailbox + hardware interrupt signalling
- Latency: < 1 ms RTT
- Throughput: 400–1000 Hz for actuator updates
- Reliability: CRC16 + sequence numbers
- Failsafe: CM33 watchdog on CM85 heartbeat (< 100 ms timeout)
- Memory: 64 KB internal SRAM at 0x201A0000

**Key Messages:**
- `actuator_cmd` (CM85 → CM33): Motor throttle, arm, kill — 400-1000 Hz
- `rc_input` (CM33 → CM85): RC channel values — 50-100 Hz
- `cm85_heartbeat` (CM85 → CM33): CM85 health — 10 Hz
- `cm33_heartbeat` (CM33 → CM85): CM33 health — 10 Hz
- `diagnostics` (Bidirectional): Error codes, CPU load — 1-10 Hz

---

## 4. SENSOR SUITE CONFIGURATION

### 4.1 Dual IMU Configuration

The R7JA8P1JSLSAJ variant implements a **dual IMU configuration** for sensor redundancy, with an optional SCI_SPI extension port for a third IMU.

#### 4.1.1 Primary IMU Configuration

| IMU # | Part Number | Interface | Bus | Power Domain | Sampling Rate | Notes |
|---|---|---|---|---|---|---|
| **IMU1** | Bosch BMI088 | SPI | SPI0 (RSPI0_A) | LDO1 (3.3V) | 2 kHz | Primary, high accuracy |
| **IMU2** | TDK ICM-42688-P | SPI | SPI1 (RSPI1_A) | LDO2 (3.3V) | 8 kHz | Secondary, high-rate backup |

**RA8P1 SPI Pin Assignments:**

| Bus | SCK Pin | MOSI Pin | MISO Pin | CS Pin | Notes |
|---|---|---|---|---|---|
| **SPI0 (RSPI0_C)** | P609 (RSPCKA_C) | P608 (MOSIA_C) | P607 (MISOA_C) | P610 (SSLA0_C) | IMU1 - Hardware SPI (relocated from RSPI0_A due to SDHI1 conflict) |
| **SPI1 (RSPI1_A)** | P102 (RSPCKB_A) | P101 (MOSIB_A) | P100 (MISOB_A) | P103 (SSLB0_A) | IMU2 - Hardware SPI |

**Note:** SPI0 uses RSPI0_C pin group instead of RSPI0_A because P203/P202 (RSPI0_A SCK/MOSI) are allocated to SDHI1 CLK/CMD for SD card interface.

**Critical Design Requirements:**
- Each IMU on dedicated SPI bus (no bus sharing)
- Independent LDO power supply per sensor
- Separate analog and digital grounds with single-point connection
- Vibration isolation: Mechanically isolated sensor board or soft-mount
- Thermal management: Heating resistor (0.5W max) with temperature sensor per IMU
- Target operating temperature: 50°C ±5°C for optimal performance

**SPI Interface Specifications:**
- Clock frequency: Up to 10MHz for BMI088, 24MHz for ICM-42688-P
- Mode: SPI Mode 3 (CPOL=1, CPHA=1)
- Chip select: Active low, independent per sensor
- Pull-ups: 10kΩ on all CS lines when inactive

**Physical Isolation & Thermal:**
- Separate power domains (LDO1, LDO2)
- Star grounding topology
- Thermal stabilization: heating resistor keeps IMUs at 50°C ± 5°C

**Sensor Voting (EKF2):**
- PX4 reads both IMUs concurrently; EKF2 computes average + stddev
- If one IMU deviates > 2σ for > 500 ms, it is voted out
- If both IMUs fail, emergency land immediately

**Example PX4 Parameters:**
```text
SENS_EN_BMI088 = 1
SENS_EN_ICM4268 = 1
COM_ARM_IMU_ACC = 0.5     # Max accel inconsistency for arming (m/s²)
COM_ARM_IMU_GYR = 0.2     # Max gyro inconsistency for arming (rad/s)
EKF2_IMU_POS_X  = 0.0
EKF2_IMU_POS_Y  = 0.0
EKF2_MULTI_IMU  = 2
```

#### 4.1.2 Optional Third IMU (SCI_SPI Extension Port)

**Purpose:** Software SPI over an SCI channel for optional IMU3 or SPI sensors

**Hardware:**
- 4 pins: SCK, MOSI, MISO, CS
- Connector: 2.54 mm header or JST-GH 4-pin
- Max clock: ~10 MHz (software SPI, interrupt-driven)
- Suggested SCI channel: SCI3_A or SCI5_C

**Supported Devices:**
- ICM-42670-P (TDK 6-axis IMU)
- BMI270 (Bosch 6-axis IMU)
- MS5611 (Barometer)
- PMW3901 (Optical flow sensor)
- VL53L1X (ToF distance sensor)

**Pin Assignment Example (SCI3_A):**
- SCK: P410 (SCK3_A)
- MOSI: P409 (TXD3_A)
- MISO: P408 (RXD3_A)
- CS: P411 (GPIO)

### 4.2 Dual Barometer Configuration

| Sensor | Part Number | Interface | Bus | Power Domain | Resolution | I2C Address |
|---|---|---|---|---|---|---|
| **BARO1** | Bosch BMP390 | I2C | I2C0 (P408/P407) | LDO3 (3.3V) | 0.08 Pa | 0x76 |
| **BARO2** | Bosch BMP390 | I2C | I2C1 (P512/P511) | LDO4 (3.3V) | 0.08 Pa | 0x77 |

**Note:** BMP390 replaces BMP388 from original specification for improved accuracy and lower power consumption.

**I2C Interface Requirements:**
- Pull-up resistors: 4.7kΩ to 3.3V on SCL and SDA
- Operating frequency: 400kHz (Fast Mode)
- ESD protection on all I2C lines

**Sensor Voting:**
- EKF2 fuses baro readings; if divergence > 2 m for > 5 s, vote out faulty sensor

### 4.3 Magnetometer

**Part:** Bosch BMM150
**Interface:** I2C2
**Pins:** P801 (SDA2_A) and P802 (SCL2_A)
**Power Domain:** LDO5 (3.3V)
**Resolution:** 0.3µT
**I2C Address:** 0x10
**Sampling Rate:** 100 Hz

**Placement Requirements:**
- Mount away from current-carrying traces and power components
- Minimum 20mm clearance from high-current paths
- Avoid placement under or near switching regulators

### 4.4 GPS

**Part:** u-blox M8N/M9N
**Interface:** UART (SCI4_C)
**Pins:** P715 (RX) / P714 (TX)
**Protocol:** UBX binary protocol
**Baud Rate:** 115200 (default), up to 921600
**Update Rate:** 10 Hz (default), up to 18 Hz

### 4.5 Camera (Optional)

**Interface:** MIPI-CSI2
**Resolution:** 1080p @ 30 fps
**Lanes:** 2-lane MIPI CSI-2 @ 500 Mbps/lane
**Compatible Cameras:**
- Arducam OV5640 (5MP)
- Sony IMX219
- Raspberry Pi Camera Module v2

---

## 5. POWER MANAGEMENT SYSTEM

### 5.1 Primary Power Architecture

**Input Specifications:**
- Voltage range: 4.5V to 5.5V DC
- Input current: 2A maximum continuous
- Source: PAB connector (pins 1-2 of 50-pin connector)
- Protection: Reverse polarity, overcurrent, overvoltage

**Primary Buck Converter:**
- Part: Renesas ISL80103IRAJZ or equivalent
- Input: 5V ±10%
- Outputs: 3.3V @ 2A, 1.2V @ 500mA
- Efficiency: >90% at nominal load
- Switching frequency: 1-2MHz (minimize EMI)
- Inductor: 2.2µH, DCR <50mΩ, saturation current >3A
- Output capacitors: Low-ESR ceramic (X5R/X7R), 22µF minimum per rail

### 5.2 Sensor Power Isolation (Critical Requirement)

**LDO Specifications:**

Each sensor group requires an independent LDO regulator:

| LDO | Part Number | Input | Output | Current | Purpose |
|---|---|---|---|---|---|
| **LDO1** | ISL80510IRAJZ | 3.3V | 3.3V | 150mA | IMU1 power |
| **LDO2** | ISL80510IRAJZ | 3.3V | 3.3V | 150mA | IMU2 power |
| **LDO3** | ISL80510IRAJZ | 3.3V | 3.3V | 100mA | BARO1 power |
| **LDO4** | ISL80510IRAJZ | 3.3V | 3.3V | 100mA | BARO2 power |
| **LDO5** | ISL80510IRAJZ | 3.3V | 3.3V | 100mA | MAG power |

**Isolation Requirements:**
- Each LDO output isolated with 10µH inductor (ferrite bead)
- Separate power plane islands for each sensor
- Single-point ground connection per sensor domain
- MCU controls enable pins for individual sensor power control

### 5.3 Decoupling Strategy

**MCU Power Pins:**
- Core (1.2V): 10µF + 100nF per power pin
- I/O (3.3V): 10µF + 100nF per power pin
- Analog (3.3V): 10µF + 100nF + 10nF per analog power pin

**Memory Devices:**
- SDRAM: 22µF + 100nF on VDD, VDDQ
- FRAM: 10µF + 100nF on VCC

**Sensors:**
- Each sensor: 4.7µF + 100nF on VDD

**Placement Rules:**
- 100nF capacitors within 5mm of power pins
- 10µF capacitors within 15mm of power pins
- Use 0402 or 0603 package sizes for minimal ESL

### 5.4 Power Rails Generation (Carrier Board)

| Rail | Voltage | Current | Regulator Type | Purpose |
|---|---|---|---|---|
| **5V_MAIN** | 5.0V ±2% | 3A | Buck converter | Servo power, peripherals |
| **5V_PERIPH** | 5.0V ±2% | 2A | Buck or load switch | Switchable peripheral power |
| **3.3V_MAIN** | 3.3V ±2% | 2A | Buck converter | Logic power, sensors |
| **3.3V_BACKUP** | 3.3V ±3% | 500mA | LDO | RTC, critical systems |
| **1.8V** | 1.8V ±3% | 500mA | LDO | Camera, special peripherals |
| **1.2V** | 1.2V ±3% | 300mA | LDO | MIPI interface |

---

## 6. PIXHAWK AUTOPILOT BUS (PAB) INTERFACE

### 6.1 Connector Specifications

**Main Connector (J1):** Hirose DF40C-100DP-0.4V(51) or equivalent
- 100 pins, dual-row, 0.4mm pitch
- Mating height: 2.0mm
- Current rating: 0.3A per contact

**Secondary Connector (J2):** Hirose DF40C-50DP-0.4V(51) or equivalent
- 50 pins, dual-row, 0.4mm pitch
- Mating height: 2.0mm
- Current rating: 0.3A per contact

### 6.2 Critical Signal Routing Requirements

**Differential Pairs (Ethernet, MIPI-CSI2):**
- Impedance: 100Ω ±5% differential
- Length matching: ±0.1mm within pair, ±0.2mm between pairs
- Minimum pair-to-pair clearance: 3× trace width
- Reference plane: Solid ground, no splits under differential traces
- Via count: Minimize (maximum 2 per trace for MIPI, 4 for Ethernet)

**High-Speed Single-Ended (SPI, I2C up to 1MHz):**
- Impedance: 50Ω ±10%
- Trace width: Calculate for 4-layer stackup
- Maximum stub length: 5mm
- Termination: Series resistors as needed (22-33Ω typical)

**Power Distribution:**
- 5V power delivery: 0.5mm minimum trace width (1A capability)
- 3.3V power delivery: 0.3mm minimum trace width (500mA capability)
- Voltage drop budget: <100mV at maximum current
- Current sense resistors: 0.010Ω, 1%, 1W minimum

### 6.3 100-Pin Main Connector (J1) Pinout

> **R7JA8P1JSLSAJ Compatibility Note:** Pin assignments are optimized for the 303-pin PLBG package. Key changes from R7KA8P1KFLCAC variant:
> - No OSPI pins (8 MB SiP flash integrated)
> - FRAM on I2C1 (P512/P511)
> - I2C2 for magnetometer
> - Native SDHI pins for SD card
> - I3C0 extension on P400/P401

| Pin | Signal Name | RA8P1 Pin | Alt Functions | Voltage | Notes |
|---|---|---|---|---|---|
| 1 | FMU_VDD_3V3 | - | Power Output | 3.3V | 500mA max |
| 2 | FMU_VDD_3V3 | - | Power Output | 3.3V | 500mA max |
| 3 | FMU_VDD_5V | - | Power Output | 5.0V | 1A max |
| 4 | FMU_VDD_5V | - | Power Output | 5.0V | 1A max |
| 5 | TELEM1_TX | P615 | TXD7_A/SDA7_A/MOSI7_A | 3.3V | TELEM1 TX (SCI7_A) |
| 6 | TELEM1_RX | P614 | RXD7_A/SCL7_A/MISO7_A | 3.3V | TELEM1 RX (SCI7_A) |
| 7 | TELEM1_CTS | P613 | CTS0_C/GTIOC9B | 3.3V | Flow control |
| 8 | TELEM1_RTS | P612 | CTS_RTS0_C/GTIOC9A | 3.3V | Flow control |
| 9 | TELEM2_TX | P603 | TXD0_B/SDA0_B/MOSI0_B | 3.3V | TELEM2 TX (SCI0_B) |
| 10 | TELEM2_RX | P602 | RXD0_B/SCL0_B/MISO0_B | 3.3V | TELEM2 RX (SCI0_B) |
| 11 | TELEM2_CTS | P605 | CTS0_B/GTIOC8A | 3.3V | Flow control |
| 12 | TELEM2_RTS | P604 | CTS_RTS0_B/GTIOC8B | 3.3V | Flow control |
| 13 | TELEM3_TX | P714 | TXD4_C/SDA4_C/MOSI4_C | 3.3V | TELEM3 TX (SCI4_C) |
| 14 | TELEM3_RX | P715 | RXD4_C/SCL4_C/MISO4_C | 3.3V | TELEM3 RX (SCI4_C) |
| 15 | TELEM3_CTS | P713 | CTS4_C/GTIOC2A | 3.3V | Flow control |
| 16 | TELEM3_RTS | P712 | CTS_RTS4_C/GTIOC2B | 3.3V | Flow control |
| 17 | GPS1_TX | PA03 | TXD2_C/SDA2_C/MOSI2_C | 3.3V | GPS1 TX (SCI2_C) |
| 18 | GPS1_RX | PA02 | RXD2_C/SCL2_C/MISO2_C | 3.3V | GPS1 RX (SCI2_C) |
| 19 | GPS2_TX | P209 | TXD9_B/SDA9_B/MOSI9_B | 3.3V | GPS2 TX (SCI9_B) |
| 20 | GPS2_RX | P208 | RXD9_B/SCL9_B/MISO9_B | 3.3V | GPS2 RX (SCI9_B) |
| 21 | I2C1_SCL | P512 | SCL1_A/CTS8_A/GTIOC0A | 3.3V | I2C1 SCL (Baro2, FRAM) |
| 22 | I2C1_SDA | P511 | SDA1_A/CTS_RTS6_A/GTIOC0B | 3.3V | I2C1 SDA (Baro2, FRAM) |
| 23 | I2C2_SCL | P801 | SDA2_A | 3.3V | I2C2 SCL (Magnetometer) |
| 24 | I2C2_SDA | P802 | SCL2_A | 3.3V | I2C2 SDA (Magnetometer) |
| 25 | I3C0_SCL | P400 | I3C_SCL0/TXD1_A/GTIOC6A | 3.3V | I3C extension SCL |
| 26 | I3C0_SDA | P401 | I3C_SDA0/RXD1_A/GTIOC6B | 3.3V | I3C extension SDA |
| 27 | SPI0_SCK | P609 | RSPCKA_C/TXD0_C/SDA0_C | 3.3V | IMU1 HW SPI Clock (RSPI0_C) |
| 28 | SPI0_MOSI | P608 | MOSIA_C/RXD0_C/SCL0_C | 3.3V | IMU1 HW SPI MOSI (RSPI0_C) |
| 29 | SPI0_MISO | P607 | MISOA_C/CTS_RTS0_C | 3.3V | IMU1 HW SPI MISO (RSPI0_C) |
| 30 | SPI0_CS0 | P610 | SSLA0_C/CTS0_C | 3.3V | IMU1 HW SPI CS (RSPI0_C) |
| 31 | SPI1_SCK | P102 | RSPCKB_A | 3.3V | IMU2 HW SPI Clock |
| 32 | SPI1_MOSI | P101 | MOSIB_A | 3.3V | IMU2 HW SPI MOSI |
| 33 | SPI1_MISO | P100 | MISOB_A | 3.3V | IMU2 HW SPI MISO |
| 34 | SPI1_CS0 | P103 | SSLB0_A | 3.3V | IMU2 HW SPI CS |
| 35 | SDHI1_CLK | P203 | SD1CLK/RSPCKA_A | 3.3V | SD card clock (SDHI1_A) |
| 36 | SDHI1_CMD | P202 | SD1CMD/MOSIA_A | 3.3V | SD card command (SDHI1_A) |
| 37 | SDHI1_DAT0 | P402 | SD1DAT0/SCK1_A | 3.3V | SD card data 0 (SDHI1_A) |
| 38 | SDHI1_DAT1 | P314 | SD1DAT1/GTIOC4A | 3.3V | SD card data 1 (SDHI1_A) |
| 39 | SDHI1_DAT2 | P810 | SD1DAT2/GTIOC10A | 3.3V | SD card data 2 (SDHI1_A) |
| 40 | SDHI1_DAT3 | P811 | SD1DAT3/GTIOC10B | 3.3V | SD card data 3 (SDHI1_A) |
| 41 | SDHI1_CD | P205 | SD1CD/GTIOC4A | 3.3V | SD card detect (SDHI1_A) |
| 42 | SDHI1_WP | P204 | SD1WP/SSLA0_A | 3.3V | SD card write protect (SDHI1_A) |
| 43 | CAN1_TX | P312 | CTX0/ET1_RX_ER/IRQ22-DS | 3.3V | CAN-FD0 TX |
| 44 | CAN1_RX | P311 | CRX0/ET1_TX_CLK/IRQ23-DS | 3.3V | CAN-FD0 RX |
| 45 | CAN2_TX | P909 | CTX1/ET1_RXD3/GTIOC12A | 3.3V | CAN-FD1 TX |
| 46 | CAN2_RX | P908 | CRX1/ET1_RXD2/GTIOC12B | 3.3V | CAN-FD1 RX |
| 47 | ETH_MDC | P415 | ET1_MDC/TXD4_B/GTIOC0A | 3.3V | Ethernet MDC |
| 48 | ETH_MDIO | P414 | ET1_MDIO/SCL3_A | 3.3V | Ethernet MDIO |
| 49 | ETH_TXD0 | P307 | ET1_TXD0/RGMII1_TXD0/RMII1_TXD0 | 3.3V | Ethernet TX Data 0 |
| 50 | ETH_TXD1 | P306 | ET1_TXD1/RGMII1_TXD1/RMII1_TXD1 | 3.3V | Ethernet TX Data 1 |
| 51 | ETH_TXEN | P310 | ET1_TX_EN/RGMII1_TX_CTL/RMII1_TX_EN | 3.3V | Ethernet TX Enable |
| 52 | ETH_RXD0 | P906 | ET1_RXD0/RGMII1_RXD0/RMII1_RXD0 | 3.3V | Ethernet RX Data 0 |
| 53 | ETH_RXD1 | P907 | ET1_RXD1/RGMII1_RXD1/RMII1_RXD1 | 3.3V | Ethernet RX Data 1 |
| 54 | ETH_RXDV | P206 | ET1_RX_DV/RGMII1_RX_CTL/RMII1_CRS_DV | 3.3V | Ethernet RX Data Valid |
| 55 | ETH_RSTN | P708 | GPIO/ET0_MDC/AUDIO_CLK | 3.3V | Ethernet PHY Reset |
| 56 | ETH_REFCLK | P905 | ET1_RX_CLK/RGMII1_RXC/RMII1_REF50CK | 3.3V | 50MHz reference |
| 57 | PWM_OUT1 | P912 | GTIOC3A/ET1_TXD6/IRQ5 | 3.3V | GPT3A |
| 58 | PWM_OUT2 | P915 | GTIOC5A/CTS6_B/IRQ8 | 3.3V | GPT5A |
| 59 | PWM_OUT3 | P903 | GTIOC11A/IRQ1 | 3.3V | GPT11A |
| 60 | PWM_OUT4 | P515 | GTIOC13A/SCL2_B/ET_TAS_STA0 | 3.3V | GPT13A |
| 61 | PWM_OUT5 | P911 | GTIOC3B/ET1_TXD5/IRQ6 | 3.3V | GPT3B |
| 62 | PWM_OUT6 | P914 | GTIOC5B/CTS_RTS6_B/IRQ9 | 3.3V | GPT5B |
| 63 | PWM_OUT7 | P904 | GTIOC11B/ET1_RXD4/IRQ2 | 3.3V | GPT11B |
| 64 | PWM_OUT8 | P514 | GTIOC13B/SCK4_C/SDA2_B | 3.3V | GPT13B |
| 65 | PWM_OUT9 | PB06 | GTIOC9A/CTS_RTS5_C/ET0_TXD6 | 3.3V | GPT9A |
| 66 | PWM_OUT10 | PB07 | GTIOC9B/ET0_TXD5/IRQ1 | 3.3V | GPT9B |
| 67 | PWM_OUT11 | P806 | GTIOC7A/RXD8_A/SCL8_A | 3.3V | GPT7A (relocated from P810 due to SDHI1 conflict) |
| 68 | PWM_OUT12 | P807 | GTIOC7B/TXD8_A/SDA8_A | 3.3V | GPT7B (relocated from P811 due to SDHI1 conflict) |
| 69 | SCI_SPI_SCK | P410 | SCK3_A/SCL3_A/RXD3_A | 3.3V | Extension SPI Clock (SCI3_A) |
| 70 | SCI_SPI_MOSI | P409 | TXD3_A/SDA3_A/GTIOC10A | 3.3V | Extension SPI MOSI (SCI3_A) |
| 71 | SCI_SPI_MISO | P408 | RXD3_A/SCL3_A/USBHS_VBUS | 3.3V | Extension SPI MISO (SCI3_A) |
| 72 | SCI_SPI_CS | P411 | GPIO/USBHS_ID | 3.3V | Extension SPI CS |
| 73 | RC_INPUT | P502 | RXD8_B/SCL8_B/MISO8_B | 3.3V | RC input (SCI8_B RX-only, relocated from P806) |
| 74 | RSSI_INPUT | P001 | AN001/IVCMP3/IRQ7-DS | 3.3V | RSSI analog input |
| 75 | SAFETY_SW | P009 | AN009/IVREF1/IRQ13-DS | 3.3V | Safety switch input |
| 76 | SAFETY_LED | P303 | SCK6_B/GTIOC7B/IRQ29-DS | 3.3V | Safety LED output |
| 77 | BUZZER | P600 | GTIOC6B/OM_0_RSTO1/IRQ30 | 3.3V | Buzzer PWM output (relocated from P807) |
| 78 | LED_RED | PA07 | CTS7_A/SD0DAT0_A/VCOUT | 3.3V | Red LED |
| 79 | LED_GREEN | P303 | SCK6_B/GTIOC7B/IRQ29-DS | 3.3V | Green LED |
| 80 | LED_BLUE | P600 | GTIOC6B/OM_0_RSTO1/IRQ30 | 3.3V | Blue LED |
| 81 | ADC1 | P001 | AN001/IVCMP3/IRQ7-DS | 3.3V | ADC channel 1 |
| 82 | ADC2 | P007 | AN007/IVCMP3/IRQ28 | 3.3V | ADC channel 2 |
| 83 | ADC3 | P003 | AN003/IVCMP3/IRQ29 | 3.3V | ADC channel 3 |
| 84 | ADC4 | P004 | AN004/IVCMP3/IRQ9-DS | 3.3V | ADC channel 4 |
| 85 | ADC5 | P014 | AN014/DA0/IVCMP0/IRQ27 | 3.3V | ADC channel 5 (DAC0) |
| 86 | ADC6 | P015 | AN015/DA1/IVCMP0/IRQ13 | 3.3V | ADC channel 6 (DAC1) |
| 87 | GPIO1 | P011 | AN011/IRQ16 | 3.3V | General purpose I/O |
| 88 | GPIO2 | P201 | MD/IRQ4 | 3.3V | General purpose I/O |
| 89 | GPIO3 | P412 | GTIOC8A/USB_EXICEN/IRQ20-DS | 3.3V | General purpose I/O |
| 90 | GPIO4 | P413 | ET_TAS_STA3/IRQ18 | 3.3V | General purpose I/O |
| 91 | GPIO5 | P704 | CTS1_B/SSLA1_C/IRQ6 | 3.3V | General purpose I/O |
| 92 | GPIO6 | PD01 | SCK8_C/ET1_RXD6/GTCPPO2 | 3.3V | General purpose I/O |
| 93 | GPIO7 | P312 | CTX0/IRQ22-DS | 3.3V | General purpose I/O |
| 94 | SPEKTRUM_RX | P808 | RXD7_B/SCL7_B/GTIOC13B | 3.3V | Spektrum receiver |
| 95 | SPEKTRUM_PWR | P901 | CTS_RTS3_C/GTADSM1/IRQ31 | 3.3V | Spektrum power control |
| 96 | VDD_BRICK1_VALID | P006 | AN006/IVCMP3/VREFH3 | 3.3V | Battery 1 valid |
| 97 | VDD_BRICK2_VALID | P012 | AN012/IRQ15 | 3.3V | Battery 2 valid |
| 98 | VDD_5V_PERIPH_EN | P710 | CTS4_B/ET0_LINKSTA/GTIOC11B | 3.3V | 5V peripheral enable |
| 99 | GND | - | Ground | 0V | System ground |
| 100 | GND | - | Ground | 0V | System ground |

### 6.4 50-Pin Secondary Connector (J2) Pinout

| Pin | Signal Name | RA8P1 Pin | Alt Functions | Voltage | Notes |
|---|---|---|---|---|---|
| 1 | VDD_5V_IN | - | Power Input | 5.0V | Primary power input |
| 2 | VDD_5V_IN | - | Power Input | 5.0V | Primary power input |
| 3 | BATT_VOLTAGE_SENS | P015 | AN015/DA1/IVCMP0/IRQ13 | 3.3V | Battery voltage sense |
| 4 | BATT_CURRENT_SENS | P014 | AN014/DA0/IVCMP0/IRQ27 | 3.3V | Battery current sense |
| 5 | FMU_CAP1 | P111 | IRQ19/GTIOC9A | 3.3V | Capture input 1 |
| 6 | FMU_CAP2 | P109 | IRQ23/GTIOC10A | 3.3V | Capture input 2 |
| 7 | FMU_CAP3 | P108 | IRQ24/GTIOC10B | 3.3V | Capture input 3 |
| 8 | FMU_CAP4 | P107 | IRQ31/GTIOC8A/AGTOA0 | 3.3V | Capture input 4 |
| 9 | FMU_CAP5 | PD01 | SCK8_C/ET1_RXD6/IRQ22 | 3.3V | Capture input 5 |
| 10 | FMU_CAP6 | PD02 | TXD8_C/ET1_RXD7/IRQ21 | 3.3V | Capture input 6 |
| 11 | RESERVED1 | PD03 | RXD8_C/ET0_RXD4/GTIOC3B | 3.3V | Future expansion |
| 12 | RESERVED2 | PD04 | CTS_RTS8_C/ET0_RXD5/GTIOC3A | 3.3V | Future expansion |
| 13 | RESERVED3 | PD05 | CTS8_C/ET0_RXD6/GTIOC2B | 3.3V | Future expansion |
| 14 | RESERVED4 | PD06 | ET0_RXD7/GTIOC2A/IRQ18 | 3.3V | Future expansion |
| 15 | RESERVED5 | PD07 | ET0_TXD4/GTCPPO0/IRQ17 | 3.3V | Future expansion |
| 16 | RESERVED6 | PB04 | SCK5_C/ET0_TXD3/IRQ9 | 3.3V | Future expansion |
| 17 | RESERVED7 | PB05 | CTS5_C/ET0_TXD7/IRQ15 | 3.3V | Future expansion |
| 18 | RESERVED8 | PB00 | SCK1_B/ET0_TXD0/GTCPPO4 | 3.3V | Future expansion |
| 19 | RESERVED9 | PB01 | ALE/ET0_TX_CLK/GTCPPO2 | 3.3V | Future expansion |
| 20 | RESERVED10 | PC01 | CTS7_C/OM_1_SIO0/IRQ27 | 3.3V | Future expansion |
| 21 | MIPI_CSI_CLK_P | MIPI_CSI_CL_P | Native MIPI Clock+ | 1.2V | MIPI Camera CLK+ |
| 22 | MIPI_CSI_CLK_N | MIPI_CSI_CL_N | Native MIPI Clock- | 1.2V | MIPI Camera CLK- |
| 23 | MIPI_CSI_D0_P | MIPI_CSI_DL0_P | Native MIPI Data0+ | 1.2V | MIPI Camera D0+ |
| 24 | MIPI_CSI_D0_N | MIPI_CSI_DL0_N | Native MIPI Data0- | 1.2V | MIPI Camera D0- |
| 25 | MIPI_CSI_D1_P | MIPI_CSI_DL1_P | Native MIPI Data1+ | 1.2V | MIPI Camera D1+ |
| 26 | MIPI_CSI_D1_N | MIPI_CSI_DL1_N | Native MIPI Data1- | 1.2V | MIPI Camera D1- |
| 27 | CAM_I2C_SCL | P512 | SCL1_A/CTS8_A/GTIOC0A | 3.3V | Camera I2C SCL1 |
| 28 | CAM_I2C_SDA | P511 | SDA1_A/CTS_RTS6_A/GTIOC0B | 3.3V | Camera I2C SDA1 |
| 29 | CAM_RESET | P709 | CTS_RTS4_B/SCL2_A/ET0_MDIO | 3.3V | Camera reset |
| 30 | CAM_PWDN | P705 | CTS1_B/SSLA2_C/CRX0 | 3.3V | Camera power-down |
| 31 | USB_DP | USBHS_DP | USB High Speed Data+ | 3.3V | USB HS D+ (P815) |
| 32 | USB_DN | USBHS_DM | USB High Speed Data- | 3.3V | USB HS D- (P814) |
| 33 | USB_VBUS | P408 | USBHS_VBUS/GPTP_PTPOUT2 | 5.0V | USB VBUS sense |
| 34 | USB_ID | P411 | USBHS_ID/GPTP_PTPOUT1 | 3.3V | USB OTG ID |
| 35 | CAM_XCLK | P501 | TXD8_B/SDA8_B/GTIOC12A | 3.3V | Camera clock |
| 36 | CAM_INT | P010 | AN010/IRQ14 | 3.3V | Camera interrupt |
| 37 | CAM_VSYNC | PB02 | RXD5_C/ET0_TXD1/GTCPPO0 | 3.3V | Camera VSYNC |
| 38 | CAM_HSYNC | PB03 | TXD5_C/ET0_TXD2/GTCPPO1 | 3.3V | Camera HSYNC |
| 39 | USB_VBUSEN | P407 | USBHS_VBUSEN/GPTP_PTPOUT3 | 3.3V | USB VBUS Enable |
| 40 | USB_OVRCUR | P413 | USBHS_OVRCURA/ET_TAS_STA3 | 3.3V | USB overcurrent detect |
| 41 | USB_EXICEN | P412 | USBHS_EXICEN/USB_EXICEN | 3.3V | USB external IC enable |
| 42 | AUX_GPIO1 | P902 | AUDIO_CLK/ETHPHYCLK/IRQ0 | 3.3V | Auxiliary GPIO 1 |
| 43 | AUX_GPIO2 | P910 | ET1_TXD4/GTCPPO12/IRQ7 | 3.3V | Auxiliary GPIO 2 |
| 44 | AUX_GPIO3 | P913 | ET1_TXD7/GTCPPO11/IRQ3 | 3.3V | Auxiliary GPIO 3 |
| 45 | HEATER_EN | P706 | RXD1_B/SCL1_B/ET0_GTX_CLK | 3.3V | IMU heater control |
| 46 | TEMP_SENS | P502 | SCK8_B/MISO8_B/GTIOC12B | 3.3V | Temperature sensor ADC |
| 47 | VDD_3V3_BACKUP | - | Power Output | 3.3V | Backup power for RTC |
| 48 | VDD_3V3_BACKUP | - | Power Output | 3.3V | Backup power for RTC |
| 49 | GND | - | Ground | 0V | System ground |
| 50 | GND | - | Ground | 0V | System ground |

---

## 7. ADVANCED INTERFACES

### 7.1 MIPI-CSI2 Camera Interface

**Connector:** 22-pin 0.5mm pitch FFC connector (bottom contact, ZIF)
- Part example: Molex 502598-2291 or equivalent
- Mating cable: 22-pin 0.5mm FFC, Type A

**Power Requirements:**
- VDD_CAM_1V8: 1.8V @ 150mA (camera core)
- VDD_CAM_2V8: 2.8V @ 100mA (camera analog)
- VDD_CAM_1V2: 1.2V @ 50mA (camera I/O)
- VDD_CAM_3V3: 3.3V @ 50mA (camera digital)

**Differential Pair Routing:**
- Clock pair + 2 data lane pairs (6 signals total)
- 100Ω ±5% differential impedance
- Length matching: ±0.05mm within pair
- Minimize vias: Maximum 2 per differential trace
- Reference: Solid ground plane, no plane splits

**Compatible Cameras:**
- Primary: Arducam OV5640 (5MP, up to 15fps @ QXGA)
- Also supports: Sony IMX219, Raspberry Pi Camera Module v2

### 7.2 Ethernet Interface

**PHY Chip:** Microchip KSZ9131RNX or equivalent
- 10/100Mbps operation
- RMII interface to MCU
- IEEE 1588 PTP support (for TSN)
- Package: 48-QFN

**Magnetics:** Integrated RJ45 connector with magnetics
- Part example: Pulse J0G-0003NL or equivalent
- 1:1 turns ratio
- Center taps for common-mode filtering
- LED indicators (link/activity)

**Critical Design Requirements:**
- 50MHz reference clock from MCU or crystal oscillator
- Differential impedance: 100Ω ±10% for MDI pairs
- Length matching: ±0.5mm for TX/RX pairs
- EMI filtering: Common-mode chokes, ferrite beads
- ESD protection: 2kV minimum on RJ45 pins

### 7.3 USB Interface

**Connector:** USB Type-C receptacle (USB 2.0 data + power delivery)
- Part example: GCT USB4105-GF-A or equivalent
- Supports USB OTG (host/device switching)
- Power Delivery: Optional, 5-20V negotiation

**Interface Requirements:**
- ESD protection: TPD2E009 or equivalent (8kV contact)
- Common-mode choke on D+/D- (90Ω @ 100MHz)
- Series termination: 27Ω resistors on D+/D-
- VBUS current limiting: 500mA default, 3A maximum

### 7.4 CAN Bus Transceivers

**Part:** Texas Instruments TCAN1042 or equivalent
- CAN-FD capable (up to 5Mbps)
- 3.3V supply voltage
- Failsafe features
- Package: SOIC-8

**External Interface:**
- 120Ω termination resistors (selectable via solder jumpers)
- TVS diodes on CAN_H/CAN_L (5.0SMDJ series)
- Common-mode choke for EMI suppression
- 5V power output for CAN nodes (500mA per port)

### 7.5 I3C Extension Port

**Purpose:** High-speed I3C bus (backward compatible with I2C)

**Pins:** P400 (SCL), P401 (SDA)
- On-board pull-ups: 1 kΩ
- Connector: 4-pin JST-GH or 2.54mm header

**Clocks:**
- I2C mode: Up to 1 MHz (Fast Mode Plus)
- I3C SDR mode: Up to 12.5 MHz

**Advantages:**
- Hot-join capability
- In-band interrupts
- Dynamic addressing
- Higher speed than I2C

**Supported Devices:**
- High-speed sensors (IMU, magnetometer, barometer)
- Smart sensors with I3C interface
- Future expansion peripherals

---

## 8. PCB DESIGN REQUIREMENTS

### 8.1 FMU Module PCB

#### 8.1.1 Stackup (8-Layer HDI)

**Layer Stack (from top):**

```
Layer 1: Signal (Top) - Components, fine-pitch routing
Layer 2: Ground - Solid copper pour
Layer 3: Signal - High-speed routing (MIPI, Ethernet)
Layer 4: Power - 3.3V plane
Layer 5: Power - 1.2V/1.8V planes
Layer 6: Signal - Medium-speed routing
Layer 7: Ground - Solid copper pour
Layer 8: Signal (Bottom) - Components, routing
```

**Material Specifications:**
- Base material: FR-4 High-Tg (Tg ≥ 170°C)
- Dielectric constant: 4.2-4.5 @ 1GHz
- Copper weight: 1oz (35µm) signal layers, 2oz (70µm) power planes
- Total thickness: 1.6mm ±0.1mm

**Via Technology:**
- Through vias: 0.2mm drill, 0.4mm pad
- Blind vias: 0.15mm drill (L1-L3, L6-L8)
- Buried vias: 0.15mm drill (L3-L6)
- Micro vias: 0.1mm drill (L1-L2, L7-L8) for BGA fanout
- Via-in-pad: Allowed with conductive fill and copper cap for BGA

#### 8.1.2 Design Rules

**Trace Widths:**
- Power traces (>500mA): 0.3mm minimum
- Standard signals: 0.1mm minimum
- Fine-pitch (BGA escape): 0.075mm minimum
- Differential pairs: 0.1mm minimum

**Clearances:**
- Trace-to-trace: 0.075mm minimum
- Trace-to-via: 0.05mm minimum
- Via-to-via: 0.1mm minimum
- High-voltage (>50V): 0.5mm minimum

**Impedance Targets:**
- Differential pairs: 100Ω ±5% (MIPI-CSI2), ±10% (Ethernet, USB)
- Single-ended: 50Ω ±10%
- Coplanar waveguide with ground return preferred for critical signals

**Length Matching:**
- MIPI-CSI2: ±0.05mm within pair, ±0.1mm between pairs
- Ethernet: ±0.1mm within pair, ±0.2mm between pairs
- SDRAM: ±0.5mm within address/data groups
- USB: ±0.5mm between D+ and D-

#### 8.1.3 Thermal Management

**MCU Thermal Design:**
- Thermal via array: 3×3 grid of 0.3mm vias under BGA center
- Connection to internal ground planes (Layer 2, Layer 7)
- Optional top-side copper pour for heat spreading
- Thermal pad clearance in solder mask

**Power Component Cooling:**
- Exposed pad packages with thermal vias to ground plane
- Wide traces (>1mm) for heat conduction
- Kelvin connections for current sensing

**IMU Temperature Control:**
- Heating resistors: 0805 or 1206 size, 10Ω, 0.5W rating
- Temperature sensors: NTC thermistors (10kΩ @ 25°C, ±1% accuracy)
- Target temperature: 50°C ±5°C
- PID control via MCU firmware

**Design Validation:**
- Thermal simulation required (ANSYS Icepak, Mentor FloTHERM, or equivalent)
- Maximum junction temperature: 105°C @ 85°C ambient, full load
- Steady-state thermal resistance: <15°C/W (MCU junction to ambient)

### 8.2 Carrier Baseboard PCB

#### 8.2.1 Stackup (6-Layer)

**Layer Stack:**

```
Layer 1: Signal (Top) - Connectors, components
Layer 2: Ground - Solid copper pour
Layer 3: Signal - Internal routing
Layer 4: Power - 5V and 3.3V planes (split/islands as needed)
Layer 5: Signal - Internal routing
Layer 6: Signal (Bottom) - Components
```

**Material:** Standard FR-4 (Tg ≥ 130°C)
**Copper weight:** 1oz signal layers, 2oz power planes
**Thickness:** 1.6mm ±0.1mm

#### 8.2.2 Design Rules

**Standard tolerances acceptable:**
- Trace width: 0.15mm minimum
- Clearance: 0.15mm minimum
- Via size: 0.3mm drill, 0.6mm pad

**Connector Placement:**
- Power connectors at corners for strain relief
- Signal connectors along edges for cable routing
- Maintain ≥5mm edge clearance for mounting

---

## 9. COMPONENT SELECTION AND BOM

### 9.1 Critical Component Requirements

**MCU:** Renesas R7JA8P1JSLSAJ
- Source: Authorized Renesas distributor only
- Package marking verification required
- Moisture sensitivity level: MSL3 (168 hours @ 30°C/60% RH)

**External Memory:**
- SDRAM: ISSI IS42S32160F-6BLI or approved alternate
- FRAM: FM24W256-GTR (Cypress/Infineon) or approved alternate
- Alternates must be functionally equivalent and tested

**Sensors:**
- Source: Authorized distributors (Digi-Key, Mouser, Arrow)
- Counterfeit screening: Verify date codes and packaging
- Moisture sensitivity: Bake before use per IPC/JEDEC J-STD-033

### 9.2 Primary Components BOM

| Component | Part Number | Manufacturer | Package | Quantity | Function |
|---|---|---|---|---|---|
| **MCU** | R7JA8P1JSLSAJ | Renesas | 303-PLBG | 1 | Main processor |
| **External SDRAM** | IS42S32160F-6BLI | ISSI | 54-TSOP | 1 | 32-64MB SDRAM |
| **FRAM** | FM24W256-GTR | Cypress/Infineon | 8-SOIC | 1 | 32KB FRAM |
| **IMU1** | BMI088 | Bosch | 16-LGA | 1 | Accel/Gyro (primary) |
| **IMU2** | ICM-42688-P | TDK | 14-LGA | 1 | Accel/Gyro (secondary) |
| **Barometer1** | BMP390 | Bosch | 10-LGA | 1 | Pressure sensor |
| **Barometer2** | BMP390 | Bosch | 10-LGA | 1 | Pressure sensor |
| **Magnetometer** | BMM150 | Bosch | 12-LGA | 1 | 3-axis compass |
| **Primary PMIC** | ISL80103IRAJZ | Renesas | 8-SOIC | 1 | Buck converter |
| **LDO1-5** | ISL80510IRAJZ | Renesas | 5-SOT23 | 5 | Sensor power |
| **Ethernet PHY** | KSZ9131RNX | Microchip | 48-QFN | 1 | 10/100 Mbps PHY |
| **CAN Transceiver** | TCAN1042 | TI | 8-SOIC | 2 | CAN-FD interface |

**Key Changes from R7KA8P1KFLCAC Variant:**
- **No external OSPI flash** (8 MB SiP flash integrated)
- **Added FRAM** (FM24W256-GTR on I2C1)
- **Dual IMU configuration** (BMI088 + ICM-42688-P)
- **No IMU3** (optional via SCI_SPI extension)

---

## 10. PIN MAPPING REFERENCE

### 10.1 Critical Pin Assignments (R7JA8P1JSLSAJ PLBG0303)

**SPI Channels:**
- **SPI0 (IMU1):** RSPCKA (SCK), MOSIA (MOSI), MISOA (MISO), SSLA0 (CS)
- **SPI1 (IMU2):** RSPCKB (SCK), MOSIB (MOSI), MISOB (MISO), SSLB0 (CS)

**I2C Channels:**
- **I2C0 (Baro1):** P408 (SCL) / P407 (SDA) — using I2C0_B pins
- **I2C1 (Baro2, FRAM):** P512 (SCL), P511 (SDA) — using I2C1_A pins
- **I2C2 (Mag):** P801 (SDA2_A)/ P802 (SCL2_A) — using I2C2_A pins

**I3C Extension:**
- **I3C0:** P400 (SCL) / P401 (SDA) — dedicated for I3C use

**SDHI (SD Card):**
- SD0CLK, SD0CMD, SD0DAT0–3, SD0CD, SD0WP

**SDRAM:**
- D0–D15, A0–A23, CS, RAS, CAS, WE, CKE

**UART Allocation:**
- SCI4_C (GPS1), SCI5_C (TELEM1), SCI6_A (TELEM2), SCI8_A (RC input)
- SCI9_B (GPS2 reserved), SCI7_B (TELEM3 reserved)

### 10.2 Resource Utilization Summary

| Resource Type | Available | Allocated | Remaining | Status |
|---|---|---|---|---|
| **UART/SCI** | 10 | 5 (TELEM1:SCI7, TELEM2:SCI0, TELEM3:SCI4, GPS1:SCI2, GPS2:SCI9) | 5 | OK |
| **RSPI (HW SPI)** | 2 | 2 (SPI0:IMU1, SPI1:IMU2) | 0 | OK |
| **SCI_SPI** | 10 | 1 (optional IMU3) | 9 | OK |
| **I2C** | 3 buses | 3 (I2C0:Baro1, I2C1:Baro2/FRAM, I2C2:Mag) | 0 | OK |
| **I3C** | 1 | 1 (I3C0:extension) | 0 | OK |
| **CAN-FD** | 2 | 2 (CAN1, CAN2) | 0 | OK |
| **PWM/GPT** | 14 channels | 12 | 2 | OK |
| **ADC Channels** | 24 | 12 (AN000-AN015 subset) | 12 | OK |
| **GPIO** | 100+ | ~45 (dedicated functions) | 55+ | OK |
| **Ethernet RMII** | 1 MAC | 1 (10 signals via ET1) | 0 | OK |
| **MIPI-CSI2** | 1 interface | 1 (2 lanes + clock) | 0 | OK |
| **USB HS** | 1 interface | 1 (D+, D-, VBUS, ID) | 0 | OK |
| **SDHI** | 1 controller | 1 (SD0) | 0 | OK |

---

## 11. MANUFACTURING REQUIREMENTS

### 11.1 PCB Fabrication

#### 11.1.1 FMU Module

**Class:** IPC-6012 Class 3 (High Reliability)

**Surface Finish:** ENIG (Electroless Nickel Immersion Gold)
- Nickel thickness: 3-6µm
- Gold thickness: 0.05-0.23µm
- Shelf life: ≥12 months

**Solder Mask:**
- Color: Green (standard) or Black (optional)
- LPI (Liquid Photoimageable) type
- Registration: ±0.075mm

**Silkscreen:**
- Color: White on green, Yellow on black
- Minimum text height: 0.8mm
- Reference designators, polarity marks, test points clearly marked
- Component outlines for assembly guidance

**Testing Requirements:**
- Electrical test: 100% netlist verification (flying probe or bed-of-nails)
- Impedance testing: Sample basis (10% of production lot minimum)
- Microsectioning: First article and periodic verification of via structures
- AOI (Automated Optical Inspection): 100% of boards

### 11.2 PCB Assembly

#### 11.2.1 Assembly Process Overview

**Assembly Standard:** IPC-A-610 Class 3 (High Performance Electronics)

**Process Flow:**
1. Incoming inspection (PCBs and components)
2. Solder paste application (stencil printing)
3. Component placement (automated pick-and-place)
4. Reflow soldering (lead-free profile)
5. Automated optical inspection (AOI)
6. X-ray inspection (BGA components)
7. In-circuit testing (ICT) if applicable
8. Functional testing
9. Conformal coating (optional, for harsh environments)
10. Final inspection and packaging

#### 11.2.2 Solder Paste and Stencil

**Solder Paste:**
- Alloy: SAC305 (96.5% Sn, 3% Ag, 0.5% Cu) lead-free
- Particle size: Type 4 (20-38µm) for fine-pitch components
- Flux type: No-clean, low-residue (ROL0 or ROL1)
- Storage: 2-10°C refrigerated, 6-month shelf life
- Working time: 4-8 hours at room temperature after removal from refrigeration

**Stencil Design:**
- Material: Laser-cut stainless steel (electropolished)
- Thickness: 0.12mm for fine pitch (BGA), 0.15mm for standard components
- Aperture design:
  - BGA pads: 0.66 ratio (aperture diameter = 0.66 × pad diameter)
  - Standard pads: 0.8-1.0 ratio
  - Area ratio: ≥0.66 (aperture area / aperture wall area)
- Fiducials: Minimum 3 per board (global + local for fine-pitch areas)

#### 11.2.3 BGA Assembly Considerations

**R7JA8P1JSLSAJ BGA Specific Requirements:**
- Package: 303-pin, 17mm × 17mm, 0.5mm ball pitch
- Ball composition: SAC305 lead-free
- Coplanarity: <0.1mm across package

**Process Controls:**
- Stencil aperture: 0.3mm diameter (66% of 0.45mm pad)
- Paste volume: 60-80% of ball volume
- Placement accuracy: ±0.025mm (±50µm)
- X-ray inspection: 100% required post-reflow

**X-ray Acceptance Criteria (IPC-A-610 Class 3):**
- Void percentage: <25% per individual joint, <15% cumulative
- Head-in-pillow defects: Zero tolerance
- Bridging: Zero tolerance
- Non-wet opens: Zero tolerance
- Solder ball diameter reduction: <20% from original

---

## 12. COMPLIANCE AND TESTING

### 12.1 Regulatory Compliance Testing

#### 12.1.1 FCC Compliance (United States)

**Applicable Standard:** FCC Part 15, Subpart B (Unintentional Radiators)
**Class:** Class A Digital Device (commercial/industrial use)

**Emissions Limits:**
- Radiated emissions: 30-1000 MHz
  - 30-88 MHz: 40 dBµV/m @ 10m
  - 88-216 MHz: 43.5 dBµV/m @ 10m
  - 216-960 MHz: 46 dBµV/m @ 10m
  - Above 960 MHz: 54 dBµV/m @ 10m

**Testing Requirements:**
- Accredited test lab (NVLAP or A2LA)
- Supplier's Declaration of Conformity (SDoC)
- Test report retention: 10 years

#### 12.1.2 CE Marking (European Union)

**Applicable Directives:**
1. EMC Directive 2014/30/EU
2. RoHS Directive 2011/65/EU
3. WEEE Directive 2012/19/EU

**Harmonized Standards:**
- EN 55032:2015 (Electromagnetic compatibility - Emission requirements)
- EN 55035:2017 (Electromagnetic compatibility - Immunity requirements)
- EN 61000-3-2 (Harmonic current emissions)
- EN 61000-3-3 (Voltage fluctuations and flicker)

**Testing Requirements:**
- EMC emissions: Class A limits
- Immunity testing: ESD (8kV contact), radiated RF (10V/m), EFT bursts, surge
- RoHS compliance: Material analysis (XRF screening + wet chemistry confirmation)

### 12.2 Environmental and Reliability Testing

#### 12.2.1 Operating Environment Qualification

**Temperature Testing:**
- Operating range: -40°C to +85°C
- Test points: -40°C, -20°C, 0°C, +25°C, +50°C, +70°C, +85°C
- Test duration: 2 hours minimum per temperature point
- Functional testing: All interfaces operational at each point

**Humidity Testing:**
- Relative humidity: 5% to 95% RH (non-condensing)
- Temperature cycling: 25°C to 55°C with humidity
- Duration: 10 cycles minimum (IEC 60068-2-30)
- Post-test: Insulation resistance >100MΩ

**Altitude Testing:**
- Operating altitude: Sea level to 40,000 feet (12,200 meters)
- Pressure simulation: 1013 mbar to 187 mbar
- Functional testing: Barometer accuracy, power supply operation

#### 12.2.2 Mechanical Stress Testing

**Vibration Testing (Sinusoidal):**
- Frequency range: 5-2000 Hz
- Amplitude: 20G peak acceleration
- Sweep rate: 1 octave/minute
- Duration: 3 axes × 30 minutes each (IEC 60068-2-6)
- Functional: No failure during and after test

**Shock Testing:**
- Amplitude: 100G peak, 11ms half-sine pulse
- Direction: 3 axes, ±directions (6 shocks total)
- Standard: MIL-STD-810G Method 516.6
- Acceptance: No mechanical damage, functional post-test

---

## 13. REFERENCE DOCUMENTS

### 13.1 Pixhawk Standards

1. **DS-020: Pixhawk Autopilot v6X-RT Standard**
   - https://github.com/pixhawk/Pixhawk-Standards/blob/master/DS-020%20Pixhawk%20Autopilot%20v6X-RT%20Standard.pdf

2. **DS-010: Pixhawk Autopilot Bus (PAB) Standard**
   - https://github.com/pixhawk/Pixhawk-Standards/blob/master/DS-010%20Pixhawk%20Autopilot%20Bus%20Standard.pdf

3. **DS-009: Pixhawk Connector Standard**
   - https://github.com/pixhawk/Pixhawk-Standards/blob/master/DS-009%20Pixhawk%20Connector%20Standard.pdf

### 13.2 Renesas Documentation

4. **RA8P1 Group User's Manual: Hardware**
   - https://www.renesas.com/us/en/document/mah/ra8p1-group-users-manual-hardware

5. **RA8P1 Group Datasheet**
   - https://www.renesas.com/us/en/document/dst/ra8p1-group-datasheet

6. **R7JA8P1JSLSAJ Datasheet (303-pin PLBG)**
   - https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus/ra8p1-group

### 13.3 Component Datasheets

7. **Bosch BMI088** (6-axis IMU)
   - https://www.bosch-sensortec.com/products/motion-sensors/imus/bmi088/

8. **TDK ICM-42688-P** (6-axis IMU)
   - https://invensense.tdk.com/products/motion-tracking/6-axis/icm-42688-p/

9. **Bosch BMP390** (Barometric pressure sensor)
   - https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp390/

10. **Bosch BMM150** (3-axis magnetometer)
    - https://www.bosch-sensortec.com/products/motion-sensors/magnetometers/bmm150/

11. **Cypress FM24W256** (32KB FRAM)
    - https://www.infineon.com/cms/en/product/memories/f-ram-ferroelectric-ram/

12. **ISSI IS42S32160F** (64MB SDRAM)
    - https://www.issi.com/WW/pdf/42-45S16160F.pdf

### 13.4 Software Specification

13. **RA8P1 FMU Software Specification — R7JA8P1JSLSAJ**
    - Companion document to this hardware specification
    - Defines PX4 integration, dual-core architecture, and AI pipeline

### 13.5 Industry Standards

14. **IPC-2221B: Generic Standard on Printed Board Design**
15. **IPC-A-610H: Acceptability of Electronic Assemblies**
16. **IPC-6012E: Qualification and Performance Specification for Rigid PCBs**

---

## 14. APPENDICES

### Appendix A: Acronyms and Abbreviations

| Acronym | Definition |
|---|---|
| ADC | Analog-to-Digital Converter |
| BGA | Ball Grid Array |
| BOM | Bill of Materials |
| CAN | Controller Area Network |
| CE | Conformité Européenne |
| DVT | Design Verification Test |
| EMC | Electromagnetic Compatibility |
| EMI | Electromagnetic Interference |
| ENIG | Electroless Nickel Immersion Gold |
| FCC | Federal Communications Commission |
| FMU | Flight Management Unit |
| FRAM | Ferroelectric RAM |
| GPIO | General Purpose Input/Output |
| HDI | High Density Interconnect |
| I2C | Inter-Integrated Circuit |
| I3C | Improved Inter-Integrated Circuit |
| IMU | Inertial Measurement Unit |
| IPC | Inter-Process Communication |
| JST | Japan Solderless Terminal |
| LDO | Low Dropout Regulator |
| MIPI | Mobile Industry Processor Interface |
| NRE | Non-Recurring Engineering |
| NPU | Neural Processing Unit |
| PAB | Pixhawk Autopilot Bus |
| PCB | Printed Circuit Board |
| PWM | Pulse Width Modulation |
| RoHS | Restriction of Hazardous Substances |
| SDHI | SD Host Interface |
| SDRAM | Synchronous Dynamic RAM |
| SiP | System in Package |
| SPI | Serial Peripheral Interface |
| UART | Universal Asynchronous Receiver-Transmitter |
| USB | Universal Serial Bus |

### Appendix B: Design Checklist

**Schematic Review:**
- ☐ All component values specified
- ☐ Power supply sequencing correct
- ☐ Decoupling capacitors on all power pins
- ☐ Pull-up/pull-down resistors on critical signals
- ☐ ESD protection on external connectors
- ☐ Test points on critical signals
- ☐ BOM complete with alternates

**Layout Review:**
- ☐ Board dimensions per specification
- ☐ High-speed signals routed differentially
- ☐ Ground and power planes solid
- ☐ Via stitching around high-speed signals
- ☐ Thermal vias under high-power components
- ☐ Differential pairs length-matched
- ☐ Design rule check (DRC) clean

### Appendix C: Test Points

**Mandatory Test Points on FMU:**
- All power rails (VCC, GND pairs)
- SWD interface signals (SWDIO, SWCLK, nRESET)
- UART console (TX, RX)
- Clock signals (crystal outputs)
- Sensor bus signals (SPI CLK, MISO, MOSI, CS)
- I2C bus signals (SCL, SDA)
- Analog inputs (ADC inputs, voltage references)

**Test Point Specification:**
- Type: Surface mount pads or through-hole pins
- Size: Minimum 1mm diameter for probe access
- Spacing: Minimum 2.54mm (0.1") for test clips
- Marking: Silkscreen label with signal name

---

## DOCUMENT APPROVAL

| Role | Name | Signature | Date |
|---|---|---|---|
| Customer Technical Lead | ____ | ____ | ____ |
| Vendor Project Manager | ____ | ____ | ____ |
| Quality Assurance | ____ | ____ | ____ |

## REVISION HISTORY

| Version | Date | Author | Changes |
|---|---:|---|---|
| 1.0 | 01-Jan-2026 | RA8P1 Integration Team | Initial release for R7JA8P1JSLSAJ variant |

---

**END OF DOCUMENT**

---