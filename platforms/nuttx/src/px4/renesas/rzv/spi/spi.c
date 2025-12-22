/****************************************************************************
 * platforms/nuttx/src/px4/renesas/rzv2h/spi/spi.c
 *
 * RZV2H SPI platform support
 ****************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <stdbool.h>
#include <stdint.h>

#include <nuttx/spi/spi.h>

/****************************************************************************
 * Public Functions
 ****************************************************************************/

__EXPORT void rzv2h_spixselect(FAR struct spi_dev_s *dev, uint32_t devid, bool selected)
{
	/* SPI chip select handled by NuttX driver */
	(void)dev;
	(void)devid;
	(void)selected;
}

__EXPORT uint8_t rzv2h_spixstatus(FAR struct spi_dev_s *dev, uint32_t devid)
{
	/* Always return ready */
	(void)dev;
	(void)devid;
	return 0;
}

#ifdef CONFIG_SPI_CMDDATA
__EXPORT int rzv2h_spixcmddata(FAR struct spi_dev_s *dev, uint32_t devid, bool cmd)
{
	(void)dev;
	(void)devid;
	(void)cmd;
	return 0;
}
#endif

/****************************************************************************
 * SPI bus callback registration
 ****************************************************************************/

__EXPORT void board_spi_reset(int ms, int bus_mask)
{
	/* Reset SPI buses - stub implementation */
	(void)ms;
	(void)bus_mask;
}
