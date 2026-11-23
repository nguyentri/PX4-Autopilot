#!/usr/bin/env python3
"""Evaluate actual optional driver and six-channel PWM Kconfig contracts."""

from pathlib import Path
import re
import tempfile
import unittest

import kconfiglib

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
GATED = ('RZV_GTM', 'RZV_GPT', 'RZV_ADC', 'RZV_CANFD', 'RZV_WDT',
         'RZV_GPIO_IRQ', 'RZV_SCI_I2C', 'RZV_I2C', 'RZV_I2C0', 'RZV_I2C1', 'RZV_I2C2', 'RZV_I2C3',
         'RZV_UART_SCIF', 'RZV_SCIF0', 'RZV_SCIF1', 'RZV_SCIF2', 'RZV_SCIF3', 'RZV_SCIF4')


class OptionalConfiguration(unittest.TestCase):
    def test_canfd_selects_supported_architecture_irq_priorities(self):
        source = (NUTTX / 'arch/arm/src/rzv/Kconfig').read_text()
        blocks = []
        for name in ('ARCH_CORTEXR8_SELECTED', 'RZV_CANFD'):
            blocks.append(re.search(
                rf'^(?:menuconfig|config) {name}\n.*?(?=^(?:menuconfig|config|if|endif|choice|endchoice|menu|endmenu) |\Z)',
                source, re.M | re.S).group())
        dependencies = set(re.findall(r'\b[A-Z][A-Z_0-9]*\b', '\n'.join(
            line for block in blocks for line in block.splitlines()
            if line.strip().startswith(('depends on ', 'select ')))))
        dependencies -= {'ARCH_IRQPRIO', 'ARCH_HAVE_IRQPRIO', 'RZV2H_BUILD_CM33'}
        contract = ''.join(f'config {name}\n bool\n default y\n' for name in sorted(dependencies))
        contract += '''config RZV2H_BUILD_CM33
 bool
config ARCH_HAVE_IRQPRIO
 bool
config ARCH_IRQPRIO
 bool "Interrupt priority control"
 depends on ARCH_HAVE_IRQPRIO
'''
        contract += '\n'.join(blocks)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Kconfig'
            path.write_text(contract)
            conf = kconfiglib.Kconfig(str(path), warn=False)
            self.assertEqual(conf.syms['ARCH_HAVE_IRQPRIO'].str_value, 'y')
            self.assertEqual(conf.syms['ARCH_IRQPRIO'].str_value, 'n')
            conf.syms['RZV_CANFD'].set_value('y')
            self.assertEqual(conf.syms['ARCH_IRQPRIO'].str_value, 'y')

    def test_all_six_can_channels_coexist_and_sci9_excludes_only_hw1(self):
        source = (NUTTX / 'arch/arm/src/rzv/Kconfig').read_text()
        start = source.index('config RZV_CANFD0\n')
        end = source.index('config RZV_CANFD_BOOT_LOOPBACK\n', start)
        contract = ''.join(f'config RZV_HAVE_CAN{channel}\n bool\n default y\n'
                           for channel in range(6))
        contract += 'config RZV_SCI9\n bool "SCI9"\n'
        contract += source[start:end]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Kconfig'
            path.write_text(contract)
            for sci9, hw1 in ((False, False), (False, True), (True, False), (True, True)):
                conf = kconfiglib.Kconfig(str(path), warn=False)
                conf.syms['RZV_SCI9'].set_value('y' if sci9 else 'n')
                conf.syms['RZV_CANFD1'].set_value('y' if hw1 else 'n')
                for channel in (0, 2, 3, 4, 5):
                    conf.syms[f'RZV_CANFD{channel}'].set_value('y')
                self.assertEqual(conf.syms['RZV_CANFD1'].str_value,
                                 'y' if hw1 and not sci9 else 'n')
                for channel in (0, 2, 3, 4, 5):
                    self.assertEqual(conf.syms[f'RZV_CANFD{channel}'].str_value, 'y')

    def test_unsupported_cm33_lower_halves_cannot_be_selected(self):
        source = (NUTTX / 'arch/arm/src/rzv/Kconfig').read_text()
        blocks = []
        for name in GATED:
            match = re.search(rf'^(?:menuconfig|config) {name}\n.*?(?=^(?:menuconfig|config|if|endif|choice|endchoice|menu|endmenu) |\Z)', source, re.M | re.S)
            self.assertIsNotNone(match, name)
            blocks.append(match.group())
        dependencies = set()
        negated = set()
        for block in blocks:
            for line in block.splitlines():
                if line.strip().startswith(('depends on ', 'select ')):
                    dependencies.update(re.findall(r'\b[A-Z][A-Z_0-9]*\b', line))
                    negated.update(re.findall(r'!([A-Z][A-Z_0-9]*)\b', line))
        external = dependencies - set(GATED) - {'RZV2H_BUILD_CM33'}
        # Satisfy every external dependency so only the CM33 gate decides; a symbol
        # referenced as "!X" (e.g. SCIF0 excludes SCI0 on /dev/ttyS0) must stay off.
        text = 'config RZV2H_BUILD_CM33\n bool "CM33"\n\n'
        text += ''.join(f'config {name}\n bool\n default {"n" if name in negated else "y"}\n\n'
                        for name in sorted(external))
        text += '\n'.join(blocks)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Kconfig'
            path.write_text(text)
            conf = kconfiglib.Kconfig(str(path), warn=False)
            for cm in ('n', 'y'):
                conf.syms['RZV2H_BUILD_CM33'].set_value(cm)
                for name in GATED:
                    conf.syms[name].set_value('y')
                for name in GATED:
                    self.assertEqual(conf.syms[name].str_value, 'n' if cm == 'y' else 'y', f'{name} on CM33={cm}')

    def test_sixth_pwm_channel_has_an_independent_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Kconfig'
            source = ROOT / 'platforms/nuttx/NuttX/apps/examples/pwm/Kconfig'
            path.write_text('''config PWM
 bool
 default y
config PWM_MULTICHAN
 bool
 default y
config PWM_NCHANNELS
 int
 default 6
config PWM_PULSECOUNT
 bool
config NSH_BUILTIN_APPS
 bool
 default y
''' + source.read_text())
            conf = kconfiglib.Kconfig(str(path), warn=False)
            conf.syms['EXAMPLES_PWM'].set_value('y')
            self.assertIn('EXAMPLES_PWM_CHANNEL6', conf.syms)
            fifth = conf.syms['EXAMPLES_PWM_CHANNEL5']
            sixth = conf.syms['EXAMPLES_PWM_CHANNEL6']
            self.assertEqual((fifth.str_value, sixth.str_value), ('5', '6'))
            fifth.set_value('2')
            self.assertEqual((fifth.str_value, sixth.str_value), ('2', '6'))


if __name__ == '__main__':
    unittest.main()
