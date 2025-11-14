# GY-912 Sensor Board SPI Configuration Fix

## Summary
This document describes the changes made to fix SPI communication issues with the GY-912 sensor board (ICM20948 + BMP388) on the Renesas FPB-RA8E1 development board.

## Problem Analysis

### Original Issues
1. **ICM20948 (IMU)**:
   - WHO_AM_I register read succeeded (sensor detected)
   - No data acquisition (FIFO empty, no accelerometer/gyro data)
   - Root cause: Default SPI settings (1 MHz, unknown mode) were incorrect

2. **BMP388 (Barometer)**:
   - Failed to initialize completely
   - Error: "no instance started (no device on bus?)"
   - Root cause: Default SPI settings incompatible with BMP388 requirements

### Root Cause
The RA8 SPI driver was using default settings for all devices:
- **Default Frequency**: 1 MHz (too slow for both sensors)
- **Default Mode**: Not specified (likely Mode 0)
- **Default CS Timing**: Generic delays not optimized for sensors

### Sensor Requirements (from datasheets and PX4 drivers)

#### ICM20948 Requirements
- **SPI Frequency**: Up to 7 MHz
- **SPI Mode**: Mode 3 (CPOL=1, CPHA=1)
- **CS Timing**: Minimum setup/hold times required
- **DRDY Signal**: External interrupt on pin P409 (IRQ6)
- **Source**: `src/drivers/imu/invensense/icm20948/InvenSense_ICM20948_registers.hpp`
  ```cpp
  static constexpr uint32_t SPI_SPEED = 7 * 1000 * 1000; // 7 MHz SPI
  ```

#### BMP388 Requirements
- **SPI Frequency**: Up to 10 MHz
- **SPI Mode**: Mode 3 (CPOL=1, CPHA=1)
- **CS Timing**: Longer delays needed for pressure sensor
- **Source**: `src/drivers/barometer/bmp388/bmp388_main.cpp`
  ```cpp
  cli.default_spi_frequency = 10 * 1000 * 1000; // 10 MHz
  ```

## Solution Implemented

### File Modified
**`boards/renesas/fpb-ra8e1/src/spi.cpp`**

### Changes Made

#### 1. Added RA SPI Header Include
```cpp
#include "ra_spi.h"  // Added to access ra_spi_ext_dev_config_s structure
```

#### 2. Implemented `ra_spi_get_dev_config()` Function
This function provides per-device SPI configuration to the RA8 SPI driver.

**Key Implementation Details:**

```cpp
extern "C" const struct ra_spi_ext_dev_config_s *ra_spi_get_dev_config(struct spi_dev_s *dev, uint32_t devid)
{
    uint16_t devtype = PX4_SPI_DEV_ID(devid);

    // ICM20948 Configuration
    static const struct ra_spi_ext_dev_config_s icm20948_config = {
        .devid = DRV_IMU_DEVTYPE_ICM20948,
        .max_frequency = 7000000,              // 7 MHz
        .mode = SPIDEV_MODE3,                  // CPOL=1, CPHA=1
        .bits = 8,
        .cs_gpio = GPIO_SPI1_CS0,              // P408
        .cs_type = RA_SPI_CS_GPIO,
        .ssl_select = 0,
        .setup_delay = 1,                      // 1 RSPCK cycle
        .hold_delay = 1,
        .negation_delay = 1,
        .active_low = true,
        .name = "ICM20948"
    };

    // BMP388 Configuration
    static const struct ra_spi_ext_dev_config_s bmp388_config = {
        .devid = DRV_BARO_DEVTYPE_BMP388,
        .max_frequency = 10000000,             // 10 MHz
        .mode = SPIDEV_MODE3,
        .bits = 8,
        .cs_gpio = GPIO_SPI1_CS1,              // P407
        .cs_type = RA_SPI_CS_GPIO,
        .ssl_select = 1,
        .setup_delay = 2,                      // 2 RSPCK cycles
        .hold_delay = 2,
        .negation_delay = 2,
        .active_low = true,
        .name = "BMP388"
    };

    switch (devtype) {
    case DRV_IMU_DEVTYPE_ICM20948:
        return &icm20948_config;
    case DRV_BARO_DEVTYPE_BMP388:
        return &bmp388_config;
    default:
        return nullptr;  // Use driver defaults
    }
}
```

### How It Works

1. **Device Detection**: When the RA8 SPI driver needs to configure a device, it calls `ra_spi_get_dev_config()`
2. **Configuration Lookup**: The function matches the device ID and returns appropriate configuration
3. **Settings Applied**: The driver applies the returned settings:
   - `ra_spi_setfrequency()` sets the SPI clock
   - `ra_spi_setmode()` sets CPOL/CPHA
   - `ra_spi_dev_configure()` sets CS timing delays
4. **Per-Transfer**: Configuration is applied on each chip select assertion

### DRDY Configuration (Already Correct)

The ICM20948 data ready pin was already properly configured:
- **Pin**: P409 (GPIO_IRQ6_P409)
- **Mode**: External interrupt input with pull-up
- **Configuration**: `px4_arch_configgpio(GPIO_SPI1_IMU_DRDY)` in `init.c`
- **Definition**: `GPIO_IRQ6_P409 = (PORT4 | PIN9 | R_PFS_PCR | R_PFS_ISEL)`

## Testing Instructions

### Prerequisites
```bash
cd /home/tringuyen/px4_ra8/PX4-Autopilot
```

### 1. Rebuild Firmware
```bash
# Clean previous build
make distclean

# Build with new SPI configuration
make renesas_fpb-ra8e1_default

# Flash to board using your preferred method (J-Link, e² studio, etc.)
```

### 2. Test ICM20948 IMU

Connect to console (115200 baud) and run:

```bash
# Start ICM20948 driver
nsh> icm20948 start -s

# Check driver status
nsh> icm20948 status

# Expected output:
#   INFO [SPI_I2C] Running on SPI Bus 1
#   icm20948: FIFO empty interval should be non-zero

# Listen to accelerometer data
nsh> listener sensor_accel

# Expected output: Continuous data stream with values
#   timestamp: <timestamp>
#   x: <value>  # ~0 when level
#   y: <value>  # ~0 when level
#   z: <value>  # ~9.8 m/s² when level

# Listen to gyroscope data
nsh> listener sensor_gyro

# Expected output: Continuous data stream
#   timestamp: <timestamp>
#   x: <value>  # ~0 when stationary
#   y: <value>  # ~0 when stationary
#   z: <value>  # ~0 when stationary
```

### 3. Test BMP388 Barometer

```bash
# Start BMP388 driver
nsh> bmp388 start -s

# Check driver status
nsh> bmp388 status

# Expected output:
#   INFO [SPI_I2C] Running on SPI Bus 1
#   (driver info showing it's running)

# Listen to barometer data
nsh> listener sensor_baro

# Expected output: Continuous data stream
#   timestamp: <timestamp>
#   pressure: <value>      # ~101325 Pa at sea level
#   temperature: <value>   # Room temperature ~20-25°C
#   altitude: <value>
```

### 4. Verify SPI Communication

```bash
# Check uORB topics
nsh> uorb top

# Should show:
#   sensor_accel0: Published with reasonable rate
#   sensor_gyro0: Published with reasonable rate
#   sensor_baro0: Published with reasonable rate

# Check for errors
nsh> dmesg

# Should NOT show:
#   - "SPI transfer timeout"
#   - "FIFO overflow"
#   - "sensor not responding"
```

## Success Criteria

### ICM20948 (IMU)
- ✅ Driver starts without errors
- ✅ `sensor_accel` topic publishes data at ~4500 Hz
- ✅ `sensor_gyro` topic publishes data at ~9000 Hz
- ✅ Accelerometer shows ~9.8 m/s² on Z-axis when board is level
- ✅ Gyroscope shows ~0 when board is stationary
- ✅ FIFO empty interval is non-zero

### BMP388 (Barometer)
- ✅ Driver starts without errors ("no device on bus" message gone)
- ✅ `sensor_baro` topic publishes data
- ✅ Pressure reading is reasonable (~101325 Pa ± 5000 Pa)
- ✅ Temperature reading is reasonable (15-30°C typical)

## Troubleshooting

### If ICM20948 Still Shows No Data

1. **Check SPI pins**:
   ```bash
   # Verify CS pin is configured
   nsh> gpio -l | grep P408
   ```

2. **Check DRDY interrupt**:
   ```bash
   # Should see IRQ6 configured
   nsh> cat /proc/interrupts
   ```

3. **Enable debug output**:
   - Modify `board_config.h`: Add `#define CONFIG_DEBUG_SPI_INFO 1`
   - Rebuild and check logs for SPI transactions

### If BMP388 Still Fails to Start

1. **Verify CS pin**:
   ```bash
   nsh> gpio -l | grep P407
   ```

2. **Check SPI mode**:
   - BMP388 requires Mode 3 (CPOL=1, CPHA=1)
   - Verify in `ra_spi_get_dev_config()` that `.mode = SPIDEV_MODE3`

3. **Try lower frequency**:
   - Temporarily reduce to 5 MHz for testing
   - Modify `bmp388_config.max_frequency = 5000000`

## Technical Details

### SPI Mode 3 Timing
- **CPOL = 1**: Clock idle state is HIGH
- **CPHA = 1**: Data sampled on rising edge (second clock transition)
- Both ICM20948 and BMP388 require this mode

### CS Timing Delays
- **Setup Delay**: Time between CS assertion and first clock edge
- **Hold Delay**: Time between last clock edge and CS de-assertion
- **Negation Delay**: Time between CS de-assertion and next CS assertion
- Measured in RSPCK (SPI clock) cycles

### Frequency Selection
- ICM20948: 7 MHz (datasheet maximum)
- BMP388: 10 MHz (datasheet maximum)
- Actual frequency may be slightly lower due to clock divider rounding

## References

### PX4 Driver Sources
- `src/drivers/imu/invensense/icm20948/ICM20948.hpp`
- `src/drivers/imu/invensense/icm20948/ICM20948.cpp`
- `src/drivers/imu/invensense/icm20948/InvenSense_ICM20948_registers.hpp`
- `src/drivers/barometer/bmp388/bmp388.h`
- `src/drivers/barometer/bmp388/bmp388_spi.cpp`
- `src/drivers/barometer/bmp388/bmp388_main.cpp`

### NuttX RA8 Driver Sources
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_spi.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_spi.h`

### Datasheets
- ICM-20948 Datasheet: TDK InvenSense
- BMP388 Datasheet: Bosch Sensortec

## Conclusion

The implementation adds per-device SPI configuration support by implementing the `ra_spi_get_dev_config()` callback function. This allows each sensor to specify its required SPI frequency, mode, and CS timing parameters, ensuring proper communication with both the ICM20948 IMU and BMP388 barometer on the GY-912 sensor board.

The fix is minimal, non-intrusive, and follows the existing RA8 SPI driver architecture without modifying core NuttX driver code.
