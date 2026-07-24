# Memory Protocol

Use local, user-controlled memory. Keep personal state outside the Skill and repository.

## Adapter Selection

Read the profile's `memory.adapter` field:

| Adapter | Use | Requirement |
|---|---|---|
| `sqlite` | Portable default for preferences, phrase mappings, decisions, and pointers | Python standard library only |
| `obsidian` | Human-editable notes and existing vault workflows | Accessible vault and Obsidian integration |
| `markdown` | Simple file-based memory without a database | Writable configured directory |
| `none` | Session-only behavior | No persistence |

If the configured adapter is unavailable, do not silently write elsewhere. Use session memory and report the unavailable backend when persistence affects completion. During onboarding, recommend SQLite unless the user explicitly chooses another adapter.

## SQLite

Use `scripts/memory_store.py` with the database path from the profile or `INTENT_TRANSLATOR_MEMORY_DB`.

```text
python scripts/memory_store.py --db <path> search --query <terms> --scope <scope>
python scripts/memory_store.py --db <path> add --kind <kind> --scope <scope> --text <text> --confidence confirmed
```

Use kinds such as `preference`, `phrase`, `decision`, `fact`, `warning`, and `pointer`. Search before adding. The script deduplicates exact scoped entries. SQLite FTS5 indexes dependency-free search tokens; Chinese text also receives unigrams, bigrams, and trigrams so retrieval does not depend on spaces.

Set `--stale-after-days` for facts likely to change. A value of `0` means no automatic staleness warning. Search results report `stale`, `access_count`, and `last_accessed_at`; stale memory may inform a clarification but must not silently override current evidence.

## Conflict Governance

Use `--conflict-key` when records are alternate values of the same setting or decision.

```text
python scripts/memory_store.py add --kind preference --scope global --conflict-key response-detail --text "先给结论" --confidence confirmed
python scripts/memory_store.py add --kind preference --scope global --conflict-key response-detail --text "完整展开" --confidence confirmed --on-conflict flag
python scripts/memory_store.py add --kind preference --scope global --conflict-key response-detail --text "先给结论，再给必要细节" --confidence confirmed --on-conflict replace
```

Apply this order: current explicit instruction, project scope, global scope, confidence, then recency. Same-scope active conflicts require clarification. Project memory may shadow a global default without deleting it. `replace` marks prior records `superseded`; `retract` preserves an audit event while removing the record from recall.

Sensitive memory requires `--sensitivity sensitive --retain-days <days>`. It expires automatically and is removed from active retrieval.

## Corrections

Corrections describe where the agent misunderstood or violated a confirmed rule. Keep them separate from ordinary memories so behavior change can be measured.

```text
python scripts/memory_store.py correction-add --scope <scope> --trigger <situation> --correction <required behavior> --severity high
python scripts/memory_store.py correction-search --scope <scope> --query <current goal>
python scripts/memory_store.py correction-outcome --id <id> --outcome heeded
```

Use `recurred` when the same failure happens after the correction was retrieved, `heeded` when observable behavior follows it, and `unknown` when the outcome cannot be judged. Do not claim the memory system improved behavior from retrieval counts alone.

For brief feedback, create a candidate first:

```text
python scripts/memory_store.py correction-suggest --message "太复杂了" --previous-behavior "Used a long explanation for a simple confirmation"
python scripts/memory_store.py correction-confirm --id <pending-id>
```

The first command returns one short confirmation prompt. Do not persist a vague or inferred correction before confirmation.

## Obsidian

Use the installed Obsidian Skill or CLI. Reuse equivalent existing notes. When no structure exists, prefer:

| Note | Contents |
|---|---|
| `AI/User Profile.md` | Stable facts, long-term goals, and confirmed preferences |
| `AI/Interaction Rules.md` | Phrase mappings and recurring workflow rules |
| `AI/Context Index.md` | Source files, projects, handoffs, and authoritative notes |

Read only matching notes or sections. Keep the original file authoritative and store a pointer rather than duplicating large content.

## Read And Write Rules

Read memory when a request depends on prior preferences, recurring phrase meanings, remembered files, or project decisions.

Write only when the user explicitly asks to remember something, establishes a future default, confirms a durable preference, or authorizes archiving reusable context. Preserve:

- concise content;
- kind and scope;
- source or artifact pointer;
- timestamp;
- confidence: `confirmed`, `observed`, or `inferred`.

Update contradictions instead of accumulating incompatible rules. Keep temporary task progress in a handoff or context pointer rather than the stable profile.

## Sensitive Data

Do not persist passwords, tokens, private keys, authentication codes, payment data, or unnecessary sensitive personal information. Require explicit authorization for the exact health, financial, identity, or similarly sensitive fact being retained. Keep storage local unless the user separately authorizes transmission.

## User Control

Support inspection, retraction, scoped deletion, complete deletion, export, and backup.

```text
python scripts/memory_store.py retract --id <id> --reason "user changed preference"
python scripts/memory_store.py export --output memory-export.json
python scripts/memory_store.py backup --output memory-backup.db
python scripts/memory_store.py purge --scope <scope> --confirm PURGE:<scope>
python scripts/memory_store.py purge --confirm PURGE:ALL
```

`purge` creates a database backup before deletion. Confirm complete or broad deletion because it is difficult to reverse. Never use deletion as a hidden side effect of profile reset, upgrade, or reinstall.
