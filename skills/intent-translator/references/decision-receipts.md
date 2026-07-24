# Decision Receipts

Explain outcomes with observable evidence, not hidden reasoning.

Use a receipt when the user asks what the agent understood, which memory affected the result, why a Skill was selected, or why confirmation is required. A receipt may also accompany a consequential preflight when it prevents ambiguity.

Include only:

- resolved meaning;
- mode;
- referenced memory and correction IDs with short summaries;
- selected Skill;
- routing evidence such as an explicit user request, phrase mapping, or installed Skill match;
- whether confirmation is required and the bounded reason.

Do not include scratchpads, discarded hypotheses, hidden model reasoning, chain-of-thought, private background unrelated to execution, or invented confidence explanations.

Generate a deterministic receipt:

```text
python scripts/decision_receipt.py < execution-envelope.json
```

Prefer the one-line `summary` for routine interaction. Return the structured fields only when the user asks for inspection, debugging, or evaluation.
