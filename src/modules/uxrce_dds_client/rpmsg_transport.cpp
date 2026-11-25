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
 * @file rpmsg_transport.cpp
 *
 * XRCE-DDS custom transport over an RPMsg message device.
 */

#include "rpmsg_transport.h"

#include <px4_platform_common/log.h>
#include <px4_platform_common/posix.h>

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <string.h>
#include <unistd.h>

namespace
{
/* Sent by the CA55 agent (NUL included) right after it binds
 * rpmsg-service-1.  It tells this endpoint the agent's address and is not
 * an XRCE message, so it is consumed here.
 */
constexpr char kAgentHandshake[] = "UXRCE_HANDSHAKE_FROM_CA55";
}

/* NuttX RZ/V driver: received packets discarded because its queue was full */
extern "C" uint32_t rzv_rpmsg_uxrce_rx_dropped(void);

RpmsgTransport::RpmsgTransport(const char *device)
{
	if (device) {
		strncpy(_device, device, sizeof(_device) - 1);
	}
}

RpmsgTransport::~RpmsgTransport()
{
	close();
}

bool RpmsgTransport::init()
{
	uxr_set_custom_transport_callbacks(&_transport, false, open_cb, close_cb, write_cb, read_cb);
	_initialized = uxr_init_custom_transport(&_transport, this);
	return _initialized;
}

void RpmsgTransport::close()
{
	if (_initialized) {
		uxr_close_custom_transport(&_transport);
		_initialized = false;
	}
}

void RpmsgTransport::print_status() const
{
	PX4_INFO("RPMsg device:        %s", _device);
	PX4_INFO("Agent handshakes:    %" PRIu32, _handshakes);
	PX4_INFO("TX errors:           %" PRIu32 " (last errno %d)", _tx_errors, _last_tx_errno);
	PX4_INFO("RX errors:           %" PRIu32, _rx_errors);
	PX4_INFO("RX dropped (queue):  %" PRIu32, rzv_rpmsg_uxrce_rx_dropped());
}

bool RpmsgTransport::rx_pending() const
{
	if (_fd < 0) {
		return false;
	}

	pollfd fds{};
	fds.fd = _fd;
	fds.events = POLLIN;

	return ::poll(&fds, 1, 0) > 0 && (fds.revents & POLLIN) != 0;
}

bool RpmsgTransport::open_cb(uxrCustomTransport *transport)
{
	RpmsgTransport *self = static_cast<RpmsgTransport *>(transport->args);

	self->_fd = ::open(self->_device, O_RDWR | O_NONBLOCK);

	if (self->_fd < 0) {
		PX4_ERR("open %s failed (%i)", self->_device, errno);
		return false;
	}

	return true;
}

bool RpmsgTransport::close_cb(uxrCustomTransport *transport)
{
	RpmsgTransport *self = static_cast<RpmsgTransport *>(transport->args);

	if (self->_fd >= 0) {
		::close(self->_fd);
		self->_fd = -1;
	}

	return true;
}

size_t RpmsgTransport::write_cb(uxrCustomTransport *transport, const uint8_t *buf, size_t len, uint8_t *error)
{
	RpmsgTransport *self = static_cast<RpmsgTransport *>(transport->args);
	ssize_t ret = ::write(self->_fd, buf, len);

	if (ret != static_cast<ssize_t>(len)) {
		/* ENOTCONN until the agent's handshake arrives, EAGAIN on a full
		 * vring, EMSGSIZE above the 496-byte RPMsg payload.  No retry here:
		 * sleeping would stall the client loop, and XRCE retransmits
		 * reliable data on its own.
		 */
		self->_tx_errors++;
		self->_last_tx_errno = ret < 0 ? errno : EIO;
		*error = 1;
		return 0;
	}

	*error = 0;
	return len;
}

size_t RpmsgTransport::read_cb(uxrCustomTransport *transport, uint8_t *buf, size_t len, int timeout, uint8_t *error)
{
	RpmsgTransport *self = static_cast<RpmsgTransport *>(transport->args);
	pollfd fds{};

	*error = 0;
	fds.fd = self->_fd;
	fds.events = POLLIN;

	int ret = ::poll(&fds, 1, timeout < 0 ? -1 : timeout);

	if (ret <= 0) {
		if (ret < 0 && errno != EINTR) {
			self->_rx_errors++;
			*error = 1;
		}

		return 0;
	}

	ssize_t nread = ::read(self->_fd, buf, len);

	if (nread <= 0) {
		if (nread < 0 && errno != EAGAIN) {
			self->_rx_errors++;
			*error = 1;
		}

		return 0;
	}

	if (static_cast<size_t>(nread) == sizeof(kAgentHandshake)
	    && memcmp(buf, kAgentHandshake, sizeof(kAgentHandshake)) == 0) {
		self->_handshakes++;
		return 0;
	}

	return static_cast<size_t>(nread);
}
