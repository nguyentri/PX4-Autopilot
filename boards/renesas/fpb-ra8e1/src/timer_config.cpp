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
 * @file timer_config.cpp
 *
 * Timer configuration for RA8E1 board
 */

#include <stdint.h>

// Forward declarations
extern "C" int io_timer_init();
extern "C" void hrt_init(void);

// Board-specific timer configuration for RA8E1
// This provides the timer configuration that the io_timer.c expects
extern "C" {

// Configuration limits for RA8E1 board
#ifndef MAX_IO_TIMERS
#define MAX_IO_TIMERS			2
#endif

#ifndef MAX_TIMER_IO_CHANNELS
#define MAX_TIMER_IO_CHANNELS	8
#endif

// Timer structure definition (matches io_timer.c)
typedef struct io_timers_t {
	uint32_t	base;
	uint32_t	first_channel_index;
	uint32_t	last_channel_index;
	uint32_t	vectorno;
} io_timers_t;

// Timer I/O channel configuration
typedef struct timer_io_channels_t {
	uint32_t			gpio_out;
	uint32_t			gpio_in;
	uint8_t				timer_index;
	uint8_t				timer_channel;
	uint8_t				freq_basis;
} timer_io_channels_t;

// RA8E1 board timer configuration
// For now, these are placeholder configurations
// In a full implementation, these would map to actual RA8 GPT timers
const io_timers_t io_timers[MAX_IO_TIMERS] = {
	{
		.base = 0x40169000,         // GPT0 base address (example)
		.first_channel_index = 0,
		.last_channel_index = 3,
		.vectorno = 0,              // IRQ vector (to be determined)
	},
	{
		.base = 0x4016A000,         // GPT1 base address (example)
		.first_channel_index = 4,
		.last_channel_index = 7,
		.vectorno = 0,              // IRQ vector (to be determined)
	}
};

// Timer channel mappings for RA8E1
// These would normally map to actual GPIO pins and their timer functions
const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
	// Timer 0 channels
	{
		.gpio_out = 0,              // GPIO configuration (to be defined)
		.gpio_in = 0,
		.timer_index = 0,
		.timer_channel = 0,         // GPT channel A
		.freq_basis = 0,            // PWM frequency basis
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 0,
		.timer_channel = 1,         // GPT channel B
		.freq_basis = 0,
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 0,
		.timer_channel = 2,         // GPT channel C
		.freq_basis = 0,
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 0,
		.timer_channel = 3,         // GPT channel D
		.freq_basis = 0,
	},
	// Timer 1 channels
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 1,
		.timer_channel = 0,
		.freq_basis = 0,
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 1,
		.timer_channel = 1,
		.freq_basis = 0,
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 1,
		.timer_channel = 2,
		.freq_basis = 0,
	},
	{
		.gpio_out = 0,
		.gpio_in = 0,
		.timer_index = 1,
		.timer_channel = 3,
		.freq_basis = 0,
	}
};

// Main initialization function
void fpb_ra8e1_timer_initialize()
{
	// Initialize HRT system first (needed for px4_usleep and timing)
	hrt_init();

	// Initialize IO timer system for RA8E1
	// This calls the io_timer_init() function in io_timer.c
	io_timer_init();
}

} // extern "C"
