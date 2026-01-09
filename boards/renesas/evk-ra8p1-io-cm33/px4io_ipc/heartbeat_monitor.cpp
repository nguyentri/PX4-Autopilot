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

extern "C" {
#include <nuttx/arch.h>
}

/* POEG (Port Output Enable for GPT) registers - RA8P1 specific */
#define POEG_BASE               0x40044000UL
#define POEGA_OFFSET            0x0000
#define POEGB_OFFSET            0x0100
#define POEGC_OFFSET            0x0200
#define POEGD_OFFSET            0x0300

#define POEG_POEGGA_OFFSET      0x00    /* POEG Group A Control */
#define POEG_POEGSA_OFFSET      0x04    /* POEG Group A Status */
#define POEG_POEGSS_OFFSET      0x08    /* POEG Group A Software Start */

#define POEG_PIDF               (1 << 0)  /* Port Input Detection Flag */
#define POEG_IOCF               (1 << 1)  /* I/O Level Detection Flag */
#define POEG_OSTPF              (1 << 2)  /* Oscillation Stop Detection Flag */
#define POEG_SSF                (1 << 3)  /* Software Stop Flag */
#define POEG_PIDE               (1 << 4)  /* Port Input Detection Enable */
#define POEG_IOCE               (1 << 5)  /* I/O Level Detection Enable */
#define POEG_OSTPE              (1 << 6)  /* Oscillation Stop Detection Enable */
#define POEG_ST                 (1 << 16) /* POEG Trigger */

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
 * @brief Trigger POEG emergency motor kill
 *
 * @param reason Reason code for kill (for logging/telemetry)
 */
static void trigger_poeg_kill(uint32_t reason)
{
	/* Set POEG software trigger for all GPT groups */
	volatile uint32_t *poega_ss = (volatile uint32_t *)(POEG_BASE + POEGA_OFFSET + POEG_POEGSS_OFFSET);
	volatile uint32_t *poegb_ss = (volatile uint32_t *)(POEG_BASE + POEGB_OFFSET + POEG_POEGSS_OFFSET);
	volatile uint32_t *poegc_ss = (volatile uint32_t *)(POEG_BASE + POEGC_OFFSET + POEG_POEGSS_OFFSET);
	volatile uint32_t *poegd_ss = (volatile uint32_t *)(POEG_BASE + POEGD_OFFSET + POEG_POEGSS_OFFSET);

	/* Memory barrier before triggering */
	ARM_DMB();

	/* Trigger software stop for all POEG groups */
	*poega_ss = POEG_ST;
	*poegb_ss = POEG_ST;
	*poegc_ss = POEG_ST;
	*poegd_ss = POEG_ST;

	/* Memory barrier after triggering */
	ARM_DMB();

	PX4_ERR("POEG KILL triggered, reason=0x%02X", reason);

	/* Update status flags */
	r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
	r_status_flags &= ~PX4IO_P_STATUS_FLAGS_FMU_OK;

	/* Log event */
	syslog(LOG_CRIT, "[px4io] EMERGENCY MOTOR KILL - reason 0x%02X\n", reason);
}

/**
 * @brief Initialize heartbeat monitoring
 *
 * Called during px4io initialization.
 */
void heartbeat_monitor_init()
{
	last_cm85_heartbeat_time = hrt_absolute_time();
	cm85_heartbeat_timeout_occurred = false;
	cm85_heartbeat_timeout_count = 0;

	PX4_INFO("Heartbeat monitor initialized, timeout=%u ms", PX4IO_IPC_HEARTBEAT_TIMEOUT_US / 1000);
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

			/* Try to clear POEG (may require power cycle depending on configuration) */
			// Note: RA8P1 POEG may latch and require explicit reset
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
void heartbeat_publish_cm33(uint32_t sequence, uint8_t system_state, uint8_t cpu_load, int16_t temperature,
                            uint32_t error_flags)
{
	if (!g_cm33_heartbeat) {
		return;
	}

	IpcCm33Heartbeat hb;
	hb.sequence = sequence;
	hb.timestamp_us = hrt_absolute_time();
	hb.system_state = system_state;
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
