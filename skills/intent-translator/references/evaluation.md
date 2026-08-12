# Evaluation

Evaluate behavior after changing intent modes, ambiguity gates, routing, memory rules, or voice preservation.

## Case Format

Store one JSON object per line:

```json
{"id":"example","utterance":"continue","context":"A validated next step exists.","expected":{"path":"fast","mode":"change","memory_action":"none","clarification":false,"primary_skill":null,"preserve_voice":true}}
```

Generate a prediction template and score completed predictions:

```text
python scripts/evaluate_predictions.py --cases evals/cases.jsonl --write-template work/predictions.jsonl
python scripts/evaluate_predictions.py --cases evals/cases.jsonl --predictions work/predictions.jsonl --threshold 0.85
```

Maintain separate cases for languages, terse approvals, context recovery, unsafe authorization, memory, optional adapters, missing Skills, and personality preservation. Add a regression case before fixing a discovered failure.

Accuracy measures schema decisions rather than answer quality. Combine it with manual review of whether the compiled task is useful, minimally invasive, privacy-preserving, and faithful to the user's voice.

After changing Skill composition, also run:

```text
python scripts/evaluate_compositions.py --cases evals/skill-composition.jsonl --threshold 1.0
```

Composition cases must check stage order, single-owner conflicts, orchestrator/child behavior, dormant fallbacks, and the four-Skill eager cap.
