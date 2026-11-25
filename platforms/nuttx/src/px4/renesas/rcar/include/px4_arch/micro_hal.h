/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
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
 * @file micro_hal.h
 *
 * R-Car V4H (Cortex-R52) PX4 micro HAL.  The SIH profile uses no PX4 bus;
 * the I2C and SPI hooks report no bus until a sensor profile maps them.
 */

#pragma once

#include <px4_platform/micro_hal.h>

#include <nuttx/config.h>
#include <nuttx/irq.h>
#include <errno.h>
#include <malloc.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

__BEGIN_DECLS

struct spi_dev_s;
struct i2c_master_s;

/* GPIO pinset type: the BSP GPIO API is not mapped to PX4 yet */
typedef uint32_t gpio_pinset_t;

/* No unique-ID register is readable from the CR52 */
#define PX4_CPU_UUID_BYTE_LENGTH                12
#define PX4_CPU_UUID_WORD32_LENGTH              (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))
#define PX4_CPU_MFGUID_BYTE_LENGTH              PX4_CPU_UUID_BYTE_LENGTH
#define PX4_CPU_UUID_WORD32_UNIQUE_H            2
#define PX4_CPU_UUID_WORD32_UNIQUE_M            1
#define PX4_CPU_UUID_WORD32_UNIQUE_L            0
#define PX4_CPU_UUID_WORD32_FORMAT_SIZE         (PX4_CPU_UUID_WORD32_LENGTH-1+(2*PX4_CPU_UUID_BYTE_LENGTH)+1)
#define PX4_CPU_MFGUID_FORMAT_SIZE              ((2*PX4_CPU_MFGUID_BYTE_LENGTH)+1)

/* No panic-save storage: the crash dump is not kept */
#define px4_savepanic(fileno, context, length)  ((void)(fileno), (void)(context), (void)(length), -ENOSYS)

#define PX4_BUS_OFFSET       0                  /* NuttX buses are 0 based */

/* The Cortex-R52 L1 data cache line is 64 bytes */
#define PX4_ARCH_DCACHE_LINESIZE  64
#define PX4_ARCH_DCACHE_ALIGNMENT PX4_ARCH_DCACHE_LINESIZE
#define px4_cache_aligned_data()  aligned_data(PX4_ARCH_DCACHE_LINESIZE)
#define px4_cache_aligned_alloc(s) memalign(PX4_ARCH_DCACHE_LINESIZE, (s))

/* No PX4 GPIO mapping yet: configuring a pin or an event fails with
 * -ENOSYS, reads return 0 and writes are ignored.  Functions, not constant
 * macros, because callers use them as statements.
 */
static inline int px4_arch_configgpio(uint32_t pinset)
{
	(void)pinset;
	return -ENOSYS;
}

static inline int px4_arch_unconfiggpio(uint32_t pinset)
{
	(void)pinset;
	return -ENOSYS;
}

static inline bool px4_arch_gpioread(uint32_t pinset)
{
	(void)pinset;
	return false;
}

static inline void px4_arch_gpiowrite(uint32_t pinset, bool value)
{
	(void)pinset;
	(void)value;
}

static inline int px4_arch_gpiosetevent(uint32_t pinset, bool risingedge, bool fallingedge,
					bool event, xcpt_t func, void *arg)
{
	(void)pinset; (void)risingedge; (void)fallingedge; (void)event; (void)func; (void)arg;
	return -ENOSYS;
}

struct i2c_master_s *px4_i2cbus_initialize(int bus);
int px4_i2cbus_uninitialize(struct i2c_master_s *dev);
struct spi_dev_s *px4_spibus_initialize(int bus);

__END_DECLS
