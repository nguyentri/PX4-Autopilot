/****************************************************************************
 *
 *   Copyright (c) 2024 PX4 Development Team. All rights reserved.
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
 * NuttX HAL-based configuration for RA8E1 GPT timers.
 */

#include <px4_arch/io_timer_hw_description.h>
#include <px4_arch/hw_description.h>

#include "board_config.h"

/* NuttX HAL-based Configuration for RA8E1 GPT timers for PWM output
 *
 * This configuration uses NuttX PWM HAL through ra_gpt driver instead of
 * direct hardware register access. The GPT timers are initialized using
 * ra_gpt_initialize() which returns pwm_lowerhalf_s structures.
 */

constexpr ::io_timers_t io_timers[MAX_IO_TIMERS] = {
	initIOTimer(Timer::Timer0, DMA{DMA::Invalid}),  // GPT0 for Motor 2
	initIOTimer(Timer::Timer2, DMA{DMA::Invalid}),  // GPT2 for Motor 3
	initIOTimer(Timer::Timer3, DMA{DMA::Invalid}),  // GPT3 for Motor 1
	initIOTimer(Timer::Timer4, DMA{DMA::Invalid}),  // GPT4 for Motor 4
};

constexpr ::timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
	initIOTimerChannel(io_timers, {Timer::Timer3, Timer::Channel1}, {BOARD_ESC_1}),  // Motor 1 -> Channel 0
	initIOTimerChannel(io_timers, {Timer::Timer0, Timer::Channel1}, {BOARD_ESC_2}),  // Motor 2 -> Channel 1
	initIOTimerChannel(io_timers, {Timer::Timer2, Timer::Channel1}, {BOARD_ESC_3}),  // Motor 3 -> Channel 2
	initIOTimerChannel(io_timers, {Timer::Timer4, Timer::Channel1}, {BOARD_ESC_4}),  // Motor 4 -> Channel 3
};

constexpr io_timers_channel_mapping_t io_timers_channel_mapping = initIOTimerChannelMapping(io_timers, timer_io_channels);
