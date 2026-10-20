/****************************************************************************
 *
 *   Copyright (C) 2025-2026 PX4 Development Team. All rights reserved.
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
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF
 * THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
 * DAMAGE.
 *
 ****************************************************************************/

/**
 * @file dshot.c
 *
 * RZ/V2H DShot TX using compare-triggered edge timestamps with one GPT
 * output and one DMAC channel per motor. Bidirectional telemetry remains
 * unsupported until a bounded interrupt or capture-DMA receive path is
 * implemented.
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>

#include <nuttx/config.h>
#include <nuttx/arch.h>

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/log.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_dshot.h>

#include "dshot.h"
#include "arm_internal.h"
#include "rzv_clock.h"
#include "rzv_dmac.h"
#include "hardware/rzv_dmac.h"
#include "hardware/rzv_gpt.h"

#define DSHOT_MAX_CHANNELS        4u
#define DSHOT_FRAME_BITS          16u
#define DSHOT_DMA_WORDS           (DSHOT_FRAME_BITS * 2u)
#define DSHOT_DMA_ALIGN           64u
#define DSHOT_FRAME_TIMEOUT_US    20u

#define DSHOT150_FREQ             150000u
#define DSHOT300_FREQ             300000u
#define DSHOT600_FREQ             600000u
#define DSHOT1200_FREQ            1200000u

/* DMkSEL uses DMAC activation-source numbers, distinct from the ELC
 * interrupt event numbering.
 */

#define DSHOT_GPT_CMPA_EVENT_U0_BASE  209u
#define DSHOT_GPT_CMPB_EVENT_U0_BASE  217u
#define DSHOT_GPT_CMPA_EVENT_U1_BASE  273u
#define DSHOT_GPT_CMPB_EVENT_U1_BASE  281u

typedef struct {
	uint8_t logical_channel;
	uint8_t timer_index;
	uint8_t gpt_channel;
	bool channel_b;
	int8_t dma_channel;
	uintptr_t gpt_base;
	uint32_t active_compare_offset;
	uint32_t bit_period_ticks;
	uint32_t t0h_ticks;
	uint32_t t1h_ticks;
	uint32_t first_compare;
	uint16_t throttle_value;
	bool telemetry_request;
	uint32_t dma_buffer[DSHOT_DMA_WORDS]
	__attribute__((aligned(DSHOT_DMA_ALIGN)));
} __attribute__((aligned(DSHOT_DMA_ALIGN))) dshot_channel_t;

static dshot_channel_t g_channels[DSHOT_MAX_CHANNELS];
static uint32_t g_active_channels;
static bool g_frame_complete_logged;
static uint32_t g_allocated_channels;
static uint32_t g_gpt_channels;
static uint32_t g_dma_channels;
static uint32_t g_frame_timeout_us;
static bool g_armed;

static inline void gpt_putreg32(const dshot_channel_t *channel,
				uint32_t offset, uint32_t value)
{
	putreg32(value, channel->gpt_base + offset);
}

static inline uint32_t gpt_getreg32(const dshot_channel_t *channel,
				    uint32_t offset)
{
	return getreg32(channel->gpt_base + offset);
}

static int dshot_gpt_compare_event(uint8_t gpt_channel, bool channel_b)
{
	if (gpt_channel < 8u) {
		return (int)((channel_b ? DSHOT_GPT_CMPB_EVENT_U0_BASE :
			      DSHOT_GPT_CMPA_EVENT_U0_BASE) + gpt_channel);
	}

	if (gpt_channel < 16u) {
		return (int)((channel_b ? DSHOT_GPT_CMPB_EVENT_U1_BASE :
			      DSHOT_GPT_CMPA_EVENT_U1_BASE) + gpt_channel - 8u);
	}

	return -EINVAL;
}

static void gpt_set_selected_duty(const dshot_channel_t *channel,
				  uint32_t duty_mode)
{
	uint32_t duty = gpt_getreg32(channel, RZV_GPT_GTUDDTYC_OFFSET);
	uint32_t mask = channel->channel_b ? GPT_GTUDDTYC_OBDTY_MASK :
			GPT_GTUDDTYC_OADTY_MASK;
	uint32_t shift = channel->channel_b ? GPT_GTUDDTYC_OBDTY_SHIFT :
			 GPT_GTUDDTYC_OADTY_SHIFT;
	uint32_t force = channel->channel_b ? GPT_GTUDDTYC_OBDTYF :
			 GPT_GTUDDTYC_OADTYF;

	duty &= ~(mask | GPT_GTUDDTYC_UDF | GPT_GTUDDTYC_OADTYF |
		  GPT_GTUDDTYC_OBDTYF);
	duty |= (duty_mode << shift) & mask;

	/* Call only while stopped. Force duty to apply at the next start rather
	 * than waiting for overflow, then release both forcible settings. */

	gpt_putreg32(channel, RZV_GPT_GTUDDTYC_OFFSET,
		     duty | GPT_GTUDDTYC_UD | GPT_GTUDDTYC_UDF | force);
	gpt_putreg32(channel, RZV_GPT_GTUDDTYC_OFFSET,
		     duty | GPT_GTUDDTYC_UD);
}

static void gpt_force_safe_low(const dshot_channel_t *channel)
{
	uint32_t mask = RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel);
	uint32_t gtior;

	gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
	gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);
	gtior &= channel->channel_b ? ~(GPT_GTIOR_OBHLD | GPT_GTIOR_OBDFLT) :
		 ~(GPT_GTIOR_OAHLD | GPT_GTIOR_OADFLT);
	gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
	gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET, mask);
	gpt_putreg32(channel, RZV_GPT_GTINTAD_OFFSET, 0);

	/* Stop drives the selected output low before disabling it. Leave WP open
	 * until DMAC is disabled; an in-flight compare write must not be blocked. */

	gtior &= channel->channel_b ? ~GPT_GTIOR_OBE : ~GPT_GTIOR_OAE;
	gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
}

static void gpt_setup_channel(const dshot_channel_t *channel)
{
	uint32_t mask = RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel);
	uint32_t gtior;

	gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
	gpt_putreg32(channel, RZV_GPT_GTPSR_OFFSET, GPT_GTPSR_CSTOP);
	gpt_putreg32(channel, RZV_GPT_GTCSR_OFFSET, GPT_GTCSR_CCLR);
	gpt_putreg32(channel, RZV_GPT_GTSSR_OFFSET, GPT_GTSSR_CSTRT);
	gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET, mask);
	gpt_putreg32(channel, RZV_GPT_GTCLR_OFFSET, mask);
	gpt_putreg32(channel, RZV_GPT_GTUPSR_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTDNSR_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTCR_OFFSET,
		     GPT_GTCR_MD_SAW | (GPT_TPCS_DIV1 << GPT_GTCR_TPCS_SHIFT));
	gpt_putreg32(channel, RZV_GPT_GTPR_OFFSET,
		     (DSHOT_FRAME_BITS + 2u) * channel->bit_period_ticks - 1u);

	gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);

	if (channel->channel_b) {
		gtior &= ~(GPT_GTIOR_GTIOB_MASK | GPT_GTIOR_OBE |
			   GPT_GTIOR_OBHLD | GPT_GTIOR_OBDFLT);
		gtior |= GPT_GTIOR_GTIOB_CYCLE_END_LOW_CMP_TOGGLE;

	} else {
		gtior &= ~(GPT_GTIOR_GTIOA_MASK | GPT_GTIOR_OAE |
			   GPT_GTIOR_OAHLD | GPT_GTIOR_OADFLT);
		gtior |= GPT_GTIOR_GTIOA_CYCLE_END_LOW_CMP_TOGGLE;
	}

	gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
	gpt_putreg32(channel, RZV_GPT_GTICASR_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTICBSR_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTBER_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTDTCR_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTITC_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTEITC_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTINTAD_OFFSET, 0);
	gpt_putreg32(channel, channel->active_compare_offset, UINT32_MAX);
	gpt_set_selected_duty(channel, GPT_UDDTYC_DTY_REGISTER);
	gpt_putreg32(channel, RZV_GPT_GTST_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
}

static void gpt_prime_frame(const dshot_channel_t *channel)
{
	uint32_t gtior;

	gpt_putreg32(channel, RZV_GPT_GTWP_OFFSET, GPT_GTWP_UNLOCK);
	gpt_putreg32(channel, RZV_GPT_GTSTP_OFFSET,
		     RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
	gpt_putreg32(channel, RZV_GPT_GTCLR_OFFSET,
		     RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
	gpt_putreg32(channel, channel->active_compare_offset,
		     channel->first_compare);
	gpt_set_selected_duty(channel, GPT_UDDTYC_DTY_REGISTER);
	gpt_putreg32(channel, RZV_GPT_GTST_OFFSET, 0);
	gpt_putreg32(channel, RZV_GPT_GTINTAD_OFFSET,
		     channel->channel_b ? GPT_GTINTAD_GTINTB : GPT_GTINTAD_GTINTA);

	/* Restore output while stopped and low. DMAC updates the active compare
	 * directly, so WP must remain unlocked until the transfer is disabled. */

	gtior = gpt_getreg32(channel, RZV_GPT_GTIOR_OFFSET);
	gtior |= channel->channel_b ? GPT_GTIOR_OBE : GPT_GTIOR_OAE;
	gpt_putreg32(channel, RZV_GPT_GTIOR_OFFSET, gtior);
}

static void gpt_start(const dshot_channel_t *channel)
{
	gpt_putreg32(channel, RZV_GPT_GTSTR_OFFSET,
		     RZV_GPT_LOGICAL_UNIT_BIT(channel->gpt_channel));
}

static uint16_t dshot_encode_frame(uint16_t throttle, bool telemetry)
{
	uint16_t payload = (uint16_t)(((throttle & 0x7ffu) << 1) |
				      (telemetry ? 1u : 0u));
	uint16_t checksum = (uint16_t)((payload ^ (payload >> 4) ^
					(payload >> 8)) & 0x0fu);

	return (uint16_t)((payload << 4) | checksum);
}

static void dshot_prepare_frame(dshot_channel_t *channel)
{
	uint16_t frame = dshot_encode_frame(channel->throttle_value,
					    channel->telemetry_request);
	unsigned int i;

	/* Prime the first rising edge after a low preamble. Each compare toggles
	 * the pin and activates one DMA word containing the next absolute edge.
	 * The final falling edge loads an unreachable compare, so delayed cleanup
	 * and counter wrap cannot create a tail pulse. */

	channel->first_compare = channel->bit_period_ticks;

	for (i = 0; i < DSHOT_FRAME_BITS; i++) {
		uint32_t rising = (i + 1u) * channel->bit_period_ticks;
		uint32_t high_ticks = (frame & (1u << (15u - i))) != 0u ?
				      channel->t1h_ticks : channel->t0h_ticks;

		channel->dma_buffer[2u * i] = rising + high_ticks;
		channel->dma_buffer[2u * i + 1u] =
			i + 1u < DSHOT_FRAME_BITS ? rising + channel->bit_period_ticks :
			UINT32_MAX;
	}
}

static int dshot_map_channel(unsigned int logical_channel,
			     dshot_channel_t *channel)
{
	const timer_io_channels_t *timer_channel;
	const io_timers_t *timer;

	if (logical_channel >= MAX_TIMER_IO_CHANNELS || channel == NULL) {
		return -EINVAL;
	}

	timer_channel = &timer_io_channels[logical_channel];

	if (timer_channel->timer_index >= MAX_IO_TIMERS ||
	    (timer_channel->timer_channel != 1u &&
	     timer_channel->timer_channel != 2u)) {
		return -EINVAL;
	}

	timer = &io_timers[timer_channel->timer_index];

	if (!RZV_GPT_LOGICAL_CHANNEL_VALID(timer->timer_id) ||
	    timer_channel->dshot.timer != timer->timer_id ||
	    timer_channel->dshot.channel != timer_channel->timer_channel - 1u ||
	    timer_channel->dshot.dma_channel < 0 ||
	    timer_channel->dshot.dma_channel >= RZV_DMAC_CHANNEL_COUNT) {
		return -EINVAL;
	}

	memset(channel, 0, sizeof(*channel));
	channel->logical_channel = (uint8_t)logical_channel;
	channel->timer_index = timer_channel->timer_index;
	channel->gpt_channel = (uint8_t)timer->timer_id;
	channel->channel_b = timer_channel->timer_channel == 2u;
	channel->dma_channel = timer_channel->dshot.dma_channel;
	channel->gpt_base = RZV_GPT_LOGICAL_BASE(timer->timer_id);
	channel->active_compare_offset = channel->channel_b ?
					 RZV_GPT_GTCCRB_OFFSET :
					 RZV_GPT_GTCCRA_OFFSET;
	return dshot_gpt_compare_event(channel->gpt_channel,
				       channel->channel_b) < 0 ? -EINVAL : OK;
}

static int dshot_dma_setup(dshot_channel_t *channel)
{
	struct rzv_dmac_config_s config;

	memset(&config, 0, sizeof(config));
	config.src_size = RZV_DMAC_SIZE_4BYTE;
	config.dst_size = RZV_DMAC_SIZE_4BYTE;
	config.src_addr_mode = RZV_DMAC_ADDR_INCREMENT;
	config.dst_addr_mode = RZV_DMAC_ADDR_FIXED;
	config.trigger = RZV_DMAC_TRIGGER_HW;
	config.src_addr = (uintptr_t)channel->dma_buffer;
	config.dst_addr = channel->gpt_base + channel->active_compare_offset;
	config.length = sizeof(channel->dma_buffer);
	config.irq_sel = dshot_gpt_compare_event(channel->gpt_channel,
			   channel->channel_b);

	return rzv_dmac_channel_configure(channel->dma_channel, &config);
}

static void dshot_stop_outputs(uint32_t mask)
{
	unsigned int i;

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if ((mask & (1u << i)) != 0u) {
			gpt_force_safe_low(&g_channels[i]);
		}
	}
}

static int dshot_quiesce(void)
{
	unsigned int i;
	int result = OK;

	/* Make every output inactive before any potentially lengthy DMA poll. */

	dshot_stop_outputs(g_gpt_channels);

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		uint32_t bit = 1u << i;

		if ((g_dma_channels & bit) != 0u) {
			int ret = rzv_dmac_channel_disable(g_channels[i].dma_channel);

			if (ret < 0) {
				if (result == OK) {
					result = ret;
				}

				/* Preserve the buffer and writable destination until a later
				 * disable or cleanup succeeds. Never rearm after this error. */

				g_armed = false;
				continue;
			}
		}

		if ((g_gpt_channels & bit) != 0u) {
			gpt_putreg32(&g_channels[i], RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
		}
	}

	return result;
}

static int dshot_cleanup(uint32_t allocated_mask, uint32_t gpt_mask,
			 uint32_t dma_mask)
{
	uint32_t retained = 0;
	unsigned int i;
	int result = OK;

	dshot_stop_outputs(gpt_mask);

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		uint32_t bit = 1u << i;

		if ((dma_mask & bit) != 0u) {
			/* Disable retains configuration on failure. Stop releases it,
			 * so call stop only after the transfer is known to be idle. */

			int ret = rzv_dmac_channel_disable(g_channels[i].dma_channel);

			if (ret < 0) {
				if (result == OK) {
					result = ret;
				}

				retained |= bit;
				continue;
			}

			ret = rzv_dmac_channel_stop(g_channels[i].dma_channel);

			if (ret < 0 && result == OK) {
				/* With requests stopped and a successful disable, DMA is
				 * idle. Stop releases the owned configuration even when it
				 * reports a hardware or routing error. */

				result = ret;
			}
		}

		if ((gpt_mask & bit) != 0u) {
			gpt_putreg32(&g_channels[i], RZV_GPT_GTWP_OFFSET, GPT_GTWP_LOCK);
		}

		if ((allocated_mask & bit) != 0u) {
			io_timer_unallocate_channel(i);
		}

		if ((allocated_mask & bit) != 0u || (gpt_mask & bit) != 0u ||
		    (dma_mask & bit) != 0u) {
			memset(&g_channels[i], 0, sizeof(g_channels[i]));
		}
	}

	/* Failed release retains all resources and descriptor storage for retry.
	 * An incomplete initialization cannot be armed. */

	g_allocated_channels = allocated_mask & retained;
	g_gpt_channels = gpt_mask & retained;
	g_dma_channels = dma_mask & retained;
	g_active_channels = retained;
	g_frame_timeout_us = 0;
	g_armed = false;
	return result;
}

static int dshot_release_active(void)
{
	return dshot_cleanup(g_allocated_channels, g_gpt_channels, g_dma_channels);
}

int up_dshot_init(uint32_t channel_mask, unsigned int dshot_pwm_freq,
		  bool enable_bidirectional_dshot)
{
	uint32_t allocated_mask = 0;
	uint32_t gpt_mask = 0;
	uint32_t dma_mask = 0;
	uint32_t clock_hz;
	uint32_t bit_period;
	uint32_t t0h_ticks;
	uint32_t t1h_ticks;
	unsigned int i;
	int ret;

	if (enable_bidirectional_dshot) {
		PX4_ERR("BDShot is not supported on RZ/V2H");
		return -ENOTSUP;
	}

	if (g_active_channels != 0u) {
		if (g_armed) {
			return -EBUSY;
		}

		ret = dshot_release_active();

		if (ret < 0) {
			return ret;
		}
	}

	if (channel_mask == 0u ||
	    (channel_mask & ~((1u << DSHOT_MAX_CHANNELS) - 1u)) != 0u) {
		return -EINVAL;
	}

	if (dshot_pwm_freq != DSHOT150_FREQ && dshot_pwm_freq != DSHOT300_FREQ &&
	    dshot_pwm_freq != DSHOT600_FREQ && dshot_pwm_freq != DSHOT1200_FREQ) {
		PX4_ERR("Invalid DShot frequency: %u", dshot_pwm_freq);
		return -EINVAL;
	}

	clock_hz = rzv_get_gpt_clock_hz();
	bit_period = clock_hz / dshot_pwm_freq;
	t0h_ticks = (bit_period * 3u) / 8u;
	t1h_ticks = (bit_period * 3u) / 4u;

	if (clock_hz == 0u || bit_period < 4u || t0h_ticks == 0u ||
	    t1h_ticks == 0u ||
	    bit_period > UINT32_MAX / (DSHOT_FRAME_BITS + 2u)) {
		return -ERANGE;
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		unsigned int j;

		if ((channel_mask & (1u << i)) == 0u) {
			continue;
		}

		ret = dshot_map_channel(i, &g_channels[i]);

		if (ret < 0) {
			PX4_ERR("Invalid DShot channel %u", i);
			goto fail;
		}

		g_channels[i].bit_period_ticks = bit_period;
		g_channels[i].t0h_ticks = t0h_ticks;
		g_channels[i].t1h_ticks = t1h_ticks;

		for (j = 0; j < i; j++) {
			if ((channel_mask & (1u << j)) != 0u &&
			    (g_channels[j].gpt_channel == g_channels[i].gpt_channel ||
			     g_channels[j].dma_channel == g_channels[i].dma_channel)) {
				PX4_ERR("Duplicate DShot resource on channel %u", i);
				ret = -EINVAL;
				goto fail;
			}
		}
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		uint32_t bit = 1u << i;

		if ((channel_mask & bit) == 0u) {
			continue;
		}

		ret = io_timer_allocate_channel(i, IOTimerChanMode_Dshot);

		if (ret < 0) {
			goto fail;
		}

		allocated_mask |= bit;
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		uint32_t bit = 1u << i;

		if ((channel_mask & bit) == 0u) {
			continue;
		}

		gpt_setup_channel(&g_channels[i]);
		gpt_mask |= bit;

		ret = dshot_dma_setup(&g_channels[i]);

		if (ret < 0) {
			PX4_ERR("DShot DMA setup failed on channel %u: %d", i, ret);
			goto fail;
		}

		dma_mask |= bit;
	}

	g_active_channels = channel_mask;
	g_allocated_channels = allocated_mask;
	g_gpt_channels = gpt_mask;
	g_dma_channels = dma_mask;
	g_frame_timeout_us =
		(((DSHOT_FRAME_BITS + 2u) * 1000000u) + dshot_pwm_freq - 1u) /
		dshot_pwm_freq + DSHOT_FRAME_TIMEOUT_US;
	g_armed = false;
	PX4_INFO("DShot TX initialized: %u Hz, channels 0x%lx",
		 dshot_pwm_freq, (unsigned long)channel_mask);
	g_frame_complete_logged = false;
	return (int)channel_mask;

fail:
	dshot_cleanup(allocated_mask, gpt_mask, dma_mask);
	return ret;
}

void dshot_motor_data_set(unsigned int channel, uint16_t throttle,
			  bool telemetry)
{
	if (channel >= DSHOT_MAX_CHANNELS ||
	    (g_active_channels & (1u << channel)) == 0u) {
		return;
	}

	g_channels[channel].throttle_value = throttle;
	g_channels[channel].telemetry_request = telemetry;
}

static int dshot_wait_frame_complete(void)
{
	uint32_t elapsed_us;

	for (elapsed_us = 0; elapsed_us < g_frame_timeout_us; elapsed_us++) {
		bool all_complete = true;
		unsigned int i;

		for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
			uint32_t status;

			if ((g_active_channels & (1u << i)) == 0u) {
				continue;
			}

			status = rzv_dmac_channel_status(g_channels[i].dma_channel);

			if ((status & DMAC_CHSTAT_ER) != 0u) {
				return -EIO;
			}

			if ((status & DMAC_CHSTAT_TC) == 0u) {
				all_complete = false;
			}
		}

		if (all_complete) {
			return OK;
		}

		up_udelay(1);
	}

	return -ETIMEDOUT;
}

void up_dshot_trigger(void)
{
	unsigned int i;
	int ret;
	int stop_ret;

	if (!g_armed) {
		return;
	}

	ret = dshot_quiesce();

	if (ret < 0) {
		PX4_ERR("DShot DMA disable failed: %d", ret);
		return;
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if ((g_active_channels & (1u << i)) == 0u) {
			continue;
		}

		dshot_prepare_frame(&g_channels[i]);
		gpt_prime_frame(&g_channels[i]);
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		uint32_t bit = 1u << i;

		if ((g_active_channels & bit) == 0u) {
			continue;
		}

		ret = rzv_dmac_channel_start(g_channels[i].dma_channel);

		if (ret < 0) {
			goto fail;
		}
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if ((g_active_channels & (1u << i)) != 0u) {
			gpt_start(&g_channels[i]);
		}
	}

	ret = dshot_wait_frame_complete();

	/* TC follows the final falling edge and unreachable compare write. The
	 * pin is already low; cleanup also contains incomplete/error transfers. */

	stop_ret = dshot_quiesce();

	if (ret == OK) {
		ret = stop_ret;
	}

	if (ret < 0) {
		g_armed = false;
		PX4_ERR("DShot frame completion failed: %d", ret);

	} else if (!g_frame_complete_logged) {
		g_frame_complete_logged = true;
		PX4_INFO("DShot TX frame complete: channels 0x%lx, %u bytes each",
			 (unsigned long)g_active_channels,
			 (unsigned)sizeof(g_channels[0].dma_buffer));
	}

	return;

fail:
	g_armed = false;
	PX4_ERR("DShot frame arm failed: %d", ret);
	stop_ret = dshot_quiesce();

	if (stop_ret < 0) {
		PX4_ERR("DShot DMA disable failed: %d", stop_ret);
	}
}

int up_dshot_arm(bool armed)
{
	unsigned int i;
	int ret;

	if (g_active_channels == 0u) {
		return -ENODEV;
	}

	g_armed = false;
	ret = dshot_quiesce();

	if (ret < 0) {
		return ret;
	}

	if (armed && g_frame_timeout_us == 0u) {
		return -EIO;
	}

	for (i = 0; i < DSHOT_MAX_CHANNELS; i++) {
		if ((g_active_channels & (1u << i)) != 0u) {
			g_channels[i].throttle_value = DSHOT_DISARM_MOTOR;
			g_channels[i].telemetry_request = false;
		}
	}

	g_armed = armed;
	return OK;
}

int up_bdshot_num_erpm_ready(void)
{
	return -ENOTSUP;
}

int up_bdshot_get_erpm(uint8_t channel, int *erpm)
{
	(void)channel;
	(void)erpm;
	return -ENOTSUP;
}

int up_bdshot_channel_status(uint8_t channel)
{
	(void)channel;
	return -ENOTSUP;
}

void up_bdshot_status(void)
{
	PX4_INFO("BDShot is not supported on RZ/V2H");
}
