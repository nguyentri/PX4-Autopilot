#!/usr/bin/env python3
"""Unit tests for the RZ/V2H IPC ELF address allowlist checker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py"
SPEC = importlib.util.spec_from_file_location("rzv2h_ipc_allowlist", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProgramHeaderTests(unittest.TestCase):
    def test_parses_load_segment(self) -> None:
        text = "  LOAD 0x001000 0x40800000 0x40800000 0x02000 0x03000 R E 0x1000"
        segments = MODULE.parse_program_headers(text)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].paddr, 0x40800000)
        self.assertEqual(segments[0].memsz, 0x3000)

    def test_accepts_bss_only_segment_for_range_validation(self) -> None:
        text = "  LOAD 0x0 0x40800000 0x40800000 0x0 0x1000 RW 0x1000"
        segments = MODULE.parse_program_headers(text)
        self.assertEqual(segments[0].filesz, 0)
        self.assertEqual(segments[0].memsz, 0x1000)

    def test_ignores_empty_load_header(self) -> None:
        text = """  LOAD 0x0 0x0 0x0 0x0 0x0 R 0x1000
  LOAD 0x1000 0x40800000 0x40800000 0x100 0x100 R E 0x1000"""
        segments = MODULE.parse_program_headers(text)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].paddr, 0x40800000)


class RangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = [MODULE.AllowedRange("ram", 0x1000, 0x2000)]

    def test_accepts_wholly_contained_memory_span(self) -> None:
        segment = MODULE.Segment(0, 0x1000, 0x100, 0x800)
        self.assertEqual(MODULE.containing_range(segment, self.allowed).name, "ram")

    def test_rejects_memsz_crossing_boundary(self) -> None:
        segment = MODULE.Segment(0, 0x1800, 0x100, 0x801)
        self.assertIsNone(MODULE.containing_range(segment, self.allowed))

    def test_rejects_bss_only_span_crossing_boundary(self) -> None:
        segment = MODULE.Segment(0, 0x1800, 0, 0x801)
        self.assertIsNone(MODULE.containing_range(segment, self.allowed))

    def test_rejects_overflow(self) -> None:
        segment = MODULE.Segment(0, (1 << 64) - 8, 4, 16)
        with self.assertRaises(ValueError):
            MODULE.containing_range(segment, self.allowed)


class CliTests(unittest.TestCase):
    def run_cli(
        self,
        *,
        headers: str,
        device: str = "R9A09G057H44_M33_0",
        manifest: Path | None = None,
        expect_sha256: str | None = None,
        allow_unverified: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            elf = root / "sample.elf"
            elf.write_bytes(b"sample-elf")

            readelf = root / "fake-readelf.py"
            readelf.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"print({headers!r})\n",
                encoding="utf-8",
            )
            readelf.chmod(0o755)

            command = [
                sys.executable,
                str(SCRIPT),
                "--elf",
                str(elf),
                "--device",
                device,
                "--readelf",
                str(readelf),
            ]

            if manifest is not None:
                command.extend(("--manifest", str(manifest)))

            if expect_sha256 is not None:
                command.extend(("--expect-sha256", expect_sha256))

            if allow_unverified:
                command.append("--allow-unverified")

            environment = dict(os.environ)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

    def write_manifest(self, root: Path, status: str = "ratified") -> Path:
        manifest = root / "allowlists.json"
        manifest.write_text(
            json.dumps(
                {
                    "devices": {
                        "R9A09G057H44_M33_0": {
                            "status": status,
                            "ranges": [
                                {
                                    "name": "secure-sram-code",
                                    "start": "0x08002800",
                                    "end": "0x080fc000",
                                }
                            ],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return manifest

    def test_default_manifest_without_expected_hash_is_inspection_only(self) -> None:
        result = self.run_cli(
            headers="  LOAD 0x000800 0x08002800 0x08002800 0x20 0x20 R E 0x1000"
        )
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("RESULT=INSPECTION_ONLY", result.stdout)

    def test_default_manifest_with_expected_hash_is_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            elf = Path(temp_dir) / "sample.elf"
            elf.write_bytes(b"sample-elf")
            digest = hashlib.sha256(elf.read_bytes()).hexdigest()

            readelf = Path(temp_dir) / "fake-readelf.py"
            readelf.write_text(
                "#!/usr/bin/env python3\n"
                "print('  LOAD 0x000800 0x08002800 0x08002800 0x20 0x20 R E 0x1000')\n",
                encoding="utf-8",
            )
            readelf.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--elf",
                    str(elf),
                    "--device",
                    "R9A09G057H44_M33_0",
                    "--readelf",
                    str(readelf),
                    "--expect-sha256",
                    digest,
                ],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("RESULT=AUTHORIZED_ADDRESS_CONTRACT", result.stdout)

    def test_custom_manifest_is_inspection_only_even_with_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = self.write_manifest(root)
            elf = root / "sample.elf"
            elf.write_bytes(b"sample-elf")
            digest = hashlib.sha256(elf.read_bytes()).hexdigest()

            readelf = root / "fake-readelf.py"
            readelf.write_text(
                "#!/usr/bin/env python3\n"
                "print('  LOAD 0x000800 0x08002800 0x08002800 0x20 0x20 R E 0x1000')\n",
                encoding="utf-8",
            )
            readelf.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--elf",
                    str(elf),
                    "--device",
                    "R9A09G057H44_M33_0",
                    "--manifest",
                    str(manifest),
                    "--readelf",
                    str(readelf),
                    "--expect-sha256",
                    digest,
                ],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("RESULT=INSPECTION_ONLY", result.stdout)

    def test_unverified_manifest_requires_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.write_manifest(Path(temp_dir), status="draft")
            result = self.run_cli(
                headers="  LOAD 0x000800 0x08002800 0x08002800 0x20 0x20 R E 0x1000",
                manifest=manifest,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("RESULT=DENY", result.stderr)

    def test_unverified_manifest_with_flag_is_inspection_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = self.write_manifest(Path(temp_dir), status="draft")
            result = self.run_cli(
                headers="  LOAD 0x000800 0x08002800 0x08002800 0x20 0x20 R E 0x1000",
                manifest=manifest,
                allow_unverified=True,
            )

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertIn("RESULT=INSPECTION_ONLY", result.stdout)


if __name__ == "__main__":
    unittest.main()
