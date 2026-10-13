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
    def test_unsupported_cm33_lower_halves_cannot_be_selected(self):
        source = (NUTTX / 'arch/arm/src/rzv/Kconfig').read_text()
        blocks = []
        for name in GATED:
            match = re.search(rf'^(?:menuconfig|config) {name}\n.*?(?=^(?:menuconfig|config|if|endif|choice|endchoice|menu|endmenu) |\Z)', source, re.M | re.S)
            self.assertIsNotNone(match, name)
            blocks.append(match.group())
        dependencies = set()
        for block in blocks:
            for line in block.splitlines():
                if line.strip().startswith(('depends on ', 'select ')):
                    dependencies.update(re.findall(r'\b[A-Z][A-Z_0-9]*\b', line))
        external = dependencies - set(GATED) - {'RZV2H_BUILD_CM33'}
        text = 'config RZV2H_BUILD_CM33\n bool "CM33"\n\n'
        text += ''.join(f'config {name}\n bool\n default y\n\n' for name in sorted(external))
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
