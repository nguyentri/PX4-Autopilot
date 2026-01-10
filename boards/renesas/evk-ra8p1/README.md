# PX4 BSP Reference for EVK-RA8P1

---

## 1.1 Overview

The FMU-RA8P1 production board follows the dual-core architecture established in the EVK-RA8P1 development board, adapted for commercial drone applications. The folder structure separates CM85 (FMU) and CM33 (IO) firmware while sharing common NuttX BSP components.

---

## 1.2 Top-Level Structure

```text
boards/renesas/
├── evk-ra8p1/              # Development board (reference implementation)
├── evk-ra8p1-io-cm33/      # Development board CM33 firmware
```

---

## 1.3 CM85 FMU Firmware Structure (boards/renesas/evk-ra8p1/)

**Current Status:** ✅ **Single IMU and PWM output working** (ICM20948 on SPI1, GPT PWM functional)

```text
boards/renesas/evk-ra8p1/
│
├── cmake/
│   └── init.cmake                      # CMake build configuration
│
├── default.px4board                    # Main board configuration (IMU + PWM)
├── dshot.px4board                      # DShot ESC configuration (experimental)
├── test.px4board                       # Test/debug configuration
├── firmware.prototype                  # Firmware metadata
├── Kconfig                             # Board-specific Kconfig options
├── manifest.xml                        # Board manifest for build system
├── test_sensors.sh                     # Sensor verification script
│
├── init/                               # Startup scripts
│   ├── rc.board                       # Board-specific initialization
│   ├── rc.board_defaults              # Default parameters for FMU-RA8P1
│   └── rc.board_sensors               # Sensor startup configuration
│
├── nuttx-config/                       # NuttX BSP configuration
│   ├── bootloader/
│   │   └── defconfig                  # Bootloader NuttX configuration
│   ├── nsh/                           # NuttShell config directory
│   ├── scripts/                       # Linker scripts (CM85)
│   └── src/                           # NuttX board-specific drivers
│
├── px4io_cm85/                         # CM85-side IPC driver (communicates with CM33)
│   ├── CMakeLists.txt
│   ├── Kconfig
│   ├── px4io_cm85.cpp                 # Main IPC driver interface
│   ├── ipc_hardware_cm85.cpp          # Hardware IPC HAL for CM85
│   ├── ipc_hardware_cm85.h
│   └── ipc_protocol.h                 # Shared IPC protocol definitions (sync with CM33)
│
└── src/                                # PX4 board drivers and initialization
    ├── CMakeLists.txt
    ├── board_config.h                 # ⚠️ Pin mappings, bus assignments, peripherals
    ├── init.c                         # Board early initialization
    ├── board_common.c                 # Common board utilities
    ├── spi.cpp                        # ✅ SPI bus init (ICM20948 on SPI1)
    ├── i2c.cpp                        # ⚠️ I2C bus init - partial
    ├── i2c_funcs.c                    # I2C helper functions
    ├── timer_config.cpp               # ✅ GPT timer/PWM configuration
    ├── led.c                          # ✅ Status LED control
    ├── system_stubs.c                 # System call stubs
    └── include/                       # Board-specific headers
```

### Key Features
- ✅ **LED status:** Status LED control
- ✅ **Single IMU:** ICM20948 on SPI1 with internal AK09916 magnetometer
- ✅ **PWM Output:** GPT-based normal PWM for 4 motor channels (GPT3/5/11/13)
- ✅ **Serial UARTs:** 4 UART ports configured (SCI0/4/5/8)
- ⚠️ **I2C Bus:** Driver initialized without sensor testing
- 🔨 **IPC with CM33:** Framework exists, not runtime tested
- ❌ **RC Input:** Requires CM33 firmware to be operational
- ❌ **DShot ESC:** Not supported (normal PWM only)

---

## 1.4 CM33 IO Firmware Structure (boards/renesas/evk-ra8p1-io-cm33/)

**Current Status:** 🔨 **Builds successfully but not runtime tested** (CM33 firmware flashes but IPC not verified)

```text
boards/renesas/evk-ra8p1-io-cm33/
│
├── default.px4board                    # Board configuration file
├── firmware.prototype                  # Firmware metadata
│
├── extras/
│   └── .gitkeep                       # Placeholder for binaries
│
├── nuttx-config/                       # NuttX BSP configuration for CM33
│   ├── nsh/                           # NuttShell config directory
│   ├── scripts/                       # Linker scripts (CM33)
│   └── src/                           # NuttX CM33-specific drivers
│
├── px4io_ipc/                          # ❌ CM33-side IPC firmware (NOT WORKING YET)
│   ├── CMakeLists.txt
│   ├── Kconfig
│   │
│   ├── px4io.cpp                      # Main IO firmware entry point
│   ├── px4io.h
│   │
│   ├── ipc.cpp                        # IPC transport layer
│   ├── ipc.h
│   ├── ipc_hardware.cpp               # Hardware IPC HAL (CM33 side)
│   ├── ipc_hardware.h
│   ├── ipc_protocol.h                 # Shared IPC protocol (must sync with CM85)
│   ├── protocol.h                     # Legacy PX4IO protocol definitions
│   ├── transport_sharedmem.cpp        # Shared memory IPC implementation
│   │
│   ├── adc.cpp                        # Battery voltage/current monitoring
│   ├── controls.cpp                   # Actuator control logic
│   ├── pwm_out.cpp                    # PWM/DShot output generation
│   ├── pwm_out.h
│   ├── rc_decoder.cpp                 # RC input decoding (S.Bus, CRSF, CPPM)
│   ├── mixer.cpp                      # Actuator mixing (quad X, etc.)
│   ├── registers.c                    # Virtual register interface
│   │
│   ├── safety_button.cpp              # Safety switch handling
│   ├── failsafe.cpp                   # Failsafe logic (RC loss, CM85 timeout)
│   └── heartbeat_monitor.cpp          # CM85 heartbeat monitoring
│
└── src/                                # CM33 board initialization
    └── (board initialization files - minimal)
```

### Known Issues

- ❌ **IPC Not Verified:** Shared memory IPC between CM85↔CM33 not tested
- ❌ **RC Input:** RC decoder not validated
- ❌ **PWM Failsafe:** Failover to CM33 PWM not tested
- ❌ **Heartbeat Monitor:** CM85 watchdog not implemented

### Planned Architecture

- CM33 runs minimal firmware handling RC input and failsafe PWM
- IPC transfers actuator commands from CM85 to CM33
- CM33 monitors CM85 heartbeat, enters failsafe if timeout
- Shared memory at `0x22008000` (32 KB) for IPC buffers

---

## 1.5 PX4 Platform Layer

The PX4 platform layer provides hardware abstraction between NuttX BSP and PX4 middleware. The architecture is split into RA8-family common code and RA8P1-specific implementations.

### 1.5.1 RA8 Common Platform Code

**Location:** `platforms/nuttx/src/px4/renesas/ra8/`

| Directory        | Key Files         | Description                                             | Status         |
|:-----------------|:------------------|:--------------------------------------------------------|:---------------|
| `version/`       | -                 | Firmware version information                            | ✅ Working     |
| `board_hw_info/` | -                 | Hardware revision detection                             | ✅ Working     |
| `hrt/`           | `hrt.c`           | High-resolution timer using GPT0 for microsecond timing | ✅ Working     |
| `spi/`           | `spi.cpp`         | SPI bus initialization wrapper for sensor drivers       | ✅ Working     |
| `io_pins/`       | `io_timer_impl.c` | PWM/Timer implementation for actuators                  | ✅ Working     |
| `micro_hal/`     | `gpio.c`          | GPIO abstraction layer for pin control                  | ✅ Working     |
| `adc/`           | -                 | ADC voltage/current monitoring (battery, RSSI)          | 🔨 Build Only  |
| `board_critmon/` | -                 | Critical section monitoring for debugging               | ❌ Not Started |
| `board_reset/`   | -                 | Software reset implementation                           | ❌ Not Started |
| `cpuload/`       | -                 | CPU utilization measurement                             | ❌ Not Started |
| `dshot/`         | -                 | DShot ESC protocol implementation                       | 🔨 Build Only  |
| `led_pwm/`       | -                 | LED brightness control via PWM                          | ❌ Not Started |
| `tone_alarm/`    | -                 | Buzzer/tone generation                                  | ❌ Not Started |

### 1.5.2 RA8P1-Specific Platform Code

**Location:** `platforms/nuttx/src/px4/renesas/ra8p1/`

#### Hardware Description Headers

**Location:** `platforms/nuttx/src/px4/renesas/ra8p1/include/px4_arch/`

| Header File                 | Description               | Purpose                                    |
|:----------------------------|:--------------------------|:-------------------------------------------|
| `hw_description.h`          | Board hardware topology   | Defines board capabilities, sensors, buses |
| `spi_hw_description.h`      | SPI bus configuration     | SPI0: BMI088, SPI1: ICM42688-P             |
| `i2c_hw_description.h`      | I2C bus configuration     | I2C0: Baro1, I2C1: Baro2/FRAM, I2C2: Mag   |
| `io_timer_hw_description.h` | Timer/PWM channel mapping | GPT channels for PWM outputs               |
| `io_timer.h`                | Timer control API         | Timer enable/disable, frequency control    |
| `micro_hal.h`               | Microcontroller HAL       | Low-level hardware abstraction             |

#### Platform Headers

**Location:** `platforms/nuttx/src/px4/renesas/ra8p1/include/px4_platform/`

| Header File | Description              |
|:------------|:-------------------------|
| `cpuload.h` | CPU load measurement API |

#### Build Configuration

| File             | Description                      |
|:-----------------|:---------------------------------|
| `CMakeLists.txt` | PX4 platform build configuration |

---

## 1.6 NuttX BSP Platform Layer

The NuttX BSP for RA8P1 provides hardware abstraction for peripheral drivers, interrupt management, clocking, and memory configuration. The architecture follows NuttX conventions with RA8-family common code and RA8P1-specific implementations.

### 1.6.1 Core Architecture Files

#### Startup and Initialization

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_start.c                        # Boot sequence, vector table setup
├── ra_start.h                        # Startup declarations
├── ra_idle.c                         # Idle task implementation
├── ra_irq.c                          # Generic IRQ handling
├── ra_lowputc.c                      # Early console output
├── ra_timerisr.c                     # System tick timer ISR
└── ra_memmng.c                       # Memory management
```

#### Clock and Power Management

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_clock.c                         # Clock initialization
├── ra_clock.h                         # Clock control API
├── ra_mstp.c                          # Module Stop (MSTP) power gating
├── ra_mstp.h                          # MSTP API definitions
└── hardware/ra8p1/
    ├── ra_clock.c                     # RA8P1-specific clock configuration
    ├── ra_clock.h                     # RA8P1 clock definitions
    └── ra_mstp.h                      # RA8P1 MSTP register map
```

#### GPIO and Interrupts

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_gpio.c                          # GPIO configuration and control
├── ra_gpio.h                          # GPIO API
├── ra_icu.c                           # Interrupt Controller Unit (ICU)
├── ra_icu.h                           # ICU API
└── hardware/ra8p1/
    ├── ra_port.h                      # I/O port register definitions
    ├── ra_pfs.h                       # Pin Function Select registers
    ├── ra_icu.h                       # ICU register definitions
    └── ra_icu_common.h                # ICU common definitions
```

### 1.6.2 Communication Peripherals

#### SPI (Serial Peripheral Interface)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_spi.c                           # SPI driver implementation
├── ra_spi.h                           # SPI API
└── hardware/ra8p1/
    └── ra_spi_b.h                     # SPI Type B register definitions

Related NuttX Stack:
├── include/nuttx/spi/spi.h            # NuttX SPI subsystem API
└── drivers/spi/                       # SPI device drivers

PX4 Integration:
└── platforms/nuttx/src/px4/renesas/ra8/spi/
    └── spi.cpp                        # PX4 SPI bus wrapper
```

#### I2C (Inter-Integrated Circuit)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_i2c.c                           # I2C driver (IIC master)
├── ra_i2c.h                           # I2C API
├── ra_i2c_slave.c                     # I2C slave mode support
├── ra_sci_i2c.c                       # SCI as I2C master (alternative)
├── ra_sci_i2c.h                       # SCI-I2C API
└── hardware/ra8p1/
    ├── ra_iic.h                       # IIC register definitions
    └── ra_iic0wu.h                    # I2C0 wakeup unit
```

> **Note:** RA8P1 does not have RIIC peripheral. Use IIC (I2C standard) or SCI-I2C mode.

```text
Related NuttX Stack:
├── include/nuttx/i2c/i2c_master.h     # NuttX I2C master API
└── drivers/i2c/                       # I2C device drivers

PX4 Integration:
└── platforms/nuttx/src/px4/renesas/ra8/i2c/
    └── (I2C wrapper if needed)
```

#### UART/SCI (Serial Communication Interface)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_serial.c                        # Serial port driver (uses SCI)
└── hardware/ra8p1/
    └── ra_sci_b.h                     # SCI Type B register definitions

Related NuttX Stack:
├── include/nuttx/serial/serial.h      # NuttX serial API
└── drivers/serial/                    # Serial device core
```

#### CAN-FD (Controller Area Network)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_canfd.c                         # CAN-FD driver
├── ra_canfd.h                         # CAN-FD API
└── hardware/
    └── ra_canfd.h                     # CAN-FD register definitions

Related NuttX Stack:
├── include/nuttx/can.h                # NuttX CAN API
└── drivers/can/                       # CAN device core
```

#### Ethernet (ETH MAC)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_ether.c                         # Ethernet MAC driver
├── ra_ether.h                         # Ethernet API
├── ra_ether_rmac.c                    # Redundant MAC driver
├── ra_ether_rmac.h                    # RMAC API
├── ra_ether_phy.c                     # Ethernet PHY abstraction
├── ra_ether_phy.h                     # PHY API
├── ra_ether_phy_*.c                   # Specific PHY drivers (DP83620, GPY111, etc.)
└── hardware/ra8p1/
    ├── ra_etha.h                      # Ethernet Acceleration registers
    ├── ra_etherc_edmac.h              # Ethernet MAC + DMA registers
    ├── ra_rmac.h                      # Redundant MAC registers
    └── ra_eswm.h                      # Ethernet Switch Module

Related NuttX Stack:
├── include/nuttx/net/                 # NuttX network stack
└── drivers/net/                       # Network device drivers
```

#### USB High-Speed

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_usbdev.c                        # USB device controller
├── ra_usbdev.h                        # USB API
├── ra8_usbdev.h                       # RA8 USB common definitions
└── hardware/ra8p1/
    ├── ra_usb_hs.h                    # USB High-Speed registers
    ├── ra_usb_fs.h                    # USB Full-Speed registers
    ├── ra_usbhs.h                     # USB HS controller
    └── ra_usbfs.h                     # USB FS controller

Related NuttX Stack:
├── include/nuttx/usb/                 # NuttX USB subsystem
└── drivers/usbdev/                    # USB device core
```

### 1.6.3 Timer and PWM Peripherals

#### GPT (General PWM Timer)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_gpt.c                           # GPT timer driver
├── ra_gpt.h                           # GPT API
├── ra_timerisr.c                      # System tick timer
└── hardware/ra8p1/
    ├── ra_gpt32.h                     # 32-bit GPT register definitions
    ├── ra_gpt_gtclk.h                 # GPT clock control
    ├── ra_gpt_odc.h                   # Output Delay Control
    ├── ra_gpt_ops.h                   # Output Protection Stop
    └── ra_gpt_poeg.h                  # Port Output Enable for GPT

Related NuttX Stack:
├── include/nuttx/timers/              # NuttX timer subsystem
└── drivers/timers/                    # Timer device drivers

PX4 Integration:
└── platforms/nuttx/src/px4/renesas/ra8/
    ├── hrt/hrt.c                      # High-resolution timer (GPT0)
    └── io_pins/io_timer_impl.c        # PWM/DShot timer control
```

#### AGT (Asynchronous General-Purpose Timer)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_agt.c                           # AGT timer driver
├── ra_agt.h                           # AGT API
└── hardware/ra8p1/
    ├── ra_agt.h                       # AGT register definitions
    └── ra_agtx.h                      # AGT extended registers
```

### 1.6.4 Storage and Memory Peripherals

#### SDHI (SD Host Interface)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_sdhi.c                          # SDHI controller driver
├── ra_sdhi.h                          # SDHI API
└── hardware/ra8p1/
    └── ra_sdhi.h                      # SDHI register definitions

Related NuttX Stack:
├── include/nuttx/sdio.h               # NuttX SDIO API
└── drivers/mmcsd/                     # MMC/SD card drivers
```

#### SDRAM Controller

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_sdram.c                         # External SDRAM initialization
├── ra_sdram.h                         # SDRAM API
└── hardware/ra8p1/
    └── ra_sdram.h                     # SDRAM controller registers
```

#### Data Flash / MRAM

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_mram.c                          # Internal MRAM driver
├── ra_mram.h                          # MRAM API
└── hardware/ra8p1/
    ├── ra_mram.h                      # MRAM register definitions
    ├── ra_mrms.h                      # MRAM Sector Management
    └── ra_flash.h                     # Flash controller registers
```

### 1.6.5 DMA and Data Transfer

#### DMAC (Direct Memory Access Controller)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_dmac.c                          # DMAC driver
├── ra_dmac.h                          # DMAC API
└── hardware/
    └── ra_dmac.h                      # DMAC register definitions

Related NuttX Stack:
└── include/nuttx/dma/                 # NuttX DMA subsystem
```

#### DTC (Data Transfer Controller)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_dtc.c                           # DTC driver (lightweight DMA)
├── ra_dtc.h                           # DTC API
└── hardware/
    └── ra_dtc.h                       # DTC register definitions
```

### 1.6.6 Analog and Sensor Interfaces

#### ADC (Analog-to-Digital Converter)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_adc.c                           # ADC driver
├── ra_adc.h                           # ADC API
└── hardware/
    └── ra_adc.h                       # ADC register definitions

Related NuttX Stack:
├── include/nuttx/analog/adc.h         # NuttX ADC API
└── drivers/analog/                    # ADC device drivers
```

#### I3C (Improved Inter-Integrated Circuit)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_i3c.c                           # I3C driver (future)
├── ra_i3c.h                           # I3C API
└── hardware/
    └── ra_i3c.h                       # I3C register definitions
```

#### MIPI CSI-2 (Camera Interface)

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_mipi_csi.c                      # MIPI CSI-2 driver (future)
└── hardware/
    └── ra_mipi.h                      # MIPI PHY register definitions
```

### 1.6.7 System Support and Utilities

#### Interrupt Management

```text
platforms/nuttx/NuttX/nuttx/arch/arm/include/ra8/
├── ra8p1_irq.h                        # RA8P1 IRQ number definitions
├── irq.h                              # Generic ARM IRQ handling
└── chip.h                             # Chip-specific definitions

platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra8_irq.c                          # IRQ dispatcher
└── hardware/
    └── ra_nvic.h                      # NVIC register definitions
```

#### Memory Management

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_memmng.c                        # Memory layout configuration
└── hardware/
    ├── ra_memorymap.h                 # Physical memory map
    └── ra8p1/
        ├── ra_sram.h                  # SRAM configuration
        └── ra_tcm.h                   # Tightly Coupled Memory
```

#### Watchdog Timer

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/
├── ra_wdt.c                           # Watchdog timer driver
├── ra_wdt.h                           # WDT API
├── ra_iwdt.c                          # Independent Watchdog driver
├── ra_iwdt.h                          # IWDT API
└── hardware/ra8p1/
    ├── ra_wdt.h                       # WDT register definitions
    └── ra_iwdt.h                      # IWDT register definitions

Related NuttX Stack:
├── include/nuttx/timers/watchdog.h    # NuttX watchdog API
└── drivers/timers/watchdog.c          # Watchdog core
```

### 1.6.8 Board-Specific Configuration

#### EVK-RA8P1 Board Files

```text
platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/
├── include/
│   └── board.h                        # Board hardware configuration
├── configs/
│   ├── nsh/defconfig                  # NuttShell configuration
│   └── bootloader/defconfig           # Bootloader configuration
├── scripts/
│   ├── evk-ra8p1.ld                   # Linker script (non-OSPI)
│   ├── ospi/evk-ra8p1.ld              # Linker script (OSPI XIP)
│   ├── renesas_ofs_defs.ld            # OFS register definitions
│   └── renesas_ofs_sections.ld        # OFS linker sections
├── src/
│   ├── ra8p1_bringup.c                # Board initialization
│   ├── ra8p1_autoleds.c               # LED control
│   ├── ra8p1_buttons.c                # Button/switch handling
│   └── ra8p1_appinit.c                # Application initialization
└── Kconfig                            # Board configuration options
```

#### EVK-RA8P1-IO-CM33 Board Files

```text
platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1-io-cm33/
├── include/
│   └── board.h                        # CM33 hardware configuration
├── configs/
│   └── nsh/defconfig                  # CM33 NuttShell configuration
├── scripts/
│   ├── evk-ra8p1-io-cm33.ld           # CM33 linker script
│   ├── renesas_ofs_defs.ld            # OFS definitions
│   └── renesas_ofs_sections.ld        # OFS sections
└── src/
    ├── ra8p1_cm33_bringup.c           # CM33 initialization
    └── ra8p1_cm33_ipc.c               # IPC hardware setup
```

### 1.6.9 PX4 Integration Layer

#### Common RA8 Platform Code

```text
platforms/nuttx/src/px4/renesas/ra8/
├── hrt/
│   └── hrt.c                          # High-resolution timer (GPT0)
├── spi/
│   └── spi.cpp                        # SPI bus wrapper
├── io_pins/
│   └── io_timer_impl.c                # PWM/Timer implementation
├── micro_hal/
│   └── gpio.c                         # GPIO abstraction
└── board_hw_version/
    └── hw_version.c                   # Hardware revision detection
```

#### RA8P1-Specific Platform Code

```text
platforms/nuttx/src/px4/renesas/ra8p1/
├── include/px4_arch/
│   ├── hw_description.h               # Hardware layout
│   ├── io_timer_hw_description.h      # Timer channel mapping
│   ├── spi_hw_description.h           # SPI bus mapping
│   └── i2c_hw_description.h           # I2C bus mapping
└── (architecture-specific adaptations)
```

### 1.6.10 Hardware Register Definitions

#### RA8P1-Specific Hardware Headers

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/hardware/ra8p1/`

Key configuration files:

```text
├── ra_pinmap.h                        # Complete pin mapping for RA8P1
├── ra_clock.c                         # Clock tree implementation (source file)
├── ra_clock.h                         # Clock configuration registers
└── (95+ peripheral register headers - see section 20.6.12 for complete list)
```

#### Common RA8 Hardware Headers

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/hardware/`

```text
├── ra_clock.h                         # Common clock control definitions
├── ra_hardware.h                      # Hardware abstraction layer
├── ra_memorymap.h                     # Physical memory map
└── ra_pinmap.h                        # Common pin mapping definitions
```

#### IRQ Definitions

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/include/ra8/`

```text
└── ra8p1_irq.h                        # RA8P1 IRQ number definitions
                                       # Maps FSP ELC events to NuttX ICU vectors
```

### 1.6.11 Kconfig Build System

#### RA8 Family Configuration

```text
platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/Kconfig
├── General RA8 architecture options
├── Clock configuration (PLL, HOCO, LOCO)
├── Peripheral enable flags (SPI, I2C, UART, etc.)
├── Memory configuration (ITCM, DTCM, SRAM)
├── DMA/DTC selection
└── Debug options (RTT, UART console)
```

#### Board-Specific Configuration

```text
platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/Kconfig
├── Board revision selection
├── Peripheral routing (pin mux conflicts)
├── Boot options (OSPI XIP, MRAM boot)
└── Board-specific features
```

### 1.6.12 RA8P1 Hardware Register Definitions (Complete)

The NuttX BSP includes comprehensive hardware register definitions for the RA8P1 SoC.

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/hardware/ra8p1/`

| Register Header     | Peripheral | Description                               |
|:--------------------|:-----------|:------------------------------------------|
| `ra_acmphs.h`       | ACMPHS     | Analog Comparator High Speed              |
| `ra_adc_b.h`        | ADC-B      | 12-bit A/D Converter Type B               |
| `ra_agt.h`          | AGT        | Asynchronous General Purpose Timer (base) |
| `ra_agtx.h`         | AGT        | AGT extended registers                    |
| `ra_bus.h`          | BUS        | Bus controller registers                  |
| `ra_cac.h`          | CAC        | Clock Frequency Accuracy Measurement      |
| `ra_cache.h`        | CACHE      | L1 Cache controller                       |
| `ra_canfd.h`        | CAN-FD     | CAN with Flexible Data-Rate               |
| `ra_ceu.h`          | CEU        | Capture Engine Unit                       |
| `ra_clock.c`        | CLOCK      | Clock tree implementation                 |
| `ra_clock.h`        | CLOCK      | Clock system registers                    |
| `ra_coma.h`         | COMA       | Communication Area                        |
| `ra_cpscu.h`        | CPSCU      | Cache/Protection Security Control         |
| `ra_cpu_ctrl.h`     | CPU        | CPU control registers                     |
| `ra_cpu_dbg.h`      | CPU        | CPU debug registers                       |
| `ra_cpu_ocd.h`      | CPU        | On-Chip Debug registers                   |
| `ra_crc.h`          | CRC        | CRC calculation unit                      |
| `ra_dac_b.h`        | DAC-B      | 12-bit D/A Converter Type B               |
| `ra_debug_ocd.h`    | DEBUG      | On-Chip Debug interface                   |
| `ra_debug.h`        | DEBUG      | Debug registers                           |
| `ra_dma.h`          | DMA        | DMA common definitions                    |
| `ra_dmac.h`         | DMAC       | DMA Controller                            |
| `ra_doc_b.h`        | DOC-B      | Data Operation Circuit Type B             |
| `ra_doc.h`          | DOC        | Data Operation Circuit                    |
| `ra_dotf.h`         | DOTF       | On-the-fly Decryption                     |
| `ra_drw.h`          | DRW        | 2D Drawing Engine                         |
| `ra_dtc.h`          | DTC        | Data Transfer Controller                  |
| `ra_eccmb.h`        | ECCMB      | ECC for Message Buffer                    |
| `ra_elc.h`          | ELC        | Event Link Controller                     |
| `ra_eswm.h`         | ESWM       | Ethernet Switch Module                    |
| `ra_etha.h`         | ETHA       | Ethernet Acceleration                     |
| `ra_etherc_edmac.h` | ETHER      | Ethernet MAC + DMA                        |
| `ra_fcache.h`       | FCACHE     | Flash Cache controller                    |
| `ra_glcdc.h`        | GLCDC      | Graphics LCD Controller                   |
| `ra_gpt_gtclk.h`    | GPT        | GPT clock control                         |
| `ra_gpt_odc.h`      | GPT        | Output Delay Control                      |
| `ra_gpt_ops.h`      | GPT        | Output Protection Stop                    |
| `ra_gpt_poeg.h`     | GPT/POEG   | Port Output Enable for GPT                |
| `ra_gpt32.h`        | GPT32      | 32-bit General PWM Timer                  |
| `ra_gptp.h`         | gPTP       | Generalized Precision Time Protocol       |
| `ra_gwca.h`         | GWCA       | Gigabit Switch                            |
| `ra_i3c.h`          | I3C        | Improved Inter-Integrated Circuit         |
| `ra_icu_common.h`   | ICU        | Interrupt Controller common               |
| `ra_icu.h`          | ICU        | Interrupt Controller Unit                 |
| `ra_iic.h`          | IIC        | Inter-IC Bus                              |
| `ra_iic0wu.h`       | IIC        | I2C Wakeup Unit                           |
| `ra_ipc.h`          | IPC        | Inter-Processor Communication             |
| `ra_iwdt.h`         | IWDT       | Independent Watchdog Timer                |
| `ra_mfwd.h`         | MFWD       | MAC Forwarding                            |
| `ra_mipi_csi.h`     | MIPI-CSI   | Camera Serial Interface                   |
| `ra_mipi_dsi.h`     | MIPI-DSI   | Display Serial Interface                  |
| `ra_mipi_phy.h`     | MIPI-PHY   | MIPI Physical Layer                       |
| `ra_mpu_mmpu.h`     | MPU/MMPU   | Memory Protection Unit                    |
| `ra_mpu_spmon.h`    | SPMON      | Stack Pointer Monitor                     |
| `ra_mram.h`         | MRAM       | Magnetoresistive RAM                      |
| `ra_mrms.h`         | MRMS       | MRAM Sector Management                    |
| `ra_mstp.h`         | MSTP       | Module Stop Control                       |
| `ra_npu.h`          | NPU        | Neural Processing Unit                    |
| `ra_ospi_b.h`       | OSPI-B     | Octal-SPI Type B                          |
| `ra_pdg.h`          | PDG        | Pulse Density Generator                   |
| `ra_pdm.h`          | PDM        | Pulse Density Modulation                  |
| `ra_pdmif.h`        | PDMIF      | PDM Interface                             |
| `ra_pfs.h`          | PFS        | Pin Function Select                       |
| `ra_pinmap.h`       | PINMAP     | Pin Multiplexing Map                      |
| `ra_pmisc.h`        | PMISC      | Port Miscellaneous                        |
| `ra_poeg.h`         | POEG       | Port Output Enable for GPT                |
| `ra_port.h`         | PORT       | I/O Port registers                        |
| `ra_pscu.h`         | PSCU       | Peripheral Security Control               |
| `ra_rmac.h`         | RMAC       | Redundant MAC                             |
| `ra_rmpu.h`         | RMPU       | Register Memory Protection                |
| `ra_rtc.h`          | RTC        | Real Time Clock                           |
| `ra_sci_b.h`        | SCI-B      | Serial Communications Interface Type B    |
| `ra_sdhi.h`         | SDHI       | SD Host Interface                         |
| `ra_sdram.h`        | SDRAM      | External SDRAM Controller                 |
| `ra_spi_b.h`        | SPI-B      | SPI Type B                                |
| `ra_sram.h`         | SRAM       | Internal SRAM                             |
| `ra_ssi.h`          | SSI        | Serial Sound Interface                    |
| `ra_ssie.h`         | SSIE       | SSI Enhanced                              |
| `ra_sysc.h`         | SYSC       | System Controller                         |
| `ra_tcm.h`          | TCM        | Tightly Coupled Memory                    |
| `ra_tsd.h`          | TSD        | Temperature Sensor                        |
| `ra_tsn_cal.h`      | TSN        | Time-Sensitive Networking Cal             |
| `ra_tsn_ctrl.h`     | TSN        | TSN Control                               |
| `ra_tsn.h`          | TSN        | Time-Sensitive Networking                 |
| `ra_ulpt.h`         | ULPT       | Ultra Low-Power Timer                     |
| `ra_usb_fs.h`       | USB-FS     | USB Full-Speed                            |
| `ra_usb_hs.h`       | USB-HS     | USB High-Speed                            |
| `ra_usbfs.h`        | USB-FS     | USB Full-Speed (alt)                      |
| `ra_usbhs.h`        | USB-HS     | USB High-Speed (alt)                      |
| `ra_vin.h`          | VIN        | Video Input                               |
| `ra_wdt.h`          | WDT        | Watchdog Timer                            |
| `ra_xspi.h`         | xSPI       | Extended SPI                              |

#### Common RA8 Hardware Headers

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/hardware/`

| Header           | Description                     |
|:-----------------|:--------------------------------|
| `ra_clock.h`     | Clock system common definitions |
| `ra_hardware.h`  | Hardware abstraction layer      |
| `ra_memorymap.h` | Physical memory map             |
| `ra_pinmap.h`    | Common pin mapping              |

#### IRQ Definitions

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/include/ra8/`

| Header        | Description                                                     |
|:--------------|:----------------------------------------------------------------|
| `ra8p1_irq.h` | RA8P1 IRQ number definitions (maps FSP ELC events to NuttX ICU) |

### 1.6.13 RA8 Architecture Driver Files

**Location:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/`

| Driver File                 | Header               | Peripheral | Description                                  |
|:----------------------------|:---------------------|:-----------|:---------------------------------------------|
| `ra_adc_b.c`                | `ra_adc_b.h`         | ADC-B      | ADC Type B driver                            |
| `ra_adc.c`                  | `ra_adc.h`           | ADC        | Legacy ADC driver                            |
| `ra_agt.c`                  | `ra_agt.h`           | AGT        | Low Power Asynchronous General Purpose Timer |
| `ra_cac.c`                  | `ra_cac.h`           | CAC        | Clock Accuracy Measurement                   |
| `ra_canfd.c`                | `ra_canfd.h`         | CAN-FD     | CAN-FD driver                                |
| `ra_clock.c`                | `ra_clock.h`         | CLOCK      | Clock configuration                          |
| `ra_dmac.c`                 | `ra_dmac.h`          | DMAC       | DMA Controller                               |
| `ra_dtc.c`                  | `ra_dtc.h`           | DTC        | Data Transfer Controller                     |
| `ra_elc.c`                  | `ra_elc.h`           | ELC        | Event Link Controller                        |
| `ra_ether_phy.c`            | `ra_ether_phy.h`     | ETH-PHY    | Ethernet PHY abstraction                     |
| `ra_ether_phy_dp83620.c`    | -                    | ETH-PHY    | TI DP83620 PHY driver                        |
| `ra_ether_phy_gpy111.c`     | -                    | ETH-PHY    | Maxlinear GPY111 PHY                         |
| `ra_ether_phy_ics1894.c`    | -                    | ETH-PHY    | ICS1894 PHY driver                           |
| `ra_ether_phy_ksz8041.c`    | -                    | ETH-PHY    | Microchip KSZ8041 PHY                        |
| `ra_ether_phy_ksz8091rnb.c` | -                    | ETH-PHY    | Microchip KSZ8091RNB                         |
| `ra_ether_rmac.c`           | `ra_ether_rmac.h`    | RMAC       | Redundant MAC driver                         |
| `ra_ether.c`                | `ra_ether.h`         | ETHER      | Ethernet MAC driver                          |
| `ra_gpio.c`                 | `ra_gpio.h`          | GPIO       | GPIO driver                                  |
| `ra_gpt.c`                  | `ra_gpt.h`           | GPT        | General PWM Timer                            |
| `ra_i2c_slave.c`            | -                    | I2C        | I2C slave mode                               |
| `ra_i2c.c`                  | `ra_i2c.h`           | I2C        | I2C master driver                            |
| `ra_i3c.c`                  | `ra_i3c.h`           | I3C        | I3C driver                                   |
| `ra_icu.c`                  | `ra_icu.h`           | ICU        | Interrupt Controller                         |
| `ra_idle.c`                 | -                    | CPU        | Idle task                                    |
| `ra_ipc_ipcc.c`             | -                    | IPC        | Inter-Processor IPCC                         |
| `ra_ipc.c`                  | `ra_ipc.h`           | IPC        | IPC driver                                   |
| `ra_irq.c`                  | -                    | IRQ        | IRQ dispatcher                               |
| `ra_iwdt.c`                 | `ra_iwdt.h`          | IWDT       | Independent Watchdog                         |
| `ra_lowputc.c`              | -                    | UART       | Low-level console output                     |
| `ra_lpm.c`                  | `ra_lpm.h`           | LPM        | Low Power Mode                               |
| `ra_mbed_crypto.c`          | `ra_mbed_crypto.h`   | CRYPTO     | Mbed TLS crypto accel                        |
| `ra_memmng.c`               | -                    | MEM        | Memory management                            |
| `ra_mipi_csi.c`             | `ra_mipi_csi.h`      | MIPI-CSI   | Camera interface                             |
| `ra_mram.c`                 | `ra_mram.h`          | MRAM       | MRAM flash driver                            |
| `ra_mstp.c`                 | `ra_mstp.h`          | MSTP       | Module Stop control                          |
| `ra_ospi_b.c`               | `ra_ospi_b.h`        | OSPI-B     | Octal-SPI driver                             |
| `ra_ov5640.c`               | `ra_ov5640.h`        | CAMERA     | OV5640 sensor driver                         |
| `ra_poeg.c`                 | `ra_poeg.h`          | POEG       | Port Output Enable                           |
| `ra_rtc_lowerhalf.c`        | `ra_rtc_lowerhalf.h` | RTC        | RTC lower-half                               |
| `ra_rtc.c`                  | `ra_rtc.h`           | RTC        | Real Time Clock                              |
| `ra_sci_i2c.c`              | `ra_sci_i2c.h`       | SCI-I2C    | SCI as I2C master                            |
| `ra_sci_spi.c`              | `ra_sci_spi.h`       | SCI-SPI    | SCI as SPI master                            |
| `ra_sdhi.c`                 | `ra_sdhi.h`          | SDHI       | SD Host Interface                            |
| `ra_sdram.c`                | `ra_sdram.h`         | SDRAM      | External SDRAM                               |
| `ra_serial.c`               | -                    | UART       | Serial port driver                           |
| `ra_spi.c`                  | `ra_spi.h`           | SPI        | SPI driver                                   |
| `ra_start.c`                | `ra_start.h`         | STARTUP    | Boot sequence CM85                           |
| `ra_start_cm33.c`           | `ra_start.h`         | STARTUP    | Boot sequence CM33                           |
| `ra_timerisr.c`             | -                    | TICK       | System tick timer                            |
| `ra_ulpt.c`                 | `ra_ulpt.h`          | ULPT       | Ultra Low-Power Timer                        |
| `ra_usbdev.c`               | `ra_usbdev.h`        | USB        | USB device controller                        |
| `ra_wdt.c`                  | `ra_wdt.h`           | WDT        | Watchdog Timer                               |

#### Build Configuration

| File        | Description                      |
|:------------|:---------------------------------|
| `Kconfig`   | RA8 family configuration options |
| `Make.defs` | Build system definitions         |

### 1.6.14 EVK-RA8P1 Board Support Package

**Location:** `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/`

#### Available Configurations (configs/)

| Config             | Description                                  |
|:-------------------|:---------------------------------------------|
| `adc-b/`           | ADC Type B demonstration                     |
| `adc-b-hwtrigger/` | ADC with hardware trigger                    |
| `agt/`             | Low Power Asynchronous General Purpose Timer |
| `cac/`             | Clock Accuracy Measurement                   |
| `canfd/`           | CAN-FD networking                            |
| `ether/`           | Ethernet networking                          |
| `gps/`             | GPS UART configuration                       |
| `i2c/`             | I2C master demonstration                     |
| `i3c/`             | I3C demonstration                            |
| `ipc-cm33/`        | IPC from CM33 perspective                    |
| `ipc-cm85/`        | IPC from CM85 perspective                    |
| `iwdt/`            | Independent Watchdog                         |
| `lpm/`             | Low Power Mode                               |
| `mbed-crypto/`     | Crypto accelerator                           |
| `mipi-csi/`        | Camera interface                             |
| `mram/`            | MRAM flash demonstration                     |
| `nsh/`             | NuttShell base config                        |
| `nsh-leds/`        | NSH with LED control                         |
| `ospi-b/`          | Octal-SPI flash                              |
| `poeg/`            | Port Output Enable                           |
| `pwm/`             | PWM output                                   |
| `rtc/`             | Real Time Clock                              |
| `sci-i2c/`         | SCI as I2C master                            |
| `sci-spi/`         | SCI as SPI master                            |
| `sdhi/`            | SD card interface                            |
| `sdram/`           | External SDRAM                               |
| `spi-loopback/`    | SPI loopback test                            |
| `usb-pcdc/`        | USB CDC serial                               |
| `wdt-cm33/`        | CM33 Watchdog                                |
| `wdt-cm85/`        | CM85 Watchdog                                |

#### Board Source Files (src/)

| Source File               | Description               |
|:--------------------------|:--------------------------|
| `evk-ra8p1.h`             | Board header definitions  |
| `ra8p1_adc_b_hwtrigger.c` | ADC hardware trigger init |
| `ra8p1_adc_b.c`           | ADC Type B board init     |
| `ra8p1_agt.c`             | AGT board initialization  |
| `ra8p1_app_examples.c`    | Application examples      |
| `ra8p1_auto_leds.c`       | Auto LED control          |
| `ra8p1_boot.c`            | Board boot sequence       |
| `ra8p1_bringup.c`         | Board bringup             |
| `ra8p1_buttons.c`         | Button handling           |
| `ra8p1_cac.c`             | CAC board init            |
| `ra8p1_canfd.c`           | CAN-FD board init         |
| `ra8p1_elc.c`             | ELC board init            |
| `ra8p1_ether.c`           | Ethernet board init       |
| `ra8p1_gpio.c`            | GPIO board init           |
| `ra8p1_i2c.c`             | I2C board init            |
| `ra8p1_i3c.c`             | I3C board init            |
| `ra8p1_ipc_test.c`        | IPC test application      |
| `ra8p1_ipc.c`             | IPC board init            |
| `ra8p1_iwdg.c`            | IWDG board init           |
| `ra8p1_iwdt.c`            | IWDT board init           |
| `ra8p1_lpm.c`             | Low Power Mode init       |
| `ra8p1_mbed_crypto.c`     | Crypto board init         |
| `ra8p1_mipi_csi.c`        | MIPI-CSI board init       |
| `ra8p1_mram.c`            | MRAM board init           |
| `ra8p1_opeg.c`            | POEG board init           |
| `ra8p1_ospi_b.c`          | OSPI board init           |
| `ra8p1_ospi_test.c`       | OSPI test application     |
| `ra8p1_pwm.c`             | PWM board init            |
| `ra8p1_rtc.c`             | RTC board init            |
| `ra8p1_sci_i2c.c`         | SCI-I2C board init        |
| `ra8p1_sci_spi.c`         | SCI-SPI board init        |
| `ra8p1_sdhi.c`            | SDHI board init           |
| `ra8p1_sdram.c`           | SDRAM board init          |
| `ra8p1_spi_loopback.c`    | SPI loopback init         |
| `ra8p1_usb.c`             | USB board init            |
| `ra8p1_user_leds.c`       | User LED control          |
| `ra8p1_wdg_test.c`        | Watchdog test             |
| `ra8p1_wdt.c`             | WDT board init            |

#### Board Include Files (include/)

| File      | Description                  |
|:----------|:-----------------------------|
| `board.h` | Board hardware configuration |

#### Linker Scripts (scripts/)

| Path                             | Description            |
|:---------------------------------|:-----------------------|
| `Make.defs`                      | Linker configuration   |
| `non-ospi/evk-ra8p1_non_ospi.ld` | Non-OSPI linker script |
| `non-ospi/cm33/`                 | CM33 non-OSPI scripts  |
| `non-ospi/cm85/`                 | CM85 non-OSPI scripts  |
| `ospi/evk-ra8p1.ld`              | OSPI XIP linker script |
| `ospi/cm33/`                     | CM33 OSPI scripts      |
| `ospi/cm85/`                     | CM85 OSPI scripts      |
| `ospi/common/`                   | Shared OSPI includes   |

### 1.6.15 Driver Support Status Summary

| Category    | Peripheral | NuttX Driver       | Hardware Header     | NuttX Status  | PX4 Integration    | Notes                   |
|:------------|:-----------|:-------------------|:--------------------|:--------------|:-------------------|:------------------------|
| **Core**    | Clock      | `ra_clock.c`       | `ra_clock.h`        | ✅ Tested     | ✅ Complete        | PLL/HOCO/LOCO           |
| **Core**    | GPIO       | `ra_gpio.c`        | `ra_port.h`         | ✅ Tested     | ✅ Complete        | Interrupt support       |
| **Core**    | ICU        | `ra_icu.c`         | `ra_icu.h`          | ✅ Tested     | ✅ Complete        | IRQ routing             |
| **Core**    | MSTP       | `ra_mstp.c`        | `ra_mstp.h`         | ✅ Tested     | ✅ Complete        | Power gating            |
| **Comm**    | SPI        | `ra_spi.c`         | `ra_spi_b.h`        | ✅ Tested     | ✅ Complete        | SPI0, SPI1              |
| **Comm**    | SCI/UART   | `ra_serial.c`      | `ra_sci_b.h`        | ✅ Tested     | ✅ Complete        | All SCI                 |
| **Timer**   | GPT        | `ra_gpt.c`         | `ra_gpt32.h`        | ⚠️ Partial    | ⚠️ PWM out and HRT | PWM output, Timer & Input Capture |
| **Comm**    | I2C        | `ra_i2c.c`         | `ra_iic.h`          | 🔨 Build Only | 🔨 Build Only      | I2C0-2                  |
| **Comm**    | SCI-I2C    | `ra_sci_i2c.c`     | `ra_sci_b.h`        | 🔨 Build Only | ❌ Not Used        | SCI as I2C              |
| **Comm**    | SCI-SPI    | `ra_sci_spi.c`     | `ra_sci_b.h`        | 🔨 Build Only | ❌ Not Used        | SCI as SPI              |
| **Comm**    | CAN-FD     | `ra_canfd.c`       | `ra_canfd.h`        | 🔨 Build Only | ❌ Not Started     | Driver exists           |
| **Comm**    | I3C        | `ra_i3c.c`         | `ra_i3c.h`          | 🔨 Build Only | ❌ Not Started     | I2C fallback            |
| **Comm**    | Ethernet   | `ra_ether.c`       | `ra_etherc_edmac.h` | 🔨 Build Only | ❌ Not Started     | RMAC support            |
| **Comm**    | USB        | `ra_usbdev.c`      | `ra_usb_hs.h`       | 🔨 Build Only | ❌ Not Started     | HS device               |
| **Timer**   | AGT        | `ra_agt.c`         | `ra_agt.h`          | 🔨 Build Only | ❌ Not Used        | Low power               |
| **Timer**   | ULPT       | `ra_ulpt.c`        | `ra_ulpt.h`         | 🔨 Build Only | ❌ Not Used        | Ultra LP                |
| **Timer**   | RTC        | `ra_rtc.c`         | `ra_rtc.h`          | 🔨 Build Only | ❌ Not Started     | Calendar                |
| **WDT**     | WDT        | `ra_wdt.c`         | `ra_wdt.h`          | 🔨 Build Only | 🔨 Build Only      | CM85 WDT                |
| **WDT**     | IWDT       | `ra_iwdt.c`        | `ra_iwdt.h`         | 🔨 Build Only | ❌ Not Used        | Independent             |
| **Storage** | SDHI       | `ra_sdhi.c`        | `ra_sdhi.h`         | 🔨 Build Only | ❌ Not Started     | SD card                 |
| **Storage** | OSPI-B     | `ra_ospi_b.c`      | `ra_ospi_b.h`       | 🔨 Build Only | ❌ Not Used        | Flash XIP               |
| **Storage** | MRAM       | `ra_mram.c`        | `ra_mram.h`         | 🔨 Build Only | ❌ Not Used        | Code Storage            |
| **Storage** | SDRAM      | `ra_sdram.c`       | `ra_sdram.h`        | 🔨 Build Only | ❌ Not Started     | External                |
| **DMA**     | DMAC       | `ra_dmac.c`        | `ra_dmac.h`         | 🔨 Build Only | ❌ Not Used        | DMA engine              |
| **DMA**     | DTC        | `ra_dtc.c`         | `ra_dtc.h`          | 🔨 Build Only | ❌ Not Used        | Lightweight             |
| **DMA**     | ELC        | `ra_elc.c`         | `ra_elc.h`          | 🔨 Build Only | ❌ Not Used        | Event link              |
| **Analog**  | ADC        | `ra_adc_b.c`       | `ra_adc_b.h`        | 🔨 Build Only | ❌ Not Started     | HW trigger              |
| **Safety**  | POEG       | `ra_poeg.c`        | `ra_poeg.h`         | 🔨 Build Only | ❌ Not Started     | PWM protect             |
| **Safety**  | CAC        | `ra_cac.c`         | `ra_cac.h`          | 🔨 Build Only | ❌ Not Used        | Clock check             |
| **Power**   | LPM        | `ra_lpm.c`         | -                   | 🔨 Build Only | ❌ Not Started     | Low power               |
| **IPC**     | IPC        | `ra_ipc.c`         | `ra_ipc.h`          | 🔨 Build Only | 🔨 Build Only      | Dual-core               |
| **Crypto**  | CRYPTO     | `ra_mbed_crypto.c` | -                   | Not Started    | ❌ Not Used       | HW Security accel       |
| **Camera**  | MIPI-CSI   | `ra_mipi_csi.c`    | `ra_mipi_csi.h`     | 🔨 Build Only | ❌ Not Started     | Camera IF               |
| **Camera**  | OV5640     | `ra_ov5640.c`      | -                   | 🔨 Build Only | ❌ Not Started     | Sensor                  |

**Legend:**

- ✅ Tested: Driver verified, tested on EVK-RA8P1
- ⚠️ Partial: Basic functionality working, needs enhancement
- 🔨 Build Only: Compiles successfully but not runtime tested
- ❌ Not Started/Not Used: Required for PX4 but not implemented or not planned

---

## 1.7 Current Implementation Status

### 1.7.1 CM85 FMU Core - Working Features

| Feature             | Status        | Details                                    |
|:--------------------|:--------------|:-------------------------------------------|
| **Boot & Init**     | ✅ Working    | NuttX boots, PX4 middleware starts         |
| **Console UART**    | ✅ Working    | SCI0 @ 115200 baud for debug console       |
| **Telemetry UARTs** | ✅ Working    | SCI4/5/8 @ 57600 baud (TEL1/TEL2/RC)       |
| **SPI Bus 1**       | ✅ Working    | ICM20948 IMU + AK09916 mag tested          |
| **I2C Bus**         | 🔨 Build Only | Driver compiled but not tested             |
| **GPIO**            | ✅ Working    | LED control, pin configuration functional  |
| **HRT (GPT0)**      | ✅ Working    | High-resolution timer for timestamps       |
| **PWM Output**      | ✅ Working    | GPT channels producing PWM signals         |
| **ADC**             | 🔨 Build Only | Basic reads work, calibration needed       |
| **LED Status**      | ✅ Working    | RGB LED or single LED control              |
| **Watchdog**        | 🔨 Build Only | Driver exists, not fully integrated        |
| **CPU Load**        | 🔨 Build Only | CPU utilization monitoring                 |
| **Sensor Drivers**  | ✅ Working    | ICM20948 (IMU) + AK09916 (mag) operational |
| **DShot ESC**       | 🔨 Build Only | Only normal PWM available                  |
| **IPC to CM33**     | 🔨 Build Only | Framework exists, not tested               |

#### Test Commands

```bash

# List sensors
nsh> px4-info sensors

# Test PWM output (8 channels)
nsh> pwm test -c 1234 -p 1100

# Monitor IMU data (ICM20948)
nsh> listener sensor_accel
nsh> listener sensor_gyro
nsh> listener sensor_mag
```

### 1.7.2 CM33 IO Core - Build Only Status

| Feature               | Status         | Details                            |
|:----------------------|:---------------|:-----------------------------------|
| **Boot & Init**       | 🔨 Build Only  | Firmware builds, flash succeeds    |
| **NuttX BSP**         | 🔨 Build Only  | NuttX kernel configured for CM33   |
| **IPC Hardware**      | ❌ Build Only  | Shared memory IPC not verified     |
| **RC Input**          | ❌ Not Started | S.Bus/CRSF decoder not implemented |
| **PWM Failsafe**      | ❌ Not Started | Autonomous PWM in failsafe mode    |
| **ADC**               | ❌ Not Started | Battery voltage monitoring         |
| **Safety Button**     | ❌ Not Started | Safety switch handling             |
| **Heartbeat Monitor** | ❌ Not Started | CM85 watchdog                      |

#### Known Issues

1. CM33 firmware builds but runtime behavior unverified
2. IPC protocol between CM85↔CM33 not tested
3. No RC input validation
4. Failsafe PWM logic not implemented
5. Shared memory address not verified in hardware

---

## 1.8 Build Instructions

### Prerequisites

```text
Ubuntu/WSL2
gdb-multiarch
arm-gnu-toolchain

Key Repositories:
- https://github.com/nguyentri/PX4-Autopilot/tree/px4_ra8_rz
- https://github.com/nguyentri/NuttX_Px4/tree/NuttX_Px4_RA8_Refactoring
- https://github.com/PX4/NuttX-apps
```

### Build CM85 FMU Firmware

```bash

# Default configuration (IMU + PWM)
make renesas_evk-ra8p1_default

# Output: build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf
```

### Build CM33 IO Firmware

```bash
make renesas_evk-ra8p1-io-cm33_default

# Output: build/renesas_evk-ra8p1-io-cm33_default/renesas_evk-ra8p1-io-cm33_default.elf
```

### Erase Chip

```bash

# use erase command with Jlink connection

```bash

# Or Erase using renesas-flash-programmer if the Chip could not be erased with jlink because there were security option settings in the flash
rfp-cli -d RA -tool jlink:<JLINK ID> -if swd -erase-chip
```

### Flash Firmware

```bash

# Flash both cores
./f
```

### Debug via J-Link

```bash

# Download Cortex-Debug extension

# Run .vscode/launch.json
```

#### Example Launch Configuration

```json
{
  "configurations": [
    {
      "name": "Debug RA8P1 CM85 (Core0)",
      "cwd": "${workspaceRoot}",
      "executable": "${workspaceRoot}/build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf",
      "armToolchainPath": "/opt/arm-gnu-toolchain-13.2.Rel1/bin",
      "request": "launch",
      "type": "cortex-debug",
      "gdbPath": "/usr/bin/gdb-multiarch",
      "svdFile": "${workspaceRoot}/R7KA8P1AD.svd",
      "servertype": "jlink",
      "serverpath": "/opt/SEGGER/JLink/JLinkGDBServer",
      "serverArgs": [
        "-speed", "15000"
      ],
      "device": "R7KA8P1KF_CPU0",
      "showDevDebugOutput": "parsed",
      "runToEntryPoint": "main",
      "rttConfig": {
        "enabled": true,
        "address": "auto",
        "decoders": [
          {
            "label": "rtt_0",
            "port": 0,
            "type": "console"
          }
        ]
      },
      "liveWatch": {
        "enabled": true,
        "samplesPerSecond": 4
      },
      "overrideLaunchCommands": [
        "monitor reset",
        "monitor halt",
        "load",
        "add-symbol-file ${workspaceRoot}/build/renesas_evk-ra8p1-io-cm33_default/renesas_evk-ra8p1-io-cm33_default.elf",
        "restore ${workspaceRoot}/build/renesas_evk-ra8p1-io-cm33_default/renesas_evk-ra8p1-io-cm33_default.elf binary",
        "monitor reset",
        "monitor halt"
      ]
    },
    {
      "name": "Debug RA8P1 CM33 (Core1) - IO Processor",
      "cwd": "${workspaceRoot}",
      "executable": "${workspaceRoot}/build/renesas_evk-ra8p1-io-cm33_default/renesas_evk-ra8p1-io-cm33_default.elf",
      "armToolchainPath": "/opt/arm-gnu-toolchain-13.2.Rel1/bin",
      "request": "launch",
      "type": "cortex-debug",
      "gdbPath": "/usr/bin/gdb-multiarch",
      "svdFile": "${workspaceRoot}/platforms/nuttx/NuttX/R7KA8P1AD.svd",
      "servertype": "jlink",
      "serverpath": "/opt/SEGGER/JLink/JLinkGDBServer",
      "serverArgs": [
        "-speed", "15000"
      ],
      "device": "R7KA8P1KF_CPU1",
      "showDevDebugOutput": "parsed",
      "runToEntryPoint": "user_start",
      "rttConfig": {
        "enabled": true,
        "address": "auto",
        "decoders": [
          {
            "label": "rtt_1",
            "port": 1,
            "type": "console"
          }
        ]
      },
      "overrideLaunchCommands": [
        "monitor reset",
        "monitor halt",
        "add-symbol-file ${workspaceRoot}/build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf",
        "restore ${workspaceRoot}/build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf binary",
        "load",
        "monitor reset",
        "monitor halt"
      ]
    }
  ]
}
```

### Decode Exception Backtrace

When an exception occurs, use addr2line to decode function addresses:

```bash
arm-none-eabi-addr2line -e build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf -f -i <addresses>
```

#### Example

```bash
arm-none-eabi-addr2line -e build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf -f -i 0x02010c1a 0x020abc42 0x020abc86 0x020ab1ee 0x0200c5ee 0x020050ac 0x0200a4b8 0x020037f8
```

---

## References

- [Renesas RA8P1 Product Page](https://www.renesas.com/en/products/ra8p1)
- [EVK-RA8P1 Development Kit](https://www.renesas.com/en/design-resources/boards-kits/ek-ra8p1)
- [SEGGER J-Link Downloads](https://www.segger.com/downloads/jlink/)
- [Renesas Flash Programmer](https://www.renesas.com/en/document/swe/renesas-flash-programmer-v32100-linuxx64?r=488871),

---
