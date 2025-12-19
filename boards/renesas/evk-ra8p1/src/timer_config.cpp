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
 * - Motor 1 (Channel 0): GPT3A on P912 (PORT9, PIN12)
 * - Motor 2 (Channel 1): GPT5A on P915 (PORT9, PIN15)
 * - Motor 3 (Channel 2): GPT11A on P903 (PORT9, PIN3)
 * - Motor 4 (Channel 3): GPT13A on P515 (PORT5, PIN15)
 *
 * Timer Settings:
 * - Frequency: 400 Hz (configurable via startup script)
 * - Mode: Standard PWM (1000-2000 µs pulse width)
 * - DShot support: Available via renesas_evk-ra8p1_dshot target
 *
 * Note: All timers use Channel 1 (GTIOCA) for PWM output.
 */

#include <nuttx/config.h>
#include <stdint.h>

#include <drivers/drv_pwm_output.h>
#include <px4_arch/io_timer_hw_description.h>

#include "board_config.h"

namespace
{

// Initialize the 4 GPT timers used for PWM motor control
constexpr io_timers_t kIOTimersRaw[MAX_IO_TIMERS] = {
        initIOTimer(Timer::Timer3),   // Motor 1 - GPT3
        initIOTimer(Timer::Timer5),   // Motor 2 - GPT5
        initIOTimer(Timer::Timer11),  // Motor 3 - GPT11
        initIOTimer(Timer::Timer13),  // Motor 4 - GPT13
};

// Map each timer to its hardware pin (verified from EVK-RA8P1 pinout)
constexpr int8_t kDmaGpt3 =
#ifdef CONFIG_RA_DMAC_GPT3_CHANNEL
CONFIG_RA_DMAC_GPT3_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt5 =
#ifdef CONFIG_RA_DMAC_GPT5_CHANNEL
CONFIG_RA_DMAC_GPT5_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt11 =
#ifdef CONFIG_RA_DMAC_GPT11_CHANNEL
CONFIG_RA_DMAC_GPT11_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt13 =
#ifdef CONFIG_RA_DMAC_GPT13_CHANNEL
CONFIG_RA_DMAC_GPT13_CHANNEL;
#else
-1;
#endif

constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer3, Timer::Channel1}, {GPIO::Port9, GPIO::Pin12},
                           makeDshotConf(3, 0, kDmaGpt3, -1)),   // Motor 1: GPT3A/P912
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer5, Timer::Channel1}, {GPIO::Port9, GPIO::Pin15},
                           makeDshotConf(5, 0, kDmaGpt5, -1)),   // Motor 2: GPT5A/P915
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer11, Timer::Channel1}, {GPIO::Port9, GPIO::Pin3},
                           makeDshotConf(11, 0, kDmaGpt11, -1)), // Motor 3: GPT11A/P903
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer13, Timer::Channel1}, {GPIO::Port5, GPIO::Pin15},
                           makeDshotConf(13, 0, kDmaGpt13, -1)), // Motor 4: GPT13A/P515
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
        makeTimer(kIOTimersRaw[1], 1),  // GPT5 - Motor 2
        makeTimer(kIOTimersRaw[2], 2),  // GPT11 - Motor 3
        makeTimer(kIOTimersRaw[3], 3),  // GPT13 - Motor 4
};

// Export timer channel configurations with GPIO mappings
// GPIO_TIMx_CH1OUT macros are defined in board_config.h and map to GPTxA pins
const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
        makeChannel(kTimerChannelsRaw[0], 0, GPIO_TIM3_CH1OUT),   // Motor 1: P912 (GPIO_GTIOC3A)
        makeChannel(kTimerChannelsRaw[1], 1, GPIO_TIM5_CH1OUT),   // Motor 2: P915 (GPIO_GTIOC5A)
        makeChannel(kTimerChannelsRaw[2], 2, GPIO_TIM11_CH1OUT),  // Motor 3: P903 (GPIO_GTIOC11A_2)
        makeChannel(kTimerChannelsRaw[3], 3, GPIO_TIM13_CH1OUT),  // Motor 4: P515 (GPIO_GTIOC13A)
};

void evk_ra8p1_timer_initialize()
{
        hrt_init();
        io_timer_init();
}

} // extern "C"
