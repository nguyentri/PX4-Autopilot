/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
 *
 ****************************************************************************/

/**
 * @file led_pwm.c
 *
 * RZV2H LED PWM (stub - LED control via GPIO)
 */

#include <px4_platform_common/px4_config.h>
#include <stdint.h>

int led_pwm_servo_set(unsigned led, uint8_t brightness)
{
	/* LED PWM not implemented - using GPIO control instead */
	(void)led;
	(void)brightness;
	return 0;
}

int led_pwm_servo_init(void)
{
	/* LED PWM initialization not needed */
	return 0;
}

void led_pwm_servo_deinit(void)
{
	/* LED PWM deinitialization not needed */
}
