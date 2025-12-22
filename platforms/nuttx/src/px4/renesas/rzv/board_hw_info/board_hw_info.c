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

const char *board_get_hw_type_name(void)
{
	return board_name;
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
