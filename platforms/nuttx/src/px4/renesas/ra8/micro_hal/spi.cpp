/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
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
 * @file spi.cpp
 * SPI micro HAL implementation for Renesas RA8
 */

#include <stdint.h>
#include <stdbool.h>

/* PX4 sensor device type definitions */
#define DRV_IMU_DEVTYPE_ICM20948  0x28
#define DRV_BARO_DEVTYPE_BMP388   0x67
#define SPI_STATUS_PRESENT        0x01

struct spi_dev_s;

extern "C" {
    extern struct spi_dev_s *ra_spibus_initialize(int bus);
    extern void fpb_ra8e1_spi_gpio_init(void);
    extern void fpb_ra8e1_spi_select(uint32_t devid, bool selected);
    extern bool fpb_ra8e1_spi_drdy_read(void);
}

/* PX4 SPI bus initialization */
extern "C" struct spi_dev_s *px4_spibus_initialize(int bus)
{
    struct spi_dev_s *spi_dev = nullptr;

    if (bus == 1) {
        spi_dev = ra_spibus_initialize(1);
        if (spi_dev != nullptr) {
            fpb_ra8e1_spi_gpio_init();
        }
    }

    return spi_dev;
}

/* SPI chip select functions for NuttX integration */
extern "C" void ra8_spi1select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
    fpb_ra8e1_spi_select(devid, selected);
}

extern "C" uint8_t ra8_spi1status(struct spi_dev_s *dev, uint32_t devid)
{
    uint8_t status = 0;

    switch (devid) {
    case DRV_IMU_DEVTYPE_ICM20948:
        if (fpb_ra8e1_spi_drdy_read()) {
            status |= SPI_STATUS_PRESENT;
        }
        break;

    case DRV_BARO_DEVTYPE_BMP388:
        status |= SPI_STATUS_PRESENT;
        break;

    default:
        break;
    }

    return status;
}

/* SPI DMA stub */
extern "C" void px4_spibus_set_dma_config(struct spi_dev_s *dev, uint32_t dma_config)
{
    (void)dev;
    (void)dma_config;
}
