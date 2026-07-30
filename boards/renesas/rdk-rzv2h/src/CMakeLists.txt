############################################################################
#
#   Copyright (c) 2025 PX4 Development Team. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
# 3. Neither the name PX4 nor the names of its contributors may be
#    used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
############################################################################

set(drivers_board_sources
	board_common.c
	init.c
	led.c
	system_stubs.c
	timer_config.cpp
	${PX4_SOURCE_DIR}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_volatile_paramfs.c
	${PX4_SOURCE_DIR}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_xspi_paramfs.c
)

if(CONFIG_DRIVERS_BAROMETER_BMP280)
	list(APPEND drivers_board_sources i2c.cpp)
endif()

if(CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250)
	list(APPEND drivers_board_sources spi.cpp)
endif()

# PX4's NuttX integration leaves the RDK board sources out of libboards (the
# generated archive contains only the generic boardctl/dummy objects). Link the
# shared SPI pinmux/CS implementation explicitly whenever the RZ/V2H SPI
# lower-half is enabled.
if(CONFIG_RZV_SPI)
	list(APPEND drivers_board_sources
		${PX4_SOURCE_DIR}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_spi.c
	)
endif()

add_library(drivers_board ${drivers_board_sources})

target_link_libraries(drivers_board
	PRIVATE
		arch_board_critmon
		arch_board_hw_info
		arch_board_reset
		arch_hrt
		arch_io_pins
		arch_led_pwm
		arch_version
		nuttx_arch
		nuttx_drivers
		px4_layer
		rzv2h_micro_hal
)

# DShot output variant (renesas_rdk-rzv2h_dshot) links the RZ/V2H DShot HAL.
# Only built/linked when CONFIG_DRIVERS_DSHOT is set, so the default PWM build
# is unaffected.
if(CONFIG_DRIVERS_DSHOT)
	target_link_libraries(drivers_board PRIVATE arch_dshot)
endif()

target_include_directories(drivers_board PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

add_custom_target(rzv2h_gpt_pwm_contract_test
	COMMAND
		${PYTHON_EXECUTABLE}
		${PX4_SOURCE_DIR}/test/rzv2h_gpt_pwm_contract_test.py
	WORKING_DIRECTORY ${PX4_SOURCE_DIR}
	COMMENT "Running RZ/V2H GPT/PWM source and pulse-phase contracts"
	VERBATIM
)

add_custom_target(rzv2h_board_gpio_contract_test ALL
	COMMAND
		${PYTHON_EXECUTABLE}
		${PX4_SOURCE_DIR}/test/rzv2h_board_gpio_contract_test.py
	WORKING_DIRECTORY ${PX4_SOURCE_DIR}
	COMMENT "Running RZ/V2H board GPIO ownership contracts"
	VERBATIM
)

add_custom_target(rzv2h_sih_demo_contract_test
	COMMAND
		${PYTHON_EXECUTABLE}
		${PX4_SOURCE_DIR}/test/rzv2h_sih_demo_contract_test.py
	WORKING_DIRECTORY ${PX4_SOURCE_DIR}
	COMMENT "Running RZ/V2H SIH configuration and startup contracts"
	VERBATIM
)

if(PX4_BOARD_LABEL STREQUAL "default" OR PX4_BOARD_LABEL STREQUAL "dshot")
	add_custom_target(rzv2h_payload_artifact_contract_test ALL
		COMMAND
			${PYTHON_EXECUTABLE}
			${PX4_SOURCE_DIR}/test/rzv2h_payload_artifact_contract_test.py
			--build-dir
			${PX4_BINARY_DIR}
			--config-name
			${PX4_CONFIG}
			--board-label
			${PX4_BOARD_LABEL}
		DEPENDS
			${PX4_BINARY_DIR}/${PX4_CONFIG}.px4
		WORKING_DIRECTORY ${PX4_SOURCE_DIR}
		COMMENT "Auditing resolved RZ/V2H payload firmware artifacts"
		VERBATIM
	)
endif()

if(PX4_BOARD_LABEL STREQUAL "sih" AND NOT NUTTX_CONFIG STREQUAL "sih")
	message(FATAL_ERROR "The RZ/V2H SIH target requires NUTTX_CONFIG=sih")
endif()

if(PX4_BOARD_LABEL STREQUAL "sih")
	add_custom_target(rzv2h_sih_artifact_contract_test ALL
		COMMAND
			${PYTHON_EXECUTABLE}
			${PX4_SOURCE_DIR}/test/rzv2h_sih_artifact_contract_test.py
			--build-dir
			${PX4_BINARY_DIR}
		DEPENDS
			${PX4_BINARY_DIR}/${PX4_CONFIG}.px4
			rzv2h_sih_demo_contract_test
		WORKING_DIRECTORY ${PX4_SOURCE_DIR}
		COMMENT "Auditing resolved RZ/V2H SIH firmware artifacts"
		VERBATIM
	)
endif()

# The CR8-1 bridge is a final-milestone feature. Independent CR8-0 images must
# not carry a dormant /dev/ipcc1 consumer.
if(CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE)
	add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../px4io_cr8_0 px4io_cr8_0)
endif()
