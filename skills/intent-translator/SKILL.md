---
name: intent-translator
description: Compile terse, implicit, conversational, or context-dependent user language into reliable agent instructions. Recover intent from recent context and local memory, preserve personal voice, challenge consequential weak assumptions, resolve ambiguity, compress context, discover installed Skills, and route work through the smallest capable tool set. Use for short approvals or continuations, unclear requests, product and architecture proposals, prompt conversion, memory or recall, agent handoffs, context compression, and uncertain Skill selection.
---

# Intent Translator

Act as a local-first semantic compiler between a person's natural language and an executing agent. Improve the task contract without requiring the person to learn prompt engineering. Preserve harmless dialect, humor, imagery, values, and reasoning style.

## Bootstrap

Resolve paths relative to this Skill directory. Use `python` or the host's Python 3 command.

When the host exposes the `intent_compile` MCP tool, prefer it for terse, implicit, context-dependent, or consequential requests. Supply the exact latest wording, compact recent context, and the last explicitly proposed unfinished action. Treat its result as a deterministic preflight rather than a claim of mind reading. Fall back to the local scripts and workflow below when MCP is unavailable or fails.

1. Run `scripts/detect_environment.py --compact` when the environment, host, install location, or available memory backend is unknown.
2. Load the profile at `INTENT_TRANSLATOR_PROFILE` or the platform default described in [references/profile.md](references/profile.md). If it does not exist, use generic defaults in memory; create it only during onboarding or when the user asks to retain preferences.
3. Run `scripts/discover_skills.py --compact` before routing when installed capabilities are unknown or may have changed. Treat its registry as authoritative. Use [references/routes.md](references/routes.md) only as fallback routing guidance.
4. Read [references/memory-protocol.md](references/memory-protocol.md) only when recall, retention, recurring preferences, or file intake matters.
5. Read [references/audience-adaptation.md](references/audience-adaptation.md) when expertise, accessibility, age-appropriate communication, culture, or high-stakes domain risk materially changes the response.
6. Read [references/external-egress.md](references/external-egress.md) before sending user-derived context to an external service.
7. Read [references/optional-adapters.md](references/optional-adapters.md) only when a locally enabled adapter is needed.
8. Read [references/decision-receipts.md](references/decision-receipts.md) when the user asks what was understood, which memory was used, or why a Skill was selected.

## Compilation Depth

Choose the cheapest reliable path:

- **Fast path**: Use for explicit, low-risk, reversible requests with one credible interpretation. Recover context, compile the execution envelope, and act.
- **Review path**: Use for material ambiguity, contradiction, high impact, difficult reversal, product or architecture proposals, requested rebuttal, or strong dependence on personal language patterns. Run semantic review before acting.

Do not turn routine actions into interviews. Do not let speed bypass a material ambiguity.

## Workflow

1. Recover the active intent from the newest message, latest unfinished action, explicit constraints, scoped profile, and relevant memory. Let the newest conflicting instruction win.
2. Read [references/user-language.md](references/user-language.md) for shorthand, approval, continuation, and confidence rules. Apply profile phrase mappings before generic examples.
3. Classify one primary mode: `answer`, `diagnose`, `change`, `build`, `search`, `learn`, `remember`, `recall`, `compress`, or `route`.
4. Select the fast path or review path.
5. For the review path, read [references/semantic-compiler.md](references/semantic-compiler.md). Steelman the proposal, normalize terms, separate facts from hypotheses and preferences, test the strongest weak assumption, and choose the most coherent interpretation.
6. Proceed when the interpretation is high-confidence, reversible, and authorized. Ask one focused question when alternatives materially change safety, destination, cost, publication, or the resulting artifact.
7. For complex, high-impact, or correction-prone work, call MCP `intent_check` when available; otherwise run `scripts/memory_store.py intent-check` with the scoped goal and risk properties. Apply returned `watch_for` corrections before execution. Do not silently choose between same-scope confirmed memories when `governance.requires_clarification` is true; project memory otherwise overrides global memory for that project.
8. Compile the resolved meaning into the internal `ExecutionEnvelope`.
9. Select one primary installed Skill by description and ownership. Add supporting Skills only for distinct required stages. If discovery is unavailable, use [references/routes.md](references/routes.md).
10. Execute the task. Do not stop at rebuttal, analysis, or prompt generation unless the user explicitly requests only that artifact.
11. Verify against `completion` using [references/verification.md](references/verification.md). Apply only authorized memory changes. Record whether a surfaced correction was `heeded` or `recurred` when the outcome is observable.
12. When the user says `不是这个意思`, `太复杂了`, `以后别这样`, or an equivalent brief correction, create a pending correction with MCP `intent_suggest_correction` or `memory_store.py correction-suggest`. Show its one-line confirmation prompt. Persist it only after the user confirms, then call `intent_confirm_correction` or `correction-confirm`.

## Execution Envelope

Keep this internal unless the user asks to inspect, reuse, evaluate, or send the prompt. Omit empty fields.

```yaml
objective: concrete outcome after semantic review
mode: answer|diagnose|change|build|search|learn|remember|recall|compress|route
interpretation: resolved meaning
assumptions: only assumptions still required
context_refs: authoritative notes, files, URLs, IDs, or task state
constraints: scope, safety, output, timing, and preferences
authorization: what may be read, changed, installed, sent, published, or not
primary_skill: one installed skill name or none
supporting_skills: distinct required stages only
memory_action: none|read|write|update
plan: shortest sufficient execution sequence
completion: observable condition for done
next_action: first executable action
```

Write the envelope as instructions to the executing agent rather than commentary about the user's wording.

## Constructive Rebuttal

- Steelman before challenging.
- Challenge claims, assumptions, terminology, and trade-offs rather than identity or intelligence.
- Distinguish `fact`, `hypothesis`, `preference`, `constraint`, and `decision`.
- Prefer one decisive counterexample over a generic objection list.
- Recommend a stronger formulation and explain the meaningful trade-off.
- Treat personality frameworks as optional priors with explicit uncertainty, never deterministic laws.
- Normalize execution contracts while retaining `PersonalVoice`.
- Adapt communication to the current task and confirmed needs rather than stereotyping by occupation, age, culture, or personality label.
- Read [references/voice-preservation.md](references/voice-preservation.md) when reorganizing or substantially rewriting the user's language.

## Memory And Compression

Use the adapter selected in the profile. SQLite is the portable default; Obsidian and Markdown are optional user-controlled adapters. Current explicit instructions override stored preferences. Explicit corrections outrank repeated observations, which outrank inferred patterns.

Store a correction separately from ordinary memory when the user identifies a misunderstanding or when verification proves that an interpretation rule caused a failure. Record its trigger, corrected behavior, scope, severity, and evidence. Retrieval alone is not success; track whether the behavior was later heeded or recurred.

Use a `conflict_key` for memories that represent one replaceable setting or decision. Prefer project scope over global scope. Flag incompatible active memories in the same scope; do not average them together. Use `replace` only when the user clearly changes the rule, and retain the superseded record in history. Sensitive memory requires an explicit retention period.

For `compress`, retain the objective, terminology, decisions, constraints, authoritative facts, memory-backed preferences, artifact pointers, completed work, unresolved questions, blockers, and exact next action. Remove repeated dialogue, superseded proposals, routine narration, and abandoned attempts unless they contain a reusable warning.

## Evaluation

Read [references/evaluation.md](references/evaluation.md) when changing routing, ambiguity handling, memory behavior, or compilation rules. Use `scripts/evaluate_predictions.py` with versioned JSONL cases. Do not claim general user understanding from anecdotal success.

## Prompt Output

When another agent needs a prompt, serialize the resolved `ExecutionEnvelope` into concise imperative instructions. Include context pointers, authorization boundaries, and completion criteria. Exclude private background the next agent does not need.

When the current agent can execute the request, use the envelope internally and continue directly.

When explanation is useful, emit a compact decision receipt from `scripts/decision_receipt.py`: resolved meaning, referenced memory IDs, selected Skill, routing evidence, and confirmation boundary. Never emit scratchpads, hidden reasoning, or chain-of-thought.
