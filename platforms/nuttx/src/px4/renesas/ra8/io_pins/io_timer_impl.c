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
 * @file io_timer_impl.c
 *
 * GPT Timer Implementation for RA8E1 ESC Control using NuttX HAL
 *
 * This module provides GPT timer initialization and PWM control for ESC outputs
 * using NuttX Hardware Abstraction Layer instead of direct register access.
 *
 * Motor Mapping (from board_config.h):
 *  - Motor 1: P300 (GPT3 Channel A) - Channel 0
 *  - Motor 2: P415 (GPT0 Channel A) - Channel 1
 *  - Motor 3: P113 (GPT2 Channel A) - Channel 2
 *  - Motor 4: P302 (GPT4 Channel A) - Channel 3
 */

#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>

#include "../include/px4_arch/io_timer.h"

#include "ra_gpt.h"
#include "ra_mstp.h"
#include "hardware/ra_memorymap.h"
#include "arm_internal.h"

#include <board_config.h>
#include "../include/px4_arch/micro_hal.h"


/* Board configuration constants - must be included before px4_arch headers */
/* This file provides BOARD_NUM_IO_TIMERS and BOARD_PCLKD_FREQUENCY */
#ifndef BOARD_PCLKD_FREQUENCY
#define BOARD_PCLKD_FREQUENCY  120000000  /* 120MHz PCLKD clock - from board.h */
#endif

#ifndef DIRECT_PWM_OUTPUT_CHANNELS
#define DIRECT_PWM_OUTPUT_CHANNELS  4  /* 4 PWM outputs - from board_config.h */
#endif

#ifndef BOARD_NUM_IO_TIMERS
#define BOARD_NUM_IO_TIMERS  4  /* 4 timers for FPB-RA8E1 */
#endif

#ifndef PWM_DEFAULT_FREQUENCY_HZ
#define PWM_DEFAULT_FREQUENCY_HZ 400u
#endif

#define PWM_MIN_PULSE_US      1000u
#define PWM_MAX_PULSE_US      2000u
#define PWM_DEFAULT_PULSE_US  1500u

#ifndef ARRAY_SIZE
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#endif

/* External declarations from timer_config.cpp */
extern const io_timers_t io_timers[];
extern const timer_io_channels_t timer_io_channels[];

static const uint32_t kPrescalerDivisors[] = {1u, 4u, 16u, 64u, 256u, 1024u};

typedef struct {
	uint32_t base;
	uint32_t period;
	uint32_t prescaler_div;
	uint32_t frequency_hz;
	uint16_t last_pulse_us;
	uint8_t prescaler_idx;
	uint8_t timer_index;
	uint8_t gpt_channel;
	bool initialized;
	bool enabled;
} gpt_channel_state_t;

static gpt_channel_state_t gpt_state[MAX_TIMER_IO_CHANNELS];

static inline void gpt_wp_begin(uint32_t base)
{
	putreg32(GPT_GTWP_PRKEY, base + R_GPT32_GTWP_OFFSET);
}

static inline void gpt_wp_end(uint32_t base)
{
	putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP | GPT_GTWP_CMNWP, base + R_GPT32_GTWP_OFFSET);
}

static inline uint32_t gpt_base_address(uint8_t gpt_channel)
{
	return R_GPT_CH_BASE(gpt_channel);
}

static int gpt_enable_clock(uint8_t gpt_channel)
{
	uint32_t bit_mask;

	switch (gpt_channel) {
	case 0: bit_mask = R_MSTP_MSTPCRE_GPT0; break;
	case 2: bit_mask = R_MSTP_MSTPCRE_GPT2; break;
	case 3: bit_mask = R_MSTP_MSTPCRE_GPT3; break;
	case 4: bit_mask = R_MSTP_MSTPCRE_GPT4; break;
	default:
		return -EINVAL;
	}

	uint32_t reg = getreg32(R_MSTP_MSTPCRE);
	reg &= ~bit_mask;
	putreg32(reg, R_MSTP_MSTPCRE);

	return 0;
}

static int gpt_configure_gpio(uint32_t gpio_pinset)
{
	if (gpio_pinset == 0) {
		return -EINVAL;
	}

	return px4_arch_configgpio(gpio_pinset);
}

static int gpt_select_timing(unsigned frequency_hz, uint32_t *prescaler_idx, uint32_t *period_ticks)
{
	if (frequency_hz == 0u || !prescaler_idx || !period_ticks) {
		return -EINVAL;
	}

	for (uint32_t idx = 0; idx < ARRAY_SIZE(kPrescalerDivisors); idx++) {
		uint32_t divisor = kPrescalerDivisors[idx];
		uint64_t timer_clk = BOARD_PCLKD_FREQUENCY / divisor;
		uint64_t ticks = (timer_clk + (frequency_hz / 2u)) / frequency_hz;

		if (ticks == 0 || ticks > UINT32_MAX) {
			continue;
		}

		*prescaler_idx = idx;
		*period_ticks = (uint32_t)(ticks - 1u);
		return 0;
	}

	return -ERANGE;
}

static int gpt_timer_init_pwm(unsigned channel, unsigned frequency_hz)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	const timer_io_channels_t *chan_cfg = &timer_io_channels[channel];
	uint8_t timer_index = chan_cfg->timer_index;

	if (timer_index >= MAX_IO_TIMERS) {
		return -EINVAL;
	}

	uint8_t gpt_channel = io_timers[timer_index].timer_id;
	if (gpt_channel == 0xff) {
		return -EINVAL;
	}

	uint32_t prescaler_idx = 0;
	uint32_t period_ticks = 0;
	int ret = gpt_select_timing(frequency_hz, &prescaler_idx, &period_ticks);

	if (ret != 0) {
		return ret;
	}

	ret = gpt_enable_clock(gpt_channel);

	if (ret != 0) {
		return ret;
	}

	(void)gpt_configure_gpio(chan_cfg->gpio_out);

	uint32_t base = gpt_base_address(gpt_channel);
	uint32_t prescaler_div = kPrescalerDivisors[prescaler_idx];
	uint32_t timer_clk = BOARD_PCLKD_FREQUENCY / prescaler_div;
	uint64_t initial_ticks = ((uint64_t)timer_clk * PWM_DEFAULT_PULSE_US) / 1000000u;

	if (initial_ticks > period_ticks) {
		initial_ticks = period_ticks;
	}

	gpt_wp_begin(base);
	putreg32(0, base + R_GPT32_GTCR_OFFSET);
	putreg32(GPT_GTCR_MD_SAW_WAVE_UP | (prescaler_idx << GPT_GTCR_TPCS_SHIFT), base + R_GPT32_GTCR_OFFSET);
	putreg32(R_GPT_GTUDDTYC_UD, base + R_GPT32_GTUDDTYC_OFFSET);
	putreg32(GPT_GTIOR_GTIOA_INITIAL_LOW, base + R_GPT32_GTIOR_OFFSET);
	putreg32(period_ticks, base + R_GPT32_GTPR_OFFSET);
	putreg32(period_ticks, base + R_GPT32_GTPBR_OFFSET);
	putreg32((uint32_t)initial_ticks, base + R_GPT32_GTCCRA_OFFSET);
	putreg32(0, base + R_GPT32_GTCNT_OFFSET);
	putreg32(getreg32(base + R_GPT32_GTCR_OFFSET) | GPT_GTCR_CST, base + R_GPT32_GTCR_OFFSET);
	gpt_wp_end(base);

	gpt_state[channel] = (gpt_channel_state_t) {
		.base = base,
		.period = period_ticks,
		.prescaler_div = prescaler_div,
		.frequency_hz = frequency_hz,
		.last_pulse_us = PWM_DEFAULT_PULSE_US,
		.prescaler_idx = (uint8_t)prescaler_idx,
		.timer_index = timer_index,
		.gpt_channel = gpt_channel,
		.initialized = true,
		.enabled = true,
	};

	return 0;
}

int gpt_set_pwm_pulse(unsigned channel, uint16_t pulse_us)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	if (pulse_us < PWM_MIN_PULSE_US) {
		pulse_us = PWM_MIN_PULSE_US;
	} else if (pulse_us > PWM_MAX_PULSE_US) {
		pulse_us = PWM_MAX_PULSE_US;
	}

	uint32_t base = gpt_state[channel].base;
	uint32_t timer_clk = BOARD_PCLKD_FREQUENCY / gpt_state[channel].prescaler_div;
	uint64_t ticks = ((uint64_t)timer_clk * pulse_us) / 1000000u;

	if (ticks > gpt_state[channel].period) {
		ticks = gpt_state[channel].period;
	}

	gpt_wp_begin(base);
	putreg32((uint32_t)ticks, base + R_GPT32_GTCCRA_OFFSET);
	gpt_wp_end(base);

	gpt_state[channel].last_pulse_us = pulse_us;
	return 0;
}

uint16_t gpt_get_pwm_pulse(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return 0;
	}

	uint32_t ccr = getreg32(gpt_state[channel].base + R_GPT32_GTCCRA_OFFSET);
	uint32_t timer_clk = BOARD_PCLKD_FREQUENCY / gpt_state[channel].prescaler_div;

	return (uint16_t)((ccr * 1000000u) / timer_clk);
}

int gpt_pwm_enable(unsigned channel, bool enable)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t base = gpt_state[channel].base;

	gpt_wp_begin(base);
	uint32_t gtcr = getreg32(base + R_GPT32_GTCR_OFFSET);

	if (enable) {
		gtcr |= GPT_GTCR_CST;
	} else {
		gtcr &= ~GPT_GTCR_CST;
	}

	putreg32(gtcr, base + R_GPT32_GTCR_OFFSET);
	gpt_wp_end(base);

	gpt_state[channel].enabled = enable;
	return 0;
}

int gpt_set_pwm_frequency(unsigned channel, unsigned frequency_hz)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized || frequency_hz == 0u) {
		return -EINVAL;
	}

	uint32_t prescaler_idx = 0;
	uint32_t period_ticks = 0;
	int ret = gpt_select_timing(frequency_hz, &prescaler_idx, &period_ticks);

	if (ret != 0) {
		return ret;
	}

	uint32_t base = gpt_state[channel].base;
	bool was_enabled = gpt_state[channel].enabled;

	gpt_pwm_enable(channel, false);

	gpt_wp_begin(base);
	uint32_t gtcr = getreg32(base + R_GPT32_GTCR_OFFSET);
	gtcr &= ~GPT_GTCR_TPCS_MASK;
	gtcr |= (prescaler_idx << GPT_GTCR_TPCS_SHIFT);
	putreg32(gtcr, base + R_GPT32_GTCR_OFFSET);
	putreg32(period_ticks, base + R_GPT32_GTPR_OFFSET);
	putreg32(period_ticks, base + R_GPT32_GTPBR_OFFSET);
	gpt_wp_end(base);

	gpt_state[channel].prescaler_idx = (uint8_t)prescaler_idx;
	gpt_state[channel].prescaler_div = kPrescalerDivisors[prescaler_idx];
	gpt_state[channel].period = period_ticks;
	gpt_state[channel].frequency_hz = frequency_hz;

	ret = gpt_set_pwm_pulse(channel, gpt_state[channel].last_pulse_us);

	if (was_enabled) {
		gpt_pwm_enable(channel, true);
	}

	return ret;
}

int gpt_oneshot_configure(unsigned channel, uint16_t pulse_us)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t base = gpt_state[channel].base;

	gpt_pwm_enable(channel, false);

	gpt_wp_begin(base);
	uint32_t gtcr = getreg32(base + R_GPT32_GTCR_OFFSET);
	gtcr &= ~GPT_GTCR_MD_MASK;
	gtcr |= RA_GPT_TIMER_ONE_SHOT;
	putreg32(gtcr, base + R_GPT32_GTCR_OFFSET);
	gpt_wp_end(base);

	return gpt_set_pwm_pulse(channel, pulse_us);
}

int gpt_oneshot_trigger(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t base = gpt_state[channel].base;

	gpt_wp_begin(base);
	putreg32((1u << gpt_state[channel].gpt_channel), base + R_GPT32_GTCLR_OFFSET);
	gpt_wp_end(base);

	return gpt_pwm_enable(channel, true);
}

int gpt_configure_input_capture(unsigned channel, bool rising_edge, bool falling_edge)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	(void)rising_edge;
	(void)falling_edge;

	return -ENOTSUP;
}

uint32_t gpt_read_capture(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return 0;
	}

	return getreg32(gpt_state[channel].base + R_GPT32_GTCCRA_OFFSET);
}

int gpt_enable_interrupts(unsigned channel, bool compare_a, bool compare_b, bool overflow)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t mask = 0;

	if (compare_a) {
		mask |= R_GPT_GTINTAD_GTINTA;
	}

	if (compare_b) {
		mask |= R_GPT_GTINTAD_GTINTA;
	}

	if (overflow) {
		mask |= R_GPT_GTINTAD_GTINTB;
	}

	putreg32(mask, gpt_state[channel].base + R_GPT32_GTINTAD_OFFSET);
	return 0;
}

int gpt_disable_interrupts(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	putreg32(0, gpt_state[channel].base + R_GPT32_GTINTAD_OFFSET);
	return 0;
}

uint32_t gpt_read_status(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return 0;
	}

	return getreg32(gpt_state[channel].base + R_GPT32_GTST_OFFSET);
}

int gpt_clear_status(unsigned channel, uint32_t flags)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t base = gpt_state[channel].base;
	uint32_t current = getreg32(base + R_GPT32_GTST_OFFSET);
	current &= ~flags;
	putreg32(current, base + R_GPT32_GTST_OFFSET);

	return 0;
}

int ra8_gpt_timer_init_all(void)
{
	int status = 0;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (timer_io_channels[channel].gpio_out == 0) {
			continue;
		}

		if (gpt_timer_init_pwm(channel, PWM_DEFAULT_FREQUENCY_HZ) != 0) {
			status = -1;
		}
	}

	return status;
}

void ra8_gpt_timer_deinit_all(void)
{
	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (!gpt_state[channel].initialized) {
			continue;
		}

		uint32_t base = gpt_state[channel].base;

		gpt_wp_begin(base);
		putreg32(getreg32(base + R_GPT32_GTCR_OFFSET) & ~GPT_GTCR_CST, base + R_GPT32_GTCR_OFFSET);
		gpt_wp_end(base);

		gpt_state[channel].initialized = false;
		gpt_state[channel].enabled = false;
	}
}

int ra8_gpt_timer_isr(unsigned channel, void *context)
{
	//int status = 0;

	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint32_t flags = px4_enter_critical_section();

	uint32_t masks = getreg32(gpt_state[channel].base + R_GPT32_GTINTAD_OFFSET);
	if (masks != 0) {
		for (unsigned idx = 0; idx < MAX_TIMER_IO_CHANNELS; idx++) {
			if (masks & (1 << idx)) {
				if (gpt_state[idx].enabled) {
					gpt_pwm_enable(idx, false);
				}
			}
		}

		px4_leave_critical_section(flags);
	}

	return 0;
}
