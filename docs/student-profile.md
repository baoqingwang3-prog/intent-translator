# Student Profile Architecture

Public profile packs teach the compiler how to adapt without shipping a student's private data.

## Public Packs

The `student-exam-prep` and `university-student` packs define reusable behavior:

- preserve the active study goal and subject;
- prefer installed study Skills when routing terms match;
- reuse registered material pointers before asking for files again;
- batch nonurgent maintenance outside focused study;
- keep optional shadow evaluation disabled until the user enables it;
- when enabled, retain at most 500 samples for 30 days;
- never store full utterances or scan an entire vault.

The packs contain no personal goal, active subject, vault location, progress, grades, deadlines, or mistake data.

## Local Overlay

`~/.intent-translator/profile.json` may add each user's goals, current subject, installed Skill preferences, Obsidian location, confirmed phrase mappings, and interaction preferences.

`~/.intent-translator/memory.db` may contain governed corrections, optional shadow aggregates, and material pointers. Study content remains in its original files. These paths are outside the repository and must stay out of commits, examples, issues, and evaluation fixtures.

## Shadow Evaluation

The host records a sample only after the user enables shadow evaluation and both the compiler proposal and host decision exist. Each event compares mode, Skill, clarification, study context switching, and material reuse. It stores a profile-salted hash and no utterance preview by default. A nonzero local preview limit is an explicit opt-in; the full utterance is never stored. Reports are maintenance artifacts, not study notifications.

## Obsidian Pointers

A pointer contains a local path, title, purpose, subject, goal, authority level, update time, and reuse count. Sync writes only the managed note configured by the user, normally `AI/intent-translator-study-index.md`. It does not crawl the vault.
