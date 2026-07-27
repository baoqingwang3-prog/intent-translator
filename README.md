# Personal Intent Compiler

[English](README.md) | [简体中文](README.zh-CN.md)

**Before an Agent acts, turn conversational wording into a visible task contract: resume the pending action, preserve prohibitions, choose a Skill, and show the local compiler state and this preflight result.**

A local-first Agent Skill that turns terse, implicit, or context-dependent language into a compact execution contract. It recovers recent context, preserves personal voice, challenges consequential assumptions, uses local memory with consent, discovers installed Skills, and routes the task to the smallest capable tool set.

It provides bounded interpretations, routing recommendations, and authorization preflight results. It becomes a mandatory gate only when the Agent host actually integrates and calls the MCP tools.

The project does not claim to read minds or understand every profession by itself. It provides a general intent and routing layer; domain Skills, trusted sources, and high-stakes policies provide specialized judgment.

The first Alpha is for people who frequently use Codex, Claude Code, or similar agents, keep several Skills installed, continue work with short natural-language messages, and want visible preflight signals intended to reduce misunderstanding, wrong routing, or over-broad authorization.

| You are... | Start here | What you get |
|---|---|---|
| A user | [Start Here](#start-here) | Install, onboarding, Studio, and plain-language limits |
| An Agent or host integrator | [Integration Contract](docs/integration-contract.md) | Request fields, response contract, confirmation state machine, and failure behavior |
| A contributor or release engineer | [Release Gate](docs/release-gate.md) and [Launch Readiness](docs/launch-readiness.md) | Tests, packaging, evidence boundaries, and remaining release P0s |

| What the user says | What the preflight should report |
|---|---|
| `Continue` | Restores the specific pending action and its constraints |
| `Okay, compare the options; do not publish` | Keeps the prohibition and does not treat `Okay` as broader permission |
| `Search GitHub for high-star Agent Skills` | Routes the search action to Agent Reach instead of confusing the object with Skill creation |
| A natural-language correction | Replays the corrected meaning in an isolated local profile |

## Start Here

Choose the smallest setup that matches your goal:

| Goal | Install | What changes on your computer |
|---|---|---|
| Let an agent follow the intent workflow | Skill only | Copies one Skill folder and creates a local profile on first setup |
| Let a host call deterministic intent tools | Skill + MCP | Also creates an isolated Python venv and host configuration snippets |
| Inspect compatibility first | Nothing | These checks read local environment and configuration without modifying the profile, database, or runtime |

For most first-time users, install the Skill only. Add MCP after the basic workflow behaves as expected. No account, API key, cloud model, or Obsidian vault is required.

### Fastest first install: no Git required

If Git, a local proxy, or an Agent's documentation helper is unavailable, do not debug those services before trying the Skill:

1. Download [`main.zip`](https://github.com/baoqingwang3-prog/intent-translator/archive/refs/heads/main.zip).
2. Extract it and open the folder containing `install.ps1`, `install.sh`, and `pyproject.toml`.
3. Ask the Agent to read only the local `README.md`, or run the Skill-only installer directly.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -TargetHost Codex
```

macOS or Linux:

```bash
sh ./install.sh --host codex
```

If output mentions an inactive proxy such as `127.0.0.1:7890`, or an optional documentation helper returns `403`, that does not mean this public repository or the Skill requires authorization. Stop the automatic clone or documentation lookup and use the ZIP path above. Do not change global Git settings unless you own that configuration.

Developers embedding the compiler can use the Python SDK directly without MCP:

```python
from intent_translator_mcp import IntentTranslator

sdk = IntentTranslator()
result = sdk.compile("Search GitHub for high-star Agent Skills", semantic_mode="off")

print(result.contract.operation)  # search
print(result.selected_skill)      # agent-reach, when installed
print(result.tool_decision)       # allow / human_review / deny
```

The SDK defaults to a typed result with no generated host prompt. See [Python SDK](docs/sdk.md).

After Skill-only installation, you can start talking immediately in generic mode. After installing the optional MCP runtime, either ask the agent to set up Intent Translator or run the three-minute setup. It asks only about local memory, ambiguity handling, and response tone:

```bash
intent-translator-onboard
```

With Skill-only installation, run the path printed by the installer instead, for example `python ~/.agents/skills/intent-translator/scripts/onboard.py start --language en`.

Every question can be skipped. See [First Three Minutes](docs/first-run.md).

### Try the local Studio

After installing the optional MCP package, start the local compiler inspection UI:

```bash
intent-translator-studio --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`. The Studio requires no API key and shows the current interpretation, non-obvious wording map, selected Skill, local memory sources, authorization boundary, actual runtime version, and whether the host needs a restart. It also exposes a copyable, sanitized typed SDK contract and reports whether the result used the deterministic local path or an optional semantic adapter; Studio compilation never generates the host prompt. Routing distinguishes installed selection from intended-but-unverified capability and never claims the host activated a Skill. It inspects the compiler and does not execute the task. A healthy Studio does not prove that another Agent host calls MCP on every turn. If the local compiler is unavailable, the page reports degraded status.

## Status

P1 Alpha, version `0.7.1a2`. GitHub-hosted evidence applies only to the exact commit that passed Windows, macOS, Linux, package, browser, and CodeQL jobs; it is never inherited from an older release. The documented 3-5 person stranger-user trial remains incomplete. The Skill utilities are dependency-free Python. An optional local MCP server uses the official Python MCP SDK and exposes the compiler as explicit host tools. Agent behavior still depends on the host model, installed Skills, and the quality of evaluation cases.

## Compatibility

Host support is intentionally narrower than the installer list. See the explicit [host support matrix](docs/support-matrix.md) for Alpha-supported, experimental, Skill-only, and MCP-unverified combinations.

| Component | Supported baseline | Degradation |
|---|---|---|
| Operating system | Windows 10/11, current macOS, mainstream Linux | Other systems receive an untested warning |
| Python | 3.10+ | Deterministic scripts stop with a diagnostic |
| Agent host | Codex, Claude Code, Cursor, Gemini CLI, Copilot/VS Code, OpenCode | Shared or manual Skill folder installation |
| Memory | Local SQLite by default | Session-only when persistence is unavailable |
| Obsidian | Optional | SQLite remains available |
| Domain expertise | Installed domain Skills and trusted sources | Base-agent response with explicit limitations |

Run the non-modifying environment report before installation. It reads local environment and configuration but does not change them:

```bash
python skills/intent-translator/scripts/detect_environment.py
```

## Install

Clone or download this repository, ensure Python 3.10 or newer is available, then enter the directory containing `pyproject.toml` before running an installer.

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

For a Codex-first Windows setup that installs the Skill and MCP, applies the reusable student profile pack, manages the Codex rules block, and runs the doctor:

```powershell
.\setup-codex.ps1 -StudyGoal "professional certification","language exam" -ObsidianVaultName "My Vault" -ObsidianVaultPath "D:\My Vault" -EnableShadow
```

The repository contains a generic `university-student` base pack plus a `student-exam-prep` goal extension. Shadow evaluation remains off unless `-EnableShadow` is supplied. Goals, current subjects, vault locations, progress, mistakes, and correction history are written to the local profile or database and must not be committed. See [docs/student-profile.md](docs/student-profile.md).

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

To remove the Skill and the complete local profile and memory store, use the explicit destructive confirmation:

```powershell
.\uninstall.ps1 -TargetHost Codex -PurgeData -ConfirmPurge DELETE-LOCAL-DATA
```

```bash
sh ./uninstall.sh --host codex --purge-data --confirm-purge DELETE-LOCAL-DATA
```

### Optional MCP runtime

The MCP runtime makes the deterministic preflight callable instead of relying on prompt instructions alone. It uses local stdio transport and does not call a model or cloud service.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-mcp.ps1 -ConfigureCodex
```

```bash
sh ./install-mcp.sh --configure-codex
```

For an isolated test or a portable environment, pass `-HomeDirectory`, `-RuntimeRoot`, and `-ConfigDir`. Keep a custom Windows runtime root short because transitive dependency paths may still be subject to the system path-length limit. The POSIX installer accepts the equivalent `INTENT_TRANSLATOR_HOME`, `INTENT_TRANSLATOR_RUNTIME`, and `INTENT_TRANSLATOR_CONFIG_DIR` environment variables.

Installers create a versioned isolated venv under `~/.intent-translator/mcp/runtimes/` and generate configuration snippets for Codex, Claude, Cursor, Gemini, Copilot, and OpenCode under `~/.intent-translator/mcp-configs/`. Each snippet points at that host's own Skill directory instead of assuming one shared Codex or Agents path. Install the Skill for a host before applying its snippet. Versioned runtimes avoid Windows upgrade failures when an older MCP process is still running.

Codex registration uses the native `codex mcp add` command with an explicit `CODEX_HOME`; the installer never rewrites `config.toml` itself. If Codex is open, registration is deliberately skipped so shutdown cannot overwrite the change. Close Codex, run the single repair command printed by the installer, and reopen Codex. The repair is idempotent and restores the previous registration when a replacement add fails.

For an optional Codex student setup that installs the Skill and MCP, applies the university base pack and exam-prep extension, and adds a replaceable managed rule block, run `setup-codex.ps1`. It backs up an existing global `AGENTS.md`; university details, study goals, and Obsidian locations are supplied locally and are never bundled in the repository.

The server exposes fourteen tools, including onboarding status/application, memory defense, and student state. Onboarding choices stay local and are all skippable. Defense status never exposes quarantined text; student state keeps sensitive items out of default context and Obsidian mirrors. Shadow evaluation is opt-in and stores no utterance preview by default. Study pointers can explicitly sync a generated index to a configured Obsidian vault without scanning the vault. Read-only recall uses an existing database without writes; `memory.adapter=none` creates and recalls no memory database.

When the same Skill exists in multiple roots, discovery uses the first configured root. Explicit `INTENT_TRANSLATOR_SKILL_ROOTS` entries win, followed by host-specific roots such as Codex, then shared roots such as `~/.agents/skills`. `discover_skills.py` reports alternates so duplicate installations are visible instead of silently merged.

Generated host configurations force Python UTF-8 mode. When manually piping Chinese text through Windows PowerShell 5.1, set `$OutputEncoding`, console input/output encoding, `PYTHONUTF8=1`, and `PYTHONIOENCODING=utf-8`, or pass the text through a UTF-8 file. Normal MCP JSON stdio calls do not use the legacy PowerShell text pipeline.

Check an installation without exposing exact home-directory paths:

```bash
intent-translator-doctor
intent-translator-doctor --json
intent-translator-doctor --json > intent-translator-diagnostic.json
```

The JSON form is a shareable redacted diagnostic: it includes versions, host snippets, restart need, and configuration health without profile text or exact private paths. The doctor distinguishes `not-installed`, `installed-not-registered`, `registered-pending-restart`, `registered-stale`, and the active runtime reported by a connected MCP call. It lists every detected Skill copy and version, compares the active Skill with the installed MCP runtime and doctor package, and prints one repair command when registration is missing or stale. A newly installed runtime does not replace an MCP process already held open by a running host.

### One-minute verification

1. Restart or reload the Agent host, then run `intent-translator-doctor`.
2. Start Studio and submit `Okay, compare the options; do not publish`.
3. Verify that `publish` appears as a prohibited action and that Studio labels itself as an inspection surface.
4. Ask the Agent host to check the same sentence with Intent Translator. If it cannot show a current decision receipt or MCP result, the compiler may be installed but that host turn was not preflighted.

Remove only the MCP runtime and generated snippets while preserving profile and memory:

```powershell
.\uninstall-mcp.ps1
```

```bash
sh ./uninstall-mcp.sh
```

### Optional semantic model

The semantic layer is a provider-neutral JSON command adapter. It can call a local model runner or a user-supplied cloud wrapper, but no provider, model, account, or API key is bundled. Configure the command as a JSON argument array, never as a shell string:

```bash
export INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON='["my-model-wrapper", "--json"]'
export INTENT_TRANSLATOR_SEMANTIC_NAME='my-local-model'
```

Or point directly at a local server implementing `/v1/chat/completions`:

```bash
export INTENT_TRANSLATOR_SEMANTIC_PROVIDER='chat-completions'
export INTENT_TRANSLATOR_SEMANTIC_BASE_URL='http://127.0.0.1:11434/v1'
export INTENT_TRANSLATOR_SEMANTIC_MODEL='your-local-model'
```

Mark a wrapper that sends data off-device with `INTENT_TRANSLATOR_SEMANTIC_EXTERNAL=1`. The first compile returns a short-lived semantic confirmation challenge. After the user confirms the exact pending input, the host resubmits that action with the one-time `confirmation_receipt` and the relevant semantic allow flag. Caller booleans alone never authorize egress. Model output may raise risk or request clarification, but cannot lower deterministic risk, grant authorization, or replace the identity of an executable objective; a materially different model goal is exposed only as a review alternative.

See [docs/semantic-layer.md](docs/semantic-layer.md) for the JSON contract and threat model.

## How It Works

1. Recover the active objective from the latest message, unfinished action, local profile, and relevant memory.
2. Choose a fast path for clear reversible work or a review path for ambiguity, consequential assumptions, and high-impact actions.
3. Compile an internal execution envelope with scope, action-bound authorization, context pointers, routing, and completion criteria.
4. Discover installed Skills dynamically and select one primary owner.
5. Execute and verify the task, then write memory only with appropriate authorization.

For complex or consequential actions, an intent preflight also retrieves relevant past corrections and checks reversibility, external effects, sensitive data, and authorization. Search uses SQLite FTS5 plus Chinese n-grams. Memory conflicts remain visible, project rules can shadow global defaults, and sensitive memories require a retention period. Every memory carries provenance and a trust level: explicit user memory has trusted provenance but is still context evidence, not guaranteed fact or permission. Model/file/web memory is non-authoritative evidence, and instruction-like or authority-claiming content is quarantined. Recalled memory is never executable authority.

Brief feedback such as `太复杂了` becomes a pending correction and is stored durably only after one short confirmation. Decision receipts can show the resolved meaning, memory IDs, selected Skill, and confirmation boundary without exposing hidden model reasoning.

Consequential actions use a short-lived, one-time confirmation receipt bound to the exact normalized action and scope. Changing a file, branch, recipient, destination, or operation invalidates the receipt. The legacy `authorization` request field is an untrusted compatibility hint and cannot authorize publication, external transfer, destructive work, or sensitive egress by itself.

MCP responses are compact by default: full corrections, memories, student state, routing candidates, and runtime diagnostics stay behind `include_diagnostics=true`. Unrelated requests do not receive study goals or student state. Set `include_prompt=false` when the host consumes the structured envelope directly.

Each response also includes a validated `intent_contract` with the original wording, goal, action owner, object, constraints, artifacts, destination, scope, required slots, risk, authorization state, alternatives, and source map. Missing required slots keep execution disabled. Final confidence is calibrated from local correction and routing evidence rather than a semantic model's self-reported confidence.

The system adapts to task-specific expertise, plain-language needs, accessibility preferences, and confirmed phrase meanings. It avoids treating occupation, personality type, age, dialect, or spelling as a deterministic model of the person.

Routing uses explicit aliases for known Skills and conservative multi-keyword matching against installed Skill descriptions. This allows third-party professional Skills to participate without adding every profession to this repository.

Intent Translator and Agent Reach are complementary. Intent Translator proposes **a bounded interpretation, validates action-bound confirmation receipts, and recommends which Skill owns the action**. Agent Reach decides **where on the internet to search and how to retrieve the result**. The control layer can route a search to Agent Reach; it does not replace an internet-access layer.

## Optional Plugins

Two local plugins ship disabled:

- `memory-breathing`: loads a small set of relevant project handoffs at session start and saves bounded handoffs, decisions, and corrections at session end.
- `reversible-context`: stores exact context sections with source pointers and SHA-256 markers, then verifies integrity when expanding them.

Both use a host-neutral JSON plugin contract, perform no network access, and never register hooks automatically. Enable and inspect them with:

```bash
python skills/intent-translator/scripts/plugin_manager.py list
python skills/intent-translator/scripts/plugin_manager.py enable memory-breathing
python skills/intent-translator/scripts/plugin_manager.py enable reversible-context
```

For Windows PowerShell, put invocation payloads in a UTF-8 JSON file and use `--input` instead of piping inline Chinese text:

```powershell
python skills/intent-translator/scripts/plugin_manager.py invoke reversible-context pack --input .\payload.json
```

See `skills/intent-translator/references/optional-adapters.md` for lifecycle payloads and retrieval examples.

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

# Run the public synthetic conformance benchmark
intent-translator-bench --system compiler --output work/intentbench-v1-compiler.json --fail-on-dangerous-miss --minimum-field-accuracy 1.0
intent-translator-bench --system keyword --output work/intentbench-v1-keyword.json

# Compare no-model, helpful-model, and adversarial-model fixtures
intent-translator-semantic-eval --cases evals/semantic_cases.jsonl

# Diagnose an installation without printing exact home paths
intent-translator-doctor --json

# List or invoke disabled-by-default local plugins
python skills/intent-translator/scripts/plugin_manager.py list

# Review silent shadow samples and sync the managed pointer index
intent-translator-study shadow-review
intent-translator-study pointer-list --exam-goal "language exam"
intent-translator-study pointer-sync
```

## Test

```bash
python -m unittest discover -s tests -v
python -m compileall -q skills src tests scripts
python scripts/release_gate.py --mode quick
python scripts/release_gate.py --mode full
```

The published Alpha line has passed GitHub-hosted Windows, macOS, and Linux jobs with Python 3.10 and 3.12 plus the independent Studio browser smoke. Each later release commit must earn its own remote evidence.

### Current deterministic evidence

The legacy 24-case internal regression compares a deliberately naive baseline with the deterministic compiler. It remains useful for backward compatibility but is not the public evidence contract.

[IntentBench v1](benchmarks/intentbench-v1/README.md) adds 32 public synthetic cases, 12 preregistered fields, exact missing-prediction penalties, constraint and dangerous-miss metrics, external prediction templates, and explicit anti-gaming rules. [IntentBench v2](benchmarks/intentbench-v2/README.md) expands the public development contract to 100 English, Chinese, and mixed-language cases across roles, safety boundaries, ambiguous actions, and third-party Skills. The repaired compiler passes both public development sets with zero dangerous misses.

The compiler's 100% conformance score is not an independent accuracy claim: the gold labels were visible and earlier runs were used to repair defects. `intent-translator-challenge` prepares evaluator-held bundles without public gold, while `intent-translator-same-model-eval` prepares and scores a paired with-Skill/without-Skill run only when model, tool, prompt, and profile conditions match. These are protocols, not independent results, until an outside evaluator runs them.

Compile and gateway responses include a bounded invocation receipt. `scripts/codex_host_trace_smoke.py` links one operator-driven Codex machine preflight to an actual local tool result and execution verification. Its claim is deliberately narrow: it does not prove that Codex, Claude, Cursor, or another host automatically invokes the preflight on every turn. Execution mismatches can be exported hash-only with `intent-translator-feedback`; consented trial metrics can be initialized, recorded, summarized, and deleted with `intent-translator-trial`. Neither tool stores raw utterances by default or promotes failures into benchmarks without human review.

Ambiguous integration requests use a project-scoped interpretation gate. A confirmed correction can apply within that project without leaking elsewhere, and `1`, `first`, or a button option ID resolve against the same pending choice. Recipient adaptation can produce a plain-language, investor, or engineering local preview, but audience labels never authorize sending files or disclosing source, diagnostics, memory, profiles, or secrets.

## Privacy And Safety

- Profiles and memory remain local by default.
- Public files contain no user-specific memory or machine paths.
- Secrets, authentication codes, payment data, and unnecessary sensitive details must not be stored.
- Medical, legal, financial, and similarly high-stakes requests raise evidence and confirmation requirements.
- Users retain the ability to inspect, correct, export, and delete memory.
- No telemetry is collected by this repository. Diagnostic output hides exact home paths unless `--show-paths` is supplied.

## Public Alpha Limits

- The deterministic regression set is small and intentionally cannot prove general understanding.
- IntentBench v1 and v2 are public synthetic development data, not hidden test sets or real-user evidence.
- Blinded challenge and same-model A/B tooling is prepared, but no independent result is claimed by this release.
- New languages, dialects, professions, and third-party Skills need out-of-distribution evaluation.
- Host auto-invocation behavior varies; an invocation receipt proves the compiler observed a call, not that the host enforced it on every message.
- No model is bundled. Real semantic quality depends on the configured adapter and still needs held-out live-model evaluation.
- The local hard-boundary policy is not a replacement for the host or platform safety system.
- A selected or installed Skill is not proof that the host exposed or successfully activated it.

See [docs/launch-readiness.md](docs/launch-readiness.md) for the prioritized release risks.
See [docs/contribution-boundary.md](docs/contribution-boundary.md), [docs/threat-model.md](docs/threat-model.md), [SECURITY.md](SECURITY.md), [docs/release-gate.md](docs/release-gate.md), [docs/alpha-trial.md](docs/alpha-trial.md), [docs/support-matrix.md](docs/support-matrix.md), [docs/value-p0.md](docs/value-p0.md), [docs/design-sources.md](docs/design-sources.md), and [docs/github-benchmark.md](docs/github-benchmark.md) for the contribution boundary, threat model, reporting policy, release evidence, trial protocol, and prior-art comparison.

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
