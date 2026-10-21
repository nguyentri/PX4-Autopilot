// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "protocol.hpp"

namespace rzv2h
{
namespace demo
{

static constexpr size_t GatewayHeaderSize = 96;
static constexpr size_t GatewayPacketSize = 384;
static constexpr uint32_t GatewayMagic = 0x31475a52;
enum class Advisory : uint8_t { Mode = 1, Trajectory = 2, Odometry = 3, Obstacle = 4 };
enum class GatewayError : uint8_t {
	None, Disabled, Session, Framing, Integrity, Replay, Clock, Age, Rate,
	Frame, Payload, Eligibility, ProgressExpired, Count
};

struct GatewayPolicy {
	uint32_t pose_frame{0}, obstacle_frame{0}, calibration{0};
	uint32_t intent_age_us{0}, observation_age_us{0}, progress_us{0}, uncertainty_us{0}, minimum_interval_us{0};
	float position_limit_m{0}, velocity_limit_m_s{0}, acceleration_limit_m_s2{0}, yaw_rate_limit_rad_s{0};
	float variance_limits[3] {}; // Position, orientation and velocity variance ceilings.
	uint16_t range_limit_cm{0};
	uint8_t minimum_odometry_quality{0};
	bool configured() const;
};

struct GatewayClockMapping {
	int64_t destination_minus_source_us{0};
	uint64_t source_from_us{0}, source_until_us{0}, qualification{0};
	uint32_t uncertainty_us{0};
};

struct GatewayEligibility {
	bool intent_authorized{false}; // CR8-owned handover policy, never sender data.
	bool position_valid{false}, velocity_valid{false}, acceleration_valid{false}, attitude_valid{false};
};

struct AdvisoryPacket { uint8_t bytes[GatewayPacketSize] {}; };
struct AdvisoryContext {
	uint64_t challenge{0}, generation{0}, source_us{0}, source_epoch{0};
	uint32_t sequence{0}, frame{0}, calibration{0}, uncertainty_us{0};
	uint32_t linux_boot[4] {};
};

size_t advisory_payload_size(Advisory kind);
AdvisoryPacket advisory_begin(Advisory kind, const AdvisoryContext &context);
void advisory_finish(AdvisoryPacket &packet);
float advisory_float(const uint8_t *source);
void advisory_write_float(uint8_t *destination, float value);

class GatewayValidator
{
public:
	explicit GatewayValidator(const GatewayPolicy &policy) : _policy(policy) {}
	bool begin(uint64_t challenge, const uint32_t (&linux_boot)[4], bool disarmed);
	bool admit(uint64_t echoed_challenge, const uint32_t (&linux_boot)[4], bool disarmed,
		   const GatewayClockMapping &mapping);
	void disconnect();
	void update(uint64_t now);
	GatewayError receive(const uint8_t *packet, size_t size, uint64_t now, const GatewayEligibility &eligibility);
	bool ready() const { return _ready; }
	bool progress_expired() const { return _progress_expired; }
	uint64_t intent_deadline() const { return _intent_deadline; }
	uint64_t accepted_source_us() const { return _accepted_source_us; }
	uint32_t accepted() const { return _accepted; }
	uint32_t rejects(GatewayError reason) const { return unsigned(reason) < unsigned(GatewayError::Count) ? _rejects[unsigned(reason)] : 0; }
	uint8_t mode(uint64_t now) const { return now < _mode_until ? _mode : 0; }

private:
	struct Stream {
		uint64_t generation{0}, source_epoch{0}, source_us{0}, received_us{0};
		uint32_t sequence{0};
		bool seen{false};
	};
	GatewayError reject(GatewayError reason);
	bool same_boot(const uint32_t (&boot)[4]) const;
	bool payload_valid(Advisory kind, const uint8_t *payload, const GatewayEligibility &eligibility) const;
	const GatewayPolicy _policy;
	GatewayClockMapping _clock{};
	Stream _streams[4] {};
	uint32_t _boot[4] {};
	uint32_t _rejects[unsigned(GatewayError::Count)] {};
	uint32_t _accepted{0};
	uint64_t _challenge{0}, _previous_challenge{0}, _now{0}, _intent_deadline{0}, _accepted_source_us{0}, _mode_until{0};
	uint8_t _mode{0};
	bool _ready{false}, _have_time{false}, _progress_expired{false};
};

}
}
