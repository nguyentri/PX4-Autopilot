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
 * - Renesas R7FA8P1AHECBD MCU
 * - ARM Cortex-M85 @ 480MHz
 * - 1024KB SRAM, 2MB Code Flash, 2MB MRAM
 * - 128MB external SDRAM (32-bit bus)
 * - Ethernet (RGMII), USB HS, CAN-FD
 * - Multiple expansion connectors: Arduino, mikroBUS, Pmod, Grove, Qwiic
 * - Custom sensor board GY-912 with ICM-20948 + BMP388 (via Arduino/Pmod SPI)
 */

/****************************************************************************************************
 * MCU Configuration
 ****************************************************************************************************/

#define BOARD_HAS_NO_RESET              1  /* No dedicated external reset */
#define BOARD_HAS_NO_BOOTLOADER         1  /* No bootloader support initially */
#define BOARD_TYPE_COMPLETE             88 /* Board type ID */
#define PX4_SOC_ARCH_ID                 PX4_SOC_ARCH_ID_NUTTX

/* CPU UUID Configuration */
#if !defined(PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH        16
#define PX4_CPU_UUID_WORD32_LENGTH      (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH      PX4_CPU_UUID_BYTE_LENGTH
#endif

/****************************************************************************************************
 * Memory Configuration
 ****************************************************************************************************/

/* Flash Memory */
#define BOARD_FLASH_SIZE                (2 * 1024 * 1024)  /* 2MB Code Flash */
#define BOARD_FLASH_SECTORS             512                /* 4KB sectors */

/* SRAM */
#define BOARD_RAM_SIZE                  (1024 * 1024)      /* 1MB SRAM */

/* MRAM Configuration (from board.h) */
#define BOARD_MRAM_CODE_BASE            0x02000000
#define BOARD_MRAM_CODE_SIZE            0x001F0000  /* 2MB - 64KB */
#define BOARD_MRAM_DATA_BASE            0x021F0000  /* Last 64KB for params */
#define BOARD_MRAM_DATA_SIZE            0x00010000  /* 64KB */
#define BOARD_MRAM_WRITE_SIZE           32          /* 32 bytes per write */
#define BOARD_MRAM_BLOCK_SIZE           8192        /* 8KB simulated blocks */

/* Mass Storage Configuration */
#define BOARD_HAS_NO_SDCARD             1  /* No SD card slot */

/****************************************************************************************************
 * UART/Serial Configuration
 ****************************************************************************************************/

/* UART Device Mapping (aligned with NuttX board.h)
 * SCI2 (ttyS0): Console (Pmod 1 UART: P802=RXD2, P801=TXD2)
 * SCI0 (ttyS1): GPS/Telemetry (Pmod 2 UART: P602=RXD0, P603=TXD0)
 * SCI7 (ttyS2): Arduino/mikroBUS UART (P808=RXD7, P809=TXD7)
 */
#define PX4_UART_CONSOLE                "ttyS0"  /* SCI2 - Console */
#define PX4_UART_GPS1                   "ttyS1"  /* SCI0 - GPS/Primary Telemetry */
#define PX4_UART_TELEM1                 "ttyS1"  /* SCI0 - Primary Telemetry */
#define PX4_UART_TELEM2                 "ttyS2"  /* SCI7 - Secondary Telemetry */

/* RC Input Configuration */
#define RC_SERIAL_PORT                  "/dev/ttyS2"  /* UART for RC input */
#define BOARD_HAS_RC_INPUT              1

/* Console Buffer */
#define BOARD_ENABLE_CONSOLE_BUFFER     1

/****************************************************************************************************
 * SPI Configuration
 ****************************************************************************************************/

/* SPI Bus Configuration */
#define BOARD_NUMBER_SPI_BUSES          1
#define BOARD_SPI_BUS_SENSORS           1  /* Arduino SPI for sensors */
#define PX4_SPI_BUS_SENSORS             1
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS

/* SPI Bus Limits */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS     1
#define BOARD_SPI_BUS_MAX_DEVICES       2  /* ICM-20948 + BMP388 */
#define SPI_BUS_MAX_BUS_ITEMS           BOARD_SPI_BUS_MAX_BUS_ITEMS

/* Arduino SPI Pin Configuration (from board.h)
 * Used for GY-912 sensor board connection
 * SCK:  P102 (Arduino D13) - GPIO_ARDUINO_SPI_SCK = GPIO_RSPCKA_B_1
 * MISO: P100 (Arduino D12) - GPIO_ARDUINO_SPI_MISO = GPIO_MISOB_A_1
 * MOSI: P101 (Arduino D11) - GPIO_ARDUINO_SPI_MOSI = GPIO_MOSIB_A_1
 * CS0:  P103 (Arduino D10) - GPIO_ARDUINO_SPI_CS0 = GPIO_SSLB0_A_1 (ICM-20948)
 * CS1:  P110 (Arduino D9)  - GPIO_ARDUINO_SPI_CS1 = GPIO_P110_OUTPUT_HIGH (BMP388)
 */
#define PX4_SPI_IMU_SCK                 GPIO_ARDUINO_SPI_SCK   /* P102 */
#define PX4_SPI_IMU_MOSI                GPIO_ARDUINO_SPI_MOSI  /* P101 */
#define PX4_SPI_IMU_MISO                GPIO_ARDUINO_SPI_MISO  /* P100 */
#define PX4_SPI_IMU_CS0                 GPIO_ARDUINO_SPI_CS0   /* P103 - ICM-20948 */
#define PX4_SPI_BARO_CS1                GPIO_ARDUINO_SPI_CS1   /* P110 - BMP388 */

/* Sensor Data Ready Interrupt (from board.h) */
#define PX4_SPI_IMU_DRDY                GPIO_ARDUINO_D2_INT    /* P011 - IRQ16 */

/****************************************************************************************************
 * I2C Configuration
 ****************************************************************************************************/

/* I2C Bus Configuration (from board.h)
 * I2C0: P400=SCL0, P401=SDA0 (Grove 1, Qwiic, Arduino, mikroBUS)
 * I2C1: P512=SCL1, P511=SDA1 (Grove 1/2, Camera Port, Qwiic)
 */
#define BOARD_NUMBER_I2C_BUSES          2
#define BOARD_I2C_BUS_CLOCK_INIT        {100000, 100000}  /* 100kHz for both buses */
#define PX4_NUMBER_I2C_BUSES            2
#define I2C_BUS_MAX_BUS_ITEMS           PX4_NUMBER_I2C_BUSES

/* I2C Bus Assignment */
#define PX4_I2C_BUS_EXPANSION           0  /* I2C0 for external devices */
#define PX4_I2C_BUS_MTD                 PX4_I2C_BUS_EXPANSION

/****************************************************************************************************
 * PWM/Timer Configuration (GPT)
 ****************************************************************************************************/

/* Motor PWM Configuration using GPT channels
 * Motor 1: P300 (GPT3A)  - GPIO_GTIOC3A_1  (PORT3, PIN0)
 * Motor 2: P415 (GPT0A)  - GPIO_GTIOC0A_2  (PORT4, PIN15)
 * Motor 3: P113 (GPT2A)  - GPIO_GTIOC2A_2  (PORT1, PIN13)
 * Motor 4: P302 (GPT4A)  - GPIO_GTIOC4A_2  (PORT3, PIN2)
 *
 * Note: Pin assignments verified from RA8P1 pinmap for ESC control
 */
#define GPIO_TIM3_CH1OUT                GPIO_GTIOC3A_1    /* P300 - GPT3A - Motor 1 */
#define GPIO_TIM0_CH1OUT                GPIO_GTIOC0A_2    /* P415 - GPT0A - Motor 2 */
#define GPIO_TIM2_CH1OUT                GPIO_GTIOC2A_2    /* P113 - GPT2A - Motor 3 */
#define GPIO_TIM4_CH1OUT                GPIO_GTIOC4A_2    /* P302 - GPT4A - Motor 4 */

/* PWM Configuration */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define DIRECT_INPUT_TIMER_CHANNELS     0
#define BOARD_NUM_IO_TIMERS             4   /* 4 GPT timers for PWM */
#define BOARD_HAS_PWM                   DIRECT_PWM_OUTPUT_CHANNELS
#define BOARD_HAS_SLOW_PWMOUT           1   /* 400Hz PWM for ESCs */
#define PWM_OUTPUT_ACTIVE_LOW           0   /* Active high PWM */

/* DShot Motor Assignment */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/****************************************************************************************************
 * High-Resolution Timer (HRT)
 ****************************************************************************************************/

/* HRT Configuration using GPT13 (from board.h)
 * GPT13A: P515 - GPIO_GTIOC13A_1
 * GPT13B: P514 - GPIO_GTIOC13B_2
 */
#define HRT_TIMER                       13  /* Use GPT13 for HRT */
#define HRT_TIMER_CHANNEL               0   /* Channel A */
#define HRT_TIMER_FREQUENCY             120000000  /* 120MHz PCLKD for GPT */

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
 * IS42S32800J: 32MB SDRAM
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

#define BOARD_HAS_POWER_CONTROL         0  /* No power control initially */

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