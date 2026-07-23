px4_add_module(
	MODULE px4io_m33
	MAIN px4io_m33
	STACK_MAIN 2048
	PRIORITY 100
	SRCS
		px4io_m33.cpp
		sharedmem_transport.cpp
		# pwm_dshot.cpp
		# dma_driver.cpp
		# safety_switch.cpp
	DEPENDS
	)
