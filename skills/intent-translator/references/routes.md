# Skill Routes

Choose one primary Skill by ownership. Add a supporting Skill only for a separate required stage.

| Intent | Primary route | Supporting route when needed |
|---|---|---|
| General web or platform search | `agent-reach` or `smart-search` | `defuddle` for clean article extraction; `deep-research` for rigorous synthesis |
| Find or improve prompts | `prompt-lookup` | `skill-creator` when the result should become reusable behavior |
| Normalize product terminology | `domain-modeling` | `codebase-design` when the result changes module interfaces or seams |
| Challenge a scientific or evidential claim | `scientific-critical-thinking` | `research` when primary-source verification is required |
| Challenge and sharpen a plan | `grilling` | Use only when an interview is wanted; otherwise use the semantic review path internally |
| Find or install Skills | `skill-lookup` | `agent-reach` when the registry is unavailable; `skill-creator` if no suitable Skill exists |
| Obsidian read, search, create, or update | `obsidian-cli` | `obsidian-markdown`, `obsidian-bases`, or `json-canvas` by file type |
| Cross-task context transfer | `handoff` | `obsidian-cli` to retain durable pointers or preferences |
| General exam learning | `study-assistant` | Its `study-*` subskills selected by the orchestrator |
| Exam or certification planning | `study-assistant` | Use an installed subject Skill only when its declared ownership matches the request |
| Mistake capture and review | `mistake-book` | `mistake-extract` or `mistake-restructure` for later processing |
| Code explanation or architecture | `graphify`, `codebase-design`, or `domain-modeling` | Choose by whether the question concerns relationships, module shape, or domain language |
| Hard bug diagnosis | `diagnosing-bugs` | `tdd` after the cause is established and a fix is authorized |
| Code implementation | Existing project workflow or `tdd` | `code-review` for verification |
| Documents and office files | `docx`, `pdf`, `pptx`, or `xlsx` | `doc-coauthoring` for content development |
| Image or information visualization | `imagegen`, `baoyu-infographic`, `visualize`, or `excalidraw-diagram` | Select by raster image, infographic, interactive view, or diagram |
| Career and job search | `career-ops` | `agent-reach` for live listings or company research |

## Routing Rules

1. Prefer a domain orchestrator over calling all its subskills directly.
2. Do not load two search routers for the same retrieval unless the first route fails or the sources are complementary.
3. Do not invoke a file-format Skill merely because a file is mentioned; invoke it when reading or changing that format is part of the requested outcome.
4. When a required Skill is unavailable, preserve the brief and use the nearest safe fallback. Report the missing capability only if it affects the result.
5. Search for a new Skill only after local routing fails to cover a required behavior.
6. Treat prompt services as optional optimizers. The local semantic and execution schemas remain authoritative.
