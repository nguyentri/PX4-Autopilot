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
 * PX4 Sensor Configuration (from FSP reference):
 * - MPU9250 IMU on SPI bus 0 with DRDY on P5_0
 * - BMP388/BMP280 barometer on I2C bus 7 at address 0x76
 *
 * Serial Ports:
 * - SCI0 (/dev/ttyS0): RC input
 * - SCI1 (/dev/ttyS1): MAVLink telemetry
 * - SCI2 (/dev/ttyS2): GPS
 * - SCI3 (/dev/ttyS3): NSH Console
 *
 * PWM Outputs:
 * - 4 channels using GPT timers on Port 7 (P7_1, P7_2, P7_5, P7_6)
 */

/****************************************************************************************************
 * MCU Configuration
 ****************************************************************************************************/

#define BOARD_OVERRIDE_UUID             "RZV2H0000000000" /* 16 characters */
#ifndef PX4_SOC_ARCH_ID
#  define PX4_SOC_ARCH_ID               PX4_SOC_ARCH_ID_NUTTX
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

/* UART Device Mapping (aligned with NuttX board.h)
 * SCI0 (ttyS0): RC input
 * SCI1 (ttyS1): MAVLink telemetry
 * SCI2 (ttyS2): GPS
 * SCI3 (ttyS3): NSH Console
 */
#define PX4_UART_CONSOLE                "ttyS3"  /* SCI3 - Console */
#define PX4_UART_GPS1                   "ttyS2"  /* SCI2 - GPS */
#define PX4_UART_TELEM1                 "ttyS1"  /* SCI1 - Primary Telemetry */
#define PX4_UART_RC                     "ttyS0"  /* SCI0 - RC Input */

/* RC Input Configuration */
#ifndef RC_SERIAL_PORT
#  define RC_SERIAL_PORT                  "/dev/ttyS0"  /* UART for RC input */
#endif
#define BOARD_HAS_RC_INPUT              1

/* Console Buffer */
#define BOARD_ENABLE_CONSOLE_BUFFER     1

/****************************************************************************************************
 * I2C Configuration
 ****************************************************************************************************/

/* I2C Bus Configuration
 * I2C7 (RIIC7): Barometer sensor (BMP388/BMP280)
 */
#define PX4_NUMBER_I2C_BUSES            1
#define BOARD_NUMBER_I2C_BUSES          1
#define BOARD_I2C_BUS_CLOCK_INIT        {100000}  /* 100kHz for I2C7 */
#define I2C_BUS_MAX_BUS_ITEMS           PX4_NUMBER_I2C_BUSES

/* I2C Bus Assignment */
#define PX4_I2C_BUS_EXPANSION           7  /* I2C7 for external devices (barometer) */
#define PX4_I2C_BUS_MTD                 PX4_I2C_BUS_EXPANSION
#define PX4_I2C_OBDEV_BMP280            0x76  /* BMP388/BMP280 I2C address */

/****************************************************************************************************
 * SPI Configuration
 ****************************************************************************************************/

/* SPI Bus Configuration
 * SPI0: MPU9250 IMU sensor
 */
#define PX4_NUMBER_SPI_BUSES            2
#define BOARD_NUMBER_SPI_BUSES          1
#define BOARD_SPI_BUS_SENSORS           0  /* SPI0 for IMU sensor */
#define PX4_SPI_BUS_SENSORS             0
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS

/* SPI Bus Limits */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS     1
#define BOARD_SPI_BUS_MAX_DEVICES       2  /* MPU9250 + potential expansion */
#define SPI_BUS_MAX_BUS_ITEMS           BOARD_SPI_BUS_MAX_BUS_ITEMS

/* MPU9250 IMU on SPI0 */
#define BOARD_MPU9250_BUS               0       /* SPI bus 0 */
#define BOARD_MPU9250_DRDY_GPIO         GPIO_P5_0_INPUT  /* P50 = PORT5 pin 0, input with IRQ */

/****************************************************************************************************
 * PWM/Timer Configuration (GPT)
 ****************************************************************************************************/

/* PWM Configuration - 4 channels using GPT timers
 * From NuttX board.h:
 * - Timer1 GTIOCA on P71 (PWM Channel 0)
 * - Timer2 GTIOCB on P72 (PWM Channel 1)
 * - Timer3 GTIOCA on P75 (PWM Channel 2)
 * - Timer4 GTIOCB on P76 (PWM Channel 3)
 */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define DIRECT_INPUT_TIMER_CHANNELS     0
#define BOARD_NUM_IO_TIMERS             4   /* 4 GPT timers for PWM */
#ifndef BOARD_HAS_PWM
#  define BOARD_HAS_PWM                 DIRECT_PWM_OUTPUT_CHANNELS
#endif
#define BOARD_HAS_SLOW_PWMOUT           1   /* 400Hz PWM for ESCs */
#define PWM_OUTPUT_ACTIVE_LOW           0   /* Active high PWM */

/* PWM GPIO Definitions (from NuttX board.h) */
#define BOARD_PWM_CH0_GPIO              GPIO_GTIOC1A_P7_1_M1  /* Timer1 GTIOCA on P71 */
#define BOARD_PWM_CH1_GPIO              GPIO_GTIOC2B_P7_2_M1  /* Timer2 GTIOCB on P72 */
#define BOARD_PWM_CH2_GPIO              GPIO_GTIOC3A_P7_5_M1  /* Timer3 GTIOCA on P75 */
#define BOARD_PWM_CH3_GPIO              GPIO_GTIOC4B_P7_6_M1  /* Timer4 GTIOCB on P76 */

/* DShot Motor Assignment */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/****************************************************************************************************
 * High-Resolution Timer (HRT)
 ****************************************************************************************************/

/* HRT Configuration using GPT */
#define HRT_TIMER                       0   /* Use GPT0 for HRT */
#define HRT_TIMER_CHANNEL               0   /* Channel A */
#define HRT_TIMER_FREQUENCY             200000000  /* 200MHz PCLK for RZV2H GPT */

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
#define BOARD_HAS_SENSOR_IMU            1  /* MPU9250 (9-axis: gyro+accel+mag) */
#define BOARD_HAS_SENSOR_MAG            1  /* AK8963 (internal to MPU9250) */
#define BOARD_HAS_SENSOR_BARO           1  /* BMP388/BMP280 */

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
