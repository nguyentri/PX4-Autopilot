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
 * IPC transport layer for CM33<->CM85 communication via shared memory.
 * Uses ring buffers with CRC16 validation and doorbell IRQ notification.
 *
 * @author PX4 Development Team
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/defines.h>

#include <syslog.h>
#include <string.h>
#include <errno.h>

#include "px4io.h"
#include "protocol.h"
#include "ipc.h"
#include "pwm_out.h"
#include "board_config.h"

#include <drivers/drv_hrt.h>

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Heartbeat interval (us) - 10Hz */
#define HEARTBEAT_INTERVAL_US       100000

/* Status update interval (us) - 50Hz */
#define STATUS_INTERVAL_US          20000

/* ADC telemetry interval (us) - 10Hz */
#define ADC_INTERVAL_US             100000

/* FMU timeout before failsafe (us) - 500ms */
#define FMU_TIMEOUT_US              500000

/* RC input timeout (us) - 200ms */
#define RC_TIMEOUT_US               200000

/* Maximum message payload size */
#define MAX_PAYLOAD_SIZE            256

/****************************************************************************
 * Private Types
 ****************************************************************************/

/* Interface statistics */
typedef struct {
	uint32_t rx_messages;           /* Total received messages */
	uint32_t tx_messages;           /* Total transmitted messages */
	uint32_t rx_crc_errors;         /* CRC validation failures */
	uint32_t rx_sync_errors;        /* Sync/magic errors */
	uint32_t rx_overflow;           /* Buffer overflow events */
	uint32_t actuator_cmds;         /* Actuator commands received */
	uint32_t heartbeats_sent;       /* Heartbeats sent */
	uint32_t rc_frames_sent;        /* RC frames sent */
	uint64_t last_fmu_msg_time;     /* Time of last FMU message */
} interface_stats_t;

/****************************************************************************
 * Private Data
 ****************************************************************************/

static uint64_t g_last_heartbeat_sent = 0;
static uint64_t g_last_status_sent = 0;
static uint64_t g_last_adc_sent = 0;
static uint64_t g_last_rc_sent = 0;
static uint16_t g_tx_sequence = 0;
static uint16_t g_last_rx_sequence = 0;
static bool g_interface_initialized = false;

static interface_stats_t g_stats = {0};

/* Receive buffer for message processing */
static uint8_t g_rx_buffer[MAX_PAYLOAD_SIZE + sizeof(IpcHeader)];

/****************************************************************************
 * Private Functions
 ****************************************************************************/

/**
 * @brief Send a message with CRC validation
 */
static int send_message(IpcFrameType type, const void *payload, uint16_t payload_len)
{
	if (!g_interface_initialized) {
		return -ENODEV;
	}

	/* Build message */
	IpcMessage msg;
	memset(&msg, 0, sizeof(msg));

	msg.header.magic = PX4IO_IPC_MAGIC;
	msg.header.version = PX4IO_IPC_PROTOCOL_VERSION;
	msg.header.type = type;
	msg.header.sequence = g_tx_sequence++;
	msg.header.timestamp_us = hrt_absolute_time();
	msg.header.payload_len = payload_len;

	/* Copy payload */
	if (payload && payload_len > 0) {
		if (payload_len > sizeof(msg.payload)) {
			return -EINVAL;
		}
		memcpy(msg.payload, payload, payload_len);
	}

	/* Calculate CRC over header (excluding CRC field) and payload */
	msg.header.crc16 = 0;  /* Clear before CRC calc */
	uint16_t crc = ipc_crc16_ccitt((const uint8_t *)&msg.header,
				       sizeof(IpcHeader) - sizeof(uint16_t));
	if (payload_len > 0) {
		crc = ipc_crc16_update(crc, (const uint8_t *)payload, payload_len);
	}
	msg.header.crc16 = crc;

	/* Send via IPC */
	int ret = ipc_send_message(&msg);
	if (ret == 0) {
		g_stats.tx_messages++;
	}

	return ret;
}

/**
 * @brief Process actuator command from FMU
 */
static void handle_actuator_cmd(const IpcActuatorCmd *cmd)
{
	g_stats.actuator_cmds++;

	/* Update motor outputs */
	for (int i = 0; i < PX4IO_SERVO_COUNT && i < 8; i++) {
		r_page_servos[i] = cmd->motor[i];
		r_page_direct_pwm[i] = cmd->motor[i];
	}

	/* Update arming state */
	if (cmd->armed) {
		atomic_modify_or(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_RAW_PWM);
	} else {
		atomic_modify_clear(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
	}

	/* Handle output mode changes */
	if (cmd->output_mode != (uint8_t)pwm_out_get_mode()) {
		/* Mode change requested - only when disarmed */
		if (!pwm_out_is_armed()) {
			pwm_out_set_mode((output_mode_t)cmd->output_mode);
		}
	}

	/* Update timestamp */
	system_state.fmu_data_received_time = hrt_absolute_time();
	g_stats.last_fmu_msg_time = system_state.fmu_data_received_time;
}

/**
 * @brief Process config command from FMU
 */
static void handle_config_cmd(const IpcConfigCmd *cmd)
{
	switch (cmd->param_id) {
	case IPC_CONFIG_PWM_RATE:
		if (cmd->value >= PWM_FREQ_MIN && cmd->value <= PWM_FREQ_MAX) {
			pwm_out_set_frequency(cmd->value);
		}
		break;

	case IPC_CONFIG_PWM_MIN:
		for (int i = 0; i < PX4IO_SERVO_COUNT; i++) {
			r_page_servo_control_min[i] = cmd->value;
		}
		break;

	case IPC_CONFIG_PWM_MAX:
		for (int i = 0; i < PX4IO_SERVO_COUNT; i++) {
			r_page_servo_control_max[i] = cmd->value;
		}
		break;

	case IPC_CONFIG_FAILSAFE:
		for (int i = 0; i < PX4IO_SERVO_COUNT; i++) {
			r_page_servo_failsafe[i] = cmd->value;
			pwm_out_set_failsafe(i, cmd->value);
		}
		break;

	case IPC_CONFIG_DISARMED:
		for (int i = 0; i < PX4IO_SERVO_COUNT; i++) {
			r_page_servo_disarmed[i] = cmd->value;
			pwm_out_set_disarmed(i, cmd->value);
		}
		break;

	default:
		syslog(LOG_WARNING, "Unknown config param: %u\n", cmd->param_id);
		break;
	}
}

/**
 * @brief Process heartbeat from FMU (CM85)
 */
static void handle_cm85_heartbeat(const IpcCm85Heartbeat *hb)
{
	system_state.fmu_data_received_time = hrt_absolute_time();
	g_stats.last_fmu_msg_time = system_state.fmu_data_received_time;

	/* Update status based on FMU state */
	if (hb->fmu_mode & IPC_FMU_MODE_ARMED) {
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_OK);
	}

	/* Check sequence for lost messages */
	if (g_last_rx_sequence != 0) {
		uint16_t expected = g_last_rx_sequence + 1;
		if (hb->sequence != expected && hb->sequence != 0) {
			/* Sequence gap detected */
			uint16_t lost = (hb->sequence > expected) ?
					(hb->sequence - expected) :
					(0xFFFF - expected + hb->sequence + 1);
			if (lost > 0 && lost < 100) {
				/* Reasonable gap, likely lost messages */
				syslog(LOG_DEBUG, "IPC: %u messages lost\n", lost);
			}
		}
	}
	g_last_rx_sequence = hb->sequence;
}

/**
 * @brief Process emergency kill command
 */
static void handle_emergency_kill(const IpcEmergencyKill *kill)
{
	if (kill->kill_switch) {
		syslog(LOG_CRIT, "Emergency kill received!\n");
		pwm_out_emergency_stop();
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
		atomic_modify_or(&r_status_alarms, PX4IO_P_STATUS_ALARMS_FMU_LOST);
	} else {
		syslog(LOG_INFO, "Emergency kill cleared\n");
		pwm_out_clear_emergency();
		atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
	}
}

/**
 * @brief Receive and process incoming messages
 */
static void process_rx_messages(void)
{
	IpcMessage msg;
	int ret;

	/* Process all available messages */
	while ((ret = ipc_receive_message(&msg)) == 0) {
		g_stats.rx_messages++;

		/* Validate message */
		if (msg.header.magic != PX4IO_IPC_MAGIC) {
			g_stats.rx_sync_errors++;
			continue;
		}

		/* Dispatch based on message type */
		switch (msg.header.type) {
		case IpcFrameType::ActuatorCmd:
			if (msg.header.payload_len >= sizeof(IpcActuatorCmd)) {
				handle_actuator_cmd((const IpcActuatorCmd *)msg.payload);
			}
			break;

		case IpcFrameType::ConfigCmd:
			if (msg.header.payload_len >= sizeof(IpcConfigCmd)) {
				handle_config_cmd((const IpcConfigCmd *)msg.payload);
			}
			break;

		case IpcFrameType::Cm85Heartbeat:
			if (msg.header.payload_len >= sizeof(IpcCm85Heartbeat)) {
				handle_cm85_heartbeat((const IpcCm85Heartbeat *)msg.payload);
			}
			break;

		case IpcFrameType::EmergencyKill:
			if (msg.header.payload_len >= sizeof(IpcEmergencyKill)) {
				handle_emergency_kill((const IpcEmergencyKill *)msg.payload);
			}
			break;

		default:
			/* Unknown message type */
			break;
		}
	}

	/* Check for CRC errors */
	if (ret == -EBADMSG) {
		g_stats.rx_crc_errors++;
	}
}

/**
 * @brief Send CM33 heartbeat to FMU
 */
static void send_heartbeat(void)
{
	IpcCm33Heartbeat hb;
	memset(&hb, 0, sizeof(hb));

	hb.status_flags = r_status_flags;
	hb.arming_flags = r_setup_arming;
	hb.error_count = g_stats.rx_crc_errors + g_stats.rx_sync_errors;
	hb.uptime_ms = (uint32_t)(hrt_absolute_time() / 1000);

	send_message(IpcFrameType::Cm33Heartbeat, &hb, sizeof(hb));
	g_stats.heartbeats_sent++;
	g_last_heartbeat_sent = hrt_absolute_time();
}

/**
 * @brief Send IO status to FMU
 */
static void send_status(void)
{
	IpcIoStatus status;
	memset(&status, 0, sizeof(status));

	status.status_flags = r_status_flags;
	status.arming_flags = r_setup_arming;
	status.alarm_flags = r_status_alarms;

	/* Copy current servo outputs */
	for (int i = 0; i < PX4IO_SERVO_COUNT && i < 8; i++) {
		status.servo_output[i] = r_page_servos[i];
	}

	status.output_mode = (uint8_t)pwm_out_get_mode();

	send_message(IpcFrameType::IoStatus, &status, sizeof(status));
	g_last_status_sent = hrt_absolute_time();
}

/**
 * @brief Send RC input to FMU
 */
static void send_rc_input(void)
{
	if (system_state.rc_channels_timestamp_received <= g_last_rc_sent) {
		return;  /* No new RC data */
	}

	IpcRcInput rc;
	memset(&rc, 0, sizeof(rc));

	rc.channel_count = r_raw_rc_count;
	rc.rssi = r_page_raw_rc_input[PX4IO_P_RAW_RC_NRSSI];
	rc.rc_lost = (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_OK) ? 0 : 1;
	rc.rc_failsafe = (r_raw_rc_flags & PX4IO_P_RAW_RC_FLAGS_FAILSAFE) ? 1 : 0;
	rc.frame_drop = (r_raw_rc_flags & PX4IO_P_RAW_RC_FLAGS_FRAME_DROP) ? 1 : 0;

	/* Determine input source */
	if (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_SBUS) {
		rc.input_source = 1;  /* SBUS */
	} else if (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_DSM) {
		rc.input_source = 2;  /* DSM */
	} else if (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_PPM) {
		rc.input_source = 3;  /* PPM */
	} else if (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_ST24) {
		rc.input_source = 4;  /* ST24 */
	} else if (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_SUMD) {
		rc.input_source = 5;  /* SUMD */
	}

	/* Copy channel values */
	for (int i = 0; i < rc.channel_count && i < 18; i++) {
		rc.channels[i] = r_raw_rc_values[i];
	}

	send_message(IpcFrameType::RcInput, &rc, sizeof(rc));
	g_stats.rc_frames_sent++;
	g_last_rc_sent = system_state.rc_channels_timestamp_received;
}

/**
 * @brief Send ADC telemetry to FMU
 */
static void send_adc_telemetry(void)
{
	IpcAdcTelemetry adc;
	memset(&adc, 0, sizeof(adc));

	/* Get ADC values (from adc.cpp extern functions) */
	extern uint16_t adc_get_vbat_mv(void);
	extern int16_t adc_get_current_ma(void);
	extern uint16_t adc_get_vservo_mv(void);
	extern uint16_t adc_get_temperature_cdeg(void);

	adc.vbat_mv = adc_get_vbat_mv();
	adc.current_ma = adc_get_current_ma();
	adc.vservo_mv = adc_get_vservo_mv();
	adc.temperature_cdeg = adc_get_temperature_cdeg();

	/* Flags from ADC state */
	adc.valid_mask = 0x0F;  /* All channels valid */

	send_message(IpcFrameType::AdcTelemetry, &adc, sizeof(adc));
	g_last_adc_sent = hrt_absolute_time();
}

/**
 * @brief Check for FMU communication timeout
 */
static void check_fmu_timeout(void)
{
	uint64_t now = hrt_absolute_time();

	if (g_stats.last_fmu_msg_time > 0 &&
	    (now - g_stats.last_fmu_msg_time) > FMU_TIMEOUT_US) {
		/* FMU communication lost */
		if (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_OK) {
			syslog(LOG_WARNING, "FMU communication timeout\n");
			atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_OK);
			atomic_modify_or(&r_status_alarms, PX4IO_P_STATUS_ALARMS_FMU_LOST);

			/* Trigger failsafe if armed */
			if (r_setup_arming & PX4IO_P_SETUP_ARMING_FMU_ARMED) {
				pwm_out_failsafe();
			}
		}
	} else if (g_stats.last_fmu_msg_time > 0) {
		/* FMU OK */
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_OK);
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_INITIALIZED);
		atomic_modify_clear(&r_status_alarms, PX4IO_P_STATUS_ALARMS_FMU_LOST);
	}
}

/****************************************************************************
 * Public Functions
 ****************************************************************************/

/**
 * @brief Initialize IPC transport interface
 */
void interface_init(void)
{
	int ret = ipc_init();
	if (ret < 0) {
		syslog(LOG_ERR, "IPC init failed: %d\n", ret);
		return;
	}

	memset(&g_stats, 0, sizeof(g_stats));

	g_interface_initialized = true;
	syslog(LOG_INFO, "IPC transport initialized\n");
}

/**
 * @brief Main interface tick function - called from main loop
 */
void interface_tick(void)
{
	if (!g_interface_initialized) {
		return;
	}

	uint64_t now = hrt_absolute_time();

	/* Process incoming messages */
	process_rx_messages();

	/* Check FMU timeout */
	check_fmu_timeout();

	/* Send heartbeat at 10Hz */
	if ((now - g_last_heartbeat_sent) >= HEARTBEAT_INTERVAL_US) {
		send_heartbeat();
	}

	/* Send status at 50Hz */
	if ((now - g_last_status_sent) >= STATUS_INTERVAL_US) {
		send_status();
	}

	/* Send RC input when available (handled by timestamp check) */
	send_rc_input();

	/* Send ADC telemetry at 10Hz */
	if ((now - g_last_adc_sent) >= ADC_INTERVAL_US) {
		send_adc_telemetry();
	}

	/* Trigger DShot frame if in DShot mode */
	if (pwm_out_get_mode() >= OUTPUT_MODE_DSHOT150) {
		pwm_out_trigger_dshot();
	}
}

/**
 * @brief Get interface statistics
 */
void interface_get_stats(uint32_t *rx_msgs, uint32_t *tx_msgs,
			 uint32_t *crc_errors, uint32_t *sync_errors)
{
	if (rx_msgs) *rx_msgs = g_stats.rx_messages;
	if (tx_msgs) *tx_msgs = g_stats.tx_messages;
	if (crc_errors) *crc_errors = g_stats.rx_crc_errors;
	if (sync_errors) *sync_errors = g_stats.rx_sync_errors;
}

/**
 * @brief Check if FMU communication is healthy
 */
bool interface_fmu_ok(void)
{
	return (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_OK) != 0;
}
