# Personal Intent Compiler

A local-first Agent Skill that turns terse, implicit, or context-dependent language into a compact execution contract. It recovers recent context, preserves personal voice, challenges consequential assumptions, uses local memory with consent, discovers installed Skills, and routes the task to the smallest capable tool set.

The project does not claim to read minds or understand every profession by itself. It provides a general intent and routing layer; domain Skills, trusted sources, and high-stakes policies provide specialized judgment.

## Status

Early public alpha. The Skill utilities are dependency-free Python. An optional local MCP server uses the official Python MCP SDK and exposes the compiler as explicit host tools. Agent behavior still depends on the host model, installed Skills, and the quality of evaluation cases.

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

The server exposes five tools: `intent_compile`, `intent_check`, `intent_recall_corrections`, `intent_record_correction`, and `intent_record_outcome`. Read-only compilation and recall do not mutate memory access counters.

Generated host configurations force Python UTF-8 mode. When manually piping Chinese text through Windows PowerShell 5.1, set `$OutputEncoding`, console input/output encoding, `PYTHONUTF8=1`, and `PYTHONIOENCODING=utf-8`, or pass the text through a UTF-8 file. Normal MCP JSON stdio calls do not use the legacy PowerShell text pipeline.

## How It Works

1. Recover the active objective from the latest message, unfinished action, local profile, and relevant memory.
2. Choose a fast path for clear reversible work or a review path for ambiguity, consequential assumptions, and high-impact actions.
3. Compile an internal execution envelope with scope, authorization, context pointers, routing, and completion criteria.
4. Discover installed Skills dynamically and select one primary owner.
5. Execute and verify the task, then write memory only with appropriate authorization.

For complex or consequential actions, an intent preflight also retrieves relevant past corrections and checks reversibility, external effects, sensitive data, and authorization.

The system adapts to task-specific expertise, plain-language needs, accessibility preferences, and confirmed phrase meanings. It avoids treating occupation, personality type, age, dialect, or spelling as a deterministic model of the person.

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

## Repository Layout

```text
skills/intent-translator/  Agent Skill, references, and deterministic utilities
evals/                     Versioned behavior cases
tests/                     Cross-platform unit tests
install.ps1                Windows installer
install.sh                 macOS/Linux installer
```

## License

MIT. See [LICENSE](LICENSE).

Architectural inspirations and license notes are recorded in [docs/design-sources.md](docs/design-sources.md).
