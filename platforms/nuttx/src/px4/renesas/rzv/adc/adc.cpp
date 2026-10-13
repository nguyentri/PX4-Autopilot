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
 * @file adc.cpp
 *
 * RZV2H ADC driver for PX4
 *
 * Provides battery voltage/current monitoring via ADC channels
 * Based on NuttX ADC driver infrastructure
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/micro_hal.h>
#include <px4_platform_common/log.h>

#include <drivers/drv_adc.h>
#include <drivers/drv_hrt.h>

#include <sys/types.h>
#include <sys/ioctl.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <errno.h>
#include <stdio.h>

#include <arch/board/board.h>
#include <nuttx/analog/adc.h>
#include <nuttx/analog/ioctl.h>
#include <nuttx/arch.h>

#include <board_config.h>

#ifdef CONFIG_ADC

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

#define ADC_BASE_PATH          "/dev/adc"
#define ADC_MAX_CHANNELS       8
#define ADC_SAMPLE_COUNT       8
#define ADC_CONVERSION_TIMEOUT_US 1000
#define ADC_POLL_INTERVAL_US    10

/****************************************************************************
 * Private Data
 ****************************************************************************/

static int g_adc_fd = -1;
static px4_adc_msg_t g_samples[ADC_MAX_CHANNELS];
static bool g_sample_valid[ADC_MAX_CHANNELS];

int px4_arch_adc_update();

/****************************************************************************
 * Public Functions
 ****************************************************************************/

int px4_arch_adc_init(uint32_t base_address)
{
	(void)base_address;
	/* Open ADC device */
	g_adc_fd = open(ADC_BASE_PATH "0", O_RDONLY | O_NONBLOCK);

	if (g_adc_fd < 0) {
		PX4_ERR("Failed to open ADC device: %d", errno);
		return -errno;
	}

	memset(g_samples, 0, sizeof(g_samples));
	memset(g_sample_valid, 0, sizeof(g_sample_valid));

	PX4_INFO("ADC initialized on %s", ADC_BASE_PATH "0");
	return OK;
}

void px4_arch_adc_uninit(uint32_t base_address)
{
	(void)base_address;

	if (g_adc_fd >= 0) {
		close(g_adc_fd);
		g_adc_fd = -1;
	}

	memset(g_sample_valid, 0, sizeof(g_sample_valid));
}

uint32_t px4_arch_adc_sample(uint32_t base_address, unsigned channel)
{
	(void)base_address;

	if (g_adc_fd < 0 || channel >= ADC_MAX_CHANNELS) {
		return UINT32_MAX;
	}

	int ret = px4_arch_adc_update();

	if (ret < 0 && ret != -EAGAIN) {
		return UINT32_MAX;
	}

	/* Discard previous results before requesting a single scan. Opening the
	 * native ADC enables scan-end interrupts but does not start conversion.
	 */
	memset(g_sample_valid, 0, sizeof(g_sample_valid));

	if (ioctl(g_adc_fd, ANIOC_TRIGGER, 0) < 0 && errno != EBUSY) {
		return UINT32_MAX;
	}

	/* An in-flight scan may still complete after EBUSY. Never serve an old
	 * cached value if the requested channel does not arrive in this wait.
	 */
	for (unsigned elapsed = 0; elapsed < ADC_CONVERSION_TIMEOUT_US; elapsed += ADC_POLL_INTERVAL_US) {
		ret = px4_arch_adc_update();

		if (ret < 0 && ret != -EAGAIN) {
			return UINT32_MAX;
		}

		if (g_sample_valid[channel]) {
			return g_samples[channel].am_data;
		}

		up_udelay(ADC_POLL_INTERVAL_US);
	}

	memset(g_sample_valid, 0, sizeof(g_sample_valid));
	return UINT32_MAX;
}

float px4_arch_adc_reference_v()
{
	return BOARD_ADC_VREF / 1000.0f;  /* Convert mV to V */
}

uint32_t px4_arch_adc_temp_sensor_mask()
{
	/* This adapter exposes the eight external ADC channels. */
	return 0;
}

uint32_t px4_arch_adc_dn_fullcount()
{
	return (1 << ADC_RESOLUTION_BITS);  /* 2^12 = 4096 for 12-bit */
}

int px4_arch_adc_px4_to_channel(int px4_channel)
{
	/* Direct mapping for RZV2H */
	return px4_channel;
}

/* Drain available samples before serving a channel from the cache. */
int px4_arch_adc_update()
{
	if (g_adc_fd < 0) {
		return -ENODEV;
	}

	struct adc_msg_s samples[ADC_SAMPLE_COUNT];

	ssize_t nbytes = read(g_adc_fd, samples, sizeof(samples));

	if (nbytes < 0) {
		const int error = errno;

		if (error != EAGAIN) {
			PX4_ERR("ADC read failed: %d", error);
			memset(g_sample_valid, 0, sizeof(g_sample_valid));
		}

		return -error;
	}

	if (nbytes == 0) {
		return -EAGAIN;
	}

	if (nbytes % sizeof(struct adc_msg_s) != 0) {
		memset(g_sample_valid, 0, sizeof(g_sample_valid));
		return -EIO;
	}

	/* Update sample cache */
	int nsamples = nbytes / sizeof(struct adc_msg_s);

	for (int i = 0; i < nsamples; i++) {
		uint8_t chan = samples[i].am_channel;

		if (chan < ADC_MAX_CHANNELS) {
			g_samples[chan].am_channel = chan;
			g_samples[chan].am_data = samples[i].am_data;
			g_sample_valid[chan] = true;
		}
	}

	return nsamples;
}

#endif /* CONFIG_ADC */
