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
 * Renesas R-Car V4H Sparrow Hawk, PX4 on CR52-0.
 *
 * No sensors, outputs, LEDs, ADC or safety switch are wired to PX4 yet: the
 * SIH profile simulates every sensor and actuator. NSH runs on HSCIF1
 * (/dev/ttyS0); MAVLink TELEM1 on HSCIF3 (/dev/ttyS1, CN7 pins 8/10).
 */

#pragma once

#include <px4_platform_common/px4_config.h>
#include <nuttx/compiler.h>
#include <stdint.h>

#define PX4_SOC_ARCH_ID                 PX4_SOC_ARCH_ID_RCARV4H

#define BOARD_OVERRIDE_UUID             "RCARV4HCR520000" /* 15 characters plus the nul */

#define BOARD_HAS_NO_RESET              1  /* CR52 cannot reset itself or the SoC */
#define BOARD_HAS_NO_BOOTLOADER         1  /* Loaded by U-Boot rproc */
#define BOARD_TYPE_COMPLETE             90

#define PX4_UART_TELEM1                 "ttyS1"  /* HSCIF3 */

#define BOARD_ENABLE_CONSOLE_BUFFER     1

/* No I2C or SPI bus yet (CONFIG_I2C/CONFIG_SPI unset) */
#define PX4_NUMBER_I2C_BUSES            0

#define BOARD_HAS_NO_SAFETY_SWITCH      1

#define ADC_BATTERY_VOLTAGE_CHANNEL     -1
#define ADC_BATTERY_CURRENT_CHANNEL     -1
#define BOARD_NUMBER_BRICKS             1
#define BOARD_ADC_BRICK_VALID           0
#define BOARD_NUMBER_USB_BRICKS         0
#define BOARD_USB_VBUS_VALID            0

__BEGIN_DECLS

#ifndef __ASSEMBLY__

int board_app_initialize(uintptr_t arg);

#include <px4_platform_common/board_common.h>

#endif /* __ASSEMBLY__ */

__END_DECLS
