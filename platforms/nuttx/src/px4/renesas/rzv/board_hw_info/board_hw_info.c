/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 ****************************************************************************/

/**
 * @file board_hw_info.c
 *
 * RZV2H board hardware info
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/board_common.h>
#include <stdint.h>
#include <string.h>

#include "board_config.h"

/* Undefine macros from board_common.h so we can implement the functions */
#undef board_get_hw_version
#undef board_get_hw_revision
#undef board_get_hw_type_name

/* Board identification string */
static const char board_name[] = "RDK-RZV2H";
static const char board_mcu[] = "R9A09G057";

int board_get_hw_version(void)
{
	return 0;
}

int board_get_hw_revision(void)
{
	return 0;
}

__attribute__((weak)) const char *board_get_hw_type_name(void)
{
	return board_name;
}

int board_get_px4_guid(px4_guid_t guid)
{
	uint8_t *out = guid;
	const uint16_t soc_arch_id = PX4_SOC_ARCH_ID;
	const size_t name_len = sizeof(board_name) - 1;
	size_t offset = 0;

	out[offset++] = (soc_arch_id >> 8) & 0xff;
	out[offset++] = soc_arch_id & 0xff;

	while (offset < PX4_GUID_BYTE_LENGTH - name_len && offset < PX4_GUID_BYTE_LENGTH) {
		out[offset++] = 0;
	}

	memcpy(&out[offset], board_name,
	       name_len < PX4_GUID_BYTE_LENGTH - offset ? name_len : PX4_GUID_BYTE_LENGTH - offset);

	return PX4_GUID_BYTE_LENGTH;
}

int board_mcu_version(char *rev, const char **revstr, const char **errata)
{
	if (rev) {
		*rev = 'A';
	}

	if (revstr) {
		*revstr = board_mcu;
	}

	if (errata) {
		*errata = NULL;
	}

	return 0;
}
