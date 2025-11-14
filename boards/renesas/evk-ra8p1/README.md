# PX4 Board Support Package for Renesas EVK-RA8P1# PX4 Board Support Package for Renesas FPB-RA8E1



This directory contains the complete PX4 board support package (BSP) for the Renesas EVK-RA8P1 development board featuring the RA8P1 MCU (ARM Cortex-M85 @ 480MHz).This directory contains the complete PX4 board support package (BSP) for the Renesas FPB-RA8E1 development board featuring the RA8E1 MCU (ARM Cortex-M85 @ 360MHz).



## Board Overview## Board Overview



The EVK-RA8P1 is a high-performance development board from Renesas featuring:The FPB-RA8E1 is a development board from Renesas featuring:



- **MCU**: R7FA8P1AHECBD (ARM Cortex-M85 @ 480MHz)- **MCU**: R7FA8E1AFDCFB (ARM Cortex-M85 @ 360MHz)

- **RAM**: 1024KB internal SRAM + 128MB external SDRAM- **RAM**: 512KB internal SRAM

- **Data Flash**: 16KB of data flash memory  - **Data Flash**: 12KB of data flash memory

- **Flash**: 2MB internal flash memory- **Flash**: 1MB internal flash memory

- **Architecture**: ARMv8-M with TrustZone support- **Architecture**: ARMv8-M with TrustZone support

- **OS**: NuttX RTOS- **OS**: NuttX RTOS

- **Additional**: Ethernet, USB HS, OSPI Flash, MIPI CSI-2 camera interface

## Hardware Features

## Hardware Features

### Currently Supported ✅

### Currently Supported ✅- **Serial (SCI/UART)**: 3 ports for debug console, telemetry, and RC input

- **Serial (SCI/UART)**: 3 ports for debug console, telemetry, and RC input- **SPI**: 1 bus for sensor communication (GY-912 module)

- **SPI**: 1 bus for sensor communication (GY-912 module via Pmod1)- **PWM (GPT)**: 4 channels for motor control (400Hz standard ESC)

- **PWM (GPT)**: 4 channels for motor control (400Hz standard ESC)- **GPIO**: Basic digital I/O pins

- **GPIO**: Basic digital I/O pins- **Sensors**: ICM-20948 IMU + BMP388 barometer (GY-912 module)

- **Sensors**: ICM-20948 IMU + BMP388 barometer (GY-912 module)  - **IMU**: `icm20948` driver for 9-axis motion sensing

  - **IMU**: `icm20948` driver for 9-axis motion sensing  - **Barometer**: `bmp388` driver for altitude/pressure

  - **Barometer**: `bmp388` driver for altitude/pressure  - **Magnetometer**: `ak09916` driver (integrated with ICM-20948)

  - **Magnetometer**: `ak09916` driver (integrated with ICM-20948)- **LEDs**: 2 status LEDs for system indication

- **LEDs**: 3 user LEDs for system indication (Blue, Green, Red)

### Planned/Future Support 🚧

### Planned/Future Support 🚧- **I2C**: External sensor expansion

- **I2C**: External sensor expansion (I2C0/I2C1 available)- **ADC**: Battery voltage/current monitoring

- **ADC**: Battery voltage/current monitoring- **Storage**: Parameter storage in data flash

- **Storage**: Parameter storage in data flash or external OSPI- **RC Input**: SBUS protocol support on UART

- **RC Input**: SBUS protocol support on UART

- **Ethernet**: Gigabit Ethernet for networking### DShot ESC Protocol Support ⚡

- **SDRAM**: External 128MB SDRAM for data buffers- **DShot150/300/600**: Digital ESC communication protocol

- **USB**: USB High Speed for MAVLink or data download- **Hardware Timers**: Uses RA8 GPT timers for precise timing

- **BDShot Support**: Bidirectional DShot for ESC telemetry (planned)

### DShot ESC Protocol Support ⚡- **Channel Mapping**: 4 channels mapped to GPT0/2/3/4 timers

- **DShot150/300/600**: Digital ESC communication protocol- **Configuration**: Use `renesas_fpb-ra8e1_dshot` target for DShot

- **Hardware Timers**: Uses RA8 GPT timers for precise timing

- **BDShot Support**: Bidirectional DShot for ESC telemetry (planned)### Not Currently Supported ❌

- **Channel Mapping**: 4 channels mapped to GPT0/10/11/12 timers- **CAN Bus**: Not implemented

- **Configuration**: Use `renesas_evk-ra8p1_dshot` target for DShot- **USB**: Limited to power only

- **SDIO**: External storage not available

### Not Currently Supported ❌

- **CAN Bus**: Not implemented## Pin Configuration

- **OSPI Flash**: External flash memory not configured

- **SDRAM**: External memory controller not configured### UART/Serial Ports

- **Ethernet**: Network stack not enabled- **SCI0** (P609/P610): Primary telemetry (57600 baud)

- **USB HS**: USB connectivity limited to power only- **SCI2** (P801/P802): Console/Debug (115200 baud)

- **MIPI CSI-2**: Camera interface not configured- **SCI3** (P309/P310): RC input/Secondary telemetry (57600 baud)



## Pin Configuration### SPI Bus 1 - Sensors (Custom sensor board GY-912)

- **SCK**: P412 (SPI1 Clock)

### UART/Serial Ports- **MOSI**: P411 (SPI1 MOSI)

- **SCI2** (P802/P801): Console/Debug (115200 baud) - Pmod1- **MISO**: P410 (SPI1 MISO)

- **SCI0** (P602/P603): Primary telemetry (57600 baud) - Pmod2- **CS0**: P408 (ICM20948 (including AK09916) IMU Chip Select)

- **SCI7** (P808/P809): RC input/Secondary telemetry (57600 baud) - Arduino/mikroBUS- **CS1**: P407 (BMP388 Barometer Chip Select)

- **DRDY**: P409 (ICM20948 Data Ready)

### SPI Bus 1 - Sensors (Custom sensor board GY-912 via Pmod1)

- **SCK**: P803 (SPI1 Clock) - Pmod1 pin 4### PWM Outputs (GPT Timers)

- **MOSI**: P801 (SPI1 MOSI) - Pmod1 pin 2 (shared with TXD2)- **Motor 1**: P300 (GPT3A)

- **MISO**: P802 (SPI1 MISO) - Pmod1 pin 3 (shared with RXD2)- **Motor 2**: P415 (GPT0A)

- **CS0**: P804 (ICM20948 including AK09916 IMU Chip Select) - Pmod1 pin 1- **Motor 3**: P113 (GPT2A)

- **CS1**: P402 (BMP388 Barometer Chip Select) - Pmod1 RESET pin (repurposed)- **Motor 4**: P302 (GPT4A)

- **DRDY**: P006 (ICM20948 Data Ready) - Pmod1 IRQ pin

### Status LEDs

### PWM Outputs (GPT Timers)- **LED1**: P404 (Status indicator)

- **Motor 1**: P211 (GPT0A)- **LED2**: P405 (Armed state indicator)

- **Motor 2**: P109 (GPT10A) - Arduino D9

- **Motor 3**: P711 (GPT11A)### User Interface

- **Motor 4**: P708 (GPT12A)- **Button**: P009 (User/Safety button)



### Status LEDs## Required Drivers

- **LED1 (Blue)**: P600 - Status indicator

- **LED2 (Green)**: P303 - Armed state indicator### NuttX Drivers (automatically configured)

- **LED3 (Red)**: PA07 - Error/Panic indicator- `ra_clock.c` - System clock configuration

- `ra_gpio.c` - GPIO control

### User Interface- `ra_serial.c` - UART/SCI drivers

- **SW1**: P009 (IRQ13-DS) - User/Safety button- `ra_spi.c` - SPI bus driver

- **SW2**: P008 - Secondary user button- `ra_gpt.c` - PWM/Timer driver

- `ra_i2c.c` - I2C bus driver (for future expansion)

## Required Drivers

### PX4 Drivers (enabled in board configuration)

### NuttX Drivers (automatically configured)- `icm20948` - 9-axis IMU driver

- `ra_clock.c` - System clock configuration (480MHz)- `bmp388` - Barometer driver

- `ra_gpio.c` - GPIO control- `pwm_out` - PWM output driver

- `ra_serial.c` - UART/SCI drivers- `led_control` - LED status driver

- `ra_spi.c` - SPI bus driver

- `ra_gpt.c` - PWM/Timer driver## Build Instructions

- `ra_i2c.c` - I2C bus driver (for future expansion)

### Prerequisites

### PX4 Drivers (enabled in board configuration)

- `icm20948` - 9-axis IMU driver1. **PX4 Development Environment**: Set up according to [PX4 Developer Guide](https://docs.px4.io/main/en/dev_setup/)

- `bmp388` - Barometer driver

- `pwm_out` - PWM output driver2. **ARM Toolchain**: Ensure arm-none-eabi-gcc is installed and in PATH:

- `led_control` - LED status driver   ```bash

   arm-none-eabi-gcc --version

## Build Instructions   ```



### Prerequisites3. **Build Dependencies**:

   ```bash

1. **PX4 Development Environment**: Set up according to [PX4 Developer Guide](https://docs.px4.io/main/en/dev_setup/)   # Ubuntu/Debian

   sudo apt-get update

2. **ARM Toolchain**: Ensure arm-none-eabi-gcc is installed and in PATH:   sudo apt-get install build-essential cmake ninja-build python3-pip

   ```bash

   arm-none-eabi-gcc --version   # macOS

   ```   brew install cmake ninja

   ```

3. **Build Dependencies**:

   ```bash### Building the Firmware

   # Ubuntu/Debian

   sudo apt-get update1. **Navigate to PX4 root directory**:

   sudo apt-get install build-essential cmake ninja-build python3-pip   ```bash

   cd ~/projects/PX4-Autopilot

   # macOS   ```

   brew install cmake ninja

   ```2. **Clean any previous builds** (recommended):

   ```bash

### Building the Firmware   make distclean

   # OR for specific target only:

1. **Navigate to PX4 root directory**:   make renesas_fpb-ra8e1_default clean

   ```bash   ```

   cd ~/px4_ra8/PX4-Autopilot

   ```3. **Build the firmware**:

   ```bash

2. **Clean any previous builds** (recommended):   # Standard build with PWM outputs

   ```bash   make renesas_fpb-ra8e1_default

   make distclean

   # OR for specific target only:   # DShot build for ESC communication

   make renesas_evk-ra8p1_default clean   make renesas_fpb-ra8e1_dshot

   ```

   # OR with verbose output for debugging

3. **Build the firmware**:   make renesas_fpb-ra8e1_default V=1

   ```bash   ```

   # Standard build with PWM outputs

   make renesas_evk-ra8p1_default4. **Build output**: The firmware will be generated as:

   ```

   # DShot build for ESC communication   build/renesas_fpb-ra8e1_default/platforms/nuttx/NuttX/nuttx/nuttx.hex

   make renesas_evk-ra8p1_dshot   build/renesas_fpb-ra8e1_default/platforms/nuttx/NuttX/nuttx/nuttx.bin

   build/renesas_fpb-ra8e1_default/platforms/nuttx/NuttX/nuttx/nuttx.elf

   # OR with verbose output for debugging

   make renesas_evk-ra8p1_default V=1   # For DShot build:

   ```   build/renesas_fpb-ra8e1_dshot/platforms/nuttx/NuttX/nuttx/nuttx.*

   ```

4. **Build output**: The firmware will be generated as:

   ```### Test Configuration Build

   build/renesas_evk-ra8p1_default/platforms/nuttx/NuttX/nuttx/nuttx.hex

   build/renesas_evk-ra8p1_default/platforms/nuttx/NuttX/nuttx/nuttx.binFor hardware validation and testing:

   build/renesas_evk-ra8p1_default/platforms/nuttx/NuttX/nuttx/nuttx.elf```bash

make renesas_fpb-ra8e1_test

   # For DShot build:```

   build/renesas_evk-ra8p1_dshot/platforms/nuttx/NuttX/nuttx/nuttx.*

   ```### DShot ESC Configuration



### Test Configuration BuildWhen using the DShot build target, you can configure DShot parameters:



For hardware validation and testing:```bash

```bash# Set DShot frequency (150, 300, or 600 kHz)

make renesas_evk-ra8p1_test# This is typically set via parameter DSHOT_CONFIG

```# 150 = DShot150, 300 = DShot300, 600 = DShot600



## Verification and Testing# Enable bidirectional DShot for ESC telemetry

# Set DSHOT_3D_ENABLE = 1 for 3D mode support

### Safety Precautions ⚠️```



**IMPORTANT**: Always follow these safety procedures:**DShot Channel Mapping**:

- **Channel 0** (Motor 1): P300 → GPT3A

1. **Remove propellers** during all testing- **Channel 1** (Motor 2): P415 → GPT0A

2. **Secure the board** to prevent movement during motor tests- **Channel 2** (Motor 3): P113 → GPT2A

3. **Use appropriate power supply** (7.4V recommended for testing, up to 12V supported)- **Channel 3** (Motor 4): P302 → GPT4A

4. **Have emergency stop** method ready (power disconnect)

5. **Test in controlled environment** away from people and property## Flash Instructions

6. **Verify all connections** before powering on

### Using Renesas e² studio / J-Link

### Basic System Checks

1. **Connect J-Link debugger** to the FPB-RA8E1 board

#### 1. Console Connection

Connect to SCI2 (P802/P801) at 115200 baud:2. **Open e² studio** and create a debug configuration:

```bash   - Target: R7FA8E1AFDCFB

# Using screen (Linux/macOS)   - Debugger: J-Link ARM

screen /dev/ttyUSB0 115200   - Connection: SWD



# Using minicom (Linux)3. **Load firmware**:

minicom -D /dev/ttyUSB0 -b 115200   - File → Import → Binary file

```   - Select `renesas_fpb-ra8e1_default.elf`

   - Flash to target

Expected output:

```### Using J-Link Commander

nsh>

``````bash

# Connect to target

#### 2. System StatusJLinkExe -device R7FA8E1AF -if SWD -speed 4000

```bash

nsh> uorb top# In J-Link console:

nsh> psconnect

nsh> freeloadfile build/renesas_fpb-ra8e1_default/renesas_fpb-ra8e1_default.hex

```r

g

**Pass criteria**:quit

- NSH prompt appears```

- No critical errors in logs

- Sufficient free memory (>100KB for RA8P1)### Alternative: Using make upload (if configured)



#### 3. Sensor Verification```bash

make renesas_fpb-ra8e1_default upload

**IMU Test**:```

```bash

nsh> icm20948 status**Note**: This requires proper J-Link setup in the build system.

nsh> listener sensor_accel

nsh> listener sensor_gyro## Verification and Testing

```

### Safety Precautions ⚠️

**Pass criteria**:

- Driver reports "OK" status**IMPORTANT**: Always follow these safety procedures:

- Acceleration shows ~9.8 m/s² on Z-axis when level

- Gyro values near zero when stationary1. **Remove propellers** during all testing

2. **Secure the board** to prevent movement during motor tests

**Barometer Test**:3. **Use appropriate power supply** (7.4V recommended for testing)

```bash4. **Have emergency stop** method ready (power disconnect)

nsh> bmp388 status5. **Test in controlled environment** away from people and property

nsh> listener sensor_baro6. **Verify all connections** before powering on

```

### Basic System Checks

**Pass criteria**:

- Driver reports "OK" status#### 1. Console Connection

- Pressure reading ~101325 Pa (sea level)Connect to SCI2 (P801/P802) at 115200 baud:

- Temperature reading reasonable (~20-25°C)```bash

# Using screen (Linux/macOS)

#### 4. PWM Output Testscreen /dev/ttyUSB0 115200



**⚠️ REMOVE PROPELLERS FIRST ⚠️**# Using minicom (Linux)

minicom -D /dev/ttyUSB0 -b 115200

```bash```

nsh> pwm_out status

nsh> pwm_out test -c 1 -p 1100Expected output:

nsh> pwm_out test -c 1 -p 1000  # Return to minimum```

```nsh>

```

**Pass criteria**:

- All 4 PWM channels active#### 2. System Status

- Motor responds to PWM commands```bash

- PWM frequency = 400Hznsh> uorb top

nsh> ps

#### 5. LED Testnsh> free

```bash```

nsh> led_control test

```**Pass criteria**:

- NSH prompt appears

**Pass criteria**:- No critical errors in logs

- All 3 LEDs cycle through patterns- Sufficient free memory (>50KB)

- LED1 (blue), LED2 (green), LED3 (red) functional

#### 3. Sensor Verification

## Troubleshooting

**IMU Test**:

### Build Issues```bash

nsh> icm20948 status

**Error: `'px4_platform_common/px4_config.h' file not found`**nsh> listener sensor_accel

- **Solution**: Ensure you're building from PX4-Autopilot root directorynsh> listener sensor_gyro

- **Command**: `make renesas_evk-ra8p1_default````



**Error: `arm-none-eabi-gcc: command not found`****Pass criteria**:

- **Solution**: Install ARM toolchain or add to PATH- Driver reports "OK" status

- **Ubuntu**: `sudo apt-get install gcc-arm-none-eabi`- Acceleration shows ~9.8 m/s² on Z-axis when level

- Gyro values near zero when stationary

**Error: `Unknown board 'renesas_evk-ra8p1'`**

- **Solution**: Verify board files are in correct directory structure**Barometer Test**:

- **Check**: `boards/renesas/evk-ra8p1/` exists with all files```bash

nsh> bmp388 status

### Runtime Issuesnsh> listener sensor_baro

```

**No NSH Prompt**

- Check UART connection and baud rate (115200)**Pass criteria**:

- Verify power supply (3.3V logic, adequate current)- Driver reports "OK" status

- Try different USB-UART adapter- Pressure reading ~101325 Pa (sea level)

- Ensure Pmod1 connector is properly seated- Temperature reading reasonable (~20-25°C)



**Sensors Not Found**#### 4. PWM Output Test

- Verify SPI connections on Pmod1 connector

- Check chip select GPIO configuration**⚠️ REMOVE PROPELLERS FIRST ⚠️**

- Ensure GY-912 module is properly connected

- Use oscilloscope to verify SPI signals```bash

nsh> pwm_out status

**PWM Not Working**nsh> pwm_out test -c 1 -p 1100

- Verify GPT timer configurationnsh> pwm_out test -c 1 -p 1000  # Return to minimum

- Check PWM pin assignments (P211, P109, P711, P708)```

- Ensure proper power supply for ESCs

- Test pins with multimeter for continuity**Pass criteria**:

- All 4 PWM channels active

## Additional Resources- Motor responds to PWM commands

- PWM frequency = 400Hz

- [PX4 Developer Guide](https://docs.px4.io/main/en/development/)

- [Renesas RA8P1 Datasheet](https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus/ra8p1-480mhz-arm-cortex-m85-trustzone-high-performance-microcontroller)#### 5. LED Test

- [EVK-RA8P1 User Manual](https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus/evk-ra8p1-evaluation-kit-ra8p1-mcu-group)```bash

- [ICM-20948 Datasheet](https://invensense.tdk.com/products/motion-tracking/9-axis/icm-20948/)nsh> led_control test

- [BMP388 Datasheet](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp388/)```



---**Pass criteria**:

- Both LEDs cycle through patterns

**Version**: 1.0.0  - LED1 (red) and LED2 (green) functional

**Last Updated**: January 2025

**Maintainer**: PX4 Development Team#### 6. RC Input Test (when connected)

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
