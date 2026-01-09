/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
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
 * IPC Protocol Definitions for RZV2H Multi-Core Communication
 *
 * This protocol defines the shared memory structure for communication between:
 * - CR8-0 (FMU) <-> CR8-1 (I/O Processor) via uORB-like messages
 * - CR8-1 (I/O Processor) <-> M33 (ESC Controller) via actuator commands
 *
 * Memory Layout (0x70000000 - 0x7000FFFF, 64KB):
 * - 0x70000000-0x70003FFF: CR8-0 <-> CR8-1 IPC region (16KB)
 * - 0x70004000-0x70007FFF: CR8-1 <-> M33 IPC region (16KB)
 * - 0x70008000-0x7000BFFF: Status/Telemetry region (16KB)
 * - 0x7000C000-0x7000FFFF: Reserved (16KB)
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

/*===========================================================================
 * Protocol Constants
 *===========================================================================*/

#define IPC_PROTOCOL_VERSION    0x02
#define IPC_MAGIC               0x525A5632 // "RZV2"
#define IPC_MAGIC_CR8           0x43523800 // "CR8\0"
#define IPC_MAGIC_M33           0x4D333300 // "M33\0"

#define IPC_MAX_ACTUATORS       8
#define IPC_MAX_RC_CHANNELS     16
#define IPC_BUFFER_SIZE         16   // Number of messages in ring buffer

/* Memory region addresses (must match linker script) */
#define IPC_CR8_CR8_BASE        0x70000000  // CR8-0 <-> CR8-1
#define IPC_CR8_M33_BASE        0x70004000  // CR8-1 <-> M33
#define IPC_STATUS_BASE         0x70008000  // Status/Telemetry
#define IPC_RESERVED_BASE       0x7000C000  // Reserved

/* Timeout definitions (in microseconds) */
#define HEARTBEAT_TIMEOUT_US    500000   // 500ms - M33 watchdog trigger
#define RC_LOSS_TIMEOUT_US      100000   // 100ms - RC loss detection
#define FMU_LOSS_TIMEOUT_US     100000   // 100ms - FMU loss detection (CR8-1 view)

/*===========================================================================
 * Message Types
 *===========================================================================*/

/**
 * @brief Message type identifiers for IPC protocol
 */
typedef enum {
	MSG_TYPE_HEARTBEAT       = 0x00,  // Alive signal between cores
	MSG_TYPE_ACTUATOR_CMD    = 0x01,  // CR8-0 -> CR8-1: Motor commands from mixer
	MSG_TYPE_PWM_FEEDBACK    = 0x02,  // M33 -> CR8-1: PWM/DShot feedback
	MSG_TYPE_FAULT_STATUS    = 0x03,  // M33/CR8-1 -> CR8-0: Fault flags
	MSG_TYPE_INPUT_RC        = 0x10,  // CR8-1 -> CR8-0: RC input channels
	MSG_TYPE_ESC_STATUS      = 0x11,  // CR8-1 -> CR8-0: ESC telemetry (via CAN-FD)
	MSG_TYPE_BATTERY_STATUS  = 0x12,  // CR8-1 -> CR8-0: Battery voltage/current
	MSG_TYPE_SAFETY_STATUS   = 0x13,  // CR8-1/M33 -> CR8-0: Safety switch state
	MSG_TYPE_VEHICLE_CMD     = 0x20,  // CR8-0 -> CR8-1: Arming, calibration commands
	MSG_TYPE_VEHICLE_STATUS  = 0x21,  // CR8-0 -> CR8-1: Armed state, flight mode
	MSG_TYPE_FAILSAFE_CMD    = 0x30,  // Any -> Any: Failsafe trigger
} MessageType_e;

/*===========================================================================
 * Message Header (Common to all messages)
 *===========================================================================*/

/**
 * @brief Common header for all IPC messages
 *
 * CRC32 covers the entire message including header (with crc32 field zeroed)
 */
typedef struct {
	uint32_t magic;          // IPC_MAGIC or core-specific magic
	uint8_t  version;        // IPC_PROTOCOL_VERSION
	uint8_t  msg_type;       // MessageType_e
	uint16_t sequence;       // Monotonic counter per message type
	uint32_t timestamp_us;   // Source timestamp (hrt_absolute_time)
	uint32_t crc32;          // CRC32 of entire message (with this field zeroed)
} __attribute__((packed)) MessageHeader_t;

/*===========================================================================
 * CR8-0 -> CR8-1 Messages (FMU to I/O Processor)
 *===========================================================================*/

/**
 * @brief Actuator command from mixer output
 *
 * CR8-0 computes motor commands via mc_rate_control -> mixer -> actuator_outputs
 * This message forwards those commands to CR8-1 for relay to M33.
 */
typedef struct {
	MessageHeader_t header;
	uint16_t outputs[IPC_MAX_ACTUATORS];  // PWM: 1000-2000us, DShot: 48-2047
	uint8_t  mixer_select;                // 0: quad+, 1: quadx, 2: hex, etc.
	uint8_t  armed;                       // 0: disarmed, 1: armed
	uint8_t  safety_off;                  // 0: safety on (outputs disabled), 1: safety off
	uint8_t  dshot_cmd;                   // DShot command (beep, reverse, etc.)
} __attribute__((packed)) ActuatorCommand_t;

/**
 * @brief Vehicle command from Commander
 *
 * CR8-0 sends arming, disarming, calibration, and mode change commands.
 */
typedef struct {
	MessageHeader_t header;
	uint16_t command;         // vehicle_command.command
	uint8_t  target_system;   // Target system ID
	uint8_t  target_component;// Target component ID
	float    param1;
	float    param2;
	float    param3;
	float    param4;
	float    param5;
	float    param6;
	float    param7;
} __attribute__((packed)) VehicleCommand_t;

/**
 * @brief Vehicle status broadcast
 *
 * CR8-0 broadcasts current arming state, flight mode, and health flags.
 */
typedef struct {
	MessageHeader_t header;
	uint8_t  arming_state;       // ARMING_STATE_* enum
	uint8_t  nav_state;          // NAVIGATION_STATE_* enum
	uint8_t  hil_state;          // HIL state
	uint8_t  vehicle_type;       // MAV_TYPE
	uint32_t system_status;      // Bitmask of subsystem health
	uint32_t failsafe_flags;     // Active failsafe conditions
} __attribute__((packed)) VehicleStatus_t;

/*===========================================================================
 * CR8-1 -> CR8-0 Messages (I/O Processor to FMU)
 *===========================================================================*/

/**
 * @brief RC input channels from decoder
 *
 * CR8-1 decodes SBUS/CRSF/PPM/DSM and sends normalized channels to CR8-0.
 */
typedef struct {
	MessageHeader_t header;
	uint16_t channels[IPC_MAX_RC_CHANNELS]; // Channel values (1000-2000us scale)
	uint8_t  channel_count;                 // Valid channel count (typically 8-16)
	uint8_t  rssi;                          // Signal strength (0-100 or 0-255)
	uint8_t  input_source;                  // 0: unknown, 1: SBUS, 2: CRSF, 3: PPM, 4: DSM
	uint8_t  failsafe;                      // 0: normal, 1: failsafe mode active
	uint32_t frame_drop_count;              // Cumulative lost frames
} __attribute__((packed)) InputRC_t;

/**
 * @brief ESC telemetry from CAN-FD UAVCAN
 *
 * CR8-1 receives ESC status via CAN-FD and forwards aggregated data.
 */
typedef struct {
	MessageHeader_t header;
	uint16_t rpm[IPC_MAX_ACTUATORS];       // Motor RPM (from DShot telemetry or UAVCAN)
	uint8_t  voltage_v[IPC_MAX_ACTUATORS]; // ESC voltage (0.1V resolution)
	uint8_t  current_a[IPC_MAX_ACTUATORS]; // ESC current (0.5A resolution)
	uint8_t  temperature_c[IPC_MAX_ACTUATORS]; // ESC temperature (1°C resolution)
	uint8_t  esc_count;                    // Number of active ESCs
	uint8_t  online_mask;                  // Bitmask of ESCs responding
} __attribute__((packed)) ESCStatus_t;

/**
 * @brief Battery status from ADC
 *
 * CR8-1 reads battery voltage/current via ADC and computes state.
 */
typedef struct {
	MessageHeader_t header;
	float    voltage_v;          // Battery voltage (V)
	float    current_a;          // Battery current (A)
	float    discharged_mah;     // Consumed capacity (mAh)
	float    remaining_pct;      // Remaining capacity (0-100%)
	uint8_t  cell_count;         // Detected cell count
	uint8_t  source;             // 0: ADC, 1: smart battery
	uint8_t  warning;            // 0: none, 1: low, 2: critical
	uint8_t  padding;
} __attribute__((packed)) BatteryStatus_t;

/**
 * @brief Safety switch and system status
 */
typedef struct {
	MessageHeader_t header;
	uint8_t  safety_switch_state;   // 0: pressed (safety on), 1: released (safety off)
	uint8_t  io_armed_state;        // Actual armed state on I/O processor
	uint8_t  fmu_heartbeat_ok;      // 1: CR8-0 heartbeat received within timeout
	uint8_t  m33_heartbeat_ok;      // 1: M33 heartbeat received within timeout
	uint32_t error_flags;           // Bitmask of I/O errors
} __attribute__((packed)) SafetyStatus_t;

/*===========================================================================
 * CR8-1 <-> M33 Messages (I/O Processor <-> ESC Controller)
 *===========================================================================*/

/**
 * @brief Actuator command forwarded to M33 ESC controller
 *
 * CR8-1 forwards actuator commands from CR8-0 (or generates safe defaults).
 */
typedef struct {
	MessageHeader_t header;
	uint16_t commands[IPC_MAX_ACTUATORS]; // PWM: 1000-2000us, DShot: 48-2047
	uint8_t  armed;                       // 0: disarmed, 1: armed
	uint8_t  safety_off;                  // 0: safety on, 1: safety off (outputs enabled)
	uint8_t  dshot_cmd;                   // DShot command (beep, direction, etc.)
	uint8_t  output_mode;                 // 0: PWM, 1: DShot600, 2: DShot1200
} __attribute__((packed)) ActuatorCmdToM33_t;

/**
 * @brief PWM/DShot feedback from M33
 *
 * M33 reports actual output values and DShot telemetry.
 */
typedef struct {
	MessageHeader_t header;
	uint16_t current_outputs[IPC_MAX_ACTUATORS]; // Actual PWM/DShot values
	uint16_t dshot_rpm[IPC_MAX_ACTUATORS];       // DShot RPM feedback (if available)
	uint8_t  voltage_v;                          // ESC voltage (0.1V resolution)
	uint8_t  current_a;                          // ESC current (0.5A resolution)
	uint8_t  temperature_c;                      // ESC temperature (1°C resolution)
	uint8_t  output_mode;                        // Active output mode
} __attribute__((packed)) PWMFeedback_t;

/**
 * @brief Fault status from M33 safety monitor
 */
typedef struct {
	MessageHeader_t header;
	uint32_t watchdog_count;        // Watchdog service counter
	uint32_t error_flags;           // FAULT_FLAG_* bitmask
	uint8_t  safety_switch_state;   // Physical safety switch state
	uint8_t  armed_state;           // Actual armed state on M33
	uint8_t  cpu_load_pct;          // M33 CPU load (0-100%)
	uint8_t  dma_active;            // DMA running flag
} __attribute__((packed)) FaultStatus_t;

/*===========================================================================
 * Heartbeat Messages
 *===========================================================================*/

/**
 * @brief Heartbeat message for liveness monitoring
 *
 * Each core sends heartbeats to neighbors for watchdog/failsafe detection.
 */
typedef struct {
	MessageHeader_t header;
	uint8_t  source_core;     // 0: CR8-0, 1: CR8-1, 2: M33
	uint8_t  state;           // Core state (0: init, 1: running, 2: error, 3: shutdown)
	uint8_t  cpu_load_pct;    // CPU utilization (0-100%)
	uint8_t  mem_load_pct;    // Memory utilization (0-100%)
	uint32_t uptime_ms;       // Milliseconds since boot
	uint32_t loop_count;      // Main loop iteration counter
} __attribute__((packed)) Heartbeat_t;

/**
 * @brief Failsafe command for emergency state transitions
 */
typedef struct {
	MessageHeader_t header;
	uint8_t  failsafe_type;   // FAILSAFE_TYPE_* enum
	uint8_t  source_core;     // Which core triggered the failsafe
	uint8_t  action;          // Requested action (0: hold, 1: land, 2: disarm)
	uint8_t  priority;        // Priority (higher = more urgent)
	uint32_t reason_flags;    // Bitmask of reasons
} __attribute__((packed)) FailsafeCmd_t;

/*===========================================================================
 * Error Flags (Bitmasks)
 *===========================================================================*/

/* FaultStatus error_flags */
#define FAULT_FLAG_WATCHDOG_TRIGGERED   (1 << 0)
#define FAULT_FLAG_DMA_ERROR            (1 << 1)
#define FAULT_FLAG_CR8_TIMEOUT          (1 << 2)
#define FAULT_FLAG_INIT_ERROR           (1 << 3)
#define FAULT_FLAG_PWM_FAULT            (1 << 4)
#define FAULT_FLAG_SAFETY_VIOLATION     (1 << 5)
#define FAULT_FLAG_MEMORY_CORRUPTION    (1 << 6)
#define FAULT_FLAG_OVERTEMP             (1 << 7)

/* SafetyStatus error_flags */
#define IO_ERROR_RC_LOSS                (1 << 0)
#define IO_ERROR_FMU_LOSS               (1 << 1)
#define IO_ERROR_M33_LOSS               (1 << 2)
#define IO_ERROR_BATTERY_LOW            (1 << 3)
#define IO_ERROR_BATTERY_CRITICAL       (1 << 4)
#define IO_ERROR_CAN_BUS                (1 << 5)
#define IO_ERROR_ADC                    (1 << 6)

/* Failsafe types */
#define FAILSAFE_TYPE_RC_LOSS           0
#define FAILSAFE_TYPE_FMU_LOSS          1
#define FAILSAFE_TYPE_BATTERY_LOW       2
#define FAILSAFE_TYPE_BATTERY_CRITICAL  3
#define FAILSAFE_TYPE_GPS_LOSS          4
#define FAILSAFE_TYPE_GEOFENCE          5
#define FAILSAFE_TYPE_MANUAL            6

/* Core identifiers */
#define CORE_ID_CR8_0                   0
#define CORE_ID_CR8_1                   1
#define CORE_ID_M33                     2

/*===========================================================================
 * Ring Buffer Structure
 *===========================================================================*/

/**
 * @brief Thread-safe ring buffer for IPC messages
 *
 * Uses volatile head/tail with memory barriers for lock-free operation.
 */
template <typename T, int Size>
struct RingBuffer {
	volatile uint32_t head;     // Write index (producer increments)
	volatile uint32_t tail;     // Read index (consumer increments)
	T buffer[Size];
};

/*===========================================================================
 * Shared Memory Layout - CR8-0 <-> CR8-1
 *===========================================================================*/

/**
 * @brief CR8-0 <-> CR8-1 IPC region at 0x70000000
 *
 * CR8-0 (FMU) writes: actuator_cmds, vehicle_cmds, vehicle_status, heartbeat_fmu
 * CR8-1 (I/O) writes: input_rc, esc_status, battery_status, safety_status, heartbeat_io
 */
typedef struct {
	uint32_t magic_start;       // IPC_MAGIC_CR8

	/* CR8-0 -> CR8-1 (FMU to I/O) */
	RingBuffer<ActuatorCommand_t, IPC_BUFFER_SIZE>  actuator_cmds;
	RingBuffer<VehicleCommand_t, IPC_BUFFER_SIZE>   vehicle_cmds;
	RingBuffer<VehicleStatus_t, IPC_BUFFER_SIZE>    vehicle_status;
	RingBuffer<Heartbeat_t, 4>                      heartbeat_fmu;

	/* CR8-1 -> CR8-0 (I/O to FMU) */
	RingBuffer<InputRC_t, IPC_BUFFER_SIZE>          input_rc;
	RingBuffer<ESCStatus_t, IPC_BUFFER_SIZE>        esc_status;
	RingBuffer<BatteryStatus_t, IPC_BUFFER_SIZE>    battery_status;
	RingBuffer<SafetyStatus_t, IPC_BUFFER_SIZE>     safety_status;
	RingBuffer<Heartbeat_t, 4>                      heartbeat_io;

	/* Failsafe commands (bidirectional) */
	RingBuffer<FailsafeCmd_t, 4>                    failsafe_cmds;

	uint32_t magic_end;         // IPC_MAGIC_CR8
} __attribute__((packed, aligned(64))) SharedMemCR8_t;

/*===========================================================================
 * Shared Memory Layout - CR8-1 <-> M33
 *===========================================================================*/

/**
 * @brief CR8-1 <-> M33 IPC region at 0x70004000
 *
 * CR8-1 (I/O) writes: actuator_cmds_m33, heartbeat_cr8
 * M33 (ESC) writes: pwm_feedback, fault_status, heartbeat_m33
 */
typedef struct {
	uint32_t magic_start;       // IPC_MAGIC_M33

	/* CR8-1 -> M33 */
	RingBuffer<ActuatorCmdToM33_t, IPC_BUFFER_SIZE> actuator_cmds;
	RingBuffer<Heartbeat_t, 4>                      heartbeat_cr8;

	/* M33 -> CR8-1 */
	RingBuffer<PWMFeedback_t, IPC_BUFFER_SIZE>      pwm_feedback;
	RingBuffer<FaultStatus_t, IPC_BUFFER_SIZE>      fault_status;
	RingBuffer<Heartbeat_t, 4>                      heartbeat_m33;

	uint32_t magic_end;         // IPC_MAGIC_M33
} __attribute__((packed, aligned(64))) SharedMemM33_t;

/*===========================================================================
 * Static Assertions
 *===========================================================================*/

static_assert(sizeof(SharedMemCR8_t) <= 16384, "SharedMemCR8_t exceeds 16KB limit");
static_assert(sizeof(SharedMemM33_t) <= 16384, "SharedMemM33_t exceeds 16KB limit");
static_assert(sizeof(MessageHeader_t) == 16, "MessageHeader_t must be 16 bytes");

#endif // PROTOCOL_H
