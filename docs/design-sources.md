# Design Sources

This project implements its own code and wording. The following open-source projects informed specific architectural choices.

| Project | License | Ideas studied |
|---|---|---|
| [AgentRecall-X](https://github.com/Goldentrii/AgentRecall-X) | MIT | Correction-first memory, recurrence measurement, small default tool surface, session lifecycle |
| [claude-memory-engine](https://github.com/HelloRuru/claude-memory-engine) | MIT | Scoped context, checkpoints, handoffs, correction cycle |
| [Claw Compactor](https://github.com/open-compress/claw-compactor) | MIT | Content-aware gates, non-destructive benchmarks, reversible context references |
| [Superpowers](https://github.com/obra/superpowers) | MIT | Behavior pressure tests and evidence-before-completion discipline |
| [claude-skills](https://github.com/alirezarezvani/claude-skills) | MIT | Voice preservation, complexity matching, context freshness, external anonymization |
| [sync-skill](https://github.com/william-garden/sync-skill) | MIT | Cross-host directory matrix and non-destructive overwrite behavior |
| [mem0](https://github.com/mem0ai/mem0) | Apache-2.0 | Memory lifecycle, explicit operations, expiration, and evaluation separation |

Repositories without a clear compatible license may be used for behavioral comparison but are not copied into this project.

Open source remains copyrighted. Reuse must follow each source license, preserve notices when required, and avoid importing incompatible obligations accidentally.
