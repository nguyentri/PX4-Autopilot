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
	PortA,
	PortB,
	PortC,
	PortD,
	PortE,
	PortF
};

enum Pin : uint32_t {
	Pin0 = 0,  Pin1,  Pin2,  Pin3,  Pin4,  Pin5,  Pin6,  Pin7,
	Pin8,  Pin9,  Pin10, Pin11, Pin12, Pin13, Pin14, Pin15
};

struct GPIOPin {
	Port port;
	Pin pin;
};


} // namespace GPIO

static inline constexpr uint32_t getGPIOPort(GPIO::Port port)
{
	// Port encoding: GPIO_PORT_SHIFT = 28 (bits 31-28) per ra_gpio.h
	switch (port) {
	case GPIO::PortInvalid: return 0;
	case GPIO::Port0: return (0 << 28);  // Port 0
	case GPIO::Port1: return (1 << 28);  // Port 1
	case GPIO::Port2: return (2 << 28);  // Port 2
	case GPIO::Port3: return (3 << 28);  // Port 3
	case GPIO::Port4: return (4 << 28);  // Port 4
	case GPIO::Port5: return (5 << 28);  // Port 5
	case GPIO::Port6: return (6 << 28);  // Port 6
	case GPIO::Port7: return (7 << 28);  // Port 7
	case GPIO::Port8: return (8 << 28);  // Port 8
	case GPIO::Port9: return (9 << 28);  // Port 9
    case GPIO::PortA: return (10 << 28); // Port 10
    case GPIO::PortB: return (11 << 28); // Port 11
    case GPIO::PortC: return (12 << 28); // Port 12
    case GPIO::PortD: return (13 << 28); // Port 13
    case GPIO::PortE: return (14 << 28); // Port 14
    case GPIO::PortF: return (15 << 28); // Port 15
	default: break;
	}
	return 0;
}

static inline constexpr uint32_t getGPIOPin(GPIO::Pin pin)
{
	// Pin encoding: GPIO_PIN_SHIFT = 24 (bits 27-24) per ra_gpio.h
	switch (pin) {
	case GPIO::Pin0: return (0 << 24);   // Pin 0
	case GPIO::Pin1: return (1 << 24);   // Pin 1
	case GPIO::Pin2: return (2 << 24);   // Pin 2
	case GPIO::Pin3: return (3 << 24);   // Pin 3
	case GPIO::Pin4: return (4 << 24);   // Pin 4
	case GPIO::Pin5: return (5 << 24);   // Pin 5
	case GPIO::Pin6: return (6 << 24);   // Pin 6
	case GPIO::Pin7: return (7 << 24);   // Pin 7
	case GPIO::Pin8: return (8 << 24);   // Pin 8
	case GPIO::Pin9: return (9 << 24);   // Pin 9
	case GPIO::Pin10: return (10 << 24); // Pin 10
	case GPIO::Pin11: return (11 << 24); // Pin 11
	case GPIO::Pin12: return (12 << 24); // Pin 12
	case GPIO::Pin13: return (13 << 24); // Pin 13
	case GPIO::Pin14: return (14 << 24); // Pin 14
	case GPIO::Pin15: return (15 << 24); // Pin 15
	}
	return 0;
}

/*
 * SPI
 */

namespace SPI
{

enum Bus : int {
	SPI0 = 0,
	SPI1 = 1,
	SPI2 = 2
};

using CS = GPIO::GPIOPin;

/**
 * DRDY (Data Ready) pin configuration for RA8
 * Includes IRQ number for proper interrupt routing
 */
struct DRDY {
	GPIO::Port port{GPIO::PortInvalid};
	GPIO::Pin pin{GPIO::Pin0};
	uint32_t irq{0};  ///< IRQ number (0-31) for this pin, 0 if not used
};

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
	Timer7,
    Timer8,
    Timer9,
    Timer10,
    Timer11,
    Timer12,
    Timer13,
    Timer14,
    Timer15
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
	I2C0 = 0,
	I2C1 = 1
};

} // namespace I2C
