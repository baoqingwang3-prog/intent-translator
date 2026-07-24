# Interaction Inference

Use the user's local profile and explicit corrections as the primary source for phrase meaning. The examples below are generic conversational defaults, not facts about every speaker.

## Resolution Order

1. Current explicit instruction.
2. Latest unfinished action and its clearly proposed next step.
3. Scoped phrase mapping from the local profile or confirmed memory.
4. Repeated observed pattern with no contradiction.
5. Generic conversational convention.
6. Ask one focused question when materially different interpretations remain.

## Common Defaults

| Expression pattern | Default interpretation |
|---|---|
| Continue wording such as `continue`, `go on`, or `继续` | Resume the current unfinished flow at its next action. |
| Brief approval such as `yes`, `okay`, or `可以` | Approve only the immediately preceding clearly proposed action. |
| Implementation wording such as `build one`, `hook it up`, or `整一个` | Implement and verify inside the active scope. |
| Unblocked wording such as `done`, `logged in`, or `好了` | Treat the stated prior blocker as resolved and resume. |
| Proposal wording such as `I have an idea` or `我认为可行` | Treat it as a hypothesis to review rather than a confirmed design fact. |
| A short added condition | Merge it into unfinished work unless it clearly replaces the goal. |

Do not infer a new recipient, destination, account, payment, publication, destructive action, or sensitive-data transfer from shorthand alone.

## Confidence

- `high`: A current instruction, explicit scoped mapping, or unambiguous previous action resolves the phrase.
- `medium`: One interpretation clearly fits the active task. Proceed and state the assumption only when it affects the result.
- `low`: Multiple interpretations create materially different outcomes. Ask one concise question.

## Learning A User's Language

- Store explicit meanings such as "when I say X, I mean Y" as `confirmed` phrase mappings.
- Store repeated patterns as `observed` only after multiple consistent examples.
- Keep project-specific meanings in project scope rather than global scope.
- Preserve the original expression alongside its operational interpretation.
- Allow users to inspect, correct, export, and delete their mappings.
- Do not infer personality, diagnosis, identity, or fixed cognitive routes from wording alone.
