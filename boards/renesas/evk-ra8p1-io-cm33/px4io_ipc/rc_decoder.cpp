/****************************************************************************
 *
 *   Copyright (c) 2024-2026 PX4 Development Team. All rights reserved.
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
 * @file rc_decoder.cpp
 *
 * Unified RC decoder for S.Bus, CRSF, DSM, PPM protocols
 *
 * Decodes RC input and publishes to IPC shared memory for CM85 consumption.
 * Handles RC loss detection and failsafe flag setting.
 *
 * @author PX4 Development Team
 */

#include "px4io.h"
#include "protocol.h"

#include <drivers/drv_hrt.h>
#include <px4_platform_common/log.h>
#include <lib/rc/sbus.h>
#include <lib/rc/dsm.h>

void rc_decoder_publish(void);

extern "C" {
#include <nuttx/arch.h>
}

/* RC decoder state */
static uint32_t rc_sequence = 0;
static hrt_abstime last_rc_frame_time = 0;
static uint32_t rc_frame_count = 0;
static uint32_t rc_lost_frame_count = 0;
static uint8_t rc_protocol = PX4IO_RC_PROTOCOL_SBUS;
static bool rc_failsafe_active = false;

/* RC channel data */
static uint16_t rc_channels[PX4IO_MAX_RC_CHANNELS];
static uint8_t rc_channel_count = 0;
static uint8_t rc_rssi = 0;
static uint8_t rc_link_quality = 255;  /* 255 = unknown */

/* IPC pointers (initialized by interface_init) */
extern volatile IpcRcInput *g_rc_input;

/* Performance tracking */
extern volatile uint16_t r_status_flags;

/**
 * @brief Initialize RC decoder
 */
void rc_decoder_init()
{
	last_rc_frame_time = hrt_absolute_time();
	rc_failsafe_active = false;
	rc_frame_count = 0;
	rc_lost_frame_count = 0;

	/* Initialize channels to safe values (1500 µs) */
	for (int i = 0; i < PX4IO_MAX_RC_CHANNELS; i++) {
		rc_channels[i] = 1500;
	}

	PX4_INFO("RC decoder initialized");
}

/**
 * @brief Decode S.Bus frame
 *
 * @param frame Pointer to S.Bus frame buffer (25 bytes)
 * @return true if frame is valid, false otherwise
 */
static bool rc_decode_sbus(const uint8_t *frame)
{
	uint16_t channels[18];
	bool failsafe = false;
	bool frame_drop = false;
	uint16_t channel_count = 18;

	/* Parse S.Bus frame using PX4 library */
	if (sbus_parse(hrt_absolute_time(), const_cast<uint8_t *>(frame), 25, channels, &channel_count, &failsafe, &frame_drop,
		       nullptr, PX4IO_MAX_RC_CHANNELS)) {
		/* Valid frame */
		rc_channel_count = channel_count;

		for (unsigned i = 0; i < channel_count && i < PX4IO_MAX_RC_CHANNELS; i++) {
			rc_channels[i] = channels[i];
		}

		/* S.Bus embeds failsafe flag */
		rc_failsafe_active = failsafe;

		/* Update status flags */
		r_status_flags |= PX4IO_P_STATUS_FLAGS_RC_OK;
		r_status_flags |= PX4IO_P_STATUS_FLAGS_RC_SBUS;
		r_status_flags &= ~(PX4IO_P_STATUS_FLAGS_RC_DSM | PX4IO_P_STATUS_FLAGS_RC_PPM |
		                    PX4IO_P_STATUS_FLAGS_RC_CRSF);

		if (failsafe) {
			r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
		} else {
			r_status_flags &= ~PX4IO_P_STATUS_FLAGS_FAILSAFE;
		}

		if (frame_drop) {
			rc_lost_frame_count++;
		}

		rc_frame_count++;
		last_rc_frame_time = hrt_absolute_time();

		return true;
	}

	return false;
}

/**
 * @brief Decode DSM frame
 *
 * @param frame Pointer to DSM frame buffer (16 bytes)
 * @return true if frame is valid, false otherwise
 */
static bool rc_decode_dsm(const uint8_t *frame)
{
	uint16_t channels[18];
	bool failsafe = false;
	bool dsm_11_bit = false;
	uint16_t channel_count = 18;

	/* Parse DSM frame using PX4 library */
	if (dsm_parse(hrt_absolute_time(), frame, 16, channels, &channel_count, &dsm_11_bit, nullptr, nullptr,
		      PX4IO_MAX_RC_CHANNELS)) {
		rc_channel_count = channel_count;

		for (unsigned i = 0; i < channel_count && i < PX4IO_MAX_RC_CHANNELS; i++) {
			rc_channels[i] = channels[i];
		}

		rc_failsafe_active = failsafe;

		/* Update status flags */
		r_status_flags |= PX4IO_P_STATUS_FLAGS_RC_OK;
		r_status_flags |= PX4IO_P_STATUS_FLAGS_RC_DSM;
		r_status_flags &= ~(PX4IO_P_STATUS_FLAGS_RC_SBUS | PX4IO_P_STATUS_FLAGS_RC_PPM |
		                    PX4IO_P_STATUS_FLAGS_RC_CRSF);

		if (failsafe) {
			r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
		} else {
			r_status_flags &= ~PX4IO_P_STATUS_FLAGS_FAILSAFE;
		}

		rc_frame_count++;
		last_rc_frame_time = hrt_absolute_time();

		return true;
	}

	return false;
}

/**
 * @brief Decode CRSF frame
 *
 * @param frame Pointer to CRSF frame buffer
 * @param len Frame length
 * @return true if frame is valid, false otherwise
 */
static bool rc_decode_crsf(const uint8_t *frame, uint8_t len)
{
	/* TODO: Implement CRSF decoder
	 * CRSF is more complex than S.Bus/DSM and requires state machine
	 * for variable-length packet parsing.
	 *
	 * For now, return false to indicate not implemented.
	 */
	(void)frame;
	(void)len;

	return false;
}

/**
 * @brief Check for RC timeout and set failsafe
 *
 * Should be called periodically (e.g., every 1ms) from main loop.
 */
void rc_decoder_check_timeout()
{
	hrt_abstime time_since_frame = hrt_elapsed_time(&last_rc_frame_time);

	if (time_since_frame > PX4IO_IPC_RC_TIMEOUT_US) {
		if (!rc_failsafe_active) {
			rc_failsafe_active = true;
			PX4_WARN("RC TIMEOUT (%llu ms) - failsafe active", time_since_frame / 1000);
		}

		/* Clear RC OK flag */
		r_status_flags &= ~PX4IO_P_STATUS_FLAGS_RC_OK;
		r_status_flags |= PX4IO_P_STATUS_FLAGS_FAILSAFE;
	}
}

/**
 * @brief Process incoming RC frame
 *
 * Called from UART RX interrupt handler or DMA complete callback.
 *
 * @param protocol RC protocol (SBUS, DSM, CRSF, PPM)
 * @param frame Pointer to frame buffer
 * @param len Frame length
 */
void rc_decoder_process_frame(uint8_t protocol, const uint8_t *frame, uint8_t len)
{
	bool valid = false;

	switch (protocol) {
	case PX4IO_RC_PROTOCOL_SBUS:
		if (len >= 25) {
			valid = rc_decode_sbus(frame);
			rc_protocol = PX4IO_RC_PROTOCOL_SBUS;
		}

		break;

	case PX4IO_RC_PROTOCOL_DSM:
		if (len >= 16) {
			valid = rc_decode_dsm(frame);
			rc_protocol = PX4IO_RC_PROTOCOL_DSM;
		}

		break;

	case PX4IO_RC_PROTOCOL_CRSF:
		valid = rc_decode_crsf(frame, len);

		if (valid) {
			rc_protocol = PX4IO_RC_PROTOCOL_CRSF;
		}

		break;

	default:
		break;
	}

	if (valid) {
		/* Publish to IPC immediately */
		rc_decoder_publish();
	}
}

/**
 * @brief Publish RC data to IPC
 *
 * Writes RC channel data to IPC shared memory for CM85 consumption.
 * Can be called from interrupt context (fast, no blocking).
 */
void rc_decoder_publish()
{
	if (!g_rc_input) {
		return;
	}

	IpcRcInput rc_msg;
	rc_msg.sequence = ++rc_sequence;
	rc_msg.timestamp_us = hrt_absolute_time();
	rc_msg.channel_count = rc_channel_count;
	rc_msg.rssi = rc_rssi;
	rc_msg.link_quality = rc_link_quality;
	rc_msg.failsafe = rc_failsafe_active ? 1 : 0;
	rc_msg.protocol = rc_protocol;

	/* Calculate frame rate (approximate) */
	static hrt_abstime last_publish_time = 0;
	hrt_abstime now = hrt_absolute_time();

	if (last_publish_time > 0) {
		hrt_abstime dt = now - last_publish_time;

		if (dt > 0) {
			rc_msg.frame_rate = (uint8_t)(1000000 / dt);  /* Hz */
		} else {
			rc_msg.frame_rate = 0;
		}
	} else {
		rc_msg.frame_rate = 0;
	}

	last_publish_time = now;

	/* Copy channel data */
	for (int i = 0; i < PX4IO_MAX_RC_CHANNELS; i++) {
		rc_msg.channel[i] = rc_channels[i];
	}

	rc_msg.frame_count = (uint16_t)rc_frame_count;
	rc_msg.lost_frame_count = (uint16_t)rc_lost_frame_count;

	/* Calculate CRC */
	rc_msg.crc16 = ipc_calculate_message_crc(&rc_msg, nullptr);

	/* Write to IPC with memory barrier */
	ARM_DMB();
	memcpy((void *)g_rc_input, &rc_msg, sizeof(IpcRcInput));
	ARM_DMB();
}

/**
 * @brief Get RC frame count
 */
uint32_t rc_decoder_get_frame_count()
{
	return rc_frame_count;
}

/**
 * @brief Get RC lost frame count
 */
uint32_t rc_decoder_get_lost_frame_count()
{
	return rc_lost_frame_count;
}

/**
 * @brief Check if RC failsafe is active
 */
bool rc_decoder_is_failsafe_active()
{
	return rc_failsafe_active;
}

/**
 * @brief Set RSSI value
 *
 * Called by protocol-specific decoder to update signal strength.
 */
void rc_decoder_set_rssi(uint8_t rssi)
{
	rc_rssi = rssi;
}

/**
 * @brief Set link quality value
 *
 * Called by CRSF decoder to update link quality percentage.
 */
void rc_decoder_set_link_quality(uint8_t quality)
{
	rc_link_quality = quality;
}
