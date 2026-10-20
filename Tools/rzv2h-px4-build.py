#!/usr/bin/env python3
"""Build RZ/V2H PX4 from independent working-source copies, without hardware."""
import argparse
from contextlib import contextmanager
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NUTTX = Path('platforms/nuttx/NuttX/nuttx')
APPS = Path('platforms/nuttx/NuttX/apps')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


CHECK = module('px4_artifacts', ROOT/'Tools/rzv2h-px4-artifact-check.py')
REGRESSION = module('px4_regression', ROOT/'Tools/rzv2h-regression.py')
SAMPLES = module('sample_build', ROOT/'platforms/nuttx/Debug/rzv2h-sample-build.py')
# Configure recreates these exact paths; source directories are never exempted.
GENERATED = {
    str(NUTTX): {'Make.defs', 'defconfig', '.config', '.config.old', '.config.orig',
                 '.config.prev', '.config.tmp', '.dirlinks', '.context', 'include/arch',
                 'drivers/platform', 'arch/arm/include/board', 'arch/arm/include/chip',
                 'arch/arm/src/board', 'arch/arm/src/chip'},
    str(APPS): {'platform/board', '.dirlinks', '.context'},
    '.': {'src/lib/version/build_git_version.h'},
}
HIDDEN_INPUTS = {'.gitignore', '.gitmodules', '.gitattributes', '.clang-format', '.clang-tidy', '.astylerc'}
# Untracked additions must be source/configuration beneath declared build roots.
# A dependency's '.' root is explicit; unknown repositories fail closed.
UNTRACKED_ROOTS = {
    '.': {'boards', 'cmake', 'msg', 'ROMFS', 'src', 'platforms', 'Tools', 'test'},
    str(NUTTX): {'arch', 'audio', 'binfmt', 'boards', 'crypto', 'drivers', 'dummy',
                 'fs', 'graphics', 'include', 'libs', 'mm', 'net', 'openamp',
                 'pass1', 'sched', 'staging', 'syscall', 'tools', 'video', 'wireless'},
    str(APPS): {'audioutils', 'boot', 'builtin', 'canutils', 'crypto', 'examples',
                'fsutils', 'games', 'gpsutils', 'graphics', 'import', 'include',
                'industry', 'interpreters', 'math', 'mlearning', 'modbus',
                'netutils', 'nshlib', 'platform', 'system', 'testing', 'tools', 'wireless'},
    **{name:{'.'} for name in (
        'src/modules/mavlink/mavlink', 'src/modules/mavlink/mavlink/pymavlink',
        'src/lib/events/libevents', 'src/lib/heatshrink/heatshrink',
        'src/modules/uxrce_dds_client/Micro-XRCE-DDS-Client', 'src/drivers/gps/devices',
        'src/drivers/uavcan/libdronecan/dsdl',
        'src/drivers/uavcan/libdronecan/libuavcan/dsdl_compiler/pydronecan')},
}
SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.S',
                   '.s', '.asm', '.ld', '.cmake', '.mk', '.sh', '.py', '.msg',
                   '.srv', '.px4board', '.prototype', '.patch', '.in'}
UNTRACKED_FILES = {'.': {'Tools/rzv2h-px4-profiles.json'}}
REQUIRED_TOOLS = ('git', 'make', 'ninja', 'cmake', 'rsync', 'unzip', 'curl',
                  'arm-none-eabi-gcc', 'arm-none-eabi-objcopy', 'arm-none-eabi-nm',
                  'arm-none-eabi-readelf', 'gdb-multiarch')
RTT_DEPENDENCIES = (
    ('RTT.zip', 'RTT_ARCHIVE_SHA256'),
    ('RTT/RTT/SEGGER_RTT.c', 'RTT_SOURCE_SHA256'),
    ('RTT/RTT/SEGGER_RTT.h', 'RTT_HEADER_SHA256'),
)


def environment():
    env = os.environ.copy()
    for name in list(env):
        if name.startswith('GIT_') or name in ('CI', 'VSCODE_PID', 'CLION_IDE', 'MAKEFLAGS', 'MFLAGS'):
            env.pop(name)
    env.update(GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null',
               GIT_TERMINAL_PROMPT='0', GIT_SUBMODULES_ARE_EVIL='1')
    return env


def command_bytes(argv, cwd=ROOT, data=None):
    process = subprocess.Popen(argv,cwd=cwd,env=environment(),stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,stdin=subprocess.PIPE,start_new_session=True)
    try:
        output,error = process.communicate(input=data,timeout=120)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode,argv,output,error)
        return output
    finally:
        REGRESSION.stop_process(process)


def command(argv,cwd=ROOT):
    return command_bytes(argv,cwd).decode().strip()


def git(repo, *args):
    return command(['git', '-c', 'core.hooksPath=/dev/null', *args], repo)


def atomic_json(path, value):
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def safe_temp_base():
    # px_mkfw uses a shell for Git identity; package input paths must be safe.
    for value in ('/tmp', *(os.environ.get(n, '/tmp') for n in ('TMPDIR', 'TMP', 'TEMP'))):
        CHECK.require(re.fullmatch(r'[A-Za-z0-9_./-]+', value) and
                      re.fullmatch(r'[A-Za-z0-9_./-]+', str(Path(value).resolve())), 'unsafe temporary path')
    return Path('/tmp').resolve()


@contextmanager
def disposable_workspace():
    directory = Path(tempfile.mkdtemp(prefix='rzv2h-px4-build-',dir=safe_temp_base()))
    remove = True
    try:
        yield directory
    except TimeoutError:
        # A failed stop_process means a group may still use these files.
        remove = False
        print('Cleanup failed; preserving owned workspace: '+str(directory),file=sys.stderr)
        raise
    finally:
        if remove:
            shutil.rmtree(directory)


def repositories(root, contract):
    result = [Path('.')]
    CHECK.require((root/'.git').exists(), 'root Git metadata missing')
    def visit(relative):
        if not (root/relative/'.gitmodules').is_file():
            return
        rows = git(root/relative,'config','-f','.gitmodules','--list')
        for row in rows.splitlines():
            key,name = row.split('=',1)
            if not key.endswith('.path'):
                continue
            child = relative/CHECK.safe_relative(name)
            if (root/child/'.git').exists():
                CHECK.require(str(child) in contract['repositories'],'unclassified local repository: '+str(child))
                expected = contract['repositories'][str(child)]
                origin = git(root/child,'remote','get-url','origin')
                declared = git(root/relative,'config','-f','.gitmodules','--get',key[:-4]+'url')
                CHECK.require(origin == declared == expected['origin'],'repository origin mismatch: '+str(child))
                if expected['branch']:
                    branch = git(root/relative,'config','-f','.gitmodules','--get',key[:-4]+'branch')
                    actual = git(root/child,'rev-parse','--abbrev-ref','HEAD')
                    CHECK.require(branch == expected['branch'] and actual in (branch,'HEAD'),
                                  'repository branch mismatch: '+str(child))
                result.append(child)
                visit(child)
    visit(Path('.'))
    for name in contract['required_submodules']:
        CHECK.require(Path(name) in result,'required local submodule: '+name)
    for relative in result:
        git(root/relative, 'rev-parse', '--verify', 'HEAD')
    return result


def eligible(name, repo):
    path = Path(name)
    return not (name in GENERATED.get(str(repo), set()) or
                any(p.startswith('.') and p not in HIDDEN_INPUTS for p in path.parts) or
                any(p in ('plans','refs','build','keys','logs','node_modules','__pycache__') for p in path.parts) or
                path.suffix in ('.o','.a','.d','.pyc','.pem','.key'))


def untracked_source(name, repo):
    path = Path(name)
    roots = UNTRACKED_ROOTS.get(str(repo))
    if not roots or '.' not in roots and path.parts[0] not in roots:
        return False
    return (name in UNTRACKED_FILES.get(str(repo),set()) or path.suffix in SOURCE_SUFFIXES or path.name in
            {'CMakeLists.txt', 'Makefile', 'Make.defs', 'Kconfig', 'defconfig', 'rcS', 'module.yaml'} or
            path.name.startswith(('Kconfig.', 'rc.')))


def repository_files(root, relative):
    repo = root/relative
    output = command_bytes(['git','ls-files','--stage','-z'],repo)
    tracked = set()
    for entry in output.split(b'\0'):
        if entry:
            fields,name = entry.split(b'\t',1)
            mode,oid,stage = fields.decode().split()
            CHECK.require(stage == '0','unmerged source index')
            if mode != '160000':
                tracked.add(name.decode())
    others = command_bytes(['git','ls-files','--others','--exclude-standard','-z'],repo).decode().split('\0')
    additions = {n for n in others if n and untracked_source(n,relative)}
    return sorted(n for n in tracked | additions if eligible(n,relative))


def source_inputs(root, repos):
    records = {}
    for relative in repos:
        repo = root/relative
        for name in repository_files(root,relative):
            path = repo/CHECK.safe_relative(name)
            key = (relative/name).as_posix()
            if path.is_symlink():
                target = os.readlink(path)
                if Path(target).is_absolute() or not path.resolve().is_relative_to(repo.resolve()):
                    records[key] = {'omitted_link':target}
                else:
                    records[key] = {'link':target}
            elif not path.exists():
                records[key] = {'deleted':True}
            else:
                CHECK.require(path.is_file(),'nonregular source input: '+key)
                records[key] = {'sha256':CHECK.digest(path),'mode':stat.S_IMODE(path.stat().st_mode)}
    versions = {str(r):{'head':git(root/r,'rev-parse','HEAD'),
                        'tags':git(root/r,'for-each-ref','--format=%(refname) %(objectname)','refs/tags'),
                        'origin':git(root/r,'remote','get-url','origin'),
                        'branch':git(root/r,'rev-parse','--abbrev-ref','HEAD'),
                        'index':git(root/r,'ls-files','--stage')} for r in repos}
    return {'files':records,'git':versions}


def assert_inputs(root,repos,expected):
    actual = source_inputs(root,repos)
    changes = [
        n for n in sorted(set(actual['files']) | set(expected['files']))
        if actual['files'].get(n) != expected['files'].get(n)]
    changes += ['git:'+str(repo)+':'+key for repo in repos for key in
                set(actual['git'][str(repo)]) | set(expected['git'][str(repo)])
                if actual['git'][str(repo)].get(key) != expected['git'][str(repo)].get(key)]
    CHECK.require(actual == expected,'source inputs changed during job: '+', '.join(changes)[:1000])


def sentinels(root):
    result = {}
    for tree,names in GENERATED.items():
        for name in names:
            path = root/('' if tree == '.' else tree)/name
            result[path.relative_to(root).as_posix()] = (
                {'link':os.readlink(path)} if path.is_symlink() else
                {'sha256':CHECK.digest(path)} if path.is_file() else {'missing':True})
    return result


def snapshot(root,destination,repos,original):
    for relative in repos:
        source,target = root/relative,destination/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        command(['git','clone','--quiet','--local','--no-hardlinks','--no-checkout','--template=',str(source),str(target)])
        version = original['git'][str(relative)]
        if version['branch'] == 'HEAD':
            git(target,'update-ref','--no-deref','HEAD',version['head'])
        else:
            git(target,'update-ref','refs/heads/'+version['branch'],version['head'])
            git(target,'symbolic-ref','HEAD','refs/heads/'+version['branch'])
        git(target,'read-tree','--empty')
        command_bytes(['git','update-index','--index-info'],target,
                      (original['git'][str(relative)]['index']+'\n').encode())
        origin = git(source,'remote','get-url','origin')
        CHECK.require(re.fullmatch(r'https://[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+',origin),'unsupported source origin')
        git(target,'remote','set-url','origin',origin)
        common = Path(git(target,'rev-parse','--path-format=absolute','--git-common-dir'))
        CHECK.require(common.is_relative_to(destination) and not (common/'objects/info/alternates').exists(),
                      'snapshot shares Git metadata')
    for name,record in original['files'].items():
        if 'omitted_link' in record:
            print('Omitting unsafe source link: '+name,flush=True)
        elif not record.get('deleted'):
            source, target = root/name, destination/name
            if 'link' in record:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(record['link'])
            else:
                copy_file(source, target)
    assert_inputs(root,repos,original)
    expected = json.loads(json.dumps(original))
    for name,record in expected['files'].items():
        if 'omitted_link' in record:
            expected['files'][name] = {'deleted':True}
    assert_inputs(destination,repos,expected)


def stage(argv,cwd,log,timeout,nested=False):
    started = time.monotonic()
    with log.open('w') as stream:
        process = subprocess.Popen(argv,cwd=cwd,env=environment(),stdout=stream,
                                   stderr=subprocess.STDOUT,start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except (KeyboardInterrupt,subprocess.TimeoutExpired):
            if nested:
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                    process.wait(timeout=15)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    pass
            REGRESSION.stop_process(process)
            raise
        finally:
            REGRESSION.stop_process(process)
    CHECK.require(process.returncode == 0,'stage failed, exit '+str(process.returncode)+': '+str(log))
    return round(time.monotonic()-started,3)


def archive_profile(work,directory,profile,contract,state_hash,timeout,repos,frozen):
    directory.mkdir(parents=True)
    name = profile['target']
    seconds = stage(['bash','build.sh',name],work,directory/'build.log',timeout)
    assert_inputs(work,repos,frozen)
    focused = []
    for index,script in enumerate(profile['focused_tests']):
        result = REGRESSION.execute({'id':Path(script).stem,'path':script},[sys.executable,script],
                                    directory/('focused-'+str(index)+'.log'),180)
        focused.append(result)
        atomic_json(directory/'focused-results.json',focused)
        CHECK.require(result['status'] == 'PASS','focused profile check failed: '+script)
    atomic_json(directory/'focused-results.json',focused)
    assert_inputs(work,repos,frozen)
    build = work/'build'/name
    for filename in CHECK.required_files(profile,contract['cores'][profile['core']]):
        if filename not in ('build.log','focused-results.json','dependency-inputs.json'):
            copy_file(build/filename, directory/filename)
    shutil.copytree(build/'etc',directory/'etc',dirs_exist_ok=True)
    for source in (set(contract['contract_owners']) | set(contract['abi_sources']) |
                   set(profile['startup_sources']) | set(contract['dependency_sources'])):
        copy_file(work/source, directory/'sources'/source)
    config = CHECK.config_values((build/'NuttX/nuttx/.config').read_text())
    dependencies = {}
    if config.get('CONFIG_SEGGER_RTT') == 'y':
        for filename, key in RTT_DEPENDENCIES:
            source = work/NUTTX/'drivers/segger'/filename
            CHECK.require(CHECK.digest(source)==contract['rtt_pins'][key],'downloaded RTT pin mismatch: '+filename)
            copy_file(source, directory/'dependencies'/filename)
            dependencies[filename] = CHECK.digest(source)
    atomic_json(directory/'dependency-inputs.json',dependencies)
    atomic_json(directory/'build-receipt.json',{
        'schema_version':1,'target':name,'source_state_sha256':state_hash,
        'policy_sha256':CHECK.digest(CHECK.POLICY),'build_exit':0,'seconds':seconds,
        'original_build_directory':str(build),'target_actions':[],'files':CHECK.inventory(directory)})
    return CHECK.check_profile(directory,profile,contract,state_hash)


def reports(output,results,error=None):
    atomic_json(output/'build-results.json',{'schema_version':1,'results':results,
        'status':'BUILD-CHECKED' if all(r['status']=='BUILD-CHECKED' for r in results) and not error else 'FAIL',
        'reason':error,'full_matrix':len(results)==8,'on_target':'NOT-RUN','target_actions':[]})
    suite = ET.Element('testsuite',name='rzv2h-px4-build',tests=str(len(results)))
    for row in results:
        case = ET.SubElement(suite,'testcase',name=row['target'],time=str(row.get('seconds',0)))
        if row['status']=='NOT-RUN':
            ET.SubElement(case,'skipped',message='not executed')
        elif row['status']!='BUILD-CHECKED':
            ET.SubElement(case,'failure',message=row.get('reason',error or 'build failed'))
    if error and all(r['status']!='FAIL' for r in results):
        ET.SubElement(suite,'error',message=error)
    temporary = output/'junit.xml.tmp'
    ET.ElementTree(suite).write(temporary,encoding='utf-8',xml_declaration=True)
    temporary.replace(output/'junit.xml')


def pair_receipt(archive,contract,state_hash):
    dual = next(p for p in contract['profiles'] if p['peer'])
    if not (archive/'builds'/dual['target']).exists():
        return
    entry = {'id':'jlink-elf-snippets','path':'test/rzv2h-jlink-debug-tools-test.py'}
    result = REGRESSION.execute(entry,[sys.executable,entry['path'],
        'OneShotReadOnlyFilter.test_shipped_snippets_resolve_against_their_elfs'],archive/'pair-types.log',180)
    CHECK.require(result['status']=='PASS','offline compiled pair types failed')
    atomic_json(archive/'pair-receipt.json',{
        'schema_version':1,'status':'BUILD-CHECKED','source_state_sha256':state_hash,
        'policy_sha256':CHECK.digest(CHECK.POLICY),'type_check':result,
        'members':{n:{'receipt_sha256':CHECK.digest(archive/'builds'/n/'build-receipt.json'),
                       'elf_sha256':CHECK.digest(archive/'builds'/n/(n+'.elf'))}
                   for n in (dual['target'],dual['peer'])}})
    CHECK.check_pair(archive,contract,state_hash)


def run(args):
    safe_temp_base()
    contract = CHECK.policy(ROOT)
    selected = CHECK.select_profiles(contract,args.target)
    if args.list:
        print('\n'.join(p['target'] for p in selected))
        return 0
    CHECK.require(args.output is not None,'--output is required')
    CHECK.require(all(math.isfinite(t) and t>0 for t in (args.timeout,args.host_timeout)),'invalid timeout')
    repos = repositories(ROOT,contract)
    for name in REQUIRED_TOOLS:
        CHECK.require(shutil.which(name),'required tool missing: '+name)
    host_catalog = REGRESSION.read_catalog(REGRESSION.CATALOG)
    for entry in REGRESSION.select(host_catalog,['port-host'],[]):
        REGRESSION.invocation(entry,{})
    output = args.output.resolve()
    CHECK.require(output != ROOT and not ROOT.is_relative_to(output),'output aliases source checkout')
    CHECK.require(not output.is_relative_to(ROOT) or output.is_relative_to(ROOT/'build'),
                  'output inside source must use the build directory')
    CHECK.require(not output.exists() or output.is_dir() and not any(output.iterdir()),'output must be new or empty')
    if args.cache_dir:
        CHECK.require(not args.cache_dir.resolve().is_relative_to(output) and
                      not output.is_relative_to(args.cache_dir.resolve()),'cache/output overlap')
    CHECK.require(shutil.disk_usage('/tmp').free >= 8*1024**3,'insufficient temporary disk space (need 8 GiB)')
    original,before = source_inputs(ROOT,repos),sentinels(ROOT)
    results = [{'target':p['target'],'status':'NOT-RUN'} for p in selected]
    output.mkdir(parents=True,exist_ok=True)
    reports(output,results)
    archive = output/'archive'
    archive.mkdir()
    error,code,index = None,1,None
    try:
        with disposable_workspace() as temporary:
            work = temporary/'source'
            snapshot(ROOT,work,repos,original)
            overrides = SAMPLES.configure_cache(work/'platforms/nuttx/NuttX',args.cache_dir)
            frozen = source_inputs(work,repos)
            state_hash_path = archive/'source-state.json'
            atomic_json(state_hash_path,{
                'schema_version':1,'created':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'policy_sha256':CHECK.digest(CHECK.POLICY),'selected_targets':[p['target'] for p in selected],
                'requested_targets':args.target,'original_inputs':original,'effective_inputs':frozen,
                'effective_input_sha256':CHECK.identity(frozen),'snapshot_overrides':overrides,
                'compiler':command(['arm-none-eabi-gcc','--version']).splitlines()[0],
                'tool_versions':{name:{'path':str(Path(shutil.which(name)).resolve()),
                                      'version':command([name,'--version']).splitlines()[0]}
                                 for name in ('git','gcc','g++','make','ninja','cmake','rsync',
                                              'arm-none-eabi-gcc','arm-none-eabi-readelf','gdb-multiarch')},
                'python':{'path':sys.executable,'version':sys.version},
                'original_sentinels':before,'target_actions':[]})
            state_hash = CHECK.digest(state_hash_path)
            shutil.copy2(CHECK.POLICY,archive/'px4-profiles.json')
            REGRESSION.ROOT = work
            stage([sys.executable,'Tools/rzv2h-regression.py','run','--group','port-host',
                   '--output',str(archive/'host')],work,archive/'host-runner.log',args.host_timeout,nested=True)
            CHECK.check_host(archive)
            assert_inputs(work,repos,frozen)
            for index,profile in enumerate(selected):
                assert_inputs(work,repos,frozen)
                print('Building '+profile['target'],flush=True)
                results[index] = archive_profile(work,archive/'builds'/profile['target'],profile,contract,
                    state_hash,args.timeout,repos,frozen)
                reports(output,results)
            pair_receipt(archive,contract,state_hash)
            assert_inputs(work,repos,frozen)
        assert_inputs(ROOT,repos,original)
        CHECK.require(sentinels(ROOT)==before,'original configuration/link sentinels changed')
        atomic_json(archive/'inventory.json',{'schema_version':1,'files':CHECK.inventory(archive)})
        atomic_json(output/'artifact-checks.json',CHECK.verify(archive,args.target))
        code = 0
    except KeyboardInterrupt:
        error,code = 'cancelled; owned process groups stopped',130
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as caught:
        error = str(caught)
    finally:
        REGRESSION.ROOT = ROOT
        if error:
            if index is not None and results[index]['status']=='NOT-RUN':
                results[index].update(status='FAIL',reason=error)
            print(error,file=sys.stderr)
        try:
            CHECK.require(sentinels(ROOT)==before,'original configuration/link sentinels changed')
            assert_inputs(ROOT,repos,original)
        except (OSError,ValueError,subprocess.SubprocessError) as caught:
            error,code = 'live source changed: '+str(caught),1
        reports(output,results,error)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--target',action='append',default=[])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--cache-dir',type=Path)
    parser.add_argument('--timeout',type=float,default=1800)
    parser.add_argument('--host-timeout',type=float,default=10800)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM,REGRESSION.interrupted)
    try:
        return run(args)
    except KeyboardInterrupt:
        print('cancelled during preflight; owned process group stopped',file=sys.stderr)
        return 130
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(error,file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
