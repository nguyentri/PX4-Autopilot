/****************************************************************************
 *
 *   Copyright (c) 2024 PX4 Development Team. All rights reserved.
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
 * FPB-RA8E1 board early initialization
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
static const char hw_type[] = "FPB-RA8E1";

#include <nuttx/board.h>
#include <nuttx/spi/spi.h>
#include <nuttx/i2c/i2c_master.h>
#include <nuttx/sdio.h>
#include <nuttx/mmcsd.h>
#include <drivers/drv_sensor.h>
#include "ra_spi.h"

#include "board_config.h"

/* External function declarations */
extern struct spi_dev_s *px4_spibus_initialize(int bus);

/* No additional board-level sensor definitions required. Standard PX4 driver
 * identifiers from drivers/drv_sensor.h are used by spi.cpp to register the
 * devices on the shared sensor bus.
 */

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
 * Name: fpb_ra8e1_gpio_initialize
 *
 * Description:
 *   Called to configure all GPIOs for the board except those controlled by NuttX Drivers
 *
 ************************************************************************************/

static void fpb_ra8e1_gpio_initialize(void)
{
	/* Configure LEDs */
	px4_arch_configgpio(GPIO_nLED_RED);   /* LED1 */
	px4_arch_configgpio(GPIO_nLED_GREEN); /* LED2 */

	/* Configure SPI1 Chip Select pins - must be initialized before SPI bus */
	px4_arch_configgpio(GPIO_SPI1_CS0);   /* P408 - ICM20948 CS (active low) */
	px4_arch_configgpio(GPIO_SPI1_CS1);   /* P407 - BMP388 CS (active low) */

	/* Set CS pins high (inactive) initially */
	px4_arch_gpiowrite(GPIO_SPI1_CS0, true);  /* Deassert ICM20948 CS */
	px4_arch_gpiowrite(GPIO_SPI1_CS1, true);  /* Deassert BMP388 CS */

	/* Configure IMU data ready pin - driver will set up interrupt */
	px4_arch_configgpio(GPIO_SPI1_IMU_DRDY);

	/* Configure safety button */
	px4_arch_configgpio(GPIO_BTN_SAFETY);
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
		// Can't use syslog yet if init failed, use direct output
		return ret;
	}

	/* Now syslog is safe to use */
	syslog(LOG_INFO, "board_app_initialize: px4_platform_init() OK\n");

	/* configure LEDs */
	board_autoled_initialize();

	/* configure pins */
	fpb_ra8e1_gpio_initialize();

	/* Initialize timers for PWM/IO */
	fpb_ra8e1_timer_initialize();

	/* Initialize SPI buses for sensors */
	syslog(LOG_INFO, "board_app_initialize: Initializing SPI bus 1\n");
	struct spi_dev_s *spi1 = px4_spibus_initialize(1);
	if (spi1 == NULL) {
		syslog(LOG_ERR, "board_app_initialize: px4_spibus_initialize(1) returned NULL!\n");
	} else {
		syslog(LOG_INFO, "board_app_initialize: SPI bus 1 initialized OK\n");
	}

	/* Reset SPI buses to ensure clean state for sensor communication */
	syslog(LOG_INFO, "board_app_initialize: Resetting SPI buses\n");
	board_spi_reset(10, 0xffff);

	syslog(LOG_INFO, "board_app_initialize: Complete!\n");
	return OK;
}

/************************************************************************************
 * Name: ra8e1_boardinitialize
 *
 * Description:
 *   All RA8E1 architectures must provide the following entry point.  This entry point
 *   is called early in the initialization -- after all memory has been configured
 *   and mapped but before any devices have been initialized.
 *
 ************************************************************************************/

__EXPORT void ra8e1_boardinitialize(void)
{
	/* Reset PWM first thing */
	board_on_reset(-1);

	/* configure read po */
	fpb_ra8e1_gpio_initialize();
}

__EXPORT const char *board_get_hw_type_name()
{
	return (const char *) hw_type;
}
