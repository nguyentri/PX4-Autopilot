// SPDX-License-Identifier: BSD-3-Clause
#include <apps/perception.hpp>
#include <cassert>
#include <cstring>

using namespace rzv2h::demo;

int main()
{
	GatewayPolicy gateway{};
	gateway.pose_frame = 101; gateway.obstacle_frame = 202; gateway.calibration = 303;
	gateway.intent_age_us = gateway.observation_age_us = gateway.progress_us = 50000;
	gateway.uncertainty_us = 100; gateway.minimum_interval_us = 1000;
	gateway.position_limit_m = 10; gateway.velocity_limit_m_s = gateway.acceleration_limit_m_s2 = 2;
	gateway.yaw_rate_limit_rad_s = 1; gateway.range_limit_cm = 1200; gateway.minimum_odometry_quality = 50;

	for (float &v : gateway.variance_limits) { v = 10; }

	GatewayValidator validator(gateway);
	AdvisoryContext context{};
	context.challenge = 1; context.generation = 1; context.source_us = 500000; context.source_epoch = 1;
	context.sequence = 1; context.frame = 202; context.calibration = 303; context.uncertainty_us = 1;
	context.linux_boot[0] = 123;
	GatewayClockMapping mapping{};
	mapping.destination_minus_source_us = 500000; mapping.source_from_us = 500000; mapping.source_until_us = 1000000;
	mapping.qualification = 1; mapping.uncertainty_us = 1;
	assert(validator.begin(1, context.linux_boot, true));
	assert(validator.admit(1, context.linux_boot, true, mapping));
	RangeAdapterPolicy policy{};
	policy.source = 9; policy.calibration = 303; policy.body_frame = 202;
	policy.minimum_cm = 10; policy.maximum_cm = 1200; policy.minimum_quality = 50;
	policy.horizontal_fov_degrees = 3.6f; policy.mount = RangeMount::Horizontal;
	RangeObservation sample{};
	sample.source = 9; sample.calibration = 303; sample.generation = 1; sample.source_us = 500000;
	sample.distance_cm = 100; sample.quality = 100; sample.result = RangeResult::Measured;
	AdvisoryPacket packet{};
	assert(!range_advisory(RangeAdapterPolicy{}, sample, context, packet));
	assert(!read32(packet.bytes));
	GatewayEligibility eligibility{};

	for (unsigned i = 0; i < 100; ++i) {
		context.sequence = i + 1; context.generation = i + 1; context.source_us = 500000 + i * 1000;
		sample.generation = context.generation; sample.source_us = context.source_us;
		policy.heading_centidegrees = int16_t(-18000 + i * 360);
		sample.result = i % 4 == 0 ? RangeResult::Unknown : i % 4 == 1 ? RangeResult::Measured
				: i % 4 == 2 ? RangeResult::ExplicitNear : RangeResult::ExplicitClear;
		assert(range_advisory(policy, sample, context, packet));
		const auto *payload = packet.bytes + GatewayHeaderSize;
		assert(read16(payload + 4) == 3); // Coverage never rounded above the fitted FoV.
		const uint16_t expected = i % 4 == 0 ? UINT16_MAX : i % 4 == 1 ? 100 : i % 4 == 2 ? 0 : 1201;
		assert(read16(payload + 8) == expected);

		for (unsigned j = 1; j < 72; ++j) { assert(read16(payload + 8 + j * 2) == UINT16_MAX); }

		assert(validator.receive(packet.bytes, 248, context.source_us + 500000, eligibility) == GatewayError::None);
		assert(validator.receive(packet.bytes, 248, context.source_us + 500000, eligibility) == GatewayError::Replay);
	}

	policy.mount = RangeMount::Downward;
	assert(!range_advisory(policy, sample, context, packet));
	policy.mount = RangeMount::Horizontal;
	++sample.generation;
	assert(!range_advisory(policy, sample, context, packet));
	sample.generation = context.generation; sample.calibration = 999;
	assert(!range_advisory(policy, sample, context, packet));
	sample.calibration = policy.calibration; sample.result = RangeResult::Measured; sample.quality = 0;
	assert(!range_advisory(policy, sample, context, packet));
	sample.result = RangeResult::Unknown;
	assert(range_advisory(policy, sample, context, packet)); // Invalid/unknown never becomes a clear sector.
	sample.quality = 100; sample.result = RangeResult::Measured; sample.distance_cm = 1;
	assert(!range_advisory(policy, sample, context, packet));
	const uint32_t nonfinite[3] {0x7f800000, 0xff800000, 0x7fc00000};

	for (uint32_t bits : nonfinite) {
		memcpy(&policy.horizontal_fov_degrees, &bits, 4);
		assert(!range_advisory(policy, sample, context, packet));
	}

	return 0;
}
