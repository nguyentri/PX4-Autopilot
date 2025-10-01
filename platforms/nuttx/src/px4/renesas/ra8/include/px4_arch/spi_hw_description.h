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

// GPIO mode definitions for RA8
#define GPIO_OUTPUT        0x01
#define GPIO_INPUT         0x00
#define GPIO_OUTPUT_HIGH   0x10
#define GPIO_OUTPUT_LOW    0x00
#define GPIO_INPUT_PULLUP  0x20

static inline constexpr px4_spi_bus_device_t initSPIDevice(uint32_t devid, SPI::CS cs_gpio, SPI::DRDY drdy_gpio = {})
{
	px4_spi_bus_device_t ret{};

	// For RA8, we create uint32_t GPIO pinset in PX4 format
	// Format: [port:8][pin:8][config:16]
	// CS pin configuration - output high (inactive)
	ret.cs_gpio = ((uint32_t)cs_gpio.port << 24) | ((uint32_t)cs_gpio.pin << 16) | GPIO_OUTPUT | GPIO_OUTPUT_HIGH;

	// DRDY pin configuration - input with pull-up if specified
	if (drdy_gpio.port != GPIO::PortInvalid) {
		ret.drdy_gpio = ((uint32_t)drdy_gpio.port << 24) | ((uint32_t)drdy_gpio.pin << 16) | GPIO_INPUT | GPIO_INPUT_PULLUP;
	}

	ret.devid = devid;
	ret.devtype_driver = devid & 0xff;

	return ret;
}

static inline constexpr px4_spi_bus_t initSPIBus(SPI::Bus bus, const px4_spi_bus_devices_t &devices, GPIO::GPIOPin power_enable = {})
{
	px4_spi_bus_t ret{};

	for (int i = 0; i < SPI_BUS_MAX_DEVICES; ++i) {
		ret.devices[i] = devices.devices[i];
	}

	ret.bus = (int)bus;
	ret.is_external = false; // RA8 SPI buses are internal

	if (power_enable.port != GPIO::PortInvalid) {
		ret.power_enable_gpio = ((uint32_t)power_enable.port << 24) | ((uint32_t)power_enable.pin << 16) | GPIO_OUTPUT | GPIO_OUTPUT_LOW;
	}

	ret.requires_locking = false; // RA8 SPI buses don't require locking by default

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
