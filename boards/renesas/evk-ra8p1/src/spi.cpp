/****************************************************************************
 *
 *   Copyright (c) 2024 PX4 Development Team. All rights reserved.
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
 *
 * EVK-RA8P1 Board-specific SPI functions for GY-912 sensor board.
 */

#include <px4_arch/spi_hw_description.h>
#include <px4_platform_common/px4_config.h>
#include <px4_platform_common/spi.h>
#include <px4_arch/io_timer.h>
#include <drivers/drv_sensor.h>
#include <nuttx/spi/spi.h>
#include "board_config.h"
#include "ra_gpio.h"

#include <lib/drivers/device/Device.hpp>
#include <stdint.h>
#include <stdbool.h>
#include <px4_platform_common/log.h>
#include <syslog.h>

// SPI Status definitions
#ifndef SPI_STATUS_PRESENT
#define SPI_STATUS_PRESENT  0x01
#endif

// Debug macro for SPI operations
#define SPI_DEBUG(fmt, ...) syslog(LOG_INFO, "SPI_DBG: " fmt "\n", ##__VA_ARGS__)

// Use predefined GPIO macros from board_config.h for GY-912 SPI pins
// GPIO_SPI1_CS0 (P804) - ICM20948 CS
// GPIO_SPI1_CS1 (P402) - BMP388 CS
// GPIO_SPI1_IMU_DRDY (P006) - ICM20948 Data Ready

// GY-912 10DOF sensor module configuration
// Contains ICM-20948 (9DOF IMU) and BMP388 (barometric pressure sensor)
//
// Hardware connections on EVK-RA8P1 via Pmod1:
// - ICM-20948: CS=P804, DRDY=P006 (9DOF IMU: gyro + accel + mag)
// - BMP388:    CS=P402            (barometric pressure sensor)
// - SPI Bus:   SPI1 (1MHz default, up to 7MHz for ICM20948, 10MHz for BMP388)
constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
        initSPIBus(SPI::Bus::SPI1, {
                // ICM-20948: 9DOF IMU (gyroscope, accelerometer, magnetometer)
                initSPIDevice(DRV_IMU_DEVTYPE_ICM20948, SPI::CS{GPIO::Port8, GPIO::Pin4}, SPI::DRDY{GPIO::Port0, GPIO::Pin6}),

                // BMP388: Barometric pressure sensor
                initSPIDevice(DRV_BARO_DEVTYPE_BMP388, SPI::CS{GPIO::Port4, GPIO::Pin2}),
        }),
};

static constexpr bool unused = validateSPIConfig(px4_spi_buses);

/************************************************************************************
 * GY-912 Board-specific SPI Functions
 ************************************************************************************/

extern "C" {
#if (1) // Set to 1 to enable override for PX4 settings
    #include "ra_spi.h"

    /**
     * Name: ra_spi_select
     *
     * Description:
     *   Board-specific SPI device select function - overrides NuttX weak function
     *   Handles device-specific configuration (frequency, mode, bits) and CS control
     *   for GY-912 sensor board.
     *
     *   This function is called by PX4 AFTER SPI_SETFREQUENCY/SETMODE/SETBITS,
     *   so we override those settings with device-specific values from ra_spi_get_dev_config().
     *
     * Input Parameters:
     *   dev - SPI device structure
     *   devid - Device ID (encoded with PX4_SPIDEV_ID)
     *   selected - true to select (assert CS), false to deselect (deassert CS)
     */
    void ra_spi_select(struct spi_dev_s *dev, uint32_t devid, bool selected)
    {
        /* Handle chip select for GY-912 SPI devices using predefined GPIO macros */
        /* Device ID determines which CS pin to control */
        /* Note: devid is encoded with PX4_SPIDEV_ID, extract lower 16 bits for device type */
        uint16_t devtype = PX4_SPI_DEV_ID(devid);

        if (selected) {
            /* Get device-specific configuration and calculate SPI parameters */
            const struct ra_spi_ext_dev_config_s *config = ra_spi_get_dev_config(dev, devid);
            /* Overwrite the PX4 settings*/
            if (config != nullptr) {
                /* Calculate device-specific settings (writes immediately to hardware) */
                SPI_DEBUG("Applying config for devtype 0x%04x: freq=%lu, mode=%u, bits=%u, dir=%s",
                          devtype, (unsigned long)config->max_frequency, config->cur_mode, config->cur_bits,
                          config->cur_dir == RA_SPI_DIR_LSB_FIRST ? "LSB" : "MSB");

                /* Write to hardware registers immediately */
                SPI_SETFREQUENCY(dev, config->max_frequency);
                SPI_SETMODE(dev, (enum spi_mode_e)config->cur_mode);
                SPI_SETBITS(dev, config->cur_bits);

                /* Set bit order (MSB-first or LSB-first) */
                ra_spi_setbitorder(dev, config->cur_dir == RA_SPI_DIR_LSB_FIRST);
            }
        }

        switch (devtype) {
        case DRV_IMU_DEVTYPE_ICM20948: /* First SPI device - ICM20948 on CS0 (P804) */
            SPI_DEBUG("  -> Controlling CS0 (P804) for ICM20948 %s", selected ? "SELECTED" : "DESELECTED");
            //ra_gpiowrite(GPIO_SPI1_CS0, !selected);  /* Active low CS */ must move GPIO configuration out of driver
            break;

        case DRV_BARO_DEVTYPE_BMP388: /* Second SPI device - BMP388 on CS1 (P402) */
            SPI_DEBUG("  -> Controlling CS1 (P402) for BMP388 %s", selected ? "SELECTED" : "DESELECTED");
            // ra_gpiowrite(GPIO_SPI1_CS1, !selected);  /* Active low CS */ must move GPIO configuration out of driver
            break;

        default:
            SPI_DEBUG("  -> Unknown devtype 0x%04x, no action taken", devtype);
            /* Unknown device ID - do nothing */
            break;
            }
    }
#endif
    /**
     * Name: ra_spi_status
     *
     * Description:
     *   Return the SPI status - required by NuttX RA8 SPI driver
     *   Returns status for GY-912 module sensors
     *
     * Input Parameters:
     *   dev - SPI device structure (unused)
     *   devid - Device ID (0 for ICM20948, 1 for BMP388)
     *
     * Returned Value:
     *   SPI_STATUS_PRESENT for configured devices, 0 for unknown devices
     */
    uint8_t ra_spi_status(struct spi_dev_s *dev, uint32_t devid)
    {
        (void)dev; /* Unused parameter */

        uint8_t status = 0;

        /* For GY-912 module, all configured SPI devices are present */
        /* Return present status for configured device IDs */
        /* Note: devid is encoded with PX4_SPIDEV_ID, extract lower 16 bits for device type */
        uint16_t devtype = PX4_SPI_DEV_ID(devid);

        switch (devtype) {
        case DRV_IMU_DEVTYPE_ICM20948: /* ICM20948 9DOF IMU on CS0 */
            status = SPI_STATUS_PRESENT;
            SPI_DEBUG("ra_spi_status: devtype=0x%04x (ICM20948) -> PRESENT", devtype);
            break;

        case DRV_BARO_DEVTYPE_BMP388: /* BMP388 Barometric pressure sensor on CS1 */
            status = SPI_STATUS_PRESENT;
            SPI_DEBUG("ra_spi_status: devtype=0x%04x (BMP388) -> PRESENT", devtype);
            break;

        default:
            SPI_DEBUG("ra_spi_status: devtype=0x%04x -> NOT PRESENT", devtype);
            status = 0;  /* Unknown device */
            break;
        }

        return status;
    }

    /**
     * Name: ra_spi_cmddata
     *
     * Description:
     *   Control the SPI CMD/DATA GPIO - required by NuttX RA8 SPI driver
     *   GY-912 module doesn't use CMD/DATA line
     */
    int ra_spi_cmddata(struct spi_dev_s *dev, uint32_t devid, bool cmd)
    {
        /* GY-912 sensors don't use CMD/DATA line */
        return 0;
    }

    /**
     * Name: ra_spi_get_dev_config
     *
     * Description:
     *   Get device-specific configuration for GY-912 sensor board
     *   Returns configuration with frequency, mode, and CS pin settings
     *
     * Input Parameters:
     *   dev - SPI device structure
     *   devid - Device ID (encoded with PX4_SPIDEV_ID)
     *
     * Returned Value:
     *   Pointer to device configuration structure, or NULL for default settings
     */
    const struct ra_spi_ext_dev_config_s *ra_spi_get_dev_config(struct spi_dev_s *dev, uint32_t devid)
    {
        /* Static configuration structures for each sensor */
        static const struct ra_spi_ext_dev_config_s icm20948_config = {
            .devid = DRV_IMU_DEVTYPE_ICM20948,
            .max_frequency = 4000000,              /* 4 MHz - ICM20948 (datasheet supports up to 7 MHz) */
            .cur_mode = SPIDEV_MODE3,              /* SPI Mode 3 (CPOL=1, CPHA=1) */
            .cur_bits = 8,                         /* 8-bit transfers */
            .cur_dir = RA_SPI_DIR_MSB_FIRST,       /* MSB first - ICM20948 datasheet */
            .cs_gpio = 0,              /* T.B.D */
            .cs_type = RA_SPI_CS_GPIO,             /* Use GPIO control for CS */
            .ssl_select = 0xFF,                    /* Use GPIO */
            .setup_delay = 2,                      /* 2 RSPCK cycles CS setup delay */
            .hold_delay = 2,                       /* 2 RSPCK cycles CS hold delay */
            .negation_delay = 0,                   /* 0 RSPCK cycles CS negation delay */
            .active_low = true,                    /* CS active low */
            .name = "ICM20948"
        };

        static const struct ra_spi_ext_dev_config_s bmp388_config = {
            .devid = DRV_BARO_DEVTYPE_BMP388,
            .max_frequency = 5000000,              /* 5 MHz - BMP388 (datasheet supports up to 10 MHz) */
            .cur_mode = SPIDEV_MODE3,              /* SPI Mode 3 (CPOL=1, CPHA=1) - BMP388 datasheet */
            .cur_bits = 8,                         /* 8-bit transfers */
            .cur_dir = RA_SPI_DIR_MSB_FIRST,       /* MSB first - BMP388 datasheet */
            .cs_gpio = 0,               /* T.B.D */
            .cs_type = RA_SPI_CS_GPIO,             /* Use GPIO control for CS */
            .ssl_select = 0xFF,                    /* Use GPIO */
            .setup_delay = 1,                      /* 1 RSPCK cycle CS setup (datasheet: min 6ns @ 5MHz = 200ns period) */
            .hold_delay = 1,                       /* 1 RSPCK cycle CS hold (datasheet: min 6ns) */
            .negation_delay = 1,                   /* 1 RSPCK cycle between transactions */
            .active_low = true,                    /* CS active low */
            .name = "BMP388"
        };

        /* Extract device type from encoded devid */
        uint16_t devtype = PX4_SPI_DEV_ID(devid);

        /* Return configuration based on device type */
        switch (devtype) {
        case DRV_IMU_DEVTYPE_ICM20948:
            SPI_DEBUG("ra_spi_get_dev_config: Returning ICM20948 config (4MHz, Mode3)");
            return &icm20948_config;

        case DRV_BARO_DEVTYPE_BMP388:
            SPI_DEBUG("ra_spi_get_dev_config: Returning BMP388 config (5MHz, Mode3)");
            return &bmp388_config;

        default:
            SPI_DEBUG("ra_spi_get_dev_config: No config for devtype 0x%04x, using defaults", devtype);
            return nullptr;  /* Use driver defaults */
        }
    }

} /* extern "C" */
