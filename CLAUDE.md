# CLAUDE.md

Guidance for Claude Code when working **on this repository** — i.e. developing the Cerberus skill itself, not using it.

## What this repo is

This repo contains a single Claude Code skill, **Cerberus**, which runs coding tasks through a three-phase `plan → implement → review` pipeline of subagents and tracks token cost in a git-ignored worklog. The authoritative description of the skill's behavior is `cerberus/SKILL.md` and its `cerberus/references/*.md` files — read those before changing anything, and keep them internally consistent.

## Structure

```
cerberus/
├── SKILL.md                  # entry point loaded by Claude Code; keep it concise, push detail to references/
├── references/
│   ├── workflow.md           # the plan → implement → review pipeline + model fallback ladder
│   ├── cost-tracking.md      # worklog layout, pricing cache, how the scripts record & roll up
│   └── token-tips.md         # tactics for reducing token usage
└── scripts/
    ├── record_usage.py       # append one dispatch to worklog/usage.jsonl (dedupes + prices); regenerates CERBERUS.md
    ├── report.py             # cost rollups + --status / --tasks task-level views
    └── worklog.py            # shared loader + task-status derivation (imported by both scripts)
README.md                     # human-facing overview
install.sh                    # symlink the skill into detected AI tools
CLAUDE.md                     # this file
LICENSE
```

## Naming

The skill is **Cerberus** (the three-headed dog) — three heads for the three phases. Spell it **Cerberus** / `cerberus` everywhere. An earlier draft used the misspelling "Cerebrus" / `cerebrus`; if you find that spelling anywhere, it's a bug — fix it. The skill's directory name and the `name:` field in `SKILL.md` frontmatter must match exactly (`cerberus`).

> Note: the enclosing project folder may still be named `cerebrus-skill` and the skill folder `cerebrus/` pending a manual rename to `cerberus`. The *content* should already say `cerberus`; the folder rename is a separate step.

## Conventions when editing the skill

- **SKILL.md stays lean.** It's loaded into context on every trigger, so keep the entry point scannable and move procedures, schemas, and recipes into `references/`. Reference files are read on demand.
- **The frontmatter `description` is the trigger.** It's how Claude Code decides to invoke the skill. When behavior changes, update the description so the trigger conditions still match reality.
- **Keep the references, scripts, and SKILL.md consistent with each other.** The model tiers (currently Fable / Sonnet / Opus), the `worklog/` layout (`usage.jsonl` + `model-pricing.json`), the record schema, and the "review tier ≥ implementation tier" invariant appear in more than one file — change them everywhere at once. Frame models by role with current names as examples, so a new model release doesn't date the prose.
- **Cost and status mechanics live in the scripts, not in prose.** Token counting, `requestId` dedupe, the cost formula, the rollup, and task-outcome inference are implemented in `scripts/` (`record_usage.py`, `report.py`, shared `worklog.py`). Docs describe *how to run* them and the record schema; don't reintroduce a hand-run token-counting recipe or ask the orchestrator to do cost arithmetic. If you change the record schema, update the scripts and `cost-tracking.md` together.
- **`CERBERUS.md` is a derived read-model, not a tracker.** It's regenerated from `usage.jsonl` by `record_usage.py`, written to the project root, git-ignored (add it to `.gitignore` in worklog setup), and holds no data that isn't inferable from the worklog. This does not violate "Cerberus writes no tickets" — there are still no per-task source files; task status is computed from the phase + `status` of each task's rows. Keep it that way.
- **A planning doc (e.g. `PRD.md`) is user-owned input, not a Cerberus artifact.** Cerberus can *read* a user-named planning doc to source tasks and *tick off* a task once review approves, but it never creates or restructures one. Don't blur this line: `CERBERUS.md` = generated/transient/git-ignored status; the planning doc = human-authored backlog that may live in source control. The doc name is the user's choice (default `PRD.md`).
- **Don't hardcode model prices.** Prices live only in the runtime `worklog/model-pricing.json` cache (fetched from the pricing page), read by the scripts, never baked into prose or code. Illustrative numbers in the docs must stay clearly labeled as examples.
- **Preserve the core invariants** when refactoring: subagents do the work (never the orchestrator); verification must actually execute tests (compiling is not verifying); the reviewer re-verifies independently; every dispatch — including bails and bounces — gets a worklog row (`record_usage.py`, with `--status`); the worklog never enters source control.

## Evaluating

This skill is intended to be evaluated with a skills-creator/skills-evaluation tool. When asked to improve it, prefer changes that keep `SKILL.md` short and the trigger `description` accurate, and that maintain consistency across the reference files.
