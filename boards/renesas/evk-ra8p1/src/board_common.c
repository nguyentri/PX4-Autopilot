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
 * @file board_common.c
 *
 * EVK-RA8P1 board common functions
 *
 * Note: Functions provided by platform (platforms/nuttx/src/px4/renesas/ra8/):
 *   - board_get_hw_type_name()  -> board_hw_info/board_hw_rev_ver.c
 *   - board_get_hw_version()    -> board_hw_info/board_hw_rev_ver.c
 *   - board_get_hw_revision()   -> board_hw_info/board_hw_rev_ver.c
 *   - board_get_uuid32()        -> platforms/common/board_identity.c
 *   - board_get_px4_guid()      -> platforms/common/board_identity.c
 *
 * This file only provides board-specific overrides not covered by platform.
 */

#include <stdint.h>
#include <stdbool.h>

#include "board_config.h"  /* For PX4_SPI_BUS_SENSORS, PX4_I2C_BUS_EXPANSION */
#include <px4_platform_common/board_common.h>  /* For enum board_bus_types */

/* Forward declarations for LED functions */
extern void led_init(void);
extern void led_on(int led);
extern void led_off(int led);
extern void led_toggle(int led);

/************************************************************************************
 * Power management functions
 ************************************************************************************/

__EXPORT int board_power_off(int status)
{
	(void)status; /* Unused */
	/* Basic power off - put system in lowest power state */
	/* TODO: Implement actual power management for RA8P1 */
	while (1) {
		/* Stay in infinite loop until reset */
	}
	return 0; /* Never reached */
}

__EXPORT int board_register_power_state_notification_cb(power_button_state_notification_t cb)
{
	(void)cb; /* Unused - no power button on this board */
	return 0;
}

/************************************************************************************
 * Bus availability functions
 ************************************************************************************/

__EXPORT bool board_has_bus(enum board_bus_types type, uint32_t bus)
{
	switch (type) {
	case BOARD_SPI_BUS:
		/* Check against configured SPI bus from board_config.h */
		return (bus == PX4_SPI_BUS_SENSORS);

	case BOARD_I2C_BUS:
		/* Check against configured I2C bus from board_config.h */
		return (bus == PX4_I2C_BUS_EXPANSION);

	case BOARD_INVALID_BUS:
	default:
		return false;
	}
}

/************************************************************************************
 * Board initialization
 ************************************************************************************/

__EXPORT void ra_board_initialize(void)
{
	/* Basic board initialization - already done in board_app_initialize */
	/* This is called from NuttX startup */
}

/************************************************************************************
 * AutoLED functions
 ************************************************************************************/

__EXPORT void board_autoled_initialize(void)
{
	/* Initialize LEDs - use existing LED init function */
	led_init();
}

__EXPORT void board_autoled_on(int led)
{
	/* Turn on LED for system indication */
    if (led >= NLEDS) {
        return;
    }
	led_on(led);
}

__EXPORT void board_autoled_off(int led)
{
	/* Turn off LED for system indication */
    if (led >= NLEDS) {
        return;
    }
	led_off(led);
}
__EXPORT void board_autoled_toggle(int led)
{
	/* Turn off LED for system indication */
    if (led >= NLEDS) {
        return;
    }
	led_toggle(led);
}