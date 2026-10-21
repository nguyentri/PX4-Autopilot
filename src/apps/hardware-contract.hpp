// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "output-configuration.hpp"
#include "battery.hpp"

namespace rzv2h
{
namespace demo
{

// Deliberately unconfigured. Replace only from a reviewed, measured ESC,
// pin/resource, power/kill and image-pair contract. Runtime parameters cannot
// manufacture a qualified hardware identity.
inline const OutputProfile *output_profiles(size_t &count)
{
	static const OutputProfile profiles[2] {};
	count = 2;
	return profiles;
}

inline Hello hardware_identity()
{
	Hello result{};
	size_t count = 0;
	result.output_config = output_profiles(count)[0].identity;
	return result;
}
static constexpr uint16_t OutputRateHz = 0;
static constexpr uint32_t OutputMask = 0;
static constexpr uint16_t HardwareContract = 0;

inline BatteryPolicy battery_policy() { return BatteryPolicy{}; }

}
}
