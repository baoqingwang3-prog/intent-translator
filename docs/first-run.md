# First Three Minutes

Intent Translator starts in generic mode. A generated profile file alone does not mean the system knows anything personal about its user.

## 1. Verify The Install

```bash
intent-translator-doctor
```

The doctor reports installation and Codex registration separately. If it says `installed-not-registered` or `registered-stale`, close Codex and run the repair command shown in the report. If it says `registered-pending-restart`, reopen Codex and verify the compile receipt reports `active` with the expected version.

The installer does not change Codex registration while Codex is running. This prevents the desktop app from overwriting a concurrent configuration update on shutdown.

## 2. Choose Three Local Preferences

```bash
intent-translator-onboard
```

For Skill-only installation, use the `scripts/onboard.py start` path printed by the installer.

The setup asks only:

1. Whether confirmed information may be remembered locally.
2. Whether important ambiguity should show choices or ask one question.
3. Whether answers should be concise, balanced, or detailed.

Every choice can be skipped. Important-decision sharp review is optional and off by default. The command prints a redacted summary, not the profile path or stored content.

An MCP-capable agent can use `intent_onboarding_status` and `intent_apply_onboarding` instead of asking the user to run the command.

## 3. Try A Real Sentence

Use the same language you normally use. For example:

> Continue the thing we just agreed to, but do not publish it yet.

The expected behavior is to recover the pending action, keep publication unauthorized, select an installed Skill when one clearly matches, and ask only when a materially different interpretation remains.

## Reset

Uninstalling the Skill or MCP preserves local profile and memory by default. Use the explicit purge confirmation only when local data should also be deleted.
