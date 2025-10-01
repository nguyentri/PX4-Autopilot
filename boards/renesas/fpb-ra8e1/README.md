# PX4 Board Support Package for Renesas FPB-RA8E1

This directory contains the complete PX4 board support package (BSP) for the Renesas FPB-RA8E1 development board featuring the RA8E1 MCU (ARM Cortex-M85 @ 360MHz).

## Board Overview

The FPB-RA8E1 is a development board from Renesas featuring:

- **MCU**: R7FA8E1AFDCFB (ARM Cortex-M85 @ 360MHz)
- **RAM**: 512KB internal SRAM
- **Data Flash**: 12KB of data flash memory
- **Flash**: 1MB internal flash memory
- **Architecture**: ARMv8-M with TrustZone support
- **OS**: NuttX RTOS

## Hardware Features

### Currently Supported ✅
- **Serial (SCI/UART)**: 3 ports for debug console, telemetry, and RC input
- **SPI**: 1 bus for sensor communication (GY-912 module)
- **PWM (GPT)**: 4 channels for motor control (400Hz standard ESC)
- **GPIO**: Basic digital I/O pins
- **Sensors**: ICM-20948 IMU + BMP388 barometer (GY-912 module)
- **LEDs**: 2 status LEDs for system indication

### Planned/Future Support 🚧
- **I2C**: External sensor expansion
- **ADC**: Battery voltage/current monitoring
- **Storage**: Parameter storage in data flash
- **RC Input**: SBUS protocol support on UART

### Not Currently Supported ❌
- **CAN Bus**: Not implemented
- **USB**: Limited to power only
- **SDIO**: External storage not available

## Pin Configuration

### UART/Serial Ports
- **SCI0** (P609/P610): Primary telemetry (57600 baud)
- **SCI2** (P801/P802): Console/Debug (115200 baud)
- **SCI3** (P309/P310): RC input/Secondary telemetry (57600 baud)

### SPI Bus 1 - Sensors
- **SCK**: P412 (SPI1 Clock)
- **MOSI**: P411 (SPI1 MOSI)
- **MISO**: P410 (SPI1 MISO)
- **CS0**: P408 (ICM20948 IMU Chip Select)
- **CS1**: P407 (BMP388 Barometer Chip Select)
- **DRDY**: P409 (ICM20948 Data Ready)

### PWM Outputs (GPT Timers)
- **Motor 1**: P300 (GPT3A)
- **Motor 2**: P415 (GPT0A)
- **Motor 3**: P113 (GPT2A)
- **Motor 4**: P302 (GPT4A)

### Status LEDs
- **LED1**: P404 (Status indicator)
- **LED2**: P405 (Armed state indicator)

### User Interface
- **Button**: P009 (User/Safety button)

## Required Drivers

### NuttX Drivers (automatically configured)
- `ra_clock.c` - System clock configuration
- `ra_gpio.c` - GPIO control
- `ra_serial.c` - UART/SCI drivers
- `ra_spi.c` - SPI bus driver
- `ra_gpt.c` - PWM/Timer driver
- `ra_i2c.c` - I2C bus driver (for future expansion)

### PX4 Drivers (enabled in board configuration)
- `icm20948` - 9-axis IMU driver
- `bmp388` - Barometer driver
- `pwm_out` - PWM output driver
- `led_control` - LED status driver

## Build Instructions

### Prerequisites

1. **PX4 Development Environment**: Set up according to [PX4 Developer Guide](https://docs.px4.io/main/en/dev_setup/)

2. **ARM Toolchain**: Ensure arm-none-eabi-gcc is installed and in PATH:
   ```bash
   arm-none-eabi-gcc --version
   ```

3. **Build Dependencies**:
   ```bash
   # Ubuntu/Debian
   sudo apt-get update
   sudo apt-get install build-essential cmake ninja-build python3-pip

   # macOS
   brew install cmake ninja
   ```

### Building the Firmware

1. **Navigate to PX4 root directory**:
   ```bash
   cd /path/to/PX4-Autopilot
   ```

2. **Clean any previous builds** (recommended):
   ```bash
   make clean
   make distclean
   ```

3. **Build the firmware**:
   ```bash
   make renesas_fpb-ra8e1_default
   ```
   - force to use custom repo:
   ```bash
    echo "y" | make renesas_fpb-ra8e1_default
   ```

4. **Build output**: The firmware will be generated as:
   ```
   build/renesas_fpb-ra8e1_default/renesas_fpb-ra8e1_default.elf
   build/renesas_fpb-ra8e1_default/renesas_fpb-ra8e1_default.hex
   build/renesas_fpb-ra8e1_default/renesas_fpb-ra8e1_default.bin
   ```

### Test Configuration Build

For hardware validation and testing:
```bash
make renesas_fpb-ra8e1_test
```

## Flash Instructions

### Using Renesas e² studio / J-Link

1. **Connect J-Link debugger** to the FPB-RA8E1 board

2. **Open e² studio** and create a debug configuration:
   - Target: R7FA8E1AFDCFB
   - Debugger: J-Link ARM
   - Connection: SWD

3. **Load firmware**:
   - File → Import → Binary file
   - Select `renesas_fpb-ra8e1_default.elf`
   - Flash to target

### Using J-Link Commander

```bash
# Connect to target
JLinkExe -device R7FA8E1AFDCFB -if SWD -speed 4000

# In J-Link console:
connect
loadfile build/renesas_fpb-ra8e1_default/renesas_fpb-ra8e1_default.hex
r
g
quit
```

### Alternative: Using make upload (if configured)

```bash
make renesas_fpb-ra8e1_default upload
```

**Note**: This requires proper J-Link setup in the build system.

## Verification and Testing

### Safety Precautions ⚠️

**IMPORTANT**: Always follow these safety procedures:

1. **Remove propellers** during all testing
2. **Secure the board** to prevent movement during motor tests
3. **Use appropriate power supply** (7.4V recommended for testing)
4. **Have emergency stop** method ready (power disconnect)
5. **Test in controlled environment** away from people and property
6. **Verify all connections** before powering on

### Basic System Checks

#### 1. Console Connection
Connect to SCI2 (P801/P802) at 115200 baud:
```bash
# Using screen (Linux/macOS)
screen /dev/ttyUSB0 115200

# Using minicom (Linux)
minicom -D /dev/ttyUSB0 -b 115200
```

Expected output:
```
nsh>
```

#### 2. System Status
```bash
nsh> uorb top
nsh> ps
nsh> free
```

**Pass criteria**:
- NSH prompt appears
- No critical errors in logs
- Sufficient free memory (>50KB)

#### 3. Sensor Verification

**IMU Test**:
```bash
nsh> icm20948 status
nsh> listener sensor_accel
nsh> listener sensor_gyro
```

**Pass criteria**:
- Driver reports "OK" status
- Acceleration shows ~9.8 m/s² on Z-axis when level
- Gyro values near zero when stationary

**Barometer Test**:
```bash
nsh> bmp388 status
nsh> listener sensor_baro
```

**Pass criteria**:
- Driver reports "OK" status
- Pressure reading ~101325 Pa (sea level)
- Temperature reading reasonable (~20-25°C)

#### 4. PWM Output Test

**⚠️ REMOVE PROPELLERS FIRST ⚠️**

```bash
nsh> pwm_out status
nsh> pwm_out test -c 1 -p 1100
nsh> pwm_out test -c 1 -p 1000  # Return to minimum
```

**Pass criteria**:
- All 4 PWM channels active
- Motor responds to PWM commands
- PWM frequency = 400Hz

#### 5. LED Test
```bash
nsh> led_control test
```

**Pass criteria**:
- Both LEDs cycle through patterns
- LED1 (red) and LED2 (green) functional

#### 6. RC Input Test (when connected)
```bash
nsh> listener input_rc
```

**Pass criteria**:
- RC channels show correct values
- Range 1000-2000 µs
- Smooth response to stick movement

### Flight Controller Tests

#### 7. Arming Test
```bash
nsh> commander status
nsh> commander arm
```

**Pass criteria**:
- System arms without errors
- Armed LED indication
- Motors spin up briefly

#### 8. Attitude Control Test
```bash
nsh> listener vehicle_attitude
nsh> listener actuator_outputs
```

**Pass criteria**:
- Attitude estimates stable
- Control outputs respond to attitude changes
- No excessive oscillations

### Advanced Verification

#### 9. EKF2 State Estimation
```bash
nsh> ekf2 status
nsh> listener vehicle_local_position
```

**Pass criteria**:
- EKF2 converged
- Position estimates reasonable
- No excessive innovation

#### 10. Parameter Storage
```bash
nsh> param save
nsh> reboot
nsh> param show | grep SYS_AUTOSTART
```

**Pass criteria**:
- Parameters saved successfully
- Values persist after reboot

## Troubleshooting

### Build Issues

**Error: `'px4_platform_common/px4_config.h' file not found`**
- **Solution**: Ensure you're building from PX4-Autopilot root directory
- **Command**: `make renesas_fpb-ra8e1_default`

**Error: `arm-none-eabi-gcc: command not found`**
- **Solution**: Install ARM toolchain or add to PATH
- **Ubuntu**: `sudo apt-get install gcc-arm-none-eabi`

**Error: `Unknown board 'renesas_fpb-ra8e1'`**
- **Solution**: Verify board files are in correct directory structure
- **Check**: `boards/renesas/fpb-ra8e1/` exists with all files

### Runtime Issues

**No NSH Prompt**
- Check UART connection and baud rate (115200)
- Verify power supply (3.3V logic, adequate current)
- Try different USB-UART adapter

**Sensors Not Found**
- Verify SPI connections and pin assignments
- Check chip select GPIO configuration
- Use oscilloscope to verify SPI signals

**PWM Not Working**
- Verify GPT timer configuration
- Check PWM pin assignments
- Ensure proper power supply for ESCs

**System Crashes/Resets**
- Check stack sizes in configuration
- Verify memory allocation
- Enable DEBUG output for more information

### Recovery Procedures

**Firmware Corruption**
1. Use J-Link to erase entire flash
2. Reload firmware using debugger
3. Verify flash programming success

**Parameter Corruption**
1. `param reset_all`
2. `reboot`
3. Reconfigure essential parameters

**System Hang**
1. Power cycle the board
2. Check for infinite loops in custom code
3. Reduce system load by disabling modules

## Development Notes

### Adding New Sensors
1. Add sensor driver to `boards/renesas/fpb-ra8e1/default.px4board`
2. Configure SPI/I2C bus in `src/spi.cpp` or `src/i2c.cpp`
3. Add initialization to `init/rc.board_sensors`
4. Update pin assignments in `src/board_config.h`

### Memory Optimization
- Current free RAM: ~200KB (typical)
- Flash usage: ~400KB (with basic drivers)
- For additional features, consider:
  - Reducing logger verbosity
  - Disabling unused modules
  - Optimizing stack sizes

### Performance Tuning
- PWM frequency can be increased to 1kHz for better response
- SPI clock can be raised for faster sensor updates
- Consider DMA for high-frequency operations

## Additional Resources

- [PX4 Developer Guide](https://docs.px4.io/main/en/development/)
- [Renesas RA8E1 Datasheet](https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus/ra8e1-360mhz-arm-cortex-m85-trustzone-high-performance-microcontroller)
- [FPB-RA8E1 User Manual](https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus/fpb-ra8e1-fast-prototyping-board-ra8e1-mcu-group)
- [ICM-20948 Datasheet](https://invensense.tdk.com/products/motion-tracking/9-axis/icm-20948/)
- [BMP388 Datasheet](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp388/)

## Support and Contributing

For issues specific to this board:
1. Check existing GitHub issues
2. Provide complete build/runtime logs
3. Include hardware setup details
4. Test with minimal configuration first

When contributing improvements:
1. Test thoroughly with hardware
2. Update documentation
3. Follow PX4 coding standards
4. Submit pull request with detailed description

---

**Version**: 0.1.0
**Last Updated**: December 2025
**Maintainer**: tri.
