/****************************************************************************
 *
 *   Copyright (c) 2012-2025 PX4 Development Team. All rights reserved.
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
 * @file mixer.cpp
 *
 * Control channel input/output mixer and failsafe.
 * Updated for RA8P1 CM33 IO processor with PWM/DShot support.
 *
 * @author Lorenz Meier <lorenz@px4.io>
 * @author PX4 Development Team
 */

#include <px4_platform_common/px4_config.h>
#include <syslog.h>

#include <sys/types.h>
#include <stdbool.h>
#include <float.h>
#include <string.h>
#include <math.h>

#include <drivers/drv_pwm_output.h>
#include <drivers/drv_hrt.h>

#include <rc/sbus.h>

#include "px4io.h"
#include "pwm_out.h"

extern "C" {
	/* #define DEBUG */
}

/*
 * Maximum interval in us before FMU signal is considered lost
 */
#define FMU_INPUT_DROP_LIMIT_US		500000

/* Failsafe activation delay after FMU loss (us) */
#define FAILSAFE_DELAY_US           100000

/* current servo arm/disarm state */
static volatile bool mixer_servos_armed = false;
static volatile bool should_arm = false;
static volatile bool should_arm_nothrottle = false;
static volatile bool should_always_enable_pwm = false;

static bool new_fmu_data = false;
static uint64_t last_fmu_update = 0;
static uint64_t fmu_lost_time = 0;

extern int _sbus_fd;

/* selected control values and count for mixing */
enum mixer_source {
	MIX_NONE,
	MIX_DISARMED,
	MIX_FAILSAFE,
	MIX_FMU,
};

/**
 * @brief Initialize mixer subsystem
 */
void mixer_init(void)
{
	/* Initialize PWM output driver */
	int ret = pwm_out_init();
	if (ret < 0) {
		syslog(LOG_ERR, "PWM output init failed: %d\n", ret);
		return;
	}

	/* Default to PWM mode */
	ret = pwm_out_set_mode(OUTPUT_MODE_PWM);
	if (ret < 0) {
		syslog(LOG_ERR, "PWM mode set failed: %d\n", ret);
		return;
	}

	/* Set default PWM rate */
	pwm_out_set_frequency(PWM_FREQ_DEFAULT);

	/* Set default disarmed and failsafe values */
	for (unsigned i = 0; i < PX4IO_SERVO_COUNT; i++) {
		pwm_out_set_disarmed(i, r_page_servo_disarmed[i]);
		pwm_out_set_failsafe(i, r_page_servo_failsafe[i]);
	}

	syslog(LOG_INFO, "Mixer initialized\n");
}

/**
 * @brief Check FMU communication status
 */
static mixer_source check_fmu_status(void)
{
	/* Check that we are receiving fresh data from the FMU */
	irqstate_t irq_flags = enter_critical_section();
	const hrt_abstime fmu_data_received_time = system_state.fmu_data_received_time;
	leave_critical_section(irq_flags);

	if ((fmu_data_received_time == 0) ||
	    hrt_elapsed_time(&fmu_data_received_time) > FMU_INPUT_DROP_LIMIT_US) {

		/* Too long without FMU input */
		if (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_OK) {
			isr_debug(1, "FMU RX timeout");
			fmu_lost_time = hrt_absolute_time();
		}

		atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_OK);

		/* Check if we should enter failsafe */
		if (fmu_lost_time > 0 &&
		    hrt_elapsed_time(&fmu_lost_time) > FAILSAFE_DELAY_US) {
			return MIX_FAILSAFE;
		}

		return MIX_DISARMED;

	} else {
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_OK);
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FMU_INITIALIZED);
		fmu_lost_time = 0;

		if (fmu_data_received_time > last_fmu_update) {
			new_fmu_data = true;
			last_fmu_update = fmu_data_received_time;
		}

		return MIX_FMU;
	}
}

/**
 * @brief Determine arming requirements
 */
static void update_arming_state(void)
{
	/*
	 * Decide whether the servos should be armed right now.
	 *
	 * We must be armed, and we must have a PWM source; either raw from
	 * FMU or from the mixer.
	 */
	should_arm = (r_status_flags & PX4IO_P_STATUS_FLAGS_INIT_OK)
		     && (r_setup_arming & PX4IO_P_SETUP_ARMING_FMU_ARMED);

	should_arm_nothrottle = ((r_status_flags & PX4IO_P_STATUS_FLAGS_INIT_OK)
				 && ((r_setup_arming & PX4IO_P_SETUP_ARMING_FMU_PREARMED)
				     || (r_status_flags & PX4IO_P_STATUS_FLAGS_RAW_PWM)));

	/* Enable PWM output if FMU is running */
	should_always_enable_pwm = ((r_status_flags & PX4IO_P_STATUS_FLAGS_INIT_OK)
				    && (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_OK));
}

/**
 * @brief Apply output values based on mixer source
 */
static void apply_outputs(mixer_source source)
{
	bool armed_output = should_arm || should_arm_nothrottle || (source == MIX_FAILSAFE);
	bool disarmed_output = (!armed_output && should_always_enable_pwm)
			       || (r_setup_arming & PX4IO_P_SETUP_ARMING_LOCKDOWN);

	/* Update failsafe flag */
	if (source == MIX_FAILSAFE) {
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
	} else {
		atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
	}

	/* Apply servo values based on source */
	if (source == MIX_FAILSAFE) {
		/* Apply failsafe values */
		for (unsigned i = 0; i < PX4IO_SERVO_COUNT; i++) {
			if (r_page_servos[i] != 0) {
				r_page_servos[i] = r_page_servo_failsafe[i];
			}
		}
	} else if (source == MIX_DISARMED || disarmed_output) {
		/* Apply disarmed values */
		for (unsigned i = 0; i < PX4IO_SERVO_COUNT; i++) {
			if (r_page_servos[i] != 0) {
				r_page_servos[i] = r_page_servo_disarmed[i];
			}
		}
	}
	/* MIX_FMU/MIX_NONE: Values already set by transport layer */

	/* Arm/disarm PWM outputs */
	bool needs_to_arm = (should_arm || should_arm_nothrottle || should_always_enable_pwm);

	if (r_setup_arming & PX4IO_P_SETUP_ARMING_LOCKDOWN) {
		needs_to_arm = true;
	}

	if (needs_to_arm && !mixer_servos_armed) {
		/* Need to arm */
		pwm_out_arm(true);
		mixer_servos_armed = true;
		atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED);
		isr_debug(5, "> PWM enabled");

	} else if (!needs_to_arm && mixer_servos_armed) {
		/* Need to disarm */
		pwm_out_arm(false);
		mixer_servos_armed = false;
		atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED);
		isr_debug(5, "> PWM disabled");
	}

	/* Update servo outputs if armed */
	if (mixer_servos_armed && (armed_output || disarmed_output)) {
		for (unsigned i = 0; i < PX4IO_SERVO_COUNT; i++) {
			pwm_out_set(i, r_page_servos[i]);
		}

		/* Set S.BUS outputs if enabled */
		if (r_setup_features & PX4IO_P_SETUP_FEATURES_SBUS2_OUT) {
			sbus2_output(_sbus_fd, r_page_servos, PX4IO_SERVO_COUNT);
		} else if (r_setup_features & PX4IO_P_SETUP_FEATURES_SBUS1_OUT) {
			sbus1_output(_sbus_fd, r_page_servos, PX4IO_SERVO_COUNT);
		}
	}
}

/**
 * @brief Main mixer tick function - called from main loop
 */
void mixer_tick(void)
{
	/* Check FMU status and determine mixing source */
	mixer_source source = check_fmu_status();

	/* Do not mix if we have raw PWM and FMU is ok */
	if ((r_status_flags & PX4IO_P_STATUS_FLAGS_RAW_PWM) &&
	    (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_OK)) {
		source = MIX_NONE;
		memcpy(r_page_servos, r_page_direct_pwm, sizeof(uint16_t) * PX4IO_SERVO_COUNT);
	}

	/* Update arming state */
	update_arming_state();

	/*
	 * Check if FMU is still alive, if not, terminate the flight
	 */
	if (REG_TO_BOOL(r_setup_flighttermination) &&
	    (source == MIX_DISARMED) &&
	    should_arm &&
	    (r_status_flags & PX4IO_P_STATUS_FLAGS_FMU_INITIALIZED)) {
		/* FMU is dead -> terminate flight */
		atomic_modify_or(&r_setup_arming, PX4IO_P_SETUP_ARMING_FORCE_FAILSAFE);
	}

	/* Check if we should force failsafe */
	if (r_setup_arming & PX4IO_P_SETUP_ARMING_FORCE_FAILSAFE) {
		source = MIX_FAILSAFE;
	}

	/* Apply outputs */
	apply_outputs(source);

	/* Clear new data flag */
	new_fmu_data = false;
}

/**
 * @brief Set output mode (PWM or DShot)
 */
int mixer_set_mode(output_mode_t mode)
{
	if (mixer_servos_armed) {
		syslog(LOG_ERR, "Cannot change mode while armed\n");
		return -EBUSY;
	}

	return pwm_out_set_mode(mode);
}

/**
 * @brief Set PWM frequency
 */
int mixer_set_pwm_rate(uint32_t rate_hz)
{
	return pwm_out_set_frequency(rate_hz);
}

/**
 * @brief Trigger emergency stop
 */
void mixer_emergency_stop(void)
{
	pwm_out_emergency_stop();
	mixer_servos_armed = false;
	atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_OUTPUTS_ARMED);
	atomic_modify_or(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
	syslog(LOG_CRIT, "Emergency stop activated\n");
}

/**
 * @brief Clear emergency stop
 */
void mixer_clear_emergency(void)
{
	pwm_out_clear_emergency();
	atomic_modify_clear(&r_status_flags, PX4IO_P_STATUS_FLAGS_FAILSAFE);
	syslog(LOG_INFO, "Emergency stop cleared\n");
}

/**
 * @brief Check if mixer is armed
 */
bool mixer_is_armed(void)
{
	return mixer_servos_armed;
}
