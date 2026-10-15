#!/usr/bin/env python3
"""Check CI selection, failure reporting, cancellation and build boundaries."""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load('regression', 'Tools/rzv2h-regression.py')
BUILDER = load('sample_build', 'platforms/nuttx/Debug/rzv2h-sample-build.py')


def live_process(pid):
    status = Path('/proc')/str(pid)/'stat'
    try:
        return status.read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


def stubborn_fixture(directory, exit_parent=False):
    marker = directory/'stubborn.pid'
    child = directory/'stubborn.py'
    child.write_text('import os, signal, time\nfrom pathlib import Path\n'
                     'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                     f'Path({str(marker)!r}).write_text(str(os.getpid()))\n'
                     'time.sleep(60)\n')
    parent = directory/'parent.py'
    parent.write_text('import subprocess, sys, time\nfrom pathlib import Path\n'
                      f'subprocess.Popen([sys.executable, {str(child)!r}])\n'
                      f'while not Path({str(marker)!r}).exists(): time.sleep(0.01)\n' +
                      ('' if exit_parent else 'time.sleep(60)\n'))
    return parent, marker


def kill_fixture_child(marker):
    if marker.is_file():
        pid = int(marker.read_text())
        if live_process(pid):
            os.kill(pid, signal.SIGKILL)


class HostRunner(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rzv2h-ci-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def run_fixture(self, content, timeout=5):
        path = self.directory/'fixture.py'
        path.write_text(content)
        return RUNNER.execute({'id': 'fixture', 'path': str(path)},
                              [sys.executable, str(path)], self.directory/'test.log', timeout)

    def test_success_failure_and_skips_are_distinct(self):
        template = ('import unittest\nclass Check(unittest.TestCase):\n'
                    ' def test_case(self):\n  {body}\n'
                    'unittest.main()\n')
        for body, expected in [('self.assertTrue(True)', 'PASS'),
                               ('self.assertTrue(False)', 'FAIL'),
                               ('self.skipTest("missing input")', 'FAIL')]:
            with self.subTest(body=body):
                result = self.run_fixture(template.format(body=body))
                self.assertEqual(result['status'], expected)

    def test_zero_tests_and_silent_success_cannot_pass(self):
        for source in ('import unittest\nunittest.main()\n', 'pass\n'):
            self.assertEqual(self.run_fixture(source)['status'], 'FAIL')

    def test_timeout_stops_owned_process_group(self):
        marker = self.directory/'child.pid'
        source = ('import subprocess, time\nfrom pathlib import Path\n'
                  'child = subprocess.Popen(["sleep", "60"])\n'
                  f'Path({str(marker)!r}).write_text(str(child.pid))\n'
                  'time.sleep(60)\n')
        result = self.run_fixture(source, timeout=0.5)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['timed_out'])
        self.assertTrue(marker.is_file())
        status = Path('/proc')/marker.read_text()/'stat'
        self.assertTrue(not status.exists() or status.read_text().split()[2] == 'Z')

    def test_timeout_kills_stubborn_child_after_parent_exits(self):
        parent, marker = stubborn_fixture(self.directory)
        try:
            result = self.run_fixture(parent.read_text(), timeout=1)
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['status'], 'FAIL')
            self.assertFalse(live_process(int(marker.read_text())),
                             'timeout left a SIGTERM-ignoring child alive')
        finally:
            kill_fixture_child(marker)

    def test_cleanup_handles_an_already_exited_parent(self):
        parent, marker = stubborn_fixture(self.directory, exit_parent=True)
        process = subprocess.Popen([sys.executable, str(parent)], start_new_session=True)
        try:
            process.wait(timeout=5)
            RUNNER.stop_process(process)
            self.assertFalse(live_process(int(marker.read_text())),
                             'cleanup skipped the exited parent\'s process group')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            kill_fixture_child(marker)

    def test_sigterm_preserves_active_and_pending_results(self):
        marker = self.directory/'child.pid'
        fixture = self.directory/'fixture.py'
        fixture.write_text('import subprocess, time\nfrom pathlib import Path\n'
                           'child = subprocess.Popen(["sleep", "60"])\n'
                           f'Path({str(marker)!r}).write_text(str(child.pid))\n'
                           'time.sleep(60)\n')
        catalog = self.directory/'catalog.json'
        catalog.write_text(json.dumps({'schema_version': 1, 'scripts': [
            {'id': name, 'path': 'fixture.py', 'kind': 'test', 'groups': ['fixture'],
             'target_access': 'none', 'command': ['{python}', str(fixture)]}
            for name in ('active', 'pending')]}))
        output = self.directory/'reports'
        bootstrap = (f'import runpy, sys\n'
                     f'namespace = runpy.run_path({str(ROOT/"Tools/rzv2h-regression.py")!r})\n'
                     'main = namespace["main"]\n'
                     f'main.__globals__["ROOT"] = __import__("pathlib").Path({str(self.directory)!r})\n'
                     f'main.__globals__["CATALOG"] = __import__("pathlib").Path({str(catalog)!r})\n'
                     f'sys.argv = ["runner", "run", "--group", "fixture", "--output", {str(output)!r}]\n'
                     'raise SystemExit(main())\n')
        process = subprocess.Popen([sys.executable, '-c', bootstrap],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic()+5
            while not marker.is_file() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.is_file(), 'fixture did not start')
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 130)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
        rows = json.loads((output/'results.json').read_text())
        self.assertEqual([row['status'] for row in rows], ['FAIL', 'NOT-RUN'])
        self.assertTrue(rows[0]['cancelled'])
        junit = ET.parse(output/'junit.xml').getroot()
        self.assertEqual(junit.attrib['tests'], '2')
        self.assertEqual(junit.attrib['failures'], '1')
        self.assertEqual(junit.attrib['skipped'], '1')
        status = Path('/proc')/marker.read_text()/'stat'
        self.assertTrue(not status.exists() or status.read_text().split()[2] == 'Z')

    def test_hardware_and_unknown_selection_are_refused(self):
        catalog = RUNNER.read_catalog(RUNNER.CATALOG)
        with self.assertRaisesRegex(ValueError, 'unknown'):
            RUNNER.select(catalog, ['does-not-exist'], [])
        with self.assertRaisesRegex(ValueError, 'empty'):
            RUNNER.select({'scripts': []}, [], [])
        hardware = next(entry for entry in catalog['scripts'] if entry['target_access'] == 'mutates')
        with self.assertRaisesRegex(ValueError, 'refuses'):
            RUNNER.invocation(hardware, {})

    def test_missing_artifact_option_and_host_tool_fail(self):
        entry = {'id': 'example', 'kind': 'test', 'target_access': 'none',
                 'command': ['{python}', '{sample_builds}']}
        with self.assertRaisesRegex(ValueError, 'missing artifact'):
            RUNNER.invocation(entry, {})
        entry['command'] = ['{python}']
        entry['requires'] = {'tools': ['rzv2h-intentionally-absent-compiler']}
        with self.assertRaisesRegex(ValueError, 'tool missing'):
            RUNNER.invocation(entry, {})

    def test_junit_and_json_preserve_failure(self):
        result = self.run_fixture('raise SystemExit(7)\n')
        RUNNER.write_reports(self.directory, [result])
        self.assertEqual(json.loads((self.directory/'results.json').read_text())[0]['exit'], 7)
        junit = ET.parse(self.directory/'junit.xml').getroot()
        self.assertEqual(junit.attrib['failures'], '1')
        self.assertIsNotNone(junit.find('testcase/failure'))

    def test_every_test_and_ipc_fragment_is_cataloged(self):
        catalog = RUNNER.read_catalog(RUNNER.CATALOG)
        paths = {entry['path'] for entry in catalog['scripts']}
        expected = {str(path.relative_to(ROOT)) for path in (ROOT/'test').iterdir()
                    if 'rzv2h' in path.name and path.suffix in ('.py', '.sh', '.c', '.cpp', '.h')}
        expected.update(str(path.relative_to(ROOT)) for path in
                        (ROOT/'platforms/nuttx/Debug/rzv2h-ipc').iterdir()
                        if path.suffix in ('.sh', '.gdb', '.jlink'))
        self.assertFalse(expected-paths, sorted(expected-paths))


class BuilderBoundaries(unittest.TestCase):
    def test_snapshot_drops_generated_links_and_preserves_source(self):
        for absolute in (False, True):
            with self.subTest(absolute=absolute), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root/'source'
                nuttx = source/BUILDER.NUTTX/'nuttx'
                apps = source/BUILDER.NUTTX/'apps'
                (nuttx/'arch/arm/include/rzv').mkdir(parents=True)
                (nuttx/'arch/arm/src/rzv').mkdir(parents=True)
                (nuttx/'include').mkdir()
                (nuttx/'drivers/dummy').mkdir(parents=True)
                (nuttx/'boards/rdk/include').mkdir(parents=True)
                (nuttx/'boards/rdk/src').mkdir()
                (apps/'platform/dummy').mkdir(parents=True)
                (apps/'sample.c').write_text('uncommitted sample source\n')
                (apps/'sample-link.c').symlink_to('sample.c')
                (source/BUILDER.NUTTX/'build.sh').write_text('#!/bin/bash\n')
                links = {
                    nuttx/'include/arch': nuttx/'arch/arm/include',
                    nuttx/'arch/arm/include/chip': nuttx/'arch/arm/include/rzv',
                    nuttx/'arch/arm/include/board': nuttx/'boards/rdk/include',
                    nuttx/'arch/arm/src/chip': nuttx/'arch/arm/src/rzv',
                    nuttx/'arch/arm/src/board': nuttx/'boards/rdk/src',
                    nuttx/'drivers/platform': nuttx/'drivers/dummy',
                    apps/'platform/board': apps/'platform/dummy',
                }
                for link, target in links.items():
                    link.symlink_to(target if absolute else os.path.relpath(target, link.parent))
                original_links = {link: link.readlink() for link in links}
                for tree in (nuttx, apps):
                    (tree/'.dirlinks').touch()
                    (tree/'.context').touch()
                (nuttx/'.config').write_text('stale configuration\n')
                (nuttx/'Make.defs').write_text('stale configuration include\n')
                outside = root/'outside'
                outside.mkdir()
                (outside/'sentinel').write_text('preserved\n')
                (apps/'outside-absolute').symlink_to(outside)
                (apps/'outside-relative').symlink_to(os.path.relpath(outside, apps))
                destination = root/'snapshot'
                with patch.object(BUILDER, 'ROOT', source):
                    BUILDER.snapshot(destination)
                for link in links:
                    staged = destination/link.relative_to(source/BUILDER.NUTTX)
                    self.assertFalse(staged.is_symlink(), str(staged))
                for tree in ('nuttx', 'apps'):
                    self.assertFalse((destination/tree/'.dirlinks').exists())
                    self.assertFalse((destination/tree/'.context').exists())
                self.assertFalse((destination/'nuttx/.config').exists())
                self.assertFalse((destination/'nuttx/Make.defs').exists())
                self.assertEqual((destination/'apps/sample-link.c').read_text(),
                                 'uncommitted sample source\n')
                for link in ('outside-absolute', 'outside-relative'):
                    self.assertFalse((destination/'apps'/link).is_symlink())
                # Recreate this build's links and run the real unlink helper.
                staged_arch = destination/'nuttx/arch/arm/include'
                (destination/'nuttx/include/arch').symlink_to(staged_arch)
                for name in ('chip', 'board'):
                    (staged_arch/name).symlink_to(staged_arch/'rzv')
                    subprocess.run(['bash', str(ROOT/'platforms/nuttx/NuttX/nuttx/tools/unlink.sh'),
                                    str(destination/'nuttx/include/arch'/name)], check=True)
                self.assertEqual({link: link.readlink() for link in links}, original_links)
                self.assertEqual((outside/'sentinel').read_text(), 'preserved\n')

    def test_cancellation_kills_stubborn_child_after_build_parent_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root/'work'
            work.mkdir()
            output = root/'output'
            parent, marker = stubborn_fixture(root)
            (work/'build.sh').write_text('#!/bin/bash\nexec ' +
                                        shlex.quote(sys.executable)+' '+shlex.quote(str(parent))+'\n')
            bootstrap = (
                'import importlib.util, signal\nfrom pathlib import Path\n'
                f'spec = importlib.util.spec_from_file_location("builder", {str(BUILDER.__file__)!r})\n'
                'builder = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(builder)\n'
                'def interrupted(signum, frame): raise KeyboardInterrupt\n'
                'signal.signal(signal.SIGTERM, interrupted)\n'
                'try:\n'
                f' builder.archive_profile(Path({str(work)!r}), Path({str(output)!r}), '
                '{"profile": "fixture"}, {}, "unused")\n'
                'except KeyboardInterrupt: raise SystemExit(130)\n')
            process = subprocess.Popen([sys.executable, '-c', bootstrap],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       start_new_session=True)
            try:
                deadline = time.monotonic()+5
                while not marker.is_file() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.is_file(), 'build fixture did not start')
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=12)
                self.assertEqual(process.returncode, 130, stdout+stderr)
                self.assertFalse(live_process(int(marker.read_text())),
                                 'builder cancellation left a stubborn child alive')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                kill_fixture_child(marker)

    def test_existing_archive_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'receipt').write_text('retained')
            with self.assertRaisesRegex(ValueError, 'new or empty'):
                BUILDER.new_output(path)
            self.assertEqual((path/'receipt').read_text(), 'retained')

    def test_unknown_profile_fails_before_build(self):
        result = subprocess.run([sys.executable, str(ROOT/'platforms/nuttx/Debug/rzv2h-sample-build.py'),
                                 '--profile', 'unknown-profile', '--output', '/tmp/unused-rzv2h-output'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unknown or duplicate', result.stderr)

    def test_missing_artifacts_do_not_turn_into_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            builds = path/'builds'
            builds.mkdir()
            state = path/'source-state.json'
            state.write_text('{}')
            result = subprocess.run([sys.executable, str(ROOT/'test/rzv2h-sample-artifact-test.py'),
                                     '--builds', str(builds), '--source-state', str(state)],
                                    text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing required build receipt', result.stderr)
            self.assertNotIn('skipped=', result.stderr)


if __name__ == '__main__':
    unittest.main()
