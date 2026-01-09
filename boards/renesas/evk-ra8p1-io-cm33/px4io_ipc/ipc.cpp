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
 * @file ipc.cpp
 *
 * RA8P1 CM33 IPC Implementation
 *
 * This module implements shared memory ring buffers for inter-core
 * communication between CM85 (FMU) and CM33 (IO).
 */

#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <stdint.h>
#include <string.h>
#include <errno.h>

#include <drivers/drv_hrt.h>

#include "ipc.h"
#include "protocol.h"

/*******************************************************************************
 * Memory Barriers for Multi-Core Synchronization
 *
 * ARM Cortex-M memory barriers ensure proper ordering of shared memory accesses.
 * - DMB: Data Memory Barrier - ensures all memory accesses complete
 * - DSB: Data Synchronization Barrier - ensures all memory transactions complete
 * - ISB: Instruction Synchronization Barrier - flushes pipeline
 ******************************************************************************/

#ifndef ARM_DMB
#define ARM_DMB()   __asm__ __volatile__ ("dmb sy" ::: "memory")
#endif

#ifndef ARM_DSB
#define ARM_DSB()   __asm__ __volatile__ ("dsb sy" ::: "memory")
#endif

#ifndef ARM_ISB
#define ARM_ISB()   __asm__ __volatile__ ("isb sy" ::: "memory")
#endif

/*******************************************************************************
 * Linker-Defined Symbols for IPC Shared Memory
 ******************************************************************************/

extern uint8_t _sipc_ram[];
extern uint8_t _eipc_ram[];

/*******************************************************************************
 * Ring Buffer Structure
 *
 * Each ring buffer is contained entirely within the shared memory region.
 * Head/tail indices are volatile to prevent compiler optimization issues.
 ******************************************************************************/

struct IpcRingBuffer {
	volatile uint32_t head;         /* Write index (producer updates) */
	volatile uint32_t tail;         /* Read index (consumer updates) */
	uint32_t          size;         /* Buffer size (fixed at init) */
	uint32_t          _reserved;    /* Padding for alignment */
	uint8_t           data[IPC_BUFFER_SIZE];
};

/*******************************************************************************
 * Shared Memory Layout
 *
 * The shared memory region contains:
 * - Magic number and initialization flags
 * - TX ring buffer (CM33 → CM85)
 * - RX ring buffer (CM85 → CM33)
 * - Optional handshake/sync data
 ******************************************************************************/

struct IpcSharedMemory {
	uint32_t       magic;           /* PX4IO_IPC_MAGIC when initialized */
	uint32_t       init_complete;   /* PX4IO_IPC_MAGIC_INIT when ready */
	uint32_t       endian_marker;   /* Endian check value */
	uint32_t       _reserved;       /* Padding */
	IpcRingBuffer  tx;              /* CM33 → CM85 */
	IpcRingBuffer  rx;              /* CM85 → CM33 */
};

/*******************************************************************************
 * Module State
 ******************************************************************************/

static IpcSharedMemory *g_shmem = nullptr;
static bool g_initialized = false;
static struct ipc_stats_s g_stats;
static uint16_t g_tx_sequence = 0;

/*******************************************************************************
 * Private Functions
 ******************************************************************************/

/**
 * @brief Initialize a ring buffer
 */
static void ring_init(IpcRingBuffer *ring)
{
	ring->head = 0;
	ring->tail = 0;
	ring->size = IPC_BUFFER_SIZE;
	ring->_reserved = 0;
	memset((void *)ring->data, 0, IPC_BUFFER_SIZE);

	ARM_DSB();
}

/**
 * @brief Get bytes available for reading in ring buffer
 */
static inline uint32_t ring_available(const IpcRingBuffer *ring)
{
	ARM_DMB();
	uint32_t head = ring->head;
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;

	if (head >= tail) {
		return head - tail;

	} else {
		return size - tail + head;
	}
}

/**
 * @brief Get free space for writing in ring buffer
 */
static inline uint32_t ring_free(const IpcRingBuffer *ring)
{
	ARM_DMB();
	uint32_t head = ring->head;
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;

	if (tail > head) {
		return tail - head - 1;

	} else {
		return size - head + tail - 1;
	}
}

/**
 * @brief Write data to ring buffer
 *
 * @param ring  Ring buffer pointer
 * @param data  Data to write
 * @param len   Length of data
 * @return      Number of bytes written
 */
static int ring_write(IpcRingBuffer *ring, const void *data, size_t len)
{
	uint32_t free_space = ring_free(ring);

	if (len > free_space) {
		return IPC_ERR_BUFFER_FULL;
	}

	const uint8_t *src = static_cast<const uint8_t *>(data);
	uint32_t head = ring->head;
	uint32_t size = ring->size;

	/* Copy data to ring buffer (may wrap) */
	for (size_t i = 0; i < len; i++) {
		ring->data[(head + i) % size] = src[i];
	}

	/* Memory barrier before updating head pointer */
	ARM_DSB();

	ring->head = (head + len) % size;

	return static_cast<int>(len);
}

/**
 * @brief Read data from ring buffer
 *
 * @param ring  Ring buffer pointer
 * @param data  Buffer to store data
 * @param len   Maximum bytes to read
 * @return      Number of bytes read
 */
static int ring_read(IpcRingBuffer *ring, void *data, size_t len)
{
	uint32_t available = ring_available(ring);

	if (available < len) {
		len = available;
	}

	if (len == 0) {
		return 0;
	}

	uint8_t *dst = static_cast<uint8_t *>(data);
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;

	/* Copy data from ring buffer (may wrap) */
	for (size_t i = 0; i < len; i++) {
		dst[i] = ring->data[(tail + i) % size];
	}

	/* Memory barrier before updating tail pointer */
	ARM_DSB();

	ring->tail = (tail + len) % size;

	return static_cast<int>(len);
}

/**
 * @brief Peek at data in ring buffer without consuming
 */
static int ring_peek(const IpcRingBuffer *ring, void *data, size_t len)
{
	uint32_t available = ring_available(ring);

	if (available < len) {
		len = available;
	}

	if (len == 0) {
		return 0;
	}

	uint8_t *dst = static_cast<uint8_t *>(data);
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;

	/* Copy data without updating tail */
	for (size_t i = 0; i < len; i++) {
		dst[i] = ring->data[(tail + i) % size];
	}

	return static_cast<int>(len);
}

/**
 * @brief Skip bytes in ring buffer
 */
static int ring_skip(IpcRingBuffer *ring, size_t len)
{
	uint32_t available = ring_available(ring);

	if (available < len) {
		len = available;
	}

	if (len == 0) {
		return 0;
	}

	ARM_DSB();
	ring->tail = (ring->tail + len) % ring->size;

	return static_cast<int>(len);
}

/*******************************************************************************
 * Public API Implementation
 ******************************************************************************/

int ipc_init(void)
{
	/* Validate shared memory region */
	size_t shmem_size = static_cast<size_t>(_eipc_ram - _sipc_ram);

	if (shmem_size < sizeof(IpcSharedMemory)) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	g_shmem = reinterpret_cast<IpcSharedMemory *>(_sipc_ram);

	/* Initialize shared memory structure */
	/* Note: CM33 initializes; CM85 checks for magic before use */
	g_shmem->magic = PX4IO_IPC_MAGIC;
	g_shmem->endian_marker = PX4IO_ENDIAN_MARKER;

	ring_init(&g_shmem->tx);
	ring_init(&g_shmem->rx);

	/* Mark initialization complete */
	ARM_DSB();
	g_shmem->init_complete = PX4IO_IPC_MAGIC_INIT;

	/* Reset statistics */
	memset(&g_stats, 0, sizeof(g_stats));
	g_tx_sequence = 0;

	/* TODO: Configure doorbell interrupt
	 * up_enable_irq(BOARD_IPC_IRQ_CM85_TO_CM33);
	 * irq_attach(BOARD_IPC_IRQ_CM85_TO_CM33, ipc_doorbell_isr, NULL);
	 */

	g_initialized = true;

	return IPC_OK;
}

void ipc_deinit(void)
{
	/* TODO: Disable doorbell interrupt */
	g_initialized = false;
}

bool ipc_is_ready(void)
{
	if (!g_initialized || g_shmem == nullptr) {
		return false;
	}

	ARM_DMB();
	return (g_shmem->magic == PX4IO_IPC_MAGIC &&
		g_shmem->init_complete == PX4IO_IPC_MAGIC_INIT);
}

int ipc_write(const void *data, size_t len, bool trigger)
{
	if (!g_initialized || g_shmem == nullptr) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	int result = ring_write(&g_shmem->tx, data, len);

	if (result > 0) {
		g_stats.tx_bytes += result;

		if (trigger) {
			ipc_trigger_doorbell();
		}

	} else {
		g_stats.tx_errors++;
	}

	return result;
}

int ipc_read(void *data, size_t len)
{
	if (!g_initialized || g_shmem == nullptr) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	int result = ring_read(&g_shmem->rx, data, len);

	if (result > 0) {
		g_stats.rx_bytes += result;
	}

	return result;
}

int ipc_peek(void *data, size_t len)
{
	if (!g_initialized || g_shmem == nullptr) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	return ring_peek(&g_shmem->rx, data, len);
}

int ipc_skip(size_t len)
{
	if (!g_initialized || g_shmem == nullptr) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	return ring_skip(&g_shmem->rx, len);
}

uint32_t ipc_available(void)
{
	if (!g_initialized || g_shmem == nullptr) {
		return 0;
	}

	return ring_available(&g_shmem->rx);
}

uint32_t ipc_tx_free(void)
{
	if (!g_initialized || g_shmem == nullptr) {
		return 0;
	}

	return ring_free(&g_shmem->tx);
}

void ipc_trigger_doorbell(void)
{
	/* TODO: Trigger hardware doorbell interrupt to CM85
	 * This is RA8P1-specific and may use the IPC/IPCC peripheral
	 * or a software interrupt mechanism.
	 *
	 * Example for RA8:
	 * putreg32(1, RA8_IPC_DOORBELL_CM33_TO_CM85);
	 */

	ARM_DSB();
	g_stats.doorbell_tx++;
}

int ipc_send_message(IpcFrameType type, const void *payload, uint16_t payload_len)
{
	if (!g_initialized) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	if (payload_len > IPC_MAX_MESSAGE_SIZE) {
		return IPC_ERR_MESSAGE_TOO_LARGE;
	}

	/* Check if there's enough space for header + payload */
	uint32_t total_len = sizeof(IpcHeader) + payload_len;

	if (ipc_tx_free() < total_len) {
		g_stats.tx_errors++;
		return IPC_ERR_BUFFER_FULL;
	}

	/* Build header */
	IpcHeader header;
	header.magic = PX4IO_IPC_MAGIC;
	header.version = PX4IO_IPC_PROTOCOL_VERSION;
	header.type = type;
	header.sequence = g_tx_sequence++;
	header.timestamp_us = hrt_absolute_time();
	header.payload_len = payload_len;
	header.crc16 = 0;  /* Will be calculated */

	/* Calculate CRC over header + payload */
	header.crc16 = ipc_calculate_message_crc(&header, payload);

	/* Write header (without doorbell trigger) */
	int result = ipc_write(&header, sizeof(header), false);

	if (result < 0) {
		return result;
	}

	/* Write payload if present (with doorbell trigger) */
	if (payload_len > 0 && payload != nullptr) {
		result = ipc_write(payload, payload_len, true);

		if (result < 0) {
			return result;
		}

	} else {
		ipc_trigger_doorbell();
	}

	g_stats.tx_messages++;
	return IPC_OK;
}

int ipc_receive_message(IpcHeader *header, void *payload, size_t max_payload)
{
	if (!g_initialized) {
		return IPC_ERR_NOT_INITIALIZED;
	}

	/* Check if enough data for header */
	if (ipc_available() < sizeof(IpcHeader)) {
		return IPC_ERR_BUFFER_EMPTY;
	}

	/* Peek at header first */
	IpcHeader peek_header;
	ipc_peek(&peek_header, sizeof(peek_header));

	/* Validate magic */
	if (peek_header.magic != PX4IO_IPC_MAGIC) {
		/* Sync lost - try to find magic */
		g_stats.rx_sync_lost++;

		/* Skip one byte and retry later */
		ipc_skip(1);
		return IPC_ERR_SYNC_LOST;
	}

	/* Check version compatibility */
	if (peek_header.version != PX4IO_IPC_PROTOCOL_VERSION) {
		g_stats.rx_errors++;
		ipc_skip(sizeof(IpcHeader));
		return IPC_ERR_VERSION_MISMATCH;
	}

	/* Check if full message is available */
	uint32_t total_len = sizeof(IpcHeader) + peek_header.payload_len;

	if (ipc_available() < total_len) {
		return IPC_ERR_BUFFER_EMPTY;
	}

	/* Check payload size */
	if (peek_header.payload_len > max_payload) {
		/* Skip this message */
		ipc_skip(total_len);
		return IPC_ERR_MESSAGE_TOO_LARGE;
	}

	/* Read header */
	ipc_read(header, sizeof(IpcHeader));

	/* Read payload if present */
	if (header->payload_len > 0) {
		ipc_read(payload, header->payload_len);
	}

	/* Validate CRC */
	uint16_t stored_crc = header->crc16;
	header->crc16 = 0;
	uint16_t calc_crc = ipc_calculate_message_crc(header, payload);
	header->crc16 = stored_crc;

	if (calc_crc != stored_crc) {
		g_stats.rx_crc_errors++;
		return IPC_ERR_CRC_MISMATCH;
	}

	g_stats.rx_messages++;
	return static_cast<int>(header->payload_len);
}

void ipc_get_stats(struct ipc_stats_s *stats)
{
	if (stats != nullptr) {
		memcpy(stats, &g_stats, sizeof(g_stats));
	}
}

void ipc_reset_stats(void)
{
	memset(&g_stats, 0, sizeof(g_stats));
}

void ipc_doorbell_isr(void)
{
	/* Called from interrupt context when CM85 triggers doorbell */
	g_stats.doorbell_rx++;

	/* Clear interrupt (RA8P1-specific) */
	/* TODO: putreg32(1, RA8_IPC_DOORBELL_CLEAR); */

	/* Signal main loop that data is available */
	/* This could use a semaphore, event flag, or just a volatile flag */
}

int ipc_poll(void)
{
	/* Non-blocking poll for messages - called from main loop */
	int messages_processed = 0;

	while (ipc_available() >= sizeof(IpcHeader)) {
		/* Try to receive a message */
		IpcHeader header;
		uint8_t payload[IPC_MAX_MESSAGE_SIZE];

		int result = ipc_receive_message(&header, payload, sizeof(payload));

		if (result == IPC_ERR_BUFFER_EMPTY) {
			break;  /* No more complete messages */

		} else if (result < 0) {
			/* Error - already logged in receive function */
			continue;
		}

		/* Message received successfully - handled by caller */
		messages_processed++;
	}

	return messages_processed;
}
