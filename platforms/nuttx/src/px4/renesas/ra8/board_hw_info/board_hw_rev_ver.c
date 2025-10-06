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
 * @file board_hw_rev_ver.c
 *
 * Board hardware revision/version for Renesas RA8
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/micro_hal.h>
#include <stdint.h>

#ifndef __EXPORT
#define __EXPORT
#endif

static const char hw_type_name[] = "FPB-RA8E1";

/************************************************************************************
 * Name: board_get_hw_type_name
 *
 * Description:
 *   Returns the board hardware type name
 *
 * Returned Value:
 *   A pointer to a string containing the hardware type name
 *
 ************************************************************************************/

__EXPORT const char *board_get_hw_type_name(void)
{
	return hw_type_name;
}

/************************************************************************************
 * Name: board_get_hw_version
 *
 * Description:
 *   Returns the board hardware version
 *
 * Returned Value:
 *   The hardware version as an integer (V1.0 = 1)
 *
 ************************************************************************************/

__EXPORT int board_get_hw_version(void)
{
	return 1; /* Version 1.0 */
}

/************************************************************************************
 * Name: board_get_hw_revision
 *
 * Description:
 *   Returns the board hardware revision
 *
 * Returned Value:
 *   The hardware revision as an integer
 *
 ************************************************************************************/

__EXPORT int board_get_hw_revision(void)
{
	return 0; /* Revision 0 */
}
