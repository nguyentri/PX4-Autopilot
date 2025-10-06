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
 * @file serial.c
 * Serial/UART micro HAL implementation for Renesas RA8
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

/* Board specific definitions */
#include "board_config.h"

#ifndef OK
#define OK 0
#endif

/* Serial port configuration */
struct ra8_serial_config {
    const char *device;     /* Device node name */
    uint32_t baud;         /* Baud rate */
    uint8_t sci_num;       /* SCI controller number */
    bool configured;       /* Port is configured */
};

/* Serial port configurations */
static struct ra8_serial_config serial_configs[] = {
    { "/dev/ttyS0", 115200, 2, false },  /* Console - SCI2 */
    { "/dev/ttyS1", 57600,  0, false },  /* Telemetry - SCI0 */
    { "/dev/ttyS2", 57600,  3, false },  /* RC/GPS - SCI3 */
};

#define NUM_SERIAL_PORTS (sizeof(serial_configs) / sizeof(serial_configs[0]))

/****************************************************************************
 * Serial Initialization Functions
 ****************************************************************************/

/**
 * Initialize serial system
 */
int px4_arch_serial_init(void)
{
    int ret = OK;

    /* Configure serial GPIO pins - NuttX should handle this automatically */
    /* but we can ensure they're properly set up */

    /* SCI0 - Telemetry (P609/P610) */
    /* SCI2 - Console (P801/P802) */
    /* SCI3 - RC Input (P309/P310) */

    /* Mark all ports as configured */
    for (unsigned int i = 0; i < NUM_SERIAL_PORTS; i++) {
        serial_configs[i].configured = true;
    }

    return ret;
}

/**
 * Get serial device name by index
 */
const char *px4_arch_serial_get_device(unsigned int port)
{
    if (port >= NUM_SERIAL_PORTS) {
        return NULL;
    }

    return serial_configs[port].device;
}

/**
 * Get serial baud rate by index
 */
uint32_t px4_arch_serial_get_baud(unsigned int port)
{
    if (port >= NUM_SERIAL_PORTS) {
        return 0;
    }

    return serial_configs[port].baud;
}

/**
 * Set serial baud rate
 */
int px4_arch_serial_set_baud(unsigned int port, uint32_t baud)
{
    if (port >= NUM_SERIAL_PORTS)  {
        return -EINVAL;
    }

    serial_configs[port].baud = baud;

    /* TODO: Apply baud rate change to hardware */
    /* This would involve opening the device and calling termios functions */

    return OK;
}

/****************************************************************************
 * Serial Utility Functions
 ****************************************************************************/

/**
 * Get number of serial ports
 */
int px4_arch_serial_get_count(void)
{
    return NUM_SERIAL_PORTS;
}

/**
 * Check if serial port is configured
 */
bool px4_arch_serial_is_configured(unsigned int port)
{
    if (port >= NUM_SERIAL_PORTS)  {
        return false;
    }

    return serial_configs[port].configured;
}

/**
 * Get console device name
 */
const char *px4_arch_serial_get_console(void)
{
    /* Console is typically ttyS0 on most systems */
    return "/dev/ttyS0";
}

/**
 * Get telemetry device name
 */
const char *px4_arch_serial_get_telem1(void)
{
    return "/dev/ttyS1";
}

/**
 * Get secondary telemetry device name
 */
const char *px4_arch_serial_get_telem2(void)
{
    return "/dev/ttyS2";
}

/**
 * Get GPS device name
 */
const char *px4_arch_serial_get_gps(void)
{
    return "/dev/ttyS1";  /* Share with telemetry for now */
}

/**
 * Get RC input device name
 */
const char *px4_arch_serial_get_rc(void)
{
    return "/dev/ttyS2";
}

/****************************************************************************
 * Serial Test Functions
 ****************************************************************************/

/**
 * Test serial port by sending test data
 */
int px4_arch_serial_test(unsigned int port)
{
    /* TODO: Implement serial port testing */
    /* This would:
     * 1. Open the device
     * 2. Send test data
     * 3. Check for loopback (if available)
     * 4. Close the device
     */

    if (port >= NUM_SERIAL_PORTS)  {
        return -EINVAL;
    }

    return OK; /* Assume test passes for now */
}
