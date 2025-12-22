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
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

/* Define __EXPORT for compatibility */
#ifndef __EXPORT
#define __EXPORT
#endif

/* Define board bus types for compatibility */
enum board_bus_types {
	BOARD_INVALID_BUS = 0,
	BOARD_SPI_BUS = 1,
	BOARD_I2C_BUS = 2
};

/* Forward declarations for LED functions */
extern void led_init(void);
extern void led_on(int led);
extern void led_off(int led);

/************************************************************************************
 * Board identification functions
 ************************************************************************************/

__EXPORT uint32_t board_get_uuid32(void)
{
	/* Return a simple unique ID based on board type for now */
	return 0x5A8F1001; /* EVK-RA8P1 identifier */
}

__EXPORT void board_get_px4_guid(uint8_t *guid)
{
	/* Generate a simple GUID for the board */
	uint32_t uuid = board_get_uuid32();

	memset(guid, 0, 16);
	guid[0] = (uuid >> 24) & 0xFF;
	guid[1] = (uuid >> 16) & 0xFF;
	guid[2] = (uuid >> 8) & 0xFF;
	guid[3] = uuid & 0xFF;
	guid[4] = 0x5A; /* Board family identifier */
	guid[5] = 0x8E;
	guid[6] = 0x10;
	guid[7] = 0x01;
}

__EXPORT void board_get_px4_guid_formated(char *s, size_t len)
{
	uint8_t guid[16];
	board_get_px4_guid(guid);

	snprintf(s, len, "%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X",
		guid[0], guid[1], guid[2], guid[3],
		guid[4], guid[5], guid[6], guid[7],
		guid[8], guid[9], guid[10], guid[11],
		guid[12], guid[13], guid[14], guid[15]);
}

__EXPORT uint32_t board_get_hw_version(void)
{
	/* Return hardware version - version 1.0 */
	return 0x00010000;
}

__EXPORT uint32_t board_get_hw_revision(void)
{
	/* Return hardware revision - revision A */
	return 0x00000001;
}

__EXPORT const char *board_mcu_version(void)
{
	return "RA8P1";
}

/************************************************************************************
 * Power management functions
 ************************************************************************************/

__EXPORT void board_power_off(void)
{
	/* Basic power off - put system in lowest power state */
	/* TODO: Implement actual power management for RA8P1 */
	while (1) {
		/* Stay in infinite loop until reset */
	}
}

__EXPORT int board_register_power_state_notification_cb(void *cb)
{
	/* Power state notification callback registration */
	(void)cb; /* Unused for now */
	return 0; /* Success */
}

/************************************************************************************
 * Bus availability functions
 ************************************************************************************/

__EXPORT bool board_has_bus(enum board_bus_types type, uint32_t bus)
{
	switch (type) {
	case BOARD_SPI_BUS:
		/* We have SPI0 bus */
		return (bus == 0);

	case BOARD_I2C_BUS:
		/* We have I2C0 */
		return (bus == 0);

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
	led_on(led);
}

__EXPORT void board_autoled_off(int led)
{
	/* Turn off LED for system indication */
	led_off(led);
}
