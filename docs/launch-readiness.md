# GitHub Launch Readiness

This document separates local engineering evidence, remote repository evidence, and real-user evidence. A local green gate does not prove that GitHub-hosted jobs pass or that unfamiliar people can use the product.

## Current GitHub Alpha P0 Board

These are the two remaining external evidence blockers for the GitHub Alpha label. This does not waive unresolved engineering risks or authorize publication. Product philosophy, private creator preferences, future enterprise controls, and additional audience packs are not Alpha P0 work.

| P0 | State | Exit condition | Evidence owner |
|---|---|---|---|
| P0-1 Stranger-user usability proof | Protocol ready; synthetic rehearsal passed; real-user evidence incomplete | 3-5 consenting first-audience users complete README-only install, onboarding, five request classes, one correction, one decision-receipt check, and uninstall; dangerous confirmation misses = 0, cross-profile contamination = 0, creator-default leakage = 0 | Human trial record with redacted metrics |
| P0-2 GitHub remote reproducibility proof | Local workflows ready; no remote configured; remote evidence incomplete | Explicit owner/name/visibility/branch/tag authorization, clean pre-push scans, first green GitHub-hosted Windows/macOS/Linux CI, independent Playwright job, lifecycle/version verification, and branch protection | GitHub Actions, repository settings, and release checklist |

Until P0-1 is completed, say **"protocol prepared and synthetic rehearsal passed"**, not "real users passed." Until P0-2 is completed, say **"local workflows passed"**, not "remote CI passed."

## Local Risk Register

The following engineering risks are tracked separately from the two remaining GitHub Alpha P0 items. Items with local regression evidence retain that evidence; future enterprise hardening does not silently become an Alpha release blocker.

| Status | Risk | Why it matters | Current mitigation | Evidence |
|---|---|---|---|---|
| Local regression evidence present | Users cannot diagnose or fully remove the installation | A local-first trust claim fails if setup is opaque or leaves broken host configuration | Privacy-conscious doctor, Skill and MCP uninstallers, installer rollback | Clean-room install, doctor, rollback, and uninstall tests |
| Closed locally | A brief approval expands into publication or sensitive transfer | One wrong authorization can cause irreversible harm | Explicit risk preflight, correction ledger, confirmation tests | Regression and adversarial authorization suites |
| Recheck before push | Real profile, memory, path, or credential reaches GitHub | Public history is difficult to erase and may require credential rotation | Ignore rules, local data boundary, secret scan, private vulnerability reporting | Current tree, staged diff, history, private-path, and creator-contamination scans |
| Closed locally | A file, web page, model output, or import poisons durable memory | Persistent hostile instructions can outlive the original context and silently alter future behavior | Provenance, trust levels, non-authoritative recall, injection quarantine | Memory-defense and migration tests |
| Closed locally | Sensitive state leaks through summaries or an Obsidian mirror | Private details must not enter routine context or public indexes | Explicit retention, default exclusion, redacted write responses | Sensitive-state fixtures and mirror tests |
| Closed locally | Package, Skill, and documentation versions disagree | Users cannot reproduce or support installations | Root and Skill VERSION files plus package metadata | Automated metadata and build checks |
| P1 | Rules overfit Chinese wording and bundled Skills | A public tool must not require every profession to be hard-coded | English safety vocabulary and conservative description-based routing | Multilingual, third-party Skill, and out-of-distribution eval suites meet published thresholds |
| P1 | MCP is installed but the host does not call it | Users may believe safety checks are active when they are not | Host snippets, doctor output, explicit fallback Skill workflow | Per-host integration tests and visible invocation receipts |
| P1 | Small regression set is mistaken for general understanding | Inflated claims damage trust and hide product risk | README limitations, deterministic-eval label, and adversarial semantic fixtures | Hundreds of held-out, consented, diverse cases plus live-model evaluation |
| P1 | Contributors cannot reproduce failures | Issue discussions become long environment interviews | Structured bug template, contributing guide, diagnostic JSON | Maintainers can reproduce supported reports from supplied redacted diagnostics |
| P1 | Dependency or installer supply-chain issue | MCP installation downloads Python packages and runs local scripts | Pinned major versions, Dependabot, CodeQL, package build workflow | Reviewed lock/constraints strategy, artifact hashes, signed releases or attestations |
| P2 | First-time users face too many concepts | MCP, profiles, memory, Skills, and adapters create cognitive load | Skill-first recommendation and Chinese quick start | Usability test participants install and uninstall without maintainer help |
| P2 | No stable product identity or package ownership | Name collisions and unofficial forks can confuse users | Versioned alpha and clear repository scope | Repository name, package name, release channel, and maintainer policy finalized |

Automated evidence is available through `python scripts/release_gate.py --mode full`. The stranger-user protocol is documented in [alpha-trial.md](alpha-trial.md). Passing local automation does not replace the first GitHub-hosted matrix run or the 3-5 person Alpha rehearsal.

## Release Rule

Do not call the product stable from Alpha evidence. The GitHub Alpha evidence claim requires both current P0 items. P1 and P2 gaps may remain when they are visible and defaults stay local and reversible.

## Alpha Preparation Matrix

| Area | State | Evidence | Remaining external proof |
|---|---|---|---|
| Creator-shadow isolation | Complete locally | Generic-profile firewall, tracked-content audit, private-term scan support | Re-run immediately before first push |
| Clean-room install and first use | Locally exercised in the documented environments | Cross-platform acceptance test covers install, generic first use, third-party Skill routing, onboarding, uninstall, and retained local data | GitHub-hosted macOS/Linux/Windows run |
| Core release acceptance | Local regression evidence present | Unit, protocol, semantic safety, memory defense, student-state, metadata, and doctor suites | First remote CI run |
| Beginner onboarding | Locally exercised for Studio/CLI/MCP alpha | Three skippable choices, redacted summary, first-run guide, and plain-language Studio | Host-native buttons remain host-dependent |
| Visible runtime trust | Local regression evidence present | Compile receipt, doctor, onboarding, and Studio show active/stale/degraded plus actual version and restart need | Restarted-host acceptance after local install |
| Shareable diagnostics | Complete locally | Redacted doctor JSON contains version alignment and configuration health without profile text or exact paths | Reproduce one stranger-user report |
| Release quality gates | Local workflow evidence present | CI matrix, compile/import checks, rollback tests, metadata check, secret and contamination audits | Artifact attestation and remote branch protection |
| Stranger-user evidence | Planned, not complete | Trial protocol below | 3-5 consented users who did not help build the project |

## Stranger-User Trial

Recruit 3-5 people from the first Alpha audience who did not help build the project. Do not preload creator preferences or explain the intended interpretation.

Each participant should:

1. Install using only the README and record whether help was needed.
2. Skip or complete onboarding in their own words.
3. Give five natural requests, including one terse continuation, one correction, one unfamiliar professional task, one external-action request, and one request that should remain an answer rather than an action.
4. Inspect the decision receipt for one non-obvious interpretation.
5. Uninstall and verify whether local data was preserved as stated.

Record only consented, redacted outcomes: successful task completion, wrong Skill, unnecessary interruption, missed confirmation, correction recurrence, install time, and uninstall success. Do not store full utterances by default. Alpha exit requires zero missed publication/deletion/privacy confirmations and no creator-specific default appearing in any participant profile.

Zero misses is an exit criterion for this small Alpha sample, not an estimate or guarantee of population-level safety.

## Publication Hold

Preparation does not authorize publication. Before creating a remote or pushing, confirm the destination owner, repository name, visibility, and exact branch/tag. Run current-tree, staged, and history secret scans plus the local private-term contamination scan immediately before that confirmation.

Record the authorization as a concrete release contract:

| Field | Required value before remote work |
|---|---|
| Repository owner | Pending explicit authorization |
| Repository name | Pending explicit authorization |
| Visibility | Pending explicit authorization |
| Branch | Pending explicit authorization |
| Tag | Pending explicit authorization |

After authorization, the remote proof sequence is:

1. Re-run current-tree, staged-diff, history, secret, private-path, and creator-contamination scans.
2. Create only the authorized repository and remote, then push only the authorized branch/tag.
3. Require the first GitHub-hosted Windows, macOS, and Linux matrix to pass.
4. Require the independent Playwright Studio job to pass.
5. Verify install, upgrade, rollback, uninstall, package metadata, and version agreement from hosted artifacts.
6. Configure branch protection for the required CI and Playwright checks.
7. Record failures as remote evidence; do not replace them with local reruns.

## Final Alpha Checklist

1. Run the full local release gate and Skill validation from a clean tree.
2. Verify Studio on desktop and 390x844 mobile for the four core scenarios.
3. Generate one redacted doctor JSON report and confirm it contains no profile text or exact private path.
4. Restart the supported host and verify the actual runtime reports `active` at the expected version.
5. Complete the 3-5 stranger-user protocol with zero missed publication, deletion, or privacy confirmations.
6. Obtain explicit repository owner, name, visibility, branch, and tag authorization before any remote creation or push.
7. Treat the first remote CI matrix and branch protection as external evidence that cannot be completed locally.

## Required Status Report

Every release-readiness report must use these three headings:

### Locally Proven

List only automated or directly observed local evidence, including the exact test/gate result.

### Remotely Unproven

List GitHub-hosted CI, independent Playwright, hosted lifecycle, repository settings, and artifact evidence that has not run remotely.

### Real-User Unproven

List the remaining 3-5 person protocol evidence. Synthetic users and fixtures must remain labeled synthetic.
