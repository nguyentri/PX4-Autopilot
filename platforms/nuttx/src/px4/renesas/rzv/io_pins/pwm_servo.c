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
#define PWM_MIN_RATE          50      /* Hz */
#define PWM_MAX_RATE          500     /* Hz */
#define PWM_MIN_PULSE_WIDTH   1000    /* us */
#define PWM_MAX_PULSE_WIDTH   2000    /* us */

static uint32_t pwm_rate = PWM_DEFAULT_RATE;

/**
 * Initialize PWM servo outputs
 */
int up_pwm_servo_init(uint32_t channel_mask)
{
	uint32_t current_mask = 0;

	/* Release only channels owned by analog PWM modes. A prior PWMOut
	 * instance may have stopped, while DShot or another timer client must
	 * remain untouched.
	 */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		int mode = io_timer_get_channel_mode(i);

		if (mode == IOTimerChanMode_PWMOut || mode == IOTimerChanMode_OneShot) {
			current_mask |= 1u << i;
		}
	}

	if (current_mask != 0) {
		io_timer_set_enable(false, IOTimerChanMode_PWMOut, current_mask);

		for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
			if (current_mask & (1u << i)) {
				io_timer_unallocate_channel(i);
			}
		}
	}

	uint32_t initialized_mask = 0;

	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (channel_mask & (1u << i)) {
			int ret = io_timer_channel_init(i, IOTimerChanMode_PWMOut, NULL, NULL);

			if (ret == 0) {
				initialized_mask |= 1u << i;

			} else {
				up_pwm_servo_deinit(initialized_mask);
				return ret;
			}
		}
	}

	return initialized_mask;
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
		int mode = io_timer_get_channel_mode(i);

		if ((channel_mask & (1u << i)) &&
		    (mode == IOTimerChanMode_PWMOut || mode == IOTimerChanMode_OneShot)) {
			io_timer_unallocate_channel(i);
		}
	}
}

/**
 * Set PWM rate (frequency)
 */
int up_pwm_servo_set_rate(unsigned rate)
{
	if (rate < PWM_MIN_RATE || rate > PWM_MAX_RATE) {
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

int up_pwm_servo_set_rate_group_update(unsigned group, unsigned rate)
{
	uint32_t channel_mask = io_timer_get_group(group);

	if (rate < PWM_MIN_RATE || rate > PWM_MAX_RATE) {
		return -ERANGE;
	}

	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if ((channel_mask & (1 << i)) &&
		    io_timer_get_channel_mode(i) == IOTimerChanMode_PWMOut) {
			int ret = io_timer_set_pwm_rate(i, rate);

			if (ret != 0) {
				return ret;
			}
		}
	}

	pwm_rate = rate;
	return 0;
}

uint32_t up_pwm_servo_get_rate_group(unsigned group)
{
	uint32_t channel_mask = io_timer_get_group(group);
	uint32_t pwm_mask = 0;

	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if ((channel_mask & (1 << i)) &&
		    io_timer_get_channel_mode(i) == IOTimerChanMode_PWMOut) {
			pwm_mask |= (1 << i);
		}
	}

	return pwm_mask;
}

void up_pwm_update(unsigned channel_mask)
{
	(void)channel_mask;
}

/**
 * Set PWM pulse width for a channel
 */
int up_pwm_servo_set(unsigned channel, uint16_t value)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	if (value == 0) {
		return io_timer_set_ccr(channel, 0);
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
		/* io_timer_set_enable() forces the selected GTIOC outputs inactive. */
		io_timer_set_enable(false, IOTimerChanMode_PWMOut, channel_mask);
	}

}
