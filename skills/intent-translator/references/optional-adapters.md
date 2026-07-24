# Optional Adapters

Optional adapters are disabled by default. Enable them in the local profile only after the host and storage behavior are understood.

## Session Hooks

Path: `optional/session-hooks/`

The adapter exposes two host-neutral events:

- `session_start`: return the most recent scoped handoff.
- `session_end`: persist a concise summary, decisions, and exact next action.

It does not register hooks automatically. A host-specific installer may bind these commands to equivalent lifecycle events. If the host has no reliable end event, use explicit invocation rather than pretending automatic capture is guaranteed.

## Reversible Context

Path: `optional/reversible-context/`

The adapter stores original sections in a local SQLite file keyed by SHA-256 and emits compact markers with previews. An agent may compile a shorter context using those markers and retrieve the exact original later.

This is a preservation layer, not a claim that arbitrary semantic compression is lossless. Do not delete source files after packing them. Keep the adapter local and do not transmit its store without separate authorization.
