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
 * @file dshot_telemetry.h
 *
 * Pure BDShot (bidirectional DShot) telemetry decode for RZ/V2H.
 *
 * Hardware-independent so the RLL/GCR/eRPM math can be reviewed and tested
 * before a GPT capture front-end is added. The algorithm mirrors
 * the upstream reference decode in
 * platforms/nuttx/src/px4/nxp/imxrt/dshot/dshot.c so the value returned by
 * up_bdshot_get_erpm() matches what src/drivers/dshot/DShot.cpp expects.
 */

#pragma once

#include <stdint.h>

__BEGIN_DECLS

/**
 * Decode a raw bidirectional-DShot response into eRPM.
 *
 * @param raw_response 20 significant response bits sampled with 1 = line high,
 *                     in receive order (bit 0 = last sample). Matches the
 *                     `raw_response` convention of the imxrt reference.
 * @return eRPM in units of 100 electrical RPM (the scale DShot.cpp multiplies
 *         back up by 100 before dividing by pole pairs); 0 when the motor is
 *         stopped (0xFFF telemetry); <0 on framing or checksum error.
 *
 * NOTE: pole-count conversion is done by the consumer (DShot.cpp), NOT here.
 */
int dshot_telem_decode_erpm(uint32_t raw_response);

__END_DECLS
