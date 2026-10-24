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
                     reset_class=None,evidence=[],release_blockers=['cold and fixture pending'],
                     **{k:x[k] for k in ('instance_id','instance') if k in x}) for x in self.profiles]}
        self.catalog=C.json.loads(C.ART.INVENTORY.COVERAGE.read_text())
        self.report['contract_inputs']=C.ART.INVENTORY.contract_inputs(C.ART.INVENTORY.POLICY)
        for row in self.report['profiles']:
            row['contract_inputs']=self.report['contract_inputs']
        self.report['hardware_coverage']=C.hardware_coverage(self.catalog,self.profiles,self.report['profiles'])

    def test_complete_partial_report_retains_validated_inventory(self):
        catalog=C.json.loads(C.ART.INVENTORY.COVERAGE.read_text())
        self.report['hardware_coverage']=C.hardware_coverage(catalog,self.profiles,self.report['profiles'])
        self.assertEqual(len(C.validate(self.report,self.profiles,catalog)['profiles']),len(self.profiles))

    def test_duplicate_missing_and_unknown_profiles_fail(self):
        for mutation in ('duplicate','missing','unknown'):
            report=copy.deepcopy(self.report)
            if mutation=='duplicate':report['profiles'][-1]=report['profiles'][0]
            if mutation=='missing':report['profiles'].pop()
            if mutation=='unknown':report['profiles'][0]['profile']='unreviewed'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):C.validate(report,self.profiles,self.catalog)

    def test_global_pass_cannot_hide_blocked_or_warm_only_rows(self):
        self.report['status']='PASS'
        with self.assertRaisesRegex(ValueError,'global PASS'):C.validate(self.report,self.profiles,self.catalog)
        for row in self.report['profiles']:
            row.update(runtime_state='PASS',warm_qualified=True,reset_class='warm-load',
                       evidence=['named-receipt'],elf_sha256='a'*64)
            profile=next(x for x in self.profiles if x['profile']==row['profile'])
            if profile['oracle']=='dmac':
                row['target_state']={'dmac_channels':[x for b in C.ART.INVENTORY.dmac_batches(profile) for x in b]}
        with self.assertRaisesRegex(ValueError,'global PASS'):C.validate(self.report,self.profiles,self.catalog)

    def test_row_pass_requires_real_evidence_and_reset_class(self):
        row=self.report['profiles'][0];row['runtime_state']='PASS'
        with self.assertRaisesRegex(ValueError,'bounded evidence'):C.validate(self.report,self.profiles,self.catalog)

    def test_unexecuted_rows_need_blockers_and_cold_cannot_be_inferred(self):
        self.report['profiles'][0]['blocker']=''
        with self.assertRaisesRegex(ValueError,'concrete blocker'):C.validate(self.report,self.profiles,self.catalog)
        self.report['profiles'][0]['blocker']='fixture'
        self.report['profiles'][0]['cold_qualified']=True
        with self.assertRaisesRegex(ValueError,'cold qualification'):C.validate(self.report,self.profiles,self.catalog)

    def test_a_later_connect_failure_cannot_hide_an_actual_sample_failure(self):
        rows=self.report['profiles']
        rows[0].update(runtime_state='FAIL',blocker='actual payload mismatch')
        rows[1].update(runtime_state='NOT-RUN',blocker='batch pending')
        C.mark_stopped(rows,'DBGEN not asserted')
        self.assertEqual(rows[0]['runtime_state'],'FAIL')
        self.assertEqual(rows[0]['blocker'],'actual payload mismatch')
        self.assertEqual(rows[1]['runtime_state'],'BLOCKED')
        self.assertIn('DBGEN',rows[1]['blocker'])

    def test_dmac_function_cells_require_checked_channels_and_merge_duplicate_profiles(self):
        rows=[dict(profile=name,build_state='BUILD-CHECKED',runtime_state='PASS',
                   evidence_class='memory-function',target_state={'dmac_channels':list(range(80))},
                   evidence=[dict(run_id=name,state='PASS')]) for name in ('dmac-memcpy','dmac-memcpy-rtt')]
        hardware=C.hardware_coverage(self.catalog,self.profiles,rows)
        dmac=next(x for x in hardware['domains'] if x['family']=='dmac')
        self.assertEqual((dmac['total'],dmac['instance_cells'],dmac['function']),(80,80,80))
        self.assertEqual(dmac['configured'],80)
        self.assertTrue(all(len(x['evidence'])==2 for x in dmac['cells']))
        rows[0]['target_state']['dmac_channels'].pop()
        with self.assertRaisesRegex(ValueError,'checked channel set'):
            C.hardware_coverage(self.catalog,self.profiles,rows)

    def test_historical_five_position_contract_does_not_expand_to_80_cells(self):
        profiles=copy.deepcopy(self.profiles)
        for profile in profiles:
            if profile['profile'] in ('dmac-memcpy','dmac-memcpy-rtt'):
                profile['commands']=['rzv_dmac 0 16 32 48 64']
        row=dict(profile='dmac-memcpy',build_state='BUILD-CHECKED',runtime_state='PASS',
                 evidence_class='memory-function',target_state={'dmac_channels':[0,16,32,48,64]},evidence=[])
        hardware=C.hardware_coverage(self.catalog,profiles,[row])
        dmac=next(x for x in hardware['domains'] if x['family']=='dmac')
        self.assertEqual((dmac['total'],dmac['configured'],dmac['function']),(80,5,5))

    def test_spi_internal_function_is_credited_only_with_loopback_contract(self):
        row=dict(profile='spi1-board-rtt',build_state='BUILD-CHECKED',runtime_state='PASS',
                 evidence_class='internal-function',evidence=[])
        hardware=C.hardware_coverage(self.catalog,self.profiles,[row])
        spi=next(x for x in hardware['domains'] if x['family']=='spi')
        self.assertEqual((spi['diagnostic'],spi['function']),(0,1))
        historical=copy.deepcopy(self.profiles)
        profile=next(x for x in historical if x['profile']=='spi1-board-rtt')
        profile['hwtest_contract']['required_case_ids'].pop()
        profile['hwtest_contract']['expected_summary']['passed']=3
        profile['evidence_class']='diagnostic'
        row['evidence_class']='diagnostic'
        hardware=C.hardware_coverage(self.catalog,historical,[row])
        spi=next(x for x in hardware['domains'] if x['family']=='spi')
        self.assertEqual((spi['diagnostic'],spi['function']),(1,0))


if __name__=='__main__':unittest.main()
