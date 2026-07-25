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

The full gate checks version agreement, Python compilation, all tests, the versioned Alpha adversarial set, clean-room lifecycle behavior, concurrent and crash-safe profile writes, profile migration and rollback backups, the two-user stranger smoke, creator-profile contamination, secrets and private paths, Studio assets and entrypoint, source archives, wheels, a CycloneDX SBOM, and a fresh wheel install with doctor, onboarding, and MCP import. It does not create a Git remote, push a commit, publish a package, or make a release.

Studio binds to loopback by default. A non-loopback bind is rejected unless the operator supplies `--allow-network`; this opt-in is intended only for a trusted test network and is not required for normal Alpha use.

Source and package success do not prove that a long-running host has reloaded the new MCP. After a local upgrade, verify the compile receipt reports the expected actual runtime version and `active` state. A `stale` result requires restarting or reloading the host before host-level acceptance is complete.

## CI Requirements

- Windows, macOS, and Linux on Python 3.10 and 3.12.
- Clean install, replacement install, failed-upgrade rollback, uninstall with data preservation, and explicit purge.
- CodeQL, secret and private-path audit, creator-shadow audit, and package-content inspection.
- Version agreement across the repository, Skill, and Python package.
- Build provenance attestation for tagged package artifacts.

GitHub Alpha is blocked if any gate fails. A local pass is necessary but does not replace the first green run on GitHub-hosted systems.
