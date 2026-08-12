# Skill Composition Protocol

Use composition only when the request has distinct stages. A larger Skill list is not a better route.

## Stage Contract

| Stage | Responsibility | Limit |
|---|---|---|
| `pre_skills` | Acquire, normalize, inspect, or prepare inputs the primary owner needs | Usually 0-1 |
| `primary_skill` | Own the requested outcome and its domain workflow | Exactly 0-1 |
| `post_skills` | Render, verify, audit, persist, or package the primary result | Usually 0-2 |
| `fallback_skills` | Replace a failed capability owner; never run eagerly | Usually 0-1 |

Run stages in order. A post-Skill does not inherit permission to publish, pay, delete, install, or transmit data. Preserve the authorization boundary from the `ExecutionEnvelope` at every handoff.

## Composition Patterns

| Pattern | Composition |
|---|---|
| Live research report | search/retrieval -> `research` or `deep-research` -> requested document renderer |
| URL analysis | search/retrieval -> `defuddle` -> analysis owner |
| Draft a formatted office artifact | `doc-coauthoring` -> one of `docx` / `pdf` / `pptx` / `xlsx` |
| Diagnose and fix code | `diagnosing-bugs` -> implementation or `tdd` -> `code-review` |
| Build or update a Skill | optional `skill-lookup` -> `skill-creator` -> `skill-refactor` and validation |
| Structured exam study | `study-assistant` owns sequencing; expose only the one explicit `study-*` child needed for the current step |
| Job discovery to application | live retrieval -> `job-market-radar` -> `career-ops` after a concrete role is selected |
| Knowledge organization | `knowledge-base-organizer` -> `obsidian-cli` only when durable vault changes are requested |

## Conflict Rules

1. Select only one search owner from `agent-reach`, `smart-search`, `anysearch`, or `global-search`. Use another only as a fallback or for a clearly complementary source.
2. Select only one office-format owner for the final artifact. Content development may precede it.
3. Prefer an orchestrator over directly invoking all of its children. In particular, let `study-assistant` sequence `study-*` Skills.
4. Keep diagnosis, implementation, and verification separate. A diagnosis request alone does not authorize a fix.
5. Do not add a Skill merely because its keyword appears. It must own a distinct required stage.
6. Cap the eager composition at four Skills including the primary. If more appear necessary, split the work into checkpoints.
7. Treat fallbacks as dormant. Record why the primary failed before switching.

## Planner

After discovery, run:

```text
python scripts/compose_skills.py --utterance "<exact latest wording>" --context "<compact context>"
```

Pass `--primary <skill>` when semantic review has already selected the primary owner. Treat the output as a routing validator and staged suggestion, not as authorization and not as a substitute for reading the selected Skills.
