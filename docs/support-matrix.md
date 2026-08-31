# Host Support Matrix

This matrix describes verified behavior, not merely whether an installer can copy files or generate a configuration snippet.

| Host and platform | Skill workflow | Local MCP | Alpha status | Evidence and limits |
|---|---|---|---|---|
| Codex on Windows 10/11 | Supported | Supported after host restart | **Alpha-supported** | Local install, version handshake, Studio, doctor, adversarial regressions, rollback, uninstall, and one operator-driven preflight-to-tool trace are verified. Automatic interception of every turn is not claimed. |
| Codex on macOS/Linux | Supported | Configuration available | **Experimental** | Cross-platform scripts and CI are prepared; host-level MCP behavior remains remotely unverified. |
| Claude Code | Supported | Configuration available | **Experimental** | Skill discovery and generated snippets are covered. A `PreToolUse` hook can now deny or escalate a tool call before it runs, with local regression coverage of the exact decision envelope; see [host-enforcement.md](host-enforcement.md). Host-session evidence for the hook is still local only. |
| Cursor | Supported | Configuration available | **Experimental** | Skill use is available; MCP invocation and restart behavior need host-specific trials. Cursor loads Claude Code hooks, so the enforcement hook may apply unchanged, but that is untested. |
| Gemini CLI | Available | Generated snippet only | **Skill-only** | The Skill can be installed manually or through the shared root. **MCP unverified**. |
| Copilot / VS Code | Available | Generated snippet only | **Skill-only** | Host auto-invocation is not established. **MCP unverified**. |
| OpenCode | Available | Generated snippet only | **Skill-only** | Installation is prepared, but **MCP unverified** in a real host session. |

## Status Meanings

- **Alpha-supported**: locally exercised end to end for the stated platform, with known Alpha limits published.
- **Experimental**: installation and protocol surfaces exist, but host-specific behavior is incomplete or lacks external evidence.
- **Skill-only**: the prompt workflow can be installed, but deterministic MCP invocation is not a supported claim.
- **MCP unverified**: a generated snippet is not evidence that the host loads or calls the runtime correctly.

## Enforcement Versus Invocation

The columns above describe whether a host can install and call the runtime. Whether a host can be *made* to call it is a separate question, answered in [host-enforcement.md](host-enforcement.md). Without a host hook, every claim in this matrix depends on the host choosing to call the preflight.

## Runtime Handshake

Installing a new runtime does not replace an MCP process already held by a running host. After every MCP upgrade, restart or reload the host and verify that the compile receipt or Studio reports `active`, the expected actual runtime version, and no Skill/MCP version conflict. A `stale` state means host-level acceptance is incomplete.

The published Alpha line has passed the GitHub-hosted Windows/macOS/Linux matrix. A later local tree must not be described as remotely proven until the same checks pass for that exact commit.
