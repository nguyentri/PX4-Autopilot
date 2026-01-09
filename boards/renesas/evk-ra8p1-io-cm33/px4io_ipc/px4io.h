/****************************************************************************
 *
 *   Copyright (c) 2012-2022 PX4 Development Team. All rights reserved.
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
 * @file px4io.h
 *
 * General defines and structures for the PX4IO module firmware.
 * Updated for RA8P1 CM33 IO processor.
 *
 * @author Lorenz Meier <lorenz@px4.io>
 * @author PX4 Development Team
 */

#pragma once

#include <px4_platform_common/px4_config.h>

#include <stdbool.h>
#include <stdint.h>

#include <board_config.h>

#include "protocol.h"

/* Forward declaration for output mode type */
#ifdef __cplusplus
#include "pwm_out.h"
#else
typedef enum {
	OUTPUT_MODE_NONE = 0,
	OUTPUT_MODE_PWM,
	OUTPUT_MODE_DSHOT150,
	OUTPUT_MODE_DSHOT300,
	OUTPUT_MODE_DSHOT600,
	OUTPUT_MODE_DSHOT1200,
} output_mode_t;
#endif

__BEGIN_DECLS

/*
 * Constants and limits.
 */
#define PX4IO_BL_VERSION			3
#define PX4IO_SERVO_COUNT			8
#define PX4IO_CONTROL_CHANNELS		8

#define PX4IO_RC_INPUT_CHANNELS		18
#define PX4IO_RC_MAPPED_CONTROL_CHANNELS		8 /**< This is the maximum number of channels mapped/used */

/*
 * Debug logging
 */

#ifdef DEBUG
# include <debug.h>
# define debug(fmt, args...)	syslog(LOG_DEBUG,fmt "\n", ##args)
#else
# define debug(fmt, args...)	do {} while(0)
#endif

/*
 * Registers.
 */
extern volatile uint16_t	r_page_status[];	/* PX4IO_PAGE_STATUS */
extern uint16_t			r_page_servos[];	/* PX4IO_PAGE_SERVOS */
extern uint16_t			r_page_direct_pwm[];	/* PX4IO_PAGE_DIRECT_PWM */
extern uint16_t			r_page_raw_rc_input[];	/* PX4IO_PAGE_RAW_RC_INPUT */

extern volatile uint16_t	r_page_setup[];		/* PX4IO_PAGE_SETUP */
extern uint16_t			r_page_servo_failsafe[]; /* PX4IO_PAGE_FAILSAFE_PWM */
extern uint16_t			r_page_servo_disarmed[];	/* PX4IO_PAGE_DISARMED_PWM */

/*
 * Register aliases.
 *
 * Handy aliases for registers that are widely used.
 */
#define r_status_flags		r_page_status[PX4IO_P_STATUS_FLAGS]
#define r_status_alarms		r_page_status[PX4IO_P_STATUS_ALARMS]

#define r_raw_rc_count		r_page_raw_rc_input[PX4IO_P_RAW_RC_COUNT]
#define r_raw_rc_values		(&r_page_raw_rc_input[PX4IO_P_RAW_RC_BASE])
#define r_raw_rc_flags		r_page_raw_rc_input[PX4IO_P_RAW_RC_FLAGS]

#define r_setup_features	r_page_setup[PX4IO_P_SETUP_FEATURES]
#define r_setup_arming		r_page_setup[PX4IO_P_SETUP_ARMING]
#define r_setup_pwm_rates	r_page_setup[PX4IO_P_SETUP_PWM_RATES]
#define r_setup_pwm_defaultrate	r_page_setup[PX4IO_P_SETUP_PWM_DEFAULTRATE]
#define r_setup_pwm_altrate	r_page_setup[PX4IO_P_SETUP_PWM_ALTRATE]

#define r_setup_sbus_rate	r_page_setup[PX4IO_P_SETUP_SBUS_RATE]

#define r_setup_flighttermination	r_page_setup[PX4IO_P_SETUP_ENABLE_FLIGHTTERMINATION]

/*
 * System state structure.
 */
struct sys_state_s {

	uint64_t	rc_channels_timestamp_received;

	/**
	 * Last FMU receive time, in microseconds since system boot
	 */
	volatile uint64_t	fmu_data_received_time;

};

extern struct sys_state_s system_state;

# define ENABLE_SBUS_OUT(_s)		px4_arch_gpiowrite(GPIO_SBUS_OENABLE, !(_s))

# define VDD_SERVO_FAULT		(!px4_arch_gpioread(GPIO_SERVO_FAULT_DETECT))

# define PX4IO_ADC_CHANNEL_COUNT	2
# define ADC_VSERVO			4
# define ADC_RSSI			5

#define PX4_CRITICAL_SECTION(cmd)	{ irqstate_t flags = px4_enter_critical_section(); cmd; px4_leave_critical_section(flags); }

void atomic_modify_or(volatile uint16_t *target, uint16_t modification);
void atomic_modify_clear(volatile uint16_t *target, uint16_t modification);
void atomic_modify_and(volatile uint16_t *target, uint16_t modification);

/*
 * Mixer
 */
extern void	mixer_tick(void);

/**
 * Safety button/LED.
 */
extern void	safety_button_init(void);
extern void	failsafe_led_init(void);
extern void	heartbeat_blink(void);
extern void	ring_blink(void);

/**
 * FMU communications
 */
extern void	interface_init(void);
extern void	interface_tick(void);
extern void	interface_get_stats(uint32_t *rx_msgs, uint32_t *tx_msgs,
				    uint32_t *crc_errors, uint32_t *sync_errors);
extern bool	interface_fmu_ok(void);

/**
 * Register space
 */
extern int	registers_set(uint8_t page, uint8_t offset, const uint16_t *values, unsigned num_values);
extern int	registers_get(uint8_t page, uint8_t offset, uint16_t **values, unsigned *num_values);

/**
 * Sensors/misc inputs
 */
extern int	adc_init(void);
extern void	adc_tick(void);
extern uint16_t	adc_measure(unsigned channel);
extern uint16_t	adc_get_vbat_mv(void);
extern int16_t	adc_get_current_ma(void);
extern uint16_t	adc_get_vservo_mv(void);
extern uint16_t	adc_get_temperature_cdeg(void);
extern bool	adc_is_brownout(void);

/**
 * R/C receiver handling.
 *
 * Input functions return true when they receive an update from the RC controller.
 */
extern void	controls_init(void);
extern void	controls_tick(void);

/**
 * Mixer
 */
extern void	mixer_init(void);
extern int	mixer_set_mode(output_mode_t mode);
extern int	mixer_set_pwm_rate(uint32_t rate_hz);
extern void	mixer_emergency_stop(void);
extern void	mixer_clear_emergency(void);
extern bool	mixer_is_armed(void);

/**
 * Servo min/max values
 */
extern uint16_t	r_page_servo_control_min[];
extern uint16_t	r_page_servo_control_max[];

/**
 * Watchdog
 */
extern void	watchdog_init(void);
extern void	watchdog_pet(void);

/**
 * Memory/System
 */
extern void	update_mem_usage(void);
extern void	check_reboot(void);
extern void	show_debug_messages(void);

/** global debug level for isr_debug() */
extern volatile uint8_t debug_level;

/** send a debug message to the console */
extern void	isr_debug(uint8_t level, const char *fmt, ...);

/** schedule a reboot */
extern void schedule_reboot(uint32_t time_delta_usec);

__END_DECLS
