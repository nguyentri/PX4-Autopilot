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

#pragma once

#include <px4_platform_common/px4_config.h>
#include <px4_arch/hw_description.h>
#include <px4_arch/io_timer.h>
#include <nuttx/timers/pwm.h>
#include <nuttx/timers/timer.h>
#include <stdint.h>

/* RA8E1 NuttX HAL-based IO Timer implementation
 *
 * This implementation uses NuttX PWM and Timer HAL instead of direct hardware register access.
 * The RA8 GPT timers are accessed through the ra_gpt.c driver which provides proper abstraction.
 */

/* DMA configuration structure for RA8E1 GPT */
struct DMA {
    enum Index : uint8_t { Invalid = 0 };
    Index index;
    constexpr DMA(Index idx = Invalid) : index(idx) {}
};

/* MAX_IO_TIMERS and MAX_TIMER_IO_CHANNELS are defined in io_timer.h */

struct io_timers_channel_mapping_t {
    uint32_t element[MAX_IO_TIMERS];
};

/* PWM device handles for RA8E1 GPT timers */
struct ra8_pwm_device_t {
    struct pwm_lowerhalf_s *pwm_dev;
    uint8_t gpt_channel;
    uint32_t gpio_pin;
};

/* Initialize RA8E1 GPT timer using NuttX HAL approach */
static inline constexpr ::io_timers_t initIOTimer(Timer::Timer timer, DMA dma_config)
{
    ::io_timers_t ret{};

    // Map timer enum to GPT channel number for NuttX HAL
    switch(timer) {
        case Timer::Timer0:
            ret.timer_id = 0;        // GPT0
            ret.first_channel_index = 0;
            ret.last_channel_index = 0;
            break;
        case Timer::Timer2:
            ret.timer_id = 2;        // GPT2
            ret.first_channel_index = 1;
            ret.last_channel_index = 1;
            break;
        case Timer::Timer3:
            ret.timer_id = 3;        // GPT3
            ret.first_channel_index = 2;
            ret.last_channel_index = 2;
            break;
        case Timer::Timer4:
            ret.timer_id = 4;        // GPT4
            ret.first_channel_index = 3;
            ret.last_channel_index = 3;
            break;
        default:
            ret.timer_id = 0xFF;
            break;
    }

    // Set base address to 0 - we'll use NuttX HAL instead of direct register access
    ret.base = 0;
    ret.vectorno = 0;

    return ret;
}

static inline constexpr ::timer_io_channels_t initIOTimerChannel(const ::io_timers_t io_timers_array[], const Timer::TimerChannel timer_channel, const GPIO::GPIOPin gpio_pin)
{
    ::timer_io_channels_t ret{};

    // Map timer to timer_index for NuttX HAL
    switch(timer_channel.timer) {
        case Timer::Timer0:
            ret.timer_index = 0;
            break;
        case Timer::Timer2:
            ret.timer_index = 1;
            break;
        case Timer::Timer3:
            ret.timer_index = 2;
            break;
        case Timer::Timer4:
            ret.timer_index = 3;
            break;
        default:
            ret.timer_index = 0xFF;
            break;
    }

    // Set channel (NuttX GPT channels)
    ret.timer_channel = (uint8_t)timer_channel.channel;

    // GPIO configuration - convert to PX4 RA8 format for NuttX compatibility
    ret.gpio_out = ((uint32_t)gpio_pin.port << 24) | ((uint32_t)gpio_pin.pin << 16) | 0x0001;
    ret.gpio_in = 0; // Not used for PWM output

    ret.freq_basis = IOTimerFrequencyBasis_PWM;

    return ret;
}

static inline constexpr io_timers_channel_mapping_t initIOTimerChannelMapping(const ::io_timers_t io_timers_array[], const ::timer_io_channels_t timer_channels[])
{
    io_timers_channel_mapping_t ret{};

    // Simple mapping - each timer maps to its index
    for (int i = 0; i < MAX_IO_TIMERS; i++) {
        ret.element[i] = i;
    }

    return ret;
}
