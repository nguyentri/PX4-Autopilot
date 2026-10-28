# Design System & UX/AX Guidelines: PX4-NuttX Dashboard

> Unified design system, visual taxonomy, and user/agent experience guidelines for the PX4-NuttX VS Code extension (`Tools/vscode_extension/`).

---

## 1. Product & Art Direction

- **Product Category**: Embedded Systems Developer Tool / Multi-Core Firmware IDE Dashboard
- **Target Audience**: Firmware engineers, drone developers, robotics researchers, and AI coding agents
- **Art Direction**: Industrial, technical, precise, and trustworthy. High information density with instant visual scannability, clear hierarchical distinction, and zero decorative noise.
- **Platform**: VS Code Extension API (`^1.85.0`) adhering to VS Code UX Guidelines and Web Content Accessibility Guidelines (WCAG 2.1 AA).

---

## 2. Color Palette & Semantic Tokens

The extension uses VS Code Theme Color tokens to follow the active theme. Contrast
across dark, light, and high-contrast themes requires native workbench verification.

| Semantic Purpose | Theme Color Token | Fallback Hex (Dark Theme) | Usage |
|------------------|-------------------|---------------------------|-------|
| **Pass / Ready / OK** | `testing.iconPassed` / `charts.green` | `#89D185` | Ready targets, verified pairs, passed doctor checks |
| **Warning / Attention** | `problemsWarningIcon.foreground` | `#CCA700` | Recovery required, outdated source, manual-only routes |
| **Error / Blocked** | `testing.iconFailed` / `problemsErrorIcon.foreground` | `#F14C4C` | Missing toolchain, prerequisite failure, build error |
| **Informational / Neutral** | `descriptionForeground` | `#CCCCCC` | Descriptions, hardware architecture, paths, hashes |
| **Focus / Highlight** | `focusBorder` / `charts.blue` | `#3794FF` | Active selection, primary CTA links, status bar |
| **Inactive / Gated** | `disabledForeground` | `#666666` | Disabled commands, unavailable routes |

---

## 3. Codicon Taxonomy

Icons must be semantically accurate and consistent across Tree Views, QuickPicks, Menus, and the Command Palette. Emojis are strictly prohibited as interface icons.

### Hardware & Profile Elements
- Target Board: `$(circuit-board)`
- Execution Core / CPU: `$(chip)` or `$(cpu)`
- Multicore Pair Group: `$(layers)`
- Firmware Binary / ELF: `$(file-binary)`
- Configuration / Mode: `$(settings-gear)`
- Debug Probe (J-Link): `$(plug)`
- Serial UART / RTT Console: `$(terminal)`

### Operational Actions
- Build (Incremental): `$(play)`
- Clean Rebuild: `$(trash)`
- Diagnostic / Health Check: `$(pulse)`
- Guarded Load (RAM): `$(cloud-upload)`
- Build & Load: `$(rocket)`
- Cortex-Debug Attach: `$(debug-alt)`
- Debug Stop / Disconnect: `$(debug-stop)` or `$(stop-circle)`
- Refresh / Re-scan: `$(refresh)`
- Resume In-Progress: `$(debug-continue)`
- Save As / Variant: `$(save-as)`
- Rename / Edit: `$(edit)`
- Validate / Checklist: `$(checklist)`

### Status Indicators
- Passed / Ready: `$(pass-filled)` or `$(check)`
- In-Progress / Building / Loading: `$(sync~spin)`
- Preparation pending / Resume required: static `$(debug-pause)`
- Warning / Needs Attention: `$(warning)`
- Blocked / Untrusted: `$(lock)`
- History / Journal: `$(history)`

---

## 4. Typography & Information Hierarchy

- **Header / Primary Label**: Standard VS Code font (`editor.fontFamily`), regular weight, standard system size. Kept concise (1-3 words).
- **Secondary Description**: Compact muted text. Contains dynamic states (e.g., `42.5 KB (cr8_0)` or `Active · use Stop Sessions before switching`).
- **Rich Hover Tooltips**: All tree items and status bar items provide formatted `vscode.MarkdownString` tooltips:
  - Header: Bold label with backtick code span: `**Target:** \`rdk-rzv2h_default\``
  - Property list: Unordered bulleted list with clear key-value separation
  - Blockquotes: Used for warnings or prerequisites (`> [!WARNING] ...`)
  - Keyboard shortcut hints: Italicized keyboard shortcuts (`*Shortcut: Ctrl+Alt+K B*`)

Firmware chords require an initialized, trusted firmware workspace and are disabled
in text inputs and terminals. Pending preparation is durable resume state; animate
the Pair row only while image preparation, a firmware workflow, or a target
transition runs.

---

## 5. Interaction Patterns & Feedback Rules

1. **Immediate Visual Feedback**:
   - Operations taking >300ms must report progress using `vscode.window.withProgress` with explicit `cancellationToken` support.
   - Status bar updates immediately upon profile switch or probe selection.
2. **Actionable Error Remediations**:
   - Error notifications never lead to dead ends; they provide actionable modal buttons (e.g. `View Local Guide`, `Run Doctor`, `Recover Load`).
3. **Empty States & Welcome Views**:
   - Every view includes a `viewsWelcome` contribution offering clear introductory guidance and 1-click Markdown command links with Codicons.
4. **Non-Destructive Workflows**:
   - Cortex-Debug configurations are computed entirely in-memory; user `launch.json` files are never overwritten.
   - Guarded RAM loading protects non-volatile flash memory from corruption.
   - Build tasks respect workspace-wide file locks (`flock`) to avoid source collisions.

---

## 6. AX (Agent eXtensibility) Standards

To ensure the extension remains discoverable and controllable by autonomous coding agents and LLM tools:
- `llms.txt` provides an indexed executive summary adhering to the llms.txt standard.
- `llms-full.txt` provides the complete API, CLI argument list, exit code dictionary, and JSON schema catalog.
- JSON Schema Draft 7 files in `schemas/` serve as the single source of truth for all data structures.
- CLI operations in `Tools/firmware-workspace.py` emit deterministic JSON when `--json` is passed.
