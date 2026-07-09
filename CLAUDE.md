# CLAUDE.md

Guidance for Claude Code when working **on this repository** — i.e. developing the Cerberus skill itself, not using it.

## What this repo is

This repo contains a single Claude Code skill, **Cerberus**, which runs coding tasks through a three-phase `plan → implement → review` pipeline of subagents and tracks token cost in a git-ignored worklog. The authoritative description of the skill's behavior is `cerberus/SKILL.md` and its `cerberus/references/*.md` files — read those before changing anything, and keep them internally consistent.

## Structure

```
cerberus/
├── SKILL.md                  # entry point loaded by Claude Code; keep it concise, push detail to references/
└── references/
    ├── workflow.md           # the plan → implement → review pipeline + model fallback ladder
    ├── cost-tracking.md      # worklog layout, pricing cache, token-counting recipe, weekly rollup
    └── token-tips.md         # tactics for reducing token usage
README.md                     # human-facing overview
CLAUDE.md                     # this file
LICENSE
```

## Naming

The skill is **Cerberus** (the three-headed dog) — three heads for the three phases. Spell it **Cerberus** / `cerberus` everywhere. An earlier draft used the misspelling "Cerebrus" / `cerebrus`; if you find that spelling anywhere, it's a bug — fix it. The skill's directory name and the `name:` field in `SKILL.md` frontmatter must match exactly (`cerberus`).

> Note: the enclosing project folder may still be named `cerebrus-skill` and the skill folder `cerebrus/` pending a manual rename to `cerberus`. The *content* should already say `cerberus`; the folder rename is a separate step.

## Conventions when editing the skill

- **SKILL.md stays lean.** It's loaded into context on every trigger, so keep the entry point scannable and move procedures, schemas, and recipes into `references/`. Reference files are read on demand.
- **The frontmatter `description` is the trigger.** It's how Claude Code decides to invoke the skill. When behavior changes, update the description so the trigger conditions still match reality.
- **Keep the three references consistent with SKILL.md and each other.** The model tiers (Fable / Sonnet / Opus), the `worklog/` layout, the weekly-file naming (`YYYY-Www.md`), and the "review tier ≥ implementation tier" invariant appear in more than one file — change them everywhere at once.
- **Don't hardcode model prices.** Prices live only in the runtime `worklog/model-pricing.json` cache (fetched from the pricing page), never baked into prose. Illustrative numbers in the docs must stay clearly labeled as examples.
- **Preserve the core invariants** when refactoring: subagents do the work (never the orchestrator); verification must actually execute tests (compiling is not verifying); the reviewer re-verifies independently; every dispatch — including bails and bounces — gets a worklog row; the worklog never enters source control.

## Evaluating

This skill is intended to be evaluated with a skills-creator/skills-evaluation tool. When asked to improve it, prefer changes that keep `SKILL.md` short and the trigger `description` accurate, and that maintain consistency across the reference files.
