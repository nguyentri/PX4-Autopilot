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
 * @file ipc_hardware_cm85.cpp
 *
 * RA8P1 Hardware IPC Interrupt Integration for CM85 (FMU)
 *
 * This module integrates the NuttX RA8 IPC driver to provide
 * interrupt-driven inter-core communication between CM85 (FMU) and
 * CM33 (IO processor).
 *
 * Hardware IPC Features:
 * - Hardware FIFOs for message passing (8-deep)
 * - Hardware semaphores for mutual exclusion (16 semaphores)
 * - Hardware interrupts (IRQ0-IRQ7 per channel, 4 channels total)
 * - NMI inter-core interrupt support
 *
 * Implementation Strategy:
 * - Channel 0: CM85→CM33 actuator commands (TX from CM85)
 * - Channel 1: CM33→CM85 RC input (RX on CM85)
 * - Channel 2: CM33→CM85 battery status (RX on CM85)
 * - Channel 3: Bidirectional heartbeat/control
 * - Semaphore 0: Shared memory protection for actuator_cmd
 * - Semaphore 1: Shared memory protection for rc_input
 * - Semaphore 2: Shared memory protection for battery_status
 *
 * @author PX4 Development Team
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/log.h>
#include <px4_platform_common/sem.h>

#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <stdint.h>
#include <string.h>
#include <errno.h>

#include <arch/board/board.h>

/* Include NuttX RA8 IPC driver */
extern "C" {
#include "../../nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_ipc.h"
}

#include "ipc_hardware_cm85.h"
#include "ipc_protocol.h"

/*******************************************************************************
 * Definitions
 ******************************************************************************/

/* IPC Channel Assignment (matches CM33) */
#define IPC_CH_ACTUATOR_CMD     0   /* CM85 → CM33: Actuator commands */
#define IPC_CH_RC_INPUT         1   /* CM33 → CM85: RC input data */
#define IPC_CH_BATTERY          2   /* CM33 → CM85: Battery status */
#define IPC_CH_HEARTBEAT        3   /* Bidirectional: Heartbeat/control */

/* IPC Semaphore Assignment */
#define IPC_SEM_ACTUATOR        0   /* Protects IpcActuatorCmd shared memory */
#define IPC_SEM_RC_INPUT        1   /* Protects IpcRcInput shared memory */
#define IPC_SEM_BATTERY         2   /* Protects IpcBatteryStatus shared memory */

/*******************************************************************************
 * Private Data
 ******************************************************************************/

static bool g_ipc_hw_initialized = false;

/* Semaphores for signaling from ISR to worker threads */
static px4_sem_t g_rc_input_sem;
static px4_sem_t g_battery_sem;
static px4_sem_t g_heartbeat_sem;

/* Callback function pointers */
static ipc_hw_cm85_callback_t g_actuator_callback = nullptr;
static ipc_hw_cm85_callback_t g_rc_callback = nullptr;
static ipc_hw_cm85_callback_t g_battery_callback = nullptr;
static ipc_hw_cm85_callback_t g_heartbeat_callback = nullptr;

/* Interrupt counters for debugging */
static volatile uint32_t g_ipc_ch0_irq_count = 0;
static volatile uint32_t g_ipc_ch1_irq_count = 0;
static volatile uint32_t g_ipc_ch2_irq_count = 0;
static volatile uint32_t g_ipc_ch3_irq_count = 0;

/*******************************************************************************
 * Private Functions
 ******************************************************************************/

/**
 * IPC Channel 0 Interrupt Callback (CM85 → CM33 Actuator Commands)
 * Note: This is TX channel from CM85, interrupt indicates acknowledgment
 */
static void ipc_ch0_actuator_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch0_irq_count++;

	/* Optional: Notify callback that command was acknowledged */
	if (g_actuator_callback) {
		g_actuator_callback(IPC_HW_CM85_CH_ACTUATOR, data);
	}
}

/**
 * IPC Channel 1 Interrupt Callback (CM33 → CM85 RC Input)
 * This is RX channel - interrupt indicates new RC data available
 */
static void ipc_ch1_rc_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch1_irq_count++;

	/* Signal semaphore to wake up RC processing */
	px4_sem_post(&g_rc_input_sem);

	/* Notify upper layer callback */
	if (g_rc_callback) {
		g_rc_callback(IPC_HW_CM85_CH_RC_INPUT, data);
	}
}

/**
 * IPC Channel 2 Interrupt Callback (CM33 → CM85 Battery Status)
 */
static void ipc_ch2_battery_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch2_irq_count++;

	/* Signal semaphore to wake up battery processing */
	px4_sem_post(&g_battery_sem);

	if (g_battery_callback) {
		g_battery_callback(IPC_HW_CM85_CH_BATTERY, data);
	}
}

/**
 * IPC Channel 3 Interrupt Callback (Bidirectional Heartbeat)
 */
static void ipc_ch3_heartbeat_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch3_irq_count++;

	/* Signal semaphore to wake up heartbeat monitoring */
	px4_sem_post(&g_heartbeat_sem);

	if (g_heartbeat_callback) {
		g_heartbeat_callback(IPC_HW_CM85_CH_HEARTBEAT, data);
	}
}

/*******************************************************************************
 * Public Functions
 ******************************************************************************/

/**
 * Initialize hardware IPC subsystem
 */
int ipc_hw_cm85_init(void)
{
	int ret;

	if (g_ipc_hw_initialized) {
		return 0;  /* Already initialized */
	}

	/* Initialize semaphores */
	ret = px4_sem_init(&g_rc_input_sem, 0, 0);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to init RC semaphore");
		return ret;
	}

	ret = px4_sem_init(&g_battery_sem, 0, 0);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to init battery semaphore");
		px4_sem_destroy(&g_rc_input_sem);
		return ret;
	}

	ret = px4_sem_init(&g_heartbeat_sem, 0, 0);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to init heartbeat semaphore");
		px4_sem_destroy(&g_rc_input_sem);
		px4_sem_destroy(&g_battery_sem);
		return ret;
	}

	/* Initialize NuttX IPC driver */
	ret = ra_ipc_initialize();

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: ra_ipc_initialize failed: %d", ret);
		px4_sem_destroy(&g_rc_input_sem);
		px4_sem_destroy(&g_battery_sem);
		px4_sem_destroy(&g_heartbeat_sem);
		return ret;
	}

	/* Register channel callbacks */
	/* Channel 0: Acknowledge actuator commands sent to CM33 (optional) */
	ret = ra_ipc_channel_register(IPC_CH_ACTUATOR_CMD, ipc_ch0_actuator_callback);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to register CH0 callback: %d", ret);
		return ret;
	}

	/* Channel 1: Receive RC input from CM33 */
	ret = ra_ipc_channel_register(IPC_CH_RC_INPUT, ipc_ch1_rc_callback);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to register CH1 callback: %d", ret);
		return ret;
	}

	/* Channel 2: Receive battery status from CM33 */
	ret = ra_ipc_channel_register(IPC_CH_BATTERY, ipc_ch2_battery_callback);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to register CH2 callback: %d", ret);
		return ret;
	}

	/* Channel 3: Heartbeat from CM33 */
	ret = ra_ipc_channel_register(IPC_CH_HEARTBEAT, ipc_ch3_heartbeat_callback);

	if (ret < 0) {
		PX4_ERR("ipc_hw_cm85: Failed to register CH3 callback: %d", ret);
		return ret;
	}

	g_ipc_hw_initialized = true;

	PX4_INFO("ipc_hw_cm85: Hardware IPC initialized for CM85 (core %d)", CONFIG_RA_CPU_CORE);

	return 0;
}

/**
 * Deinitialize hardware IPC
 */
void ipc_hw_cm85_deinit(void)
{
	if (!g_ipc_hw_initialized) {
		return;
	}

	/* Unregister all callbacks */
	ra_ipc_channel_unregister(IPC_CH_ACTUATOR_CMD);
	ra_ipc_channel_unregister(IPC_CH_RC_INPUT);
	ra_ipc_channel_unregister(IPC_CH_BATTERY);
	ra_ipc_channel_unregister(IPC_CH_HEARTBEAT);

	/* Destroy semaphores */
	px4_sem_destroy(&g_rc_input_sem);
	px4_sem_destroy(&g_battery_sem);
	px4_sem_destroy(&g_heartbeat_sem);

	g_actuator_callback = nullptr;
	g_rc_callback = nullptr;
	g_battery_callback = nullptr;
	g_heartbeat_callback = nullptr;

	g_ipc_hw_initialized = false;
}

/**
 * Register callback for upper layer notification
 */
int ipc_hw_cm85_register_callback(ipc_hw_cm85_channel_t channel, ipc_hw_cm85_callback_t callback)
{
	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (channel) {
	case IPC_HW_CM85_CH_ACTUATOR:
		g_actuator_callback = callback;
		break;

	case IPC_HW_CM85_CH_RC_INPUT:
		g_rc_callback = callback;
		break;

	case IPC_HW_CM85_CH_BATTERY:
		g_battery_callback = callback;
		break;

	case IPC_HW_CM85_CH_HEARTBEAT:
		g_heartbeat_callback = callback;
		break;

	default:
		return -EINVAL;
	}

	return 0;
}

/**
 * Send notification to CM33 (trigger interrupt)
 */
int ipc_hw_cm85_notify_cm33(ipc_hw_cm85_channel_t channel, uint32_t data)
{
	int ret;
	uint8_t hw_channel;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	/* Map logical channel to hardware channel */
	switch (channel) {
	case IPC_HW_CM85_CH_ACTUATOR:
		hw_channel = IPC_CH_ACTUATOR_CMD;
		break;

	case IPC_HW_CM85_CH_RC_INPUT:
		hw_channel = IPC_CH_RC_INPUT;
		break;

	case IPC_HW_CM85_CH_BATTERY:
		hw_channel = IPC_CH_BATTERY;
		break;

	case IPC_HW_CM85_CH_HEARTBEAT:
		hw_channel = IPC_CH_HEARTBEAT;
		break;

	default:
		return -EINVAL;
	}

	/* Write data to hardware channel FIFO and trigger IRQ0 interrupt */
	ret = ra_ipc_channel_write(hw_channel, data);

	if (ret < 0) {
		/* FIFO full or other error */
		return ret;
	}

	return 0;
}

/**
 * Validate CRC for received IPC message
 * Returns true if CRC is valid, false otherwise
 */
static bool ipc_validate_crc(const void *msg, size_t len, uint16_t expected_crc)
{
	uint16_t calculated_crc = ipc_crc16_ccitt(static_cast<const uint8_t *>(msg), len);
	return (calculated_crc == expected_crc);
}

/**
 * Wait for RC input notification (blocking) with CRC validation
 */
int ipc_hw_cm85_wait_rc_input(uint32_t timeout_ms)
{
	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	int ret;

	if (timeout_ms == 0) {
		/* Non-blocking check */
		ret = px4_sem_trywait(&g_rc_input_sem);
	} else {
		/* Blocking wait with timeout */
		struct timespec abstime;
		clock_gettime(CLOCK_REALTIME, &abstime);
		abstime.tv_sec += timeout_ms / 1000;
		abstime.tv_nsec += (timeout_ms % 1000) * 1000000;

		if (abstime.tv_nsec >= 1000000000) {
			abstime.tv_sec++;
			abstime.tv_nsec -= 1000000000;
		}

		ret = px4_sem_timedwait(&g_rc_input_sem, &abstime);
	}

	return ret;
}

/**
 * Wait for battery status notification (blocking) with CRC validation
 */
int ipc_hw_cm85_wait_battery(uint32_t timeout_ms)
{
	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	int ret;

	if (timeout_ms == 0) {
		ret = px4_sem_trywait(&g_battery_sem);
	} else {
		struct timespec abstime;
		clock_gettime(CLOCK_REALTIME, &abstime);
		abstime.tv_sec += timeout_ms / 1000;
		abstime.tv_nsec += (timeout_ms % 1000) * 1000000;

		if (abstime.tv_nsec >= 1000000000) {
			abstime.tv_sec++;
			abstime.tv_nsec -= 1000000000;
		}

		ret = px4_sem_timedwait(&g_battery_sem, &abstime);
	}

	return ret;
}

/**
 * Wait for heartbeat notification (blocking) with CRC validation
 */
int ipc_hw_cm85_wait_heartbeat(uint32_t timeout_ms)
{
	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	int ret;

	if (timeout_ms == 0) {
		ret = px4_sem_trywait(&g_heartbeat_sem);
	} else {
		struct timespec abstime;
		clock_gettime(CLOCK_REALTIME, &abstime);
		abstime.tv_sec += timeout_ms / 1000;
		abstime.tv_nsec += (timeout_ms % 1000) * 1000000;

		if (abstime.tv_nsec >= 1000000000) {
			abstime.tv_sec++;
			abstime.tv_nsec -= 1000000000;
		}

		ret = px4_sem_timedwait(&g_heartbeat_sem, &abstime);
	}

	return ret;
}

/**
 * Acquire IPC semaphore for shared memory protection
 */
int ipc_hw_cm85_sem_take(ipc_hw_cm85_semaphore_t sem)
{
	uint8_t sem_num;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (sem) {
	case IPC_HW_CM85_SEM_ACTUATOR:
		sem_num = IPC_SEM_ACTUATOR;
		break;

	case IPC_HW_CM85_SEM_RC_INPUT:
		sem_num = IPC_SEM_RC_INPUT;
		break;

	case IPC_HW_CM85_SEM_BATTERY:
		sem_num = IPC_SEM_BATTERY;
		break;

	default:
		return -EINVAL;
	}

	/* Non-blocking take */
	return ra_ipc_semaphore_take(sem_num);
}

/**
 * Release IPC semaphore
 */
int ipc_hw_cm85_sem_give(ipc_hw_cm85_semaphore_t sem)
{
	uint8_t sem_num;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (sem) {
	case IPC_HW_CM85_SEM_ACTUATOR:
		sem_num = IPC_SEM_ACTUATOR;
		break;

	case IPC_HW_CM85_SEM_RC_INPUT:
		sem_num = IPC_SEM_RC_INPUT;
		break;

	case IPC_HW_CM85_SEM_BATTERY:
		sem_num = IPC_SEM_BATTERY;
		break;

	default:
		return -EINVAL;
	}

	return ra_ipc_semaphore_give(sem_num);
}

/**
 * Get IPC interrupt statistics
 */
void ipc_hw_cm85_get_stats(struct ipc_hw_cm85_stats_s *stats)
{
	if (!stats) {
		return;
	}

	stats->ch0_irq_count = g_ipc_ch0_irq_count;
	stats->ch1_irq_count = g_ipc_ch1_irq_count;
	stats->ch2_irq_count = g_ipc_ch2_irq_count;
	stats->ch3_irq_count = g_ipc_ch3_irq_count;
}

/**
 * Reset statistics
 */
void ipc_hw_cm85_reset_stats(void)
{
	g_ipc_ch0_irq_count = 0;
	g_ipc_ch1_irq_count = 0;
	g_ipc_ch2_irq_count = 0;
	g_ipc_ch3_irq_count = 0;
}

/*******************************************************************************
 * CRC Validation Functions for Shared Memory Messages
 ******************************************************************************/

/* CRC error counter for statistics */
static volatile uint32_t g_crc_error_count = 0;

/**
 * Read and validate RC input from shared memory with CRC check
 */
int ipc_hw_cm85_read_rc_input_validated(ipc_rc_input_t *rc_input)
{
	if (!g_ipc_hw_initialized || rc_input == nullptr) {
		return -EINVAL;
	}

	/* Acquire semaphore for shared memory access */
	int ret = ipc_hw_cm85_sem_take(IPC_HW_CM85_SEM_RC_INPUT);

	if (ret != 0) {
		return ret;
	}

	/* Read from shared memory (volatile read) */
	volatile ipc_rc_input_t *shmem = reinterpret_cast<volatile ipc_rc_input_t *>(IPC_RC_INPUT_ADDR);

	/* Copy to local buffer */
	memcpy(rc_input, const_cast<const ipc_rc_input_t *>(shmem), sizeof(ipc_rc_input_t));

	/* Release semaphore */
	ipc_hw_cm85_sem_give(IPC_HW_CM85_SEM_RC_INPUT);

	/* Validate CRC */
	uint16_t calculated_crc = ipc_crc16_ccitt(reinterpret_cast<const uint8_t *>(rc_input),
				  offsetof(ipc_rc_input_t, crc16));

	if (calculated_crc != rc_input->crc16) {
		g_crc_error_count++;
		PX4_WARN("ipc_hw_cm85: RC input CRC mismatch (calc: 0x%04X, recv: 0x%04X)",
			 calculated_crc, rc_input->crc16);
		return -EBADMSG;
	}

	return 0;
}

/**
 * Read and validate battery status from shared memory with CRC check
 */
int ipc_hw_cm85_read_battery_validated(ipc_battery_status_t *battery)
{
	if (!g_ipc_hw_initialized || battery == nullptr) {
		return -EINVAL;
	}

	/* Acquire semaphore for shared memory access */
	int ret = ipc_hw_cm85_sem_take(IPC_HW_CM85_SEM_BATTERY);

	if (ret != 0) {
		return ret;
	}

	/* Read from shared memory */
	volatile ipc_battery_status_t *shmem = reinterpret_cast<volatile ipc_battery_status_t *>
					       (IPC_BATTERY_STATUS_ADDR);

	/* Copy to local buffer */
	memcpy(battery, const_cast<const ipc_battery_status_t *>(shmem), sizeof(ipc_battery_status_t));

	/* Release semaphore */
	ipc_hw_cm85_sem_give(IPC_HW_CM85_SEM_BATTERY);

	/* Validate CRC */
	uint16_t calculated_crc = ipc_crc16_ccitt(reinterpret_cast<const uint8_t *>(battery),
				  offsetof(ipc_battery_status_t, crc16));

	if (calculated_crc != battery->crc16) {
		g_crc_error_count++;
		PX4_WARN("ipc_hw_cm85: Battery CRC mismatch (calc: 0x%04X, recv: 0x%04X)",
			 calculated_crc, battery->crc16);
		return -EBADMSG;
	}

	return 0;
}

/**
 * Read and validate CM33 heartbeat from shared memory with CRC check
 */
int ipc_hw_cm85_read_heartbeat_cm33_validated(ipc_heartbeat_cm33_t *heartbeat)
{
	if (!g_ipc_hw_initialized || heartbeat == nullptr) {
		return -EINVAL;
	}

	/* Read from shared memory (no semaphore needed for heartbeat - single writer) */
	volatile ipc_heartbeat_cm33_t *shmem = reinterpret_cast<volatile ipc_heartbeat_cm33_t *>
					       (IPC_HEARTBEAT_CM33_ADDR);

	/* Copy to local buffer */
	memcpy(heartbeat, const_cast<const ipc_heartbeat_cm33_t *>(shmem), sizeof(ipc_heartbeat_cm33_t));

	/* Validate CRC */
	uint16_t calculated_crc = ipc_crc16_ccitt(reinterpret_cast<const uint8_t *>(heartbeat),
				  offsetof(ipc_heartbeat_cm33_t, crc16));

	if (calculated_crc != heartbeat->crc16) {
		g_crc_error_count++;
		PX4_WARN("ipc_hw_cm85: Heartbeat CM33 CRC mismatch (calc: 0x%04X, recv: 0x%04X)",
			 calculated_crc, heartbeat->crc16);
		return -EBADMSG;
	}

	return 0;
}

/**
 * Write actuator command to shared memory with CRC generation
 */
int ipc_hw_cm85_write_actuator_cmd(ipc_actuator_cmd_t *actuator)
{
	if (!g_ipc_hw_initialized || actuator == nullptr) {
		return -EINVAL;
	}

	/* Calculate and set CRC */
	actuator->crc16 = ipc_crc16_ccitt(reinterpret_cast<const uint8_t *>(actuator),
					  offsetof(ipc_actuator_cmd_t, crc16));

	/* Acquire semaphore for shared memory access */
	int ret = ipc_hw_cm85_sem_take(IPC_HW_CM85_SEM_ACTUATOR);

	if (ret != 0) {
		return ret;
	}

	/* Write to shared memory */
	volatile ipc_actuator_cmd_t *shmem = reinterpret_cast<volatile ipc_actuator_cmd_t *>(IPC_ACTUATOR_CMD_ADDR);
	memcpy(const_cast<ipc_actuator_cmd_t *>(shmem), actuator, sizeof(ipc_actuator_cmd_t));

	/* Memory barrier to ensure write completes before notification */
	__DMB();

	/* Release semaphore */
	ipc_hw_cm85_sem_give(IPC_HW_CM85_SEM_ACTUATOR);

	/* Notify CM33 */
	ret = ipc_hw_cm85_notify_cm33(IPC_HW_CM85_CH_ACTUATOR, actuator->sequence);

	return ret;
}

/**
 * Write CM85 heartbeat to shared memory with CRC generation
 */
int ipc_hw_cm85_write_heartbeat_cm85(ipc_heartbeat_cm85_t *heartbeat)
{
	if (!g_ipc_hw_initialized || heartbeat == nullptr) {
		return -EINVAL;
	}

	/* Calculate and set CRC */
	heartbeat->crc16 = ipc_crc16_ccitt(reinterpret_cast<const uint8_t *>(heartbeat),
					   offsetof(ipc_heartbeat_cm85_t, crc16));

	/* Write to shared memory (no semaphore needed - single writer) */
	volatile ipc_heartbeat_cm85_t *shmem = reinterpret_cast<volatile ipc_heartbeat_cm85_t *>
					       (IPC_HEARTBEAT_CM85_ADDR);
	memcpy(const_cast<ipc_heartbeat_cm85_t *>(shmem), heartbeat, sizeof(ipc_heartbeat_cm85_t));

	/* Memory barrier to ensure write completes before notification */
	__DMB();

	/* Notify CM33 */
	int ret = ipc_hw_cm85_notify_cm33(IPC_HW_CM85_CH_HEARTBEAT, heartbeat->sequence);

	return ret;
}

/**
 * Get CRC error count
 */
uint32_t ipc_hw_cm85_get_crc_error_count(void)
{
	return g_crc_error_count;
}
