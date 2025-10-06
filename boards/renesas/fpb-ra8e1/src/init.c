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
#include <px4_arch/io_timer.h>

#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <debug.h>

/* Hardware version definition */
static const char hw_type[] = "FPB-RA8E1";

#include <nuttx/board.h>
#include <nuttx/spi/spi.h>
#include <nuttx/i2c/i2c_master.h>
#include <nuttx/sdio.h>
#include <nuttx/mmcsd.h>
#include "ra_spi.h"

#include "board_config.h"

/****************************************************************************
 * Pre-Processor Definitions
 ****************************************************************************/
#define DRV_IMU_DEVTYPE_ICM20948  0x28
#define DRV_BARO_DEVTYPE_BMP388   0x67

/* NuttX SPI device IDs - must match order in spi.cpp px4_spi_buses array */
#define NUTTX_SPI_ICM20948_DEVID  0  /* First device in spi.cpp */
#define NUTTX_SPI_BMP388_DEVID    1  /* Second device in spi.cpp */

/****************************************************************************
 * Private Variables
 ****************************************************************************/

/* No private variables needed - driver handles interrupts internally */

/****************************************************************************
 * Private Functions
 ****************************************************************************/

/* No private functions needed - driver handles interrupts internally */

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
	syslog(LOG_DEBUG, "reset done, %d ms", ms);

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
	/* Power on Peripherals, board_peripheral_reset called by px4_platform_init()
	 * that is called from board_late_initialize()
	 */

	/* configure LEDs */
	board_autoled_initialize();

	/* configure pins */
	fpb_ra8e1_gpio_initialize();

	/* Initialize PX4 platform (this starts the work queue manager) */
	px4_platform_init();

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

__EXPORT void board_gpio_init(void){
	fpb_ra8e1_gpio_initialize();
}


/* fpb_ra8e1_spi_select is no longer needed - functionality moved to ra_spi_select */

__EXPORT bool fpb_ra8e1_spi_drdy_read(void)
{
	/* Read the ICM20948 data ready pin directly */
	return px4_arch_gpioread(GPIO_SPI1_IMU_DRDY);
}

__EXPORT void fpb_ra8e1_spi_gpio_init(void)
{
	/* Initialize SPI-related GPIO pins for FPB-RA8E1 board */
	/* SPI GPIO initialization is handled by fpb_ra8e1_gpio_initialize() */
	/* This is a stub for specific SPI GPIO setup if needed */
}

__EXPORT void fpb_ra8e1_spi_select(uint32_t devid, bool selected)
{
	/* Handle chip select for SPI devices based on device ID */
	/* This functionality is moved to ra_spi_select but kept for compatibility */
	(void)devid;    /* Suppress unused parameter warning */
	(void)selected; /* Suppress unused parameter warning */
}





/************************************************************************************
 * NuttX SPI Driver Interface Functions
 ************************************************************************************/

/**
 * Name: ra_spi_select
 *
 * Description:
 *   Enable/disable the SPI chip select - required by NuttX RA8 SPI driver
 */
void ra_spi_select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
	syslog(LOG_INFO, "ra_spi_select: devid=0x%x, selected=%d", (unsigned)devid, (int)selected);

	/* Extract the actual device type from PX4 device ID */
	uint32_t device_type = devid & 0xFFFF;  /* Lower 16 bits contain the device type */
	syslog(LOG_INFO, "ra_spi_select: extracted device_type=0x%x", (unsigned)device_type);

	/* Handle chip select for SPI devices based on PX4 device types */
	switch (device_type) {
	case DRV_IMU_DEVTYPE_ICM20948: /* ICM20948 */
		syslog(LOG_INFO, "ra_spi_select: ICM20948 CS, selected=%d", (int)selected);
		px4_arch_gpiowrite(GPIO_SPI1_CS0, !selected);
		break;

	case DRV_BARO_DEVTYPE_BMP388: /* BMP388 */
		syslog(LOG_INFO, "ra_spi_select: BMP388 CS, selected=%d", (int)selected);
		px4_arch_gpiowrite(GPIO_SPI1_CS1, !selected);
		break;

	default:
		syslog(LOG_INFO, "ra_spi_select: Unknown device_type 0x%x", (unsigned)device_type);
		break;
	}
}

/**
 * Name: ra_spi_status
 *
 * Description:
 *   Return the SPI status - required by NuttX RA8 SPI driver
 */
uint8_t ra_spi_status(struct spi_dev_s *dev, uint32_t devid)
{
	uint8_t status = 0;

	syslog(LOG_INFO, "ra_spi_status: devid=0x%x", (unsigned)devid);

	/* Extract the actual device type from PX4 device ID */
	uint32_t device_type = devid & 0xFFFF;  /* Lower 16 bits contain the device type */
	syslog(LOG_INFO, "ra_spi_status: extracted device_type=0x%x", (unsigned)device_type);

	/* Return device-specific status based on PX4 device types */
	switch (device_type) {
	case DRV_IMU_DEVTYPE_ICM20948: /* ICM20948 */
		syslog(LOG_INFO, "ra_spi_status: ICM20948 device");
		/* ICM20948 is always present if configured */
		status = 1; /* SPI_STATUS_PRESENT equivalent */
		break;

	case DRV_BARO_DEVTYPE_BMP388: /* BMP388 */
		syslog(LOG_INFO, "ra_spi_status: BMP388 device");
		/* BMP388 is always present if configured */
		status = 1; /* SPI_STATUS_PRESENT equivalent */
		break;

	default:
		syslog(LOG_INFO, "ra_spi_status: Unknown device_type 0x%x", (unsigned)device_type);
		status = 0;
		break;
	}

	syslog(LOG_INFO, "ra_spi_status: returning status=0x%x", (unsigned)status);
	return status;
}

/************************************************************************************
 * Name: fpb_ra8e1_spibus_initialize
 *
 * Description:
 *   Initialize the SPI bus for the board - called by PX4 HAL
 *
 ************************************************************************************/

struct spi_dev_s *fpb_ra8e1_spibus_initialize(int bus)
{
	struct spi_dev_s *spi_dev;

	syslog(LOG_INFO, "fpb_ra8e1_spibus_initialize: Initializing SPI bus %d", bus);

	/* Call the NuttX RA8 SPI driver initialization */
	spi_dev = ra_spibus_initialize(bus);

	if (spi_dev) {
		syslog(LOG_INFO, "fpb_ra8e1_spibus_initialize: Successfully initialized SPI bus %d", bus);
	} else {
		syslog(LOG_ERR, "fpb_ra8e1_spibus_initialize: Failed to initialize SPI bus %d", bus);
	}

	return spi_dev;
}
