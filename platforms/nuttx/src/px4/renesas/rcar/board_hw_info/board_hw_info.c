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
 * @file board_hw_info.c
 *
 * R-Car V4H board identity: GUID and MCU version.  The CR52 has no unique
 * ID register PX4 can read, so the GUID is the SoC id and the board name.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/board_common.h>
#include <stdint.h>
#include <string.h>

#include "board_config.h"

#ifndef BOARD_HW_TYPE_NAME
#  define BOARD_HW_TYPE_NAME "R-CAR-V4H"
#endif

static const char board_name[] = BOARD_HW_TYPE_NAME;
static const char board_mcu[] = "R8A779G3";

int board_get_px4_guid(px4_guid_t guid)
{
	uint8_t *out = guid;
	const uint16_t soc_arch_id = PX4_SOC_ARCH_ID_RCARV4H;
	size_t name_len = sizeof(board_name) - 1;
	size_t offset = 0;

	memset(out, 0, PX4_GUID_BYTE_LENGTH);
	out[offset++] = (soc_arch_id >> 8) & 0xff;
	out[offset++] = soc_arch_id & 0xff;

	if (name_len > PX4_GUID_BYTE_LENGTH - offset) {
		name_len = PX4_GUID_BYTE_LENGTH - offset;
	}

	/* Right-align the name, as the other Renesas ports do */
	memcpy(&out[PX4_GUID_BYTE_LENGTH - name_len], board_name, name_len);
	return PX4_GUID_BYTE_LENGTH;
}

int board_mcu_version(char *rev, const char **revstr, const char **errata)
{
	if (rev) {
		*rev = '?';
	}

	if (revstr) {
		*revstr = board_mcu;
	}

	if (errata) {
		*errata = NULL;
	}

	return 0;
}
