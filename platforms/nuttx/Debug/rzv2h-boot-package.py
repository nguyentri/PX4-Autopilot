#!/usr/bin/env python3
"""Validate/rebase native CR8 split images; emit host candidates, never deploy."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

LIMIT = 1 << 32
HEADER_SIZE = 128
MAGIC = 0x1234FEDC
SIGNATURE = 0x562F5A52


def integer(value):
    return int(value, 0) if isinstance(value, str) else value


def bounded(start, size):
    if not isinstance(start, int) or not isinstance(size, int):
        raise ValueError("addresses and sizes must be integers")
    if start < 0 or start >= LIMIT or size < 0 or size > LIMIT - start:
        raise ValueError("address range outside ARM32")
    return start, start + size


def contained(start, size, regions):
    left, right = bounded(start, size)
    return any(left >= base and right <= end for base, end in regions)


def elf_loads(data):
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("only little-endian ELF32 is supported")
    header = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, version, entry, offset = header[:5]
    if kind != 2 or machine != 40 or version != 1 or header[7] != 52 or header[8] != 32:
        raise ValueError("expected executable ARM ELF32 program headers")
    count = header[9]
    if not count or offset < 52 or count * 32 > len(data) - offset:
        raise ValueError("truncated ELF program headers")
    loads = []
    for index in range(count):
        kind, file_offset, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from("<8I", data, offset + index * 32)
        if kind != 1 or memsz == 0:
            continue
        bounded(vaddr, memsz)
        bounded(paddr, memsz)
        if filesz > memsz or file_offset > len(data) or filesz > len(data) - file_offset:
            raise ValueError("invalid ELF segment size")
        if align and (align & (align - 1) or vaddr % align != file_offset % align):
            raise ValueError("unsupported ELF alignment")
        if paddr != vaddr:
            raise ValueError("unsupported relocated ELF load segment")
        loads.append((vaddr, filesz, memsz, flags, data[file_offset:file_offset + filesz]))
    if not any(flags & 1 and address <= entry < address + size for address, size, _, flags, _ in loads):
        raise ValueError("entry point is outside executable initialized memory")
    for index, item in enumerate(loads):
        for other in loads[index + 1:]:
            if item[0] < other[0] + other[2] and other[0] < item[0] + item[2]:
                raise ValueError("overlapping ELF load segments")
    return entry, loads


def make_package(elf, image, layout):
    if layout.get("format") != "rzv2h-cr8-split-v1" or layout.get("core") != "cr8_0":
        raise ValueError("unsupported boot layout/core")
    if layout.get("deployment_enabled") is not False:
        raise ValueError("host candidates must keep deployment disabled")
    entry, loads = elf_loads(elf)
    if len(image) < HEADER_SIZE:
        raise ValueError("truncated native image header")
    words = list(struct.unpack_from("<32I", image))
    if words[19] != MAGIC or words[20] != SIGNATURE or any(words[21:]):
        raise ValueError("unsupported native header signature/padding")
    if words[18] != integer(layout["handoff_address"]) or words[18] % 4:
        raise ValueError("handoff address mismatch")
    source_base = words[0] - HEADER_SIZE
    bounded(source_base, len(image))
    target_base = integer(layout["image_base"])
    bounded(target_base, len(image))
    if target_base % 4:
        raise ValueError("image placement must be word aligned")
    alias = integer(layout["itcm_axi_alias"])
    bounded(alias, 0)
    regions = [bounded(integer(item["base"]), integer(item["size"])) for item in layout["load_regions"]]
    reserved = [bounded(integer(item["base"]), integer(item["size"])) for item in layout.get("reserved_regions", [])]
    if not contained(words[18], 4, reserved):
        raise ValueError("handoff word must be in an explicit reserved region")
    cursor = HEADER_SIZE
    blocks = []
    for index, name in enumerate(("itcm", "sram", "sdram")):
        pos = index * 6
        source, destination, size = words[pos:pos + 3]
        if words[pos + 3:pos + 6] != [value ^ 0xFFFFFFFF for value in (source, destination, size)]:
            raise ValueError("native header complement mismatch")
        if source != source_base + cursor or size > len(image) - cursor:
            raise ValueError("noncontiguous or truncated native load image")
        runtime = destination - alias if index == 0 else destination
        bounded(destination, size)
        if size and any(target_base < start + size and start < target_base + len(image)
                        for start in (runtime, destination)):
            raise ValueError("source image overlaps copy destination")
        if size and not contained(runtime, size, regions):
            raise ValueError("load block outside configured private RAM")
        if size and any(runtime < end and base < runtime + size for base, end in reserved):
            raise ValueError("load block overlaps reserved memory")
        for old in blocks:
            if size and old["size"] and runtime < old["runtime"] + old["size"] and old["runtime"] < runtime + size:
                raise ValueError("overlapping copy blocks")
        block = {"name": name, "source": target_base + cursor, "destination": destination,
                 "runtime": runtime, "size": size, "file_offset": cursor}
        blocks.append(block)
        words[pos:pos + 6] = [block["source"], destination, size,
                              block["source"] ^ 0xFFFFFFFF, destination ^ 0xFFFFFFFF, size ^ 0xFFFFFFFF]
        cursor += size
    if cursor != len(image):
        raise ValueError("native image has undeclared trailing bytes")
    header_address = integer(layout["header_runtime"])
    header_data = image[:HEADER_SIZE]
    header_seen = False
    for address, size, memsz, flags, payload in loads:
        if not contained(address, memsz, regions):
            raise ValueError("ELF memory outside configured private RAM")
        if any(address < end and base < address + memsz for base, end in reserved):
            raise ValueError("ELF memory overlaps reservation")
        if not size:
            continue
        if address == header_address and size == HEADER_SIZE and payload == header_data:
            header_seen = True
            continue
        matches = [block for block in blocks if block["runtime"] <= address and address + size <= block["runtime"] + block["size"]]
        if len(matches) != 1:
            raise ValueError("initialized ELF segment not covered exactly once by loader")
        offset = matches[0]["file_offset"] + address - matches[0]["runtime"]
        if payload != image[offset:offset + size]:
            raise ValueError("loader bytes differ from initialized ELF contents")
    if not header_seen:
        raise ValueError("native ELF header missing or mismatched")
    candidate = struct.pack("<32I", *words) + image[HEADER_SIZE:]
    manifest = {"format": layout["format"], "core": layout["core"], "deployment_enabled": False,
                "image_base": target_base, "entry": entry, "handoff_address": words[18],
                "handoff_magic": MAGIC, "blocks": blocks,
                "zero_initialization": "native startup owns BSS; retained noinit is not zeroed by this package",
                "loader_prerequisites": "TCM/DDR/clocks, MPU/cache maintenance and reset/handoff sequence require an approved loader",
                "elf_sha256": hashlib.sha256(elf).hexdigest(),
                "input_image_sha256": hashlib.sha256(image).hexdigest(),
                "layout_sha256": hashlib.sha256(json.dumps(layout, sort_keys=True).encode()).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate).hexdigest()}
    return candidate, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new directory; existing paths are rejected")
    args = parser.parse_args()
    try:
        candidate, manifest = make_package(args.elf.read_bytes(), args.image.read_bytes(), json.loads(args.layout.read_text()))
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "candidate.bin").write_bytes(candidate)
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    except (ValueError, KeyError, TypeError, OSError, struct.error) as error:
        parser.exit(1, "boot package rejected: " + str(error) + "\n")
    print("Validated host candidate; deployment remains disabled: " + str(args.output))


if __name__ == "__main__":
    main()
