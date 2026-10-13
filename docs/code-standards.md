# Code Standards & Conventions

**Status:** Active

This document defines coding conventions for the RDK-RZ/V2H port. Standards diverge between PX4 code and the NuttX submodule; follow the section matching your target directory.

## Control flow

`goto` is prohibited in hand-written RZ/V2H port code, including error and
cleanup paths in PX4 and NuttX. Use structured conditionals, early returns,
and small helpers that express resource ownership. Failures must release
only acquired resources in reverse order and preserve the original error.
Apply this rule to new and modified code; upstream and vendor files retain
their owning conventions.

---

## 1. Directory-Based Convention Split

### 1.1 PX4 Code (src/, boards/, platforms/nuttx/src/)

The executable style owner is `Tools/astyle/astylerc`, with repository-wide
line and newline defaults in `.editorconfig`. Keep PX4 AStyle's Linux variant,
8-column tabs, right-aligned pointers, padded operators, and its configured
block/preprocessor handling. The project limit is 120 columns.

**Validation:**
```bash
./Tools/astyle/check_code_style_all.sh       # Check all non-excluded files
./Tools/astyle/fix_code_style.sh <file.c>   # Auto-fix single file
```

### 1.2 NuttX Submodule (platforms/nuttx/NuttX/nuttx/**)

Follow the NuttX coding standard in
`platforms/nuttx/NuttX/nuttx/Documentation/contributing/coding_style.rst` and
the submodule's `nxstyle` checker inputs. The RZ/V2H port uses two-space
indentation, no tabs, braces on their own line, a 78-column target, C block
comments, snake_case symbols, `rzv_` architecture prefixes, UPPER_CASE
macros, and the existing section-banner pattern.

**Check before committing in the submodule:**
```bash
cd platforms/nuttx/NuttX/nuttx
./tools/checkpatch.sh -f arch/arm/src/rzv/rzv_<driver>.c   # builds and runs nxstyle
```

### 1.3 NuttX Driver Engineering Guidance

These rules supplement the NuttX style and apply to hand-written PX4/NuttX
driver code. Keep the NuttX file header, required source path, copyright,
author/contact, license, and any existing SPDX attribution intact. Vendor and
generated files remain owned by their generator or configuration inputs.
Authors remain responsible for every accepted line, including AI-generated code.

**Comments and API contracts:**

- Comments explain stable engineering reasons: invariants, hardware
  constraints, ownership, races, timing, or required sequencing. Remove
  comments that only restate the code.
- Keep process metadata out of comments and file headers: plans, phases, audit
  findings, session labels, specification coordinates, repository or source
  links, porting provenance, and change history. Symbol names and meaningful
  hardware terms are appropriate.
- Do not add `TODO` or `FIXME` comments. A `Fix:` or `FIX:` prefix is also a
  process label and does not belong in a comment. Track unresolved work in the
  owning issue or document. The conventional commit type `fix(...)` remains
  valid.
- Use NuttX function headers with `Name:`, `Description:`, `Input Parameters:`,
  and `Returned Value:` sections; add `Assumptions/Limitations:` when needed.
  Document ranges, NULL handling, ownership, required context, and every
  success or error result. NuttX C code does not use Doxygen tags.

**State, scope, and types:**

- Keep objects at the narrowest scope that satisfies their lifetime. Use
  module-private `static` state for persistent state, and keep resettable state
  out of function-local `static` objects.
- Group related state by responsibility, writer, and reset lifetime. A struct
  does not make concurrent access atomic. Keep immutable tables and constants
  `static const`.
- Use fixed-width types for hardware-defined data and the existing NuttX/POSIX
  types for API results, sizes, and addresses. Preserve external ABI types and
  names, and encode non-obvious units in names such as `_hz`, `_mv`, or `_ns`.

**Interrupt and real-time work:**

- ISR work must be bounded and finite. Do not allocate, block, wait for an
  unbounded condition, retry without a cap, or perform logging or other heavy
  I/O in an ISR; defer that work to the appropriate task or worker.
- Measure worst-case execution on target, including callees and relevant interrupt
  interference, and keep it within the allocated period with margin. Recheck
  after compiler, optimization, code-generation, or linker-placement changes.
- Use RTOS-native synchronization that matches the execution context, such as
  NuttX mutexes, semaphores, or interrupt-safe primitives. `volatile` does not
  make a compound operation atomic, and local interrupt masking does not
  protect data shared with another core.

**Dependencies, configuration, and failure paths:**

- Include directly what the file uses; do not rely on transitive includes.
  Forward-declare opaque types in headers when possible and keep public
  headers minimal.
- Do not hand-edit generated or vendor sources. Change their generator or
  configuration input, and avoid unrelated reformatting in the same change.
- Keep defaults for independent physical signals independent, even when their
  numeric values match. Use separate configuration symbols and unit-bearing
  interface fields so one missing value cannot select another signal's limit.
- Check return values and document the sentinel or negative `errno` contract.
  Initialization failures must unwind resources in reverse order and leave a
  documented, predictable state; do not silently swallow errors.

---

## 2. Kconfig Conventions

**File Location:** Any `Kconfig` file in `arch/arm/src/rzv/` or board-specific dirs.

**Structure:**
```kconfig
# Comment describing the subsystem or driver family

menu "Driver Name (optional subsystem grouping)"

config SUBSYS_FEATURE_NAME
  bool "Feature description (shown in menuconfig)"
  default n
  depends on ARCH_CHIP_R9A09G057 && SOME_PREREQUISITE
  ---help---
    Detailed explanation of what this option enables.
    Wrap at ~70 cols; use 2-space indent for continuation.
    Reference related options, architectural constraints.

config SUBSYS_DRIVER_PARAM
  int "Parameter name"
  default 256
  range 0 4096
  depends on SUBSYS_FEATURE_NAME
  ---help---
    Parameter range and rationale.

endmenu
```

**Rules:**
- Use `---help---` (not `help`) for multi-line help blocks
- Indent menu contents by 2 spaces
- Indent `depends`, `range`, `default` by 2 spaces
- Use `bool`, `int`, `hex` for type (no misspellings)
- Document defaults and constraints in help text
- Reference hardware blocks explicitly (e.g., "requires ICU interrupt controller")

---

## 3. Commit Message Format

**Style:** Conventional Commits (v1.0.0)

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat` – new feature (driver, subsystem)
- `fix` – bug fix (existing behavior correction)
- `refactor` – code reorganization (no behavior change)
- `perf` – performance optimization
- `test` – test additions/updates
- `docs` – documentation only

**Scope:**
- Driver name (e.g., `gpt`, `serial`, `gpio`)
- Subsystem (e.g., `ipc`, `build`, `config`)
- Module path (e.g., `rzv_serial`)

**RZ/V2H port scope rule (mandatory for this port):**
Any commit that touches the RDK-RZ/V2H port — NuttX RZ/V2H drivers, board wiring under `boards/renesas/rdk-rzv2h*/`, `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`, `boards/arm/rzv/rdk-rzv2h/`, PX4 HAL glue for RZ/V2H, or docs under `docs/renesas/` — MUST use `rzv2h` as the scope:

```
feat(rzv2h): <subject>
fix(rzv2h): <subject>
feature(rzv2h): <subject>     # equivalent to feat(rzv2h); prefer feat
```

A driver-specific sub-scope may be appended with `/`:

```
feat(rzv2h/spi): add DMA-backed transfer path
fix(rzv2h/icu): clear pending bit before unmask
```

Rationale: makes port commits filterable by `git log --grep '(rzv2h'` and keeps history consistent across the multi-year port effort.

**Subject:**
- Imperative mood ("add", not "adds")
- Lowercase
- No period
- ≤50 characters

**Body:**
- Explain *why*, not what (code shows what)
- Describe the concrete behavior and rationale; mention compatibility or side
  effects when relevant
- Wrap at 72 columns
- Keep workflow or history narrative, plans, phases, audit or session labels,
  specification coordinates, `Fix:`/`FIX:` labels, repository paths, and
  porting-source links out of the subject and body
- Retain meaningful external issue or commit footers when relevant
- Include breaking changes or side effects

**Example:**
```
feat(rzv2h/serial): add SCIF-B multi-baud rate support

Extends rzv_serial driver to handle SCIF-B clock source
changes for UART baud rates 115200 and 921600. Reprograms the
CPG clock and baud divisor together when the source changes.

Fixes: #457
```

**Exception for .claude/ Changes:**
Per project rule: do NOT use `chore` or `docs` for `.claude/` directory changes (scripts, plans, internal docs). Use descriptive `feat`, `fix`, `refactor` instead. These are tooling for the team, not external packages.

---

## 4. File Naming

**Python, Go, Rust:** Follow language convention (snake_case)
**C/C++:** Follow local pattern; prefer kebab-case for new modules

**New Files:**
- Drivers: `rzv_<peripheral>.<c|h>` (matches NuttX pattern)
- Board wiring: `rzv2h_<feature>.c`
- PX4 HAL glue: `px4_hal_<interface>.c`
- Scripts/tools: kebab-case (e.g., `validate-rzv-config.sh`)

**Avoid:**
- Abbreviations (use `timer`, not `tmr`)
- CamelCase at file level (ok inside C++ classes)
- Redundant prefixes (file is already in `platforms/nuttx/...`)

---

## 5. Editor Configuration

**File:** `.editorconfig` (enforced at project root)

**Key Settings:**
- Insert final newline: always
- Line endings: LF (Unix)
- Max line length: 120
- Tab width: 8 (visual; respect indent style rule above)

**IDE Setup:**
- VS Code: install EditorConfig extension
- JetBrains IDEs: built-in support
- Vim: `vim-editorconfig` plugin

---

## 6. Pre-Commit Checks

The scoped Renesas runner inventories the parent and NuttX repositories
separately, skips symlinks, and uses each tree's native checker:

```bash
python3 Tools/renesas-coding-standards.py inventory --output /tmp/renesas-inventory.json
python3 Tools/renesas-coding-standards.py report --output /tmp/renesas-findings.json
python3 Tools/renesas-coding-standards.py check --family nuttx
python3 Tools/renesas-coding-standards.py fix --path boards/renesas/rdk-rzv2h/src/init.c --output /tmp/renesas-fix.json
python3 test/renesas-coding-standards-test.py
```

`report` and `check` leave source and Git indexes unchanged. `fix` requires
explicit paths, checks every proposal before starting replacements, and
preserves code tokens, directives, literals, attribution and file permissions.
Each replacement is atomic; detected concurrent edits stop the batch, which
can already contain completed replacements. A printed recovery manifest in
`/tmp` retains original and candidate bytes and replacement status; inspect
the actual file hashes before restoring an interrupted batch. Re-run `check` after applying
fixes. Exit codes are 0 for success, 1 for remaining eligible findings, and
2 for an input/tool error. Generated findings remain visible in the report.
Existing hardware-register macro spellings can have an explicit, reviewed
disposition in the ownership policy. It must bind the exact source and defining
header hashes and identify the token at the native diagnostic column. Raw
diagnostics remain in `findings`, with ownership evidence in
`reviewed_findings`; `unresolved_findings` controls the check result. Changed
source, a changed header, missing definitions, other symbols or other rules
require review again. This does not disable or modify the native checker.
Incomplete native checker coverage also returns 2 and prevents automatic
application; it must be repaired through source review. Tool failures print
a `/tmp` log location containing complete stdout and stderr.

Report destinations must be under `/tmp` or `plans/**/reports`; source and
tracked destinations are rejected. An explicit fix with no eligible C/C++
source is an error. Paths missing from the exact ownership manifest are
reported as unknown and cannot be automatically changed.

The runner covers the three `boards/renesas/rdk-rzv2h*` boards and the NuttX
RZ/V architecture, include and board directories. RA8 is outside its scope.
Full reports retain proposed diffs and
checker fingerprints. `Tools/renesas-coding-standards.json` records exact
generated-file ownership exceptions. Structural PX4 proposals and uncertain
NuttX edits require source review. NuttX automatic edits are limited to
whitespace, path and comment spacing; function contracts and engineering
rules still require maintainer review. Neither a checker pass nor a clean
build proves hardware behavior.

Reviewed function headers can be applied with `fix --contracts <file.json>`
on an explicit NuttX selection. This input contains `schema: 1` and a `files`
mapping from repository-relative paths to `sha256` and `functions`. Each
function entry supplies `description`, a `parameters` name-to-description
mapping, `returns`, and optional `assumptions`. The runner uses these explicit
contracts rather than inferring behavior. Review them against the actual
bodies and callees first. A changed source hash, unknown function, comment
terminator, altered token/directive/license, or new native diagnostic refuses
application. Contract text remains the reviewer's responsibility.

The project hook is `Tools/astyle/pre-commit`; use it together with the
language-specific checker owned by the relevant tree. It applies the configured
formatting, newline, whitespace, and indentation checks.

**To Bypass (rarely; requires justification):**
```bash
git commit --no-verify  # Skip all hooks
```
Do not use routinely; commit message will flag style violations for review.

---

## 7. Related References

- `.editorconfig` — line length, endings, indentation defaults
- `Tools/astyle/astylerc` — PX4 AStyle rules (C/C++)
- `platforms/nuttx/NuttX/nuttx/.github/nxstyle.json` and
  `platforms/nuttx/NuttX/nuttx/tools/nxstyle.c` — NuttX style checker inputs
- Architecture: [System Architecture](./system-architecture.md)
- Driver work: [Porting Playbook](./renesas/porting-playbook.md)

---

**Maintenance:** Update this document when astylerc or project rules change.
