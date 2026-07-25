# Stranger-User Alpha Trial

Run a small consented trial with 3-5 people who have not seen the implementation. Do not teach prompt syntax or explain internal component names before the tasks.

## Safety

- Start with a temporary home directory or a test account.
- Ask participants to use invented tasks first, not private documents or real credentials.
- Collect metrics and redacted observations only. Do not retain raw wording without explicit consent.
- Stop immediately if an action attempts publication, payment, destructive deletion, or private-data transfer without concrete confirmation.

## Tasks

1. Install from the repository instructions without maintainer intervention.
2. Confirm the first message says the system has no personal memory.
3. Complete or skip the three onboarding choices.
4. Describe a small reusable helper in ordinary language, choose an interpretation, create it, and invoke it once.
5. Correct one misunderstood phrase in natural language and verify the corrected meaning applies immediately.
6. Repeat the phrase and verify profile promotion is suggested only at the configured threshold.
7. Uninstall and verify local data is preserved; use explicit purge only in the disposable test environment.

## Record

- Time and steps to first successful Skill invocation.
- Number of invalid or unnecessary questions.
- Internal technical terms the participant had to understand. Target: 0.
- Whether the first semantic correction took effect.
- Cross-user contamination. Target: 0.
- Install, reinstall, rollback, uninstall, and purge outcome.
- Confusing wording, failed routes, and unsupported host behavior.

The automated protocol-level rehearsal is:

```bash
python scripts/stranger_smoke.py
```

It uses five isolated synthetic users with conflicting language rules, creates and invokes five minimal Skills, verifies Agent Reach and Obsidian routing, and checks publication/deletion confirmation behavior. The JSON report includes first-success steps and timing, unnecessary questions, wrong routes, dangerous confirmation misses, correction recurrence, technical terms, and cross-user contamination.

The local Studio is separately browser-tested on desktop and 390x844 mobile, but automation still does not replace real-user observation. A passing rehearsal means the build is a local Alpha candidate. Real-user evidence remains incomplete until 3-5 consenting strangers finish the protocol.
