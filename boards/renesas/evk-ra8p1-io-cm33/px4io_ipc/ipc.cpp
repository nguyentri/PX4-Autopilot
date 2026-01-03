#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <stdint.h>
#include <string.h>
#include <errno.h>

#include "protocol.h"
#include "px4io.h"

// Defined in linker script
extern uint8_t _sipc_ram[];
extern uint8_t _eipc_ram[];

#define IPC_BUFFER_SIZE 4096

struct IpcRingBuffer {
	volatile uint32_t head;
	volatile uint32_t tail;
	uint32_t size;
	uint8_t data[IPC_BUFFER_SIZE];
};

struct IpcSharedMemory {
	IpcRingBuffer tx; // CM33 -> CM85
	IpcRingBuffer rx; // CM85 -> CM33
};

static IpcSharedMemory *g_shmem = (IpcSharedMemory *)_sipc_ram;

static void ipc_ring_init(IpcRingBuffer *ring) {
	ring->head = 0;
	ring->tail = 0;
	ring->size = IPC_BUFFER_SIZE;
	memset(ring->data, 0, IPC_BUFFER_SIZE);
}

void ipc_init(void) {
	// Initialize shared memory
	// Note: In a real scenario, we might want to check if CM85 already initialized it
	// or have a handshake. For now, we assume CM33 initializes it or we just reset pointers.
	// Actually, usually the master (CM85) might init it.
	// But since we are defining the firmware here, let's init it.
	ipc_ring_init(&g_shmem->tx);
	ipc_ring_init(&g_shmem->rx);
}

bool ipc_write(const void *data, size_t len) {
	IpcRingBuffer *ring = &g_shmem->tx;
	uint32_t head = ring->head;
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;
	uint32_t next_head = (head + len) % size;

	// Check overflow (simplified, assumes len < size)
	uint32_t free_space = (tail > head) ? (tail - head - 1) : (size - head + tail - 1);
	if (len > free_space) {
		return false;
	}

	const uint8_t *buf = (const uint8_t *)data;
	for (size_t i = 0; i < len; i++) {
		ring->data[(head + i) % size] = buf[i];
	}

	// Memory barrier to ensure data is written before head update
	ARM_DSB();
	ring->head = (head + len) % size;

	// Trigger interrupt to CM85 (Doorbell)
	// TODO: Implement doorbell trigger
	return true;
}

bool ipc_read(void *data, size_t len) {
	IpcRingBuffer *ring = &g_shmem->rx;
	uint32_t head = ring->head;
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;

	uint32_t available = (head >= tail) ? (head - tail) : (size - tail + head);
	if (available < len) {
		return false;
	}

	uint8_t *buf = (uint8_t *)data;
	for (size_t i = 0; i < len; i++) {
		buf[i] = ring->data[(tail + i) % size];
	}

	// Memory barrier
	ARM_DSB();
	ring->tail = (tail + len) % size;
	return true;
}

uint32_t ipc_available(void) {
	IpcRingBuffer *ring = &g_shmem->rx;
	uint32_t head = ring->head;
	uint32_t tail = ring->tail;
	uint32_t size = ring->size;
	return (head >= tail) ? (head - tail) : (size - tail + head);
}
