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
 * @file spi.c
 * SPI micro HAL implementation for Renesas RA8
 */

#include <stdint.h>
#include <stdbool.h>
#include <errno.h>

#include <px4_platform_common/px4_config.h>
#include <px4_arch/spi_hw_description.h>

/* Board specific definitions */
#include "board_config.h"

#ifndef OK
#define OK 0
#endif

/* Forward declarations */
struct spi_dev_s;

/* NuttX SPI driver function */
extern struct spi_dev_s *ra_spibus_initialize(int bus);

/****************************************************************************
 * SPI Bus Initialization
 ****************************************************************************/

/**
 * Initialize SPI bus
 */
struct spi_dev_s *px4_spibus_initialize(int bus)
{
    struct spi_dev_s *spi_dev = NULL;

    switch (bus) {
    case 1:
        /* Initialize SPI1 for sensors */
        spi_dev = ra_spibus_initialize(1);

        if (spi_dev != NULL) {
            /* Configure SPI1 GPIO pins */
            px4_arch_configgpio(GPIO_SPI1_SCK);
            px4_arch_configgpio(GPIO_SPI1_MISO);
            px4_arch_configgpio(GPIO_SPI1_MOSI);
            px4_arch_configgpio(GPIO_SPI1_CS0_ICM20948);
            px4_arch_configgpio(GPIO_SPI1_CS1_BMP388);
            px4_arch_configgpio(GPIO_IMU_DRDY);

            /* Set chip selects to inactive (high) */
            px4_arch_gpiowrite(GPIO_SPI1_CS0_ICM20948, true);
            px4_arch_gpiowrite(GPIO_SPI1_CS1_BMP388, true);
        }
        break;

    default:
        break;
    }

    return spi_dev;
}

/****************************************************************************
 * SPI Chip Select Functions
 ****************************************************************************/

/**
 * SPI1 chip select function
 */
void ra8_spi1select(struct spi_dev_s *dev, uint32_t devid, bool selected)
{
    /* Handle chip select for SPI1 devices */
    switch (devid) {
    case PX4_SPIDEV_ICM20948:
        px4_arch_gpiowrite(GPIO_SPI1_CS0_ICM20948, !selected);
        break;

    case PX4_SPIDEV_BMP388:
        px4_arch_gpiowrite(GPIO_SPI1_CS1_BMP388, !selected);
        break;

    default:
        break;
    }
}

/**
 * SPI1 status function
 */
uint8_t ra8_spi1status(struct spi_dev_s *dev, uint32_t devid)
{
    uint8_t status = 0;

    /* Return device-specific status */
    switch (devid) {
    case PX4_SPIDEV_ICM20948:
        /* Check data ready pin */
        if (px4_arch_gpioread(GPIO_IMU_DRDY)) {
            status |= SPI_STATUS_PRESENT;
        }
        break;

    case PX4_SPIDEV_BMP388:
        /* BMP388 is always present if configured */
        status |= SPI_STATUS_PRESENT;
        break;

    default:
        break;
    }

    return status;
}

/****************************************************************************
 * SPI DMA Functions (stubs for now)
 ****************************************************************************/

/**
 * Configure SPI DMA - stub implementation
 */
void px4_spibus_set_dma_config(struct spi_dev_s *dev, uint32_t dma_config)
{
    /* TODO: Implement DMA configuration for RA8 SPI */
    (void)dev;
    (void)dma_config;
}

/****************************************************************************
 * SPI Device ID Definitions for PX4
 ****************************************************************************/

/* These should match the device IDs used in spi.cpp */
#ifndef PX4_SPIDEV_ICM20948
#define PX4_SPIDEV_ICM20948  1
#endif

#ifndef PX4_SPIDEV_BMP388
#define PX4_SPIDEV_BMP388    2
#endif

#ifndef SPI_STATUS_PRESENT
#define SPI_STATUS_PRESENT   0x01
#endif
