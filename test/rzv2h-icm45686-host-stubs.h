/* Host boundary for the real RZ/V2H ICM-45686 SPI helpers and NSH command.
 * The contract test strips platform includes from the board sources; this
 * header supplies the NuttX types, SPI operations, critical sections, and a
 * fake monotonic clock that the fixture advances deterministically.
 */
#ifndef RZV2H_ICM45686_HOST_STUBS_H
#define RZV2H_ICM45686_HOST_STUBS_H

#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define SPIDEV_MODE3 3
#define SPIDEV_ACCELEROMETER(n) (0x10000u | (n))

typedef unsigned int irqstate_t;
struct spi_dev_s { int port; };

irqstate_t enter_critical_section(void);
void leave_critical_section(irqstate_t flags);
int board_spi_initialize(void);
struct spi_dev_s *rzv_spibus_initialize(int port);
int rzv2h_icm45686_main(int argc, char *argv[]);

int host_lock(struct spi_dev_s *dev, bool lock);
void host_mode(struct spi_dev_s *dev, int mode);
void host_bits(struct spi_dev_s *dev, int bits);
uint32_t host_frequency(struct spi_dev_s *dev, uint32_t frequency);
void host_select(struct spi_dev_s *dev, uint32_t id, bool selected);
void host_exchange(struct spi_dev_s *dev, const void *tx, void *rx,
                   size_t len);
int host_clock_gettime(clockid_t clock, struct timespec *now);
int host_usleep(useconds_t usec);

#define SPI_LOCK host_lock
#define SPI_SETMODE host_mode
#define SPI_SETBITS host_bits
#define SPI_SETFREQUENCY host_frequency
#define SPI_SELECT host_select
#define SPI_EXCHANGE host_exchange
#define clock_gettime host_clock_gettime
#define usleep host_usleep

#include "icm45686-spi-under-test.h"
#endif
