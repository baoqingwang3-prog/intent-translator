# Short-confirmation hijack postmortem

## Summary

Several failures that looked like one keyword bug were caused by five interacting behaviors:

1. The host was still connected to an older MCP process after newer source code had been tested.
2. Legacy phrase matching allowed short confirmations such as `可以`, `好`, `继续`, and `OK` to match inside long requests.
3. A matched phrase meaning could replace the complete user sentence and outrank a more specific pending action.
4. The utterance, context, pending action, and prohibited actions were mixed into one text before risk and routing checks.
5. Routing scores favored object words such as `Skill` over the owner of the requested action, such as web search.

The result was repeatable: a long request containing an ordinary short word could be compiled as approval, a prohibition such as `不要发布` could be treated as an external action, and a GitHub search for Skills could route to `skill-creator` instead of `agent-reach`.

## Why source tests and the loaded host disagreed

Repository tests exercised the current source package, while the host kept a long-running older MCP process. Updating files on disk does not hot-reload a stdio MCP server. Without an explicit version handshake, a passing source test could be mistaken for proof that the connected host was fixed.

The P0 handshake now reports:

- actual running package version;
- installed versioned runtime;
- active Skill version and duplicate-copy versions;
- local profile schema version;
- invocation entrypoint;
- `active`, `stale`, or `degraded` state and whether a host restart is required.

The same evidence is present in compile results, decision receipts, doctor output, and onboarding status.

## Technical root causes

### Short phrase matching

Legacy matching used substring behavior for personal phrase rules. A phrase such as `可以` could therefore match `这些优点可不可以实现`. The matched expansion then became the normalized goal.

The compiler now hard-protects short confirmations even when a local profile incorrectly requests `contains`. Profile migration also changes dangerous short-confirmation mappings to `exact`, creates a backup, and reports the number of safety repairs.

### Pending action precedence

An exact `继续` mapping could produce a generic goal such as “continue the current process” even when the request carried a concrete pending action. The compiler now gives a specific pending action precedence and emits a sparse `context-resumption` source map entry.

A standalone confirmation without a pending action, recent context, or confirmed local state enters review and cannot execute.

### Negation scope

Keyword-only risk checks could not distinguish `发布到 GitHub` from `不要发布` or `不上传 GitHub`. The compiler now extracts explicit prohibited actions as constraints, removes those spans from action classification, and keeps the original prohibition visible in the result.

### Action ownership routing

The previous score could give `skill-creator` a higher score for the object word `Skill` than `agent-reach` received for the action word `搜索`. Search and research requests now assign ownership to `agent-reach` before object-name scoring.

### Unsupported semantic compression

A semantic adapter could propose a goal that differed materially from the original sentence. When that compression has low similarity and lacks reliable explanatory support, the original sentence remains the primary goal, the proposal becomes a candidate interpretation, and execution is blocked pending review.

## Why earlier tests missed it

The original suite covered isolated `继续` and `可以` messages, affirmative publication risk, and simple web search. It did not combine:

- short confirmations configured as `contains` with long sentences;
- a personal continuation mapping with a specific pending action;
- prohibitions with publication vocabulary;
- the action `search` with the object `Skill`;
- current source tests with a separately loaded long-running host process.

The versioned adversarial set at `evals/adversarial-alpha.jsonl` now covers these combinations. Release verification must distinguish source, built package, installed runtime, and restarted-host evidence.

## P0 prevention gates

- Short confirmations never match inside a longer request, regardless of local `contains` configuration.
- A short confirmation cannot execute without one specific previous action or confirmed local state.
- A specific pending action outranks a generic continuation mapping.
- Prohibited actions remain constraints and do not become requested external actions.
- Search and research action ownership outranks the name of the searched artifact.
- Unsupported large semantic compression preserves the original wording and blocks execution.
- Compile and diagnostic results expose the actual loaded version and stale-process state.
- Profile upgrades back up and repair unsafe short-confirmation matching rules.
- The adversarial cases pass against source, built artifacts, and the restarted installed MCP before the issue is considered closed.
