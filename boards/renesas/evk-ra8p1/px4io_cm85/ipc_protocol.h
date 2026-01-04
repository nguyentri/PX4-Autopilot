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
 * @file ipc_protocol.h
 *
 * RA8P1 CM85 ↔ CM33 Shared-Memory IPC Protocol (Single-Source Header)
 *
 * This is the authoritative protocol definition shared between CM85 (FMU)
 * and CM33 (IO). Both cores MUST use identical copies of this header.
 *
 * Memory Layout @ 0x201A0000 (64KB non-cacheable SRAM):
 * - 0x201A0000: actuator_cmd  (128 B, CM85→CM33)
 * - 0x201A0080: rc_input      (128 B, CM33→CM85)
 * - 0x201A0100: battery_status(128 B, CM33→CM85)
 * - 0x201A0180: heartbeat_cm85(32 B,  CM85→CM33)
 * - 0x201A01A0: heartbeat_cm33(32 B,  CM33→CM85)
 * - 0x201A01C0: reserved      (3.9KB)
 * - 0x201A1000: perf counters (60KB)
 *
 * Protocol guarantees:
 * - All structs 128-byte aligned for cache efficiency
 * - CRC16-CCITT on all messages
 * - Sequence numbers for gap detection
 * - Memory barriers (__DMB) enforced by transport layer
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

__BEGIN_DECLS

/*******************************************************************************
 * Memory Map Definitions
 ******************************************************************************/

#define IPC_SRAM_BASE           0x201A0000UL
#define IPC_SRAM_SIZE           0x00010000UL  /* 64 KB */

/* Message region offsets */
#define IPC_ACTUATOR_CMD_OFFSET     0x0000
#define IPC_RC_INPUT_OFFSET         0x0080
#define IPC_BATTERY_STATUS_OFFSET   0x0100
#define IPC_HEARTBEAT_CM85_OFFSET   0x0180
#define IPC_HEARTBEAT_CM33_OFFSET   0x01A0
#define IPC_PERF_COUNTERS_OFFSET    0x1000

/* Computed addresses */
#define IPC_ACTUATOR_CMD_ADDR       (IPC_SRAM_BASE + IPC_ACTUATOR_CMD_OFFSET)
#define IPC_RC_INPUT_ADDR           (IPC_SRAM_BASE + IPC_RC_INPUT_OFFSET)
#define IPC_BATTERY_STATUS_ADDR     (IPC_SRAM_BASE + IPC_BATTERY_STATUS_OFFSET)
#define IPC_HEARTBEAT_CM85_ADDR     (IPC_SRAM_BASE + IPC_HEARTBEAT_CM85_OFFSET)
#define IPC_HEARTBEAT_CM33_ADDR     (IPC_SRAM_BASE + IPC_HEARTBEAT_CM33_OFFSET)
#define IPC_PERF_COUNTERS_ADDR      (IPC_SRAM_BASE + IPC_PERF_COUNTERS_OFFSET)

/*******************************************************************************
 * Protocol Constants
 ******************************************************************************/

#define IPC_PROTOCOL_VERSION    2
#define IPC_MAGIC_NUMBER        0x50583449UL  /* "PX4I" */
#define IPC_INIT_MAGIC          0xDEADBEEFUL

/* Timing constants (microseconds) */
#define IPC_ACTUATOR_TIMEOUT_US     10000   /* 10ms - CM33 kills motors if no update */
#define IPC_RC_TIMEOUT_US          100000   /* 100ms - CM85 declares RC loss */
#define IPC_HEARTBEAT_CM33_TIMEOUT 100000   /* 100ms - CM85 declares IO failure */
#define IPC_HEARTBEAT_CM85_TIMEOUT 100000   /* 100ms - CM33 triggers POEG */
#define IPC_BATTERY_TIMEOUT_US    1000000   /* 1s - non-critical */

/* Array sizes */
#define IPC_MAX_MOTORS          8
#define IPC_MAX_SERVOS          8
#define IPC_MAX_RC_CHANNELS     18
#define IPC_MAX_BATTERY_CELLS   12

/*******************************************************************************
 * CRC16-CCITT (polynomial 0x1021, init 0xFFFF)
 ******************************************************************************/

/**
 * @brief Calculate CRC16-CCITT over buffer
 * @param data Buffer to checksum
 * @param len Buffer length in bytes
 * @return CRC16 value
 */
static inline uint16_t ipc_crc16_ccitt(const uint8_t *data, size_t len)
{
	uint16_t crc = 0xFFFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= (uint16_t)data[i] << 8;

		for (int b = 0; b < 8; b++) {
			crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
		}
	}

	return crc;
}

/*******************************************************************************
 * System State Enumerations
 ******************************************************************************/

/* System state (aligned with MAVLink MAV_STATE) */
typedef enum {
	IPC_STATE_UNINIT       = 0,
	IPC_STATE_BOOT         = 1,
	IPC_STATE_STANDBY      = 3,
	IPC_STATE_ACTIVE       = 4,
	IPC_STATE_CRITICAL     = 5,
	IPC_STATE_EMERGENCY    = 6,
	IPC_STATE_POWEROFF     = 7,
	IPC_STATE_FLIGHT_TERMINATION = 8
} ipc_system_state_t;

/* Output protocol modes */
typedef enum {
	IPC_OUTPUT_PWM         = 0,
	IPC_OUTPUT_DSHOT150    = 1,
	IPC_OUTPUT_DSHOT300    = 2,
	IPC_OUTPUT_DSHOT600    = 3,
	IPC_OUTPUT_DSHOT1200   = 4
} ipc_output_protocol_t;

/* RC protocol types */
typedef enum {
	IPC_RC_PROTOCOL_SBUS   = 0,
	IPC_RC_PROTOCOL_CRSF   = 1,
	IPC_RC_PROTOCOL_DSM    = 2,
	IPC_RC_PROTOCOL_PPM    = 3,
	IPC_RC_PROTOCOL_CPPM   = 4
} ipc_rc_protocol_t;

/*******************************************************************************
 * Message Structures (MUST be 128-byte aligned, packed)
 ******************************************************************************/

#pragma pack(push, 1)

/**
 * @brief Actuator Command (CM85 → CM33)
 *
 * Motor and servo setpoints. Rate: 400-1000Hz.
 * Timeout: 10ms → CM33 emergency kill.
 *
 * Total size: 128 bytes
 */
typedef struct {
	uint32_t sequence;                      /* Monotonic counter, wraps at UINT32_MAX */
	uint64_t timestamp_us;                  /* CM85 HRT timestamp */

	uint16_t motor[IPC_MAX_MOTORS];         /* Motor values: DShot (48-2047), PWM (1000-2000) */
	uint16_t servo[IPC_MAX_SERVOS];         /* Servo values: PWM (1000-2000 µs) */

	uint8_t  armed;                         /* 1=armed, 0=disarmed */
	uint8_t  emergency_kill;                /* 1=immediate POEG kill */
	uint8_t  protocol;                      /* ipc_output_protocol_t */
	uint8_t  failsafe_active;               /* 1=failsafe mode */

	uint8_t  _reserved[84];                 /* Pad to 124 bytes */
	uint16_t crc16;                         /* CRC16-CCITT of bytes 0-125 */
	uint16_t _pad_align;                    /* Align to 128 bytes */
} __attribute__((aligned(128))) ipc_actuator_cmd_t;

/**
 * @brief RC Input (CM33 → CM85)
 *
 * RC channel data and signal quality. Rate: 50-500Hz.
 * Timeout: 100ms → CM85 declares RC loss.
 *
 * Total size: 128 bytes
 */
typedef struct {
	uint32_t sequence;
	uint64_t timestamp_us;                  /* CM33 timestamp */

	uint16_t channel[IPC_MAX_RC_CHANNELS];  /* Channel values (1000-2000 µs) */
	uint8_t  channel_count;                 /* Number of active channels */
	uint8_t  rssi;                          /* Signal strength (0-255) */
	uint8_t  link_quality;                  /* Link quality 0-100%, 255=unknown */
	uint8_t  failsafe;                      /* 1=RC lost/failsafe active */
	uint8_t  protocol;                      /* ipc_rc_protocol_t */
	uint8_t  frame_rate;                    /* Frames per second (50-500) */

	uint16_t frame_count;                   /* Total frames received */
	uint16_t lost_frame_count;              /* Lost frames */

	uint8_t  _reserved[70];                 /* Pad to 124 bytes */
	uint16_t crc16;
	uint16_t _pad_align;
} __attribute__((aligned(128))) ipc_rc_input_t;

/**
 * @brief Battery Status (CM33 → CM85)
 *
 * Battery voltage, current, capacity. Rate: 10Hz.
 * Timeout: 1s (non-critical).
 *
 * Total size: 128 bytes
 */
typedef struct {
	uint32_t sequence;
	uint64_t timestamp_us;

	uint16_t voltage_mv;                    /* Total voltage (millivolts) */
	int16_t  current_ma;                    /* Current (milliamps, negative=discharge) */
	uint16_t capacity_mah;                  /* Remaining capacity (mAh) */
	uint8_t  percentage;                    /* Battery % (0-100) */
	uint8_t  cell_count;                    /* Number of cells (2-12) */

	uint16_t cell_voltage_mv[IPC_MAX_BATTERY_CELLS];  /* Individual cell voltages */

	uint8_t  warning_flags;                 /* Bit 0: low voltage, Bit 1: overcurrent */
	int8_t   temperature_degC;              /* Battery temperature */

	uint8_t  _reserved[68];                 /* Pad to 124 bytes */
	uint16_t crc16;
	uint16_t _pad_align;
} __attribute__((aligned(128))) ipc_battery_status_t;

/**
 * @brief CM85 Heartbeat (CM85 → CM33)
 *
 * FMU alive signal. Rate: 10Hz.
 * Timeout: 100ms → CM33 triggers POEG motor kill.
 *
 * Total size: 32 bytes
 */
typedef struct {
	uint32_t sequence;
	uint64_t timestamp_us;

	uint8_t  system_state;                  /* ipc_system_state_t */
	uint8_t  cpu_load_percent;              /* 0-100 */
	int16_t  temperature_degC;              /* MCU die temp */
	uint32_t error_flags;                   /* Bitmask of error conditions */

	uint8_t  _reserved[10];                 /* Pad to 28 bytes */
	uint16_t crc16;
} __attribute__((aligned(32))) ipc_heartbeat_cm85_t;

/**
 * @brief CM33 Heartbeat (CM33 → CM85)
 *
 * IO processor status. Rate: 10Hz.
 * Timeout: 200ms → CM85 emergency land.
 *
 * Total size: 32 bytes
 */
typedef struct {
	uint32_t sequence;
	uint64_t timestamp_us;

	uint8_t  system_state;                  /* ipc_system_state_t */
	uint8_t  cpu_load_percent;              /* 0-100 */
	int16_t  temperature_degC;
	uint32_t error_flags;

	uint8_t  _reserved[10];
	uint16_t crc16;
} __attribute__((aligned(32))) ipc_heartbeat_cm33_t;

/**
 * @brief Performance Counters (shared, 60KB region)
 *
 * Optional debug/telemetry data.
 */
typedef struct {
	/* IPC performance */
	uint32_t ipc_write_count;
	uint32_t ipc_read_count;
	uint32_t ipc_crc_errors;
	uint32_t ipc_sequence_gaps;
	uint32_t ipc_rtt_min_us;
	uint32_t ipc_rtt_max_us;
	uint32_t ipc_rtt_avg_us;

	/* Timeout events */
	uint32_t actuator_timeouts;
	uint32_t rc_timeouts;
	uint32_t heartbeat_cm85_timeouts;
	uint32_t heartbeat_cm33_timeouts;

	/* CM85 stats */
	uint32_t cm85_loop_rate_hz;
	uint32_t cm85_loop_jitter_us;

	/* CM33 stats */
	uint32_t cm33_loop_rate_hz;
	uint32_t cm33_pwm_rate_hz;
	uint32_t cm33_rc_frame_rate_hz;

	uint8_t  _reserved[3904];               /* Pad to 4KB */
} ipc_perf_counters_t;

#pragma pack(pop)

/*******************************************************************************
 * Helper Macros for CRC Calculation
 ******************************************************************************/

/* Calculate CRC for a message (excludes the crc16 field itself) */
#define IPC_CALC_CRC(msg_ptr, msg_type) \
	ipc_crc16_ccitt((const uint8_t *)(msg_ptr), \
	                offsetof(msg_type, crc16))

/* Validate CRC for a message */
#define IPC_VALIDATE_CRC(msg_ptr, msg_type) \
	((msg_ptr)->crc16 == IPC_CALC_CRC(msg_ptr, msg_type))

/*******************************************************************************
 * Compile-Time Size Assertions
 ******************************************************************************/

/* Ensure structures are correctly sized */
_Static_assert(sizeof(ipc_actuator_cmd_t) == 128, "actuator_cmd must be 128 bytes");
_Static_assert(sizeof(ipc_rc_input_t) == 128, "rc_input must be 128 bytes");
_Static_assert(sizeof(ipc_battery_status_t) == 128, "battery_status must be 128 bytes");
_Static_assert(sizeof(ipc_heartbeat_cm85_t) == 32, "heartbeat_cm85 must be 32 bytes");
_Static_assert(sizeof(ipc_heartbeat_cm33_t) == 32, "heartbeat_cm33 must be 32 bytes");

__END_DECLS
