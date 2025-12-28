/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
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
 * @file version.c
 *
 * Board identity and version information for Renesas RA8
 * Provides UUID, GUID, and MCU version functions required by PX4.
 */

#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/board_common.h>
#include <stdio.h>
#include <string.h>

#include "board_config.h"

/* SOC architecture ID */
static const uint16_t soc_arch_id = PX4_SOC_ARCH_ID;

/* Board UUID string (16 chars + null) */
static const char board_uuid[17] = "RA8P1EVK00000000";

/************************************************************************************
 * Name: board_get_uuid
 *
 * Description:
 *   Get the board UUID as an array of bytes
 *
 ************************************************************************************/

__EXPORT void board_get_uuid(uuid_byte_t uuid_bytes)
{
    unsigned int len = strlen(board_uuid);

    if (len > PX4_CPU_UUID_BYTE_LENGTH) {
        len = PX4_CPU_UUID_BYTE_LENGTH;
    }

    for (unsigned int i = 0; i < len; i++) {
        uuid_bytes[i] = board_uuid[i];
    }

    for (unsigned int i = len; i < PX4_CPU_UUID_BYTE_LENGTH; i++) {
        uuid_bytes[i] = '0';
    }
}

/************************************************************************************
 * Name: board_get_uuid32
 *
 * Description:
 *   Get the board UUID as an array of 32-bit words
 *
 ************************************************************************************/

__EXPORT void board_get_uuid32(uuid_uint32_t uuid_words)
{
    uint8_t *bp = (uint8_t *)uuid_words;
    unsigned int len = strlen(board_uuid);

    if (len > PX4_CPU_UUID_BYTE_LENGTH) {
        len = PX4_CPU_UUID_BYTE_LENGTH;
    }

    for (unsigned int i = 0; i < len; i++) {
        *bp++ = board_uuid[i];
    }

    for (unsigned int i = len; i < PX4_CPU_UUID_BYTE_LENGTH; i++) {
        *bp++ = '0';
    }
}

/************************************************************************************
 * Name: board_get_uuid32_formated
 *
 * Description:
 *   Get the board UUID formatted as a string
 *
 ************************************************************************************/

__EXPORT int board_get_uuid32_formated(char *format_buffer, int size,
       const char *format,
       const char *seperator)
{
    uuid_uint32_t uuid;
    board_get_uuid32(uuid);
    int offset = 0;
    int sep_size = seperator ? strlen(seperator) : 0;

    for (unsigned i = 0; (offset < size - 1) && (i < PX4_CPU_UUID_WORD32_LENGTH); i++) {
        offset += snprintf(&format_buffer[offset], size - offset, format, uuid[i]);

        if (sep_size && (offset < size - sep_size - 1) && (i < PX4_CPU_UUID_WORD32_LENGTH - 1)) {
            strncat(&format_buffer[offset], seperator, size - offset);
            offset += sep_size;
        }
    }

    return 0;
}

/************************************************************************************
 * Name: board_get_mfguid
 *
 * Description:
 *   Get the manufacturer GUID
 *
 ************************************************************************************/

__EXPORT int board_get_mfguid(mfguid_t mfgid)
{
	board_get_uuid(mfgid);
	return PX4_CPU_MFGUID_BYTE_LENGTH;
}

/************************************************************************************
 * Name: board_get_mfguid_formated
 *
 * Description:
 *   Get the manufacturer GUID formatted as a string
 *
 ************************************************************************************/

__EXPORT int board_get_mfguid_formated(char *format_buffer, int size)
{
    mfguid_t mfguid;

    board_get_mfguid(mfguid);
    int offset = 0;

    for (unsigned int i = 0; i < PX4_CPU_MFGUID_BYTE_LENGTH; i++) {
        offset += snprintf(&format_buffer[offset], size - offset, "%02x", mfguid[i]);
    }

    return offset;
}

/************************************************************************************
 * Name: board_get_px4_guid
 *
 * Description:
 *   Get the PX4 GUID (includes SOC arch ID + UUID)
 *
 ************************************************************************************/

__EXPORT int board_get_px4_guid(px4_guid_t px4_guid)
{
    uint8_t *pb = (uint8_t *)&px4_guid[0];

    /* First 2 bytes: SOC architecture ID */
    *pb++ = (soc_arch_id >> 8) & 0xff;
    *pb++ = (soc_arch_id & 0xff);

    /* Padding bytes (if any) */
    int padding_size = PX4_GUID_BYTE_LENGTH - ((int)sizeof(soc_arch_id) + (int)PX4_CPU_UUID_BYTE_LENGTH);

    for (int i = 0; i < padding_size; i++) {
        *pb++ = 0;
    }

    /* Remaining bytes: UUID */
    board_get_uuid(pb);
    return PX4_GUID_BYTE_LENGTH;
}

/************************************************************************************
 * Name: board_get_px4_guid_formated
 *
 * Description:
 *   Get the PX4 GUID formatted as a hex string
 *
 ************************************************************************************/

__EXPORT int board_get_px4_guid_formated(char *format_buffer, int size)
{
    px4_guid_t px4_guid;
    board_get_px4_guid(px4_guid);
    int offset = 0;

    /* size should be 2 per byte + 1 for termination
    * So it needs to be odd
    */
    size = size & 1 ? size : size - 1;

    /* Discard from MSD */
    for (unsigned i = PX4_GUID_BYTE_LENGTH - size / 2; offset < size && i < PX4_GUID_BYTE_LENGTH; i++) {
        offset += snprintf(&format_buffer[offset], size - offset, "%02x", px4_guid[i]);
    }

    return offset;
}

/************************************************************************************
 * Name: board_mcu_version
 *
 * Description:
 *   Get MCU version information
 *
 ************************************************************************************/

__EXPORT int board_mcu_version(char *rev, const char **revstr, const char **errata)
{
    static const char mcu_rev[] = "1";
    static const char mcu_revstr[] = "RA8";
    static const char mcu_errata[] = "";

    if (rev) {
        *rev = mcu_rev[0];
    }

    if (revstr) {
        *revstr = mcu_revstr;
    }

    if (errata) {
        *errata = mcu_errata;
    }

    return 0;
}
