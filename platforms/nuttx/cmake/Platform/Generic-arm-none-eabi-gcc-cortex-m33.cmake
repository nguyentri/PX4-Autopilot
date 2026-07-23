# Cortex-M33 flags matching NuttX Toolchain.defs exactly
# TOOLCHAIN_MTUNE := -mtune=cortex-m33
# TOOLCHAIN_MARCH := -march=armv8-m.main$(EXTCPUFLAGS)

# Architecture flags logic from NuttX armv8-m/Toolchain.defs for Cortex-M33
if(CONFIG_ARM_DSP)
	set(march_flags "-march=armv8-m.main+dsp")
else()
	set(march_flags "-march=armv8-m.main")
endif()

# FPU flags logic from NuttX - Cortex-M33 uses fpv5-sp-d16 (single precision)
if(CONFIG_ARCH_FPU)
	set(mfpu_flags "-mfpu=fpv5-sp-d16")
	# Float ABI logic from NuttX
	if(CONFIG_ARM_FPU_ABI_SOFT)
		set(mfloat_flags "-mfloat-abi=softfp ${mfpu_flags}")
	else()
		set(mfloat_flags "-mfloat-abi=hard ${mfpu_flags}")
	endif()
else()
	set(mfloat_flags "-mfloat-abi=soft")
endif()

# Final CPU flags: $(TOOLCHAIN_MARCH) $(TOOLCHAIN_MTUNE) -mthumb $(TOOLCHAIN_MFLOAT)
# Note: Only use -mtune, not -mcpu, to avoid conflicts with -march
set(cpu_flags "${march_flags} -mtune=cortex-m33 -mthumb ${mfloat_flags}")

set(CMAKE_C_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS "${cpu_flags}" CACHE STRING "" FORCE)
set(CMAKE_ASM_FLAGS "${cpu_flags} -D__ASSEMBLY__" CACHE STRING "" FORCE)
