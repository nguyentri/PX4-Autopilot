/****************************************************************************
 *
 *   Copyright (c) 2024 PX4 Development Team. All rights reserved.
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
 * Renesas FPB-RA8E1 board configuration
 */

#pragma once

/****************************************************************************************************
 * Included Files
 ****************************************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

/* Undefine PX4 GPIO constants that conflict with NuttX RA8 definitions */
#ifdef GPIO_OUTPUT
#undef GPIO_OUTPUT
#endif
#ifdef GPIO_INPUT
#undef GPIO_INPUT
#endif
#ifdef GPIO_OUTPUT_HIGH
#undef GPIO_OUTPUT_HIGH
#endif
#ifdef GPIO_OUTPUT_LOW
#undef GPIO_OUTPUT_LOW
#endif

#include <ra_pinmap.h>
#include <ra_gpio.h>

/* RA8 GPIO definitions - need to avoid GPIO_OUTPUT conflict with PX4 */
/* Define only what we need from ra8e1_pinmap.h */
#ifndef gpio_pinset_t
typedef uint32_t gpio_pinset_t;
#endif

/* Port Number definitions from RA8E1 */
#ifndef PORT4
#define PORT0                                   (0 << 24)
#define PORT1                                   (1 << 24)
#define PORT2                                   (2 << 24)
#define PORT3                                   (3 << 24)
#define PORT4                                   (4 << 24)
#define PORT5                                   (5 << 24)
#define PORT6                                   (6 << 24)
#define PORT7                                   (7 << 24)
#define PORT8                                   (8 << 24)
#define PORT9                                   (9 << 24)
#endif

/* Pin Number definitions from RA8E1 */
#ifndef PIN0
#define PIN0                                   (0 << 16)
#define PIN1                                   (1 << 16)
#define PIN2                                   (2 << 16)
#define PIN3                                   (3 << 16)
#define PIN4                                   (4 << 16)
#define PIN5                                   (5 << 16)
#define PIN6                                   (6 << 16)
#define PIN7                                   (7 << 16)
#define PIN8                                   (8 << 16)
#define PIN9                                   (9 << 16)
#define PIN10                                  (10 << 16)
#define PIN11                                  (11 << 16)
#define PIN12                                  (12 << 16)
#define PIN13                                  (13 << 16)
#define PIN14                                  (14 << 16)
#define PIN15                                  (15 << 16)
#endif

/* Use NuttX ra8e1_pinmap.h GPIO definitions directly */
/* GPIO_OUTPUT, GPIO_INPUT, GPIO_LOW_DRIVE, etc. are defined in ra8e1_pinmap.h */
/* Peripheral functions like GPIO_RSPCKB_B_1, GPIO_MISOB_B_1, etc. are predefined */

/****************************************************************************************************
 * Definitions
 ****************************************************************************************************/

/* Configuration ************************************************************************************/

/* FPB-RA8E1 GPIOs **********************************************************************************/

/*
 * FPB-RA8E1 has the following:
 * - Renesas RA8E1 MCU (R7FA8E1AFDCFB)
 * - ARM Cortex-M85 @ 360MHz
 * - 512KB SRAM, 1MB Flash
 * - Custom sensor board GY-912 with ICM-20948 + BMP388
 */


/*
 * Board hardware configuration for PX4
 */

/* RA8E1 MCU Configuration */
#define BOARD_HAS_SLOW_PWMOUT   1  /* PWM outputs run at 400Hz for ESCs */
#define BOARD_HAS_PWM           DIRECT_PWM_OUTPUT_CHANNELS
#define BOARD_HAS_NO_RESET      1  /* No dedicated reset button */
#define BOARD_HAS_NO_BOOTLOADER 1  /* No bootloader support initially */

/* PWM Configuration */
#define DIRECT_PWM_OUTPUT_CHANNELS  4   /* 4 PWM channels for motor control */
#define DIRECT_INPUT_TIMER_CHANNELS 0   /* No input capture channels yet */

/* PWM Channel Configuration - Using GPT channels */
#define PWM_OUTPUT_ACTIVE_LOW   0       /* Active high PWM signals */

/* Serial Configuration */
#define BOARD_NUMBER_I2C_BUSES  1
#define BOARD_I2C_BUS_CLOCK_INIT {100000}  /* 100kHz I2C clock */

/* SPI Configuration */
#define BOARD_NUMBER_SPI_BUSES  1
#define BOARD_SPI_BUS_SENSORS   1       /* SPI bus for sensors */

/* I2C Bus Configuration */
#define PX4_I2C_BUS_EXPANSION   3       /* I2C3 for expansion/sensors */
#define PX4_I2C_BUS_MTD         PX4_I2C_BUS_EXPANSION

/* Sensor Bus Configuration */
#define PX4_SPI_BUS_SENSORS     1       /* SPI1 for sensors */
#define PX4_SPI_BUS_MEMORY      PX4_SPI_BUS_SENSORS


/* Chip Select Configuration - using NuttX ra8e1_pinmap.h gpio_pinset_t format */
#define GPIO_SPI1_CS0_ICM20948  ((gpio_pinset_t)(PORT4 | PIN8 | GPIO_OUTPUT | GPIO_LOW_DRIVE | GPIO_OUTPUT_HIGH))  /* P408 - ICM20948 CS */
#define GPIO_SPI1_CS1_BMP388    ((gpio_pinset_t)(PORT4 | PIN7 | GPIO_OUTPUT | GPIO_LOW_DRIVE | GPIO_OUTPUT_HIGH))  /* P407 - BMP388 CS */

/* IMU Data Ready Pin - P409 */
#define GPIO_SPI1_IMU_DRDY      ((gpio_pinset_t)(PORT4 | PIN9 | GPIO_INPUT))  /* P409 - ICM20948 Data Ready */

/* SPI Bus Pin Definitions - using NuttX ra8e1_pinmap.h predefined constants */
#define GPIO_SPI1_IMU_SCK       GPIO_RSPCKB_B_1     /* P412 - SPI1 Clock */
#define GPIO_SPI1_IMU_MISO      GPIO_MISOB_B_1      /* P410 - SPI1 MISO */
#define GPIO_SPI1_IMU_MOSI      GPIO_MOSIB_B_1      /* P411 - SPI1 MOSI */

/* SPI Bus Configuration */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS 1
#define BOARD_SPI_BUS_MAX_DEVICES 2

/* PWM/GPT Timer Pin Definitions for ESC Control - use ra8e1_pinmap.h per-pin macros */
#define GPIO_TIM3_CH1OUT        GPIO_P300_OUTPUT_LOW   /* P300 - GPT3A - Motor 1 */
#define GPIO_TIM0_CH1OUT        GPIO_P415_OUTPUT_LOW   /* P415 - GPT0A - Motor 2 */
#define GPIO_TIM2_CH1OUT        GPIO_P113_OUTPUT_LOW   /* P113 - GPT2A - Motor 3 */
#define GPIO_TIM4_CH1OUT        GPIO_P302_OUTPUT_LOW   /* P302 - GPT4A - Motor 4 */

/* Define Timer channels for PX4 */
#define DIRECT_PWM_OUTPUT_CHANNELS  4
#define DIRECT_INPUT_TIMER_CHANNELS 0
#define BOARD_NUM_IO_TIMERS         4  /* 4 GPT timers for PWM */

/* LED GPIO Definitions - use ra8e1_pinmap.h per-pin macros */
#define GPIO_nLED_RED           GPIO_P404_OUTPUT_HIGH  /* P404 - LED1 Status indicator */
#define GPIO_nLED_GREEN         GPIO_P405_OUTPUT_HIGH  /* P405 - LED2 Armed state indicator */

#define BOARD_HAS_CONTROL_STATUS_LEDS      1
#define BOARD_OVERLOAD_LED     		   0
#define BOARD_ARMED_STATE_LED  		   1

#define GPIO_BTN_SAFETY         GPIO_P009_INPUT_PULLUP  /* P009 - User Button */
#define BOARD_HAS_NO_SAFETY_SWITCH 1   /* No dedicated safety switch */

/* Use NuttX GPIO definitions from board.h instead of custom ones */
/* All GPIO pins, ports, and utility macros are defined in NuttX arch headers */

/* Power Configuration */
#define BOARD_HAS_POWER_CONTROL 0       /* No power control */
#define BOARD_HAS_NO_USB        1       /* No USB support initially */

/* ADC Configuration */
#define BOARD_ADC_USB_CONNECTED 0       /* No USB detection */
#define BOARD_ADC_BRICK_VALID   0       /* No power brick */
#define BOARD_ADC_SERVO_VALID   0       /* No servo rail monitoring */
#define BOARD_ADC_PERIPH_5V_OC  0       /* No 5V overcurrent detection */
#define BOARD_ADC_HIPOWER_5V_OC 0       /* No high power 5V overcurrent */

/* Battery Configuration */
#define BOARD_BATTERY1_V_DIV    (10.1f)     /* Voltage divider ratio */
#define BOARD_BATTERY1_A_PER_V  (15.391030303f) /* Current sense ratio */

/* RC Input Configuration */
#define RC_SERIAL_PORT          "/dev/ttyS3"    /* UART for RC input */
#define BOARD_HAS_RC_INPUT      1

/* Telemetry Configuration */
#define BOARD_TELEM1_DEV        "/dev/ttyS0"    /* Primary telemetry */
#define BOARD_TELEM2_DEV        "/dev/ttyS3"    /* Secondary telemetry */

/* Timer Configuration */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT {0, 1, 2, 3} /* Motor assignment for DShot */

/* Bootloader Configuration */
#define BOARD_TYPE_COMPLETE     88          /* Board type ID */
#define PX4_SOC_ARCH_ID         PX4_SOC_ARCH_ID_NUTTX

/* Flash Configuration */
#define BOARD_FLASH_SIZE        (1024 * 1024)   /* 1MB flash */
#define BOARD_FLASH_SECTORS     256             /* 4KB sectors */

/* Memory Configuration */
#define BOARD_RAM_SIZE          (512 * 1024)    /* 512KB SRAM */

/* System Configuration */
#define BOARD_MAX_LEDS          2               /* Maximum number of LEDs */
#define BOARD_HAS_BUS_MANIFEST  1               /* Has bus manifest */
#define BOARD_HAS_VERSIONING    1               /* Board supports hardware versioning */

/* CAN Configuration - Not supported initially */
#define BOARD_NUMBER_CAN_BUSES  0

/* I2C Configuration */
#define PX4_NUMBER_I2C_BUSES    1
#define I2C_BUS_MAX_BUS_ITEMS   PX4_NUMBER_I2C_BUSES

/* UART Mapping - Corrected to match NuttX assignment */
#define PX4_UART_CONSOLE        "ttyS0"         /* Console on SCI2 -> ttyS0 */
#define PX4_UART_GPS1           "ttyS1"         /* GPS on SCI0 -> ttyS1 */
#define PX4_UART_TELEM1         "ttyS1"         /* Telemetry on SCI0 -> ttyS1 */
#define PX4_UART_TELEM2         "ttyS2"         /* Secondary on SCI3 -> ttyS2 */

/* IMU/Sensor Configuration */
#define BOARD_HAS_SENSOR_IMU    1
#define BOARD_HAS_SENSOR_MAG    1
#define BOARD_HAS_SENSOR_BARO   1

/* Board ADC Configuration **************************************************/

#define BOARD_ADC_VREF              3300
#define BOARD_ADC_RESOLUTION        4096

/* ADC Channel Definitions for FPB-RA8E1 */

#define ADC_BATTERY_VOLTAGE_CHANNEL   0   /* AN000 - P004 (Arduino A0) */
#define ADC_BATTERY_CURRENT_CHANNEL   104 /* AN104 - P003 (Arduino A1) */

/* Number of ADC channels used for battery monitoring */

#define BOARD_ADC_CHANNELS           2

/* Battery monitoring constants */

#define BATTERY_VOLTAGE_DIVIDER_RATIO  5.7f  /* 5.7:1 voltage divider */
#define CURRENT_SENSOR_SENSITIVITY    185   /* ACS712-05B: 185mV/A */
#define ADC_VREF_MV                   3300  /* 3.3V reference voltage */
#define ADC_RESOLUTION_BITS          12    /* 12-bit ADC */
#define ADC_MAX_VALUE                ((1 << ADC_RESOLUTION_BITS) - 1)

/* Battery voltage thresholds (in mV) */

#define BATTERY_VOLTAGE_MAX          4200  /* 4.2V fully charged */
#define BATTERY_VOLTAGE_MIN          3200  /* 3.2V discharged */

/* GPIO pin definitions for ADC channels */

#define GPIO_ADC_BATTERY_VOLTAGE     GPIO_P004_AN000  /* P004 as AN000 */
#define GPIO_ADC_BATTERY_CURRENT     GPIO_P003_AN104  /* P003 as AN104 */

/* Hardfault logging path */
#define HARDFAULT_ULOG_PATH      "/fs/microsd/fault.log"

/* Default Sensor Orientation */
#define BOARD_ROTATION_DEFAULT  ROTATION_NONE

#if !defined (PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH 16
#define PX4_CPU_UUID_WORD32_LENGTH (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH PX4_CPU_UUID_BYTE_LENGTH
#endif

#define BOARD_ENABLE_CONSOLE_BUFFER


/* High-resolution timer - RA8 specific configuration */
#define HRT_TIMER               1  /* Use GPT1 for HRT */
#define HRT_TIMER_CHANNEL       0  /* Use channel 0 */
#define HRT_TIMER_FREQUENCY     120000000  /* 120MHz PCLKD for GPT timers */

/* Power Control */
#define BOARD_HAS_PWM                   DIRECT_PWM_OUTPUT_CHANNELS
#define BOARD_HAS_NO_RESET              1
#define BOARD_HAS_NO_BOOTLOADER         1

/* PWM Configuration */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define DIRECT_INPUT_TIMER_CHANNELS     0

/* Board provides GPIO or other Hardware for signaling to timing analyze pins */
#define BOARD_HAS_TIMING_DEBUG          0

/* Mass Storage Configuration */
#define BOARD_HAS_NO_SDCARD             1

/* Battery Configuration */
#define BOARD_BATTERY1_V_DIV            (10.1f)
#define BOARD_BATTERY1_A_PER_V          (15.391030303f)

/* This board provides a DMA pool and APIs */
#define BOARD_DMA_ALLOC_POOL_SIZE       5120

/* This board provides the board_on_reset interface */
#define BOARD_HAS_ON_RESET              1

/* Console buffer already defined above */

#define BOARD_HAS_STATIC_MANIFEST       1

/* Hardware Configuration */
#define BOARD_NUMBER_I2C_BUSES          1
#define BOARD_I2C_BUS_CLOCK_INIT        {100000}

#define BOARD_NUMBER_SPI_BUSES          1
#define BOARD_SPI_BUS_SENSORS           1

/* Sensor Configuration */
#define PX4_SPI_BUS_SENSORS             1
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS

/* Bus Configuration */
#define PX4_I2C_BUS_EXPANSION           3
#define PX4_I2C_BUS_MTD                 PX4_I2C_BUS_EXPANSION

/* RC Input Configuration - already defined above */
#define BOARD_HAS_RC_INPUT              1

/* ADC Configuration - Limited/None initially */
#define BOARD_ADC_USB_CONNECTED         0
#define BOARD_ADC_BRICK_VALID           0
#define BOARD_ADC_SERVO_VALID           0

/* CAN Configuration - Not supported */
#define BOARD_NUMBER_CAN_BUSES          0

/* Flash Configuration */
#define BOARD_FLASH_SIZE                (1024 * 1024)
#define BOARD_FLASH_SECTORS             256

/* Memory Configuration */
#define BOARD_RAM_SIZE                  (512 * 1024)

/* Timer Configuration */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/* Console Configuration */
#define PX4_UART_CONSOLE                "ttyS0"  /* SCI2 */

/* Serial Port Mapping */
#define PX4_UART_GPS1                   "ttyS1"  /* SCI0 */
#define PX4_UART_TELEM1                 "ttyS1"  /* SCI0 */
#define PX4_UART_TELEM2                 "ttyS2"  /* SCI3 */

/* Board Type */
#define BOARD_TYPE_COMPLETE             88

#include <px4_platform_common/board_common.h>

/****************************************************************************************************
 * Public Types
 ****************************************************************************************************/

/****************************************************************************************************
 * Public data
 ****************************************************************************************************/

#ifndef __ASSEMBLY__

/****************************************************************************************************
 * Public Functions
 ****************************************************************************************************/

/****************************************************************************************************
 * Name: fpb_ra8e1_boardinitialize
 *
 * Description:
 *   All RA8E1 architectures must provide the following entry point.  This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ****************************************************************************************************/

extern void fpb_ra8e1_boardinitialize(void);

#include <px4_platform_common/board_common.h>

#endif /* __ASSEMBLY__ */
