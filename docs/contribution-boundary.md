# Contribution And Prior-Art Boundary

## Falsifiable Project Claim

Intent Translator is a pre-execution control layer that compiles bounded conversational input into a typed Intent Contract and a deterministic execution decision. Its claim is narrower than "understands the user": compared with declared baselines on the same cases, it should preserve more explicit constraints, make fewer unsafe authorization errors, and expose enough state for a user or host to detect uncertainty.

This claim can be rejected by running the versioned benchmark, supplying competing predictions, or demonstrating a host integration that bypasses the preflight.

## Project Contributions

The contribution is the tested integration of the following mechanisms, not the invention of every underlying primitive.

| Contribution | Distinguishing rule | Implementation evidence | Regression evidence |
|---|---|---|---|
| Typed pre-execution contract | One validated object joins intent, action ownership, effect, data egress, active-task source, prohibitions, missing slots, and authorization | `src/intent_translator_mcp/intent_contract.py` | `tests/test_enterprise_p0.py`, `tests/test_value_p0.py` |
| Action-ownership-first routing | Search, create, test, install, and publish verbs own routing before nouns such as Skill, GitHub, or prompt | `src/intent_translator_mcp/core.py` | `tests/test_role_matrix_p0.py`, `tests/test_value_p0.py` |
| Effect and data-flow safety gate | Public reads are separated from external writes, private transfer, destructive work, and system changes | `src/intent_translator_mcp/core.py` | `tests/test_value_p0.py`, `tests/test_enterprise_p0.py` |
| Concrete approval continuity | Approval is bound to the pending action and cannot become broad future authorization | `src/intent_translator_mcp/core.py` | `tests/test_alpha_p0_regressions.py`, `tests/test_decision_receipt.py` |
| Relevance-gated personalization | Current wording and pending work outrank project context and long-term profile; unrelated profile blocks stay out | `src/intent_translator_mcp/core.py` | `tests/test_personalization_firewall.py`, `tests/test_study_shadow.py` |
| Visible capability state | Skill selection, installation evidence, host exposure, activation verification, and stale runtime are reported separately | `src/intent_translator_mcp/core.py`, `src/intent_translator_mcp/doctor.py` | `tests/test_doctor.py`, `tests/test_server_contract.py` |
| Correction-governed autonomy | Corrections are scoped evidence, recurrence is measurable, and autonomy restoration requires user confirmation | `skills/intent-translator/scripts/memory_store.py`, `src/intent_translator_mcp/core.py` | `tests/test_memory_store.py`, `tests/test_mcp_core.py` |

## Prior Art We Do Not Claim

The project does not claim to have invented schema validation, structured model output, human-in-the-loop interrupts, semantic routing, local memory, prompt evaluation matrices, or software supply-chain attestations. The specific projects and licenses studied for these mechanisms are listed in [design-sources.md](design-sources.md).

No listed upstream runtime is vendored into this repository. Similarity of mechanism is not evidence of copied implementation. Any future code reuse must preserve the upstream license and notices and must be identified in the pull request that introduces it.

## Evidence Classes

Claims must identify which evidence class supports them:

1. **Local conformance:** deterministic tests and the release gate on a maintainer machine.
2. **Remote reproducibility:** GitHub-hosted cross-platform CI, browser smoke, package build, and security analysis.
3. **Synthetic benchmark:** author-written, versioned cases scored under a published metric contract.
4. **Independent reproduction:** results produced by a person who did not author the implementation or gold labels.
5. **Real-user evidence:** consented use in the participant's own language and environment.

Evidence from one class must not be advertised as another. In particular, synthetic benchmark accuracy is not real-user understanding, and repository stars are not effectiveness evidence.

## Disallowed Claims

- "Guarantees correct understanding."
- "Guarantees safe execution" when the host may bypass the preflight.
- "Works for every profession, personality, language, or computer."
- "Scientifically proven" without an independent protocol and reproducible data.
- "Original technology" without naming the exact mechanism and its prior-art boundary.

## Review Rule

Every new headline capability must add at least one falsifiable case, identify its prior art, state its trust boundary, and name the evidence class that supports the claim. Features without those four items remain experimental and must not expand the public product promise.
