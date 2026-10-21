// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#include "gateway.hpp"
#include <math.h>
#include <string.h>
#include <float.h>

namespace rzv2h
{
namespace demo
{

namespace
{
uint32_t float_bits(float value) { uint32_t bits; memcpy(&bits, &value, sizeof(bits)); return bits; }
bool finite32(float value) { return (float_bits(value) & 0x7f800000u) != 0x7f800000u; }
bool nan32(float value) { return (float_bits(value) & 0x7fffffffu) > 0x7f800000u; }
static_assert(FLT_RADIX == 2 && FLT_MANT_DIG == 24 && FLT_MAX_EXP == 128, "wire requires IEEE binary32");
}

bool GatewayPolicy::configured() const
{
	for (float limit : variance_limits) { if (!finite32(limit) || limit <= 0) { return false; } }

	return pose_frame && obstacle_frame && pose_frame != obstacle_frame && calibration
	       && intent_age_us && intent_age_us <= progress_us && progress_us <= 100000
	       && observation_age_us && observation_age_us <= 250000 && uncertainty_us && uncertainty_us <= intent_age_us
	       && minimum_interval_us && minimum_interval_us < progress_us && range_limit_cm > 1 && range_limit_cm < 65534
	       && minimum_odometry_quality && minimum_odometry_quality <= 100
	       && finite32(position_limit_m) && position_limit_m > 0 && finite32(velocity_limit_m_s) && velocity_limit_m_s > 0
	       && finite32(acceleration_limit_m_s2) && acceleration_limit_m_s2 > 0
	       && finite32(yaw_rate_limit_rad_s) && yaw_rate_limit_rad_s > 0;
}

size_t advisory_payload_size(Advisory kind)
{
	switch (kind) {
	case Advisory::Mode: return 1;

	case Advisory::Trajectory: return 44;

	case Advisory::Odometry: return 84;

	case Advisory::Obstacle: return 152;
	}

	return 0;
}

AdvisoryPacket advisory_begin(Advisory kind, const AdvisoryContext &context)
{
	AdvisoryPacket packet{};
	auto *p = packet.bytes;
	write32(p, GatewayMagic); p[4] = 1; p[6] = uint8_t(kind); p[7] = GatewayHeaderSize;
	write16(p + 8, GatewayHeaderSize + advisory_payload_size(kind));
	write32(p + 12, context.sequence); write64(p + 16, context.challenge);
	write64(p + 32, context.generation); write64(p + 40, context.source_us);
	write32(p + 48, context.uncertainty_us); write32(p + 52, context.frame); write32(p + 56, context.calibration);
	write32(p + 60, 1); // Qualified Linux monotonic-source mapping is still required at the receiver.

	for (unsigned i = 0; i < 4; ++i) { write32(p + 64 + i * 4, context.linux_boot[i]); }

	write64(p + 80, context.source_epoch); write32(p + 88, 1);
	return packet;
}

void advisory_finish(AdvisoryPacket &packet)
{
	const size_t length = read16(packet.bytes + 8);

	if (length >= GatewayHeaderSize && length <= GatewayPacketSize) {
		write32(packet.bytes + 28, 0); write32(packet.bytes + 28, crc32(packet.bytes, length));
	}
}

float advisory_float(const uint8_t *source)
{
	static_assert(sizeof(float) == sizeof(uint32_t), "wire requires binary32");
	const uint32_t bits = read32(source);
	float result;
	memcpy(&result, &bits, sizeof(result));
	return result;
}

void advisory_write_float(uint8_t *destination, float value)
{
	uint32_t bits;
	memcpy(&bits, &value, sizeof(bits));
	write32(destination, bits);
}

GatewayError GatewayValidator::reject(GatewayError reason)
{
	uint32_t &counter = _rejects[unsigned(reason)];

	if (counter != UINT32_MAX) { ++counter; }

	return reason;
}

bool GatewayValidator::same_boot(const uint32_t (&boot)[4]) const
{
	for (unsigned i = 0; i < 4; ++i) { if (_boot[i] != boot[i]) { return false; } }

	return true;
}

void GatewayValidator::disconnect()
{
	_ready = false; _challenge = 0; _mode = 0; _intent_deadline = 0; _accepted_source_us = 0;
	_mode_until = 0;
	_progress_expired = false; _have_time = false; _clock = GatewayClockMapping{};

	for (auto &stream : _streams) { stream = Stream{}; }
}

bool GatewayValidator::begin(uint64_t challenge, const uint32_t (&linux_boot)[4], bool disarmed)
{
	disconnect();

	if (!_policy.configured() || !disarmed || !challenge || challenge <= _previous_challenge
	    || !(linux_boot[0] | linux_boot[1] | linux_boot[2] | linux_boot[3])) { return false; }

	_challenge = _previous_challenge = challenge;

	for (unsigned i = 0; i < 4; ++i) { _boot[i] = linux_boot[i]; }

	return true;
}

bool GatewayValidator::admit(uint64_t echoed_challenge, const uint32_t (&linux_boot)[4], bool disarmed,
			     const GatewayClockMapping &mapping)
{
	if (!_challenge || _ready || echoed_challenge != _challenge || !same_boot(linux_boot) || !disarmed
	    || !mapping.qualification || mapping.source_until_us < mapping.source_from_us
	    || mapping.source_until_us > uint64_t(INT64_MAX) || mapping.uncertainty_us > _policy.uncertainty_us) { return false; }

	_clock = mapping;
	_ready = true;
	return true;
}

void GatewayValidator::update(uint64_t now)
{
	if (_have_time && now < _now) { disconnect(); return; }

	_now = now; _have_time = true;

	if (_intent_deadline && now >= _intent_deadline) { _progress_expired = true; }
}

bool GatewayValidator::payload_valid(Advisory kind, const uint8_t *p, const GatewayEligibility &e) const
{
	if (kind == Advisory::Mode) { return p[0] == 1 || p[0] == 2 || p[0] == 4; }

	if (kind == Advisory::Trajectory) {
		if (!_mode || !e.attitude_valid || (_mode == 1 && !e.position_valid) || (_mode == 2 && !e.velocity_valid)) { return false; }

		bool any_primary = false;

		// PositionControl::_inputValid requires horizontal pairs for every
		// controlled state, including feed-forward velocity/acceleration.
		for (unsigned dimension = 0; dimension < 3; ++dimension) {
			if (finite32(advisory_float(p + dimension * 12)) != finite32(advisory_float(p + dimension * 12 + 4))) { return false; }
		}

		for (unsigned axis = 0; axis < 3; ++axis) {
			bool controlled = false;

			for (unsigned dimension = 0; dimension < 3; ++dimension) {
				const float value = advisory_float(p + (dimension * 3 + axis) * 4);

				if (nan32(value)) { continue; }

				const float limit = dimension == 0 ? _policy.position_limit_m :
						    dimension == 1 ? _policy.velocity_limit_m_s : _policy.acceleration_limit_m_s2;

				if (!finite32(value) || fabsf(value) > limit || (dimension == 0 && _mode != 1)
				    || (dimension == 1 && _mode == 4)) { return false; }

				if ((dimension == 0 && !e.position_valid)
				    || (dimension == 1 && (!e.velocity_valid || !e.acceleration_valid))) { return false; }

				controlled = true;

				if ((_mode == 1 && dimension == 0) || (_mode == 2 && dimension == 1) || (_mode == 4 && dimension == 2)) {
					any_primary = true;
				}
			}

			if (!controlled) { return false; }
		}

		const float yaw = advisory_float(p + 36), yaw_rate = advisory_float(p + 40);
		return any_primary && (nan32(yaw) || (finite32(yaw) && fabsf(yaw) <= 3.14159266f))
		       && (nan32(yaw_rate) || (finite32(yaw_rate) && fabsf(yaw_rate) <= _policy.yaw_rate_limit_rad_s));
	}

	if (kind == Advisory::Odometry) {
		float norm = 0;

		for (unsigned i = 0; i < 19; ++i) {
			const float value = advisory_float(p + 4 * i);

			if (!finite32(value)) { return false; }

			if (i < 3 && fabsf(value) > _policy.position_limit_m) { return false; }

			if (i >= 3 && i < 7) { norm += value * value; }

			if (i >= 7 && i < 10 && fabsf(value) > _policy.velocity_limit_m_s) { return false; }

			if (i >= 10 && (value < 0 || value > _policy.variance_limits[(i - 10) / 3])) { return false; }
		}

		if (!finite32(norm) || fabsf(norm - 1) > .01f || p[76] < _policy.minimum_odometry_quality || p[76] > 100) { return false; }

		for (unsigned i = 78; i < 84; ++i) { if (p[i]) { return false; } }

		return true;
	}

	if (kind == Advisory::Obstacle) {
		const uint16_t minimum = read16(p), maximum = read16(p + 2), increment = read16(p + 4);
		const int16_t offset = int16_t(read16(p + 6));

		if (!minimum || maximum <= minimum || maximum > _policy.range_limit_cm || !increment || increment > 45
		    || offset < -18000 || offset > 18000) { return false; }

		for (unsigned i = 0; i < 72; ++i) {
			const uint16_t distance = read16(p + 8 + i * 2);

			if (distance != UINT16_MAX && distance != 0 && (distance < minimum || distance > maximum + 1u)) { return false; }
		}

		return true;
	}

	return false;
}

GatewayError GatewayValidator::receive(const uint8_t *p, size_t size, uint64_t now,
				       const GatewayEligibility &eligibility)
{
	update(now);

	if (!_policy.configured()) { return reject(GatewayError::Disabled); }

	if (!_ready) { return reject(GatewayError::Session); }

	if (!p || size < GatewayHeaderSize || size > GatewayPacketSize || read32(p) != GatewayMagic
	    || p[4] != 1 || p[5] || p[7] != GatewayHeaderSize || read16(p + 8) != size || read16(p + 10)
	    || read32(p + 24) || read32(p + 92)) { return reject(GatewayError::Framing); }

	const Advisory kind = Advisory(p[6]);
	const size_t payload_size = advisory_payload_size(kind);

	if (!payload_size || size != GatewayHeaderSize + payload_size) { return reject(GatewayError::Framing); }

	if (read32(p + 28) != crc32(p, size)) { return reject(GatewayError::Integrity); }

	uint32_t boot[4] {};

	for (unsigned i = 0; i < 4; ++i) { boot[i] = read32(p + 64 + i * 4); }

	if (read64(p + 16) != _challenge || !same_boot(boot)) { return reject(GatewayError::Session); }

	const bool intent = kind == Advisory::Mode || kind == Advisory::Trajectory;

	if (intent && (!eligibility.intent_authorized || _progress_expired)) {
		return reject(_progress_expired ? GatewayError::ProgressExpired : GatewayError::Eligibility);
	}

	if (kind == Advisory::Trajectory && (!_mode || now >= _mode_until)) { return reject(GatewayError::Eligibility); }

	if (read32(p + 52) != (kind == Advisory::Obstacle ? _policy.obstacle_frame : _policy.pose_frame)
	    || read32(p + 56) != _policy.calibration) { return reject(GatewayError::Frame); }

	Stream &stream = _streams[unsigned(kind) - 1];
	const uint32_t sequence = read32(p + 12);
	const uint64_t generation = read64(p + 32), source_epoch = read64(p + 80), source_us = read64(p + 40);

	if (!sequence || sequence >= CounterLimit || !generation || generation == UINT64_MAX || !source_epoch
	    || (stream.seen && (sequence <= stream.sequence || generation <= stream.generation
				|| source_epoch != stream.source_epoch || source_us <= stream.source_us))) {
		return reject(GatewayError::Replay);
	}

	const uint64_t uncertainty = uint64_t(read32(p + 48)) + _clock.uncertainty_us;

	if (read32(p + 60) != 1 || read32(p + 88) != 1 || uncertainty > _policy.uncertainty_us
	    || source_us < _clock.source_from_us || source_us > _clock.source_until_us || source_us > uint64_t(INT64_MAX)) {
		return reject(GatewayError::Clock);
	}

	const int64_t source_signed = int64_t(source_us), offset = _clock.destination_minus_source_us;

	if ((offset > 0 && source_signed > INT64_MAX - offset) || (offset < 0 && source_signed < INT64_MIN - offset)) {
		return reject(GatewayError::Clock);
	}

	const int64_t mapped = source_signed + offset;

	if (mapped < 0 || uint64_t(mapped) < uncertainty) { return reject(GatewayError::Clock); }

	const uint64_t earliest = uint64_t(mapped) - uncertainty;

	if (earliest > now) { return reject(GatewayError::Age); }

	const uint64_t age = now - earliest;

	if (age > (intent ? _policy.intent_age_us : _policy.observation_age_us)) { return reject(GatewayError::Age); }

	if (stream.seen && now - stream.received_us < _policy.minimum_interval_us) { return reject(GatewayError::Rate); }

	if (!payload_valid(kind, p + GatewayHeaderSize, eligibility)) { return reject(GatewayError::Payload); }

	if (kind == Advisory::Trajectory && earliest > UINT64_MAX - _policy.progress_us) { return reject(GatewayError::Clock); }

	stream.sequence = sequence; stream.generation = generation; stream.source_epoch = source_epoch;
	stream.source_us = source_us;
	stream.received_us = now; stream.seen = true;

	if (kind == Advisory::Mode) { _mode = p[GatewayHeaderSize]; _mode_until = earliest + _policy.intent_age_us; }

	if (kind == Advisory::Trajectory) { _intent_deadline = earliest + _policy.progress_us; }

	_accepted_source_us = uint64_t(mapped);

	if (_accepted != UINT32_MAX) { ++_accepted; }

	return GatewayError::None;
}

}
}
