# Local Profile

The profile stores per-user adapter choices and interaction defaults outside the repository.

## Location

Resolution order:

1. `INTENT_TRANSLATOR_PROFILE`
2. `~/.intent-translator/profile.json`

Create or validate it with `scripts/init_profile.py`:

```text
python scripts/init_profile.py init --language auto
python scripts/init_profile.py validate
python scripts/init_profile.py show
python scripts/init_profile.py set-phrase --phrase "continue" --meaning "Resume the current unfinished flow"
python scripts/init_profile.py remove-phrase --phrase "continue"
python scripts/init_profile.py apply-pack --pack student-exam-prep --goal "exam name"
```

Profile packs are optional starting points, not inferred identities. Applying one merges generic defaults while preserving existing phrase mappings, memory settings, and private paths. Users must supply any local vault path explicitly.

## Fields

- `language`: Preferred language or `auto`.
- `response_style`: Output preferences that do not change task authority.
- `autonomy`: Defaults for reversible and high-impact actions.
- `adaptation`: Confirmed expertise, plain-language, accessibility, and domain preferences.
- `risk_policy`: Evidence and consent defaults for high-stakes work and sensitive memory.
- `optional_adapters`: Explicit switches for host hooks and reversible context storage. Defaults are off.
- `phrase_mappings`: User-confirmed shorthand and scoped meanings.
- `memory`: Adapter and local storage location.
- `cognitive_priors`: Optional, explicitly chosen interpretive hints.
- `study`, `knowledge_pointers`, and `shadow_evaluation`: Optional pack-provided workflow preferences that remain local and must not silently scan files or retain full utterances.

Treat cognitive priors as uncertain suggestions. Never use them to override current language, evidence, or user correction.

Do not require profession, age, diagnosis, or personality type. Prefer task-specific expertise and accessibility settings because they are more useful and less likely to stereotype the user.

## Portability

Do not put absolute paths, user IDs, memory databases, or private profiles in the public repository. Installers generate local defaults. A user may export a redacted profile template, but memory content remains separate.
