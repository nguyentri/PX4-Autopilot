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
 * @file ipc.h
 *
 * RA8P1 CM33 IPC (Inter-Processor Communication) Interface
 *
 * This module provides the transport layer for CM85 ↔ CM33 communication
 * using shared memory ring buffers and hardware doorbell interrupts.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#include "protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/*******************************************************************************
 * IPC Configuration
 ******************************************************************************/

#define IPC_BUFFER_SIZE             4096    /* Ring buffer size per direction */
#define IPC_MAX_MESSAGE_SIZE        256     /* Maximum single message size */

/*******************************************************************************
 * IPC Error Codes
 ******************************************************************************/

#define IPC_OK                      0
#define IPC_ERR_NOT_INITIALIZED     -1
#define IPC_ERR_BUFFER_FULL         -2
#define IPC_ERR_BUFFER_EMPTY        -3
#define IPC_ERR_CRC_MISMATCH        -4
#define IPC_ERR_MAGIC_INVALID       -5
#define IPC_ERR_VERSION_MISMATCH    -6
#define IPC_ERR_MESSAGE_TOO_LARGE   -7
#define IPC_ERR_SYNC_LOST           -8
#define IPC_ERR_TIMEOUT             -9

/*******************************************************************************
 * IPC Statistics
 ******************************************************************************/

struct ipc_stats_s {
	uint32_t tx_messages;           /* Total messages sent */
	uint32_t rx_messages;           /* Total messages received */
	uint32_t tx_bytes;              /* Total bytes sent */
	uint32_t rx_bytes;              /* Total bytes received */
	uint32_t tx_errors;             /* Transmit errors (overflow) */
	uint32_t rx_errors;             /* Receive errors (CRC, sync) */
	uint32_t rx_crc_errors;         /* CRC validation failures */
	uint32_t rx_sync_lost;          /* Sync loss count */
	uint32_t rx_overflows;          /* Buffer overflow count */
	uint32_t doorbell_tx;           /* Doorbell triggers sent */
	uint32_t doorbell_rx;           /* Doorbell interrupts received */
	uint32_t last_latency_us;       /* Last measured RTT (µs) */
	uint32_t avg_latency_us;        /* Average RTT (µs) */
	uint32_t max_latency_us;        /* Maximum RTT (µs) */
};

/*******************************************************************************
 * Public API
 ******************************************************************************/

/**
 * @brief Initialize the IPC subsystem
 *
 * Sets up shared memory ring buffers, configures doorbell interrupts,
 * and performs initial synchronization with CM85.
 *
 * @return IPC_OK on success, negative error code on failure
 */
int ipc_init(void);

/**
 * @brief Deinitialize the IPC subsystem
 */
void ipc_deinit(void);

/**
 * @brief Check if IPC is initialized and ready
 *
 * @return true if ready, false otherwise
 */
bool ipc_is_ready(void);

/**
 * @brief Write data to the TX ring buffer
 *
 * Writes a message to the outgoing ring buffer and optionally triggers
 * the doorbell interrupt to notify CM85.
 *
 * @param data      Pointer to data to send
 * @param len       Length of data in bytes
 * @param trigger   If true, trigger doorbell after write
 * @return          Number of bytes written, or negative error code
 */
int ipc_write(const void *data, size_t len, bool trigger);

/**
 * @brief Read data from the RX ring buffer
 *
 * Reads up to 'len' bytes from the incoming ring buffer.
 *
 * @param data      Buffer to store received data
 * @param len       Maximum bytes to read
 * @return          Number of bytes read, or negative error code
 */
int ipc_read(void *data, size_t len);

/**
 * @brief Peek at data in the RX ring buffer without consuming
 *
 * @param data      Buffer to store peeked data
 * @param len       Maximum bytes to peek
 * @return          Number of bytes available to peek
 */
int ipc_peek(void *data, size_t len);

/**
 * @brief Skip bytes in the RX ring buffer
 *
 * @param len       Number of bytes to skip
 * @return          Number of bytes skipped
 */
int ipc_skip(size_t len);

/**
 * @brief Get number of bytes available for reading
 *
 * @return Number of bytes available in RX buffer
 */
uint32_t ipc_available(void);

/**
 * @brief Get free space in TX buffer
 *
 * @return Number of bytes free in TX buffer
 */
uint32_t ipc_tx_free(void);

/**
 * @brief Trigger doorbell interrupt to notify CM85
 */
void ipc_trigger_doorbell(void);

/**
 * @brief Send a complete IPC message
 *
 * Constructs a message with header, calculates CRC, and sends atomically.
 *
 * @param type          Message type
 * @param payload       Payload data (can be NULL for header-only messages)
 * @param payload_len   Length of payload
 * @return              IPC_OK on success, negative error code on failure
 */
#ifdef __cplusplus
int ipc_send_message(IpcFrameType type, const void *payload, uint16_t payload_len);
#else
int ipc_send_message(uint8_t type, const void *payload, uint16_t payload_len);
#endif

/**
 * @brief Receive a complete IPC message
 *
 * Reads a message from the RX buffer, validates CRC, and returns header + payload.
 *
 * @param header        Pointer to store received header
 * @param payload       Buffer to store payload (must be at least IPC_MAX_MESSAGE_SIZE)
 * @param max_payload   Maximum payload size
 * @return              Payload length on success, negative error code on failure
 */
int ipc_receive_message(struct IpcHeader *header, void *payload, size_t max_payload);

/**
 * @brief Get IPC statistics
 *
 * @param stats     Pointer to statistics structure to fill
 */
void ipc_get_stats(struct ipc_stats_s *stats);

/**
 * @brief Reset IPC statistics
 */
void ipc_reset_stats(void);

/**
 * @brief Doorbell interrupt handler (called from ISR)
 *
 * This function is called when CM85 triggers the doorbell interrupt.
 * It should be called from the NuttX IRQ handler.
 */
void ipc_doorbell_isr(void);

/**
 * @brief Poll for incoming messages (non-blocking)
 *
 * Call this from the main loop to process any pending messages.
 *
 * @return Number of messages processed, or negative error code
 */
int ipc_poll(void);

#ifdef __cplusplus
}
#endif
