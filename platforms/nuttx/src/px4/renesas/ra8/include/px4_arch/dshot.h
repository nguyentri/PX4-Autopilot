/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights
 *   reserved.
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

#include <stdint.h>

/**
 * RA8 specific DShot hardware description per IO timer channel.
 *
 * The structure is intentionally small so it can be embedded inside
 * timer_io_channels_t without increasing flash usage.
 */
typedef struct dshot_conf_s {
	uint8_t gpt_channel;   ///< GPT instance number (0-13)
	uint8_t gpt_output;    ///< GPT output (0 = A, 1 = B)
	int8_t  dma_channel;   ///< DMAC channel index for waveform generation (-1 = unused)
	int8_t  dma_capture;   ///< Optional DMAC channel for telemetry capture (-1 = unused)
} dshot_conf_t;

#ifdef __cplusplus
constexpr dshot_conf_t makeDshotConf(uint8_t gpt_channel,
				     uint8_t gpt_output,
				     int8_t dma_channel,
				     int8_t dma_capture = -1)
{
	return dshot_conf_t{gpt_channel, gpt_output, dma_channel, dma_capture};
}
#else
static inline dshot_conf_t makeDshotConf(uint8_t gpt_channel,
					 uint8_t gpt_output,
					 int8_t dma_channel,
					 int8_t dma_capture)
{
	dshot_conf_t conf = {gpt_channel, gpt_output, dma_channel, dma_capture};
	return conf;
}
#endif
