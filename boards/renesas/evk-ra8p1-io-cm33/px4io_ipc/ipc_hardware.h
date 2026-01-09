/****************************************************************************
 *
 *   Copyright (c) 2024-2026 PX4 Development Team. All rights reserved.
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
 * @file ipc_hardware.h
 *
 * RA8P1 Hardware IPC Interrupt API
 *
 * This header defines the interface for hardware IPC interrupt integration
 * using the NuttX RA8 IPC driver.
 *
 * @author PX4 Development Team
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

__BEGIN_DECLS

/*******************************************************************************
 * Public Types
 ******************************************************************************/

/**
 * IPC Logical Channels (application layer)
 */
typedef enum {
	IPC_HW_CH_ACTUATOR   = 0,  /**< Actuator commands (CM85 → CM33) */
	IPC_HW_CH_RC_INPUT   = 1,  /**< RC input data (CM33 → CM85) */
	IPC_HW_CH_BATTERY    = 2,  /**< Battery status (CM33 → CM85) */
	IPC_HW_CH_HEARTBEAT  = 3,  /**< Heartbeat/control (bidirectional) */
} ipc_hw_channel_t;

/**
 * IPC Hardware Semaphores for shared memory protection
 */
typedef enum {
	IPC_HW_SEM_ACTUATOR  = 0,  /**< Protects IpcActuatorCmd structure */
	IPC_HW_SEM_RC_INPUT  = 1,  /**< Protects IpcRcInput structure */
	IPC_HW_SEM_BATTERY   = 2,  /**< Protects IpcBatteryStatus structure */
} ipc_hw_semaphore_t;

/**
 * IPC Interrupt Callback Function Type
 *
 * @param channel  Logical channel that triggered interrupt
 * @param data     32-bit data from IPC FIFO (can be sequence number, timestamp, etc.)
 */
typedef void (*ipc_hw_callback_t)(uint32_t channel, uint32_t data);

/**
 * IPC Hardware Statistics
 */
struct ipc_hw_stats_s {
	uint32_t ch0_irq_count;  /**< Channel 0 interrupt count (actuator commands) */
	uint32_t ch1_irq_count;  /**< Channel 1 interrupt count (RC input) */
	uint32_t ch2_irq_count;  /**< Channel 2 interrupt count (battery status) */
	uint32_t ch3_irq_count;  /**< Channel 3 interrupt count (heartbeat) */
};

/*******************************************************************************
 * Public Function Prototypes
 ******************************************************************************/

/**
 * Initialize hardware IPC subsystem
 *
 * This function:
 * - Initializes the NuttX RA8 IPC driver
 * - Registers interrupt handlers for all 4 IPC channels
 * - Enables hardware interrupts
 *
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_init(void);

/**
 * Deinitialize hardware IPC subsystem
 */
void ipc_hw_deinit(void);

/**
 * Register callback for IPC channel events
 *
 * The callback will be invoked from interrupt context when data is
 * received on the specified channel.
 *
 * @param channel   Logical IPC channel
 * @param callback  Callback function (can be NULL to unregister)
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_register_callback(ipc_hw_channel_t channel, ipc_hw_callback_t callback);

/**
 * Send notification to CM85 via IPC interrupt
 *
 * This function writes a 32-bit value to the IPC channel FIFO and
 * triggers an IRQ0 interrupt on the CM85 core.
 *
 * Typical usage:
 * 1. CM33 writes RC data to shared memory
 * 2. CM33 calls ipc_hw_notify_cm85(IPC_HW_CH_RC_INPUT, sequence_number)
 * 3. CM85 receives interrupt and reads shared memory
 *
 * @param channel  Logical IPC channel
 * @param data     32-bit notification data (sequence number, timestamp, etc.)
 * @return 0 on success, -EBUSY if FIFO full, negative errno on other errors
 */
int ipc_hw_notify_cm85(ipc_hw_channel_t channel, uint32_t data);

/**
 * Acquire hardware IPC semaphore (non-blocking)
 *
 * Use this to protect shared memory access between cores.
 *
 * Example:
 * ```
 * if (ipc_hw_sem_take(IPC_HW_SEM_RC_INPUT) == 0) {
 *     // Write to IpcRcInput shared memory
 *     memcpy(ipc_rc_input, &data, sizeof(data));
 *     ipc_hw_sem_give(IPC_HW_SEM_RC_INPUT);
 *     ipc_hw_notify_cm85(IPC_HW_CH_RC_INPUT, sequence_number);
 * }
 * ```
 *
 * @param sem  Hardware semaphore ID
 * @return 0 if acquired, -EBUSY if already locked, negative errno on error
 */
int ipc_hw_sem_take(ipc_hw_semaphore_t sem);

/**
 * Release hardware IPC semaphore
 *
 * @param sem  Hardware semaphore ID
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_sem_give(ipc_hw_semaphore_t sem);

/**
 * Get IPC hardware interrupt statistics
 *
 * @param stats  Pointer to statistics structure
 */
void ipc_hw_get_stats(struct ipc_hw_stats_s *stats);

/**
 * Reset IPC hardware interrupt statistics
 */
void ipc_hw_reset_stats(void);

__END_DECLS
