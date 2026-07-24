# Contributing

Thanks for helping make intent translation safer and easier to use.

## Before Opening An Issue

1. Run `intent-translator-doctor --json` or `python skills/intent-translator/scripts/detect_environment.py --compact`.
2. Remove personal text, exact home paths, profiles, memory databases, credentials, and private files from the report.
3. Check whether the problem reproduces with a temporary profile and memory database.

Security or privacy vulnerabilities belong in GitHub private vulnerability reporting, not a public issue.

## Development

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests -v
python -m compileall -q skills src tests
```

Run the Skill validator and secret scanner before a pull request. New routing or safety behavior needs at least one regression case and one focused unit test.

## Design Rules

- Keep personal profiles and memory out of the repository.
- Preserve local-first and reversible defaults.
- Do not treat personality, occupation, age, spelling, or dialect as deterministic identity.
- Keep deterministic safety checks separate from optional model interpretation.
- Do not improve benchmark numbers by encoding case IDs or copying expected outputs into production logic.
- Keep `SKILL.md` concise and move detailed material into directly linked references.

## Pull Requests

Describe the user-visible behavior, authorization impact, migration impact, tests run, and remaining limitations. Small, reviewable changes are preferred.
