############################################################################
#
#   Copyright (c) 2025 PX4 Development Team. All rights reserved.
#
############################################################################

px4_add_library(arch_hrt
	hrt.c
)

target_include_directories(arch_hrt PRIVATE
	${CMAKE_CURRENT_SOURCE_DIR}/../include
)
