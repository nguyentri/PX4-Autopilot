#!/usr/bin/env python3
"""Exercise root build selection, real Git isolation and owned process cleanup."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import kconfiglib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('px4_build',ROOT/'Tools/rzv2h-px4-build.py')
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
CHECK = BUILD.CHECK


class ProfileContracts(unittest.TestCase):
    def test_policy_matches_sources_and_root_listing(self):
        contract = CHECK.policy(ROOT)
        names = subprocess.check_output(['bash','build.sh','--list'],cwd=ROOT,text=True).splitlines()
        self.assertEqual({p['target'] for p in contract['profiles']},
                         {n for n in names if n.startswith('renesas_rdk-rzv2h')})

    def test_cr81_capacity_boundary_and_identity(self):
        contract = CHECK.policy(ROOT)
        p = next(p for p in contract['profiles'] if p['core']=='CR8-1')
        cap = CHECK.cr81_capacity((ROOT/contract['cores']['CR8-1']['linker']).read_text(),
                                 (ROOT/'platforms/nuttx/CMakeLists.txt').read_text())
        self.assertEqual(cap,8650368)
        proto = CHECK.load_json(ROOT/p['prototype'])
        self.assertEqual((proto['board_id'],proto['magic'],proto['board_revision']),(14,'PX4FWv2',0))
        self.assertEqual(proto['image_maxsize'],cap)
        self.assertTrue(CHECK.size_allowed(cap,cap))
        self.assertFalse(CHECK.size_allowed(cap+1,cap))

    def test_selection_dependency_set_and_order(self):
        c = CHECK.policy(); dual = next(p for p in c['profiles'] if p['peer'])
        self.assertEqual(CHECK.select_profiles(c,[dual['target'],dual['peer']]),
                         CHECK.select_profiles(c,[dual['peer'],dual['target']]))
        self.assertEqual(len(CHECK.select_profiles(c,[dual['target']])),2)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            CHECK.select_profiles(c,[dual['target']]*2)

    def test_bad_selection_and_temp_path_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'output'; marker = Path(temp)/'sentinel'
            cases = [(['--target','unknown'],os.environ),
                     (['--target','renesas_rdk-rzv2h_default']*2,os.environ),
                     ([],dict(os.environ,TMPDIR="/tmp/quote'; touch "+str(marker)+"; #"))]
            for flags,process_environment in cases:
                result = subprocess.run([sys.executable,str(ROOT/'Tools/rzv2h-px4-build.py'),
                    '--output',str(out),*flags],env=process_environment,capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertFalse(out.exists()); self.assertFalse(marker.exists())

    def test_native_coverage_is_registered(self):
        entries = BUILD.REGRESSION.read_catalog(BUILD.REGRESSION.CATALOG)['scripts']
        self.assertTrue(set(CHECK.policy()['native_coverage'].values()) <=
                        {e['path'] for e in entries if 'port-host' in e['groups']})

    def test_raw_io_transport_is_independent_of_generic_ipcc(self):
        nuttx = ROOT/BUILD.NUTTX
        text = (nuttx/'arch/arm/src/rzv/Kconfig').read_text()
        raw = text.split('config RZV_IPC_RAW\n',1)[1].split('config RZV_IPC_RAW_RING_ENTRIES\n',1)[0]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'Kconfig'
            path.write_text('config EXPERIMENTAL\n bool\n default n\n'
                'config MM_CIRCBUF\n bool\n'+
                'source "'+str(nuttx/'drivers/ipcc/Kconfig')+'"\n'+
                'config RZV_IPC_RAW\n'+raw)
            model = kconfiglib.Kconfig(str(path),warn_to_stderr=False)
            for name in ('IPCC','IPCC_BUFFERED','RZV_IPC_RAW'):model.syms[name].set_value('y')
            self.assertEqual(model.syms['IPCC'].str_value,'n')
            self.assertEqual(model.syms['IPCC_BUFFERED'].str_value,'n')
            self.assertEqual(model.syms['RZV_IPC_RAW'].str_value,'y')
        profile = next(p for p in CHECK.policy()['profiles'] if p['core']=='CR8-1')
        self.assertNotIn('CONFIG_IPCC',profile['required_config'])
        self.assertNotIn('CONFIG_IPCC_BUFFERED',profile['required_config'])
        for name in ('CONFIG_RZV_IPC_RAW','CONFIG_RZV_IPC_CR8_CR8','CONFIG_RZV_IPC_CR8_1_CM33'):
            self.assertEqual(profile['required_config'][name],'y')
        self.assertIn('rzv_ipc_raw_chardev_register',profile['required_symbols'])

    def test_archive_wrapper_output_cannot_modify_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); archive = root/'archive'; archive.mkdir()
            (archive/'sentinel').write_text('sealed')
            (root/'alias').symlink_to(archive,target_is_directory=True)
            before = CHECK.inventory(archive)
            for out in (archive/'reports',root/'alias/reports'):
                r = subprocess.run([sys.executable,str(ROOT/'Tools/rzv2h-regression.py'),'run',
                    '--group','px4-archive-artifacts','--px4-archive',str(archive),'--output',str(out)],
                    capture_output=True,text=True)
                self.assertEqual(r.returncode,2,r.stderr)
                self.assertEqual(CHECK.inventory(archive),before)


class RootScript(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rzv2h-root-script-')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        shutil.copy2(ROOT/'build.sh',self.root/'build.sh')
        for board,label in [('rdk-rzv2h','default'),('rdk-rzv2h','dshot'),('other','dshot')]:
            d = self.root/'boards/renesas'/board; d.mkdir(parents=True,exist_ok=True)
            (d/(label+'.px4board')).touch()
        (self.root/'bin').mkdir(); make = self.root/'bin/make'
        make.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
            'with open(os.environ["CALLS"],"a") as f:\n'
            ' f.write(json.dumps([sys.argv[1:],os.getenv("CC"),os.getenv("GIT_SUBMODULES_ARE_EVIL")])+"\\n")\n'
            'raise SystemExit(int(os.getenv("MAKE_EXIT","0")))\n')
        make.chmod(0o755)
        self.process_environment = dict(os.environ,PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'],
                                        CALLS=str(self.root/'calls'),CC='bad-compiler')

    def invoke(self,*args):
        return subprocess.run(['bash','build.sh',*args],cwd=self.root,env=self.process_environment,
                              capture_output=True,text=True)

    def calls(self):
        p = self.root/'calls'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_listing_and_invalid_batch_never_invoke_make(self):
        self.assertEqual(self.invoke('--list').returncode,0)
        for bad in ('dshot','unknown'):
            self.assertEqual(self.invoke('rdk-rzv2h',bad).returncode,2)
        self.assertEqual(self.calls(),[])

    def test_shortcuts_cleaning_and_environment(self):
        for name in ('renesas_rdk-rzv2h_default','rdk-rzv2h','rdk-rzv2h_default'):
            self.assertEqual(self.invoke(name).returncode,0)
            self.assertEqual(self.calls()[-2][0],['-C','platforms/nuttx/NuttX/nuttx','distclean'])
            self.assertEqual(self.calls()[-1],[['renesas_rdk-rzv2h_default'],None,'1'])

    def test_no_clean_and_nonzero_propagation(self):
        self.process_environment['MAKE_EXIT']='7'
        self.assertEqual(self.invoke('--no-clean','rdk-rzv2h').returncode,7)
        self.assertEqual(len(self.calls()),1)


class GitIsolation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rzv2h-px4-git-',dir='/tmp')
        self.addCleanup(self.temp.cleanup); self.base = Path(self.temp.name)
        self.source = self.base/'original'; self.source.mkdir()
        for args in [('init','-q'),('config','user.name','Fixture'),
                     ('config','user.email','fixture@example.invalid'),
                     ('remote','add','origin','https://example.invalid/fixture.git')]:
            BUILD.git(self.source,*args)
        for name in ('source.c','deleted.c'): (self.source/name).write_text('original\n')
        BUILD.git(self.source,'add','.'); BUILD.git(self.source,'commit','-qm','fixture')
        BUILD.git(self.source,'tag','v1.0.0')

    def test_dirty_deleted_untracked_links_and_independent_objects(self):
        (self.source/'source.c').write_text('working edit\n'); (self.source/'deleted.c').unlink()
        (self.source/'src').mkdir()
        (self.source/'src/extra.c').write_text('extra\n')
        (self.source/'src/link.c').symlink_to('../source.c')
        original = BUILD.source_inputs(self.source,[Path('.')]); target = self.base/'copy'
        BUILD.snapshot(self.source,target,[Path('.')],original)
        self.assertEqual(BUILD.source_inputs(target,[Path('.')]),original)
        self.assertFalse((target/'deleted.c').exists())
        for obj in (target/'.git/objects').rglob('*'):
            source = self.source/'.git/objects'/obj.relative_to(target/'.git/objects')
            if obj.is_file() and source.exists(): self.assertNotEqual(source.stat().st_ino,obj.stat().st_ino)

    def test_detects_content_mode_addition_and_deletion(self):
        before = BUILD.source_inputs(self.source,[Path('.')]); path = self.source/'source.c'
        (self.source/'src').mkdir()
        for change in ('content','mode','addition','deletion'):
            if change=='content': path.write_text('changed\n')
            elif change=='mode': path.chmod(0o755)
            elif change=='addition': (self.source/'src/new.c').touch()
            else: path.unlink()
            with self.assertRaisesRegex(ValueError,'inputs changed'):
                BUILD.assert_inputs(self.source,[Path('.')],before)
            path.write_text('original\n'); path.chmod(0o644); (self.source/'src/new.c').unlink(missing_ok=True)

    def test_untracked_private_and_unrelated_files_are_not_inputs(self):
        omitted = ('credentials.txt', 'notes.txt', 'secrets.json', 'id_rsa',
                   'src/notes.txt', 'docs/local.json', 'Tools/secrets.json',
                   'src/credentials.yaml', 'platforms/private.conf')
        for name in omitted:
            path = self.source/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('fixture private data\n')
        (self.source/'src/new-driver.c').write_text('int driver;\n')
        # Tracked text remains part of the overlay regardless of untracked policy.
        (self.source/'tracked.txt').write_text('tracked\n')
        BUILD.git(self.source,'add','tracked.txt');BUILD.git(self.source,'commit','-qm','tracked input')
        original = BUILD.source_inputs(self.source,[Path('.')])
        self.assertTrue(set(omitted).isdisjoint(original['files']))
        self.assertIn('src/new-driver.c',original['files']);self.assertIn('tracked.txt',original['files'])
        target = self.base/'private-copy';BUILD.snapshot(self.source,target,[Path('.')],original)
        self.assertTrue(all(not (target/name).exists() for name in omitted))
        self.assertEqual((target/'src/new-driver.c').read_text(),'int driver;\n')
        (self.source/'src/new-driver.c').write_text('int changed;\n')
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            BUILD.assert_inputs(self.source,[Path('.')],original)
        for repo in BUILD.UNTRACKED_ROOTS:
            self.assertFalse(BUILD.untracked_source('drivers/credentials.json',Path(repo)))
        self.assertFalse(BUILD.untracked_source('src/driver.c',Path('unknown-repository')))
        self.assertTrue(BUILD.untracked_source('generator.c',Path('src/modules/mavlink/mavlink/pymavlink')))

    def test_generated_paths_and_escaping_links(self):
        for repo,names in BUILD.GENERATED.items():
            for name in names: self.assertFalse(BUILD.eligible(name,Path(repo)))
        (self.source/'src').mkdir()
        (self.source/'src/escape.c').symlink_to('../../outside')
        self.assertIn('omitted_link',BUILD.source_inputs(self.source,[Path('.')])['files']['src/escape.c'])

    def test_nested_repositories_and_staged_working_inputs(self):
        contract = {'required_submodules':['child','child/nested'],'repositories':{}}
        for relative in ('child','child/nested'):
            child = self.source/relative; child.mkdir(parents=True,exist_ok=True)
            for args in [('init','-q'),('config','user.name','Fixture'),
                         ('config','user.email','fixture@example.invalid'),
                         ('remote','add','origin','https://example.invalid/'+relative+'.git')]:
                BUILD.git(child,*args)
            (child/'file.c').write_text('original\n')
            BUILD.git(child,'add','.'); BUILD.git(child,'commit','-qm','child')
            parent = child.parent
            for key,value in [('path',child.name),('url','https://example.invalid/'+relative+'.git')]:
                BUILD.git(parent,'config','-f','.gitmodules','submodule.'+child.name+'.'+key,value)
            BUILD.git(parent,'add','.gitmodules',child.name)
            contract['repositories'][relative]={'origin':'https://example.invalid/'+relative+'.git','branch':None}
        (self.source/'source.c').write_text('staged\n'); BUILD.git(self.source,'add','source.c')
        (self.source/'source.c').write_text('working after staging\n')
        (self.source/'child/nested/file.c').write_text('nested dirty\n')
        repos = BUILD.repositories(self.source,contract)
        before = BUILD.source_inputs(self.source,repos); target = self.base/'nested-copy'
        BUILD.snapshot(self.source,target,repos,before)
        self.assertEqual(BUILD.source_inputs(target,repos),before)
        BUILD.git(self.source/'child','remote','set-url','origin','https://wrong.invalid/fork.git')
        with self.assertRaisesRegex(ValueError,'origin mismatch'): BUILD.repositories(self.source,contract)

    def test_tag_object_change_is_detected(self):
        BUILD.git(self.source,'commit','--allow-empty','-qm','second')
        before = BUILD.source_inputs(self.source,[Path('.')])
        BUILD.git(self.source,'tag','-f','v1.0.0','HEAD')
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            BUILD.assert_inputs(self.source,[Path('.')],before)

    def test_host_failure_leaves_all_firmware_targets_not_run(self):
        tools = self.source/'Tools';tools.mkdir()
        (tools/'rzv2h-regression.py').write_text('print("host fixture failed")\nraise SystemExit(7)\n')
        BUILD.git(self.source,'add','Tools');BUILD.git(self.source,'commit','-qm','host fixture')
        contract = CHECK.policy();contract['profiles']=contract['profiles'][:1]
        output = self.base/'job'
        args = SimpleNamespace(target=[],list=False,output=output,cache_dir=None,timeout=10,host_timeout=10)
        with patch.object(BUILD,'ROOT',self.source),patch.object(BUILD.REGRESSION,'ROOT',ROOT), \
                patch.object(CHECK,'policy',return_value=contract), \
                patch.object(BUILD,'repositories',return_value=[Path('.')]):
            self.assertEqual(BUILD.run(args),1)
        rows = json.loads((output/'build-results.json').read_text())
        self.assertEqual(rows['status'],'FAIL')
        self.assertEqual([r['status'] for r in rows['results']],['NOT-RUN'])
        self.assertFalse((output/'archive/builds').exists())

    def test_build_focused_archive_and_timeout_failures_keep_diagnostics(self):
        contract = CHECK.policy()
        (self.source/'test').mkdir()
        (self.source/'test/failure.py').write_text('print("focused failure")\nraise SystemExit(7)\n')
        for phase in ('build','focused','archive','timeout'):
            with self.subTest(phase=phase):
                script = 'echo boundary-'+phase+'\n'
                script += 'sleep 60\n' if phase=='timeout' else 'exit '+('7' if phase=='build' else '0')+'\n'
                (self.source/'build.sh').write_text(script)
                BUILD.git(self.source,'add','build.sh','test')
                BUILD.git(self.source,'commit','-qm','failure boundary '+phase)
                profile = dict(contract['profiles'][0],
                               focused_tests=['test/failure.py'] if phase=='focused' else [])
                directory = self.base/phase
                frozen = BUILD.source_inputs(self.source,[Path('.')])
                expected = (subprocess.TimeoutExpired if phase=='timeout' else
                            FileNotFoundError if phase=='archive' else ValueError)
                with patch.object(BUILD.REGRESSION,'ROOT',self.source),self.assertRaises(expected):
                    BUILD.archive_profile(self.source,directory,profile,contract,'unused',
                                          .2 if phase=='timeout' else 10,[Path('.')],frozen)
                self.assertIn('boundary-'+phase,(directory/'build.log').read_text())
                self.assertFalse((directory/'build-receipt.json').exists())
                if phase=='focused':
                    rows = json.loads((directory/'focused-results.json').read_text())
                    self.assertEqual(rows[0]['status'],'FAIL')


class Lifecycle(unittest.TestCase):
    def test_cleanup_failure_preserves_only_owned_workspace(self):
        owned = None
        try:
            with self.assertRaises(TimeoutError):
                with BUILD.disposable_workspace() as owned:
                    (owned/'sentinel').write_text('owned')
                    raise TimeoutError('simulated process cleanup failure')
            self.assertTrue((owned/'sentinel').is_file())
        finally:
            if owned is not None:shutil.rmtree(owned)

    def test_exited_leader_child_is_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'pid'
            child = ('import signal,time,os; from pathlib import Path; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                f'Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)')
            parent = ('import subprocess,sys,time; from pathlib import Path; '
                f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                f'\nwhile not Path({str(marker)!r}).exists(): time.sleep(.01)\n')
            BUILD.stage([sys.executable,'-c',parent],root,root/'log',10)
            status = Path('/proc')/marker.read_text()/'stat'
            self.assertTrue(not status.exists() or status.read_text().rsplit(')',1)[1].split()[0]=='Z')

    def test_nested_runner_has_time_to_reap_stubborn_test_child(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'pid'; script = root/'fixture.py'
            child = ('import os,signal,time; from pathlib import Path; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                f'Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)')
            script.write_text('import subprocess,sys,time\n'+
                f'subprocess.Popen([sys.executable,"-c",{child!r}])\ntime.sleep(60)\n')
            catalog = {'schema_version':1,'scripts':[{'id':name,'path':'fixture.py','kind':'test',
                'groups':['fixture'],'target_access':'none','command':['{python}',str(script)]}
                for name in ('active','pending')]}
            (root/'catalog.json').write_text(json.dumps(catalog))
            bootstrap = ('import importlib.util,sys; from pathlib import Path; '
                f's=importlib.util.spec_from_file_location("r",{str(ROOT/"Tools/rzv2h-regression.py")!r}); '
                'r=importlib.util.module_from_spec(s);s.loader.exec_module(r); '
                f'r.ROOT=Path({str(root)!r});r.CATALOG=r.ROOT/"catalog.json";'
                f'sys.argv=["r","run","--group","fixture","--output",{str(root/"results")!r}];'
                'raise SystemExit(r.main())')
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                BUILD.stage([sys.executable,'-c',bootstrap],root,root/'log',1,nested=True)
            self.assertLess(time.monotonic()-started,16)
            rows = json.loads((root/'results/results.json').read_text())
            self.assertEqual([r['status'] for r in rows],['FAIL','NOT-RUN'])
            status = Path('/proc')/marker.read_text()/'stat'
            self.assertTrue(not status.exists() or status.read_text().rsplit(')',1)[1].split()[0]=='Z')


if __name__=='__main__':
    unittest.main()
