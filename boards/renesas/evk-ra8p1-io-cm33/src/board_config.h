/****************************************************************************
 *
 *   Copyright (c) 2013-2026 PX4 Development Team. All rights reserved.
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
 * RA8P1 CM33 IO Processor - PX4IO Replacement
 *
 * This board configuration defines the peripheral assignments for the
 * Cortex-M33 core running as an IO processor on the RA8P1 dual-core MCU.
 * The CM33 handles motor control, RC input, safety logic, and ADC telemetry.
 */

#pragma once

/******************************************************************************
 * Included Files
 ******************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

/* RA8 pin/function definitions for GPIO_FUNC_GPT and port/pin masks */
#include <ra_gpio.h>
#include <hardware/ra_pinmap.h>

/******************************************************************************
 * RA8P1 CM33 Core Configuration
 ******************************************************************************/

/* CM33 Clock Configuration (set by CM85 bootloader or hardware) */
#define BOARD_CM33_CLOCK_HZ         250000000   /* 250 MHz PCLKD domain */
#define BOARD_PCLKD_HZ              BOARD_CM33_CLOCK_HZ

/******************************************************************************
 * Inter-Core Communication (IPC)
 ******************************************************************************/

/* IPC Doorbell Interrupt Configuration */
#define BOARD_IPC_IRQ_CM85_TO_CM33  100     /* IRQ number for CM85→CM33 doorbell */
#define BOARD_IPC_IRQ_CM33_TO_CM85  101     /* IRQ number for CM33→CM85 doorbell */
#define BOARD_IPC_IRQ_PRIORITY      2       /* High priority (0=highest, 15=lowest) */

/* IPC Timing Requirements */
#define BOARD_IPC_HEARTBEAT_TIMEOUT_US  100000  /* 100ms FMU heartbeat timeout */
#define BOARD_IPC_ACTUATOR_TIMEOUT_US   10000   /* 10ms actuator command timeout */

/******************************************************************************
 * GPT Timer Configuration (Motor PWM/DShot)
 *
 * CM33 uses GPT3, GPT5, GPT11, GPT13 for 4-motor outputs.
 * CM85 uses GPT0 for HRT (high-resolution timer).
 ******************************************************************************/

/* Motor output GPT assignments (DShot capable) */
#define BOARD_GPT_MOTOR1            3       /* GPT3 - Motor 1 */
#define BOARD_GPT_MOTOR2            5       /* GPT5 - Motor 2 */
#define BOARD_GPT_MOTOR3            11      /* GPT11 - Motor 3 */
#define BOARD_GPT_MOTOR4            13      /* GPT13 - Motor 4 */

/* Motor PWM Configuration using GPT channels
 * Motor 1: P912 (GPT3A)
 * Motor 2: P915 (GPT5A)
 * Motor 3: P903 (GPT11A)
 * Motor 4: P515 (GPT13A)
 *
 * GPIO Configuration Attributes for Motor Pins:
 * -----------------------------------------------
 * - Mode:          Peripheral function (PMR=1, PSEL=GPT)
 * - Direction:     Output (PDR=1)
 * - Drive:         High drive strength (DSCR=10b) for 3.3V fast switching
 * - Pull-up:       Disabled (PCR=0) - external ESC pull-down expected
 * - Open-drain:    Disabled (NCODR=0) - push-pull output required
 * - Slew rate:     High speed (default for GPT outputs)
 */
#define GPIO_MOTOR_CFG       (GPIO_PERIPHERAL | GPIO_OUTPUT | GPIO_HIGH_DRIVE)

#define GPIO_PWM_MOTOR1      GPIO_GTIOC3A_2      /* P912 - GPT3A */
#define GPIO_PWM_MOTOR2      GPIO_GTIOC5A_4      /* P915 - GPT5A */
#define GPIO_PWM_MOTOR3      GPIO_GTIOC11A_4     /* P903 - GPT11A */
#define GPIO_PWM_MOTOR4      GPIO_GTIOC13A_1     /* P515 - GPT13A */

/* PX4 motor layout macros (match CM85 naming) - with motor configuration */
#define PX4_GPIO_MOTOR_FRONT_RIGHT  (GPIO_PWM_MOTOR1 | GPIO_MOTOR_CFG)
#define PX4_GPIO_MOTOR_REAR_LEFT    (GPIO_PWM_MOTOR2 | GPIO_MOTOR_CFG)
#define PX4_GPIO_MOTOR_FRONT_LEFT   (GPIO_PWM_MOTOR3 | GPIO_MOTOR_CFG)
#define PX4_GPIO_MOTOR_REAR_RIGHT   (GPIO_PWM_MOTOR4 | GPIO_MOTOR_CFG)

/* PWM Configuration */
#define BOARD_PWM_FREQ_HZ           400     /* Default PWM frequency (Hz) */
#define BOARD_PWM_MIN_US            1000    /* Minimum pulse width (µs) */
#define BOARD_PWM_MAX_US            2000    /* Maximum pulse width (µs) */
#define BOARD_PWM_DISARMED_US       900     /* Disarmed pulse width (µs) */

/* DShot Configuration */
#define BOARD_DSHOT_BITRATE         600000  /* DShot600 (600 kbps) */
#define BOARD_DSHOT_T0H_NS          625     /* 0-bit high time (ns) */
#define BOARD_DSHOT_T1H_NS          1250    /* 1-bit high time (ns) */
#define BOARD_DSHOT_TBIT_NS         1670    /* Total bit time (ns) */

#define DIRECT_PWM_OUTPUT_CHANNELS  4       /* Number of motor outputs */
#define BOARD_HAS_NO_CAPTURE                /* No input capture on motor pins */

/******************************************************************************
 * UART/SCI Configuration (RC Input)
 ******************************************************************************/

/* RC Input UART (SBUS/CRSF/DSM) - SCI8 */
#define BOARD_RC_UART_DEV           "/dev/ttyS0"
#define BOARD_RC_UART_SCI           8       /* SCI8_A channel */
#define BOARD_RC_UART_BAUD_SBUS     100000  /* SBUS baud rate (100 kbps, inverted) */
#define BOARD_RC_UART_BAUD_CRSF     420000  /* CRSF baud rate (420 kbps) */
#define BOARD_RC_UART_BAUD_DSM      115200  /* DSM baud rate */

/* RC Input GPIO pins - SCI8 RX-only on P806 */
#define GPIO_UART_RC_RX             GPIO_RXD8_A  /* P806 - SCI8 RX (matches CM85) */
/* Note: TX not used for RC input (RX-only) */

/* SBUS inversion control (external inverter or software) */
#define BOARD_SBUS_INVERT_HARDWARE  0       /* 1 = external inverter, 0 = software */
#define GPIO_SBUS_INVERT_EN         GPIO_P110_OUTPUT_LOW  /* P110 - SBUS inverter enable */

/******************************************************************************
 * ADC Configuration (Battery Monitoring)
 *
 * ADC_B used for CM33, ADC_A used by CM85 for sensors.
 ******************************************************************************/

/* ADC_B Channel Assignments */
#define BOARD_ADC_VBAT_CHANNEL      0       /* Battery voltage input */
#define BOARD_ADC_CURRENT_CHANNEL   1       /* Battery current input */
#define BOARD_ADC_SERVO_RAIL_CHANNEL 2      /* Servo rail voltage */
#define BOARD_ADC_RSSI_CHANNEL      3       /* RSSI analog input (optional) */
#define BOARD_ADC_TEMP_CHANNEL      4       /* Temperature sensor (optional) */

/* ADC Scaling Factors */
#define BOARD_ADC_VBAT_DIVIDER_RATIO    11.0f   /* 11:1 voltage divider */
#define BOARD_ADC_CURRENT_GAIN          50.0f   /* 50x current sense amp gain */
#define BOARD_ADC_CURRENT_OFFSET_MA     0       /* Zero-current offset */
#define BOARD_ADC_SERVO_DIVIDER_RATIO   3.0f    /* 3:1 voltage divider */
#define BOARD_ADC_VREF_MV               3300    /* ADC reference voltage (mV) */
#define BOARD_ADC_RESOLUTION            4096    /* 12-bit ADC */

/* ADC Thresholds */
#define BOARD_VBAT_MIN_MV               14400   /* Minimum battery voltage (4S LiPo @ 3.6V/cell) */
#define BOARD_VBAT_BROWNOUT_MV          12000   /* Brownout threshold → POEG kill */

/* ADC Pin Configuration - Using Arduino A0-A3 pins from board.h pattern */
#define GPIO_ADC_VBAT               GPIO_P001_ANALOG  /* P001 (AN001) - Battery voltage */
#define GPIO_ADC_CURRENT            GPIO_P007_ANALOG  /* P007 (AN007) - Battery current */
#define GPIO_ADC_SERVO_RAIL         GPIO_P003_ANALOG  /* P003 (AN003) - Servo rail voltage */
#define GPIO_ADC_RSSI               GPIO_P004_ANALOG  /* P004 (AN004) - RSSI */

#define PX4IO_ADC_CHANNEL_COUNT     4

/******************************************************************************
 * Safety Switch and LEDs
 ******************************************************************************/

/* Safety Switch (GPIO input with IRQ) - Using SW1 button pattern */
#define GPIO_BTN_SAFETY             GPIO_IRQ13_P009_DS  /* P009 - SW1 (IRQ13) */
#define BOARD_SAFETY_DEBOUNCE_MS    50      /* 50ms debounce time */
#define BOARD_SAFETY_HOLD_MS        1000    /* 1s hold to toggle arming */

/* Status LEDs - CM33 IO processor indicators (active high for simplicity) */
#define GPIO_LED_BLUE               GPIO_P600_OUTPUT_LOW   /* P600 - Blue LED */
#define GPIO_LED_AMBER              GPIO_P303_OUTPUT_LOW   /* P303 - Amber/Green LED */
#define GPIO_LED_SAFETY             GPIO_PA07_OUTPUT_LOW   /* PA07 - Safety/Red LED */
#define GPIO_LED_GREEN              GPIO_P303_OUTPUT_LOW   /* P303 - Green LED (same as amber) */

/* LED Control Macros (active low for open-drain) */
#define LED_BLUE(on_true)           ra_gpiowrite(GPIO_LED_BLUE, !(on_true))
#define LED_AMBER(on_true)          ra_gpiowrite(GPIO_LED_AMBER, !(on_true))
#define LED_SAFETY(on_true)         ra_gpiowrite(GPIO_LED_SAFETY, !(on_true))
#define LED_GREEN(on_true)          ra_gpiowrite(GPIO_LED_GREEN, (on_true))

/* LED Patterns (16-bit patterns at 8Hz) */
#define LED_PATTERN_DISARMED        0x0003  /* Slow blink: ....XXXX....XXXX */
#define LED_PATTERN_ARMED           0x5555  /* Fast blink: .X.X.X.X.X.X.X.X */
#define LED_PATTERN_ERROR           0xFFFF  /* Solid on:   XXXXXXXXXXXXXXXX */
#define LED_PATTERN_RC_LOSS         0x00FF  /* 50% duty:   ........XXXXXXXX */

/******************************************************************************
 * POEG (Port Output Enable for GPT) - Emergency Motor Kill
 ******************************************************************************/

/* POEG group for motor GPT channels */
#define BOARD_POEG_GROUP            0       /* POEGG0 for motor kill */
#define GPIO_POEG_TRIGGER           (GPIO_OUTPUT | GPIO_PUSHPULL | GPIO_PORT1 | GPIO_PIN5)

/* POEG triggers */
#define BOARD_POEG_TRIGGER_BROWNOUT     (1 << 0)
#define BOARD_POEG_TRIGGER_CM85_TIMEOUT (1 << 1)
#define BOARD_POEG_TRIGGER_WATCHDOG     (1 << 2)
#define BOARD_POEG_TRIGGER_SOFTWARE     (1 << 3)

/* POEG timing */
#define BOARD_POEG_REACTION_US      1       /* Hardware kill in <1µs */

/******************************************************************************
 * Watchdog Configuration
 ******************************************************************************/

/* Independent Watchdog (IWDT) */
#define BOARD_IWDT_TIMEOUT_MS       500     /* Watchdog timeout */
#define BOARD_IWDT_WINDOW_MS        250     /* Watchdog window */

/* FMU (CM85) Heartbeat Monitoring */
#define BOARD_FMU_HEARTBEAT_RATE_HZ     10      /* Expected heartbeat rate */
#define BOARD_FMU_TIMEOUT_MS            100     /* FMU loss timeout */

/******************************************************************************
 * DMA Configuration (DShot)
 ******************************************************************************/

/* DMA channels for DShot frame generation */
#define BOARD_DSHOT_DMA_CHANNEL_M1  0       /* DMAC channel for motor 1 */
#define BOARD_DSHOT_DMA_CHANNEL_M2  1       /* DMAC channel for motor 2 */
#define BOARD_DSHOT_DMA_CHANNEL_M3  2       /* DMAC channel for motor 3 */
#define BOARD_DSHOT_DMA_CHANNEL_M4  3       /* DMAC channel for motor 4 */

/******************************************************************************
 * Buzzer (Optional)
 ******************************************************************************/

#define GPIO_BUZZER                 (GPIO_OUTPUT | GPIO_PUSHPULL | GPIO_PORT1 | GPIO_PIN6)
#define BUZZER_ON()                 ra_gpiowrite(GPIO_BUZZER, 1)
#define BUZZER_OFF()                ra_gpiowrite(GPIO_BUZZER, 0)

/******************************************************************************
 * High-Resolution Timer (HRT) for CM33
 *
 * Uses GPT1 for microsecond timing (GPT0 reserved for CM85 HRT)
 ******************************************************************************/

#define HRT_TIMER                   1       /* GPT1 for CM33 HRT */
#define HRT_TIMER_CHANNEL           0       /* Compare channel 0 */
#define BOARD_HRT_CLOCK_HZ          BOARD_PCLKD_HZ

/******************************************************************************
 * Board Initialization
 ******************************************************************************/

/* IO Timers: GPT3, GPT5, GPT11, GPT13 for 4 PWM outputs (matching CM85) */
#ifndef BOARD_NUM_IO_TIMERS
#define BOARD_NUM_IO_TIMERS         4
#endif

#ifndef DIRECT_PWM_OUTPUT_CHANNELS
#define DIRECT_PWM_OUTPUT_CHANNELS  4
#endif

#ifndef __ASSEMBLY__

/* Forward declarations */
void board_initialize(void);
void board_peripheral_init(void);
void board_poeg_init(void);
void board_poeg_trigger_kill(uint32_t reason);
void board_watchdog_init(void);
void board_watchdog_refresh(void);

/* GPIO access functions (RA8-specific) */
void ra_gpiowrite(gpio_pinset_t pinset, bool value);
bool ra_gpioread(gpio_pinset_t pinset);
int ra_gpioconfig(gpio_pinset_t pinset);

#endif /* __ASSEMBLY__ */

/* I2C buses - CM33 IO processor doesn't actively use I2C, set to minimum */
#define PX4_NUMBER_I2C_BUSES 1

/* SPI buses - CM33 IO processor doesn't use SPI (handled by CM85) */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS 1

#include <px4_platform_common/board_common.h>
