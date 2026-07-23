/****************************************************************************
 * platforms/nuttx/src/px4/renesas/rzv2h/version/version.c
 *
 * RZV2H board version detection
 ****************************************************************************/

#include <px4_platform_common/px4_config.h>
#include <stdint.h>

/* Undefine macros from board_common.h so we can implement the functions */
#undef board_get_hw_version
#undef board_get_hw_revision
#undef board_get_hw_type_name

/****************************************************************************
 * Public Functions
 ****************************************************************************/

__EXPORT int board_get_hw_version(void)
{
	/* RDK-RZV2H board version 0 */
	return 0;
}

__EXPORT int board_get_hw_revision(void)
{
	/* RDK-RZV2H revision 0 */
	return 0;
}

__EXPORT const char *board_get_hw_type_name(void)
{
	return "RDK-RZV2H";
}
