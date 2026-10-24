#!/usr/bin/env python3
"""Exercise real inventory, source selectors and offline evidence admission."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT/'platforms/nuttx/Debug'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


I = module('driver_inventory', HERE/'rzv2h-sample-inventory.py')
A = module('driver_artifacts', HERE/'rzv2h-sample-artifact-check.py')
C = module('driver_coverage', HERE/'rzv2h-sample-coverage.py')
R = module('driver_runner', HERE/'rzv2h-sample-runner.py')


class InstanceCoverage(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads(I.COVERAGE.read_text())
        self.manifest = json.loads(I.POLICY.read_text())
        cell = next(x for x in self.catalog['instances'] if x['profile'] == 'gpt12-b-board-rtt')
        self.cell = copy.deepcopy(cell)
        self.profile = dict(profile=cell['profile'], core=cell['core'], mode='hwtest', oracle='hwtest',
            commands=['hwtest'], instance_id=cell['instance_id'], instance=cell['instance'],
            hwtest_contract=I.instance_contract(cell['instance']), evidence_class='diagnostic')
        self.profiles = [x for x in self.manifest['profiles'] if x['profile'] != self.profile['profile']]+[self.profile]

    def test_hardware_denominators_and_source_evidence(self):
        I.validate_coverage(self.catalog, self.profiles)
        expected = dict(adc=8, canfd=6, dmac=80, gpio=86, gpt=16, gtm=8, riic=9,
                        sci=10, spi=3, scifa=1, poeg=8, wdt=4, ether=2, sdhi=3, mhu=12)
        actual = {x['family']:sum(len(y) for y in x['channels_by_unit']) for x in self.catalog['domains']}
        self.assertEqual(actual, expected)
        for domain in self.catalog['domains']:
            for path in domain['source_evidence']:
                self.assertTrue((ROOT/path).is_file(), path)
        hardware = C.hardware_coverage(self.catalog, self.profiles, [])
        domains = {x['family']:x for x in hardware['domains']}
        self.assertEqual(domains['gpt']['instance_cells'], 32)
        self.assertEqual(domains['sci']['instance_cells'], 30)
        self.assertEqual(domains['mhu']['reserved'], 1)
        self.assertEqual(sum(x['electrical'] for x in domains.values()), 0)
        self.assertEqual(hardware['status'], 'INCOMPLETE')

    def test_gpt_mapping_and_sparse_mhu_are_not_flat_counts(self):
        gpt = next(x for x in self.catalog['domains'] if x['family'] == 'gpt')
        self.assertEqual(gpt['physical_channels_by_unit'], [list(range(8)), list(range(10,18))])
        mhu = next(x for x in self.catalog['domains'] if x['family'] == 'mhu')
        self.assertEqual(mhu['channels_by_unit'][0], [3,4,9,10,15,16,21,22,28,34,40,41])
        self.assertEqual((self.profile['instance']['unit'], self.profile['instance']['channel'],
                          self.profile['instance']['output']), (1,12,'B'))

    def test_unknown_duplicate_omitted_and_mismatched_instances_fail(self):
        for change in ('unknown', 'duplicate', 'omitted', 'channel', 'mode', 'output', 'unit', 'profile', 'command'):
            profiles = copy.deepcopy(self.profiles)
            row = profiles[-1]
            if change == 'unknown': row['instance_id'] = 'unknown-instance'
            if change == 'duplicate': profiles.append(copy.deepcopy(row))
            if change == 'omitted':
                for key in ('instance_id','instance','hwtest_contract'): row.pop(key)
            if change in ('channel','unit'): row['instance'][change] += 1
            if change == 'mode': row['instance']['mode'] = 'oneshot'
            if change == 'output': row['instance']['output'] = 'A'
            if change == 'profile': row['profile'] = 'gpt12-a-board-rtt'
            if change == 'command': row['commands'] = ['hwtest', 'hwtest']
            with self.subTest(change=change), self.assertRaises(ValueError):
                I.validate_coverage(self.catalog, profiles)

    def test_baseline_profiles_cannot_disappear_as_inventory_grows(self):
        profiles = copy.deepcopy(self.profiles)
        profiles.pop(0)
        with self.assertRaisesRegex(ValueError, 'baseline'):
            I.validate_coverage(self.catalog, profiles)

    def test_typed_telemetry_matches_actual_tuple_and_positive_identity(self):
        spec = self.profile['hwtest_contract']
        text = ('TEST_STATE: instance_family=gpt instance_unit=1 instance_channel=12 '
                'instance_output=B instance_identity=4096')
        self.assertEqual(R.decode_state(text, spec)['instance_identity'], 4096)
        for field, value in [('instance_channel=12','instance_channel=11'),
                             ('instance_output=B','instance_output=A'),
                             ('instance_identity=4096','instance_identity=0')]:
            with self.subTest(field=field), self.assertRaises(R.EvidenceError):
                R.decode_state(text.replace(field,value), spec)
        for field in ('instance_channel', 'instance_identity'):
            row = copy.deepcopy(self.profile)
            row['hwtest_contract']['target_state_required'].pop(field)
            with self.assertRaises(ValueError):
                I.validate_coverage(self.catalog, self.profiles[:-1]+[row])

    def test_unknown_suites_never_resolve_to_hil_full(self):
        for name in ('unknown', 'hil-new', 'hil-spi-unreviewed'):
            with self.subTest(name=name), self.assertRaisesRegex(R.EvidenceError, 'unknown native hwtest suite'):
                R.native_cases(dict(profile=name))
        self.assertEqual(R.native_cases(dict(profile='hil-full'))['mode'], 'hil-full')

    def test_configured_tuple_and_instance_contract_are_generated(self):
        metadata = I.configured_instance(self.cell['required_config'], self.cell['profile'], 'cr8_0', self.catalog)
        for key in ('instance_id','instance','hwtest_contract'):
            self.assertEqual(metadata[key], self.profile[key])
        for suffix, value in (('FAMILY','99'),('CHANNEL','16'),('OUTPUT','2')):
            config = dict(self.cell['required_config'])
            config['CONFIG_TESTING_RZV_HWTEST_INSTANCE_'+suffix] = value
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                I.configured_instance(config, self.cell['profile'], 'cr8_0', self.catalog)

    def test_real_fixed_defconfigs_match_catalog_selectors_and_generated_metadata(self):
        for cell in self.catalog['instances']:
            path=ROOT/I.BOARD/'configs'/cell['profile']/'defconfig'
            config=I.read_config(path)
            with self.subTest(profile=cell['profile']):
                metadata=I.configured_instance(config,cell['profile'],cell['core'],self.catalog)
                self.assertEqual(metadata['instance'],cell['instance'])
                for key,value in cell['required_config'].items():
                    self.assertEqual(config.get(key,'n'),value,key)
                for symbol in cell['required_symbols']:
                    if symbol=='hwtest_main':continue
                    self.assertTrue(any(symbol+'(' in (ROOT/source).read_text() or
                                        symbol+' (' in (ROOT/source).read_text()
                                        for source in cell['source_evidence']),symbol)

    def test_inventory_regeneration_is_deterministic_and_keeps_native_policy(self):
        generated=I.generate(self.manifest)
        self.assertEqual(I.generate(generated),generated)
        self.assertEqual(generated,self.manifest)
        self.assertEqual(sum('instance_id' in row for row in generated['profiles']),len(self.catalog['instances']))

    def test_only_native_spi_gets_four_cases_and_requires_loopback_provider(self):
        instances=[x for x in self.manifest['profiles'] if 'instance_id' in x]
        self.assertEqual(len(instances),73)
        for row in instances:
            expected=4 if row['instance']['family']=='spi' else 3
            self.assertEqual(len(row['hwtest_contract']['required_case_ids']),expected)
            self.assertEqual(row['hwtest_contract']['expected_summary'],dict(passed=expected,failed=0,skipped=0))
            if row['instance']['family']=='spi':
                self.assertEqual(row['evidence_class'],'internal-function')
                self.assertEqual(row['requirements'],['controller-clock-ownership','pad-ownership'])
        catalog=copy.deepcopy(self.catalog)
        cell=next(x for x in catalog['instances'] if x['profile']=='spi0-board-rtt')
        cell['required_symbols'].remove('rzv2h_spi_sample_loopback_at')
        with self.assertRaisesRegex(ValueError,'loopback implementation'):
            I.validate_coverage(catalog,self.manifest['profiles'])
        historical=copy.deepcopy(self.manifest)
        for row in historical['profiles']:
            if row.get('instance',{}).get('family')=='spi':
                row['hwtest_contract']['required_case_ids'].pop()
                row['hwtest_contract']['expected_summary']['passed']=3
        I.validate_coverage(self.catalog,historical['profiles'])

    def test_dmac_batches_cover_all_channels_within_real_nsh_argument_limits(self):
        kconfig=(ROOT/'platforms/nuttx/NuttX/apps/nshlib/Kconfig').read_text()
        default=int(I.re.search(r'config NSH_MAXARGUMENTS\n\s*int[^\n]*\n\s*default (\d+)',kconfig)[1])
        for name in ('dmac-memcpy','dmac-memcpy-rtt'):
            row=next(x for x in self.manifest['profiles'] if x['profile']==name)
            config=I.read_config(ROOT/I.BOARD/'configs'/name/'defconfig')
            limit=int(config.get('CONFIG_NSH_MAXARGUMENTS',default))
            self.assertEqual(len(row['commands']),16)
            self.assertTrue(all(len(command.split())<=limit for command in row['commands']))
            self.assertEqual([x for batch in I.dmac_batches(row) for x in batch],list(range(80)))
            self.assertEqual(row['requirements'],[])
            self.assertEqual(row['hazards'],[])
        legacy=dict(row,commands=['rzv_dmac 0 16 32 48 64'])
        body='\n'.join(f'PASS: DMAC memcpy ch={x}' for x in (0,16,32,48,64))
        self.assertEqual(R.check_dmac(legacy,body),[0,16,32,48,64])
        with self.assertRaises(R.EvidenceError):R.check_dmac(row,body)
        for command in ('rzv_dmac 0 0','rzv_dmac 80','rzv_dmac 0; reboot','rzv_dmac 00',
                        'rzv_dmac '+' '.join(str(x) for x in range(80))):
            with self.subTest(command=command),self.assertRaises(ValueError):I.dmac_batches(dict(commands=[command]))

    def test_non_executable_metadata_is_source_backed_and_excluded_from_totals(self):
        categories=('core_private_timers','shared_timer_services','non_channel_services','header_only_ip')
        hardware=C.hardware_coverage(self.catalog,self.profiles,[])
        for category in categories:
            self.assertTrue(self.catalog[category])
            self.assertEqual(hardware['non_executable_metadata'][category],self.catalog[category])
            for record in self.catalog[category]:
                self.assertFalse(record['executable'])
                self.assertIn(record['state'],('reference-only','unimplemented'))
                for path in record['source_evidence']:self.assertTrue((ROOT/path).is_file(),path)
        self.assertEqual({x['name'] for x in self.catalog['header_only_ip']},
                         {'CRC','I3C','PDM','SSI','XSPI','RTC','CMTW'})
        stripped={k:v for k,v in self.catalog.items() if k not in categories}
        self.assertEqual(hardware['domains'],C.hardware_coverage(stripped,self.profiles,[])['domains'])
        for change in ('executable','state','blockers'):
            catalog=copy.deepcopy(self.catalog)
            record=catalog['header_only_ip'][0]
            if change=='executable':record[change]=True
            if change=='state':record[change]='implemented'
            if change=='blockers':record[change]=[]
            with self.subTest(change=change),self.assertRaises(ValueError):I.validate_coverage(catalog,self.profiles)

    def test_required_case_skip_and_duplicate_contract_cases_are_rejected(self):
        for change in ('skip','duplicate','unknown-type'):
            contract = copy.deepcopy(self.profile['hwtest_contract'])
            if change == 'skip': contract['expected_summary'].update(passed=2, skipped=1)
            if change == 'duplicate': contract['required_case_ids'][1] = contract['required_case_ids'][0]
            if change == 'unknown-type': contract['target_state_types']['instance_identity'] = 'counter'
            with self.subTest(change=change), self.assertRaises(ValueError): I.validate_hwtest(contract)

    def test_resolved_selector_mutants_cannot_be_hidden_by_catalog_rehash(self):
        config = dict(self.cell['required_config'])
        symbols = {x:1 for x in self.cell['required_symbols']}
        strings = ['driver-instance','instance','guard','identity','stable']
        receipt = {k:self.profile[k] for k in ('instance_id','instance')}
        receipt['core'] = self.profile['core']
        A.verify_instance(self.profile, config, symbols, strings, self.catalog, receipt)
        for suffix, value in (('CHANNEL','11'),('OUTPUT','0'),('FAMILY','1')):
            changed = dict(config)
            key = 'CONFIG_TESTING_RZV_HWTEST_INSTANCE_'+suffix
            changed[key] = value
            catalog = copy.deepcopy(self.catalog)
            next(x for x in catalog['instances'] if x['instance_id'] == self.cell['instance_id'])['required_config'][key] = value
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'selector mismatch'):
                A.verify_instance(self.profile, changed, symbols, strings, catalog, receipt)
        symbols.pop('rzv_gpt_initialize_output')
        with self.assertRaisesRegex(ValueError, 'implementation not linked'):
            A.verify_instance(self.profile, config, symbols, strings, self.catalog, receipt)

    def test_unconfigured_and_historical_cells_remain_blocked(self):
        hardware = C.hardware_coverage(self.catalog, self.profiles, [])
        self.assertTrue(all(x['gates'] for d in hardware['domains'] for x in d['cells']))
        historical = C.hardware_coverage(self.catalog, self.profiles, [], bound=False)
        self.assertEqual(sum(x['configured'] for x in historical['domains']), 0)
        self.assertEqual(historical['contract_binding'], 'historical-unbound')


class ArchivedContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path, name in [(I.POLICY,'sample-profiles.json'), (I.LEGACY,'legacy-sample-profiles.json'),
                           (I.COVERAGE,'driver-coverage.json')]:
            (self.root/name).write_bytes(path.read_bytes())
        self.records = I.contract_inputs(self.root/'sample-profiles.json',
            self.root/'legacy-sample-profiles.json', self.root/'driver-coverage.json')
        self.state = dict(manifest_sha256=self.records[0]['sha256'], contract_inputs=self.records)
        self.source = self.root/'source-state.json'
        self.write()

    def write(self):
        self.source.write_text(json.dumps(self.state))

    def test_all_three_distinct_roles_are_verified_and_read_from_archive(self):
        contracts = I.archived_contracts(self.source, dict(contract_inputs=self.records), required=True)
        self.assertEqual(set(contracts), set(I.CONTRACT_PATHS))
        self.assertEqual(len(contracts['legacy_contract']['profiles']), 14)
        self.assertEqual(contracts['driver_coverage']['kind'], 'rzv2h-driver-coverage')

    def test_unknown_duplicate_missing_or_mismatched_roles_and_paths_fail(self):
        for change in ('unknown','duplicate','omitted','path','hash'):
            self.state['contract_inputs'] = copy.deepcopy(self.records)
            records = self.state['contract_inputs']
            if change == 'unknown': records[1]['role'] = 'another-contract'
            if change == 'duplicate': records[1] = records[0]
            if change == 'omitted': records.pop()
            if change == 'path': records[1]['path'] = '../legacy.json'
            if change == 'hash': records[1]['sha256'] = '0'*64
            self.write()
            with self.subTest(change=change), self.assertRaises(ValueError): I.archived_contracts(self.source)

    def test_receipt_cannot_omit_or_replace_secondary_contract_binding(self):
        for receipt in ({}, dict(contract_inputs=self.records[:-1]), dict(contract_inputs=[])):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(ValueError, 'binding mismatch'):
                I.archived_contracts(self.source, receipt)

    def test_secondary_mutation_and_coherent_rehash_are_detected(self):
        path = self.root/'driver-coverage.json'
        catalog = json.loads(path.read_text())
        catalog['instances'][0]['required_symbols'] = []
        path.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'): I.archived_contracts(self.source)
        self.state['contract_inputs'][2]['sha256'] = I.digest(path)
        self.write()
        with self.assertRaisesRegex(ValueError, 'selector/link/source'): I.archived_contracts(self.source)

    def test_historical_source_remains_unbound_and_cannot_admit_instances(self):
        self.state.pop('contract_inputs'); self.write()
        self.assertEqual(I.archived_contracts(self.source), {})
        with self.assertRaisesRegex(ValueError, 'inputs required'):
            I.archived_contracts(self.source, required=True)


if __name__ == '__main__':
    unittest.main()
