############################################################################
#
#   Copyright (c) 2025 PX4 Development Team. All rights reserved.
#
############################################################################

px4_add_library(rzv2h_micro_hal
	micro_hal.cpp
)

target_link_libraries(rzv2h_micro_hal INTERFACE nuttx_arch)

target_include_directories(rzv2h_micro_hal PRIVATE
	${CMAKE_CURRENT_SOURCE_DIR}/../include
)
