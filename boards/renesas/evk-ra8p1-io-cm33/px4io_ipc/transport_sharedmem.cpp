#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/defines.h>

#include <syslog.h>
#include <string.h>

#include "px4io.h"
#include "protocol.h"
#include "ipc.h"

#include <drivers/drv_hrt.h>

static uint64_t last_heartbeat_sent = 0;
static uint64_t last_rc_sent = 0;
static uint16_t tx_sequence = 0;

void interface_init(void)
{
	ipc_init();
}

void interface_tick(void)
{
	// 1. Handle Incoming Messages
	while (ipc_available() >= sizeof(IpcHeader)) {
		// We assume that if header is available, the full payload is also available
		// because the sender commits the write atomically (updates head pointer last).
		// However, we can't peek easily with the current API, so we read the header.

		IpcHeader header_copy;
		// Note: This is a destructive read of the header. If payload is missing (shouldn't happen), we desync.
		// A robust implementation would peek or handle sync loss.
		if (!ipc_read(&header_copy, sizeof(header_copy))) {
			break;
		}

		if (header_copy.magic != PX4IO_IPC_MAGIC) {
			// Sync loss or garbage.
			// Ideally we should scan for magic.
			continue;
		}

		if (header_copy.payload_len > 0) {
			uint8_t payload[256]; // Max payload buffer
			if (header_copy.payload_len > sizeof(payload)) {
				// Payload too large, ignore and flush?
				// For now just consume it to get back in sync if possible, or break.
				// We can't easily flush without reading.
				// Let's try to read it into a dummy buffer or loop.
				uint8_t dummy;
				for(int i=0; i<header_copy.payload_len; i++) ipc_read(&dummy, 1);
				continue;
			}

			if (!ipc_read(payload, header_copy.payload_len)) {
				// Should not happen if atomic write
				continue;
			}

			// Handle Payload
			switch (header_copy.type) {
				case IpcFrameType::ActuatorCmd: {
					IpcActuatorCmd *cmd = (IpcActuatorCmd *)payload;

					// Update PWM/DShot
					// Map to r_page_servos
					for (int i = 0; i < 8; i++) {
						r_page_servos[i] = cmd->motor[i];
					}

					// Update Arming State
					if (cmd->armed) {
						atomic_modify_or(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
					} else {
						atomic_modify_clear(&r_setup_arming, PX4IO_P_SETUP_ARMING_FMU_ARMED);
					}

					// Update Heartbeat
					system_state.fmu_data_received_time = hrt_absolute_time();
					break;
				}
				case IpcFrameType::Cm85Heartbeat: {
					system_state.fmu_data_received_time = hrt_absolute_time();
					break;
				}
				default:
					break;
			}
		}
	}

	// 2. Send Heartbeat / Status
	if (hrt_absolute_time() - last_heartbeat_sent > 100000) { // 10Hz
		IpcHeader header;
		header.magic = PX4IO_IPC_MAGIC;
		header.version = PX4IO_IPC_PROTOCOL_VERSION;
		header.type = IpcFrameType::Cm33Heartbeat;
		header.sequence = tx_sequence++;
		header.timestamp_us = hrt_absolute_time();
		header.payload_len = sizeof(IpcCm33Heartbeat);
		header.crc16 = 0;

		IpcCm33Heartbeat hb;
		hb.status_flags = r_status_flags;
		hb.arming_flags = r_setup_arming;

		ipc_write(&header, sizeof(header));
		ipc_write(&hb, sizeof(hb));

		last_heartbeat_sent = hrt_absolute_time();
	}

	// 3. Send RC Input (if new)
	if (system_state.rc_channels_timestamp_received > last_rc_sent) {
		IpcHeader header;
		header.magic = PX4IO_IPC_MAGIC;
		header.version = PX4IO_IPC_PROTOCOL_VERSION;
		header.type = IpcFrameType::RcInput;
		header.sequence = tx_sequence++;
		header.timestamp_us = system_state.rc_channels_timestamp_received;
		header.payload_len = sizeof(IpcRcInput);
		header.crc16 = 0;

		IpcRcInput rc;
		rc.channel_count = r_raw_rc_count;
		rc.rssi = 100; // Placeholder
		rc.rc_lost = (r_status_flags & PX4IO_P_STATUS_FLAGS_RC_OK) ? 0 : 1;
		rc.rc_failsafe = 0;

		for (int i = 0; i < rc.channel_count && i < 18; i++) {
			rc.channels[i] = r_raw_rc_values[i];
		}

		ipc_write(&header, sizeof(header));
		ipc_write(&rc, sizeof(rc));

		last_rc_sent = system_state.rc_channels_timestamp_received;
	}
}
