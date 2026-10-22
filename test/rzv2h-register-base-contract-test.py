#!/usr/bin/env python3
"""Compile core-specific register bases against the local CMSIS authority."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HW = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware"
HEADERS = {
    "intc": "intc", "adc": "adc_e", "canfd": "canfd", "gtm": "gtm",
    "gpt": "gpt", "poeg": "poeg", "wdt": "wdt", "i2c": "riic",
    "scifa": "scifa", "i3c": "i3c_b", "crc": "crc", "pdm": "pdm",
    "rtc": "rtc", "ssi": "ssi", "tsu": "tsu_b", "tzc": "tzc",
    "cmtw": "cmtw", "xspi": "xspi",
}


def references(core, sample=None):
    sample = sample or ("cm33" if core == "cm" else "cr8_0")
    return ROOT / (f"refs/rzv2h_evk/adc_e/adc_e_rzv2h_evk_{sample}_ep/"
                   "e2studio/rzv/fsp/src/bsp/cmsis/Device/RENESAS/Include/"
                   f"R9A09G057H/{core}/iodefines")


class RegisterBases(unittest.TestCase):
    def test_each_core_matches_its_cmsis_view(self):
        for core, sample in (("cr", "cr8_0"), ("cr", "cr8_1"), ("cm", "cm33")):
            ref = references(core, sample)
            if not ref.is_dir():
                self.skipTest(f"local CMSIS authority unavailable: {ref}")
            with tempfile.TemporaryDirectory(prefix="rzv2h-bases-") as d:
                tmp = Path(d)
                (tmp / "nuttx").mkdir()
                (tmp / "nuttx/config.h").write_text(
                    "#define CONFIG_RZV2H_BUILD_CM33 1\n" if core == "cm" else "")
                for native, vendor in HEADERS.items():
                    header = HW / f"rzv_{native}.h"
                    bases = dict(re.findall(
                        r"^#define\s+(R_\w+_BASE)\s+(0x[\da-fA-F]+)",
                        (ref / f"{vendor}_iodefine.h").read_text(), re.M))
                    names = set(re.findall(r"#\s*define\s+(RZV_\w+_BASE)\b",
                                           header.read_text()))
                    assertions = []
                    for symbol, value in bases.items():
                        mapped = symbol.replace("R_", "RZV_", 1).replace("I3C_B", "I3C").replace("TSU_B", "TSU")
                        found = {mapped} & names
                        if not found and re.search(r"[^\d]_BASE$", mapped):
                            found = {mapped.replace("_BASE", "0_BASE")} & names
                        if native == "tzc" or symbol == "R_RTC_RO_BASE":
                            self.assertTrue(found, symbol)
                        for name in found:
                            assertions.append(f'_Static_assert({name} == {value}, "{name}:{core}");')
                    self.assertTrue(assertions, native)
                    source = tmp / "test.c"
                    source.write_text(f'#include "{header}"\n' + "\n".join(assertions))
                    with self.subTest(core=sample, header=native):
                        result = subprocess.run(["cc", "-std=c11", "-Werror", "-fsyntax-only",
                                                 "-I", str(tmp), str(source)],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_canfd_sparse_channel_access_matches_cmsis(self):
        ref = references("cr") / "canfd_iodefine.h"
        if not ref.is_file():
            self.skipTest(f"local CMSIS authority unavailable: {ref}")
        reference_root = ROOT / 'refs/rzv2h_evk/can_fd/can_fd_rzv2h_evk_cr8_0_ep/e2studio'
        sense = (reference_root / 'rzv/fsp/src/bsp/mcu/rzv2h/bsp_irq_sense.h').read_text()
        irq = (ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/include/rzv/rzv2h_irq.h').read_text()
        for event, alias in (('TX', 'TRX'), ('CHERR', 'ERR')):
            sources = dict((int(ch), int(selector)) for selector, ch in
                           re.findall(rf'SEL(\d+): CANFD_CAN_{event}_INT_(\d+)_IRQSELn', sense))
            self.assertEqual(set(sources), set(range(6)))
            for ch, selector in sources.items():
                match = re.search(rf'^#define RZV_ELC_CANFD_CH{ch}_{alias}\s+\((\d+)\)', irq, re.M)
                self.assertIsNotNone(match)
                self.assertEqual(int(match[1]), selector)
        with tempfile.TemporaryDirectory(prefix="rzv2h-canfd-layout-") as d:
            tmp = Path(d)
            (tmp / "nuttx").mkdir()
            (tmp / "nuttx/config.h").write_text("")
            code = ('#include <stdint.h>\n#include <stddef.h>\n'
                    '#define __IM volatile const\n#define __OM volatile\n'
                    '#define __IOM volatile\n'
                    f'#include "{ref}"\n'
                    f'#include "{HW / "rzv_canfd.h"}"\n')
            for channel in range(6):
                mb = channel * 64
                for member, macro in (
                    (f"CFDC[{channel}].NCFG", f"RZV_CANFD_CFDC_NCFG({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC[{channel}].CTR", f"RZV_CANFD_CFDC_CTR({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC[{channel}].STS", f"RZV_CANFD_CFDC_STS({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC[{channel}].ERFL", f"RZV_CANFD_CFDC_ERFL({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC2[{channel}].DCFG", f"RZV_CANFD_CFDC2_DCFG({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC2[{channel}].FDCFG", f"RZV_CANFD_CFDC2_FDCFG({channel}) - RZV_CANFD_BASE"),
                    (f"CFDC2[{channel}].FDCTR", f"RZV_CANFD_CFDC2_FDCTR({channel}) - RZV_CANFD_BASE"),
                    (f"CFDTMC[{mb}]", f"RZV_CANFD_CFDTMC_OFFSET(RZV_CANFD_TXMB_CH({channel}))"),
                    (f"CFDTMSTS[{mb}]", f"RZV_CANFD_CFDTMSTS_OFFSET(RZV_CANFD_TXMB_CH({channel}))"),
                    (f"CFDTM[{mb}].ID", f"RZV_CANFD_CFDTMID_OFFSET(RZV_CANFD_TXMB_CH({channel}))"),
                    (f"CFDTMIEC[{channel*2}]", f"RZV_CANFD_CFDTMIEC({channel*2}) - RZV_CANFD_BASE"),
                    (f"CFDGAFLCFG[{channel//2}]", f"RZV_CANFD_CFDGAFLCFG({channel//2}) - RZV_CANFD_BASE")):
                    code += f'_Static_assert({macro} == offsetof(R_CANFD_Type, {member}), "{member}");\n'
            (tmp / "check.c").write_text(code)
            result = subprocess.run(["cc", "-std=c11", "-Werror", "-fsyntax-only",
                                     "-I", str(tmp), str(tmp / "check.c")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
