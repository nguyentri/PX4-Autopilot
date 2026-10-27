#!/usr/bin/env python3
"""Real-binutils host regressions for captured CR8 images; no hardware required."""
import copy
import contextlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Tools"))
from firmware_workspace import import_images as importer
from firmware_workspace.artifacts import compute_sha256
from firmware_workspace.catalog import load_groups
from firmware_workspace.contracts import validate_schema
from firmware_workspace.verification import OperationError, admitted_inputs, read_json
from firmware_workspace import artifacts as artifact_tools, load, debug, doctor
from firmware_workspace.probe import probe_history_path
from firmware_workspace.target_state import TargetState
from firmware_workspace.verification import prepared_identity


def elf(path, value=1, address=0x100, start=True, machine=40, flags=5, thumb=False):
    """Construct a genuine minimal ELF with a defined __start and ARM mapping symbol."""
    data = bytearray(512)
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 2, machine, 1, address, 52, 312,
                     0x5000200, 52, 32, 1, 40, 5, 4)
    struct.pack_into('<IIIIIIII', data, 52, 1, 128, address, address, 4, 4, flags, 4)
    struct.pack_into('<I', data, 128, 0xe1a00000 + value)
    strings = b'\x00__start\x00$a\x00$t\x00'
    data[200:200+len(strings)] = strings
    struct.pack_into('<IIIBBH', data, 160, 1, address + (1 if thumb else 0), 4, 0x12, 0, 1 if start else 0)
    struct.pack_into('<IIIBBH', data, 176, 11 if thumb else 9, address, 0, 0, 0, 1)
    names = b'\x00.text\x00.symtab\x00.strtab\x00.shstrtab\x00'
    data[240:240+len(names)] = names
    sections = [(1,1,6,address,128,4,0,0,4,0),(7,2,0,0,144,48,3,1,4,16),
                (15,3,0,0,200,len(strings),0,0,1,0),(23,3,0,0,240,len(names),0,0,1,0)]
    for index, section in enumerate(sections, 1):
        struct.pack_into('<10I', data, 312+index*40, *section)
    path.write_bytes(data)
    return path


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='core images ')
        self.root = Path(self.temp.name)
        self.patch = patch.object(importer, 'ARTIFACTS_ROOT', self.root / 'staged')
        self.patch.start()
        self.selection = {'schemaVersion':1,'id':'rzv-native-ipc-rtt','board':'rdk-rzv2h',
                          'core':'multicore','group':'rzv-native-ipc-rtt','build':{'family':'nuttx','mode':'incremental'},
                          'load':{'recipe':'rzv-dual-cr8-ram'}}
        self.members = {m['core']:m for m in load_groups()['groups'][self.selection['group']]['members']}

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def source(self, core, path):
        return {'kind':'file','path':str(path),'declaration':self.members[core]}

    def request(self, sources):
        return {'schemaVersion':1,'requestId':str(uuid.uuid4()),'selection':self.selection,'sources':sources}

    def prepare(self, sources):
        request = self.request(sources)
        path, result = importer.prepare_images(request)
        receipt = read_json(path)
        self.assertEqual(validate_schema(receipt, 'artifact-receipt'), [])
        return request, path, result, receipt

    def assembled_image(self, name, cpu, instructions, strip_mappings=False):
        source = self.root / (name + '.s')
        obj = source.with_suffix('.o')
        image = source.with_suffix('.elf')
        source.write_text(f'.syntax unified\n.cpu {cpu}\n.global __start\n{instructions}\n')
        commands = [
            ['arm-none-eabi-as', str(source), '-o', str(obj)],
            ['arm-none-eabi-ld', '-Ttext=0x100', '-e', '__start', str(obj), '-o', str(image)],
        ]
        if strip_mappings:
            commands.append(['arm-none-eabi-objcopy', '--strip-symbol=$a', '--strip-symbol=$t', str(image)])
        for command in commands:
            subprocess.run(command, check=True, capture_output=True, text=True)
        return image

    def test_thumb_only_start_without_mapping_cannot_publish(self):
        image = self.assembled_image('thumb-only', 'cortex-m4', '.thumb\n__start:\n b __start', True)
        other = elf(self.root / 'other.elf', value=2)
        for sources in ({'cr8_0': self.source('cr8_0', image)},
                        {'cr8_0': self.source('cr8_0', image), 'cr8_1': self.source('cr8_1', other)}):
            with self.subTest(pair=len(sources) == 2):
                with self.assertRaises(OperationError) as raised:
                    self.prepare(sources)
                self.assertEqual(raised.exception.code, 'UNSUPPORTED_STARTUP_CONTRACT')
        self.assertFalse(list((self.root / 'staged').glob('*/receipt.json')))

    def test_arm_start_with_thumb_functions_remains_supported(self):
        instructions = '.arm\n__start:\n b __start\n.thumb\n.thumb_func\nthumb_helper:\n bx lr'
        for strip in (False, True):
            with self.subTest(strip_mappings=strip):
                image = self.assembled_image('mixed-' + str(strip), 'cortex-r8', instructions, strip)
                _, _, result, _ = self.prepare({'cr8_0': self.source('cr8_0', image)})
                self.assertEqual(result['artifacts'][0]['checks']['startup'], 'supported')

    def test_published_metadata_survives_optional_symbol_tool_changes(self):
        instructions = '.arm\n__start:\n b __start\n.data\n.global _SEGGER_RTT\n_SEGGER_RTT:\n .word 0'
        lookup = artifact_tools.check_tool
        for initially_available in (False, True):
            with self.subTest(initially_available=initially_available):
                image = self.assembled_image('rtt-' + str(initially_available), 'cortex-r8', instructions)
                def tool(available):
                    return lambda name: None if name == 'arm-none-eabi-nm' and not available else lookup(name)
                with patch.object(artifact_tools, 'check_tool', side_effect=tool(initially_available)):
                    request, path, _, receipt = self.prepare({'cr8_0': self.source('cr8_0', image)})
                digest = compute_sha256(path)
                image.unlink()
                with patch.object(artifact_tools, 'check_tool', side_effect=tool(not initially_available)):
                    resumed_path, result = importer.prepare_images(request)
                    self.assertEqual(result['artifacts'], receipt['artifacts'])
                    # A new explicit preparation may discover metadata using the current tools.
                    _, _, _, updated = self.prepare({'cr8_0': {
                        'kind': 'prepared-receipt', 'receiptPath': str(path), 'artifactCore': 'cr8_0'}})
                self.assertEqual(resumed_path, path)
                self.assertEqual(compute_sha256(path), digest)
                self.assertEqual(bool(updated['artifacts'][0]['rttAddress']), not initially_available)

    def test_first_capture_survives_original_overwrite_and_becomes_pair(self):
        original = elf(self.root / 'nuttx')
        req, path, result, receipt = self.prepare({'cr8_0':self.source('cr8_0', original)})
        self.assertEqual(result['preparationState'], 'partial')
        original.unlink()
        self.assertEqual(importer.prepare_images(req)[0], path)
        replacement = elf(original, value=2)
        _, pair_path, result, pair = self.prepare({'cr8_0':{'kind':'prepared-receipt','receiptPath':str(path),'artifactCore':'cr8_0'},
                                                  'cr8_1':self.source('cr8_1', replacement)})
        self.assertEqual(result['preparationState'], 'ready')
        self.assertEqual(pair['artifacts'][0]['sha256'], receipt['artifacts'][0]['sha256'])
        self.assertIsNone(pair['compiler'])
        self.assertEqual(pair['artifacts'][0]['provenance']['evidence'], 'developer-declared')
        selection_path = self.root/'selection.json'
        selection_path.write_text(json.dumps(self.selection))
        self.assertEqual(len(admitted_inputs(SimpleNamespace(selection=selection_path, receipt=pair_path), 'load')[3]), 2)
        with self.assertRaisesRegex(OperationError, 'committed'):
            admitted_inputs(SimpleNamespace(selection=selection_path, receipt=path), 'debug')
        # A committed import is also a valid prepared member source.
        self.prepare({'cr8_0':{'kind':'prepared-receipt','receiptPath':str(pair_path),'artifactCore':'cr8_0'}})

    def test_startup_rejections(self):
        for kwargs in ({'start':False},{'machine':62},{'flags':6},{'thumb':True}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(OperationError, 'startup contract'):
                self.prepare({'cr8_0':self.source('cr8_0', elf(self.root/'bad', **kwargs))})
        self.assertFalse(list((self.root/'staged').glob('*/receipt.json')))
        for offset, replacement in ((4,b'\x02'),(5,b'\x02'),(16,b'\x03\x00'),(160+4,struct.pack('<I',0x1000)),
                                    (200+1,b'no_start')):
            invalid=elf(self.root/'malformed'); data=bytearray(invalid.read_bytes())
            data[offset:offset+len(replacement)]=replacement;invalid.write_bytes(data)
            with self.subTest(offset=offset),self.assertRaisesRegex(OperationError,'startup contract'):
                self.prepare({'cr8_0':self.source('cr8_0',invalid)})

    def test_missing_import_tool_and_bad_envelope(self):
        source=self.source('cr8_0',elf(self.root/'one'))
        with patch.object(importer,'check_tool',return_value=None),self.assertRaisesRegex(OperationError,'arm-none-eabi-readelf'):
            self.prepare({'cr8_0':source})
        for sources in ({},{'cm33':source},{'cr8_0':{'kind':'file','path':str(self.root/'one')}}):
            with self.subTest(sources=sources),self.assertRaises(OperationError):
                self.prepare(sources)

    def test_private_core_range_conflict(self):
        with self.assertRaisesRegex(OperationError, 'address admission'):
            self.prepare({'cr8_0':self.source('cr8_0', elf(self.root/'bad', address=0x081e0000))})

    def test_duplicate_bytes_and_declaration_rejected(self):
        one=elf(self.root/'one'); two=elf(self.root/'two')
        with self.assertRaisesRegex(OperationError, 'distinct image bytes'):
            self.prepare({'cr8_0':self.source('cr8_0', one),'cr8_1':self.source('cr8_1',two)})
        with self.assertRaisesRegex(OperationError, 'Declare the exact'):
            self.prepare({'cr8_1':self.source('cr8_0',one)})

    def test_explicit_folder_and_symlink_escape(self):
        folder = self.root/'folder'; folder.mkdir()
        elf(folder/'nuttx'); elf(folder/'other.elf', value=2)
        source={'kind':'folder','path':str(folder),'relativePath':'nuttx','declaration':self.members['cr8_0']}
        self.prepare({'cr8_0':source})
        (folder/'link').symlink_to(self.root/'outside')
        elf(self.root/'outside')
        for relative in ('../outside','link','/tmp/outside'):
            with self.subTest(relative=relative), self.assertRaises((OperationError,OSError)):
                self.prepare({'cr8_0':dict(source, relativePath=relative)})

    def test_tamper_and_request_id_collision(self):
        request,path,_,receipt=self.prepare({'cr8_0':self.source('cr8_0',elf(self.root/'nuttx'))})
        collision=copy.deepcopy(request); collision['selection']['id']='other'
        with self.assertRaisesRegex(OperationError,'different inputs'):
            importer.prepare_images(collision)
        staged=Path(receipt['artifacts'][0]['path']); staged.chmod(0o600); staged.write_bytes(b'tampered')
        with self.assertRaisesRegex(OperationError,'Captured bytes changed'):
            importer.prepare_images(request)

    def test_resume_after_capture_before_manifest_commit(self):
        original=elf(self.root/'nuttx')
        request=self.request({'cr8_0':self.source('cr8_0',original)})
        real=importer.atomic_json
        def fail(path,value):
            if path.name=='preparation.json' and value['state']=='captured':
                raise OSError('simulated crash')
            return real(path,value)
        with patch.object(importer,'atomic_json',side_effect=fail),self.assertRaises(OSError):
            importer.prepare_images(request)
        original.unlink()
        self.assertEqual(importer.prepare_images(request)[1]['preparationState'],'partial')

    def test_strict_duplicate_keys(self):
        path=self.root/'duplicate.json';path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(OperationError,'Duplicate JSON key'):
            read_json(path)

    def pair(self):
        return self.prepare({'cr8_0':self.source('cr8_0',elf(self.root/'one')),
                             'cr8_1':self.source('cr8_1',elf(self.root/'two',value=2))})

    def args(self, receipt):
        selection=self.root/'selection.json'; selection.write_text(json.dumps(self.selection))
        return SimpleNamespace(selection=selection,receipt=receipt,serial='host-fixture',core='cr8_0',json=True,
                               recover=False,require_loaded=False,expect_receipt_id=None,expect_pair_sha256=None)

    def invoke(self, command, args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output): code=command(args)
        return code,json.loads(output.getvalue())

    def test_receipt_reported_evidence_and_v2_non_upgrade(self):
        path=elf(self.root/'one')
        member=self.members['cr8_0']
        receipt={'schemaVersion':1,'receiptId':'external-copy','timestamp':'now','family':member['family'],
                 'board':self.selection['board'],'core':'cr8_0','selectionId':'external', 'config':member['config'],
                 'gitRevision':'reported','gitDirty':True,'compiler':'reported compiler','status':'committed',
                 'artifacts':[{'path':str(path),'size':path.stat().st_size,'sha256':compute_sha256(path)}]}
        receipt_path=self.root/'external.json'; receipt_path.write_text(json.dumps(receipt))
        _,prepared,_,result=self.prepare({'cr8_0':{'kind':'build-receipt','receiptPath':str(receipt_path),'artifactCore':'cr8_0'}})
        self.assertEqual(result['artifacts'][0]['provenance']['evidence'],'receipt-reported')
        self.assertEqual(result['artifacts'][0]['provenance']['reportedCompiler'],'reported compiler')
        self.assertIsNone(result['compiler'])
        receipt['config']='wrong';receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(OperationError,'member target'):
            self.prepare({'cr8_0':{'kind':'build-receipt','receiptPath':str(receipt_path),'artifactCore':'cr8_0'}})

    def test_every_publication_barrier_is_resumable_without_original(self):
        for barrier in ('captured','validated','published'):
            with self.subTest(barrier=barrier):
                original=elf(self.root/(barrier+'.elf'))
                request=self.request({'cr8_0':self.source('cr8_0',original)})
                real=importer.atomic_json
                def fail(path,value):
                    if path.name=='preparation.json' and value['state']==barrier:
                        raise OSError('simulated power loss')
                    return real(path,value)
                with patch.object(importer,'atomic_json',side_effect=fail),self.assertRaises(OSError):
                    importer.prepare_images(request)
                original.unlink()
                path,_=importer.prepare_images(request)
                self.assertEqual(read_json(path)['status'],'provisional')

    def test_source_rewrite_during_capture_rejected(self):
        original=elf(self.root/'mutable')
        real=os.read; changed=False
        def rewrite(fd,count):
            nonlocal changed
            value=real(fd,count)
            if value and not changed:
                changed=True;elf(original,value=2)
            return value
        with patch.object(importer.os,'read',side_effect=rewrite),self.assertRaisesRegex(OperationError,'changed during capture'):
            self.prepare({'cr8_0':self.source('cr8_0',original)})
        self.assertFalse(list((self.root/'staged').glob('*/receipt.json')))

    def test_prepared_containment_and_staged_hash_rejected(self):
        _,path,_,receipt=self.prepare({'cr8_0':self.source('cr8_0',elf(self.root/'one'))})
        receipt['artifacts'][0]['path']=str(self.root/'one');path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(OperationError,'escapes'):
            self.prepare({'cr8_0':{'kind':'prepared-receipt','receiptPath':str(path),'artifactCore':'cr8_0'}})

    def test_expectations_checked_before_any_probe_access(self):
        _,path,_,receipt=self.pair();args=self.args(path);args.expect_receipt_id='replaced'
        for module,command in ((load,load.cmd_load),(debug,debug.cmd_debug_config)):
            with self.subTest(command=command.__name__),patch.object(module,'resolve_serial') as probe:
                code,result=self.invoke(command,args)
                self.assertEqual(code,2);self.assertEqual(result['diagnostics'][0]['code'],'PREPARED_IDENTITY_MISMATCH')
                probe.assert_not_called()

    def test_loaded_history_requires_complete_byte_pair_and_invalidates_legacy_writes(self):
        _,path,_,receipt=self.pair();args=self.args(path)
        selection,resolved,receipt,artifacts=admitted_inputs(args,'debug')
        expected=prepared_identity(selection,resolved,receipt,artifacts)
        state=TargetState(self.root/'target-state.json')
        rich={'digests':expected['artifactDigests'],'group':expected['groupDefinitionSha256'],
              'pair_id':expected['pairSha256'],'operation_id':'operation-one'}
        for cores,phase in ((['cr8_0'],'verified'),(['cr8_0'],'indeterminate/recovery-required'),(['cr8_1'],'started'),
                            (['cm33'],'indeterminate/recovery-required')):
            state.record(['cr8_0','cr8_1'],'verified','receipt-old',**rich)
            state.require_loaded(expected)
            state.record(cores,phase,'legacy-receipt')
            self.assertNotIn('verifiedPair',state.value)
            with self.assertRaises(OperationError):state.require_loaded(expected)
        state.record(['cr8_0','cr8_1'],'verified','older-receipt',**rich)
        # Receipt IDs are audit references: identical bytes in a new receipt still match.
        state.require_loaded(dict(expected,receiptId='new-receipt'))
        with self.assertRaisesRegex(OperationError,'differs'):
            state.require_loaded(dict(expected,pairSha256='0'*64))

    def test_strict_debug_is_optional_and_history_read_is_probe_free(self):
        _,path,_,receipt=self.pair();args=self.args(path)
        with patch.dict(os.environ,{'FIRMWARE_WORKSPACE_RUNTIME':str(self.root/'runtime')}):
            args.require_loaded=True
            code,result=self.invoke(debug.cmd_debug_config,args)
            self.assertEqual(result['diagnostics'][0]['code'],'LOADED_IMAGE_MISMATCH')
            self.assertFalse((self.root/'runtime').exists())
            selection,resolved,receipt,artifacts=admitted_inputs(args,'debug')
            expected=prepared_identity(selection,resolved,receipt,artifacts)
            TargetState(probe_history_path(args.serial)).record(['cr8_0','cr8_1'],'verified','old-receipt',
                digests=expected['artifactDigests'],group=expected['groupDefinitionSha256'],pair_id=expected['pairSha256'],operation_id='paired')
            with patch.object(debug,'debug_snapshot',return_value=self.root/'symbols.elf'):
                code,result=self.invoke(debug.cmd_debug_config,args)
                self.assertEqual(code,0);self.assertEqual(result['data']['artifactSha256'],expected['artifactDigests']['cr8_0'])
            with patch.object(doctor,'run_doctor',return_value=({'tools':{}},[])):
                code,result=self.invoke(doctor.cmd_doctor,args)
                self.assertEqual(result['data']['targetHistory']['verifiedPair']['pairSha256'],expected['pairSha256'])
                self.assertTrue(result['data']['importPrerequisites']['ready'])
            probe_history_path(args.serial).write_text('corrupt')
            with patch.object(doctor,'run_doctor',return_value=({'tools':{}},[])):
                _,result=self.invoke(doctor.cmd_doctor,args)
                self.assertTrue(result['data']['targetHistory']['recoveryRequired'])

    def test_progress_chunking_and_interruption(self):
        progress=load.LoadProgress('operation',self.root)
        errors=io.StringIO()
        with contextlib.redirect_stderr(errors):
            progress.output('PX4_WORKSPACE_ST','stderr')
            progress.output('EP cr8_0 load begin\nplain\nPX4_WORKSPACE_STEP cr8_0 load ok\n','stderr')
            progress.output('PX4_WORKSPACE_STEP cr8_1 load begin\n','stderr')
        progress.finish()
        self.assertEqual([item['state'] for item in progress.steps],['begin','ok','begin','indeterminate'])
        self.assertEqual(len(errors.getvalue().splitlines()),3)

    def test_real_pair_script_progress_logs_failure_and_recovery(self):
        _,path,_,receipt=self.pair();args=self.args(path)
        canonical=Path(load.REPO_ROOT)/'platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh'
        scripts=self.root/'platforms/nuttx/Debug/rzv2h-ipc';scripts.mkdir(parents=True)
        shutil.copy2(canonical,scripts/canonical.name)
        for name in ('rzv2h-ipc-hil-loadstart.gdb','rzv2h-ipc-hil-verify-resume.gdb'):
            (scripts/name).write_text('# fixture')
        (scripts/'rzv2h-ipc-demo-jlink-lib.sh').write_text('''
resolve_tools() { return 0; }
_stop_server() { :; }
load_core() { echo load > "${LOG_DIR}/load-$3.log"; [ "${FAIL_CORE:-}" != "$3" ]; }
verify_core() { echo verify > "${LOG_DIR}/verify-$3.log"; [ "${FAIL_VERIFY:-}" != "$3" ]; }
''')
        with patch.dict(os.environ,{'FIRMWARE_WORKSPACE_RUNTIME':str(self.root/'runtime')}), \
                patch.object(load,'REPO_ROOT',self.root),patch.object(load,'check_rz_allowlist'), \
                patch.object(load,'ProbeLease',side_effect=lambda _:contextlib.nullcontext()),patch.object(load,'require_probe_available'):
            errors=io.StringIO()
            with contextlib.redirect_stderr(errors):code,result=self.invoke(load.cmd_load,args)
            self.assertEqual(code,0)
            self.assertEqual([(s['core'],s['phase'],s['state']) for s in result['data']['steps']],
                [(core,phase,state) for core,phase in (('cr8_0','load'),('cr8_1','load'),('cr8_0','verify'),('cr8_1','verify')) for state in ('begin','ok')])
            self.assertEqual(errors.getvalue().count('PX4_WORKSPACE_EVENT '),8)
            first_logs=Path(result['data']['logPath']); self.assertTrue((first_logs/'load-CR8-0.log').exists())
            with patch.dict(os.environ,{'FAIL_VERIFY':'CR8-1'}),contextlib.redirect_stderr(io.StringIO()):
                code,failed=self.invoke(load.cmd_load,args)
            self.assertEqual(code,1); self.assertTrue(failed['data']['recoveryRequired'])
            self.assertEqual(failed['data']['steps'][-1]['state'],'fail')
            self.assertNotEqual(failed['data']['logPath'],str(first_logs))
            self.assertEqual((first_logs/'load-CR8-0.log').read_text(),'load\n')
            code,blocked=self.invoke(load.cmd_load,args);self.assertEqual(code,3)
            args.recover=True
            with contextlib.redirect_stderr(io.StringIO()):code,recovered=self.invoke(load.cmd_load,args)
            self.assertEqual(code,0)
            history=TargetState(probe_history_path(args.serial)).history()
            self.assertFalse(history['recoveryRequired']);self.assertEqual(history['verifiedPair']['pairSha256'],recovered['data']['pairSha256'])


if __name__ == '__main__':
    unittest.main()
