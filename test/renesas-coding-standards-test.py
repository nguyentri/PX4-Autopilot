#!/usr/bin/env python3
"""Exercise real formatter adapters and source-preservation boundaries."""

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("standards", ROOT / "Tools/renesas-coding-standards.py")
STANDARDS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STANDARDS
SPEC.loader.exec_module(STANDARDS)


class RegisterSpellingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.owner_path = STANDARDS.NUTTX / 'arch/arm/src/rzv/hardware/registers.h'
        self.owner = self.root / self.owner_path
        self.owner.parent.mkdir(parents=True)
        self.owner.write_text('#define REGISTER_Field (1u << 0)\n')
        self.text = '  value = REGISTER_Field;\n'
        self.finding = {'rule': 'nxstyle', 'line': 1, 'column': 10,
                        'message': 'Mixed case identifier found'}
        self.source = STANDARDS.Source(Path('source.c'), 'nuttx', '100644', 'handwritten',
            {'native_symbol_dispositions': {
                'source_sha256': STANDARDS.digest(self.text.encode()),
                'symbols': {'REGISTER_Field': {'path': str(self.owner_path),
                    'sha256': STANDARDS.digest(self.owner.read_bytes()),
                    'evidence': 'Public register field spelling.'}}}})

    def test_raw_diagnostic_is_retained_with_verified_owner(self):
        raw = [self.finding.copy()]
        reviewed = STANDARDS.reviewed_symbol_findings(self.root, self.source, self.text, raw)
        self.assertEqual(raw, [self.finding])
        self.assertEqual(reviewed[0]['identifier'], 'REGISTER_Field')

    def test_source_or_owner_change_requires_review(self):
        self.assertEqual(STANDARDS.reviewed_symbol_findings(
            self.root, self.source, self.text + '\n', [self.finding]), [])
        self.owner.write_text('#define REGISTER_Field 2u\n')
        self.assertEqual(STANDARDS.reviewed_symbol_findings(
            self.root, self.source, self.text, [self.finding]), [])

    def test_other_rule_or_column_cannot_be_dispositioned(self):
        for update in ({'rule': 'comment-policy'}, {'column': 11},
                       {'message': 'Long line found'}):
            with self.subTest(update=update):
                self.assertEqual(STANDARDS.reviewed_symbol_findings(self.root, self.source,
                    self.text, [{**self.finding, **update}]), [])

    def test_missing_definition_cannot_be_dispositioned(self):
        self.owner.write_text('#define OTHER_Field 1u\n')
        self.source.ownership['native_symbol_dispositions']['symbols']['REGISTER_Field'][
            'sha256'] = STANDARDS.digest(self.owner.read_bytes())
        self.assertEqual(STANDARDS.reviewed_symbol_findings(
            self.root, self.source, self.text, [self.finding]), [])

    def test_owner_definition_uses_the_same_snapshot_as_its_digest(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('second owner read')):
            reviewed = STANDARDS.reviewed_symbol_findings(
                self.root, self.source, self.text, [self.finding])
        self.assertEqual(len(reviewed), 1)

    def test_final_owner_change_invalidates_the_checker_run(self):
        reviewed = STANDARDS.reviewed_symbol_findings(
            self.root, self.source, self.text, [self.finding])
        checkers = STANDARDS.Checkers(self.root, self.root / 'cache')
        checkers.inputs[str(self.owner_path)] = reviewed[0]['disposition']['sha256']
        checkers.owner_inputs[str(self.owner_path)] = reviewed[0]['owner_identity']
        self.owner.write_text('#define REGISTER_Field 2u\n')
        with self.assertRaises(STANDARDS.ToolError):
            checkers.assert_inputs()

    def test_owner_symlink_is_refused(self):
        original = self.owner.with_suffix('.original')
        self.owner.rename(original)
        self.owner.symlink_to(original)
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.reviewed_symbol_findings(self.root, self.source, self.text, [self.finding])


class PreservationTests(unittest.TestCase):
    def test_strings_and_legal_text_are_not_process_comments(self):
        source = 'const char *s = "TODO https://example.invalid";\n/* SPDX-License-Identifier: Apache-2.0 */\n'
        self.assertEqual(STANDARDS.policy_findings(source), [])

    def test_actual_comments_are_found(self):
        findings = STANDARDS.policy_findings('/* TODO: bound the retry. */\n/* phase 2 */\n')
        self.assertEqual([x["line"] for x in findings], [1, 2])

    def test_audit_labels_are_found_without_matching_hardware_names(self):
        text = '/* (A3+A10 fix) */\n/* (#13 fix) */\n/* [M12] */\n'
        self.assertEqual([x['line'] for x in STANDARDS.policy_findings(text)],
                         [1, 2, 3])
        self.assertEqual(STANDARDS.policy_findings(
            '/* Cortex-M33 accesses SCI9 and sets the sampling phase. */'), [])

    def test_malformed_comments_and_literals_are_refused(self):
        for text in ['int x; /* unterminated   ', 'char *p = "unterminated',
                     "char c = 'x", 'auto p = R"tag(unterminated',
                     'char *p = "text\\\n/* TODO still literal']:
            with self.subTest(text=text), self.assertRaises(STANDARDS.ToolError):
                STANDARDS.normalize_nuttx(text, [], Path('file.c'))

    def test_raw_strings_and_continued_comments_are_lexical(self):
        self.assertEqual(STANDARDS.policy_findings('auto x = R"tag(TODO " // https://example)tag";'), [])
        findings = STANDARDS.policy_findings('// continued \\\n TODO needs disposition\n')
        self.assertEqual([f['message'] for f in findings], ['TODO'])

    def test_license_header_does_not_exempt_process_metadata(self):
        text = '/* Copyright 2026\n * https://www.apache.org/licenses/LICENSE-2.0\n * TODO: bound the retry\n */'
        self.assertEqual([x['message'] for x in STANDARDS.policy_findings(text)], ['TODO'])

    def test_protected_content_detects_macro_and_attribution_changes(self):
        text = '#define VALUE 1\n/* Copyright 2026 */\nint value;\n'
        self.assertNotEqual(STANDARDS.protected_content(text),
                            STANDARDS.protected_content(text.replace('VALUE 1', 'VALUE 2')))
        self.assertNotEqual(STANDARDS.protected_content(text),
                            STANDARDS.protected_content(text.replace('2026', '2025')))

    def test_hardware_phase_and_valid_commit_type_are_not_labels(self):
        self.assertEqual(STANDARDS.policy_findings('/* Set the sampling phase. fix(rzv2h): bound retry */'), [])

    def test_multi_character_operators_preserve_token_identity(self):
        self.assertNotEqual(STANDARDS.code_tokens('a + + b;'), STANDARDS.code_tokens('a ++ b;'))

    def test_added_braces_are_detected(self):
        self.assertNotEqual(STANDARDS.code_tokens('if (x) y();'),
                            STANDARDS.code_tokens('if (x) { y(); }'))

    def test_continued_macro_strings_and_backslashes_remain_identical(self):
        text = '#define LOG(x) \\\r\n  "value=" x \\  \r\n  "tail"\r\n'
        result = STANDARDS.normalize_nuttx(text, [], Path('arch/arm/src/rzv/example.c'))
        self.assertEqual(text, result)

    def test_multiline_comment_inside_directive_remains_identical(self):
        text = '#define VALUE /* Explanation   \n * extends here.   \n */ 1\n'
        self.assertEqual(STANDARDS.normalize_nuttx(text, [], Path('file.c')), text)

    def test_literal_tabs_quotes_and_continued_literals_remain_identical(self):
        for text in ['char *s = "a\tb";\n', 'char *s = "a\\\n' + '\\"b";\n',
                     'char *s = "a\\\r\nb";\r\n', "char c = '\\'';\n"]:
            with self.subTest(text=text):
                self.assertEqual(STANDARDS.normalize_nuttx(text, [], Path('file.c')), text)

    def test_missing_newline_and_trailing_spaces_can_be_normalized(self):
        text = 'int value;  '
        normalized = STANDARDS.normalize_nuttx(text, [], Path('file.c'))
        self.assertEqual(normalized, 'int value;\n')
        self.assertEqual(STANDARDS.normalize_nuttx(normalized, [], Path('file.c')), normalized)

    def test_diagnostic_mapping_accepts_shifted_unchanged_finding(self):
        issue = lambda line, message: {"line": line, "column": 1, "message": message}
        before = [issue(1, 'spacing'), issue(2, 'long line')]
        after = [issue(3, 'long line')]
        self.assertTrue(STANDARDS.diagnostics_improve(before, after, 'a\nb\n', 'a\n\nb\n'))

    def test_smaller_count_cannot_hide_a_new_finding(self):
        issue = lambda line, message: {"line": line, "column": 1, "message": message}
        self.assertFalse(STANDARDS.diagnostics_improve(
            [issue(1, 'spacing'), issue(2, 'long line')], [issue(2, 'spacing')], 'a\nb\n', 'a\nb\n'))

    def test_unmapped_changed_line_finding_is_refused(self):
        issue = {"line": 1, "column": 1, "message": 'spacing'}
        self.assertFalse(STANDARDS.diagnostics_improve([issue, issue], [issue], 'a\n', 'b\n'))

    def test_function_contract_is_attached_to_named_definition(self):
        text = '/* Name: alpha\n * Description: Return a value.\n * Input Parameters: None.\n * Returned Value: One.\n */\nint alpha(void)\n{\n return 1;\n}\nint beta(void)\n{\n return 2;\n}\n'
        self.assertEqual([f['message'] for f in STANDARDS.function_findings(text)], ['beta'])

    def test_reviewed_contract_preserves_multiline_signature_and_is_idempotent(self):
        source = '/* Name: example */\n\nstatic int\nexample(int value)\n{\n  return value;\n}\n'
        contracts = {'example': {'description': 'Return the supplied value.',
                                'parameters': {'value': 'Value to return.'},
                                'returns': 'The supplied value.'}}
        candidate = STANDARDS.reviewed_contracts(source, contracts)
        self.assertEqual(STANDARDS.code_tokens(source), STANDARDS.code_tokens(candidate))
        self.assertEqual(STANDARDS.function_findings(candidate), [])
        self.assertEqual(STANDARDS.reviewed_contracts(candidate, contracts), candidate)

    def test_reviewed_contract_rejects_code_injection_and_unknown_names(self):
        source = 'int example(void)\n{\n  return 1;\n}\n'
        contract = {'description': 'Return one.', 'parameters': {}, 'returns': 'One.'}
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.reviewed_contracts(source, {'absent': contract})
        for value in ['*/ int injected;', '', None]:
            with self.subTest(value=value), self.assertRaises(STANDARDS.ToolError):
                STANDARDS.reviewed_contracts(source, {'example': {**contract, 'returns': value}})

    def test_reviewed_contract_rejects_invented_parameters(self):
        contract = {'description': 'Return the supplied value.',
                    'parameters': {'missing': 'Invented argument.'}, 'returns': 'The value.'}
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.reviewed_contracts('int example(int value)\n{\n  return value;\n}\n',
                                        {'example': contract})

    def test_conditional_signature_contract_covers_both_variants(self):
        source = '#ifdef WITH_HANDLE\nint example(int value, void *handle)\n#else\nint example(int value)\n#endif\n{\n  return value;\n}\n'
        contract = {'description': 'Return the supplied value.',
                    'parameters': {'value': 'Value to return.', 'handle': 'Optional build argument.'},
                    'returns': 'The supplied value.'}
        candidate = STANDARDS.reviewed_contracts(source, {'example': contract})
        self.assertEqual(STANDARDS.code_tokens(source), STANDARDS.code_tokens(candidate))
        self.assertEqual(STANDARDS.protected_content(source), STANDARDS.protected_content(candidate))
        self.assertEqual(STANDARDS.function_findings(candidate), [])
        self.assertEqual(STANDARDS.reviewed_contracts(candidate, {'example': contract}), candidate)

    def test_contract_stays_outside_continued_conditional(self):
        source = '#if defined(A) || \\\n    defined(B)\nint example(void)\n{\n  return 1;\n}\n#endif\n'
        contract = {'description': 'Return one.', 'parameters': {}, 'returns': 'One.'}
        candidate = STANDARDS.reviewed_contracts(source, {'example': contract})
        self.assertEqual(STANDARDS.protected_content(source), STANDARDS.protected_content(candidate))
        self.assertEqual(STANDARDS.reviewed_contracts(candidate, {'example': contract}), candidate)

    def test_mutually_exclusive_bodies_have_separate_contracts(self):
        source = '#ifdef VARIANT\nint example(void)\n{\n  return 1;\n}\n#else\nint example(void)\n{\n  return 2;\n}\n#endif\n'
        contract = {'description': 'Return the variant value.', 'parameters': {},
                    'returns': 'One or two, depending on the build variant.'}
        candidate = STANDARDS.reviewed_contracts(source, {'example': contract})
        self.assertEqual(STANDARDS.code_tokens(source), STANDARDS.code_tokens(candidate))
        self.assertEqual(candidate.count('Name: example'), 2)
        self.assertEqual(STANDARDS.reviewed_contracts(candidate, {'example': contract}), candidate)


class FileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='standards-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'source with spaces.c'
        self.path.write_bytes(b'int value;\n')

    def test_regular_path_with_spaces(self):
        self.assertEqual(STANDARDS.assert_regular(self.root, Path(self.path.name)), self.path)

    def test_path_traversal_and_absolute_paths_are_refused(self):
        for relative in [Path('../outside.c'), self.path]:
            with self.subTest(relative=relative), self.assertRaises(STANDARDS.ToolError):
                STANDARDS.assert_regular(self.root, relative)

    def test_option_like_components_are_refused(self):
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.assert_regular(self.root, Path('-source.c'))

    def test_file_and_directory_symlinks_are_refused(self):
        (self.root / 'link.c').symlink_to(self.path)
        (self.root / 'loop').symlink_to(self.root, target_is_directory=True)
        for relative in [Path('link.c'), Path('loop') / self.path.name]:
            with self.subTest(relative=relative), self.assertRaises(STANDARDS.ToolError):
                STANDARDS.assert_regular(self.root, relative)

    def test_replace_preserves_executable_mode(self):
        self.path.chmod(0o755)
        STANDARDS.atomic_replace(self.path, b'int value;\n', b'int value;\n\n')
        self.assertEqual(self.path.read_bytes(), b'int value;\n\n')
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o755)
        self.assertEqual(list(self.root.glob('.coding-standard-*')), [])

    def test_concurrent_content_change_is_refused(self):
        self.path.write_bytes(b'int changed;\n')
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.atomic_replace(self.path, b'int value;\n', b'int replacement;\n')
        self.assertEqual(self.path.read_bytes(), b'int changed;\n')

    def test_symlink_replacement_is_refused(self):
        self.path.unlink()
        target = self.root / 'target.c'
        target.write_bytes(b'int value;\n')
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            STANDARDS.atomic_replace(self.path, b'int value;\n', b'int replacement;\n')
        self.assertEqual(target.read_bytes(), b'int value;\n')

    def test_missing_tool_and_failed_process_are_errors(self):
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.run([str(self.root / 'missing-tool')])
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.run([sys.executable, '-c', 'raise SystemExit(3)'])

    def test_timeout_does_not_indicate_a_pass(self):
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.run([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.01)

    def test_report_symlink_swap_cannot_overwrite_source(self):
        output = self.root / 'report.json'
        output.write_text('{}\n')
        snapshot = STANDARDS.output_snapshot(output)
        output.unlink()
        output.symlink_to(self.path)
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.write_report(output, b'{"changed":true}\n', snapshot)
        self.assertEqual(self.path.read_bytes(), b'int value;\n')

    def test_new_report_refuses_a_concurrently_created_destination(self):
        output = self.root / 'report.json'
        snapshot = STANDARDS.output_snapshot(output)
        output.write_text('{"editor":true}\n')
        with self.assertRaises(OSError):
            STANDARDS.write_report(output, b'{}\n', snapshot)
        self.assertEqual(output.read_text(), '{"editor":true}\n')

    def test_report_parent_swap_during_open_is_refused(self):
        parent = self.root / 'reports'
        parent.mkdir()
        output = parent / 'report.json'
        output.write_bytes(b'{}\n')
        snapshot = STANDARDS.output_snapshot(output)
        original_open = os.open
        swapped = False
        def swapped_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if Path(path) == parent and flags & os.O_DIRECTORY and not swapped:
                swapped = True
                parent.rename(self.root / 'moved')
                parent.mkdir()
                output.write_bytes(b'{}\n')
            return original_open(path, flags, *args, **kwargs)
        with patch.object(STANDARDS.os, 'open', swapped_open):
            with self.assertRaises(STANDARDS.ToolError):
                STANDARDS.write_report(output, b'{"changed":true}\n', snapshot)
        self.assertEqual(output.read_bytes(), b'{}\n')
        self.assertEqual((self.root / 'moved/report.json').read_bytes(), b'{}\n')

    def test_full_subprocess_failure_output_is_retained(self):
        with self.assertRaises(STANDARDS.ToolError) as raised:
            STANDARDS.run([sys.executable, '-c',
                           'import sys; print("out" * 2000); print("err" * 2000, file=sys.stderr); raise SystemExit(3)'])
        log = Path(str(raised.exception).split('full tool log: ')[1])
        self.addCleanup(STANDARDS.shutil.rmtree, log)
        self.assertEqual((log / 'stdout').read_bytes(), b'out' * 2000 + b'\n')
        self.assertEqual((log / 'stderr').read_bytes(), b'err' * 2000 + b'\n')


class NativeAdapterTests(unittest.TestCase):

    def test_contract_schema_and_output_collision_are_controlled_errors(self):
        with tempfile.TemporaryDirectory(prefix='standards-contract-cli-') as directory:
            path = Path(directory) / 'contracts.json'
            path.write_text('[]\n')
            command = [sys.executable, str(ROOT / 'Tools/renesas-coding-standards.py'),
                       'fix', '--family', 'nuttx', '--path',
                       str(STANDARDS.NUTTX / 'arch/arm/src/rzv/rzv_adc.c'),
                       '--contracts', str(path)]
            for extra in ([], ['--output', str(path)]):
                result = subprocess.run(command + extra, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(path.read_text(), '[]\n')
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-native-test-')
        self.addCleanup(temporary.cleanup)
        self.checkers = STANDARDS.Checkers(ROOT, Path(temporary.name))

    def test_mirrored_header_path_must_be_exact(self):
        path = Path('arch/arm/src/rzv/example.h')
        header = '/****************************************************************************\n * arch/arm/src/rzv/example.h\n ****************************************************************************/\n'
        correct = self.checkers.nxstyle(header, path)
        wrong = self.checkers.nxstyle(header.replace('arch/arm/src/rzv/example.h', 'example.h'), path)
        self.assertFalse(any('Relative file path' in d['message'] for d in correct))
        self.assertTrue(any('Relative file path' in d['message'] for d in wrong))

    def test_real_astyle_preserves_tokens_for_spacing_and_is_idempotent(self):
        source = 'int value=1;\n'
        result = self.checkers.px4(source)
        self.assertEqual(STANDARDS.code_tokens(source), STANDARDS.code_tokens(result))
        self.assertEqual(self.checkers.px4(result), result)

    def test_real_astyle_structural_changes_are_detected(self):
        source = 'void example(void)\n{\nif(value) value++;\n}\n'
        result = self.checkers.px4(source)
        self.assertNotEqual(STANDARDS.code_tokens(source), STANDARDS.code_tokens(result))

    def test_owned_tree_inventory_has_no_duplicate_canonical_paths(self):
        policy = json.loads((ROOT / 'Tools/renesas-coding-standards.json').read_text())
        sources = STANDARDS.inventory(ROOT, policy)
        self.assertEqual(len(sources), len({s.path for s in sources}))
        links = [s for s in sources if s.classification == 'symlink']
        self.assertEqual(len(links), 2)
        self.assertFalse(any('/include/chip/' in str(s.path) for s in sources))
        for source in sources:
            if source.classification != 'symlink':
                self.assertEqual(source.classification, policy['files'][str(source.path)]['classification'])

    def test_invalid_selections_fail_before_formatting(self):
        for selection in ['src', 'boards/renesas/../other', '/tmp/outside',
                          'boards/renesas/evk-ra8p1',
                          'platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8',
                          'platforms/nuttx/NuttX/nuttx/arch/arm/include/rzv/rzv']:
            with self.subTest(selection=selection), self.assertRaises(STANDARDS.ToolError):
                STANDARDS.inventory(ROOT, {}, [selection])

    def test_unlisted_source_ownership_is_unknown_and_never_writable(self):
        sources = STANDARDS.inventory(ROOT, {}, ['boards/renesas/rdk-rzv2h/src/init.c'])
        self.assertEqual(sources[0].classification, 'unknown')
        pending = []
        result = STANDARDS.process(ROOT, sources[0], self.checkers, 'fix', pending)
        self.assertEqual(pending, [])
        self.assertIn('ownership', [f['rule'] for f in result['findings']])

    def test_generated_and_non_code_only_fix_selections_fail(self):
        policy = json.loads((ROOT / 'Tools/renesas-coding-standards.json').read_text())
        sources = STANDARDS.inventory(ROOT, policy)
        for classification in ['generated', 'non-code']:
            source = next(s for s in sources if s.classification == classification)
            result = subprocess.run([sys.executable, str(ROOT / 'Tools/renesas-coding-standards.py'),
                                     'fix', '--path', str(source.path)], capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 2, result.stderr)

    def test_untracked_ownership_policy_cannot_be_report_output(self):
        policy = ROOT / 'Tools/renesas-coding-standards.json'
        original = policy.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'Tools/renesas-coding-standards.py'),
                                 'report', '--output', str(policy)], capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(policy.read_bytes(), original)

    def test_generated_source_is_reported_without_writing(self):
        policy = json.loads((ROOT / 'Tools/renesas-coding-standards.json').read_text())
        source = next(s for s in STANDARDS.inventory(ROOT, policy)
                      if s.classification == 'generated' and s.path.suffix == '.h')
        path = ROOT / source.path
        original = path.read_bytes()
        pending = []
        result = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        self.assertTrue(result['findings'])
        self.assertEqual(pending, [])
        self.assertFalse(result['changed'])
        self.assertEqual(path.read_bytes(), original)

    def test_incomplete_native_check_cannot_queue_a_fix(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-incomplete-',
                    dir=ROOT / STANDARDS.NUTTX / 'arch/arm/src/rzv')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'example.c'
        relative = path.relative_to(ROOT / STANDARDS.NUTTX)
        path.write_text('/****************************************************************************\n * ' + str(relative) +
                        '\n ****************************************************************************/\n\nint example(void)\n{\n  return 0;\n}\n')
        source = STANDARDS.Source(path.relative_to(ROOT), 'nuttx', '100644', 'handwritten', {})
        pending = []
        record = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        self.assertTrue(record['checker_incomplete'])
        self.assertEqual(pending, [])

    def test_report_and_check_do_not_change_source_or_indexes(self):
        policy = json.loads((ROOT / 'Tools/renesas-coding-standards.json').read_text())
        paths = [ROOT / s.path for s in STANDARDS.inventory(ROOT, policy)
                 if s.classification != 'symlink']
        for repo in [ROOT, ROOT / STANDARDS.NUTTX]:
            _, index, _ = STANDARDS.run(['git', 'rev-parse', '--git-path', 'index'], cwd=repo)
            paths.append((repo / index.strip()).resolve())
        before = [(p, p.read_bytes(), p.stat().st_mode) for p in paths]
        selection = 'boards/renesas/rdk-rzv2h/src/timer_config.cpp'
        outputs = []
        for mode in ['report', 'check', 'report']:
            destination = self.checkers.cache / (mode + '.json')
            result = subprocess.run([sys.executable, str(ROOT / 'Tools/renesas-coding-standards.py'),
                                     mode, '--path', selection, '--output', str(destination)],
                                    capture_output=True, timeout=120)
            self.assertIn(result.returncode, (0, 1), result.stderr)
            if mode == 'report':
                outputs.append(destination.read_bytes())
        self.assertEqual(outputs[0], outputs[1])
        for path, content, mode in before:
            self.assertEqual(path.read_bytes(), content, str(path))
            self.assertEqual(path.stat().st_mode, mode, str(path))

    def test_git_status_cannot_refresh_a_writable_index(self):
        with tempfile.TemporaryDirectory(prefix='standards-index-') as directory:
            repository = Path(directory)
            STANDARDS.run(['git', 'init', '-q'], cwd=repository)
            source = repository / 'source.c'
            source.write_text('int value;\n')
            STANDARDS.run(['git', 'add', 'source.c'], cwd=repository)
            STANDARDS.run(['git', '-c', 'user.name=Fixture',
                           '-c', 'user.email=fixture@example.invalid',
                           'commit', '-qm', 'fixture'], cwd=repository)
            metadata = source.stat()
            os.utime(source, ns=(metadata.st_atime_ns,
                                 metadata.st_mtime_ns + 2_000_000_000))
            index = repository / '.git/index'
            original = index.read_bytes()
            with patch.dict(os.environ, {'GIT_OPTIONAL_LOCKS': '1'}):
                _, output, _ = STANDARDS.run(
                    ['git', 'status', '--porcelain'], cwd=repository)
            self.assertEqual(output, '')
            self.assertEqual(index.read_bytes(), original)

    def test_batch_refuses_concurrent_edits_before_any_write(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-batch-', dir=ROOT / 'test')
        self.addCleanup(temporary.cleanup)
        paths = [Path(temporary.name) / name for name in ['first.c', 'second.c']]
        for path in paths:
            path.write_bytes(b'int value;\n')
        pending = [(p, b'int value;\n', b'int value;\n\n', {}) for p in paths]
        paths[1].write_bytes(b'int changed;\n')
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.apply_batch(pending, self.checkers)
        self.assertEqual(paths[0].read_bytes(), b'int value;\n')

    def test_mid_batch_failure_retains_recovery_bytes(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-batch-', dir=ROOT / 'test')
        self.addCleanup(temporary.cleanup)
        paths = [Path(temporary.name) / name for name in ['first.c', 'second.c']]
        for path in paths:
            path.write_bytes(b'int value;\n')
        pending = [(p, b'int value;\n', b'int value;\n\n', {}) for p in paths]
        original_replace = STANDARDS.atomic_replace
        def interrupted_replace(path, original, candidate, **kwargs):
            if path == paths[1]:
                raise OSError('injected second-file I/O failure')
            original_replace(path, original, candidate, **kwargs)
        with patch.object(STANDARDS, 'atomic_replace', interrupted_replace):
            with self.assertRaises(STANDARDS.ToolError) as raised:
                STANDARDS.apply_batch(pending, self.checkers)
        journal = Path(str(raised.exception).split('recovery files: ')[1])
        self.addCleanup(STANDARDS.shutil.rmtree, journal.parent)
        manifest = json.loads(journal.read_text())
        self.assertEqual(manifest['state'], 'interrupted')
        self.assertEqual([f['state'] for f in manifest['files']], ['replaced', 'uncertain'])
        self.assertEqual(manifest['files'][1]['observed_sha256'], STANDARDS.digest(b'int value;\n'))
        self.assertEqual(paths[0].read_bytes(), b'int value;\n\n')
        self.assertEqual(paths[1].read_bytes(), b'int value;\n')
        self.assertEqual((journal.parent / '0.original').read_bytes(), b'int value;\n')

    def test_source_scope_cannot_be_used_as_report_destination(self):
        result = subprocess.run([sys.executable, str(ROOT / 'Tools/renesas-coding-standards.py'),
                                 'report', '--output', str(ROOT / 'boards/renesas/report.json')],
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((ROOT / 'boards/renesas/report.json').exists())

    def test_real_px4_fix_is_idempotent_and_records_recovery(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-fix-', dir=ROOT / 'test')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'example.cpp'
        path.write_text('int value=1;\n')
        source = STANDARDS.Source(path.relative_to(ROOT), 'px4', '100644', 'handwritten', {})
        pending = []
        first = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        journal = STANDARDS.apply_batch(pending, self.checkers)
        self.addCleanup(STANDARDS.shutil.rmtree, Path(journal).parent)
        self.assertTrue(first['changed'])
        self.assertEqual(json.loads(Path(journal).read_text())['state'], 'completed')
        before = path.read_bytes()
        pending = []
        second = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        self.assertEqual(pending, [])
        self.assertEqual(second['findings'], [])
        self.assertIsNone(STANDARDS.apply_batch(pending, self.checkers))
        self.assertEqual(path.read_bytes(), before)

    def test_real_nuttx_fix_reduces_diagnostics_and_is_idempotent(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-fix-',
                    dir=ROOT / STANDARDS.NUTTX / 'arch/arm/src/rzv')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'example.h'
        relative = path.relative_to(ROOT / STANDARDS.NUTTX)
        path.write_text('/****************************************************************************\n * ' + str(relative) +
                        '\n ****************************************************************************/\n\nint value;  \n')
        source = STANDARDS.Source(path.relative_to(ROOT), 'nuttx', '100644', 'handwritten', {})
        pending = []
        first = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        self.assertEqual(first['proposed_diagnostic_count'], 0)
        journal = STANDARDS.apply_batch(pending, self.checkers)
        self.addCleanup(STANDARDS.shutil.rmtree, Path(journal).parent)
        self.assertTrue(first['changed'])
        before = path.read_bytes()
        pending = []
        second = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending)
        self.assertEqual(second['findings'], [])
        self.assertEqual(pending, [])
        self.assertEqual(path.read_bytes(), before)

    def test_reviewed_contract_fix_requires_original_hash_and_native_coverage(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-contract-',
                    dir=ROOT / STANDARDS.NUTTX / 'arch/arm/src/rzv')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'example.c'
        relative = path.relative_to(ROOT / STANDARDS.NUTTX)
        path.write_text('/****************************************************************************\n * ' + str(relative) +
                        '\n ****************************************************************************/\n\n' +
                        '/****************************************************************************\n * Public Functions\n' +
                        ' ****************************************************************************/\n\n' +
                        'int example(void)\n{\n  return 1;\n}\n')
        source = STANDARDS.Source(path.relative_to(ROOT), 'nuttx', '100644', 'handwritten', {})
        entry = {'sha256': 'stale', 'functions': {'example': {
                 'description': 'Return one.', 'parameters': {}, 'returns': 'One.'}}}
        contracts = {str(source.path): entry}
        with self.assertRaises(STANDARDS.ToolError):
            STANDARDS.process(ROOT, source, self.checkers, 'fix', [], contracts)
        entry['sha256'] = STANDARDS.digest(path.read_bytes())
        pending = []
        record = STANDARDS.process(ROOT, source, self.checkers, 'fix', pending, contracts)
        self.assertEqual(record['proposed_diagnostic_count'], 0)
        self.assertEqual(len(pending), 1)
        journal = STANDARDS.apply_batch(pending, self.checkers)
        self.addCleanup(STANDARDS.shutil.rmtree, Path(journal).parent)
        self.assertEqual(STANDARDS.function_findings(path.read_text()), [])

    def test_post_replacement_failure_records_actual_candidate_hash(self):
        temporary = tempfile.TemporaryDirectory(prefix='standards-batch-', dir=ROOT / 'test')
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'example.c'
        path.write_bytes(b'int value;\n')
        pending = [(path, b'int value;\n', b'int value;\n\n', {})]
        original_replace = STANDARDS.atomic_replace
        def failed_after_replace(*args, **kwargs):
            original_replace(*args, **kwargs)
            raise OSError('injected post-replacement failure')
        with patch.object(STANDARDS, 'atomic_replace', failed_after_replace):
            with self.assertRaises(STANDARDS.ToolError) as raised:
                STANDARDS.apply_batch(pending, self.checkers)
        journal = Path(str(raised.exception).split('recovery files: ')[1])
        self.addCleanup(STANDARDS.shutil.rmtree, journal.parent)
        manifest = json.loads(journal.read_text())
        self.assertEqual(manifest['files'][0]['state'], 'uncertain')
        self.assertEqual(manifest['files'][0]['observed_sha256'], STANDARDS.digest(path.read_bytes()))
        self.assertEqual(path.read_bytes(), b'int value;\n\n')


if __name__ == '__main__':
    unittest.main()
