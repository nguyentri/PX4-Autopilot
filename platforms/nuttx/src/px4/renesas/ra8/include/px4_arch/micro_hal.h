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
#pragma once

#include <px4_platform/micro_hal.h>

/* NuttX includes */
#include <nuttx/config.h>
#include <nuttx/spi/spi.h>
#include <nuttx/i2c/i2c_master.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Forward declarations */
struct spi_dev_s;
struct i2c_master_s;

/* GPIO pinset type for RA8 - use uint32_t for PX4 compatibility */
typedef uint32_t gpio_pinset_t;

/* Renesas RA8 defines the 128 bit UUID
 * Based on RA8E1 datasheet unique ID structure
 */
#define PX4_CPU_UUID_BYTE_LENGTH                16
#define PX4_CPU_UUID_WORD32_LENGTH              (PX4_CPU_UUID_BYTE_LENGTH/sizeof(uint32_t))

/* The mfguid will be an array of bytes with
 * MSD @ index 0 - LSD @ index PX4_CPU_MFGUID_BYTE_LENGTH-1
 */
#define PX4_CPU_MFGUID_BYTE_LENGTH              PX4_CPU_UUID_BYTE_LENGTH

/* UUID correlation for Renesas RA8 */
#define PX4_CPU_UUID_WORD32_UNIQUE_H            0 /* Least significant digits change the most */
#define PX4_CPU_UUID_WORD32_UNIQUE_M            1 /* Middle significant digits */
#define PX4_CPU_UUID_WORD32_UNIQUE_L            2 /* Most significant digits change the least */

/*                                                  Separator    nnn:nnn:nnnn     2 char per byte           term */
#define PX4_CPU_UUID_WORD32_FORMAT_SIZE         (PX4_CPU_UUID_WORD32_LENGTH-1+(2*PX4_CPU_UUID_BYTE_LENGTH)+1)
#define PX4_CPU_MFGUID_FORMAT_SIZE              ((2*PX4_CPU_MFGUID_BYTE_LENGTH)+1)

/* Panic save implementation for RA8 */
#define px4_savepanic(fileno, context, length)  ra8_save_panic(fileno, context, length)

#define PX4_BUS_OFFSET       0                  /* RA8 buses are 0 based */

/* Bus initialization functions using RA8 NuttX drivers */
#define px4_spibus_initialize(bus_num_1based)   ra_spibus_initialize(bus_num_1based - PX4_BUS_OFFSET)
#define px4_i2cbus_initialize(bus_num_1based)   ra_i2cbus_initialize(bus_num_1based - PX4_BUS_OFFSET)
#define px4_i2cbus_uninitialize(pdev)           ra_i2cbus_uninitialize(pdev)

/* GPIO functions using RA8 NuttX drivers */
#define px4_arch_configgpio(pinset)             px4_ra8_configgpio(pinset)
#define px4_arch_unconfiggpio(pinset)           px4_ra8_unconfiggpio(pinset)
#define px4_arch_gpioread(pinset)               px4_ra8_gpioread(pinset)
#define px4_arch_gpiowrite(pinset, value)       px4_ra8_gpiowrite(pinset, value)
#define px4_arch_gpiosetevent(pinset,r,f,e,fp,a) px4_ra8_gpiosetevent(pinset,r,f,e,fp,a)

/* GPIO macros for RA8 - using generic bit operations for now */
#define PX4_MAKE_GPIO_INPUT(gpio)               (gpio)
#define PX4_MAKE_GPIO_EXTI(gpio)                (gpio)
#define PX4_MAKE_GPIO_OUTPUT_CLEAR(gpio)        (gpio)
#define PX4_MAKE_GPIO_OUTPUT_SET(gpio)          (gpio)
#define PX4_GPIO_PIN_OFF(def)                   (def)

/* Timer configuration for RA8E1 - Based on PCLKD frequency */
#ifndef CONFIG_RA_PCLKD_FREQUENCY
#  define CONFIG_RA_PCLKD_FREQUENCY    120000000  /* 120MHz PCLKD */
#endif

#define TIMER_HRT_CYCLES_PER_US (CONFIG_RA_PCLKD_FREQUENCY / 1000000)
#define TIMER_HRT_CYCLES_PER_MS (CONFIG_RA_PCLKD_FREQUENCY / 1000)

/* Cache alignment - ARMv8-M Cortex-M85 has cache */
#if defined(CONFIG_ARMV8M_DCACHE)
#  define PX4_ARCH_DCACHE_ALIGNMENT 32 /* ARMv8-M cache line size */
#  define px4_cache_aligned_data() __attribute__((aligned(32)))
#  define px4_cache_aligned_alloc(s) memalign(32,(s))
#else
#  define PX4_ARCH_DCACHE_ALIGNMENT 1
#  define px4_cache_aligned_data()
#  define px4_cache_aligned_alloc malloc
#endif

/* Interrupt handler function pointer type */
typedef int (*gpio_interrupt_t)(int irq, void *context, void *arg);

/* Function declarations for RA8 specific implementations */
struct spi_dev_s *ra_spibus_initialize(int bus);
struct i2c_master_s *ra_i2cbus_initialize(int bus);
int ra_i2cbus_uninitialize(struct i2c_master_s *dev);

/* PX4 GPIO wrapper functions that convert uint32_t to RA8 format */
int px4_ra8_configgpio(gpio_pinset_t pinset);
int px4_ra8_unconfiggpio(gpio_pinset_t pinset);
bool px4_ra8_gpioread(gpio_pinset_t pinset);
void px4_ra8_gpiowrite(gpio_pinset_t pinset, bool value);
int px4_ra8_gpiosetevent(gpio_pinset_t pinset, bool risingedge, bool fallingedge,
                         bool event, gpio_interrupt_t func, void *arg);

void ra8_save_panic(int fileno, void *context, int length);

#ifdef __cplusplus
}
#endif
