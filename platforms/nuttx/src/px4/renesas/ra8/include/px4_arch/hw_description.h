/****************************************************************************
 *
 *   Copyright (C) 2025 PX4 Development Team. All rights reserved.
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

#pragma once

#include <stdint.h>

#include <px4_platform_common/constexpr_util.h>

/*
 * GPIO Port/Pin Definitions for RA8
 */

namespace GPIO
{

enum Port : uint32_t {
	PortInvalid = 0,
	Port0,
	Port1,
	Port2,
	Port3,
	Port4,
	Port5,
	Port6,
	Port7,
	Port8,
	Port9,
	Port10,
	Port11,
	Port12,
	Port13,
	Port14,
	Port15
};

enum Pin : uint32_t {
	Pin0,  Pin1,  Pin2,  Pin3,  Pin4,  Pin5,  Pin6,  Pin7,
	Pin8,  Pin9,  Pin10, Pin11, Pin12, Pin13, Pin14, Pin15
};

/* GPIO pinset structure for NuttX RA8 compatibility */
typedef struct gpio_pinset
{
    uint8_t port;
    uint8_t pin;
    uint32_t cfg;
} gpio_pinset_t;

/* GPIO type alias for PX4 compatibility */
using GPIOPin = gpio_pinset_t;

/* Helper function to create GPIO pinset */
constexpr gpio_pinset_t GPIO_PINSET(Port port, Pin pin, uint32_t config = 0) {
	return {static_cast<uint8_t>(port), static_cast<uint8_t>(pin), config};
}

} // namespace GPIO

/*
 * SPI
 */

namespace SPI
{

enum Bus : int {
	SPI1 = 1,
	SPI2 = 2,
	SPI3 = 3
};

using CS = GPIO::GPIOPin;
using DRDY = GPIO::GPIOPin;

} // namespace SPI

/*
 * Timer
 */

namespace Timer
{

enum Timer : uint32_t {
	TimerInvalid = 0,
	Timer0,
	Timer1,
	Timer2,
	Timer3,
	Timer4,
	Timer5,
	Timer6,
	Timer7
};

enum Channel : uint32_t {
	Channel1 = 1,
	Channel2,
	Channel3,
	Channel4
};

struct TimerChannel {
    Timer timer;
    Channel channel;
    constexpr TimerChannel(Timer t, Channel c) : timer(t), channel(c) {}
};

} // namespace Timer

/*
 * I2C
 */

namespace I2C
{

enum Bus : int {
	I2C1 = 1,
	I2C2 = 2,
	I2C3 = 3
};

} // namespace I2C
