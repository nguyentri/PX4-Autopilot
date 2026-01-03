#pragma once

#include <nuttx/config.h>

#ifndef __ASSEMBLY__
#  include <stdint.h>
#  include <stdbool.h>
#endif

/* Clocking *****************************************************************/
/* The CM33 runs at 250MHz (PCLKD domain) */
#define BOARD_CPU_CLOCK      250000000

/* LED definitions **********************************************************/
/* 3 LEDs */
#define BOARD_LED1           0
#define BOARD_LED2           1
#define BOARD_LED3           2
#define BOARD_NLEDS          3

/* LED bits for use with board_userled_all() */
#define BOARD_LED1_BIT       (1 << BOARD_LED1)
#define BOARD_LED2_BIT       (1 << BOARD_LED2)
#define BOARD_LED3_BIT       (1 << BOARD_LED3)

/* Button definitions *******************************************************/
#define BOARD_BUTTON_SAFETY  0
#define BOARD_NBUTTONS       1

/* ADC definitions **********************************************************/
/* VBAT, Current, Servo Rail */
#define BOARD_ADC_VBAT_CHANNEL       0
#define BOARD_ADC_CURRENT_CHANNEL    1
#define BOARD_ADC_SERVO_RAIL_CHANNEL 2

/* GPIO Pin Definitions *****************************************************/
/* These need to be mapped to actual RA8P1 pins.
 * Assuming some standard mappings or placeholders.
 */

/* Safety Switch: GPIO Input with IRQ */
#define GPIO_SAFETY_SWITCH   (GPIO_INPUT | GPIO_PULLUP | GPIO_INT_BOTHEDGES | GPIO_PORT1 | GPIO_PIN0)

/* LEDs */
#define GPIO_LED1            (GPIO_OUTPUT | GPIO_VALUE_ONE | GPIO_PORT1 | GPIO_PIN1)
#define GPIO_LED2            (GPIO_OUTPUT | GPIO_VALUE_ONE | GPIO_PORT1 | GPIO_PIN2)
#define GPIO_LED3            (GPIO_OUTPUT | GPIO_VALUE_ONE | GPIO_PORT1 | GPIO_PIN3)

/* POEG (Port Output Enable for GPT) */
#define GPIO_POEG_KILL       (GPIO_OUTPUT | GPIO_VALUE_ZERO | GPIO_PORT1 | GPIO_PIN4)

/* IPC Interrupts */
/* Mailbox interrupt from CM85 */
#define RA8_IPC_IRQ_CM85     100 /* Placeholder IRQ number */

#ifndef __ASSEMBLY__
extern void board_initialize(void);
#endif
