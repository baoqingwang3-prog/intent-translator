# Design Sources

This project implements its own code and wording. The following open-source projects informed specific architectural choices.

The exact project contribution and the mechanisms not claimed as original are separated in [contribution-boundary.md](contribution-boundary.md).

| Project | License | Ideas studied |
|---|---|---|
| [TypeChat](https://github.com/microsoft/TypeChat) | MIT | Schema-first intent contracts, validation, and repair instead of free-text completion |
| [Instructor](https://github.com/567-labs/instructor) | MIT | Pydantic output validation and explicit failure when required fields are missing |
| [Workflow-skill-router](https://github.com/eric861129/Workflow-skill-router) | MIT | One primary plus at most three supporting Skills, smallest verifiable capability set, and separate capability facts |
| [Semantic Router](https://github.com/aurelio-labs/semantic-router) | MIT | Calibrated routing thresholds and abstaining with `None` when no route matches |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | MIT | Typed approval outcomes and capability-oriented agent contracts |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | Action-bound interrupt/resume semantics without broad future authorization |
| [PMB](https://github.com/oleksiijko/pmb) | Apache-2.0 | SQLite as durable local truth, rebuildable indexes, and no model call on the read path |
| [AgentRecall-X](https://github.com/Goldentrii/AgentRecall-X) | MIT | Correction-first memory, recurrence measurement, small default tool surface, session lifecycle |
| [claude-memory-engine](https://github.com/HelloRuru/claude-memory-engine) | MIT | Scoped context, checkpoints, handoffs, correction cycle |
| [Claw Compactor](https://github.com/open-compress/claw-compactor) | MIT | Content-aware gates, non-destructive benchmarks, reversible context references |
| [Superpowers](https://github.com/obra/superpowers) | MIT | Behavior pressure tests and evidence-before-completion discipline |
| [claude-skills](https://github.com/alirezarezvani/claude-skills) | MIT | Voice preservation, complexity matching, context freshness, external anonymization |
| [sync-skill](https://github.com/william-garden/sync-skill) | MIT | Cross-host directory matrix and non-destructive overwrite behavior |
| [mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | Memory lifecycle, explicit operations, expiration, and evaluation separation |
| [promptfoo](https://github.com/promptfoo/promptfoo) | MIT | Versioned evaluation matrices, CI gates, and adversarial regression cases |

Repositories without a clear compatible license may be used for behavioral comparison but are not copied into this project.

Open source remains copyrighted. Reuse must follow each source license, preserve notices when required, and avoid importing incompatible obligations accidentally.

The Alpha implementation borrows mechanisms and terminology only. It does not vendor these projects or add their runtimes as dependencies.
