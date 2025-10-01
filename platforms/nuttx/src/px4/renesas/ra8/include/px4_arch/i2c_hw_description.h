/****************************************************************************
 *
 *   Copyright (C) 2021 PX4 Development Team. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright
 *	notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *	notice, this list of conditions and the following disclaimer in
 *	the documentation and/or other materials provided with the
 *	distribution.
 * 3. Neither the name PX4 nor the names of its contributors may be
 *	used to endorse or promote products derived from this software
 *	without specific prior written permission.
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

#ifdef __cplusplus
extern "C" {
#endif

/* I2C bus maximum number definition */
#define I2C_BUS_MAX_BUS_ITEMS 4

/* I2C hardware interface structure */
struct i2c_master_s {
    int bus_num;
    /* Add your RZV platform specific I2C controller data here */
};

/* I2C message structure */
struct i2c_msg_s {
    uint16_t addr;      /* Slave address */
    uint16_t flags;     /* Flags for message transfer */
    uint8_t *buffer;    /* Data buffer */
    size_t length;      /* Length of buffer in bytes */
    uint32_t frequency; /* I2C bus speed */
};

/* I2C message flags */
#define I2C_M_READ          0x0001  /* Read data */
#define I2C_M_NOSTART       0x0002  /* Don't send START condition */
#define I2C_M_NOSTOP        0x0004  /* Don't send STOP condition */
#define I2C_M_NORESTART     0x0008  /* Don't send RESTART condition */
#define I2C_M_NACK          0x0010  /* Expect NACK bit */
#define I2C_M_SCAN          0x0020  /* Scan the bus for devices */

/* I2C control operations */
#define I2C_RESET(dev)      px4_i2cbus_reset(dev)

/* I2C transfer function - performs a sequence of I2C transfers */
#define I2C_TRANSFER(dev, msgs, count) px4_i2c_transfer(dev, msgs, count)

/* I2C hardware interface functions for RZV FreeRTOS */
struct i2c_master_s *px4_i2cbus_initialize(int bus);
int px4_i2cbus_uninitialize(struct i2c_master_s *dev);
int px4_i2cbus_reset(struct i2c_master_s *dev);
int px4_i2c_transfer(struct i2c_master_s *dev, struct i2c_msg_s *msgs, int count);

#ifdef __cplusplus
}
#endif
