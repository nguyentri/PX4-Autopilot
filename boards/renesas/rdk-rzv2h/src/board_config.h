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

/** @file board_config.h
 *
 * Renesas RDK-RZV2H board configuration for PX4.
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
 * PX4 Sensor Configuration:
 * - MPU9250 IMU on RSPI0 (P90=MOSI, P91=MISO, P92=SCK, P93=GPIO CS) with INT on P94 (TINT)
 * - The simple bench profile substitutes ICM20948 on the same SPI0/CS/INT wiring
 * - BMP280 barometer on RSCI7 SCI-mode I2C (P76=SDA, P77=SCL) at address 0x76
 *
 * Serial Ports (sparse numbering matches SCI channel; no debug UART, console = SEGGER RTT):
 * - RSCI4 (/dev/ttyS4): TFminiPlus LiDAR (P70=TXD, P71=RXD)
 * - RSCI5 (/dev/ttyS5): Sik Telemetry v3 (P72=TXD, P73=RXD)
 * - RSCI6 (/dev/ttyS6): fs-a8s RC receiver (P75=RXD only)
 * - RSCI9 (/dev/ttyS9): GPS M10 module (P82=TXD, P83=RXD)
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
#define BOARD_HAS_ON_RESET              1  /* Quiesce motor pins before reset */
#define BOARD_TYPE_COMPLETE             89 /* Board type ID for RZV2H */

/* CPU UUID Configuration */
#if !defined(PX4_CPU_UUID_BYTE_LENGTH)
#define PX4_CPU_UUID_BYTE_LENGTH        16
#define PX4_CPU_UUID_WORD32_LENGTH      (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH      PX4_CPU_UUID_BYTE_LENGTH
#endif

/****************************************************************************************************
 * UART/Serial Configuration
 ****************************************************************************************************/

/* UART Device Mapping (sparse SCI channels; console = RTT, no debug UART)
 * RSCI4 (ttyS4): TFminiPlus LiDAR  (P70=TXD4, P71=RXD4)
 * RSCI5 (ttyS5): Sik Telemetry v3  (P72=TXD5, P73=RXD5)
 * RSCI6 (ttyS6): fs-a8s RC input   (P75=RXD6 only)
 * RSCI9 (ttyS9): GPS M10           (P82=TXD9, P83=RXD9)
 */
/* PX4_UART_CONSOLE intentionally undefined: console routed via SEGGER RTT (J-Link). */
#define PX4_UART_GPS1                   "ttyS9"  /* RSCI9 - GPS M10 */
#define PX4_UART_TELEM1                 "ttyS5"  /* RSCI5 - Sik Telemetry v3 */
#define PX4_UART_RANGEFINDER            "ttyS4"  /* RSCI4 - TFminiPlus */
#define PX4_UART_RC                     "ttyS6"  /* RSCI6 - fs-a8s RC input */

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
 * I2C7 = RSCI7 in SCI-mode I2C (NOT a standalone RIIC peripheral): BMP280 barometer
 * (P76=SDA, P77=SCL). Driver: rzv_sci_i2c.c. PIO mode; DMAC is disabled.
 *
 * Secondary / ADC-I2C Bus (RSCI0):
 * SCI0: RXD0=P51(Mode1) -> SCL (40-pin Pin 36), TXD0=P50(Mode1) -> SDA (40-pin Pin 22)
 * Driver: rzv_sci_i2c.c (/dev/i2c10, PX4 bus 0 when CONFIG_RZV_SCI0_I2C). Used for ADC-I2C
 * (ADS1115: standalone ads1115 config, PX4 demo profile), candidate dedicated interface for BMS monitor (battery management).
 * External pull-ups to 3.3V are required (RDK has no on-board pull-ups on P50/P51).
 */
#if defined(CONFIG_RZV_SCI0_I2C)
/* Order matches px4_i2c_buses[] in i2c.cpp: SCI7 (bus 7), then SCI0 (bus 0). */
#define PX4_NUMBER_I2C_BUSES            2
#define BOARD_NUMBER_I2C_BUSES          2
#define BOARD_I2C_BUS_CLOCK_INIT        {100000, 100000}  /* 100kHz for I2C7 and SCI0 */
#else
#define PX4_NUMBER_I2C_BUSES            1
#define BOARD_NUMBER_I2C_BUSES          1
#define BOARD_I2C_BUS_CLOCK_INIT        {100000}  /* 100kHz for I2C7 */
#endif
#define I2C_BUS_MAX_BUS_ITEMS           PX4_NUMBER_I2C_BUSES

/* I2C Bus Assignment */
#define PX4_I2C_BUS_EXPANSION           7  /* I2C7 for external devices (barometer) */
#define PX4_I2C_BUS_ADC_EXTERNAL        0  /* SCI0 simple-I2C, opt-in per profile (ADS1115) */
/* Parameters are intended for CR8-owned XSPI + LittleFS. Do not map MTD to
 * the sensor I2C bus; add a real XSPI MTD manifest before enabling PX4 MTD
 * persistence on this board.
 */
#define PX4_I2C_OBDEV_BMP280            0x76  /* BMP280 I2C address */

/****************************************************************************************************
 * SPI Configuration
 ****************************************************************************************************/

/* SPI Bus Configuration
 * RSPI0: one selected MPU9250 or ICM20948 IMU on the shared wiring.
 * P90 = MOSI A, P91 = MISO A, P92 = SCK A. P93 is configured as an
 * active-low GPIO chip select by the NuttX board layer.
 * P94 is used as the selected IMU INT input (TINT), not as SSLA1. It is shared
 * with the NuttX button demo, so the two cannot be wired at the same time.
 */
#define PX4_NUMBER_SPI_BUSES            1
#define BOARD_NUMBER_SPI_BUSES          1
#define BOARD_SPI_BUS_SENSORS           0  /* RSPI0 for IMU */
#define PX4_SPI_BUS_SENSORS             0
#define PX4_SPI_BUS_MEMORY              PX4_SPI_BUS_SENSORS

/* SPI Bus Limits */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS     1
#define BOARD_SPI_BUS_MAX_DEVICES       1  /* One physical IMU/CS */
#define SPI_BUS_MAX_BUS_ITEMS           BOARD_SPI_BUS_MAX_BUS_ITEMS

/* MPU9250 IMU on RSPI0 */
#ifndef BOARD_MPU9250_BUS
#  define BOARD_MPU9250_BUS             0  /* RSPI0 */
#endif
#ifndef BOARD_MPU9250_CS_GPIO
#  define BOARD_MPU9250_CS_GPIO         GPIO_P9_3_OUTPUT_HIGH  /* P93 = active-low GPIO CS */
#endif
#ifndef BOARD_MPU9250_DRDY_GPIO
#  define BOARD_MPU9250_DRDY_GPIO       GPIO_P9_4_INPUT  /* P94 (TINT) */
#endif

/* ICM20948 alternative on the same SPI0 pads; P94 is exclusively owned. */
#ifndef BOARD_ICM20948_BUS
#  define BOARD_ICM20948_BUS            0
#endif
#ifndef BOARD_ICM20948_CS_GPIO
#  define BOARD_ICM20948_CS_GPIO        GPIO_P9_3_OUTPUT_HIGH
#endif
#ifndef BOARD_ICM20948_DRDY_GPIO
#  define BOARD_ICM20948_DRDY_GPIO      GPIO_TINT_P9_4
#endif

/****************************************************************************************************
 * PWM/Timer Configuration (GPT)
 ****************************************************************************************************/

/**
 * PWM Configuration - 4 ESC channels using GPT timers
 *
 * Timer-to-Channel-to-Pin Mapping (Single Source of Truth):
 * Based on RDK-RZV2H pin mapping table:
 * +--------+-----------+----------+--------------------+---------+
 * | PX4 Ch | GPT Timer | Output   | GPIO Pin           | Mode    |
 * +--------+-----------+----------+--------------------+---------+
 * | PWM0   | GPT6      | GTIOC6A  | PA4 (Port10, Pin4) | Mode 11 |
 * | PWM1   | GPT7      | GTIOC7B  | PA7 (Port10, Pin7) | Mode 11 |
 * | PWM2   | GPT9      | GTIOC9A  | P96 (Port9, Pin6)  | Mode 9  |
 * | PWM3   | GPT10     | GTIOC10B | P53 (Port5, Pin3)  | Mode 11 |
 * +--------+-----------+----------+--------------------+---------+
 *
 * GPIO Header Pin Assignment:
 * - GPIO12/PWM0 -> PA4 -> ESC1 (GPT6A)
 * - GPIO13/PWM1 -> PA7 -> ESC2 (GPT7B)
 * - GPIO19      -> P96 -> ESC3 (GPT9A)
 * - GPIO06      -> P53 -> ESC4 (GPT10B)
 *
 * PWM Settings:
 * - Frequency: 400 Hz (default ESC rate, configurable to 50-500 Hz)
 * - Pulse Width: 1000-2000 us (standard PWM servo range)
 * - Resolution: runtime P4CLK dependent; nominal P4CLK is 200 MHz
 *
 * Reference: NuttX arch/arm/src/rzv/hardware/rzv2h/rzv2h_pinmap.h
 */

/* ESC Channel Count */
#define DIRECT_PWM_OUTPUT_CHANNELS      4
#define BOARD_PWM_MOTOR_OUTPUTS_DISABLE_ON_STOP_MOTORS 1
#ifndef CONFIG_DRIVERS_DSHOT
#  define BOARD_PWM_OUTPUTS_REQUIRE_COMPLETE_INIT 1
#endif
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
#  define BOARD_PWM_CH0_GPIO            (GPIO_GTIOC6A_PA_4_M11 | RZV_GPIO_PERIPH)  /* ESC1: GPT6A on PA4 (GPIO12/PWM0) */
#endif
#ifndef BOARD_PWM_CH1_GPIO
#  define BOARD_PWM_CH1_GPIO            (GPIO_GTIOC7B_PA_7_M11 | RZV_GPIO_PERIPH)  /* ESC2: GPT7B on PA7 (GPIO13/PWM1) */
#endif
#ifndef BOARD_PWM_CH2_GPIO
#  define BOARD_PWM_CH2_GPIO            (GPIO_GTIOC9A_P9_6_M9 | RZV_GPIO_PERIPH)   /* ESC3: GPT9A on P96 (GPIO19) */
#endif
#ifndef BOARD_PWM_CH3_GPIO
#  define BOARD_PWM_CH3_GPIO            (GPIO_GTIOC10B_P5_3_M11 | RZV_GPIO_PERIPH) /* ESC4: GPT10B on P53 (GPIO06) */
#endif

/* The same motor pad as a GPIO output driven low. Used while no GPT owns the
 * pad (early boot, reset, a failed timer bring-up) so an ESC input never
 * floats: a floating line can read high and look like a pulse.
 */
#define BOARD_PWM_GPIO_DRIVEN_LOW(gpio) \
	(((gpio) & (GPIO_PORT_MASK | GPIO_PIN_MASK)) | RZV_GPIO_OUTPUT | \
	 RZV_GPIO_DRVSTR_NORMAL | RZV_GPIO_INITIAL_LOW)

/* DShot Motor Assignment (channel index mapping) */
#define BOARD_DSHOT_MOTOR_ASSIGNMENT    {0, 1, 2, 3}

/****************************************************************************************************
 * High-Resolution Timer (HRT)
 ****************************************************************************************************/

/* HRT is owned by the RZ/V2H NuttX lower-half on dedicated GTM7. Its timebase
 * is derived from runtime P1CLK; board code must not publish a second timer
 * number or hard-coded frequency contract.
 */

/****************************************************************************************************
 * LED Configuration
 ****************************************************************************************************/

/* LED GPIO Definitions (matched to NuttX board.h and actual RDK hardware)
 *
 * The RDK-RZV2H has 2 user LEDs on the board silk:
 *   LED0 (index 0): PB4 (GPIO Port B / PORT11, Pin 4) — active HIGH
 *   LED1 (index 1): PB5 (GPIO Port B / PORT11, Pin 5) — active HIGH
 *
 * Active high: write 1 to turn on, 0 to turn off.
 * Initial state OUTPUT_LOW = LED off at boot.
 *
 * PX4 naming uses GPIO_LED_n (non-inverted) since these are active-high.
 */
#define GPIO_LED_1                      GPIO_PB_4_OUTPUT_LOW   /* LED0 - Status (PB4) */
#define GPIO_LED_2                      GPIO_PB_5_OUTPUT_LOW   /* LED1 - Armed  (PB5) */

#define GPIO_LED_BLUE                   GPIO_LED_1
#define GPIO_LED_GREEN                  GPIO_LED_2

#define BOARD_HAS_CONTROL_STATUS_LEDS   1
#define BOARD_OVERLOAD_LED              0  /* LED0 for overload */
#define BOARD_ARMED_STATE_LED           1  /* LED1 for armed state */
#define BOARD_MAX_LEDS                  2

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
#if defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250) || defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948) || defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM45686)
#define BOARD_HAS_SENSOR_IMU            1
#else
#define BOARD_HAS_SENSOR_IMU            0
#endif
#if defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250) || defined(CONFIG_DRIVERS_MAGNETOMETER_BOSCH_BMM150)
#define BOARD_HAS_SENSOR_MAG            1
#else
#define BOARD_HAS_SENSOR_MAG            0  /* ICM20948 auxiliary mag is an optional manual start */
#endif
#if defined(CONFIG_DRIVERS_BAROMETER_BMP280) || defined(CONFIG_DRIVERS_BAROMETER_BMP388)
#define BOARD_HAS_SENSOR_BARO           1
#else
#define BOARD_HAS_SENSOR_BARO           0
#endif
#define BOARD_HAS_SENSOR_RANGEFINDER    1  /* TFminiPlus LiDAR */

/* Default Sensor Orientation */
#define BOARD_ROTATION_DEFAULT          ROTATION_NONE

/****************************************************************************************************
 * CAN Configuration (Not available on this board)
 ****************************************************************************************************/

#define BOARD_HAS_CAN                   0

/****************************************************************************************************
 * Hardfault Log Configuration
 ****************************************************************************************************/

#define HARDFAULT_ULOG_PATH             "/fs/fault.log"
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
