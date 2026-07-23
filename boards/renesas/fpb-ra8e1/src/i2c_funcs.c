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

/**
 * @file i2c_funcs.c
 *
 * I2C bus functions for FPB-RA8E1
 */

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* Define __EXPORT for compatibility */
#ifndef __EXPORT
#define __EXPORT
#endif

/* Forward declaration for NuttX I2C structure */
struct i2c_master_s;

/* I2C bus structure definition */
struct px4_i2c_bus_t {
	int bus;       /* physical bus number (1, ...) (-1 means this is unused) */
	bool is_external; /* static external configuration */
};

/* Define the I2C bus array that the linker is looking for */
/* For FPB-RA8E1, we have 1 I2C bus configured as internal */
__EXPORT const struct px4_i2c_bus_t px4_i2c_buses[1] = {
	{
		.bus = 1,
		.is_external = false
	},
};

/* I2C bus initialization and management functions */

__EXPORT struct i2c_master_s *px4_i2cbus_initialize(int bus)
{
	/* For now, return a stub - actual I2C implementation can be added later */
	(void)bus; /* Suppress unused parameter warning */
	return NULL; /* Return NULL to indicate not available */
}

__EXPORT int px4_i2cbus_uninitialize(struct i2c_master_s *dev)
{
	/* Stub implementation */
	(void)dev; /* Suppress unused parameter warning */
	return 0; /* Return success */
}
