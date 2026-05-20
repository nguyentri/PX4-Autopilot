 /****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *    used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

/**
 * @file board_config.h
 *
 * Renesas EVK-RA8P1 board configuration
 * Aligned with NuttX board.h definitions
 */

#pragma once

/****************************************************************************************************
 * Included Files
 ****************************************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

#if defined(__PX4_NUTTX)
#include <hardware/ra_pinmap.h>
#include <ra_gpio.h>
#endif

/****************************************************************************************************
 * Board Hardware Overview
 ****************************************************************************************************/

/*
 * EVK-RA8P1 Hardware Features:
 * - Renesas R7KA8P1KFLCAC MCU (RA8P1)
 *   • 1 GHz ARM Cortex-M85 core
 *   • 250 MHz ARM Cortex-M33 core
 *   • 1 MB MRAM, 2 MB SRAM with ECC
 *   • 289 pins, BGA package
 * - Memory:
 *   • 64 MB (512 Mb) external Octo-SPI Flash
 *   • 64 MB (512 Mb) external SDRAM (32-bit bus)
 * - Connectivity:
 *   • Ethernet (RJ45 RGMII interface)
 *   • USB Full Speed (USB-C)
 *   • USB High Speed (USB-C)
 *   • CAN-FD (2 channels)
 * - User Interface:
 *   • Three User LEDs (red, blue, green)
 *   • Two User Switches, One Reset Switch
 *   • Power LED (white), Debug LED (yellow), Ethernet LEDs
 * - Expansion Connectors:
 *   • Arduino (Uno R3)
 *   • mikroBUS (not populated)
 *   • Two Pmod (SPI, UART, I2C)
 *   • Two Grove (I2C/I3C/Analog, not populated)
 *   • Qwiic (not populated)
 * - Special Features:
 *   • Parallel Graphics Expansion Port
 *   • Camera Expansion Port (underside)
 *   • MIPI Graphics Expansion Port (underside)
 *   • PDM MEMS Microphones (underside)
 *   • Audio CODEC with speaker connections
 * - Custom Sensor Board:
 *   • GY-912 with ICM-20948 (9-axis IMU) + BMP388 (barometer)
 *   • Connected via Arduino/Pmod SPI interface
 */

/****************************************************************************************************
 * MCU Configuration
 ****************************************************************************************************/

#define BOARD_HAS_NO_RESET              1  /* No dedicated external reset */
#define BOARD_HAS_NO_BOOTLOADER         1  /* No bootloader support initially */
#define BOARD_TYPE_COMPLETE             88 /* Board type ID */
#if !defined(PX4_SOC_ARCH_ID) && defined(PX4_SOC_ARCH_ID_RA8P1)
#define PX4_SOC_ARCH_ID         PX4_SOC_ARCH_ID_RA8P1
#else
#define PX4_SOC_ARCH_ID         0xFFFF  /* Unknown SOC */
#endif

/****************************************************************************************************
 * Board Hardware Info (used by platforms/nuttx/src/px4/renesas/ra8/board_hw_info/)
 ****************************************************************************************************/

#define BOARD_HW_TYPE_NAME              "EVK-RA8P1"
#define BOARD_HW_VERSION                1  /* Version 1.x */
#define BOARD_HW_REVISION               0  /* Revision 0 */

/* Board UUID - used by board_identity.c for GUID generation
 * Must be exactly 16 characters for PX4_CPU_UUID_BYTE_LENGTH */
// #define BOARD_OVERRIDE_UUID             "RA8P10000000000"  /* 16 characters */
// #define BOARD_OVERRIDE_PX4_GUID         1  /* Enable PX4 GUID override */
// #define BOARD_OVERRIDE_MFGUID           1  /* Enable MFGUID override */

/* MCU Version override - prevents need for board_mcu_version() implementation */
/* #define BOARD_OVERRIDE_CPU_VERSION      0 */  /* Define only if using macro override */

/* CPU UUID Configuration */
#if !defined(PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH        16
#define PX4_CPU_UUID_WORD32_LENGTH      (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH      PX4_CPU_UUID_BYTE_LENGTH
#endif

/****************************************************************************************************
 * UART/Serial Configuration
 ****************************************************************************************************/

/* UART Device Mapping (aligned with NuttX board.h)
 * SCI0 (ttyS0): Console on Pmod2 UART (P602=RXD0, P603=TXD0)
 * SCI4 (ttyS1): TELEM1/GPS on J1 (P715=RXD4_C, P714=TXD4_C)
 * SCI5 (ttyS2): TELEM2 on J1 (PB02=RXD5_C, PB03=TXD5_C)
 * SCI8 (ttyS3): RC input RX-only on P806 (RXD8_A)
 * SCI7 (ttyS4): TELEM3 on Arduino J23 (P808=RXD7_B, P809=TXD7_B)
 * SCI9 (ttyS5): spare UART on P208/P209 (RXD9_B/TXD9_B)
 */
#define PX4_UART_CONSOLE                "ttyS0"  /* SCI0 - Console */
#define PX4_UART_GPS1                   "ttyS1"  /* SCI4 - Primary telemetry/GPS */
#define PX4_UART_TELEM1                 "ttyS1"  /* SCI4 - Primary telemetry */
#define PX4_UART_TELEM2                 "ttyS2"  /* SCI5 - Secondary telemetry */
#define PX4_UART_TELEM3                 "ttyS4"  /* SCI7 - Arduino telemetry */

/* UART GPIO Pin Macros (aliases from board.h for initialization in init.c) */
#ifndef GPIO_SCI7_RX
#define GPIO_SCI7_RX                    GPIO_RXD7_B
#endif

#ifndef GPIO_SCI7_TX
#define GPIO_SCI7_TX                    GPIO_TXD7_B
#endif

/* SCI0 - Console */
#define PX4_UART_CONSOLE_RX             GPIO_SCI0_RX  /* P602 - RXD0_B */
#define PX4_UART_CONSOLE_TX             GPIO_SCI0_TX  /* P603 - TXD0_B */

/* SCI4 - TELEM1 */
#define PX4_UART_TELEM1_RX              GPIO_SCI4_RX  /* P715 - RXD4_C */
#define PX4_UART_TELEM1_TX              GPIO_SCI4_TX  /* P714 - TXD4_C */

/* SCI5 - TELEM2 */
#define PX4_UART_TELEM2_RX              GPIO_SCI5_RX  /* PB02 - RXD5_C */
#define PX4_UART_TELEM2_TX              GPIO_SCI5_TX  /* PB03 - TXD5_C */

/* SCI7 - TELEM3 (Arduino J23) */
#define PX4_UART_TELEM3_RX              GPIO_SCI7_RX  /* P808 - RXD7_B */
#define PX4_UART_TELEM3_TX              GPIO_SCI7_TX  /* P809 - TXD7_B */

/* SCI8 - RC Input (RX only) */
#define PX4_UART_RC_RX                  GPIO_SCI8_RX  /* P806 - RXD8_A */

/* RC Input Configuration */
#define RC_SERIAL_PORT                  "/dev/ttyS3"  /* SCI8 RX-only on P806 */
#define BOARD_HAS_RC_INPUT              1

/* Console Buffer */
#define BOARD_ENABLE_CONSOLE_BUFFER     1

/****************************************************************************************************
 * SPI Configuration - CENTRALIZED CONFIGURATION
 *
 * To switch SPI buses, only change the defines in this section.
 * All other files (init.c, spi.cpp, board_common.c, rc.board_sensors) use these defines.
 *
 * Available buses on RA8P1:
 *   - SPI0: Requires CONFIG_RA_SPI0=y in defconfig (Arduino header alternate)
 *   - SPI1: Requires CONFIG_RA_SPI1=y in defconfig (Arduino header default)
 *
 * To enable a bus, ensure the corresponding CONFIG_RA_SPIx=y is set in:
 *   boards/renesas/evk-ra8p1/nuttx-config/nsh/defconfig
 ****************************************************************************************************/

/* ============== USER CONFIGURABLE SECTION - CHANGE ONLY HERE ============== */

/* Primary sensor SPI bus selection (0 or 1) */
#define PX4_SPI_BUS_SENSORS             1       /* Change to 0 for SPI0, 1 for SPI1 */

/* Number of SPI buses enabled */
#define BOARD_NUMBER_SPI_BUSES          1       /* Set to 2 if using both buses */

/* Maximum devices per bus */
#define BOARD_SPI_BUS_MAX_DEVICES       2       /* ICM-20948 + optional BMP388 */

/* ============== END USER CONFIGURABLE SECTION ============== */

/* Derived configuration - DO NOT MODIFY */
#define BOARD_SPI_BUS_SENSORS           PX4_SPI_BUS_SENSORS
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS
#define BOARD_SPI_BUS_MAX_BUS_ITEMS     BOARD_NUMBER_SPI_BUSES
#define SPI_BUS_MAX_BUS_ITEMS           BOARD_SPI_BUS_MAX_BUS_ITEMS

/* SPI Bus enum for spi.cpp - maps to NuttX SPI bus number */
#if (PX4_SPI_BUS_SENSORS == 0)
#define PX4_SPI_BUS_SENSORS_ENUM        SPI::Bus::SPI0
#elif (PX4_SPI_BUS_SENSORS == 1)
#define PX4_SPI_BUS_SENSORS_ENUM        SPI::Bus::SPI1
#else
#error "Invalid PX4_SPI_BUS_SENSORS value. Must be 0 or 1."
#endif

/* Arduino SPI Pin Configuration (from board.h)
 * Used for GY-912 sensor board connection
 * SCK:  P102 (Arduino D13) - GPIO_ARDUINO_SPI_SCK = GPIO_RSPCKB_A_1
 * MISO: P100 (Arduino D12) - GPIO_ARDUINO_SPI_MISO = GPIO_MISOB_A_1
 * MOSI: P101 (Arduino D11) - GPIO_ARDUINO_SPI_MOSI = GPIO_MOSIB_A_1
 * CS0:  P103 (Arduino D10) - GPIO_ARDUINO_SPI_CS0 = GPIO_SSLB0_A_1 (ICM-20948)
 */
#define PX4_SPI_IMU_SCK                 GPIO_ARDUINO_SPI_SCK   /* P102 */
#define PX4_SPI_IMU_MOSI                GPIO_ARDUINO_SPI_MOSI  /* P101 */
#define PX4_SPI_IMU_MISO                GPIO_ARDUINO_SPI_MISO  /* P100 */
//#define PX4_SPI_IMU_CS0                 GPIO_ARDUINO_SPI_CS0 | GPIO_CFG_OUTPUT_HIGH   /* P103 - HW CS */
#define PX4_SPI_IMU_CS1                 GPIO_ARDUINO_SPI_CS1 | GPIO_CFG_OUTPUT_HIGH     /* P110 - GPIO CS */
/* Sensor Data Ready Interrupt (from board.h) */
#define PX4_SPI_IMU_DRDY                GPIO_ARDUINO_D2_INT    /* P011 - IRQ16 */

/* SPI CS and DRDY Pin Port/Pin for spi.cpp initSPIDevice()
 * These map to the GPIO::Port and GPIO::Pin enums used by PX4 SPI framework
 * CS0:  P103 = Port1, Pin3
 * DRDY: P011 = Port0, Pin11
 */
#if defined PX4_SPI_IMU_CS0
#define PX4_SPI_IMU_CS_PORT             GPIO::Port1
#define PX4_SPI_IMU_CS_PIN              GPIO::Pin3
#elif defined PX4_SPI_IMU_CS1
#define PX4_SPI_IMU_CS_PORT             GPIO::PortB
#define PX4_SPI_IMU_CS_PIN              GPIO::Pin0
#else
#error "CS is not defined!"
#endif
#define PX4_SPI_IMU_DRDY_PORT           GPIO::Port0
#define PX4_SPI_IMU_DRDY_PIN            GPIO::Pin11
#define PX4_SPI_IMU_DRDY_IRQ            (16)  /* IRQ16 for P011 */

/****************************************************************************************************
 * I2C Configuration
 ****************************************************************************************************/

/* I2C Bus Configuration (from board.h)
 * I2C0: P400=SCL0, P401=SDA0 (Grove 1, Qwiic, Arduino, mikroBUS)
 * I2C1: P512=SCL1, P511=SDA1 (Grove 1/2, Camera Port, Qwiic) - NOT USED IN PX4
 *
 * Only I2C0 is enabled for BMP388 barometer sensor.
 */
#define BOARD_NUMBER_I2C_BUSES          1       /* Only I2C0 configured */
#define BOARD_I2C_BUS_CLOCK_INIT        {100000}  /* 100kHz for bus 0 */
#define PX4_NUMBER_I2C_BUSES            1
#define I2C_BUS_MAX_BUS_ITEMS           PX4_NUMBER_I2C_BUSES

/* I2C Pin Definitions */
#define PX4_I2C0_SCL                    GPIO_I2C0_SCL  /* P400 */
#define PX4_I2C0_SDA                    GPIO_I2C0_SDA  /* P401 */

/* I2C Bus Assignment */
#define PX4_I2C_BUS_EXPANSION           0  /* I2C0 for external devices */
#define PX4_I2C_BUS_MTD                 PX4_I2C_BUS_EXPANSION

/****************************************************************************************************
 * PWM/Timer Configuration (GPT)
 ****************************************************************************************************/

/* PWM Configuration */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define DIRECT_INPUT_TIMER_CHANNELS     0
#define BOARD_NUM_IO_TIMERS             4   /* 4 GPT timers for PWM */
#define BOARD_HAS_PWM                   DIRECT_PWM_OUTPUT_CHANNELS
#define BOARD_HAS_SLOW_PWMOUT           1   /* 400Hz PWM for ESCs */
#define PWM_OUTPUT_ACTIVE_LOW           0   /* Active high PWM */

/* DShot Motor Assignment */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/* PWM GPIO Macros - Standard Quadcopter Motor Layout
 *
 * Motor Layout (X Configuration):
 *   Front
 *  3     1
 *    \ /
 *     X
 *    / \
 *  2     4
 *   Rear
 *
 * Motor 1: Front Right - GPT3  (P912)
 * Motor 2: Rear Left   - GPT5  (P915)
 * Motor 3: Front Left  - GPT11 (P903)
 * Motor 4: Rear Right  - GPT13 (P515)
 *
 * GPIO Configuration Attributes for Motor Pins:
 * -----------------------------------------------
 * - Mode:          Peripheral function (PMR=1, PSEL=GPT)
 * - Direction:     Output (PDR=1)
 * - Drive:         High drive strength (DSCR=10b) for 3.3V fast switching
 * - Pull-up:       Disabled (PCR=0) - external ESC pull-down expected
 * - Open-drain:    Disabled (NCODR=0) - push-pull output required
 * - Slew rate:     High speed (default for GPT outputs)
 *
 * Electrical Characteristics (RA8P1 @ 3.3V VCC):
 * - High drive: IOH = 8mA sink/source typical
 * - Rise/fall time: ~5ns at high drive
 * - PWM frequency: 400Hz standard, up to 1.2MHz for DShot1200
 */
#define PX4_GPIO_MOTOR_FRONT_RIGHT      GPIO_TIM3_CH1OUT   /* Motor 1: P912 - GPT3A */
#define PX4_GPIO_MOTOR_REAR_LEFT        GPIO_TIM5_CH1OUT   /* Motor 2: P915 - GPT5A */
#define PX4_GPIO_MOTOR_FRONT_LEFT       GPIO_TIM11_CH1OUT  /* Motor 3: P903 - GPT11A */
#define PX4_GPIO_MOTOR_REAR_RIGHT       GPIO_TIM13_CH1OUT  /* Motor 4: P515 - GPT13A */

/****************************************************************************************************
 * High-Resolution Timer (HRT)
 ****************************************************************************************************/

/* HRT Configuration using GPT0 (dedicated, no pin output required)
 *
 * HRT_TIMER: GPT channel number (0 = GPT0)
 * HRT_TIMER_CHANNEL: Compare register (0 = GTCCRA)
 *
 * Note: The actual timer clock configuration (PCLKD/64 = 3.90625 MHz)
 * is set in hrt.c using the correct GPT register definitions.
 * HRT_TIMER_FREQUENCY is deprecated and no longer used - the clock
 * calculation is now done correctly in hrt.c using BOARD_PCLKD_FREQUENCY.
 */
#define HRT_TIMER                       0   /* Use GPT0 for HRT */
#define HRT_TIMER_CHANNEL               0   /* Channel A (GTCCRA for compare) */

/****************************************************************************************************
 * LED Configuration
 ****************************************************************************************************/

/* LED GPIO Definitions (from board.h)
 * LED1 (Blue):  P600 - GPIO_USER_LED_BLUE  = GPIO_P600_OUTPUT_HIGH
 * LED2 (Green): P303 - GPIO_USER_LED_GREEN = GPIO_P303_OUTPUT_HIGH
 * LED3 (Red):   PA07 - GPIO_USER_LED_RED   = GPIO_PA07_OUTPUT_HIGH
 */
#ifndef GPIO_nLED_BLUE
#  define GPIO_nLED_BLUE                GPIO_USER_LED_BLUE   /* P600 - LED1 Blue */
#endif

#ifndef GPIO_nLED_GREEN
#  define GPIO_nLED_GREEN               GPIO_USER_LED_GREEN  /* P303 - LED2 Green */
#endif

#ifndef GPIO_nLED_RED
#  define GPIO_nLED_RED                 GPIO_USER_LED_RED    /* PA07 - LED3 Red */
#endif

/* Map to standard PX4 LED names */
#define GPIO_nLED_1                     GPIO_nLED_BLUE   /* Status indicator */
#define GPIO_nLED_2                     GPIO_nLED_GREEN  /* Armed state indicator */

#define BOARD_HAS_CONTROL_STATUS_LEDS   1
#define BOARD_OVERLOAD_LED              0  /* Blue LED for overload */
#define BOARD_ARMED_STATE_LED           1  /* Green LED for armed state */
#define BOARD_FAILED_STATE_LED          2  /* Red LED for failure */
#define BOARD_MAX_LEDS                  3

/****************************************************************************************************
 * Button/Switch Configuration
 ****************************************************************************************************/

/* Safety Switch Configuration (from board.h)
 * SW1 (Blue): P009 - GPIO_USER_SW1 = GPIO_IRQ13_P009_DS
 * SW2 (Blue): P008 - GPIO_USER_SW2 = GPIO_P008_INPUT_PULLUP
 */
#ifndef GPIO_BTN_SAFETY
#  define GPIO_BTN_SAFETY               GPIO_USER_SW1  /* P009 - User Button SW1 */
#endif

#define BOARD_HAS_NO_SAFETY_SWITCH      1  /* No dedicated safety switch */

/****************************************************************************************************
 * ADC Configuration
 ****************************************************************************************************/

/* ADC Reference and Resolution */
#define BOARD_ADC_VREF                  3300  /* 3.3V reference */
#define BOARD_ADC_RESOLUTION            4096  /* 12-bit ADC */
#define ADC_RESOLUTION_BITS             12
#define ADC_MAX_VALUE                   ((1 << ADC_RESOLUTION_BITS) - 1)

/* ADC Channel Definitions (from board.h Arduino analog pins)
 * A0: P001 (AN001) - Battery Voltage
 * A1: P007 (AN007) - Battery Current
 * A2: P003 (AN003)
 * A3: P004 (AN004) - mikroBUS AN
 * A4: P014 (AN014/DA0)
 * A5: P015 (AN015/DA1)
 */
#define ADC_BATTERY_VOLTAGE_CHANNEL     1    /* AN001 - P001 (Arduino A0) */
#define ADC_BATTERY_CURRENT_CHANNEL     7    /* AN007 - P007 (Arduino A1) */
#define BOARD_ADC_CHANNELS              2

/* GPIO Definitions for ADC */
#ifndef GPIO_ADC_BATTERY_VOLTAGE
#  define GPIO_ADC_BATTERY_VOLTAGE      GPIO_ARDUINO_A0  /* P001 */
#endif
#ifndef GPIO_ADC_BATTERY_CURRENT
#  define GPIO_ADC_BATTERY_CURRENT      GPIO_ARDUINO_A1  /* P007 */
#endif

/* Power Monitoring (limited initially) */
#define BOARD_ADC_USB_CONNECTED         0
#define BOARD_ADC_BRICK_VALID           0
#define BOARD_ADC_SERVO_VALID           0
#define BOARD_ADC_PERIPH_5V_OC          0
#define BOARD_ADC_HIPOWER_5V_OC         0

/****************************************************************************************************
 * Battery Configuration
 ****************************************************************************************************/

/* Battery Monitoring Constants */
#define BATTERY_VOLTAGE_DIVIDER_RATIO   5.7f   /* Voltage divider ratio */
#define CURRENT_SENSOR_SENSITIVITY      185    /* ACS712-05B: 185mV/A */
#define ADC_VREF_MV                     3300

/* Battery Thresholds (in mV) */
#define BATTERY_VOLTAGE_MAX             4200   /* 4.2V fully charged */
#define BATTERY_VOLTAGE_MIN             3200   /* 3.2V discharged */

/* PX4 Battery Configuration */
#define BOARD_BATTERY1_V_DIV            (10.1f)
#define BOARD_BATTERY1_A_PER_V          (15.391030303f)

/****************************************************************************************************
 * Sensor Configuration
 ****************************************************************************************************/

/* Sensor Availability */
#define BOARD_HAS_SENSOR_IMU            1  /* ICM-20948 (9-axis: gyro+accel+mag) */
#define BOARD_HAS_SENSOR_MAG            1  /* AK09916 (internal to ICM-20948) */
#define BOARD_HAS_SENSOR_BARO           1  /* BMP388 */

/* Default Sensor Orientation */
#define BOARD_ROTATION_DEFAULT          ROTATION_NONE

/****************************************************************************************************
 * CAN Configuration
 ****************************************************************************************************/

/* CAN-FD Configuration (from board.h)
 * CANFD0: P312=TX, P311=RX - GPIO_CTX0_3, GPIO_CRX0_3
 * CANFD1: P909=TX, P908=RX - GPIO_CTX1_5, GPIO_CRX1_4
 * Note: CAN support not enabled initially
 */
#define BOARD_NUMBER_CAN_BUSES          0  /* CAN not supported initially */

/****************************************************************************************************
 * Ethernet Configuration
 ****************************************************************************************************/

/* Ethernet RGMII Interface (from board.h)
 * PHY Management: P415=MDC, P414=MDIO
 * PHY Control: P708=RSTN, P107=INT
 * RGMII TX: P307-P304 (TXD0-3), P310 (TX_CTL), P308 (TX_CLK)
 * RGMII RX: P906-P909 (RXD0-3), P905 (RX_CTL), P904 (RX_CLK)
 * Note: Ethernet support not enabled initially
 */

/****************************************************************************************************
 * USB Configuration
 ****************************************************************************************************/

/* USB High Speed (from board.h)
 * VBUS: P408 - GPIO_USBHS_VBUS_1
 * ID: P411 - GPIO_USBHS_ID_1
 * OVRCURA: P413 - GPIO_USBHS_OVRCURA_1
 * VBUSEN: P407 - GPIO_USBHS_VBUSEN_1
 * Note: USB not supported initially
 */
#define BOARD_HAS_NO_USB                1

/****************************************************************************************************
 * External Memory Configuration
 ****************************************************************************************************/

/* SDRAM Configuration (from board.h - 32-bit bus)
 * IS42S32160F-6BLI: 64MB SDRAM
 * Address: A0-A23, Data: DQ0-DQ31, Control: CKE, CLK, CS, WE, CAS, RAS
 * Data Mask: DQM0-DQM3
 * Note: SDRAM support not enabled initially
 */

/* OSPI/QSPI Flash Configuration (from board.h)
 * 8-bit Octo-SPI interface
 * Control: P104=CS0, P106=RESET, P105=ECS
 * Data: P100-P804 (SIO0-SIO7)
 * Clock: P808=SCLK, P801=DQS
 * Note: QSPI support not enabled initially
 */

/****************************************************************************************************
 * IPC (Inter-Processor Communication) Configuration
 ****************************************************************************************************/

/* Shared Memory IPC between CM85 (FMU) and CM33 (IO Processor)
 *
 * Memory Region: 32KB non-cacheable SRAM @ 0x22008000
 * - actuator_cmd:    0x22008000 (128 B, CM85→CM33)
 * - rc_input:        0x22008080 (128 B, CM33→CM85)
 * - battery_status:  0x22008100 (128 B, CM33→CM85)
 * - heartbeat_cm85:  0x22008180 (32 B,  CM85→CM33)
 * - heartbeat_cm33:  0x220081A0 (32 B,  CM33→CM85)
 * - perf_counters:   0x22009000 (28 KB)
 *
 * Protocol: CRC16-CCITT validation, sequence numbers, memory barriers
 * Latency target: <100µs round-trip (50× better than serial FMU-IO)
 */

/* IPC shared memory symbols from linker script */
extern uint8_t __ipc_ram_start[];
extern uint8_t __ipc_ram_end[];

#define IPC_SRAM_BASE           ((uintptr_t)__ipc_ram_start)
#define IPC_SRAM_SIZE           ((size_t)((uintptr_t)__ipc_ram_end - (uintptr_t)__ipc_ram_start))

/* Message region offsets (must match ipc_protocol.h) */
#define IPC_ACTUATOR_CMD_OFFSET     0x0000
#define IPC_RC_INPUT_OFFSET         0x0080
#define IPC_BATTERY_STATUS_OFFSET   0x0100
#define IPC_HEARTBEAT_CM85_OFFSET   0x0180
#define IPC_HEARTBEAT_CM33_OFFSET   0x01A0
#define IPC_PERF_COUNTERS_OFFSET    0x1000

/* Computed addresses */
#define IPC_ACTUATOR_CMD_ADDR       (IPC_SRAM_BASE + IPC_ACTUATOR_CMD_OFFSET)
#define IPC_RC_INPUT_ADDR           (IPC_SRAM_BASE + IPC_RC_INPUT_OFFSET)
#define IPC_BATTERY_STATUS_ADDR     (IPC_SRAM_BASE + IPC_BATTERY_STATUS_OFFSET)
#define IPC_HEARTBEAT_CM85_ADDR     (IPC_SRAM_BASE + IPC_HEARTBEAT_CM85_OFFSET)
#define IPC_HEARTBEAT_CM33_ADDR     (IPC_SRAM_BASE + IPC_HEARTBEAT_CM33_OFFSET)
#define IPC_PERF_COUNTERS_ADDR      (IPC_SRAM_BASE + IPC_PERF_COUNTERS_OFFSET)

/****************************************************************************************************
 * Camera Interface Configuration
 ****************************************************************************************************/

/* Parallel Camera Interface (from board.h - J35 connector)
 * Data: P400, P902, P405, P406, P700-P703 (D2-D9, D0/D1/D10/D11 NC)
 * Control: PB02=VSYNC, PB03=HSYNC, PB04=PCLK
 * GPIO: P709=RST, P705=PWDN, P501=XCLK, P010=INT
 * I2C: P512=SCL1, P511=SDA1
 * Note: Camera support not enabled initially
 */

/****************************************************************************************************
 * Expansion Connectors
 ****************************************************************************************************/

/* Pmod Connectors (from board.h)
 * Pmod 1 (J8): SPI1/UART2/I2C - P801-P804
 *   SPI: P803=SCK, P802=MISO, P801=MOSI, P804=CS
 *   UART: P802=RX, P801=TX
 *   GPIO: P402=RST, P412/P413=GPIO, P006=IRQ
 *
 * Pmod 2 (J9): SPI0/UART0/I2C - P601-P604
 *   SPI: P601=SCK, P602=MISO, P603=MOSI, P604=CS
 *   UART: P602=RX, P603=TX
 *   GPIO: P410=RST, P409/P704=GPIO, P012=IRQ
 */

/* Grove Connectors (from board.h)
 * Grove 1: I2C0/I2C1 - P400/P401 or P512/P511
 * Grove 2: I2C1/Analog - P512/P511 or P002/P005
 */

/* Qwiic Connector (from board.h)
 * I2C0 or I2C1 - P400/P401 or P512/P511
 */

/****************************************************************************************************
 * Power Configuration
 ****************************************************************************************************/

/* Note: BOARD_HAS_POWER_CONTROL is intentionally NOT defined (not even as 0)
 * to prevent compilation of power button callback registration in Commander.
 * The #if defined() check requires the macro to be undefined, not just 0.
 */
/* #define BOARD_HAS_POWER_CONTROL      1 */  /* Enable when power control is implemented */

/****************************************************************************************************
 * Board-Specific Features
 ****************************************************************************************************/

#define BOARD_HAS_BUS_MANIFEST          1  /* Has bus manifest */
#define BOARD_HAS_STATIC_MANIFEST       1  /* Static manifest */
#define BOARD_HAS_VERSIONING            1  /* Hardware versioning support */
#define BOARD_HAS_ON_RESET              1  /* Has board_on_reset interface */
#define BOARD_HAS_TIMING_DEBUG          0  /* No timing debug pins */

/****************************************************************************************************
 * Logging Configuration
 ****************************************************************************************************/

#define HARDFAULT_ULOG_PATH             "/fs/microsd/fault.log"
#define HARDFAULT_MAX_ULOG_FILE_LEN     64

/****************************************************************************************************
 * Include Common Board Configuration
 ****************************************************************************************************/

#include <px4_platform_common/board_common.h>

/****************************************************************************************************
 * Public Types
 ****************************************************************************************************/

/****************************************************************************************************
 * Public Data
 ****************************************************************************************************/

#ifndef __ASSEMBLY__

__BEGIN_DECLS

/****************************************************************************************************
 * Public Function Prototypes
 ****************************************************************************************************/

/**
 * Name: evk_ra8p1_boardinitialize
 *
 * Description:
 *   Board-specific early initialization
 */
void evk_ra8p1_boardinitialize(void);

/**
 * Name: evk_ra8p1_timer_initialize
 *
 * Description:
 *   Initialize board timers (GPT)
 */
void evk_ra8p1_timer_initialize(void);

/**
 * Name: board_pwm_initialize
 *
 * Description:
 *   Initialize GPT PWM devices (from board.h)
 */
#ifdef CONFIG_PWM
int board_pwm_initialize(void);
#endif

__END_DECLS

#endif /* __ASSEMBLY__ */
