/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
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
 * @file io_timer.h
 *
 * RA8 timer I/O interface
 */
#include <px4_platform_common/px4_config.h>
#include <stdint.h>
#include <stdbool.h>

#include <px4_arch/dshot.h>

#pragma once

#ifndef __EXPORT
#define __EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Configuration limits for RA8 */
#ifdef BOARD_NUM_IO_TIMERS
#define MAX_IO_TIMERS			BOARD_NUM_IO_TIMERS
#else
#define MAX_IO_TIMERS			2
#endif

#ifdef DIRECT_PWM_OUTPUT_CHANNELS
#define MAX_TIMER_IO_CHANNELS	DIRECT_PWM_OUTPUT_CHANNELS
#else
#define MAX_TIMER_IO_CHANNELS	8
#endif

#define MAX_LED_TIMERS			2
#define MAX_TIMER_LED_CHANNELS	6

#define IO_TIMER_ALL_MODES_CHANNELS 0

/* Timer channel modes */
typedef enum io_timer_channel_mode_t {
	IOTimerChanMode_NotUsed = 0,
	IOTimerChanMode_PWMOut  = 1,
	IOTimerChanMode_PWMIn   = 2,
	IOTimerChanMode_Capture = 3,
	IOTimerChanMode_OneShot = 4,
	IOTimerChanMode_Trigger = 5,
	IOTimerChanMode_LED     = 7,
} io_timer_channel_mode_t;

/* Timer allocation */
typedef enum io_timer_allocation_t {
	IOTimerChanAllocMode_NotUsed = 0,
	IOTimerChanAllocMode_Dedicated = 1,
	IOTimerChanAllocMode_Shared = 2,
} io_timer_allocation_t;

/* Timer frequency base */
typedef enum timer_frequency_base_t {
	IOTimerFrequencyBasis_PWM = 0,
	IOTimerFrequencyBasis_OneShot = 1,
} timer_frequency_base_t;

/* IO timer configuration structure */
typedef struct io_timers_t {
	uint32_t	base;               /* GPT timer base address */
	uint32_t	first_channel_index;
	uint32_t	last_channel_index;
	uint32_t	vectorno;          /* IRQ vector number */
	uint8_t		timer_id;          /* GPT timer ID (0-13) */
} io_timers_t;

/* Timer channel configuration */
typedef struct timer_io_channels_t {
	uint32_t			gpio_out;      /* GPIO configuration for output */
	uint32_t			gpio_in;       /* GPIO configuration for input */
	uint8_t				timer_index;   /* Index into io_timers array */
	uint8_t				timer_channel; /* GPT channel (A or B) */
	timer_frequency_base_t	freq_basis;
	dshot_conf_t			dshot;        /* Optional DShot specific data */
} timer_io_channels_t;

/* Function declarations */
__EXPORT int io_timer_init(void);
__EXPORT int io_timer_allocate_timer(unsigned timer, io_timer_channel_mode_t mode);
__EXPORT int io_timer_unallocate_timer(unsigned timer);

__EXPORT int io_timer_allocate_channel(unsigned channel, io_timer_channel_mode_t mode);
__EXPORT int io_timer_unallocate_channel(unsigned channel);

__EXPORT int io_timer_set_rate(unsigned timer, unsigned rate);
__EXPORT int io_timer_set_enable(bool state, io_timer_channel_mode_t mode, io_timer_allocation_t allocate);
__EXPORT int io_timer_set_rate_group_update(unsigned timer, unsigned rate);

__EXPORT uint32_t io_timer_get_group(unsigned timer);
__EXPORT int io_timer_validate_channel_index(unsigned channel);
__EXPORT int io_timer_is_channel_free(unsigned channel);
__EXPORT int io_timer_free_channel(unsigned channel);

__EXPORT int io_timer_get_channel_mode(unsigned channel);
__EXPORT int io_timer_get_mode_channels(io_timer_channel_mode_t mode);
__EXPORT uint32_t io_timer_channel_get_gpio_output(unsigned channel);
__EXPORT uint32_t io_timer_channel_get_as_pwm_input(unsigned channel);

__EXPORT int io_timer_set_pwm_rate(unsigned timer, unsigned rate);
__EXPORT int io_timer_set_pwm_alt_rate(unsigned timer, unsigned rate);
__EXPORT int io_timer_set_alt_rate(unsigned timer, unsigned rate);

/* PWM output functions */
__EXPORT int io_channel_init(void);
__EXPORT void io_timer_trigger(unsigned channel_mask);

/* Timer CCR (Compare/Capture Register) functions */
__EXPORT int io_timer_set_ccr(unsigned channel, uint16_t value);
__EXPORT uint16_t io_channel_get_ccr(unsigned channel);

/* Timer channel initialization */
typedef void (*channel_handler_t)(void *context, uint32_t chan_index,
				  uint64_t isrs_time, uint32_t isrs_rcnt);
__EXPORT int io_timer_channel_init(unsigned channel, io_timer_channel_mode_t mode,
				    channel_handler_t callback, void *context);

/**
 * Synchronized timer start/stop functions for ESC PWM outputs
 *
 * These functions start/stop all initialized PWM timers simultaneously,
 * ensuring all ESC channels have perfectly aligned PWM edges.
 * This reduces electromagnetic interference (EMI) and ensures
 * consistent motor control timing.
 */
__EXPORT int gpt_start_all_synchronized(void);
__EXPORT int gpt_stop_all_synchronized(void);

/* Board-specific timer configuration - must be defined in board code */
__EXPORT extern const io_timers_t io_timers[MAX_IO_TIMERS];
__EXPORT extern const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS];

#ifdef __cplusplus
}
#endif
