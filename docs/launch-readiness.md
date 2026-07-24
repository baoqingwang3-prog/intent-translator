# GitHub Launch Readiness

This document separates repository readiness from product intelligence. A green CI badge does not prove that the compiler understands unfamiliar people.

| Priority | Risk | Why it matters | Current mitigation | Exit condition |
|---|---|---|---|---|
| P0 | Users cannot diagnose or fully remove the installation | A local-first trust claim fails if setup is opaque or leaves broken host configuration | Privacy-conscious doctor, Skill and MCP uninstallers, installer rollback | Clean install, doctor, and uninstall pass in isolated Windows/macOS/Linux environments |
| P0 | A brief approval expands into publication or sensitive transfer | One wrong authorization can cause irreversible harm | Explicit risk preflight, correction ledger, confirmation tests | Zero missed confirmations in regression and adversarial authorization suites |
| P0 | Real profile, memory, path, or credential reaches GitHub | Public history is difficult to erase and may require credential rotation | Ignore rules, local data boundary, secret scan, private vulnerability reporting | Current tree, staged diff, and history scan are clean before first push |
| P0 | Package, Skill, and documentation versions disagree | Users cannot reproduce or support installations | Root and Skill VERSION files plus package metadata | Automated metadata test and tag build agree on one version |
| P1 | Rules overfit Chinese wording and bundled Skills | A public tool must not require every profession to be hard-coded | English safety vocabulary and conservative description-based routing | Multilingual, third-party Skill, and out-of-distribution eval suites meet published thresholds |
| P1 | MCP is installed but the host does not call it | Users may believe safety checks are active when they are not | Host snippets, doctor output, explicit fallback Skill workflow | Per-host integration tests and visible invocation receipts |
| P1 | Small regression set is mistaken for general understanding | Inflated claims damage trust and hide product risk | README limitations and explicit deterministic-eval label | Hundreds of held-out, consented, diverse cases plus live-model evaluation |
| P1 | Contributors cannot reproduce failures | Issue discussions become long environment interviews | Structured bug template, contributing guide, diagnostic JSON | Maintainers can reproduce supported reports from supplied redacted diagnostics |
| P1 | Dependency or installer supply-chain issue | MCP installation downloads Python packages and runs local scripts | Pinned major versions, Dependabot, CodeQL, package build workflow | Reviewed lock/constraints strategy, artifact hashes, signed releases or attestations |
| P2 | First-time users face too many concepts | MCP, profiles, memory, Skills, and adapters create cognitive load | Skill-first recommendation and Chinese quick start | Usability test participants install and uninstall without maintainer help |
| P2 | No stable product identity or package ownership | Name collisions and unofficial forks can confuse users | Versioned alpha and clear repository scope | Repository name, package name, release channel, and maintainer policy finalized |

## Release Rule

Do not call a release stable until P0 exit conditions are met and the real-user evaluation design is published. Alpha releases may ship with P1 gaps when the limitation is visible and the default remains local and reversible.
