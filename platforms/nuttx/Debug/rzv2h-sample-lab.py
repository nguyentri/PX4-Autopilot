#!/usr/bin/env python3
"""Preview or explicitly execute one admitted native sample on a local bench.

This is an operator utility, not an approval service. --execute and an external
approval reference are mandatory for probe access. Archive booleans never grant
permission. Reset, flash, arbitrary console commands and CM33 are unsupported.
"""

import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ARTIFACT = module('lab_artifacts', HERE/'rzv2h-sample-artifact-check.py')
RUNNER = module('lab_evidence', HERE/'rzv2h-sample-runner.py')
PROCESSES = module('lab_processes', ROOT/'Tools/rzv2h-regression.py')
LAB_PORTS = (19021, 50000)
PASSTHROUGH_ENVIRONMENT = ('PATH', 'HOME', 'LANG', 'LC_ALL')
ALLOWED_COMMANDS = {
    'free', 'ps', 'hwtest', 'can', 'rzv_canfd', 'rzv_dmac', 'timer',
    'gy912_test', 'bmm150', 'adc'
}
REDACTED_SUFFIXES = ('.log', '.txt', '.jlink', '.gdb', '.json')
RESET = re.compile(r'Resetting via Reset pin|cold reset sequence|DBGEN(?: is)? not asserted|DBGEN is not asserted', re.I)
TERMINAL = {'hwtest': r'TEST_DONE: exit=', 'can': r'Terminating!',
            'canfd': r'(?:FAIL|PASS) frames=', 'dmac': r'PASS: DMAC memcpy ch=64',
            'timer': r'Finished', 'gy912': r'ICM20948 result=',
            'bmm150': r'bmm150: (?:scan )?PASS', 'adc': r'channel:\s*3 value:\s*-?\d+\b'}
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
TASK_GDB = '''printf "TASK_HEALTH_BEGIN count=%d\\n", g_npidhash
if g_npidhash > 0 && g_npidhash <= 256
set $sample_index = 0
while $sample_index < g_npidhash
if g_pidhash[$sample_index] != 0
printf "TASK_ENTRY: %#x\\n", g_pidhash[$sample_index]->entry.main
end
set $sample_index = $sample_index + 1
end
printf "TASK_HEALTH_END\\n"
end
info registers pc cpsr sp
'''


class LabError(ValueError):
    pass


class RecoveryRequired(LabError):
    pass


class LabTimeout(LabError):
    pass


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(archive, name, fixture):
    manifest = ARTIFACT.INVENTORY.load()
    rows = [x for x in manifest['profiles'] if x['profile'] == name]
    if len(rows) != 1:
        raise LabError('unknown or duplicate profile')
    row = rows[0]
    if row['core'] == 'cm33' or row['mode'] == 'blocked':
        raise LabError(row.get('reason') or 'unsupported target route')
    if row['core'] != 'cr8_0':
        raise LabError('peer/core-1 images require separately admitted pair/console workflow')
    if row['hazards'] and row['hazards'] != ['fitted-led-output']:
        raise LabError('boot/output hazard requires separate admission')
    if fixture.get('reset_class') != 'warm-load' or not fixture.get('initial_state'):
        raise LabError('known predecessor state and warm-load class required')
    verified = fixture.get('verified', {})
    if not isinstance(verified, dict) or any(not verified.get(x) for x in row['requirements']):
        raise LabError('unverified fixture prerequisites: ' + ', '.join(x for x in row['requirements'] if not verified.get(x)))
    if sha(archive/'sample-profiles.json') != sha(ARTIFACT.INVENTORY.POLICY):
        raise LabError('archive execution policy differs from reviewed installed policy')
    directory = archive/'builds'/name
    admission = ARTIFACT.verify_native(row, directory, archive/'source-state.json', manifest)
    if row['commands'] and row['mode'] not in ('shell','hwtest','native'):
        raise LabError('invalid action registry mode')
    # Every command comes from the installed policy, never fixture/receipt text.
    for command in row['commands']:
        if not re.fullmatch(r'[A-Za-z0-9_ /.,:=+-]+', command):
            raise LabError('shell syntax or unbounded command in installed action')
        if command.split()[0] not in ALLOWED_COMMANDS:
            raise LabError('action not in the native command registry')
    return row, admission, directory


def environment(output, serial):
    result = {key: os.environ[key] for key in PASSTHROUGH_ENVIRONMENT if key in os.environ}
    result.update(LOAD_ATTEMPTS='1', JLINK_SERIAL=serial, JLINK_SPEED='auto',
                  GDB_PORT='50000', RTT_PORT='19021', LOG_DIR=str(output/'loader'))
    return result


def port_free(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1',port))
            return True
        except OSError:
            return False


def ports_free():
    return all(port_free(port) for port in LAB_PORTS)


def cleanup_observation(env, output, serial):
    # Host inspection only: never opens a target connection during recovery.
    observed = invoke([sys.executable,str(HERE/'jlink-debug-preflight.py')],
                      env,output,'post-preflight',15,serial)
    owners = observed.split('== probe owners',1)[-1].split('== ports',1)[0]
    dead = bool(re.search(r'(?m)^\s*none\s*$', owners))
    free = ports_free()
    return {'bridge_stopped':dead and free,'owned_pid_dead':dead,'port_free':free}


def clean_console(path):
    return ANSI.sub('', path.read_text(errors='replace').replace('\r', ''))


def invoke(argv, env, output, label, timeout, serial=''):
    with (output/(label+'.raw.log')).open('w') as stream:
        child = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stream,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            PROCESSES.stop_process(child)
            raise LabTimeout(label + ': timeout; target state unresolved')
        except KeyboardInterrupt:
            PROCESSES.stop_process(child)
            raise LabError(label + ': interrupted; target state unresolved')
        finally:
            if child.poll() is None:
                PROCESSES.stop_process(child)
    text = (output/(label+'.raw.log')).read_text(errors='replace')
    safe = text.replace(serial,'<probe-sn>') if serial else text
    (output/(label+'.log')).write_text(safe)
    if RESET.search(text):
        raise RecoveryRequired(label + ': reset/connect failure; no reconnect or reload without fresh approval')
    if child.returncode:
        raise LabError(label + ': helper exit ' + str(child.returncode))
    return text


def execute(args, row, admission, directory, fixture):
    output = args.output.resolve()
    serial_result = subprocess.run([sys.executable,str(HERE/'jlink-debug-preflight.py'),'--print-serial'],
                                   capture_output=True,text=True,timeout=10)
    if serial_result.returncode or not serial_result.stdout.strip().isdigit():
        raise LabError('exactly one host-visible J-Link is required')
    serial = serial_result.stdout.strip()
    env = environment(output,serial)
    check = invoke([sys.executable,str(HERE/'jlink-debug-preflight.py'),str(directory/'nuttx.elf')],
                   env,output,'preflight',15,serial)
    owners = check.split('== probe owners',1)[-1].split('== ports',1)[0]
    if not re.search(r'(?m)^\s*none\s*$', owners) or not ports_free():
        raise LabError('probe/ports have a pre-existing owner; refusing to stop it')
    run_id = args.run_id or datetime.datetime.now().strftime('%y%m%d-%H%M%S-')+row['profile']
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id):
        raise LabError('invalid run id')
    raw = output/'console.raw.txt'
    shell = row['entrypoint'] == 'nsh_main'
    bridge = False
    cleanup = {'bridge_stopped':False,'owned_pid_dead':False,'port_free':False}
    receipt = dict(profile=row['profile'],core=row['core'],console=row['console'],
                   board='rdk-rzv2h',operator=os.environ.get('USER','local-operator'),
                   probe='<probe-sn>',commands=row['commands'],run_id=run_id,
                   elf_sha256=admission['elf_sha256'],config_sha256=admission['config_sha256'],
                   source_state_sha256=admission['source_state_sha256'],
                   approval_reference=args.approval_ref,reset_class='warm-load',
                   initial_state=fixture['initial_state'],fixture=fixture,
                   completion_source='waitpid' if admission['waitpid'] else 'task-resource-oracle',
                   timed_out=False,cleanup=cleanup,loader_environment={'LOAD_ATTEMPTS':'1'},
                   policy_sha256=sha(ARTIFACT.INVENTORY.POLICY),
                   executor_sha256=sha(Path(__file__)),target_actions=[])
    def checkpoint():
        (output/'run-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    checkpoint()
    print('Loading',row['core'],directory/'nuttx.elf','SHA256',admission['elf_sha256'],'probe=<probe-sn>',flush=True)
    try:
        receipt['target_actions'].append('guarded-ram-load')
        checkpoint()
        invoke(['bash',str(HERE/'rzv2h-ipc/rzv2h-load-one-core.sh'),row['core'],str(directory/'nuttx.elf')],
               env,output,'load',120,serial)
        if row['console'].startswith('rtt'):
            receipt['target_actions'].append('rtt-attach')
            checkpoint()
            invoke(['bash',str(HERE/'nuttx-rtt-bridge.sh'),'start',row['core'],str(directory/'nuttx.elf')],
                   env,output,'bridge-start',110,serial)
            bridge = True
            transport = ['--rtt','19021']
        elif row['console'] == 'sci4':
            transport = ['--serial','/dev/ttyUSB0','--baud','115200']
        else:
            raise LabError('console route not available on this fixture')
        client = [sys.executable,str(HERE/'nsh_console_exec.py'),*transport]
        if row['mode'] == 'boot':
            boot = invoke([*client,'--monitor','--timeout',str(row['timeout'])],
                          env,output,'boot-capture',row['timeout']+5,serial)
            transcript = 'RUN_BEGIN: '+run_id+'\n'+boot+'\nRUN_END: '+run_id+'\n'
        else:
            invoke([*client,'--timeout','8','--log',str(raw),'echo SAMPLE_READY'],env,output,'sync',12,serial)
            invoke([*client,'--timeout','8','--log',str(raw),'echo RUN_BEGIN: '+run_id],env,output,'begin',12,serial)
            for index, command in enumerate(row['commands']):
                receipt['target_actions'].append('bounded-command:'+str(index))
                checkpoint()
                extra = []
                commands = [command]
                if admission['waitpid']:
                    commands.append('echo APP_EXIT_'+str(index)+'=$?')
                elif row['mode'] != 'shell':
                    extra = ['--marker','--until',TERMINAL[row['oracle']]]
                invoke([*client,'--timeout',str(row['timeout']),'--log',str(raw),*extra,*commands],
                       env,output,'command-'+str(index),row['timeout']*(len(commands)+1)+5,serial)
            invoke([*client,'--timeout','8','--log',str(raw),'echo RUN_END: '+run_id],env,output,'end',12,serial)
            transcript = clean_console(raw)
        if shell:
            health_raw = output/'health.raw.txt'
            invoke([*client,'--timeout','8','--log',str(health_raw),'ps','free'],env,output,'health',30,serial)
            health = clean_console(health_raw)
            transcript += '\n'+health
        else:
            health = ''
        if bridge:
            invoke(['bash',str(HERE/'nuttx-rtt-bridge.sh'),'stop'],env,output,'bridge-stop',20,serial)
            bridge = False
        if not admission['waitpid'] and row['mode'] != 'shell':
            receipt['target_actions'].append('read-only-task-census')
            checkpoint()
            gdb = output/'tasks.gdb'
            gdb.write_text(TASK_GDB)
            health += '\n'+invoke([sys.executable,str(HERE/'jlink-gdb-oneshot.py'),row['core'],
                                   str(directory/'nuttx.elf'),'--attempts','1','--log',str(output/'gdb-server.log'),
                                   '-x',str(gdb)],env,output,'task-census',90,serial)
        cleanup.update(cleanup_observation(env,output,serial))
        for name,text in (('transcript',transcript),('health',health)):
            safe = text.replace(serial,'<probe-sn>')
            (output/(name+'.txt')).write_text(safe)
            receipt[name+'_sha256'] = hashlib.sha256(safe.encode()).hexdigest()
        checkpoint()
        result = RUNNER.check_native(row,(output/'transcript.txt').read_text(),
                                     (output/'health.txt').read_text(),receipt,admission)
        return result
    except LabTimeout:
        receipt['timed_out'] = True
        raise
    finally:
        try:
            if bridge:
                invoke(['bash',str(HERE/'nuttx-rtt-bridge.sh'),'stop'],env,output,'bridge-stop-final',20,serial)
            if not all(cleanup.values()):
                cleanup.update(cleanup_observation(env,output,serial))
        except (LabError,OSError,subprocess.SubprocessError) as error:
            receipt['cleanup_error'] = str(error)
            cleanup.update(bridge_stopped=False,owned_pid_dead=False,port_free=ports_free())
        finally:
            checkpoint()
            # Even failed shutdown paths must checkpoint and redact identifiers.
            for path in output.rglob('*'):
                if path.is_file() and path.suffix in REDACTED_SUFFIXES:
                    text = path.read_text(errors='replace')
                    if serial in text:
                        path.write_text(text.replace(serial,'<probe-sn>'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='new or empty run directory')
    parser.add_argument('--run-id')
    parser.add_argument('--approval-ref',help='independent explicit user/runtime or protected-job approval')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute',action='store_true')
    mode.add_argument('--dry-run',action='store_true',help='default; no probe, serial or target access')
    args = parser.parse_args()
    args.archive = args.archive.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    if any(args.output.iterdir()):
        parser.error('output must be new or empty')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    result = {'profile':args.profile,'status':'BLOCKED','target_actions':[]}
    code = 2
    try:
        row, admission, directory = prepare(args.archive,args.profile,json.loads(args.fixture.read_text()))
        result.update(core=row['core'],elf_sha256=admission['elf_sha256'],commands=row['commands'])
        if args.execute:
            if not args.approval_ref or '\n' in args.approval_ref:
                raise LabError('--execute requires an independent approval reference')
            with open('/tmp/rzv2h-sample-lab.lock','a') as lock:
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    raise LabError('another lab executor owns the probe/fixture lock')
                result = execute(args,row,admission,directory,json.loads(args.fixture.read_text()))
            code = 0
        else:
            result.update(status='DRY-RUN',target_actions=[],loader_environment={'LOAD_ATTEMPTS':'1'})
            code = 0
    except RecoveryRequired as error:
        result.update(status='BLOCKED',reason=str(error),recovery_required=True)
        code = 3
    except (LabError,RUNNER.EvidenceError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,KeyboardInterrupt) as error:
        result.update(status='NOT-PASS',reason=str(error))
        code = 1
    if (args.output/'run-receipt.json').exists():
        partial = json.loads((args.output/'run-receipt.json').read_text())
        result['target_actions'] = partial.get('target_actions',[])
        if partial.get('timed_out'):
            result.update(status='BLOCKED',recovery_required=True,target_state_unresolved=True)
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
