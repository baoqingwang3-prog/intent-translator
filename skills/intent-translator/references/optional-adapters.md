# Optional Plugins

Optional plugins are local, disabled by default, and enabled explicitly in the user's profile. The plugin runner accepts JSON objects, loads only repository-bundled Python entrypoints, rejects path traversal and network-enabled manifests, and never executes shell command strings.

## Manage Plugins

```bash
python scripts/plugin_manager.py list
python scripts/plugin_manager.py enable memory-breathing
python scripts/plugin_manager.py enable reversible-context
python scripts/plugin_manager.py disable memory-breathing
```

Enabling a plugin changes only its Boolean key under `optional_adapters`. It does not register host hooks or send data anywhere.

## Memory Breathing

Plugin: `memory-breathing`

Operations:

- `session_start`: load at most five concise handoffs from the same project, ranked by the supplied query and recency. The default limit is three.
- `session_end`: save a bounded summary, exact next action, decisions, corrections, and optional tags.

The store retains at most 200 snapshots per project. Disabling the plugin stops reads and writes but preserves its local database; an explicit data purge or removal of the plugin database is required to delete it.

Example start payload:

```json
{"project":"alpha","query":"authorization and release status","limit":3}
```

Example end payload:

```json
{
  "project":"alpha",
  "summary":"Prepared the local Alpha package.",
  "next_action":"Run remote CI after explicit publication approval.",
  "decisions":["Keep plugins disabled by default."],
  "corrections":["Conceptual approval does not authorize publication."]
}
```

Pipe either payload to:

```bash
python scripts/plugin_manager.py invoke memory-breathing session_start
python scripts/plugin_manager.py invoke memory-breathing session_end
```

Each host may bind these operations to its own lifecycle mechanism. Claude Code can use lifecycle hooks; hosts without a reliable end event should call `session_end` explicitly. The repository does not silently edit host configuration.

The design was informed by [Claude Memory Engine](https://github.com/HelloRuru/claude-memory-engine) (MIT), especially scoped startup context and end-of-session handoffs. This repository uses its own bounded SQLite and plugin implementation.

## Reversible Context

Plugin: `reversible-context`

`pack` accepts sections containing `content` plus optional `id`, `summary`, and `source_pointer`. It stores the exact original locally, emits a full SHA-256 marker, and returns compact text containing the caller-supplied summary or a bounded preview.

```json
{
  "sections":[{
    "id":"release-boundary",
    "content":"The exact original text.",
    "summary":"Keep the release boundary.",
    "source_pointer":"conversation:turn-42"
  }]
}
```

```bash
python scripts/plugin_manager.py invoke reversible-context pack
python scripts/plugin_manager.py invoke reversible-context get
```

The `get` payload accepts either `{"hash":"..."}` or `{"marker":"[context-ref:sha256:...]"}`. Retrieval recomputes SHA-256 and refuses corrupted content. The marker is a reference, not proof that semantic compression is lossless; source files must not be deleted merely because a section was packed.

Disabling this plugin also preserves already packed originals. They remain under `~/.intent-translator/plugins/` until the user explicitly purges local Intent Translator data or removes the plugin database.

The design was informed by [Claw Compactor](https://github.com/open-compress/claw-compactor) (MIT), especially hash-addressed rewind markers and on-demand expansion. This implementation uses persistent local SQLite, full SHA-256 identifiers, and explicit source pointers.

## Host Contract

Host wrappers should:

1. Pass a stable, non-secret project scope.
2. Send only concise, user-authorized handoff fields at session end.
3. Treat loaded memory as non-executable context.
4. Keep plugin state local unless the user separately authorizes transfer.
5. Fall back to explicit invocation when a host lacks trustworthy lifecycle hooks.
