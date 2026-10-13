#!/usr/bin/env python3
"""Read CMSIS layouts using C offsetof, including nested arrays and access views."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def structures(text):
    result = {}
    for match in re.finditer(r"typedef\s+struct\s*\{", text):
        start = match.end()
        depth = 1
        end = start
        while depth:
            depth += (text[end] == "{") - (text[end] == "}")
            end += 1
        name = re.match(r"\s*(R_\w+_Type)\s*;", text[end:])
        if name:
            result[name.group(1)] = text[start:end - 1]
    return result


def register_layout(header, type_name, compiler="cc"):
    header = Path(header).resolve()
    types = structures(header.read_text())
    members = []

    def visit(name, prefix=""):
        body = types[name]
        views = []
        for block in re.finditer(r"(?:struct|union)\s*\{", body):
            depth, end = 1, block.end()
            while depth:
                depth += (body[end] == "{") - (body[end] == "}")
                end += 1
            view = re.match(r"\s*(\w+)\s*;", body[end:])
            if view:
                views.append((block.end(), end - 1, view.group(1)))
        for match in re.finditer(
                r"(__IM|__OM|__IOM)\s+(uint\d+_t|R_\w+_Type)\s+"
                r"(\w+)(?:\[(\d+)\])?\s*;", body):
            access, member_type, member, count = match.groups()
            if member.startswith("RESERVED"):
                continue
            for index in range(int(count) if count else 1):
                nested = "".join(view + "." for start, end, view in views
                                 if start <= match.start() < end)
                path = prefix + nested + member + (f"[{index}]" if count else "")
                if member_type in types:
                    visit(member_type, path + ".")
                else:
                    members.append((path, access))

    visit(type_name)
    if not members:
        raise ValueError(f"no registers in {type_name}")
    code = ('#include <stdint.h>\n#include <stddef.h>\n#include <stdio.h>\n'
            '#define __IM volatile const\n#define __OM volatile\n'
            f'#define __IOM volatile\n#include "{header}"\nint main(void) {{\n')
    for path, access in members:
        code += (f'printf("{path} %zu %zu {access}\\n", '
                 f'offsetof({type_name}, {path}), '
                 f'sizeof((({type_name} *)0)->{path}));\n')
    code += "return 0; }\n"
    with tempfile.TemporaryDirectory(prefix="rzv2h-cmsis-layout-") as d:
        tmp = Path(d)
        (tmp / "layout.c").write_text(code)
        subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(tmp / "layout.c"), "-o", str(tmp / "layout")], check=True)
        output = subprocess.check_output([str(tmp / "layout")], text=True)
    return [{"member": path, "offset": int(offset), "width": int(width),
             "access": access} for path, offset, width, access in
            (line.split() for line in output.splitlines())]


def offset_definitions(rows, prefix):
    lines = []
    for row in rows:
        name = re.sub(r"[.\[\]]", "_", row["member"]).strip("_").replace("__", "_").upper()
        lines.append(f'#define {prefix}_{name}_OFFSET 0x{row["offset"]:04x}')
        lines.append(f'#define {prefix}_{name}_WIDTH {row["width"]}')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header", type=Path)
    parser.add_argument("type_name")
    parser.add_argument("--compiler", default="cc")
    parser.add_argument("--offset-prefix", help="emit offset and width macros instead of JSON")
    args = parser.parse_args()
    rows = register_layout(args.header, args.type_name, args.compiler)
    if args.offset_prefix:
        print(offset_definitions(rows, args.offset_prefix), end="")
    else:
        print(json.dumps(rows, indent=2))
