# PX4 BSP for Renesas RDK-RZV2H

This document describes the PX4 Board Support Package (BSP) created for the Renesas RDK-RZV2H development board.

## Overview

The RDK-RZV2H BSP enables PX4 flight controller functionality on the Renesas
RZV2H MPU using the Cortex-R8 (CR8_0) core for real-time flight control. The
default image is independent of CA55, CR8_1, CM33, OpenAMP, and IPCC.
Multicore transports remain opt-in final-milestone features.

The board also ships `renesas_rdk-rzv2h_core_only`, a deterministic rollback
image built from `core_only.px4board`, `nuttx-config/core_only/defconfig`, and
the generated `ROMFS/rdk-rzv2h-core-only` startup tree. It retains
RTT/HRT/work queues/parameters/uORB and the diagnostic commands needed to
inspect failures, auto-starts `pwm_out`, and excludes payload UARTs,
SPI/I2C/RC/GPS/IMU/baro drivers, flight-module startup, and serial consumers.

The board also ships `renesas_rdk-rzv2h_sih`, a CR8-0 FC-SIH demo with a
bounded on-target transcript. It is built from `sih.px4board`,
`nuttx-config/sih/defconfig`, and the compact
`ROMFS/rdk-rzv2h-sih` startup tree. It starts simulated accel/gyro/baro/mag/GPS
paths through HIL sensors and `pwm_out_sim`, but it does not start physical
payload/sensor buses, GPT/PWM output, or `control_allocator`. SCI4 remains the
interactive shell. Cold-cycle provenance, physical pin-safety measurement,
and soak validation remain open.

## Hardware Configuration

### Processor
- **MCU**: Renesas RZV2H (R9A09G057)
- **Core**: ARM Cortex-R8 (CR8_0) @ 800MHz
- **Architecture**: ARMv7-R with FPU
- **Linked memory**: CR8-0 private ITCM/DTCM plus 8 MiB cacheable DDR at
  0x40800000 and 8 MiB non-cacheable DDR at 0x41000000. The legacy
  `CONFIG_RAM_*` values are not the PX4 link/heap authority.

### Inter-core Topology
| Role | Processor | Image | Communication |
|------|-----------|-------|---------------|
| Primary PX4 | CR8_0 | `renesas_rdk-rzv2h_default` | Independent local PX4; optional future OpenAMP/RPMsg |
| Linux/OpenAMP host | CA55 | External Linux image | MHU channel 3 + resource table at `0x42f00000` |
| Optional PX4IO | CM33 | `renesas_rdk-rzv2h-io-cm33_default` | Standalone shared-memory PX4IO image |
| Optional PX4IO | CR8_1 | `renesas_rdk-rzv2h-io-cr8_1_default` | Standalone shared-memory PX4IO image |

The OpenAMP layout follows the Renesas FreeRTOS/FSP reference:

| Resource | Address / Name |
|----------|----------------|
| Resource table | `0x42f00000` |
| MHU shared memory | `0x42f01000` |
| RPMsg memory window | `0x43000000` size `0x00800000` |
| Vring0 / Vring1 | `0x43000000` / `0x43050000` |
| RPC endpoint | `rpmsg-service-0`, CR8 local address `0x0` |

### Sensors
| Sensor | Interface | Configuration |
|--------|-----------|---------------|
| MPU9250 (IMU) | RSPI0 | CS=P93, INT=P50 (GPIO25) |
| BMP280 (Baro) | SCI-mode I2C7 | Address 0x76, P76/P77 (GPIO02/03) |

### Serial Ports
| Port | SCI | Pins        | Device      | Function |
|------|-----|-------------|-------------|----------|
| ttyS4 | SCI4 | P70/P71     | /dev/ttyS4  | TFminiPlus LiDAR |
| ttyS5 | SCI5 | P72/P73     | /dev/ttyS5  | Sik Telemetry v3 for MAVLink/QGroundControl |
| ttyS6 | SCI6 | P75         | /dev/ttyS6  | FS-A8S SBUS, 100000 8E2; external NPN inverter |
| ttyS9 | SCI9 | P82/P83     | /dev/ttyS9  | GPS M10 |

SCI3 is not an active console on the RDK-RZV2H board. The board uses
SCI4 for the standalone CR8-0 NuttX shell, and integrated PX4 diagnostics
use RTT rather than SCI3.

The integrated PX4 images expose SCI4 as the generated `EXT2` serial role and
assign `SENS_TFMINI_CFG=401`, so common `rc.serial` starts TFmini on
`/dev/ttyS4`. The standalone NuttX shell is a separate image that owns SCI4
instead.

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
| PWM2 (ESC3) | logical GPT9  | GTIOC9A  | P96  | GPIO_GTIOC9A_P9_6_M9     | GPIO19     |
| PWM3 (ESC4) | logical GPT10 | GTIOC10B | P53  | GPIO_GTIOC10B_P5_3_M11   | GPIO06     |

**PWM Configuration:**
- Default Frequency: 400 Hz (configurable 50-500 Hz)
- Pulse Width Range: 1000-2000 µs (standard PWM servo range)
- Timer Clock: runtime P4CLK from NuttX `rzv_get_gpt_clock_hz()`; nominal 200 MHz
- Resolution: nominal 200 ticks/µs at 200 MHz
- Logical GPT9/GPT10 map to physical R_GPT11/R_GPT12 register blocks.
- The default PX4 board path exposes 50-500 Hz analog PWM only and rejects
  `PWM_MAIN_TIMx=-1`. OneShot ownership plumbing is internal and has no board
  trigger path; standalone NuttX finite pulse-count PWM is separate.

**DShot Support:**
- Disabled by default and experimental only.
- Do not use for ESC testing until GPT compare timing, DMAC trigger routing,
  cache coherency, and logic-analyzer waveform validation are complete.

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
├── sih.px4board              # FC-SIH board configuration
├── init/
│   ├── rc.board_defaults     # Boot defaults script
│   ├── rc.board_defaults.cmds # Safe parameter defaults
│   ├── rc.board_sensors      # Board-specific sensor probes
│   └── rc.offline_sensor_check
├── nuttx-config/
│   ├── nsh/
│   │   └── defconfig         # NuttX kernel configuration
│   └── sih/
│       └── defconfig         # FC-SIH NuttX kernel configuration
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

### Core-Only Diagnostic Build
```bash
make renesas_rdk-rzv2h_core_only
```

Core-only artifacts are emitted under `build/renesas_rdk-rzv2h_core_only/`
and include `renesas_rdk-rzv2h_core_only.elf` and
`renesas_rdk-rzv2h_core_only.px4`.

### SIH Sensor Demo Build

```bash
make renesas_rdk-rzv2h_sih
```

The SIH image is the CR8-0 software demo path only. It links simulated
accel/gyro/baro/mag/GPS, HIL sensors, and `pwm_out_sim`; it does not start any
physical payload/sensor bus, GPT, or PWM driver. The current board transcript
proves boot, interactive shell, one bounded HRT callback, work queues,
simulated topics, and the HIL endpoint. Use it from a cold power-cycle; the
four-pin static-level measurement and 10-minute resource/rate soak remain
pending.

Build RZ/V2H NuttX targets sequentially. Their separate top-level build
directories still regenerate shared files under `platforms/nuttx/NuttX`, so
parallel or interleaved target builds can create stale cross-target state.

### SIH Demo Shell Checks

```bash
ver all
ps
top once
work_queue status
system_time hrt-test
listener sensor_accel -n 5
listener sensor_gyro -n 5
listener sensor_baro -n 5
listener sensor_mag -n 5
listener sensor_gps -n 5
pwm_out_sim status
free
perf
```

Queue count is timing-dependent on this image, so use `work_queue status`
alongside `ps` and `top` rather than expecting a fixed thread count.

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

### OpenAMP / IPCC Options

The default CR8_0 PX4 target excludes OpenAMP/IPCC so local startup does not
depend on CA55, CR8-1, or CM33. An opt-in multicore variant may enable:

```
CONFIG_OPENAMP=y
CONFIG_RPTUN=y
CONFIG_RPTUN_THREAD=y
CONFIG_RZV_OPENAMP=y
CONFIG_RZV_IPC_IPCC=y
CONFIG_IPCC=y
CONFIG_IPCC_BUFFERED=y
```

When enabled, PX4 initializes its CR8-0-local services first, then attempts
`rzv_ipc_initialize()` and `rzv_ipcc_initialize()` as best-effort optional
services. Transport failure is logged and does not abort local PX4 startup.

## Initialization Sequence

1. `rzv_board_initialize()` - Early hardware init
2. `board_app_initialize()` / `px4_platform_init()` - CR8-0-local PX4 services
3. Optional `rzv_ipc_initialize()` / `rzv_ipcc_initialize()` when enabled
4. `rdk_rzv2h_gpio_initialize()` - GPIO configuration
5. `rdk_rzv2h_timer_initialize()` - GPT timer setup
6. SPI/I2C bus initialization
7. Safe parameter defaults via `rc.board_defaults.cmds`
8. Board sensor probes via `rc.board_sensors`, then common PX4 startup

## Default Parameters (rc.board_defaults.cmds)

```
# S500 quad-X configuration (matches the checked-in RZ/V2H reference)
param set-default SYS_AUTOSTART 4014

# Volatile pre-G9 dataman backend
param set-default SYS_DM_BACKEND 1

# PWM configuration
# Default target: 400 Hz PWM. DShot target: -3 (DShot600).
param set-default PWM_MAIN_TIM0 400  # or -3
param set-default PWM_MAIN_TIM1 400  # or -3
param set-default PWM_MAIN_TIM2 400  # or -3
param set-default PWM_MAIN_TIM3 400  # or -3
param set-default PWM_MAIN_FUNC1 101
param set-default PWM_MAIN_FUNC2 102
param set-default PWM_MAIN_FUNC3 103
param set-default PWM_MAIN_FUNC4 104
```

The defaults script does not start core PX4 modules, install placeholder
calibration IDs, or relax arming/circuit-breaker checks. Common `rcS` owns
dataman, RC, estimator, control, output, GPS, and MAVLink startup. The board
sensor hook starts only MPU9250 on SPI0 and BMP280 on SCI7 bus 7.

## Integration Notes

### Operating Modes

| Mode | Console / Debug | Serial Policy | Validation State |
|------|-----------------|---------------|------------------|
| Core-only diagnostic image | RTT0 console/debug only | RTT shell, HRT, lazy work queues, params, uORB, `pwm_out start/stop/status`, `work_queue status`, `ver`, `dmesg`, `system_time`, `top`, `uorb`, `listener`, `perf` | build-clean; no hardware run |
| Standalone CR8-0 NuttX | SCI4 shell + RTT diagnostics | SCI4 is the interactive shell; RTT carries boot, syslog, and debug output | Validated by `nsh-rtt` |
| Standalone CR8-1 target | SCI5 shell + RTT diagnostics | SCI5 is the intended shell path for the CR8-1 IO target; not yet hardware validated | Target policy only |
| Standalone CM33 target | SCI9 shell + RTT diagnostics | SCI9 is the intended shell path for the CM33 IO target; not yet hardware validated | Target policy only |
| Integrated PX4 CR8-0 | RTT0 console/debug + SCI4/5/6/9 peripheral links | RTT0 `/dev/console` input/output is build-clean; SCI4 LiDAR, SCI5 MAVLink/QGC, SCI6 RC, SCI9 GPS | Target shell I/O pending |

### Clock Configuration
- External crystal: 24MHz
- GPT timer clock: runtime P4CLK from NuttX; nominal 200 MHz
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
- Current default: volatile TMPFS at `/fs`; PX4 uses `/fs/params`, but values
  reset on every reboot.
- The experimental RZ/V2H XSPI lower-half is disabled. Controller
  initialization, installed flash geometry, partition ownership, MPU/cache
  handling, erase/program/readback, reboot persistence, and power-loss
  recovery must pass before it can replace TMPFS.

## Core-Only PWM Demonstration

The core-only image starts `pwm_out` from
`ROMFS/rdk-rzv2h-core-only/init.d/rcS`, then prints `work_queue status`. That
path keeps output disabled until an explicit actuator command is issued and
uses the minimal lazy queue footprint expected on RZ/V2H, not the broader
RA8P1 queue fan-out. PWMOut starts on `wq:hp_default` and can migrate its
subscription callback to `wq:rate_ctrl`; queue creation is asynchronous, so
the immediate startup listing can differ from a later `work_queue status`.

`control_allocator` stays linked only because the actuator metadata generator
needs the mixer schema. The compact `rcS` does not start `control_allocator`,
and the image has no sensors, payload peripherals, or serial consumers.

Use the current bounded bench command for a single-channel waveform check:

```bash
actuator_test set -m 1 -v 0 -t 5
```

`pwm_out` supports `start`, `stop`, and `status` only. The board-scoped PWM
path keeps outputs disabled under `stop_motors`, so this remains a safe
demonstration target rather than a flight validation path. The command drives
Motor 1 at its configured 1100 µs minimum for five seconds; the other enabled
channels retain their 1000 µs disarmed values.

### DShot Mode

DShot is not enabled for `renesas_rdk-rzv2h_default`. Treat the RZ/V2H
DShot source as experimental reference code only until hardware waveform
validation proves the GPT/DMAC timing path.

## Troubleshooting

### PWM Not Working

1. **Check GPIO configuration**: Verify pins are configured for the listed GTIOC peripheral function
2. **Check timer initialization**: `rdk_rzv2h_timer_initialize()` should complete without errors
3. **Verify clock**: `rzv_get_gpt_clock_hz()` should report P4CLK used for PWM period calculation

### Motor Spin at Boot

1. Check `PWM_MAIN_DISx` parameters are set to 1000 (disarmed value)
2. Verify `up_pwm_servo_arm()` is not called before arming

### Arming Fails

1. Check `commander status` for arming blockers
2. Verify `COM_ARM_WO_GPS 1` is set for GPS-less operation
3. Check sensor calibration status

1. No USB support; console/debug routes are mode-specific (SCI4 standalone CR8-0 shell, RTT0 for integrated PX4)
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
