/****************************************************************************
 *
 *   Copyright (c) 2025 PX4 Development Team. All rights reserved.
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
 * @file hw_description.h
 *
 * Hardware description types for RZV2H
 */

#pragma once

#include <stdint.h>

/* GPIO port and pin definitions for RZV2H */
namespace GPIO
{
enum Port : uint8_t {
	Port0 = 0,
	Port1,
	Port2,
	Port3,
	Port4,
	Port5,
	Port6,
	Port7,
	Port8,
	Port9,
	PortA = 10,
	PortB = 11,
	PortInvalid = 0xFF
};

enum Pin : uint8_t {
	Pin0 = 0,
	Pin1,
	Pin2,
	Pin3,
	Pin4,
	Pin5,
	Pin6,
	Pin7,
	Pin8,
	Pin9,
	Pin10,
	Pin11,
	Pin12,
	Pin13,
	Pin14,
	Pin15,
	PinInvalid = 0xFF
};

struct GPIOPin {
	Port port;
	Pin pin;
};

} // namespace GPIO

/* Timer definitions for RZV2H GPT */
namespace Timer
{
enum Timer : uint8_t {
	Timer0 = 0,
	Timer1,
	Timer2,
	Timer3,
	Timer4,
	Timer5,
	Timer6,
	Timer7,
	Timer10 = 10,
	Timer11,
	Timer12,
	Timer13,
	Timer14,
	Timer15,
	Timer16,
	Timer17,
	TimerInvalid = 0xFF
};

enum Channel : uint8_t {
	Channel1 = 1,  /* GTIOCA */
	Channel2 = 2,  /* GTIOCB */
	ChannelInvalid = 0xFF
};

struct TimerChannel {
	Timer timer;
	Channel channel;
};

} // namespace Timer

/* SPI definitions for RZV2H */
namespace SPI
{
enum Bus : int {
	SPI0 = 0,
	SPI1 = 1
};

struct CS {
	GPIO::Port port;
	GPIO::Pin pin;
};

struct DRDY {
	GPIO::Port port;
	GPIO::Pin pin;
};

} // namespace SPI

/* Helper functions to convert GPIO enums to uint32_t pinset encoding */
static inline constexpr uint32_t getGPIOPort(GPIO::Port port)
{
	// Port encoding: bits 27-24 (shifted << 24)
	// Direct mapping: Port0=0, Port1=1, ..., PortA=10, PortB=11
	return ((uint32_t)port << 24);
}

static inline constexpr uint32_t getGPIOPin(GPIO::Pin pin)
{
	// Pin encoding: bits 19-16 (shifted << 16)
	// Direct mapping: Pin0=0, Pin1=1, ..., Pin15=15
	return ((uint32_t)pin << 16);
}

/* I2C definitions for RZV2H */
namespace I2C
{
struct Bus {
	uint8_t bus_num;
};

} // namespace I2C
