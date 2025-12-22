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
 * @file io_timer_hal_bridge.c
 *
 * NuttX PWM HAL Bridge for PX4 io_timer
 *
 * This module provides a bridge between PX4's io_timer interface and NuttX's
 * PWM device driver interface (/dev/pwmN). It replaces direct register access
 * with proper HAL usage.
 *
 * Benefits of using NuttX HAL:
 *  - Buffer enable for glitch-free duty cycle updates
 *  - Atomic register updates with hardware double buffering
 *  - Proper error handling and validation
 *  - State management by driver
 *  - Interrupt handling abstraction
 *
 * Motor Mapping:
 *  - Motor 1: /dev/pwm0 (GPT3 Channel A / P300)
 *  - Motor 2: /dev/pwm1 (GPT0 Channel A / P415)
 *  - Motor 3: /dev/pwm2 (GPT2 Channel A / P113)
 *  - Motor 4: /dev/pwm3 (GPT4 Channel A / P302)
 */

#include <nuttx/config.h>

#include <sys/types.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include <debug.h>

#include <nuttx/timers/pwm.h>

#include "../include/px4_arch/io_timer.h"
#include <board_config.h>

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

#define PWM_DEVICE_COUNT        4
#define PWM_DEFAULT_FREQ_HZ     400
#define PWM_MIN_PULSE_US        1000
#define PWM_MAX_PULSE_US        2000
#define PWM_DEFAULT_PULSE_US    1500

/****************************************************************************
 * Private Types
 ****************************************************************************/

typedef struct {
	int fd;                      /* File descriptor for /dev/pwmN */
	uint32_t frequency_hz;       /* Current PWM frequency */
	uint16_t pulse_us;           /* Current pulse width in microseconds */
	bool initialized;            /* Device initialized flag */
	bool started;                /* PWM output started flag */
} pwm_device_state_t;

/****************************************************************************
 * Private Data
 ****************************************************************************/

static pwm_device_state_t pwm_devices[PWM_DEVICE_COUNT];

/****************************************************************************
 * Private Functions
 ****************************************************************************/

/**
 * Open a PWM device
 */
static int pwm_device_open(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd > 0) {
		return 0;  /* Already open */
	}

	char devpath[16];
	snprintf(devpath, sizeof(devpath), "/dev/pwm%u", channel);

	dev->fd = open(devpath, O_RDWR);

	if (dev->fd < 0) {
		pwmerr("ERROR: Failed to open %s: %d\n", devpath, errno);
		return -errno;
	}

	pwminfo("Opened %s (fd=%d)\n", devpath, dev->fd);
	return 0;
}

/**
 * Close a PWM device
 */
static void pwm_device_close(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd > 0) {
		close(dev->fd);
		dev->fd = -1;
		dev->initialized = false;
		dev->started = false;
	}
}

/**
 * Configure PWM frequency and pulse width
 */
static int pwm_device_configure(unsigned channel, uint32_t frequency_hz, uint16_t pulse_us)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd < 0) {
		return -EBADF;
	}

	struct pwm_info_s info;
	memset(&info, 0, sizeof(info));

	info.frequency = frequency_hz;

	/* Convert pulse width (microseconds) to duty cycle (16-bit) */
	uint32_t period_us = (1000000 + frequency_hz / 2) / frequency_hz;
	info.duty = (uint16_t)(((uint32_t)pulse_us * 65536UL) / period_us);

	int ret = ioctl(dev->fd, PWMIOC_SETCHARACTERISTICS, (unsigned long)&info);

	if (ret < 0) {
		pwmerr("ERROR: PWMIOC_SETCHARACTERISTICS failed for channel %u: %d\n",
		       channel, errno);
		return -errno;
	}

	dev->frequency_hz = frequency_hz;
	dev->pulse_us = pulse_us;
	dev->initialized = true;

	pwminfo("Channel %u configured: freq=%lu Hz, pulse=%u us, duty=0x%04lx\n",
	        channel, (unsigned long)frequency_hz, pulse_us, (unsigned long)info.duty);

	return 0;
}

/**
 * Start PWM output
 */
static int pwm_device_start(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd < 0) {
		return -EBADF;
	}

	if (dev->started) {
		return 0;  /* Already started */
	}

	struct pwm_info_s info;
	memset(&info, 0, sizeof(info));

	info.frequency = dev->frequency_hz;

	uint32_t period_us = (1000000 + dev->frequency_hz / 2) / dev->frequency_hz;
	info.duty = (uint16_t)(((uint32_t)dev->pulse_us * 65536UL) / period_us);

	int ret = ioctl(dev->fd, PWMIOC_START, 0);

	if (ret < 0) {
		pwmerr("ERROR: PWMIOC_START failed for channel %u: %d\n", channel, errno);
		return -errno;
	}

	dev->started = true;
	pwminfo("Channel %u started\n", channel);

	return 0;
}

/**
 * Stop PWM output
 */
static int pwm_device_stop(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd < 0) {
		return -EBADF;
	}

	if (!dev->started) {
		return 0;  /* Already stopped */
	}

	int ret = ioctl(dev->fd, PWMIOC_STOP, 0);

	if (ret < 0) {
		pwmerr("ERROR: PWMIOC_STOP failed for channel %u: %d\n", channel, errno);
		return -errno;
	}

	dev->started = false;
	pwminfo("Channel %u stopped\n", channel);

	return 0;
}

/**
 * Update PWM pulse width
 */
static int pwm_device_set_pulse(unsigned channel, uint16_t pulse_us)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd < 0) {
		return -EBADF;
	}

	if (!dev->initialized) {
		return -EINVAL;
	}

	struct pwm_info_s info;
	memset(&info, 0, sizeof(info));

	info.frequency = dev->frequency_hz;

	uint32_t period_us = (1000000 + dev->frequency_hz / 2) / dev->frequency_hz;
	info.duty = (uint16_t)(((uint32_t)pulse_us * 65536UL) / period_us);

	int ret = ioctl(dev->fd, PWMIOC_SETCHARACTERISTICS, (unsigned long)&info);

	if (ret < 0) {
		pwmerr("ERROR: Failed to set pulse width for channel %u: %d\n",
		       channel, errno);
		return -errno;
	}

	dev->pulse_us = pulse_us;

	return 0;
}

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/**
 * Initialize PWM HAL bridge
 */
int io_timer_hal_init(void)
{
	int ret;

	/* Initialize all device states */
	memset(pwm_devices, 0, sizeof(pwm_devices));

	for (unsigned i = 0; i < PWM_DEVICE_COUNT; i++) {
		pwm_devices[i].fd = -1;
		pwm_devices[i].frequency_hz = PWM_DEFAULT_FREQ_HZ;
		pwm_devices[i].pulse_us = PWM_DEFAULT_PULSE_US;
	}

	/* Open all PWM devices */
	for (unsigned i = 0; i < PWM_DEVICE_COUNT; i++) {
		ret = pwm_device_open(i);

		if (ret < 0) {
			pwmerr("ERROR: Failed to open PWM device %u: %d\n", i, ret);

			/* Clean up already opened devices */
			for (unsigned j = 0; j < i; j++) {
				pwm_device_close(j);
			}

			return ret;
		}

		/* Configure with default parameters */
		ret = pwm_device_configure(i, PWM_DEFAULT_FREQ_HZ, PWM_DEFAULT_PULSE_US);

		if (ret < 0) {
			pwmerr("ERROR: Failed to configure PWM device %u: %d\n", i, ret);

			for (unsigned j = 0; j <= i; j++) {
				pwm_device_close(j);
			}

			return ret;
		}
	}

	pwminfo("PWM HAL bridge initialized successfully\n");
	return 0;
}

/**
 * Set PWM frequency for a channel
 */
int io_timer_hal_set_rate(unsigned channel, unsigned frequency_hz)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	/* Reconfigure with new frequency, keeping current pulse width */
	return pwm_device_configure(channel, frequency_hz, dev->pulse_us);
}

/**
 * Set PWM pulse width (duty cycle)
 */
int io_timer_hal_set_ccr(unsigned channel, uint16_t pulse_us)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	/* Clamp pulse width to valid range */
	if (pulse_us < PWM_MIN_PULSE_US) {
		pulse_us = PWM_MIN_PULSE_US;
	} else if (pulse_us > PWM_MAX_PULSE_US) {
		pulse_us = PWM_MAX_PULSE_US;
	}

	return pwm_device_set_pulse(channel, pulse_us);
}

/**
 * Enable PWM output
 */
int io_timer_hal_channel_enable(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	return pwm_device_start(channel);
}

/**
 * Disable PWM output
 */
int io_timer_hal_channel_disable(unsigned channel)
{
	if (channel >= PWM_DEVICE_COUNT) {
		return -EINVAL;
	}

	return pwm_device_stop(channel);
}

/**
 * Get current PWM pulse width
 */
int io_timer_hal_get_ccr(unsigned channel, uint16_t *pulse_us)
{
	if (channel >= PWM_DEVICE_COUNT || !pulse_us) {
		return -EINVAL;
	}

	pwm_device_state_t *dev = &pwm_devices[channel];

	if (dev->fd < 0 || !dev->initialized) {
		return -EINVAL;
	}

	*pulse_us = dev->pulse_us;
	return 0;
}

/**
 * Deinitialize PWM HAL bridge
 */
void io_timer_hal_deinit(void)
{
	for (unsigned i = 0; i < PWM_DEVICE_COUNT; i++) {
		pwm_device_stop(i);
		pwm_device_close(i);
	}

	pwminfo("PWM HAL bridge deinitialized\n");
}
