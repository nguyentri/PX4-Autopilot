#pragma once

#include <stdint.h>

#define PX4IO_IPC_PROTOCOL_VERSION 1
#define PX4IO_IPC_MAGIC 0x50583449 // "PX4I"

#pragma pack(push, 1)

enum class IpcFrameType : uint8_t {
	ActuatorCmd = 1,
	RcInput = 2,
	Cm85Heartbeat = 3,
	Cm33Heartbeat = 4,
	Diagnostics = 5
};

struct IpcHeader {
	uint32_t magic;
	uint8_t version;
	IpcFrameType type;
	uint16_t sequence;
	uint64_t timestamp_us;
	uint16_t payload_len;
	uint16_t crc16;
};

struct IpcActuatorCmd {
	uint16_t motor[8];
	uint16_t servo[8];
	uint8_t armed;
	uint8_t emergency_kill;
	uint8_t failsafe_active;
	uint8_t _padding[5];
};

struct IpcRcInput {
	uint16_t channels[18];
	uint8_t channel_count;
	uint8_t rssi;
	uint8_t rc_lost;
	uint8_t rc_failsafe;
	uint8_t _padding[4];
};

struct IpcCm85Heartbeat {
	uint32_t state;
	uint32_t mode;
};

struct IpcCm33Heartbeat {
	uint32_t status_flags;
	uint32_t arming_flags;
};

struct IpcDiagnostics {
	uint32_t cpu_load;
	uint32_t stack_free;
	uint32_t heap_free;
	uint16_t vbat_mv;
	uint16_t current_ma;
	uint16_t servo_rail_mv;
	uint16_t temperature_c;
};

#pragma pack(pop)
