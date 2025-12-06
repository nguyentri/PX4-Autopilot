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
 * @file io_timer_hal_bridge.h
 *
 * NuttX PWM HAL Bridge Interface
 */

#ifndef __PX4_NUTTX_RA8_IO_TIMER_HAL_BRIDGE_H
#define __PX4_NUTTX_RA8_IO_TIMER_HAL_BRIDGE_H

#include <stdint.h>

__BEGIN_DECLS

/**
 * Initialize the PWM HAL bridge layer
 *
 * Opens all PWM device files and configures them with default parameters.
 *
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_init(void);

/**
 * Set PWM frequency for a channel
 *
 * @param channel       PWM channel (0-3)
 * @param frequency_hz  PWM frequency in Hz
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_set_rate(unsigned channel, unsigned frequency_hz);

/**
 * Set PWM pulse width (duty cycle) for a channel
 *
 * @param channel   PWM channel (0-3)
 * @param pulse_us  Pulse width in microseconds (1000-2000)
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_set_ccr(unsigned channel, uint16_t pulse_us);

/**
 * Enable PWM output on a channel
 *
 * @param channel  PWM channel (0-3)
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_channel_enable(unsigned channel);

/**
 * Disable PWM output on a channel
 *
 * @param channel  PWM channel (0-3)
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_channel_disable(unsigned channel);

/**
 * Get current PWM pulse width for a channel
 *
 * @param channel   PWM channel (0-3)
 * @param pulse_us  Pointer to store pulse width in microseconds
 * @return 0 on success, negative errno on failure
 */
int io_timer_hal_get_ccr(unsigned channel, uint16_t *pulse_us);

/**
 * Deinitialize the PWM HAL bridge layer
 *
 * Stops all PWM outputs and closes device files.
 */
void io_timer_hal_deinit(void);

__END_DECLS

#endif /* __PX4_NUTTX_RA8_IO_TIMER_HAL_BRIDGE_H */
