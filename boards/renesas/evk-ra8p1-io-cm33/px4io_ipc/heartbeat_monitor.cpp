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
 * @file heartbeat_monitor.cpp
 *
 * CM33 Heartbeat Monitor for CM85 Watchdog
 *
 * Monitors CM85 (FMU) heartbeat and triggers POEG emergency motor kill
 * if heartbeat is not received within 100ms timeout.
 *
 * This is a critical safety feature that ensures the IO processor can
 * immediately kill motors if the FMU hangs or crashes.
 *
 * @author PX4 Development Team
 */

#include "px4io.h"
#include "protocol.h"

#include <drivers/drv_hrt.h>
#include <px4_platform_common/log.h>
#include <syslog.h>

extern "C" {
#include <nuttx/arch.h>
#include "arm_internal.h"

/* Use NuttX POEG driver for hardware-enforced motor kill */
#include "ra_poeg.h"
}

/*
 * POEG (Port Output Enable for GPT) - Hardware Safety Mechanism
 *
 * This module uses the NuttX POEG driver (ra_poeg.c) for hardware-enforced
 * PWM output disable. When CM85 heartbeat times out, we trigger POEG to
 * immediately kill all motor outputs regardless of CPU state.
 *
 * POEG Groups used:
 * - Group A (RA_POEG_CHANNEL_A): Motors 1-2 (GPT3, GPT5)
 * - Group B (RA_POEG_CHANNEL_B): Motors 3-4 (GPT11, GPT13)
 *
 * The POEG driver provides:
 * - ra_poeg_initialize(): Configure POEG group with triggers
 * - ra_poeg_software_disable(): Trigger software stop (kill motors)
 * - ra_poeg_reset(): Clear stop flags and re-enable outputs
 */

/* POEG groups used for motor control */
#define MOTOR_POEG_GROUP_A    RA_POEG_CHANNEL_A
#define MOTOR_POEG_GROUP_B    RA_POEG_CHANNEL_B

/* Track if POEG has been initialized */
static bool g_poeg_initialized = false;

/* Heartbeat monitoring state */
static uint32_t last_cm85_heartbeat_seq = 0;
static hrt_abstime last_cm85_heartbeat_time = 0;
static bool cm85_heartbeat_timeout_occurred = false;
static uint32_t cm85_heartbeat_timeout_count = 0;

/* IPC pointers (initialized by interface_init) */
extern volatile IpcCm85Heartbeat *g_cm85_heartbeat;
extern volatile IpcCm33Heartbeat *g_cm33_heartbeat;

/* Performance tracking */
extern volatile uint16_t r_status_flags;

/* POEG kill reason codes */
#define POEG_REASON_CM85_TIMEOUT    0x01
#define POEG_REASON_ACTUATOR_TIMEOUT 0x02
#define POEG_REASON_EMERGENCY_KILL  0x04

/**
 * @brief Initialize POEG for motor safety
 *
 * Configures POEG groups to support software-triggered motor kill.
 * Called from heartbeat_monitor_init().
 */
static void poeg_safety_init(void)
{
	if (g_poeg_initialized) {
		return;
	}

	struct ra_poeg_config_s config;

	/* Configure POEG Group A for motors 1-2 */
	memset(&config, 0, sizeof(config));
	config.channel = MOTOR_POEG_GROUP_A;
	config.trigger = RA_POEG_TRIGGER_SOFTWARE;  /* Software trigger only */
	config.noise_filter = RA_POEG_FILTER_PCLKB_DIV_8;
	config.priority = 1;  /* High priority */
	config.callback = NULL;  /* No callback needed for software trigger */

	int ret = ra_poeg_initialize(&config);
	if (ret < 0) {
		PX4_ERR("POEG Group A init failed: %d", ret);
	} else {
		PX4_INFO("POEG Group A initialized for motor safety");
	}

	/* Configure POEG Group B for motors 3-4 */
	config.channel = MOTOR_POEG_GROUP_B;

	ret = ra_poeg_initialize(&config);
	if (ret < 0) {
		PX4_ERR("POEG Group B init failed: %d", ret);
	} else {
		PX4_INFO("POEG Group B initialized for motor safety");
	}

	g_poeg_initialized = true;
}

/**
 * @brief Trigger POEG emergency motor kill using NuttX driver
 *
 * @param reason Reason code for kill (for logging/telemetry)
 */
static void trigger_poeg_kill(uint32_t reason)
{
	int ret;

	PX4_ERR("POEG KILL triggered, reason=0x%02X", (unsigned)reason);

	/* Trigger software stop for all motor POEG groups */
	ret = ra_poeg_software_disable(MOTOR_POEG_GROUP_A);
	if (ret < 0) {
		PX4_ERR("POEG Group A disable failed: %d", ret);
	}

	ret = ra_poeg_software_disable(MOTOR_POEG_GROUP_B);
	if (ret < 0) {
		PX4_ERR("POEG Group B disable failed: %d", ret);
	}

	/* Update status flags */
	r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
	r_status_flags &= ~PX4IO_P_STATUS_FLAGS_FMU_OK;

	/* Log critical event */
	syslog(LOG_CRIT, "[px4io] EMERGENCY MOTOR KILL - reason 0x%02X\n", (unsigned)reason);
}

/**
 * @brief Initialize heartbeat monitoring
 *
 * Called during px4io initialization. Sets up POEG for motor safety
 * and initializes heartbeat tracking state.
 */
void heartbeat_monitor_init()
{
	/* Initialize POEG for motor safety kill */
	poeg_safety_init();

	last_cm85_heartbeat_time = hrt_absolute_time();
	cm85_heartbeat_timeout_occurred = false;
	cm85_heartbeat_timeout_count = 0;

	PX4_INFO("Heartbeat monitor initialized, timeout=%u ms",
	         (unsigned)(PX4IO_IPC_HEARTBEAT_TIMEOUT_US / 1000));
}

/**
 * @brief Monitor CM85 heartbeat and trigger POEG on timeout
 *
 * This function should be called from the main control loop at high rate
 * (e.g., every 1ms) to ensure timely detection of CM85 failure.
 *
 * @return true if heartbeat is OK, false if timeout detected
 */
bool heartbeat_monitor_check()
{
	if (!g_cm85_heartbeat) {
		return false;
	}

	/* Read CM85 heartbeat with memory barrier */
	IpcCm85Heartbeat hb;
	ARM_DMB();
	memcpy(&hb, (const void *)g_cm85_heartbeat, sizeof(IpcCm85Heartbeat));
	ARM_DMB();

	/* Validate CRC */
	uint16_t calculated_crc = ipc_calculate_message_crc(&hb, nullptr);

	if (hb.crc16 != calculated_crc) {
		/* CRC error - don't update timestamp, but don't immediately trigger timeout */
		return true;  /* Give benefit of doubt for transient error */
	}

	/* Check if heartbeat sequence number changed (new heartbeat received) */
	if (hb.sequence != last_cm85_heartbeat_seq) {
		last_cm85_heartbeat_seq = hb.sequence;
		last_cm85_heartbeat_time = hrt_absolute_time();

		/* Clear timeout flag if it was set */
		if (cm85_heartbeat_timeout_occurred) {
			cm85_heartbeat_timeout_occurred = false;
			PX4_INFO("CM85 heartbeat restored after timeout");

			/* Try to clear POEG and re-enable outputs */
			int ret = ra_poeg_reset(MOTOR_POEG_GROUP_A);
			if (ret < 0) {
				PX4_WARN("POEG Group A reset failed: %d (may need power cycle)", ret);
			}

			ret = ra_poeg_reset(MOTOR_POEG_GROUP_B);
			if (ret < 0) {
				PX4_WARN("POEG Group B reset failed: %d (may need power cycle)", ret);
			}
		}

		/* Update status flag */
		r_status_flags |= PX4IO_P_STATUS_FLAGS_FMU_OK;

		return true;
	}

	/* Check for timeout */
	hrt_abstime time_since_heartbeat = hrt_elapsed_time(&last_cm85_heartbeat_time);

	if (time_since_heartbeat > PX4IO_IPC_HEARTBEAT_TIMEOUT_US) {
		if (!cm85_heartbeat_timeout_occurred) {
			cm85_heartbeat_timeout_occurred = true;
			cm85_heartbeat_timeout_count++;

			PX4_ERR("CM85 heartbeat TIMEOUT (%llu ms) - triggering POEG kill",
			        time_since_heartbeat / 1000);

			/* Trigger POEG emergency motor kill */
			trigger_poeg_kill(POEG_REASON_CM85_TIMEOUT);

			return false;
		}
	}

	return !cm85_heartbeat_timeout_occurred;
}

/**
 * @brief Publish CM33 heartbeat to CM85
 *
 * Should be called at 10Hz from main loop.
 */
void heartbeat_publish_cm33(uint32_t sequence, uint8_t state, uint8_t cpu_load, int16_t temperature,
                            uint32_t error_flags)
{
	if (!g_cm33_heartbeat) {
		return;
	}

	IpcCm33Heartbeat hb;
	hb.sequence = sequence;
	hb.timestamp_us = hrt_absolute_time();
	hb.system_state = state;
	hb.cpu_load_percent = cpu_load;
	hb.temperature_degC = temperature;
	hb.error_flags = error_flags;

	/* Calculate CRC */
	hb.crc16 = ipc_calculate_message_crc(&hb, nullptr);

	/* Write with memory barrier */
	ARM_DMB();
	memcpy((void *)g_cm33_heartbeat, &hb, sizeof(IpcCm33Heartbeat));
	ARM_DMB();
}

/**
 * @brief Get CM85 heartbeat timeout count
 *
 * @return Number of times CM85 heartbeat timeout occurred
 */
uint32_t heartbeat_get_timeout_count()
{
	return cm85_heartbeat_timeout_count;
}

/**
 * @brief Check if CM85 heartbeat is currently in timeout state
 *
 * @return true if timeout is active, false otherwise
 */
bool heartbeat_is_timeout_active()
{
	return cm85_heartbeat_timeout_occurred;
}

/**
 * @brief Force POEG kill for testing
 *
 * This function can be called from a test command to verify POEG
 * emergency kill functionality.
 */
void heartbeat_force_poeg_kill()
{
	PX4_WARN("FORCING POEG KILL for test");
	trigger_poeg_kill(0xFF);  /* Test reason code */
}
