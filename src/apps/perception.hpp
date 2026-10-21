// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once
#include "gateway.hpp"

namespace rzv2h
{
namespace demo
{

enum class RangeResult : uint8_t { Unknown, Measured, ExplicitNear, ExplicitClear };
enum class RangeMount : uint8_t { Unconfigured, Horizontal, Downward };

struct RangeAdapterPolicy {
	uint32_t source{0}, calibration{0}, body_frame{0};
	uint16_t minimum_cm{0}, maximum_cm{0};
	int16_t heading_centidegrees{0};
	float horizontal_fov_degrees{0};
	uint8_t minimum_quality{0};
	RangeMount mount{RangeMount::Unconfigured};
};
struct RangeObservation {
	uint32_t source{0}, calibration{0};
	uint64_t generation{0}, source_us{0};
	uint16_t distance_cm{0};
	uint8_t quality{0};
	RangeResult result{RangeResult::Unknown};
};

// Convert a qualified horizontal ray to one measured bin. Clock/session/age
// validation remains mandatory at the private gateway; no uORB is published here.
bool range_advisory(const RangeAdapterPolicy &policy, const RangeObservation &sample,
		    const AdvisoryContext &context, AdvisoryPacket &packet);

}
}
