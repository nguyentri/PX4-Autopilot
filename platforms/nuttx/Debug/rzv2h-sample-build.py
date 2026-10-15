#!/usr/bin/env python3
"""Build and archive RTT samples in isolation; never connect to a board."""

import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
NUTTX = Path('platforms/nuttx/NuttX')
MANIFEST = ROOT/'platforms/nuttx/Debug/rzv2h-sample-profiles.json'
SPEC = importlib.util.spec_from_file_location(
    'sample_artifacts', ROOT/'platforms/nuttx/Debug/rzv2h-sample-artifact-check.py')
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)
SPEC = importlib.util.spec_from_file_location('regression', ROOT/'Tools/rzv2h-regression.py')
REGRESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGRESSION)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, cwd=ROOT):
    return subprocess.check_output(argv, cwd=cwd, text=True).strip()


def new_output(path):
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise ValueError('output directory must be new or empty: ' + str(path))
    return path


def snapshot(destination):
    """Use the working source, preserving uncommitted driver/config changes."""
    destination.mkdir()
    for name in ('nuttx', 'apps'):
        # Configure must recreate these links for this tree and target. Even
        # relative links can retain the previous chip/board selection.
        generated = ('/platform/board',) if name == 'apps' else (
            '/Make.defs', '/include/arch', '/drivers/platform',
            '/arch/arm/include/board', '/arch/arm/include/chip',
            '/arch/arm/src/board', '/arch/arm/src/chip')
        subprocess.run([
            'rsync', '-a', '--safe-links', '--exclude=.git', '--exclude=*.o', '--exclude=*.a',
            '--exclude=*.d', '--exclude=__pycache__', '--exclude=/nuttx',
            '--exclude=/nuttx.bin', '--exclude=/nuttx.hex', '--exclude=/nuttx.map',
            '--exclude=/System.map', '--exclude=/.config*',
            '--exclude=.dirlinks', '--exclude=.context',
            *('--exclude='+path for path in generated),
            str(ROOT/NUTTX/name)+'/', str(destination/name)+'/',
        ], check=True)
    shutil.copy2(ROOT/NUTTX/'build.sh', destination/'build.sh')


def configure_cache(work, cache):
    """Change download URLs only inside the disposable build snapshot."""
    if cache is None:
        return []
    overrides = []
    for relative, filename, pattern in (
        ('drivers/segger/Make.defs', 'RTT.zip',
         r'https://github.com/SEGGERMicro/RTT/archive/\$\(RTT_REVISION\)\.zip'),
        ('fs/littlefs/Make.defs', 'v2.4.0.tar.gz',
         r'https://github.com/ARMmbed/littlefs/archive/\$\(LITTLEFS_TARBALL\)'),
    ):
        archive = (cache/filename).resolve()
        if not archive.is_file():
            raise ValueError('missing download cache: ' + str(archive))
        path = work/'nuttx'/relative
        original = path.read_text()
        archive_digest = digest(archive)
        if filename == 'RTT.zip':
            expected = re.search(r'RTT_ARCHIVE_SHA256\s*=\s*(\w+)', original)
            if not expected or archive_digest != expected[1]:
                raise ValueError('RTT cache does not match the source-pinned digest')
        updated, count = re.subn(pattern, lambda _: archive.as_uri(), original)
        if count != 1:
            raise ValueError('cache URL no longer matches source: ' + relative)
        path.write_text(updated)
        overrides.append({'path': relative, 'archive': filename,
                          'archive_sha256': archive_digest,
                          'staged_sha256': digest(path), 'kind': 'download URL only'})
    return overrides


def source_state(work, overrides):
    commits = {}
    dirty = {}
    files = {NUTTX/'build.sh'}
    for label, directory in (('px4', Path('.')), ('nuttx', NUTTX/'nuttx'),
                             ('apps', NUTTX/'apps')):
        commits[label] = command(['git', 'rev-parse', 'HEAD'], ROOT/directory)
        dirty[label] = command(['git', 'status', '--porcelain'], ROOT/directory).splitlines()
        if label != 'px4':
            names = command(['git', 'ls-files', '--modified', '--others',
                             '--exclude-standard'], ROOT/directory).splitlines()
            files.update(directory/name for name in names)
    for relative in ('nuttx/arch/arm/src/rzv', 'nuttx/boards/arm/rzv/rdk-rzv2h',
                     'apps/testing/rzv_hwtest'):
        for path in (ROOT/NUTTX/relative).rglob('*'):
            if path.is_file() and (path.suffix in ('.c', '.h', '.txt') or
                                  path.name in ('Kconfig', 'Makefile', 'Make.defs', 'defconfig')):
                files.add(path.relative_to(ROOT))
    records = []
    for relative in sorted(files):
        original = ROOT/relative
        staged = work/relative.relative_to(NUTTX)
        if not original.is_file():
            records.append({'path': str(relative), 'deleted': True})
        elif original.suffix not in ('.o', '.a', '.d'):
            if not staged.is_file() or digest(original) != digest(staged):
                raise ValueError('snapshot/source mismatch: ' + str(relative))
            records.append({'path': str(relative), 'sha256': digest(staged)})
    return {'schema_version': 1,
            'created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'commits': commits, 'dirty_status': dirty,
            'compiler': command(['arm-none-eabi-gcc', '--version']).splitlines()[0],
            'source_files': records, 'snapshot_overrides': overrides,
            'manifest_sha256': digest(MANIFEST), 'target_actions': []}


def archive_profile(work, output, profile, state, state_hash):
    directory = output/'builds'/profile['profile']
    directory.mkdir(parents=True)
    with (directory/'build.log').open('w') as log:
        process = subprocess.Popen(['bash', str(work/'build.sh'), profile['profile']],
                                   stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            process.wait()
        except KeyboardInterrupt:
            REGRESSION.stop_process(process)
            raise
    if process.returncode:
        return {'profile': profile['profile'], 'status': 'BUILD-FAILED',
                'build_exit': process.returncode, 'log': str(directory/'build.log')}
    for original, name in (('nuttx', 'nuttx.elf'), ('.config', 'resolved.config'),
                           ('nuttx.map', 'nuttx.map'), ('System.map', 'System.map')):
        shutil.copy2(work/'nuttx'/original, directory/name)
    for name in ('nuttx.bin', 'nuttx.hex'):
        if (work/'nuttx'/name).is_file():
            shutil.copy2(work/'nuttx'/name, directory/name)
    names = ['nuttx.elf', 'resolved.config', 'nuttx.map', 'System.map']
    if profile['mode'] == 'scif-internal-loopback':
        shutil.copy2(work/'nuttx/arch/arm/src/libarch.a', directory/'libarch.a')
        (directory/'rzv_scif.o').write_bytes(subprocess.check_output(
            ['arm-none-eabi-ar', 'p', str(directory/'libarch.a'), 'rzv_scif.o']))
        names += ['libarch.a', 'rzv_scif.o']
    receipt = {'profile': profile['profile'], 'build_exit': 0,
               'compiler': state['compiler'], 'submodule_commits': state['commits'],
               'source_state_sha256': state_hash,
               'file_sha256': {name: digest(directory/name) for name in names}}
    (directory/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return ARTIFACTS.verify(profile, directory, output/'source-state.json')


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='list default RTT profile names')
    parser.add_argument('--profile', action='append', help='repeat to select profiles; default: all 14')
    parser.add_argument('--output', type=Path, help='new or empty archive directory')
    parser.add_argument('--cache-dir', type=Path, help='optional RTT.zip and v2.4.0.tar.gz download cache')
    args = parser.parse_args()
    profiles = json.loads(MANIFEST.read_text())['profiles']
    if args.list:
        print('\n'.join(p['profile'] for p in profiles))
        return 0
    if not args.output:
        parser.error('--output is required for builds')
    selected = args.profile or [p['profile'] for p in profiles]
    if len(set(selected)) != len(selected) or set(selected) - {p['profile'] for p in profiles}:
        parser.error('unknown or duplicate --profile')
    for tool in ('rsync', 'git', 'make', 'arm-none-eabi-gcc', 'arm-none-eabi-nm',
                 'arm-none-eabi-ar', 'arm-none-eabi-strings'):
        if not shutil.which(tool):
            parser.error('required host tool missing: ' + tool)
    try:
        output = new_output(args.output)
        with tempfile.TemporaryDirectory(prefix='rzv2h-sample-build-') as temporary:
            work = Path(temporary)/'NuttX'
            snapshot(work)
            # Record the pristine source snapshot before applying cache-only URLs.
            state = source_state(work, [])
            state['snapshot_overrides'] = configure_cache(work, args.cache_dir)
            (output/'source-state.json').write_text(json.dumps(state, indent=2)+'\n')
            shutil.copy2(MANIFEST, output/'sample-profiles.json')
            results = []
            for name in selected:
                profile = next(p for p in profiles if p['profile'] == name)
                try:
                    item = archive_profile(work, output, profile, state,
                                           digest(output/'source-state.json'))
                except (OSError, ValueError, subprocess.CalledProcessError) as error:
                    item = {'profile': name, 'status': 'NOT-READY', 'reason': str(error)}
                item.update(on_target='NOT-RUN', artifact_authorized=False,
                            target_prerequisites_verified=False)
                results.append(item)
                (output/'build-results.json').write_text(json.dumps(results, indent=2)+'\n')
                print(name, item['status'], flush=True)
                if item['status'] != 'BUILD-CHECKED':
                    return 1
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('build preparation failed: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('interrupted; owned build process stopped', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
