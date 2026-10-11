"""Host declarations and extraction for real RZ/V descriptor/IRQ code."""

from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RZV = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
HAL = ROOT / "platforms/nuttx/src/px4/renesas/rzv/include"
BOARD = ROOT / "boards/renesas/rdk-rzv2h/src"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def body(source, name):
    match = re.search(r"\b" + name + r"\s*\([^;{}]*\)\s*\{", source)
    if match is None:
        raise AssertionError("missing real function: " + name)
    start = source.index("{", match.start())
    depth = 0
    for index in range(start, len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError("unclosed function: " + name)


def host_headers(directory):
    # Only unrelated OS/CPU declarations are replaced. GPIO ABI, SPI types,
    # driver IDs, descriptor helpers and the board table use actual headers.
    shims = {
        "nuttx/config.h": "#pragma once\n#define CONFIG_RZV2H_GROUP 1\n",
        "nuttx/compiler.h": "#pragma once\n#define FAR\n#define __EXPORT\n",
        "nuttx/irq.h": "#pragma once\ntypedef int (*xcpt_t)(int, void *, void *);\n",
        "arch/rzv/chip.h": "#pragma once\n",
        "arch/rzv/irq.h": "#pragma once\n#define RZV_IRQ_NEXTINT 400\n",
        "px4_platform_common/px4_config.h": "#pragma once\n#define __EXPORT\n",
        "px4_platform_common/defines.h": "#pragma once\n",
        "px4_platform_common/board_common.h": "#pragma once\n",
        "px4_arch/micro_hal.h": "#pragma once\n",
        "drivers/device/spi.h": "#pragma once\n",
        "nuttx/spi/spi.h": "#pragma once\n",
    }
    for name, content in shims.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def compile_descriptor(directory, name, defines):
    compiler = shutil.which("c++")
    if compiler is None:
        raise RuntimeError("host C++ compiler is required")
    command = [compiler, "-std=c++14", "-Wall", "-Wextra", "-Werror",
               "-Wno-unused-parameter", "-D__PX4_NUTTX", "-DCONFIG_SPI",
               "-DCONFIG_RZV_SPI0"]
    # Production chip headers expose these board definitions before the PX4
    # board header. Include the real header to catch conflicting shared names.
    command += ["-include", str(ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/include/board.h")]
    for include in (directory, BOARD, HAL, RZV, ROOT / "platforms/common/include", ROOT / "src"):
        command += ["-I", str(include)]
    command += ["-D" + define for define in defines]
    binary = directory / name
    command += [str(ROOT / "test/rzv2h-simple-spi-descriptor-test.cpp"), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return binary, result


def compile_irq(directory):
    gpio = read("platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c")
    board = read("boards/renesas/rdk-rzv2h/src/init.c")
    declarations = "\n".join(re.search(pattern, gpio, re.S).group(0) for pattern in (
        r"enum rzv_gpio_irq_path_e\s*\{.*?\};",
        r"struct rzv_gpio_irq_s\s*\{.*?\};",
    ))
    raw = body(gpio, "rzv_gpio_irq_initialize")
    guard = body(board, "rdk_rzv2h_gpio_irq_initialize_once")
    pinmap = (RZV / "hardware/rzv2h/rzv2h_pinmap.h").read_text()
    slots = re.search(r"^#define MAX_GPIO_IRQS\s+(.+)$", pinmap, re.M).group(1)
    source = """#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint32_t gpio_pinset_t;
typedef int (*xcpt_t)(int, void *, void *);
typedef unsigned irqstate_t;
#define MAX_GPIO_IRQS HOST_SLOT_COUNT
static unsigned raw_calls, depth;
static irqstate_t enter_critical_section(void) { ++depth; return 0; }
static void leave_critical_section(irqstate_t state) { (void)state; assert(depth == 1); --depth; }
""".replace("HOST_SLOT_COUNT", slots) + declarations + "\nstatic struct rzv_gpio_irq_s g_gpio_irqs[MAX_GPIO_IRQS];\n"
    source += "static void rzv_gpio_irq_initialize(void) { ++raw_calls; assert(depth == 1); }\n"
    # Count/critical instrumentation wraps the exact lower-half initializer.
    source = source.replace("++raw_calls; assert(depth == 1); }",
                            "++raw_calls; assert(depth == 1); " + raw[1:-1] + " }")
    source += "static void rdk_rzv2h_gpio_irq_initialize_once(void) " + guard
    source += """
static int callback(int irq, void *context, void *arg)
{ (void)irq; (void)context; ++*(unsigned *)arg; return 0; }
int main(void)
{
  unsigned delivered = 0;
  rdk_rzv2h_gpio_irq_initialize_once();
  assert(raw_calls == 1 && depth == 0);
  for (unsigned i = 0; i < MAX_GPIO_IRQS; ++i)
    assert(g_gpio_irqs[i].icu_slot == -1 && !g_gpio_irqs[i].allocated);
  g_gpio_irqs[0].allocated = true;
  g_gpio_irqs[0].pinset = 0x94000120u;
  g_gpio_irqs[0].callback = callback;
  g_gpio_irqs[0].arg = &delivered;
  g_gpio_irqs[0].icu_slot = 299;
  rdk_rzv2h_gpio_irq_initialize_once();
  rdk_rzv2h_gpio_irq_initialize_once();
  assert(raw_calls == 1 && depth == 0);
  assert(g_gpio_irqs[0].allocated && g_gpio_irqs[0].icu_slot == 299);
  assert(g_gpio_irqs[0].pinset == 0x94000120u && g_gpio_irqs[0].callback == callback);
  assert(g_gpio_irqs[0].arg == &delivered);
  g_gpio_irqs[0].callback(299, NULL, g_gpio_irqs[0].arg);
  assert(delivered == 1);
  return 0;
}
"""
    path = directory / "irq.c"
    path.write_text(source, encoding="utf-8")
    binary = directory / "irq"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(path),
                    "-o", str(binary)], check=True, capture_output=True, text=True)
    return binary
