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
#include <px4_arch/micro_hal.h>

#if defined(CONFIG_SPI)

constexpr bool validateSPIConfig(const px4_spi_bus_t spi_busses_conf[SPI_BUS_MAX_BUS_ITEMS])
{
	const bool nuttx_enabled_spi_buses[] = {
#ifdef CONFIG_RA_SPI0
		true,
#else
		false,
#endif
#ifdef CONFIG_RA_SPI1
		true,
#else
		false,
#endif
	};

	for (unsigned i = 0; i < sizeof(nuttx_enabled_spi_buses) / sizeof(nuttx_enabled_spi_buses[0]); ++i) {
		bool found_bus = false;

		for (int j = 0; j < SPI_BUS_MAX_BUS_ITEMS; ++j) {
			// RA8 SPI bus numbering: CONFIG_RA_SPIx corresponds to PX4 SPI bus x
			// CONFIG_RA_SPI0 -> PX4 SPI bus 0, CONFIG_RA_SPI1 -> PX4 SPI bus 1
			if (spi_busses_conf[j].bus == (int)i) {
				found_bus = true;
			}
		}

		// Either the bus is enabled in NuttX and configured in spi_busses_conf, or disabled and not configured
		constexpr_assert(found_bus == nuttx_enabled_spi_buses[i], "SPI bus config mismatch (CONFIG_RA_SPIx)");
	}

	return true;
}

static inline constexpr px4_spi_bus_device_t initSPIDevice(uint32_t devid, SPI::CS cs_gpio, SPI::DRDY drdy_gpio = {})
{
	px4_spi_bus_device_t ret{};

	// CS pin configuration - output high (inactive)
	// GPIO_OUTPUT_HIGH = GPIO_OUTPUT_BIT | GPIO_OUTPUT_SET_BIT
	ret.cs_gpio = getGPIOPort(cs_gpio.port) | getGPIOPin(cs_gpio.pin) | (0x00010000 | 0x00020000); // GPIO_OUTPUT_HIGH

	// DRDY pin configuration - input if specified
	if (drdy_gpio.port != GPIO::PortInvalid) {
		ret.drdy_gpio = getGPIOPort(drdy_gpio.port) | getGPIOPin(drdy_gpio.pin) | 0; // GPIO_INPUT
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
	}

	ret.bus = (int)bus;
	ret.is_external = false; // RA8 SPI buses are internal

	if (power_enable.port != GPIO::PortInvalid) {
		ret.power_enable_gpio = getGPIOPort(power_enable.port) | getGPIOPin(power_enable.pin) | 0x00010000; // GPIO_OUTPUT_LOW
	}

	return ret;
}

// Helper function to create GPIO pinset for RA8
static inline constexpr uint32_t px4_ra8_gpio_pinset(GPIO::Port port, GPIO::Pin pin, uint32_t mode, uint32_t config)
{
	// For RA8, we need to convert the generic GPIO port/pin to RA8 format
	// This is a simplified implementation - in practice, this would map to the actual RA8 GPIO structure
	return ((uint32_t)port << 16) | ((uint32_t)pin << 8) | (mode & 0xFF) | (config & 0xFF);
}

#endif /* CONFIG_SPI */
