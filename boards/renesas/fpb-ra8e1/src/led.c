/****************************************************************************
 *
 *   Copyright (c) 2024 PX4 Development Team. All rights reserved.
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
 * @file led.c
 *
 * LED backend.
 */

#include <px4_platform_common/px4_config.h>

#include <stdbool.h>

#include "board_config.h"

#include <nuttx/board.h>
#include <arch/board/board.h>

/*
 * Ideally we'd be able to get these from up_internal.h,
 * but since we want to be able to disable the NuttX use
 * of leds for system indication at will and there is no
 * separate switch, we need to build independent of the
 * CONFIG_ARCH_LEDS configuration switch.
 */
extern void led_init(void);
extern void led_on(int led);
extern void led_off(int led);
extern void led_toggle(int led);

static bool _led_inited = false;

__EXPORT void led_init()
{
	/* Configure LED1 & LED2 GPIOs for output */
	px4_arch_configgpio(GPIO_nLED_RED);
	px4_arch_configgpio(GPIO_nLED_GREEN);
	_led_inited = true;
}

static void phy_set_led(int led, bool state)
{
	/* Pull LED low to switch on */
	if (led == 0) {
		px4_arch_gpiowrite(GPIO_nLED_RED, !state);
	}

	if (led == 1) {
		px4_arch_gpiowrite(GPIO_nLED_GREEN, !state);
	}
}

__EXPORT void led_on(int led)
{
	if (!_led_inited) {
		led_init();
	}

	phy_set_led(led, true);
}

__EXPORT void led_off(int led)
{
	if (!_led_inited) {
		led_init();
	}

	phy_set_led(led, false);
}

__EXPORT void led_toggle(int led)
{
	if (!_led_inited) {
		led_init();
	}

	if (led == 0) {
		phy_set_led(led, !px4_arch_gpioread(GPIO_nLED_RED));
	}

	if (led == 1) {
		phy_set_led(led, !px4_arch_gpioread(GPIO_nLED_GREEN));
	}
}
