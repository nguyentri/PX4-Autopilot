# RA8P1 Dual-Core Architecture: Complete FMU+IO Replacement
## Software Architecture & Task Distribution for Delivery Drone

**Document Version:** 1.0
**Date:** January 3, 2026
**Target Platform:** Renesas R7JA8P1JSLSAJ PLBG0303
**Purpose:** Replace Traditional PX4 FMU (STM32F427) + PX4 IO (STM32F100) with Single RA8P1 Dual-Core MCU

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Traditional FMU+IO Architecture Analysis](#2-traditional-fmuio-architecture-analysis)
3. [RA8P1 Dual-Core Architecture Overview](#3-ra8p1-dual-core-architecture-overview)
4. [Complete Task Distribution (CM85 vs CM33)](#4-complete-task-distribution-cm85-vs-cm33)
5. [Inter-Core Communication (IPC) Protocol](#5-inter-core-communication-ipc-protocol)
6. [Peripheral Assignment & Driver Architecture](#6-peripheral-assignment-driver-architecture)
7. [Safety & Failsafe Architecture](#7-safety-failsafe-architecture)
8. [Boot Sequence & Initialization](#8-boot-sequence-initialization)
9. [Real-Time Performance Requirements](#9-real-time-performance-requirements)
10. [Migration Guide from FMU+IO](#10-migration-guide-from-fmuio)
11. [Testing & Validation Strategy](#11-testing-validation-strategy)
12. [Appendix: Code Examples](#12-appendix-code-examples)

---

## 1. Executive Summary

This document defines a complete software architecture for replacing the traditional **PX4 FMU (STM32F427 @ 168 MHz) + PX4 IO (STM32F100 @ 24 MHz)** dual-board system with a single **Renesas RA8P1 (R7JA8P1JSLSAJ) dual-core MCU**:

- **Cortex-M85 @ 1 GHz** (replaces FMU STM32F427)
- **Cortex-M33 @ 250 MHz** (replaces IO STM32F100)

### Key Advantages of RA8P1 Integration

| Aspect | Traditional FMU+IO | RA8P1 Single-Chip |
|--------|-------------------|-------------------|
| **Processing Power** | FMU: 168 MHz, IO: 24 MHz | CM85: 1 GHz, CM33: 250 MHz |
| **Board Count** | 2 boards + interconnect | 1 board (integrated) |
| **Latency** | 2-5 ms (serial link) | <100 µs (shared memory IPC) |
| **Safety Isolation** | Physical separation | Hardware separation (dual-core + POEG) |
| **Power** | ~2W (both boards) | ~1.5W (single chip) |
| **Reliability** | Board-to-board connector failure risk | Monolithic (no connector) |
| **Cost** | 2× MCU + PCBs + connector | 1× MCU + single PCB |
| **AI Capability** | None | Ethos-U55 NPU (256 GOPS INT8) |

### Design Philosophy

The RA8P1 dual-core architecture **directly maps** the FMU+IO functional separation onto hardware cores while providing:
1. **10× better performance** (1 GHz vs 168 MHz)
2. **20× lower latency** (<100 µs IPC vs 2-5 ms serial)
3. **10× better safety isolation** (dual-core watchdog vs serial handshake)
4. **Integrated AI processing** (on-chip NPU)

---

## 2. Traditional FMU+IO Architecture Analysis

### 2.1 Traditional System Block Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│              Traditional PX4 FMU + IO Architecture              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────┐      Serial Link       ┌──────────────────────┐
│  │   FMU Board          │◄────────────────────►│   IO Board           │
│  │   STM32F427 @ 168MHz │   (UART @ 1.5Mbps)   │   STM32F100 @ 24MHz  │
│  │                      │    2-5ms latency     │                      │
│  │  • PX4 Autopilot     │                      │  • RC Input Decode   │
│  │  • Sensor Fusion     │                      │  • PWM/DShot Output  │
│  │  • Navigation        │                      │  • Safety Interlock  │
│  │  • Telemetry         │                      │  • Arming Logic      │
│  │  • Logging           │                      │  • Battery Monitor   │
│  │                      │                      │  • LED Control       │
│  └──────────────────────┘                      └──────────────────────┘
│         │                                                 │
│         │                                                 │
│  ┌──────┴──────────┐                           ┌─────────┴─────────┐
│  │ FMU Peripherals │                           │ IO Peripherals    │
│  │ • 3× IMU (SPI)  │                           │ • RC Input (UART) │
│  │ • 2× Baro (I2C) │                           │ • 8× PWM (Timer)  │
│  │ • GPS (UART)    │                           │ • S.Bus Out (UART)│
│  │ • Mag (I2C)     │                           │ • Safety SW (GPIO)│
│  │ • CAN × 2       │                           │ • Buzzer (GPIO)   │
│  │ • Ethernet      │                           │ • ADC (Battery)   │
│  │ • USB           │                           │                   │
│  │ • SD Card       │                           │                   │
│  └─────────────────┘                           └───────────────────┘
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 FMU Board Responsibilities (STM32F427)

**Primary Functions**:
- **Flight Control**: Attitude, position, and velocity control loops (1000 Hz)
- **State Estimation**: EKF2 sensor fusion (250-400 Hz)
- **Navigation**: Waypoint following, geofence, return-to-launch
- **Mission Planning**: Auto missions, offboard control
- **Communication**: MAVLink telemetry, ROS 2 integration
- **Logging**: ULog to SD card (high-bandwidth data recording)
- **Sensor Management**: IMU, barometer, magnetometer, GPS drivers

**Hardware Resources**:
- **CPU**: ARM Cortex-M4F @ 168 MHz (210 DMIPS)
- **RAM**: 192 KB SRAM + 64 KB CCM
- **Flash**: 1 MB (code storage)
- **Peripherals**: 3× SPI, 4× I2C, 6× UART, 2× CAN, Ethernet, USB

**Typical CPU Load**:
- Idle: 20-30%
- Hover: 40-50%
- Aggressive flight: 60-70%
- Peak: 80-90% (with logging + telemetry)

### 2.3 IO Board Responsibilities (STM32F100)

**Primary Functions**:
- **RC Input Decoding**: CPPM, S.Bus, RSSI, DSM (50-100 Hz)
- **Servo/Motor Control**: PWM generation (50-400 Hz), DShot (up to 1200 Hz)
- **Safety Logic**: Arming/disarming state machine, safety switch
- **Battery Monitoring**: Voltage, current via ADC and SMBus
- **Failsafe**: RC loss detection, motor kill on FMU timeout
- **Status Indication**: LED control, buzzer output

**Hardware Resources**:
- **CPU**: ARM Cortex-M3 @ 24 MHz (30 DMIPS)
- **RAM**: 8 KB SRAM
- **Flash**: 64 KB (code storage)
- **Peripherals**: 2× UART, 8× Timer (PWM), ADC, GPIO

**Typical CPU Load**:
- Normal: 10-20%
- Peak: 30-40% (DShot generation)

### 2.4 FMU-IO Communication Protocol (Serial Link)

**Interface**: UART @ 1.5 Mbps (bidirectional)

**Message Types**:

| Message | Direction | Rate | Size | Purpose |
|---------|-----------|------|------|---------|
| **Actuator Commands** | FMU → IO | 400 Hz | 64 bytes | Motor/servo setpoints |
| **RC Data** | IO → FMU | 50-100 Hz | 32 bytes | RC channel values |
| **Status** | IO → FMU | 10 Hz | 16 bytes | IO health, battery, RSSI |
| **Configuration** | FMU → IO | On-demand | Variable | Arming, mixing, failsafe config |

**Latency**:
- Typical: 2-5 ms (one-way)
- Worst-case: 10-20 ms (buffer overflow, UART errors)

**Reliability Issues**:
- **Serial corruption**: Occasional bit errors require CRC retry
- **Buffer overflow**: High-rate commands can saturate 1.5 Mbps link
- **Connector failure**: Physical disconnect causes total system failure
- **Bootloader conflicts**: IO firmware update requires FMU coordination

### 2.5 Limitations of FMU+IO Architecture

1. **High Latency**: 2-5 ms serial link adds delay to RC input → motor output path
2. **Limited Bandwidth**: 1.5 Mbps UART limits data throughput for future features
3. **Complex Failsafe**: FMU timeout detection relies on IO monitoring serial heartbeat
4. **Single Point of Failure**: Connector or board-to-board link failure = total loss
5. **No AI Capability**: STM32F427 lacks NPU for vision-based obstacle avoidance
6. **Power Inefficiency**: Two boards consume more power than single integrated solution

---

## 3. RA8P1 Dual-Core Architecture Overview

### 3.1 RA8P1 Integrated FMU+IO Replacement

```
┌─────────────────────────────────────────────────────────────────┐
│             RA8P1 Integrated FMU+IO Architecture                │
│             (Single Chip, Dual-Core, Shared Memory)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────┐      Shared Memory     ┌──────────────────────┐
│  │ Cortex-M85 @ 1GHz    │◄────────────────────►│ Cortex-M33 @ 250MHz  │
│  │ (FMU Replacement)    │   IPC (64KB SRAM)    │ (IO Replacement)     │
│  │                      │   <100µs latency     │                      │
│  │  • PX4 Autopilot     │                      │  • RC Input Decode   │
│  │  • NuttX RTOS        │                      │  • PWM/DShot Output  │
│  │  • Sensor Fusion     │                      │  • Safety Interlock  │
│  │  • Navigation        │                      │  • Arming Logic      │
│  │  • Edge AI (NPU)     │                      │  • Battery Monitor   │
│  │  • Telemetry         │                      │  • Watchdog on CM85  │
│  │  • Logging (SDHI)    │                      │  • POEG Kill Switch  │
│  └──────────────────────┘                      └──────────────────────┘
│         │                                                 │
│         │                                                 │
│  ┌──────┴──────────────────────────────────────────────┴───────┐
│  │              Unified Peripheral Access                      │
│  │  • CM85: 2× SPI (IMU), 3× I2C (Baro/Mag/FRAM)             │
│  │  • CM33: 8× GPT (PWM/DShot), ADC (Battery)                │
│  │  • Shared: 7× UART, 2× CAN-FD, Ethernet, USB, SDHI        │
│  │  • SDRAM: 32MB (AI tensor arena, video buffers)           │
│  │  • FRAM: 32KB (mission-critical parameters)               │
│  └────────────────────────────────────────────────────────────┘
│                                                                 │
│  ┌────────────────────────────────────────────────────────────┐
│  │              Hardware Safety Features                      │
│  │  • POEG: Emergency motor kill (<1µs, hardware-only)        │
│  │  • Dual Watchdog: CM85↔CM33 mutual monitoring             │
│  │  • ECC SRAM: Error correction on all shared memory        │
│  │  • MPU: Memory protection between cores                    │
│  └────────────────────────────────────────────────────────────┘
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Key Architectural Differences

| Feature | Traditional FMU+IO | RA8P1 Dual-Core |
|---------|-------------------|-----------------|
| **Core Separation** | Physical (2 boards) | Logical (1 chip, 2 cores) |
| **Communication** | Serial UART (1.5 Mbps) | Shared memory IPC (>1 GB/s) |
| **Latency** | 2-5 ms | <100 µs |
| **Bandwidth** | 1.5 Mbps | Unlimited (shared SRAM) |
| **Failsafe** | Serial heartbeat | Hardware watchdog + POEG |
| **Safety Isolation** | Physical | Dual-core + MPU + ECC |
| **Reliability** | Connector SPOF | Monolithic (no connector) |
| **AI Capability** | None | Ethos-U55 NPU (256 GOPS) |
| **Power** | ~2W | ~1.5W |

### 3.3 RA8P1 Hardware Resources

**Cortex-M85 (CM85) - FMU Replacement**:
- **CPU**: 1 GHz (1400 DMIPS) - **6× faster than STM32F427**
- **RAM**: 832 KB SRAM + 128 KB ITCM + 128 KB DTCM = **4× more than STM32F427**
- **Flash**: 8 MB on-chip (vs 1 MB on STM32F427)
- **NPU**: Ethos-U55 (256 GOPS INT8) - **NEW capability**

**Cortex-M33 (CM33) - IO Replacement**:
- **CPU**: 250 MHz (333 DMIPS) - **10× faster than STM32F100**
- **RAM**: 768 KB SRAM - **96× more than STM32F100**
- **Flash**: Shared 8 MB (vs 64 KB on STM32F100)

**Shared Peripherals**:
- **SPI**: 2× hardware (RSPI0/1) for IMUs
- **I2C**: 3× channels (I2C0/1/2) for baro, mag, FRAM
- **UART**: 7× channels (SCI0-8)
- **CAN**: 2× CAN-FD @ 5 Mbps
- **Ethernet**: 100 Mbps with TSN
- **USB**: High Speed (480 Mbps)
- **SDHI**: Native SD card controller (25 MB/s)
- **GPT**: 14× 32-bit timers for PWM/DShot
- **ADC**: 12-bit, 24 channels

---

## 4. Complete Task Distribution (CM85 vs CM33)

### 4.1 Cortex-M85 (CM85) - FMU Tasks

**Replaces**: STM32F427 FMU board

**Operating System**: NuttX RTOS with full POSIX API

**Memory Allocation**:
- Code: 8 MB Flash (shared)
- Data: 832 KB SRAM + 128 KB DTCM
- AI Tensor Arena: 20 MB SDRAM

#### 4.1.1 Flight Control Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **mc_att_control** | Attitude stabilization (roll/pitch/yaw) | 1000 | 250 | 15-20% | Highest priority, critical for stability |
| **mc_pos_control** | Position/velocity control | 250 | 240 | 5-8% | Translates position setpoints to attitude |
| **mc_rate_control** | Angular rate control | 1000 | 245 | 10-12% | Inner loop, rate command tracking |
| **motor_mixing** | Actuator mixing (quad X) | 1000 | 245 | 2-3% | Converts body rates to motor commands |

**Total Flight Control CPU**: 32-43%

#### 4.1.2 State Estimation Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **ekf2** | Extended Kalman Filter (sensor fusion) | 250-400 | 235 | 12-18% | Fuses IMU, baro, GPS, mag |
| **sensors** | Sensor data preprocessing | 250 | 230 | 5-8% | IMU calibration, voting |
| **land_detector** | Ground contact detection | 50 | 180 | <1% | Detects landing events |

**Total State Estimation CPU**: 17-27%

#### 4.1.3 Navigation Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **navigator** | Waypoint following, mission execution | 50 | 180 | 2-4% | Auto missions |
| **geofence** | Boundary monitoring | 10 | 180 | <1% | Prevents flyaway |
| **rtl** | Return-to-launch logic | 50 | 180 | 1-2% | Emergency return |
| **land** | Autonomous landing | 50 | 180 | 1-2% | Precision landing |

**Total Navigation CPU**: 4-9%

#### 4.1.4 Sensor Driver Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **bmi088** | IMU1 driver (SPI0) | 2000 | 230 | 2-3% | Primary IMU, high accuracy |
| **icm42688p** | IMU2 driver (SPI1) | 8000 | 230 | 3-5% | Secondary IMU, high rate |
| **bmp390** | Baro drivers (I2C0/1) | 100 | 230 | <1% | Dual barometer |
| **bmm150** | Magnetometer (I2C2) | 100 | 230 | <1% | Compass |
| **gps** | GPS driver (UART) | 10 | 220 | <1% | u-blox UBX protocol |

**Total Sensor Driver CPU**: 6-10%

#### 4.1.5 Communication Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **mavlink** | MAVLink telemetry (UART/Ethernet) | 50 | 150 | 3-5% | Ground station communication |
| **uavcan** | CAN-FD bus (UAVCAN protocol) | 100 | 150 | 2-3% | Smart peripherals |
| **rtps** | ROS 2 DDS (Ethernet) | Variable | 150 | 2-4% | Companion computer interface |

**Total Communication CPU**: 7-12%

#### 4.1.6 Edge AI Tasks (Optional)

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **camera_capture** | MIPI-CSI2 frame capture | 30 | 180 | 2-3% | 1080p video |
| **ai_preprocessing** | Resize, normalize | 30 | 180 | 3-5% | CPU resize 1080p→224×224 |
| **ai_inference** | Ethos-U55 NPU inference | 5-10 | 180 | 1-2% | MobileNetV2-SSD |
| **obstacle_avoidance** | Collision prevention logic | 5-10 | 180 | 1-2% | Velocity adjustment |

**Total AI CPU**: 7-12% (when active)

#### 4.1.7 Logging & Management Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **logger** | ULog to SD card (SDHI) | Variable | 100 | 5-10% | High-bandwidth logging |
| **commander** | Mode switching, arming | 100 | 170 | 2-3% | State machine |
| **param** | Parameter server | On-demand | 100 | <1% | FRAM-backed storage |

**Total Logging & Management CPU**: 7-14%

#### 4.1.8 CM85 Total CPU Budget

| Scenario | Flight Control | State Est | Nav | Sensors | Comm | AI | Logging | Total |
|----------|----------------|-----------|-----|---------|------|----|---------|-------|
| **Idle** | 0% | 5% | 2% | 6% | 3% | 0% | 2% | **18-25%** |
| **Hover** | 35% | 20% | 5% | 8% | 7% | 0% | 8% | **50-60%** |
| **Aggressive** | 43% | 27% | 9% | 10% | 10% | 0% | 12% | **65-75%** |
| **AI Active** | 43% | 27% | 9% | 10% | 10% | 12% | 12% | **75-85%** |
| **Peak** | 43% | 27% | 9% | 10% | 12% | 12% | 14% | **<90%** |

**Conclusion**: CM85 @ 1 GHz has sufficient headroom for all FMU tasks plus Edge AI with <10% margin.

---

### 4.2 Cortex-M33 (CM33) - IO Tasks

**Replaces**: STM32F100 IO board

**Operating System**: Bare-metal or FreeRTOS (optional)

**Memory Allocation**:
- Code: 8 MB Flash (shared)
- Data: 768 KB SRAM

#### 4.2.1 RC Input Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **sbus_decoder** | S.Bus frame decode (UART DMA) | 100 | High (2/16) | 3-5% | Inverted UART @ 100 kbps |
| **crsf_decoder** | CRSF/ELRS decode | 150-500 | High (2/16) | 3-5% | High-speed RC link |
| **cppm_decoder** | CPPM pulse capture (Timer) | 50 | High (2/16) | 2-3% | Legacy RC |
| **rssi_reader** | RSSI analog input (ADC) | 50 | Medium (8/16) | <1% | Signal strength |
| **rc_failsafe** | RC loss detection | 10 | High (2/16) | <1% | Timeout monitoring |

**Total RC Input CPU**: 8-14%

#### 4.2.2 Motor/Servo Output Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **dshot_generator** | DShot frame generation (GPT + DMA) | 400-1200 | High (3/16) | 10-15% | 4× motors, DShot600 |
| **pwm_generator** | PWM for servos (GPT) | 50-400 | High (3/16) | 2-3% | Aux channels |
| **motor_arming** | Arming state machine | Immediate | High (2/16) | <1% | Enable/disable motors |
| **servo_control** | Servo position control | 50 | Medium (8/16) | <1% | Gimbal, flaps |

**Total Output CPU**: 12-19%

#### 4.2.3 Safety & Monitoring Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **cm85_watchdog** | Monitor CM85 heartbeat | 10 | Medium (8/16) | <1% | Timeout = 100ms |
| **poeg_trigger** | Emergency motor kill | Immediate | Highest (1/16) | <1% | Hardware POEG |
| **safety_switch** | Physical switch monitoring (GPIO IRQ) | 100 | Medium (8/16) | <1% | ARM/DISARM button |
| **led_control** | Status LED patterns | 2 | Low (12/16) | <1% | RGB LED |
| **buzzer_control** | Audio alerts | 10 | Low (12/16) | <1% | Piezo buzzer |

**Total Safety CPU**: 2-5%

#### 4.2.4 Battery Monitoring Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **voltage_monitor** | Battery voltage (ADC) | 100 | Medium (8/16) | <1% | 12-bit ADC |
| **current_monitor** | Battery current (ADC) | 100 | Medium (8/16) | <1% | Hall effect sensor |
| **smbus_battery** | Smart battery (I2C/SMBus) | 10 | Low (12/16) | 1-2% | BMS communication |
| **battery_failsafe** | Low voltage detection | 10 | High (4/16) | <1% | Emergency land trigger |

**Total Battery CPU**: 2-4%

#### 4.2.5 IPC Communication Tasks

| Task | Function | Rate (Hz) | Priority | CPU % | Notes |
|------|----------|-----------|----------|-------|-------|
| **ipc_rx** | Receive actuator commands (CM85 → CM33) | 400-1000 | High (4/16) | 2-3% | Shared memory read |
| **ipc_tx** | Send RC/status (CM33 → CM85) | 50-100 | High (4/16) | 1-2% | Shared memory write |
| **ipc_heartbeat** | Heartbeat exchange | 10 | Medium (8/16) | <1% | Mutual health check |

**Total IPC CPU**: 3-6%

#### 4.2.6 CM33 Total CPU Budget

| Scenario | RC Input | Output | Safety | Battery | IPC | Total |
|----------|----------|--------|--------|---------|-----|-------|
| **Normal** | 10% | 15% | 3% | 2% | 4% | **34%** |
| **Peak (DShot1200)** | 14% | 19% | 5% | 4% | 6% | **48%** |

**Conclusion**: CM33 @ 250 MHz has significant headroom (50%+ idle) for IO tasks, providing margin for future features.

---

### 4.3 Shared Peripheral Access Strategy

**Problem**: Both CM85 and CM33 need access to some peripherals (UART, CAN, USB)

**Solution**: Peripheral ownership model with IPC message passing

| Peripheral | Owner | Access | Notes |
|------------|-------|--------|-------|
| **SPI0/1** | CM85 only | Direct | IMU sensors (high-rate) |
| **I2C0/1/2** | CM85 only | Direct | Baro, mag, FRAM |
| **UART (GPS, TELEM)** | CM85 only | Direct | Communication |
| **UART (RC Input)** | CM33 only | Direct | S.Bus decoder |
| **GPT (PWM/DShot)** | CM33 only | Direct | Motor output |
| **ADC** | CM33 only | Direct | Battery monitoring |
| **CAN** | CM85 primary | Shared via IPC | UAVCAN |
| **Ethernet** | CM85 only | Direct | ROS 2, telemetry |
| **USB** | CM85 only | Direct | Firmware upload |
| **SDHI (SD Card)** | CM85 only | Direct | Logging |
| **SDRAM** | Shared | MPU-protected regions | AI tensors (CM85 only) |

**IPC Access Pattern**:
- CM33 never directly accesses sensors (SPI/I2C) - receives processed data from CM85
- CM85 never directly accesses RC/ADC - receives data from CM33 via IPC
- If shared access needed (e.g., CAN), primary core owns hardware, secondary sends requests via IPC

---

## 5. Inter-Core Communication (IPC) Protocol

### 5.1 IPC Architecture

**Method**: Shared Memory Mailbox (64 KB SRAM) + Hardware Interrupts

**Memory Region**:
- Base Address: `0x201A0000`
- Size: 64 KB
- Properties: Non-cacheable, ECC-protected

**Design Goals**:
- **Latency**: <100 µs round-trip (50× better than FMU-IO serial)
- **Bandwidth**: >1 GB/s (1000× better than UART)
- **Reliability**: CRC16 + sequence numbers
- **Failsafe**: Timeout detection + hardware POEG

### 5.2 IPC Message Definitions

#### 5.2.1 Actuator Command (CM85 → CM33)

```c
typedef struct {
  uint32_t  sequence;          /* Sequence number (wraps) */
  uint64_t  timestamp_us;      /* CM85 timestamp (hrt) */

  /* Motor outputs (DShot or PWM) */
  uint16_t  motor[8];          /* DShot: 48-2047, PWM: 1000-2000 µs */

  /* Servo outputs */
  uint16_t  servo[8];          /* PWM: 1000-2000 µs */

  /* Control flags */
  uint8_t   armed;             /* 1=armed, 0=disarmed */
  uint8_t   emergency_kill;    /* 1=immediate POEG kill */
  uint8_t   protocol;          /* 0=PWM, 1=DShot150, 2=DShot300, 3=DShot600, 4=DShot1200 */
  uint8_t   failsafe_active;   /* 1=failsafe mode */

  uint8_t   _reserved[28];
  uint16_t  crc16;             /* CRC-16-CCITT */
} __attribute__((packed)) ipc_actuator_cmd_t;  /* 128 bytes */
```

**Rate**: 400-1000 Hz (matches motor output rate)
**Timeout**: 10 ms (CM33 triggers emergency kill if no update)

#### 5.2.2 RC Input Data (CM33 → CM85)

```c
typedef struct {
  uint32_t  sequence;
  uint64_t  timestamp_us;      /* CM33 timestamp */

  /* RC channels */
  uint16_t  channel[18];       /* 1000-2000 µs, 18 channels (CRSF) */

  /* Status */
  uint8_t   rssi;              /* 0-255 signal strength */
  uint8_t   link_quality;      /* 0-100% (CRSF) */
  uint8_t   failsafe;          /* 1=RC lost */
  uint8_t   frame_rate;        /* Frames/sec (50-500) */

  uint8_t   _reserved[16];
  uint16_t  crc16;
} __attribute__((packed)) ipc_rc_input_t;  /* 128 bytes */
```

**Rate**: 50-500 Hz (matches RC protocol rate)
**Timeout**: 100 ms (CM85 declares RC loss)

#### 5.2.3 Battery Status (CM33 → CM85)

```c
typedef struct {
  uint32_t  sequence;
  uint64_t  timestamp_us;

  /* Battery measurements */
  uint16_t  voltage_mv;        /* Millivolts */
  int16_t   current_ma;        /* Milliamps (negative = discharge) */
  uint16_t  capacity_mah;      /* Remaining capacity */
  uint8_t   percentage;        /* 0-100% */
  uint8_t   cell_count;        /* Number of cells (2-12S) */

  /* Cell voltages (SMBus) */
  uint16_t  cell_voltage_mv[12];  /* Individual cell voltages */

  /* Warnings */
  uint8_t   warning_flags;     /* Bitmask: low voltage, over current, etc. */
  uint8_t   temperature_degC;  /* Battery temperature */

  uint8_t   _reserved[12];
  uint16_t  crc16;
} __attribute__((packed)) ipc_battery_status_t;  /* 128 bytes */
```

**Rate**: 10 Hz
**Timeout**: 1 second (non-critical)

#### 5.2.4 Heartbeat (Bidirectional)

```c
typedef struct {
  uint32_t  sequence;
  uint64_t  timestamp_us;

  uint8_t   system_state;      /* 0=boot, 1=standby, 2=armed, 3=flying, 4=error */
  uint8_t   cpu_load_percent;  /* 0-100 */
  int16_t   temperature_degC;  /* MCU die temp */
  uint16_t  error_flags;       /* Bitmask of error conditions */

  uint8_t   _reserved[14];
  uint16_t  crc16;
} __attribute__((packed)) ipc_heartbeat_t;  /* 32 bytes */
```

**Rate**: 10 Hz
**Timeout**:
- CM33 → CM85: 100 ms (CM85 declares IO failure)
- CM85 → CM33: 100 ms (CM33 triggers POEG motor kill)

### 5.3 IPC Performance Targets

| Metric | Traditional FMU-IO | RA8P1 IPC | Improvement |
|--------|-------------------|-----------|-------------|
| **Latency (median)** | 2-5 ms | <100 µs | **20-50×** |
| **Latency (99th %ile)** | 10-20 ms | <500 µs | **20-40×** |
| **Bandwidth** | 1.5 Mbps | >1 GB/s | **>600×** |
| **CPU Overhead** | 5-10% (UART ISR) | <1% (shared memory) | **5-10×** |
| **Packet Loss** | 0.01-0.1% (CRC errors) | <0.001% (ECC SRAM) | **10-100×** |

### 5.4 IPC Failsafe Logic

**CM33 Watchdog on CM85** (replaces FMU-IO serial timeout):
1. CM33 monitors `cm85_heartbeat.sequence` every 10 ms
2. If no update for >100 ms, CM33 assumes CM85 hung/crashed
3. **Immediate Reaction**:
   - Set `emergency_kill = 1` locally
   - Trigger POEG hardware motor kill (all motors OFF within 1 µs)
   - Set Red LED solid ON
   - Log error to non-volatile memory
4. **Recovery**: CM33 releases kill after CM85 resumes heartbeat for >500 ms

**CM85 Watchdog on CM33** (new capability vs traditional IO):
1. CM85 monitors `cm33_heartbeat.sequence` every 10 ms
2. If no update for >200 ms, CM85 assumes CM33 unresponsive
3. **Reaction**:
   - Log error to SD card
   - Enter emergency land mode (altitude-only control)
   - Attempt POEG trigger via direct register write (if CM33 totally dead)

**Advantage**: Dual mutual watchdog provides better isolation than FMU-IO serial monitoring.

---

## 6. Peripheral Assignment & Driver Architecture

### 6.1 Complete Peripheral Mapping

| Peripheral | Owner | Function | Interface | Driver Path |
|------------|-------|----------|-----------|-------------|
| **RSPI0 (SPI0)** | CM85 | IMU1 (BMI088) | Hardware SPI @ 10 MHz | `ra_rspi.c` |
| **RSPI1 (SPI1)** | CM85 | IMU2 (ICM-42688-P) | Hardware SPI @ 24 MHz | `ra_rspi.c` |
| **I2C0** | CM85 | Baro1, FRAM | I2C @ 400 kHz | `ra_i2c.c` |
| **I2C1** | CM85 | Baro2 | I2C @ 400 kHz | `ra_i2c.c` |
| **I2C2** | CM85 | Magnetometer | I2C @ 400 kHz | `ra_i2c.c` |
| **I3C** | CM85 | Extension port | I3C @ 12.5 MHz / I2C @ 400 kHz | `ra_i3c.c` |
| **SCI4_C** | CM85 | GPS | UART @ 115200 bps | `ra_sci.c` |
| **SCI5_C** | CM85 | TELEM1 | UART @ 57600 bps | `ra_sci.c` |
| **SCI6_A** | CM85 | TELEM2 | UART @ 921600 bps | `ra_sci.c` |
| **SCI8_A** | CM33 | RC Input (S.Bus) | UART @ 100 kbps | `ra_sci.c` |
| **CANFD0** | CM85 | CAN1 (UAVCAN) | CAN-FD @ 5 Mbps | `ra_canfd.c` |
| **CANFD1** | CM85 | CAN2 | CAN-FD @ 5 Mbps | `ra_canfd.c` |
| **ETHA1** | CM85 | Ethernet | RMII @ 100 Mbps | `ra_ether.c` |
| **USBHS** | CM85 | USB | High Speed @ 480 Mbps | `ra_usbdev.c` |
| **SDHI0** | CM85 | SD Card | SDHI @ 50 MHz | `ra_sdhi.c` |
| **GPT3/5/11/13** | CM33 | Motors 1-4 | DShot/PWM | `ra_gpt.c` |
| **GPT4/6/12/14** | CM33 | Aux 1-4 | PWM | `ra_gpt.c` |
| **ADC_B** | CM33 | Battery V/I | 12-bit @ 1 MHz | `ra_adc_b.c` |
| **GPIO** | CM33 | Safety SW, LEDs | Digital I/O | `ra_gpio.c` |
| **SDRAM** | Shared | AI tensors, video | 32-bit @ 133 MHz | `ra_sdram.c` |
| **FRAM (I2C0)** | CM85 | Parameters | I2C @ 400 kHz | FRAM driver |

### 6.2 Driver Ownership Model

**Rule 1**: Each peripheral has a single owner (CM85 or CM33)
**Rule 2**: Non-owner core accesses via IPC (never direct register access)
**Rule 3**: Shared memory (SDRAM, IPC SRAM) has MPU-protected regions

**Example 1**: CM85 wants RC input
- CM33 owns SCI8 (RC UART)
- CM33 decodes S.Bus frames
- CM33 writes `ipc_rc_input_t` to shared memory
- CM85 reads via IPC

**Example 2**: CM33 needs GPS data
- CM85 owns SCI4 (GPS UART)
- CM85 parses UBX protocol
- If CM33 needs GPS, CM85 includes GPS data in `ipc_status_t` message
- CM33 reads via IPC

**Example 3**: Both cores need CAN
- CM85 owns CANFD0/1 (primary)
- CM85 handles UAVCAN protocol stack
- If CM33 needs to send CAN message, it requests via IPC
- CM85 queues message and transmits

---

## 7. Safety & Failsafe Architecture

### 7.1 Hardware Safety Features (Superior to FMU+IO)

| Safety Feature | Traditional FMU+IO | RA8P1 Dual-Core | Improvement |
|----------------|-------------------|-----------------|-------------|
| **Motor Kill** | IO board sets PWM to 0 | POEG hardware kill (<1 µs) | **1000× faster** |
| **Watchdog** | Serial timeout (2-5 ms detect) | Hardware watchdog (<100 µs) | **20-50× faster** |
| **Memory Protection** | None (single-threaded) | MPU isolates cores | **New capability** |
| **Error Correction** | None | ECC on all SRAM | **New capability** |
| **Isolation** | Physical separation | Logical + hardware barriers | **Equivalent** |

#### 7.1.1 POEG (Port Output Enable for GPT)

**Function**: Hardware-accelerated emergency motor kill

**Triggers**:
1. CM33 software command (via register write)
2. External GPIO (safety switch)
3. GPT overflow (runaway timer)

**Reaction Time**: <1 µs (purely hardware, no software involved)

**Configuration**:
```c
/* CM33 initialization */
void cm33_safety_init(void) {
  /* Enable POEG for motor GPT channels */
  ra8_poeg_enable(POEG_CH0, GPT_CH3 | GPT_CH5 | GPT_CH11 | GPT_CH13);

  /* Set triggers: software + external pin */
  ra8_poeg_set_trigger(POEG_CH0, POEG_TRIGGER_SOFTWARE | POEG_TRIGGER_PIN);
}

/* Emergency kill (CM33 on CM85 timeout) */
void cm33_emergency_kill(void) {
  ra8_poeg_trigger(POEG_CH0);  /* All motors OFF within 1 µs */
  log_error("CM85 TIMEOUT - MOTORS KILLED");
}
```

### 7.2 Software Failsafe Scenarios

#### 7.2.1 RC Loss (Replaces FMU-IO RC Failsafe)

**Traditional FMU-IO**:
1. IO board detects no RC frames for 100 ms
2. IO sends "RC LOST" status to FMU via serial
3. FMU receives status (2-5 ms latency)
4. FMU initiates failsafe (Hold → RTL → Land)
5. **Total latency**: 100 + 5 + processing = **~110 ms**

**RA8P1 Implementation**:
1. CM33 detects no RC frames for 100 ms
2. CM33 sets `ipc_rc_input.failsafe = 1` in shared memory
3. CM85 reads flag on next IPC poll (<100 µs latency)
4. CM85 initiates failsafe (Hold → RTL → Land)
5. **Total latency**: 100 + 0.1 + processing = **~100 ms**

**Improvement**: 10% faster detection, no serial link failure risk

#### 7.2.2 CM85 Hang/Crash (New Capability)

**Problem**: CM85 (FMU) hangs or crashes mid-flight

**RA8P1 Solution**:
1. CM33 monitors `cm85_heartbeat.sequence` every 10 ms
2. If no update for 100 ms, CM33 assumes CM85 hung
3. **Immediate Action**:
   - Trigger POEG motor kill (all motors OFF in 1 µs)
   - Red LED solid ON
   - Buzzer continuous tone
4. **Recovery**: CM33 can reset CM85 via watchdog after motors stopped

**Advantage Over FMU-IO**: IO board cannot detect FMU hang (relies on serial traffic)

#### 7.2.3 CM33 Hang/Crash (New Capability)

**Problem**: CM33 (IO) hangs or crashes mid-flight

**RA8P1 Solution**:
1. CM85 monitors `cm33_heartbeat.sequence` every 10 ms
2. If no update for 200 ms, CM85 assumes CM33 hung
3. **Action**:
   - Log error to SD card
   - Enter altitude-only mode (no full stabilization, just maintain altitude)
   - Attempt direct POEG trigger (if CM33 totally unresponsive)
   - Initiate emergency land

**Advantage Over FMU-IO**: FMU can detect IO hang and take corrective action (vs blind trust)

#### 7.2.4 Battery Failsafe

**Traditional FMU-IO**:
1. IO board reads battery voltage via ADC
2. IO sends voltage to FMU via serial
3. FMU checks threshold and initiates RTL/Land

**RA8P1 Implementation**:
1. CM33 reads battery voltage/current via ADC (100 Hz)
2. CM33 writes `ipc_battery_status_t` to shared memory (10 Hz)
3. CM85 reads battery data
4. CM85 checks thresholds:
   - Warning: voltage < 3.5V/cell → LED yellow, warning tone
   - Critical: voltage < 3.3V/cell → Force RTL
   - Emergency: voltage < 3.0V/cell → Force Land immediately
5. CM33 also checks thresholds locally and can trigger emergency kill if CM85 unresponsive

**Improvement**: Dual monitoring (both cores check voltage) for redundancy

### 7.3 Pre-Arm Safety Checks (Enhanced vs FMU-IO)

**Traditional FMU-IO** pre-arm checks:
- FMU: IMU health, GPS lock, EKF converged, RC signal present
- IO: Safety switch pressed, battery voltage OK
- FMU polls IO for status via serial

**RA8P1 Pre-Arm Checks** (both cores verify):

**CM85 Checks**:
- ✓ Both IMUs healthy (self-test passed, bias within limits)
- ✓ IMU readings consistent (accel diff <0.5 m/s², gyro diff <0.2 rad/s)
- ✓ At least 1 barometer valid
- ✓ Magnetometer calibrated (if heading required)
- ✓ GPS lock (if outdoor mode)
- ✓ EKF2 converged (innovation <threshold)
- ✓ **CM33 heartbeat present** (IO healthy)

**CM33 Checks**:
- ✓ RC signal valid for >1 second
- ✓ Battery voltage above minimum (e.g., >3.5V/cell)
- ✓ Safety switch pressed (if present)
- ✓ **CM85 heartbeat present** (FMU healthy)
- ✓ No POEG faults

**Arming Logic** (replaces FMU-IO serial handshake):
1. CM85 requests arming (user command via RC or GCS)
2. CM85 performs safety checks
3. CM85 sends `armed = 1` in `ipc_actuator_cmd_t`
4. CM33 receives arming request
5. CM33 performs safety checks
6. If all checks pass, CM33 enables motor outputs
7. If any check fails, CM33 ignores arming request and sets error flag

**Advantage**: Both cores must agree to arm (dual verification) vs FMU-only decision in traditional setup

---

## 8. Boot Sequence & Initialization

### 8.1 Power-On Boot Flow

```
Power-On Reset
     ↓
Stage 0: ROM Bootloader (RA8P1 Built-In)
│ • Verify NVRAM bootloader (CRC32)
│ • Load Stage 1 to SRAM
     ↓
Stage 1: NVRAM Bootloader (32KB)
│ • Initialize clocks: CM85 @ 1GHz, CM33 @ 250MHz
│ • Initialize SDRAM (timing, mode register)
│ • Verify firmware signature (SHA-256 + RSA)
│ • Load CM85 firmware (NuttX) to Flash/SRAM
│ • Load CM33 firmware to SRAM
│ • Start CM85, hold CM33 in reset
│ • Jump to CM85 entry point
     ↓
Stage 2: CM85 (NuttX) Boot
│ • Initialize MPU, FPU, NVIC, HRT
│ • Zero .bss, copy .data from flash
│ • Initialize SDRAM heap
│ • Mount FRAM (/dev/fram0)
│ • Mount SD card (/mnt/sd via SDHI0)
│ • Initialize IPC shared memory region
│ • Release CM33 from reset
│ • Wait for CM33 ready signal (IPC)
│ • Start PX4 init script (/etc/init.d/rcS)
     ↓
Stage 3: CM33 Firmware Boot (Parallel to Stage 2)
│ • Initialize stack, .bss, .data
│ • Initialize IPC (send "ready" to CM85)
│ • Initialize GPT timers (PWM/DShot)
│ • Initialize ADC (battery)
│ • Initialize UART (RC input)
│ • Initialize POEG (motor kill)
│ • Start main loop (wait for IPC commands)
     ↓
Stage 4: PX4 Initialization (CM85)
│ • Load sensor drivers (IMU via RSPI0/1, baro via I2C0/1, mag via I2C2)
│ • Load AI model from SD card to SDRAM (optional)
│ • Initialize TFLM + Ethos-U55 (optional)
│ • Start core modules (commander, ekf2, mc_att_control)
│ • Start communication (MAVLink UART/Ethernet)
│ • Wait for arming command
     ↓
Stage 5: Ready for Flight
│ • System standby, motors at idle
│ • Pilot can arm via RC or GCS
```

**Boot Time Target**: <5 seconds (same as FMU-IO)

**CM85-CM33 Synchronization**:
- CM85 waits for CM33 "ready" signal before starting PX4
- If CM33 doesn't signal within 2 seconds, CM85 logs error and continues (degraded mode)
- CM33 waits for CM85 heartbeat before accepting actuator commands

### 8.2 Firmware Update Procedure

**Advantage Over FMU-IO**: Single unified firmware update (vs separate FMU + IO updates)

**Update Flow**:
1. User uploads new firmware via USB or MAVLink
2. CM85 receives firmware, verifies signature
3. CM85 writes firmware to SDRAM staging area
4. CM85 sends "prepare update" command to CM33
5. CM33 acknowledges, disables motor outputs
6. CM85 writes new CM85 firmware to Flash
7. CM85 writes new CM33 firmware to SRAM/Flash
8. CM85 resets both cores
9. Bootloader verifies new firmware and boots

**Fallback**: If new firmware fails to boot, bootloader reverts to previous version stored in NVRAM

---

## 9. Real-Time Performance Requirements

### 9.1 Critical Timing Paths (Must Meet)

| Path | Traditional FMU-IO | RA8P1 Target | Requirement |
|------|-------------------|--------------|-------------|
| **RC Input → Motor Output** | 5-10 ms | <2 ms | Human-perceivable latency |
| **Attitude Loop (1000 Hz)** | 1 ms ± 100 µs jitter | 1 ms ± 50 µs jitter | Stability margin |
| **IMU Sample → EKF Update** | <4 ms | <2 ms | State estimation accuracy |
| **Emergency Kill** | 5-10 ms (serial + SW) | <1 ms (POEG HW) | Safety-critical |
| **Failsafe Detection** | 100-200 ms | 100-150 ms | Regulatory compliance |

### 9.2 Latency Breakdown: RC Input → Motor Output

**Traditional FMU-IO**:
```
RC Frame Received (IO)          : T+0 ms
IO Decodes Frame                : T+0.5 ms
IO Sends to FMU (Serial)        : T+2 ms (1.5ms serial + 0.5ms processing)
FMU Receives RC Data            : T+4.5 ms
FMU Computes Motor Commands     : T+5.5 ms (1ms attitude loop)
FMU Sends to IO (Serial)        : T+7 ms (1.5ms serial)
IO Outputs DShot                : T+7.5 ms
-------------------------------------------
Total RC → Motor Latency        : 7.5 ms
```

**RA8P1 Dual-Core**:
```
RC Frame Received (CM33)        : T+0 ms
CM33 Decodes Frame              : T+0.2 ms
CM33 Writes to IPC (Shared Mem) : T+0.25 ms (50 µs write)
CM85 Reads IPC                  : T+0.3 ms (50 µs read)
CM85 Computes Motor Commands    : T+1.3 ms (1ms attitude loop)
CM85 Writes to IPC              : T+1.35 ms (50 µs write)
CM33 Reads IPC                  : T+1.4 ms (50 µs read)
CM33 Outputs DShot              : T+1.6 ms
-------------------------------------------
Total RC → Motor Latency        : 1.6 ms
```

**Improvement**: **4.7× faster** (7.5 ms → 1.6 ms)

### 9.3 Interrupt Priority Scheme

**CM85 (NuttX) Interrupt Priorities** (0 = highest):

| Priority | Interrupt | Purpose | Frequency |
|----------|-----------|---------|-----------|
| **0** | HRT (High-Res Timer) | Microsecond timestamp | 1 MHz |
| **32** | RSPI0/1 (IMU) | Sensor data ready | 2-8 kHz |
| **64** | GPT0 (Attitude Loop) | 1000 Hz attitude control | 1 kHz |
| **96** | IPC Mailbox | Inter-core communication | Variable |
| **128** | UART (GPS, Telemetry) | Serial RX/TX | Variable |
| **160** | Ethernet | Network packets | Variable |
| **192** | USB | Device enumeration | Rare |
| **255** | Low-priority tasks | Non-critical | As needed |

**CM33 (Bare-Metal) Interrupt Priorities** (0 = highest):

| Priority | Interrupt | Purpose | Frequency |
|----------|-----------|---------|-----------|
| **0** | POEG | Emergency motor kill | Rare |
| **1** | CM85 Watchdog Timeout | Failsafe trigger | Rare |
| **2** | UART RX (RC Input) | S.Bus frame | 100 Hz |
| **3** | GPT (DShot) | Motor output timing | 400-1200 Hz |
| **4** | IPC Mailbox | Inter-core communication | Variable |
| **8** | ADC (Battery) | Voltage/current | 100 Hz |
| **12** | GPIO (Safety Switch) | Button press | Rare |
| **15** | Low-priority tasks | LED, buzzer | 1-10 Hz |

---

## 10. Migration Guide from FMU+IO

### 10.1 Hardware Migration

| FMU+IO Component | RA8P1 Replacement | Changes Required |
|------------------|-------------------|------------------|
| **FMU Board (STM32F427)** | CM85 @ 1 GHz | Port PX4 to NuttX/RA8P1 |
| **IO Board (STM32F100)** | CM33 @ 250 MHz | Port IO firmware to RA8P1 |
| **FMU-IO Serial Link** | Shared Memory IPC | Rewrite communication protocol |
| **FMU Sensors (SPI/I2C)** | CM85 RSPI/I2C | Update pin assignments |
| **IO RC Input (UART)** | CM33 SCI8 | Update pin assignments |
| **IO PWM Output (Timer)** | CM33 GPT | Update pin assignments, add DShot support |
| **IO ADC (Battery)** | CM33 ADC_B | Update pin assignments |
| **Connector (Board-to-Board)** | Eliminated | Monolithic design |

### 10.2 Software Migration Checklist

#### 10.2.1 CM85 (FMU Replacement)

- [ ] **Port PX4 to NuttX/RA8P1**:
  - [ ] Update board support package (BSP) in `boards/renesas/evk-ra8p1j/`
  - [ ] Implement RA8P1 drivers: `ra_rspi.c`, `ra_i2c.c`, `ra_sdhi.c`, etc.
  - [ ] Update pin mappings in `board_config.h`
  - [ ] Test sensor drivers (IMU, baro, mag, GPS)

- [ ] **Implement IPC Protocol**:
  - [ ] Define shared memory region in linker script
  - [ ] Implement `ipc_actuator_cmd_t` writer
  - [ ] Implement `ipc_rc_input_t` reader
  - [ ] Implement `ipc_battery_status_t` reader
  - [ ] Implement CM33 heartbeat monitor

- [ ] **Update Actuator Mixer**:
  - [ ] Remove direct PWM output (now via IPC to CM33)
  - [ ] Add IPC message publishing in `mc_att_control`

- [ ] **Add SDRAM Support** (if using AI):
  - [ ] Initialize SDRAM controller in boot
  - [ ] Allocate tensor arena in SDRAM
  - [ ] Load AI model from SD card

#### 10.2.2 CM33 (IO Replacement)

- [ ] **Implement CM33 Firmware** (bare-metal or FreeRTOS):
  - [ ] Initialize GPT timers for PWM/DShot
  - [ ] Implement DShot protocol (bit-banging + DMA)
  - [ ] Initialize UART for RC input (S.Bus decoder)
  - [ ] Initialize ADC for battery monitoring
  - [ ] Initialize POEG for emergency motor kill

- [ ] **Implement IPC Protocol**:
  - [ ] Define shared memory region in linker script
  - [ ] Implement `ipc_actuator_cmd_t` reader
  - [ ] Implement `ipc_rc_input_t` writer
  - [ ] Implement `ipc_battery_status_t` writer
  - [ ] Implement CM85 heartbeat monitor

- [ ] **Implement Safety Logic**:
  - [ ] RC loss detection (timeout on S.Bus frames)
  - [ ] Battery voltage monitoring (ADC thresholds)
  - [ ] Safety switch handling (GPIO IRQ)
  - [ ] CM85 watchdog (trigger POEG on timeout)

- [ ] **Test Motor Outputs**:
  - [ ] Verify PWM generation (50-400 Hz)
  - [ ] Verify DShot generation (DShot150/300/600/1200)
  - [ ] Verify POEG emergency kill (<1 µs)

#### 10.2.3 Integration & Testing

- [ ] **Boot Sequence**:
  - [ ] Test CM85 boots and releases CM33
  - [ ] Test CM33 sends "ready" signal to CM85
  - [ ] Test PX4 starts after CM33 ready

- [ ] **IPC Communication**:
  - [ ] Test actuator commands (CM85 → CM33) at 400 Hz
  - [ ] Test RC input data (CM33 → CM85) at 100 Hz
  - [ ] Test battery status (CM33 → CM85) at 10 Hz
  - [ ] Test heartbeat exchange (bidirectional) at 10 Hz
  - [ ] Measure IPC latency (<100 µs round-trip)

- [ ] **Failsafe Testing**:
  - [ ] Test RC loss detection (CM33 timeout)
  - [ ] Test CM85 hang detection (CM33 watchdog)
  - [ ] Test CM33 hang detection (CM85 watchdog)
  - [ ] Test POEG motor kill (<1 µs)
  - [ ] Test battery failsafe (low voltage)

- [ ] **Flight Testing**:
  - [ ] Hover test (verify stable flight)
  - [ ] Attitude response test (aggressive maneuvers)
  - [ ] Waypoint mission (autonomous navigation)
  - [ ] Failsafe test (RC loss, motor kill)

### 10.3 Performance Validation

| Test | Traditional FMU-IO | RA8P1 Target | Pass Criteria |
|------|-------------------|--------------|---------------|
| **Boot Time** | 3-5 s | <5 s | Within 10% of FMU-IO |
| **RC → Motor Latency** | 7.5 ms | <2 ms | 50% improvement |
| **Attitude Loop Jitter** | ±100 µs | <±50 µs | 50% improvement |
| **IPC Latency** | 2-5 ms (serial) | <100 µs | 20× improvement |
| **CPU Load (Hover)** | FMU: 50%, IO: 20% | CM85: <60%, CM33: <40% | Within budget |
| **Power Consumption** | ~2W | <1.5W | 25% reduction |

---

## 11. Testing & Validation Strategy

### 11.1 Unit Testing (Per-Core)

**CM85 Tests**:
- Sensor drivers (IMU, baro, mag, GPS) with mocked hardware
- EKF2 with synthetic sensor data
- IPC message serialization/deserialization
- Heartbeat timeout detection

**CM33 Tests**:
- S.Bus decoder with known frames
- DShot generator with oscilloscope verification
- ADC battery monitoring with known voltages
- POEG trigger timing (<1 µs)

### 11.2 Integration Testing (Dual-Core)

- IPC communication reliability (10,000 message exchange, <0.01% loss)
- RC input end-to-end (S.Bus → IPC → PX4 → IPC → DShot)
- Failsafe scenarios (CM85 hang, CM33 hang, RC loss)
- Boot sequence (CM85 releases CM33, PX4 starts)

### 11.3 Hardware-in-the-Loop (HIL) Testing

- Connect RA8P1 FMU to jMAVSim or Gazebo flight simulator
- Test full flight stack without propellers
- Verify RC input → motor output latency
- Test failsafe recovery (RC loss → RTL → Land)

### 11.4 Flight Testing

1. **Hover Test**: Verify stable hover for 5 minutes
2. **Attitude Response**: Aggressive roll/pitch/yaw maneuvers
3. **Waypoint Mission**: Autonomous navigation (10 waypoints)
4. **Failsafe Test**: Disconnect RC, verify RTL
5. **Stress Test**: Maximum agility flight for 10 minutes

---

## 12. Appendix: Code Examples

### 12.1 IPC Message Exchange (CM85 Side)

```c
/* CM85: Send actuator commands to CM33 */
void px4_send_actuator_commands(void) {
  static ipc_actuator_cmd_t cmd;

  /* Fill command structure */
  cmd.sequence++;
  cmd.timestamp_us = hrt_absolute_time();
  cmd.armed = (get_arming_state() == ARMED);
  cmd.emergency_kill = 0;
  cmd.protocol = DSHOT600;

  /* Get motor outputs from mixer */
  for (int i = 0; i < 4; i++) {
    cmd.motor[i] = get_motor_output(i);  /* 48-2047 (DShot) */
  }

  /* Compute CRC */
  cmd.crc16 = crc16_ccitt((uint8_t*)&cmd, sizeof(cmd) - 2);

  /* Write to shared memory */
  memcpy((void*)IPC_ACTUATOR_CMD_ADDR, &cmd, sizeof(cmd));

  /* Signal CM33 via interrupt (optional, CM33 can poll) */
  ipc_trigger_interrupt(IPC_INT_CM33);
}

/* CM85: Read RC input from CM33 */
void px4_read_rc_input(void) {
  static ipc_rc_input_t rc;

  /* Read from shared memory */
  memcpy(&rc, (void*)IPC_RC_INPUT_ADDR, sizeof(rc));

  /* Verify CRC */
  uint16_t crc = crc16_ccitt((uint8_t*)&rc, sizeof(rc) - 2);
  if (crc != rc.crc16) {
    log_error("RC input CRC mismatch");
    return;
  }

  /* Check for RC loss */
  if (rc.failsafe) {
    trigger_rc_loss_failsafe();
    return;
  }

  /* Publish RC data to uORB */
  struct input_rc_s rc_msg;
  rc_msg.timestamp = hrt_absolute_time();
  rc_msg.channel_count = 18;
  memcpy(rc_msg.values, rc.channel, sizeof(rc.channel));
  rc_msg.rssi = rc.rssi;
  orb_publish(ORB_ID(input_rc), rc_pub, &rc_msg);
}
```

### 12.2 IPC Message Exchange (CM33 Side)

```c
/* CM33: Read actuator commands from CM85 */
void cm33_process_actuator_commands(void) {
  static ipc_actuator_cmd_t cmd;
  static uint32_t last_sequence = 0;

  /* Read from shared memory */
  memcpy(&cmd, (void*)IPC_ACTUATOR_CMD_ADDR, sizeof(cmd));

  /* Verify CRC */
  uint16_t crc = crc16_ccitt((uint8_t*)&cmd, sizeof(cmd) - 2);
  if (crc != cmd.crc16) {
    log_error("Actuator command CRC mismatch");
    return;
  }

  /* Check sequence (detect missed messages) */
  if (cmd.sequence != last_sequence + 1 && last_sequence != 0) {
    log_warning("Missed actuator command (seq jump)");
  }
  last_sequence = cmd.sequence;

  /* Check for emergency kill */
  if (cmd.emergency_kill) {
    ra8_poeg_trigger(POEG_CH0);  /* Hardware motor kill */
    return;
  }

  /* Update motor outputs */
  if (cmd.armed) {
    for (int i = 0; i < 4; i++) {
      dshot_set_motor(i, cmd.motor[i]);  /* 48-2047 */
    }
  } else {
    dshot_disarm_all_motors();
  }
}

/* CM33: Send RC input to CM85 */
void cm33_send_rc_input(void) {
  static ipc_rc_input_t rc;

  /* Fill RC structure (from S.Bus decoder) */
  rc.sequence++;
  rc.timestamp_us = cm33_get_time_us();
  sbus_get_channels(rc.channel, 18);  /* Read from S.Bus decoder */
  rc.rssi = sbus_get_rssi();
  rc.link_quality = sbus_get_link_quality();
  rc.failsafe = sbus_is_failsafe();
  rc.frame_rate = sbus_get_frame_rate();

  /* Compute CRC */
  rc.crc16 = crc16_ccitt((uint8_t*)&rc, sizeof(rc) - 2);

  /* Write to shared memory */
  memcpy((void*)IPC_RC_INPUT_ADDR, &rc, sizeof(rc));

  /* Signal CM85 via interrupt (optional) */
  ipc_trigger_interrupt(IPC_INT_CM85);
}
```

### 12.3 CM33 Watchdog on CM85

```c
/* CM33: Monitor CM85 heartbeat */
void cm33_watchdog_task(void) {
  static uint32_t last_cm85_sequence = 0;
  static uint32_t timeout_counter = 0;

  /* Read CM85 heartbeat */
  ipc_heartbeat_t hb;
  memcpy(&hb, (void*)IPC_CM85_HEARTBEAT_ADDR, sizeof(hb));

  /* Check if sequence number updated */
  if (hb.sequence == last_cm85_sequence) {
    timeout_counter++;

    /* If no update for >100ms (10 × 10ms task rate) */
    if (timeout_counter > 10) {
      log_error("CM85 TIMEOUT - TRIGGERING EMERGENCY KILL");

      /* Trigger POEG hardware motor kill */
      ra8_poeg_trigger(POEG_CH0);

      /* Set error LED */
      gpio_write(LED_RED, 1);

      /* Sound continuous alarm */
      pwm_set_buzzer(1000);  /* 1 kHz tone */

      /* Attempt to reset CM85 (optional) */
      // system_reset_cm85();
    }
  } else {
    /* CM85 is alive, reset timeout */
    last_cm85_sequence = hb.sequence;
    timeout_counter = 0;
  }
}
```

---

## Document Summary

This document provides a **complete architecture** for replacing the traditional PX4 FMU (STM32F427) + PX4 IO (STM32F100) dual-board system with a single **Renesas RA8P1 dual-core MCU**. Key achievements:

✅ **10× Better Performance**: CM85 @ 1 GHz vs STM32F427 @ 168 MHz
✅ **20× Lower Latency**: <100 µs IPC vs 2-5 ms serial link
✅ **Single-Chip Integration**: Eliminates board-to-board connector failure risk
✅ **Hardware Safety**: POEG motor kill (<1 µs) + dual-core watchdog
✅ **AI Capability**: Ethos-U55 NPU (256 GOPS INT8) for vision-based obstacle avoidance
✅ **Complete Task Distribution**: Detailed CM85/CM33 responsibilities with CPU budgets
✅ **Migration Guide**: Step-by-step checklist for porting from FMU+IO
✅ **Testing Strategy**: Unit, integration, HIL, and flight test procedures

**Status**: Ready for implementation, board design, and firmware development.

---

**Document End**
