#!/usr/bin/env python3
"""Lab authority, fail-stop loading and native evidence negative controls."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lab',ROOT/'platforms/nuttx/Debug/rzv2h-sample-lab.py')
LAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAB)


class LabBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_caller_cannot_reenable_loader_retries_or_inject_debug_tools(self):
        with patch.dict(os.environ,{'LOAD_ATTEMPTS':'3','JLINK_GDB':'malicious','LD_PRELOAD':'bad','LD_LIBRARY_PATH':'bad'}):
            env = LAB.environment(self.root,'unit-probe')
        self.assertEqual(env['LOAD_ATTEMPTS'],'1')
        self.assertNotIn('JLINK_GDB',env)
        self.assertNotIn('LD_PRELOAD',env)
        self.assertNotIn('LD_LIBRARY_PATH',env)

    def test_reset_marker_is_terminal_even_when_helper_exits_zero(self):
        with self.assertRaises(LAB.RecoveryRequired):
            LAB.invoke([sys.executable,'-c','print("DBGEN is not asserted")'],
                       os.environ.copy(),self.root,'failure',5)

    def test_bridge_and_temporary_target_logs_stay_in_the_run_directory(self):
        with patch.dict(os.environ, {'STATE_DIR': '/outside/bridge', 'TMPDIR': '/outside/tmp'}):
            env = LAB.environment(self.root, 'unit-probe')
        self.assertEqual(Path(env['STATE_DIR']).parent, self.root)
        temporary = Path(env['TMPDIR'])
        self.assertEqual(temporary.parent, self.root)
        self.assertTrue(temporary.is_dir())
        with tempfile.TemporaryDirectory(dir=env['TMPDIR']) as child:
            self.assertTrue(Path(child).is_relative_to(self.root))

    def test_load_failure_never_starts_a_bridge_or_another_connection(self):
        args = argparse.Namespace(output=self.root,run_id='test',approval_ref='test-user-approval')
        row = {'core':'cr8_0','profile':'canfd-rtt','commands':['can -n 4'],'console':'rtt','entrypoint':'nsh_main','mode':'native','oracle':'can','timeout':15}
        admission = {'elf_sha256':'a'*64,'config_sha256':'b'*64,
                     'source_state_sha256':'c'*64,'waitpid':True}
        called=[]
        def invoke(argv,env,out,label,*args):
            called.append(label)
            if label=='preflight':return '== probe owners\n  none\n== ports\n'
            if label=='post-preflight':return '== probe owners\n  none\n== ports\n'
            if label=='load':raise LAB.RecoveryRequired('injected failed connection')
            self.fail('unexpected operation '+label)
        serial = subprocess.CompletedProcess([],0,'123456\n','')
        with patch.object(LAB.subprocess,'run',return_value=serial), \
             patch.object(LAB,'port_free',return_value=True), \
             patch.object(LAB,'invoke',side_effect=invoke):
            with self.assertRaises(LAB.RecoveryRequired):
                LAB.execute(args,row,admission,self.root,{'initial_state':'bench stopped'})
        self.assertEqual(called,['preflight','load','post-preflight'])
        receipt=json.loads((self.root/'run-receipt.json').read_text())
        self.assertEqual(receipt['target_actions'],['guarded-ram-load'])

    def test_cleanup_requires_observed_process_and_port_release(self):
        with patch.object(LAB,'ports_free',return_value=True), \
             patch.object(LAB,'invoke',return_value='== probe owners\n  12 JLinkExe\n== ports\n'):
            observed = LAB.cleanup_observation({},self.root,'')
        self.assertFalse(observed['owned_pid_dead'])
        self.assertFalse(observed['bridge_stopped'])

    def test_failed_shutdown_still_checkpoints_and_redacts_logs(self):
        args=argparse.Namespace(output=self.root,run_id='cleanup',approval_ref='unit-approval')
        row={'core':'cr8_0','profile':'canfd-rtt','console':'rtt','entrypoint':'nsh_main',
             'mode':'native','commands':['can -n 4'],'oracle':'can','timeout':5}
        admission={'elf_sha256':'a'*64,'config_sha256':'b'*64,'source_state_sha256':'c'*64,'waitpid':False}
        (self.root/'private.log').write_text('probe 123456')
        def invoke(argv,env,out,label,*rest):
            if label=='preflight':return '== probe owners\n none\n== ports\n'
            if label=='sync':raise LAB.LabError('original console failure')
            if label=='bridge-stop-final':raise LAB.LabError('shutdown failed')
            return ''
        with patch.object(LAB.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'123456\n','')), \
             patch.object(LAB,'ports_free',return_value=True),patch.object(LAB,'invoke',side_effect=invoke):
            with self.assertRaisesRegex(LAB.LabError,'original console failure'):
                LAB.execute(args,row,admission,self.root,{'initial_state':'known bench'})
        receipt=json.loads((self.root/'run-receipt.json').read_text())
        self.assertIn('shutdown failed',receipt['cleanup_error'])
        self.assertFalse(receipt['cleanup']['owned_pid_dead'])
        self.assertNotIn('123456',(self.root/'private.log').read_text())

    def test_cm33_and_unbounded_boot_are_refused_before_any_archive_access(self):
        for name in ('nsh-cm33','ipcc-raw-cm33','wdt','ether'):
            with self.subTest(name=name), self.assertRaises(LAB.LabError):
                LAB.prepare(self.root/'missing',name,{'reset_class':'warm-load','initial_state':'known','verified':{}})

    def test_external_fixture_cannot_be_inferred_from_artifact_flags(self):
        with self.assertRaisesRegex(LAB.LabError,'fixture prerequisites'):
            LAB.prepare(self.root/'missing','bmm150',{'reset_class':'warm-load','initial_state':'known','verified':{}})

    def test_task_census_contains_only_guarded_read_commands(self):
        reader=LAB.module('reader',ROOT/'platforms/nuttx/Debug/jlink-gdb-oneshot.py')
        for line in LAB.TASK_GDB.splitlines():
            self.assertIsNone(reader.mutation_reason(line),line)


class NativeEvidence(unittest.TestCase):
    def setUp(self):
        self.profile=copy.deepcopy(next(x for x in LAB.ARTIFACT.INVENTORY.load()['profiles']
                                       if x['profile']=='canfd-rtt'))
        self.admission={'status':'BUILD-CHECKED','elf_sha256':'a'*64,'config_sha256':'b'*64,
                        'source_state_sha256':'c'*64,'waitpid':True,'application_entry':'0x40801000'}
        payload=[];first=0
        for length in range(1,5):
            payload.extend([f'ID: {length} DLC: {length}',f'ID: {length} DLC: {length}','Data received:'])
            payload.extend(f'{i}: 0x{first+i:02x}' for i in range(length));first+=length
        self.transcript='RUN_BEGIN: test\n'+'\n'.join(payload)+'\nTerminating!\nAPP_EXIT_0=0\nRUN_END: test\nnsh> '
        self.health='nsh> ps\nPID PRI NAME\n0 0 idle\n1 100 nsh_main\nnsh> '
        self.receipt={'profile':'canfd-rtt','commands':['can -n 4'],'run_id':'test',
                      'elf_sha256':'a'*64,'config_sha256':'b'*64,'source_state_sha256':'c'*64,
                      'timed_out':False,'approval_reference':'unit-user-approval',
                      'reset_class':'warm-load','initial_state':'known predecessor',
                      'cleanup':{'bridge_stopped':True,'owned_pid_dead':True,'port_free':True}}
        self.receipt.update(policy_sha256=LAB.sha(LAB.ARTIFACT.INVENTORY.POLICY),
                            executor_sha256=LAB.sha(Path(LAB.__file__)))

    def verify(self):
        for name,text in [('transcript',self.transcript),('health',self.health)]:
            self.receipt[name+'_sha256']=hashlib.sha256(text.encode()).hexdigest()
        return LAB.RUNNER.check_native(self.profile,self.transcript,self.health,self.receipt,self.admission)

    def test_native_payload_and_exit_are_required(self):
        self.assertEqual(self.verify()['status'],'PASS')
        self.transcript=self.transcript.replace('0: 0x00','0: 0xff')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'payload mismatch'):
            self.verify()

    def test_receipt_cannot_replace_reviewed_executor_or_policy(self):
        for key in ('policy_sha256','executor_sha256'):
            old=self.receipt[key]
            self.receipt[key]='0'*64
            with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'tool/policy digest'):
                self.verify()
            self.receipt[key]=old

    def test_rehashed_contract_cannot_weaken_installed_execution_policy(self):
        self.profile['evidence_class']='connected-function'
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'reviewed installed policy'):
            self.verify()

    def test_terminal_before_nonzero_exit_cannot_pass(self):
        self.transcript=self.transcript.replace('APP_EXIT_0=0','APP_EXIT_0=1')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'exit status'):
            self.verify()

    def test_passing_terminal_with_resident_task_cannot_pass(self):
        self.health=self.health.replace('nsh> ','4 100 can\nnsh> ',1)
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'task remains'):
            self.verify()

    def test_false_elf_stale_run_and_boot_fault_cannot_pass(self):
        self.receipt['elf_sha256']='d'*64
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'artifact hash'):
            self.verify()
        self.receipt['elf_sha256']='a'*64
        self.transcript=self.transcript.replace('RUN_END: test','RUN_END: stale')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'boundaries'):
            self.verify()
        self.transcript=self.transcript.replace('RUN_END: stale','RUN_END: test')
        self.transcript='data abort\n'+self.transcript
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'fatal'):
            self.verify()

    def test_missing_waitpid_requires_actual_task_census(self):
        self.admission['waitpid']=False
        self.receipt['completion_source']='task-resource-oracle'
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'census'):
            self.verify()
        self.health+='\nTASK_HEALTH_BEGIN count=16\nTASK_ENTRY: 0x40802000\nTASK_HEALTH_END\n'
        self.assertEqual(self.verify()['status'],'PASS')
        self.health=self.health.replace('0x40802000','0x40801000')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'still alive'):
            self.verify()

    def choose(self,name,body):
        self.profile=copy.deepcopy(next(x for x in LAB.ARTIFACT.INVENTORY.load()['profiles'] if x['profile']==name))
        self.receipt.update(profile=name,commands=self.profile['commands'])
        self.transcript='RUN_BEGIN: test\n'+body+'\n'+''.join(
            f'APP_EXIT_{n}=0\n' for n in range(len(self.profile['commands'])))+'RUN_END: test\nnsh> '

    def test_timer_requires_all_samples_and_positive_progress(self):
        body='Start the timer\n'+'\n'.join(f'nsignals: {x//10}' for x in range(24))+'\nStop the timer\nFinished'
        self.choose('gtm-rtt',body)
        self.assertEqual(self.verify()['status'],'PASS')
        self.transcript=self.transcript.replace('nsignals: 2\n','',1)
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'sample count'):self.verify()

    def test_bmm150_scan_and_sample_outputs_have_distinct_grammars(self):
        body='bmm150: scan PASS\nbmm150: self-test X:pass Y:pass Z:pass\n'+''.join(
            f'bmm150: [{n}] uT X=1 Y=2 Z=3 rhall=100\n' for n in range(20))+'bmm150: 20 valid, 0 not-ready, 0 overflow\nbmm150: PASS'
        self.choose('bmm150',body)
        self.assertEqual(self.verify()['status'],'PASS')
        self.assertIsNotNone(LAB.re.search(LAB.TERMINAL['bmm150'],'bmm150: scan PASS'))
        self.transcript=self.transcript.replace('rhall=100','rhall=0',1)
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'sample data'):self.verify()

    def test_dmac_requires_all_80_comparisons_and_every_indexed_batch_exit(self):
        body='\n'.join(f'PASS: DMAC memcpy ch={channel}' for channel in range(80))
        self.choose('dmac-memcpy-rtt',body)
        result=self.verify()
        self.assertEqual(result['state']['dmac_channels'],list(range(80)))
        original=self.transcript
        for old,new in [('PASS: DMAC memcpy ch=79',''),
                        ('PASS: DMAC memcpy ch=7\n','PASS: DMAC memcpy ch=6\n'),
                        ('APP_EXIT_15=0','APP_EXIT_15=1'),
                        ('APP_EXIT_15=0','APP_EXIT_14=0')]:
            self.transcript=original.replace(old,new)
            with self.subTest(new=new),self.assertRaises(LAB.RUNNER.EvidenceError):self.verify()

    def test_each_dmac_batch_has_its_own_terminal_and_legacy_terminal_remains_decodable(self):
        profile=next(x for x in LAB.ARTIFACT.INVENTORY.load()['profiles'] if x['profile']=='dmac-memcpy')
        self.assertEqual(len(profile['commands']),16)
        for index,command in enumerate(profile['commands']):
            terminal=LAB.command_terminal(profile,command)
            last=index*5+4
            self.assertIsNotNone(LAB.re.search(terminal,f'PASS: DMAC memcpy ch={last}\n'))
            self.assertIsNone(LAB.re.search(terminal,f'PASS: DMAC memcpy ch={last+10}\n'))
            self.assertIsNone(LAB.re.search(terminal,f'PASS: DMAC memcpy ch={last}0\n'))
        with self.assertRaises(LAB.LabError):LAB.command_terminal(profile,'rzv_dmac 79')
        legacy=dict(profile,commands=['rzv_dmac 0 16 32 48 64'])
        self.assertIsNotNone(LAB.re.search(LAB.command_terminal(legacy,legacy['commands'][0]),'PASS: DMAC memcpy ch=64'))


class InstanceEvidence(unittest.TestCase):
    def setUp(self):
        self.profile=copy.deepcopy(next(x for x in LAB.ARTIFACT.INVENTORY.load()['profiles']
                                       if x['profile']=='gpt12-b-board-rtt'))
        contracts=LAB.ARTIFACT.INVENTORY.contract_inputs(LAB.ARTIFACT.INVENTORY.POLICY)
        self.admission=dict(status='BUILD-CHECKED',core='cr8_0',elf_sha256='a'*64,
            config_sha256='b'*64,source_state_sha256='c'*64,waitpid=True,
            application_entry='0x40801000',contract_inputs=contracts,
            hwtest_contract=self.profile['hwtest_contract'],
            **{k:self.profile[k] for k in ('instance_id','instance')})
        self.receipt=dict(profile=self.profile['profile'],core='cr8_0',commands=['hwtest'],run_id='instance-test',
            elf_sha256='a'*64,config_sha256='b'*64,source_state_sha256='c'*64,
            contract_inputs=copy.deepcopy(contracts),policy_sha256=LAB.sha(LAB.ARTIFACT.INVENTORY.POLICY),
            executor_sha256=LAB.sha(Path(LAB.__file__)),timed_out=False,
            approval_reference='parser-fixture-only',reset_class='warm-load',initial_state='parser fixture',
            cleanup=dict(bridge_stopped=True,owned_pid_dead=True,port_free=True),
            **{k:copy.deepcopy(self.profile[k]) for k in ('instance_id','instance')})
        self.health='PID PRI NAME\n0 0 idle\n1 100 nsh_main\nnsh> '
        self.transcript='RUN_BEGIN: instance-test\nTEST_ENV: mode=driver-instance expects=diagnostic\n'
        for case in self.profile['hwtest_contract']['required_case_ids']:
            self.transcript+='TEST: '+case+' START\nTEST: '+case+' PASS\n'
        self.transcript+=('TEST_STATE: instance_family=gpt instance_unit=1 instance_channel=12 '
            'instance_output=B instance_identity=4096\nTEST_SUMMARY: passed=3 failed=0 skipped=0\n'
            'TEST_DONE: exit=0\nAPP_EXIT_0=0\nRUN_END: instance-test\nnsh> ')

    def verify(self):
        return NativeEvidence.verify(self)

    def test_fixed_instance_contract_passes_only_its_exact_receipt_tuple(self):
        result=self.verify()
        self.assertEqual(result['instance_id'],'gpt12-b-board-rtt')
        self.assertEqual(result['instance']['output'],'B')
        for key,value in [('instance_id','unknown-instance'),('core','cr8_1')]:
            saved=self.receipt[key];self.receipt[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'instance'):
                self.verify()
            self.receipt[key]=saved
        self.receipt['instance']['output']='A'
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'instance mismatch'):self.verify()

    def test_secondary_contract_bindings_are_required_for_instance_receipts(self):
        self.receipt['contract_inputs'].pop()
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'contract binding'):self.verify()

    def test_rehashed_secondary_contract_cannot_weaken_installed_policy_inputs(self):
        self.receipt['contract_inputs'][1]['sha256']='0'*64
        self.admission['contract_inputs']=copy.deepcopy(self.receipt['contract_inputs'])
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'reviewed installed policy inputs'):self.verify()

    def test_wrong_actual_identity_or_required_skip_cannot_pass(self):
        original=self.transcript
        for old,new in [('instance_channel=12','instance_channel=11'),
                        ('instance_identity=4096','instance_identity=0'),
                        ('TEST: instance.stable PASS','TEST: instance.stable SKIP')]:
            self.transcript=original.replace(old,new)
            with self.subTest(new=new),self.assertRaises(LAB.RUNNER.EvidenceError):self.verify()

    def test_terminal_before_summary_or_duplicated_actual_state_cannot_pass(self):
        original=self.transcript
        self.transcript=original.replace('TEST_DONE: exit=0\n','').replace('TEST_SUMMARY:','TEST_DONE: exit=0\nTEST_SUMMARY:')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'sequence'):self.verify()
        self.transcript=original.replace('instance_unit=1','instance_unit=1 instance_unit=1')
        with self.assertRaisesRegex(LAB.RUNNER.EvidenceError,'duplicate state'):self.verify()

    def test_native_spi_requires_the_fourth_actual_loopback_case(self):
        self.profile=copy.deepcopy(next(x for x in LAB.ARTIFACT.INVENTORY.load()['profiles']
                                       if x['profile']=='spi2-board-rtt'))
        for target in (self.admission,self.receipt):
            target.update(profile=self.profile['profile'],instance_id=self.profile['instance_id'],
                          instance=copy.deepcopy(self.profile['instance']))
        self.admission['hwtest_contract']=self.profile['hwtest_contract']
        self.transcript='RUN_BEGIN: instance-test\nTEST_ENV: mode=driver-instance expects=internal-loopback\n'
        for case in self.profile['hwtest_contract']['required_case_ids']:
            self.transcript+='TEST: '+case+' START\nTEST: '+case+' PASS\n'
        self.transcript+=('TEST_STATE: instance_family=spi instance_unit=0 instance_channel=2 '
            'instance_output=none instance_identity=4096\nTEST_SUMMARY: passed=4 failed=0 skipped=0\n'
            'TEST_DONE: exit=0\nAPP_EXIT_0=0\nRUN_END: instance-test\nnsh> ')
        self.assertEqual(self.verify()['status'],'PASS')
        original=self.transcript
        for old,new in [('TEST: instance.loopback START\nTEST: instance.loopback PASS\n',''),
                        ('TEST: instance.loopback PASS','TEST: instance.loopback SKIP'),
                        ('passed=4 failed=0 skipped=0','passed=3 failed=0 skipped=0')]:
            self.transcript=original.replace(old,new)
            with self.subTest(new=new),self.assertRaises(LAB.RUNNER.EvidenceError):self.verify()


if __name__ == '__main__':
    unittest.main()
