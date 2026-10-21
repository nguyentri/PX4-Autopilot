############################################################################
#
#   Copyright (c) 2026 PX4 Development Team. All rights reserved.
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

add_library(drivers_board
	init.c
	${PX4_SOURCE_DIR}/platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_ipc.c
	led.c
)

target_link_libraries(drivers_board
	PRIVATE
		nuttx_arch
		px4_layer
		parameters
		arch_hrt
		rzv2h_micro_hal
)

# Build the board-local px4io_cr8 module (I/O processor) so it is compiled into
# the firmware. It was previously present but wired into no build.
if(PX4_BOARD_LABEL STREQUAL "pwm")
	target_sources(drivers_board PRIVATE timer_config.cpp)
	target_link_libraries(drivers_board PRIVATE arch_io_pins)
	# This minimal image has no early uORB publisher or filesystem client to
	# pull these archives in incidentally. Declare the platform-init and BSON
	# fsync dependencies explicitly rather than relying on module link order.
	cmake_policy(SET CMP0079 NEW)
	target_link_libraries(px4_layer PRIVATE uORB)
	target_link_libraries(tinybson PRIVATE nuttx_fs)
	px4_add_module(
		MODULE drivers__rzv2h_io
		MAIN rzv2h_io
		SRCS ${CMAKE_CURRENT_LIST_DIR}/../px4io_cr8_1/io-supervisor.cpp
		DEPENDS rzv2h_demo arch_io_pins
	)
else()
	add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../px4io_cr8_1 px4io_cr8_1)
endif()
