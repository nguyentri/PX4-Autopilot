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
 * @file ipc_hardware.cpp
 *
 * RA8P1 Hardware IPC Interrupt Integration for CM33
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
 * - Channel 0: CM85→CM33 actuator commands (IRQ0 trigger)
 * - Channel 1: CM33→CM85 RC input (IRQ0 trigger)
 * - Channel 2: CM33→CM85 battery status (IRQ0 trigger)
 * - Channel 3: Bidirectional heartbeat/control (IRQ0 trigger)
 * - Semaphore 0: Shared memory protection for actuator_cmd
 * - Semaphore 1: Shared memory protection for rc_input
 * - Semaphore 2: Shared memory protection for battery_status
 *
 * @author PX4 Development Team
 */

#include <nuttx/config.h>
#include <nuttx/arch.h>
#include <nuttx/irq.h>

#include <stdint.h>
#include <string.h>
#include <errno.h>

#include <arch/board/board.h>

/* Include NuttX RA8 IPC driver */
#include "../../nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_ipc.h"

#include "ipc_hardware.h"
#include "protocol.h"

/*******************************************************************************
 * Definitions
 ******************************************************************************/

/* IPC Channel Assignment (matches both CM85 and CM33) */
#define IPC_CH_ACTUATOR_CMD     0   /* CM85 → CM33: Actuator commands */
#define IPC_CH_RC_INPUT         1   /* CM33 → CM85: RC input data */
#define IPC_CH_BATTERY          2   /* CM33 → CM85: Battery status */
#define IPC_CH_HEARTBEAT        3   /* Bidirectional: Heartbeat/control */

/* IPC Semaphore Assignment */
#define IPC_SEM_ACTUATOR        0   /* Protects IpcActuatorCmd shared memory */
#define IPC_SEM_RC_INPUT        1   /* Protects IpcRcInput shared memory */
#define IPC_SEM_BATTERY         2   /* Protects IpcBatteryStatus shared memory */

/* IPC Events (using IRQ0 for data-ready notifications) */
#define IPC_EVENT_DATA_READY    (1 << 0)  /* IPC_CH_SET_SET0 */

/*******************************************************************************
 * Private Data
 ******************************************************************************/

static bool g_ipc_hw_initialized = false;

/* Callback function pointers */
static ipc_hw_callback_t g_actuator_callback = nullptr;
static ipc_hw_callback_t g_rc_callback = nullptr;
static ipc_hw_callback_t g_battery_callback = nullptr;
static ipc_hw_callback_t g_heartbeat_callback = nullptr;

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
 */
static void ipc_ch0_actuator_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch0_irq_count++;

	/* Notify upper layer that actuator command is ready */
	if (g_actuator_callback) {
		g_actuator_callback(IPC_CH_ACTUATOR_CMD, data);
	}
}

/**
 * IPC Channel 1 Interrupt Callback (CM33 → CM85 RC Input)
 * Note: This is TX from CM33 perspective, but we still register callback
 * to detect acknowledgment from CM85 if needed
 */
static void ipc_ch1_rc_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch1_irq_count++;

	if (g_rc_callback) {
		g_rc_callback(IPC_CH_RC_INPUT, data);
	}
}

/**
 * IPC Channel 2 Interrupt Callback (CM33 → CM85 Battery Status)
 */
static void ipc_ch2_battery_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch2_irq_count++;

	if (g_battery_callback) {
		g_battery_callback(IPC_CH_BATTERY, data);
	}
}

/**
 * IPC Channel 3 Interrupt Callback (Bidirectional Heartbeat)
 */
static void ipc_ch3_heartbeat_callback(uint32_t channel, uint32_t data)
{
	g_ipc_ch3_irq_count++;

	if (g_heartbeat_callback) {
		g_heartbeat_callback(IPC_CH_HEARTBEAT, data);
	}
}

/*******************************************************************************
 * Public Functions
 ******************************************************************************/

/**
 * Initialize hardware IPC subsystem
 */
int ipc_hw_init(void)
{
	int ret;

	if (g_ipc_hw_initialized) {
		return 0;  /* Already initialized */
	}

	/* Initialize NuttX IPC driver */
	ret = ra_ipc_initialize();

	if (ret < 0) {
		syslog(LOG_ERR, "ipc_hw: ra_ipc_initialize failed: %d\n", ret);
		return ret;
	}

	/* Register channel callbacks */
	/* Channel 0: Receive actuator commands from CM85 */
	ret = ra_ipc_channel_register(IPC_CH_ACTUATOR_CMD, ipc_ch0_actuator_callback);

	if (ret < 0) {
		syslog(LOG_ERR, "ipc_hw: Failed to register CH0 callback: %d\n", ret);
		return ret;
	}

	/* Channel 1: Acknowledge RC input sent to CM85 (optional) */
	ret = ra_ipc_channel_register(IPC_CH_RC_INPUT, ipc_ch1_rc_callback);

	if (ret < 0) {
		syslog(LOG_ERR, "ipc_hw: Failed to register CH1 callback: %d\n", ret);
		return ret;
	}

	/* Channel 2: Acknowledge battery status sent to CM85 (optional) */
	ret = ra_ipc_channel_register(IPC_CH_BATTERY, ipc_ch2_battery_callback);

	if (ret < 0) {
		syslog(LOG_ERR, "ipc_hw: Failed to register CH2 callback: %d\n", ret);
		return ret;
	}

	/* Channel 3: Heartbeat from CM85 */
	ret = ra_ipc_channel_register(IPC_CH_HEARTBEAT, ipc_ch3_heartbeat_callback);

	if (ret < 0) {
		syslog(LOG_ERR, "ipc_hw: Failed to register CH3 callback: %d\n", ret);
		return ret;
	}

	g_ipc_hw_initialized = true;

	syslog(LOG_INFO, "ipc_hw: Hardware IPC initialized for CM33 (core %d)\n", CONFIG_RA_CPU_CORE);

	return 0;
}

/**
 * Deinitialize hardware IPC
 */
void ipc_hw_deinit(void)
{
	if (!g_ipc_hw_initialized) {
		return;
	}

	/* Unregister all callbacks */
	ra_ipc_channel_unregister(IPC_CH_ACTUATOR_CMD);
	ra_ipc_channel_unregister(IPC_CH_RC_INPUT);
	ra_ipc_channel_unregister(IPC_CH_BATTERY);
	ra_ipc_channel_unregister(IPC_CH_HEARTBEAT);

	g_actuator_callback = nullptr;
	g_rc_callback = nullptr;
	g_battery_callback = nullptr;
	g_heartbeat_callback = nullptr;

	g_ipc_hw_initialized = false;
}

/**
 * Register callback for upper layer notification
 */
int ipc_hw_register_callback(ipc_hw_channel_t channel, ipc_hw_callback_t callback)
{
	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (channel) {
	case IPC_HW_CH_ACTUATOR:
		g_actuator_callback = callback;
		break;

	case IPC_HW_CH_RC_INPUT:
		g_rc_callback = callback;
		break;

	case IPC_HW_CH_BATTERY:
		g_battery_callback = callback;
		break;

	case IPC_HW_CH_HEARTBEAT:
		g_heartbeat_callback = callback;
		break;

	default:
		return -EINVAL;
	}

	return 0;
}

/**
 * Send notification to CM85 (trigger interrupt)
 */
int ipc_hw_notify_cm85(ipc_hw_channel_t channel, uint32_t data)
{
	int ret;
	uint8_t hw_channel;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	/* Map logical channel to hardware channel */
	switch (channel) {
	case IPC_HW_CH_ACTUATOR:
		hw_channel = IPC_CH_ACTUATOR_CMD;
		break;

	case IPC_HW_CH_RC_INPUT:
		hw_channel = IPC_CH_RC_INPUT;
		break;

	case IPC_HW_CH_BATTERY:
		hw_channel = IPC_CH_BATTERY;
		break;

	case IPC_HW_CH_HEARTBEAT:
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
 * Acquire IPC semaphore for shared memory protection
 */
int ipc_hw_sem_take(ipc_hw_semaphore_t sem)
{
	uint8_t sem_num;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (sem) {
	case IPC_HW_SEM_ACTUATOR:
		sem_num = IPC_SEM_ACTUATOR;
		break;

	case IPC_HW_SEM_RC_INPUT:
		sem_num = IPC_SEM_RC_INPUT;
		break;

	case IPC_HW_SEM_BATTERY:
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
int ipc_hw_sem_give(ipc_hw_semaphore_t sem)
{
	uint8_t sem_num;

	if (!g_ipc_hw_initialized) {
		return -EAGAIN;
	}

	switch (sem) {
	case IPC_HW_SEM_ACTUATOR:
		sem_num = IPC_SEM_ACTUATOR;
		break;

	case IPC_HW_SEM_RC_INPUT:
		sem_num = IPC_SEM_RC_INPUT;
		break;

	case IPC_HW_SEM_BATTERY:
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
void ipc_hw_get_stats(struct ipc_hw_stats_s *stats)
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
void ipc_hw_reset_stats(void)
{
	g_ipc_ch0_irq_count = 0;
	g_ipc_ch1_irq_count = 0;
	g_ipc_ch2_irq_count = 0;
	g_ipc_ch3_irq_count = 0;
}
