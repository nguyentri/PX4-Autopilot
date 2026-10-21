// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include "protocol.hpp"

namespace rzv2h
{
namespace demo
{

uint16_t read16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
uint32_t read32(const uint8_t *p) { return uint32_t(read16(p)) | uint32_t(read16(p + 2)) << 16; }
uint64_t read64(const uint8_t *p) { return uint64_t(read32(p)) | uint64_t(read32(p + 4)) << 32; }
void write16(uint8_t *p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
void write32(uint8_t *p, uint32_t v) { write16(p, uint16_t(v)); write16(p + 2, uint16_t(v >> 16)); }
void write64(uint8_t *p, uint64_t v) { write32(p, uint32_t(v)); write32(p + 4, uint32_t(v >> 32)); }

bool Hello::matches(const Hello &other) const
{
	return configured() && other.configured() && roles == other.roles && board == other.board
	       && resources == other.resources && profile == other.profile && output_config == other.output_config;
}

uint8_t encoded_size(Type type)
{
	switch (type) {
	case Type::Heartbeat: return 44;

	case Type::Hello: return 48;

	case Type::Command:
	case Type::Status:
	case Type::Battery:
	case Type::BatteryDetail: return 64;
	}

	return 0;
}

uint32_t crc32(const uint8_t *bytes, size_t size)
{
	uint32_t value = 0xffffffff;

	for (size_t i = 0; i < size; ++i) {
		value ^= i >= 28 && i < 32 ? 0 : bytes[i];

		for (unsigned bit = 0; bit < 8; ++bit) {
			value = (value >> 1) ^ ((value & 1) ? 0xedb88320 : 0);
		}
	}

	return ~value;
}

Frame begin(Type type, const Context &context)
{
	Frame frame{};
	write32(frame.bytes, WireMagic);
	frame.bytes[4] = Major;
	frame.bytes[6] = uint8_t(type);
	frame.bytes[7] = encoded_size(type);
	frame.bytes[8] = context.source;
	write32(frame.bytes + 12, context.sequence);
	write32(frame.bytes + 16, context.epoch);
	write64(frame.bytes + 20, context.publication_us);
	return frame;
}

void finish(Frame &frame)
{
	const uint8_t length = frame.bytes[7];

	if (length >= HeaderSize && length <= EntrySize) {
		write32(frame.bytes + 28, crc32(frame.bytes, length));
	}
}

Error validate(const uint8_t *p, size_t size, uint8_t expected_source, uint32_t epoch)
{
	if (!p || size < HeaderSize || size > EntrySize) { return Error::Length; }

	if (read32(p) != WireMagic) { return Error::Magic; }

	if (p[4] != Major || p[5] != 0) { return Error::Version; }

	const Type type = Type(p[6]);
	const uint8_t length = encoded_size(type);

	if (!length) { return Error::Type; }

	if (p[7] != length || (size != length && size != EntrySize)) { return Error::Length; }

	if (expected_source > 1 || p[8] != expected_source) { return Error::Source; }

	if ((type == Type::Command || type == Type::Hello) && expected_source != 0) { return Error::Source; }

	if ((type == Type::Status || type == Type::Battery || type == Type::BatteryDetail) && expected_source != 1) {
		return Error::Source;
	}

	if (p[9] || read16(p + 10)) { return Error::Reserved; }

	if (!epoch || read32(p + 16) != epoch) { return Error::Epoch; }

	if (!read32(p + 12) || read32(p + 12) >= CounterLimit) { return Error::Sequence; }

	if (read32(p + 28) != crc32(p, length)) { return Error::Crc; }

	for (size_t i = length; i < size; ++i) {
		if (p[i]) { return Error::Padding; }
	}

	if (type == Type::Command) {
		const uint16_t rate = read16(p + 58);

		if (!read32(p + 32) || !read32(p + 36) || !read32(p + 60)
		    || (read16(p + 56) & ~uint16_t(0x7f)) || rate < 50 || rate > 500) { return Error::Semantic; }

		for (unsigned i = 0; i < 4; ++i) {
			const uint16_t pulse = read16(p + 48 + 2 * i);

			if (pulse && (pulse < 90 || pulse > 2500 || uint32_t(pulse) * rate >= 1000000)) {
				return Error::Semantic;
			}
		}
	}

	if (type == Type::Hello && read16(p + 32) != 1) { return Error::Semantic; }

	if (type == Type::Heartbeat && (p[32] > 3 || (p[33] > 100 && p[33] != PercentUnavailable)
					|| (p[34] > 100 && p[34] != PercentUnavailable) || p[35])) {
		return Error::Semantic;
	}

	if (type == Type::Status) {
		const uint8_t backend = p[59];

		if ((read16(p + 52) & ~RequiredActuatorCapabilities) || p[58] > 3 || (backend & 0x80)
		    || ((backend & Initialized) && !(backend & Claimed))
		    || ((backend & (ArmReady | RecoveryEligible)) && !(backend & Initialized))) { return Error::Semantic; }
	}

	if ((type == Type::Battery && read16(p + 58)) || (type == Type::BatteryDetail && read16(p + 50))) {
		return Error::Reserved;
	}

	return Error::None;
}

Frame encode_heartbeat(const Context &context, uint8_t state, uint32_t uptime_ms, uint32_t loop_count)
{
	Frame frame = begin(Type::Heartbeat, context);
	frame.bytes[32] = state;
	frame.bytes[33] = PercentUnavailable;
	frame.bytes[34] = PercentUnavailable;
	write32(frame.bytes + 36, uptime_ms);
	write32(frame.bytes + 40, loop_count);
	finish(frame);
	return frame;
}

Frame encode(const Command &value, const Context &context)
{
	Frame frame = begin(Type::Command, context);
	write32(frame.bytes + 32, value.generation);
	write32(frame.bytes + 36, value.state_generation);
	write64(frame.bytes + 40, value.produced_us);

	for (unsigned i = 0; i < 4; ++i) { write16(frame.bytes + 48 + 2 * i, value.outputs[i]); }

	write16(frame.bytes + 56, value.state);
	write16(frame.bytes + 58, value.rate_hz);
	write32(frame.bytes + 60, value.token);
	finish(frame);
	return frame;
}

Frame encode(const Hello &value, const Context &context)
{
	Frame frame = begin(Type::Hello, context);
	write16(frame.bytes + 32, value.roles);
	write16(frame.bytes + 34, value.board);
	write32(frame.bytes + 36, value.resources);
	write32(frame.bytes + 40, value.profile);
	write32(frame.bytes + 44, value.output_config);
	finish(frame);
	return frame;
}

Frame encode(const Status &value, const Context &context)
{
	Frame frame = begin(Type::Status, context);
	write32(frame.bytes + 32, value.accepted_sequence);
	write32(frame.bytes + 36, value.applied_sequence);
	write32(frame.bytes + 40, value.applied_generation);
	write32(frame.bytes + 44, value.token);
	write32(frame.bytes + 48, value.faults);
	write16(frame.bytes + 52, value.capabilities);
	write16(frame.bytes + 54, value.rate_hz);
	write16(frame.bytes + 56, value.hardware_contract);
	frame.bytes[58] = value.lease_state;
	frame.bytes[59] = value.backend;
	write32(frame.bytes + 60, value.loop_count);
	finish(frame);
	return frame;
}

Command command(const Frame &frame)
{
	Command value{};
	value.generation = read32(frame.bytes + 32);
	value.state_generation = read32(frame.bytes + 36);
	value.produced_us = read64(frame.bytes + 40);

	for (unsigned i = 0; i < 4; ++i) { value.outputs[i] = read16(frame.bytes + 48 + 2 * i); }

	value.state = read16(frame.bytes + 56);
	value.rate_hz = read16(frame.bytes + 58);
	value.token = read32(frame.bytes + 60);
	return value;
}

Hello hello(const Frame &frame)
{
	Hello value{};
	value.roles = read16(frame.bytes + 32);
	value.board = read16(frame.bytes + 34);
	value.resources = read32(frame.bytes + 36);
	value.profile = read32(frame.bytes + 40);
	value.output_config = read32(frame.bytes + 44);
	return value;
}

Status status(const Frame &frame)
{
	Status value{};
	value.accepted_sequence = read32(frame.bytes + 32);
	value.applied_sequence = read32(frame.bytes + 36);
	value.applied_generation = read32(frame.bytes + 40);
	value.token = read32(frame.bytes + 44);
	value.faults = read32(frame.bytes + 48);
	value.capabilities = read16(frame.bytes + 52);
	value.rate_hz = read16(frame.bytes + 54);
	value.hardware_contract = read16(frame.bytes + 56);
	value.lease_state = frame.bytes[58];
	value.backend = frame.bytes[59];
	value.loop_count = read32(frame.bytes + 60);
	return value;
}

} // namespace demo
} // namespace rzv2h
