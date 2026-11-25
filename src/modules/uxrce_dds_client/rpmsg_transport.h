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

/**
 * @file rpmsg_transport.h
 *
 * Unframed XRCE-DDS custom transport over an RPMsg message device, used on
 * RZ/V2H CR8-0 to reach the CA55 CustomXRCEAgent (rpmsg-service-1).
 * One write() is one RPMsg packet and one read() returns one packet.
 */

#pragma once

#include <stddef.h>
#include <stdint.h>

#include <uxr/client/profile/transport/custom/custom_transport.h>

class RpmsgTransport
{
public:
	explicit RpmsgTransport(const char *device);
	~RpmsgTransport();

	RpmsgTransport(const RpmsgTransport &) = delete;
	RpmsgTransport &operator=(const RpmsgTransport &) = delete;

	/** Open the device and register the callbacks; false if the device cannot be opened. */
	bool init();
	void close();

	uxrCommunication *comm() { return &_transport.comm; }

	/** True while the driver holds at least one received packet (non-blocking). */
	bool rx_pending() const;
	const char *device() const { return _device; }
	void print_status() const;

private:
	static bool open_cb(uxrCustomTransport *transport);
	static bool close_cb(uxrCustomTransport *transport);
	static size_t write_cb(uxrCustomTransport *transport, const uint8_t *buf, size_t len, uint8_t *error);
	static size_t read_cb(uxrCustomTransport *transport, uint8_t *buf, size_t len, int timeout, uint8_t *error);

	uxrCustomTransport _transport{};
	char _device[32] {};
	int _fd{-1};
	bool _initialized{false};

	uint32_t _tx_errors{0};
	int _last_tx_errno{0};
	uint32_t _rx_errors{0};
	uint32_t _handshakes{0};
};
