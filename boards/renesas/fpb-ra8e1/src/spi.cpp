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
 * @file spi.cpp
 *
 * Board-specific SPI functions.
 */

#include <px4_arch/spi_hw_description.h>
#include <px4_platform_common/px4_config.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_sensor.h>
#include <nuttx/spi/spi.h>
#include "board_config.h"
#include "ra_gpio.h"

#include <lib/drivers/device/Device.hpp>
#include <stdint.h>
#include <stdbool.h>
#include <px4_platform_common/log.h>
#include <syslog.h>

// SPI Status definitions
#ifndef SPI_STATUS_PRESENT
#define SPI_STATUS_PRESENT  0x01
#endif

// Debug macro for SPI operations
#define SPI_DEBUG(fmt, ...) syslog(LOG_INFO, "SPI_DBG: " fmt "\n", ##__VA_ARGS__)

// Use predefined GPIO macros from board_config.h for GY-912 SPI pins
// GPIO_SPI1_CS0 (P408) - ICM20948 CS
// GPIO_SPI1_CS1 (P407) - BMP388 CS
// GPIO_SPI1_IMU_DRDY (P409) - ICM20948 Data Ready

// GY-912 10DOF sensor module configuration
// Contains ICM-20948 (9DOF IMU) and BMP388 (barometric pressure sensor)
//
// Hardware connections on FPB-RA8E1:
// - ICM-20948: CS=P408, DRDY=P409 (9DOF IMU: gyro + accel + mag)
// - BMP388:    CS=P407            (barometric pressure sensor)
// - SPI Bus:   SPI1 (1MHz default, up to 7MHz for ICM20948, 10MHz for BMP388)
constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
	initSPIBus(SPI::Bus::SPI1, {
		// ICM-20948: 9DOF IMU (gyroscope, accelerometer, magnetometer)
		initSPIDevice(DRV_IMU_DEVTYPE_ICM20948, SPI::CS{GPIO::Port4, GPIO::Pin8}, SPI::DRDY{GPIO::Port4, GPIO::Pin9}),

		// BMP388: Barometric pressure sensor
		initSPIDevice(DRV_BARO_DEVTYPE_BMP388, SPI::CS{GPIO::Port4, GPIO::Pin7}),
	}),
};

static constexpr bool unused = validateSPIConfig(px4_spi_buses);

/************************************************************************************
 * GY-912 Board-specific SPI Functions
 ************************************************************************************/

/**
 * Name: fpb_ra8e1_spi_drdy_read
 *
 * Description:
 *   Read ICM20948 data ready pin for GY-912 module
 */
bool fpb_ra8e1_spi_drdy_read()
{
	/* Read the ICM20948 data ready pin directly using predefined GPIO macro */
	return ra_gpioread(GPIO_SPI1_IMU_DRDY);
}

/**
 * Name: ra_spi_select
 *
 * Description:
 *   Enable/disable the SPI chip select - required by NuttX RA8 SPI driver
 *   Handles GY-912 module sensors (ICM20948 + BMP388)
 *
 * Input Parameters:
 *   dev - SPI device structure
 *   devid - Device ID (0 for ICM20948, 1 for BMP388)
 *   selected - true to assert CS (active low), false to deassert
 */
extern "C" void ra_spi_select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
	SPI_DEBUG("ra_spi_select: devid=%lu selected=%d", (unsigned long)devid, selected);

	/* Handle chip select for GY-912 SPI devices using predefined GPIO macros */
	/* Device ID determines which CS pin to control */
	switch (devid) {
	case 0: /* First SPI device - ICM20948 on CS0 (P408) */
		SPI_DEBUG("  -> Controlling CS0 (P408) for ICM20948");
		ra_gpiowrite(GPIO_SPI1_CS0, !selected);  /* Active low CS */
		break;

	case 1: /* Second SPI device - BMP388 on CS1 (P407) */
		SPI_DEBUG("  -> Controlling CS1 (P407) for BMP388");
		ra_gpiowrite(GPIO_SPI1_CS1, !selected);  /* Active low CS */
		break;

	default:
		SPI_DEBUG("  -> Unknown devid, no action taken");
		/* Unknown device ID - do nothing */
		break;
	}
}

/**
 * Name: ra_spi_status
 *
 * Description:
 *   Return the SPI status - required by NuttX RA8 SPI driver
 *   Returns status for GY-912 module sensors
 *
 * Input Parameters:
 *   dev - SPI device structure (unused)
 *   devid - Device ID (0 for ICM20948, 1 for BMP388)
 *
 * Returned Value:
 *   SPI_STATUS_PRESENT for configured devices, 0 for unknown devices
 */
extern "C" uint8_t ra_spi_status(struct spi_dev_s *dev, uint32_t devid)
{
	(void)dev; /* Unused parameter */

	uint8_t status = 0;

	/* For GY-912 module, all configured SPI devices are present */
	/* Return present status for configured device IDs */
	switch (devid) {
	case 0: /* ICM20948 9DOF IMU on CS0 */
		status = SPI_STATUS_PRESENT;
		SPI_DEBUG("ra_spi_status: devid=0 (ICM20948) -> PRESENT");
		break;

	case 1: /* BMP388 Barometric pressure sensor on CS1 */
		status = SPI_STATUS_PRESENT;
		SPI_DEBUG("ra_spi_status: devid=1 (BMP388) -> PRESENT");
		break;

	default:
		SPI_DEBUG("ra_spi_status: devid=%lu -> NOT PRESENT", (unsigned long)devid);
		status = 0;  /* Unknown device */
		break;
	}

	return status;
}

/**
 * Name: ra_spi_cmddata
 *
 * Description:
 *   Control the SPI CMD/DATA GPIO - required by NuttX RA8 SPI driver
 *   GY-912 module doesn't use CMD/DATA line
 */
extern "C" int ra_spi_cmddata(struct spi_dev_s *dev, uint32_t devid, bool cmd)
{
	/* GY-912 sensors don't use CMD/DATA line */
	return 0;
}
