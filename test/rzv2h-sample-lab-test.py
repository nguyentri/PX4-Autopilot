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


if __name__ == '__main__':
    unittest.main()
