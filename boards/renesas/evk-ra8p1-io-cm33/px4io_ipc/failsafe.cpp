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
 * @file failsafe.cpp
 *
 * CM33 Failsafe Coordination
 *
 * Coordinates multiple failsafe conditions:
 * - RC loss (100ms timeout)
 * - FMU loss (100ms CM85 heartbeat timeout → POEG)
 * - Actuator command timeout (10ms → disarm/kill)
 * - Battery low voltage
 *
 * @author PX4 Development Team
 */

#include "px4io.h"
#include "protocol.h"

#include <drivers/drv_hrt.h>
#include <px4_platform_common/log.h>

extern "C" {
#include <nuttx/arch.h>
}

/* Failsafe state */
typedef struct {
	bool rc_lost;
	bool fmu_lost;
	bool actuator_timeout;
	bool battery_low;
	bool any_failsafe_active;
	hrt_abstime last_actuator_cmd_time;
	uint32_t last_actuator_cmd_seq;
} failsafe_state_t;

static failsafe_state_t failsafe;

/* IPC pointers */
extern volatile IpcActuatorCmd *g_actuator_cmd;

/* External functions */
extern void heartbeat_force_poeg_kill();
extern bool rc_decoder_is_failsafe_active();

/**
 * @brief Initialize failsafe system
 */
void failsafe_init()
{
	memset(&failsafe, 0, sizeof(failsafe));
	failsafe.last_actuator_cmd_time = hrt_absolute_time();

	PX4_INFO("Failsafe system initialized");
}

/**
 * @brief Check actuator command timeout
 *
 * If no actuator command received within 10ms, trigger emergency disarm.
 */
static void failsafe_check_actuator_timeout()
{
	if (!g_actuator_cmd) {
		return;
	}

	/* Read actuator command sequence with memory barrier */
	ARM_DMB();
	uint32_t current_seq = g_actuator_cmd->sequence;
	ARM_DMB();

	/* Check if new command received */
	if (current_seq != failsafe.last_actuator_cmd_seq) {
		failsafe.last_actuator_cmd_seq = current_seq;
		failsafe.last_actuator_cmd_time = hrt_absolute_time();

		/* Clear timeout flag */
		if (failsafe.actuator_timeout) {
			failsafe.actuator_timeout = false;
			PX4_INFO("Actuator command restored");
		}

		return;
	}

	/* Check timeout */
	hrt_abstime time_since_cmd = hrt_elapsed_time(&failsafe.last_actuator_cmd_time);

	if (time_since_cmd > PX4IO_IPC_ACTUATOR_TIMEOUT_US) {
		if (!failsafe.actuator_timeout) {
			failsafe.actuator_timeout = true;
			PX4_ERR("Actuator command TIMEOUT (%llu ms) - disarming", time_since_cmd / 1000);

			/* Set failsafe flag */
			r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
			r_status_flags &= ~PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED;

			/* Motor kill will be handled by controls.cpp reading this flag */
		}
	}
}

/**
 * @brief Check battery voltage and set warning flags
 *
 * @param voltage_mv Battery voltage in millivolts
 * @param cell_count Number of cells
 * @return Warning flags bitmask
 */
static uint8_t failsafe_check_battery(uint16_t voltage_mv, uint8_t cell_count)
{
	uint8_t warnings = 0;

	if (cell_count == 0) {
		return 0;
	}

	/* Calculate per-cell voltage */
	uint16_t cell_voltage_mv = voltage_mv / cell_count;

	/* LiPo thresholds */
	const uint16_t CELL_LOW_MV = 3300;      /* 3.3V per cell = low warning */
	const uint16_t CELL_CRITICAL_MV = 3000; /* 3.0V per cell = critical */

	if (cell_voltage_mv < CELL_CRITICAL_MV) {
		warnings |= 0x02;  /* Critical low */
		failsafe.battery_low = true;
		PX4_ERR("Battery CRITICAL: %u mV/cell", cell_voltage_mv);

	} else if (cell_voltage_mv < CELL_LOW_MV) {
		warnings |= 0x01;  /* Low warning */
		failsafe.battery_low = true;
		PX4_WARN("Battery LOW: %u mV/cell", cell_voltage_mv);

	} else {
		failsafe.battery_low = false;
	}

	return warnings;
}

/**
 * @brief Update failsafe state
 *
 * Should be called periodically (e.g., every 1ms) from main loop.
 */
void failsafe_update()
{
	/* Check RC failsafe (handled by rc_decoder) */
	failsafe.rc_lost = rc_decoder_is_failsafe_active();

	/* Check FMU heartbeat (handled by heartbeat_monitor) */
	extern bool heartbeat_is_timeout_active();
	failsafe.fmu_lost = heartbeat_is_timeout_active();

	/* Check actuator command timeout */
	failsafe_check_actuator_timeout();

	/* Update aggregate failsafe flag */
	failsafe.any_failsafe_active = failsafe.rc_lost || failsafe.fmu_lost ||
	                                failsafe.actuator_timeout || failsafe.battery_low;

	if (failsafe.any_failsafe_active) {
		r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;

	} else {
		r_status_flags &= ~PX4IO_P_STATUS_FLAGS_FAILSAFE;
	}
}

/**
 * @brief Process battery status and check thresholds
 *
 * Called from ADC processing when new battery reading is available.
 *
 * @param voltage_mv Battery voltage in millivolts
 * @param current_ma Battery current in milliamps
 * @param cell_count Number of cells
 * @return Warning flags to be published in IPC battery status
 */
uint8_t failsafe_process_battery(uint16_t voltage_mv, int16_t current_ma, uint8_t cell_count)
{
	uint8_t warnings = failsafe_check_battery(voltage_mv, cell_count);

	/* Check for overcurrent (example threshold: 100A) */
	if (abs(current_ma) > 100000) {
		warnings |= 0x04;  /* Overcurrent flag */
		PX4_WARN("Battery OVERCURRENT: %d mA", current_ma);
	}

	return warnings;
}

/**
 * @brief Get current failsafe state flags
 *
 * @return Bitmask of active failsafe conditions
 */
uint8_t failsafe_get_flags()
{
	uint8_t flags = 0;

	if (failsafe.rc_lost) {
		flags |= 0x01;
	}

	if (failsafe.fmu_lost) {
		flags |= 0x02;
	}

	if (failsafe.actuator_timeout) {
		flags |= 0x04;
	}

	if (failsafe.battery_low) {
		flags |= 0x08;
	}

	return flags;
}

/**
 * @brief Check if any failsafe condition is active
 */
bool failsafe_is_active()
{
	return failsafe.any_failsafe_active;
}

/**
 * @brief Force failsafe for testing
 *
 * @param reason Test reason string
 */
void failsafe_force_test(const char *reason)
{
	PX4_WARN("FORCING FAILSAFE for test: %s", reason);
	heartbeat_force_poeg_kill();
}

/**
 * @brief Print failsafe status
 */
void failsafe_print_status()
{
	PX4_INFO("Failsafe Status:");
	PX4_INFO("  RC lost:         %s", failsafe.rc_lost ? "YES" : "NO");
	PX4_INFO("  FMU lost:        %s", failsafe.fmu_lost ? "YES" : "NO");
	PX4_INFO("  Actuator TO:     %s", failsafe.actuator_timeout ? "YES" : "NO");
	PX4_INFO("  Battery low:     %s", failsafe.battery_low ? "YES" : "NO");
	PX4_INFO("  Any active:      %s", failsafe.any_failsafe_active ? "YES" : "NO");
}
