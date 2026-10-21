#!/usr/bin/env python3
"""Exercise evidence arithmetic and rejection of false qualification receipts."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evidence', ROOT/'Tools/rzv2h-autonomy-evidence.py')
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


def sample(generation=1):
    return {'stream': 'inference', 'session': 'test-session', 'generation': generation, 'generation_kind': 'source',
            'start_us': generation*100, 'end_us': generation*100+20, 'start_clock': 'linux:boot-a:raw',
            'end_clock': 'linux:boot-a:raw', 'endpoint_start': 'runtime-submit', 'endpoint_end': 'runtime-return'}


class MeasurementChecks(unittest.TestCase):
    def test_distributions_preserve_outlier_and_missing_generations(self):
        records = [sample(i) for i in (1, 2, 4)]
        records[-1]['end_us'] += 80
        result = EVIDENCE.analyze(records)[0]
        self.assertEqual(result['samples'], 3)
        self.assertEqual(result['missing_generations'], 1)
        self.assertEqual(result['max_us'], 100)
        self.assertEqual(result['median_us'], 20)
        self.assertAlmostEqual(result['p99_us'], 98.4)
        self.assertNotIn('passed', result)

    def test_cross_clock_offsets_and_uncertainty(self):
        row = sample()
        row['end_clock'] = 'cr8-0:epoch-4:hrt'
        row['end_us'] = 1000020
        with self.assertRaisesRegex(ValueError, 'unsynchronized'):
            EVIDENCE.analyze([row])
        row['clock_mapping'] = {'source_clock': row['start_clock'], 'destination_clock': row['end_clock'],
                                'qualification': 'test mapping, not lab evidence', 'destination_minus_source_us': 999900,
                                'uncertainty_us': 7, 'valid_from_source_us': 0, 'valid_until_source_us': 1000}
        result = EVIDENCE.analyze([row])[0]
        self.assertEqual(result['max_us'], 20)
        self.assertEqual(result['max_upper_bound_us'], 27)
        row['clock_mapping']['valid_until_source_us'] = 99
        with self.assertRaisesRegex(ValueError, 'expired'):
            EVIDENCE.analyze([row])

    def test_bad_values_semantics_replay_and_regression_are_rejected(self):
        for key, value in [('start_us', float('nan')), ('end_us', float('inf')), ('generation', True),
                           ('generation', 0), ('generation_kind', 'assumed-exposure'), ('end_us', -1)]:
            row = sample(); row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                EVIDENCE.analyze([row])
        for second in (sample(), {**sample(2), 'start_us': 1}, {**sample(2), 'endpoint_end': 'camera-exposure'}):
            with self.assertRaises(ValueError):
                EVIDENCE.analyze([sample(), second])

    def test_epoch_changes_have_separate_distributions(self):
        second = sample(); second['session'] = 'new-session'
        self.assertEqual(len(EVIDENCE.analyze([sample(), second])), 2)


class ReceiptChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='rzv2h-evidence-test-')
        self.root = Path(self.directory.name)
        (self.root/'parameters.bin').write_bytes(b'host test parameter bytes')
        (self.root/'calibration.bin').write_bytes(b'host test calibration bytes')
        self.raw = [{'path': name, 'sha256': hashlib.sha256((self.root/name).read_bytes()).hexdigest()}
                    for name in ('parameters.bin', 'calibration.bin')]
        self.ledger = {'schema': 1, 'cards': [{'id': card, 'meaning': meaning, 'state': 'not-run',
                                            'limitations': ['host test only']} for card, meaning in EVIDENCE.CARDS.items()]}

    def tearDown(self):
        self.directory.cleanup()

    def test_all_cards_and_meanings_are_required(self):
        self.assertEqual(EVIDENCE.check_ledger(self.ledger, self.root)['passed'], [])
        self.ledger['cards'][-1]['meaning'] = 'physical landing'
        with self.assertRaisesRegex(ValueError, 'meaning drift'):
            EVIDENCE.check_ledger(self.ledger, self.root)

    def test_build_receipt_cannot_pass_physical_card_or_support_claim(self):
        row = self.ledger['cards'][0]
        row.update(state='passed', stage='build-clean', raw=self.raw)
        with self.assertRaises(ValueError):
            EVIDENCE.check_ledger(self.ledger, self.root)
        row.update(state='not-run')
        self.ledger['claims'] = [{'text': 'Customer performance claim', 'cards': ['T00']}]
        with self.assertRaisesRegex(ValueError, 'unpassed'):
            EVIDENCE.check_ledger(self.ledger, self.root)

    def test_raw_tamper_path_traversal_and_symlink(self):
        EVIDENCE.raw_files(self.raw, self.root)
        for path in ('../parameters.bin', '/etc/passwd', 'a/../parameters.bin'):
            bad = copy.deepcopy(self.raw); bad[0]['path'] = path
            with self.assertRaises(ValueError):
                EVIDENCE.raw_files(bad, self.root)
        (self.root/'parameters.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            EVIDENCE.raw_files(self.raw, self.root)
        (self.root/'link').symlink_to(self.root/'calibration.bin')
        with self.assertRaises(ValueError):
            EVIDENCE.raw_files([{'path': 'link', 'sha256': self.raw[1]['sha256']}], self.root)

    def test_provisional_calibration_never_grants_output_readiness(self):
        receipt = {'schema': 1, 'generation': 1, 'physical_identity': 'host-test-fixture', 'image_sha256': 'a'*64,
                   'parameter_schema': 'test-schema', 'sensors': [{'device_id': 1, 'orientation': 0,
                   'serial_or_replacement_epoch': 'maintenance-epoch-1'}], 'raw': self.raw,
                   'parameters_path': 'parameters.bin', 'calibration_path': 'calibration.bin',
                   'storage_class': 'volatile', 'provisional': True}
        result = EVIDENCE.check_calibration(receipt, self.root, 'host-test-fixture', 'a'*64)
        self.assertTrue(result['compatible'])
        self.assertTrue(result['provisional'])
        self.assertFalse(result['output_ready'])
        with self.assertRaisesRegex(ValueError, 'physical identity mismatch'):
            EVIDENCE.check_calibration(receipt, self.root, 'replacement-fixture', 'a'*64)
        receipt['storage_class'] = 'qualified-durable'; receipt['provisional'] = False
        with self.assertRaisesRegex(ValueError, 'durability evidence missing'):
            EVIDENCE.check_calibration(receipt, self.root, 'host-test-fixture', 'a'*64)


if __name__ == '__main__':
    unittest.main()
