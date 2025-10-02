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
#include <nuttx/irq.h>
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
/* I2C functions are implemented in micro_hal/i2c.c - do not use macros */

/* GPIO functions using RA8 NuttX drivers */
#define px4_arch_configgpio(pinset)             px4_ra8_configgpio(pinset)
#define px4_arch_unconfiggpio(pinset)           px4_ra8_unconfiggpio(pinset)
#define px4_arch_gpioread(pinset)               px4_ra8_gpioread(pinset)
#define px4_arch_gpiowrite(pinset, value)       px4_ra8_gpiowrite(pinset, value)
#define px4_arch_gpiosetevent(pinset,r,f,e,fp,a) px4_ra8_gpiosetevent(pinset,r,f,e,fp,a)

/* GPIO pin encoding definitions for RA8 */
#define GPIO_PORT_SHIFT     8
#define GPIO_PIN_SHIFT      0
#define GPIO_OUTPUT_BIT     0x00010000
#define GPIO_OUTPUT_SET_BIT 0x00020000
#define GPIO_PULLUP_BIT     0x00080000
#define GPIO_ALT_BIT        0x00000200

/* GPIO port encoding (bits 11-8) */
#define GPIO_PORTA          (0 << GPIO_PORT_SHIFT)
#define GPIO_PORTB          (1 << GPIO_PORT_SHIFT)
#define GPIO_PORTC          (2 << GPIO_PORT_SHIFT)
#define GPIO_PORTD          (3 << GPIO_PORT_SHIFT)
#define GPIO_PORTE          (4 << GPIO_PORT_SHIFT)
#define GPIO_PORTF          (5 << GPIO_PORT_SHIFT)
#define GPIO_PORTG          (6 << GPIO_PORT_SHIFT)
#define GPIO_PORTH          (7 << GPIO_PORT_SHIFT)
#define GPIO_PORTI          (8 << GPIO_PORT_SHIFT)
#define GPIO_PORTJ          (9 << GPIO_PORT_SHIFT)

/* GPIO pin encoding (bits 3-0) */
#define GPIO_PIN0           (0 << GPIO_PIN_SHIFT)
#define GPIO_PIN1           (1 << GPIO_PIN_SHIFT)
#define GPIO_PIN2           (2 << GPIO_PIN_SHIFT)
#define GPIO_PIN3           (3 << GPIO_PIN_SHIFT)
#define GPIO_PIN4           (4 << GPIO_PIN_SHIFT)
#define GPIO_PIN5           (5 << GPIO_PIN_SHIFT)
#define GPIO_PIN6           (6 << GPIO_PIN_SHIFT)
#define GPIO_PIN7           (7 << GPIO_PIN_SHIFT)
#define GPIO_PIN8           (8 << GPIO_PIN_SHIFT)
#define GPIO_PIN9           (9 << GPIO_PIN_SHIFT)
#define GPIO_PIN10          (10 << GPIO_PIN_SHIFT)
#define GPIO_PIN11          (11 << GPIO_PIN_SHIFT)
#define GPIO_PIN12          (12 << GPIO_PIN_SHIFT)
#define GPIO_PIN13          (13 << GPIO_PIN_SHIFT)
#define GPIO_PIN14          (14 << GPIO_PIN_SHIFT)
#define GPIO_PIN15          (15 << GPIO_PIN_SHIFT)

/* GPIO mode encoding */
#define GPIO_INPUT          0
#define GPIO_OUTPUT         GPIO_OUTPUT_BIT

/* Additional GPIO mode combinations for compatibility */
#define GPIO_OUTPUT_HIGH    (GPIO_OUTPUT_BIT | GPIO_OUTPUT_SET_BIT)
#define GPIO_OUTPUT_LOW     GPIO_OUTPUT_BIT
#define GPIO_INPUT_PULLUP   GPIO_PULLUP_BIT

/* GPIO macros for RA8 - proper implementations */
#define PX4_MAKE_GPIO_INPUT(gpio)               ((gpio) & ~GPIO_OUTPUT_BIT)
#define PX4_MAKE_GPIO_EXTI(gpio)                ((gpio) & ~GPIO_OUTPUT_BIT)
#define PX4_MAKE_GPIO_OUTPUT_CLEAR(gpio)        ((gpio) | GPIO_OUTPUT_BIT)
#define PX4_MAKE_GPIO_OUTPUT_SET(gpio)          ((gpio) | GPIO_OUTPUT_BIT | GPIO_OUTPUT_SET_BIT)
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

/* PX4 I2C functions - implemented in platforms/nuttx/src/px4/renesas/ra8_common/micro_hal/i2c.c */
struct i2c_master_s *px4_i2cbus_initialize(int bus);
int px4_i2cbus_uninitialize(struct i2c_master_s *dev);
/* px4_i2cbus_reset is declared in i2c_hw_description.h with device pointer parameter */
int px4_i2cbus_set_bus_frequency(struct i2c_master_s *dev, uint32_t frequency);
int px4_i2cbus_scan(int bus, uint8_t *devices, int max_devices);

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
