# Governed Learning Lifecycle

Use this lifecycle when repeated corrections, failures, successful patterns, or explicit preferences may improve future behavior.

## Lifecycle

1. **Capture** a concise candidate with `scripts/learning_lifecycle.py capture`. Preserve scope, type, summary, and bounded evidence. Exact repeats increase `occurrence_count` instead of creating duplicates.
2. **Review** candidates with `signals`. Repetition is evidence that review matters; it is not user confirmation.
3. **Promote** only after the user explicitly accepts the exact candidate. Use `--confirm PROMOTE:<id>`. Promotion writes through the existing governed memory store as `user_confirmed` and starts at the `hot` retrieval tier.
4. **Reinforce** a stored memory only when its usefulness is observable. `helpful` and `unhelpful` outcomes change retrieval tier, never confidence, provenance, trust, authority, or authorization.
5. **Maintain** tiers with a dry run first. Apply demotion only with `maintain --apply`. Stale or repeatedly unhelpful memories become `cold`; repeatedly helpful memories become `hot`.
6. **Verify** behavior with a regression case and fresh command output before claiming improvement.

## Source Repair Escalation

Treat a candidate as a `source-fix candidate` when the same scoped failure appears at least twice, appears at least three times across active and historical evidence, or recurs after a governing rule already exists.

1. Locate the smallest source that can prevent recurrence: the owning Skill, reference template, validation script, hook, or project rule.
2. Reproduce the failure with a regression test or a deterministic validation command before changing the source.
3. Use `skill-creator` and `writing-for-agents` when the source is agent-facing documentation; preserve progressive disclosure and one source of truth.
4. Apply the smallest source repair, then run the regression and the owning Skill's validation suite.
5. Record the repaired source path and verification evidence. Archive or dismiss the candidate only after the check passes.

Source repair is a reviewed maintenance action. The lifecycle may recommend it, but never edits `SKILL.md`, project rules, templates, hooks, or scripts by itself. Durable user preferences and consequential rules still require explicit confirmation.

## Capture Policy

Capture candidates for:

- explicit corrections that are not yet durable rules;
- execution failures with a reusable cause;
- explicit preferences that may deserve cross-task reuse;
- successful patterns proven by an observable result;
- reflections grounded in a completed task.

Keep ordinary task narration, speculative personality claims, silence, one-off mood, secrets, and unverified web content out of learning candidates. Use the dedicated correction workflow when the user directly identifies a misunderstanding.

## Safety Boundary

- A candidate is non-authoritative and local-only.
- Automatic promotion is unavailable.
- Repetition cannot create permission or a confirmed preference.
- Promotion cannot pre-authorize publication, external transfer, destructive work, payment, or sensitive-data handling.
- The lifecycle never edits `SKILL.md`, `AGENTS.md`, hooks, profile, or policy by itself.
- Scheduled heartbeat behavior is outside this Skill. Run maintenance only during requested maintenance or a natural session end.

## ADHD And Profile Composition

Use the profile to choose goals, domain routing, continuity, scope, and authorization defaults. When `i-have-adhd` is active, use it only to shape delivery: lead with the next action, bound steps, suppress tangents, restate state, and make progress visible. An accessibility style never changes inferred intent, memory authority, or safety gates.

For nonurgent candidates during study, capture silently and batch review until the study session ends. Interrupt only when the candidate exposes a current correctness or safety risk.

## Commands

Run `python scripts/learning_lifecycle.py --help` for the current interface. Typical flow:

```text
python scripts/learning_lifecycle.py capture --scope project:x --type failure --summary "..." --evidence "..."
python scripts/learning_lifecycle.py signals --scope project:x --status candidate
python scripts/learning_lifecycle.py promote --id 7 --kind warning --confirm PROMOTE:7
python scripts/learning_lifecycle.py reinforce --id 12 --outcome helpful
python scripts/learning_lifecycle.py maintain --scope project:x
python scripts/learning_lifecycle.py maintain --scope project:x --apply
python scripts/learning_lifecycle.py stats --scope project:x
```

Use `memory_store.py export`, `retract`, `delete`, or `purge` for inspection, forgetting, and recovery controls.
