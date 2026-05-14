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
 * PWM/GPT Hardware Mapping (Single Source of Truth - see board_config.h):
 * -----------------------------------------------------------------------
 * This file configures the General Purpose Timer (GPT) channels for PWM motor control.
 * The RDK-RZV2H uses 4 GPT channels mapped to specific pins for ESC control.
 *
 * Timer-to-Channel-to-Pin Mapping:
 * ┌─────────┬───────────┬─────────┬─────────────────────┬───────────┐
 * │ PX4 Ch  │ GPT Timer │ Output  │ GPIO Pin            │ Mode      │
 * ├─────────┼───────────┼─────────┼─────────────────────┼───────────┤
 * │ PWM0    │ GPT6      │ GTIOC6A │ PA4 (Port10, Pin4)  │ Mode 11   │
 * │ PWM1    │ GPT7      │ GTIOC7B │ PA7 (Port10, Pin7)  │ Mode 11   │
 * │ PWM2    │ GPT9      │ GTIOC9A │ P96 (Port9, Pin6)   │ Mode 9    │
 * │ PWM3    │ GPT10     │ GTIOC10B│ P53 (Port5, Pin3)   │ Mode 11   │
 * └─────────┴───────────┴─────────┴─────────────────────┴───────────┘
 *
 * GPIO Header Mapping:
 * - GPIO12/PWM0 → PA4 → ESC1 (GPT6A)
 * - GPIO13/PWM1 → PA7 → ESC2 (GPT7B)
 * - GPIO19      → P96 → ESC3 (GPT9A)
 * - GPIO06      → P53 → ESC4 (GPT10B)
 *
 * Timer Settings:
 * - Frequency: 400 Hz (configurable via startup script, range 50-500 Hz)
 * - Mode: Standard PWM (1000-2000 µs pulse width)
 * - Clock: runtime PCLK from NuttX rzv_get_pclk_frequency()
 *
 * Pin assignments from rzv2h_pinmap.h
 */

#include <nuttx/config.h>
#include <stdint.h>
#include <syslog.h>

#include <drivers/drv_pwm_output.h>
#include "board_config.h"
#include <px4_arch/io_timer_hw_description.h>
#include <px4_platform_common/px4_config.h>

#include "rzv_gpio.h"

namespace
{

/**
 * GPT Timer Instances for PWM Output
 *
 * Each timer controls one PWM channel. Timer IDs map to:
 * - Timer6 = GPT6 - PWM0/PA4
 * - Timer7 = GPT7 - PWM1/PA7
 * - Timer9 = GPT9 - PWM2/P96
 * - Timer10 = GPT10 - PWM3/P53
 *
 * Note: These timers were chosen to match the RDK-RZV2H
 * header pin mapping for ESC connections.
 */
constexpr io_timers_t kIOTimersRaw[MAX_IO_TIMERS] = {
	initIOTimer(Timer::Timer6),   // PWM0 - GPT6 (PA4)
	initIOTimer(Timer::Timer7),   // PWM1 - GPT7 (PA7)
	initIOTimer(Timer::Timer9),   // PWM2 - GPT9 (P96)
	initIOTimer(Timer::Timer10),  // PWM3 - GPT10 (P53)
};

/**
 * DMA Channel Configuration
 *
 * DMA is optional and used for DShot protocol. When disabled (-1),
 * PWM operates in software mode which is sufficient for standard ESC control.
 */
constexpr int8_t kDmaGpt6 =
#ifdef CONFIG_RZV_DMAC_GPT6_CHANNEL
	CONFIG_RZV_DMAC_GPT6_CHANNEL;
#else
	-1;  /* DMA disabled */
#endif

constexpr int8_t kDmaGpt7 =
#ifdef CONFIG_RZV_DMAC_GPT7_CHANNEL
	CONFIG_RZV_DMAC_GPT7_CHANNEL;
#else
	-1;  /* DMA disabled */
#endif

constexpr int8_t kDmaGpt9 =
#ifdef CONFIG_RZV_DMAC_GPT9_CHANNEL
	CONFIG_RZV_DMAC_GPT9_CHANNEL;
#else
	-1;  /* DMA disabled */
#endif

constexpr int8_t kDmaGpt10 =
#ifdef CONFIG_RZV_DMAC_GPT10_CHANNEL
	CONFIG_RZV_DMAC_GPT10_CHANNEL;
#else
	-1;  /* DMA disabled */
#endif

/**
 * Timer Channel Configuration
 *
 * Maps each PWM channel to:
 * - Timer instance (from kIOTimersRaw)
 * - Timer output channel (Channel1=GTIOCA, Channel2=GTIOCB)
 * - GPIO port and pin
 * - DShot DMA configuration
 *
 * Channel types:
 * - Channel1 = GTIOCA output (even compare register)
 * - Channel2 = GTIOCB output (odd compare register)
 */
constexpr timer_io_channels_t kTimerChannelsRaw[MAX_TIMER_IO_CHANNELS] = {
	/* PWM0: GPT6 GTIOCA on PA4 (PortA, Pin4) - ESC1 */
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer6, Timer::Channel1}, {GPIO::PortA, GPIO::Pin4},
			   makeDshotConf(6, 0, kDmaGpt6, -1)),
	/* PWM1: GPT7 GTIOCB on PA7 (PortA, Pin7) - ESC2 */
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer7, Timer::Channel2}, {GPIO::PortA, GPIO::Pin7},
			   makeDshotConf(7, 1, kDmaGpt7, -1)),
	/* PWM2: GPT9 GTIOCA on P96 (Port9, Pin6) - ESC3 */
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer9, Timer::Channel1}, {GPIO::Port9, GPIO::Pin6},
			   makeDshotConf(9, 0, kDmaGpt9, -1)),
	/* PWM3: GPT10 GTIOCB on P53 (Port5, Pin3) - ESC4 */
	initIOTimerChannel(kIOTimersRaw, {Timer::Timer10, Timer::Channel2}, {GPIO::Port5, GPIO::Pin3},
			   makeDshotConf(10, 1, kDmaGpt10, -1)),
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

	/**
	 * Timer Configuration Export
	 *
	 * These arrays are the single source of truth for timer configuration,
	 * referenced by io_timer.c and pwm_servo.c. GPIO pins are defined in
	 * board_config.h (BOARD_PWM_CHx_GPIO macros).
	 */
	const io_timers_t io_timers[MAX_IO_TIMERS] = {
		makeTimer(kIOTimersRaw[0], 0),  /* GPT6 - PWM0/PA4 */
		makeTimer(kIOTimersRaw[1], 1),  /* GPT7 - PWM1/PA7 */
		makeTimer(kIOTimersRaw[2], 2),  /* GPT9 - PWM2/P96 */
		makeTimer(kIOTimersRaw[3], 3),  /* GPT10 - PWM3/P53 */
	};

	/**
	 * Timer Channel Configuration Export
	 *
	 * Maps timer channels to GPIO pins defined in board_config.h.
	 * This ensures single-source configuration with no duplication.
	 */
	const timer_io_channels_t timer_io_channels[MAX_TIMER_IO_CHANNELS] = {
		makeChannel(kTimerChannelsRaw[0], 0, BOARD_PWM_CH0_GPIO),  /* PWM0: GPT6 GTIOCA/PA4 */
		makeChannel(kTimerChannelsRaw[1], 1, BOARD_PWM_CH1_GPIO),  /* PWM1: GPT7 GTIOCB/PA7 */
		makeChannel(kTimerChannelsRaw[2], 2, BOARD_PWM_CH2_GPIO),  /* PWM2: GPT9 GTIOCA/P96 */
		makeChannel(kTimerChannelsRaw[3], 3, BOARD_PWM_CH3_GPIO),  /* PWM3: GPT10 GTIOCB/P53 */
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
		/* Ensure PWM pins are configured for GPT output */
#ifdef BOARD_PWM_CH0_GPIO
		px4_arch_configgpio(BOARD_PWM_CH0_GPIO);
#endif
#ifdef BOARD_PWM_CH1_GPIO
		px4_arch_configgpio(BOARD_PWM_CH1_GPIO);
#endif
#ifdef BOARD_PWM_CH2_GPIO
		px4_arch_configgpio(BOARD_PWM_CH2_GPIO);
#endif
#ifdef BOARD_PWM_CH3_GPIO
		px4_arch_configgpio(BOARD_PWM_CH3_GPIO);
#endif

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
