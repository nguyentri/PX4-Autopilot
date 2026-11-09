/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *	notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *	notice, this list of conditions and the following disclaimer in
 *	the documentation and/or other materials provided with the
 *	distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *	used to endorse or promote products derived from this software
 *	without specific prior written permission.
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

#include <stdint.h>
#include <nuttx/i2c/i2c_master.h>
#include <px4_platform_common/i2c.h>
#include <px4_platform_common/constexpr_util.h>
#include <px4_arch/hw_description.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef __cplusplus
}

#if defined(CONFIG_I2C)

/* Validate I2C configuration against available NuttX buses */
constexpr bool validateI2CConfig(const px4_i2c_bus_t i2c_busses_conf[I2C_BUS_MAX_BUS_ITEMS])
{
#if defined(CONFIG_RZV_I2C0) && defined(CONFIG_RZV_SCI0_I2C)
	constexpr_assert(false, "RIIC0 and SCI0 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C1) && defined(CONFIG_RZV_SCI1_I2C)
	constexpr_assert(false, "RIIC1 and SCI1 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C2) && defined(CONFIG_RZV_SCI2_I2C)
	constexpr_assert(false, "RIIC2 and SCI2 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C3) && defined(CONFIG_RZV_SCI3_I2C)
	constexpr_assert(false, "RIIC3 and SCI3 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C4) && defined(CONFIG_RZV_SCI4_I2C)
	constexpr_assert(false, "RIIC4 and SCI4 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C5) && defined(CONFIG_RZV_SCI5_I2C)
	constexpr_assert(false, "RIIC5 and SCI5 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C6) && defined(CONFIG_RZV_SCI6_I2C)
	constexpr_assert(false, "RIIC6 and SCI6 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C7) && defined(CONFIG_RZV_SCI7_I2C)
	constexpr_assert(false, "RIIC7 and SCI7 claim the same PX4 I2C bus");
#endif
#if defined(CONFIG_RZV_I2C8) && defined(CONFIG_RZV_SCI8_I2C)
	constexpr_assert(false, "RIIC8 and SCI8 claim the same PX4 I2C bus");
#endif

	/* PX4 bus n is owned by either RIICn or SCIn (simple I2C), never both. */
	const bool nuttx_enabled_i2c_buses[] = {
#if defined(CONFIG_RZV_I2C0) || defined(CONFIG_RZV_SCI0_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C1) || defined(CONFIG_RZV_SCI1_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C2) || defined(CONFIG_RZV_SCI2_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C3) || defined(CONFIG_RZV_SCI3_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C4) || defined(CONFIG_RZV_SCI4_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C5) || defined(CONFIG_RZV_SCI5_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C6) || defined(CONFIG_RZV_SCI6_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C7) || defined(CONFIG_RZV_SCI7_I2C)
		true,
#else
		false,
#endif
#if defined(CONFIG_RZV_I2C8) || defined(CONFIG_RZV_SCI8_I2C)
		true,
#else
		false,
#endif
	};

	for (int j = 0; j < I2C_BUS_MAX_BUS_ITEMS; ++j) {
		constexpr_assert(i2c_busses_conf[j].bus < (int)(sizeof(nuttx_enabled_i2c_buses) /
				 sizeof(nuttx_enabled_i2c_buses[0])), "I2C bus outside RIIC/SCI 0-8 domain");
	}

	for (unsigned i = 0; i < sizeof(nuttx_enabled_i2c_buses) / sizeof(nuttx_enabled_i2c_buses[0]); ++i) {
		bool found_bus = false;

		for (int j = 0; j < I2C_BUS_MAX_BUS_ITEMS; ++j) {
			// RZV2H I2C bus numbering: CONFIG_RZV_I2Cx or CONFIG_RZV_SCIx_I2C
			// corresponds to PX4 I2C bus x (e.g. SCI0 simple I2C -> PX4 bus 0)
			if (i2c_busses_conf[j].bus == (int)i) {
				found_bus = true;
			}
		}

		// Either the bus is enabled in NuttX and configured here, or both are disabled.
		constexpr_assert(found_bus == nuttx_enabled_i2c_buses[i], "I2C bus config mismatch");
	}

	return true;
}

/* Initialize I2C bus configuration */
static inline constexpr px4_i2c_bus_t initI2CBusInternal(I2C::Bus bus)
{
	px4_i2c_bus_t ret{};
	ret.bus = (int)bus.bus_num;
	ret.is_external = false;
	return ret;
}

static inline constexpr px4_i2c_bus_t initI2CBusExternal(I2C::Bus bus)
{
	px4_i2c_bus_t ret{};
	ret.bus = (int)bus.bus_num;
	ret.is_external = true;
	return ret;
}

/* Convenience function for internal I2C bus */
#define initI2CBus(bus, devices) initI2CBusInternal(bus)

#endif // CONFIG_I2C
#endif
