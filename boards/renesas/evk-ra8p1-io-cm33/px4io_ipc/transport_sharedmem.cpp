/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
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
 * @file transport_sharedmem.cpp
 *
 * Fixed-layout shared-memory transport for CM33<->CM85 IPC.
 *
 * Maps the shared SRAM window at 0x201A0000 to typed structs defined in the
 * single-source protocol header (ipc_protocol.h). No ring buffers are used;
 * each message resides at a fixed offset with CRC16 and sequence numbers.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/defines.h>
#include <px4_platform_common/atomic.h>

#include <syslog.h>
#include <string.h>

#include "px4io.h"
#include "protocol.h"
#include "pwm_out.h"
#include "board_config.h"

#include <drivers/drv_hrt.h>

/* IPC shared-memory pointers (exported) */
volatile IpcActuatorCmd   *g_actuator_cmd   = nullptr;
volatile IpcRcInput       *g_rc_input       = nullptr;
volatile IpcBatteryStatus *g_battery_status = nullptr;
volatile IpcCm85Heartbeat *g_cm85_heartbeat = nullptr;
volatile IpcCm33Heartbeat *g_cm33_heartbeat = nullptr;
volatile IpcPerfCounters  *g_perf_counters  = nullptr;

/* Internal state */
static uint32_t last_actuator_seq = 0;
static hrt_abstime last_actuator_time = 0;
static uint32_t actuator_crc_errors = 0;
static bool interface_ready = false;
static uint32_t heartbeat_seq = 0;
static uint64_t last_heartbeat_us = 0;

/* Performance tracking */
static uint32_t rx_messages = 0;
static uint32_t tx_messages = 0;
static uint32_t crc_errors = 0;
static uint32_t sync_errors = 0;

/* Map shared SRAM region to typed pointers */
static void map_shared_region(void)
{
	g_actuator_cmd   = (volatile IpcActuatorCmd *)IPC_ACTUATOR_CMD_ADDR;
	g_rc_input       = (volatile IpcRcInput *)IPC_RC_INPUT_ADDR;
	g_battery_status = (volatile IpcBatteryStatus *)IPC_BATTERY_STATUS_ADDR;
	g_cm85_heartbeat = (volatile IpcCm85Heartbeat *)IPC_HEARTBEAT_CM85_ADDR;
	g_cm33_heartbeat = (volatile IpcCm33Heartbeat *)IPC_HEARTBEAT_CM33_ADDR;
	g_perf_counters  = (volatile IpcPerfCounters *)IPC_PERF_COUNTERS_ADDR;
}

/* Safe copy with barriers */
template<typename T>
static inline void ipc_read(T *dst, const volatile T *src)
{
	ARM_DMB();
	memcpy(dst, (const void *)src, sizeof(T));
	ARM_DMB();
}

template<typename T>
static inline void ipc_write(volatile T *dst, const T *src)
{
	ARM_DMB();
	memcpy((void *)dst, src, sizeof(T));
	ARM_DMB();
}

/* Handle actuator command from CM85 */
static void handle_actuator_cmd()
{
	if (!g_actuator_cmd) {
		return;
	}

	IpcActuatorCmd cmd{};
	ipc_read(&cmd, g_actuator_cmd);

	uint16_t crc = ipc_calculate_message_crc(&cmd, nullptr);

	if (cmd.crc16 != crc) {
		actuator_crc_errors++;

		if (g_perf_counters) {
			px4::atomic_fetch_add(&g_perf_counters->ipc_crc_errors, 1u);
		}

		return;
	}

	/* New command? */
	if (cmd.sequence == last_actuator_seq) {
		return;
	}

	last_actuator_seq = cmd.sequence;
	last_actuator_time = hrt_absolute_time();
	rx_messages++;

	/* Update motor outputs */
	for (int i = 0; i < PX4IO_SERVO_COUNT && i < IPC_MAX_MOTORS; i++) {
		r_page_servos[i] = cmd.motor[i];
		r_page_direct_pwm[i] = cmd.motor[i];
	}

	/* Update arming flags */
	if (cmd.armed) {
		atomic_modify_or(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED | PX4IO_P_STATUS_FLAGS_FMU_OK);
	} else {
		atomic_modify_clear(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
		atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED);
	}

	/* Mode changes only allowed when disarmed */
	if (!pwm_out_is_armed()) {
		pwm_out_set_mode((output_mode_t)cmd.protocol);
	}
}

/* Publish CM33 heartbeat (10Hz) */
static void publish_cm33_heartbeat()
{
	if (!g_cm33_heartbeat) {
		return;
	}

	hrt_abstime now = hrt_absolute_time();

	if ((now - last_heartbeat_us) < 100000) {
		return;
	}

	IpcCm33Heartbeat hb{};
	hb.sequence = ++heartbeat_seq;
	hb.timestamp_us = now;
	hb.system_state = (r_setup_arming & PX4IO_P_SETUP_ARMING_FMU_ARMED) ? IPC_STATE_ACTIVE : IPC_STATE_STANDBY;
	hb.cpu_load_percent = 0; /* TODO: wire real CPU load */
	hb.temperature_degC = 0;
	hb.error_flags = 0;
	hb.crc16 = IPC_CALC_CRC(&hb, ipc_heartbeat_cm33_t);

	ipc_write(g_cm33_heartbeat, &hb);
	tx_messages++;
	last_heartbeat_us = now;
}

void interface_init(void)
{
	map_shared_region();

	/* Clear regions to known state */
	if (g_actuator_cmd) {
		memset((void *)g_actuator_cmd, 0, sizeof(IpcActuatorCmd));
	}

	if (g_rc_input) {
		memset((void *)g_rc_input, 0, sizeof(IpcRcInput));
	}

	if (g_battery_status) {
		memset((void *)g_battery_status, 0, sizeof(IpcBatteryStatus));
	}

	if (g_cm85_heartbeat) {
		memset((void *)g_cm85_heartbeat, 0, sizeof(IpcCm85Heartbeat));
	}

	if (g_cm33_heartbeat) {
		memset((void *)g_cm33_heartbeat, 0, sizeof(IpcCm33Heartbeat));
	}

	if (g_perf_counters) {
		memset((void *)g_perf_counters, 0, sizeof(IpcPerfCounters));
	}

	last_actuator_seq = 0;
	last_actuator_time = hrt_absolute_time();
	interface_ready = true;

	syslog(LOG_INFO, "IPC shared memory mapped at 0x%08lx", (unsigned long)IPC_SRAM_BASE);
}

void interface_tick(void)
{
	if (!interface_ready) {
		return;
	}

	handle_actuator_cmd();
	publish_cm33_heartbeat();
}

void interface_get_stats(uint32_t *rx_msgs, uint32_t *tx_msgs,
			 uint32_t *crc_errs, uint32_t *sync_errs)
{
	if (rx_msgs) *rx_msgs = rx_messages;
	if (tx_msgs) *tx_msgs = tx_messages;
	if (crc_errs) *crc_errs = crc_errors + actuator_crc_errors;
	if (sync_errs) *sync_errs = sync_errors;
}

bool interface_fmu_ok(void)
{
	hrt_abstime now = hrt_absolute_time();
	return (now - last_actuator_time) < IPC_ACTUATOR_TIMEOUT_US;
}
