#!/usr/bin/env python3
"""Coverage publication cannot turn blocked or warm-only rows into green."""

import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('coverage',ROOT/'platforms/nuttx/Debug/rzv2h-sample-coverage.py')
C=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


class CoverageClosure(unittest.TestCase):
    def setUp(self):
        self.profiles=C.ART.INVENTORY.load()['profiles']
        self.report={'status':'INCOMPLETE','profiles':[dict(profile=x['profile'],core=x['core'],evidence_class=x['evidence_class'],build_state='BUILD-CHECKED',
                     runtime_state='BLOCKED',blocker='fixture unverified',warm_qualified=False,cold_qualified=False,
                     reset_class=None,evidence=[],release_blockers=['cold and fixture pending']) for x in self.profiles]}

    def test_complete_partial_report_retains_all_55_rows(self):
        self.assertEqual(len(C.validate(self.report,self.profiles)['profiles']),55)

    def test_duplicate_missing_and_unknown_profiles_fail(self):
        for mutation in ('duplicate','missing','unknown'):
            report=copy.deepcopy(self.report)
            if mutation=='duplicate':report['profiles'][-1]=report['profiles'][0]
            if mutation=='missing':report['profiles'].pop()
            if mutation=='unknown':report['profiles'][0]['profile']='unreviewed'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):C.validate(report,self.profiles)

    def test_global_pass_cannot_hide_blocked_or_warm_only_rows(self):
        self.report['status']='PASS'
        with self.assertRaisesRegex(ValueError,'global PASS'):C.validate(self.report,self.profiles)
        for row in self.report['profiles']:
            row.update(runtime_state='PASS',warm_qualified=True,reset_class='warm-load',
                       evidence=['named-receipt'],elf_sha256='a'*64)
        with self.assertRaisesRegex(ValueError,'global PASS'):C.validate(self.report,self.profiles)

    def test_row_pass_requires_real_evidence_and_reset_class(self):
        row=self.report['profiles'][0];row['runtime_state']='PASS'
        with self.assertRaisesRegex(ValueError,'bounded evidence'):C.validate(self.report,self.profiles)

    def test_unexecuted_rows_need_blockers_and_cold_cannot_be_inferred(self):
        self.report['profiles'][0]['blocker']=''
        with self.assertRaisesRegex(ValueError,'concrete blocker'):C.validate(self.report,self.profiles)
        self.report['profiles'][0]['blocker']='fixture'
        self.report['profiles'][0]['cold_qualified']=True
        with self.assertRaisesRegex(ValueError,'cold qualification'):C.validate(self.report,self.profiles)

    def test_a_later_connect_failure_cannot_hide_an_actual_sample_failure(self):
        rows=self.report['profiles']
        rows[0].update(runtime_state='FAIL',blocker='actual payload mismatch')
        rows[1].update(runtime_state='NOT-RUN',blocker='batch pending')
        C.mark_stopped(rows,'DBGEN not asserted')
        self.assertEqual(rows[0]['runtime_state'],'FAIL')
        self.assertEqual(rows[0]['blocker'],'actual payload mismatch')
        self.assertEqual(rows[1]['runtime_state'],'BLOCKED')
        self.assertIn('DBGEN',rows[1]['blocker'])


if __name__=='__main__':unittest.main()
