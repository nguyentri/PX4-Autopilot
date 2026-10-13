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

#include "sharedmem_transport.h"

#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <drivers/drv_hrt.h>
#include <nuttx/ipc/rzv_ipc_raw.h>

/* The IPCC ring entry payload is 64 bytes (RZV_IPC_*_RING_ENTRY_SZ); every
 * protocol message fits in one entry. read() returns one entry and write()
 * takes exactly one entry.
 */
static constexpr size_t IPC_ENTRY_SIZE = 64;

SharedMemTransport::SharedMemTransport(const char *dev_path) :
	_dev_path(dev_path)
{
}

SharedMemTransport::~SharedMemTransport()
{
	if (_fd >= 0) {
		close(_fd);
		_fd = -1;
	}
}

bool SharedMemTransport::init(bool is_master)
{
	(void)is_master;

	if (_fd < 0) {
		_fd = open(_dev_path, O_RDWR | O_NONBLOCK);
	}

	return _fd >= 0;
}

uint32_t SharedMemTransport::calculate_crc32(const uint8_t *data, size_t len)
{
	uint32_t crc = 0xFFFFFFFF;

	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];

		for (int j = 0; j < 8; j++) {
			if (crc & 1) {
				crc = (crc >> 1) ^ 0xEDB88320;

			} else {
				crc >>= 1;
			}
		}
	}

	return ~crc;
}

bool SharedMemTransport::send_framed(MessageType_e type, uint16_t &seq,
				     void *msg, size_t len)
{
	if (_fd < 0 || len > IPC_ENTRY_SIZE) {
		return false;
	}

	MessageHeader_t *hdr = reinterpret_cast<MessageHeader_t *>(msg);
	hdr->magic    = IPC_MAGIC;
	hdr->version  = IPC_PROTOCOL_VERSION;
	hdr->msg_type = static_cast<uint8_t>(type);
	hdr->sequence = seq++;
	hdr->timestamp_us = (uint32_t)hrt_absolute_time();
	hdr->crc32    = 0;
	hdr->crc32    = calculate_crc32(reinterpret_cast<const uint8_t *>(msg), len);

	/* The raw IPC driver moves exactly one ring entry per write() and
	 * rejects any other length with EMSGSIZE, so the frame is zero-padded to
	 * a full entry.  Receivers check the CRC over the message length only.
	 */
	uint8_t entry[IPC_ENTRY_SIZE] {};
	memcpy(entry, msg, len);

	ssize_t n = write(_fd, entry, sizeof(entry));
	return n == static_cast<ssize_t>(sizeof(entry));
}

bool SharedMemTransport::receive_framed(MessageType_e want, void *msg, size_t len)
{
	if (_fd < 0 || len > IPC_ENTRY_SIZE) {
		return false;
	}

	for (size_t i = 0; i < _pending_count; i++) {
		const auto *header = reinterpret_cast<const MessageHeader_t *>(_pending[i]);

		if (header->msg_type == static_cast<uint8_t>(want)) {
			memcpy(msg, _pending[i], len);

			if (i + 1 < _pending_count) {
				memmove(_pending[i], _pending[i + 1], (_pending_count - i - 1) * IPC_ENTRY_SIZE);
			}

			_pending_count--;
			return true;
		}
	}

	/* Stop consuming when storage is full.  The other receiver drains its
	 * retained messages before this path reads more entries from the fd.
	 */
	for (size_t scanned = 0; scanned < PENDING_CAPACITY && _pending_count < PENDING_CAPACITY; scanned++) {
		uint8_t frame[IPC_ENTRY_SIZE] {};
		const ReadResult result = read_frame(frame);

		if (result == ReadResult::Empty) {
			return false;
		}

		if (result == ReadResult::Invalid) {
			continue;
		}

		const uint8_t type = reinterpret_cast<const MessageHeader_t *>(frame)->msg_type;

		if (type == static_cast<uint8_t>(want)) {
			memcpy(msg, frame, len);
			return true;
		}

		/* Only the ESC-leg replies have a second reader.  Any other type has
		 * no consumer here and would otherwise occupy retained storage
		 * forever.
		 */
		if (type == MSG_TYPE_PWM_FEEDBACK || type == MSG_TYPE_FAULT_STATUS) {
			memcpy(_pending[_pending_count++], frame, IPC_ENTRY_SIZE);
		}
	}

	return false;
}

SharedMemTransport::ReadResult SharedMemTransport::read_frame(uint8_t (&frame)[64])
{
	ssize_t n = read(_fd, frame, IPC_ENTRY_SIZE);

	if (n <= 0) {
		return ReadResult::Empty;
	}

	if (n < static_cast<ssize_t>(sizeof(MessageHeader_t))) {
		return ReadResult::Invalid;
	}

	auto *hdr = reinterpret_cast<MessageHeader_t *>(frame);
	size_t frame_size;

	switch (hdr->msg_type) {
	case MSG_TYPE_HEARTBEAT:
		frame_size = sizeof(Heartbeat_t);
		break;

	case MSG_TYPE_ACTUATOR_CMD:
		frame_size = sizeof(ActuatorCommand_t);
		break;

	case MSG_TYPE_PWM_FEEDBACK:
		frame_size = sizeof(PWMFeedback_t);
		break;

	case MSG_TYPE_FAULT_STATUS:
		frame_size = sizeof(FaultStatus_t);
		break;

	default:
		return ReadResult::Invalid;
	}

	if (hdr->magic != IPC_MAGIC || hdr->version != IPC_PROTOCOL_VERSION ||
	    (n != static_cast<ssize_t>(frame_size) && n != static_cast<ssize_t>(IPC_ENTRY_SIZE))) {
		return ReadResult::Invalid;
	}

	uint32_t received_crc = hdr->crc32;
	hdr->crc32 = 0;

	if (calculate_crc32(frame, frame_size) != received_crc) {
		return ReadResult::Invalid;
	}

	hdr->crc32 = received_crc;
	return ReadResult::Valid;
}

bool SharedMemTransport::receive_fmu_message(FmuMessage &msg)
{
	if (_fd < 0) {
		return false;
	}

	uint8_t frame[IPC_ENTRY_SIZE] {};

	/* The FMU leg has a single reader, so nothing is retained: every frame is
	 * delivered in order or dropped.
	 */
	for (size_t scanned = 0; scanned < PENDING_CAPACITY; scanned++) {
		const ReadResult result = read_frame(frame);

		if (result == ReadResult::Empty) {
			return false;
		}

		if (result == ReadResult::Invalid) {
			continue;
		}

		msg.type = reinterpret_cast<const MessageHeader_t *>(frame)->msg_type;

		if (msg.type == MSG_TYPE_ACTUATOR_CMD) {
			memcpy(&msg.command, frame, sizeof(msg.command));
			return true;
		}

		if (msg.type == MSG_TYPE_HEARTBEAT) {
			memcpy(&msg.heartbeat, frame, sizeof(msg.heartbeat));
			return true;
		}
	}

	return false;
}

bool SharedMemTransport::wait_readable(int timeout_ms) const
{
	if (_fd < 0) {
		return false;
	}

	struct pollfd fds {};

	fds.fd = _fd;

	fds.events = POLLIN;

	return poll(&fds, 1, timeout_ms) > 0 && (fds.revents & POLLIN) != 0;
}

bool SharedMemTransport::send_heartbeat(const Heartbeat_t &heartbeat)
{
	Heartbeat_t msg = heartbeat;
	return send_framed(MSG_TYPE_HEARTBEAT, _tx_seq_heartbeat, &msg, sizeof(msg));
}

bool SharedMemTransport::send_fault_status(const FaultStatus_t &status)
{
	FaultStatus_t msg = status;
	return send_framed(MSG_TYPE_FAULT_STATUS, _tx_seq_fault, &msg, sizeof(msg));
}

bool SharedMemTransport::send_actuator_cmd(const ActuatorCmdToM33_t &cmd)
{
	ActuatorCmdToM33_t msg = cmd;
	return send_framed(MSG_TYPE_ACTUATOR_CMD, _tx_seq_actuator, &msg, sizeof(msg));
}

bool SharedMemTransport::receive_pwm_feedback(PWMFeedback_t &feedback)
{
	return receive_framed(MSG_TYPE_PWM_FEEDBACK, &feedback, sizeof(feedback));
}

bool SharedMemTransport::receive_fault_status(FaultStatus_t &status)
{
	return receive_framed(MSG_TYPE_FAULT_STATUS, &status, sizeof(status));
}

bool SharedMemTransport::link_epoch(uint32_t &epoch) const
{
	struct rzv_ipc_raw_stats_s stats {};

	if (_fd < 0 || ioctl(_fd, RZV_IPC_RAWIOC_GET_STATS, reinterpret_cast<unsigned long>(&stats)) < 0) {
		return false;
	}

	epoch = stats.epoch;
	return true;
}
