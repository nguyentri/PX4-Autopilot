/****************************************************************************
 *
 *   Copyright (C) 2026 PX4 Development Team. All rights reserved.
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
 * @file dshot_telemetry.c
 *
 * BDShot RLL/GCR/eRPM decode. Hardware-independent; see dshot_telemetry.h.
 *
 * Algorithm and constants mirror the upstream reference
 * (platforms/nuttx/src/px4/nxp/imxrt/dshot/dshot.c `up_bdshot_erpm`) so the
 * returned units match the shared src/drivers/dshot/DShot.cpp consumer, which
 * computes esc_rpm = (erpm * 100) / (pole_count / 2).
 */

#include "dshot_telemetry.h"

#define DSHOT_GCR_INVALID 0xffu

/* GCR quintet -> nibble map applied after the RLL de-interleave. Invalid
 * alphabet symbols must be rejected before checksum evaluation. */
static const uint8_t g_gcr_decode[32] = {
	DSHOT_GCR_INVALID, DSHOT_GCR_INVALID, DSHOT_GCR_INVALID, DSHOT_GCR_INVALID,
	DSHOT_GCR_INVALID, DSHOT_GCR_INVALID, DSHOT_GCR_INVALID, DSHOT_GCR_INVALID,
	DSHOT_GCR_INVALID, 0x9, 0xA, 0xB, DSHOT_GCR_INVALID, 0xD, 0xE, 0xF,
	DSHOT_GCR_INVALID, DSHOT_GCR_INVALID, 0x2, 0x3,
	DSHOT_GCR_INVALID, 0x5, 0x6, 0x7,
	DSHOT_GCR_INVALID, 0x0, 0x8, 0x1,
	DSHOT_GCR_INVALID, 0x4, 0xC, DSHOT_GCR_INVALID
};

int dshot_telem_decode_erpm(uint32_t raw_response)
{
	/* The line idles high and the response is inverted DShot; take the
	 * complement of the 20 sampled bits. */
	uint32_t value = ~raw_response & 0xFFFFFu;

	/* Framing: the least-significant received bit must be 1. */
	if ((value & 0x1u) == 0u) {
		return -1;
	}

	/* RLL de-interleave. */
	value ^= (value >> 1);

	/* GCR: four quintets -> four nibbles (LSB quintet -> low nibble). */
	uint8_t symbols[4] = {
		g_gcr_decode[value & 0x1Fu],
		g_gcr_decode[(value >> 5) & 0x1Fu],
		g_gcr_decode[(value >> 10) & 0x1Fu],
		g_gcr_decode[(value >> 15) & 0x1Fu]
	};

	for (unsigned i = 0; i < 4; i++) {
		if (symbols[i] == DSHOT_GCR_INVALID) {
			return -1;
		}
	}

	uint32_t data = symbols[0] | ((uint32_t)symbols[1] << 4) |
			((uint32_t)symbols[2] << 8) | ((uint32_t)symbols[3] << 12);

	/* Bidirectional checksum: XOR of the four nibbles must be 0xF. */
	uint32_t csum = data ^ (data >> 8);
	csum ^= (csum >> 4);

	if ((csum & 0xFu) != 0xFu) {
		return -1;
	}

	/* Drop the checksum nibble -> 12-bit telemetry payload. */
	data = (data >> 4) & 0xFFFu;

	if (data == 0xFFFu) {
		return 0;  /* Motor stopped. */
	}

	uint32_t exponent = (data >> 9) & 0x7u;      /* 3-bit exponent */
	uint32_t period = (data & 0x1FFu) << exponent; /* 9-bit base -> period (us) */

	if (period == 0u) {
		return -1;
	}

	/* eRPM / 100 (DShot.cpp scales back up by 100 then divides by pole pairs). */
	return (int)((1000000u * 60u / 100u + period / 2u) / period);
}
