#!/usr/bin/env python3
"""Source/config regressions for the isolated RZ/V2H SCI-SPI sample."""

from pathlib import Path
import re
import importlib.util
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    pattern = rf"^[^\n;{{}}]*\b{name}\s*\([^;{{}}]*\)\s*{{"
    match = re.search(pattern, source, re.M)
    if match is None:
        raise AssertionError(f"function {name} not found")
    start = match.end() - 1

    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]

    raise AssertionError(f"function {name} has no closing brace")


class SciSpiSampleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.board = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rzv2h_sci_spi.c"
        )
        cls.defconfig = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/configs/sci-spi-loopback/defconfig"
        )

    def test_cmddata_is_a_noop_for_generic_character_transfers(self) -> None:
        body = function_body(self.board, "rzv_sci_spi_cmddata")
        self.assertIn("UNUSED(dev)", body)
        self.assertIn("UNUSED(devid)", body)
        self.assertIn("UNUSED(cmd)", body)
        self.assertIn("return OK", body)
        self.assertNotIn("return -ENODEV", body)

    def test_sample_selects_one_bus_spitool_consumer(self) -> None:
        self.assertIn("CONFIG_SYSTEM_SPITOOL=y", self.defconfig)
        self.assertIn("CONFIG_SPITOOL_MAXBUS=0", self.defconfig)
        self.assertIn("CONFIG_SPITOOL_DEFFREQ=1000000", self.defconfig)

    def test_sample_uses_the_documented_loopback_wiring_and_oracle(self) -> None:
        guide = read("docs/renesas/validation/validation-checklist.md")
        self.assertIn("P5_0 to MOSI, P5_1 to MISO and P6_0 to SCK", guide)
        self.assertIn("spi exch -b 0 -f 1000000 -m 0 -w 8 -x 4 a55ac33c", guide)
        self.assertIn("`A5 5A C3 3C`", guide)
        body = function_body(self.board, "rzv2h_sci0_spi_setup")
        for pin in ("RZV_SCI0_MOSI_PIN", "RZV_SCI0_MISO_PIN", "RZV_SCI0_SCK_PIN"):
            self.assertIn(f"rzv_gpioconfig({pin})", body)

NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
ARCH = NUTTX / "arch/arm/src/rzv"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h"


def without_includes(source):
    return re.sub(r"^\s*#\s*include[^\n]*$", "", source, flags=re.M)


def definition(source, signature):
    name = signature.split("(")[0].split()[-1].lstrip("*")
    return signature + "\n" + function_body(source, name) + "\n"


def compile_and_run(code, arguments=(), defines=()):
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory(prefix="rzv2h-sci-channels-") as directory:
        path = Path(directory)
        (path / "test.c").write_text(code)
        result = subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", *defines,
             str(path / "test.c"), "-o", str(path / "test")],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        result = subprocess.run([str(path / "test"), *arguments],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)


def initializer_harness(mode, source=None):
    """Compile the real initializer, hardware setup, calculator and types."""
    source = source or (ARCH / f"rzv_sci_{mode}.c").read_text()
    enabled = "\n".join(f"#define CONFIG_RZV_SCI{ch}_{mode.upper()} 1"
                        for ch in range(10))
    prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
#define OK 0
#define FAR
#define CODE
#define irqstate_t unsigned
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define ARM_DSB() ((void)0)
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
#define i2cerr(...) ((void)0)
#define i2cinfo(...) ((void)0)
#define TEST_UNUSED __attribute__((unused))
#define SCI_I2C_CHANNEL_COUNT 10u
typedef struct { bool ready; } sem_t;
typedef struct { bool ready; } mutex_t;
enum spi_mode_e { SPIDEV_MODE0, SPIDEV_MODE1, SPIDEV_MODE2, SPIDEV_MODE3 };
struct spi_ops_s { int unused; };
struct spi_dev_s { const struct spi_ops_s *ops; };
struct i2c_ops_s { int unused; };
struct i2c_master_s { const struct i2c_ops_s *ops; };
struct i2c_msg_s;
#if !defined(TEST_UNOWNED) && !defined(TEST_ROUTE)
# define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1
#endif
#ifdef CONFIG_RZV2H_BUILD_CM33
# define RZV_IRQ_FIRST 16
#else
# define RZV_IRQ_FIRST 32
#endif
'''
    prelude += enabled + f'''
#ifdef TEST_DISABLED
# undef CONFIG_RZV_SCI9_{mode.upper()}
#endif
#ifdef TEST_CONFLICT
# define CONFIG_RZV_SCI9 1
#endif
'''
    if mode == "i2c":
        prelude += r'''
#ifdef TEST_ROUTE
# define BOARD_SCI0_I2C_SCL_GPIO 100u
# define BOARD_SCI0_I2C_SDA_GPIO 101u
# define BOARD_SCI0_I2C_SCL_RESET_GPIO 102u
# define BOARD_SCI0_I2C_SDA_RESET_GPIO 103u
# define BOARD_SCI7_I2C_SCL_GPIO 170u
# define BOARD_SCI7_I2C_SDA_GPIO 171u
# define BOARD_SCI7_I2C_SCL_RESET_GPIO 172u
# define BOARD_SCI7_I2C_SDA_RESET_GPIO 173u
#endif
'''
    for name in ("hardware/rzv_sci.h", "hardware/rzv_sci_spi.h",
                 "hardware/rzv_cpg.h", "rzv_clock.h",
                 f"rzv_sci_{mode}_internal.h"):
        prelude += without_includes((ARCH / name).read_text())
    prelude += without_includes((NUTTX / "arch/arm/include/rzv/rzv2h_irq.h").read_text())
    for name in ("g_sci_base", "g_sci_clk"):
        prelude += re.search(rf"static const uint32_t {name}\[.*?\n\}};",
                             source, re.S).group() + "\n"
    prelude += f"static struct rzv_sci_{mode}_priv_s g_sci_{mode}_priv[10];\n"
    prelude += f"static const struct {'spi' if mode == 'spi' else 'i2c'}_ops_s g_sci_{mode}_ops = {{0}};\n"
    boundary = r'''
static const uint32_t expected_clocks[] = {
  RZV_CPG_CLK_SCI0, RZV_CPG_CLK_SCI1, RZV_CPG_CLK_SCI2,
  RZV_CPG_CLK_SCI3, RZV_CPG_CLK_SCI4, RZV_CPG_CLK_SCI5,
  RZV_CPG_CLK_SCI6, RZV_CPG_CLK_SCI7, RZV_CPG_CLK_SCI8,
  RZV_CPG_CLK_SCI9
};
static unsigned clocks[10], modules[10], writes[10], semaphores, mutexes;
static unsigned pin_calls, current, attempts, failure, touches;
static bool installed[512], enabled[512];
static uint32_t registers[10][256];
static unsigned clock_channel(uint32_t id) {
  for (unsigned ch = 0; ch < 10; ++ch) if (expected_clocks[ch] == id) return ch;
  assert(false); return 0;
}
int rzv_clock_enable(uint32_t id) {
  unsigned ch = clock_channel(id); assert(ch == current); ++touches;
  if (failure == 1) return -ETIMEDOUT;
  assert(!clocks[ch]); ++clocks[ch]; return 0;
}
int rzv_clock_disable(uint32_t id) {
  unsigned ch = clock_channel(id); assert(ch == current && clocks[ch] == 1 && !modules[ch]);
  --clocks[ch]; return 0;
}
int rzv_module_unreset(uint32_t id) {
  unsigned ch = clock_channel(id); assert(ch == current && clocks[ch] == 1);
  if (failure == 2) return -ETIMEDOUT;
  assert(!modules[ch]); ++modules[ch]; return 0;
}
int rzv_module_reset(uint32_t id) {
  unsigned ch = clock_channel(id); assert(ch == current && modules[ch] == 1);
  --modules[ch]; return 0;
}
uint32_t rzv_clock_get_rate(enum rzv_clock_id_e id) {
  assert(id == RZV_CLOCK_P5CLK); return failure == 9 ? 0 : 100000000;
}
static unsigned address_channel(uintptr_t address) {
  assert(address >= RZV_SCI0_BASE && address < RZV_SCI0_BASE + 10 * 0x400);
  unsigned ch = (address - RZV_SCI0_BASE) / 0x400;
  assert(ch == current && clocks[ch] == 1 && modules[ch] == 1); return ch;
}
static uint32_t TEST_UNUSED getreg32(uintptr_t address) {
  unsigned ch = address_channel(address);
  assert((address - RZV_SCI0_BASE) % 0x400 != RZV_SCI_CESR_OFFSET);
  return registers[ch][((address - RZV_SCI0_BASE) % 0x400) / 4];
}
static uint8_t TEST_UNUSED getreg8(uintptr_t address) {
  (void)address_channel(address);
  assert((address - RZV_SCI0_BASE) % 0x400 == RZV_SCI_CESR_OFFSET);
  return failure == 3 ? SCI_CESR_RIST | SCI_CESR_TIST : 0;
}
static void putreg32(uint32_t value, uintptr_t address) {
  unsigned ch = address_channel(address); ++writes[ch];
  registers[ch][((address - RZV_SCI0_BASE) % 0x400) / 4] = value;
}
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; }
static void TEST_UNUSED up_udelay(unsigned delay) { assert(delay > 0); }
static void TEST_UNUSED nxmutex_init(mutex_t *m) { assert(!m->ready); m->ready = true; ++mutexes; }
static void TEST_UNUSED nxmutex_destroy(mutex_t *m) { assert(m->ready); m->ready = false; --mutexes; }
static void nxsem_init(sem_t *s, int shared, int value) {
  (void)shared; (void)value; assert(!s->ready); s->ready = true; ++semaphores;
}
static void nxsem_destroy(sem_t *s) { assert(s->ready); s->ready = false; --semaphores; }
static int irq_attach(int irq, int (*handler)(int,void *,void *), void *arg) {
  (void)handler; (void)arg;
  assert(irq >= (int)RZV_IRQ_SCI_ERI(current) && irq <= (int)RZV_IRQ_SCI_TEI(current));
  assert(!installed[irq] && !enabled[irq]);
  if (++attempts + 3 == failure) return -EIO;
  installed[irq] = true; return 0;
}
static void irq_detach(int irq) { assert(installed[irq] && !enabled[irq]); installed[irq] = false; }
static void up_enable_irq(int irq) { assert(installed[irq]); enabled[irq] = true; }
static void up_disable_irq(int irq) { assert(installed[irq]); enabled[irq] = false; }
static void TEST_UNUSED rzv_gic_set_irq_type(int irq, bool edge) {
  assert(installed[irq] && !enabled[irq]);
  assert(edge == (irq == (int)RZV_IRQ_SCI_TXI(current) || irq == (int)RZV_IRQ_SCI_RXI(current)));
}
static int TEST_UNUSED rzv_gpioconfig(uint32_t pin) { (void)pin; ++pin_calls; return 0; }
'''
    for name in (("rzv_sci_spi_txi_isr", "rzv_sci_spi_rxi_isr", "rzv_sci_spi_tei_isr", "rzv_sci_spi_eri_isr")
                 if mode == "spi" else ("sci_i2c_txi_isr", "sci_i2c_tei_isr")):
        boundary += f"int {name}(int irq, void *context, void *arg) {{ (void)irq; (void)context; (void)arg; return 0; }}\n"
    functions = without_includes((ARCH / f"rzv_sci_{mode}_clock.c").read_text())
    if mode == "spi":
        functions += definition(source, "void rzv_sci_spi_sync_delay(void)")
        functions += definition(source, "static uint32_t sci_spi_ccr3_format(const struct rzv_sci_spi_priv_s *priv)")
        functions += definition(source, "static void sci_spi_write_ccr3(struct rzv_sci_spi_priv_s *priv, uint32_t ccr3)")
        functions += definition(source, "static int sci_spi_hw_configure(struct rzv_sci_spi_priv_s *priv)")
        init = "struct spi_dev_s *rzv_sci_spi_initialize(int channel)"
    else:
        prelude += r'''
#define SCI_I2C_CHANNEL_COUNT 10u
#define SCI_I2C_CESR_TIMEOUT 10000u
#define SCI_I2C_DEFAULT_SCL_HZ 100000u
#define SCI_I2C_CCR2_BCP 4u
#define SCI_I2C_PCLK_FALLBACK_HZ RZV_CLOCK_P5CLK_HZ
'''
        for signature in (
            "static int sci_i2c_wait_idle(struct rzv_sci_i2c_priv_s *priv)",
            "static void sci_i2c_clear_status(struct rzv_sci_i2c_priv_s *priv)",
            "static void sci_i2c_unwind_init(struct rzv_sci_i2c_priv_s *priv)",
            "static int sci_i2c_config_pins(struct rzv_sci_i2c_priv_s *priv)",
            "static int sci_i2c_hw_init(struct rzv_sci_i2c_priv_s *priv, uint32_t scl_hz)",
        ):
            functions += definition(source, signature)
        init = "struct i2c_master_s *rzv_sci_i2c_initialize(int channel)"
    functions += definition(source, init)
    device = "spi_dev_s" if mode == "spi" else "i2c_master_s"
    functions += definition(source, f"int rzv_sci_{mode}_sample_instance(struct {device} *dev, unsigned int *channel, uintptr_t *base)")
    main = r'''
int main(void) {
  unsigned before = touches;
  assert(INIT(-1) == NULL && INIT(10) == NULL && INIT(INT_MAX) == NULL && touches == before);
#if defined(TEST_DISABLED) || defined(TEST_CONFLICT)
  assert(INIT(9) == NULL && !touches && !pin_calls && !semaphores && !mutexes);
#elif defined(TEST_ROUTE)
  const unsigned routed[] = {0, 7};
  for (unsigned index = 0; index < 2; ++index) {
    current = routed[index]; attempts = failure = 0;
    assert(INIT(current) == &PRIV[current].dev);
    assert(PRIV[current].pins_configured && PRIV[current].recovery_configured);
    assert(PRIV[current].scl_gpio == 100 + 10 * current);
    assert(PRIV[current].sda_gpio == 101 + 10 * current);
    assert(pin_calls == (index + 1) * 2);
  }
  before = touches;
  for (current = 0; current < 10; ++current) if (current != 0 && current != 7)
    assert(INIT(current) == NULL);
  assert(touches == before && pin_calls == 4);
#elif defined(TEST_UNOWNED)
  for (current = 0; current < 10; ++current) assert(INIT(current) == NULL);
  assert(!touches && !pin_calls && !semaphores && !mutexes);
#else
  for (current = 0; current < 10; ++current) {
    for (failure = 1; failure <= FAILURES; ++failure) {
      attempts = 0;
      unsigned saved[10]; memcpy(saved, writes, sizeof(saved));
      assert(INIT(current) == NULL);
      assert(!clocks[current] && !modules[current] && !PRIV[current].initialized && !PRIV[current].initializing);
      assert(semaphores == current * SEMS && mutexes == current * MUTEXES);
      for (unsigned irq = RZV_IRQ_SCI_ERI(current); irq <= RZV_IRQ_SCI_TEI(current); ++irq)
        assert(!installed[irq] && !enabled[irq]);
      for (unsigned other = 0; other < 10; ++other) if (other != current) {
        assert(saved[other] == writes[other]);
        assert(clocks[other] == (other < current) && modules[other] == (other < current));
      }
    }
    failure = 9; attempts = 0; /* Exercise the runtime clock fallback too. */
    assert(INIT(current) == &PRIV[current].dev);
    assert(PRIV[current].channel == current && PRIV[current].base == RZV_SCI0_BASE + current * 0x400);
    assert(PRIV[current].clk_id == expected_clocks[current]);
    unsigned actual_channel = UINT_MAX; uintptr_t actual_base = 0;
    assert(INSTANCE(&PRIV[current].dev, &actual_channel, &actual_base) == 0);
    assert(actual_channel == current && actual_base == PRIV[current].base);
    assert(INSTANCE(&PRIV[current].dev, NULL, &actual_base) == -EINVAL);
    assert(INSTANCE(NULL, &actual_channel, &actual_base) == -EINVAL);
    struct DEVICE foreign = {0};
    actual_channel = UINT_MAX; actual_base = UINTPTR_MAX;
    assert(INSTANCE(&foreign, &actual_channel, &actual_base) == -ENODEV);
    assert(actual_channel == UINT_MAX && actual_base == UINTPTR_MAX);
    assert((registers[current][RZV_SCI_CCR3_OFFSET / 4] & SCI_CCR3_MOD_MASK) == EXPECTED_MODE);
    assert(!registers[current][RZV_SCI_CCR0_OFFSET / 4] && writes[current]);
    assert(clocks[current] == 1 && modules[current] == 1);
    assert(semaphores == (current + 1) * SEMS && mutexes == (current + 1) * MUTEXES);
    assert(PRIV[current].irq_txi == (int)(RZV_IRQ_FIRST + 116 + 6 * current));
    assert(PRIV[current].irq_tei == (int)(RZV_IRQ_FIRST + 117 + 6 * current));
    before = touches; unsigned saved_writes = writes[current], saved_attempts = attempts;
    assert(INIT(current) == &PRIV[current].dev);
    assert(touches == before && writes[current] == saved_writes && attempts == saved_attempts);
  }
  assert(!pin_calls);
#endif
  return 0;
}
'''
    settings = f"\n#define INIT rzv_sci_{mode}_initialize\n#define PRIV g_sci_{mode}_priv\n"
    settings += f"#define INSTANCE rzv_sci_{mode}_sample_instance\n#define DEVICE {device}\n"
    settings += ("#define FAILURES 7\n#define SEMS 1\n#define MUTEXES 1\n#define EXPECTED_MODE SCI_CCR3_MOD_SPI\n"
                 if mode == "spi" else
                 "#define FAILURES 5\n#define SEMS 2\n#define MUTEXES 0\n#define EXPECTED_MODE SCI_CCR3_MOD_I2C\n")
    return prelude + boundary + functions + settings + main


class SciSpiInitialization(unittest.TestCase):
    def test_real_initializer_all_channels_rolls_back_and_retries(self):
        for core in ((), ("-DCONFIG_RZV2H_BUILD_CM33=1",)):
            with self.subTest(core=core):
                compile_and_run(initializer_harness("spi"), defines=core)

    def test_disabled_and_uart_conflicted_channels_have_no_side_effects(self):
        for variant in ("TEST_DISABLED", "TEST_CONFLICT"):
            with self.subTest(variant=variant):
                compile_and_run(initializer_harness("spi"), defines=(f"-D{variant}=1",))

class SciChannelReference(unittest.TestCase):
    def test_cmsis_declares_one_register_type_for_all_ten_channels(self):
        header = ROOT / ("refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/"
                         "rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/R9A09G057H/cr/iodefines/sci_b_iodefine.h")
        self.assertTrue(header.is_file(), "Local read-only CMSIS reference is required")
        text = header.read_text()
        for channel in range(10):
            self.assertRegex(text, rf"#define R_SCI{channel}\s+\(\(R_SCI_B0_Type \*\) R_SCI{channel}_BASE\)")
            self.assertRegex(text, rf"#define R_SCI{channel}_BASE\s+0x{0x12800c00 + channel * 0x400:08X}")
        features = header.parents[7] / "mcu/rzv2h/cr/bsp_feature.h"
        self.assertRegex(features.read_text(), r"BSP_FEATURE_SCI_CHANNELS\s+\(0x3FFU\)")


def board_harness(mode, channels, *, controlled=True, register=True):
    source = without_includes((BOARD / f"src/rzv2h_sci_{mode}.c").read_text())
    state = re.search(r"struct rzv2h_bus_sample_state_s\s*\{.*?\n\};",
                      (BOARD / "include/rzv2h-sample-test.h").read_text(), re.S).group()
    prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
#define OK 0
#define UNUSED(x) ((void)(x))
#define spiinfo(...) ((void)0)
#define spierr(...) ((void)0)
#define i2cerr(...) ((void)0)
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define BOARD_SCI_I2C_BUS_BASE 10
#define BOARD_SCI7_I2C_BUS 7
#define GPIO_TXD0_MOSI0_DA0_P5_0_M1 1u
#define GPIO_RXD0_MISO0_SCL0_P5_1_M1 2u
#define GPIO_SCK0_P6_0_M1 3u
#define PORT6 0x600u
#define PIN1 0x10u
#define RZV_GPIO_OUTPUT 1u
#define RZV_GPIO_DRVSTR_NORMAL 2u
#define RZV_GPIO_INITIAL_HIGH 4u
#define SPIDEV_NONE(n) (n)
#define SPIDEV_USER(n) (0x1000u | (n))
#define SPI_STATUS_PRESENT 1u
#define TEST_UNUSED __attribute__((unused))
struct spi_dev_s { unsigned channel; uintptr_t base; };
struct i2c_master_s { unsigned channel; uintptr_t base; };
static unsigned pins, selects;
static unsigned last_pin;
static bool last_level;
static int lower_failure = -1, register_failure = -1;
static unsigned lower_calls[10], register_calls[10];
static const unsigned i2c_buses[10] TEST_UNUSED = {10, 11, 12, 13, 14, 15, 16, 7, 18, 19};
static int TEST_UNUSED rzv_gpioconfig(uint32_t pin) { ++pins; last_pin = pin; return 0; }
static void TEST_UNUSED rzv_gpiowrite(uint32_t pin, bool level) {
  ++selects; last_pin = pin; last_level = level;
}
'''
    prelude += f"#define CONFIG_RZV_SCI_{mode.upper()} 1\n"
    for channel in channels:
        prelude += f"#define CONFIG_RZV_SCI{channel}_{mode.upper()} 1\n"
    if controlled:
        prelude += "#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1\n"
    if register:
        prelude += f"#define CONFIG_{mode.upper()}_DRIVER 1\n#define TEST_REGISTER 1\n"
    device = "spi_dev_s" if mode == "spi" else "i2c_master_s"
    prelude += state + f'''
static struct {device} devices[10];
static struct {device} *rzv_sci_{mode}_initialize(int channel) {{
  assert(channel >= 0 && channel < 10); ++lower_calls[channel];
  devices[channel].channel = channel;
  devices[channel].base = 0x12800c00u + (unsigned)channel * 0x400u;
  return channel == lower_failure ? NULL : &devices[channel];
}}
static int rzv_sci_{mode}_sample_instance(struct {device} *dev, unsigned int *channel, uintptr_t *base) {{
  if (dev == NULL) return -ENODEV;
  for (unsigned index = 0; index < 10; ++index) if (dev == &devices[index]) {{
    *channel = dev->channel; *base = dev->base; return 0;
  }}
  return -ENODEV;
}}
static uint32_t rzv2h_sci_{mode}_sample_transfers_at(unsigned int channel) {{
  assert(channel < 10); return channel + 100;
}}
static int {mode}_register(struct {device} *dev, int bus) {{
  unsigned channel = dev->channel;
  assert(dev == &devices[channel]);
  assert(bus == (int){('channel' if mode == 'spi' else 'i2c_buses[channel]')});
  ++register_calls[channel]; return (int)channel == register_failure ? -EACCES : 0;
}}
'''
    if not register:
        prelude = prelude.replace(f"static int {mode}_register(", f"static int TEST_UNUSED {mode}_register(")
    setup = "board_sci_spi_initialize" if mode == "spi" else "rzv2h_sci_i2c_setup"
    settings = f"\n#define SETUP {setup}\n#define STATE rzv2h_sci_{mode}_sample_state_at\n#define WRAPPER rzv2h_sci_{mode}_sample_state\n"
    settings += f"#define FIRST {channels[0]}\n#define LAST {channels[-1]}\n"
    settings += "static const unsigned selected_channels[] = {" + ",".join(map(str, channels)) + "};\n"
    main = r'''
int main(void) {
#ifdef TEST_REJECT
  assert(SETUP() == TEST_REJECT);
  for (unsigned ch = 0; ch < 10; ++ch) assert(!lower_calls[ch] && !register_calls[ch]);
  assert(!pins && !selects);
#else
  lower_failure = LAST;
  assert(SETUP() == -ENODEV && lower_calls[LAST] == 1);
  lower_failure = -1;
#ifdef TEST_REGISTER
  register_failure = LAST;
  assert(SETUP() == -EACCES && lower_calls[LAST] == 2 && register_calls[LAST] == 1);
#endif
  register_failure = -1;
  assert(SETUP() == 0);
  for (unsigned i = 0; i < sizeof(selected_channels)/sizeof(selected_channels[0]); ++i) {
    unsigned ch = selected_channels[i];
    assert(lower_calls[ch] == (ch == LAST ? 2 : 1));
    struct rzv2h_bus_sample_state_s state;
    assert(STATE(ch, &state) == 0 && state.identity == (uintptr_t)&devices[ch]);
    assert(state.channel == devices[ch].channel && state.base == devices[ch].base);
    devices[ch].channel = (ch + 3) % 10; devices[ch].base += 0x80;
    assert(STATE(ch, &state) == 0 && state.channel == devices[ch].channel && state.base == devices[ch].base);
    devices[ch].channel = ch; devices[ch].base -= 0x80;
    assert(STATE(ch, &state) == 0);
#ifdef TEST_REGISTER
    assert(state.registrations == 1 && register_calls[ch] == (ch == LAST ? 2 : 1));
#else
    assert(!state.registrations && !register_calls[ch]);
#endif
    assert(state.transfers == ch + 100);
  }
  unsigned saved_lower[10], saved_register[10];
  memcpy(saved_lower, lower_calls, sizeof(saved_lower));
  memcpy(saved_register, register_calls, sizeof(saved_register));
  assert(SETUP() == 0 && !memcmp(saved_lower, lower_calls, sizeof(saved_lower)));
  assert(!memcmp(saved_register, register_calls, sizeof(saved_register)));
  struct rzv2h_bus_sample_state_s state;
  assert(WRAPPER(&state) == 0 && state.identity == (uintptr_t)&devices[FIRST]);
  assert(STATE(-1, &state) == -EINVAL && STATE(10, &state) == -EINVAL && STATE(FIRST, NULL) == -EINVAL);
  bool selected[10] = {false};
  for (unsigned i = 0; i < sizeof(selected_channels)/sizeof(selected_channels[0]); ++i)
    selected[selected_channels[i]] = true;
  for (unsigned ch = 0; ch < 10; ++ch) if (!selected[ch]) {
    assert(!lower_calls[ch] && !register_calls[ch] && STATE(ch, &state) == -ENODEV);
  }
#ifdef TEST_SPI
# ifndef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT
  assert(pins && rzv_sci_spi_status(&devices[0], SPIDEV_USER(0)) == SPI_STATUS_PRESENT);
  rzv_sci_spi_select(&devices[0], SPIDEV_USER(0), true);
  assert(selects == 1 && !last_level && last_pin == RZV_SCI0_CS_PIN);
  rzv_sci_spi_select(&devices[0], SPIDEV_NONE(0), false);
  assert(selects == 2 && last_level);
# else
  assert(!pins);
# endif
  unsigned saved_selects = selects;
  struct spi_dev_s foreign = {0};
  assert(!rzv_sci_spi_status(NULL, SPIDEV_USER(0)));
  assert(!rzv_sci_spi_status(&foreign, SPIDEV_USER(0)));
  rzv_sci_spi_select(NULL, SPIDEV_USER(0), true);
  rzv_sci_spi_select(&foreign, SPIDEV_USER(0), true);
  for (unsigned ch = 1; ch < 10; ++ch) {
    assert(!rzv_sci_spi_status(&devices[ch], SPIDEV_USER(0)));
    rzv_sci_spi_select(&devices[ch], SPIDEV_USER(0), true);
  }
  rzv_sci_spi_select(&devices[0], SPIDEV_USER(1), true);
  assert(selects == saved_selects);
#endif
#endif
  return 0;
}
'''
    if mode == "spi":
        prelude += "#define TEST_SPI 1\n"
    return prelude + source + settings + main


class SciSpiBoardRegistration(unittest.TestCase):
    def test_all_channels_register_distinct_buses_and_retry_only_failures(self):
        compile_and_run(board_harness("spi", list(range(10))))

    def test_single_nonzero_channel_registers_and_reports_its_own_identity(self):
        for channel in (1, 2, 3, 7, 9):
            with self.subTest(channel=channel):
                compile_and_run(board_harness("spi", [channel]))

    def test_controller_without_character_device_does_not_claim_registration(self):
        compile_and_run(board_harness("spi", list(range(10)), register=False),
                        defines=("-DCONFIG_RZV_SPI0=1", "-DCONFIG_RZV_SPI1=1", "-DCONFIG_RZV_SPI2=1"))

    def test_unassigned_route_and_collisions_fail_before_any_side_effect(self):
        for flags, controlled in (
            (("-DTEST_REJECT=-ENOTSUP",), False),
            (("-DTEST_REJECT=-EBUSY", "-DCONFIG_RZV_SPI1=1"), True),
            (("-DTEST_REJECT=-EBUSY", "-DCONFIG_RZV_SCI1=1"), True),
            (("-DTEST_REJECT=-EBUSY", "-DCONFIG_RZV_SCI1_I2C=1"), True),
        ):
            with self.subTest(flags=flags):
                code = board_harness("spi", [1], controlled=controlled)
                code = code.replace("static const unsigned selected_channels[]", "static const unsigned TEST_UNUSED selected_channels[]")
                compile_and_run(code, defines=flags)

    def test_legacy_sci0_route_selects_only_its_own_device(self):
        compile_and_run(board_harness("spi", [0], controlled=False))


def sci_cpg_harness(body):
    source = (ARCH / "rzv_clock.c").read_text()
    code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <string.h>
#define OK 0
#define irqstate_t unsigned
#define clkinfo(...) ((void)0)
#define clkerr(...) ((void)0)
#define CPG_TIMEOUT_CLOCK_ENABLE 1u
#define CPG_TIMEOUT_CLOCK_DISABLE 2u
#define CPG_TIMEOUT_RESET_ASSERT 3u
#define CPG_TIMEOUT_RESET_RELEASE 4u
'''
    code += without_includes((ARCH / "hardware/rzv_cpg.h").read_text())
    code += r'''
static uint32_t clocks[16], resets[16], module_stop;
static uint32_t before_clocks[16], before_resets[16], before_stop;
static unsigned channel, depth, reads, writes, waits, failure;
static bool saw_failure, rollback_fault;
static uintptr_t last_address;
static uint32_t last_mask, last_data;
static irqstate_t enter_critical_section(void) { assert(!depth); return depth++; }
static void leave_critical_section(irqstate_t flags) { assert(flags == 0 && depth == 1); --depth; }
static uint32_t rzv_cpg_getreg(uintptr_t address) {
  ++reads;
  if (address == RZV_CPG_BUS_11_MSTOP) return module_stop;
  if (address >= RZV_CPG_CLKON(0) && address <= RZV_CPG_CLKON(15))
    return clocks[(address - RZV_CPG_CLKON(0)) / 4];
  if (address >= RZV_CPG_RST(0) && address <= RZV_CPG_RST(15))
    return resets[(address - RZV_CPG_RST(0)) / 4];
  assert(address >= RZV_CPG_CLKMON(0) && address <= RZV_CPG_CLKMON(7));
  unsigned pair = (address - RZV_CPG_CLKMON(0)) / 4;
  return clocks[pair * 2] | (clocks[pair * 2 + 1] << 16);
}
static void rzv_cpg_putreg(uint32_t value, uintptr_t address) {
  assert(depth == 1); ++writes;
  uint32_t mask = value >> 16, low = value & 0xffff;
  assert(mask && !(low & ~mask));
  last_address = address; last_mask = mask; last_data = low;
  if (address == RZV_CPG_BUS_11_MSTOP) {
    assert(mask == (1u << (3 + channel)));
    module_stop = (module_stop & ~mask) | low;
    return;
  }
  uint32_t *bank; unsigned domain, first, span;
  if (address >= RZV_CPG_CLKON(0) && address <= RZV_CPG_CLKON(15)) {
    bank = clocks; domain = (address - RZV_CPG_CLKON(0)) / 4;
    first = 93 + 5 * channel; span = 5;
  } else {
    assert(address >= RZV_CPG_RST(0) && address <= RZV_CPG_RST(15));
    bank = resets; domain = (address - RZV_CPG_RST(0)) / 4;
    first = 129 + 2 * channel; span = 2;
  }
  for (unsigned bit = 0; bit < 16; ++bit) if (mask & (1u << bit))
    assert(domain * 16 + bit >= first && domain * 16 + bit < first + span);
  bank[domain] = (bank[domain] & ~mask) | low;
}
static int poll_result(void) {
  ++waits;
  if (!saw_failure && waits == failure) {
    /* Failure is injected after the real helper's write changed the model. */
    assert(writes > 0);
    saw_failure = true;
    return -ETIMEDOUT;
  }
  return saw_failure && rollback_fault ? -EIO : 0;
}
static int rzv_cpg_wait_clkmon(uint32_t bit, uint32_t count, bool set, uint32_t timeout) {
  assert(!depth && count == 1 && bit >= 93 + 5 * channel && bit < 98 + 5 * channel);
  assert(timeout == (set ? CPG_TIMEOUT_CLOCK_ENABLE : CPG_TIMEOUT_CLOCK_DISABLE));
  assert(!!(clocks[bit / 16] & (1u << (bit % 16))) == set);
  assert(last_address == RZV_CPG_CLKON(bit / 16));
  assert(last_mask == (1u << (bit % 16)));
  assert(last_data == (set ? last_mask : 0u));
  return poll_result();
}
static int rzv_cpg_wait_rstmon(uint32_t bit, uint32_t count, bool asserted, uint32_t timeout) {
  assert(!depth && count == 1 && bit >= 129 + 2 * channel && bit < 131 + 2 * channel);
  assert(timeout == (asserted ? CPG_TIMEOUT_RESET_ASSERT : CPG_TIMEOUT_RESET_RELEASE));
  assert(!!(resets[bit / 16] & (1u << (bit % 16))) != asserted);
  assert(last_address == RZV_CPG_RST(bit / 16));
  assert(last_mask == (1u << (bit % 16)));
  assert(last_data == (asserted ? 0u : last_mask));
  return poll_result();
}
'''
    code += definition(source, "static void rzv_cpg_mstop_write(uintptr_t reg, uint32_t bits, bool release)")
    if "static void rzv_cpg_sci_restore(" in source:
        code += definition(source, "static void rzv_cpg_sci_restore(uint32_t first, uint32_t count, uint32_t previous, bool clock)")
    for signature in (
        "static int rzv_cpg_sci_clock_ctrl(int ch, bool enable)",
        "static int rzv_cpg_sci_reset_ctrl(int ch, bool assert_rst)",
    ):
        code += definition(source, signature)
    code += r'''
static void expected_change(uint32_t *bank, unsigned first, unsigned span, bool high) {
  for (unsigned bit = first; bit < first + span; ++bit) {
    if (high) bank[bit / 16] |= 1u << (bit % 16);
    else bank[bit / 16] &= ~(1u << (bit % 16));
  }
}
static void inherited_state(unsigned gates, unsigned reset_pair, bool stopped) {
  for (unsigned bank = 0; bank < 16; ++bank) {
    clocks[bank] = (0xa55au ^ (0x1111u * bank)) & 0xffffu;
    resets[bank] = (0x5aa5u ^ (0x1111u * bank)) & 0xffffu;
  }
  for (unsigned gate = 0; gate < 5; ++gate)
    expected_change(clocks, 93 + 5 * channel + gate, 1, (gates & (1u << gate)) != 0);
  for (unsigned bit = 0; bit < 2; ++bit)
    expected_change(resets, 129 + 2 * channel + bit, 1, (reset_pair & (1u << bit)) != 0);
  uint32_t owned = 1u << (3 + channel);
  module_stop = (0xc3a5u & ~owned) | (stopped ? owned : 0u);
  memcpy(before_clocks, clocks, sizeof(clocks));
  memcpy(before_resets, resets, sizeof(resets));
  before_stop = module_stop;
  reads = writes = waits = failure = 0;
  saw_failure = rollback_fault = false;
  assert(!depth);
}
static void restored(void) {
  assert(!memcmp(before_clocks, clocks, sizeof(clocks)));
  assert(!memcmp(before_resets, resets, sizeof(resets)));
  assert(module_stop == before_stop && depth == 0);
}
'''
    return (code + "\nint main(void) {\n"
            "(void)rzv_cpg_sci_clock_ctrl; (void)rzv_cpg_sci_reset_ctrl; (void)restored;\n" +
            body + "\nassert(!depth); return 0; }\n")


class SciClockResetBoundaries(unittest.TestCase):
    def test_real_clock_reset_helpers_preserve_neighbors_across_bank_boundaries(self):
        compile_and_run(sci_cpg_harness(r'''
  for (channel = 0; channel < 10; ++channel) {
    for (unsigned high = 0; high <= 1; ++high) {
      inherited_state(0x15u, 1u, true);
      uint32_t expected[16]; memcpy(expected, clocks, sizeof(expected));
      expected_change(expected, 93 + 5 * channel, 5, high);
      assert(rzv_cpg_sci_clock_ctrl(channel, high) == 0 && waits == 5 && writes == 6);
      assert(!memcmp(expected, clocks, sizeof(expected)));
      assert(!memcmp(before_resets, resets, sizeof(resets)));
      uint32_t owned = 1u << (3 + channel);
      assert(module_stop == ((before_stop & ~owned) | (high ? 0u : owned)));
      memcpy(expected, resets, sizeof(expected));
      expected_change(expected, 129 + 2 * channel, 2, high);
      waits = writes = 0;
      uint32_t saved_clock[16]; memcpy(saved_clock, clocks, sizeof(clocks));
      uint32_t saved_stop = module_stop;
      assert(rzv_cpg_sci_reset_ctrl(channel, !high) == 0 && waits == 2 && writes == 2);
      assert(!memcmp(expected, resets, sizeof(expected)));
      assert(!memcmp(saved_clock, clocks, sizeof(clocks)) && module_stop == saved_stop);
    }
  }
'''))

    def test_each_clock_poll_failure_restores_all_inherited_gates_and_mstop(self):
        compile_and_run(sci_cpg_harness(r'''
  for (channel = 0; channel < 10; ++channel)
    for (unsigned enable = 0; enable < 2; ++enable)
      for (unsigned gates = 0; gates < 32; ++gates)
        for (unsigned stopped = 0; stopped < 2; ++stopped)
          for (unsigned stage = 1; stage <= 5; ++stage) {
            inherited_state(gates, channel % 4, stopped != 0);
            failure = stage;
            assert(rzv_cpg_sci_clock_ctrl(channel, enable != 0) == -ETIMEDOUT);
            assert(saw_failure && waits == stage + 5);
            assert(writes == stage + 6 + (enable == 0));
            restored();
            failure = 0; saw_failure = false;
            assert(rzv_cpg_sci_clock_ctrl(channel, enable != 0) == 0);
          }
'''))

    def test_each_reset_poll_failure_restores_both_inherited_reset_bits(self):
        compile_and_run(sci_cpg_harness(r'''
  for (channel = 0; channel < 10; ++channel)
    for (unsigned asserted = 0; asserted < 2; ++asserted)
      for (unsigned pair = 0; pair < 4; ++pair)
        for (unsigned stage = 1; stage <= 2; ++stage) {
          inherited_state(0x15u, pair, (channel & 1u) != 0);
          failure = stage;
          assert(rzv_cpg_sci_reset_ctrl(channel, asserted != 0) == -ETIMEDOUT);
          assert(saw_failure && waits == stage + 2 && writes == stage + 2);
          restored();
          failure = 0; saw_failure = false;
          assert(rzv_cpg_sci_reset_ctrl(channel, asserted != 0) == 0);
        }
'''))

    def test_rollback_poll_errors_preserve_original_error_and_restore_peer_bits(self):
        compile_and_run(sci_cpg_harness(r'''
  for (channel = 0; channel < 10; ++channel)
    for (unsigned action = 0; action < 2; ++action) {
      for (unsigned stage = 1; stage <= 5; ++stage) {
        inherited_state(0x15u, 2u, action != 0);
        failure = stage; rollback_fault = true;
        assert(rzv_cpg_sci_clock_ctrl(channel, action != 0) == -ETIMEDOUT);
        assert(waits == stage + 5); restored();
      }
      for (unsigned stage = 1; stage <= 2; ++stage) {
        inherited_state(0xau, action + 1u, action != 0);
        failure = stage; rollback_fault = true;
        assert(rzv_cpg_sci_reset_ctrl(channel, action != 0) == -ETIMEDOUT);
        assert(waits == stage + 2); restored();
      }
    }
'''))

    def test_invalid_channels_fail_before_any_cpg_access(self):
        compile_and_run(sci_cpg_harness(r'''
  const int invalid[] = {-1, 10, INT_MAX};
  for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
    inherited_state(0x15u, 1u, true);
    assert(rzv_cpg_sci_clock_ctrl(invalid[i], true) == -EINVAL);
    assert(rzv_cpg_sci_clock_ctrl(invalid[i], false) == -EINVAL);
    assert(rzv_cpg_sci_reset_ctrl(invalid[i], true) == -EINVAL);
    assert(rzv_cpg_sci_reset_ctrl(invalid[i], false) == -EINVAL);
    assert(!reads && !writes && !waits); restored();
  }
'''))



class SciSpiClockContracts(unittest.TestCase):
    def test_integer_search_matches_manual_oracle_without_modulation(self):
        code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <assert.h>
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
'''
        for name in ('hardware/rzv_sci.h', 'hardware/rzv_sci_spi.h', 'rzv_sci_spi_clock.c'):
            code += without_includes((ARCH / name).read_text())
        code += r'''
int main(void) {
  const uint32_t clocks[] = {25000000, 50000000, 100000000, 200000000, 400000000};
  const uint32_t requests[] = {1000, 1500, 3000, 3906, 15625, 62500, 100000,
                             1000000, 2500000, 3000000, 5000000, 6000000, 7000000,
                             7500000, 8000000, 10000000, 12000000, 20000000, 25000000};
  for (unsigned clock = 0; clock < sizeof(clocks)/sizeof(clocks[0]); ++clock)
    for (unsigned request = 0; request < sizeof(requests)/sizeof(requests[0]); ++request) {
      uint8_t brr = 66, cks = 77, mddr = 88;
      uint64_t best = 0;
      /* Table 7.3-8, BGDM=1: B = P5 / (2 * 4^CKS * (BRR+1)).  Vendor
       * round-down: the smallest divisor whose rate does not exceed the
       * request, or no setting when even the largest divisor is too fast.
       */
      for (unsigned k = 0; k < 4; ++k) for (unsigned n = 0; n < 256; ++n) {
        uint64_t div = 2ull * (1u << (2u * k)) * (n + 1u);
        if ((uint64_t)requests[request] * div >= clocks[clock] && (!best || div < best)) best = div;
      }
      int result = rzv_sci_spi_calc_bitrate(clocks[clock], requests[request], &brr, &cks, &mddr);
      if (!best) {
        assert(result == -EINVAL && brr == 66 && cks == 77 && mddr == 88);
      } else {
        assert(result == 0 && cks <= 3 && mddr == 0);
        uint64_t div = 2ull * (1u << (2u * cks)) * (brr + 1u);
        assert(div == best);
        uint32_t actual = clocks[clock] / (uint32_t)div;
        assert(actual <= requests[request]);
        assert(rzv_sci_spi_actual_bitrate(clocks[clock], brr, cks, 0) == actual);
        assert(rzv_sci_spi_actual_bitrate(clocks[clock], brr, cks, 255) == actual);
      }
    }
  const uint32_t invalid[] = {0, 999, 25000001, UINT32_MAX};
  for (unsigned i = 0; i < sizeof(invalid)/sizeof(invalid[0]); ++i) {
    uint8_t brr = 66, cks = 77, mddr = 88;
    assert(rzv_sci_spi_calc_bitrate(100000000, invalid[i], &brr, &cks, &mddr) == -EINVAL);
    assert(brr == 66 && cks == 77 && mddr == 88);
  }
  uint8_t brr = 66, cks = 77, mddr = 88;
  assert(rzv_sci_spi_calc_bitrate(0, 1000000, &brr, &cks, &mddr) == -EINVAL);
  assert(brr == 66 && cks == 77 && mddr == 88);
  return 0;
}
'''
        compile_and_run(code)

# The complete portable suite includes the production transfer/ISR cases.
# Keep the reference-only class separate without duplicating method lists.
MODE_SPEC = importlib.util.spec_from_file_location(
    "rzv2h_sci_spi_mode_runtime", ROOT / "test/rzv2h-sci-spi-mode-runtime-test.py")
MODE_RUNTIME = importlib.util.module_from_spec(MODE_SPEC)
MODE_SPEC.loader.exec_module(MODE_RUNTIME)
SciSpiModeRuntime = MODE_RUNTIME.SciSpiModeRuntime


if __name__ == "__main__":
    if "--portable" in sys.argv:
        sys.argv.remove("--portable")
        portable_classes = [
            name for name, value in list(globals().items())
            if isinstance(value, type) and issubclass(value, unittest.TestCase)
            and value is not SciChannelReference
        ]
        unittest.main(defaultTest=portable_classes)
    else:
        unittest.main()
