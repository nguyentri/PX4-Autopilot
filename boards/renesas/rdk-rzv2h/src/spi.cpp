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
 * - SPI0: one profile-selected MPU9250 or ICM20948 IMU sensor
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

#ifdef CONFIG_RZV2H_DRONE_SENSOR_EXTENSION
#if !defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM45686) || defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250) || defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948)
#error "The drone extension requires ICM45686 without legacy IMU drivers"
#endif
static constexpr uint32_t imu_device_type = DRV_IMU_DEVTYPE_ICM45686;
#elif defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250) && defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948)
#error "SPI0/P93 supports one IMU; select either MPU9250 or ICM20948"
#elif defined(CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948)
static constexpr uint32_t imu_device_type = DRV_IMU_DEVTYPE_ICM20948;
#elif defined(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250)
static constexpr uint32_t imu_device_type = DRV_IMU_DEVTYPE_MPU9250;
#else
#error "The sensor SPI table requires an enabled IMU driver"
#endif

constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
	initSPIBus(SPI::Bus(PX4_SPI_BUS_SENSORS), {
#ifdef CONFIG_RZV2H_DRONE_SENSOR_EXTENSION
		initSPIDevice(imu_device_type, SPI::CS{GPIO::Port9, GPIO::Pin3}),
		initSPIDevice(imu_device_type, SPI::CS{GPIO::Port9, GPIO::Pin4}),
		initSPIDevice(imu_device_type, SPI::CS{GPIO::Port9, GPIO::Pin5}),
#else
		// CS = P93 (GPIO-driven, active-low). DRDY = P94 (IMU INT, TINT).
		// Do not use PA7; that pin is GPT7B/ESC2 PWM (see timer_config.cpp:154).
		initSPIDevice(imu_device_type, SPI::CS{GPIO::Port9, GPIO::Pin3}, SPI::DRDY{GPIO::Port9, GPIO::Pin4}),
#endif
	}),
};

static_assert(validateSPIConfig(px4_spi_buses), "SPI bus configuration mismatch");
static_assert(px4_spi_buses[0].power_enable_gpio == 0, "The IMU bus has no switched power GPIO");

#ifdef CONFIG_RZV2H_DRONE_SENSOR_EXTENSION
extern "C" int board_spi_configure_device_ids(const uint32_t *devids, unsigned int count);

extern "C" __EXPORT int rdk_rzv2h_configure_sensor_cs(void)
{
	const uint32_t devids[] = {
		px4_spi_buses[0].devices[0].devid,
		px4_spi_buses[0].devices[1].devid,
		px4_spi_buses[0].devices[2].devid
	};
	return board_spi_configure_device_ids(devids, sizeof(devids) / sizeof(devids[0]));
}
#endif

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
