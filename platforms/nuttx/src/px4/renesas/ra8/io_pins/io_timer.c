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
 * @file io_timer.c
 *
 * NuttX HAL-based IO Timer implementation for RA8E1 GPT timers
 */

#include <px4_platform_common/px4_config.h>
#include <systemlib/px4_macros.h>

#include <nuttx/arch.h>
#include <nuttx/irq.h>
#include <nuttx/timers/pwm.h>

#include <sys/types.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <syslog.h>

#include <drivers/drv_pwm_output.h>

#include <px4_arch/io_timer.h>
#include <px4_arch/micro_hal.h>

/* External GPT driver functions from NuttX */
extern struct pwm_lowerhalf_s *ra_gpt_initialize(int channel);

/* Global PWM device handles for RA8E1 GPT timers */
static struct pwm_lowerhalf_s *pwm_devices[MAX_IO_TIMERS] = { NULL };
static int pwm_fds[MAX_IO_TIMERS] = { -1, -1, -1, -1 };

/* PWM configuration storage */
static uint16_t pwm_values[MAX_TIMER_IO_CHANNELS] = { 0 };
static uint32_t pwm_rate = 400; /* Default 400Hz for ESC */
static bool pwm_armed = false;

/* Channel to GPT mapping */
static const uint8_t channel_to_gpt[MAX_TIMER_IO_CHANNELS] = {
	3, /* Channel 0 -> GPT3 */
	0, /* Channel 1 -> GPT0 */
	2, /* Channel 2 -> GPT2 */
	4, /* Channel 3 -> GPT4 */
};

/**
 * Initialize PWM servo outputs using NuttX PWM HAL
 */
int up_pwm_servo_init(uint32_t channel_mask)
{
	int ret = 0;
	char device_path[16];

	/* Initialize PWM devices for enabled channels */
	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (channel_mask & (1 << channel)) {
			uint8_t gpt_channel = channel_to_gpt[channel];

			/* Initialize GPT PWM device */
			pwm_devices[channel] = ra_gpt_initialize(gpt_channel);
			if (pwm_devices[channel] == NULL) {
				syslog(LOG_ERR, "Failed to initialize GPT%d for PWM channel %d\n",
				       gpt_channel, channel);
				ret = -1;
				continue;
			}

			/* Open PWM device */
			snprintf(device_path, sizeof(device_path), "/dev/pwm%d", gpt_channel);
			pwm_fds[channel] = open(device_path, O_RDWR);
			if (pwm_fds[channel] < 0) {
				syslog(LOG_ERR, "Failed to open PWM device %s: %d\n",
				       device_path, errno);
				ret = -1;
				continue;
			}

			/* Configure default PWM characteristics */
			struct pwm_info_s info = {
				.frequency = pwm_rate,
				.duty = 0 /* Start disarmed */
			};

			if (ioctl(pwm_fds[channel], PWMIOC_SETCHARACTERISTICS,
			          (unsigned long)&info) < 0) {
				syslog(LOG_ERR, "Failed to set PWM characteristics for channel %d\n",
				       channel);
				ret = -1;
			}

			syslog(LOG_INFO, "Initialized PWM channel %d (GPT%d) at %ldHz\n",
			       channel, gpt_channel, pwm_rate);
		}
	}

	return ret;
}

/**
 * De-initialize PWM servo outputs
 */
void up_pwm_servo_deinit(uint32_t channel_mask)
{
	up_pwm_servo_arm(false, channel_mask);

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if ((channel_mask & (1 << channel)) && pwm_fds[channel] >= 0) {
			close(pwm_fds[channel]);
			pwm_fds[channel] = -1;
			pwm_devices[channel] = NULL;
		}
	}
}

/**
 * Set PWM servo output value
 */
int up_pwm_servo_set(unsigned channel, uint16_t value)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || pwm_fds[channel] < 0) {
		return -1;
	}

	/* Store the raw PWM value */
	pwm_values[channel] = value;

	/* Convert PWM value (1000-2000us) to duty cycle (0-65535) */
	/* PWM period = 1000000/frequency microseconds */
	/* Duty cycle = (pulse_width_us * 65536) / period_us */
	uint32_t period_us = 1000000 / pwm_rate;
	uint32_t pulse_us = value; /* Value is already in microseconds */
	uint32_t duty = (uint64_t)pulse_us * 65536 / period_us;

	/* Clamp duty cycle */
	if (duty > 65535) duty = 65535;

	struct pwm_info_s info = {
		.frequency = pwm_rate,
		.duty = duty
	};

	if (ioctl(pwm_fds[channel], PWMIOC_SETCHARACTERISTICS,
	          (unsigned long)&info) < 0) {
		return -1;
	}

	/* Start PWM if armed */
	if (pwm_armed) {
		if (ioctl(pwm_fds[channel], PWMIOC_START, 0) < 0) {
			return -1;
		}
	}

	return 0;
}

/**
 * Get PWM servo output value
 */
uint16_t up_pwm_servo_get(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return 0;
	}

	return pwm_values[channel];
}

/**
 * Set PWM servo update rate for a group
 */
int up_pwm_servo_set_rate_group_update(unsigned group, unsigned rate)
{
	/* For RA8E1, we don't have groups - update all channels */
	pwm_rate = rate;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (pwm_fds[channel] >= 0) {
			struct pwm_info_s info = {
				.frequency = rate,
				.duty = 0 /* Will be updated by up_pwm_servo_set */
			};

			if (ioctl(pwm_fds[channel], PWMIOC_SETCHARACTERISTICS,
			          (unsigned long)&info) < 0) {
				return -1;
			}

			/* Reapply current PWM value with new frequency */
			up_pwm_servo_set(channel, pwm_values[channel]);
		}
	}

	return 0;
}

/**
 * Set PWM servo update rate
 */
int up_pwm_servo_set_rate(unsigned rate)
{
	return up_pwm_servo_set_rate_group_update(0, rate);
}

/**
 * Get PWM servo update rate for a group
 */
uint32_t up_pwm_servo_get_rate_group(unsigned group)
{
	return pwm_rate;
}

/**
 * Arm or disarm PWM servo outputs
 */
void up_pwm_servo_arm(bool armed, uint32_t channel_mask)
{
	pwm_armed = armed;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if ((channel_mask & (1 << channel)) && pwm_fds[channel] >= 0) {
			if (armed) {
				/* Start PWM output */
				ioctl(pwm_fds[channel], PWMIOC_START, 0);
			} else {
				/* Stop PWM output */
				ioctl(pwm_fds[channel], PWMIOC_STOP, 0);
			}
		}
	}
}

/**
 * Get the servo arm state
 */
bool up_pwm_servo_get_arm_status(void)
{
	return pwm_armed;
}

/**
 * Convert a timer and channel pair to a PWM output
 */
int io_timer_channel_get_as_pwm_input(unsigned channel)
{
	if (channel < MAX_TIMER_IO_CHANNELS) {
		return channel;
	}
	return -1;
}

/**
 * Get timer information
 */
int io_timer_get_channel_count(void)
{
	return MAX_TIMER_IO_CHANNELS;
}

/**
 * Validate timer configuration
 */
int io_timer_validate_channel_index(unsigned channel)
{
	return (channel < MAX_TIMER_IO_CHANNELS) ? 0 : -EINVAL;
}

/**
 * Get timer mode for a channel
 */
int io_timer_get_mode_channels(io_timer_channel_mode_t mode)
{
	/* For basic PWM implementation, return all channels for PWM mode */
	if (mode == IOTimerChanMode_PWMOut) {
		return (1 << MAX_TIMER_IO_CHANNELS) - 1;
	}
	return 0;
}

/**
 * Free a timer channel
 */
int io_timer_free_channel(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	if (pwm_fds[channel] >= 0) {
		close(pwm_fds[channel]);
		pwm_fds[channel] = -1;
		pwm_devices[channel] = NULL;
	}

	return 0;
}

/**
 * Allocate a timer channel for PWM output
 */
int io_timer_allocate_channel(unsigned channel, io_timer_channel_mode_t mode)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	if (mode != IOTimerChanMode_PWMOut) {
		return -EINVAL; /* Only PWM output supported for now */
	}

	/* Channel allocation is handled by up_pwm_servo_init */
	return 0;
}
