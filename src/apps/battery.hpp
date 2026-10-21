// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "protocol.hpp"

namespace rzv2h
{
namespace demo
{

struct BatteryBase {
	uint16_t source{0}, valid{0}, remaining_permille{0}, state{0};
	uint32_t generation{0}, age_us{0}, voltage_mv{0}, errors{0};
	int32_t current_ma{0};
	uint8_t warning{0}, cells{0};
};
struct BatteryDetail {
	uint16_t source{0}, valid{0}, min_cell_mv{0}, max_cell_mv{0};
	uint32_t generation{0}, age_us{0}, remaining_mah{0}, capacity_mah{0}, faults{0};
	int16_t temperature_centic{0};
};

// Wire masks, states, units/ranges and the transit bound come from the selected
// device/transport ICD. Zero defaults grant no acquisition or publication.
struct BatteryPolicy {
	uint32_t contract{0}, maximum_age_us{0}, transit_bound_us{0};
	uint32_t minimum_voltage_mv{0}, maximum_voltage_mv{0}, maximum_current_ma{0}, maximum_capacity_mah{0};
	uint16_t source{0}, healthy_state{0}, voltage{0}, current{0}, remaining{0}, cells{0}, warning{0};
	uint16_t temperature{0}, cell_range{0}, charge{0}, capacity{0}, faults{0};
	uint16_t required_base{0}, required_detail{0};
	uint8_t cell_count{0}, warning_values[5] {};
	bool configured() const;
	uint16_t base_mask() const { return voltage | current | remaining | cells | warning; }
	uint16_t detail_mask() const { return temperature | cell_range | charge | capacity | faults; }
};

Frame encode(const BatteryBase &value, const Context &context);
Frame encode(const BatteryDetail &value, const Context &context);
BatteryBase battery_base(const Frame &frame);
BatteryDetail battery_detail(const Frame &frame);

struct BatteryObservation {
	BatteryBase base{};
	BatteryDetail detail{};
	uint64_t age_upper_us{0};
	bool connected{false}, detail_available{false};
	uint8_t warning{0}; // PX4 severity only after the reviewed raw-enum mapping.
};

struct BatteryThresholds {
	float low{0}, critical{0}, emergency{0};
	bool configured() const { return emergency > 0 && critical > emergency && low > critical && low < 1; }
};

struct BatteryTelemetry {
	bool connected{false};
	float voltage_v{0}, current_a{-1}, remaining{-1}, temperature_c{__builtin_nanf("")};
	float cell_delta_v{__builtin_nanf("")};
	uint8_t cells{0}, warning{0};
	uint16_t capacity_mah{0}, errors{0};
};

// This route uses physically acquired SOC. Voltage-based estimation needs a
// separately selected pack/discharge model; it is not inferred from defaults.
BatteryTelemetry battery_telemetry(const BatteryObservation &sample, const BatteryPolicy &policy,
				   const BatteryThresholds &thresholds);

class BatteryReceiver
{
public:
	explicit BatteryReceiver(const BatteryPolicy &policy) : _policy(policy) {}
	void session(uint32_t epoch);
	bool receive(const Frame &frame, uint64_t now);
	BatteryObservation observation(uint64_t now);
private:
	bool monotonic(uint64_t now);
	bool base_valid(const BatteryBase &base) const;
	bool detail_valid(const BatteryDetail &detail) const;
	BatteryPolicy _policy;
	BatteryBase _base{};
	BatteryDetail _detail{};
	uint32_t _epoch{0}, _base_sequence{0}, _detail_sequence{0};
	uint64_t _last_time{0}, _base_received{0}, _detail_received{0};
	uint32_t _base_first_age{0}, _detail_first_age{0};
	bool _have_time{false}, _clock_fault{false}, _have_base{false}, _have_detail{false}, _revoked{false};
};

}
}
