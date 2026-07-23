/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
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
 * RDK-RZV2H IO Processor (CR8 Core 1) autoLED control.
 *
 * NuttX arm_initialize()/arm_sigdeliver() call board_autoled_on/off
 * unconditionally, so every image must provide these symbols. The CR8-1 I/O
 * coprocessor has no dedicated autoLED GPIOs wired, so each body reduces to a
 * no-op via the GPIO_nLED_* guards (same pattern as the primary RDK-RZV2H
 * board). Define GPIO_nLED_* in board_config.h to drive real LEDs.
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/board.h>
#include <stdbool.h>

#include "board_config.h"

/* Undefine NuttX empty macros so we can provide implementation */
#undef board_autoled_initialize
#undef board_autoled_on
#undef board_autoled_off

__EXPORT void board_autoled_initialize(void)
{
#ifdef GPIO_nLED_1
	px4_arch_configgpio(GPIO_nLED_1);
#endif
#ifdef GPIO_nLED_2
	px4_arch_configgpio(GPIO_nLED_2);
#endif
}

__EXPORT void board_autoled_on(int led)
{
	switch (led) {
	case 0:
#ifdef GPIO_nLED_1
		px4_arch_gpiowrite(GPIO_nLED_1, false);  /* Active low - false turns ON */
#endif
		break;

	case 1:
#ifdef GPIO_nLED_2
		px4_arch_gpiowrite(GPIO_nLED_2, false);
#endif
		break;

	default:
		break;
	}
}

__EXPORT void board_autoled_off(int led)
{
	switch (led) {
	case 0:
#ifdef GPIO_nLED_1
		px4_arch_gpiowrite(GPIO_nLED_1, true);   /* Active low - true turns OFF */
#endif
		break;

	case 1:
#ifdef GPIO_nLED_2
		px4_arch_gpiowrite(GPIO_nLED_2, true);
#endif
		break;

	default:
		break;
	}
}
