# Value P0: Execution-Preflight Evidence

This gate tests whether Intent Translator adds behavior that an end-of-run summary cannot provide.
It is a deterministic regression gate, not a claim that every user or model will always be understood.

## Public Evidence Behind The Gate

- Underspecified instructions can cause models to invent missing tool parameters. The P0 gate requires
  vague external actions to stop with typed missing slots instead of executing.
  Source: [Learning to Ask (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.1104/).
- Users experience prompt gambling when they cannot predict what an agent will do. The P0 gate exposes
  operation, effect, data egress, active task source, selected Skill, and whether execution may proceed.
  Source: [Why Johnny Can't Use Agents](https://pradyumnashome.com/documents/papers/2025-Why-Johnny-Can't-Use-Agents-Industry-Aspirations-vs-User-Realities-with-AI-Agent-Software.pdf).
- Large Skill pools make noun-only routing unreliable. The P0 gate gives action ownership priority and
  separates one primary Skill from at most three supporting Skills.
  Sources: [Workflow-skill-router](https://github.com/eric861129/Workflow-skill-router) and
  [SkillRouter](https://github.com/zhengyanzhao1997/SkillRouter).
- Correction retrieval alone is insufficient. Existing local tests also track whether corrections are
  heeded or recur, and lower autonomy after repeated misunderstanding.
- A selected Skill is not the same as an activated Skill. The P0 gate separates discovered metadata,
  installation, policy eligibility, freshness, and unverified activation, and abstains when no eligible
  route meets the evidence threshold.
- Public source and private personalization are separate layers. The repository ships generic packs;
  personal goals, paths, progress, and Skill preferences remain in the local profile.

## Required P0 Scenarios

1. A product-value discussion containing `prompt` or `Skill` stays in answer mode and invokes no Skill.
2. Long-term study state is loaded only for an explicit study or exam request, never for unrelated development.
3. A public GitHub search is `read_public` with `public_query` egress and needs no write approval.
4. A Playwright request is a test action and routes to a browser-capable Skill when installed.
5. A private profile transfer is `write_external`, remains action-bound, and cannot execute implicitly.
6. A vague external action exposes missing object and destination slots instead of inventing them.
7. Automatic autonomy restoration is never allowed; restoration always requires user confirmation.
8. Developer, product, design, research, operations, content, finance, and legal/admin scenarios produce
   equivalent contracts in Chinese, English, and mixed-language wording.
9. Routing reports `selected-installed`, `intended-unverified`, or `not-selected` without claiming that
   the host actually activated a Skill.
10. The public tree contains no creator-specific exam goals or private subject Skill defaults.

The executable regressions live in `tests/test_value_p0.py` and `tests/test_role_matrix_p0.py`.

The broader public conformance contract lives in [IntentBench v1](../benchmarks/intentbench-v1/README.md). Its gold labels are public and were used to repair the implementation, so its final score proves conformance to declared behavior rather than generalization to unfamiliar users. The contribution and prior-art boundary is documented in [contribution-boundary.md](contribution-boundary.md), and the controls are mapped to threats in [threat-model.md](threat-model.md).
