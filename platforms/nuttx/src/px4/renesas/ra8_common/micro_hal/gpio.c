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

/**
 * @file gpio.c
 * GPIO micro HAL implementation for Renesas RA8
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

#include <nuttx/config.h>
#include <arch/board/board.h>

/* RA8 specific headers */
#include "hardware/ra8e1/ra8e1_pinmap.h"
#include "ra8_gpio.h"

#ifndef OK
#define OK 0
#endif

/****************************************************************************
 * GPIO Configuration Functions
 ****************************************************************************/

/**
 * Configure a GPIO pin
 */
int px4_arch_configgpio(uint32_t pinset)
{
    return ra_configgpio((gpio_pinset_t)pinset);
}

/**
 * Unconfigure a GPIO pin (return to default state)
 */
int px4_arch_unconfiggpio(uint32_t pinset)
{
    /* Set pin back to input with no pull-up */
    uint32_t input_pinset = (pinset & ~(GPIO_OUTPUT | R_PFS_PCR)) | GPIO_INPUT;
    return ra_configgpio((gpio_pinset_t)input_pinset);
}

/**
 * Read a GPIO pin value
 */
bool px4_arch_gpioread(uint32_t pinset)
{
    return ra_gpioread((gpio_pinset_t)pinset);
}

/**
 * Write a GPIO pin value
 */
void px4_arch_gpiowrite(uint32_t pinset, bool value)
{
    ra_gpiowrite((gpio_pinset_t)pinset, value);
}

/****************************************************************************
 * Interrupt Functions
 ****************************************************************************/

/**
 * Configure GPIO interrupt
 * Note: This is a simplified implementation
 */
int px4_arch_gpiosetevent(uint32_t pinset, bool rising, bool falling,
                         bool event, xcpt_t func, void *arg)
{
    /* TODO: Implement GPIO interrupt configuration for RA8 */
    /* This would involve:
     * 1. Configure the pin for interrupt mode
     * 2. Set up the interrupt controller
     * 3. Register the callback function
     */

    /* For now, return success but don't actually set up interrupts */
    (void)pinset;
    (void)rising;
    (void)falling;
    (void)event;
    (void)func;
    (void)arg;

    return OK;
}

/****************************************************************************
 * LED Control Functions
 ****************************************************************************/

/**
 * Initialize board LEDs
 */
void px4_arch_init_leds(void)
{
    /* Configure LED pins as outputs */
    px4_arch_configgpio(GPIO_nLED_RED);
    px4_arch_configgpio(GPIO_nLED_GREEN);

    /* Turn off both LEDs initially (active low) */
    px4_arch_gpiowrite(GPIO_nLED_RED, true);    /* LED off */
    px4_arch_gpiowrite(GPIO_nLED_GREEN, true);  /* LED off */
}

/**
 * Set LED state
 */
void px4_arch_set_led(int led, bool state)
{
    switch (led) {
    case 0: /* Red LED */
        px4_arch_gpiowrite(GPIO_nLED_RED, !state);  /* Active low */
        break;
    case 1: /* Green LED */
        px4_arch_gpiowrite(GPIO_nLED_GREEN, !state); /* Active low */
        break;
    default:
        break;
    }
}

/****************************************************************************
 * Safety Button Functions
 ****************************************************************************/

/**
 * Initialize safety button
 */
void px4_arch_init_safety_button(void)
{
    /* Configure safety button pin as input with pull-up */
    px4_arch_configgpio(GPIO_BTN_SAFETY);
}

/**
 * Read safety button state
 */
bool px4_arch_read_safety_button(void)
{
    /* Button is active low when pressed */
    return !px4_arch_gpioread(GPIO_BTN_SAFETY);
}
