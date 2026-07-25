# Optional Semantic Layer

The semantic layer helps with unfamiliar metaphors, ellipsis, indirect wording, and domain language. It is optional because local-first deterministic safety must still work without a model or network connection.

## Trust Split

- The model proposes `normalized_goal`, `interpretation`, `mode`, assumptions, alternatives, confidence, a Skill candidate, and risk hints.
- Deterministic code owns authorization, external-transfer checks, irreversible-action checks, memory policy, and the final execute/confirm decision.
- Model output can raise risk but cannot erase deterministic risk.
- A model-only action inference enters review before execution. A semantic adapter cannot replace an already executable objective; a different goal is returned only as an alternative.
- The normalized model goal is scanned again by deterministic risk rules.
- The adapter returns concise structured interpretation, not chain-of-thought or hidden reasoning.

## Configure A Command Adapter

Set `INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON` to a JSON array containing the executable and arguments. The command receives one UTF-8 JSON object on stdin and must return one UTF-8 JSON object on stdout. It is launched directly without a shell.

```bash
export INTENT_TRANSLATOR_SEMANTIC_COMMAND_JSON='["my-model-wrapper", "--json"]'
export INTENT_TRANSLATOR_SEMANTIC_NAME='local-model'
export INTENT_TRANSLATOR_SEMANTIC_TIMEOUT='20'
```

For an adapter that sends data off-device:

```bash
export INTENT_TRANSLATOR_SEMANTIC_EXTERNAL='1'
```

External adapters are not called from caller allow flags alone. The first compile returns `risk.semantic_confirmation_challenge.receipt`, bound to the exact pending input and scope. After the user explicitly confirms, the host resubmits the exact action in `pending_action`, the confirmation in `utterance`, the one-time value in `confirmation_receipt`, and the corresponding allow flag. Sensitive content binds both external and sensitive semantic grants into the receipt. Any changed input, scope, expired receipt, or replay is rejected.

## Configure A Chat-Completions Endpoint

For a local server that implements `/v1/chat/completions`:

```bash
export INTENT_TRANSLATOR_SEMANTIC_PROVIDER='chat-completions'
export INTENT_TRANSLATOR_SEMANTIC_BASE_URL='http://127.0.0.1:11434/v1'
export INTENT_TRANSLATOR_SEMANTIC_MODEL='your-local-model'
```

For a remote endpoint, set the same values to the remote HTTPS URL and provide a key only when that server requires it:

```bash
export INTENT_TRANSLATOR_SEMANTIC_API_KEY='set-this-in-your-local-secret-store'
```

Loopback hosts are treated as local. Other hosts are treated as external and require per-request egress authorization. Keys are read from the process environment and are never included in doctor output, semantic payloads, or decision receipts.

## Output Contract

```json
{
  "normalized_goal": "Publish the project publicly",
  "interpretation": "The visibility metaphor means public publication.",
  "mode": "build",
  "assumptions": [],
  "alternatives": [],
  "confidence": 0.91,
  "primary_skill": "release-manager",
  "risk_hints": ["external", "irreversible"],
  "clarification_recommended": true,
  "language": "en"
}
```

Allowed risk hints are `external`, `sensitive`, `irreversible`, and `high_stakes`. Unknown modes, risk hints, malformed JSON, timeouts, and non-zero exits are rejected. Adapter errors fall back to deterministic compilation in `auto` mode; `required` mode stops execution and requests review.

## Evaluation

`intent-translator-semantic-eval` compares no-model, helpful-model, and adversarial-model fixtures. This verifies merge and safety behavior only. It is not evidence that a real model understands unfamiliar users. Real evaluation must use held-out prompts, multiple model families, multiple languages, and consented user data.
