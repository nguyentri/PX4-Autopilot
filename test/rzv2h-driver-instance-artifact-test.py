#!/usr/bin/env python3
"""Admit real instance ELFs and reject coherently rehashed compiled mutants.

Defaults to the focused v2 archive; --builds selects another completed archive
and --source-state overrides its parent/source-state.json. No firmware runs.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILDS = ROOT / 'build/rzv2h-driver-channel-focused-v2-261024/builds'
BUILDS = SOURCE = None
SPEC = importlib.util.spec_from_file_location(
    'instance_artifact', ROOT/'platforms/nuttx/Debug/rzv2h-sample-artifact-check.py')
ART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ART)


def virtual_offset(data, address, length=4):
    header = struct.unpack_from('<I', data, 28)[0]
    stride, count = struct.unpack_from('<HH', data, 42)
    for index in range(count):
        kind, start, base, _, size, _, _, _ = struct.unpack_from('<8I', data, header + index * stride)
        if kind == 1 and base <= address and address + length <= base + size:
            return start + address - base
    raise AssertionError('mutation address is not file-backed')


def symbol_entry(data, wanted):
    header = struct.unpack_from('<I', data, 32)[0]
    stride, count = struct.unpack_from('<HH', data, 46)
    sections = [struct.unpack_from('<10I', data, header + index * stride)
                for index in range(count)]
    found = []
    for section in sections:
        if section[1] != 2:
            continue
        strings = sections[section[6]]
        names = data[strings[4]:strings[4] + strings[5]]
        for offset in range(section[4], section[4] + section[5], section[9]):
            name = struct.unpack_from('<I', data, offset)[0]
            end = names.find(b'\0', name)
            if names[name:end] == wanted.encode():
                found.append(offset)
    if len(found) != 1:
        raise AssertionError('mutation symbol is missing/ambiguous: ' + wanted)
    return found[0]


class CaseTableFixtures(unittest.TestCase):
    """Compiled ARM ABI fixtures; these are not driver or board evidence."""

    CASES = ['instance.guard', 'instance.identity', 'instance.stable']

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='rzv2h-instance-cases-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.binaries = {}
        (cls.directory/'cases.c').write_text(r'''
struct hwtest_case_s {
  const char *suite;
  const char *name;
  int (*fn)(void);
};
static volatile int state;
#define KEEP __attribute__((used, noinline))
static int KEEP guard(void) { return state += 1; }
static int KEEP identity(void) { return state += 2; }
static int KEEP stable(void) { return state += 3; }
#if CASE_COUNT == 4
#ifndef OMIT_LOOPBACK_PROVIDER
int rzv2h_spi_sample_loopback_at(void) { return state += 4; }
#endif
static int KEEP loopback(void) { return state += 5; }
#endif
static const struct hwtest_case_s g_cases[] = {
  {"instance", "guard", guard},
  {"instance", "identity", identity},
#if defined(SWAP_LAST_ROWS)
  {"instance", "loopback", loopback},
  {"instance", "stable", stable}
#else
  {"instance", "stable", stable},
#if CASE_COUNT == 4 && !defined(OMIT_LAST_ROW)
#ifdef NULL_LOOPBACK
  {"instance", "loopback", 0}
#else
  {"instance", "loopback", loopback}
#endif
#endif
#endif
};
#ifndef PUBLISHED_COUNT
#define PUBLISHED_COUNT CASE_COUNT
#endif
__attribute__((noipa))
const struct hwtest_case_s *driver_instance_cases(unsigned int *count) {
  *count = PUBLISHED_COUNT;
  return g_cases;
}
static const struct hwtest_case_s *volatile observed;
static volatile unsigned int observed_count;
void hwtest_main(void) {
  unsigned int count;
  observed = driver_instance_cases(&count);
  observed_count = count;
}
''')

    def compiled(self, count, *options):
        key = count, options
        if key not in self.binaries:
            output = self.directory/('cases-' + str(len(self.binaries)) + '.elf')
            command = ['arm-none-eabi-gcc', '-std=c11', '-Os', '-Wall', '-Wextra',
                       '-Werror', '-mcpu=cortex-r8', '-marm', '-ffreestanding',
                       '-nostdlib', '-Wl,--build-id=none', '-Wl,-e,hwtest_main',
                       '-Wl,-Ttext=0x40800000', '-DCASE_COUNT=' + str(count)]
            command += ['-D' + option for option in options]
            result = subprocess.run(command + [str(self.directory/'cases.c'),
                                               '-o', str(output)],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.binaries[key] = output
        return self.binaries[key]

    def check(self, elf, count):
        cases = self.CASES + (['instance.loopback'] if count == 4 else [])
        providers = {'rzv2h_spi_sample_loopback_at'} if count == 4 else set()
        return ART.compiled_instance_cases(elf, cases, providers)

    def test_legacy_three_case_abi_is_admitted(self):
        self.assertEqual(self.check(self.compiled(3), 3), self.CASES)

    def test_spi_four_case_abi_is_admitted(self):
        self.assertEqual(self.check(self.compiled(4), 4), self.CASES + ['instance.loopback'])

    def test_contract_count_must_match_the_compiled_provider(self):
        for compiled, required in ((3, 4), (4, 3)):
            # Omit provider requirements here to isolate the count invariant.
            cases = self.CASES + (['instance.loopback'] if required == 4 else [])
            with self.subTest(compiled=compiled, required=required), self.assertRaisesRegex(
                    ValueError, 'provider count/table'):
                ART.compiled_instance_cases(self.compiled(compiled), cases, set())

    def test_published_count_cannot_hide_a_four_row_table(self):
        with self.assertRaisesRegex(ValueError, 'provider count/table'):
            self.check(self.compiled(4, 'PUBLISHED_COUNT=3'), 4)

    def test_missing_fourth_row_cannot_match_a_four_case_contract(self):
        with self.assertRaisesRegex(ValueError, 'case table size/type'):
            self.check(self.compiled(4, 'OMIT_LAST_ROW'), 4)

    def test_missing_loopback_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'callable provider.*rzv2h_spi_sample_loopback_at'):
            self.check(self.compiled(4, 'OMIT_LOOPBACK_PROVIDER'), 4)

    def test_null_loopback_case_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'case function pointer.*instance.loopback'):
            self.check(self.compiled(4, 'NULL_LOOPBACK'), 4)

    def test_loopback_must_follow_the_three_prerequisite_cases(self):
        with self.assertRaisesRegex(ValueError, 'case identity/order'):
            self.check(self.compiled(4, 'SWAP_LAST_ROWS'), 4)

    def test_empty_and_duplicate_case_contracts_are_rejected(self):
        for cases in ([], self.CASES + [self.CASES[-1]]):
            with self.subTest(cases=cases), self.assertRaisesRegex(ValueError, 'case contract'):
                ART.compiled_instance_cases(self.compiled(3), cases, set())


class CompiledInstanceArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builds = (BUILDS or DEFAULT_BUILDS).resolve()
        cls.source = (SOURCE or cls.builds.parent/'source-state.json').resolve()
        if not cls.builds.is_dir() or not cls.source.is_file():
            raise RuntimeError('real compiler archive required; provide --builds/--source-state')
        cls.policy = json.loads((cls.source.parent/'sample-profiles.json').read_text())
        cls.rows = [row for row in cls.policy['profiles'] if 'instance_id' in row and
                    (cls.builds/row['profile']/'build-receipt.json').is_file()]
        if not cls.rows:
            raise RuntimeError('archive has no completed instance images')
        cls.baseline = next((row for row in cls.rows if row['instance']['family'] == 'riic'), None)
        if cls.baseline is None:
            raise RuntimeError('a real RIIC instance image is required for provider mutants')

    def copied(self):
        temporary = tempfile.TemporaryDirectory(prefix='rzv2h-instance-artifact-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root/'source-state.json'
        shutil.copy2(self.source, source)
        for name in ('sample-profiles.json', 'legacy-sample-profiles.json', 'driver-coverage.json'):
            shutil.copy2(self.source.parent/name, root/name)
        row = copy.deepcopy(self.baseline)
        directory = root/'builds'/row['profile']
        shutil.copytree(self.builds/row['profile'], directory)
        return row, directory, source

    def verify(self, inputs):
        return ART.verify_native(*inputs, self.policy)

    def rehash(self, directory, name):
        path = directory/'build-receipt.json'
        receipt = json.loads(path.read_text())
        receipt['file_sha256'][name] = hashlib.sha256((directory/name).read_bytes()).hexdigest()
        path.write_text(json.dumps(receipt))
        self.assertEqual(receipt['file_sha256'][name], ART.INVENTORY.digest(directory/name))

    def patch_word(self, directory, address, value):
        path = directory/'nuttx.elf'
        data = bytearray(path.read_bytes())
        struct.pack_into('<I', data, virtual_offset(data, address), value)
        path.write_bytes(data)
        self.rehash(directory, 'nuttx.elf')

    def table(self, directory):
        data = (directory/'nuttx.elf').read_bytes()
        tables = [item for item in ART.elf32_symbols(data)['g_cases'] if item[1:3] == (36, 1)]
        self.assertEqual(len(tables), 1)
        return tables[0][0]

    def address(self, directory, name):
        data = (directory/'nuttx.elf').read_bytes()
        return ART.elf32_symbols(data)[name][0][0]

    def test_completed_images_admit_or_explicitly_reject_missing_gpt_pwm(self):
        for row in self.rows:
            inputs = row, self.builds/row['profile'], self.source
            config = ART.INVENTORY.read_config(inputs[1]/'resolved.config')
            with self.subTest(profile=row['profile']):
                if row['instance']['family'] == 'gpt' and config.get('CONFIG_RZV_PWM') != 'y':
                    # The historical v2 GPT image lacks its lower-half provider.
                    with self.assertRaisesRegex(ValueError, 'CONFIG_RZV_PWM'):
                        self.verify(inputs)
                else:
                    result = self.verify(inputs)
                    self.assertEqual(result['status'], 'BUILD-CHECKED')
                    self.assertEqual(result['on_target'], 'NOT-RUN')
                    self.assertFalse(result['artifact_authorized'])
                    self.assertFalse(result['target_prerequisites_verified'])

    def test_rehashed_wrong_resolved_selectors_are_rejected(self):
        for suffix, value in (('CHANNEL', '99'), ('FAMILY', '5'), ('OUTPUT', '1')):
            inputs = self.copied()
            path = inputs[1]/'resolved.config'
            key = 'CONFIG_TESTING_RZV_HWTEST_INSTANCE_' + suffix
            text, changes = ART.re.subn(r'(?m)^' + key + r'=.*$', key + '=' + value,
                                        path.read_text())
            self.assertEqual(changes, 1)
            path.write_text(text)
            self.rehash(inputs[1], 'resolved.config')
            with self.subTest(selector=suffix), self.assertRaisesRegex(ValueError, 'selector mismatch'):
                self.verify(inputs)

    def test_rehashed_missing_driver_getter_and_case_functions_are_rejected(self):
        for symbol in ('rzv_i2c_initialize', 'driver_instance_cases', 'guard'):
            inputs = self.copied()
            elf = inputs[1]/'nuttx.elf'
            subprocess.run(['arm-none-eabi-objcopy', '--redefine-sym',
                            symbol + '=unavailable_' + symbol, str(elf)],
                           check=True, capture_output=True)
            self.rehash(inputs[1], 'nuttx.elf')
            with self.subTest(symbol=symbol), self.assertRaisesRegex(
                    ValueError, 'implementation not linked|callable provider'):
                self.verify(inputs)

    def test_rehashed_object_or_weak_provider_is_not_callable_evidence(self):
        for name, info in (('rzv_i2c_initialize', 0x11), ('rzv_i2c_initialize', 0x22),
                           ('guard', 0x01)):
            inputs = self.copied()
            path = inputs[1]/'nuttx.elf'
            data = bytearray(path.read_bytes())
            data[symbol_entry(data, name) + 12] = info
            path.write_bytes(data)
            self.rehash(inputs[1], 'nuttx.elf')
            with self.subTest(symbol=name, info=info), self.assertRaisesRegex(
                    ValueError, 'callable provider'):
                self.verify(inputs)

    def test_rehashed_null_wrong_data_and_interior_case_pointers_are_rejected(self):
        for kind in ('null', 'wrong-function', 'data', 'interior'):
            inputs = self.copied()
            table = self.table(inputs[1])
            pointer = {'null': 0, 'wrong-function': self.address(inputs[1], 'hwtest_main'),
                       'data': table, 'interior': self.address(inputs[1], 'guard') + 4}[kind]
            self.patch_word(inputs[1], table + 8, pointer)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'case function pointer'):
                self.verify(inputs)

    def test_rehashed_duplicate_rows_and_wrong_case_names_are_rejected(self):
        for kind in ('duplicate-row', 'wrong-name', 'null-suite', 'unmapped-name'):
            inputs = self.copied()
            path = inputs[1]/'nuttx.elf'
            data = bytearray(path.read_bytes())
            table = self.table(inputs[1])
            offset = virtual_offset(data, table, 36)
            if kind == 'duplicate-row':
                data[offset + 12:offset + 24] = data[offset:offset + 12]
            else:
                field, value = {'wrong-name': (4, struct.unpack_from('<I', data, offset + 16)[0]),
                                'null-suite': (0, 0), 'unmapped-name': (4, 0xffff0000)}[kind]
                struct.pack_into('<I', data, offset + field, value)
            path.write_bytes(data)
            self.rehash(inputs[1], 'nuttx.elf')
            with self.subTest(kind=kind), self.assertRaisesRegex(
                    ValueError, 'case identity|case string|file-backed'):
                self.verify(inputs)

    def test_rehashed_getter_wrong_count_and_null_table_are_rejected(self):
        for kind in ('count', 'table'):
            inputs = self.copied()
            address = self.address(inputs[1], 'driver_instance_cases')
            self.patch_word(inputs[1], address if kind == 'count' else address + 16,
                            0xe3a03002 if kind == 'count' else 0)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'provider count/table'):
                self.verify(inputs)

    def test_rehashed_truncated_table_symbol_is_rejected(self):
        inputs = self.copied()
        path = inputs[1]/'nuttx.elf'
        data = bytearray(path.read_bytes())
        struct.pack_into('<I', data, symbol_entry(data, 'g_cases') + 8, 24)
        path.write_bytes(data)
        self.rehash(inputs[1], 'nuttx.elf')
        with self.assertRaisesRegex(ValueError, 'case table size/type'):
            self.verify(inputs)

    def test_rehashed_getter_clobbering_return_register_is_rejected(self):
        inputs = self.copied()
        getter = self.address(inputs[1], 'driver_instance_cases')
        # MOV lr,#3; STR lr,[r0] still writes the expected count, but BX lr
        # cannot return to hwtest. The getter decoder must preserve the ABI.
        self.patch_word(inputs[1], getter, 0xe3a0e003)
        self.patch_word(inputs[1], getter + 4, 0xe580e000)
        with self.assertRaisesRegex(ValueError, 'case provider register'):
            self.verify(inputs)

    def test_rehashed_main_disconnected_from_case_provider_is_rejected(self):
        inputs = self.copied()
        path = inputs[1]/'nuttx.elf'
        data = bytearray(path.read_bytes())
        main, size = ART.elf32_symbols(data)['hwtest_main'][0][:2]
        getter = self.address(inputs[1], 'driver_instance_cases')
        code = ART.elf32_bytes(data, main, size, executable=True)
        patched = 0
        for index in range(0, len(code) - 3, 4):
            word = struct.unpack_from('<I', code, index)[0]
            if word & 0xff000000 != 0xeb000000:
                continue
            displacement = word & 0xffffff
            if displacement & 0x800000:
                displacement -= 0x1000000
            if main + index + 8 + displacement * 4 == getter:
                struct.pack_into('<I', data, virtual_offset(data, main + index), 0xe1a00000)
                patched += 1
        self.assertEqual(patched, 1)
        path.write_bytes(data)
        self.rehash(inputs[1], 'nuttx.elf')
        with self.assertRaisesRegex(ValueError, 'does not call the instance case provider'):
            self.verify(inputs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builds', type=Path)
    parser.add_argument('--source-state', type=Path)
    args, remaining = parser.parse_known_args()
    BUILDS, SOURCE = args.builds, args.source_state
    unittest.main(argv=[__file__, *remaining])
