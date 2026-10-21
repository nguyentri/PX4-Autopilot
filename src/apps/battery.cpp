// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include "battery.hpp"

namespace rzv2h
{
namespace demo
{

static bool independent_bits(const uint16_t *bits, unsigned count)
{
	uint16_t used = 0;

	for (unsigned i = 0; i < count; ++i) {
		if ((bits[i] && (bits[i] & (bits[i] - 1))) || (used & bits[i])) { return false; }

		used |= bits[i];
	}

	return true;
}

bool BatteryPolicy::configured() const
{
	const uint16_t base_bits[5] {voltage, current, remaining, cells, warning};
	const uint16_t detail_bits[5] {temperature, cell_range, charge, capacity, faults};

	if (!contract || !source || !maximum_age_us || !transit_bound_us || transit_bound_us >= maximum_age_us
	    || !voltage || !minimum_voltage_mv || maximum_voltage_mv <= minimum_voltage_mv
	    || !cell_count || cell_count > 14 || (current && !maximum_current_ma)
	    || ((charge || capacity) && !maximum_capacity_mah)
	    || !(required_base & voltage) || (required_base & ~base_mask()) || (required_detail & ~detail_mask())
	    || !independent_bits(base_bits, 5) || !independent_bits(detail_bits, 5)) { return false; }

	if (warning) {
		for (unsigned i = 0; i < 5; ++i) {
			for (unsigned j = i + 1; j < 5; ++j) {
				if (warning_values[i] == warning_values[j]) { return false; }
			}
		}
	}

	return true;
}

Frame encode(const BatteryBase &v, const Context &context)
{
	Frame f = begin(Type::Battery, context);
	write16(f.bytes + 32, v.source); write16(f.bytes + 34, v.valid);
	write32(f.bytes + 36, v.generation); write32(f.bytes + 40, v.age_us); write32(f.bytes + 44, v.voltage_mv);
	write32(f.bytes + 48, uint32_t(v.current_ma)); write16(f.bytes + 52, v.remaining_permille);
	f.bytes[54] = v.warning; f.bytes[55] = v.cells; write16(f.bytes + 56, v.state); write32(f.bytes + 60, v.errors);
	finish(f); return f;
}

Frame encode(const BatteryDetail &v, const Context &context)
{
	Frame f = begin(Type::BatteryDetail, context);
	write16(f.bytes + 32, v.source); write16(f.bytes + 34, v.valid);
	write32(f.bytes + 36, v.generation); write32(f.bytes + 40, v.age_us);
	write16(f.bytes + 44, uint16_t(v.temperature_centic)); write16(f.bytes + 46, v.min_cell_mv);
	write16(f.bytes + 48, v.max_cell_mv); write32(f.bytes + 52, v.remaining_mah);
	write32(f.bytes + 56, v.capacity_mah); write32(f.bytes + 60, v.faults);
	finish(f); return f;
}

BatteryBase battery_base(const Frame &f)
{
	BatteryBase v{};
	v.source = read16(f.bytes + 32); v.valid = read16(f.bytes + 34); v.generation = read32(f.bytes + 36);
	v.age_us = read32(f.bytes + 40); v.voltage_mv = read32(f.bytes + 44);
	const uint32_t raw = read32(f.bytes + 48);
	v.current_ma = raw <= INT32_MAX ? int32_t(raw) : -1 - int32_t(UINT32_MAX - raw);
	v.remaining_permille = read16(f.bytes + 52); v.warning = f.bytes[54]; v.cells = f.bytes[55];
	v.state = read16(f.bytes + 56); v.errors = read32(f.bytes + 60); return v;
}

BatteryDetail battery_detail(const Frame &f)
{
	BatteryDetail v{};
	v.source = read16(f.bytes + 32); v.valid = read16(f.bytes + 34); v.generation = read32(f.bytes + 36);
	v.age_us = read32(f.bytes + 40);
	const uint16_t raw = read16(f.bytes + 44);
	v.temperature_centic = raw <= INT16_MAX ? int16_t(raw) : int16_t(-1 - int16_t(UINT16_MAX - raw));
	v.min_cell_mv = read16(f.bytes + 46); v.max_cell_mv = read16(f.bytes + 48);
	v.remaining_mah = read32(f.bytes + 52); v.capacity_mah = read32(f.bytes + 56); v.faults = read32(f.bytes + 60);
	return v;
}

void BatteryReceiver::session(uint32_t epoch)
{
	_epoch = epoch; _base = BatteryBase{}; _detail = BatteryDetail{};
	_base_sequence = _detail_sequence = 0; _base_received = _detail_received = _last_time = 0;
	_base_first_age = _detail_first_age = 0;
	_have_base = _have_detail = _have_time = _clock_fault = _revoked = false;
}

bool BatteryReceiver::monotonic(uint64_t now)
{
	if (_have_time && now < _last_time) { _clock_fault = true; }

	_have_time = true; _last_time = now; return !_clock_fault;
}

bool BatteryReceiver::base_valid(const BatteryBase &v) const
{
	if (v.source != _policy.source || (v.valid & ~_policy.base_mask()) || v.generation >= CounterLimit
	    || (v.valid && !v.generation)) { return false; }

	if ((v.valid & _policy.voltage) && (v.voltage_mv < _policy.minimum_voltage_mv
					    || v.voltage_mv > _policy.maximum_voltage_mv)) { return false; }

	if ((v.valid & _policy.current) && (int64_t(v.current_ma) > _policy.maximum_current_ma
					    || -int64_t(v.current_ma) > _policy.maximum_current_ma)) { return false; }

	if ((v.valid & _policy.remaining) && v.remaining_permille > 1000) { return false; }

	if ((v.valid & _policy.cells) && v.cells != _policy.cell_count) { return false; }

	if (v.valid & _policy.warning) {
		bool known = false;

		for (uint8_t raw : _policy.warning_values) { known |= raw == v.warning; }

		if (!known) { return false; }
	}

	return true;
}

bool BatteryReceiver::detail_valid(const BatteryDetail &v) const
{
	return v.source == _policy.source && !(v.valid & ~_policy.detail_mask()) && v.generation && v.generation < CounterLimit
	       && (!(v.valid & _policy.cell_range) || (v.min_cell_mv && v.min_cell_mv <= v.max_cell_mv
			       && uint32_t(v.max_cell_mv) * _policy.cell_count <= _policy.maximum_voltage_mv))
	       && (!(v.valid & _policy.charge) || v.remaining_mah <= _policy.maximum_capacity_mah)
	       && (!(v.valid & _policy.capacity) || (v.capacity_mah && v.capacity_mah <= _policy.maximum_capacity_mah))
	       && (!((v.valid & _policy.charge) && (v.valid & _policy.capacity)) || v.remaining_mah <= v.capacity_mah);
}

bool BatteryReceiver::receive(const Frame &frame, uint64_t now)
{
	if (!monotonic(now) || !_policy.configured() || validate(frame.bytes, EntrySize, 1, _epoch) != Error::None) { return false; }

	const uint32_t sequence = read32(frame.bytes + 12);

	if (Type(frame.bytes[6]) == Type::Battery) {
		const BatteryBase v = battery_base(frame);

		if (sequence <= _base_sequence || !base_valid(v) || (_have_base && v.generation < _base.generation)) { return false; }

		if (_have_base && v.generation == _base.generation) {
			if ((v.valid & ~_base.valid) || v.age_us < _base.age_us
			    || ((v.valid & _policy.voltage) && v.voltage_mv != _base.voltage_mv)
			    || ((v.valid & _policy.current) && v.current_ma != _base.current_ma)
			    || ((v.valid & _policy.remaining) && v.remaining_permille != _base.remaining_permille)
			    || ((v.valid & _policy.warning) && v.warning != _base.warning)
			    || ((v.valid & _policy.cells) && v.cells != _base.cells)) { return false; }

			// A repeated acquisition may revoke validity, never extend its lifetime.

		} else {
			_base_received = now; _base_first_age = v.age_us; _have_detail = false; _revoked = false;
		}

		_revoked |= v.state != _policy.healthy_state || (v.valid & _policy.required_base) != _policy.required_base;
		_base = v; _base_sequence = sequence; _have_base = true; return true;
	}

	if (Type(frame.bytes[6]) == Type::BatteryDetail) {
		const BatteryDetail v = battery_detail(frame);

		if (sequence <= _detail_sequence || !detail_valid(v) || !_have_base || v.generation != _base.generation) { return false; }

		if (_have_detail) {
			if ((v.valid & ~_detail.valid) || v.age_us < _detail.age_us || v.temperature_centic != _detail.temperature_centic
			    || v.min_cell_mv != _detail.min_cell_mv || v.max_cell_mv != _detail.max_cell_mv
			    || v.remaining_mah != _detail.remaining_mah || v.capacity_mah != _detail.capacity_mah) { return false; }

		} else { _detail_received = now; _detail_first_age = v.age_us; }

		_revoked |= (v.valid & _policy.required_detail) != _policy.required_detail || ((v.valid & _policy.faults) && v.faults);
		_detail = v; _detail_sequence = sequence; _have_detail = true; return true;
	}

	return false;
}

BatteryObservation BatteryReceiver::observation(uint64_t now)
{
	BatteryObservation result{};

	if (!monotonic(now) || !_policy.configured() || !_have_base) { return result; }

	result.base = _base; result.detail = _detail;
	const uint64_t elapsed = now - _base_received;
	// Saturate before addition so even an extreme monotonic interval cannot wrap.
	const uint64_t fixed = uint64_t(_base_first_age) + _policy.transit_bound_us;
	result.age_upper_us = elapsed > UINT64_MAX - fixed ? UINT64_MAX : elapsed + fixed;

	if (result.age_upper_us < uint64_t(_base.age_us) + _policy.transit_bound_us) {
		result.age_upper_us = uint64_t(_base.age_us) + _policy.transit_bound_us;
	}

	const bool detail_fresh = _have_detail && now - _detail_received < _policy.maximum_age_us
				  && uint64_t(_detail_first_age) + _policy.transit_bound_us + (now - _detail_received) < _policy.maximum_age_us
				  && uint64_t(_detail.age_us) + _policy.transit_bound_us < _policy.maximum_age_us;
	result.detail_available = detail_fresh;
	result.connected = !_revoked && result.age_upper_us < _policy.maximum_age_us && _base.state == _policy.healthy_state
			   && (_base.valid & _policy.required_base) == _policy.required_base
			   && (!_policy.required_detail || (detail_fresh && (_detail.valid & _policy.required_detail) == _policy.required_detail));

	if (detail_fresh && (_detail.valid & _policy.faults) && _detail.faults) { result.connected = false; }

	if (_base.valid & _policy.warning) {
		for (unsigned i = 0; i < 5; ++i) { if (_policy.warning_values[i] == _base.warning) { result.warning = i; } }
	}

	return result;
}

BatteryTelemetry battery_telemetry(const BatteryObservation &sample, const BatteryPolicy &policy,
				   const BatteryThresholds &thresholds)
{
	BatteryTelemetry result{};
	result.errors = sample.base.errors > UINT16_MAX ? UINT16_MAX : uint16_t(sample.base.errors);

	if (!policy.configured() || !thresholds.configured() || !sample.connected
	    || !policy.remaining || !(sample.base.valid & policy.remaining)) { return result; }

	result.connected = true;
	result.voltage_v = float(sample.base.voltage_mv) * 0.001f;

	if (sample.base.valid & policy.current) { result.current_a = float(sample.base.current_ma) * 0.001f; }

	result.remaining = float(sample.base.remaining_permille) * 0.001f;
	result.cells = policy.cell_count;
	result.warning = result.remaining < thresholds.emergency ? 3 : result.remaining < thresholds.critical ? 2
			 : result.remaining < thresholds.low ? 1 : 0;

	if (sample.warning > result.warning) { result.warning = sample.warning; }

	if (sample.detail_available) {
		if (sample.detail.valid & policy.temperature) { result.temperature_c = float(sample.detail.temperature_centic) * 0.01f; }

		if (sample.detail.valid & policy.cell_range) { result.cell_delta_v = float(sample.detail.max_cell_mv - sample.detail.min_cell_mv) * 0.001f; }

		if ((sample.detail.valid & policy.capacity) && sample.detail.capacity_mah <= UINT16_MAX) {
			result.capacity_mah = uint16_t(sample.detail.capacity_mah);
		}
	}

	return result;
}

}
}
