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
 * Timer I/O driver for Renesas RZV2H - GPT based implementation
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <stddef.h>

/* Include board config first to get BOARD_NUM_IO_TIMERS */
#include "board_config.h"

/* Include GPT hardware definitions */
#include "hardware/rzv_gpt.h"
#include "rzv_clock.h"

/* Include timer configuration structures */
#include "../include/px4_arch/io_timer.h"

/* Include critical section support */
#include "rzv_gpio.h"
#include <px4_platform/micro_hal.h>
#include <px4_platform_common/micro_hal.h>
#include <nuttx/irq.h>

/* Define missing types and constants */
#ifndef UINT16_MAX
#define UINT16_MAX 65535
#endif

#ifndef OK
#define OK 0
#endif

/**
 * GPT Clock Configuration
 *
 * The RZV2H GPT timers use the runtime PCLK reported by the NuttX clock
 * driver. The current RZ/V2H clock table reports nominal P0CLK at 100 MHz.
 *
 * PWM Frequency Calculation:
 *   PWM_freq = PCLK / (prescaler * period)
 *   For 400Hz @ 100MHz: period = 100000000 / 400 = 250000 ticks
 *
 * Duty Cycle Resolution:
 *   At 400Hz with 100MHz clock: 250000 ticks per period
 *   Resolution per µs: 100 ticks (sufficient for 1µs PWM precision)
 */
#define GPT_INVALID_CLOCK_ID       UINT32_MAX

/* PWM Configuration Constants */
#define PWM_DEFAULT_FREQUENCY_HZ    400      /* Default 400Hz for ESCs */
#define PWM_MIN_FREQUENCY_HZ        50       /* Minimum supported frequency */
#define PWM_MAX_FREQUENCY_HZ        500      /* Maximum supported frequency */

/* High-resolution time type */
typedef uint64_t hrt_abstime;

/* Callback function type for timer channels */
typedef void (*channel_handler_t)(void *context, uint32_t chan_index,
				  hrt_abstime isrs_time, uint32_t isrs_rcnt);

/* Timer channel allocation type */
/* Array sized for all possible channel modes */
#define NUM_CHANNEL_MODES  8

static io_timer_channel_allocation_t channel_allocations[NUM_CHANNEL_MODES] = { 0 };
static io_timer_channel_allocation_t timer_allocations[MAX_IO_TIMERS] = { 0 };

/* External declarations from board timer_config.cpp */
extern const io_timers_t io_timers[];
extern const timer_io_channels_t timer_io_channels[];

/* GPT timer state tracking */
static struct {
	bool initialized;
	bool enabled;
	uint32_t pclk;        /* GPT clock in Hz */
	uint32_t period;      /* PWM period in timer ticks */
	uint16_t ccr_value;   /* Current compare value (pulse width in µs) */
} gpt_state[MAX_TIMER_IO_CHANNELS];

/**
 * Get GPT base address from timer ID
 *
 * RZV2H GPT Memory Map:
 * - GPT0-7:   0x13010000 + (channel * 0x100)
 * - GPT10-17: 0x13020000 + ((channel-10) * 0x100)
 */
static uint32_t get_gpt_base(uint8_t timer_id)
{
	switch (timer_id) {
	case 0:  return RZV_GPT0_BASE;
	case 1:  return RZV_GPT1_BASE;
	case 2:  return RZV_GPT2_BASE;
	case 3:  return RZV_GPT3_BASE;
	case 4:  return RZV_GPT4_BASE;
	case 5:  return RZV_GPT5_BASE;
	case 6:  return RZV_GPT6_BASE;
	case 7:  return RZV_GPT7_BASE;
#ifdef RZV_GPT8_BASE
	case 8:  return RZV_GPT8_BASE;
#endif
#ifdef RZV_GPT9_BASE
	case 9:  return RZV_GPT9_BASE;
#endif
	case 10: return RZV_GPT10_BASE;
	case 11: return RZV_GPT11_BASE;
	case 12: return RZV_GPT12_BASE;
	case 13: return RZV_GPT13_BASE;
	case 14: return RZV_GPT14_BASE;
	case 15: return RZV_GPT15_BASE;
	case 16: return RZV_GPT16_BASE;
	case 17: return RZV_GPT17_BASE;
	default: return 0;
	}
}

/* Helper function to write 32-bit register */
static inline void io_timer_putreg32(uint32_t val, uint32_t addr)
{
	*(volatile uint32_t *)(uintptr_t)addr = val;
}

static inline void gpt_unlock(uint32_t base)
{
	io_timer_putreg32(GPT_GTWP_UNLOCK, base + RZV_GPT_GTWP_OFFSET);
}

static inline void gpt_lock(uint32_t base)
{
	io_timer_putreg32(GPT_GTWP_LOCK, base + RZV_GPT_GTWP_OFFSET);
}

static inline uint32_t gpt_channel_mask(uint8_t timer_id)
{
	uint8_t unit_channel = timer_id >= 10 ? timer_id - 10 : timer_id;

	return RZV_GPT_UNIT_BIT(unit_channel);
}

static uint32_t get_gpt_clock_id(uint8_t timer_id)
{
	switch (timer_id) {
	case 0:  return RZV_CPG_CLK_GPT0;
	case 1:  return RZV_CPG_CLK_GPT1;
	case 2:  return RZV_CPG_CLK_GPT2;
	case 3:  return RZV_CPG_CLK_GPT3;
	case 4:  return RZV_CPG_CLK_GPT4;
	case 5:  return RZV_CPG_CLK_GPT5;
	case 6:  return RZV_CPG_CLK_GPT6;
	case 7:  return RZV_CPG_CLK_GPT7;
#ifdef RZV_CPG_CLK_GPT8
	case 8:  return RZV_CPG_CLK_GPT8;
#endif
#ifdef RZV_CPG_CLK_GPT9
	case 9:  return RZV_CPG_CLK_GPT9;
#endif
	case 10: return RZV_CPG_CLK_GPT10;
	default: return GPT_INVALID_CLOCK_ID;
	}
}

static bool is_configured_channel(unsigned channel)
{
	return channel < MAX_TIMER_IO_CHANNELS &&
	       timer_io_channels[channel].timer_index < MAX_IO_TIMERS &&
	       (timer_io_channels[channel].timer_channel == 1 ||
		timer_io_channels[channel].timer_channel == 2);
}

static uint32_t pulse_width_to_ticks(unsigned channel, uint16_t value)
{
	uint64_t ticks = (uint64_t)value * gpt_state[channel].pclk / 1000000ULL;

	if (ticks >= gpt_state[channel].period) {
		ticks = gpt_state[channel].period ? gpt_state[channel].period - 1 : 0;
	}

	return (uint32_t)ticks;
}

static uint32_t gpt_output_control(unsigned channel, bool enable)
{
	if (timer_io_channels[channel].timer_channel == 1) {
		return GPT_GTIOR_GTIOA_HIGH_CMP_LOW | (enable ? GPT_GTIOR_OAE : 0);
	}

	return GPT_GTIOR_GTIOB_HIGH_CMP_LOW | (enable ? GPT_GTIOR_OBE : 0);
}

/**
 * Initialize a single GPT channel for PWM output
 */
static int rzv2h_gpt_init_channel(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	if (!is_configured_channel(channel)) {
		return -EINVAL;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint8_t timer_id = io_timers[timer_idx].timer_id;
	uint32_t base = get_gpt_base(io_timers[timer_idx].timer_id);
	if (base == 0) {
		return -EINVAL;
	}

	uint32_t clock_id = get_gpt_clock_id(timer_id);
	if (clock_id == GPT_INVALID_CLOCK_ID) {
		return -EINVAL;
	}

	int ret = rzv_clock_enable(clock_id);
	if (ret < 0) {
		return ret;
	}

	ret = rzv_module_reset(clock_id);
	if (ret < 0) {
		return ret;
	}

	uint32_t pclk = rzv_get_pclk_frequency();
	if (pclk == 0) {
		return -EINVAL;
	}

	/* Stop timer before configuration */
	io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTSTP_OFFSET);

	/* Clear timer counter */
	io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTCLR_OFFSET);

	gpt_unlock(base);

	/* Configure GPT control register for PWM mode */
	io_timer_putreg32(GPT_GTCR_MD_SAW | ((uint32_t)GPT_TPCS_DIV1 << GPT_GTCR_TPCS_SHIFT),
			  base + RZV_GPT_GTCR_OFFSET);

	/* Configure up-count direction */
	io_timer_putreg32(GPT_GTUDDTYC_UD, base + RZV_GPT_GTUDDTYC_OFFSET);

	/* Calculate period for 400Hz (default PWM frequency)
	 * Period = PCLK / frequency
	 */
	uint32_t period = pclk / PWM_DEFAULT_FREQUENCY_HZ;
	io_timer_putreg32(period - 1, base + RZV_GPT_GTPR_OFFSET);
	gpt_state[channel].pclk = pclk;
	gpt_state[channel].period = period;

	/* Set initial duty cycle to 0 (off) */
	gpt_state[channel].ccr_value = 0;
	gpt_state[channel].enabled = false;

	if (timer_io_channels[channel].timer_channel == 1) {
		io_timer_putreg32(0, base + RZV_GPT_GTCCRA_OFFSET);
	} else {
		io_timer_putreg32(0, base + RZV_GPT_GTCCRB_OFFSET);
	}

	/* Keep timer output disabled until PX4 arms/enables PWM. */
	io_timer_putreg32(gpt_output_control(channel, false), base + RZV_GPT_GTIOR_OFFSET);
	io_timer_putreg32(0, base + RZV_GPT_GTST_OFFSET);
	gpt_lock(base);

	gpt_state[channel].initialized = true;

	return 0;
}

/**
 * Initialize the I/O timer system for RZV2H
 */
int io_timer_init(void)
{
	/* Initialize channel allocations - all channels start as NotUsed */
	channel_allocations[0] = (1 << MAX_TIMER_IO_CHANNELS) - 1;

	for (int i = 1; i < NUM_CHANNEL_MODES; i++) {
		channel_allocations[i] = 0;
	}

	/* Initialize timer state */
	memset(gpt_state, 0, sizeof(gpt_state));

	/* Initialize all configured GPT channels */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (is_configured_channel(i)) {
			int ret = rzv2h_gpt_init_channel(i);
			if (ret != 0) {
				return ret;
			}
		}
	}

	return 0;
}

/* Validation functions */
int io_timer_validate_channel_index(unsigned channel)
{
	return (channel < MAX_TIMER_IO_CHANNELS) ? 0 : -EINVAL;
}

static inline int validate_timer_index(unsigned timer)
{
	return (timer < MAX_IO_TIMERS) ? 0 : -EINVAL;
}

/* Channel allocation functions */
int io_timer_allocate_timer(unsigned timer, io_timer_channel_mode_t mode)
{
	int ret = -EINVAL;
	if (validate_timer_index(timer) == 0) {
		if (timer_allocations[timer] == IOTimerChanMode_NotUsed || timer_allocations[timer] == mode) {
			timer_allocations[timer] = mode;
			ret = 0;
		} else {
			ret = -EBUSY;
		}
	}
	return ret;
}

int io_timer_unallocate_timer(unsigned timer)
{
	int ret = -EINVAL;
	if (validate_timer_index(timer) == 0) {
		timer_allocations[timer] = IOTimerChanMode_NotUsed;
		ret = 0;
	}
	return ret;
}

int io_timer_allocate_channel(unsigned channel, io_timer_channel_mode_t mode)
{
	irqstate_t flags = px4_enter_critical_section();
	int existing_mode = io_timer_get_channel_mode(channel);
	int ret = -EBUSY;

	if (existing_mode <= IOTimerChanMode_NotUsed || existing_mode == mode) {
		io_timer_channel_allocation_t bit = 1 << channel;
		channel_allocations[IOTimerChanMode_NotUsed] &= ~bit;
		channel_allocations[mode] |= bit;
		ret = 0;
	}
	px4_leave_critical_section(flags);
	return ret;
}

int io_timer_unallocate_channel(unsigned channel)
{
	irqstate_t flags = px4_enter_critical_section();
	io_timer_channel_allocation_t bit = 1 << channel;

	for (int i = 0; i < NUM_CHANNEL_MODES; i++) {
		channel_allocations[i] &= ~bit;
	}

	channel_allocations[IOTimerChanMode_NotUsed] |= bit;
	px4_leave_critical_section(flags);
	return 0;
}

int io_timer_get_channel_mode(unsigned channel)
{
	io_timer_channel_allocation_t bit = 1 << channel;

	for (int mode = IOTimerChanModeSize - 1; mode >= 0; mode--) {
		if (channel_allocations[mode] & bit) {
			return mode;
		}
	}

	return IOTimerChanMode_NotUsed;
}

/**
 * Set PWM rate (frequency) for a channel
 */
int io_timer_set_pwm_rate(unsigned channel, unsigned rate)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized ||
	    rate < PWM_MIN_FREQUENCY_HZ || rate > PWM_MAX_FREQUENCY_HZ) {
		return -EINVAL;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint8_t timer_id = io_timers[timer_idx].timer_id;
	uint32_t base = get_gpt_base(timer_id);
	if (base == 0) {
		return -EINVAL;
	}

	/* Calculate new period */
	uint32_t period = gpt_state[channel].pclk / rate;
	if (period == 0) {
		return -ERANGE;
	}

	irqstate_t flags = px4_enter_critical_section();
	gpt_unlock(base);
	io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTSTP_OFFSET);
	io_timer_putreg32(period - 1, base + RZV_GPT_GTPR_OFFSET);
	gpt_state[channel].period = period;

	uint32_t ticks = pulse_width_to_ticks(channel, gpt_state[channel].ccr_value);
	if (timer_io_channels[channel].timer_channel == 1) {
		io_timer_putreg32(ticks, base + RZV_GPT_GTCCRA_OFFSET);
	} else {
		io_timer_putreg32(ticks, base + RZV_GPT_GTCCRB_OFFSET);
	}

	if (gpt_state[channel].enabled) {
		io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTSTR_OFFSET);
	}

	gpt_lock(base);
	px4_leave_critical_section(flags);

	return 0;
}

/**
 * Enable/disable PWM output channels
 */
int io_timer_set_enable(bool enable, io_timer_channel_mode_t mode, io_timer_channel_allocation_t masks)
{
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (masks & (1 << i)) {
			if (gpt_state[i].initialized) {
				uint8_t timer_idx = timer_io_channels[i].timer_index;
				uint8_t timer_id = io_timers[timer_idx].timer_id;
				uint32_t base = get_gpt_base(timer_id);
				if (base != 0) {
					irqstate_t flags = px4_enter_critical_section();
					gpt_unlock(base);

					if (enable) {
						io_timer_putreg32(gpt_output_control(i, true), base + RZV_GPT_GTIOR_OFFSET);
						io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTSTR_OFFSET);
						gpt_state[i].enabled = true;
					} else {
						io_timer_putreg32(gpt_channel_mask(timer_id), base + RZV_GPT_GTSTP_OFFSET);
						io_timer_putreg32(gpt_output_control(i, false), base + RZV_GPT_GTIOR_OFFSET);
						gpt_state[i].enabled = false;
					}

					gpt_lock(base);
					px4_leave_critical_section(flags);
				}
			}
		}
	}
	return 0;
}

/**
 * Set PWM compare value (pulse width in timer ticks)
 */
int io_timer_set_ccr(unsigned channel, uint16_t value)
{
	if (channel >= MAX_TIMER_IO_CHANNELS || !gpt_state[channel].initialized) {
		return -EINVAL;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint32_t base = get_gpt_base(io_timers[timer_idx].timer_id);
	if (base == 0) {
		return -EINVAL;
	}

	uint32_t ticks = pulse_width_to_ticks(channel, value);

	/* Write to appropriate compare register */
	irqstate_t flags = px4_enter_critical_section();
	gpt_unlock(base);

	if (timer_io_channels[channel].timer_channel == 1) {
		io_timer_putreg32(ticks, base + RZV_GPT_GTCCRA_OFFSET);
	} else {
		io_timer_putreg32(ticks, base + RZV_GPT_GTCCRB_OFFSET);
	}

	gpt_lock(base);
	px4_leave_critical_section(flags);
	gpt_state[channel].ccr_value = value;

	return 0;
}

/**
 * Get current PWM compare value
 */
uint16_t io_timer_get_ccr(unsigned channel)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return 0;
	}
	return gpt_state[channel].ccr_value;
}

/**
 * Get channel group mask for a timer
 */
uint32_t io_timer_get_group(unsigned timer)
{
	uint32_t group = 0;
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (timer_io_channels[i].timer_index == timer) {
			group |= (1 << i);
		}
	}
	return group;
}

/**
 * Initialize a channel with specific mode and callback
 */
int io_timer_channel_init(unsigned channel, io_timer_channel_mode_t mode,
			  void (*callback)(void *, uint32_t, uint64_t, uint32_t), void *context)
{
	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	int ret = io_timer_allocate_channel(channel, mode);
	if (ret != 0) {
		return ret;
	}

	/* Initialize the channel if not already done */
	if (!gpt_state[channel].initialized) {
		ret = rzv2h_gpt_init_channel(channel);
		if (ret != 0) {
			io_timer_unallocate_channel(channel);
			return ret;
		}
	}

	return 0;
}

/**
 * Set DShot mode for a timer (stub - DShot not yet implemented for RZV2H)
 */
int io_timer_set_dshot_mode(uint8_t timer, unsigned dshot_pwm_freq, uint8_t dma_burst_length)
{
	/* DShot requires DMA support - not yet implemented for RZV2H */
	return -ENOSYS;
}
