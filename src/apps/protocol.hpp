// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#pragma once

#include <stddef.h>
#include <stdint.h>

namespace rzv2h
{
namespace demo
{

static constexpr uint32_t WireMagic = 0x525a5632;
static constexpr uint8_t Major = 3;
static constexpr size_t EntrySize = 64;
static constexpr size_t HeaderSize = 32;
static constexpr uint32_t CounterLimit = 0xffffff00;
static constexpr uint64_t ActuatorFreshnessUs = 50000;
static constexpr uint8_t PercentUnavailable = 255;
// Implemented protocol capabilities, distinct from current resource ownership.
enum CapabilityBits : uint16_t {
	PwmBackend = 1 << 0, CoherentValues = 1 << 1, StopInhibit = 1 << 2,
	TokenLease = 1 << 3, AppliedFeedback = 1 << 4,
};
static constexpr uint16_t RequiredActuatorCapabilities = PwmBackend | CoherentValues | StopInhibit | TokenLease |
		AppliedFeedback;

enum class Type : uint8_t { Heartbeat = 0, Command = 1, Status = 4, Hello = 5, Battery = 0x12, BatteryDetail = 0x14 };
enum StateBits : uint16_t {
	Armed = 1 << 0,
	SafetyOff = 1 << 1,
	ForceFailsafe = 1 << 2,
	Lockdown = 1 << 3,
	ManualLockdown = 1 << 4,
	StopMotors = 1 << 5,
	Termination = 1 << 6,
};
enum BackendBits : uint8_t {
	Claimed = 1 << 0,
	Initialized = 1 << 1,
	ArmReady = 1 << 2,
	Inhibited = 1 << 3,
	FaultLatched = 1 << 4,
	RecoveryEligible = 1 << 5,
	RotateSession = 1 << 6,
};

struct Frame { uint8_t bytes[EntrySize] {}; };
struct Context {
	uint32_t sequence{0};
	uint32_t epoch{0};
	uint64_t publication_us{0};
	uint8_t source{0};
};
struct Command {
	uint32_t generation{0};
	uint32_t state_generation{0};
	uint64_t produced_us{0};
	uint16_t outputs[4] {};
	uint16_t state{StopMotors};
	uint16_t rate_hz{0};
	uint32_t token{0};
};
struct Hello {
	uint16_t roles{1};
	uint16_t board{0};
	uint32_t resources{0};
	uint32_t profile{0};
	uint32_t output_config{0};

	bool configured() const { return roles == 1 && board && resources && profile && output_config; }
	bool matches(const Hello &other) const;
};
struct Status {
	uint32_t accepted_sequence{0};
	uint32_t applied_sequence{0};
	uint32_t applied_generation{0};
	uint32_t token{0};
	uint32_t faults{0};
	uint16_t capabilities{0};
	uint16_t rate_hz{0};
	uint16_t hardware_contract{0};
	uint8_t lease_state{0};
	uint8_t backend{Inhibited};
	uint32_t loop_count{0};
};

// Layout declarations are checked independently of the byte-wise codec.
struct __attribute__((packed)) WireHeader {
	uint32_t magic;
	uint8_t major, minor, type, length;
	uint8_t source, flags;
	uint16_t reserved;
	uint32_t sequence, epoch;
	uint64_t publication_us;
	uint32_t crc;
};
struct __attribute__((packed)) WireCommand {
	WireHeader header;
	uint32_t generation, state_generation;
	uint64_t produced_us;
	uint16_t outputs[4], state, rate_hz;
	uint32_t token;
};
struct __attribute__((packed)) WireStatus {
	WireHeader header;
	uint32_t accepted_sequence, applied_sequence, applied_generation, token, faults;
	uint16_t capabilities, rate_hz, hardware_contract;
	uint8_t lease_state, backend;
	uint32_t loop_count;
};
struct __attribute__((packed)) WireHeartbeat {
	WireHeader header;
	uint8_t state, cpu_load, memory_load, reserved;
	uint32_t uptime_ms, loop_count;
};
struct __attribute__((packed)) WireHello {
	WireHeader header;
	uint16_t roles, board;
	uint32_t resources, profile, output_config;
};
struct __attribute__((packed)) WireBattery {
	WireHeader header;
	uint16_t source_id, valid;
	uint32_t generation, sample_age_us, voltage_mv;
	int32_t current_ma;
	uint16_t remaining_permille;
	uint8_t warning, cells;
	uint16_t source_state, reserved;
	uint32_t errors;
};
struct __attribute__((packed)) WireBatteryDetail {
	WireHeader header;
	uint16_t source_id, valid;
	uint32_t generation, sample_age_us;
	int16_t temperature_centic;
	uint16_t min_cell_mv, max_cell_mv, reserved;
	uint32_t remaining_mah, capacity_mah, faults;
};

static_assert(sizeof(WireHeader) == 32 && offsetof(WireHeader, sequence) == 12
	      &&offsetof(WireHeader, epoch) == 16 && offsetof(WireHeader, publication_us) == 20
	      &&offsetof(WireHeader, crc) == 28, "header wire layout");
static_assert(sizeof(WireCommand) == 64 && offsetof(WireCommand, generation) == 32
	      &&offsetof(WireCommand, state_generation) == 36 && offsetof(WireCommand, produced_us) == 40
	      &&offsetof(WireCommand, outputs) == 48 && offsetof(WireCommand, state) == 56
	      &&offsetof(WireCommand, rate_hz) == 58 && offsetof(WireCommand, token) == 60, "command wire layout");
static_assert(sizeof(WireStatus) == 64 && offsetof(WireStatus, accepted_sequence) == 32
	      &&offsetof(WireStatus, applied_sequence) == 36 && offsetof(WireStatus, applied_generation) == 40
	      &&offsetof(WireStatus, token) == 44 && offsetof(WireStatus, faults) == 48
	      &&offsetof(WireStatus, capabilities) == 52 && offsetof(WireStatus, rate_hz) == 54
	      &&offsetof(WireStatus, hardware_contract) == 56 && offsetof(WireStatus, lease_state) == 58
	      &&offsetof(WireStatus, backend) == 59 && offsetof(WireStatus, loop_count) == 60, "status wire layout");
static_assert(sizeof(WireHeartbeat) == 44 && offsetof(WireHeartbeat, uptime_ms) == 36
	      &&offsetof(WireHeartbeat, loop_count) == 40 && sizeof(WireHello) == 48
	      &&offsetof(WireHello, output_config) == 44, "heartbeat/hello wire layout");
static_assert(sizeof(WireBattery) == 64 && offsetof(WireBattery, current_ma) == 48
	      &&offsetof(WireBattery, reserved) == 58 && sizeof(WireBatteryDetail) == 64
	      &&offsetof(WireBatteryDetail, reserved) == 50, "battery wire layout");

enum class Error : uint8_t { None, Length, Magic, Version, Type, Source, Reserved, Epoch, Sequence, Crc, Padding, Semantic };

uint16_t read16(const uint8_t *p);
uint32_t read32(const uint8_t *p);
uint64_t read64(const uint8_t *p);
void write16(uint8_t *p, uint16_t value);
void write32(uint8_t *p, uint32_t value);
void write64(uint8_t *p, uint64_t value);
uint8_t encoded_size(Type type);
uint32_t crc32(const uint8_t *bytes, size_t size);
Frame begin(Type type, const Context &context);
void finish(Frame &frame);
Error validate(const uint8_t *bytes, size_t size, uint8_t expected_source, uint32_t epoch);
Frame encode(const Command &command, const Context &context);
Frame encode(const Hello &hello, const Context &context);
Frame encode(const Status &status, const Context &context);
Frame encode_heartbeat(const Context &context, uint8_t state, uint32_t uptime_ms, uint32_t loop_count);
Command command(const Frame &frame);
Hello hello(const Frame &frame);
Status status(const Frame &frame);

} // namespace demo
} // namespace rzv2h
