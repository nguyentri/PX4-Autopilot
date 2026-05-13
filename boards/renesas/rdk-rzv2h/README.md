# PX4 BSP for Renesas RDK-RZV2H

This document describes the PX4 Board Support Package (BSP) created for the Renesas RDK-RZV2H development board.

## Overview

The RDK-RZV2H BSP enables PX4 flight controller functionality on the Renesas RZV2H MPU using the Cortex-R8 (CR8_0) core for real-time flight control.

## Hardware Configuration

### Processor
- **MCU**: Renesas RZV2H (R9A09G057)
- **Core**: ARM Cortex-R8 (CR8_0) @ 800MHz
- **Architecture**: ARMv7-R with FPU
- **Memory**: 524KB RAM at 0x22060000

### Sensors
| Sensor | Interface | Configuration |
|--------|-----------|---------------|
| MPU9250 (IMU) | RSPI0 | CS=P93, INT=P50 (GPIO25) |
| BMP280 (Baro) | SCI-mode I2C7 | Address 0x76, P76/P77 (GPIO02/03) |

### Serial Ports
| Port | SCI | Pins        | Device      | Function |
|------|-----|-------------|-------------|----------|
| ttyS3 | SCI3 | -           | /dev/ttyS3  | NuttX standalone NSH console |
| ttyS4 | SCI4 | P70/P71     | /dev/ttyS4  | TFminiPlus LiDAR |
| ttyS5 | SCI5 | P72/P73     | /dev/ttyS5  | Sik Telemetry v3 |
| ttyS6 | SCI6 | P75         | /dev/ttyS6  | fs-a8s RC Input |
| ttyS9 | SCI9 | P82/P83     | /dev/ttyS9  | GPS M10 |

### I2C Buses
| Bus | SCI | Pins     | Device      |
|-----|-----|----------|-------------|
| I2C7 | SCI-I2C7 | P76/P77 | BMP280 Barometer (0x76) |

### SPI Buses
| Bus  | Pins              | Device        |
|------|-------------------|---------------|
| RSPI0 | P90/P91/P92      | MPU9250 IMU   |
|       | P93 (SSLA0)      | MPU9250 NCS   |
| INT  | P50               | MPU9250 INT   |

### PWM Outputs (4 ESC channels)

PWM outputs use the RZV2H GPT (General Purpose Timer) peripheral for ESC control.

| PX4 Channel | GPT Timer | Output   | Pin  | GPIO Macro               | Header Pin |
|-------------|-----------|----------|------|--------------------------|------------|
| PWM0 (ESC1) | GPT6      | GTIOC6A  | PA4  | GPIO_GTIOC6A_PA_4_M11    | GPIO12     |
| PWM1 (ESC2) | GPT7      | GTIOC7B  | PA7  | GPIO_GTIOC7B_PA_7_M11    | GPIO13     |
| PWM2 (ESC3) | GPT9      | GTIOC9A  | P96  | GPIO_GTIOC9A_P9_6_M9     | GPIO19     |
| PWM3 (ESC4) | GPT10     | GTIOC10B | P53  | GPIO_GTIOC10B_P5_3_M11   | GPIO06     |

**PWM Configuration:**
- Default Frequency: 400 Hz (configurable 50-500 Hz)
- Pulse Width Range: 1000-2000 µs (standard PWM servo range)
- Timer Clock: 120 MHz (PCLKD)
- Resolution: ~120 ticks/µs (sufficient for 1µs precision)

**DShot Support:**
- Deferred for v1 until DMAC/cache coherency and GPT event generation are validated.

### LEDs
| LED | Port | Pin | Function |
|-----|------|-----|----------|
| LED1 | P0 | 0 | Status (Blue) |
| LED2 | P0 | 1 | Armed (Green) |
| LED3 | P0 | 2 | Red |
| LED4 | P0 | 3 | - |

## File Structure

### Board Configuration (`boards/renesas/rdk-rzv2h/`)
```
boards/renesas/rdk-rzv2h/
├── default.px4board          # Main board configuration
├── firmware.prototype        # Firmware metadata
├── Kconfig                   # Board Kconfig options
├── init/
│   ├── rc.board_defaults     # Boot defaults script
│   ├── rc.board_defaults.cmds # Initialization commands
│   └── rc.offline_sensor_check
├── nuttx-config/
│   └── nsh/
│       └── defconfig         # NuttX kernel configuration
└── src/
    ├── CMakeLists.txt
    ├── board_config.h        # Hardware definitions
    ├── board_common.c        # Common board functions
    ├── i2c.cpp               # I2C bus support
    ├── init.c                # Board initialization
    ├── led.c                 # LED control
    ├── spi.cpp               # SPI bus support
    ├── system_stubs.c        # System stub functions
    └── timer_config.cpp      # GPT timer configuration
```

### Platform Support (`platforms/nuttx/src/px4/renesas/rzv2h/`)
```
platforms/nuttx/src/px4/renesas/rzv2h/
├── CMakeLists.txt            # Main CMake
├── include/
│   └── px4_arch/
│       ├── hw_description.h      # GPIO/Timer namespaces
│       ├── io_timer.h            # Timer API
│       ├── io_timer_hw_description.h # Timer hardware abstraction
│       └── micro_hal.h           # Platform abstraction
├── board_critmon/            # Critical section monitoring
├── board_hw_info/            # Hardware info (version)
├── board_reset/              # Board reset handling
├── hrt/                      # High-resolution timer
├── io_pins/                  # PWM/IO timer driver
├── led_pwm/                  # LED PWM support
├── micro_hal/                # HAL implementation
├── spi/                      # SPI platform support
└── version/                  # Board version detection
```

## Building

### Prerequisites
- ARM Cortex-R8 toolchain (arm-none-eabi-gcc)
- NuttX RTOS with RZV2H support
- PX4 build environment

### Build Command
```bash
make renesas_rdk-rzv2h_default
```

### Clean Build
```bash
make clean
make renesas_rdk-rzv2h_default
```

## Configuration Options

### Board Kconfig (`boards/renesas/rdk-rzv2h/Kconfig`)
- `BOARD_RDK_RZV2H`: Enable board support
- `BOARD_RDK_RZV2H_PWM_CHANNELS`: Number of PWM channels (1-8, default 4)
- `BOARD_RDK_RZV2H_HAS_BARO`: Enable barometer (default y)
- `BOARD_RDK_RZV2H_HAS_IMU`: Enable IMU (default y)
- `BOARD_RDK_RZV2H_HAS_MAG`: Enable magnetometer (default y)

### Key PX4board Options
- Flight modules: EKF2, Commander, Navigator, MC attitude/position control
- Sensors: MPU9250, BMP280
- Outputs: PWM (4 channels), RC input (SBUS)
- Interfaces: MAVLink, GPS

## Initialization Sequence

1. `rzv_board_initialize()` - Early hardware init
2. `board_app_initialize()` - PX4 platform init
3. `rdk_rzv2h_gpio_initialize()` - GPIO configuration
4. `rdk_rzv2h_timer_initialize()` - GPT timer setup
5. SPI/I2C bus initialization
6. Sensor driver startup (via rc.board_defaults.cmds)

## Default Parameters (rc.board_defaults.cmds)

```
# Quadcopter X configuration
param set-default SYS_AUTOSTART 4001

# Sensor parameters
param set-default IMU_GYRO_CUTOFF 40
param set-default IMU_DGYRO_CUTOFF 20

# PWM Configuration
pwm_out mode -p 400      # 400Hz ESC frequency
param set-default PWM_MAIN_RATE 400

# Rate controller tuning
param set-default MC_ROLLRATE_P 0.130
param set-default MC_PITCHRATE_P 0.130
param set-default MC_YAWRATE_P 0.100
```

## Integration Notes

### Clock Configuration
- External crystal: 24MHz
- PCLKD for GPT timers: 120MHz
- HRT resolution: 1µs

### Memory Map
- RAM: 0x22060000, 524KB
- DTCM: 16KB (for fast data)
- ITCM: 16KB (for fast code)

### DMA
- Disabled for v1 flight-critical SPI/I2C/DShot paths until cache coherency is validated.
- Future enhancement for sensor data acquisition.

### Parameter Storage
- Target backend: CR8-owned XSPI flash mounted with LittleFS at `/fs`.
- Current build path: `/fs/params`.
- Runtime persistence still requires an RZV2H XSPI MTD lower-half and mount hook.

## ESC/PWM Validation

### Test Commands

Test PWM outputs using the NSH console:

```bash
# Test single channel (channel 1, 1100µs pulse)
pwm_out test -c 1 -p 1100

# Test single channel at minimum (1000µs)
pwm_out test -c 1 -p 1000

# Test all channels at armed value
pwm_out arm

# Disarm all channels
pwm_out disarm
```

### Expected Results

| Command | Expected Behavior |
|---------|-------------------|
| `pwm_out test -c 1 -p 1100` | PWM0 (PA4) outputs 1100µs pulse at 400Hz |
| `pwm_out test -c 1 -p 1000` | PWM0 outputs minimum 1000µs pulse |
| `pwm_out arm` | All 4 channels output armed value |
| `pwm_out disarm` | All channels return to 1000µs (disarmed) |

### Signal Verification with Oscilloscope

Connect oscilloscope to PWM pins and verify:
- Frequency: 400 Hz (2.5ms period)
- Pulse width: 1000-2000 µs range
- Rising/falling edge: Clean, no ringing
- Signal level: 3.3V logic

### DShot Mode (Optional)

To use DShot instead of PWM:

```bash
# Stop PWM output first
pwm_out stop

# Start DShot at 600kHz
dshot start -m 600

# Test motor spin (throttle 0-2047)
dshot motor_test -m 1 -p 100
```

## Troubleshooting

### PWM Not Working

1. **Check GPIO configuration**: Verify pins are configured in Mode 1 (GPT peripheral)
2. **Check timer initialization**: `rdk_rzv2h_timer_initialize()` should complete without errors
3. **Verify clock**: PCLKD should be 120MHz for correct PWM timing

### Motor Spin at Boot

1. Check `PWM_MAIN_DISx` parameters are set to 1000 (disarmed value)
2. Verify `up_pwm_servo_arm()` is not called before arming

### Arming Fails

1. Check `commander status` for arming blockers
2. Verify `COM_ARM_WO_GPS 1` is set for GPS-less operation
3. Check sensor calibration status

1. No USB support (console via SCI3 only)
2. No CAN bus support
3. Battery monitoring ADC not implemented
4. Single I2C bus (I2C7 only)
5. No hardware safety switch

## References

- [PX4 FreeRTOS+FSP Reference](.refs/rzv2h_px4_freertos_fsp/)
- [NuttX RZV2H Board](platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/)
- [RA8P1 Board](boards/renesas/evk-ra8p1/) - Reference implementation
- [RZV2H Technical Manual](https://www.renesas.com/rzv2h)

## Authors

PX4 Development Team - 2025
