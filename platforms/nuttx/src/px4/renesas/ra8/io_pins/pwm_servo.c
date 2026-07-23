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
 * Servo driver supporting PWM servos connected to Renesas RA8 GPT timer blocks.
 *
 * This provides the interface between PX4's pwm_out driver and the RA8 GPT
 * hardware timers for motor control.
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <sys/types.h>
#include <stdbool.h>

#include <assert.h>
#include <debug.h>
#include <time.h>
#include <queue.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>

#include <arch/board/board.h>
#include <drivers/drv_pwm_output.h>

#include <px4_arch/io_timer.h>

/**
 * Set PWM pulse width for a servo channel
 *
 * @param channel PWM channel number (0-3 for 4 motors)
 * @param value   Pulse width in microseconds (typically 1000-2000)
 * @return        OK on success, negative errno on failure
 */
int up_pwm_servo_set(unsigned channel, uint16_t value)
{
	return io_timer_set_ccr(channel, value);
}

/**
 * Get current PWM pulse width for a servo channel
 *
 * @param channel PWM channel number
 * @return        Current pulse width in microseconds, or 0 on error
 */
uint16_t up_pwm_servo_get(unsigned channel)
{
	return io_channel_get_ccr(channel);
}

/**
 * Initialize PWM servo outputs
 *
 * @param channel_mask Bitmask of channels to initialize (bit 0 = channel 0, etc.)
 * @return             Bitmask of successfully initialized channels, or negative errno
 */
int up_pwm_servo_init(uint32_t channel_mask)
{
	/* Get currently allocated PWM channels */
	uint32_t current = io_timer_get_mode_channels(IOTimerChanMode_PWMOut) |
			   io_timer_get_mode_channels(IOTimerChanMode_OneShot);

	/* First free the current set of PWM channels */
	for (unsigned channel = 0; current != 0 && channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (current & (1 << channel)) {
			io_timer_set_enable(false, IOTimerChanMode_PWMOut, 1 << channel);
			io_timer_unallocate_channel(channel);
			current &= ~(1 << channel);
		}
	}

	/* Now allocate the new set of channels */
	int ret_val = OK;
	int channels_init_mask = 0;

	for (unsigned channel = 0; channel_mask != 0 && channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (channel_mask & (1 << channel)) {
			/* Initialize channel for PWM output mode */
			ret_val = io_timer_channel_init(channel, IOTimerChanMode_PWMOut, NULL, NULL);
			channel_mask &= ~(1 << channel);

			if (OK == ret_val) {
				channels_init_mask |= 1 << channel;

			} else if (ret_val == -EBUSY) {
				/* Timer or channel already in use - not fatal */
				ret_val = 0;
			}
		}
	}

	return ret_val == OK ? channels_init_mask : ret_val;
}

/**
 * Deinitialize PWM servo outputs
 *
 * @param channel_mask Bitmask of channels to deinitialize
 */
void up_pwm_servo_deinit(uint32_t channel_mask)
{
	/* Disable the timers */
	up_pwm_servo_arm(false, channel_mask);
}

/**
 * Set PWM rate (frequency) for a channel's timer group
 *
 * @param channel PWM channel number
 * @param rate    PWM frequency in Hz (0 for OneShot mode, 1-10000 for normal PWM)
 * @return        OK on success, negative errno on failure
 */
int up_pwm_servo_set_rate_group_update(unsigned channel, unsigned rate)
{
	if (io_timer_validate_channel_index(channel) < 0) {
		return ERROR;
	}

	/* Allow a rate of 0 to enter OneShot mode */
	if (rate != 0) {
		/* Limit update rate to 1..10000Hz; somewhat arbitrary but safe */
		if (rate < 1) {
			return -ERANGE;
		}

		if (rate > 10000) {
			return -ERANGE;
		}
	}

	return io_timer_set_pwm_rate(channel, rate);
}

/**
 * Trigger PWM update for OneShot/DShot modes
 *
 * @param channel_mask Bitmask of channels to update
 */
void up_pwm_update(unsigned channel_mask)
{
	io_timer_trigger(channel_mask);
}

/**
 * Get the set of PWM channels in a timer group
 *
 * @param group Timer group number
 * @return      Bitmask of channels in the group
 */
uint32_t up_pwm_servo_get_rate_group(unsigned group)
{
	/* Return the set of channels in the group which we own */
	return (io_timer_get_mode_channels(IOTimerChanMode_PWMOut) |
		io_timer_get_mode_channels(IOTimerChanMode_OneShot)) &
	       io_timer_get_group(group);
}

/**
 * Enable or disable PWM outputs (arm/disarm motors)
 *
 * @param armed        true to enable outputs, false to disable
 * @param channel_mask Bitmask of channels to arm/disarm
 */
void up_pwm_servo_arm(bool armed, uint32_t channel_mask)
{
	io_timer_set_enable(armed, IOTimerChanMode_OneShot, channel_mask);
	io_timer_set_enable(armed, IOTimerChanMode_PWMOut, channel_mask);
}
