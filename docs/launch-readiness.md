# GitHub Launch Readiness

This document separates local engineering evidence, remote repository evidence, and real-user evidence. A local green gate does not prove that GitHub-hosted jobs pass or that unfamiliar people can use the product.

## Current GitHub Alpha P0 Board

The initial GitHub remote reproducibility blocker is closed for the published Alpha line. Real-user usability evidence remains incomplete. Product philosophy, private creator preferences, future enterprise controls, and additional audience packs are not Alpha P0 work.

| P0 | State | Exit condition | Evidence owner |
|---|---|---|---|
| P0-1 Stranger-user usability proof | Protocol ready; synthetic rehearsal passed; real-user evidence incomplete | 3-5 consenting first-audience users complete README-only install, onboarding, five request classes, one correction, one decision-receipt check, and uninstall; dangerous confirmation misses = 0, cross-profile contamination = 0, creator-default leakage = 0 | Human trial record with redacted metrics |
| P0-2 GitHub remote reproducibility proof | Complete for the published `0.7.0a3` line; later commits require their own run | GitHub-hosted Windows/macOS/Linux CI, independent Playwright job, Package, and CodeQL pass for the release line | Public GitHub Actions runs and immutable tag |

Until P0-1 is completed, say **"protocol prepared and synthetic rehearsal passed"**, not "real users passed." Remote evidence must always name the exact commit or release line; a previous green run does not validate an unpushed tree.

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
| P1 local evidence present | Rules overfit Chinese wording and bundled Skills | A public tool must not require every profession to be hard-coded | Bilingual and mixed-language IntentBench v2, third-party Skill cases, action-first routing, and conservative abstention | Independent out-of-distribution challenge still required |
| P1 partially closed | MCP is installed but the host does not call it | Users may believe safety checks are active when they are not | Host snippets, doctor output, bounded invocation receipts, and one operator-driven Codex trace | Automatic interception and non-Codex host enforcement remain unverified |
| P1 tooling ready | Small regression set is mistaken for general understanding | Inflated claims damage trust and hide product risk | README limitations, two public development sets, blinded challenge bundles, and same-model paired A/B validation | Independent hidden results, live-model evaluation, and consented real-user evidence remain required |
| P1 | Contributors cannot reproduce failures | Issue discussions become long environment interviews | Structured bug template, contributing guide, diagnostic JSON | Maintainers can reproduce supported reports from supplied redacted diagnostics |
| P1 | Dependency or installer supply-chain issue | MCP installation downloads Python packages and runs local scripts | Pinned major versions, Dependabot, CodeQL, package build workflow | Reviewed lock/constraints strategy, artifact hashes, signed releases or attestations |
| P2 | First-time users face too many concepts | MCP, profiles, memory, Skills, and adapters create cognitive load | Skill-first recommendation and Chinese quick start | Usability test participants install and uninstall without maintainer help |
| P2 | No stable product identity or package ownership | Name collisions and unofficial forks can confuse users | Versioned alpha and clear repository scope | Repository name, package name, release channel, and maintainer policy finalized |

Automated evidence is available through `python scripts/release_gate.py --mode full`. The stranger-user protocol is documented in [alpha-trial.md](alpha-trial.md). Passing local automation does not replace GitHub-hosted evidence for the same commit or the 3-5 person Alpha rehearsal.

## Release Rule

Do not call the product stable from Alpha evidence. The GitHub Alpha evidence claim requires both current P0 items. P1 and P2 gaps may remain when they are visible and defaults stay local and reversible.

## Alpha Preparation Matrix

| Area | State | Evidence | Remaining external proof |
|---|---|---|---|
| Creator-shadow isolation | Complete locally | Generic-profile firewall, tracked-content audit, private-term scan support | Re-run immediately before first push |
| Clean-room install and first use | Locally exercised in the documented environments | Cross-platform acceptance test covers install, generic first use, third-party Skill routing, onboarding, uninstall, and retained local data | GitHub-hosted macOS/Linux/Windows run |
| Core release acceptance | Local and published-Alpha remote evidence present | Unit, protocol, IntentBench, semantic safety, memory defense, metadata, doctor, and GitHub matrix | Repeat for every later release commit |
| Beginner onboarding | Locally exercised for Studio/CLI/MCP alpha | Three skippable choices, redacted summary, first-run guide, and plain-language Studio | Host-native buttons remain host-dependent |
| Visible runtime trust | Local regression evidence present | Compile receipt, doctor, onboarding, and Studio show active/stale/degraded plus actual version and restart need | Restarted-host acceptance after local install |
| Shareable diagnostics | Complete locally | Redacted doctor JSON contains version alignment and configuration health without profile text or exact paths | Reproduce one stranger-user report |
| Release quality gates | Local and published-Alpha remote evidence present | CI matrix, compile/import checks, rollback tests, metadata check, secret and contamination audits | Repeat attestation and required checks for every later release |
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

## Future Publication Rule

The current public repository is `baoqingwang3-prog/intent-translator`. Existing publication does not authorize a later push or tag. Before each future release, confirm the exact branch/tag and run current-tree, staged, history, secret, and creator-contamination scans.

Record the authorization as a concrete release contract:

| Field | Required value before remote work |
|---|---|
| Repository owner | `baoqingwang3-prog` |
| Repository name | `intent-translator` |
| Visibility | Public |
| Branch | `main` |
| Tag | Per-release explicit authorization required |

After authorization, the remote proof sequence is:

1. Re-run current-tree, staged-diff, history, secret, private-path, and creator-contamination scans.
2. Create only the authorized repository and remote, then push only the authorized branch/tag.
3. Require the release commit's GitHub-hosted Windows, macOS, and Linux matrix to pass.
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
6. Obtain explicit branch and tag authorization before a future push or release; reconfirm owner, repository, and visibility if they change.
7. Treat remote CI and branch protection as external evidence that cannot be completed locally or inherited from a different commit.

## Required Status Report

Every release-readiness report must use these three headings:

### Locally Proven

List only automated or directly observed local evidence, including the exact test/gate result.

### Remote Status

List GitHub-hosted CI, independent Playwright, hosted lifecycle, repository settings, and artifact evidence with the exact commit. Separate completed release evidence from current-tree work that has not been pushed.

### Real-User Unproven

List the remaining 3-5 person protocol evidence. Synthetic users and fixtures must remain labeled synthetic.
