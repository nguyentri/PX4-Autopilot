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
 * Renesas EVK-RA8P1 board configuration
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
 * Definitions
 ****************************************************************************************************/

/* Configuration ************************************************************************************/

/* EVK-RA8P1 GPIOs **********************************************************************************/

/*
 * EVK-RA8P1 has the following:
 * - Renesas RA8P1 MCU (R7FA8P1AHECBD)
 * - ARM Cortex-M85 @ 480MHz
 * - 1024KB SRAM, 2MB Flash, 128MB external SDRAM
 * - Custom sensor board GY-912 with ICM-20948 + BMP388 (via Pmod connector)
 */


/*
 * Board hardware configuration for PX4
 */

/* RA8P1 MCU Configuration */
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

/* I2C Bus Configuration - For future expansion only, sensors use SPI */
#define PX4_I2C_BUS_EXPANSION   3       /* I2C3 for future expansion (not sensors) */
#define PX4_I2C_BUS_MTD         PX4_I2C_BUS_EXPANSION

/* Sensor Bus Configuration - Primary sensor interface */
#define PX4_SPI_BUS_SENSORS     1       /* SPI1 for all sensors (ICM20948 (including AK09916) + BMP388) */
#define PX4_SPI_BUS_MEMORY      PX4_SPI_BUS_SENSORS

/* Arduino SPI - Used for GY-912 sensor board via Arduino connector
 * Pin mapping based on EVK-RA8P1 Arduino Expansion Header:
 * - SCK:   P102 (Arduino D13)
 * - MISO:  P100 (Arduino D12)
 * - MOSI:  P101 (Arduino D11)
 * - CS0:   P103 (Arduino D10) - ICM20948 (including AK09916)
 * - CS1:   P110 (Arduino D9)  -  BMP388 CS)
 * - DRDY:  P011 (Arduino D2)  - ICM20948 Data Ready
 */

#define PX4_SPI_IMU_SCK   GPIO_ARDUINO_SPI_SCK
#define PX4_SPI_IMU_MOSI  GPIO_ARDUINO_SPI_MOSI
#define PX4_SPI_IMU_MISO  GPIO_ARDUINO_SPI_MISO
#define PX4_SPI_IMU_CS0   GPIO_ARDUINO_SPI_CS0
#define PX4_SPI_BARO_CS1  GPIO_ARDUINO_SPI_CS1
#define PX4_SPI_IMU_DRDY  GPIO_ARDUINO_D2_INT

/* End NuttX-only SIMPLIFIED block */

/* SPI Bus Configuration */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS 1
#define BOARD_SPI_BUS_MAX_DEVICES 2

/* PX4 SPI configuration constants */
#define SPI_BUS_MAX_BUS_ITEMS   BOARD_SPI_BUS_MAX_BUS_ITEMS
/* Note: SPI_BUS_MAX_DEVICES is defined in px4_platform_common/spi.h (default=6)
 * We only use 2 devices, but the platform array size of 6 is fine - unused slots are empty */

/* PWM/GPT Timer Pin Definitions for ESC Control
 * Motor mapping for EVK-RA8P1:
 * Using GPT channels that don't conflict with SDRAM, Ethernet, or USB pins
 * - Motor 1: P211 (PORT2 | PIN11) -> GPT0A (GTIOC0A_1)
 * - Motor 2: P109 (PORT1 | PIN9)  -> GPT10A (GTIOC10A_1) - Arduino D9
 * - Motor 3: P711 (PORT7 | PIN11) -> GPT11A (GTIOC11A_1)
 * - Motor 4: P708 (PORT7 | PIN8)  -> GPT12A (GTIOC12A_1)
 */
#define GPIO_TIM0_CH1OUT        GPIO_GTIOC0A_1    /* P211 - GPT0A - Motor 1 */
#define GPIO_TIM10_CH1OUT       GPIO_GTIOC10A_1   /* P109 - GPT10A - Motor 2 */
#define GPIO_TIM11_CH1OUT       GPIO_GTIOC11A_1   /* P711 - GPT11A - Motor 3 */
#define GPIO_TIM12_CH1OUT       GPIO_GTIOC12A_1   /* P708 - GPT12A - Motor 4 */

/* Define Timer channels for PX4 */
#define DIRECT_PWM_OUTPUT_CHANNELS  4
#define DIRECT_INPUT_TIMER_CHANNELS 0
#define BOARD_NUM_IO_TIMERS         4  /* 4 GPT timers for PWM */

/* LED GPIO Definitions - use ra8p1_pinmap.h per-pin macros
 * EVK-RA8P1 has 3 user LEDs:
 * - LED1 (Blue):  P600
 * - LED2 (Green): P303
 * - LED3 (Red):   PA07
 */
#ifndef GPIO_nLED_BLUE
# ifdef GPIO_USER_LED_BLUE
#  define GPIO_nLED_BLUE GPIO_USER_LED_BLUE
# else
#  define GPIO_nLED_BLUE GPIO_P600_OUTPUT_HIGH  /* P600 - LED1 Blue */
# endif
#endif

#ifndef GPIO_nLED_GREEN
# ifdef GPIO_USER_LED_GREEN
#  define GPIO_nLED_GREEN GPIO_USER_LED_GREEN
# else
#  define GPIO_nLED_GREEN GPIO_P303_OUTPUT_HIGH  /* P303 - LED2 Green */
# endif
#endif

#ifndef GPIO_nLED_RED
# ifdef GPIO_USER_LED_RED
#  define GPIO_nLED_RED GPIO_USER_LED_RED
# else
#  define GPIO_nLED_RED GPIO_PA07_OUTPUT_HIGH  /* PA07 - LED3 Red */
# endif
#endif

/* Map to standard PX4 LED names */
#ifdef GPIO_nLED_BLUE
#define GPIO_nLED_1             GPIO_nLED_BLUE         /* Status indicator */
#endif
#ifdef GPIO_nLED_GREEN
#define GPIO_nLED_2             GPIO_nLED_GREEN        /* Armed state indicator */
#endif

#define BOARD_HAS_CONTROL_STATUS_LEDS      1
#define BOARD_OVERLOAD_LED                 0
#define BOARD_ARMED_STATE_LED              1

#ifndef GPIO_BTN_SAFETY
# ifdef GPIO_USER_SW1
#  define GPIO_BTN_SAFETY GPIO_USER_SW1
# else
#  define GPIO_BTN_SAFETY GPIO_P009_INPUT_PULLUP  /* P009 - User Button */
# endif
#endif
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
#define RC_SERIAL_PORT          "/dev/ttyS2"    /* UART for RC input */
#define BOARD_HAS_RC_INPUT      1

/* Telemetry Configuration */
#define BOARD_TELEM1_DEV        "/dev/ttyS1"    /* Primary telemetry */
#define BOARD_TELEM2_DEV        "/dev/ttyS2"    /* Secondary telemetry */

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
#define CURRENT_SENSOR_SENSITIVITY     185   /* ACS712-05B: 185mV/A */
#define ADC_VREF_MV                    3300  /* 3.3V reference voltage */
#define ADC_RESOLUTION_BITS            12    /* 12-bit ADC */
#define ADC_MAX_VALUE                  ((1 << ADC_RESOLUTION_BITS) - 1)

/* Battery voltage thresholds (in mV) */

#define BATTERY_VOLTAGE_MAX          4200  /* 4.2V fully charged */
#define BATTERY_VOLTAGE_MIN          3200  /* 3.2V discharged */

/* GPIO pin definitions for ADC channels */

#ifndef GPIO_ADC_BATTERY_VOLTAGE
#  define GPIO_ADC_BATTERY_VOLTAGE GPIO_P004_AN000  /* P004 as AN000 */
#endif
#ifndef GPIO_ADC_BATTERY_CURRENT
#  define GPIO_ADC_BATTERY_CURRENT GPIO_P003_AN104  /* P003 as AN104 */
#endif

/* Hardfault logging path */
#define HARDFAULT_ULOG_PATH      "/fs/microsd/fault.log"
#define HARDFAULT_MAX_ULOG_FILE_LEN 64  /* Maximum ulog file path length */

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
/* #define BOARD_DMA_ALLOC_POOL_SIZE       5120 */  /* Disabled - CONFIG_GRAN not enabled */

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

__BEGIN_DECLS

/****************************************************************************************************
 * Public Functions
 ****************************************************************************************************/

/****************************************************************************************************
 * Name: evk_ra8p1_boardinitialize
 *
 * Description:
 *   All RA8P1 architectures must provide the following entry point.  This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ****************************************************************************************************/

/* Timer initialization function */
extern void evk_ra8p1_timer_initialize(void);


__END_DECLS

#endif /* __ASSEMBLY__ */
