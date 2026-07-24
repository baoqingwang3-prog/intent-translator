# Personal Intent Compiler

[English](README.md) | [简体中文](README.zh-CN.md)

A local-first Agent Skill that turns terse, implicit, or context-dependent language into a compact execution contract. It recovers recent context, preserves personal voice, challenges consequential assumptions, uses local memory with consent, discovers installed Skills, and routes the task to the smallest capable tool set.

The project does not claim to read minds or understand every profession by itself. It provides a general intent and routing layer; domain Skills, trusted sources, and high-stakes policies provide specialized judgment.

## Start Here

Choose the smallest setup that matches your goal:

| Goal | Install | What changes on your computer |
|---|---|---|
| Let an agent follow the intent workflow | Skill only | Copies one Skill folder and creates a local profile on first setup |
| Let a host call deterministic intent tools | Skill + MCP | Also creates an isolated Python venv and host configuration snippets |
| Inspect compatibility first | Nothing | `detect_environment.py` and `intent-translator-doctor` are read-only |

For most first-time users, install the Skill only. Add MCP after the basic workflow behaves as expected. No account, API key, cloud model, or Obsidian vault is required.

## Status

Early public alpha, version `0.4.0`. The Skill utilities are dependency-free Python. An optional local MCP server uses the official Python MCP SDK and exposes the compiler as explicit host tools. Agent behavior still depends on the host model, installed Skills, and the quality of evaluation cases.

## Compatibility

| Component | Supported baseline | Degradation |
|---|---|---|
| Operating system | Windows 10/11, current macOS, mainstream Linux | Other systems receive an untested warning |
| Python | 3.10+ | Deterministic scripts stop with a diagnostic |
| Agent host | Codex, Claude Code, Cursor, Gemini CLI, Copilot/VS Code, OpenCode | Shared or manual Skill folder installation |
| Memory | Local SQLite by default | Session-only when persistence is unavailable |
| Obsidian | Optional | SQLite remains available |
| Domain expertise | Installed domain Skills and trusted sources | Base-agent response with explicit limitations |

Run the read-only environment report before installation:

```bash
python skills/intent-translator/scripts/detect_environment.py
```

## Install

Clone or download this repository, then run one installer from the repository root.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

`Bypass` applies only to this process and does not change the machine's permanent execution policy.

macOS or Linux:

```bash
sh ./install.sh
```

The installer detects known configuration directories. When none is present, it installs to the cross-host `~/.agents/skills/` directory. Existing installations are not overwritten unless `-Replace` or `--replace` is supplied.

Examples:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -TargetHost Codex
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -TargetHost All -Replace
```

```bash
sh ./install.sh --host gemini
sh ./install.sh --host all --replace
```

Restart or reload the agent host after installation. Personal configuration is created at `~/.intent-translator/profile.json`; memory defaults to `~/.intent-translator/memory.db`. Neither belongs in this repository.

Installers report the installed and available versions, stage upgrades before replacing the active Skill, and restore the previous version when installation fails. Check without changing files:

```powershell
.\install.ps1 -TargetHost Codex -CheckOnly
```

```bash
sh ./install.sh --host codex --check
```

Uninstalling preserves local profile and memory unless an explicit purge confirmation is supplied:

```powershell
.\uninstall.ps1 -TargetHost Codex
```

```bash
sh ./uninstall.sh --host codex
```

### Optional MCP runtime

The MCP runtime makes the deterministic preflight callable instead of relying on prompt instructions alone. It uses local stdio transport and does not call a model or cloud service.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-mcp.ps1
```

```bash
sh ./install-mcp.sh
```

Installers create an isolated venv under `~/.intent-translator/mcp/` and generate configuration snippets for Codex, Claude, Cursor, Gemini, Copilot, and OpenCode under `~/.intent-translator/mcp-configs/`. Windows users may pass `-ConfigureCodex` to append a new Codex entry when one does not already exist.

The server exposes seven tools: `intent_compile`, `intent_check`, `intent_recall_corrections`, `intent_record_correction`, `intent_suggest_correction`, `intent_confirm_correction`, and `intent_record_outcome`. Read-only compilation and recall do not mutate memory access counters.

Generated host configurations force Python UTF-8 mode. When manually piping Chinese text through Windows PowerShell 5.1, set `$OutputEncoding`, console input/output encoding, `PYTHONUTF8=1`, and `PYTHONIOENCODING=utf-8`, or pass the text through a UTF-8 file. Normal MCP JSON stdio calls do not use the legacy PowerShell text pipeline.

Check an installation without exposing exact home-directory paths:

```bash
intent-translator-doctor
intent-translator-doctor --json
```

Remove only the MCP runtime and generated snippets while preserving profile and memory:

```powershell
.\uninstall-mcp.ps1
```

```bash
sh ./uninstall-mcp.sh
```

## How It Works

1. Recover the active objective from the latest message, unfinished action, local profile, and relevant memory.
2. Choose a fast path for clear reversible work or a review path for ambiguity, consequential assumptions, and high-impact actions.
3. Compile an internal execution envelope with scope, authorization, context pointers, routing, and completion criteria.
4. Discover installed Skills dynamically and select one primary owner.
5. Execute and verify the task, then write memory only with appropriate authorization.

For complex or consequential actions, an intent preflight also retrieves relevant past corrections and checks reversibility, external effects, sensitive data, and authorization. Search uses SQLite FTS5 plus Chinese n-grams. Memory conflicts remain visible, project rules can shadow global defaults, and sensitive memories require a retention period.

Brief feedback such as `太复杂了` becomes a pending correction and is stored durably only after one short confirmation. Decision receipts can show the resolved meaning, memory IDs, selected Skill, and confirmation boundary without exposing hidden model reasoning.

The system adapts to task-specific expertise, plain-language needs, accessibility preferences, and confirmed phrase meanings. It avoids treating occupation, personality type, age, dialect, or spelling as a deterministic model of the person.

Routing uses explicit aliases for known Skills and conservative multi-keyword matching against installed Skill descriptions. This allows third-party professional Skills to participate without adding every profession to this repository.

## Optional Adapters

Two adapters ship disabled:

- `session-hooks`: host-neutral session start/end snapshots. It does not register host hooks automatically.
- `reversible-context`: stores exact context sections locally by hash and emits compact retrieval markers.

Enable them explicitly in the local profile after reviewing `skills/intent-translator/references/optional-adapters.md`.

## Commands

```bash
# Discover installed Skills
python skills/intent-translator/scripts/discover_skills.py

# Initialize and validate a local profile
python skills/intent-translator/scripts/init_profile.py init
python skills/intent-translator/scripts/init_profile.py validate
python skills/intent-translator/scripts/init_profile.py set-phrase --phrase "continue" --meaning "Resume the current unfinished flow"

# Add and search local memory
python skills/intent-translator/scripts/memory_store.py add --kind preference --scope global --text "Prefer concise answers"
python skills/intent-translator/scripts/memory_store.py search --query "concise answers" --scope global

# Govern conflicts and confirm a brief correction
python skills/intent-translator/scripts/memory_store.py add --kind preference --scope global --conflict-key response-detail --text "先给结论" --confidence confirmed
python skills/intent-translator/scripts/memory_store.py correction-suggest --message "太复杂了" --previous-behavior "Used a long response for a simple confirmation"
python skills/intent-translator/scripts/memory_store.py correction-confirm --id 1

# Record a correction and check a consequential intent before acting
python skills/intent-translator/scripts/memory_store.py correction-add --scope global --trigger "brief approval" --correction "approve only the proposed next action"
python skills/intent-translator/scripts/memory_store.py intent-check --goal "publish repository" --impact high --reversible no --external

# Scan context before sending it to an external service
python skills/intent-translator/scripts/privacy_guard.py --redact < context.txt

# Create and score evaluation predictions
python skills/intent-translator/scripts/evaluate_predictions.py --cases evals/cases.jsonl --write-template work/predictions.jsonl
python skills/intent-translator/scripts/evaluate_predictions.py --cases evals/cases.jsonl --predictions work/predictions.jsonl --threshold 0.85

# Compare a naive baseline with the deterministic compiler
intent-translator-eval --cases evals/cases.jsonl --output work/ab-report.json

# Diagnose an installation without printing exact home paths
intent-translator-doctor --json
```

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q skills src tests
```

The GitHub Actions matrix is configured for Windows, macOS, and Linux with Python 3.10 and 3.12.

### Current deterministic A/B

On the isolated 24-case regression set, the naive baseline scores 60.4% across routing fields and misses 7 required confirmations. The compiler scores 100% and misses 0 required confirmations, with about 11.5 ms mean local latency on the development machine. This is a regression result, not a claim of 100% real-user understanding; live-model and out-of-distribution evaluation remain required before a stable release.

## Privacy And Safety

- Profiles and memory remain local by default.
- Public files contain no user-specific memory or machine paths.
- Secrets, authentication codes, payment data, and unnecessary sensitive details must not be stored.
- Medical, legal, financial, and similarly high-stakes requests raise evidence and confirmation requirements.
- Users retain the ability to inspect, correct, export, and delete memory.
- No telemetry is collected by this repository. Diagnostic output hides exact home paths unless `--show-paths` is supplied.

## Public Alpha Limits

- The deterministic regression set is small and intentionally cannot prove general understanding.
- New languages, dialects, professions, and third-party Skills need out-of-distribution evaluation.
- Host auto-invocation behavior varies; installing the MCP server does not guarantee every host will call it on every message.
- The optional semantic model layer is not implemented, so novel metaphors and indirect language still depend on the host model.

See [docs/launch-readiness.md](docs/launch-readiness.md) for the prioritized release risks.

## Repository Layout

```text
skills/intent-translator/  Agent Skill, references, and deterministic utilities
src/intent_translator_mcp/ Optional local stdio MCP server and deterministic A/B evaluator
evals/                     Versioned behavior cases
tests/                     Cross-platform unit tests
install.ps1                Windows installer
install.sh                 macOS/Linux installer
uninstall.ps1              Windows uninstaller
uninstall.sh               macOS/Linux uninstaller
uninstall-mcp.ps1          Windows MCP runtime uninstaller
uninstall-mcp.sh           macOS/Linux MCP runtime uninstaller
```

## License

MIT. See [LICENSE](LICENSE).

Architectural inspirations and license notes are recorded in [docs/design-sources.md](docs/design-sources.md).
