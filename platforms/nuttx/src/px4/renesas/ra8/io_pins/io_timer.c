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
#include "hardware/ra_memorymap.h"

/* Include timer configuration structures - this will use BOARD_NUM_IO_TIMERS for MAX_IO_TIMERS */
#include "../include/px4_arch/io_timer.h"

/* Include critical section support */
#include "ra_gpio.h"
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
extern uint16_t gpt_get_pwm_pulse(unsigned channel);
extern int gpt_set_pwm_frequency(unsigned channel, unsigned frequency_hz);
extern int gpt_oneshot_configure(unsigned channel, uint16_t pulse_us);
extern int gpt_oneshot_trigger(unsigned channel);
extern int gpt_configure_input_capture(unsigned channel, bool rising_edge, bool falling_edge);
extern uint32_t gpt_read_capture(unsigned channel);
extern int gpt_enable_interrupts(unsigned channel, bool compare_a, bool compare_b, bool overflow);
extern int gpt_disable_interrupts(unsigned channel);
extern uint32_t gpt_read_status(unsigned channel);
extern int gpt_clear_status(unsigned channel, uint32_t flags);
extern int gpt_pwm_enable(unsigned channel, bool enable);

/* Helper function to read 32-bit register */
static inline uint32_t io_timer_getreg32(uint32_t addr)
{
	return *(volatile uint32_t *)(uintptr_t)addr;
}

/* Helper function to write 32-bit register */
static inline void io_timer_putreg32(uint32_t val, uint32_t addr)
{
	*(volatile uint32_t *)(uintptr_t)addr = val;
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

	/* Return the GPIO configuration for PWM output */
	return timer_io_channels[channel].gpio_out;
}

uint32_t io_timer_channel_get_as_pwm_input(unsigned channel)
{
	if (io_timer_validate_channel_index(channel) != 0) {
		return 0;
	}

	/* Return the GPIO configuration for PWM input */
	/* Input capture not yet implemented for RA8 */
	return 0;
}

/* Timer control functions */
int io_timer_set_rate(unsigned timer, unsigned rate)
{
	if (validate_timer_index(timer) != 0) {
		return -EINVAL;
	}

	/* Validate rate is within reasonable bounds for typical PWM/oneshot */
	if (rate < 25 || rate > 2000) {
		return -EINVAL;
	}

	bool updated = false;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (timer_io_channels[channel].gpio_out == 0) {
			continue;
		}
		if (timer_io_channels[channel].timer_index == timer) {
			updated = true;
			int result = gpt_set_pwm_frequency(channel, rate);

			if (result != 0) {
				return result;
			}
		}
	}

	return updated ? 0 : -EINVAL;
}

int io_timer_set_enable(bool state, io_timer_channel_mode_t mode, io_timer_allocation_t allocate)
{
	switch (mode) {
	case IOTimerChanMode_NotUsed:
	case IOTimerChanMode_PWMOut:
	case IOTimerChanMode_OneShot:
	case IOTimerChanMode_Trigger:
		break;

	case IOTimerChanMode_PWMIn:
	case IOTimerChanMode_Capture:
	default:
		return -EINVAL;
	}

	/* Was the request for all channels in this mode? */
	io_timer_channel_allocation_t masks = allocate;

	if (masks == IO_TIMER_ALL_MODES_CHANNELS) {
		/* Yes - we provide them */
		masks = channel_allocations[mode];

	} else {
		/* No - caller provided mask */
		/* Only allow the channels in that mode to be affected */
		masks &= channel_allocations[mode];
	}

	if (masks) {
		irqstate_t flags = px4_enter_critical_section();

		/* Enable or disable each channel in the mask */
		for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
			if (masks & (1 << channel)) {
				if (state) {
					gpt_pwm_enable(channel, true);
				} else {
					gpt_pwm_enable(channel, false);
				}
			}
		}

		px4_leave_critical_section(flags);
	}

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
			/* Read actual CCR value from GPT hardware */
			value = gpt_get_pwm_pulse(channel);
		}
	}

	return value;
}

uint32_t io_timer_get_group(unsigned timer)
{
	/* Get the channel mask for this timer */
	if (validate_timer_index(timer) < 0) {
		return 0;
	}

	uint32_t channels = 0;

	for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
		if (timer_io_channels[channel].gpio_out == 0) {
			continue;
		}
		if (timer_io_channels[channel].timer_index == timer) {
			channels |= (1u << channel);
		}
	}

	return channels;
}

void io_timer_trigger(unsigned channel_mask)
{
	/* Trigger OneShot channels
	 * For RA8 GPT timers in OneShot mode:
	 * 1. Reload the counter value
	 * 2. Trigger a single pulse via GTSTR
	 */

	int mode_mask = io_timer_get_mode_channels(IOTimerChanMode_OneShot);
	io_timer_channel_allocation_t oneshots = (mode_mask < 0) ? 0 :
			(io_timer_channel_allocation_t)mode_mask;
	oneshots &= (io_timer_channel_allocation_t)channel_mask;

	if (oneshots != 0) {
		irqstate_t flags = px4_enter_critical_section();

		/* Trigger each channel in OneShot mode */
		for (unsigned channel = 0; channel < MAX_TIMER_IO_CHANNELS; channel++) {
			if (timer_io_channels[channel].gpio_out == 0) {
				continue;
			}
			if (oneshots & (1u << channel)) {
				/* Trigger GPT OneShot pulse via hardware implementation */
				gpt_oneshot_trigger(channel);
			}
		}

		px4_leave_critical_section(flags);
	}
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

	/* Determine GPIO configuration based on mode */
	uint32_t gpio = 0;

	switch (mode) {
	case IOTimerChanMode_OneShot:
	case IOTimerChanMode_PWMOut:
	case IOTimerChanMode_Trigger:
		gpio = timer_io_channels[channel].gpio_out;
		break;

	case IOTimerChanMode_PWMIn:
	case IOTimerChanMode_Capture:
		/* Input modes not yet supported */
		return -EINVAL;

	case IOTimerChanMode_NotUsed:
		/* Free the channel */
		break;

	default:
		return -EINVAL;
	}

	irqstate_t flags = px4_enter_critical_section();

	/* Get current mode */
	int previous_mode = io_timer_get_channel_mode(channel);

	/* Allocate the channel */
	int status = io_timer_allocate_channel(channel, mode);

	if (status == 0 && previous_mode == IOTimerChanMode_NotUsed) {
		/* Initialize the timer if this is the first use */
		/* The timer is already initialized by ra8_gpt_timer_init_all() in io_timer_init() */

		/* Configure GPIO if needed */
		if (gpio) {
			px4_arch_configgpio(gpio);
		}

		/* Store callback if provided */
		if (callback != NULL) {
			/* Callbacks are not yet supported on the RA8 GPT backend */
			status = -ENOTSUP;
		}
	}

	if (status != 0 && previous_mode == IOTimerChanMode_NotUsed) {
		/* Free the channel if we couldn't initialize it */
		io_timer_unallocate_channel(channel);
	}

	px4_leave_critical_section(flags);

	(void)context;

	return status;
}
