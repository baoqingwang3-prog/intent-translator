# Changelog

All notable changes are recorded here. The project follows semantic versioning after `1.0.0`; alpha releases may still refine interfaces with migration notes.

## [Unreleased]

### Fixed

- Confirmation receipts were signed with a key generated per process and recorded in an in-memory single-use set, so a receipt issued by one process failed verification in any other process with `invalid signature`, and every outstanding approval was silently invalidated by a restart. This failed closed rather than open, but it made the control unusable in any deployment running more than one worker, and it forced users to re-approve pending actions after each restart. The signing key and the single-use ledger are now shared through the local data directory, so a receipt survives a restart within its expiry and single use is enforced across processes.
- Issuing or verifying a receipt raised `RuntimeError: Could not determine home directory.` in an environment that names no home directory, such as a service unit, a container without `HOME`, or a Windows process started with an explicit environment. The location of the shared key and ledger is resolved without requiring a home directory, and an unresolvable location degrades to the reported process-local mode instead of raising.

### Added

- Host enforcement for Claude Code. `intent-translator-hook install` registers a `PreToolUse` hook that compiles the session's latest prompt, classifies the tool call the host is about to make, and denies a prohibited or blocked action before it runs. Until now every control in this project depended on the host choosing to call the preflight; a model that went straight to a shell command bypassed all of them. A `UserPromptSubmit` hook records the wording the compiler needs, since a pre-tool hook receives the tool call and not the user's request, and a `SessionEnd` hook forgets it. An allowed verdict prints nothing and exits 0, so the host's own permission flow is untouched: returning `allow` would skip the user's permission prompt, and a preflight may raise friction but never lower it. `INTENT_TRANSLATOR_HOOK_ON_ERROR` decides what an unusable preflight means, defaulting to escalating to the user rather than silently allowing, because Claude Code treats a crashed hook as non-blocking. Limits, other hosts, and remaining bypass paths are documented in [docs/host-enforcement.md](docs/host-enforcement.md).
- `actor` on `CompileRequest` (default `INTENT_TRANSLATOR_ACTOR`) binds a receipt to the identity that approved it. Verification of a receipt carrying an actor fails with `actor mismatch` for anyone else, which keeps one person's approval from being spent by another in a shared or multi-user host. Receipts without an actor keep working unchanged for single-user local installs.
- `INTENT_TRANSLATOR_RECEIPT_SECRET` and `INTENT_TRANSLATOR_RECEIPT_SECRET_PREVIOUS` for an explicit signing key and single-step key rotation, for deployments whose processes cannot share a filesystem. The auto-created `receipt-key` file is written with owner-only permissions.
- `authorization_backend` in the compile response reports whether receipts are shared across processes and survive a restart. It is included in the compact response only when they are not, so a host can surface the warning instead of silently running in the degraded mode.

### Changed

- The invocation receipt no longer claims `preflight-observed-not-host-enforced` unconditionally. A compile that a host hook performed before the tool call ran now reports `preflight-enforced-by-host-hook`, and every other entrypoint keeps the original claim because it was called voluntarily.
- The threat model and support matrix no longer describe host enforcement as unavailable. T01's residual risk is now the specific set of paths a hook cannot cover rather than "a non-cooperating host remains outside enforcement".

## [0.10.0a1] - 2026-08-12

### Added

- A governed learning lifecycle for capturing, reviewing, explicitly promoting, reinforcing, and maintaining local memory candidates without turning inference into authority.
- A generated Skill registry and compact capability catalog with duplicate detection, source precedence, fingerprints, and metadata-based routing.
- Regression coverage for the learning lifecycle, Skill registry, Chinese installation prohibitions, source-tree release execution, and deployed-runtime acceptance.

### Changed

- Intent compilation now preserves more Chinese prohibited actions, including deletion, uninstallation, overwrite, and installing additional software.
- Runtime and doctor checks now distinguish configured installations from repository source copies and report degraded host registration more accurately.
- Release gates now run source-tree benchmarks and Codex host traces against the repository package explicitly before validating built artifacts.

## [0.8.0a1] - 2026-08-12

### Added

- A deterministic staged Skill composition planner with preparation, primary, verification/rendering, and dormant fallback stages.
- Regression cases and focused unit tests for search-to-report workflows, diagnosis-to-fix verification, study orchestrator ownership, and missing primary Skills.

### Changed

- Multi-Skill routing now keeps one capability owner per stage, caps eager compositions at four Skills, and preserves authorization boundaries across handoffs.

## [0.7.1a3] - 2026-07-28

### Added

- An official Claude, Codex, and Grok capability baseline with a 45-day release freshness gate.
- Honest per-turn value receipts that quantify observable preflight activity while reserving counterfactual benefit claims for paired evaluation.

### Changed

- Public positioning is now native-host-first: local memory, Skill routing, permissions, hooks, and compaction remain useful adapters and fallbacks, while cross-host evidence and evaluation are the independent core.
- The local workflows that already help existing users remain enabled; this release does not remove personal correction or continuity behavior.

## [0.7.1a2] - 2026-07-27

### Added

- A local-first Python SDK facade with typed compile, risk-check, gate-resolution, and confirmation-receipt helpers.
- A natural-language-first Studio workflow with a copyable sanitized SDK contract.

### Fixed

- Read-only compatibility for legacy local memory databases.
- Raw memory and correction diagnostics are excluded from default SDK results.

## [0.7.1a1] - 2026-07-26

### Added

- IntentBench v1 with packaged public synthetic cases, external prediction scoring, exact missing-prediction penalties, confidence intervals, and dangerous-miss reporting.
- IntentBench v2 with 100 public synthetic bilingual and mixed-language development cases, third-party Skill coverage, dangerous-miss gates, and blinded private-challenge tooling.
- A same-model paired A/B protocol that rejects model, tool, prompt, profile, or gold-label mismatches before scoring.
- Bounded invocation receipts, operator-driven Codex execution-trace evidence, privacy-preserving feedback export, and consented trial-record tooling with deletion support.
- Project-scoped interpretation-gate continuity and a typed recipient-adaptation contract for local previews.
- A falsifiable contribution and prior-art boundary, domain glossary, public threat model, and private vulnerability reporting policy.
- Release and GitHub CI gates that run IntentBench, including a clean installed-wheel benchmark check.

### Changed

- Action ownership now handles English update/testing language, prompt conversion, Skill creation with validation, and private file transfer without noun-based route hijacking.
- Negated file/profile transfer and no-change constraints are removed from the requested action while remaining visible as prohibitions.
- Ambiguous integration wording abstains outside a confirmed project correction; numbered, textual, and button option selections resolve against the same pending gate.
- Audience and relationship context can change a preview's terminology and sections but never expands disclosure or external-send authorization.
- Compile and tool-gateway responses distinguish observed preflight from host-enforced execution; automatic interception remains explicitly unverified.

## [0.7.0a3] - 2026-07-25

### Added

- A clean-room Playwright Studio gate for desktop and mobile, with redacted reproducible evidence and a prepared GitHub CI job.
- Typed operation, effect, data-egress, and active-task-source fields in the intent contract.
- Chinese, English, and mixed-language role regressions across development, product, design, research, operations, content, finance, and legal/admin work.
- Visible Skill selection, abstention, installation, and unverified activation states.
- Public design-source and product-value evidence documents with license provenance.

### Changed

- Public source now ships only generic study and certification examples; personal goals and subject Skill preferences stay in the local profile.
- Action ownership now precedes Skill noun matching, with public reads separated from external writes.

### Fixed

- Studio hidden states no longer leave large blank result areas, and clean first runs now state that no personal memory is loaded.
- English token boundaries no longer confuse words such as `unpublished` with a publication action.
- Automatic autonomy restoration is disabled and requires explicit confirmation.

## [0.7.0a2] - 2026-07-25

### Added

- A real local bilingual Studio for inspecting understanding, source mapping, Skill routing, memory sources, authorization boundaries, and runtime freshness without an API key.
- An explicit host support matrix, first-Alpha audience, Agent Reach complement, shareable redacted diagnostic workflow, and final Alpha checklist.
- Loopback-only Studio binding by default, with explicit opt-in required for trusted-network exposure.
- Native Codex MCP registration management with running-host protection, explicit repair status, idempotent updates, and rollback to the previous registration when replacement fails.
- A reproducible five-user stranger rehearsal covering isolated corrections, downstream routing, risk confirmation, and Skill invocation metrics.

### Changed

- Skill listing metadata now describes understanding, authorization, local memory, and routing instead of only prompt rewriting.
- MCP installers no longer edit Codex TOML directly; doctor now separates runtime installation from host registration and restart state.

## [0.7.0a1] - 2026-07-25

### Added

- Minimal three-category first-run onboarding for generic users.
- Reproducible two-user stranger smoke with isolated language correction and Skill invocation metrics.
- Release gate, creator-shadow and secret audit, package inspection, lifecycle coverage, and tagged artifact provenance.
- Stranger-user Alpha protocol and high-star GitHub release benchmark.
- CLI and MCP onboarding entry points for three skippable local preferences.
- Cross-platform clean-room acceptance covering install, generic first use, third-party Skill routing, onboarding, uninstall, and data preservation.
- Tracked-content creator-shadow scanning with local private-term fingerprints.
- Disabled-by-default `memory-breathing` and `reversible-context` plugins with a host-neutral local JSON runner.
- Bounded relevant handoff loading, decision and correction snapshots, source pointers, SHA-256 markers, and verified context expansion.
- Cross-process profile locks, crash-safe JSON replacement, and concurrent correction regression tests.
- Legacy profile migration with pre-migration backups and future-schema downgrade protection.
- Deterministic CycloneDX SBOM generation from the clean installed wheel environment.
- Runtime version handshakes in compile receipts, doctor, and onboarding status, including stale-host restart guidance.
- Versioned Alpha adversarial regressions for short confirmations, negative publication scope, continuation recovery, and action-owned Skill routing.
- A public, redacted postmortem for repeated short-confirmation hijacking failures.
- Host-specific MCP configuration paths for Codex, Claude, Cursor, Gemini, Copilot, and OpenCode.
- Doctor version alignment diagnostics for active Skill copies, the installed runtime, and the doctor package.

### Changed

- A newly initialized but uncustomized profile remains generic and no longer claims personal knowledge.
- Confirmed phrase mappings use exact matching unless a profile explicitly opts into `match_mode: contains`.
- Public student profile packs use generic managed-note names instead of names reused by the creator's local setup.
- Skill installers migrate and validate existing profiles before completing an upgrade.
- Dangerous short-confirmation `contains` mappings are repaired to `exact` during a backed-up profile upgrade.
- Explicit prohibitions are retained as constraints instead of being classified as requested external actions.
- Search and research action ownership outranks artifact words such as `Skill` during routing.
- Unsupported large semantic compression preserves the original wording and requires review.
- MCP installers accept PEP 440 alpha, beta, and release-candidate versions, retry transient package downloads, preserve readable UTF-8 paths, and reject unsafe Windows runtime path lengths early.

## [0.6.0] - 2026-07-25

### Added

- Memory provenance, trust levels, prompt-injection detection, and a non-executable quarantine.
- Poisoning-resistant updates, non-authoritative external facts, and correction-policy defense.
- Read-only MCP and CLI defense status that never exposes quarantined text.
- Legacy-memory trust migration, bounded student-state persistence, and private-state exclusion from summaries and Obsidian mirrors.
- Generic-profile contamination audit and profile-independent behavior regression tests.
- Skippable local onboarding, hashed pre-confirmation language observations, and cautious-mode policy after repeated misunderstandings.

## [0.5.0] - 2026-07-25

### Added

- Optional bounded semantic adapters for JSON commands and compatible chat-completions endpoints.
- Semantic safety fixtures, adversarial evaluation, and explicit external/sensitive egress authorization.
- Opt-in local shadow evaluation, study material pointers, Obsidian index sync, and generic student profile packs.
- Versioned MCP runtimes, Codex setup helper, and runtime-aware doctor checks.

### Changed

- MCP now exposes ten tools while keeping shadow evaluation disabled and utterance previews empty by default.

## [0.4.0] - 2026-07-25

### Added

- Privacy-conscious installation doctor.
- Dedicated MCP runtime uninstallers.
- English safety vocabulary and conservative third-party Skill routing.
- Chinese quick-start documentation and GitHub community files.

## [0.3.0] - 2026-07-25

### Added

- Local stdio MCP server with seven intent and correction tools.
- Governed SQLite memory, Chinese n-gram retrieval, conflict handling, and decision receipts.
- Cross-platform installer rollback, version checks, and Skill/MCP uninstall support.
- Deterministic A/B evaluation and protocol tests.

## [0.1.0] - 2026-07-24

### Added

- Initial public-alpha Skill, local profile, memory store, privacy guard, evaluation cases, and multi-host installation.
