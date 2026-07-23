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
 *
 * PWM/GPT Hardware Mapping:
 * -------------------------
 * This file configures the General Purpose Timer (GPT) channels for PWM motor control.
 * The FPB-RA8E1 uses 4 GPT channels mapped to specific pins for ESC control.
 *
 * Hardware Configuration (verified from datasheet):
 * - Motor 1 (Channel 0): GPT3A on P300 (PORT3, PIN0)
 * - Motor 2 (Channel 1): GPT0A on P415 (PORT4, PIN15)
 * - Motor 3 (Channel 2): GPT2A on P113 (PORT1, PIN13)
 * - Motor 4 (Channel 3): GPT4A on P302 (PORT3, PIN2)
 *
 * Timer Settings:
 * - Frequency: 400 Hz (configurable via startup script)
 * - Mode: Standard PWM (1000-2000 µs pulse width)
 * - DShot support: Available via renesas_fpb-ra8e1_dshot target
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
        initIOTimer(Timer::Timer0),   // Motor 2 - GPT0
        initIOTimer(Timer::Timer2),   // Motor 3 - GPT2
        initIOTimer(Timer::Timer4),   // Motor 4 - GPT4
};

// Map each timer to its hardware pin (verified from RA8E1 datasheet)
constexpr int8_t kDmaGpt3 =
#ifdef CONFIG_RA_DMAC_GPT3_CHANNEL
CONFIG_RA_DMAC_GPT3_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt0 =
#ifdef CONFIG_RA_DMAC_GPT0_CHANNEL
CONFIG_RA_DMAC_GPT0_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt2 =
#ifdef CONFIG_RA_DMAC_GPT2_CHANNEL
CONFIG_RA_DMAC_GPT2_CHANNEL;
#else
-1;
#endif

constexpr int8_t kDmaGpt4 =
#ifdef CONFIG_RA_DMAC_GPT4_CHANNEL
CONFIG_RA_DMAC_GPT4_CHANNEL;
#else
-1;
#endif

constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer3, Timer::ChannelA}, {GPIO::Port3, GPIO::Pin0},
                           makeDshotConf(3, 0, kDmaGpt3, -1)),   // Motor 1: GPT3A/P300
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer0, Timer::ChannelA}, {GPIO::Port4, GPIO::Pin15},
                           makeDshotConf(0, 0, kDmaGpt0, -1)),   // Motor 2: GPT0A/P415
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer2, Timer::ChannelA}, {GPIO::Port1, GPIO::Pin13},
                           makeDshotConf(2, 0, kDmaGpt2, -1)), // Motor 3: GPT2A/P113
        initIOTimerChannel(kIOTimersRaw, {Timer::Timer4, Timer::ChannelA}, {GPIO::Port3, GPIO::Pin2},
                           makeDshotConf(4, 0, kDmaGpt4, -1)), // Motor 4: GPT4A/P302
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
        makeChannel(kTimerChannelsRaw[0], 0, GPIO_TIM3_CH1OUT),   // P300 - GPT3A - Motor 1
        makeChannel(kTimerChannelsRaw[1], 1, GPIO_TIM0_CH1OUT),   // P415 - GPT0A - Motor 2
        makeChannel(kTimerChannelsRaw[2], 2, GPIO_TIM2_CH1OUT),   // P113 - GPT2A - Motor 3
        makeChannel(kTimerChannelsRaw[3], 3, GPIO_TIM4_CH1OUT),   // P302 - GPT4A - Motor 4
};

void fpb_ra8e1_timer_initialize()
{
        hrt_init();
        io_timer_init();
}

} // extern "C"
