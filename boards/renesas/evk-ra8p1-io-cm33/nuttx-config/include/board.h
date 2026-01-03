/****************************************************************************
 * boards/renesas/evk-ra8p1-io-cm33/nuttx-config/include/board.h
 *
 * RA8P1 CM33 IO Processor - NuttX Board Configuration
 *
 * This file defines the clock tree, peripheral assignments, and GPIO
 * configurations for the Cortex-M33 core running as an IO processor
 * on the RA8P1 dual-core MCU.
 *
 ****************************************************************************/

#pragma once

#include <nuttx/config.h>

#ifndef __ASSEMBLY__
#  include <stdint.h>
#  include <stdbool.h>
#endif

/****************************************************************************
 * Clock Configuration
 *
 * CM33 operates in the PCLKD domain at 250 MHz.
 * Clock tree is configured by CM85 bootloader or hardware defaults.
 ****************************************************************************/

/* Main clocks */
#define BOARD_CPU_CLOCK             250000000   /* CM33 CPU clock: 250 MHz */
#define BOARD_PCLKD_CLOCK           250000000   /* Peripheral clock D: 250 MHz */
#define BOARD_PCLKB_CLOCK           125000000   /* Peripheral clock B: 125 MHz */
#define BOARD_PCLKA_CLOCK           250000000   /* Peripheral clock A: 250 MHz */

/* Timer clocks */
#define BOARD_GPT_CLOCK             BOARD_PCLKD_CLOCK   /* GPT timer clock */
#define BOARD_SCI_CLOCK             BOARD_PCLKB_CLOCK   /* SCI/UART clock */
#define BOARD_ADC_CLOCK             BOARD_PCLKA_CLOCK   /* ADC clock */

/****************************************************************************
 * LED Definitions
 *
 * 4 Status LEDs:
 * - LED_BLUE:   System heartbeat
 * - LED_AMBER:  Error/failsafe indicator
 * - LED_SAFETY: Safety switch status
 * - LED_GREEN:  Armed status
 ****************************************************************************/

#define BOARD_LED1                  0           /* Blue LED */
#define BOARD_LED2                  1           /* Amber LED */
#define BOARD_LED3                  2           /* Safety LED */
#define BOARD_LED4                  3           /* Green LED */
#define BOARD_NLEDS                 4

/* LED bits for use with board_userled_all() */
#define BOARD_LED1_BIT              (1 << BOARD_LED1)
#define BOARD_LED2_BIT              (1 << BOARD_LED2)
#define BOARD_LED3_BIT              (1 << BOARD_LED3)
#define BOARD_LED4_BIT              (1 << BOARD_LED4)

/* LED states for NuttX LED driver */
#define LED_STARTED                 0           /* LED1 */
#define LED_HEAPALLOCATE            1           /* LED2 */
#define LED_IRQSENABLED             2           /* LED3 */
#define LED_STACKCREATED            3           /* LED4 */
#define LED_INIRQ                   4           /* LED1 */
#define LED_SIGNAL                  5           /* LED2 */
#define LED_ASSERTION               6           /* LED3 */
#define LED_PANIC                   7           /* LED4 blink */

/****************************************************************************
 * Button Definitions
 ****************************************************************************/

#define BOARD_BUTTON_SAFETY         0           /* Safety switch button */
#define BOARD_NBUTTONS              1

/****************************************************************************
 * ADC Definitions (ADC_B for CM33)
 *
 * ADC_B channels used for battery monitoring and telemetry:
 * - Channel 0: Battery voltage (VBAT)
 * - Channel 1: Battery current
 * - Channel 2: Servo rail voltage
 * - Channel 3: RSSI (optional)
 * - Channel 4: Temperature (optional)
 ****************************************************************************/

/* ADC_B configuration */
#define BOARD_ADC_INSTANCE          1           /* ADC_B instance */
#define BOARD_ADC_RESOLUTION        12          /* 12-bit resolution */
#define BOARD_ADC_VREF_MV           3300        /* Reference voltage: 3.3V */

/* Channel assignments */
#define BOARD_ADC_VBAT_CHANNEL      0           /* AN000 - Battery voltage */
#define BOARD_ADC_CURRENT_CHANNEL   1           /* AN001 - Battery current */
#define BOARD_ADC_SERVO_RAIL_CHANNEL 2          /* AN002 - Servo rail */
#define BOARD_ADC_RSSI_CHANNEL      3           /* AN003 - RSSI */
#define BOARD_ADC_TEMP_CHANNEL      4           /* AN004 - Temperature */

/* ADC sampling configuration */
#define BOARD_ADC_SAMPLE_TIME       20          /* Sampling time in µs (for high-Z inputs) */
#define BOARD_ADC_NUM_CHANNELS      5           /* Total ADC channels */

/****************************************************************************
 * GPT Timer Definitions (Motor PWM/DShot)
 *
 * GPT timer assignments for motor outputs:
 * - GPT3:  Motor 1 (GTIOC3A)
 * - GPT5:  Motor 2 (GTIOC5A)
 * - GPT11: Motor 3 (GTIOC11A)
 * - GPT13: Motor 4 (GTIOC13A)
 *
 * GPT0 is reserved for CM85 HRT.
 * GPT1 is used for CM33 HRT (microsecond timing).
 ****************************************************************************/

/* HRT timer (microsecond resolution) */
#define BOARD_HRT_GPT               1           /* GPT1 for CM33 HRT */
#define BOARD_HRT_GPT_CHANNEL       0           /* Compare channel A */

/* Motor GPT assignments */
#define BOARD_MOTOR1_GPT            3           /* GPT3 */
#define BOARD_MOTOR2_GPT            5           /* GPT5 */
#define BOARD_MOTOR3_GPT            11          /* GPT11 */
#define BOARD_MOTOR4_GPT            13          /* GPT13 */

/* GPT clock prescaler for PWM frequency calculation */
/* PWM freq = PCLKD / (prescaler * period) */
#define BOARD_GPT_PRESCALER         1           /* No prescaling */

/****************************************************************************
 * UART/SCI Definitions (RC Input)
 *
 * SCI8 used for RC input (SBUS/CRSF/DSM).
 * Console on SCI0 (shared with CM85, optional).
 ****************************************************************************/

/* Console UART (optional, for debugging) */
#define BOARD_CONSOLE_SCI           0           /* SCI0 for console */
#define BOARD_CONSOLE_BAUD          115200

/* RC Input UART */
#define BOARD_RC_SCI                8           /* SCI8 for RC input */
#define BOARD_RC_BAUD_SBUS          100000      /* SBUS: 100 kbps (8E2, inverted) */
#define BOARD_RC_BAUD_CRSF          420000      /* CRSF: 420 kbps (8N1) */
#define BOARD_RC_BAUD_DSM           115200      /* DSM: 115.2 kbps (8N1) */

/****************************************************************************
 * IPC (Inter-Processor Communication) Definitions
 *
 * Shared memory region for CM85 ↔ CM33 communication.
 * Located at 0x220E0000, 64KB, non-cacheable.
 ****************************************************************************/

/* IPC shared memory layout */
#define BOARD_IPC_SHMEM_BASE        0x220E0000
#define BOARD_IPC_SHMEM_SIZE        0x10000     /* 64KB */

/* Ring buffer sizes within IPC region */
#define BOARD_IPC_TX_BUFFER_SIZE    4096        /* CM33 → CM85 */
#define BOARD_IPC_RX_BUFFER_SIZE    4096        /* CM85 → CM33 */

/* IPC doorbell interrupts */
#define BOARD_IPC_IRQ_CM85_TO_CM33  100         /* Doorbell: CM85 → CM33 */
#define BOARD_IPC_IRQ_CM33_TO_CM85  101         /* Doorbell: CM33 → CM85 */

/****************************************************************************
 * DMA/DMAC Definitions (DShot)
 *
 * DMAC channels used for DShot frame generation.
 ****************************************************************************/

#define BOARD_DMAC_CHANNEL_DSHOT1   0           /* DMA for Motor 1 DShot */
#define BOARD_DMAC_CHANNEL_DSHOT2   1           /* DMA for Motor 2 DShot */
#define BOARD_DMAC_CHANNEL_DSHOT3   2           /* DMA for Motor 3 DShot */
#define BOARD_DMAC_CHANNEL_DSHOT4   3           /* DMA for Motor 4 DShot */

/****************************************************************************
 * POEG (Port Output Enable for GPT)
 *
 * POEG provides hardware-level motor kill capability.
 * Triggers: CM85 timeout, brownout, watchdog.
 ****************************************************************************/

#define BOARD_POEG_GROUP            0           /* POEGG0 */
#define BOARD_POEG_OUTPUT_DISABLE   1           /* Output disable state */

/****************************************************************************
 * GPIO Pin Definitions
 *
 * Pin assignments for RA8P1 (303-pin PLBG package).
 * Format: GPIO_FUNC | GPIO_MODE | GPIO_PORT | GPIO_PIN
 ****************************************************************************/

/* GPIO port/pin encoding (RA8 style) */
#define GPIO_PORT0                  (0 << 8)
#define GPIO_PORT1                  (1 << 8)
#define GPIO_PORT2                  (2 << 8)
#define GPIO_PORT3                  (3 << 8)
#define GPIO_PORT4                  (4 << 8)
#define GPIO_PORT5                  (5 << 8)
#define GPIO_PORT6                  (6 << 8)
#define GPIO_PORT7                  (7 << 8)
#define GPIO_PORT8                  (8 << 8)
#define GPIO_PORT9                  (9 << 8)

#define GPIO_PIN(n)                 ((n) & 0xFF)

/* GPIO function encoding */
#define GPIO_INPUT                  (0 << 16)
#define GPIO_OUTPUT                 (1 << 16)
#define GPIO_FUNC_GPT               (2 << 16)
#define GPIO_FUNC_SCI               (3 << 16)
#define GPIO_FUNC_ADC               (4 << 16)

/* GPIO mode encoding */
#define GPIO_PULLUP                 (1 << 20)
#define GPIO_PULLDOWN               (2 << 20)
#define GPIO_PUSHPULL               (0 << 22)
#define GPIO_OPENDRAIN              (1 << 22)
#define GPIO_IRQ_RISING             (1 << 24)
#define GPIO_IRQ_FALLING            (2 << 24)
#define GPIO_IRQ_BOTH               (3 << 24)

/* GPIO initial value */
#define GPIO_VALUE_ZERO             (0 << 28)
#define GPIO_VALUE_ONE              (1 << 28)

/****************************************************************************
 * Board Initialization Functions
 ****************************************************************************/

#ifndef __ASSEMBLY__

/* Board initialization (called from NuttX start) */
void board_initialize(void);

/* Peripheral initialization */
void ra8_gpt_initialize(void);
void ra8_adc_initialize(void);
void ra8_sci_initialize(void);
void ra8_dmac_initialize(void);
void ra8_poeg_initialize(void);
void ra8_ipc_initialize(void);

/* GPIO functions */
void ra8_configgpio(uint32_t pinset);
void ra8_gpiowrite(uint32_t pinset, bool value);
bool ra8_gpioread(uint32_t pinset);

/* IPC doorbell trigger */
void ra8_ipc_doorbell_cm85(void);

/* POEG emergency kill */
void ra8_poeg_kill(void);
void ra8_poeg_release(void);

#endif /* __ASSEMBLY__ */
