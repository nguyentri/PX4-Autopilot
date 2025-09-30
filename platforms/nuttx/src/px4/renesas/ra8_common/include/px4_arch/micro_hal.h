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

__BEGIN_DECLS

/* Renesas RA8 specific includes - stub for now */
/* TODO: Add actual Renesas RA8 HAL includes when available */

/* Renesas RA8 defines the 128 bit UUID 
 * TODO: Define actual UUID structure for Renesas RA8
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

/* Stub panic save - TODO: Implement for Renesas RA8 */
#define px4_savepanic(fileno, context, length)  /* stub */

#define PX4_BUS_OFFSET       0                  /* RA8 buses are 0 based */

/* Stub bus initialization - TODO: Implement for Renesas RA8 */
#define px4_spibus_initialize(bus_num_1based)   ((void*)1) /* stub */
#define px4_i2cbus_initialize(bus_num_1based)   ((void*)1) /* stub */
#define px4_i2cbus_uninitialize(pdev)           /* stub */

/* Stub GPIO functions - TODO: Implement for Renesas RA8 */
#define px4_arch_configgpio(pinset)             (0) /* stub */
#define px4_arch_unconfiggpio(pinset)           (0) /* stub */
#define px4_arch_gpioread(pinset)               (false) /* stub */
#define px4_arch_gpiowrite(pinset, value)       /* stub */
#define px4_arch_gpiosetevent(pinset,r,f,e,fp,a) (0) /* stub */

/* Stub GPIO macros - TODO: Implement for Renesas RA8 */
#define PX4_MAKE_GPIO_INPUT(gpio) (gpio)
#define PX4_MAKE_GPIO_EXTI(gpio) (gpio)
#define PX4_MAKE_GPIO_OUTPUT_CLEAR(gpio) (gpio)
#define PX4_MAKE_GPIO_OUTPUT_SET(gpio) (gpio)
#define PX4_GPIO_PIN_OFF(def) (def)

/* Timer configuration - TODO: Implement for Renesas RA8 */
#define TIMER_HRT_CYCLES_PER_US (360) /* Assuming 360MHz */
#define TIMER_HRT_CYCLES_PER_MS (360000)

/* Cache alignment - ARMv8-M may have cache */
#if defined(CONFIG_ARMV8M_DCACHE)
#  define PX4_ARCH_DCACHE_ALIGNMENT 32 /* Typical ARMv8-M cache line size */
#  define px4_cache_aligned_data() aligned_data(32)
#  define px4_cache_aligned_alloc(s) memalign(32,(s))
#else
#  define px4_cache_aligned_data()
#  define px4_cache_aligned_alloc malloc
#endif

__END_DECLS
