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

namespace
{

constexpr io_timers_t kIOTimersRaw[MAX_IO_TIMERS] = {
	initIOTimer(Timer::Timer3),
	initIOTimer(Timer::Timer0),
	initIOTimer(Timer::Timer2),
	initIOTimer(Timer::Timer4),
};

constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer3, Timer::Channel1}, {GPIO::Port3, GPIO::Pin0}),
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer0, Timer::Channel1}, {GPIO::Port4, GPIO::Pin15}),
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer2, Timer::Channel1}, {GPIO::Port1, GPIO::Pin13}),
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer4, Timer::Channel1}, {GPIO::Port3, GPIO::Pin2}),
};

template<typename TimerType>
constexpr TimerType makeTimer(TimerType base, uint8_t timer_index)
{
	base.first_channel_index = timer_index;
	base.last_channel_index = timer_index;
	return base;
}

template<typename ChannelType>
constexpr ChannelType makeChannel(ChannelType base, uint8_t timer_index, uint32_t gpio_config)
{
	return ChannelType{gpio_config, base.gpio_in, timer_index, base.timer_channel, base.freq_basis};
}

} // namespace

// Forward declarations
extern "C" int io_timer_init();
extern "C" void hrt_init(void);

extern "C" {

const io_timers_t io_timers[MAX_IO_TIMERS] = {
	makeTimer(kIOTimersRaw[0], 0),
	makeTimer(kIOTimersRaw[1], 1),
	makeTimer(kIOTimersRaw[2], 2),
	makeTimer(kIOTimersRaw[3], 3),
};

const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
	makeChannel(kTimerChannelsRaw[0], 0, GPIO_TIM3_CH1OUT),
	makeChannel(kTimerChannelsRaw[1], 1, GPIO_TIM0_CH1OUT),
	makeChannel(kTimerChannelsRaw[2], 2, GPIO_TIM2_CH1OUT),
	makeChannel(kTimerChannelsRaw[3], 3, GPIO_TIM4_CH1OUT),
};

void fpb_ra8e1_timer_initialize()
{
	hrt_init();
	io_timer_init();
}

} // extern "C"
