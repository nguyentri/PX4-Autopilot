#!/usr/bin/env python3
"""Check and safely normalize the tracked Renesas PX4 and NuttX sources."""

import argparse
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap


ROOT = Path(__file__).resolve().parents[1]
NUTTX = Path("platforms/nuttx/NuttX/nuttx")
NUTTX_ROOTS = tuple(Path(p) for p in (
    "arch/arm/src/rzv", "arch/arm/include/rzv", "boards/arm/rzv"))
PX4_ROOTS = tuple(Path("boards/renesas") / board for board in (
    "rdk-rzv2h", "rdk-rzv2h-io-cr8_1", "rdk-rzv2h-io-cm33"))
C_EXTENSIONS = {".c", ".h", ".cpp", ".hpp"}
TOKEN = re.compile(
    r'(?:u8|[LuU])?R"(?P<raw_delimiter>[^\s()\\]{0,16})\([\s\S]*?\)(?P=raw_delimiter)"'
    r'|/\*[\s\S]*?\*/|//(?:\\\r?\n|[^\n])*|(?:u8|[LuU])?"(?:\\(?:\r?\n|[\s\S])|[^"\\\r\n])*"'
    r"|(?:[LuU])?'(?:\\(?:\r?\n|[\s\S])|[^'\\\r\n])*'"
    r'|[A-Za-z_]\w*|(?:\d[\w.]*|\.\d[\w.]*)'
    r'|>>=|<<=|\.\.\.|->|\+\+|--|&&|\|\||<=|>=|==|!=|<<|>>'
    r'|[+*/%&|^!-]=|##|[^\s]')
PROCESS = re.compile(
    r'\b(?:TODO|FIXME|REVISIT)\b|\b(?:Fix|FIX):'
    r'|\b(?:phase\s+\d+|plans?/\S+|SPEC\s*§\s*\d+)'
    r'|\b(?:ported\s+from|porting\s+(?:source|reference)|audit\s+finding)\b'
    r'|\([A-Z]\d+(?:\+[A-Z]\d+)*\s+fix\)|\(#\d+\s+fix\)|\[[A-Z]\d+\]'
    r'|https?://', re.I)
LEGAL = re.compile(r'copyright|licen[cs]e|SPDX|Apache Software Foundation', re.I)
DIAGNOSTIC = re.compile(r'^(.+):(\d+):(\d+): (error|warning): (.+)$')
FILE_DIAGNOSTIC = re.compile(r'^(.+): (error|warning): (No block comments found)$')


class ToolError(RuntimeError):
    """An input or tool failure that must not be interpreted as a pass."""


def failure_log(argv, stdout, stderr):
    directory = Path(tempfile.mkdtemp(prefix="renesas-tool-error-"))
    (directory / "command.json").write_text(json.dumps([str(a) for a in argv]) + "\n")
    for name, value in (("stdout", stdout), ("stderr", stderr)):
        (directory / name).write_bytes(value or b"")
    return directory


def run(argv, cwd=None, data=None, allowed=(0,), timeout=120):
    try:
        command = [str(a) for a in argv]
        executable = shutil.which(command[0])
        if executable:
            command[0] = str(Path(executable).resolve())
        environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
        result = subprocess.run(command, cwd=cwd, input=data,
                                capture_output=True, timeout=timeout, check=False,
                                env=environment)
    except (OSError, subprocess.TimeoutExpired) as error:
        log = failure_log(argv, getattr(error, "stdout", b""), getattr(error, "stderr", b""))
        raise ToolError(f"{error}; full tool log: {log}") from error
    if result.returncode not in allowed:
        detail = result.stderr.decode("utf-8", errors="replace")[-2000:]
        log = failure_log(argv, result.stdout, result.stderr)
        raise ToolError(f"{Path(str(argv[0])).name} exited {result.returncode}: {detail}; full tool log: {log}")
    try:
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
    except UnicodeDecodeError as error:
        log = failure_log(argv, result.stdout, result.stderr)
        raise ToolError(f"Tool output is not valid UTF-8; full tool log: {log}") from error


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, roots):
    return any(path == root or root in path.parents for root in roots)


def assert_regular(root, relative):
    if relative.is_absolute() or ".." in relative.parts:
        raise ToolError(f"Invalid relative path: {relative}")
    parent = root
    for part in relative.parts:
        if part.startswith("-"):
            raise ToolError(f"Option-like path component: {relative}")
        parent = parent / part
        if parent.is_symlink():
            raise ToolError(f"Symlink input: {relative}")
    if not parent.is_file():
        raise ToolError(f"Not a regular file: {relative}")
    if not stat.S_ISREG(parent.lstat().st_mode):
        raise ToolError(f"Non-regular input: {relative}")
    return parent


@dataclass
class Source:
    path: Path
    family: str
    mode: str
    classification: str
    ownership: dict

    def record(self):
        return {"path": self.path.as_posix(), "family": self.family,
                "mode": self.mode, "classification": self.classification,
                "ownership": self.ownership}


def inventory(root, policy, selections=(), family=None):
    _, top, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=root)
    if Path(top.strip()).resolve() != root.resolve():
        raise ToolError("Root is not the expected repository root")
    _, sub_top, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=root / NUTTX)
    if Path(sub_top.strip()).resolve() != (root / NUTTX).resolve():
        raise ToolError("NuttX path is not a separate repository")
    _, link, _ = run(["git", "ls-files", "--stage", "--", NUTTX], cwd=root)
    if not link.startswith("160000 "):
        raise ToolError("NuttX path is not a tracked submodule")
    selected = []
    for value in selections:
        p = Path(value)
        if p.is_absolute():
            try:
                p = p.relative_to(root)
            except ValueError as error:
                raise ToolError("Selection escapes the repository") from error
        if ".." in p.parts or not inside(p, PX4_ROOTS + tuple(NUTTX / x for x in NUTTX_ROOTS)):
            raise ToolError(f"Selection outside the declared scope: {p}")
        cursor = root
        for part in p.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ToolError(f"Selection follows a symlink: {p}")
        selected.append(p)
    sources = []
    for repo, roots, owner in ((root, PX4_ROOTS, "px4"),
                               (root / NUTTX, NUTTX_ROOTS, "nuttx")):
        if family and family != owner:
            continue
        _, listing, _ = run(["git", "ls-files", "--stage", "-z", "--", *roots], cwd=repo)
        for entry in listing.split("\0"):
            if not entry:
                continue
            meta, name = entry.split("\t", 1)
            mode, _, stage = meta.split()
            if stage != "0":
                raise ToolError(f"Unmerged file: {name}")
            relative = (repo / name).relative_to(root)
            if selected and not inside(relative, selected):
                continue
            exception = policy.get("files", {}).get(relative.as_posix(), {})
            if mode == "120000":
                classification = "symlink"
            else:
                assert_regular(root, relative)
                classification = exception.get("classification", "unknown")
                if classification not in ("handwritten", "configuration", "non-code",
                                          "vendor", "generated", "unknown"):
                    raise ToolError(f"Unknown ownership classification: {relative}")
                if classification in ("vendor", "generated") and not all(
                        exception.get(key) for key in ("evidence", "owner", "regenerate")):
                    raise ToolError(f"Incomplete ownership evidence: {relative}")
            sources.append(Source(relative, owner, mode, classification, exception))
    sources.sort(key=lambda s: s.path.as_posix())
    if not sources or (selected and not any(s.classification != "symlink" for s in sources)):
        raise ToolError("Selection has no tracked regular files")
    return sources


def lexical(text):
    matches = list(TOKEN.finditer(text))
    for match in matches:
        token = match.group()
        tail = text[match.start():match.start() + 20]
        if (token in ('"', "'") or
                text.startswith("/*", match.start()) and not token.startswith("/*") or
                re.match(r'(?:u8|[LuU])?R"', tail) and not re.match(r'(?:u8|[LuU])?R"', token)):
            raise ToolError("Unterminated or invalid comment/literal")
    return matches


def code_tokens(text):
    return [m.group() for m in lexical(text) if not m.group().startswith(("/*", "//"))]


def continues_line(line):
    return line.rstrip("\r\n").rstrip().endswith("\\")


def protected_content(text):
    """Keep directive bytes and legal attribution exactly intact."""
    protected = directive_lines(text)
    directives = [line for i, line in enumerate(text.splitlines(keepends=True)) if i in protected]
    legal = [m.group() for m in lexical(text)
             if m.group().startswith(("/*", "//")) and LEGAL.search(m.group())]
    return directives, legal


def directive_lines(text):
    lines = text.splitlines(keepends=True)
    protected = set()
    continuation = False
    for index, line in enumerate(lines):
        continued = continues_line(line)
        if continuation or line.lstrip().startswith("#") or continued:
            protected.add(index)
        continuation = continued
    for match in lexical(text):
        if match.group().startswith("/*"):
            start = text.count("\n", 0, match.start())
            if start in protected:
                protected.update(range(start, start + match.group().count("\n") + 1))
    return protected


def protected_lines(text):
    protected = directive_lines(text)
    for match in lexical(text):
        token = match.group()
        if token.startswith(("/*", "//")):
            continue
        if '"' in token or token.startswith("'"):
            start = text.count("\n", 0, match.start())
            protected.update(range(start, start + token.count("\n") + 1))
    return protected


def policy_findings(text):
    findings = []
    for match in lexical(text):
        comment = match.group()
        if not comment.startswith(("/*", "//")):
            continue
        for marker in PROCESS.finditer(comment):
            line_start = comment.rfind("\n", 0, marker.start()) + 1
            line_end = comment.find("\n", marker.end())
            line = comment[line_start:line_end if line_end >= 0 else len(comment)]
            # License URLs are legal text; unrelated workflow text in the same
            # file header still requires disposition.
            if marker.group().lower().startswith("http") and (
                    LEGAL.search(line) or "apache.org/licenses/" in line):
                continue
            findings.append({"rule": "comment-policy",
                             "line": 1 + text.count("\n", 0, match.start() + marker.start()),
                             "column": 0, "message": marker.group()})
    return findings


def function_findings(text):
    """Identify top-level C definitions; contracts still require source review."""
    matches = definition_tokens(text)
    depth = 0
    findings = []
    for index, match in enumerate(matches):
        token = match.group()
        if token.startswith(("/*", "//")):
            continue
        if token == "{" and depth == 0 and index and matches[index - 1].group() == ")":
            nesting = 1
            j = index - 2
            while j >= 0 and nesting:
                nesting += (matches[j].group() == ")") - (matches[j].group() == "(")
                j -= 1
            if j >= 0:
                name = matches[j].group()
                if re.fullmatch(r"[A-Za-z_]\w*", name) and name not in ("if", "for", "while", "switch"):
                    previous = [m for m in matches[:j] if m.group().startswith("/*")]
                    header = previous[-1].group() if previous else ""
                    required = ("Name:", "Description:", "Input Parameters:", "Returned Value:")
                    if not all(section in header for section in required) or not re.search(
                            r"Name:\s*" + re.escape(name) + r"\b", header):
                        findings.append({"rule": "function-contract", "line": 1 + text.count(
                            "\n", 0, matches[j].start()), "column": 0, "message": name})
        depth += (token == "{") - (token == "}")
    return findings


def definition_tokens(text):
    directives = directive_lines(text)
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    return [m for m in lexical(text) if bisect_right(starts, m.start()) - 1 not in directives]


def parameter_names(signature):
    parameters = set()
    nesting = 0
    start = 0
    parts = []
    for index, char in enumerate(signature):
        nesting += (char in "([") - (char in ")]")
        if char == "," and nesting == 0:
            parts.append(signature[start:index])
            start = index + 1
    parts.append(signature[start:])
    for part in parts:
        if part.strip() in ("", "void", "..."):
            continue
        pointer = re.search(r"\(\s*\*\s*(\w+)\s*\)", part)
        names = re.findall(r"[A-Za-z_]\w*", part.split("[", 1)[0])
        if pointer:
            parameters.add(pointer[1])
        elif names:
            parameters.add(names[-1])
    return parameters


def reviewed_contracts(text, contracts):
    """Apply explicit reviewer text; never infer a function's behavior."""
    if not isinstance(contracts, dict) or any(not isinstance(n, str) or not re.fullmatch(
            r"[A-Za-z_]\w*", n) for n in contracts):
        raise ToolError("Invalid reviewed function names")
    original = text
    matches = definition_tokens(text)
    directives = directive_lines(text)
    depth = 0
    edits = []
    found = set()
    for index, match in enumerate(matches):
        token = match.group()
        if token.startswith(("/*", "//")):
            continue
        if token == "{" and depth == 0 and index and matches[index - 1].group() == ")":
            nesting = 1
            j = index - 2
            while j >= 0 and nesting:
                nesting += (matches[j].group() == ")") - (matches[j].group() == "(")
                j -= 1
            name = matches[j].group() if j >= 0 else ""
            if name in contracts:
                contract = contracts[name]
                if not isinstance(contract, dict) or set(contract) - {
                        "description", "parameters", "returns", "assumptions"}:
                    raise ToolError(f"Invalid contract for {name}")
                if not isinstance(contract.get("parameters"), dict):
                    raise ToolError(f"Missing parameters for {name}")
                values = [contract.get("description"), contract.get("returns"),
                          *contract["parameters"].values()]
                if "assumptions" in contract:
                    values.append(contract["assumptions"])
                if any(not isinstance(v, str) or not v.strip() or "*/" in v
                       or "\x00" in v for v in values):
                    raise ToolError(f"Invalid contract text for {name}")
                if any(not re.fullmatch(r"[A-Za-z_]\w*", p)
                       for p in contract["parameters"]):
                    raise ToolError(f"Invalid parameter name for {name}")
                # Find the start of the signature without consuming a banner
                # or the preceding declaration/directive.
                start = text.rfind("\n", 0, matches[j].start()) + 1
                while start > 0:
                    previous_start = text.rfind("\n", 0, start - 1) + 1
                    previous = text[previous_start:start].strip()
                    if not previous or text.count("\n", 0, previous_start) in directives or previous.endswith((";", "}", "*/")):
                        break
                    start = previous_start
                signature_start = start
                signature = text[matches[j + 1].end():matches[index - 1].start()]
                parameters = parameter_names(signature)
                # A conditional signature shares one body. Put its contract
                # above the selection and cover both parameter variants.
                previous_start = text.rfind("\n", 0, start - 1) + 1
                if text[previous_start:start].strip() == "#else":
                    selection = list(re.finditer(r"^#\s*if(?:def|ndef)?\b[^\n]*$",
                                                 text[:previous_start], re.M))
                    if selection:
                        begin = selection[-1].start()
                        alternative = text[begin:previous_start]
                        other = re.search(r"\b" + re.escape(name) + r"\s*\(([\s\S]*?)\)", alternative)
                        if other and not any(t.group() == "{" for t in lexical(alternative)):
                            parameters.update(parameter_names(other[1]))
                            start = signature_start = begin
                if set(contract["parameters"]) != parameters:
                    raise ToolError(f"Reviewed parameter names differ for {name}")
                comments = [c for c in matches[:j] if c.group().startswith("/*")]
                if comments:
                    comment = comments[-1]
                    if "Name:" in comment.group() and not text[comment.end():start].strip():
                        if LEGAL.search(comment.group()):
                            raise ToolError("Function header contains legal attribution")
                        start = comment.start()
                header = ["/****************************************************************************",
                          f" * Name: {name}", " *", " * Description:"]

                def prose(value, prefix="   "):
                    for line in textwrap.wrap(value, width=74 - len(prefix),
                                              break_long_words=False, break_on_hyphens=False):
                        header.append(" *" + prefix + line)

                prose(contract["description"])
                header.extend([" *", " * Input Parameters:"])
                if contract["parameters"]:
                    for parameter, description in contract["parameters"].items():
                        prose(parameter + " - " + description)
                else:
                    prose("None.")
                header.extend([" *", " * Returned Value:"])
                prose(contract["returns"])
                if contract.get("assumptions"):
                    header.extend([" *", " * Assumptions/Limitations:"])
                    prose(contract["assumptions"])
                header.extend([" *", " ****************************************************************************/", "", ""])
                edits.append((start, signature_start, "\n".join(header)))
                found.add(name)
        depth += (token == "{") - (token == "}")
    if found != set(contracts):
        raise ToolError("Reviewed contract names do not match definitions: " +
                        ", ".join(sorted(set(contracts) - found)))
    for left, right in zip(edits, edits[1:]):
        if left[1] > right[0]:
            raise ToolError("Reviewed function-header edits overlap")
    for start, end, header in reversed(edits):
        text = text[:start] + header + text[end:]
    if code_tokens(original) != code_tokens(text):
        raise ToolError("Reviewed contracts changed code tokens")
    return text


def normalize_nuttx(text, diagnostics, relative):
    lines = text.splitlines(keepends=True)
    protected = protected_lines(text)
    for i, line in enumerate(lines):
        if i not in protected:
            lines[i] = line.rstrip(" \t\r\n") + ("\n" if line.endswith(("\n", "\r")) else "")
    before, after, remove = set(), set(), set()
    comments = [match for match in lexical(text) if match.group().startswith("/*")]
    spans = [(text.count("\n", 0, match.start()), text.count("\n", 0, match.end()))
             for match in comments]
    for issue in diagnostics:
        i = issue["line"] - 1
        if i < 0 or i >= len(lines) or i in protected:
            continue
        message = issue["message"]
        if message == "Too many blank lines" and not lines[i].strip():
            remove.add(i)
        if "Missing blank line" in message:
            for start, end in spans:
                if start <= i <= end or ("after comment" in message and i == end + 1):
                    if any(n in protected for n in range(start, end + 1)):
                        continue
                    if "before comment" in message and start > 0 and lines[start - 1].strip():
                        if not lines[start].split("/*", 1)[0].strip():
                            before.add(start)
                    if "after comment" in message and end + 1 < len(lines) and lines[end + 1].strip():
                        after.add(end)
        if message == "Relative file path does not match actual file" and i == 1:
            if re.fullmatch(r"\s*\*\s+[^\n]+\n?", lines[i]):
                lines[i] = f" * {relative.as_posix()}\n"
    result = []
    for i, line in enumerate(lines):
        if i in before:
            result.append("\n")
        if i not in remove:
            result.append(line)
        if i in after:
            result.append("\n")
    if result and not result[-1].endswith("\n") and len(lines) - 1 not in protected:
        result[-1] += "\n"
    candidate = "".join(result)
    if code_tokens(candidate) != code_tokens(text):
        raise ToolError("Normalization changed code tokens")
    return candidate


def diagnostics_improve(before, after, original, candidate, allow_equal=False):
    """Require every remaining finding to map to an unchanged original line."""
    if len(after) > len(before) or len(after) == len(before) and not allow_equal:
        return False
    old = original.splitlines()
    new = candidate.splitlines()
    mapping = {}
    for match in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_matching_blocks():
        for offset in range(match.size):
            mapping[match.b + offset + 1] = match.a + offset + 1
    expected = Counter((d["line"], d["column"], d["message"]) for d in before)
    for issue in after:
        line = mapping.get(issue["line"])
        identity = (line, issue["column"], issue["message"])
        if line is None or expected[identity] == 0:
            return False
        expected[identity] -= 1
    return True


class Checkers:
    def __init__(self, root, cache):
        self.root = root
        self.cache = cache
        self.mirror = cache / "mirror/nuttx"
        self.version = None
        self.binary = {}
        self.inputs = {}
        self.owner_inputs = {}
        self.executables = {}
        self.git_version = run([self.executable("git"), "--version"])[1].strip()
        for relative in ("Tools/astyle/astylerc", "Tools/astyle/check_code_style_all.sh",
                         "Tools/renesas-coding-standards.py",
                         "Tools/renesas-coding-standards.json",
                         str(NUTTX / "tools/Makefile.host"), str(NUTTX / "tools/Config.mk"),
                         str(NUTTX / "tools/nxstyle.c"), str(NUTTX / "Make.defs"),
                         str(NUTTX / ".config"),
                         str(NUTTX / "arch/arm/src/armv7-r/Toolchain.defs"),
                         str(NUTTX / "arch/arm/src/armv8-m/Toolchain.defs")):
            path = root / relative
            self.inputs[relative] = digest(path.read_bytes()) if path.is_file() else None

    def executable(self, name):
        location = shutil.which(name)
        if not location:
            raise ToolError(f"{name} is missing")
        location = Path(location).resolve()
        fingerprint = digest(location.read_bytes())
        existing = self.executables.get(name)
        if existing and existing != {"path": str(location), "sha256": fingerprint}:
            raise ToolError(f"Executable changed: {name}")
        self.executables[name] = {"path": str(location), "sha256": fingerprint}
        return location

    def assert_inputs(self):
        for relative, expected_identity in self.owner_inputs.items():
            path = assert_regular(self.root, Path(relative))
            if file_identity(path.lstat()) != expected_identity:
                raise ToolError(f"Register spelling owner changed: {relative}")
        for relative, expected in self.inputs.items():
            path = self.root / relative
            current = digest(path.read_bytes()) if path.is_file() else None
            if current != expected:
                raise ToolError(f"Checker input changed: {relative}")
        for name in list(self.executables):
            self.executable(name)

    def px4(self, text):
        astyle = self.executable("astyle")
        _, output, _ = run([astyle, "--version"])
        if output.strip() not in ("Artistic Style Version 2.06", "Artistic Style Version 3.0",
                                  "Artistic Style Version 3.0.1", "Artistic Style Version 3.1"):
            raise ToolError(f"Unsupported AStyle: {output.strip()}")
        self.version = output.strip()
        _, formatted, error = run([astyle, "--options=" + str(self.root / "Tools/astyle/astylerc"),
                                   "--quiet"], data=text.encode())
        if error.strip():
            raise ToolError(error)
        return formatted

    def nxstyle(self, text, relative, canonical=False):
        mode = "canonical" if canonical else "mirror"
        original = self.root / NUTTX
        top = original if canonical else self.mirror
        tool = self.cache / mode / "tools"
        if mode not in self.binary:
            tool.mkdir(parents=True, exist_ok=True)
            (self.mirror / "tools").mkdir(parents=True, exist_ok=True)
            for filename in ("Makefile.host", "Config.mk", "nxstyle.c"):
                source = original / "tools" / filename
                shutil.copyfile(source, tool / filename)
                if not canonical:
                    shutil.copyfile(source, self.mirror / "tools" / filename)
            run([self.executable("make"), "-C", tool, "-f", "Makefile.host", "TOPDIR=" + str(top),
                 "HOSTCC=" + str(self.executable("cc")), "nxstyle"], timeout=120)
            self.binary[mode] = tool / "nxstyle"
        if canonical:
            target = original / relative
        else:
            target = self.mirror / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        code, out, err = run([self.binary[mode], target], allowed=(0, 1))
        findings = []
        for line in (out + err).splitlines():
            match = DIAGNOSTIC.fullmatch(line)
            if not match:
                file_match = FILE_DIAGNOSTIC.fullmatch(line)
                if file_match and file_match[1] == str(target):
                    findings.append({"rule": "nxstyle", "line": 0,
                                     "column": 0, "message": file_match[3]})
                    continue
                log = failure_log([self.binary[mode], target], out.encode(), err.encode())
                raise ToolError(f"Unrecognized nxstyle result: {line}; full tool log: {log}")
            if match[1] != str(target):
                raise ToolError("nxstyle reported a different file")
            findings.append({"rule": "nxstyle", "line": int(match[2]),
                             "column": int(match[3]), "message": match[5]})
        if bool(findings) != bool(code):
            raise ToolError("nxstyle exit status disagrees with diagnostics")
        return findings


def file_identity(status):
    return (status.st_dev, status.st_ino, status.st_mode, status.st_uid,
            status.st_gid, status.st_size, status.st_mtime_ns)


def atomic_replace(path, expected, candidate, expected_identity=None,
                   parent_fd=None, expected_parent=None):
    owns_parent = parent_fd is None
    if owns_parent:
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parent = os.fstat(parent_fd)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = None
    temporary = None
    try:
        if expected_parent and (parent.st_dev, parent.st_ino) != expected_parent:
            raise ToolError("Parent changed before replacement")
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        original_stat = os.fstat(descriptor)
        if not stat.S_ISREG(original_stat.st_mode):
            raise ToolError("Input ceased to be regular")
        if expected_identity and file_identity(original_stat) != expected_identity:
            raise ToolError("Input identity changed before replacement")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            if stream.read() != expected:
                raise ToolError("Input changed concurrently")
        temporary = ".coding-standard-" + os.urandom(12).hex()
        temporary_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600, dir_fd=parent_fd)
        with os.fdopen(temporary_fd, "wb") as stream:
            stream.write(candidate)
            staged_stat = os.fstat(stream.fileno())
            if (staged_stat.st_uid, staged_stat.st_gid) != (original_stat.st_uid, original_stat.st_gid):
                os.fchown(stream.fileno(), original_stat.st_uid, original_stat.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(original_stat.st_mode))
            stream.flush()
            os.fsync(stream.fileno())
        current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        current_parent = path.parent.lstat()
        if file_identity(current) != file_identity(original_stat) or (
                current_parent.st_dev, current_parent.st_ino) != (parent.st_dev, parent.st_ino):
            raise ToolError("Input or parent changed concurrently")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            stream.seek(0)
            if stream.read() != expected:
                raise ToolError("Input changed concurrently")
        os.replace(temporary, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        os.fsync(parent_fd)
        verify_fd = os.open(path.name, flags, dir_fd=parent_fd)
        with os.fdopen(verify_fd, "rb") as stream:
            if (stream.read() != candidate or stat.S_IMODE(os.fstat(stream.fileno()).st_mode) !=
                    stat.S_IMODE(original_stat.st_mode)):
                raise ToolError("Replacement verification failed")
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        if descriptor is not None:
            os.close(descriptor)
        if owns_parent:
            os.close(parent_fd)


def output_snapshot(path):
    parents = {}
    for parent in path.parents:
        if parent.is_symlink():
            raise ToolError("Report output follows a symlink")
        if parent.exists():
            status = parent.lstat()
            parents[str(parent)] = (status.st_dev, status.st_ino)
    if path.exists() or path.is_symlink():
        assert_regular(path.parent, Path(path.name))
        return parents, path.read_bytes(), file_identity(path.lstat())
    return parents, None, None


def write_report(path, content, snapshot):
    """Refuse output swaps and create new reports without clobbering files."""
    parents, original, identity = snapshot
    def validate():
        for parent in path.parents:
            if parent.is_symlink():
                raise ToolError("Report parent became a symlink")
            if str(parent) in parents:
                current = parent.lstat()
                if (current.st_dev, current.st_ino) != parents[str(parent)]:
                    raise ToolError("Report parent changed during checking")
    validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    validate()
    if str(path.parent) not in parents:
        parent = path.parent.lstat()
        parents[str(path.parent)] = (parent.st_dev, parent.st_ino)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".renesas-report-" + os.urandom(12).hex()
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != parents[str(path.parent)]:
            raise ToolError("Report parent changed before opening")
        validate()
        if original is not None:
            try:
                atomic_replace(path, original, content, expected_identity=identity,
                               parent_fd=descriptor, expected_parent=parents[str(path.parent)])
            except OSError as error:
                raise ToolError(f"Report replacement refused: {error}") from error
            return
        stream_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600, dir_fd=descriptor)
        with os.fdopen(stream_fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate()
        parent = path.parent.lstat()
        opened = os.fstat(descriptor)
        if (parent.st_dev, parent.st_ino) != (opened.st_dev, opened.st_ino):
            raise ToolError("Report parent changed during writing")
        os.link(temporary, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor,
                follow_symlinks=False)
        os.fsync(descriptor)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        finally:
            os.close(descriptor)


def reviewed_symbol_findings(root, source, text, findings):
    """Retain raw native diagnostics and identify reviewed register spellings."""
    disposition = source.ownership.get("native_symbol_dispositions")
    if not disposition or disposition.get("source_sha256") != digest(text.encode()):
        return []
    symbols = disposition.get("symbols", {})
    lines = text.splitlines()
    reviewed = []
    for finding in findings:
        if finding.get("rule") != "nxstyle" or finding.get("message") != "Mixed case identifier found":
            continue
        line = finding.get("line", 0) - 1
        column = finding.get("column", -1)
        if line < 0 or line >= len(lines) or column < 0:
            continue
        token = re.match(r"[A-Za-z_]\w*", lines[line][column:])
        if not token or token.group() not in symbols:
            continue
        owner = symbols[token.group()]
        if not isinstance(owner, dict) or not owner.get("evidence"):
            raise ToolError("Register spelling disposition lacks ownership evidence")
        owner_path = Path(owner["path"])
        if not owner_path.is_relative_to(NUTTX / "arch/arm/src/rzv/hardware") or owner_path.suffix != ".h":
            raise ToolError("Register spelling owner is outside the RZ/V hardware headers")
        path = assert_regular(root, owner_path)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            owner_identity = file_identity(os.fstat(stream.fileno()))
            owner_bytes = stream.read()
        if owner_identity != file_identity(path.lstat()):
            raise ToolError("Register spelling owner changed during reading")
        if digest(owner_bytes) != owner.get("sha256"):
            continue
        definition = re.compile(r"^#\s*define\s+" + re.escape(token.group()) + r"(?:\s|\()", re.M)
        if not definition.search(owner_bytes.decode("utf-8")):
            continue
        reviewed.append({**finding, "identifier": token.group(), "disposition": owner,
                         "owner_identity": owner_identity})
    return reviewed


def process(root, source, checkers, mode, pending=None, contracts=None):
    record = source.record()
    record.update(findings=[], changed=False)
    if source.classification == "unknown":
        record["findings"].append({"rule": "ownership", "line": 0, "column": 0,
                                   "message": "Source ownership requires review"})
    if source.classification == "symlink" or source.path.suffix not in C_EXTENSIONS:
        return record
    path = assert_regular(root, source.path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        input_identity = file_identity(os.fstat(stream.fileno()))
        original_bytes = stream.read()
    if input_identity != file_identity(path.lstat()):
        raise ToolError("Input changed during reading")
    record["input_identity"] = input_identity
    original = original_bytes.decode("utf-8")
    record["sha256"] = digest(original_bytes)
    findings = record["findings"] + policy_findings(original)
    eligible = source.classification == "handwritten"
    if source.family == "px4":
        candidate = checkers.px4(original)
        if candidate != original:
            findings.append({"rule": "astyle", "line": 0, "column": 0, "message": "Formatting differs"})
        safe = code_tokens(original) == code_tokens(candidate)
        if not safe:
            record["manual_required"] = "Formatter changes code tokens"
    else:
        relative = source.path.relative_to(NUTTX)
        native = checkers.nxstyle(original, relative, canonical=True)
        record["checker_incomplete"] = any("File will not be checked" in d["message"] for d in native)
        findings.extend(native)
        findings.extend(function_findings(original))
        reviewed = contracts.get(str(source.path)) if contracts else None
        candidate = original
        if reviewed:
            if not eligible or reviewed.get("sha256") != digest(original_bytes):
                raise ToolError(f"Reviewed source changed: {source.path}")
            candidate = reviewed_contracts(original, reviewed["functions"])
            if code_tokens(candidate) != code_tokens(original):
                raise ToolError("Reviewed contracts changed code tokens")
            if policy_findings(candidate):
                raise ToolError("Reviewed contracts retain policy markers")
            record["reviewed_contracts"] = sorted(reviewed["functions"])
        candidate_native = checkers.nxstyle(candidate, relative) if candidate != original else native
        candidate = normalize_nuttx(candidate, candidate_native, relative) if eligible else original
        proposal = checkers.nxstyle(candidate, relative) if candidate != original else native
        safe = candidate != original and diagnostics_improve(
            native, proposal, original, candidate, allow_equal=bool(reviewed))
        record["proposed_diagnostic_count"] = len(proposal)
        if record["checker_incomplete"]:
            safe = False
            record["manual_required"] = "Native checker did not inspect the complete file"
    if protected_content(original) != protected_content(candidate):
        safe = False
        record["manual_required"] = "Proposal changes a directive or legal attribution"
    record["findings"] = findings
    record["reviewed_findings"] = reviewed_symbol_findings(root, source, original, findings)
    for finding in record["reviewed_findings"]:
        owner = finding["disposition"]
        checkers.inputs[owner["path"]] = owner["sha256"]
        checkers.owner_inputs[owner["path"]] = finding["owner_identity"]
    record["unresolved_findings"] = [f for f in findings if not any(
        all(f.get(k) == d.get(k) for k in ("rule", "line", "column", "message"))
        for d in record["reviewed_findings"])]
    if candidate != original:
        record["edited_line_ranges"] = [
            {"original": [a0 + 1, a1], "candidate": [b0 + 1, b1]}
            for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(
                a=original.splitlines(True), b=candidate.splitlines(True),
                autojunk=False).get_opcodes() if tag != "equal"]
        record["proposal"] = "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                                           fromfile=str(source.path), tofile=str(source.path)))
    if mode == "fix" and eligible and safe and candidate != original:
        if pending is None:
            raise ToolError("Fix requires a staged batch")
        pending.append((path, original_bytes, candidate.encode(), record))
    return record


def apply_batch(pending, checkers):
    """Finish all checks before writing; individual replacements are atomic."""
    checkers.assert_inputs()
    for path, original, _, record in pending:
        assert_regular(checkers.root, path.relative_to(checkers.root))
        if record.get("input_identity") and file_identity(path.lstat()) != record["input_identity"]:
            raise ToolError(f"Input identity changed during inspection: {path}")
        if path.read_bytes() != original:
            raise ToolError(f"Input changed during batch inspection: {path}")
    if not pending:
        return None
    recovery = Path(tempfile.mkdtemp(prefix="renesas-standards-recovery-"))
    manifest = {"root": str(checkers.root), "state": "prepared", "files": []}
    for index, (path, original, candidate, _) in enumerate(pending):
        for suffix, content in (("original", original), ("candidate", candidate)):
            with (recovery / f"{index}.{suffix}").open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        manifest["files"].append({"path": str(path.relative_to(checkers.root)),
                                  "original_sha256": digest(original),
                                  "candidate_sha256": digest(candidate),
                                  "mode": stat.S_IMODE(path.stat().st_mode),
                                  "state": "pending"})
    journal = recovery / "manifest.json"

    def save():
        with tempfile.NamedTemporaryFile(dir=recovery, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write((json.dumps(manifest, indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, journal)
        descriptor = os.open(recovery, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    save()
    try:
        for index, (path, original, candidate, record) in enumerate(pending):
            checkers.assert_inputs()
            atomic_replace(path, original, candidate, expected_identity=record.get("input_identity"))
            record["changed"] = True
            record["result_sha256"] = digest(candidate)
            manifest["files"][index]["state"] = "replaced"
            save()
        manifest["state"] = "completed"
        save()
    except (OSError, ToolError) as error:
        manifest["state"] = "interrupted"
        manifest["error"] = str(error)
        attempted = manifest["files"][index]
        attempted["state"] = "uncertain"
        try:
            assert_regular(checkers.root, path.relative_to(checkers.root))
            attempted["observed_sha256"] = digest(path.read_bytes())
        except (OSError, ToolError):
            attempted["observed_sha256"] = None
        try:
            save()
        except OSError:
            pass
        raise ToolError(f"Batch stopped: {error}; recovery files: {journal}") from error
    return str(journal)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inventory", "report", "check", "fix"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--family", choices=("px4", "nuttx"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contracts", type=Path,
                        help="Reviewed, source-hash-bound function contracts (fix only)")
    parser.add_argument("--limit", type=int, default=12, help="Maximum printed finding files")
    args = parser.parse_args(argv)
    if args.root.resolve() != ROOT:
        parser.error("--root must identify the repository containing this runner")
    if args.mode == "fix" and not args.path:
        parser.error("fix requires an explicit --path")
    if args.contracts and (args.mode != "fix" or args.family == "px4"):
        parser.error("--contracts requires a NuttX fix selection")
    try:
        if args.output:
            output = args.output.absolute()
            if output.is_symlink() or output.suffix != ".json":
                raise ToolError("Report output must be a regular .json destination")
            for parent in output.parents:
                if parent.is_symlink():
                    raise ToolError("Report output follows a symlink")
            output = output.resolve()
            args.output = output
            reports = ROOT / "plans"
            if not (output.is_relative_to(Path("/tmp")) or
                    output.is_relative_to(reports) and "reports" in output.relative_to(reports).parts[:-1]):
                raise ToolError("Report output must be in /tmp or plans/**/reports")
            if output.is_relative_to(ROOT) and inside(output.relative_to(ROOT),
                    PX4_ROOTS + tuple(NUTTX / x for x in NUTTX_ROOTS)):
                raise ToolError("Report output cannot overwrite source scope")
            if output.is_relative_to(ROOT):
                _, tracked, _ = run(["git", "ls-files", "--", output.relative_to(ROOT)], cwd=ROOT)
                if tracked.strip() or output.is_relative_to(ROOT / NUTTX):
                    raise ToolError("Report output cannot overwrite tracked files or submodule content")
            report_snapshot = output_snapshot(output)
        policy = json.loads((ROOT / "Tools/renesas-coding-standards.json").read_text())
        if policy.get("schema") != 1 or not isinstance(policy.get("files"), dict):
            raise ToolError("Unsupported ownership policy schema")
        sources = inventory(ROOT, policy, args.path, args.family)
        contracts = None
        if args.contracts:
            args.contracts = args.contracts.absolute()
            if args.output == args.contracts.resolve():
                raise ToolError("Report output cannot overwrite reviewed contracts")
            assert_regular(args.contracts.parent, Path(args.contracts.name))
            contract_bytes = args.contracts.read_bytes()
            data = json.loads(contract_bytes)
            if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("files"), dict):
                raise ToolError("Unsupported reviewed contract schema")
            contracts = data["files"]
            selected = {str(s.path) for s in sources if s.family == "nuttx" and
                        s.classification == "handwritten" and s.path.suffix in C_EXTENSIONS}
            if not contracts or set(contracts) - selected:
                raise ToolError("Reviewed contracts escape the eligible selection")
            for entry in contracts.values():
                if not isinstance(entry, dict) or set(entry) != {"sha256", "functions"} or not isinstance(
                        entry["functions"], dict) or not entry["functions"] or not isinstance(
                        entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                    raise ToolError("Invalid reviewed contract file entry")
        if args.mode == "fix" and not any(s.classification == "handwritten" and
                                         s.path.suffix in C_EXTENSIONS for s in sources):
            raise ToolError("Fix selection has no eligible hand-written C/C++ source")
        with tempfile.TemporaryDirectory(prefix="renesas-standards-") as cache:
            checkers = Checkers(ROOT, Path(cache))
            if contracts:
                checkers.inputs[str(args.contracts)] = digest(contract_bytes)
            lock_path = Path(tempfile.gettempdir()) / ("renesas-standards-" + digest(str(ROOT).encode())[:16] + ".lock")
            with lock_path.open("a") as lock:
                if args.mode == "fix":
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as error:
                        raise ToolError("Another fixer owns this repository") from error
                pending = []
                records = [s.record() if args.mode == "inventory" else process(
                    ROOT, s, checkers, args.mode, pending, contracts)
                           for s in sources]
                if args.mode == "fix" and any(r.get("checker_incomplete") for r in records):
                    raise ToolError("Native checker coverage is incomplete; no proposals applied")
                recovery_journal = apply_batch(pending, checkers) if args.mode == "fix" else None
                checkers.assert_inputs()
            counts = Counter(s.classification for s in sources)
            violations = [r for r in records if r.get("unresolved_findings", r.get("findings")) and r["classification"] in ("handwritten", "unknown")]
            report = {"schema": 1, "mode": args.mode, "astyle": checkers.version,
                      "checker_inputs": checkers.inputs,
                      "executables": checkers.executables, "python": sys.version,
                      "git": checkers.git_version,
                      "recovery_journal": recovery_journal,
                      "incomplete_files": sum(bool(r.get("checker_incomplete")) for r in records),
                      "counts": dict(sorted(counts.items())), "files": records,
                      "reviewed_diagnostics": sum(len(r.get("reviewed_findings", [])) for r in records),
                      "violating_files": len(violations), "changed_files": sum(r.get("changed", False) for r in records)}
            for repo, label in ((ROOT, "px4"), (ROOT / NUTTX, "nuttx")):
                _, head, _ = run(["git", "rev-parse", "HEAD"], cwd=repo)
                report[label + "_head"] = head.strip()
                _, status_output, _ = run(["git", "status", "--porcelain", "-z", "--untracked-files=no"], cwd=repo)
                report[label + "_status"] = status_output.split("\0")[:-1]
            _, gitlink, _ = run(["git", "ls-files", "--stage", "--", NUTTX], cwd=ROOT)
            report["nuttx_gitlink"] = gitlink.strip()
            chip = ROOT / NUTTX / "arch/arm/include/chip"
            report["aliases"] = [{"path": str(chip.relative_to(ROOT)),
                                  "target": os.readlink(chip) if chip.is_symlink() else None,
                                  "classification": "build-selected-alias", "editable": False}]
            if args.output:
                write_report(args.output, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
                             report_snapshot)
            print(f"{len(records)} tracked entries; {len(violations)} files with unresolved findings; "
                  f"{report['changed_files']} files changed")
            if report["reviewed_diagnostics"]:
                print(f"{report['reviewed_diagnostics']} raw diagnostics retain reviewed register spellings")
            if recovery_journal:
                print(f"Recovery record: {recovery_journal}")
            if report["incomplete_files"]:
                print(f"{report['incomplete_files']} files lack complete native checker coverage")
            for record in violations[:max(0, args.limit)]:
                print(f"{record['path']}: {len(record['findings'])} findings")
            if len(violations) > args.limit:
                print("Additional findings retained in the JSON report; use --output for full details.")
            if args.mode == "check" and any(r.get("checker_incomplete") for r in records):
                return 2
            return 1 if violations and args.mode in ("check", "fix") else 0
    except (ToolError, OSError, ValueError) as error:
        print(f"coding-standards: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
