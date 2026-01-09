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
 * @file board_config.h
 *
 * Renesas RDK-RZV2H IO Processor (CM33) configuration
 */

#pragma once

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

#if defined(__PX4_NUTTX)
#include <nuttx/config.h>
#endif

/* Board identification */
#if !defined(BOARD_OVERRIDE_UUID)
#define BOARD_OVERRIDE_UUID "RZV2H_IO_CM33"
#endif

/* SOC Architecture ID */
#ifndef PX4_SOC_ARCH_ID
#define PX4_SOC_ARCH_ID 0x0011  /* RZV2H CM33 */
#endif

/* Console is SCI1 (/dev/ttyS0) */
#define BOARD_CONSOLE_UART_BAUDRATE 115200

/* PWM Outputs (8 channels) */
#define DIRECT_PWM_OUTPUT_CHANNELS  8

/* Watchdog */
#define BOARD_HAS_WATCHDOG 1
#define WATCHDOG_TIMEOUT_MS 500

/* IPC Shared Memory */
#define PX4IO_IPC_RAM_BASE 0x70000000
#define PX4IO_IPC_RAM_SIZE 0x10000

/* Safety Switch */
#define GPIO_SAFETY_SWITCH_IN (0) /* Placeholder */

/* LEDs */
#define GPIO_LED_SAFETY (0) /* Placeholder */

#define BOARD_HAS_NO_RESET 1
#define BOARD_HAS_NO_BOOTLOADER 1

/* I2C buses - CM33 IO processor doesn't actively use I2C */
#ifndef PX4_NUMBER_I2C_BUSES
#define PX4_NUMBER_I2C_BUSES 1
#endif

/* SPI buses - CM33 IO processor doesn't use SPI (ESC control only) */
#define BOARD_SPI_BUS_MAX_BUS_ITEMS 1
/* SPI_BUS_MAX_BUS_ITEMS is defined by board_common.h based on BOARD_SPI_BUS_MAX_BUS_ITEMS */

#include <px4_platform_common/board_common.h>

__BEGIN_DECLS

/****************************************************************************************************
 * Public Types
 ****************************************************************************************************/

/****************************************************************************************************
 * Public data
 ****************************************************************************************************/

/****************************************************************************************************
 * Public Functions
 ****************************************************************************************************/

__END_DECLS
