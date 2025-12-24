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
 * @file dshot.c
 *
 * DShot protocol implementation for Renesas RZV2H
 * Uses GPT timers with DMAC for bit-level generation
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <syslog.h>

#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/log.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_dshot.h>

#include "dshot.h"
#include "arm_internal.h"

#ifdef CONFIG_RZV_DMAC
#include "rzv_dmac.h"
#endif

#include "hardware/rzv_gpt.h"

extern const io_timers_t io_timers[MAX_IO_TIMERS];
extern const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS];

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

#define DSHOT_MAX_CHANNELS       4
#define DSHOT_FRAME_BITS         16
#define DSHOT_THROTTLE_BITS      11
#define DSHOT_TELEMETRY_BIT      1
#define DSHOT_CHECKSUM_BITS      4

#define DSHOT150_FREQ            150000u
#define DSHOT300_FREQ            300000u
#define DSHOT600_FREQ            600000u
#define DSHOT1200_FREQ           1200000u

#define DSHOT_T0H_PERCENT        37.5f
#define DSHOT_T1H_PERCENT        75.0f

/**
 * GPT Clock Frequency
 *
 * Use the same clock definition as io_timer.c for consistency.
 * PCLKD is the peripheral clock for GPT timers on RZV2H.
 */
#ifndef CONFIG_RZV_PCLK_FREQUENCY
#define CONFIG_RZV_PCLK_FREQUENCY 120000000  /* 120MHz PCLKD for RZV2H GPT */
#endif
#define PCLKD_FREQUENCY          CONFIG_RZV_PCLK_FREQUENCY

#define BDSHOT_OFFLINE_COUNT     400

/****************************************************************************
 * Private Types
 ****************************************************************************/

typedef struct {
	uint8_t logical_channel;
	uint8_t timer_index;
	uint8_t gpt_channel;
	uint8_t timer_channel;  /* A=1, B=2 */
	int8_t  dma_channel;
	uintptr_t gpt_base;

	uint32_t bit_period_ticks;
	uint32_t t0h_ticks;
	uint32_t t1h_ticks;

	uint16_t throttle_value;
	bool telemetry_request;
	uint32_t dma_buffer[DSHOT_FRAME_BITS];

	/* BDShot telemetry */
	uint32_t erpm;
	uint32_t last_erpm_update;
	uint32_t no_response_count;
} dshot_channel_t;

/****************************************************************************
 * Private Data
 ****************************************************************************/

__attribute__((unused))
static bool g_dma_available =
#ifdef CONFIG_RZV_DMAC
	true;
#else
	false;
#endif

static bool g_bdshot_enabled = false;
static uint32_t g_active_channels = 0;
static uint32_t g_dshot_frequency = 0;
static bool g_dmac_initialized = false;

static dshot_channel_t g_channels[DSHOT_MAX_CHANNELS];

/****************************************************************************
 * Private Functions
 ****************************************************************************/

static bool dshot_map_channel(uint8_t logical_channel, dshot_channel_t *ch)
{
	if (logical_channel >= MAX_TIMER_IO_CHANNELS) {
		return false;
	}

	const timer_io_channels_t *timer_channel = &timer_io_channels[logical_channel];
	const io_timers_t *timer = &io_timers[timer_channel->timer_index];

	ch->logical_channel = logical_channel;
	ch->timer_index = timer_channel->timer_index;
	ch->gpt_channel = timer->timer_id;
	ch->timer_channel = timer_channel->timer_channel;
	ch->dma_channel = timer_channel->dshot.dma_channel;
	ch->gpt_base = timer->base;

	return true;
}

static inline void gpt_putreg32(uint8_t ch, uint32_t offset, uint32_t val)
{
	uintptr_t base = RZV_GPT0_BASE + (ch * 0x100);
	putreg32(val, base + offset);
}

static inline uint32_t gpt_getreg32(uint8_t ch, uint32_t offset)
{
	uintptr_t base = RZV_GPT0_BASE + (ch * 0x100);
	return getreg32(base + offset);
}

static void dshot_calculate_timing(uint32_t frequency, uint32_t *bit_period,
					   uint32_t *t0h, uint32_t *t1h)
{
	*bit_period = PCLKD_FREQUENCY / frequency;
	*t0h = (uint32_t)(*bit_period * DSHOT_T0H_PERCENT / 100.0f);
	*t1h = (uint32_t)(*bit_period * DSHOT_T1H_PERCENT / 100.0f);
}

static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry)
{
	uint16_t frame = (throttle & 0x7FF) << 5;

	if (telemetry) {
		frame |= (1 << 4);
	}

	/* Calculate CRC */
	uint16_t crc = (frame ^ (frame >> 4) ^ (frame >> 8)) & 0x0F;
	frame |= crc;

	return frame;
}

/**
 * Setup GPT channel for DShot timing
 */
static int gpt_setup_channel(uint8_t gpt_channel, uint32_t bit_period_ticks)
{
	/* Stop timer */
	gpt_putreg32(gpt_channel, RZV_GPT_GTSTR_OFFSET, 0);

	/* Set cycle period */
	gpt_putreg32(gpt_channel, RZV_GPT_GTPR_OFFSET, bit_period_ticks - 1);

	/* Configure timer control register */
	uint32_t gtcr = 0;
	gtcr |= (0 << 0);  /* MD: Saw-wave PWM mode */
	gtcr |= (0 << 16); /* TPCS: P0CLK/1 */
	gpt_putreg32(gpt_channel, RZV_GPT_GTCR_OFFSET, gtcr);

	/* Configure I/O control register for PWM output */
	uint32_t gtior = 0;
	gtior |= (0x6 << 0);  /* GTIOA: Low at cycle start, high at compare match */
	gtior |= (0x1 << 4);  /* OAE: Output enabled */
	gpt_putreg32(gpt_channel, RZV_GPT_GTIOR_OFFSET, gtior);

	/* Clear status */
	gpt_putreg32(gpt_channel, RZV_GPT_GTST_OFFSET, 0);

	return OK;
}

static void gpt_start(uint8_t gpt_channel)
{
	gpt_putreg32(gpt_channel, RZV_GPT_GTSTR_OFFSET, 1);
}

__attribute__((unused))
static void gpt_stop(uint8_t gpt_channel)
{
	gpt_putreg32(gpt_channel, RZV_GPT_GTSTP_OFFSET, 1);
}

#ifdef CONFIG_RZV_DMAC
static int dshot_dma_setup(dshot_channel_t *ch)
{
	if (ch->dma_channel < 0) {
		return -EINVAL;
	}

	int ret = rzv_dmac_channel_initialize(ch->dma_channel);
	if (ret < 0) {
		return ret;
	}

	/* Configure DMA transfer */
	struct rzv_dmac_config_s dma_config;
	memset(&dma_config, 0, sizeof(dma_config));

	dma_config.mode = RZV_DMAC_MODE_REGISTER;
	dma_config.src_size = RZV_DMAC_SIZE_4BYTE;
	dma_config.dst_size = RZV_DMAC_SIZE_4BYTE;
	dma_config.src_addr_mode = RZV_DMAC_ADDR_INCREMENT;
	dma_config.dst_addr_mode = RZV_DMAC_ADDR_FIXED;
	dma_config.trigger = RZV_DMAC_TRIGGER_HW;
	dma_config.src_addr = (uintptr_t)ch->dma_buffer;
	dma_config.dst_addr = ch->gpt_base + RZV_GPT_GTCCRA_OFFSET;
	dma_config.length = DSHOT_FRAME_BITS * sizeof(uint32_t);
	dma_config.callback = NULL;
	dma_config.user_data = NULL;

	ret = rzv_dmac_channel_configure(ch->dma_channel, &dma_config);
	return ret;
}

static void dshot_prepare_buffer(dshot_channel_t *ch)
{
	uint16_t frame = dshot_encode_frame(ch->throttle_value, ch->telemetry_request);

	for (int i = 0; i < DSHOT_FRAME_BITS; i++) {
		if (frame & (1 << (15 - i))) {
			ch->dma_buffer[i] = ch->t1h_ticks;
		} else {
			ch->dma_buffer[i] = ch->t0h_ticks;
		}
	}
}

static int dshot_dma_start(dshot_channel_t *ch)
{
	if (ch->dma_channel < 0) {
		return -EINVAL;
	}

	dshot_prepare_buffer(ch);
	return rzv_dmac_channel_start(ch->dma_channel);
}

static inline void dshot_dma_stop(dshot_channel_t *ch)
{
	if (ch->dma_channel >= 0) {
		rzv_dmac_channel_stop(ch->dma_channel);
	}
}
#endif /* CONFIG_RZV_DMAC */

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/**
 * Initialize DShot protocol
 */
int up_dshot_init(uint32_t channel_mask, unsigned dshot_pwm_freq,
		  bool enable_bidirectional_dshot)
{
	int ret = OK;

#ifndef CONFIG_RZV_DMAC
	PX4_ERR("DShot requires CONFIG_RZV_DMAC");
	return -ENODEV;
#endif

	if (g_active_channels != 0) {
		PX4_WARN("DShot already initialized");
		return -EBUSY;
	}

	switch (dshot_pwm_freq) {
	case DSHOT150_FREQ:
	case DSHOT300_FREQ:
	case DSHOT600_FREQ:
	case DSHOT1200_FREQ:
		g_dshot_frequency = dshot_pwm_freq;
		break;

	default:
		PX4_ERR("Invalid DShot frequency: %u", dshot_pwm_freq);
		return -EINVAL;
	}

	g_bdshot_enabled = enable_bidirectional_dshot;

	/* Calculate timing parameters */
	uint32_t bit_period, t0h, t1h;
	dshot_calculate_timing(g_dshot_frequency, &bit_period, &t0h, &t1h);

	/* Initialize requested channels */
	for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if (!(channel_mask & (1 << i))) {
			continue;
		}

		dshot_channel_t *ch = &g_channels[i];
		memset(ch, 0, sizeof(dshot_channel_t));

		if (!dshot_map_channel(i, ch)) {
			PX4_ERR("Failed to map channel %u", i);
			continue;
		}

		ch->bit_period_ticks = bit_period;
		ch->t0h_ticks = t0h;
		ch->t1h_ticks = t1h;

		/* Setup GPT timer */
		ret = gpt_setup_channel(ch->gpt_channel, bit_period);
		if (ret < 0) {
			PX4_ERR("GPT setup failed: %d", ret);
			continue;
		}

#ifdef CONFIG_RZV_DMAC
		/* Setup DMA */
		if (ch->dma_channel >= 0) {
			ret = dshot_dma_setup(ch);
			if (ret < 0) {
				PX4_ERR("DMA setup failed: %d", ret);
				continue;
			}
		}
#endif

		g_active_channels |= (1 << i);
	}

	if (g_active_channels == 0) {
		PX4_ERR("No channels initialized");
		return -ENXIO;
	}

	g_dmac_initialized = true;

	PX4_INFO("DShot initialized: freq=%lu Hz, channels=0x%lx, BDShot=%s",
		 (unsigned long)g_dshot_frequency, (unsigned long)g_active_channels,
		 g_bdshot_enabled ? "enabled" : "disabled");

	return OK;
}

/**
 * Set motor throttle value
 */
void dshot_motor_data_set(unsigned channel, uint16_t throttle, bool telemetry)
{
	if (channel >= DSHOT_MAX_CHANNELS) {
		return;
	}

	if (!(g_active_channels & (1 << channel))) {
		return;
	}

	dshot_channel_t *ch = &g_channels[channel];
	ch->throttle_value = throttle;
	ch->telemetry_request = telemetry;
}

/**
 * Trigger DShot output
 */
void up_dshot_trigger(void)
{
#ifdef CONFIG_RZV_DMAC
	if (!g_dmac_initialized) {
		return;
	}

	/* Start DMA transfers for all active channels */
	for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if (!(g_active_channels & (1 << i))) {
			continue;
		}

		dshot_channel_t *ch = &g_channels[i];

		/* Prepare and start DMA */
		if (dshot_dma_start(ch) == OK) {
			/* Start timer to trigger DMA */
			gpt_start(ch->gpt_channel);
		}
	}
#else
	/* Software bit-banging fallback (not optimal) */
	for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if (!(g_active_channels & (1 << i))) {
			continue;
		}

		dshot_channel_t *ch = &g_channels[i];
		uint16_t frame = dshot_encode_frame(ch->throttle_value, ch->telemetry_request);

		/* Manually set compare values */
		for (int bit = 0; bit < DSHOT_FRAME_BITS; bit++) {
			uint32_t pulse_width = (frame & (1 << (15 - bit))) ? ch->t1h_ticks : ch->t0h_ticks;
			gpt_putreg32(ch->gpt_channel, RZV_GPT_GTCCRA_OFFSET, pulse_width);
			gpt_start(ch->gpt_channel);
			up_udelay(ch->bit_period_ticks / 120);  /* Approximate delay */
			gpt_stop(ch->gpt_channel);
		}
	}
#endif
}

/**
 * Arm/disarm DShot outputs
 */
int up_dshot_arm(bool armed)
{
	if (armed) {
		for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
			if (g_active_channels & (1 << i)) {
				g_channels[i].throttle_value = DSHOT_MIN_THROTTLE;
			}
		}
	} else {
		for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
			if (g_active_channels & (1 << i)) {
				g_channels[i].throttle_value = DSHOT_DISARM_MOTOR;
			}
		}
	}

	return OK;
}

/**
 * Get number of BDShot channels with telemetry ready
 */
int up_bdshot_num_erpm_ready(void)
{
	if (!g_bdshot_enabled) {
		return 0;
	}

	int ready_count = 0;

	for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if (!(g_active_channels & (1 << i))) {
			continue;
		}

		if (g_channels[i].erpm > 0 && g_channels[i].no_response_count < BDSHOT_OFFLINE_COUNT) {
			ready_count++;
		}
	}

	return ready_count;
}

int up_bdshot_get_erpm(uint8_t channel, int *erpm)
{
	if (channel >= DSHOT_MAX_CHANNELS) {
		return -EINVAL;
	}

	if (!(g_active_channels & (1 << channel))) {
		return -EINVAL;
	}

	if (!g_bdshot_enabled) {
		return -ENOSYS;
	}

	*erpm = (int)g_channels[channel].erpm;
	return OK;
}

int up_bdshot_channel_status(uint8_t channel)
{
	if (channel >= DSHOT_MAX_CHANNELS) {
		return -EINVAL;
	}

	if (!(g_active_channels & (1 << channel))) {
		return -EINVAL;
	}

	if (!g_bdshot_enabled) {
		return -ENOSYS;
	}

	if (g_channels[channel].no_response_count >= BDSHOT_OFFLINE_COUNT) {
		return -ETIMEDOUT;
	}

	return OK;
}

void up_bdshot_status(void)
{
	if (!g_bdshot_enabled) {
		PX4_INFO("BDShot not enabled");
		return;
	}

	PX4_INFO("BDShot Status:");

	for (unsigned i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if (!(g_active_channels & (1 << i))) {
			continue;
		}

		PX4_INFO("  Ch%u: eRPM=%lu, no_resp=%lu",
			 i, (unsigned long)g_channels[i].erpm,
			 (unsigned long)g_channels[i].no_response_count);
	}
}
