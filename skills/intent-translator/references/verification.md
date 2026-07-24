# Verification Gate

Do not claim that work is complete, installed, fixed, published, remembered, or compatible without fresh evidence for that exact claim.

## Evidence By Mode

| Claim | Minimum evidence |
|---|---|
| Code or configuration changed | Relevant diff or direct file inspection plus focused tests |
| Tests pass | Fresh command output with zero failures |
| Installation works | Install into an isolated destination and run a smoke test |
| Memory was written | Read the stored record back from the selected adapter |
| Routing works | Discovery output plus an evaluation or realistic forward test |
| External publication succeeded | Remote URL or API response showing the artifact |
| Cross-platform support | CI matrix or real tests on each claimed platform |

When evidence is partial, state the verified subset and the remaining risk. Never convert an expected outcome into a completed claim.

For behavior changes, prefer a regression case. For high-impact behavior, include an adversarial or pressure scenario that tests whether the rule survives tempting shortcuts.
