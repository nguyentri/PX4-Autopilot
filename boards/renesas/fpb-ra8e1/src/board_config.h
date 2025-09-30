/****************************************************************************
 *
 *   Copyright (C) 2024 PX4 Development Team. All rights reserved.
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
 * FPB-RA8E1 board configuration
 */

#pragma once

#include <nuttx/config.h>
#include <stdint.h>
#include <stdbool.h>

/*
 * Board hardware configuration
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

/* Use GPIO definitions from NuttX board.h to avoid conflicts */
/* Chip Select Configuration - use NuttX definitions */
#define GPIO_SPI1_CS0_ICM20948  GPIO_SPI1_CS0  /* Already defined in board.h */
#define GPIO_SPI1_CS1_BMP388    GPIO_SPI1_CS1  /* Already defined in board.h */

/* SPI Bus Configuration */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS 1
#define BOARD_SPI_BUS_MAX_DEVICES 2

/* LED Configuration - map to NuttX LED definitions */
#define GPIO_nLED_RED           GPIO_LED1      /* P404 - LED1 from board.h */
#define GPIO_nLED_GREEN         GPIO_LED2      /* P405 - LED2 from board.h */

/* PWM GPIO pins are already defined in nuttx-config/include/board.h */
/* GPIO_GPT0_A, GPIO_GPT2_A, GPIO_GPT3_A, GPIO_GPT4_A */

/* IMU Data Ready - use NuttX definition */
/* GPIO_IMU_DRDY is already defined in board.h */

#define BOARD_HAS_CONTROL_STATUS_LEDS      1
#define BOARD_OVERLOAD_LED     LED_RED
#define BOARD_ARMED_STATE_LED  LED_GREEN

/* Safety Switch Configuration - use NuttX GPIO definition */
#define GPIO_BTN_SAFETY         GPIO_SW1       /* P009 - User Button from board.h */
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

/* UART Mapping - Corrected to match NuttX assignment */
#define PX4_UART_CONSOLE        "ttyS0"         /* Console on SCI2 -> ttyS0 */
#define PX4_UART_GPS1           "ttyS1"         /* GPS on SCI0 -> ttyS1 */
#define PX4_UART_TELEM1         "ttyS1"         /* Telemetry on SCI0 -> ttyS1 */
#define PX4_UART_TELEM2         "ttyS2"         /* Secondary on SCI3 -> ttyS2 */

/* IMU/Sensor Configuration */
#define BOARD_HAS_SENSOR_IMU    1
#define BOARD_HAS_SENSOR_MAG    1
#define BOARD_HAS_SENSOR_BARO   1

/* Default Sensor Orientation */
#define BOARD_ROTATION_DEFAULT  ROTATION_NONE

#if !defined (PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH 16
#define PX4_CPU_UUID_WORD32_LENGTH (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH PX4_CPU_UUID_BYTE_LENGTH
#endif

#include <px4_platform_common/board_common.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef __ASSEMBLY__

extern void ra8e1_boardinitialize(void);

#define board_peripheral_reset(ms)
#define board_gpio_init()

#endif /* __ASSEMBLY__ */

#ifdef __cplusplus
}
#endif
