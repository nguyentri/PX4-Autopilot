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
 * CM33 view of the shared-memory IPC protocol (single-source definition).
 * This header simply aliases the authoritative CM85 protocol header so both
 * cores use identical layouts, sizes, and CRC rules.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

/* PX4IO register page definitions used by the compatibility layer. */
#include "../../../../src/modules/px4iofirmware/protocol.h"

/* Single-source protocol definition */
#include "../../evk-ra8p1/px4io_cm85/ipc_protocol.h"

/* Compatibility aliases for existing CM33 code */
#define PX4IO_IPC_PROTOCOL_VERSION   IPC_PROTOCOL_VERSION
#define PX4IO_IPC_MAGIC              IPC_MAGIC_NUMBER
#define PX4IO_IPC_MAGIC_INIT         IPC_INIT_MAGIC

#define PX4IO_IPC_ACTUATOR_TIMEOUT_US   IPC_ACTUATOR_TIMEOUT_US
#define PX4IO_IPC_RC_TIMEOUT_US         IPC_RC_TIMEOUT_US
#define PX4IO_IPC_HEARTBEAT_TIMEOUT_US  IPC_HEARTBEAT_CM85_TIMEOUT

#define PX4IO_MAX_MOTORS           IPC_MAX_MOTORS
#define PX4IO_MAX_SERVOS           IPC_MAX_SERVOS
#define PX4IO_MAX_RC_CHANNELS      IPC_MAX_RC_CHANNELS

#define PX4IO_RC_PROTOCOL_SBUS     IPC_RC_PROTOCOL_SBUS
#define PX4IO_RC_PROTOCOL_CRSF     IPC_RC_PROTOCOL_CRSF
#define PX4IO_RC_PROTOCOL_DSM      IPC_RC_PROTOCOL_DSM
#define PX4IO_RC_PROTOCOL_PPM      IPC_RC_PROTOCOL_PPM
#define PX4IO_RC_PROTOCOL_CPPM     IPC_RC_PROTOCOL_CPPM

typedef ipc_actuator_cmd_t    IpcActuatorCmd;
typedef ipc_rc_input_t        IpcRcInput;
typedef ipc_battery_status_t  IpcBatteryStatus;
typedef ipc_heartbeat_cm85_t  IpcCm85Heartbeat;
typedef ipc_heartbeat_cm33_t  IpcCm33Heartbeat;
typedef ipc_perf_counters_t   IpcPerfCounters;
typedef ipc_setup_config_t    IpcSetupConfig;

#ifdef __cplusplus
/* CRC helper to match previous API shape */
template<typename T>
static inline uint16_t ipc_calculate_message_crc(const T *msg, const void *payload_unused = nullptr)
{
	(void)payload_unused;
	return IPC_CALC_CRC(msg, T);
}
#endif
