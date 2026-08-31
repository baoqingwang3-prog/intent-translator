# Host Enforcement

Everything else in this project is advisory. The compiler produces a decision, but a host reaches it only by choosing to call `intent_compile` first, and a model that skips the call and goes straight to a shell command bypasses every control. This document covers the one mechanism that closes that gap: a host hook that runs before a tool call and can refuse it.

Claude Code is the first supported host. Cursor and Codex expose comparable hooks with different limits, recorded at the end.

## What The Hook Does

Two events are needed, because a `PreToolUse` hook receives the tool call and not the user's wording, while the compiler requires the exact wording.

| Event | Purpose |
|---|---|
| `UserPromptSubmit` | Record the latest prompt for the session so the next tool call can be compiled against real wording. |
| `PreToolUse` | Compile that prompt, classify the tool call the host is about to make, and return a decision. |
| `SessionEnd` | Forget the recorded prompt. |

On each `PreToolUse` call the hook does four things in order:

1. **Classify the tool call.** The effect of the *action* is named with the compiler's own vocabulary (`destructive`, `write_external`, `system_change`, `write_local`, `read_public`, `read_local`) so it can be compared against the compiled request directly.
2. **Deny anything the request denied.** A blocked request blocks every tool call, including a harmless-looking one.
3. **Deny a prohibited action class.** `千万不要发布` followed by `git push` is refused, and the reason names the exact command.
4. **Escalate a consequential action** that is unconfirmed, or that is more consequential than the request appears to be.

Everything else prints nothing.

## The Hook Never Widens Permissions

An allowed verdict exits 0 with no output, which Claude Code documents as "no decision: the normal permission flow applies."

This is deliberate. Returning `permissionDecision: "allow"` would *skip* Claude Code's own permission prompt, so a preflight that answered "allow" would be quietly removing a control the user had configured. The hook may raise friction and never lower it, which is the same rule the compiler applies to its semantic layer.

Preparation is not gated either. An unconfirmed transfer means the *transfer* needs confirmation, not that the agent may not read a file or write a local draft while preparing it. Only a tool call that is itself consequential is measured against the request.

## Install

```bash
intent-translator-hook install                 # ~/.claude/settings.json
intent-translator-hook install --scope project # <project>/.claude/settings.json
intent-translator-hook print-settings          # emit the block without writing it
intent-translator-hook uninstall
```

The installer merges into the `hooks` block and leaves every other hook and setting alone; installing twice does not duplicate the handler, and uninstalling removes only this project's handler. Restart Claude Code afterwards.

The generated handler runs the current interpreter with `-m intent_translator_mcp.host_hook run`, so the hook uses the same runtime as the installer rather than whatever `PATH` resolves to inside the host.

The default `PreToolUse` matcher is `Bash|PowerShell|Write|Edit|NotebookEdit|WebFetch|mcp__.*`. Scope the hook with `matcher`, which Claude Code evaluates against the tool name, rather than with a handler's `if` field: the Claude Code documentation calls `if` best-effort and advises against relying on it for a hard allow or deny. This project's own MCP tools are always allowed, so the hook cannot gate itself.

## Configuration

| Setting | Effect |
|---|---|
| `INTENT_TRANSLATOR_HOOK_ON_ERROR` | `ask` (default), `deny`, or `allow`. What an unusable preflight means: see below. |
| `INTENT_TRANSLATOR_HOOK_SESSION_TTL` | Seconds a recorded prompt stays usable. Default 12 hours. |
| `INTENT_TRANSLATOR_DATA_DIR` | Where the recorded prompt and the receipt ledger live. Every process that must agree needs the same directory. |

The hook reads its input and writes its decision as UTF-8 directly, without going through the console's code page. A hook exchanges the user's own wording, which frequently cannot be represented in a Windows console encoding, and a decoding error while a tool call waits on a decision would be resolved by the error policy rather than by the request.

The recorded prompt is the user's own text. It is kept as one row per session rather than a history, written with owner-only permissions, expired on a timer, and deleted when the session ends.

## Failure Behavior

Claude Code cannot fail closed on this project's behalf: a crashed, timed-out, or unparseable hook is a non-blocking error, and the tool call proceeds. The hook therefore takes its own position whenever it cannot produce a verdict — an unreadable event, a compiler that raises, or a consequential tool call in a session whose prompt was never recorded. By default it escalates to the user rather than silently allowing or hard blocking. `INTENT_TRANSLATOR_HOOK_ON_ERROR=deny` converts those cases into a block.

A timeout is the one case the hook cannot cover, because a hook that never answers cannot answer with `ask`. Keep the configured `timeout` well above the preflight's normal cost, which is a few milliseconds.

## Known Limits

- **Shell text is matched, not parsed.** An unrecognized command is reported as `read_local`, so a consequential command written in a form these patterns do not cover is not escalated. The classifier raises suspicion on what it recognizes and never invents it.
- **A prohibition blocks its whole action class.** The contract records `不要删除 data 目录` as a prohibition on `delete` without the object, so the hook refuses deletion generally. Narrowing that is compiler work, not hook work.
- **A third-party MCP tool is judged by the shape of its name.** A name containing `write`, `send`, `delete`, `publish` and similar is treated as leaving the machine; anything else is treated as a public read.
- **The utterance can be missing.** A session resumed from before the hook was installed, or one whose prompt has expired, has no recorded wording. Consequential calls then escalate.
- **The host's own prompt is the human gate in this path.** The hook has no channel to return an action-bound confirmation receipt to the user and read the answer back, so `ask` hands the decision to Claude Code's permission prompt, which does display the exact action. Receipts remain the mechanism for the MCP path described in [integration-contract.md](integration-contract.md).
- **Enforcement can be turned off.** `claude --settings '{"disableAllHooks": true}'`, `claude --bare`, or an edit to `settings.json` removes the hook. Only Claude Code's managed policy settings resist that, and hook entries there merge rather than being replaced.
- **Some paths never produce a tool call.** A file inlined with `@` in a prompt, or a directly invoked `/skill`, does not fire `PreToolUse`.
- **One approved shell call is one tool call.** The hook sees the command string, not what the spawned process goes on to do.

## Other Hosts

| Host | Mechanism | Status here | The limit that matters |
|---|---|---|---|
| Claude Code | `PreToolUse` hook | **Implemented** | A deny is evaluated before permission rules and beats an allow rule. |
| Cursor | `beforeShellExecution`, `beforeMCPExecution` in `.cursor/hooks.json` | Not implemented | The only host with a `failClosed` option, so a crashed checker can be made to deny. Cursor also loads Claude Code hooks, so this hook may work there unchanged. Cloud agents do not run `beforeMCPExecution` at all. |
| Codex | `PreToolUse` hook | Not implemented | `permissionDecision: "ask"` is parsed but **not supported**: Codex marks the hook failed and *continues the tool call*. Every `human_review` would have to become a hard deny. Codex also records trust against the hook's hash, so a runtime upgrade silently disables enforcement until a human re-trusts it. |
| MCP protocol | none | Not possible | Nothing in the 2026-07-28 spec lets one server gate another's tool call, and no MCP mechanism reaches a host's own shell and edit tools. The proposal that would provide it, SEP-2624 interceptors, is open and unmerged. |
