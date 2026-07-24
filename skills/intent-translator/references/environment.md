# Environment Compatibility

Run `scripts/detect_environment.py` to inspect the current machine without changing it.

The supported baseline is:

- Windows, macOS, or Linux;
- Python 3.10 or newer;
- a writable user configuration directory;
- Codex, Claude Code, or another Agent Skills-compatible host.

Obsidian, additional Skills, shell-specific commands, and network access are optional capabilities. Detect them before use and degrade to the portable path when possible.

## Degradation Rules

- No Obsidian: use configured SQLite memory or session-only behavior.
- No known host: provide the Skill folder and report manual installation requirements.
- No additional routed Skill: execute with the base agent when safe, or report the missing capability.
- No network: preserve the task envelope and continue local work; do not pretend live research succeeded.
- Python below 3.10: stop deterministic scripts and report the required upgrade.

Do not infer compatibility solely from the operating-system name. Use the diagnostic report's commands, directories, host signals, and warnings.
