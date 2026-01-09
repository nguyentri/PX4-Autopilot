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
 * Renesas RDK-RZV2H board configuration for PX4
 * Based on PX4 FreeRTOS+FSP reference implementation
 */

#pragma once

/****************************************************************************************************
 * Included Files
 ****************************************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

#if defined(__PX4_NUTTX)
#include <nuttx/config.h>
#include "rzv_gpio.h"
#endif

/****************************************************************************************************
 * Board Hardware Overview
 ****************************************************************************************************/

/*
 * RDK-RZV2H Hardware Features:
 * - Renesas RZV2H MPU (R9A09G057)
 * - ARM Cortex-R8 core (CR8_0) for real-time processing
 * - ARM Cortex-A55 cores for Linux/application processing
 * - 24 MHz crystal oscillator
 *
 * PX4 Sensor Configuration (from hardware table):
 * - MPU9250 IMU on SPI6 (P90=MOSI, P91=MISO, P92=SCK, P93=CS0) with INT on P50
 * - ICM20948 IMU on SPI6 (P94=CS1) with INT on PA0
 * - BMP280 barometer on I2C7 at address 0x76 (P76=SDA, P77=SCL)
 *
 * Serial Ports:
 * - SCI3 (/dev/ttyS3): NSH Console
 * - SCI4 (/dev/ttyS4): TFminiPlux LiDAR (P70=TXD, P71=RXD)
 * - SCI5 (/dev/ttyS5): Sik Telemetry v3 (P72=TXD, P73=RXD)
 * - SCI6 (/dev/ttyS6): fs-a8s RC receiver (P75=RXD)
 * - SCI9 (/dev/ttyS9): GPS M10 module (P82=TXD, P83=RXD)
 *
 * PWM Outputs (ESC control):
 * - 4 channels using GPT timers: GPT6A(PA4), GPT7B(PA7), GPT9A(P96), GPT10B(P53)
 */

/****************************************************************************************************
 * MCU Configuration
 ****************************************************************************************************/

#define BOARD_OVERRIDE_UUID             "RZV2H0000000000" /* 16 characters */

/* System architecture ID */
#if !defined(PX4_SOC_ARCH_ID) && defined(PX4_SOC_ARCH_ID_RZV2H)
#define PX4_SOC_ARCH_ID         PX4_SOC_ARCH_ID_RZV2H
#else
#define PX4_SOC_ARCH_ID         0xFFFF  /* Unknown SOC */
#endif

#define BOARD_HAS_NO_RESET              1  /* No dedicated external reset */
#define BOARD_HAS_NO_BOOTLOADER         1  /* No bootloader support initially */
#define BOARD_TYPE_COMPLETE             89 /* Board type ID for RZV2H */

/* CPU UUID Configuration */
#if !defined(PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH        16
#define PX4_CPU_UUID_WORD32_LENGTH      (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH      PX4_CPU_UUID_BYTE_LENGTH
#endif

/****************************************************************************************************
 * Interface Configuration
 ****************************************************************************************************/

#define CONFIG_I2C                      1
#define CONFIG_SPI                      1
#define CONFIG_UART                     1

/****************************************************************************************************
 * UART/Serial Configuration
 ****************************************************************************************************/

/* UART Device Mapping (aligned with hardware table)
 * SCI3 (ttyS3): NSH Console
 * SCI4 (ttyS4): TFminiPlux LiDAR (P70=TXD4, P71=RXD4)
 * SCI5 (ttyS5): Sik Telemetry v3 (P72=TXD5, P73=RXD5)
 * SCI6 (ttyS6): fs-a8s RC receiver (P75=RXD6)
 * SCI9 (ttyS9): GPS M10 (P82=TXD9, P83=RXD9)
 */
#define PX4_UART_CONSOLE                "ttyS3"  /* SCI3 - Console */
#define PX4_UART_GPS1                   "ttyS9"  /* SCI9 - GPS M10 */
#define PX4_UART_TELEM1                 "ttyS5"  /* SCI5 - Sik Telemetry v3 */
#define PX4_UART_RANGEFINDER            "ttyS4"  /* SCI4 - TFminiPlux */
#define PX4_UART_RC                     "ttyS6"  /* SCI6 - fs-a8s RC Input */

/* RC Input Configuration */
#ifndef RC_SERIAL_PORT
#  define RC_SERIAL_PORT                  "/dev/ttyS6"  /* SCI6 for RC input */
#endif
#define BOARD_HAS_RC_INPUT              1

/* Console Buffer */
#define BOARD_ENABLE_CONSOLE_BUFFER     1

/****************************************************************************************************
 * I2C Configuration
 ****************************************************************************************************/

/* I2C Bus Configuration
 * I2C7 (RIIC7): BMP280 barometer (P76=SDA7, P77=SCL7)
 */
#define PX4_NUMBER_I2C_BUSES            1
#define BOARD_NUMBER_I2C_BUSES          1
#define BOARD_I2C_BUS_CLOCK_INIT        {100000}  /* 100kHz for I2C7 */
#define I2C_BUS_MAX_BUS_ITEMS           PX4_NUMBER_I2C_BUSES

/* I2C Bus Assignment */
#define PX4_I2C_BUS_EXPANSION           7  /* I2C7 for external devices (barometer) */
#define PX4_I2C_BUS_MTD                 PX4_I2C_BUS_EXPANSION
#define PX4_I2C_OBDEV_BMP280            0x76  /* BMP280 I2C address */

/****************************************************************************************************
 * SPI Configuration
 ****************************************************************************************************/

/* SPI Bus Configuration
 * SPI6: MPU9250 and ICM20948 IMU sensors
 * P90 = MOSI6, P91 = MISO6, P92 = SCK6
 * P93 = SS0 (MPU9250 NCS), P94 = SS1 (ICM20948 NCS)
 */
#define PX4_NUMBER_SPI_BUSES            2
#define BOARD_NUMBER_SPI_BUSES          1
#define BOARD_SPI_BUS_SENSORS           6  /* SPI6 for IMU sensors */
#define PX4_SPI_BUS_SENSORS             6
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS

/* SPI Bus Limits */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS     1
#define BOARD_SPI_BUS_MAX_DEVICES       2  /* MPU9250 + ICM20948 */
#define SPI_BUS_MAX_BUS_ITEMS           BOARD_SPI_BUS_MAX_BUS_ITEMS

/* MPU9250 IMU on SPI6 */
#ifndef BOARD_MPU9250_BUS
#  define BOARD_MPU9250_BUS             6       /* SPI bus 6 */
#endif
#ifndef BOARD_MPU9250_CS_GPIO
#  define BOARD_MPU9250_CS_GPIO         GPIO_P9_3_OUTPUT_HIGH  /* P93 = RSPI6_SSL0 */
#endif
#ifndef BOARD_MPU9250_DRDY_GPIO
#  define BOARD_MPU9250_DRDY_GPIO       GPIO_IRQ0_P5_0  /* P50 = IRQ0 input */
#endif

/* ICM20948 IMU on SPI6 */
#ifndef BOARD_ICM20948_BUS
#  define BOARD_ICM20948_BUS            6       /* SPI bus 6 */
#endif
#ifndef BOARD_ICM20948_CS_GPIO
#  define BOARD_ICM20948_CS_GPIO        GPIO_P9_4_OUTPUT_HIGH  /* P94 = RSPI6_SSL1 */
#endif
#ifndef BOARD_ICM20948_DRDY_GPIO
#  define BOARD_ICM20948_DRDY_GPIO      GPIO_IRQ10_PA_2  /* PA0 = IRQ10 input */
#endif

/****************************************************************************************************
 * PWM/Timer Configuration (GPT)
 ****************************************************************************************************/

/**
 * PWM Configuration - 4 ESC channels using GPT timers
 *
 * Timer-to-Channel-to-Pin Mapping (Single Source of Truth):
 * Based on RDK-RZV2H pin mapping table:
 * ┌─────────┬───────────┬─────────┬──────────────────────────┬───────────┐
 * │ PX4 Ch  │ GPT Timer │ Output  │ GPIO Pin                 │ Mode      │
 * ├─────────┼───────────┼─────────┼──────────────────────────┼───────────┤
 * │ PWM0    │ GPT6      │ GTIOC6A │ PA4 (Port10, Pin4)       │ Mode 11   │
 * │ PWM1    │ GPT7      │ GTIOC7B │ PA7 (Port10, Pin7)       │ Mode 11   │
 * │ PWM2    │ GPT9      │ GTIOC9A │ P96 (Port9, Pin6)        │ Mode 9    │
 * │ PWM3    │ GPT10     │ GTIOC10B│ P53 (Port5, Pin3)        │ Mode 11   │
 * └─────────┴───────────┴─────────┴──────────────────────────┴───────────┘
 *
 * GPIO Header Pin Assignment:
 * - GPIO12/PWM0 → PA4 → ESC1 (GPT6A)
 * - GPIO13/PWM1 → PA7 → ESC2 (GPT7B)
 * - GPIO19      → P96 → ESC3 (GPT9A)
 * - GPIO06      → P53 → ESC4 (GPT10B)
 *
 * PWM Settings:
 * - Frequency: 400 Hz (default ESC rate, configurable to 50-500 Hz)
 * - Pulse Width: 1000-2000 µs (standard PWM servo range)
 * - Resolution: ~10-bit at 400Hz with 120MHz PCLK
 *
 * Reference: NuttX arch/arm/src/rzv/hardware/rzv2h/rzv2h_pinmap.h
 */

/* ESC Channel Count */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define DIRECT_INPUT_TIMER_CHANNELS     0
#define BOARD_NUM_IO_TIMERS             4   /* 4 GPT timers for PWM */
#ifndef BOARD_HAS_PWM
#  define BOARD_HAS_PWM                 DIRECT_PWM_OUTPUT_CHANNELS
#endif
#define BOARD_HAS_SLOW_PWMOUT           1   /* 400Hz PWM for ESCs */
#define PWM_OUTPUT_ACTIVE_LOW           0   /* Active high PWM */

/**
 * PWM GPIO Definitions
 *
 * These must match the RZV2H pinmap definitions from NuttX.
 * Reference: platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv2h/rzv2h_pinmap.h
 *
 * Pin Mapping:
 * - PA4 (Port10, Pin4): GPT6A (GTIOC6A) - PWM0/ESC1, Mode 11
 * - PA7 (Port10, Pin7): GPT7B (GTIOC7B) - PWM1/ESC2, Mode 11
 * - P96 (Port9, Pin6):  GPT9A (GTIOC9A) - PWM2/ESC3, Mode 9
 * - P53 (Port5, Pin3):  GPT10B (GTIOC10B) - PWM3/ESC4, Mode 11
 */
#ifndef BOARD_PWM_CH0_GPIO
#  define BOARD_PWM_CH0_GPIO            GPIO_GTIOC6A_PA_4_M11  /* ESC1: GPT6A on PA4 (GPIO12/PWM0) */
#endif
#ifndef BOARD_PWM_CH1_GPIO
#  define BOARD_PWM_CH1_GPIO            GPIO_GTIOC7B_PA_7_M11  /* ESC2: GPT7B on PA7 (GPIO13/PWM1) */
#endif
#ifndef BOARD_PWM_CH2_GPIO
#  define BOARD_PWM_CH2_GPIO            GPIO_GTIOC9A_P9_6_M9   /* ESC3: GPT9A on P96 (GPIO19) */
#endif
#ifndef BOARD_PWM_CH3_GPIO
#  define BOARD_PWM_CH3_GPIO            GPIO_GTIOC10B_P5_3_M11 /* ESC4: GPT10B on P53 (GPIO06) */
#endif

/* DShot Motor Assignment (channel index mapping) */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/****************************************************************************************************
 * High-Resolution Timer (HRT)
 ****************************************************************************************************/

/**
 * HRT Configuration using GPT
 *
 * The High-Resolution Timer provides microsecond-accurate timing for PX4.
 * Uses GPT0 which is separate from the PWM output timers (GPT1-4).
 *
 * Note: HRT_TIMER_FREQUENCY should match CONFIG_RZV_PCLK_FREQUENCY (120MHz)
 * for accurate timing calculations.
 */
#define HRT_TIMER                       0   /* Use GPT0 for HRT */
#define HRT_TIMER_CHANNEL               0   /* Channel A */
#define HRT_TIMER_FREQUENCY             120000000  /* 120MHz PCLKD for RZV2H GPT */

/****************************************************************************************************
 * LED Configuration
 ****************************************************************************************************/

/* LED GPIO Definitions (from NuttX board.h)
 * LED1: P0_0 (GPIO Port 0, Pin 0)
 * LED2: P0_1 (GPIO Port 0, Pin 1)
 * LED3: P0_2 (GPIO Port 0, Pin 2)
 * LED4: P0_3 (GPIO Port 0, Pin 3)
 * LEDs are active low (write 0 to turn on)
 */
#define GPIO_nLED_1                     GPIO_P0_0_OUTPUT_HIGH  /* LED1 - Status */
#define GPIO_nLED_2                     GPIO_P0_1_OUTPUT_HIGH  /* LED2 - Armed */
#define GPIO_nLED_3                     GPIO_P0_2_OUTPUT_HIGH  /* LED3 */
#define GPIO_nLED_4                     GPIO_P0_3_OUTPUT_HIGH  /* LED4 */

#define GPIO_nLED_BLUE                  GPIO_nLED_1
#define GPIO_nLED_GREEN                 GPIO_nLED_2
#define GPIO_nLED_RED                   GPIO_nLED_3

#define BOARD_HAS_CONTROL_STATUS_LEDS   1
#define BOARD_OVERLOAD_LED              0  /* LED1 for overload */
#define BOARD_ARMED_STATE_LED           1  /* LED2 for armed state */
#define BOARD_MAX_LEDS                  4

/****************************************************************************************************
 * Button/Switch Configuration
 ****************************************************************************************************/

#define BOARD_HAS_NO_SAFETY_SWITCH      1  /* No dedicated safety switch */

/****************************************************************************************************
 * ADC Configuration
 ****************************************************************************************************/

/* ADC not available for battery monitoring on this board initially */
#define ADC_BATTERY_VOLTAGE_CHANNEL     -1
#define ADC_BATTERY_CURRENT_CHANNEL     -1
#define BOARD_NUMBER_BRICKS             1
#define BOARD_ADC_BRICK_VALID           0
#define BOARD_NUMBER_USB_BRICKS         0
#define BOARD_USB_VBUS_VALID            0

/* ADC Reference and Resolution (when enabled) */
#define BOARD_ADC_VREF                  3300  /* 3.3V reference */
#define BOARD_ADC_RESOLUTION            4096  /* 12-bit ADC */
#define ADC_RESOLUTION_BITS             12
#define ADC_MAX_VALUE                   ((1 << ADC_RESOLUTION_BITS) - 1)

/****************************************************************************************************
 * Battery Configuration
 ****************************************************************************************************/

/* Battery monitoring disabled initially - set source to -1 */
#define BOARD_BATTERY1_V_DIV            (10.1f)
#define BOARD_BATTERY1_A_PER_V          (15.391030303f)

/****************************************************************************************************
 * Sensor Configuration
 ****************************************************************************************************/

/* Sensor Availability */
#define BOARD_HAS_SENSOR_IMU            2  /* MPU9250 + ICM20948 (dual 9-axis IMU) */
#define BOARD_HAS_SENSOR_MAG            2  /* AK8963 (MPU9250) + AK09916 (ICM20948) */
#define BOARD_HAS_SENSOR_BARO           1  /* BMP280 */
#define BOARD_HAS_SENSOR_RANGEFINDER    1  /* TFminiPlux LiDAR */

/* Default Sensor Orientation */
#define BOARD_ROTATION_DEFAULT          ROTATION_NONE

/****************************************************************************************************
 * CAN Configuration (Not available on this board)
 ****************************************************************************************************/

#define BOARD_HAS_CAN                   0

/****************************************************************************************************
 * Hardfault Log Configuration
 ****************************************************************************************************/

#define HARDFAULT_ULOG_PATH             "/fs/microsd/fault.log"
#define HARDFAULT_MAX_ULOG_FILE_LEN     64

/****************************************************************************************************
 * Board Functions
 ****************************************************************************************************/

/* External function declarations */
__BEGIN_DECLS

int rdk_rzv2h_timer_initialize(void);

__END_DECLS

/****************************************************************************************************
 * Include common board definitions
 ****************************************************************************************************/

#include <px4_platform_common/board_common.h>
