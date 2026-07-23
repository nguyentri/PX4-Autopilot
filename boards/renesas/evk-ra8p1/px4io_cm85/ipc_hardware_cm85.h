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
 * @file ipc_hardware_cm85.h
 *
 * RA8P1 Hardware IPC Interrupt API for CM85 (FMU)
 *
 * This header defines the interface for hardware IPC interrupt integration
 * on the CM85 core using the NuttX RA8 IPC driver.
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
 * IPC Logical Channels (application layer - CM85 perspective)
 */
typedef enum {
	IPC_HW_CM85_CH_ACTUATOR   = 0,  /**< Actuator commands (CM85 → CM33, TX) */
	IPC_HW_CM85_CH_RC_INPUT   = 1,  /**< RC input data (CM33 → CM85, RX) */
	IPC_HW_CM85_CH_BATTERY    = 2,  /**< Battery status (CM33 → CM85, RX) */
	IPC_HW_CM85_CH_HEARTBEAT  = 3,  /**< Heartbeat/control (bidirectional) */
} ipc_hw_cm85_channel_t;

/**
 * IPC Hardware Semaphores for shared memory protection
 */
typedef enum {
	IPC_HW_CM85_SEM_ACTUATOR  = 0,  /**< Protects IpcActuatorCmd structure */
	IPC_HW_CM85_SEM_RC_INPUT  = 1,  /**< Protects IpcRcInput structure */
	IPC_HW_CM85_SEM_BATTERY   = 2,  /**< Protects IpcBatteryStatus structure */
} ipc_hw_cm85_semaphore_t;

/**
 * IPC Interrupt Callback Function Type
 *
 * @param channel  Logical channel that triggered interrupt
 * @param data     32-bit data from IPC FIFO (can be sequence number, timestamp, etc.)
 */
typedef void (*ipc_hw_cm85_callback_t)(uint32_t channel, uint32_t data);

/**
 * IPC Hardware Statistics
 */
struct ipc_hw_cm85_stats_s {
	uint32_t ch0_irq_count;  /**< Channel 0 interrupt count (actuator ACK) */
	uint32_t ch1_irq_count;  /**< Channel 1 interrupt count (RC input RX) */
	uint32_t ch2_irq_count;  /**< Channel 2 interrupt count (battery RX) */
	uint32_t ch3_irq_count;  /**< Channel 3 interrupt count (heartbeat) */
};

/*******************************************************************************
 * Public Function Prototypes
 ******************************************************************************/

/**
 * Initialize hardware IPC subsystem for CM85
 *
 * This function:
 * - Initializes the NuttX RA8 IPC driver
 * - Registers interrupt handlers for all 4 IPC channels
 * - Creates semaphores for blocking wait operations
 * - Enables hardware interrupts
 *
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_cm85_init(void);

/**
 * Deinitialize hardware IPC subsystem
 */
void ipc_hw_cm85_deinit(void);

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
int ipc_hw_cm85_register_callback(ipc_hw_cm85_channel_t channel, ipc_hw_cm85_callback_t callback);

/**
 * Send notification to CM33 via IPC interrupt
 *
 * This function writes a 32-bit value to the IPC channel FIFO and
 * triggers an IRQ0 interrupt on the CM33 core.
 *
 * Typical usage:
 * 1. CM85 writes actuator commands to shared memory
 * 2. CM85 calls ipc_hw_cm85_notify_cm33(IPC_HW_CM85_CH_ACTUATOR, sequence_number)
 * 3. CM33 receives interrupt and reads shared memory
 *
 * @param channel  Logical IPC channel
 * @param data     32-bit notification data (sequence number, timestamp, etc.)
 * @return 0 on success, -EBUSY if FIFO full, negative errno on other errors
 */
int ipc_hw_cm85_notify_cm33(ipc_hw_cm85_channel_t channel, uint32_t data);

/**
 * Wait for RC input interrupt (blocking)
 *
 * This function blocks until the CM33 sends new RC data via IPC interrupt.
 * Useful for synchronous processing models.
 *
 * @param timeout_ms  Timeout in milliseconds (0 = non-blocking check)
 * @return 0 on success (interrupt received), -ETIMEDOUT on timeout,
 *         -EAGAIN for non-blocking when no data available
 */
int ipc_hw_cm85_wait_rc_input(uint32_t timeout_ms);

/**
 * Wait for battery status interrupt (blocking)
 *
 * @param timeout_ms  Timeout in milliseconds (0 = non-blocking check)
 * @return 0 on success, -ETIMEDOUT on timeout
 */
int ipc_hw_cm85_wait_battery(uint32_t timeout_ms);

/**
 * Wait for heartbeat interrupt (blocking)
 *
 * @param timeout_ms  Timeout in milliseconds (0 = non-blocking check)
 * @return 0 on success, -ETIMEDOUT on timeout
 */
int ipc_hw_cm85_wait_heartbeat(uint32_t timeout_ms);

/**
 * Acquire hardware IPC semaphore (non-blocking)
 *
 * Use this to protect shared memory access between cores.
 *
 * Example:
 * ```
 * if (ipc_hw_cm85_sem_take(IPC_HW_CM85_SEM_ACTUATOR) == 0) {
 *     // Write to IpcActuatorCmd shared memory
 *     memcpy(ipc_actuator_cmd, &data, sizeof(data));
 *     ipc_hw_cm85_sem_give(IPC_HW_CM85_SEM_ACTUATOR);
 *     ipc_hw_cm85_notify_cm33(IPC_HW_CM85_CH_ACTUATOR, sequence_number);
 * }
 * ```
 *
 * @param sem  Hardware semaphore ID
 * @return 0 if acquired, -EBUSY if already locked, negative errno on error
 */
int ipc_hw_cm85_sem_take(ipc_hw_cm85_semaphore_t sem);

/**
 * Release hardware IPC semaphore
 *
 * @param sem  Hardware semaphore ID
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_cm85_sem_give(ipc_hw_cm85_semaphore_t sem);

/**
 * Get IPC hardware interrupt statistics
 *
 * @param stats  Pointer to statistics structure
 */
void ipc_hw_cm85_get_stats(struct ipc_hw_cm85_stats_s *stats);

/**
 * Reset IPC hardware interrupt statistics
 */
void ipc_hw_cm85_reset_stats(void);

/*******************************************************************************
 * CRC Validation Functions for Shared Memory Messages
 ******************************************************************************/

/**
 * Read and validate RC input from shared memory with CRC check
 *
 * This function reads the rc_input structure from shared memory, validates
 * its CRC16-CCITT checksum, and copies it to the provided buffer.
 *
 * @param rc_input  Pointer to destination buffer for validated RC input
 * @return 0 on success with valid CRC, -EBADMSG if CRC invalid,
 *         -EAGAIN if no new data, negative errno on other errors
 */
int ipc_hw_cm85_read_rc_input_validated(struct ipc_rc_input_t *rc_input);

/**
 * Read and validate battery status from shared memory with CRC check
 *
 * @param battery  Pointer to destination buffer for validated battery status
 * @return 0 on success with valid CRC, -EBADMSG if CRC invalid,
 *         negative errno on other errors
 */
int ipc_hw_cm85_read_battery_validated(struct ipc_battery_status_t *battery);

/**
 * Read and validate CM33 heartbeat from shared memory with CRC check
 *
 * @param heartbeat  Pointer to destination buffer for validated heartbeat
 * @return 0 on success with valid CRC, -EBADMSG if CRC invalid,
 *         negative errno on other errors
 */
int ipc_hw_cm85_read_heartbeat_cm33_validated(struct ipc_heartbeat_cm33_t *heartbeat);

/**
 * Write actuator command to shared memory with CRC generation
 *
 * This function calculates CRC16-CCITT, stores it in the message,
 * and writes to shared memory with proper synchronization.
 *
 * @param actuator  Pointer to actuator command to send
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_cm85_write_actuator_cmd(struct ipc_actuator_cmd_t *actuator);

/**
 * Write CM85 heartbeat to shared memory with CRC generation
 *
 * @param heartbeat  Pointer to heartbeat message to send
 * @return 0 on success, negative errno on failure
 */
int ipc_hw_cm85_write_heartbeat_cm85(struct ipc_heartbeat_cm85_t *heartbeat);

/**
 * Get CRC error count for diagnostics
 *
 * @return Number of CRC validation failures since initialization
 */
uint32_t ipc_hw_cm85_get_crc_error_count(void);

__END_DECLS
