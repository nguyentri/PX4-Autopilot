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
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <errno.h>
#include <stdio.h>

#include <arch/board/board.h>
#include <nuttx/analog/adc.h>
#include <nuttx/arch.h>

#include <board_config.h>

#ifdef CONFIG_ADC

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

#define ADC_BASE_PATH          "/dev/adc"
#define ADC_MAX_CHANNELS       8
#define ADC_SAMPLE_COUNT       8

/****************************************************************************
 * Private Data
 ****************************************************************************/

static int g_adc_fd = -1;
static px4_adc_msg_t g_samples[ADC_MAX_CHANNELS];

/****************************************************************************
 * Public Functions
 ****************************************************************************/

int px4_arch_adc_init(uint32_t base_address)
{
	/* Open ADC device */
	g_adc_fd = open(ADC_BASE_PATH "0", O_RDONLY | O_NONBLOCK);

	if (g_adc_fd < 0) {
		PX4_ERR("Failed to open ADC device: %d", errno);
		return -errno;
	}

	memset(g_samples, 0, sizeof(g_samples));

	PX4_INFO("ADC initialized on %s", ADC_BASE_PATH "0");
	return OK;
}

void px4_arch_adc_uninit(uint32_t base_address)
{
	if (g_adc_fd >= 0) {
		close(g_adc_fd);
		g_adc_fd = -1;
	}
}

uint32_t px4_arch_adc_sample(unsigned channel)
{
	if (g_adc_fd < 0 || channel >= ADC_MAX_CHANNELS) {
		return 0;
	}

	return g_samples[channel].am_data;
}

float px4_arch_adc_reference_v()
{
	return BOARD_ADC_VREF / 1000.0f;  /* Convert mV to V */
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

/* Periodic update function - call from work queue or timer */
int px4_arch_adc_update()
{
	if (g_adc_fd < 0) {
		return -ENODEV;
	}

	struct adc_msg_s samples[ADC_SAMPLE_COUNT];
	ssize_t nbytes = read(g_adc_fd, samples, sizeof(samples));

	if (nbytes < 0) {
		if (errno != EAGAIN) {
			PX4_ERR("ADC read failed: %d", errno);
		}

		return -errno;
	}

	/* Update sample cache */
	int nsamples = nbytes / sizeof(struct adc_msg_s);

	for (int i = 0; i < nsamples; i++) {
		uint8_t chan = samples[i].am_channel;

		if (chan < ADC_MAX_CHANNELS) {
			g_samples[chan].am_channel = chan;
			g_samples[chan].am_data = samples[i].am_data;
		}
	}

	return nsamples;
}

#endif /* CONFIG_ADC */
