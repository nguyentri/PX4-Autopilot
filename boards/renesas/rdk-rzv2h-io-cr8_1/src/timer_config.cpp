// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include <px4_arch/io_timer_hw_description.h>
#include "rzv_gpio.h"

// Candidate RDK four-output mapping from the existing reference board table.
// Merely linking this table touches no peripheral. The unconfigured contract
// prevents io_timer_init() and every pad/GPT/cleanup call before admission.
// SCI1 console is excluded by the pwm defconfig (P53 is output four).
namespace
{
constexpr io_timers_t raw[MAX_IO_TIMERS] {
	initIOTimer(Timer::Timer6), initIOTimer(Timer::Timer7),
	initIOTimer(Timer::Timer9), initIOTimer(Timer::Timer10)
};
constexpr uint32_t pins[4] {
	GPIO_GTIOC6A_PA_4_M11 | RZV_GPIO_PERIPH, GPIO_GTIOC7B_PA_7_M11 | RZV_GPIO_PERIPH,
	GPIO_GTIOC9A_P9_6_M9 | RZV_GPIO_PERIPH, GPIO_GTIOC10B_P5_3_M11 | RZV_GPIO_PERIPH
};
constexpr timer_io_channels_t channels[MAX_TIMER_IO_CHANNELS] {
	initIOTimerChannel(raw, {Timer::Timer6, Timer::Channel1}, {GPIO::PortA, GPIO::Pin4}, makeDshotConf(6, 0, -1, -1)),
	initIOTimerChannel(raw, {Timer::Timer7, Timer::Channel2}, {GPIO::PortA, GPIO::Pin7}, makeDshotConf(7, 1, -1, -1)),
	initIOTimerChannel(raw, {Timer::Timer9, Timer::Channel1}, {GPIO::Port9, GPIO::Pin6}, makeDshotConf(9, 0, -1, -1)),
	initIOTimerChannel(raw, {Timer::Timer10, Timer::Channel2}, {GPIO::Port5, GPIO::Pin3}, makeDshotConf(10, 1, -1, -1))
};
constexpr io_timers_t timer(unsigned i) { auto t = raw[i]; t.first_channel_index = i; t.last_channel_index = i; return t; }
constexpr timer_io_channels_t channel(unsigned i) { auto c = channels[i]; c.timer_index = i; c.gpio_out = pins[i]; return c; }
}
extern "C" {
	const io_timers_t io_timers[MAX_IO_TIMERS] {timer(0), timer(1), timer(2), timer(3)};
	const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] {channel(0), channel(1), channel(2), channel(3)};
}
