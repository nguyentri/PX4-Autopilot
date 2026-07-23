/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
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

#pragma once

#include <px4_arch/hw_description.h>
#include <px4_platform_common/spi.h>
#include <px4_platform_common/constexpr_util.h>
#include <px4_arch/micro_hal.h>
#include <rzv_gpio.h>

#include <board_config.h>

#if defined(CONFIG_SPI)

constexpr bool validateSPIConfig(const px4_spi_bus_t spi_busses_conf[SPI_BUS_MAX_BUS_ITEMS])
{
	const bool nuttx_enabled_spi_buses[] = {
#ifdef CONFIG_RZV_SPI0
		true,
#else
		false,
#endif
#ifdef CONFIG_RZV_SPI1
		true,
#else
		false,
#endif
	};

	for (unsigned i = 0; i < sizeof(nuttx_enabled_spi_buses) / sizeof(nuttx_enabled_spi_buses[0]); ++i) {
		bool found_bus = false;

		for (int j = 0; j < SPI_BUS_MAX_BUS_ITEMS; ++j) {
			// RZV2H SPI bus numbering: CONFIG_RZV_SPIx corresponds to PX4 SPI bus x
			// CONFIG_RZV_SPI0 -> PX4 SPI bus 0, CONFIG_RZV_SPI1 -> PX4 SPI bus 1
			if (spi_busses_conf[j].bus == (int)i) {
				found_bus = true;
			}
		}

		// Either the bus is enabled in NuttX and configured in spi_busses_conf, or disabled and not configured
		constexpr_assert(found_bus == nuttx_enabled_spi_buses[i], "SPI bus config mismatch (CONFIG_RZV_SPIx)");
	}

	return true;
}

static inline constexpr px4_spi_bus_device_t initSPIDevice(uint32_t devid, SPI::CS cs_gpio, SPI::DRDY drdy_gpio = {})
{
	px4_spi_bus_device_t ret{};

	// CS pin configuration - output high (inactive)
	// For RZV2H, use getGPIOPort and getGPIOPin to extract port and pin from the enum
	// GPIO flags: GPIO_OUTPUT | GPIO_OUTPUT_HIGH
	ret.cs_gpio = getGPIOPort(cs_gpio.port) | getGPIOPin(cs_gpio.pin) |
	              (1 << 2) |  // GPIO_OUTPUT (direction bit)
	              (1 << 0);   // GPIO_OUTPUT_HIGH (initial value)

	// DRDY pin configuration - input with pull-up
	if (drdy_gpio.port != GPIO::PortInvalid) {
		ret.drdy_gpio = getGPIOPort(drdy_gpio.port) | getGPIOPin(drdy_gpio.pin) |
		                (1 << 4);   // GPIO_INPUT with pull-up
	}

	if (PX4_SPIDEVID_TYPE(devid) == 0) { // it's a PX4 device (internal or external)
		ret.devid = PX4_SPIDEV_ID(PX4_SPI_DEVICE_ID, devid);
	} else { // it's a NuttX device (e.g. SPIDEV_FLASH(0))
		ret.devid = devid;
	}

	ret.devtype_driver = PX4_SPI_DEV_ID(devid);
	return ret;
}

static inline constexpr px4_spi_bus_t initSPIBus(SPI::Bus bus, const px4_spi_bus_devices_t &devices, GPIO::GPIOPin power_enable = {})
{
	px4_spi_bus_t ret{};
	ret.requires_locking = false;

	for (int i = 0; i < SPI_BUS_MAX_DEVICES; ++i) {
		ret.devices[i] = devices.devices[i];

		if (ret.devices[i].cs_gpio != 0) {
			if (PX4_SPI_DEVICE_ID == PX4_SPIDEVID_TYPE(ret.devices[i].devid)) {
				int same_devices_count = 0;

				for (int j = 0; j < i; ++j) {
					if (ret.devices[j].cs_gpio != 0) {
						same_devices_count += (ret.devices[i].devid & 0xff) == (ret.devices[j].devid & 0xff);
					}
				}

				// increment the 2. LSB byte to allow multiple devices of the same type
				ret.devices[i].devid |= same_devices_count << 8;

			} else {
				// A bus potentially requires locking if it is accessed by non-PX4 devices (i.e. NuttX drivers)
				ret.requires_locking = true;
			}
		}
	}

	ret.bus = (int)bus;
	ret.is_external = false;

	if (power_enable.port != GPIO::PortInvalid) {
		// Power enable GPIO - output low (power off initially)
		ret.power_enable_gpio = getGPIOPort(power_enable.port) | getGPIOPin(power_enable.pin) |
		                        (1 << 2);  // GPIO_OUTPUT, bit 0=0 for low
	}

	return ret;
}

#endif /* CONFIG_SPI */
