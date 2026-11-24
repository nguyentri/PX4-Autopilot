# PX4 BSP for Renesas RDK-RZV2H

This document describes the PX4 Board Support Package (BSP) created for the Renesas RDK-RZV2H development board.

## Overview

The RDK-RZV2H BSP enables PX4 flight controller functionality on the Renesas
RZV2H MPU using the Cortex-R8 (CR8_0) core for real-time flight control. The
`default` image is independent of CA55, CR8_1, CM33, OpenAMP, and IPCC.
Multicore transports remain opt-in final-milestone features.

The board ships four CR8-0 targets:

| Target | Purpose |
|--------|---------|
| `renesas_rdk-rzv2h_default` | Reference drone on the RDK sensor extension (3× ICM-45686, BMM150, BMP390L, INA228, M10, TFmini, SBUS). Links `pwm_out` and `dshot`; `PWM_MAIN_TIM0..3` selects which one starts. |
| `renesas_rdk-rzv2h_demo` | Bench demo: one ICM-45686, BMP280, ADS1115, TFmini, 400 Hz PWM, QGC. |
| `renesas_rdk-rzv2h_demosih` | SIH showcase of the demo wiring; no output driver. |
| `renesas_rdk-rzv2h_dualcr8` | Sensor flight core for the dual-CR8 pair; outputs go to the CR8-1 `default` supervisor over IPC. |

The `drone`, `dshot`, `simple`, `sih` and core-only targets were retired on
2026-11-18 (`drone` + `dshot` became `default`). Their validation guides and
evidence remain under `docs/renesas/` as history. Pin ownership per target:
[pinmap profiles](../../../docs/renesas/pinmap.md#px4-configuration-profiles).

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
| Output supervisor | CR8_1 | `renesas_rdk-rzv2h-io-cr8_1_default` | `rzv2h_io` over raw IPC, paired with `dualcr8` only (`demo`: heartbeat peer) |

The OpenAMP layout follows the Renesas FreeRTOS/FSP reference:

| Resource | Address / Name |
|----------|----------------|
| Resource table | `0x42f00000` |
| MHU shared memory | `0x42f01000` |
| RPMsg memory window | `0x43000000` size `0x00800000` |
| Vring0 / Vring1 | `0x43000000` / `0x43050000` |
| RPC endpoint | `rpmsg-service-0`, CR8 local address `0x0` |

### Sensors (`default`)
| Sensor | Interface | Configuration |
|--------|-----------|---------------|
| 3× ICM-45686 (IMU) | RSPI0 | GPIO CS P93/P94/P95 (`-c 3/4/5`), polled |
| BMM150 (Mag) | SCI-mode I2C7 | Address 0x10, P76/P77 |
| BMP390L (Baro, `bmp388`) | SCI-mode I2C7 | Address 0x76, P76/P77 |
| INA228 (Power) | SCI-mode I2C7 | Address 0x45, `BAT1_SOURCE 0` |

### Serial Ports
| Port | SCI | Pins        | Device      | Function |
|------|-----|-------------|-------------|----------|
| ttyS4 | SCI4 | P70/P71     | /dev/ttyS4  | TFminiPlus LiDAR |
| ttyS5 | SCI5 | P72/P73     | /dev/ttyS5  | Sik Telemetry v3 for MAVLink/QGroundControl |
| ttyS6 | SCI6 | P75         | /dev/ttyS6  | FS-A8S SBUS, 100000 8E2; external NPN inverter |
| ttyS9 | SCI9 | P82/P83     | /dev/ttyS9  | GPS M10 |

SCI3 is not an active console on the RDK-RZV2H board. SCI5 is shared:
PX4 images use it for MAVLink telemetry, and NuttX/PX4 images without
telemetry use it as the serial shell. Integrated PX4 diagnostics use RTT.

The integrated PX4 images expose SCI4 as the generated `EXT2` serial role and
assign `SENS_TFMINI_CFG=401`, so common `rc.serial` starts TFmini on
`/dev/ttyS4`. SCI4 is not a shell UART.

### I2C Buses
| Bus | SCI | Pins     | Device      |
|-----|-----|----------|-------------|
| I2C7 | SCI-I2C7 | P76/P77 | BMM150 0x10, BMP390L 0x76, INA228 0x45 |

### SPI Buses
| Bus  | Pins              | Device        |
|------|-------------------|---------------|
| RSPI0 | P90/P91/P92      | 3× ICM-45686  |
|       | P93/P94/P95 (GPIO CS) | IMU #1/#2/#3 CS |

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
- Bench check (props off, disarmed): defaults are minimum 1100 µs, maximum
  1900 µs and disarmed 1000 µs. The finite command
  `actuator_test set -m 1 -v 0 -t 5` requests motor 1 at its 1100 µs minimum
  for five seconds, then leaves it inactive. Measure each pin; the other
  channels output DIS1000 pulses during the test window.

**DShot Support (`default`):**
- `pwm_out` and `dshot` are both linked but drive the same GPT units, so
  `rc.board_defaults.cmds` starts exactly one: `pwm_out` while `PWM_MAIN_TIM0 > -2`,
  otherwise `dshot`. Set all four `PWM_MAIN_TIMx` to `-3` (DShot600), `-4`
  (DShot300) or `-5` (DShot150), save and reboot.
- Motor-stop DShot TX was bounded on target in the retired `dshot` image;
  waveform, ESC and nonzero-throttle proof are pending. The merged image is
  build-clean only.

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
├── default.px4board          # Reference drone (PWM or DShot)
├── demo.px4board             # Bench demo
├── demosih.px4board          # SIH showcase of the demo wiring
├── dualcr8.px4board          # Dual-CR8 sensor flight core
├── firmware.prototype        # Firmware metadata
├── Kconfig                   # Board Kconfig options
├── init/
│   ├── rc.board_defaults     # Boot defaults script
│   ├── rc.board_defaults.cmds # Defaults + pwm_out/dshot selection
│   ├── rc.board_sensors      # Extension sensor probes
│   ├── rc.offline_sensor_check
│   └── demo/ demosih/ dualcr8/ # Per-variant hooks (CONFIG_BOARD_INIT_SUBDIR)
├── nuttx-config/
│   ├── nsh/defconfig         # default
│   ├── demo/defconfig
│   ├── demosih/defconfig     # symlink to ../demo/defconfig
│   └── dualcr8/defconfig
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

### Build Commands
```bash
./build.sh renesas_rdk-rzv2h_default
./build.sh renesas_rdk-rzv2h_demo
./build.sh renesas_rdk-rzv2h_demosih
./build.sh renesas_rdk-rzv2h_dualcr8
```

Artifacts: `build/<target>/<target>.{elf,px4}`. Use `--no-clean` only to
rebuild the same target.

Build RZ/V2H NuttX targets sequentially. Their separate top-level build
directories still regenerate shared files under `platforms/nuttx/NuttX`, so
parallel or interleaved target builds can create stale cross-target state.

### Clean Build
```bash
./build.sh renesas_rdk-rzv2h_default
```

`build.sh` cleans by default; pass `--no-clean` to iterate.

## Configuration Options

### Board Kconfig (`boards/renesas/rdk-rzv2h/Kconfig`)
- `BOARD_RDK_RZV2H`: Enable board support
- `BOARD_RDK_RZV2H_PWM_CHANNELS`: Number of PWM channels (1-8, default 4)
- `BOARD_RDK_RZV2H_HAS_BARO`: Enable barometer (default y)
- `BOARD_RDK_RZV2H_HAS_IMU`: Enable IMU (default y)
- `BOARD_RDK_RZV2H_HAS_MAG`: Enable magnetometer (default y)

### Key PX4board Options
- Flight modules: EKF2, Commander, Navigator, MC attitude/position control
- Sensors: 3× ICM-45686, BMM150, BMP390L (`bmp388`), INA228
- Outputs: PWM or DShot (4 channels), RC input (SBUS)
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
# S500 quad-X: airframe 4210 runs the stock 4014_s500 chain, then restores
# the reference values that chain replaces
param set-default SYS_AUTOSTART 4210

# Volatile pre-G9 dataman backend
param set-default SYS_DM_BACKEND 1

# PWM configuration: 400 Hz PWM; set all four to -3/-4/-5 for DShot
param set-default PWM_MAIN_TIM0 400
param set-default PWM_MAIN_TIM1 400
param set-default PWM_MAIN_TIM2 400
param set-default PWM_MAIN_TIM3 400
param set-default PWM_MAIN_FUNC1 101
param set-default PWM_MAIN_FUNC2 102
param set-default PWM_MAIN_FUNC3 103
param set-default PWM_MAIN_FUNC4 104
```

The defaults script does not start core PX4 modules, install placeholder
calibration IDs, or relax arming/circuit-breaker checks. Common `rcS` owns
dataman, RC, estimator, control, output, GPS, and MAVLink startup. The board
sensor hook starts three ICM-45686 on SPI0 and BMM150, BMP390L and INA228 on
SCI7 bus 7. After the defaults, the script starts `pwm_out` or `dshot` from
`PWM_MAIN_TIM0`.

`rcS` runs the selected airframe after this file, and the last `param
set-default` wins. The stock S500 chain (`rc.mc_defaults`, then `4014_s500`)
would replace the reference roll/pitch rate gains, the rotor positions,
`IMU_GYRO_RATEMAX`, `NAV_ACC_RAD`, the RTL altitudes, `GPS_UBX_DYNMODEL` and
`EKF2_RNG_FOG`. Airframe `4210_rzv2h_rdk_s500`, installed by
`CONFIG_BOARD_RDK_RZV2H_REFERENCE_AIRFRAME`, sources that chain and then
restores those values, so `default` and `demo` end at the reference values.
One value is the port's own: `IMU_GYRO_RATEMAX` is 800 Hz, not the
reference's 400. The reference caps the ICM-45686 FIFO read at 200 Hz for its
1 MHz SPI; SPI0 here runs at 20 MHz (200 MHz P4CLK / 10), so each driver reads
eight 6400 Hz samples per read. At 20-byte FIFO records that is about 5% of
SPI0 per IMU, independent of the read rate.
`test/rzv2h-reference-airframe-parity-test.py` checks the result. `/fs` is
TMPFS, so saved parameters last only until the next reset; a stored
`SYS_AUTOSTART` other than 4210 can only come from the current boot (or from
persistent storage once it exists). If `param show SYS_AUTOSTART` is not 4210,
reload the image; once parameters persist, run `param set SYS_AUTOSTART 4210`
and `param save` once before the reset. `dualcr8` stays on
4014 because its CR8-1 output contract keys on that ID.

## Integration Notes

### Operating Modes

| Mode | Console / Debug | Serial Policy | Validation State |
|------|-----------------|---------------|------------------|
| Standalone CR8-0 NuttX | Serial shell (SCI5) + RTT diagnostics | SCI5 is the interactive shell when no telemetry runs; RTT carries boot, syslog, and debug output | Earlier `nsh-rtt` pass was on SCI4; SCI5 shell needs on-target validation |
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

1. No USB support; console/debug routes are mode-specific (SCI5 serial shell when telemetry is absent, RTT0 for integrated PX4)
2. No CAN bus support
3. Battery monitoring ADC not implemented
4. Single I2C bus (I2C7 only)
5. No hardware safety switch

## References

- PX4 FreeRTOS RDK reference: `refs/rzv2h_drone_px4-dev/` (local only, gitignored)
- [NuttX RZV2H Board](../../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/)
- [RZV2H Technical Manual](../../../docs/renesas/r01uh1032ej0130-rzv2h.pdf) (local only, gitignored)

## Authors

PX4 Kiwi Team - 2026
