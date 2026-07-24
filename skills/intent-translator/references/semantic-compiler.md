# Semantic Compiler

Use this reference for the review path. Convert an imperfect utterance into a stable `SemanticFrame` before producing an execution prompt.

## Canonical Terms

| Term | Meaning |
|---|---|
| `Utterance` | The user's raw message in its conversational context |
| `CandidateIntent` | One plausible meaning of the utterance |
| `SemanticFrame` | The normalized, reviewed meaning selected for compilation |
| `CanonicalTerm` | A precise term replacing vague, overloaded, or inconsistent wording |
| `ConstructiveRebuttal` | A steelmanned challenge to a weak assumption, contradiction, or trade-off |
| `ExecutionEnvelope` | Machine-oriented instructions passed to the executing agent |
| `MemoryPatch` | A proposed durable update derived from explicit preference or correction |
| `SharedProtocol` | Common task language required for agents, tools, safety, and collaboration |
| `PersonalVoice` | The user's harmless dialect, humor, imagery, rhythm, values, and way of framing ideas |

Do not call the raw user message a prompt. It is an utterance. The compiler is responsible for producing the prompt.

## First-Pass Schema

Use internally and omit empty fields:

```yaml
semantic_frame:
  intended_outcome: what the user ultimately wants to improve or obtain
  current_proposal: the strongest coherent version of the proposed approach
  personal_voice: imagery, tone, values, or reasoning style worth preserving
  shared_protocol: task semantics that must become explicit for reliable execution
  canonical_terms:
    vague_term: precise_term
  statements:
    - text: normalized statement
      kind: fact|hypothesis|preference|constraint|decision
      confidence: high|medium|low
  ambiguities:
    - competing interpretations that materially matter
  constructive_rebuttal:
    weak_assumption: the most consequential unsupported assumption
    counterexample: one concrete case where it fails
    improved_formulation: a more reliable version
  recommendation: preferred interpretation and why
  clarification_gate: proceed|ask
```

## Review Procedure

1. Recover the intended outcome independently of the proposed implementation.
2. Steelman the implementation so the review attacks its best version.
3. Replace overloaded language with canonical terms. Use `domain-modeling` when terminology itself changes the design.
4. Label each important statement as fact, hypothesis, preference, constraint, or decision.
5. Find the single assumption whose failure would most damage the result.
6. Test it with a concrete counterexample or edge case.
7. Produce an improved formulation that preserves the intended outcome.
8. Check that normalization changed the task contract rather than erasing harmless personal voice.
9. Decide whether to proceed or ask one question.

## Teacher Principle

Behave like a good elementary teacher introducing a shared human language:

- Teach the common protocol needed to cooperate, reason, use tools, and respect boundaries.
- Preserve the learner's origin, metaphors, curiosity, humor, and distinctive way of noticing the world.
- Explain why a term or rule helps instead of enforcing conformity for its own sake.
- Translate unusual expression into precise operational meaning while retaining a concise trace of its human value when relevant.
- Correct harmful ambiguity, false factual claims, unsafe authorization, and broken task contracts. Do not correct harmless difference.

The success condition is mutual intelligibility with preserved individuality, not uniform speech.

## Prompt Compilation

Compile only the resolved meaning, not every intermediate thought. Convert human framing into operational language:

| Human framing | Agent-facing compilation |
|---|---|
| "帮我想明白" | Compare interpretations, identify the decisive uncertainty, and recommend one path. |
| "反驳我" | Steelman the claim, test the highest-impact assumption, then propose a stronger formulation. |
| "劝导我" | Present evidence, trade-offs, and a recommendation while preserving the user's final choice. |
| "按老样子" | Retrieve the scoped interaction preference and cite its memory source internally. |
| "整一个" | Implement and verify the previously defined artifact inside the active scope. |

Do not expose chain-of-thought. Output only conclusions, concise rationale, assumptions that affect action, and the compiled prompt when requested.

## Failure Modes

- **Literal compilation**: Treating the first wording as a complete specification.
- **Contrarian performance**: Producing objections merely because rebuttal was requested.
- **Terminology drift**: Using several words for the same concept or one word for several concepts.
- **Hidden authorization**: Turning conceptual agreement into permission to publish, pay, send data, or make irreversible changes.
- **Memory overreach**: Converting one observation or personality label into a permanent rule.
- **Prompt inflation**: Expanding a simple task into a long envelope that adds no execution value.
- **Personality flattening**: Producing technically normalized prompts that discard the user's values, playfulness, or distinctive reasoning style.
