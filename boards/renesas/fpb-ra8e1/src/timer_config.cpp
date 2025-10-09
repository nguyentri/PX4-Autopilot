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

#include <drivers/drv_pwm_output.h>
#include <px4_arch/io_timer_hw_description.h>

#include "board_config.h"

// Forward declarations
extern "C" int io_timer_init();
extern "C" void hrt_init(void);

// Board-specific timer configuration for RA8E1
// This provides the timer configuration that the io_timer.c expects
extern "C" {

// Configuration limits for RA8E1 board - 4 GPT timers for 4 ESC outputs
#ifndef MAX_IO_TIMERS
#define MAX_IO_TIMERS			4
#endif

#ifndef MAX_TIMER_IO_CHANNELS
#define MAX_TIMER_IO_CHANNELS	4
#endif

// RA8E1 board timer configuration for 4 ESC outputs
// Motor mapping:
//   Motor 1: P300 (GPT3A) - Channel 0
//   Motor 2: P415 (GPT0A) - Channel 1
//   Motor 3: P113 (GPT2A) - Channel 2
//   Motor 4: P302 (GPT4A) - Channel 3
const io_timers_t io_timers[MAX_IO_TIMERS] = {
	initIOTimer(Timer::Timer3),
	initIOTimer(Timer::Timer0),
	initIOTimer(Timer::Timer2),
	initIOTimer(Timer::Timer4),
};

// Timer channel mappings for RA8E1
// Maps each PWM channel to its GPIO pin and GPT timer
// GPIO values will be configured at runtime using ra_gpio functions
const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
	initIOTimerChannel(io_timers, {Timer::Timer3, Timer::Channel1}, {GPIO::Port3, GPIO::Pin0}),
	initIOTimerChannel(io_timers, {Timer::Timer0, Timer::Channel1}, {GPIO::Port4, GPIO::Pin15}),
	initIOTimerChannel(io_timers, {Timer::Timer2, Timer::Channel1}, {GPIO::Port1, GPIO::Pin13}),
	initIOTimerChannel(io_timers, {Timer::Timer4, Timer::Channel1}, {GPIO::Port3, GPIO::Pin2}),
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
