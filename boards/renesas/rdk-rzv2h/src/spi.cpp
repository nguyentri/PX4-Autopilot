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
 * @file spi.cpp
 *
 * RDK-RZV2H SPI bus configuration for PX4 sensor drivers
 *
 * Sensor Configuration:
 * - SPI0: MPU9250 IMU sensor
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/spi.h>
#include <px4_arch/spi_hw_description.h>
#include <nuttx/spi/spi.h>
#include <drivers/device/spi.h>
#include <drivers/drv_sensor.h>
#include <syslog.h>

#include "board_config.h"

/* SPI bus configuration */

constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
	initSPIBus(SPI::Bus(PX4_SPI_BUS_SENSORS), {
		initSPIDevice(DRV_IMU_DEVTYPE_MPU9250, SPI::CS{GPIO::PortA, GPIO::Pin7}, SPI::DRDY{GPIO::Port5, GPIO::Pin0}),
	}),
};

/* SPI bus devices - used for device registration */

static constexpr uint32_t spi1_bus1_devices[] = {
	DRV_IMU_DEVTYPE_MPU9250,
};

/**
 * Initialize SPI bus for sensors
 */
__EXPORT void board_spi_reset(int ms, int bus_mask)
{
	/* Give sensors time to reset */
	if (ms > 0) {
		usleep(ms * 1000);
	}

	/* SPI bus reset - nothing specific needed for RZV2H */
}
