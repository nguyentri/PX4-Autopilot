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
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 ****************************************************************************/

#include <px4_platform_common/px4_config.h>

#include <nuttx/fs/ioctl.h>

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "rzv_serial.h"

static int serial_channel_from_path(const char *path)
{
	static const char prefix[] = "/dev/ttyS";
	const size_t prefix_length = sizeof(prefix) - 1;

	if (strncmp(path, prefix, prefix_length) != 0
	    || path[prefix_length] < '0' || path[prefix_length] > '9'
	    || path[prefix_length + 1] != '\0') {
		return -1;
	}

	return path[prefix_length] - '0';
}

static int print_serial_status(const char *path)
{
	struct serial_icounter_struct counters;
	int channel;
	int ret;

	channel = serial_channel_from_path(path);

	if (channel < 0) {
		fprintf(stderr, "%s: expected /dev/ttyS0 through /dev/ttyS9\n", path);
		return -1;
	}

	memset(&counters, 0, sizeof(counters));
	ret = rzv_serial_get_icount((unsigned int)channel, &counters);

	if (ret < 0) {
		fprintf(stderr, "%s: counter snapshot failed: %s\n", path, strerror(-ret));
		return -1;
	}

	printf("%s: rx=%" PRIu32 " tx=%" PRIu32
	       " frame=%" PRIu32 " overrun=%" PRIu32
	       " parity=%" PRIu32 " buf_overrun=%" PRIu32 "\n",
	       path, (uint32_t)counters.rx, (uint32_t)counters.tx,
	       (uint32_t)counters.frame, (uint32_t)counters.overrun,
	       (uint32_t)counters.parity, (uint32_t)counters.buf_overrun);
	return 0;
}

int serial_status_main(int argc, char *argv[])
{
	int failures = 0;

	if (argc < 2) {
		fprintf(stderr, "Usage: serial_status <device> [device ...]\n");
		fprintf(stderr, "Counters are boot-lifetime modulo 2^32 snapshots.\n");
		return 1;
	}

	for (int i = 1; i < argc; i++) {
		if (print_serial_status(argv[i]) < 0) {
			failures++;
		}
	}

	return failures == 0 ? 0 : 1;
}
