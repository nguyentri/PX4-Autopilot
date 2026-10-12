/* Host boundary for the real RZ/V2H board and ICM20948 SPI code. */
#ifndef RZV2H_ICM20948_HOST_STUBS_H
#define RZV2H_ICM20948_HOST_STUBS_H

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <syslog.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>

#define OK 0
#define UNUSED(x) ((void)(x))
#define spiinfo(...) ((void)printf(__VA_ARGS__))
#define spiwarn(...) ((void)printf(__VA_ARGS__))
#define GPIO_MOSA_P9_0_M1 0x90u
#define GPIO_MISO4_P9_1_M1 0x91u
#define GPIO_RSPCK4_P9_2_M1 0x92u
#define GPIO_SSLA0_P9_3_M1 0x100093u
#define GPIO_P9_3_OUTPUT_HIGH 0x200093u
#define GPIO_P9_4_INPUT 0x300094u
#define GPIO_TINT_P9_4 0x400094u
#define RZV_GPIO_PERIPH 0x10000000u
#define RZV_GPIO_DRVSTR_HIGH 0x20000000u
#define SPI_STATUS_PRESENT 1
#define SPIDEV_MODE3 3
#define SPIDEV_ACCELEROMETER(n) (0x10000u | (n))

struct spi_dev_s { int port; };
int rzv_gpioconfig(uint32_t pin);
void rzv_gpiowrite(uint32_t pin, bool level);
struct spi_dev_s *rzv_spibus_initialize(int port);
int spi_register(struct spi_dev_s *dev, int port);
int host_lock(struct spi_dev_s *dev, bool lock);
void host_mode(struct spi_dev_s *dev, int mode);
void host_bits(struct spi_dev_s *dev, int bits);
uint32_t host_frequency(struct spi_dev_s *dev, uint32_t frequency);
void host_select(struct spi_dev_s *dev, uint32_t id, bool selected);
void host_exchange(struct spi_dev_s *dev, const void *tx, void *rx, size_t len);
#define SPI_LOCK host_lock
#define SPI_SETMODE host_mode
#define SPI_SETBITS host_bits
#define SPI_SETFREQUENCY host_frequency
#define SPI_SELECT host_select
#define SPI_EXCHANGE host_exchange

#include "board-under-test.h"
#include "icm20948-under-test.h"
#endif
