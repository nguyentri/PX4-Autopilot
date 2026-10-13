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

#pragma once

/*
 * CR8-1 output safety state machine for CR8-0 actuator commands.
 *
 * CR8-1 is the last core before the outputs, so it enforces output safety
 * itself instead of trusting the FMU stream:
 *
 *   Safe  --fresh disarmed command, valid session-->  Ready
 *   Ready --fresh armed command-->                    Armed
 *   Armed --lease expiry or session change-->         Fault (latched)
 *   Ready --lease expiry or session change-->         Safe
 *   Fault --fresh disarmed command, valid session-->  Ready
 *
 * Outputs are forwarded only in Ready (disarmed values) and Armed, and only
 * while the newest command is younger than the lease.  An armed command in
 * Safe or Fault is held safe and reported, so a CR8-0 that was armed across
 * a link loss must disarm before outputs return; no path leads from Fault
 * straight to armed output.
 */

#include "protocol.h"
#include <stdint.h>

class OutputLease
{
public:
	enum class State : uint8_t {
		Safe = 0,	// outputs off, no handshake yet
		Ready = 1,	// disarmed handshake done, disarmed values forwarded
		Armed = 2,	// armed values forwarded while the lease is fresh
		Fault = 3,	// latched: outputs off until a disarmed handshake
	};

	/* Record the CR8-0 link epoch seen after a read.  Zero means no valid
	 * session.  A change ends the current session and invalidates its lease.
	 */
	void observe_session(uint32_t epoch);

	/* Apply one validated CR8-0 command received at local time now. */
	void accept(const ActuatorCommand_t &cmd, uint64_t now);

	/* Expire the lease when no command arrived within FMU_LOSS_TIMEOUT_US. */
	void update(uint64_t now);

	/* Command for the output stage: every output off and disarmed unless the
	 * state is Ready or Armed with a fresh command.
	 */
	ActuatorCmdToM33_t output(uint64_t now) const;

	/* FAULT_FLAG_* bits for this core's output state.  With
	 * FAULT_FLAG_OUTPUT_SAFE_FAULT set, FAULT_FLAG_CR8_TIMEOUT and
	 * FAULT_FLAG_PEER_SESSION also name the latch reason.
	 */
	uint32_t fault_flags(uint64_t now) const;

	bool fresh(uint64_t now) const;
	State state() const { return _state; }

private:
	void end_session(uint32_t reason);

	State _state{State::Safe};
	ActuatorCommand_t _cmd{};	// newest command accepted in Ready or Armed
	uint64_t _last_cmd_us{0};	// local receive time of the newest valid command
	uint32_t _epoch{0};		// CR8-0 link epoch of the current session
	uint32_t _latched_reason{0};	// fault flags that latched Fault
	bool _arm_rejected{false};	// newest command was armed but held safe
};
