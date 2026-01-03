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
 * @file protocol.h
 *
 * RA8P1 CM85 ↔ CM33 Inter-Core Communication Protocol
 *
 * This header defines the message structures and protocol for communication
 * between the Cortex-M85 (FMU) and Cortex-M33 (IO) cores via shared memory.
 *
 * Protocol Requirements:
 * - Round-trip time: <1ms (target <<500µs)
 * - Update rate: 400-1000 Hz for actuator commands
 * - Reliability: CRC16 validation, sequence numbers
 * - Safety: Failsafe on message timeout
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

/*******************************************************************************
 * Protocol Version and Magic Numbers
 ******************************************************************************/

#define PX4IO_IPC_PROTOCOL_VERSION  2           /* Increment on breaking changes */
#define PX4IO_IPC_MAGIC             0x50583449  /* "PX4I" in little-endian */
#define PX4IO_IPC_MAGIC_INIT        0xDEADBEEF  /* Initialization complete marker */

/* Endian marker for cross-core validation */
#define PX4IO_ENDIAN_MARKER         0x12345678

/*******************************************************************************
 * Timing Constants
 ******************************************************************************/

#define PX4IO_IPC_HEARTBEAT_RATE_HZ     10      /* Heartbeat rate */
#define PX4IO_IPC_HEARTBEAT_TIMEOUT_US  100000  /* 100ms timeout */
#define PX4IO_IPC_ACTUATOR_TIMEOUT_US   10000   /* 10ms actuator timeout */
#define PX4IO_IPC_RC_TIMEOUT_US         100000  /* 100ms RC timeout */

/*******************************************************************************
 * Message Sizes and Limits
 ******************************************************************************/

#define PX4IO_MAX_MOTORS            8
#define PX4IO_MAX_SERVOS            8
#define PX4IO_MAX_RC_CHANNELS       18
#define PX4IO_MAX_PAYLOAD_SIZE      256

/*******************************************************************************
 * CRC16-CCITT Implementation (polynomial 0x1021)
 ******************************************************************************/

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Calculate CRC16-CCITT over a data buffer
 *
 * @param data   Pointer to data buffer
 * @param len    Length of data in bytes
 * @param crc    Initial CRC value (use 0xFFFF for new calculation)
 * @return uint16_t Computed CRC16 value
 */
static inline uint16_t ipc_crc16(const uint8_t *data, uint16_t len, uint16_t crc)
{
	while (len--) {
		crc ^= (*data++ << 8);

		for (int i = 0; i < 8; i++) {
			if (crc & 0x8000) {
				crc = (crc << 1) ^ 0x1021;

			} else {
				crc = crc << 1;
			}
		}
	}

	return crc;
}

/**
 * @brief Calculate CRC16 for a complete message (header + payload)
 *
 * @param header Pointer to message header
 * @param payload Pointer to payload (can be NULL if payload_len is 0)
 * @return uint16_t Computed CRC16 value
 */
static inline uint16_t ipc_calculate_message_crc(const void *header, const void *payload);

#ifdef __cplusplus
}
#endif

/*******************************************************************************
 * Message Frame Types
 ******************************************************************************/

#ifdef __cplusplus
enum class IpcFrameType : uint8_t {
	Invalid        = 0,
	ActuatorCmd    = 1,     /* CM85→CM33: Motor/servo commands */
	RcInput        = 2,     /* CM33→CM85: RC channel data */
	Cm85Heartbeat  = 3,     /* CM85→CM33: FMU alive signal */
	Cm33Heartbeat  = 4,     /* CM33→CM85: IO status */
	Diagnostics    = 5,     /* Bidirectional: Debug/telemetry */
	ConfigWrite    = 6,     /* CM85→CM33: Configuration update */
	ConfigRead     = 7,     /* CM85→CM33: Configuration request */
	ConfigResponse = 8,     /* CM33→CM85: Configuration response */
	EmergencyKill  = 9,     /* CM85→CM33: Immediate motor kill */
	Ack            = 10,    /* Generic acknowledgment */
	Nack           = 11,    /* Generic negative ack */
	Max            = 12
};
#else
typedef enum {
	IpcFrameType_Invalid        = 0,
	IpcFrameType_ActuatorCmd    = 1,
	IpcFrameType_RcInput        = 2,
	IpcFrameType_Cm85Heartbeat  = 3,
	IpcFrameType_Cm33Heartbeat  = 4,
	IpcFrameType_Diagnostics    = 5,
	IpcFrameType_ConfigWrite    = 6,
	IpcFrameType_ConfigRead     = 7,
	IpcFrameType_ConfigResponse = 8,
	IpcFrameType_EmergencyKill  = 9,
	IpcFrameType_Ack            = 10,
	IpcFrameType_Nack           = 11,
	IpcFrameType_Max            = 12
} IpcFrameType;
#endif

/*******************************************************************************
 * Message Structures (packed for cross-core compatibility)
 *
 * All structures use explicit padding to ensure alignment across cores.
 * Total size should be multiple of 4 bytes for efficient memory access.
 ******************************************************************************/

#pragma pack(push, 1)

/**
 * @brief IPC Message Header (20 bytes)
 *
 * Present at the start of every IPC message.
 * CRC16 is computed over header (excluding crc16 field) + payload.
 */
struct IpcHeader {
	uint32_t magic;             /* 0x50583449 "PX4I" */
	uint8_t  version;           /* Protocol version (PX4IO_IPC_PROTOCOL_VERSION) */
#ifdef __cplusplus
	IpcFrameType type;          /* Message type */
#else
	uint8_t  type;              /* Message type (IpcFrameType) */
#endif
	uint16_t sequence;          /* Sequence number (monotonic, wraps) */
	uint64_t timestamp_us;      /* Timestamp in microseconds (sender's HRT) */
	uint16_t payload_len;       /* Payload length in bytes (0 for header-only) */
	uint16_t crc16;             /* CRC16-CCITT of header (sans crc16) + payload */
};

/**
 * @brief Actuator Command (CM85 → CM33)
 *
 * Motor and servo setpoints from FMU to IO processor.
 * Sent at 400-1000 Hz during flight.
 */
struct IpcActuatorCmd {
	uint16_t motor[PX4IO_MAX_MOTORS];   /* Motor outputs (0-2000 µs PWM or DShot value) */
	uint16_t servo[PX4IO_MAX_SERVOS];   /* Servo outputs (0-2000 µs PWM) */
	uint8_t  armed;                     /* 1 = motors armed, 0 = disarmed */
	uint8_t  emergency_kill;            /* 1 = immediate kill (POEG trigger) */
	uint8_t  failsafe_active;           /* 1 = failsafe mode active */
	uint8_t  mixer_mode;                /* Mixer mode (0=direct, 1=quad_x, etc.) */
	uint8_t  output_mode;               /* 0=PWM, 1=DShot300, 2=DShot600, 3=DShot1200 */
	uint8_t  _padding[3];               /* Pad to 40 bytes total */
};

/**
 * @brief RC Input (CM33 → CM85)
 *
 * RC channel values and status from IO to FMU.
 * Sent at RC frame rate (50-500 Hz depending on protocol).
 */
struct IpcRcInput {
	uint16_t channels[PX4IO_MAX_RC_CHANNELS];   /* RC channel values (1000-2000 µs) */
	uint8_t  channel_count;             /* Number of valid channels */
	uint8_t  rssi;                      /* Signal strength (0-100, 255=unknown) */
	uint8_t  rc_lost;                   /* 1 = RC signal lost */
	uint8_t  rc_failsafe;               /* 1 = RC failsafe active (from receiver) */
	uint8_t  protocol;                  /* RC protocol (0=SBUS, 1=CRSF, 2=DSM, 3=PPM) */
	uint8_t  frame_drop;                /* Frame drop flag */
	uint16_t frame_count;               /* Total frames received */
	uint16_t lost_frame_count;          /* Lost frame count */
	uint8_t  _padding[2];               /* Pad to 48 bytes total */
};

/**
 * @brief CM85 Heartbeat (CM85 → CM33)
 *
 * FMU alive signal. CM33 triggers POEG kill if not received within timeout.
 */
struct IpcCm85Heartbeat {
	uint32_t state;                     /* FMU state (see MAV_STATE) */
	uint32_t mode;                      /* FMU mode flags */
	uint32_t cpu_load;                  /* FMU CPU load (0-1000, 1000=100%) */
	uint32_t error_count;               /* Accumulated error count */
};

/**
 * @brief CM33 Heartbeat (CM33 → CM85)
 *
 * IO processor status and diagnostics.
 */
struct IpcCm33Heartbeat {
	uint32_t status_flags;              /* IO status flags (see PX4IO_P_STATUS_FLAGS) */
	uint32_t arming_flags;              /* Arming state flags */
	uint32_t error_flags;               /* Error flags */
	uint16_t ipc_rx_errors;             /* IPC receive errors (CRC, timeout) */
	uint16_t ipc_tx_errors;             /* IPC transmit errors (overflow) */
	uint32_t watchdog_resets;           /* Watchdog reset count */
};

/**
 * @brief Diagnostics (Bidirectional)
 *
 * Telemetry and debug information.
 */
struct IpcDiagnostics {
	uint32_t cpu_load;                  /* CPU load (0-1000) */
	uint32_t stack_free;                /* Free stack space (bytes) */
	uint32_t heap_free;                 /* Free heap space (bytes) */
	uint16_t vbat_mv;                   /* Battery voltage (mV) */
	uint16_t current_ma;                /* Battery current (mA) */
	uint16_t servo_rail_mv;             /* Servo rail voltage (mV) */
	int16_t  temperature_cdeg;          /* Temperature (centi-degrees Celsius) */
	uint32_t ipc_latency_us;            /* Last IPC round-trip time (µs) */
	uint32_t pwm_update_rate_hz;        /* Actual PWM update rate */
	uint32_t rc_frame_rate_hz;          /* RC frame rate */
	uint32_t _padding;                  /* Pad to 36 bytes */
};

/**
 * @brief Emergency Kill Command (CM85 → CM33)
 *
 * Immediate motor kill with reason code.
 */
struct IpcEmergencyKill {
	uint32_t reason;                    /* Kill reason (see POEG trigger reasons) */
	uint32_t timestamp_us_high;         /* High 32 bits of kill timestamp */
	uint32_t timestamp_us_low;          /* Low 32 bits of kill timestamp */
};

#pragma pack(pop)

/*******************************************************************************
 * Status Flag Definitions (compatible with PX4IO register interface)
 ******************************************************************************/

/* PX4IO_P_STATUS_FLAGS */
#define PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED      (1 << 0)
#define PX4IO_P_STATUS_FLAGS_RC_OK              (1 << 1)
#define PX4IO_P_STATUS_FLAGS_RC_PPM             (1 << 2)
#define PX4IO_P_STATUS_FLAGS_RC_DSM             (1 << 3)
#define PX4IO_P_STATUS_FLAGS_RC_SBUS            (1 << 4)
#define PX4IO_P_STATUS_FLAGS_RC_CRSF            (1 << 5)
#define PX4IO_P_STATUS_FLAGS_FMU_OK             (1 << 6)
#define PX4IO_P_STATUS_FLAGS_INIT_OK            (1 << 7)
#define PX4IO_P_STATUS_FLAGS_FAILSAFE           (1 << 8)
#define PX4IO_P_STATUS_FLAGS_SAFETY_OFF         (1 << 9)
#define PX4IO_P_STATUS_FLAGS_SAFETY_BUTTON_EVENT (1 << 10)

/* PX4IO_P_SETUP_ARMING */
#define PX4IO_P_SETUP_ARMING_IO_ARM_OK          (1 << 0)
#define PX4IO_P_SETUP_ARMING_FMU_ARMED          (1 << 1)
#define PX4IO_P_SETUP_ARMING_FMU_PREARMED       (1 << 2)
#define PX4IO_P_SETUP_ARMING_FAILSAFE_CUSTOM    (1 << 3)
#define PX4IO_P_SETUP_ARMING_LOCKDOWN           (1 << 4)
#define PX4IO_P_SETUP_ARMING_FORCE_FAILSAFE     (1 << 5)
#define PX4IO_P_SETUP_ARMING_TERMINATION_FAILSAFE (1 << 6)

/* RC protocol identifiers */
#define PX4IO_RC_PROTOCOL_SBUS                  0
#define PX4IO_RC_PROTOCOL_CRSF                  1
#define PX4IO_RC_PROTOCOL_DSM                   2
#define PX4IO_RC_PROTOCOL_PPM                   3

/* Output mode identifiers */
#define PX4IO_OUTPUT_MODE_PWM                   0
#define PX4IO_OUTPUT_MODE_DSHOT300              1
#define PX4IO_OUTPUT_MODE_DSHOT600              2
#define PX4IO_OUTPUT_MODE_DSHOT1200             3

/*******************************************************************************
 * Inline CRC Calculation Function (implementation)
 ******************************************************************************/

#ifdef __cplusplus
static inline uint16_t ipc_calculate_message_crc(const void *header_ptr, const void *payload)
{
	const IpcHeader *hdr = static_cast<const IpcHeader *>(header_ptr);

	/* Calculate CRC over header (excluding the crc16 field itself) */
	uint16_t crc = 0xFFFF;

	/* CRC over header fields before crc16 */
	const uint8_t *header_bytes = static_cast<const uint8_t *>(header_ptr);
	crc = ipc_crc16(header_bytes, offsetof(IpcHeader, crc16), crc);

	/* CRC over payload (if present) */
	if (hdr->payload_len > 0 && payload != nullptr) {
		crc = ipc_crc16(static_cast<const uint8_t *>(payload), hdr->payload_len, crc);
	}

	return crc;
}
#endif
