# Threat Model

## Scope

This model covers the local Intent Translator package, its profile and memory stores, optional semantic adapters, discovered Skill metadata, host integration, decision receipts, installers, diagnostics, and release artifacts. It models the control layer before an Agent action. It does not model every vulnerability inside a downstream Agent, Skill, browser, operating system, or external service.

## Security Claim

When a host calls the preflight with the exact current request and honors its result, the deterministic gate should preserve explicit prohibitions, separate public reads from consequential writes, require action-bound approval for external or destructive effects, and prevent untrusted semantic or memory content from lowering risk.

Installation alone does not provide this property. A host that bypasses the preflight can bypass every protection in this project.

## Assets

- The user's current action and explicit constraints.
- Concrete authorization receipts and their scope.
- Local profiles, corrections, memory, and state Markdown.
- Private files and destinations named in a request.
- Skill registry metadata and runtime integrity state.
- Diagnostic output, benchmark fixtures, packages, and release provenance.

## Trust Boundaries

1. **User to host:** conversational wording enters a host that may omit or alter context.
2. **Host to compiler:** the host supplies wording, pending action, files, scope, and authorization hints.
3. **Compiler to semantic adapter:** optional model input may leave the device and model output is untrusted.
4. **Compiler to local state:** profiles and memory are persistent evidence but never executable authority.
5. **Compiler to Skill or tool:** selected capability metadata does not prove host exposure or successful activation.
6. **Repository to installed runtime:** packages, installers, dependencies, and long-running processes may differ by version.

## Threat Register

| ID | Threat | Boundary | Required control | Current evidence | Residual risk |
|---|---|---|---|---|---|
| T01 | Host bypasses preflight while UI implies protection | Host to compiler | Hosts must call preflight and display active/stale/degraded state | Host registration, doctor, runtime receipt tests | A non-cooperating host remains outside enforcement |
| T02 | Short confirmation expands into broad or future authority | User to host | Bind approval to exact action, arguments, destination, scope, and expiry | Authorization and continuation regressions | A host can still submit the wrong pending action |
| T03 | Old task or profile overrides the latest request | Local state | Latest wording and pending action outrank project context and relevant profile | Personalization firewall and state-priority tests | Semantic relevance remains imperfect for unseen language |
| T04 | Object nouns steal action ownership | Compiler to Skill | Route by operation before Skill, file, GitHub, or prompt nouns | IntentBench routing cases and role matrix | New verbs and third-party capability descriptions need evaluation |
| T05 | Semantic model lowers deterministic risk or replaces action identity | Semantic adapter | Model output may raise risk only; material goal changes become alternatives | Adversarial semantic tests | A persuasive but wrong proposal may still create user confusion |
| T06 | Imported text or memory injects durable instructions | Local state | Provenance, trust levels, quarantine, and non-authoritative recall | Memory-defense and migration tests | Socially engineered user confirmation can still promote bad data |
| T07 | Public query, user text, profile, memory, or private file is misclassified | Host to compiler | Separate operation, effect, and data egress; require approval for private egress | IntentBench control cases | Classification cannot inspect data hidden from the host request |
| T08 | Approval receipt is replayed or substituted | User to host | One-time, expiring, action-bound receipt verification | Receipt replay and mismatch tests | Clock or state loss may force safe re-confirmation |
| T09 | Cross-profile or creator-default leakage | Local state | Generic defaults, scoped stores, creator contamination audit | Leakage and clean-room tests | Host-level shared directories can defeat intended isolation |
| T10 | Malicious Skill metadata wins routing or claims activation | Compiler to Skill | Deterministic ownership, abstention, integrity checks, separate selected/verified states | Routing and Skill integrity tests | Third-party Skill code remains outside this package's sandbox |
| T11 | Installer or dependency supply chain is compromised | Repository to runtime | Minimal dependencies, package audit, SBOM, CodeQL, attestations, rollback | Release gate and GitHub package workflow | Dependency compromise before detection remains possible |
| T12 | Logs, diagnostics, issues, or benchmarks expose private data | Repository boundary | Redaction, no telemetry, synthetic public fixtures, private reporting | Privacy guard and release audit | Users may manually paste sensitive data into public issues |
| T13 | Long input or repeated requests cause resource exhaustion | User to compiler | Bounded retrieval, timeouts for adapters, compact output, no full-vault scan | Performance and adapter timeout tests | The host must enforce broader process and rate limits |
| T14 | Hard-boundary content is converted into an executable task | User to host | Deterministic local policy can block configured illegal or harmful actions | Local policy and IntentBench hard-boundary case | Policy coverage is not a substitute for host or platform safety systems |

## Attacker Capabilities

The model assumes an attacker may control request text, imported documents, model output, a memory candidate, Skill descriptions, external web content, or an outdated local configuration. It also assumes accidental misuse: terse confirmations, stale context, wrong destinations, and confirmation fatigue.

The model does not assume the compiler can defend against an administrator who modifies installed code, a host that fabricates compiler results, an already-compromised operating system, or malicious downstream code executing outside host controls.

## Security Invariants

1. Memory and model output cannot grant authorization.
2. A semantic adapter cannot lower deterministic risk.
3. Consequential approval is action-bound and expires.
4. Explicit prohibitions survive continuation and routing.
5. Public read effects do not inherit write-level confirmation solely because a network is involved.
6. Selected, installed, host-exposed, and activation-verified are separate states.
7. Generic public defaults contain no creator-specific goals or phrase mappings.
8. Missing required slots disable execution rather than being filled with invented values.

## Verification

Run the local security and conformance checks:

```bash
python -m unittest discover -s tests -v
python -m intent_translator_mcp.intentbench --system compiler --fail-on-dangerous-miss --minimum-field-accuracy 1.0
python scripts/release_gate.py --mode full
```

Remote CI, package attestations, independent challenge sets, and real-user trials are distinct evidence classes. A green local run cannot replace them.

## Reporting

Report suspected vulnerabilities through the repository's private security advisory channel described in [../SECURITY.md](../SECURITY.md). Do not place credentials, private profiles, or identifying utterances in a public issue.
