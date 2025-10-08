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

#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>

struct spi_dev_s;

#ifndef __EXPORT
#define __EXPORT
#endif

#ifndef SPI_STATUS_PRESENT
#define SPI_STATUS_PRESENT  0x01
#endif

extern "C" {
    extern struct spi_dev_s *ra_spibus_initialize(int bus);
}

/************************************************************************************
 * Name: ra_spi0select and ra_spi0status
 *
 * Description:
 *   Called by RA SPI driver on bus 0.
 *
 ************************************************************************************/
#ifdef CONFIG_RA_SPI0
__EXPORT void ra_spi0select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
	// CS handling will be done by board-specific code
	(void)dev;
	(void)devid;
	(void)selected;
}

__EXPORT uint8_t ra_spi0status(struct spi_dev_s *dev, uint32_t devid)
{
	(void)dev;
	(void)devid;
	return SPI_STATUS_PRESENT;
}
#endif // CONFIG_RA_SPI0

/************************************************************************************
 * Name: ra_spi1select and ra_spi1status
 *
 * Description:
 *   Called by RA SPI driver on bus 1.
 *
 ************************************************************************************/
#ifdef CONFIG_RA_SPI1
__EXPORT void ra_spi1select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
	// CS handling will be done by board-specific code
	(void)dev;
	(void)devid;
	(void)selected;
}

__EXPORT uint8_t ra_spi1status(struct spi_dev_s *dev, uint32_t devid)
{
	(void)dev;
	(void)devid;
	return SPI_STATUS_PRESENT;
}
#endif // CONFIG_RA_SPI1

/* PX4 SPI bus initialization */
extern "C" struct spi_dev_s *px4_spibus_initialize(int bus)
{
	return ra_spibus_initialize(bus);
}

/* SPI power control stub */
extern "C" __EXPORT void board_control_spi_sensors_power(bool enable_power, int bus_mask)
{
	(void)enable_power;
	(void)bus_mask;
	// Board-specific power control implementation
}

/* SPI power GPIO configuration stub */
extern "C" __EXPORT void board_control_spi_sensors_power_configgpio()
{
	// Board-specific GPIO configuration
}

/* SPI reset function */
extern "C" __EXPORT void board_spi_reset(int ms, int bus_mask)
{
	// Disable SPI sensors
	board_control_spi_sensors_power(false, bus_mask);

	usleep((unsigned int)(ms * 1000));

	// Re-enable SPI sensors
	board_control_spi_sensors_power(true, bus_mask);
}


/* Platform SPI functions removed - implemented in board-specific layer */
