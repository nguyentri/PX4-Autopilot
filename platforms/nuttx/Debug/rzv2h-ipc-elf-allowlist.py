#!/usr/bin/env python3
"""Fail-closed PT_LOAD checker and guarded RZ/V2H volatile ELF loader."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator


LOAD_RE = re.compile(
    r"^\s*LOAD\s+"
    r"(?P<offset>0x[0-9a-fA-F]+)\s+"
    r"(?P<vaddr>0x[0-9a-fA-F]+)\s+"
    r"(?P<paddr>0x[0-9a-fA-F]+)\s+"
    r"(?P<filesz>0x[0-9a-fA-F]+)\s+"
    r"(?P<memsz>0x[0-9a-fA-F]+)\b"
)
MAX_ADDRESS = (1 << 64) - 1
ACCEPTED_STATUSES = frozenset(("ratified", "target-proven"))


@dataclass(frozen=True)
class Segment:
    index: int
    paddr: int
    filesz: int
    memsz: int


@dataclass(frozen=True)
class AllowedRange:
    name: str
    start: int
    end: int


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"address is not an integer/string: {value!r}")
    return int(value, 0)


def checked_end(start: int, size: int) -> int:
    if start < 0 or size <= 0 or start > MAX_ADDRESS:
        raise ValueError(f"invalid span start={start:#x} size={size:#x}")
    end = start + size
    if end > MAX_ADDRESS + 1 or end <= start:
        raise ValueError(f"overflowed span start={start:#x} size={size:#x}")
    return end


def parse_program_headers(text: str) -> list[Segment]:
    segments: list[Segment] = []
    for line in text.splitlines():
        match = LOAD_RE.match(line)
        if match is None:
            continue
        filesz = int(match.group("filesz"), 16)
        memsz = int(match.group("memsz"), 16)
        # GNU ld can emit an empty LOAD header for an empty output region.
        # It has no destination span and GDB has no bytes to transfer.
        if filesz == 0 and memsz == 0:
            continue

        if memsz == 0 or filesz > memsz:
            raise ValueError(
                f"unexpected PT_LOAD sizes filesz={filesz:#x} memsz={memsz:#x}"
            )
        segments.append(
            Segment(
                index=len(segments),
                paddr=int(match.group("paddr"), 16),
                filesz=filesz,
                memsz=memsz,
            )
        )
    if not segments:
        raise ValueError("ELF contains no parseable PT_LOAD program headers")
    return segments


def load_device_manifest(path: Path, device: str) -> tuple[str, list[AllowedRange]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    device_data = raw.get("devices", {}).get(device)
    if not isinstance(device_data, dict):
        raise ValueError(f"device {device!r} is absent from {path}")

    status = device_data.get("status")
    if not isinstance(status, str):
        raise ValueError(f"device {device!r} has no status")

    ranges: list[AllowedRange] = []
    for item in device_data.get("ranges", []):
        start = parse_int(item.get("start"))
        end = parse_int(item.get("end"))
        name = item.get("name")
        if not isinstance(name, str) or start < 0 or end <= start:
            raise ValueError(f"invalid allowlist range: {item!r}")
        ranges.append(AllowedRange(name=name, start=start, end=end))
    if not ranges:
        raise ValueError(f"device {device!r} has no allowed RAM ranges")
    return status, ranges


def containing_range(
    segment: Segment, allowed: list[AllowedRange]
) -> AllowedRange | None:
    file_end = (
        segment.paddr
        if segment.filesz == 0
        else checked_end(segment.paddr, segment.filesz)
    )
    memory_end = checked_end(segment.paddr, segment.memsz)
    for candidate in allowed:
        if segment.paddr >= candidate.start and memory_end <= candidate.end:
            if file_end <= candidate.end:
                return candidate
    return None


@contextmanager
def snapshot_elf(path: Path) -> Iterator[tuple[BinaryIO, str]]:
    """Copy one opened ELF into a private inode used for all validation."""
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="rzv2h-elf-") as temp_dir:
        snapshot_path = Path(temp_dir) / "snapshot.elf"
        with path.open("rb") as source, snapshot_path.open("xb") as destination:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                destination.write(chunk)
        snapshot_path.chmod(0o400)
        with snapshot_path.open("rb") as snapshot:
            snapshot_path.unlink()
            yield snapshot, digest.hexdigest()


def snapshot_fd_path(elf: BinaryIO) -> Path:
    descriptor = elf.fileno()
    proc_path = Path("/proc") / str(os.getpid()) / "fd" / str(descriptor)
    fd_path = proc_path if proc_path.exists() else Path("/dev/fd") / str(descriptor)
    if not fd_path.exists():
        raise RuntimeError("host has no file-descriptor path for ELF snapshot")
    return fd_path


def readelf_headers(elf: BinaryIO, readelf: str) -> str:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    descriptor = elf.fileno()
    fd_path = snapshot_fd_path(elf)
    result = subprocess.run(
        (readelf, "-W", "-l", str(fd_path)),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        pass_fds=(descriptor,),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "readelf failed")
    return result.stdout


def run_loader(
    elf: BinaryIO, loader: str, loader_args: list[str]
) -> subprocess.CompletedProcess[bytes]:
    """Run a loader against the retained snapshot without shell expansion."""
    if loader_args.count("{elf}") != 1:
        raise ValueError("loader arguments must contain exactly one {elf} token")

    descriptor = elf.fileno()
    fd_path = snapshot_fd_path(elf)

    command = [loader]
    command.extend(str(fd_path) if item == "{elf}" else item for item in loader_args)
    return subprocess.run(command, check=False, pass_fds=(descriptor,))


def build_parser() -> argparse.ArgumentParser:
    default_manifest = Path(__file__).with_name("rzv2h-ipc-elf-allowlists.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", required=True, type=Path)
    parser.add_argument("--device", required=True)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument("--readelf", default="arm-none-eabi-readelf")
    parser.add_argument("--expect-sha256")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="host inspection only; output remains NOT AUTHORIZED FOR LOAD",
    )
    parser.add_argument(
        "--loader",
        help="executable for guarded load; requires one literal {elf} loader argument",
    )
    parser.add_argument(
        "--loader-arg",
        action="append",
        default=[],
        help="one loader argv item; repeat and use exactly one literal {elf}",
    )
    parser.add_argument(
        "--authorize-load",
        action="store_true",
        help="explicitly authorize invoking --loader after every gate passes",
    )
    return parser


def authorization_mode(
    manifest: Path, canonical_manifest: Path, status: str, expected_sha256: str | None
) -> tuple[bool, str | None]:
    if status not in ACCEPTED_STATUSES:
        return False, f"manifest status {status!r} is not load-authorized"

    if manifest != canonical_manifest:
        return False, "custom manifest is inspection-only"

    if not expected_sha256:
        return False, "expected SHA-256 is required for load authorization"

    return True, None


def main() -> int:
    args = build_parser().parse_args()
    try:
        elf = args.elf.resolve(strict=True)
        manifest = args.manifest.resolve(strict=True)
        canonical_manifest = Path(__file__).with_name(
            "rzv2h-ipc-elf-allowlists.json"
        ).resolve(strict=True)
        with snapshot_elf(elf) as (snapshot, digest):
            if args.expect_sha256 and digest.lower() != args.expect_sha256.lower():
                raise ValueError(
                    f"SHA-256 mismatch expected={args.expect_sha256} actual={digest}"
                )

            status, allowed = load_device_manifest(manifest, args.device)
            if status not in ACCEPTED_STATUSES and not args.allow_unverified:
                raise ValueError(
                    f"device status {status!r} is not authorized; target proof required"
                )

            segments = parse_program_headers(readelf_headers(snapshot, args.readelf))
            failures = 0
            print(f"ELF={elf}")
            print(f"SHA256={digest}")
            print(f"DEVICE={args.device}")
            print(f"MANIFEST_STATUS={status}")
            print(f"MANIFEST={manifest}")
            print("IDX PADDR FILESZ MEMSZ ALLOWED_RANGE VERDICT")
            for segment in segments:
                candidate = containing_range(segment, allowed)
                verdict = "PASS" if candidate else "DENY"
                range_name = candidate.name if candidate else "-"
                print(
                    f"{segment.index} {segment.paddr:#010x} {segment.filesz:#x} "
                    f"{segment.memsz:#x} {range_name} {verdict}"
                )
                failures += candidate is None

            if failures:
                raise ValueError(f"{failures} PT_LOAD segment(s) outside allowed RAM")

            authorized, reason = authorization_mode(
                manifest, canonical_manifest, status, args.expect_sha256
            )
            if not authorized:
                print(f"RESULT=INSPECTION_ONLY reason={reason}")
                return 2

            if args.loader is None:
                if args.loader_arg:
                    raise ValueError("--loader-arg requires --loader")
                if args.authorize_load:
                    raise ValueError("--authorize-load requires --loader")
                print("LOAD_EXECUTED=NO")
                print("RESULT=ADDRESS_CONTRACT_VERIFIED")
                return 0

            if not args.authorize_load:
                raise ValueError("--loader requires explicit --authorize-load")
            loader_result = run_loader(snapshot, args.loader, args.loader_arg)
            if loader_result.returncode != 0:
                print(
                    f"RESULT=LOAD_FAILED returncode={loader_result.returncode}",
                    file=sys.stderr,
                )
                return 1

            print("LOAD_EXECUTED=YES")
            print("RESULT=GUARDED_LOAD_COMPLETED")
            return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"RESULT=DENY reason={error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
