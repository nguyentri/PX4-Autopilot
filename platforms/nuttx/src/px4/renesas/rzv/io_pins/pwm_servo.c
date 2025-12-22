/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
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
 * @file pwm_servo.c
 *
 * PWM servo driver for RZV2H GPT timers
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

#include <px4_platform_common/px4_config.h>
#include <drivers/drv_pwm_output.h>
#include "../include/px4_arch/io_timer.h"

#include "board_config.h"

/* Default PWM parameters */
#define PWM_DEFAULT_RATE      400     /* Hz */
#define PWM_MIN_PULSE_WIDTH   900     /* us */
#define PWM_MAX_PULSE_WIDTH   2100    /* us */
#define PWM_DISARMED_WIDTH    1000    /* us */

static bool pwm_initialized = false;
static uint32_t pwm_rate = PWM_DEFAULT_RATE;

/**
 * Initialize PWM servo outputs
 */
int up_pwm_servo_init(uint32_t channel_mask)
{
	if (pwm_initialized) {
		return 0;
	}

	/* Initialize IO timer system */
	int ret = io_timer_init();
	if (ret != 0) {
		return ret;
	}

	/* Allocate channels for PWM output */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (channel_mask & (1 << i)) {
			ret = io_timer_allocate_channel(i, IOTimerChanMode_PWMOut);
			if (ret != 0) {
				return ret;
			}
		}
	}

	pwm_initialized = true;
	return 0;
}

/**
 * De-initialize PWM servo outputs
 */
void up_pwm_servo_deinit(uint32_t channel_mask)
{
	/* Disable all channels */
	io_timer_set_enable(false, IOTimerChanMode_PWMOut, channel_mask);

	/* Unallocate channels */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (channel_mask & (1 << i)) {
			io_timer_unallocate_channel(i);
		}
	}
}

/**
 * Set PWM rate (frequency)
 */
int up_pwm_servo_set_rate(unsigned rate)
{
	if (rate < 50 || rate > 500) {
		return -EINVAL;
	}

	pwm_rate = rate;

	/* Update all channels with new rate */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (io_timer_get_channel_mode(i) == IOTimerChanMode_PWMOut) {
			io_timer_set_pwm_rate(i, rate);
		}
	}

	return 0;
}

/**
 * Get current PWM rate
 */
unsigned up_pwm_servo_get_rate(void)
{
	return pwm_rate;
}

/**
 * Set PWM pulse width for a channel
 */
int up_pwm_servo_set(unsigned channel, uint16_t value)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	/* Clamp value to valid range */
	if (value < PWM_MIN_PULSE_WIDTH) {
		value = PWM_MIN_PULSE_WIDTH;
	} else if (value > PWM_MAX_PULSE_WIDTH) {
		value = PWM_MAX_PULSE_WIDTH;
	}

	return io_timer_set_ccr(channel, value);
}

/**
 * Get current PWM pulse width for a channel
 */
uint16_t up_pwm_servo_get(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return 0;
	}

	return io_timer_get_ccr(channel);
}

/**
 * Arm PWM outputs
 */
void up_pwm_servo_arm(bool armed, uint32_t channel_mask)
{
	if (armed) {
		/* Enable all channels in mask */
		io_timer_set_enable(true, IOTimerChanMode_PWMOut, channel_mask);
	} else {
		/* Set all channels to disarmed value, then disable */
		for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
			if (channel_mask & (1 << i)) {
				io_timer_set_ccr(i, PWM_DISARMED_WIDTH);
			}
		}
		io_timer_set_enable(false, IOTimerChanMode_PWMOut, channel_mask);
	}

}
