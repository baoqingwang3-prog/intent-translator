# Release Quality Gate

The gate is intentionally stricter than the package build. It must fail before publication when tests, metadata, privacy isolation, lifecycle behavior, or package contents are unsafe.

## Local Commands

Fast preflight:

```bash
python scripts/release_gate.py --mode quick
```

Full cross-module check:

```bash
python scripts/release_gate.py --mode ci
```

Release candidate build and artifact inspection:

```bash
python -m pip install build
python scripts/release_gate.py --mode full
```

The full gate checks version agreement, Python compilation, all tests, clean-room lifecycle behavior, the two-user stranger smoke, creator-profile contamination, secrets and private paths, source archives, wheels, and a fresh wheel install with doctor, onboarding, and MCP import. It does not create a Git remote, push a commit, publish a package, or make a release.

## CI Requirements

- Windows, macOS, and Linux on Python 3.10 and 3.12.
- Clean install, replacement install, failed-upgrade rollback, uninstall with data preservation, and explicit purge.
- CodeQL, secret and private-path audit, creator-shadow audit, and package-content inspection.
- Version agreement across the repository, Skill, and Python package.
- Build provenance attestation for tagged package artifacts.

GitHub Alpha is blocked if any gate fails. A local pass is necessary but does not replace the first green run on GitHub-hosted systems.
