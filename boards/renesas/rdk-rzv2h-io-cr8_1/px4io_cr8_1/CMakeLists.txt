px4_add_module(
	MODULE px4io_cr8
	MAIN px4io_cr8
	STACK_MAIN 2048
	PRIORITY 100
	SRCS
		px4io_cr8.cpp
		sharedmem_transport.cpp
		# rc_decoder.cpp
		# can_uavcan.cpp
		# battery_monitor.cpp
		# safety_monitor.cpp
		# failsafe.cpp
		# uorb_bridge.cpp
	DEPENDS
	)
