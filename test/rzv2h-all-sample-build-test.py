#!/usr/bin/env python3
"""Native builder orchestration at its compiler boundary, without a probe."""

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('builder', ROOT/'platforms/nuttx/Debug/rzv2h-sample-build.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class NativeBuildOrchestration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = json.loads(BUILDER.ARTIFACTS.INVENTORY.POLICY.read_text())
        self.manifest['profiles'] = self.manifest['profiles'][:3]
        self.policy = self.root/'policy.json'
        self.policy.write_text(json.dumps(self.manifest))
        self.args = argparse.Namespace(profile=None, list=False, output=self.root/'out',
                                      resume=False, cache_dir=None, timeout=10)

    def test_failure_is_retained_and_remaining_profiles_are_attempted(self):
        attempted = []
        def snapshot(destination):
            destination.mkdir(parents=True)
            (destination/'input.c').write_text('original')
        def compile_boundary(work, output, row, *args):
            self.assertEqual((work/'input.c').read_text(), 'original')
            (work/'input.c').write_text('changed during build')
            attempted.append(row['profile'])
            return {'profile':row['profile'], 'status':'BUILD-FAILED' if len(attempted)==2 else 'BUILD-CHECKED'}
        with patch.object(BUILDER.ARTIFACTS.INVENTORY, 'validate'), \
             patch.object(BUILDER, 'snapshot', side_effect=snapshot), \
             patch.object(BUILDER, 'source_state', return_value={'commits':{},'compiler':'test'}), \
             patch.object(BUILDER, 'archive_profile', side_effect=compile_boundary):
            self.assertEqual(BUILDER.build_native(self.args, self.policy, self.manifest), 1)
        self.assertEqual(attempted, [x['profile'] for x in self.manifest['profiles']])
        results = json.loads((self.args.output/'build-results.json').read_text())
        self.assertEqual([x['status'] for x in results], ['BUILD-CHECKED','BUILD-FAILED','BUILD-CHECKED'])
        self.assertTrue((self.args.output/'junit.xml').is_file())
        self.assertTrue(all(x['on_target']=='NOT-RUN' and not x['artifact_authorized'] for x in results))

    def test_unknown_duplicate_and_dirty_output_are_rejected(self):
        for names in (['unknown'], ['adc','adc']):
            self.args.profile=names
            with patch.object(BUILDER.ARTIFACTS.INVENTORY, 'validate'), self.assertRaises(ValueError):
                BUILDER.build_native(self.args, self.policy, self.manifest)
        self.args.profile=None
        self.args.output.mkdir()
        (self.args.output/'unrelated').touch()
        with patch.object(BUILDER.ARTIFACTS.INVENTORY, 'validate'), self.assertRaisesRegex(ValueError,'new or empty'):
            BUILDER.build_native(self.args, self.policy, self.manifest)

    def test_resume_requires_previous_source_state(self):
        self.args.resume=True
        with patch.object(BUILDER.ARTIFACTS.INVENTORY, 'validate'), self.assertRaisesRegex(ValueError,'previous source-state'):
            BUILDER.build_native(self.args, self.policy, self.manifest)

    def test_px4_cache_api_remains_callable_without_manifest_io(self):
        self.assertEqual(BUILDER.configure_cache(self.root/'does-not-exist', None), [])

    def test_resume_rejects_manifest_and_tool_drift_before_compiling(self):
        self.args.resume=True
        self.args.output.mkdir()
        original={'commits':{},'compiler':'test','source_files':[],
                  'manifest_sha256':'a'*64,'snapshot_overrides':[],
                  'tool_sha256':{'builder':'b'*64}}
        for key,value in (('manifest_sha256','c'*64),('tool_sha256',{'builder':'d'*64})):
            (self.args.output/'source-state.json').write_text(json.dumps(original))
            changed=copy.deepcopy(original);changed[key]=value
            with self.subTest(key=key),patch.object(BUILDER.ARTIFACTS.INVENTORY,'validate'), \
                 patch.object(BUILDER,'snapshot',side_effect=lambda destination:destination.mkdir(parents=True)), \
                 patch.object(BUILDER,'source_state',return_value=changed), \
                 patch.object(BUILDER,'archive_profile') as compiler, \
                 self.assertRaisesRegex(ValueError,'resume source/input drift: '+key):
                BUILDER.build_native(self.args,self.policy,self.manifest)
            compiler.assert_not_called()

    def test_snapshot_build_script_reaches_the_shared_lock_helper(self):
        # build.sh resolves the lock helper three directories above itself;
        # the snapshot must keep that path valid and point at this repository.
        work=BUILDER.snapshot_root(self.root)
        self.assertEqual(work, self.root/'platforms/nuttx/NuttX')
        work.mkdir(parents=True)
        helper=work/'../../../Tools/firmware_workspace/build_lock.sh'
        self.assertTrue(os.access(helper, os.X_OK))
        self.assertEqual(helper.resolve(), (ROOT/'Tools/firmware_workspace/build_lock.sh').resolve())
        self.assertIn('../../../Tools/firmware_workspace/build_lock.sh',
                      (ROOT/'platforms/nuttx/NuttX/build.sh').read_text())

    def test_compile_timeout_reaps_the_owned_process(self):
        work=self.root/'work';work.mkdir()
        output=self.root/'output';output.mkdir()
        pidfile=self.root/'owned.pid'
        (work/'build.sh').write_text('#!/bin/sh\nprintf "%s\\n" "$$" > '+shlex.quote(str(pidfile))+'\nexec sleep 60\n')
        with self.assertRaises(subprocess.TimeoutExpired):
            BUILDER.archive_profile(work,output,{'profile':'timeout-fixture'},{},'unit',timeout=0.2)
        pid=int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)


if __name__ == '__main__':
    unittest.main()
