// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include <apps/gateway.hpp>
#include <cassert>
#include <math.h>
#include <cstring>
#include <cstdio>

using namespace rzv2h::demo;

static GatewayPolicy test_policy()
{
	GatewayPolicy p{};
	p.pose_frame = 101; p.obstacle_frame = 202; p.calibration = 303;
	p.intent_age_us = 25000; p.observation_age_us = 100000; p.progress_us = 75000;
	p.uncertainty_us = 500; p.minimum_interval_us = 500;
	p.position_limit_m = 100; p.velocity_limit_m_s = 5; p.acceleration_limit_m_s2 = 4;
	p.yaw_rate_limit_rad_s = 2; p.range_limit_cm = 1200; p.minimum_odometry_quality = 50;

	for (auto &limit : p.variance_limits) { limit = 10; }

	return p;
}

struct Fixture {
	GatewayValidator validator{test_policy()};
	AdvisoryContext context{};
	GatewayClockMapping mapping{};
	GatewayEligibility eligible{};
	uint64_t now{1000000};
	Fixture()
	{
		context.challenge = 1; context.sequence = 1; context.generation = 1;
		context.source_us = 500000; context.source_epoch = 9; context.uncertainty_us = 100;
		context.frame = 101; context.calibration = 303;

		for (unsigned i = 0; i < 4; ++i) { context.linux_boot[i] = i + 1; }

		mapping.destination_minus_source_us = 500000; mapping.source_from_us = 1000;
		mapping.source_until_us = 1000000000000; mapping.qualification = 99; mapping.uncertainty_us = 100;
		assert(validator.begin(1, context.linux_boot, true));
		assert(validator.admit(1, context.linux_boot, true, mapping));
		eligible.intent_authorized = eligible.position_valid = eligible.velocity_valid =
						     eligible.acceleration_valid = eligible.attitude_valid = true;
	}
	AdvisoryPacket mode(uint8_t mask = 1)
	{
		auto p = advisory_begin(Advisory::Mode, context);
		p.bytes[GatewayHeaderSize] = mask; advisory_finish(p); return p;
	}
	AdvisoryPacket trajectory()
	{
		auto p = advisory_begin(Advisory::Trajectory, context);

		for (unsigned i = 0; i < 11; ++i) { write32(p.bytes + GatewayHeaderSize + i * 4, 0x7fc00000); }

		for (unsigned i = 0; i < 3; ++i) { advisory_write_float(p.bytes + GatewayHeaderSize + i * 4, float(i + 1)); }

		advisory_finish(p); return p;
	}
	GatewayError send(const AdvisoryPacket &p) { return validator.receive(p.bytes, read16(p.bytes + 8), now, eligible); }
};

static void session_and_progress()
{
	Fixture f;
	GatewayValidator unconfigured{GatewayPolicy{}};
	assert(!unconfigured.begin(1, f.context.linux_boot, true));
	assert(unconfigured.receive(nullptr, 0, f.now, f.eligible) == GatewayError::Disabled);
	assert(f.send(f.mode()) == GatewayError::None);
	const auto original = f.trajectory();
	assert(f.send(original) == GatewayError::None);
	assert(f.validator.intent_deadline() == 1074800);
	assert(f.send(original) == GatewayError::Replay);
	++f.context.sequence; // Fresh transport sequence with cached source generation is not new intent.
	assert(f.send(f.trajectory()) == GatewayError::Replay);
	f.context.source_us += 40000; ++f.context.generation; f.now += 40000;
	assert(f.send(f.mode()) == GatewayError::None);
	f.validator.update(1074800);
	assert(f.validator.progress_expired());
	f.now = 1075000; f.context.source_us = 575000; ++f.context.sequence; ++f.context.generation;
	assert(f.send(f.trajectory()) == GatewayError::ProgressExpired);
	f.validator.disconnect();
	assert(f.send(original) == GatewayError::Session);
	assert(!f.validator.begin(1, f.context.linux_boot, true));
	assert(f.validator.begin(2, f.context.linux_boot, true));
	assert(!f.validator.admit(1, f.context.linux_boot, true, f.mapping));
	assert(f.validator.admit(2, f.context.linux_boot, true, f.mapping));
	assert(f.send(original) == GatewayError::Session);
	assert(!f.validator.begin(1, f.context.linux_boot, true)); // Older challenge cannot recur within this boot.
}

static void fields_and_clocks()
{
	const unsigned masks[] {0u, 3u, 5u, 7u, 8u, 16u, 32u, 64u, 128u, 255u};

	for (unsigned mask : masks) {
		Fixture f;
		assert(f.send(f.mode(mask)) == GatewayError::Payload);
	}

	Fixture f;
	assert(f.send(f.mode()) == GatewayError::None);
	f.eligible.intent_authorized = false;
	assert(f.send(f.trajectory()) == GatewayError::Eligibility);
	f.eligible.intent_authorized = true;
	auto p = f.trajectory();
	write32(p.bytes + GatewayHeaderSize, 0x7f800000); advisory_finish(p);
	assert(f.send(p) == GatewayError::Payload);
	p = f.trajectory();
	write32(p.bytes + GatewayHeaderSize + 4, 0x7fc00000); // Horizontal position pair is incomplete.
	advisory_write_float(p.bytes + GatewayHeaderSize + 16, 0); advisory_finish(p);
	assert(f.send(p) == GatewayError::Payload);
	p = f.trajectory();
	write32(p.bytes + 52, 999); advisory_finish(p);
	assert(f.send(p) == GatewayError::Frame);
	p = f.trajectory();
	write32(p.bytes + 48, 1000); advisory_finish(p);
	assert(f.send(p) == GatewayError::Clock);
	p = f.trajectory();
	write64(p.bytes + 40, 600000); advisory_finish(p);
	assert(f.send(p) == GatewayError::Age);
	p = f.trajectory();
	write64(p.bytes + 40, 400000); advisory_finish(p);
	assert(f.send(p) == GatewayError::Age);
	assert(f.send(f.trajectory()) == GatewayError::None); // Both yaw fields NaN retain valid current yaw.
	f.now -= 1;
	assert(f.send(f.mode()) == GatewayError::Session); // Flight clock regression revokes the session.
	Fixture overflow;
	overflow.validator.disconnect();
	assert(overflow.validator.begin(2, overflow.context.linux_boot, true));
	overflow.mapping.destination_minus_source_us = INT64_MAX;
	assert(overflow.validator.admit(2, overflow.context.linux_boot, true, overflow.mapping));
	overflow.context.challenge = 2;
	assert(overflow.send(overflow.mode()) == GatewayError::Clock);
}

static void observations()
{
	Fixture f;
	auto p = advisory_begin(Advisory::Odometry, f.context);
	advisory_write_float(p.bytes + GatewayHeaderSize + 12, 1); // w,x,y,z quaternion.
	p.bytes[GatewayHeaderSize + 76] = 100; advisory_finish(p);
	assert(f.send(p) == GatewayError::None);
	++f.context.sequence; ++f.context.generation; f.context.source_us += 1000; f.now += 1000;
	p = advisory_begin(Advisory::Odometry, f.context);
	advisory_write_float(p.bytes + GatewayHeaderSize + 12, 1);
	advisory_write_float(p.bytes + GatewayHeaderSize + 40, -1); // Negative position variance.
	p.bytes[GatewayHeaderSize + 76] = 100; advisory_finish(p);
	assert(f.send(p) == GatewayError::Payload);
	f.context.frame = 202;
	p = advisory_begin(Advisory::Obstacle, f.context);
	auto *v = p.bytes + GatewayHeaderSize;
	write16(v, 10); write16(v + 2, 1200); write16(v + 4, 5);

	for (unsigned i = 0; i < 72; ++i) { write16(v + 8 + i * 2, UINT16_MAX); }

	write16(v + 8, 100); advisory_finish(p);
	assert(f.send(p) == GatewayError::None);
	++f.context.sequence; ++f.context.generation; f.context.source_us += 1000; f.now += 1000;
	write32(p.bytes + 12, f.context.sequence); write64(p.bytes + 32, f.context.generation);
	write64(p.bytes + 40, f.context.source_us); write16(v + 8, 1); advisory_finish(p);
	assert(f.send(p) == GatewayError::Payload);
	++f.context.sequence; ++f.context.generation; f.context.source_us += 1000; f.now += 1000;
	write32(p.bytes + 12, f.context.sequence); write64(p.bytes + 32, f.context.generation);
	write64(p.bytes + 40, f.context.source_us); write16(v + 8, 0); advisory_finish(p);
	assert(f.send(p) == GatewayError::None); // Explicit near-range indication, not an invalid reading.
}

static void malformed()
{
	Fixture f;
	const auto valid = f.mode();

	for (size_t bit = 0; bit < 97 * 8; ++bit) {
		Fixture isolated;
		auto p = valid; p.bytes[bit / 8] ^= uint8_t(1u << (bit % 8));
		assert(isolated.send(p) != GatewayError::None);
	}

	uint32_t random = 0xa552dca8;

	for (unsigned trial = 0; trial < 100000; ++trial) {
		AdvisoryPacket p{};

		for (auto &byte : p.bytes) { random ^= random << 13; random ^= random >> 17; random ^= random << 5; byte = uint8_t(random); }

		const size_t length = trial % (GatewayPacketSize + 1);
		assert(f.validator.receive(p.bytes, length, f.now, f.eligible) != GatewayError::None);
	}
}

int main(int argc, char *[])
{
	if (argc > 1) {
		Fixture f;
		const auto packet = f.mode();

		for (unsigned i = 0; i < 97; ++i) { printf("%02x", packet.bytes[i]); }

		puts("");
		return 0;
	}

	session_and_progress(); fields_and_clocks(); observations(); malformed();
	puts("private gateway fields, time mapping, planner progress, reconnect and 100000 malformed frames passed");
}
