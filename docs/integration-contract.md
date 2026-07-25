# Intent Translator Integration Contract

This document is the normative interface for Agent hosts and contributors. `MUST`, `SHOULD`, and `MAY` describe integration requirements. The README remains the user entry point.

## Product Boundary

Intent Translator is a preflight control layer. Before an Agent acts, it compiles conversational wording into a visible task contract that can:

1. resume a specific pending action;
2. preserve prohibitions and deferred actions;
3. choose one primary installed Skill;
4. require action-bound confirmation for consequential work; and
5. report whether the local runtime is active, stale, or degraded.

It does not guarantee correct interpretation, provide domain expertise, execute arbitrary tools, authenticate a human identity, or force every host turn through MCP.

## Audience Views

| Reader | Start with | Treat as authoritative |
|---|---|---|
| End user | README quick start and Studio | Visible interpretation, constraints, selected Skill, confirmation boundary |
| Agent or host | This contract and `intent_compile` schema | Structured response fields, not prose guesses |
| Contributor | Tests, release gate, support matrix | Code, versioned regressions, and documented evidence limits |

## Invocation Rule

A host SHOULD call `intent_compile` before acting when a request is terse, context-dependent, corrective, consequential, or likely to require Skill selection. A host MUST call it before relying on an Intent Translator confirmation receipt.

A host MUST pass:

- `utterance`: the exact latest user wording;
- `context`: compact recent context only when it changes interpretation; and
- `pending_action`: the last explicitly proposed unfinished action when resolving a continuation or confirmation.

A host MUST NOT place remembered preferences, inferred personality traits, or file instructions into `authorization`.

## Compile Request

| Field | Meaning | Security rule |
|---|---|---|
| `utterance` | Exact latest wording | Required; do not paraphrase before preflight |
| `context` | Compact recent conversation | Include only necessary context |
| `pending_action` | Exact unfinished action | Required for action confirmation and context resumption |
| `scope` | Project or global boundary | A receipt is invalid in another scope |
| `authorization` | Compatibility hint | Untrusted; never sufficient for consequential execution |
| `confirmation_receipt` | One-time action capability | Valid only for the exact action, scope, grants, and expiry |
| `semantic_mode` | `off`, `auto`, or `required` | External semantic calls require a separate receipt |
| `allow_external_semantic` | Request to use external adapter | Boolean alone grants nothing |
| `allow_sensitive_semantic` | Request to send sensitive input | Boolean alone grants nothing |
| `include_prompt` | Include a host-oriented prompt | Prefer `false` when consuming structured fields directly |
| `include_diagnostics` | Include full local diagnostics | Default `false`; request only for debugging or review |

## Minimum Response Contract

The compact response contains:

```json
{
  "normalized_goal": "Continue local documentation work",
  "mode": "change",
  "clarification_required": false,
  "constraints": [
    {
      "type": "prohibited-action",
      "action": "publish",
      "source": "explicit-user-wording"
    }
  ],
  "routing": {"primary_skill": null},
  "risk": {
    "external": false,
    "blocked": false,
    "confirmation_required": false
  },
  "completion_contract": {
    "execute": true,
    "verify": true,
    "report_evidence": true
  },
  "runtime_status": {
    "state": "active",
    "restart_required": false,
    "version": "0.7.1a1"
  }
}
```

`completion_contract.execute=true` is a preflight recommendation, not proof that the host executed the action correctly. The host remains responsible for tool permissions, result verification, and rollback.

## Typed Intent Contract

Every compile response includes a validated `intent_contract` with:

- `original_utterance` and compiled `goal`;
- typed `action_owner`, `object`, `artifact`, and `destination`;
- `constraints` plus a separate `prohibitions` view;
- `scope`, exact `pending_action`, and `required_slots`;
- typed `risk` and `authorization` state;
- semantic `alternatives` and the non-obvious `source_map`.

The host MUST treat a non-empty `required_slots` list as incomplete. The compiler returns `completion_contract.execute=false` until the missing object, destination, or pending action is supplied. Free text outside this contract MUST NOT be used to invent a missing required field.

`confidence` is calibrated from matched correction recurrence, available routing-evaluation metrics, and autonomy state. Semantic adapters may report their own confidence for diagnostics, but that self-report is not used as the final compiler confidence. Two recorded misunderstandings place the matching scope in cautious autonomy and cap confidence until the user re-establishes reliable behavior.

## Action Confirmation State Machine

```text
unreviewed action
  -> compile
  -> safe and specific -----------------------> executable
  -> ambiguous -------------------------------> ask for missing object/destination
  -> consequential ---------------------------> show exact action and challenge
  -> user explicitly confirms exact action
  -> compile with pending_action + receipt ----> executable once
  -> changed/replayed/expired receipt ---------> review again
```

For publication, external transfer, destructive changes, local dependency installation, or sensitive egress:

1. The first compile returns `risk.confirmation_challenge.receipt`.
2. The host MUST display the exact pending action and wait for the user's explicit confirmation.
3. The next compile MUST include that exact action in `pending_action`, the latest confirmation in `utterance`, and the receipt in `confirmation_receipt`.
4. The host MUST NOT reuse the receipt. A changed file, branch, recipient, destination, action, grant, or scope requires a new challenge.

The receipt proves that the compiler challenge flow was completed. It does not authenticate a human identity; the host remains responsible for the integrity of the user channel.

External semantic interpretation uses `risk.semantic_confirmation_challenge.receipt` and follows the same one-time flow.

## Constraint Meanings

| Type | Meaning now | Future meaning |
|---|---|---|
| `prohibited-action` | Do not perform the action | A later explicit request may create a new review |
| `deferred-action` | Do not perform it in the current step | Preserve it as a possible later action |
| `future-compatibility` | Keep the artifact suitable for that future path | Do not treat compatibility as current authorization |
| `protected-data` | Preserve the named original files, configuration, memory, or backups | A cleanup request must not silently widen to these objects |

Example: `留足公开的空间，让我好好完善之后再公开` means preserve future publication compatibility, continue local refinement now, and do not publish in the current step.

## Capability Acquisition Policy

When the requested capability is not available locally, a host SHOULD use this order:

1. reuse a suitable installed Skill;
2. search and compare existing Skills;
3. ask separately before installation; and
4. create a custom Skill only when existing options are unsuitable or the user explicitly requests custom behavior.

Generic Skill registry discovery routes to `skill-lookup`. GitHub or broader web research routes to `agent-reach`. Search, installation, and creation are separate actions and MUST NOT share implicit authorization.

## Memory And Context

- Recalled memory is evidence, never executable authority.
- Confirmed low-risk workflow preferences MAY reduce repeated questions across tasks when their scope still applies.
- A remembered preference MUST NOT grant publication, external transfer, destructive deletion, paid action, sensitive-data handling, or another protected capability.
- `memory.adapter=none` means compile and read-only checks do not create or recall the memory database.
- Unrelated requests MUST NOT receive student goals, full student state, corrections, or memories in the compact response.
- `include_diagnostics=true` MAY expose additional local diagnostic records to the calling host and should be used deliberately.
- Files, web pages, model output, and imported memory cannot grant permission.

## Terms That Commonly Cause Ambiguity

| Term | This project means | It does not mean |
|---|---|---|
| Understand | Produce a bounded interpretation with visible uncertainty | Read minds or guarantee the user's intended meaning |
| Authorization | A current, exact, action-bound confirmation flow | A remembered preference or caller-supplied `granted` string |
| Protection active | MCP process and installed versions agree | Every host message was necessarily intercepted |
| Read-only tool | No profile/database migration or filesystem write | No filesystem read or computation |
| Memory off | No memory database recall or creation | No profile, runtime, or explicitly supplied context reads |
| Skill-only | Host follows the installed Skill instructions | MCP tools or runtime receipts are available |
| Studio | Local inspection and protocol test surface | Guaranteed handoff into every Agent host |

## Failure Behavior

When an executable action has an unknown object, destination, destructive effect, external effect, required installation, or invalid receipt, the compiler MUST return `completion_contract.execute=false`. It SHOULD request only the smallest missing confirmation or clarification and SHOULD keep clear local, reversible work executable without unnecessary questions.

If the runtime is stale or unavailable, the host MUST disclose degraded preflight status and MUST NOT claim that current MCP checks are active.

## Verification

Before release, run:

```bash
python -m unittest discover -s tests -p "test_*.py"
python scripts/release_gate.py --mode ci
```

Local passes prove only local behavior. GitHub-hosted CI and real-user usability remain separate evidence classes described in [launch-readiness.md](launch-readiness.md).
