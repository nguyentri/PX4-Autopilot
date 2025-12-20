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
 * Timer configuration for RDK-RZV2H board
 *
 * PWM/GPT Hardware Mapping:
 * -------------------------
 * This file configures the General Purpose Timer (GPT) channels for PWM motor control.
 * The RDK-RZV2H uses 4 GPT channels mapped to specific pins for ESC control.
 *
 * Hardware Configuration (from NuttX board.h):
 * - Motor 1 (Channel 0): GPT1A on P7_1 (Timer1 GTIOCA)
 * - Motor 2 (Channel 1): GPT2B on P7_2 (Timer2 GTIOCB)
 * - Motor 3 (Channel 2): GPT3A on P7_5 (Timer3 GTIOCA)
 * - Motor 4 (Channel 3): GPT4B on P7_6 (Timer4 GTIOCB)
 *
 * Timer Settings:
 * - Frequency: 400 Hz (configurable via startup script)
 * - Mode: Standard PWM (1000-2000 µs pulse width)
 *
 * Pin assignments follow the FSP configuration in pin_data.c
 */

#include <nuttx/config.h>
#include <stdint.h>
#include <syslog.h>

#include <drivers/drv_pwm_output.h>
#include <px4_arch/io_timer_hw_description.h>

#include "board_config.h"

namespace
{

// Initialize the 4 GPT timers used for PWM motor control
constexpr io_timers_t kIOTimersRaw[MAX_IO_TIMERS] = {
	initIOTimer(Timer::Timer1),   // Motor 1 - GPT1
	initIOTimer(Timer::Timer2),   // Motor 2 - GPT2
	initIOTimer(Timer::Timer3),   // Motor 3 - GPT3
	initIOTimer(Timer::Timer4),   // Motor 4 - GPT4
};

// DMA configuration - disabled by default, can be enabled per channel
constexpr int8_t kDmaGpt1 =
#ifdef CONFIG_RZV_DMAC_GPT1_CHANNEL
	CONFIG_RZV_DMAC_GPT1_CHANNEL;
#else
	- 1;
#endif

constexpr int8_t kDmaGpt2 =
#ifdef CONFIG_RZV_DMAC_GPT2_CHANNEL
	CONFIG_RZV_DMAC_GPT2_CHANNEL;
#else
	- 1;
#endif

constexpr int8_t kDmaGpt3 =
#ifdef CONFIG_RZV_DMAC_GPT3_CHANNEL
	CONFIG_RZV_DMAC_GPT3_CHANNEL;
#else
	- 1;
#endif

constexpr int8_t kDmaGpt4 =
#ifdef CONFIG_RZV_DMAC_GPT4_CHANNEL
	CONFIG_RZV_DMAC_GPT4_CHANNEL;
#else
	- 1;
#endif

// Map each timer to its hardware pin (from NuttX board.h)
constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer1, Timer::Channel1}, {GPIO::Port7, GPIO::Pin1},
			   makeDshotConf(1, 0, kDmaGpt1, -1)),   // Motor 1: GPT1A/P7_1
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer2, Timer::Channel2}, {GPIO::Port7, GPIO::Pin2},
			   makeDshotConf(2, 1, kDmaGpt2, -1)),   // Motor 2: GPT2B/P7_2
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer3, Timer::Channel1}, {GPIO::Port7, GPIO::Pin5},
			   makeDshotConf(3, 0, kDmaGpt3, -1)),   // Motor 3: GPT3A/P7_5
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer4, Timer::Channel2}, {GPIO::Port7, GPIO::Pin6},
			   makeDshotConf(4, 1, kDmaGpt4, -1)),   // Motor 4: GPT4B/P7_6
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
		makeTimer(kIOTimersRaw[0], 0),  // GPT1 - Motor 1
		makeTimer(kIOTimersRaw[1], 1),  // GPT2 - Motor 2
		makeTimer(kIOTimersRaw[2], 2),  // GPT3 - Motor 3
		makeTimer(kIOTimersRaw[3], 3),  // GPT4 - Motor 4
	};

	// Export timer channel configurations with GPIO mappings
	// GPIO_TIMx_CHxOUT macros are defined in board_config.h and map to GPTx pins
	const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
		makeChannel(kTimerChannelsRaw[0], 0, BOARD_PWM_CH0_GPIO),  // Motor 1: GPT1A/P7_1
		makeChannel(kTimerChannelsRaw[1], 1, BOARD_PWM_CH1_GPIO),  // Motor 2: GPT2B/P7_2
		makeChannel(kTimerChannelsRaw[2], 2, BOARD_PWM_CH2_GPIO),  // Motor 3: GPT3A/P7_5
		makeChannel(kTimerChannelsRaw[3], 3, BOARD_PWM_CH3_GPIO),  // Motor 4: GPT4B/P7_6
	};

	/**
	 * @brief Initialize timer subsystem for RDK-RZV2H
	 *
	 * This function initializes the GPT timers for PWM output and the HRT timer.
	 * Called from board_app_initialize() during board startup.
	 *
	 * @return 0 on success, negative errno on failure
	 */
	int rdk_rzv2h_timer_initialize(void)
	{
		/* Initialize high-resolution timer first */
		hrt_init();

		/* Initialize IO timer subsystem */
		int ret = io_timer_init();

		if (ret != 0) {
			syslog(LOG_ERR, "rdk_rzv2h_timer_initialize: io_timer_init() failed: %d\n", ret);
			return ret;
		}

		return 0;
	}

} // extern "C"
