// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#pragma once

#include "output-configuration.hpp"

namespace rzv2h
{
namespace demo
{

class ActuatorLease
{
public:
	static constexpr uint64_t LeaseUs = ActuatorFreshnessUs;
	static constexpr uint64_t HeartbeatUs = 500000;
	static constexpr uint64_t TokenPeriodUs = 20000;
	enum class State : uint8_t { Safe, Ready, Armed, Fault };
	enum Fault : uint32_t { CommandLost = 1, HeartbeatLost = 2, SessionLost = 4, BackendFailed = 8, ClockFault = 16, CounterExhausted = 32 };

	struct Output {
		uint16_t values[4] {};
		uint64_t deadline_us{0};
		uint32_t epoch{0};
		uint32_t sequence{0};
		uint32_t generation{0};
		bool enabled{false};
	};

	ActuatorLease(const Hello &expected, uint16_t rate_hz, const OutputProfile *profiles = nullptr, size_t count = 0) :
		_expected(expected), _rate_hz(rate_hz), _profiles(profiles), _profile_count(count) {}
	void session(uint32_t epoch);
	bool receive_hello(const Frame &frame, uint64_t now);
	bool receive_heartbeat(const Frame &frame, uint64_t now);
	bool receive_command(const Frame &frame, uint64_t now);
	uint32_t issue_token(uint64_t now);
	void backend(bool safely_initialized, bool ready);
	void acknowledge(uint32_t epoch, uint32_t sequence, uint32_t generation, bool inhibited);
	void update(uint64_t now);
	void fault(uint32_t reason);
	Output output(uint64_t now) const;
	State state() const { return _state; }
	bool compatible() const { return _compatible; }
	bool ready() const { return _backend_ready; }
	bool rotation_requested() const { return _rotate; }
	uint32_t first_fault() const { return _first_fault; }
	uint32_t faults() const { return _faults; }
	uint32_t accepted_sequence() const { return _command_sequence; }
	uint32_t token() const { return _token; }
	uint32_t rejects() const { return _rejects; }

private:
	struct Token { uint32_t id{0}; uint64_t issued_us{0}; };
	bool advance(uint64_t now);
	void expire(uint64_t now);
	bool fresh_heartbeat(uint64_t now) const;
	const Token *fresh_token(uint32_t id, uint64_t now) const;
	bool reject() { ++_rejects; return false; }
	const Hello _expected;
	const uint16_t _rate_hz;
	const OutputProfile *const _profiles;
	const size_t _profile_count;
	const OutputProfile *_selected_profile{nullptr};
	Token _tokens[3] {};
	Command _command{};
	State _state{State::Safe};
	uint64_t _last_time{0};
	uint64_t _heartbeat_until{0};
	uint64_t _command_until{0};
	uint64_t _token_issued{0};
	uint32_t _epoch{0};
	uint32_t _hello_sequence{0};
	uint32_t _heartbeat_sequence{0};
	uint32_t _command_sequence{0};
	uint32_t _handshake_sequence{0};
	uint32_t _handshake_generation{0};
	uint32_t _token{0};
	uint32_t _faults{0};
	uint32_t _first_fault{0};
	uint32_t _rejects{0};
	uint8_t _token_slot{0};
	bool _compatible{false};
	bool _backend_initialized{false};
	bool _backend_ready{false};
	bool _handshake_acked{false};
	bool _clock_fault{false};
	bool _have_time{false};
	bool _rotate{false};
};

} // namespace demo
} // namespace rzv2h
