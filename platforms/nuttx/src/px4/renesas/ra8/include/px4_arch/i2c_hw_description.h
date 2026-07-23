/****************************************************************************
 *
 *   Copyright (C) 2021 PX4 Development Team. All rights reserved.
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
#include <px4_platform_common/i2c.h>
#include <px4_arch/hw_description.h>

#ifdef __cplusplus
extern "C" {
#endif


/* Use NuttX I2C structures - no redefinition needed */
/* struct i2c_master_s and struct i2c_msg_s are already defined in nuttx/i2c/i2c_master.h */

/* I2C message flags - use guards to prevent redefinition */
#ifndef I2C_M_READ
#define I2C_M_READ          0x0001  /* Read data */
#endif
#ifndef I2C_M_NOSTART
#define I2C_M_NOSTART       0x0002  /* Don't send START condition */
#endif
#ifndef I2C_M_NOSTOP
#define I2C_M_NOSTOP        0x0004  /* Don't send STOP condition */
#endif
#ifndef I2C_M_NORESTART
#define I2C_M_NORESTART     0x0008  /* Don't send RESTART condition */
#endif
#ifndef I2C_M_NACK
#define I2C_M_NACK          0x0010  /* Expect NACK bit */
#endif
#ifndef I2C_M_SCAN
#define I2C_M_SCAN          0x0020  /* Scan the bus for devices */
#endif

/* I2C control operations */
#define I2C_RESET(dev)      px4_i2cbus_reset(dev)

/* I2C transfer function - performs a sequence of I2C transfers */
#ifndef I2C_TRANSFER
#define I2C_TRANSFER(dev, msgs, count) px4_i2c_transfer(dev, msgs, count)
#endif

/* I2C hardware interface function declarations
 * px4_i2cbus_initialize/uninitialize are macros defined in micro_hal.h
 * that redirect to NuttX ra_i2cbus_initialize/uninitialize
 */
int px4_i2cbus_reset(struct i2c_master_s *dev);
int px4_i2c_transfer(struct i2c_master_s *dev, struct i2c_msg_s *msgs, int count);

#ifdef __cplusplus
}

#if defined(CONFIG_I2C)

/* Validate I2C configuration against available NuttX buses */
constexpr bool validateI2CConfig(const px4_i2c_bus_t i2c_busses_conf[I2C_BUS_MAX_BUS_ITEMS])
{
	const bool nuttx_enabled_i2c_buses[] = {
#ifdef CONFIG_RA_I2C0
		true,
#else
		false,
#endif
#ifdef CONFIG_RA_I2C1
		true,
#else
		false,
#endif
#ifdef CONFIG_RA_I2C2
        true,
#else
        false,
#endif
#ifdef CONFIG_RA_I3C
        true,
#else
        false,
#endif
	};

	for (unsigned i = 0; i < sizeof(nuttx_enabled_i2c_buses) / sizeof(nuttx_enabled_i2c_buses[0]); ++i) {
		bool found_bus = false;

		for (int j = 0; j < I2C_BUS_MAX_BUS_ITEMS; ++j) {
			// RA8 I2C bus numbering: CONFIG_RA_I2Cx corresponds to PX4 I2C bus x
			// CONFIG_RA_I2C0 -> PX4 I2C bus 0, CONFIG_RA_I2C1 -> PX4 I2C bus 1
			if (i2c_busses_conf[j].bus == (int)i) {
				found_bus = true;
			}
		}

		// Either the bus is enabled in NuttX and configured in i2c_busses_conf, or disabled and not configured
		constexpr_assert(found_bus == nuttx_enabled_i2c_buses[i], "I2C bus config mismatch (CONFIG_RA_I2Cx)");
	}

	return true;
}

/* Initialize I2C bus configuration */
static inline constexpr px4_i2c_bus_t initI2CBusInternal(I2C::Bus bus)
{
	px4_i2c_bus_t ret{};
	ret.bus = (int)bus;
	ret.is_external = false;
	return ret;
}

static inline constexpr px4_i2c_bus_t initI2CBusExternal(I2C::Bus bus)
{
	px4_i2c_bus_t ret{};
	ret.bus = (int)bus;
	ret.is_external = true;
	return ret;
}

/* Convenience function for internal I2C bus */
#define initI2CBus(bus, devices) initI2CBusInternal(bus)

#endif // CONFIG_I2C
#endif
