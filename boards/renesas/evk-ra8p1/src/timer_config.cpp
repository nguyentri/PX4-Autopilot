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
 * Timer configuration for EVK-RA8P1 board
 *
 * PWM/GPT Hardware Mapping:
 * -------------------------
 * This file configures the General Purpose Timer (GPT) channels for PWM motor control.
 * The EVK-RA8P1 uses 4 GPT channels mapped to specific pins for ESC control.
 *
 * Hardware Configuration (verified from EVK-RA8P1 pinout):
 * - Motor 1 (Channel 0): GPT0A on P211 (PORT2, PIN11)
 * - Motor 2 (Channel 1): GPT10A on P109 (PORT1, PIN9) - Arduino D9
 * - Motor 3 (Channel 2): GPT11A on P711 (PORT7, PIN11)
 * - Motor 4 (Channel 3): GPT12A on P708 (PORT7, PIN8)
 *
 * Timer Settings:
 * - Frequency: 400 Hz (configurable via startup script)
 * - Mode: Standard PWM (1000-2000 µs pulse width)
 * - DShot support: Available via renesas_evk-ra8p1_dshot target
 *
 * Note: All timers use Channel 1 (GTIOCA) for PWM output.
 */

#include <stdint.h>

#include <drivers/drv_pwm_output.h>
#include <px4_arch/io_timer_hw_description.h>

#include "board_config.h"

namespace
{

// Initialize the 4 GPT timers used for PWM motor control
constexpr io_timers_t kIOTimersRaw[MAX_IO_TIMERS] = {
        initIOTimer(Timer::Timer0),   // Motor 1 - GPT0
        initIOTimer(Timer::Timer10),  // Motor 2 - GPT10
        initIOTimer(Timer::Timer11),  // Motor 3 - GPT11
        initIOTimer(Timer::Timer12),  // Motor 4 - GPT12
};

// Map each timer to its hardware pin (verified from EVK-RA8P1 pinout)
constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer0, Timer::Channel1}, {GPIO::Port2, GPIO::Pin11}),  // Motor 1: GPT0A/P211
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer10, Timer::Channel1}, {GPIO::Port1, GPIO::Pin9}),  // Motor 2: GPT10A/P109
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer11, Timer::Channel1}, {GPIO::Port7, GPIO::Pin11}), // Motor 3: GPT11A/P711
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer12, Timer::Channel1}, {GPIO::Port7, GPIO::Pin8}),  // Motor 4: GPT12A/P708
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

// Export timer configurations for PX4 PWM subsystem
// These are referenced by the pwm_out driver to control motor outputs
const io_timers_t io_timers[MAX_IO_TIMERS] = {
        makeTimer(kIOTimersRaw[0], 0),  // GPT3 - Motor 1
        makeTimer(kIOTimersRaw[1], 1),  // GPT0 - Motor 2
        makeTimer(kIOTimersRaw[2], 2),  // GPT2 - Motor 3
        makeTimer(kIOTimersRaw[3], 3),  // GPT4 - Motor 4
};

// Export timer channel configurations with GPIO mappings
// GPIO_TIMx_CH1OUT macros are defined in board_config.h and map to GPTxA pins
const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
        makeChannel(kTimerChannelsRaw[0], 0, GPIO_TIM0_CH1OUT),  // Motor 1: P300 (GPIO_GTIOC3A_1)
        makeChannel(kTimerChannelsRaw[1], 1, GPIO_TIM10_CH1OUT),  // Motor 2: P415 (GPIO_GTIOC0A_3)
        makeChannel(kTimerChannelsRaw[2], 2, GPIO_TIM11_CH1OUT),  // Motor 3: P113 (GPIO_GTIOC2A_2)
        makeChannel(kTimerChannelsRaw[3], 3, GPIO_TIM12_CH1OUT),  // Motor 4: P302 (GPIO_GTIOC4A_2)
};

void evk_ra8p1_timer_initialize()
{
        hrt_init();
        io_timer_init();
}

} // extern "C"
