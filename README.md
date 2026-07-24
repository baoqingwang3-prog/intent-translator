# Personal Intent Compiler

A local-first Agent Skill that turns terse, implicit, or context-dependent language into a compact execution contract. It recovers recent context, preserves personal voice, challenges consequential assumptions, uses local memory with consent, discovers installed Skills, and routes the task to the smallest capable tool set.

The project does not claim to read minds or understand every profession by itself. It provides a general intent and routing layer; domain Skills, trusted sources, and high-stakes policies provide specialized judgment.

## Status

Early public alpha. The deterministic utilities are dependency-free Python and covered by unit tests. Agent behavior still depends on the host model, installed Skills, and the quality of evaluation cases.

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
```

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q skills tests
```

The GitHub Actions matrix is configured for Windows, macOS, and Linux with Python 3.10 and 3.12.

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
