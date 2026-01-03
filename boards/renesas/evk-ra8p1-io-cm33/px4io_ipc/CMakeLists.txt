############################################################################
#
#   Copyright (c) 2015-2025 PX4 Development Team. All rights reserved.
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

# PX4IO firmware library for RA8P1 CM33 IO processor
# Supports: PWM/DShot output, RC input, ADC telemetry, IPC transport

option(PX4IO_PERF "Enable px4io perf counters" OFF)
option(PX4IO_DEBUG "Enable px4io debug output" OFF)

# Source files
set(PX4IO_SRCS
	adc.cpp
	controls.cpp
	ipc.cpp
	mixer.cpp
	pwm_out.cpp
	px4io.cpp
	registers.c
	safety_button.cpp
	transport_sharedmem.cpp
)

add_library(px4iofirmware ${PX4IO_SRCS})

set_property(GLOBAL APPEND PROPERTY PX4_MODULE_LIBRARIES px4iofirmware)

# Include directories
target_include_directories(px4iofirmware
	PUBLIC
		${CMAKE_CURRENT_SOURCE_DIR}
)

# Link dependencies
target_link_libraries(px4iofirmware
	PUBLIC
		arch_io_pins
		arch_watchdog_iwdg
		nuttx_apps
		nuttx_arch
		nuttx_c
		nuttx_mm
		rc
)

# Optional: DMA support for DShot
if(CONFIG_RA_DMAC)
	target_compile_definitions(px4iofirmware PRIVATE CONFIG_RA_DMAC=1)
endif()

# Optional: GPT timer support
if(CONFIG_RA_GPT)
	target_compile_definitions(px4iofirmware PRIVATE CONFIG_RA_GPT=1)
endif()

# Optional: POEG support for emergency stop
if(CONFIG_RA_POEG)
	target_compile_definitions(px4iofirmware PRIVATE CONFIG_RA_POEG=1)
endif()

# Performance counters
if(PX4IO_PERF)
	target_compile_definitions(px4iofirmware PRIVATE PX4IO_PERF)
	target_link_libraries(px4iofirmware PRIVATE perf)
endif()

# Debug output
if(PX4IO_DEBUG)
	target_compile_definitions(px4iofirmware PRIVATE PX4IO_DEBUG)
endif()

# Compiler optimizations for real-time performance
target_compile_options(px4iofirmware
	PRIVATE
		-O2
		-ffunction-sections
		-fdata-sections
)
