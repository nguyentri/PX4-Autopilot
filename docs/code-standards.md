# Code Standards & Conventions

**Date:** 2026-10-01
**Status:** Active

This document defines coding conventions for the RDK-RZ/V2H port. Standards diverge between PX4 code and the NuttX submodule; follow the section matching your target directory.

---

## 1. Directory-Based Convention Split

### 1.1 PX4 Code (src/, boards/, platforms/nuttx/src/)

**Style:** PX4 AStyle (Linux variant)
**Configuration:** `Tools/astyle/astylerc`
**Tool:** `astyle` (or `Tools/astyle/fix_code_style.sh`)

**Rules:**
- Indent: 8-column tabs (force-tab=8)
- Style: Linux K&R with modifications
- Line length: ≤120 columns (enforced; see `.editorconfig`)
- Pointer alignment: right (align-pointer=name)
- Operators: padded (pad-oper, pad-header)
- Blocks: all break-blocks, keep-one-line-blocks intact
- Preprocessor: indented (indent-preprocessor, indent-cases)

**Validation:**
```bash
./Tools/astyle/check_code_style_all.sh       # Check all non-excluded files
./Tools/astyle/fix_code_style.sh <file.c>   # Auto-fix single file
```

### 1.2 NuttX Submodule (platforms/nuttx/NuttX/nuttx/**)

**Style:** NuttX coding standard (`Documentation/contributing/coding_style.rst` in the submodule)
**Rules:**
- Indent: 2 spaces per level, no tabs; braces on their own line, indented with the body
- Line length: 78 columns target (nxstyle warns beyond)
- Comments: `/* */` only, never `//`
- Naming: snake_case functions/variables, `rzv_` prefix for arch symbols, UPPER_CASE macros
- Section banners (`/****...` Included Files / Pre-processor Definitions / Private Functions / Public Functions) as in existing `rzv_*.c`

**Check before committing in the submodule:**
```bash
cd platforms/nuttx/NuttX/nuttx
./tools/checkpatch.sh -f arch/arm/src/rzv/rzv_<driver>.c   # builds and runs nxstyle
```

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
- Wrap at 72 columns
- Reference issues/commits when relevant
- Include breaking changes or side effects

**Example:**
```
feat(rzv2h/serial): add SCIF-B multi-baud rate support

Extends rzv_serial driver to handle SCIF-B clock source
changes for UART baud rates 115200 and 921600. Requires
CPG clock reconfig on mode switch; see rzv_clk.c for details.

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

**Hook Location:** `Tools/astyle/pre-commit`

**Runs:**
1. AStyle on modified C/C++ files (non-excluded)
2. Newline check (final LF)
3. Trailing whitespace removal
4. Tab/space indent rules (config-aware)

**To Bypass (rarely; requires justification):**
```bash
git commit --no-verify  # Skip all hooks
```
Do not use routinely; commit message will flag style violations for review.

---

## 7. Related References

- `.editorconfig` — line length, endings, indentation defaults
- `Tools/astyle/astylerc` — PX4 AStyle rules (C/C++)
- `platforms/nuttx/NuttX/nuttx/.nxstyle` — NuttX K&R rules
- Architecture: [System Architecture](./system-architecture.md)
- Driver work: [Design Guidelines](./design-guidelines.md), [Porting Playbook](./renesas/porting-playbook.md)

---

**Maintenance:** Update this document when astylerc or project rules change; keep the date header current.
