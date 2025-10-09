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
 * Timer I/O driver for Renesas RA8 - GPT based implementation
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <string.h>
#include <stddef.h>

/* Include board config first to get BOARD_NUM_IO_TIMERS */
#include "board_config.h"

/* Include GPT hardware definitions */
#include <hardware/ra_gpt.h>
#include <hardware/ra8e1/ra8e1_memorymap.h>

/* Include timer configuration structures - this will use BOARD_NUM_IO_TIMERS for MAX_IO_TIMERS */
#include <px4_arch/io_timer.h>

/* Include critical section support */
#include <px4_platform_common/micro_hal.h>
#include <nuttx/irq.h>


/* Define missing types and constants */
#ifndef UINT16_MAX
#define UINT16_MAX 65535
#endif

#ifndef OK
#define OK 0
#endif

/* High-resolution time type */
typedef uint64_t hrt_abstime;

/* Callback function type for timer channels */
typedef void (*channel_handler_t)(void *context, uint32_t chan_index,
				  hrt_abstime isrs_time, uint32_t isrs_rcnt);

#ifndef MAX_TIMER_IO_CHANNELS
#define MAX_TIMER_IO_CHANNELS	8
#endif

/* Timer channel allocation type (defined here, not in header) */
typedef uint16_t io_timer_channel_allocation_t;

/* Channel allocation tracking */
/* Array sized for all possible channel modes (IOTimerChanMode_LED=7, so 8 total modes) */
#define NUM_CHANNEL_MODES  8

static io_timer_channel_allocation_t channel_allocations[NUM_CHANNEL_MODES] = { 0 };
static io_timer_channel_allocation_t timer_allocations[MAX_IO_TIMERS] = { 0 };

/* Forward declarations - these are declared in io_timer.h */
/* No need for forward declarations, header provides them */

/* External declarations from board timer_config.cpp */
extern const io_timers_t io_timers[];
extern const timer_io_channels_t timer_io_channels[];

/* External GPT hardware functions from io_timer_impl.c */
extern int ra8_gpt_timer_init_all(void);
extern void ra8_gpt_timer_deinit_all(void);
extern int gpt_set_pwm_pulse(unsigned channel, uint16_t pulse_us);
extern int gpt_set_pwm_frequency(unsigned channel, unsigned frequency_hz);

/* Helper function to read 32-bit register */
static inline uint32_t io_timer_getreg32(uint32_t addr)
{
	return *(volatile uint32_t *)addr;
}

/* Helper function to write 32-bit register */
static inline void io_timer_putreg32(uint32_t val, uint32_t addr)
{
	*(volatile uint32_t *)addr = val;
}

/**
 * Initialize the I/O timer system for RA8
 */
int io_timer_init(void)
{
	/* Initialize channel allocations - all channels start as NotUsed (mode 0) */
	/* Set all bits for NotUsed mode (mode index 0) */
	channel_allocations[0] = (1 << MAX_TIMER_IO_CHANNELS) - 1;

	/* All other modes start with no channels allocated */
	for (int i = 1; i < NUM_CHANNEL_MODES; i++) {
		channel_allocations[i] = 0;
	}

	/* Initialize GPT timers for PWM at 400Hz */
	int ret = ra8_gpt_timer_init_all();
	if (ret != 0) {
		return ret;
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
	int mode = io_timer_get_channel_mode(channel);
	if (mode > IOTimerChanMode_NotUsed) {
		io_timer_channel_allocation_t bit = 1 << channel;
		channel_allocations[mode] &= ~bit;
		channel_allocations[IOTimerChanMode_NotUsed] |= bit;
	}
	return mode;
}

int io_timer_get_channel_mode(unsigned channel)
{
	io_timer_channel_allocation_t bit = 1 << channel;
	for (int mode = IOTimerChanMode_NotUsed; mode < 8; mode++) {  /* 8 = size of channel_allocations array */
		if (bit & channel_allocations[mode]) {
			return mode;
		}
	}
	return -1;
}

int io_timer_get_mode_channels(io_timer_channel_mode_t mode)
{
	if (mode < 8) {  /* 8 = size of channel_allocations array */
		return channel_allocations[mode];
	}
	return 0;
}

/* GPIO configuration functions */
uint32_t io_timer_channel_get_gpio_output(unsigned channel)
{
	if (io_timer_validate_channel_index(channel) != 0) {
		return 0;
	}
	return 0;
}

uint32_t io_timer_channel_get_as_pwm_input(unsigned channel)
{
	if (io_timer_validate_channel_index(channel) != 0) {
		return 0;
	}
	return 0;
}

/* Timer control functions */
int io_timer_set_rate(unsigned timer, unsigned rate)
{
	if (validate_timer_index(timer) != 0) {
		return -EINVAL;
	}

	/* Validate rate is within reasonable bounds (50Hz - 400Hz for PWM) */
	if (rate < 50 || rate > 400) {
		return -EINVAL;
	}

	/* Get the channel index for this timer */
	/* Each timer in our configuration maps to one channel */
	unsigned channel = timer;  /* For FPB-RA8E1, timer index = channel index */

	if (channel >= MAX_TIMER_IO_CHANNELS) {
		return -EINVAL;
	}

	/* Update the GPT timer frequency using hardware implementation */
	return gpt_set_pwm_frequency(channel, rate);
}

int io_timer_set_enable(bool state, io_timer_channel_mode_t mode, io_timer_allocation_t allocate)
{
	(void)state;    /* Unused parameter */
	(void)mode;     /* Unused parameter */
	(void)allocate; /* Unused parameter */
	return 0;
}

int io_timer_set_ccr(unsigned channel, uint16_t value)
{
	int ret_val = io_timer_validate_channel_index(channel);
	int mode = io_timer_get_channel_mode(channel);

	if (ret_val == 0) {
		if ((mode != IOTimerChanMode_PWMOut) &&
		    (mode != IOTimerChanMode_OneShot) &&
		    (mode != IOTimerChanMode_Trigger)) {
			ret_val = -EIO;
		} else {
			/* Use GPT hardware implementation to set PWM pulse width */
			ret_val = gpt_set_pwm_pulse(channel, value);
		}
	}
	return ret_val;
}

uint16_t io_channel_get_ccr(unsigned channel)
{
	uint16_t value = 0;
	if (io_timer_validate_channel_index(channel) == 0) {
		int mode = io_timer_get_channel_mode(channel);
		if ((mode == IOTimerChanMode_PWMOut) ||
		    (mode == IOTimerChanMode_OneShot) ||
		    (mode == IOTimerChanMode_Trigger)) {
			/* TODO: Implement RA8 GPT CCR reading */
		}
	}
	return value;
}

uint32_t io_timer_get_group(unsigned timer)
{
	return 0;
}

void io_timer_trigger(unsigned channel_mask)
{
	/* TODO: Implement RA8 GPT triggering for OneShot mode */
	(void)channel_mask; /* Unused parameter */
}

/* Additional required functions */
int io_timer_is_channel_free(unsigned channel)
{
	return io_timer_get_channel_mode(channel) == IOTimerChanMode_NotUsed ? 1 : 0;
}

int io_timer_free_channel(unsigned channel)
{
	return io_timer_unallocate_channel(channel);
}

int io_timer_set_pwm_rate(unsigned timer, unsigned rate)
{
	return io_timer_set_rate(timer, rate);
}

int io_timer_set_pwm_alt_rate(unsigned timer, unsigned rate)
{
	return io_timer_set_rate(timer, rate);
}

int io_timer_set_alt_rate(unsigned timer, unsigned rate)
{
	return io_timer_set_rate(timer, rate);
}

int io_timer_set_rate_group_update(unsigned timer, unsigned rate)
{
	return io_timer_set_rate(timer, rate);
}

int io_channel_init(void)
{
	return io_timer_init();
}

/* Stub for compatibility */
void ra8_io_timer_stub(void)
{
	/* Stub function to allow compilation */
}

/**
 * Initialize a timer channel
 *
 * @param channel Channel number (0-7)
 * @param mode    Channel mode (PWMOut, Capture, etc.)
 * @param callback Optional callback function
 * @param context Optional callback context
 * @return        OK on success, negative errno on failure
 */
int io_timer_channel_init(unsigned channel, io_timer_channel_mode_t mode,
			   channel_handler_t callback, void *context)
{
	if (io_timer_validate_channel_index(channel) < 0) {
		return -EINVAL;
	}

	/* Check if channel is already allocated for a different mode */
	int current_mode = io_timer_get_channel_mode(channel);

	if (current_mode > IOTimerChanMode_NotUsed && current_mode != mode) {
		return -EBUSY;
	}

	/* For NotUsed mode, just free the channel */
	if (mode == IOTimerChanMode_NotUsed) {
		return io_timer_unallocate_channel(channel);
	}

	/* Allocate the channel for the requested mode */
	int ret = io_timer_allocate_channel(channel, mode);

	if (ret != 0) {
		return ret;
	}

	/* TODO: Configure hardware timer channel based on mode */
	/* This would involve:
	 * 1. Determine which timer this channel belongs to
	 * 2. Enable timer clock if not already enabled
	 * 3. Configure timer mode (PWM, capture, etc.)
	 * 4. Configure GPIO pin for timer function
	 * 5. Set up interrupt if callback provided
	 */

	(void)callback;  /* Unused for now */
	(void)context;   /* Unused for now */

	return OK;
}
