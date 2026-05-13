/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
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
 * @file system_stubs.c
 *
 * RDK-RZV2H system stub functions for features not yet implemented
 */

#include <px4_platform_common/px4_config.h>
#include <nuttx/board.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>

#include "board_config.h"
/* board_config.h includes board_common.h at the end, so redundant include removed */

/* USB stubs - USB not available on this board */

__EXPORT int board_read_VBUS_state(void)
{
	return 0;  /* USB not powered */
}

/* Power monitor stubs - no power monitoring on this board initially */

__EXPORT int board_register_power_state_notification_cb(power_button_state_notification_t cb)
{
	return 0;
}

/* Safety button stub - no physical safety button */

#ifdef BOARD_HAS_NO_SAFETY_SWITCH
__EXPORT bool board_safety_button_pressed(void)
{
	return false;
}
#endif

/* Panic save stub */

void rzv_save_panic(int fileno, void *context, int length)
{
	(void)fileno;
	(void)context;
	(void)length;
	/* Not implemented - could save to backup RAM or external storage */
}

__EXPORT int pipe(int pipefd[2])
{
	(void)pipefd;
	errno = ENOSYS;
	return -1;
}
