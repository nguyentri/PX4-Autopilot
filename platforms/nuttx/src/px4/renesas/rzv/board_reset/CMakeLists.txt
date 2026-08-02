############################################################################
px4_add_library(arch_board_reset
	board_reset.c
)

# board_reset() calls the architecture-provided up_systemreset(). Keep the
# NuttX archive after this library in the final static-link order.
target_link_libraries(arch_board_reset PRIVATE nuttx_arch)
