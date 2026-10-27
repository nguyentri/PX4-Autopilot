#!/usr/bin/env python3
"""Exercise paired IPC build/load dispatch without connecting to hardware."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
IPC = ROOT / "platforms/nuttx/Debug/rzv2h-ipc"
CONFIGS = ("ipcc-raw-cr8_0-sci4", "ipcc-raw-cr8_1")


def executable(path, body):
    path.write_text(body)
    path.chmod(0o755)


class BuildLoadModes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ipc modes ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ipc = self.root / "platforms/nuttx/Debug/rzv2h-ipc"
        self.ipc.mkdir(parents=True)
        self.nuttx = self.root / "platforms/nuttx/NuttX/nuttx"
        self.nuttx.mkdir(parents=True)
        self.wrapper = self.ipc / "rzv2h-ipc-demo-build-and-load.sh"
        for name in (self.wrapper.name, "rzv2h-ipc-demo-load-both.sh"):
            shutil.copy2(IPC / name, self.ipc / name)
        self.events = self.root / "events.jsonl"
        self.process_environment = dict(os.environ, JLINK_SERIAL="fixture", EVENTS=str(self.events))
        for key in ("OUT_DIR", "CR8_0_CONFIG", "CR8_1_CONFIG", "LOAD_CODE"):
            self.process_environment.pop(key, None)
        record = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["EVENTS"], "a") as log:
    log.write(json.dumps({"tool": TOOL, "args": args}) + "\\n")
'''
        executable(self.root / "platforms/nuttx/NuttX/build.sh",
                   record.replace("TOOL", '"build"') +
                   'pathlib.Path(__file__).with_name("nuttx").joinpath("nuttx").write_text(args[0])\n')
        lock = self.root / "Tools/firmware_workspace/build_lock.sh"
        lock.parent.mkdir(parents=True)
        executable(lock, record.replace("TOOL", '"lock"'))
        executable(self.ipc / "rzv2h-ipc-demo-load-both-auto.sh",
                   record.replace("TOOL", '"load"') + '''
with open(os.environ["EVENTS"], "a") as log:
    log.write(json.dumps({"images": [pathlib.Path(p).read_text() for p in args]}) + "\\n")
sys.exit(int(os.environ.get("LOAD_CODE", "0")))
''')

    def run_wrapper(self, *args):
        return subprocess.run(["sh", str(self.wrapper), *args], cwd=self.root,
                              env=self.process_environment, text=True, capture_output=True, timeout=10)

    def recorded(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def save_images(self, directory=None, configs=CONFIGS):
        directory = directory or self.nuttx
        directory.mkdir(parents=True, exist_ok=True)
        paths = [directory / f"nuttx-{config}.elf" for config in configs]
        for path, config in zip(paths, configs):
            path.write_text(config)
        return paths

    def test_load_only_preserves_exact_saved_pair_without_building(self):
        paths = self.save_images()
        (self.nuttx.parent / "build.sh").unlink()
        (self.nuttx / "nuttx").write_text("unrelated shared output")
        result = self.run_wrapper("--load-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), [
            {"tool": "lock", "args": ["--check"]},
            {"tool": "load", "args": list(map(str, paths))}, {"images": list(CONFIGS)}])
        self.assertIn("consoles were not started", result.stdout)

    def test_load_only_honors_saved_directory_and_config_overrides(self):
        configs = ("ipcc-raw-cr8_0", "ipcc-raw-cr8_1")
        paths = self.save_images(self.root / "saved images", configs)
        self.process_environment.update(OUT_DIR=str(paths[0].parent),
                                        CR8_0_CONFIG="rdk-rzv2h:" + configs[0])
        result = self.run_wrapper("--load-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded()[1]["args"], list(map(str, paths)))

    def test_build_only_preserves_each_image_and_never_loads(self):
        self.process_environment.pop("JLINK_SERIAL")
        result = self.run_wrapper("--build-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row["tool"] for row in self.recorded()], ["lock", "build", "build"])
        for config in CONFIGS:
            self.assertEqual((self.nuttx / f"nuttx-{config}.elf").read_text(), config)

    def test_default_still_builds_then_loads_preserved_images(self):
        result = self.run_wrapper("-j2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row["tool"] for row in self.recorded() if "tool" in row],
                         ["lock", "build", "build", "load"])
        self.assertEqual(self.recorded()[-1], {"images": list(CONFIGS)})

    def test_load_only_rejects_missing_inputs_before_invoking_loader(self):
        for missing in ("serial", *CONFIGS):
            with self.subTest(missing=missing):
                paths = self.save_images()
                self.process_environment["JLINK_SERIAL"] = "fixture"
                if missing == "serial":
                    self.process_environment.pop("JLINK_SERIAL")
                else:
                    paths[CONFIGS.index(missing)].unlink()
                result = self.run_wrapper("--load-only")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(all(row["tool"] == "lock" for row in self.recorded()))

    def test_load_failure_or_cancellation_is_not_reported_as_success(self):
        self.save_images()
        for code in (1, 3, 130):
            with self.subTest(code=code):
                self.process_environment["LOAD_CODE"] = str(code)
                result = self.run_wrapper("--load-only")
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn("Both images loaded and verified", result.stdout)

    def test_invalid_modes_are_host_only_usage_errors(self):
        for args in (("--load-only", "--build-only"), ("--bad-mode",)):
            with self.subTest(args=args):
                result = self.run_wrapper(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(self.recorded(), [])

    def test_help_needs_no_submodule_tools_or_probe(self):
        shutil.rmtree(self.nuttx.parent)
        self.process_environment.pop("JLINK_SERIAL")
        result = self.run_wrapper("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--load-only", result.stdout)
        self.assertEqual(self.recorded(), [])


if __name__ == "__main__":
    unittest.main()
