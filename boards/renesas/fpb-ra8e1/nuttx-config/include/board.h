/****************************************************************************
 * boards/renesas/fpb-ra8e1/nuttx-config/include/board.h
 *
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.  The
 * ASF licenses this file to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance with the
 * License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.  See the
 * License for the specific language governing permissions and limitations
 * under the License.
 *
 ****************************************************************************/

#ifndef __BOARDS_RENESAS_FPB_RA8E1_NUTTX_CONFIG_INCLUDE_BOARD_H
#define __BOARDS_RENESAS_FPB_RA8E1_NUTTX_CONFIG_INCLUDE_BOARD_H

/****************************************************************************
 * Included Files
 ****************************************************************************/

#include <nuttx/config.h>

/****************************************************************************
 * Pre-processor Definitions
 ****************************************************************************/

/* Clocking *****************************************************************/

/* The FPB-RA8E1 board has a 20MHz crystal oscillator */

#define BOARD_XTAL_FREQUENCY    20000000  /* 20MHz crystal */
#define BOARD_HOCO_FREQUENCY    20000000  /* 20MHz HOCO */
#define BOARD_MOCO_FREQUENCY     8000000  /* 8MHz MOCO */
#define BOARD_LOCO_FREQUENCY       32768  /* 32.768kHz LOCO */

/* PLL Configuration for RA8E1 - 360MHz system clock */
#define BOARD_PLL_SOURCE        BOARD_HOCO_FREQUENCY /* Use HOCO as PLL source */
#define BOARD_PLL_MUL           18                   /* PLL multiplier: 20MHz * 18 = 360MHz */
#define BOARD_PLL_DIV           1                    /* PLL input divider */

/* System Clock Configuration */
#define BOARD_ICLK_FREQUENCY    360000000  /* 360MHz CPU clock */
#define BOARD_PCLKA_FREQUENCY   120000000  /* 120MHz PCLKA */
#define BOARD_PCLKB_FREQUENCY   60000000   /* 60MHz PCLKB */
#define BOARD_PCLKC_FREQUENCY   60000000   /* 60MHz PCLKC */
#define BOARD_PCLKD_FREQUENCY   120000000  /* 120MHz PCLKD (GPT) */
#define BOARD_FCLK_FREQUENCY    60000000   /* 60MHz Flash clock */

/* UART/SCI Pin Definitions */
#define GPIO_SCI0_RX   GPIO_RXD0_MISO0_SCL0_C  /* P609 - Telemetry */
#define GPIO_SCI0_TX   GPIO_TXD0_MOSI0_SDA0_C  /* P610 - Telemetry */

#define GPIO_SCI2_RX   GPIO_RXD2_MISO2_SCL2_A  /* P802 - Console */
#define GPIO_SCI2_TX   GPIO_TXD2_MOSI2_SDA2_A  /* P801 - Console */

#define GPIO_SCI3_RX   GPIO_RXD3_MISO3_SCL3_B  /* P309 - RC Input */
#define GPIO_SCI3_TX   GPIO_TXD3_MOSI3_SDA3_B  /* P310 - RC Input */

/* Board-specific pin definitions removed - defined in board_config.h instead */

/* LED Configuration for NuttX */
#define LED_STARTED       0  /* LED1 */
#define LED_HEAPALLOCATE  0  /* LED1 */
#define LED_IRQSENABLED   0  /* LED1 */
#define LED_STACKCREATED  1  /* LED1 ON */
#define LED_INIRQ         2  /* LED2 ON */
#define LED_SIGNAL        2  /* LED2 ON */
#define LED_ASSERTION     2  /* LED2 ON */
#define LED_PANIC         3  /* LED2 BLINK */

/****************************************************************************
 * Public Data
 ****************************************************************************/

#ifndef __ASSEMBLY__

#undef EXTERN
#if defined(__cplusplus)
#define EXTERN extern "C"
extern "C"
{
#else
#define EXTERN extern
#endif

/****************************************************************************
 * Public Function Prototypes
 ****************************************************************************/

#undef EXTERN
#if defined(__cplusplus)
}
#endif

#endif /* __ASSEMBLY__ */

#endif /* __BOARDS_RENESAS_FPB_RA8E1_NUTTX_CONFIG_INCLUDE_BOARD_H */
