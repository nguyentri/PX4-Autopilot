// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include "perception.hpp"
#include <string.h>

namespace rzv2h
{
namespace demo
{

bool range_advisory(const RangeAdapterPolicy &policy, const RangeObservation &sample,
		    const AdvisoryContext &context, AdvisoryPacket &packet)
{
	packet = AdvisoryPacket{};
	uint32_t fov_bits = 0;
	static_assert(sizeof(fov_bits) == sizeof(policy.horizontal_fov_degrees), "float representation");
	memcpy(&fov_bits, &policy.horizontal_fov_degrees, sizeof(fov_bits));

	if ((fov_bits & 0x7f800000u) == 0x7f800000u || policy.horizontal_fov_degrees < 1
	    || policy.horizontal_fov_degrees > 45 || policy.mount != RangeMount::Horizontal
	    || !policy.source || !policy.calibration || !policy.body_frame || !policy.minimum_cm
	    || policy.maximum_cm <= policy.minimum_cm || policy.maximum_cm >= UINT16_MAX - 1
	    || !policy.minimum_quality || policy.minimum_quality > 100
	    || policy.heading_centidegrees < -18000 || policy.heading_centidegrees > 18000
	    || sample.source != policy.source || sample.calibration != policy.calibration
	    || context.calibration != policy.calibration || context.frame != policy.body_frame
	    || !sample.generation || context.generation != sample.generation || context.source_us != sample.source_us
	    || !sample.source_us || sample.quality > 100) { return false; }

	uint16_t distance = UINT16_MAX;

	if (sample.result != RangeResult::Unknown) {
		if (sample.quality < policy.minimum_quality) { return false; }

		switch (sample.result) {
		case RangeResult::Measured:
			if (sample.distance_cm < policy.minimum_cm || sample.distance_cm > policy.maximum_cm) { return false; }

			distance = sample.distance_cm; break;

		case RangeResult::ExplicitNear: distance = 0; break;

		case RangeResult::ExplicitClear: distance = policy.maximum_cm + 1; break;

		default: return false;
		}
	}

	packet = advisory_begin(Advisory::Obstacle, context);
	uint8_t *payload = packet.bytes + GatewayHeaderSize;
	write16(payload, policy.minimum_cm); write16(payload + 2, policy.maximum_cm);
	// The private schema uses integer degrees. Round coverage down, never claim
	// a wider observed FoV. The remaining entries and uncovered arc are unknown.
	write16(payload + 4, uint16_t(policy.horizontal_fov_degrees));
	write16(payload + 6, uint16_t(policy.heading_centidegrees));

	for (unsigned i = 0; i < 72; ++i) { write16(payload + 8 + i * 2, UINT16_MAX); }

	write16(payload + 8, distance);
	advisory_finish(packet); return true;
}

}
}
