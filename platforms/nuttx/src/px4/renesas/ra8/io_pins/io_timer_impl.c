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

/**
 * @file io_timer_impl.c
 *
 * GPT Timer Implementation for RA8E1 ESC Control using NuttX HAL
 *
 * This module provides GPT timer initialization and PWM control for ESC outputs
 * using NuttX Hardware Abstraction Layer instead of direct register access.
 *
 * Motor Mapping (from board_config.h):
 *  - Motor 1: P300 (GPT3 Channel A) - Channel 0
 *  - Motor 2: P415 (GPT0 Channel A) - Channel 1
 *  - Motor 3: P113 (GPT2 Channel A) - Channel 2
 *  - Motor 4: P302 (GPT4 Channel A) - Channel 3
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

/* Board configuration constants - must be included before px4_arch headers */
/* This file provides BOARD_NUM_IO_TIMERS and BOARD_PCLKD_FREQUENCY */
#ifndef BOARD_PCLKD_FREQUENCY
#define BOARD_PCLKD_FREQUENCY  120000000  /* 120MHz PCLKD clock - from board.h */
#endif

#ifndef DIRECT_PWM_OUTPUT_CHANNELS
#define DIRECT_PWM_OUTPUT_CHANNELS  4  /* 4 PWM outputs - from board_config.h */
#endif

#ifndef BOARD_NUM_IO_TIMERS
#define BOARD_NUM_IO_TIMERS  4  /* 4 timers for FPB-RA8E1 */
#endif

/* Include IO timer types and declarations */
#include "../include/px4_arch/io_timer.h"

/* NuttX RA8 hardware headers - provides register addresses, offsets and bits */
#include <hardware/ra_gpt.h>                  /* GPT register offsets and bit definitions */
#include <hardware/ra_mstp.h>                 /* Module stop control register definitions */
#include <hardware/ra8e1/ra8e1_memorymap.h>  /* R_GPT*_BASE addresses, R_MSTP_BASE */
#include <arm_internal.h>                    /* For getreg32/putreg32 macros */

#include "board_config.h"                  /* Board-specific configuration */

/* External declarations from timer_config.cpp */
extern const io_timers_t io_timers[];
extern const timer_io_channels_t timer_io_channels[];

/* PWM Configuration Parameters - Use board configuration */
#define PWM_DEFAULT_FREQUENCY_HZ    400        /* Default 400Hz for standard ESCs */
#define DEFAULT_PRESCALER           64         /* PCLKD/64 */

/* PWM pulse width limits (in microseconds) */
#define PWM_MIN_PULSE_US    1000
#define PWM_MAX_PULSE_US    2000
#define PWM_DEFAULT_PULSE_US 1500

/* GPT timer configuration - populated at runtime */
static struct {
	uint32_t base;
	uint32_t period;
	uint32_t prescaler;
	uint8_t gpt_channel;
	bool initialized;
} gpt_config[DIRECT_PWM_OUTPUT_CHANNELS];

/* Forward declarations */
static int gpt_enable_clock(uint8_t gpt_channel);
static int gpt_configure_gpio(uint32_t gpio_config);
static uint32_t gpt_get_base_address(uint8_t gpt_channel);

/**
 * @brief Get GPT base address from GPT channel number
 *
 * Uses NuttX RA_GPT_BASE() macro from ra_gpt.h which calculates:
 * Base = R_GPT0_BASE + (channel * 0x100)
 */
static uint32_t gpt_get_base_address(uint8_t gpt_channel)
{
	return RA_GPT_BASE(gpt_channel);
}

/**
 * @brief Enable GPT timer clock via MSTP (Module Stop Control)
 *
 * Uses NuttX definitions from ra_mstp.h:
 * - R_MSTP_MSTPCRE: Module Stop Control Register E address
 * - R_MSTP_MSTPCRE_GPT*: Bit masks for each GPT timer
 */
static int gpt_enable_clock(uint8_t gpt_channel)
{
	uint32_t mstpcre;
	uint32_t bit_mask = 0;

	/* Determine the MSTP bit for this GPT channel using NuttX definitions */
	switch (gpt_channel) {
	case 0:  bit_mask = R_MSTP_MSTPCRE_GPT0; break;
	case 2:  bit_mask = R_MSTP_MSTPCRE_GPT2; break;
	case 3:  bit_mask = R_MSTP_MSTPCRE_GPT3; break;
	case 4:  bit_mask = R_MSTP_MSTPCRE_GPT4; break;
	default: return -EINVAL;
	}

	/* Read-modify-write to clear the stop bit (enable clock) */
	mstpcre = getreg32(R_MSTP_MSTPCRE);
	mstpcre &= ~bit_mask;
	putreg32(mstpcre, R_MSTP_MSTPCRE);

	return 0;
}

/**
 * @brief Configure GPIO pin for GPT timer output
 */
static int gpt_configure_gpio(uint32_t gpio_config)
{
	if (gpio_config == 0) {
		return -EINVAL;
	}

	/* Extract port and pin from encoded config */
	uint8_t port = (gpio_config >> 24) & 0xFF;
	uint8_t pin = (gpio_config >> 16) & 0xFF;

	/* GPIO configuration will be done by board-specific code
	 * using the GPIO definitions from board_config.h
	 * The gpio_config value is just a placeholder for now
	 */
	(void)port;
	(void)pin;

	/* TODO: Call ra_configgpio() with proper pinset when available */
	ra_configgpio(GPIO_TIM3_CH1OUT);
	ra_configgpio(GPIO_TIM0_CH1OUT);
	ra_configgpio(GPIO_TIM2_CH1OUT);
	ra_configgpio(GPIO_TIM4_CH1OUT);

	return 0;
}

/**
 * @brief Initialize a single GPT timer for PWM output
 *
 * Configures a GPT timer channel for standard PWM ESC control.
 * All register offsets and bit definitions are from NuttX ra_gpt.h
 */
static int gpt_timer_init_pwm(unsigned channel, unsigned frequency_hz)
{
	if (channel >= DIRECT_PWM_OUTPUT_CHANNELS) {
		return -EINVAL;
	}

	/* Get timer configuration from io_timers array */
	uint8_t gpt_channel = io_timers[channel].timer_id;
	uint32_t base = gpt_get_base_address(gpt_channel);

	/* Enable GPT clock */
	int ret = gpt_enable_clock(gpt_channel);

	if (ret != 0) {
		return ret;
	}

	/* Configure GPIO pin for timer output */
	ret = gpt_configure_gpio(timer_io_channels[channel].gpio_out);

	if (ret != 0) {
		/* Non-fatal for now, continue with timer config */
	}

	/* 1. Disable write protection using NuttX macros */
	putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, base + RA_GPT_GTWP_OFFSET);

	/* 2. Stop the timer if running */
	putreg32(0, base + RA_GPT_GTCR_OFFSET);

	/* 3. Clear the counter */
	putreg32(1 << gpt_channel, base + RA_GPT_GTCLR_OFFSET);

	/* 4. Calculate period for desired frequency
	 * Timer clock = PCLKD / Prescaler
	 * Period = (Timer clock / Frequency) - 1
	 */
	uint32_t prescaler = DEFAULT_PRESCALER;
	uint32_t timer_clock = BOARD_PCLKD_FREQUENCY / prescaler;
	uint32_t period = (timer_clock / frequency_hz) - 1;

	/* Store configuration for later use */
	gpt_config[channel].base = base;
	gpt_config[channel].period = period;
	gpt_config[channel].prescaler = prescaler;
	gpt_config[channel].gpt_channel = gpt_channel;
	gpt_config[channel].initialized = true;

	/* 5. Configure timer mode: Saw-wave PWM (up-counting), PCLKD/64 */
	uint32_t gtcr = GPT_GTCR_MD_SAW_WAVE_UP | GPT_GTCR_TPCS_PCLKD_64;
	putreg32(gtcr, base + RA_GPT_GTCR_OFFSET);

	/* 6. Set count direction to up */
	putreg32(GPT_GTUDDTYC_UD, base + RA_GPT_GTUDDTYC_OFFSET);

	/* 7. Configure I/O control - GTIOA output initial low, high on compare match */
	uint32_t gtior = GPT_GTIOR_GTIOA_INITIAL_LOW;
	putreg32(gtior, base + RA_GPT_GTIOR_OFFSET);

	/* 8. Set period for desired PWM frequency */
	putreg32(period, base + RA_GPT_GTPR_OFFSET);
	putreg32(period, base + RA_GPT_GTPBR_OFFSET);

	/* 9. Set initial duty cycle to neutral (1500us) */
	uint32_t initial_ccr = (PWM_DEFAULT_PULSE_US * period * frequency_hz) / 1000000;
	putreg32(initial_ccr, base + RA_GPT_GTCCRA_OFFSET);

	/* 10. Enable buffer operation */
	putreg32(0x03, base + RA_GPT_GTBER_OFFSET);

	/* 11. Start the timer */
	uint32_t gtcr_run = getreg32(base + RA_GPT_GTCR_OFFSET);
	putreg32(gtcr_run | GPT_GTCR_CST, base + RA_GPT_GTCR_OFFSET);

	/* 12. Re-enable write protection */
	putreg32(GPT_GTWP_PRKEY, base + RA_GPT_GTWP_OFFSET);

	return 0;
}

/**
 * @brief Set PWM pulse width in microseconds
 *
 * @param channel PWM channel (0-3)
 * @param pulse_us Pulse width in microseconds (1000-2000)
 * @return 0 on success, -1 on error
 */
int gpt_set_pwm_pulse(unsigned channel, uint16_t pulse_us)
{
	if (channel >= DIRECT_PWM_OUTPUT_CHANNELS || !gpt_config[channel].initialized) {
		return -EINVAL;
	}

	/* Clamp pulse width to valid range */
	if (pulse_us < PWM_MIN_PULSE_US) {
		pulse_us = PWM_MIN_PULSE_US;
	}
	if (pulse_us > PWM_MAX_PULSE_US) {
		pulse_us = PWM_MAX_PULSE_US;
	}

	/* Convert microseconds to timer counts
	 * CCR = (pulse_us * timer_frequency) / 1000000
	 * Where timer_frequency = PCLKD / prescaler
	 */
	uint32_t base = gpt_config[channel].base;
	uint32_t period = gpt_config[channel].period;
	uint32_t timer_freq = BOARD_PCLKD_FREQUENCY / gpt_config[channel].prescaler;
	uint32_t ccr = (pulse_us * timer_freq) / 1000000;

	/* Clamp to period */
	if (ccr > period) {
		ccr = period;
	}

	/* Write to compare register using NuttX offset definition */
	putreg32(ccr, base + RA_GPT_GTCCRA_OFFSET);

	return 0;
}

/**
 * @brief Set PWM frequency for a timer
 *
 * @param channel PWM channel
 * @param frequency_hz Desired frequency in Hz
 * @return 0 on success, negative on error
 */
int gpt_set_pwm_frequency(unsigned channel, unsigned frequency_hz)
{
	if (channel >= DIRECT_PWM_OUTPUT_CHANNELS || !gpt_config[channel].initialized) {
		return -EINVAL;
	}

	/* Calculate new period */
	uint32_t prescaler = gpt_config[channel].prescaler;
	uint32_t timer_clock = BOARD_PCLKD_FREQUENCY / prescaler;
	uint32_t period = (timer_clock / frequency_hz) - 1;

	/* Update hardware using NuttX register definitions */
	uint32_t base = gpt_config[channel].base;

	/* Disable write protection */
	putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, base + RA_GPT_GTWP_OFFSET);

	/* Update period registers */
	putreg32(period, base + RA_GPT_GTPR_OFFSET);
	putreg32(period, base + RA_GPT_GTPBR_OFFSET);

	/* Re-enable write protection */
	putreg32(GPT_GTWP_PRKEY, base + RA_GPT_GTWP_OFFSET);

	/* Update cached configuration */
	gpt_config[channel].period = period;

	return 0;
}

/**
 * @brief Initialize all GPT timers for ESC control
 *
 * @return 0 on success, negative on error
 */
int ra8_gpt_timer_init_all(void)
{
	int ret = 0;

	/* Initialize all configured PWM channels */
	for (unsigned i = 0; i < DIRECT_PWM_OUTPUT_CHANNELS; i++) {
		if (gpt_timer_init_pwm(i, PWM_DEFAULT_FREQUENCY_HZ) != 0) {
			ret = -1;
		}
	}

	return ret;
}

/**
 * @brief Deinitialize GPT timers
 *
 * Stops all GPT timers and marks them as uninitialized.
 * Uses NuttX register definitions from ra_gpt.h
 */
void ra8_gpt_timer_deinit_all(void)
{
	/* Stop all timers */
	for (unsigned i = 0; i < DIRECT_PWM_OUTPUT_CHANNELS; i++) {
		if (gpt_config[i].initialized) {
			uint32_t base = gpt_config[i].base;

			/* Disable write protection, stop timer, re-enable protection */
			putreg32(GPT_GTWP_PRKEY | GPT_GTWP_WP, base + RA_GPT_GTWP_OFFSET);
			putreg32(0, base + RA_GPT_GTCR_OFFSET);
			putreg32(GPT_GTWP_PRKEY, base + RA_GPT_GTWP_OFFSET);

			gpt_config[i].initialized = false;
		}
	}
}
