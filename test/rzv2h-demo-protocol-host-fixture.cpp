// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include <apps/protocol.hpp>
#include <assert.h>
#include <stdio.h>
#include <string.h>

using namespace rzv2h::demo;

static Frame golden()
{
	Context context{};
	context.sequence = 0x01020304;
	context.epoch = 7;
	context.publication_us = 0x1020304050607080;
	Command value{};
	value.generation = 9;
	value.state_generation = 2;
	value.produced_us = context.publication_us - 10;
	value.outputs[0] = 1000;
	value.outputs[1] = 1200;
	value.outputs[3] = 2000;
	value.state = Armed | SafetyOff;
	value.rate_hz = 400;
	value.token = 3;
	return encode(value, context);
}

int main(int argc, char **argv)
{
	Frame frame = golden();

	if (argc == 2 && !strcmp(argv[1], "--golden")) {
		for (uint8_t byte : frame.bytes) { printf("%02x", byte); }

		printf("\n");
		return 0;
	}

	assert(validate(frame.bytes, 64, 0, 7) == Error::None);
	const Command decoded = command(frame);
	assert(decoded.generation == 9 && decoded.outputs[0] == 1000 && decoded.outputs[2] == 0);
	assert(decoded.produced_us == 0x1020304050607076 && decoded.token == 3);
	assert(validate(nullptr, 64, 0, 7) == Error::Length);

	for (size_t size = 0; size < 64; ++size) { assert(validate(frame.bytes, size, 0, 7) == Error::Length); }

	assert(validate(frame.bytes, 65, 0, 7) == Error::Length);
	assert(validate(frame.bytes, 64, 1, 7) == Error::Source);
	assert(validate(frame.bytes, 64, 0, 8) == Error::Epoch);
	assert(validate(frame.bytes, 64, 0, 0) == Error::Epoch);

	for (unsigned bit = 0; bit < 512; ++bit) {
		Frame damaged = frame;
		damaged.bytes[bit / 8] ^= uint8_t(1u << (bit % 8));
		assert(validate(damaged.bytes, 64, 0, 7) != Error::None);
	}

	// A byte-aligned private copy is sufficient; no packed raw pointer is loaded.
	uint8_t unaligned[65] {};
	memcpy(unaligned + 1, frame.bytes, 64);
	assert(validate(unaligned + 1, 64, 0, 7) == Error::None);

	Frame wrong = frame;
	wrong.bytes[4] = 2;
	finish(wrong);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Version);
	wrong = frame;
	wrong.bytes[6] = 255;
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Type);
	wrong = frame;
	write32(wrong.bytes + 12, CounterLimit);
	finish(wrong);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Sequence);
	wrong = frame;
	write32(wrong.bytes + 12, 0);
	finish(wrong);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Sequence);

	Command invalid = decoded;
	invalid.outputs[0] = 89;
	Context context{};
	context.sequence = 1;
	context.epoch = 7;
	wrong = encode(invalid, context);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Semantic);
	invalid = decoded;
	invalid.rate_hz = 500;
	invalid.outputs[0] = 2500;
	wrong = encode(invalid, context);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Semantic);
	invalid = decoded;
	invalid.state = 0x80;
	wrong = encode(invalid, context);
	assert(validate(wrong.bytes, 64, 0, 7) == Error::Semantic);

	Hello unconfigured{};
	assert(!unconfigured.configured() && !unconfigured.matches(unconfigured));
	frame = encode(unconfigured, context);
	assert(validate(frame.bytes, 48, 0, 7) == Error::None);
	assert(validate(frame.bytes, 64, 0, 7) == Error::None);
	assert(!hello(frame).configured());
	frame.bytes[63] = 1;
	assert(validate(frame.bytes, 64, 0, 7) == Error::Padding);

	context.source = 1;
	Status unavailable{};
	frame = encode(unavailable, context);
	assert(validate(frame.bytes, 64, 1, 7) == Error::None);
	assert(status(frame).rate_hz == 0 && status(frame).backend == Inhibited);
	unavailable.capabilities = 0x8000;
	frame = encode(unavailable, context);
	assert(validate(frame.bytes, 64, 1, 7) == Error::Semantic);
	unavailable.capabilities = RequiredActuatorCapabilities;
	unavailable.backend = Initialized | ArmReady;
	frame = encode(unavailable, context);
	assert(validate(frame.bytes, 64, 1, 7) == Error::Semantic);

	frame = begin(Type::Heartbeat, context);
	finish(frame);
	assert(validate(frame.bytes, 44, 1, 7) == Error::None);
	assert(validate(frame.bytes, 64, 1, 7) == Error::None);
	frame = encode_heartbeat(context, 0, 1234, 99);
	assert(validate(frame.bytes, 64, 1, 7) == Error::None);
	assert(frame.bytes[33] == PercentUnavailable && frame.bytes[34] == PercentUnavailable);
	assert(read32(frame.bytes + 36) == 1234 && read32(frame.bytes + 40) == 99);
	frame.bytes[33] = 101;
	finish(frame);
	assert(validate(frame.bytes, 64, 1, 7) == Error::Semantic);
	frame = encode_heartbeat(context, 0, 1234, 99);
	frame.bytes[35] = 1;
	finish(frame);
	assert(validate(frame.bytes, 64, 1, 7) == Error::Semantic);

	const Type battery_types[] {Type::Battery, Type::BatteryDetail};

	for (Type type : battery_types) {
		frame = begin(type, context);
		finish(frame);
		assert(validate(frame.bytes, 64, 1, 7) == Error::None);
		write16(frame.bytes + (type == Type::Battery ? 58 : 50), 1);
		finish(frame);
		assert(validate(frame.bytes, 64, 1, 7) == Error::Reserved);
	}

	uint32_t random = 0x12345678;
	uint8_t fuzz[72] {};

	for (unsigned trial = 0; trial < 100000; ++trial) {
		for (auto &byte : fuzz) {
			random ^= random << 13;
			random ^= random >> 17;
			random ^= random << 5;
			byte = uint8_t(random);
		}

		(void)validate(fuzz, trial % sizeof(fuzz), uint8_t(trial % 3), 7);
	}

	puts("protocol boundary, corruption and 100000 seeded malformed-frame checks passed");
	return 0;
}
