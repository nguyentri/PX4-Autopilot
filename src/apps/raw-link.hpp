// Copyright (c) 2026 PX4 Development Team. All rights reserved.
// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "protocol.hpp"
#include <nuttx/ipc/rzv_ipc_raw.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>

namespace rzv2h
{
namespace demo
{

// Called only by a transport task. read() is nonblocking; raw write/RECOVER
// may wait for the peer and must never execute in the mixer or output worker.
class RawLink
{
public:
	~RawLink() { if (_fd >= 0) { close(_fd); } }
	bool open_link()
	{
		if (_fd < 0) { _fd = open("/dev/ipcc1", O_RDWR | O_NONBLOCK); }

		return _fd >= 0;
	}
	bool state(rzv_ipc_raw_stats_s &stats)
	{
		return _fd >= 0 && ioctl(_fd, RZV_IPC_RAWIOC_GET_STATS, reinterpret_cast<unsigned long>(&stats)) == 0;
	}
	bool recover() { return _fd >= 0 && ioctl(_fd, RZV_IPC_RAWIOC_RECOVER, 0) == 0; }
	bool receive(Frame &frame) { return _fd >= 0 && read(_fd, frame.bytes, EntrySize) == ssize_t(EntrySize); }
	bool send(const Frame &frame) { return _fd >= 0 && write(_fd, frame.bytes, EntrySize) == ssize_t(EntrySize); }

private:
	int _fd{-1};
};

}
}
