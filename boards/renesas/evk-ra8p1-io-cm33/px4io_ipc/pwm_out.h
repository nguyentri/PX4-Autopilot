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
 * @file pwm_out.h
 *
 * PWM and DShot output driver for RA8P1 CM33 IO processor.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Number of motor output channels */
#define PWM_OUT_MAX_CHANNELS    4

/* PWM frequency range */
#define PWM_FREQ_MIN            50      /* Hz */
#define PWM_FREQ_MAX            500     /* Hz */
#define PWM_FREQ_DEFAULT        400     /* Hz */

/* PWM pulse width range (microseconds) */
#define PWM_PULSE_MIN           800     /* us - minimum pulse */
#define PWM_PULSE_MAX           2200    /* us - maximum pulse */
#define PWM_PULSE_DISARMED      900     /* us - disarmed pulse */
#define PWM_PULSE_FAILSAFE      900     /* us - failsafe pulse */

/* DShot throttle range */
#define DSHOT_THROTTLE_MIN      48      /* First valid throttle value */
#define DSHOT_THROTTLE_MAX      2047    /* Maximum throttle value */

/* DShot special commands (0-47 when motor is stopped) */
#define DSHOT_CMD_MOTOR_STOP            0
#define DSHOT_CMD_BEEP1                 1
#define DSHOT_CMD_BEEP2                 2
#define DSHOT_CMD_BEEP3                 3
#define DSHOT_CMD_BEEP4                 4
#define DSHOT_CMD_BEEP5                 5
#define DSHOT_CMD_ESC_INFO              6
#define DSHOT_CMD_SPIN_DIRECTION_1      7
#define DSHOT_CMD_SPIN_DIRECTION_2      8
#define DSHOT_CMD_3D_MODE_OFF           9
#define DSHOT_CMD_3D_MODE_ON            10
#define DSHOT_CMD_SETTINGS_REQUEST      11
#define DSHOT_CMD_SAVE_SETTINGS         12
#define DSHOT_CMD_SPIN_DIRECTION_NORMAL 20
#define DSHOT_CMD_SPIN_DIRECTION_REV    21
#define DSHOT_CMD_LED0_ON               22
#define DSHOT_CMD_LED1_ON               23
#define DSHOT_CMD_LED2_ON               24
#define DSHOT_CMD_LED3_ON               25
#define DSHOT_CMD_LED0_OFF              26
#define DSHOT_CMD_LED1_OFF              27
#define DSHOT_CMD_LED2_OFF              28
#define DSHOT_CMD_LED3_OFF              29

/****************************************************************************
 * Public Types
 ****************************************************************************/

/**
 * @brief Output mode enumeration
 */
typedef enum {
	OUTPUT_MODE_NONE = 0,       /**< No output configured */
	OUTPUT_MODE_PWM,            /**< Standard PWM output */
	OUTPUT_MODE_DSHOT150,       /**< DShot150 protocol */
	OUTPUT_MODE_DSHOT300,       /**< DShot300 protocol */
	OUTPUT_MODE_DSHOT600,       /**< DShot600 protocol */
	OUTPUT_MODE_DSHOT1200,      /**< DShot1200 protocol */
} output_mode_t;

/****************************************************************************
 * Public Function Prototypes
 ****************************************************************************/

/**
 * @brief Initialize PWM/DShot output driver
 * @return 0 on success, negative errno on failure
 */
int pwm_out_init(void);

/**
 * @brief Set output mode (PWM or DShot)
 * @param mode Output mode to configure
 * @return 0 on success, negative errno on failure
 */
int pwm_out_set_mode(output_mode_t mode);

/**
 * @brief Set PWM frequency (PWM mode only)
 * @param freq_hz Frequency in Hz (50-500)
 * @return 0 on success, negative errno on failure
 */
int pwm_out_set_frequency(uint32_t freq_hz);

/**
 * @brief Arm/disarm motor outputs
 * @param arm true to arm, false to disarm
 * @return 0 on success, negative errno on failure
 */
int pwm_out_arm(bool arm);

/**
 * @brief Set motor output value
 * @param channel Motor channel (0-3)
 * @param value PWM pulse width in us (PWM mode) or throttle 0-2047 (DShot mode)
 * @return 0 on success, negative errno on failure
 */
int pwm_out_set(unsigned channel, uint16_t value);

/**
 * @brief Trigger DShot frame transmission for all channels
 * Call this at the desired DShot update rate (typically 1-8kHz)
 */
void pwm_out_trigger_dshot(void);

/**
 * @brief Set disarmed value for channel
 * @param channel Motor channel (0-3)
 * @param value Disarmed PWM/throttle value
 */
void pwm_out_set_disarmed(unsigned channel, uint16_t value);

/**
 * @brief Set failsafe value for channel
 * @param channel Motor channel (0-3)
 * @param value Failsafe PWM/throttle value
 */
void pwm_out_set_failsafe(unsigned channel, uint16_t value);

/**
 * @brief Apply failsafe values to all channels
 */
void pwm_out_failsafe(void);

/**
 * @brief Trigger emergency stop via POEG
 * Immediately stops all motor outputs using hardware POEG
 */
void pwm_out_emergency_stop(void);

/**
 * @brief Clear emergency stop
 * Must be called to re-enable motor outputs after emergency stop
 */
void pwm_out_clear_emergency(void);

/**
 * @brief Check if emergency stop is active
 * @return true if emergency stop is active
 */
bool pwm_out_is_emergency(void);

/**
 * @brief Get current output mode
 * @return Current output mode
 */
output_mode_t pwm_out_get_mode(void);

/**
 * @brief Check if outputs are armed
 * @return true if outputs are armed
 */
bool pwm_out_is_armed(void);

/**
 * @brief Request telemetry on next DShot frame
 * @param channel Motor channel (0-3)
 */
void pwm_out_request_telemetry(unsigned channel);

/**
 * @brief Send DShot command (special command 0-47)
 * @param channel Motor channel (0-3)
 * @param command DShot command (0-47)
 * @param telemetry Request telemetry response
 * @return 0 on success, negative errno on failure
 */
int pwm_out_dshot_command(unsigned channel, uint8_t command, bool telemetry);

/****************************************************************************
 * PX4IO Interface Compatibility Functions
 ****************************************************************************/

/**
 * @brief Initialize PWM servo outputs (PX4IO interface)
 * @param channel_mask Bitmask of channels to initialize
 * @return Number of channels initialized
 */
int up_pwm_servo_init(uint32_t channel_mask);

/**
 * @brief Deinitialize PWM servo outputs (PX4IO interface)
 * @param channel_mask Bitmask of channels to deinitialize
 */
void up_pwm_servo_deinit(uint32_t channel_mask);

/**
 * @brief Arm/disarm PWM servo outputs (PX4IO interface)
 * @param arm true to arm, false to disarm
 * @param channel_mask Bitmask of channels to arm/disarm
 * @return 0 on success, negative errno on failure
 */
void up_pwm_servo_arm(bool arm, uint32_t channel_mask);

/**
 * @brief Set PWM servo value (PX4IO interface)
 * @param channel Servo channel
 * @param value PWM pulse width in microseconds
 * @return 0 on success, negative errno on failure
 */
int up_pwm_servo_set(unsigned channel, uint16_t value);

/**
 * @brief Get current PWM servo value (PX4IO interface)
 * @param channel Servo channel
 * @return Current PWM pulse width in microseconds
 */
uint16_t up_pwm_servo_get(unsigned channel);

/**
 * @brief Set PWM frequency (PX4IO interface)
 * @param rate Frequency in Hz
 * @return 0 on success, negative errno on failure
 */
int up_pwm_servo_set_rate(unsigned rate);

/**
 * @brief Get rate group for channel (PX4IO interface)
 * @param group Rate group
 * @return Bitmask of channels in group
 */
uint32_t up_pwm_servo_get_rate_group(unsigned group);

#ifdef __cplusplus
}
#endif
