# Python SDK

The Python SDK is the smallest supported embedding surface. It does not execute tools, publish data, or call a model unless an optional semantic adapter is configured and allowed.

```python
from intent_translator_mcp import IntentTranslator

sdk = IntentTranslator()
result = sdk.compile(
    "Continue the local tests, do not upload to GitHub",
    pending_action="Run the remaining local regression tests",
    semantic_mode="off",
)

print(result.contract.operation)
print(result.contract.prohibitions)
print(result.selected_skill)
print(result.tool_decision)

if result.can_execute:
    # The host may now invoke its own tool layer.
    pass
```

## Public surface

| Method | Purpose | Writes data | Calls a model by default |
|---|---|---:|---:|
| `compile()` | Produce a typed intent contract and tool-gateway decision | No | No |
| `check()` | Review explicit risk and authorization properties | No | No |
| `resolve()` | Bind a selection to the previous Interpretation Gate | No | No |
| `receipt()` | Extract an action-bound challenge already issued by the compiler | No | No |

`compile()` defaults to `include_prompt=False`. A host that consumes the typed contract does not need a second generated prompt.
It also defaults to `include_diagnostics=False`, so raw memory and correction records are not included in the public result.

## Resolve an ambiguity

```python
first = sdk.compile("Connect Obsidian too", scope="project-a", semantic_mode="off")

if first.interpretation_gate:
    resolved = sdk.resolve(first, "1", semantic_mode="off")
```

The selection is accepted only with the exact gate ID and options from the previous result. An isolated number without that context is not executable.

## Confirm a protected action

```python
action = "Publish dist/release.whl to the GitHub Release"
first = sdk.compile(action, semantic_mode="off")
challenge = sdk.receipt(first)

# Obtain explicit human approval in the host UI before resubmitting this receipt.
approved = sdk.compile(
    "Confirm",
    pending_action=action,
    semantic_mode="off",
    confirmation_receipt=challenge["receipt"],
)
```

The SDK cannot mint broader permission through `receipt()`. It only returns the short-lived, action-bound challenge created by the compiler. Changing the operation, destination, scope, or action invalidates it.

## Result object

`CompilationResult` provides:

- `contract`: validated `TypedIntentContract`
- `selected_skill`
- `tool_decision`: `allow`, `human_review`, or `deny`
- `can_execute`
- `requires_clarification`
- `requires_confirmation`
- `model_used`
- `interpretation_gate`
- `to_dict()`: a defensive copy of the complete envelope
