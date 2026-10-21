// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause

#include "actuator-lease.hpp"

namespace rzv2h
{
namespace demo
{

void ActuatorLease::fault(uint32_t reason)
{
	if (!_first_fault) {
		_first_fault = reason;
	}

	_faults |= reason;
	_state = State::Fault;
	_backend_ready = false;
	_handshake_acked = false;
	_command_until = 0;
}

void ActuatorLease::session(uint32_t epoch)
{
	if (epoch == _epoch) {
		return;
	}

	if (_state == State::Armed || _state == State::Fault) {
		fault(SessionLost);
	}

	_epoch = epoch;
	_compatible = false;
	_selected_profile = nullptr;
	_backend_initialized = false;
	_backend_ready = false;
	_hello_sequence = 0;
	_heartbeat_sequence = 0;
	_command_sequence = 0;
	_handshake_sequence = 0;
	_handshake_generation = 0;
	_handshake_acked = false;
	_heartbeat_until = 0;
	_command_until = 0;
	_token_issued = 0;
	_token = 0;
	_token_slot = 0;
	_clock_fault = false;
	_have_time = false;
	_rotate = false;
	_command = Command{};

	for (auto &entry : _tokens) {
		entry = Token{};
	}

	if (_state != State::Fault) {
		_state = State::Safe;
	}
}

bool ActuatorLease::fresh_heartbeat(uint64_t now) const
{
	return _heartbeat_until && now < _heartbeat_until;
}

const ActuatorLease::Token *ActuatorLease::fresh_token(uint32_t id, uint64_t now) const
{
	for (const auto &entry : _tokens) {
		if (entry.id != 0 && entry.id == id && now >= entry.issued_us && now - entry.issued_us < LeaseUs) {
			return &entry;
		}
	}

	return nullptr;
}

bool ActuatorLease::advance(uint64_t now)
{
	if (_clock_fault) {
		return false;
	}

	if ((_have_time && now < _last_time) || now > UINT64_MAX - HeartbeatUs) {
		_clock_fault = true;
		fault(ClockFault);
		return false;
	}

	_last_time = now;
	_have_time = true;
	expire(now);
	return _epoch != 0 && !_rotate;
}

void ActuatorLease::update(uint64_t now)
{
	advance(now);
}

void ActuatorLease::expire(uint64_t now)
{
	if (_state != State::Ready && _state != State::Armed) {
		return;
	}

	uint32_t reason = 0;

	if (!_command_until || now >= _command_until) {
		reason |= CommandLost;
	}

	if (!fresh_heartbeat(now)) {
		reason |= HeartbeatLost;
	}

	if (reason) {
		if (_state == State::Armed) {
			fault(reason);

		} else {
			_state = State::Safe;
			_backend_ready = false;
			_command_until = 0;
		}
	}
}

bool ActuatorLease::receive_hello(const Frame &frame, uint64_t now)
{
	if (!advance(now) || validate(frame.bytes, EntrySize, 0, _epoch) != Error::None
	    || Type(frame.bytes[6]) != Type::Hello) { return reject(); }

	const uint32_t sequence = read32(frame.bytes + 12);
	const Hello incoming = hello(frame);
	Hello expected = _expected;
	const OutputProfile *selected = nullptr;

	if (_profiles) {
		selected = find_output_profile(_profiles, _profile_count, incoming.output_config);

		if (!selected || selected->configuration.rate_hz != _rate_hz) { return reject(); }

		expected.output_config = selected->identity;
	}

	if (sequence <= _hello_sequence || !expected.matches(incoming) || _rate_hz < 50 || _rate_hz > 500) {
		return reject();
	}

	if (_selected_profile && _selected_profile != selected) {
		_rotate = true;
		fault(SessionLost);
		return reject();
	}

	_hello_sequence = sequence;
	_compatible = true;
	_selected_profile = selected;
	return true;
}

void ActuatorLease::backend(bool safely_initialized, bool ready)
{
	const bool was_initialized = _backend_initialized;
	_backend_initialized = _compatible && safely_initialized;
	_backend_ready = _backend_initialized && ready && _handshake_acked
			 && (_state == State::Ready || _state == State::Armed);

	if (was_initialized && !_backend_initialized) {
		fault(BackendFailed);
	}
}

void ActuatorLease::acknowledge(uint32_t epoch, uint32_t sequence, uint32_t generation, bool inhibited)
{
	if (epoch == _epoch && epoch && _handshake_generation && inhibited
	    && sequence >= _handshake_sequence && sequence < CounterLimit
	    && generation >= _handshake_generation && generation < CounterLimit) {
		_handshake_acked = true;
	}
}

bool ActuatorLease::receive_heartbeat(const Frame &frame, uint64_t now)
{
	// Expire previous authority before this heartbeat is allowed to refresh liveness.
	if (!advance(now) || !_compatible || validate(frame.bytes, EntrySize, 0, _epoch) != Error::None
	    || Type(frame.bytes[6]) != Type::Heartbeat) { return reject(); }

	const uint32_t sequence = read32(frame.bytes + 12);

	if (sequence <= _heartbeat_sequence) {
		return reject();
	}

	_heartbeat_sequence = sequence;
	_heartbeat_until = now + HeartbeatUs;
	return true;
}

uint32_t ActuatorLease::issue_token(uint64_t now)
{
	if (!advance(now) || !_compatible) {
		return 0;
	}

	if (_token && now - _token_issued < TokenPeriodUs) {
		return _token;
	}

	if (_token + 1 >= CounterLimit) {
		_rotate = true;
		fault(CounterExhausted);
		return 0;
	}

	++_token;
	_token_issued = now;
	_tokens[_token_slot].id = _token;
	_tokens[_token_slot].issued_us = now;
	_token_slot = (_token_slot + 1) % 3;
	return _token;
}

bool ActuatorLease::receive_command(const Frame &frame, uint64_t now)
{
	if (!advance(now) || !_compatible || !_backend_initialized || !fresh_heartbeat(now)
	    || validate(frame.bytes, EntrySize, 0, _epoch) != Error::None || Type(frame.bytes[6]) != Type::Command) {
		return reject();
	}

	const Command next = command(frame);

	if (_selected_profile && !_selected_profile->configuration.accepts(next)) { return reject(); }

	const uint32_t sequence = read32(frame.bytes + 12);
	const Token *token = fresh_token(next.token, now);

	if (!token || sequence <= _command_sequence || next.generation <= _command.generation
	    || next.generation >= CounterLimit || next.state_generation >= CounterLimit
	    || next.state_generation < _command.state_generation || next.rate_hz != _rate_hz
	    || (_command_sequence && next.state_generation == _command.state_generation && next.state != _command.state)) {
		return reject();
	}

	const bool armed = next.state & demo::Armed;
	bool stopped = !armed && (next.state & StopMotors);

	for (uint16_t pulse : next.outputs) {
		stopped = stopped && pulse == 0;
	}

	if ((_state == State::Safe || _state == State::Fault) && !stopped) {
		return reject();
	}

	if (armed && !_backend_ready) {
		return reject();
	}

	const bool inhibited_command = next.state & (StopMotors | Lockdown | ManualLockdown | Termination);

	if (_state == State::Safe || _state == State::Fault || (!armed && _state == State::Armed)
	    || (armed && inhibited_command)) {
		_handshake_sequence = sequence;
		_handshake_generation = next.generation;
		_handshake_acked = false;
		_backend_ready = false;
	}

	if (stopped) {
		_state = State::Ready;
		_faults = 0;

	} else {
		_state = armed ? State::Armed : State::Ready;
	}

	_command = next;
	_command_sequence = sequence;
	const uint64_t token_deadline = token->issued_us + LeaseUs;
	_command_until = token_deadline < now + LeaseUs ? token_deadline : now + LeaseUs;
	return true;
}

ActuatorLease::Output ActuatorLease::output(uint64_t now) const
{
	Output result{};
	result.epoch = _epoch;
	result.sequence = _command_sequence;
	result.generation = _command.generation;
	result.deadline_us = _command_until < _heartbeat_until ? _command_until : _heartbeat_until;

	if (!_backend_ready || _state != State::Armed || _clock_fault || now < _last_time
	    || now >= result.deadline_us || !(_command.state & SafetyOff)
	    || (_command.state & (StopMotors | Lockdown | ManualLockdown | Termination))) { return result; }

	result.enabled = true;

	for (unsigned i = 0; i < 4; ++i) {
		result.values[i] = _command.outputs[i];
	}

	return result;
}

} // namespace demo
} // namespace rzv2h
