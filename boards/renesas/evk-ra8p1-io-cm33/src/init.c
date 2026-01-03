/****************************************************************************
 *
 *   Copyright (C) 2012-2025 PX4 Development Team. All rights reserved.
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
 * @file init.c
 *
 * RA8P1 CM33 IO processor early startup code.
 * This file implements board initialization for the Cortex-M33 core
 * running as PX4IO coprocessor.
 *
 * Code here is run before the rcS script is invoked; it should start required
 * subsystems and perform board-specific initialization.
 */

/****************************************************************************
 * Included Files
 ****************************************************************************/

#include <px4_platform_common/px4_config.h>

#include <stdbool.h>
#include <stdio.h>
#include <debug.h>
#include <errno.h>
#include <syslog.h>

#include <nuttx/config.h>
#include <nuttx/board.h>

#include "board_config.h"
#include <arch/board/board.h>

/****************************************************************************
 * Pre-Processor Definitions
 ****************************************************************************/

/****************************************************************************
 * Protected Functions
 ****************************************************************************/

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/************************************************************************************
 * Name: ra_board_initialize
 *
 * Description:
 *   All RA8 architectures must provide the following entry point. This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ************************************************************************************/

__EXPORT void ra_board_initialize(void)
{
/* Configure GPIOs for LEDs */
#ifdef CONFIG_ARCH_LEDS
/* LED configurations would go here using RA8 GPIO API */
#endif

/* Configure GPIO for safety button */
#ifdef GPIO_BTN_SAFETY
/* Safety button GPIO config using RA8 GPIO API */
#endif

/* PWM outputs will be configured by the pwm_out driver */

/* IPC shared memory is configured via linker script and MPU */
}

/************************************************************************************
 * Name: board_app_initialize
 *
 * Description:
 *   Perform application-specific initialization. This function is called after
 *   basic initialization is complete.
 *
 ************************************************************************************/

__EXPORT int board_app_initialize(uintptr_t arg)
{
syslog(LOG_INFO, "[init] RA8P1 CM33 IO processor board initialization\n");

#ifdef IPC_SHMEM_BASE
syslog(LOG_INFO, "[init] IPC shared memory at 0x%08x (size: %d bytes)\n",
       IPC_SHMEM_BASE, IPC_SHMEM_SIZE);
#endif

return OK;
}

/************************************************************************************
 * Name: board_late_initialize
 *
 * Description:
 *   If CONFIG_BOARD_LATE_INITIALIZE is selected, then an additional
 *   initialization call will be performed in the boot-up sequence to a function
 *   called board_late_initialize().  board_late_initialize() will be called
 *   immediately after up_initialize() is called and just before the initial
 *   application is started.
 *
 ************************************************************************************/

#ifdef CONFIG_BOARD_LATE_INITIALIZE
__EXPORT void board_late_initialize(void)
{
/* Additional late initialization can go here */
}
#endif
