// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "protocol.hpp"

namespace rzv2h
{
namespace demo
{

struct OutputChannelConfiguration {
	uint16_t function{0};
	uint16_t minimum{0};
	uint16_t maximum{0};
	uint16_t disarmed{0};
	uint16_t failsafe{0};
	bool equals(const OutputChannelConfiguration &other) const
	{
		return function == other.function && minimum == other.minimum && maximum == other.maximum
		       && disarmed == other.disarmed && failsafe == other.failsafe;
	}
};

struct OutputConfiguration {
	uint32_t airframe_id{0};
	OutputChannelConfiguration channels[4] {};
	uint16_t rate_hz{0};
	uint16_t range_reverse_mask{0};
	uint16_t reversible_motor_mask{0};

	bool legal_pulse(uint16_t value) const
	{
		return value == 0 || (value >= 90 && value <= 2500 && uint32_t(value) * rate_hz < 1000000);
	}
	uint16_t active_mask() const
	{
		uint16_t result = 0;

		for (unsigned i = 0; i < 4; ++i) {
			if (channels[i].function) {
				result |= 1u << i;
			}
		}

		return result;
	}
	bool valid() const
	{
		if (rate_hz < 50 || rate_hz > 500 || (range_reverse_mask & ~0xfu) || reversible_motor_mask) { return false; }

		unsigned motors = 0;
		uint16_t functions = 0;

		for (const auto &channel : channels) {
			if (!channel.function) {
				continue;
			}

			if (channel.function < 101 || channel.function > 104 || !channel.minimum
			    || channel.minimum >= channel.maximum || !legal_pulse(channel.minimum) || !legal_pulse(channel.maximum)
			    || !legal_pulse(channel.disarmed) || !legal_pulse(channel.failsafe)) { return false; }

			const uint16_t bit = 1u << (channel.function - 101);

			if (functions & bit) {
				return false;
			}

			functions |= bit;
			++motors;
		}

		// These are the explicitly supported product and laboratory identities.
		return (airframe_id == 4014 && motors == 4) || (airframe_id == 22001 && motors == 2);
	}
	bool equals(const OutputConfiguration &other) const
	{
		if (airframe_id != other.airframe_id || rate_hz != other.rate_hz || range_reverse_mask != other.range_reverse_mask
		    || reversible_motor_mask != other.reversible_motor_mask) { return false; }

		for (unsigned i = 0; i < 4; ++i) {
			if (!channels[i].equals(other.channels[i])) {
				return false;
			}
		}

		return true;
	}
	bool accepts(const Command &command) const
	{
		if (!valid() || command.rate_hz != rate_hz) { return false; }

		for (unsigned i = 0; i < 4; ++i) {
			const auto &channel = channels[i];
			const uint16_t pulse = command.outputs[i];

			if (!channel.function && pulse) {
				return false;
			}

			if (pulse && !((pulse >= channel.minimum && pulse <= channel.maximum)
				       || pulse == channel.disarmed || pulse == channel.failsafe)) { return false; }
		}

		return true;
	}
};

struct OutputProfile {
	uint32_t identity{0};
	OutputConfiguration configuration{};
};

inline const OutputProfile *find_output_profile(const OutputProfile *profiles, size_t count, uint32_t identity)
{
	if (!profiles || count > 2 || !identity) { return nullptr; }

	const OutputProfile *result = nullptr;

	for (size_t i = 0; i < count; ++i) {
		if (profiles[i].identity != identity) {
			continue;
		}

		if (result || !profiles[i].configuration.valid()) {
			return nullptr;
		}

		result = &profiles[i];
	}

	return result;
}

inline uint32_t identify_output_configuration(const OutputProfile *profiles, size_t count,
		const OutputConfiguration &actual)
{
	if (!profiles || count > 2 || !actual.valid()) { return 0; }

	uint32_t identity = 0;

	for (size_t i = 0; i < count; ++i) {
		if (!profiles[i].identity || !profiles[i].configuration.equals(actual)) {
			continue;
		}

		if (identity || !find_output_profile(profiles, count, profiles[i].identity)) {
			return 0;
		}

		identity = profiles[i].identity;
	}

	return identity;
}

}
}
