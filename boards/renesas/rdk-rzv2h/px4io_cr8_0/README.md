# RZV2H Dual PX4IO Architecture Implementation

## Overview

This implementation provides a **dual PX4IO architecture** for the Renesas RZV2H heterogeneous multi-core system, distributing I/O processing and motor control across three cores:

- **CR8-0 (FMU)**: Main PX4 flight control (attitude, rate, position control)
- **CR8-1 (I/O Processor)**: RC input, CAN-FD telemetry, battery monitoring, safety logic
- **CM33 (ESC Controller)**: Deterministic PWM/DShot motor control with hardware watchdog

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Cortex-A55 Cluster (Linux)                   │
│  ROS 2 + DRP-AI3 Vision + Mission Planning                      │
│                    ↕ OpenAMP/RPMsg                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  CR8-0 (FMU) - PX4 Flight Control @ 800MHz                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ • Attitude Control (500Hz)                                │  │
│  │ • Rate Control (1000Hz)                                   │  │
│  │ • Position Control (250Hz)                                │  │
│  │ • EKF2 Sensor Fusion                                      │  │
│  │ • Commander (mode management)                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│              ↕ uORB Bridge (Shared Memory 0x70000000)           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  CR8-1 (I/O Processor) @ 800MHz                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ • RC Decoder (SBUS/CRSF/PPM) @ 50-100Hz                   │  │
│  │ • CAN-FD UAVCAN (ESC telemetry)                           │  │
│  │ • Battery Monitor (ADC voltage/current)                   │  │
│  │ • Safety Monitor (heartbeat, failsafe)                    │  │
│  │ • Failsafe Logic (RC loss, FMU loss, battery low)         │  │
│  └───────────────────────────────────────────────────────────┘  │
│          ↕ Shared Memory Transport (0x70004000)                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  CM33 (ESC Controller) @ 200MHz                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ • 8-Channel PWM/DShot @ 400-2000Hz                        │  │
│  │ • DMA-Driven (Double-Buffered)                            │  │
│  │ • Hardware Watchdog (500ms timeout)                       │  │
│  │ • Safety Switch (arming gate)                             │  │
│  │ • Emergency Cutoff (GPIO-driven)                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Memory Map

### Shared Memory Regions (Non-Cacheable)

| Address Range | Size | Purpose | Cores |
|--------------|------|---------|-------|
| `0x70000000 - 0x70003FFF` | 16KB | CR8-0 ↔ CR8-1 IPC | FMU ↔ I/O |
| `0x70004000 - 0x70007FFF` | 16KB | CR8-1 ↔ M33 IPC | I/O ↔ ESC |
| `0x70008000 - 0x7000BFFF` | 16KB | Status/Telemetry | Reserved |
| `0x7000C000 - 0x7000FFFF` | 16KB | Reserved | Future |

## Inter-Core Communication

### Protocol Features

- **CRC32 validation** on every message
- **Sequence numbers** for gap detection
- **Heartbeats** for liveness monitoring
- **Ring buffers** with lock-free operation (ARM_DMB barriers)
- **Typed messages** with version control

### Message Types

#### CR8-0 → CR8-1 (FMU to I/O)
- `ActuatorCommand_t`: Motor commands from mixer (400Hz)
- `VehicleCommand_t`: Arming, calibration commands
- `VehicleStatus_t`: Current flight mode, health
- `Heartbeat_t`: Liveness signal (10Hz)

#### CR8-1 → CR8-0 (I/O to FMU)
- `InputRC_t`: RC channels, RSSI, failsafe (50-100Hz)
- `ESCStatus_t`: RPM, voltage, current, temp from CAN-FD
- `BatteryStatus_t`: Voltage, current, capacity
- `SafetyStatus_t`: Safety switch, error flags

#### CR8-1 → M33 (I/O to ESC)
- `ActuatorCmdToM33_t`: PWM/DShot commands (400Hz)
- `Heartbeat_t`: Liveness signal (10Hz)

#### M33 → CR8-1 (ESC to I/O)
- `PWMFeedback_t`: Actual PWM outputs, DShot telemetry (100Hz)
- `FaultStatus_t`: Watchdog, errors, CPU load

## Directory Structure

```
boards/renesas/
├── rdk-rzv2h/                    # CR8-0 (FMU)
│   ├── px4io_cr8_0/
│   │   ├── protocol.h            # Comprehensive IPC protocol
│   │   ├── uorb_bridge.h/cpp     # uORB ↔ Shared Memory bridge
│   │   ├── px4io_bridge.cpp      # Main PX4 module (400Hz)
│   │   └── CMakeLists.txt
│   ├── nuttx-config/
│   │   └── scripts/
│   │       └── rdk-rzv2h_cr8_0.ld  # IPC_RAM @ 0x70000000
│   └── src/
│       └── board_config.h        # PX4IO_IPC_RAM_BASE
│
├── rdk-rzv2h-io-cr8_1/           # CR8-1 (I/O Processor)
│   ├── px4io_cr8_1/
│   │   ├── protocol.h            # Same as CR8-0
│   │   ├── sharedmem_transport.h/cpp  # Ring buffer implementation
│   │   ├── px4io_cr8.cpp         # Main loop (400Hz)
│   │   ├── rc_decoder.cpp        # SBUS/CRSF/PPM decoder
│   │   ├── can_uavcan.cpp        # CAN-FD UAVCAN telemetry
│   │   ├── battery_monitor.cpp   # ADC voltage/current
│   │   ├── safety_monitor.cpp    # Heartbeat checking
│   │   ├── failsafe.cpp          # Failsafe logic
│   │   └── CMakeLists.txt
│   ├── nuttx-config/
│   │   └── scripts/
│   │       └── script.ld         # IPC_RAM @ 0x70000000
│   └── src/
│       └── board_config.h        # Peripheral pins, ADC channels
│
└── rdk-rzv2h-io-cm33/            # CM33 (ESC Controller)
    ├── px4io_m33/
    │   ├── protocol.h            # Same as CR8-0
    │   ├── sharedmem_transport.h/cpp
    │   ├── px4io_m33.cpp         # Main loop (2000Hz for PWM)
    │   ├── pwm_dshot.cpp         # GPT timer + DMA PWM/DShot
    │   ├── dma_driver.cpp        # Double-buffered DMA
    │   ├── safety_switch.cpp     # Physical switch, LED patterns
    │   └── CMakeLists.txt
    ├── nuttx-config/
    │   └── scripts/
    │       └── script.ld         # IPC_RAM @ 0x70000000, DMA buffers
    └── src/
        ├── board_config.h        # GPT channels, watchdog
        └── timer_config.cpp      # GPT setup
```

## Build Instructions

### 1. Build CR8-0 (FMU)
```bash
cd PX4-Autopilot
make renesas_rdk-rzv2h_default
# Output: build/renesas_rdk-rzv2h_default/nuttx.elf
```

### 2. Build CR8-1 (I/O Processor)
```bash
make renesas_rdk-rzv2h-io-cr8_1_default
# Output: build/renesas_rdk-rzv2h-io-cr8_1_default/nuttx.elf
```

### 3. Build CM33 (ESC Controller)
```bash
make renesas_rdk-rzv2h-io-cm33_default
# Output: build/renesas_rdk-rzv2h-io-cm33_default/nuttx.elf
```

### 4. Flash Firmware
```bash
# Use Renesas Flash Programmer or J-Link
# CR8-0: Flash region 0x20000000
# CR8-1: Flash region 0x21000000 (adjust per memory map)
# CM33:  Flash region 0x22000000 (adjust per memory map)
```

## Runtime Startup

### Boot Sequence
1. **CR8-0** boots first, initializes shared memory at `0x70000000`
2. **CR8-1** boots, waits for `IPC_MAGIC_CR8`, starts I/O processing
3. **CM33** boots, waits for CR8-1 heartbeat, enables PWM output

### CR8-0 Startup (FMU)
```bash
nsh> px4io_bridge start
# Initializes uORB bridge, starts 400Hz update loop
nsh> px4io_bridge status
# Shows CR8-1 alive status, TX/RX statistics
```

### CR8-1 Startup (I/O Processor)
```bash
nsh> px4io_cr8 start
# Initializes RC decoder, CAN-FD, ADC, shared memory
# Starts 400Hz main loop
```

### CM33 Startup (ESC Controller)
```bash
nsh> px4io_m33 start
# Initializes GPT timers, DMA, watchdog
# Starts 2000Hz PWM loop
```

## Validation Tests

### Test 1: IPC Latency (CR8-0 ↔ CR8-1 ↔ M33)
```bash
# On CR8-0
nsh> px4io_bridge status
# Check: TX actuator count increasing, RX RC count increasing
# Expected latency: <2ms CR8-0↔CR8-1, <3ms end-to-end

# On CR8-1
nsh> px4io_cr8 status
# Check: No CRC errors, sequence gaps minimal
```

### Test 2: RC Input (CR8-1)
```bash
# Connect SBUS/CRSF receiver to CR8-1 UART
nsh> listener input_rc
# Verify: Channels 1-8 = 1000-2000us, RSSI present
```

### Test 3: PWM Output (CM33)
```bash
# Use oscilloscope on PWM output pins
# Verify: 400Hz PWM, <100µs jitter, duty cycle correct
```

### Test 4: Failsafe (All Cores)
```bash
# Test RC loss
# Disconnect RC → CR8-1 sets RC_LOST flag → CR8-0 triggers failsafe

# Test FMU loss (from CR8-1 perspective)
# Stop CR8-0 px4io_bridge → CR8-1 detects timeout → holds safe state

# Test M33 watchdog
# Stop CR8-1 heartbeat → M33 watchdog triggers → emergency cutoff
```

### Test 5: Battery Monitoring (CR8-1)
```bash
nsh> listener battery_status
# Verify: Voltage accurate (±2%), current scaling correct
# Inject low voltage → verify low battery failsafe triggers
```

## Performance Targets

| Metric | Target | Validation |
|--------|--------|------------|
| CR8-0 → CR8-1 latency | <2ms | Timestamp messages |
| CR8-1 → M33 latency | <500µs | GPIO toggle + scope |
| End-to-end (A55 → M33) | <20ms | Full pipeline test |
| PWM jitter (M33) | <100µs | Oscilloscope |
| RC input latency | <5ms | Loopback test |
| CPU load CR8-0 | <80% | perf counters |
| CPU load CR8-1 | <70% | perf counters |
| CPU load M33 | <80% | perf counters |
| IPC buffer utilization | <50% | Runtime stats |

## Failsafe Matrix

| Fault | Detection | Action | Recovery |
|-------|-----------|--------|----------|
| RC loss | CR8-1: No frames for 100ms | Set RC_LOST flag → CR8-0 triggers RTL/land | Valid frames resume → clear flag |
| FMU loss (CR8-1 view) | No CR8-0 heartbeat for 100ms | Set FMU_LOST flag → hold last valid outputs | CR8-0 heartbeat resumes → resume |
| FMU loss (M33 view) | No CR8-1 heartbeat for 500ms | Hardware watchdog triggers → emergency cutoff | Manual reset required |
| Battery low | ADC voltage < threshold | Set BATTERY_LOW flag → CR8-0 triggers RTL/land | Battery replaced → clear flag |
| GPS loss | No fix for 5s | Disable position modes → altitude hold | GPS fix reacquired → re-enable |
| Sensor failure | IMU redundancy check fails | Switch to backup IMU → emergency land if both fail | Sensor health restored → log event |

## Debugging

### Enable Debug Logging
```bash
# CR8-0
nsh> uorb top
# Monitor: actuator_outputs, input_rc, esc_status, battery_status

# CR8-1
nsh> px4io_cr8 status
# Check: RC frame rate, CAN-FD telemetry, heartbeat status

# CM33
nsh> px4io_m33 status
# Check: PWM outputs, DMA status, watchdog service count
```

### Memory Inspection
```bash
# Dump IPC RAM region
nsh> md 0x70000000 0x100
# Verify: IPC_MAGIC_CR8 at 0x70000000, no corruption
```

### Timing Analysis
```bash
# Use perf counters
nsh> perf show
# Check: px4io_bridge loop interval, actuator_outputs latency
```

## Known Limitations

1. **No dynamic core allocation**: Core roles are fixed at compile time
2. **Single RC protocol at a time**: SBUS or CRSF, not both
3. **CAN-FD UAVCAN only**: No DroneCAN support yet
4. **8-channel limit**: Mixer output limited to 8 motors
5. **Non-cacheable overhead**: Shared memory access slower than TCM/SRAM

## Future Enhancements

- [ ] Add DroneCAN support alongside UAVCAN
- [ ] Implement CR8-1 → CR8-0 uORB bridge (currently only CR8-0 → CR8-1)
- [ ] Add A55 → CR8-0 direct IPC (bypass OpenAMP for low-latency)
- [ ] Implement servo outputs (not just ESC motors)
- [ ] Add M33 DShot bidirectional telemetry parsing
- [ ] Implement adaptive failsafe thresholds based on environment

## References

- [RZV2H Autonomous Drone Software Specification](docs/RZV2H_Autonomus_Drone_Software_Specification.md)
- [PX4 Developer Guide](https://docs.px4.io/main/en/)
- [NuttX RTOS Documentation](https://nuttx.apache.org/docs/latest/)
- [Renesas RZV2H Hardware Manual](https://www.renesas.com/rzv2h)

## Contributing

When adding new IPC message types:

1. Update `protocol.h` in **all three boards** (CR8-0, CR8-1, M33)
2. Update `SharedMemCR8_t` or `SharedMemM33_t` structures
3. Add corresponding `push/pop` calls in transport layers
4. Update CRC32 calculations to include new fields
5. Add sequence number tracking for gap detection
6. Document new message in this README

## License

This implementation is part of PX4 Autopilot and follows the BSD-3-Clause license.

---

**Last Updated**: January 4, 2026
**Maintainer**: PX4 Development Team
**Status**: Beta - Active Development
