# IntentBench v2

IntentBench v2 expands the public development conformance set from 32 to 100 synthetic cases. It keeps every frozen v1 case unchanged and adds role-diverse English, Chinese, and mixed-language requests, third-party document Skills, ambiguous local actions, cross-context continuations, and broader safety-critical effects.

## Coverage

- 100 public synthetic cases: 56 English, 25 Chinese, and 19 mixed-language.
- At least 10 user roles, including developers, product managers, lawyers, recruiters, researchers, designers, analysts, teachers, operators, and security engineers.
- 29 safety-critical cases.
- 12 cases involving third-party or registry-discovered document capabilities.
- Exact scoring across the same 12 typed routing and control fields as v1.

The first compiler run scored 87.83% field accuracy with zero dangerous misses. It exposed missing multilingual action vocabulary, weak ambiguous-object abstention, and third-party Skill routing gaps. Those general mechanisms were repaired before the candidate set was frozen. The repaired compiler scores 100% on this public development set with zero dangerous misses.

This is not independent evidence. The cases and gold labels were visible during development, and the failures were used to improve the implementation.

## Run

```bash
intent-translator-bench \
  --benchmark intentbench-v2 \
  --system compiler \
  --fail-on-dangerous-miss \
  --minimum-field-accuracy 1.0
```

Rebuild the checked-in case file from the reviewed scenario families:

```bash
python scripts/build_intentbench_v2.py
```

## Private Challenge

Keep evaluator-held cases outside the repository and create a blinded input bundle:

```bash
intent-translator-challenge \
  --cases /private/path/challenge.jsonl \
  --output-dir work/private-challenge \
  --challenge-id evaluator-2026-01 \
  --sampling-rule "First unseen request from each consenting participant" \
  --independent-evaluator
```

The public manifest contains hashes and aggregate slice counts, not utterances or gold labels. Independence, consent, and sampling remain external attestations and cannot be created by this command.

## Claim Boundary

- v2 is a public development set, not a hidden leaderboard.
- A 100% score means declared conformance on these exact cases.
- Unfamiliar users, dialects, hosts, and Skills still require evaluator-held and real-user evidence.
- Any material change to cases or scoring creates a later benchmark version.
