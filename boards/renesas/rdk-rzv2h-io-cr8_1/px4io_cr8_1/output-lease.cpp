/****************************************************************************
 *
 *   Copyright (c) 2026 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *    used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 * FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 * BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
 * OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
 * AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 * ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

#include "output-lease.h"

bool OutputLease::fresh(uint64_t now) const
{
	/* Local receive time, because the cores do not share a timebase. */
	return _last_cmd_us != 0 && now - _last_cmd_us < FMU_LOSS_TIMEOUT_US;
}

bool OutputLease::peer_alive(uint64_t now) const
{
	return _last_heartbeat_us != 0 && now - _last_heartbeat_us < HEARTBEAT_TIMEOUT_US;
}

void OutputLease::end_session(uint32_t reason)
{
	if (_state == State::Armed || _state == State::Fault) {
		_state = State::Fault;
		_latched_reason |= reason;

	} else {
		_state = State::Safe;
	}
}

void OutputLease::observe_session(uint32_t epoch)
{
	if (epoch == _epoch) {
		return;
	}

	/* A command from the new session never continues the old lease. */
	end_session(FAULT_FLAG_PEER_SESSION);
	_last_cmd_us = 0;
	_last_heartbeat_us = 0;
	_epoch = epoch;
}

void OutputLease::update(uint64_t now)
{
	if (_state != State::Ready && _state != State::Armed) {
		return;
	}

	uint32_t reason = 0;

	if (!fresh(now)) {
		reason |= FAULT_FLAG_CR8_TIMEOUT;
	}

	if (!peer_alive(now)) {
		reason |= FAULT_FLAG_FMU_HEARTBEAT;
	}

	if (reason != 0) {
		end_session(reason);
	}
}

void OutputLease::heartbeat(uint64_t now)
{
	/* Only a heartbeat read in a valid session proves that session alive. */
	if (_epoch != 0) {
		_last_heartbeat_us = now;
	}
}

void OutputLease::accept(const ActuatorCommand_t &cmd, uint64_t now)
{
	/* A gap longer than the lease ends the session even when the loop did
	 * not run update() in between.
	 */
	update(now);

	if (_epoch == 0) {
		_arm_rejected = cmd.armed != 0;
		return;
	}

	_last_cmd_us = now;

	if (!peer_alive(now)) {
		/* Fresh commands without the CR8-0 heartbeat never leave Safe or
		 * Fault; update() already ended a Ready or Armed session.
		 */
		_arm_rejected = cmd.armed != 0;

	} else if (cmd.armed == 0) {
		/* Disarmed handshake in the current session: the only way out of
		 * Safe and Fault.
		 */
		_state = State::Ready;
		_latched_reason = 0;
		_arm_rejected = false;
		_cmd = cmd;

	} else if (_state == State::Ready || _state == State::Armed) {
		_state = State::Armed;
		_arm_rejected = false;
		_cmd = cmd;

	} else {
		_arm_rejected = true;
	}
}

ActuatorCmdToM33_t OutputLease::output(uint64_t now) const
{
	/* Default: every output off, disarmed, PWM mode. */
	ActuatorCmdToM33_t out{};

	/* The FMU mixer already selected armed, disarmed or failsafe values, so a
	 * fresh accepted command is forwarded channel for channel, as PX4IO does
	 * while the FMU is alive.
	 */
	if ((_state == State::Ready || _state == State::Armed) && fresh(now) && peer_alive(now)) {
		for (unsigned i = 0; i < IPC_MAX_ACTUATORS; i++) {
			out.commands[i] = _cmd.outputs[i];
		}

		out.armed = _state == State::Armed ? _cmd.armed : 0;
		out.safety_off = _cmd.safety_off;
	}

	return out;
}

uint32_t OutputLease::fault_flags(uint64_t now) const
{
	uint32_t flags = 0;

	if (!fresh(now)) {
		flags |= FAULT_FLAG_CR8_TIMEOUT;
	}

	if (!peer_alive(now)) {
		flags |= FAULT_FLAG_FMU_HEARTBEAT;
	}

	if (_state == State::Fault) {
		flags |= FAULT_FLAG_OUTPUT_SAFE_FAULT | _latched_reason;
	}

	if (_arm_rejected) {
		flags |= FAULT_FLAG_ARM_REJECTED;
	}

	return flags;
}
