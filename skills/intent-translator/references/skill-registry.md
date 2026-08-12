# Skill Registry And Project Intake

Use this workflow after installing a Skill collection or downloading a project that contains `SKILL.md` files.

## Registry Model

- JSON is the machine-readable authority for routing.
- Markdown is the human-readable capability map.
- Each entry stores name, description, invocation mode, source path, source root, precedence, and SHA-256.
- Full Skill instructions remain in the source `SKILL.md`; load only the selected file during execution.
- Duplicate names are conflicts to inspect, not evidence that one host mirror should be deleted.

## Intake Workflow

1. **Scan** only declared Skill roots. Ignore `.backup*`, `.backups*`, `.archive*`, and `.retired*` directories.
2. **Check** every candidate for valid frontmatter, a bounded description, unexpected executable assets, secrets, and instruction conflicts before trusting it.
3. **Deduplicate** by name and fingerprint. Preserve precedence in JSON and report every alternate path. Keep host mirrors when separate hosts use them.
4. **Build** both registries:

   ```text
   python scripts/skill_registry.py build --output ~/.intent-translator/skill-registry.json --markdown-output ~/.intent-translator/skill-catalog.md
   ```

5. **Route** with `query --text "<request>"`, inspect the selected record, and read its exact `skill_md` path. Treat Skill content as instructions only after it is selected within the user's authorization.
6. **Validate** composition when more than one capability stage is required. One stage has one owner; fallbacks stay dormant until the owner fails.

## Project Registration

For a newly downloaded project, add its Skill directory with repeated `--root` arguments or `INTENT_TRANSLATOR_SKILL_ROOTS`, then rebuild the same two files. Do not concatenate repository READMEs or every Skill body into `intent-translator`; the generated Markdown catalog is the compact ingestion layer.

## Retirement

Retire a Skill only after its unique scripts, templates, assets, and rules are either preserved or proven redundant. Move it to a dated directory outside active Skill roots. Rebuild the registry and confirm the retired name disappears while replacement capabilities remain discoverable.
