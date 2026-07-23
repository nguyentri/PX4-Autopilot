/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 ****************************************************************************/

/**
 * @file board_reset.c
 *
 * RZV2H board reset implementation
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/arch.h>
#include <stdint.h>

void board_reset(int status)
{
	/* Perform system reset */
	up_systemreset();
}
