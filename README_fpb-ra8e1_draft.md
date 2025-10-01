# PX4 Support for Renesas FPB-RA8E1 Development Board

This directory contains the **experimental** PX4 board support package for the Renesas FPB-RA8E1 development board featuring the RA8E1 MCU (ARM Cortex-M85).

⚠️ **DEVELOPMENT STATUS**: This is an early-stage port with limited functionality. Only basic flight control is currently supported.

## Board Overview

The FPB-RA8E1 is a development board from Renesas featuring:

- **MCU**: R7FA8E1AFDCFB (ARM Cortex-M85 @ 360MHz)
- **RAM**: 512KB internal SRAM
- **Data Flash**: 12KB of data flash memory
- **Flash**: 1MB internal flash memory
- **Architecture**: ARMv8-M with TrustZone support
- **OS**: NuttX RTOS

## Hardware Features

### Currently Supported Interfaces ✅
- **Serial (SCI/UART)**: 3 ports for debug console and RC input
- **SPI**: 1 bus for sensor communication
- **PWM (GPT)**: 4 channels for motor control
- **GPIO**: Basic digital I/O pins

### Planned/Future Support 🚧
- **Sensors**: IMU (ICM-20948), Barometer (BMP388)
- **RC Input**: SBUS protocol support
- **ADC**: Battery voltage/current monitoring
- **I2C**: External sensor expansion
- **Storage**: Parameter storage in data flash

### Not Currently Supported ❌
- **CAN Bus**: Not implemented
- **USB**: Limited to power only
- **SDIO**: External storage not available
- **Telemetry**: MAVLink over additional UARTs
- **Safety Systems**: Safety switch, buzzers

## Pin Assignments (Current Implementation)

### Serial Ports (SCI/UART)
- **SCI0** (/dev/ttyS0): Telematry - Primary MAVLink P609(RX), P610(TX)
- **SCI2** (/dev/ttyS2): Debug console (NSH) - P802(RX), P801(TX)
- **SCI3** (/dev/ttyS3): RC input (SBUS) - P309(RX), P310(TX)

### SPI Bus
- **SPI1**: Sensor bus - P412(SCK), P411(MOSI), P410(MISO)
  - CS0 (P408): Reserved for IMU (ICM-20948)
  - CS1 (P407): Reserved for Barometer (BMP388)
  - DRDY (P409): IMU data ready interrupt

### PWM Outputs (GPT Timers)
- **Motor 1**: P300 (GPT3A)
- **Motor 2**: P415 (GPT0A)
- **Motor 3**: P113 (GPT2A)
- **Motor 4**: P302 (GPT4A)

### Status LEDs
- **LED1**: P404 (Green) - System status
- **LED2**: P408 (Green) - Activity (conflicts with SPI CS)

### User Interface
- **Button S1**: P009 (IRQ13) - User button
- **Buzzer**: P303 - Tone output (reserved)

### Arduino Connector Compatibility
- **I2C**: P511(SDA), P512(SCL) - Reserved for expansion
- **ADC**: A0-A5 pins available but not yet supported
  - A0: P004, A1: P003, A2: P007, A3: P001, A4: P014, A5: P015

## Building Firmware

### Prerequisites
- NuttX build environment configured
- ARM GCC toolchain installed
- J-Link software package

### Building
To build the basic PX4 firmware for FPB-RA8E1:

```bash
# Build the board support package
make renesas_fpb-ra8e1_default

# Clean build if needed
make renesas_fpb-ra8e1_default clean
```

**Note**: Build may require NuttX-specific configuration and dependencies.

## Flashing

### Using On-Board J-Link Debugger
1. Connect the FPB-RA8E1 board via USB-C
2. Ensure J-Link drivers are installed
3. Flash using J-Link Commander:

```bash
# Start J-Link Commander
JLinkExe

# Configure target
si 1                    # Select SWD interface
speed 4000              # Set speed to 4 MHz
device R7FA8E1AFDCFB    # Specify exact MCU part number
connect                 # Connect to target

# Programming sequence
r                       # Reset target
h                       # Halt CPU
erase                   # Full chip erase
loadfile px4_fmu-v6xrt_default.bin 0x00000000  # Load firmware
r                       # Reset
g                       # Start execution
exit                    # Quit J-Link
```

### Alternative: Using J-Flash
1. Open J-Flash application
2. Select device: R7FA8E1AFDCFB
3. Load firmware binary file
4. Program and verify
5. Reset and run

### Verification
After flashing, connect serial terminal (115200 baud) to see:
```
NuttX: Starting PX4 on Renesas FPB-RA8E1
nsh>
```

## Getting Started

### 1. Hardware Setup
1. Connect the FPB-RA8E1 board via USB-C
2. Connect a serial terminal to the debug port (115200 baud)
3. **DO NOT** connect propellers or flight hardware yet

### 2. Basic Testing
After flashing, you should see the NuttX shell:
```
nsh> help
nsh> px4
nsh> led_control test
nsh> pwm_out test
```

### 3. Development Workflow
1. **Hardware Validation**: Test LEDs, buttons, PWM outputs
2. **Sensor Development**: Work on SPI sensor drivers
3. **RC Input**: Implement and test SBUS reception
4. **Flight Control**: Integrate PX4 flight stack

⚠️ **Important**: This is development hardware only. Do not attempt flight operations.

## Default Configuration

⚠️ **Note**: This is a development configuration, not flight-ready.

- **Target**: Basic hardware validation
- **Console**: 115200 baud on SCI2 (debug)
- **PWM**: 400Hz output on 4 channels
- **Boot**: NuttX shell (NSH) prompt
- **Sensors**: Initialization only (drivers under development)

## Current Support Status

### ✅ Working Features
- **NuttX Boot**: System boots and runs NuttX shell
- **Debug Console**: Serial console access via SCI2
- **GPIO Control**: Basic pin control and LED operation
- **PWM Output**: 4-channel motor control via GPT timers
- **SPI Communication**: Bus initialization and basic transfers

### 🚧 In Development
- **Sensor Drivers**: ICM-20948 IMU and BMP388 barometer integration
- **RC Input**: SBUS receiver support via SCI3
- **Flight Control**: Basic attitude stabilization
- **Parameter Storage**: Using data flash memory

### ❌ Not Yet Supported
- **Navigation**: GPS, optical flow, advanced flight modes
- **Telemetry**: MAVLink communication
- **Safety Systems**: Arming checks, failsafes
- **Logging**: Flight data recording
- **Advanced Features**: Missions, autonomous flight

### Current Capabilities
This board support is suitable for:
- ✅ Basic hardware testing and validation
- ✅ NuttX development and debugging
- ✅ GPIO and PWM functionality testing
- ✅ SPI sensor communication development
- ❌ **NOT ready for flight operations**

## Troubleshooting

### Common Issues

**Board won't boot:**
- Check USB-C connection and power LED
- Verify firmware was flashed correctly
- Try erasing and reflashing

**No debug console:**
- Verify serial connection to SCI2 (P802/P801)
- Check baud rate (115200)
- Ensure proper USB-to-serial adapter

**PWM not working:**
- Check PWM pin assignments (P300, P415, P113, P302)
- Verify GPT timer initialization
- Test with oscilloscope or logic analyzer

**SPI communication issues:**
- Verify SPI1 pin connections (P412/P411/P410)
- Check chip select pins (P408, P407)
- Use SPI analyzer to debug communication

### Debug Console Commands

Connect to the debug console at 115200 baud on SCI2:
```bash
# Basic system info
nsh> uname -a
nsh> free
nsh> ps

# Hardware testing
nsh> led_control test
nsh> pwm_out test -c 1234 -p 1500

# Development commands
nsh> spi test 1
nsh> gpio read P404
```

## Development

### Current Development Priorities
1. **Sensor Integration**: Complete ICM-20948 and BMP388 drivers
2. **RC Input**: Implement SBUS protocol on SCI3
3. **Parameter Storage**: Utilize 12KB data flash
4. **Flight Control**: Basic attitude control loop

### Hardware Abstraction
Key files for board support:
- `board.h`: Pin definitions and GPIO mappings
- `board_config.h`: PX4-specific configuration
- `init.c`: Board initialization code
- `spi.c`: SPI bus configuration
- `timer_config.c`: PWM timer setup

### Testing Framework
Current testing capabilities:
```bash
# Hardware tests
nsh> led_control test
nsh> pwm_out test
nsh> spi test 1

# GPIO testing
nsh> gpio read P404
nsh> gpio write P404 1
```

### Adding New Features
1. Update NuttX board configuration
2. Modify PX4 board files
3. Test with hardware-in-the-loop
4. Document changes

### Debug Tools
- **J-Link**: On-board debugger
- **Serial Console**: Real-time debugging
- **Logic Analyzer**: SPI/UART protocol analysis
- **Oscilloscope**: PWM signal verification

## Support

For support and questions:
- PX4 Discord: https://discord.gg/px4
- PX4 Discuss: https://discuss.px4.io/
- GitHub Issues: https://github.com/PX4/PX4-Autopilot/issues

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Test thoroughly on hardware
4. Submit a pull request with clear description

## License

This board support package is licensed under the same terms as PX4 (BSD-3-Clause).
