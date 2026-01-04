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
 * @file init.c
 *
 * Renesas RDK-RZV2H IO Processor (CM33) initialization
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/init.h>
#include <nuttx/board.h>
#include <nuttx/arch.h>
#include <nuttx/leds/userled.h>

#include "board_config.h"

/****************************************************************************************************
 * Public Functions
 ****************************************************************************************************/

/****************************************************************************************************
 * Name: board_app_initialize
 ****************************************************************************************************/
int board_app_initialize(uintptr_t arg)
{
    /* Initialize peripherals */

    /* Initialize PWM/DShot */
#ifdef CONFIG_PWM
    /* board_pwm_initialize(); */
#endif

    return 0;
}


/****************************************************************************
 * Name: rzv_board_initialize
 *
 * Description:
 *   All RZV architectures must provide the following entry point.  This
 *   entry point is called early in the initialization -- after clocks and
 *   memory have been configured but before any devices have been
 *   initialized.
 *
 ****************************************************************************/

void rzv_board_initialize(void)
{
  /* Minimal initialization for CM33 IO processor */

  /* No LEDs to configure - CONFIG_ARCH_LEDS is disabled */

  /* GPIO and peripheral initialization will be done in board_app_initialize() */
}
