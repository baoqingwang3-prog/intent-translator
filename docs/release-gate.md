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

The full gate checks version agreement, Python compilation, all tests, the versioned Alpha adversarial set, clean-room lifecycle behavior, concurrent and crash-safe profile writes, profile migration and rollback backups, the five-user stranger rehearsal, creator-profile contamination, secrets and private paths, Studio assets and entrypoint, source archives, wheels, a CycloneDX SBOM, and a fresh wheel install with doctor, onboarding, and MCP import. It does not create a Git remote, push a commit, publish a package, or make a release.

Studio binds to loopback by default. A non-loopback bind is rejected unless the operator supplies `--allow-network`; this opt-in is intended only for a trusted test network and is not required for normal Alpha use.

Run the real browser gate separately after installing the pinned Playwright driver. It starts Studio in an isolated temporary home, uses synthetic Skills, checks desktop and `390x844` mobile layouts, and exercises the four Alpha scenarios without reading the creator profile:

```bash
npm install --no-save --package-lock=false playwright@1.61.1
npx playwright install chromium
python scripts/studio_browser_smoke.py --node-modules node_modules --output work/studio-browser-smoke-report.json --screenshot-dir work/studio-browser-smoke
```

The latest redacted local evidence is [studio-browser-smoke-0.7.0a3.json](evidence/studio-browser-smoke-0.7.0a3.json). The GitHub workflow prepares the same test as an independent required job; it remains remote-unverified until the repository is actually pushed and the hosted job runs.

Source and package success do not prove that a long-running host has reloaded the new MCP. The installer must refuse Codex registration changes while Codex is open, use the native Codex CLI after exit, and pass the registration overwrite regressions. After a local upgrade, verify the compile receipt reports the expected actual runtime version and `active` state. A `stale` result requires restarting or reloading the host before host-level acceptance is complete.

## CI Requirements

- Windows, macOS, and Linux on Python 3.10 and 3.12.
- Clean install, replacement install, failed-upgrade rollback, uninstall with data preservation, and explicit purge.
- CodeQL, secret and private-path audit, creator-shadow audit, and package-content inspection.
- Version agreement across the repository, Skill, and Python package.
- Build provenance attestation for tagged package artifacts.

GitHub Alpha is blocked if any gate fails. A local pass is necessary but does not replace the first green run on GitHub-hosted systems.
