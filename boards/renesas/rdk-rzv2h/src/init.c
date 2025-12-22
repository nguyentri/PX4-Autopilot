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
 * @file init.c
 *
 * RDK-RZV2H board early initialization
 */

#include <px4_platform_common/init.h>
#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/console_buffer.h>
#include <px4_platform_common/board_common.h>
#include <px4_arch/io_timer.h>

#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <debug.h>
#include <syslog.h>

/* Hardware version definition */
static const char hw_type[] = "RDK-RZV2H";

#if defined(__PX4_NUTTX)
#include <nuttx/board.h>
#include <nuttx/spi/spi.h>
#include <nuttx/i2c/i2c_master.h>
#include <drivers/drv_sensor.h>
#include "rzv_gpio.h"
#include <arch/board/board.h>
#endif

#include "board_config.h"
/* Undefine macros from board_common.h so we can implement the functions */
#undef board_get_hw_type_name

/* External function declarations */
extern struct spi_dev_s *px4_spibus_initialize(int bus);
extern struct i2c_master_s *px4_i2cbus_initialize(int bus);

/****************************************************************************
 * Protected Functions
 ****************************************************************************/

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/************************************************************************************
 * Name: board_peripheral_reset
 *
 * Description:
 *   Called to reset peripherals on the board.
 *
 ************************************************************************************/

__EXPORT void board_peripheral_reset(int ms)
{
	/* set the peripheral rails off */

	/* wait for the peripheral rail to reach GND */
	usleep(ms * 1000);

	/* re-enable power */

	/* switch the peripheral rail back on */
}

/************************************************************************************
 * Name: board_on_reset
 *
 * Description:
 *   Optionally provided function called on entry to board_system_reset
 *   It should perform any house keeping prior to the rest.
 *
 * Input Parameters:
 *   status - 1 if resetting to boot loader
 *            0 if just resetting
 *
 ************************************************************************************/

__EXPORT void board_on_reset(int status)
{
	/* configure the GPIO pins to outputs and keep them low */

	if (status >= 0) {
		up_mdelay(6);
	}
}

/************************************************************************************
 * Name: rdk_rzv2h_gpio_initialize
 *
 * Description:
 *   Called to configure all GPIOs for the board except those controlled by NuttX Drivers
 *
 ************************************************************************************/

static void rdk_rzv2h_gpio_initialize(void)
{
	/* Configure LEDs */
#ifdef GPIO_nLED_1
	px4_arch_configgpio(GPIO_nLED_1);
#endif
#ifdef GPIO_nLED_2
	px4_arch_configgpio(GPIO_nLED_2);
#endif
#ifdef GPIO_nLED_3
	px4_arch_configgpio(GPIO_nLED_3);
#endif
#ifdef GPIO_nLED_4
	px4_arch_configgpio(GPIO_nLED_4);
#endif

	/* Configure MPU9250 DRDY interrupt pin */
#ifdef BOARD_MPU9250_DRDY_GPIO
	px4_arch_configgpio(BOARD_MPU9250_DRDY_GPIO);
#endif

	/* Configure UART pins */
#ifdef BOARD_SCI0_TXD_GPIO
	px4_arch_configgpio(BOARD_SCI0_TXD_GPIO);
#endif
#ifdef BOARD_SCI0_RXD_GPIO
	px4_arch_configgpio(BOARD_SCI0_RXD_GPIO);
#endif
#ifdef BOARD_SCI1_TXD_GPIO
	px4_arch_configgpio(BOARD_SCI1_TXD_GPIO);
#endif
#ifdef BOARD_SCI1_RXD_GPIO
	px4_arch_configgpio(BOARD_SCI1_RXD_GPIO);
#endif
#ifdef BOARD_SCI2_TXD_GPIO
	px4_arch_configgpio(BOARD_SCI2_TXD_GPIO);
#endif
#ifdef BOARD_SCI2_RXD_GPIO
	px4_arch_configgpio(BOARD_SCI2_RXD_GPIO);
#endif
#ifdef BOARD_SCI3_TXD_GPIO
	px4_arch_configgpio(BOARD_SCI3_TXD_GPIO);
#endif
#ifdef BOARD_SCI3_RXD_GPIO
	px4_arch_configgpio(BOARD_SCI3_RXD_GPIO);
#endif

	/* Configure I2C7 pins for barometer */
#ifdef BOARD_I2C7_SDA_GPIO
	px4_arch_configgpio(BOARD_I2C7_SDA_GPIO);
#endif
#ifdef BOARD_I2C7_SCL_GPIO
	px4_arch_configgpio(BOARD_I2C7_SCL_GPIO);
#endif
}

/************************************************************************************
 * Name: board_app_initialize
 *
 * Description:
 *   Perform application specific initialization.  This function is never called
 *   directly from application code, but only indirectly via the (non-standard)
 *   boardctl() interface using the command BOARDIOC_INIT.
 *
 * Input Parameters:
 *   arg - The boardctl() argument is passed to the board_app_initialize()
 *         implementation without modification.  The argument has no
 *         meaning to NuttX; the meaning of the argument is a contract
 *         between the board-specific initialization logic and the
 *         matching application logic.  The value could be such things as a
 *         mode enumeration value, a set of DIP switch settings, a pointer
 *         to other configuration data read from a file or serial FLASH, or
 *         whatever you would like to do with it.  Every implementation
 *         should accept zero/NULL as a default configuration.
 *
 * Returned Value:
 *   Zero (OK) is returned on success; a negated errno value is returned on
 *   any failure to indicate the nature of the failure.
 *
 ************************************************************************************/

__EXPORT int board_app_initialize(uintptr_t arg)
{
	/* Initialize PX4 platform FIRST - this sets up all core infrastructure */
	/* This includes: HRT, console buffer, work queues, params, uORB */
	int ret = px4_platform_init();

	if (ret != OK) {
		syslog(LOG_ERR, "board_app_initialize: px4_platform_init() failed with error %d\n", ret);
		return ret;
	}

	/* configure LEDs */
	board_autoled_initialize();

	/* configure pins */
	rdk_rzv2h_gpio_initialize();

	/* Initialize timers for PWM/IO */
	rdk_rzv2h_timer_initialize();

	/* Initialize SPI bus for IMU sensor */
#ifdef CONFIG_RZV_SPI
	struct spi_dev_s *spi0 = px4_spibus_initialize(BOARD_MPU9250_BUS);
	if (spi0 == NULL) {
		syslog(LOG_ERR, "board_app_initialize: px4_spibus_initialize(%d) returned NULL!\n", BOARD_MPU9250_BUS);
	}
#endif

	/* Initialize I2C bus for barometer sensor */
#ifdef CONFIG_RZV_I2C
	struct i2c_master_s *i2c7 = px4_i2cbus_initialize(PX4_I2C_BUS_EXPANSION);
	if (i2c7 == NULL) {
		syslog(LOG_ERR, "board_app_initialize: px4_i2cbus_initialize(%d) returned NULL!\n", PX4_I2C_BUS_EXPANSION);
	}
#endif

	/* Reset SPI buses to ensure clean state for sensor communication */
	board_spi_reset(10, 0xffff);

	return OK;
}

/************************************************************************************
 * Name: rzv_board_initialize
 *
 * Description:
 *   All RZV architectures must provide the following entry point.  This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ************************************************************************************/

__EXPORT void rzv_board_initialize(void)
{
	/* Reset PWM first thing */
	board_on_reset(-1);

	/* Configure GPIOs */
	rdk_rzv2h_gpio_initialize();
}

__EXPORT const char *board_get_hw_type_name(void)
{
	return (const char *) hw_type;
}
