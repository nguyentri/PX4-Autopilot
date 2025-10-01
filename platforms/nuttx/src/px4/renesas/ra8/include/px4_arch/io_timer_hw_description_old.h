/****************************************************************************
 *
 *   Copyright (C) 2021 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *	notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *	notice, this list of conditions and the following disclaimer in
 *	the documentation and/or other materials provided with the
 *	distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *	used to endorse or promote products derived from this software
 *	without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
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

// Timer configuration constants
#define MAX_IO_TIMERS 4      // Maximum number of IO timers
#define MAX_TIMER_IO_CHANNELS 4 // Maximum number of timer channels

// Timer channel mode enum - must be defined before io_timer.h inclusion
typedef enum {
    IOTimerChanMode_NotUsed = 0,
    IOTimerChanMode_PWMOut,
    IOTimerChanMode_PWMIn,
    IOTimerChanMode_Capture,
    IOTimerChanMode_OneShot,
    IOTimerChanMode_Trigger,
    IOTimerChanMode_Dshot,
    IOTimerChanMode_NP_OneShot,
    IOTimerChanModeSize
} io_timer_channel_mode_t;

// Timer allocation types
typedef uint32_t io_timer_allocation_t;
typedef uint32_t io_timer_channel_allocation_t;

// Forward declare types from io_timer.h to avoid circular dependencies
struct io_timers_t;
struct timer_io_channels_t;

// DMA configuration for RA8 (simplified - no DMA initially)
struct DMA {
    enum Index { Invalid = 0 };
    Index index;
    constexpr DMA() : index(Invalid) {}
    constexpr DMA(Index idx) : index(idx) {}
};

// Timer channel mapping structure
struct io_timers_channel_mapping_t {
    uint32_t element[MAX_IO_TIMERS];
};

// Initialization helper functions
static inline constexpr io_timers_t initIOTimer(Timer::Timer timer, DMA dma_config)
{
    io_timers_t ret{};
    
    // Map timer enum to actual GPT timer configuration
    switch(timer) {
        case Timer::Timer0:
            ret.base = 0x40078000; // GPT0 base address for RA8E1
            ret.timer_id = 0;
            ret.vectorno = 32;     // GPT0 IRQ vector
            ret.first_channel_index = 0;
            ret.last_channel_index = 0;
            break;
        case Timer::Timer2:
            ret.base = 0x40078200; // GPT2 base address for RA8E1  
            ret.timer_id = 2;
            ret.vectorno = 34;     // GPT2 IRQ vector
            ret.first_channel_index = 1;
            ret.last_channel_index = 1;
            break;
        case Timer::Timer3:
            ret.base = 0x40078300; // GPT3 base address for RA8E1
            ret.timer_id = 3;
            ret.vectorno = 35;     // GPT3 IRQ vector
            ret.first_channel_index = 2;
            ret.last_channel_index = 2;
            break;
        case Timer::Timer4:
            ret.base = 0x40078400; // GPT4 base address for RA8E1
            ret.timer_id = 4;
            ret.vectorno = 36;     // GPT4 IRQ vector
            ret.first_channel_index = 3;
            ret.last_channel_index = 3;
            break;
        default:
            ret.base = 0;
            ret.timer_id = 0xFF;
            break;
    }
    
    return ret;
}

static inline constexpr timer_io_channels_t initIOTimerChannel(const io_timers_t io_timers[], const Timer::TimerChannel timer_channel, const GPIO::GPIOPin gpio_pin)
{
    timer_io_channels_t ret{};
    
    // Map timer to timer_index
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
    
    // Set channel (always Channel1 for our basic implementation)
    ret.timer_channel = (uint8_t)timer_channel.channel;
    
    // GPIO configuration - convert to PX4 RA8 format
    ret.gpio_out = ((uint32_t)gpio_pin.port << 24) | ((uint32_t)gpio_pin.pin << 16) | 0x0001;
    ret.gpio_in = 0; // Not used for PWM output
    
    ret.freq_basis = IOTimerFrequencyBasis_PWM;
    
    return ret;
}

static inline constexpr io_timers_channel_mapping_t initIOTimerChannelMapping(const io_timers_t io_timers[], const timer_io_channels_t timer_channels[])
{
    io_timers_channel_mapping_t ret{};
    
    // Simple mapping - each timer maps to its index
    for (int i = 0; i < MAX_IO_TIMERS; i++) {
        ret.element[i] = i;
    }
    
    return ret;
}
