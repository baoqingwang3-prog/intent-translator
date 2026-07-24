# GitHub Launch Readiness

This document separates repository readiness from product intelligence. A green CI badge does not prove that the compiler understands unfamiliar people.

| Priority | Risk | Why it matters | Current mitigation | Exit condition |
|---|---|---|---|---|
| P0 | Users cannot diagnose or fully remove the installation | A local-first trust claim fails if setup is opaque or leaves broken host configuration | Privacy-conscious doctor, Skill and MCP uninstallers, installer rollback | Clean install, doctor, and uninstall pass in isolated Windows/macOS/Linux environments |
| P0 | A brief approval expands into publication or sensitive transfer | One wrong authorization can cause irreversible harm | Explicit risk preflight, correction ledger, confirmation tests | Zero missed confirmations in regression and adversarial authorization suites |
| P0 | Real profile, memory, path, or credential reaches GitHub | Public history is difficult to erase and may require credential rotation | Ignore rules, local data boundary, secret scan, private vulnerability reporting | Current tree, staged diff, and history scan are clean before first push |
| P0 | A file, web page, model output, or import poisons durable memory | Persistent hostile instructions can outlive the original context and silently alter future behavior | Provenance, trust levels, non-authoritative recall, injection quarantine, poisoning-resistant updates | Adversarial import and migration suites show zero quarantined recall and zero authority escalation |
| P0 | Sensitive state leaks through summaries or an Obsidian mirror | Local-first storage still fails if private details are copied into routine agent context or human-readable indexes | Explicit retention, default exclusion, redacted write responses, and public-only Markdown refresh | Sensitive-state fixtures show zero context or mirror exposure and no deletion during public refresh |
| P0 | Package, Skill, and documentation versions disagree | Users cannot reproduce or support installations | Root and Skill VERSION files plus package metadata | Automated metadata test and tag build agree on one version |
| P1 | Rules overfit Chinese wording and bundled Skills | A public tool must not require every profession to be hard-coded | English safety vocabulary and conservative description-based routing | Multilingual, third-party Skill, and out-of-distribution eval suites meet published thresholds |
| P1 | MCP is installed but the host does not call it | Users may believe safety checks are active when they are not | Host snippets, doctor output, explicit fallback Skill workflow | Per-host integration tests and visible invocation receipts |
| P1 | Small regression set is mistaken for general understanding | Inflated claims damage trust and hide product risk | README limitations, deterministic-eval label, and adversarial semantic fixtures | Hundreds of held-out, consented, diverse cases plus live-model evaluation |
| P1 | Contributors cannot reproduce failures | Issue discussions become long environment interviews | Structured bug template, contributing guide, diagnostic JSON | Maintainers can reproduce supported reports from supplied redacted diagnostics |
| P1 | Dependency or installer supply-chain issue | MCP installation downloads Python packages and runs local scripts | Pinned major versions, Dependabot, CodeQL, package build workflow | Reviewed lock/constraints strategy, artifact hashes, signed releases or attestations |
| P2 | First-time users face too many concepts | MCP, profiles, memory, Skills, and adapters create cognitive load | Skill-first recommendation and Chinese quick start | Usability test participants install and uninstall without maintainer help |
| P2 | No stable product identity or package ownership | Name collisions and unofficial forks can confuse users | Versioned alpha and clear repository scope | Repository name, package name, release channel, and maintainer policy finalized |

Automated evidence is available through `python scripts/release_gate.py --mode full`. The stranger-user protocol is documented in [alpha-trial.md](alpha-trial.md). Passing local automation does not replace the first GitHub-hosted matrix run or the 3-5 person Alpha rehearsal.

## Release Rule

Do not call a release stable until P0 exit conditions are met and the real-user evaluation design is published. Alpha releases may ship with P1 gaps when the limitation is visible and the default remains local and reversible.

## Alpha Preparation Matrix

| Area | State | Evidence | Remaining external proof |
|---|---|---|---|
| Creator-shadow isolation | Complete locally | Generic-profile firewall, tracked-content audit, private-term scan support | Re-run immediately before first push |
| Clean-room install and first use | Complete locally | Cross-platform acceptance test covers install, generic first use, third-party Skill routing, onboarding, uninstall, and retained local data | GitHub-hosted macOS/Linux/Windows run |
| Core release acceptance | Complete locally | Unit, protocol, semantic safety, memory defense, student-state, metadata, and doctor suites | First remote CI run |
| Beginner onboarding | Complete for CLI/MCP alpha | Three skippable choices, redacted summary, first-run guide | Host-native buttons remain host-dependent |
| Release quality gates | Complete locally | CI matrix, compile/import checks, rollback tests, metadata check, secret and contamination audits | Artifact attestation and remote branch protection |
| Stranger-user evidence | Planned, not complete | Trial protocol below | At least five consented users who did not help build the project |

## Stranger-User Trial

Recruit at least five people across different roles or study situations. Do not preload creator preferences or explain the intended interpretation.

Each participant should:

1. Install using only the README and record whether help was needed.
2. Skip or complete onboarding in their own words.
3. Give five natural requests, including one terse continuation, one correction, one unfamiliar professional task, one external-action request, and one request that should remain an answer rather than an action.
4. Inspect the decision receipt for one non-obvious interpretation.
5. Uninstall and verify whether local data was preserved as stated.

Record only consented, redacted outcomes: successful task completion, wrong Skill, unnecessary interruption, missed confirmation, correction recurrence, install time, and uninstall success. Do not store full utterances by default. Alpha exit requires zero missed publication/deletion/privacy confirmations and no creator-specific default appearing in any participant profile.

## Publication Hold

Preparation does not authorize publication. Before creating a remote or pushing, confirm the destination owner, repository name, visibility, and exact branch/tag. Run current-tree, staged, and history secret scans plus the local private-term contamination scan immediately before that confirmation.
