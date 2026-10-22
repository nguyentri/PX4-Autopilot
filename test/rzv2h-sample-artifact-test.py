#!/usr/bin/env python3
"""Check artifact admission using real archived compiler outputs, host only."""
import argparse
import copy
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDS = None
SOURCE_STATE = None
PROFILES = json.loads((ROOT/'platforms/nuttx/Debug/rzv2h-sample-profiles.json').read_text())['profiles']
SPEC = importlib.util.spec_from_file_location('artifact', ROOT/'platforms/nuttx/Debug/rzv2h-sample-artifact-check.py')
ARTIFACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACT)


def verify(profile, directory, source_state=None):
    return ARTIFACT.verify(profile, directory, source_state or SOURCE_STATE)


class ElfBounds(unittest.TestCase):
    def test_invalid_and_truncated_header(self):
        for data in (b'', b'\x7fELF', b'\x7fELF\x01\x01\x01'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                ARTIFACT.elf32_bytes(data, 0, 1)


class ArchiveAdmission(unittest.TestCase):
    def artifact(self, name='serial-board-rtt'):
        profile = next(p for p in PROFILES if p['profile'] == name)
        self.assertIsNotNone(BUILDS, 'integration checks require --builds')
        directory = BUILDS/name
        self.assertTrue((directory/'build-receipt.json').is_file(),
                        'missing required build receipt: ' + str(directory))
        return profile, directory

    def copied(self, directory):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name)
        for name in ('resolved.config', 'nuttx.elf', 'nuttx.map', 'System.map', 'build-receipt.json',
                     'libarch.a', 'rzv_scif.o', 'linker-script.ld'):
            if not (directory/name).exists():
                continue
            shutil.copy2(directory/name, target/name)
        return target

    def load_receipt(self, target):
        return json.loads((target/'build-receipt.json').read_text())

    def write_receipt(self, target, receipt):
        (target/'build-receipt.json').write_text(json.dumps(receipt))

    def refresh_digest(self, target, filename):
        receipt = self.load_receipt(target)
        receipt['file_sha256'][filename] = hashlib.sha256((target/filename).read_bytes()).hexdigest()
        self.write_receipt(target, receipt)

    def test_all_manifest_profiles_are_admitted(self):
        self.assertTrue(PROFILES, 'the sample manifest must contain profiles')
        for profile in PROFILES:
            with self.subTest(profile=profile['profile']):
                self.assertEqual(verify(*self.artifact(profile['profile']))['status'], 'BUILD-CHECKED')

    def test_system_map_requires_a_matching_digest(self):
        profile, directory = self.artifact()
        target = self.copied(directory)
        receipt = self.load_receipt(target)
        del receipt['file_sha256']['System.map']
        self.write_receipt(target, receipt)
        with self.assertRaisesRegex(ValueError, 'missing build digest: System.map'):
            verify(profile, target)
        self.refresh_digest(target, 'System.map')
        path = target/'System.map'
        path.write_text(path.read_text()+'\nchanged\n')
        with self.assertRaisesRegex(ValueError, 'digest mismatch: System.map'):
            verify(profile, target)

    def test_real_builtin_is_callable_without_target_authority(self):
        p, d = self.artifact()
        result = verify(p, d)
        self.assertEqual(result['status'], 'BUILD-CHECKED')
        self.assertEqual(result['on_target'], 'NOT-RUN')
        self.assertFalse(result['artifact_authorized'])
        self.assertFalse(result['target_prerequisites_verified'])
        self.assertGreater(int(result['builtin']['entry'], 16), 0)

    def test_three_character_suite_names(self):
        for name in ('ipc-local-loopback-rtt', 'wdt-nonstart-rtt'):
            with self.subTest(name=name):
                p, d = self.artifact(name)
                self.assertEqual(verify(p, d)['status'], 'BUILD-CHECKED')

    def test_missing_foreground_parent_status_and_wrong_core(self):
        p, d = self.artifact()
        for key in ('CONFIG_SCHED_HAVE_PARENT', 'CONFIG_SCHED_CHILD_STATUS',
                    'CONFIG_RZV2H_BUILD_CR8_0'):
            with self.subTest(key=key):
                target = self.copied(d)
                path = target/'resolved.config'
                path.write_text(path.read_text().replace(key+'=y', '# '+key+' is not set'))
                with self.assertRaisesRegex(ValueError, key):
                    verify(p, target)

    def test_serial_console_cannot_accompany_rtt(self):
        p, d = self.artifact()
        target = self.copied(d)
        path = target/'resolved.config'
        path.write_text(path.read_text()+'\nCONFIG_SCI4_SERIAL_CONSOLE=y\n')
        with self.assertRaisesRegex(ValueError, 'prohibited setting'):
            verify(p, target)

    def test_lower_only_storage_and_ethernet_autostart(self):
        for name, key in (('sdhi-lower-only-rtt', 'CONFIG_MMCSD_SDIO'),
                          ('sdhi-lower-only-rtt', 'CONFIG_FS_FAT'),
                          ('ether-register-rtt', 'CONFIG_NSH_NETINIT'),
                          ('ether-register-rtt', 'CONFIG_NETUTILS_DHCPC'),
                          ('wdt-nonstart-rtt', 'CONFIG_EXAMPLES_WATCHDOG')):
            with self.subTest(key=key):
                p, d = self.artifact(name)
                target = self.copied(d)
                path = target/'resolved.config'
                path.write_text(path.read_text()+'\n'+key+'=y\n')
                with self.assertRaisesRegex(ValueError, 'prohibited setting'):
                    verify(p, target)

    def test_missing_or_nonobject_digest_receipt(self):
        p, d = self.artifact()
        original = json.loads((d/'build-receipt.json').read_text())
        for value in (None, [], 'digest'):
            target = self.copied(d)
            receipt = copy.deepcopy(original)
            if value is None:
                receipt.pop('file_sha256')
            else:
                receipt['file_sha256'] = value
            self.write_receipt(target, receipt)
            with self.assertRaisesRegex(ValueError, 'digest object'):
                verify(p, target)

    def test_elf_receipt_mismatch(self):
        p, d = self.artifact()
        target = self.copied(d)
        receipt = self.load_receipt(target)
        receipt['file_sha256']['nuttx.elf'] = '0'*64
        self.write_receipt(target, receipt)
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify(p, target)

    def test_source_state_digest_and_commits_are_required(self):
        p, d = self.artifact()
        for field, replacement in (('source_state_sha256', None),
                                   ('source_state_sha256', '0'*64),
                                   ('submodule_commits', None),
                                   ('submodule_commits', {}),
                                   ('compiler', None),
                                   ('compiler', 'different toolchain')):
            with self.subTest(field=field, replacement=replacement):
                target = self.copied(d)
                receipt = self.load_receipt(target)
                if replacement is None:
                    receipt.pop(field, None)
                else:
                    receipt[field] = replacement
                self.write_receipt(target, receipt)
                with self.assertRaisesRegex(ValueError, 'source-state'):
                    verify(p, target)

    def test_scif_requires_recorded_link_inputs(self):
        p, d = self.artifact('scif-internal-loopback-rtt')
        for name in ('libarch.a', 'rzv_scif.o'):
            with self.subTest(name=name):
                target = self.copied(d)
                receipt = self.load_receipt(target)
                receipt['file_sha256'].pop(name)
                self.write_receipt(target, receipt)
                with self.assertRaisesRegex(ValueError, 'provenance missing'):
                    verify(p, target)
        target = self.copied(d)
        path = target/'nuttx.map'
        path.write_text(path.read_text().replace('libarch.a(rzv_scif.o)', 'libarch.a(other.o)'))
        self.refresh_digest(target, 'nuttx.map')
        with self.assertRaisesRegex(ValueError, 'recorded linker input'):
            verify(p, target)

    def test_scif_rejects_duplicate_compiled_provider(self):
        p, d = self.artifact('scif-internal-loopback-rtt')
        target = self.copied(d)
        shutil.copy2(target/'rzv_scif.o', target/'second_scif.o')
        subprocess.run(['arm-none-eabi-ar', 'r', str(target/'libarch.a'),
                        str(target/'second_scif.o')], check=True, capture_output=True)
        self.refresh_digest(target, 'libarch.a')
        with self.assertRaisesRegex(ValueError, 'multiple/wrong serial providers'):
            verify(p, target)

    def test_xspi_rejects_changed_weak_default_body(self):
        p, d = self.artifact('xspi-authority-guard-rtt')
        target = self.copied(d)
        elf = target/'nuttx.elf'
        symbols = subprocess.check_output(['arm-none-eabi-nm', str(elf)], text=True)
        address = next(int(line.split()[0], 16) for line in symbols.splitlines()
                       if line.endswith(' W board_xspi_paramfs_validate'))
        data = bytearray(elf.read_bytes())
        ph = struct.unpack_from('<I', data, 28)[0]
        stride, count = struct.unpack_from('<HH', data, 42)
        for index in range(count):
            kind, offset, virtual, _, size, _, _, _ = struct.unpack_from('<8I', data, ph+index*stride)
            if kind == 1 and virtual <= address < virtual+size:
                data[offset+address-virtual] ^= 1
                break
        else:
            self.fail('compiled validator is not file-backed')
        elf.write_bytes(data)
        self.refresh_digest(target, 'nuttx.elf')
        with self.assertRaisesRegex(ValueError, 'not the default denial'):
            verify(p, target)

    def test_wrong_machine_truncated_segment_and_nonexecutability(self):
        _, d = self.artifact()
        original = (d/'nuttx.elf').read_bytes()
        for offset, value in ((18, 183), (42, 0)):
            data = bytearray(original)
            struct.pack_into('<H', data, offset, value)
            with self.assertRaises(ValueError):
                ARTIFACT.elf32_bytes(data, 0, 1)
        data = bytearray(original)
        ph = struct.unpack_from('<I', data, 28)[0]
        stride, count = struct.unpack_from('<HH', data, 42)
        entry = int(verify(*self.artifact())['builtin']['entry'], 16) & ~1
        for i in range(count):
            base = ph+i*stride
            if struct.unpack_from('<I', data, base)[0] == 1:
                flags = struct.unpack_from('<I', data, base+24)[0]
                struct.pack_into('<I', data, base+24, flags & ~1)
        with self.assertRaises(ValueError):
            ARTIFACT.elf32_bytes(data, entry, 1, executable=True)
        data = bytearray(original)
        struct.pack_into('<I', data, ph+16, len(data)+1)
        with self.assertRaises(ValueError):
            ARTIFACT.elf32_bytes(data, entry, 1)


def main():
    global BUILDS, SOURCE_STATE
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--builds', type=Path, help='archive root with one directory per profile')
    mode.add_argument('--unit-only', action='store_true', help='ELF parser tests without artifacts')
    parser.add_argument('--source-state', type=Path, help='defaults to the parent of --builds/source-state.json')
    args = parser.parse_args()
    if args.unit_only:
        if args.source_state:
            parser.error('--source-state requires --builds')
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ElfBounds)
    else:
        BUILDS = args.builds.resolve()
        SOURCE_STATE = (args.source_state or BUILDS.parent/'source-state.json').resolve()
        if not BUILDS.is_dir() or not SOURCE_STATE.is_file():
            parser.error('archive directory and source-state.json must exist')
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
