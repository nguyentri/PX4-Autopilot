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
 * The RZV2H GPT timers use the P4CLK source reported by the NuttX clock
 * driver.
 *
 * PWM Frequency Calculation:
 *   PWM_freq = PCLK / (prescaler * period)
 *   For 400Hz @ 200MHz: period = 200000000 / 400 = 500000 ticks
 *
 * Duty Cycle Resolution:
 *   At 400Hz with 200MHz clock: 500000 ticks per period
 *   Resolution per µs: 200 ticks (sufficient for 1µs PWM precision)
 */
/* PWM Configuration Constants */
#define PWM_DEFAULT_FREQUENCY_HZ    400      /* Default 400Hz for ESCs */
#define PWM_MIN_FREQUENCY_HZ        50       /* Minimum supported frequency */
#define PWM_MAX_FREQUENCY_HZ        500      /* Maximum supported frequency */

/* High-resolution time type */
typedef uint64_t hrt_abstime;

/* Callback function type for timer channels */
typedef void (*channel_handler_t)(void *context, uint32_t chan_index,
				  hrt_abstime isrs_time, uint32_t isrs_rcnt);

static io_timer_channel_allocation_t channel_allocations[IOTimerChanModeSize] = { 0 };
static io_timer_channel_allocation_t timer_allocations[MAX_IO_TIMERS] = { 0 };
static bool io_timer_initialized;

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
 * FSP logical GPT channels 0-7 use physical GPT0-7.  Logical channels 8-15
 * use physical GPT10-17.  RZV_GPT_LOGICAL_BASE() owns the translation.
 */
static uint32_t get_gpt_base(uint8_t timer_id)
{
	if (!RZV_GPT_LOGICAL_CHANNEL_VALID(timer_id)) {
		return 0;
	}

	return (uint32_t)RZV_GPT_LOGICAL_BASE(timer_id);
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
	return RZV_GPT_LOGICAL_UNIT_BIT(timer_id);
}

static inline uint32_t gpt_compare_offset(unsigned channel, bool buffered)
{
	if (timer_io_channels[channel].timer_channel == 1) {
		return buffered ? RZV_GPT_GTCCRC_OFFSET : RZV_GPT_GTCCRA_OFFSET;
	}

	return buffered ? RZV_GPT_GTCCRE_OFFSET : RZV_GPT_GTCCRB_OFFSET;
}

static void gpt_set_compare(uint32_t base, unsigned channel, uint32_t ticks,
			    bool buffered)
{
	uint32_t compare = UINT32_MAX;

	if (ticks > 0 && ticks < gpt_state[channel].period) {
		compare = ticks - 1u;
	}

	io_timer_putreg32(compare, base + gpt_compare_offset(channel, buffered));
}

static uint32_t gpt_duty_control(unsigned channel, uint32_t ticks, uint32_t period)
{
	uint32_t duty = GPT_GTUDDTYC_UD;
	uint32_t selected_duty = GPT_UDDTYC_DTY_REGISTER;

	if (ticks == 0) {
		selected_duty = GPT_UDDTYC_DTY_0_PERCENT;

	} else if (ticks >= period) {
		selected_duty = GPT_UDDTYC_DTY_100_PERCENT;
	}

	if (timer_io_channels[channel].timer_channel == 1) {
		duty |= selected_duty << GPT_GTUDDTYC_OADTY_SHIFT;
		duty |= GPT_UDDTYC_DTY_0_PERCENT << GPT_GTUDDTYC_OBDTY_SHIFT;

	} else {
		duty |= GPT_UDDTYC_DTY_0_PERCENT << GPT_GTUDDTYC_OADTY_SHIFT;
		duty |= selected_duty << GPT_GTUDDTYC_OBDTY_SHIFT;
	}

	return duty;
}

static void gpt_write_duty_control(uint32_t base, unsigned channel,
				   uint32_t ticks, uint32_t period,
				   bool latch_direction)
{
	uint32_t duty = gpt_duty_control(channel, ticks, period);

	if (latch_direction) {
		io_timer_putreg32(duty | GPT_GTUDDTYC_UDF,
				  base + RZV_GPT_GTUDDTYC_OFFSET);
	}

	io_timer_putreg32(duty, base + RZV_GPT_GTUDDTYC_OFFSET);
}

static bool valid_channel(unsigned channel)
{
	return channel < MAX_TIMER_IO_CHANNELS &&
	       timer_io_channels[channel].timer_index < MAX_IO_TIMERS &&
	       (timer_io_channels[channel].timer_channel == 1 ||
		timer_io_channels[channel].timer_channel == 2);
}

static bool valid_mode(io_timer_channel_mode_t mode)
{
	return mode > IOTimerChanMode_NotUsed && mode < IOTimerChanModeSize;
}

static bool analog_pwm_mode(io_timer_channel_mode_t mode)
{
	return mode == IOTimerChanMode_PWMOut || mode == IOTimerChanMode_OneShot;
}

static io_timer_channel_allocation_t valid_channel_mask(void)
{
	io_timer_channel_allocation_t mask = 0;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (valid_channel(channel)) {
			mask |= (io_timer_channel_allocation_t)1u << channel;
		}
	}

	return mask;
}

static uint32_t pulse_width_to_ticks(uint32_t pclk, uint32_t period,
				     uint16_t value)
{
	uint64_t ticks = (uint64_t)value * pclk / 1000000ULL;

	if (ticks > period) {
		ticks = period;
	}

	return (uint32_t)ticks;
}

static uint32_t gpt_output_control(unsigned channel, bool enable)
{
	if (timer_io_channels[channel].timer_channel == 1) {
		return GPT_GTIOR_GTIOA_CYCLE_END_HIGH_CMP_LOW | (enable ? GPT_GTIOR_OAE : 0);
	}

	return GPT_GTIOR_GTIOB_CYCLE_END_HIGH_CMP_LOW | (enable ? GPT_GTIOR_OBE : 0);
}

/**
 * Initialize a single GPT channel for PWM output
 */
static int rzv2h_gpt_init_channel(unsigned channel)
{
	if (!valid_channel(channel)) {
		return -EINVAL;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint8_t timer_id = io_timers[timer_idx].timer_id;
	uint32_t base = get_gpt_base(io_timers[timer_idx].timer_id);
	if (base == 0) {
		return -EINVAL;
	}

	int ret = rzv_gpt_module_start(timer_id);
	if (ret < 0) {
		return ret;
	}

	uint32_t pclk = rzv_get_gpt_clock_hz();
	if (pclk == 0) {
		rzv_gpt_module_stop(timer_id);
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

	gpt_set_compare(base, channel, 0, false);
	gpt_set_compare(base, channel, 0, true);
	io_timer_putreg32(period - 1, base + RZV_GPT_GTPBR_OFFSET);
	io_timer_putreg32(GPT_GTBER_FORCE_TRANSFER, base + RZV_GPT_GTBER_OFFSET);
	gpt_write_duty_control(base, channel, 0, period, true);

	/* Keep timer output disabled until PX4 arms/enables PWM. */
	io_timer_putreg32(gpt_output_control(channel, false), base + RZV_GPT_GTIOR_OFFSET);
	io_timer_putreg32(0, base + RZV_GPT_GTST_OFFSET);
	gpt_lock(base);

	gpt_state[channel].initialized = true;

	return 0;
}

static void rzv2h_gpt_deinit_channel(unsigned channel)
{
	if (!valid_channel(channel) || !gpt_state[channel].initialized) {
		return;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint8_t timer_id = io_timers[timer_idx].timer_id;
	uint32_t base = get_gpt_base(timer_id);

	if (base != 0) {
		gpt_unlock(base);
		gpt_write_duty_control(base, channel, 0,
				       gpt_state[channel].period, false);
		io_timer_putreg32(gpt_channel_mask(timer_id),
				  base + RZV_GPT_GTSTP_OFFSET);
		io_timer_putreg32(gpt_channel_mask(timer_id),
				  base + RZV_GPT_GTCLR_OFFSET);
		io_timer_putreg32(gpt_output_control(channel, false),
				  base + RZV_GPT_GTIOR_OFFSET);
		io_timer_putreg32(0, base + RZV_GPT_GTINTAD_OFFSET);
		io_timer_putreg32(0, base + RZV_GPT_GTST_OFFSET);
		gpt_lock(base);
	}

	(void)rzv_gpt_module_stop(timer_id);
	memset(&gpt_state[channel], 0, sizeof(gpt_state[channel]));
}

/**
 * Initialize the I/O timer system for RZV2H
 */
int io_timer_init(void)
{
	if (io_timer_initialized) {
		return 0;
	}

	/* Initialize channel allocations - all channels start as NotUsed */
	memset(channel_allocations, 0, sizeof(channel_allocations));
	memset(timer_allocations, 0, sizeof(timer_allocations));
	memset(gpt_state, 0, sizeof(gpt_state));
	channel_allocations[IOTimerChanMode_NotUsed] = valid_channel_mask();

	/* Initialize all configured GPT channels */
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (valid_channel(i)) {
			int ret = rzv2h_gpt_init_channel(i);
			if (ret != 0) {
				while (i > 0) {
					i--;
					rzv2h_gpt_deinit_channel(i);
				}

				return ret;
			}
		}
	}

	io_timer_initialized = true;
	return 0;
}

/* Validation functions */
int io_timer_validate_channel_index(unsigned channel)
{
	return valid_channel(channel) ? 0 : -EINVAL;
}

static inline int validate_timer_index(unsigned timer)
{
	return (timer < MAX_IO_TIMERS) ? 0 : -EINVAL;
}

/* Channel allocation functions */
int io_timer_allocate_timer(unsigned timer, io_timer_channel_mode_t mode)
{
	int ret = -EINVAL;
	if (validate_timer_index(timer) == 0 && valid_mode(mode)) {
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
	if (!valid_channel(channel) || !valid_mode(mode)) {
		return -EINVAL;
	}

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
	if (!valid_channel(channel)) {
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();
	io_timer_channel_allocation_t bit = 1 << channel;

	for (int i = 0; i < IOTimerChanModeSize; i++) {
		channel_allocations[i] &= ~bit;
	}

	channel_allocations[IOTimerChanMode_NotUsed] |= bit;
	px4_leave_critical_section(flags);
	return 0;
}

int io_timer_get_channel_mode(unsigned channel)
{
	if (!valid_channel(channel)) {
		return -EINVAL;
	}

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
	if (!valid_channel(channel) ||
	    rate < PWM_MIN_FREQUENCY_HZ || rate > PWM_MAX_FREQUENCY_HZ) {
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();

	int mode = io_timer_get_channel_mode(channel);
	if (!gpt_state[channel].initialized ||
	    !analog_pwm_mode((io_timer_channel_mode_t)mode)) {
		px4_leave_critical_section(flags);
		return -EPERM;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint8_t timer_id = io_timers[timer_idx].timer_id;
	uint32_t base = get_gpt_base(timer_id);
	if (base == 0) {
		px4_leave_critical_section(flags);
		return -EINVAL;
	}

	/* Calculate new period */
	uint32_t period = gpt_state[channel].pclk / rate;
	if (period == 0) {
		px4_leave_critical_section(flags);
		return -ERANGE;
	}

	gpt_unlock(base);
	gpt_state[channel].period = period;

	uint32_t ticks = pulse_width_to_ticks(gpt_state[channel].pclk, period,
					     gpt_state[channel].ccr_value);
	if (gpt_state[channel].enabled) {
		io_timer_putreg32(period - 1u, base + RZV_GPT_GTPBR_OFFSET);
		gpt_set_compare(base, channel, ticks, true);
		gpt_write_duty_control(base, channel, ticks, period, false);

	} else {
		io_timer_putreg32(gpt_channel_mask(timer_id),
				  base + RZV_GPT_GTSTP_OFFSET);
		io_timer_putreg32(period - 1u, base + RZV_GPT_GTPR_OFFSET);
		io_timer_putreg32(period - 1u, base + RZV_GPT_GTPBR_OFFSET);
		gpt_set_compare(base, channel, ticks, false);
		gpt_set_compare(base, channel, ticks, true);
		gpt_write_duty_control(base, channel, ticks, period, false);
		io_timer_putreg32(gpt_channel_mask(timer_id),
				  base + RZV_GPT_GTCLR_OFFSET);
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
	io_timer_channel_allocation_t available = valid_channel_mask();

	if (!valid_mode(mode) || !analog_pwm_mode(mode) ||
	    (masks & ~available) != 0) {
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();

	if ((channel_allocations[mode] & masks) != masks) {
		px4_leave_critical_section(flags);
		return -EINVAL;
	}

	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if ((masks & (1u << i)) != 0 &&
		    (!valid_channel(i) || !gpt_state[i].initialized ||
		     get_gpt_base(io_timers[timer_io_channels[i].timer_index].timer_id) == 0)) {
			px4_leave_critical_section(flags);
			return -EINVAL;
		}
	}

	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if ((masks & (1u << i)) == 0) {
			continue;
		}

		uint8_t timer_idx = timer_io_channels[i].timer_index;
		uint8_t timer_id = io_timers[timer_idx].timer_id;
		uint32_t base = get_gpt_base(timer_id);
		gpt_unlock(base);

		if (enable) {
			uint32_t ticks = pulse_width_to_ticks(gpt_state[i].pclk,
							     gpt_state[i].period,
							     gpt_state[i].ccr_value);
			gpt_write_duty_control(base, i, ticks,
					       gpt_state[i].period, false);
			io_timer_putreg32(gpt_channel_mask(timer_id),
					  base + RZV_GPT_GTCLR_OFFSET);
			io_timer_putreg32(gpt_output_control(i, true),
					  base + RZV_GPT_GTIOR_OFFSET);
			io_timer_putreg32(gpt_channel_mask(timer_id),
					  base + RZV_GPT_GTSTR_OFFSET);
			gpt_state[i].enabled = true;

		} else {
			gpt_state[i].ccr_value = 0;
			gpt_write_duty_control(base, i, 0,
					       gpt_state[i].period, false);
			io_timer_putreg32(gpt_channel_mask(timer_id),
					  base + RZV_GPT_GTSTP_OFFSET);
			io_timer_putreg32(gpt_channel_mask(timer_id),
					  base + RZV_GPT_GTCLR_OFFSET);
			io_timer_putreg32(gpt_output_control(i, false),
					  base + RZV_GPT_GTIOR_OFFSET);
			gpt_state[i].enabled = false;
		}

		gpt_lock(base);
	}

	px4_leave_critical_section(flags);
	return 0;
}

/**
 * Set PWM compare value (pulse width in timer ticks)
 */
int io_timer_set_ccr(unsigned channel, uint16_t value)
{
	if (!valid_channel(channel)) {
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();

	int mode = io_timer_get_channel_mode(channel);
	if (!gpt_state[channel].initialized ||
	    !analog_pwm_mode((io_timer_channel_mode_t)mode)) {
		px4_leave_critical_section(flags);
		return -EPERM;
	}

	uint8_t timer_idx = timer_io_channels[channel].timer_index;
	uint32_t base = get_gpt_base(io_timers[timer_idx].timer_id);
	if (base == 0) {
		px4_leave_critical_section(flags);
		return -EINVAL;
	}

	uint32_t ticks = pulse_width_to_ticks(gpt_state[channel].pclk,
					     gpt_state[channel].period, value);

	gpt_unlock(base);
	gpt_write_duty_control(base, channel, ticks,
			       gpt_state[channel].period, false);
	gpt_set_compare(base, channel, ticks, gpt_state[channel].enabled);
	if (!gpt_state[channel].enabled) {
		gpt_set_compare(base, channel, ticks, true);
	}
	gpt_state[channel].ccr_value = value;

	gpt_lock(base);
	px4_leave_critical_section(flags);

	return 0;
}

/**
 * Get current PWM compare value
 */
uint16_t io_timer_get_ccr(unsigned channel)
{
	if (!valid_channel(channel)) {
		return 0;
	}
	return gpt_state[channel].ccr_value;
}

/**
 * Get channel group mask for a timer
 */
uint32_t io_timer_get_group(unsigned timer)
{
	if (validate_timer_index(timer) != 0) {
		return 0;
	}

	uint32_t group = 0;
	for (unsigned i = 0; i < MAX_TIMER_IO_CHANNELS; i++) {
		if (valid_channel(i) && timer_io_channels[i].timer_index == timer) {
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
	(void)callback;
	(void)context;

	if (!valid_channel(channel) || !valid_mode(mode)) {
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
 * Set DShot mode for a timer.
 *
 * Unused on RZ/V2H: the DShot HAL (up_dshot_* in renesas/rzv/dshot/dshot.c)
 * drives the GPT compare registers directly rather than through this io_timer
 * hook, mirroring the RA8/imxrt DShot ports. Kept for io_timer.h API parity;
 * returns -ENOSYS so any unexpected caller fails loudly.
 */
int io_timer_set_dshot_mode(uint8_t timer, unsigned dshot_pwm_freq, uint8_t dma_burst_length)
{
	return -ENOSYS;
}
