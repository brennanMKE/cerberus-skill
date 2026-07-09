---
name: cerberus
description: Run any coding task through a three-headed plan → implement → review pipeline of fresh subagents — planning on the top model (Fable), implementation on a mid model (Sonnet), review on a smarter model (Opus) — and keep a git-ignored worklog of token usage and cost that rolls up per week or month against the user's Claude Code plan. Use this skill whenever the user wants a task done thoroughly with a plan-then-build-then-verify structure, asks to "run this through Cerberus", wants subagents to handle plan/implement/review, wants to drive work from a planning doc like PRD.md, asks what's in flight or what they've finished lately, or asks what their work has cost or how to spend fewer tokens. Cerberus creates NO per-task ticket files — it works the task in-session, keeps a git-ignored cost worklog, mirrors progress to a transient git-ignored CERBERUS.md status dashboard, and can read (and, when asked, tick off tasks in) an optional user-named planning doc such as PRD.md.
---

# Cerberus — a three-headed plan → implement → review pipeline

Cerberus guarded the underworld with three heads; Cerberus guards code quality with three **subagents**. Every non-trivial task runs through the same pipeline, each phase in a **fresh subagent** dispatched by the orchestrator (this session):

1. **Planning** — the strongest available reasoning model (currently Fable) reasons out the approach.
2. **Implementation** — a capable, cost-efficient model (currently Sonnet) builds and verifies it.
3. **Review** — a model at least as strong as the implementer (currently Opus) independently re-verifies.

The orchestrator picks the task, dispatches each head, records what it cost, and reports back. It never does the plan/build/review work in its own context — isolating each phase in a subagent is what keeps the orchestrator small enough to drive a long series of tasks.

**Cerberus is not a ticket tracker.** It does **not** create or manage per-task ticket files. The task is described in the session (or drawn from the user's own planning doc) and worked in the session. What it writes to disk is deliberately small: a git-ignored `worklog/` folder recording token usage and cost, and a git-ignored `CERBERUS.md` status dashboard at the project root — both *derived* from the pipeline's own activity, not a parallel bug database. If the user keeps a planning doc (see below), Cerberus reads it and can tick off completed tasks in it, but it never invents ticket files of its own.

## When to use this skill

Trigger Cerberus whenever the user:

- asks to run a task through "Cerberus", "the pipeline", or "plan → implement → review"
- wants a coding task done thoroughly, with a plan written before code and an independent review after
- wants work delegated to subagents by phase, keeping the main session as a coordinator
- asks "what has this week cost?", "how much have I spent?", or "does this fit my plan?"
- asks how to use fewer tokens / reduce cost

If the task is a one-line trivial edit, running the full three-head pipeline is overkill — just do it inline and say so. Cerberus earns its overhead on tasks with real design or verification surface.

## The three heads

| Phase | Model (default) | The subagent does | Writes to disk |
|---|---|---|---|
| **1. Planning** | **Fable** (top available) | Reads project conventions + the task, writes an implementation plan. No code. | nothing (plan returns to orchestrator) |
| **2. Implementation** | **Sonnet** (good-enough) | Follows the plan, makes the change, builds + runs verification, commits code. | code + commit |
| **3. Review** | **Opus** (smarter than impl) | Independently re-reads the diff and re-runs verification, then approves or bounces. | approval/bounce summary |

After each subagent returns, the orchestrator records **one worklog row** by running `scripts/record_usage.py` — it reads the subagent's transcript, sums and prices the usage, and appends a record to `worklog/usage.jsonl`. See `references/cost-tracking.md`.

The full dispatch procedure, each subagent's checklist, and the verification standard live in **`references/workflow.md`** — read it before dispatching any phase.

## Bundled files

Read these rather than reconstructing from memory:

- **`references/workflow.md`** — the canonical spec for the plan → implement → review pipeline: how the orchestrator dispatches each head, what each subagent reads and does, the mandatory verification standard, the model-selection/fallback rules, and how a bounce loops back. Read before dispatching.
- **`references/cost-tracking.md`** — the `worklog/` layout, the `worklog/model-pricing.json` daily price cache, and how the two scripts record and roll up usage. Read whenever you dispatch a subagent or the user asks about cost.
- **`references/token-tips.md`** — concrete tactics for spending fewer tokens across the pipeline (scoping context, cache-friendly ordering, when to skip a head, right-sizing models). Read when the user asks to reduce cost or when a rollup looks high.
- **`scripts/record_usage.py`** — records one dispatch to `worklog/usage.jsonl`: finds the subagent's transcript, dedupes and sums usage, prices it from the cache, and regenerates `CERBERUS.md`. Run after every subagent returns.
- **`scripts/report.py`** — cost rollups (`--this-week`/`--this-month`/`--week`/`--month`/`--range`) broken down by phase, model, and task, plus the task-level views `--status` (what's in flight) and `--tasks` (recent-task log). Run when the user asks about cost or status.
- **`scripts/worklog.py`** — shared helper the two scripts import (loads the worklog, derives task outcomes, renders `CERBERUS.md`). Not run directly.

## First, orient yourself

Before dispatching, take a few cheap seconds to set up the worklog and learn the project's conventions.

1. **Check for a git repo.** `git rev-parse --is-inside-work-tree 2>/dev/null`. This decides whether implementation commits code (repo) or only edits the working tree (no repo).
2. **Ensure the worklog and status file are ignored.** If there's no `worklog/` folder, create it and add both `worklog/` and `CERBERUS.md` to `.gitignore` (create `.gitignore` if absent). Both are local, transient bookkeeping — they must **never** enter source control. See "Worklog setup" below.
3. **Read `CLAUDE.md`** at the repo root if it exists — code conventions, restricted areas, the build/verify command. Treat its instructions as binding and pass them to every subagent.
4. **Look for a planning doc.** If the user keeps one (e.g. `PRD.md`, or whatever they name it), that's where the task list lives — see "Working from a planning doc" below. Absent one, the task comes straight from the user's request.
5. **Note the verification command.** Every phase-2 and phase-3 subagent must run it. If the project doesn't define one, ask the user how the change should be verified before dispatching implementation — a pipeline that can't verify can't review.

## Worklog setup

The worklog is a git-ignored folder in the user's project holding cost bookkeeping only:

```
worklog/                 # git-ignored bookkeeping
├── model-pricing.json   # daily-refreshed per-MTok price cache (see references/cost-tracking.md)
└── usage.jsonl          # one JSON record per subagent dispatch — the source of truth
CERBERUS.md              # git-ignored status dashboard at the project root, auto-regenerated
```

`usage.jsonl` is machine-readable so `scripts/report.py` can roll it up exactly; human-readable weekly/monthly reports and the `CERBERUS.md` dashboard are generated on demand from it, not maintained by hand. `CERBERUS.md` is a transient, git-ignored read-out (in-flight task + recent tasks), not a per-task ticket — Cerberus still writes no tickets.

Set it up once, the first time Cerberus runs in a project:

```bash
mkdir -p worklog
# ignore the worklog and the transient status dashboard (both local-only)
git check-ignore -q worklog/   2>/dev/null || printf '\n# Cerberus cost bookkeeping — local only\nworklog/\n'  >> .gitignore
git check-ignore -q CERBERUS.md 2>/dev/null || printf '# Cerberus status dashboard — transient\nCERBERUS.md\n' >> .gitignore
```

Confirm `worklog/` and `CERBERUS.md` show as ignored (`git check-ignore -q` exits 0) before writing. If the user later wants either shared, that's their call — but the default is local-only, so a machine's cost history and transient status never leak into the repo.

## Working from a planning doc (optional)

Cerberus stays flexible about where the task comes from. A user often keeps a **planning document** — commonly a `PRD.md`, but they can name it anything (`PLAN.md`, `ROADMAP.md`, …) — structured as **phases, each containing tasks**. When one exists, treat it as the backlog:

- **Read it, don't replace it.** The planning doc is the user's own, may live in source control, and is authored by them. Cerberus consumes it; it is *not* a Cerberus-generated ticket file. Ask which doc to use if it's ambiguous, or take the name the user gives.
- **Pick the task.** Run the specific phase/task the user names ("do phase 2, task 3"), or the next unchecked task if they say "take the next one." Feed that task through the plan → implement → review pipeline like any other. The head-1 planner should read the planning doc (alongside `CLAUDE.md`) for surrounding context.
- **Label the worklog to match**, e.g. `--task "PRD P2.T3: export CSV"`, so cost rollups and the `CERBERUS.md` task log group by planning-doc item.
- **Tick it off when review approves** — if the doc uses checkboxes, mark that task done (and note the commit) after head 3 approves, so the planning doc reflects reality. This is the one place Cerberus edits a user doc; keep the edit minimal and only after verification passes. Don't rewrite or restructure the doc.

This gives the user a durable, human-owned view of *what to do* (the planning doc) alongside Cerberus's transient view of *what's happening* (`CERBERUS.md`) — without Cerberus ever becoming a ticket tracker.

## Running a task through the pipeline

At a high level (full detail in `references/workflow.md`):

1. **Refresh pricing if stale.** Read `worklog/model-pricing.json`; if missing or its `fetched` date isn't today, fetch current prices once and rewrite it. Do this before the first dispatch of the session.
2. **Head 1 — Plan.** Dispatch a fresh planning subagent (top model) to read conventions + the task and return an implementation plan. The top model runs *only* in a subagent, never in this orchestrator context — the point is to spend its tokens against a fresh, minimal context. Record its worklog row (`scripts/record_usage.py --task "…" --phase plan`).
3. **Head 2 — Implement.** Dispatch a fresh implementation subagent with the plan. It makes the change, **builds and runs the verification command, confirming tests actually executed and passed**, then commits the code (if in a repo). Record its worklog row (`--phase implement`), passing `--summary "<what landed>"` and `--commit <hash>` so the task log and `CERBERUS.md` read well.
4. **Head 3 — Review.** Dispatch a fresh review subagent (≥ implementation tier) to independently re-read the diff and **re-run verification itself** — it does not trust the implementer's claim. It approves, or bounces back with specific notes. Record its worklog row (`--phase review`).
5. **On a bounce**, re-dispatch head 2 with the reviewer's notes, then head 3 again. Each attempt gets its own worklog row (`--status bounce` on the rejected review, `--status bail` if implementation gave up) — a failed attempt still spent tokens.
6. **Report to the user**: what landed, the review verdict, and this task's cost. Do not tell the user the task is "done and confirmed" on your own inference — the reviewer's approval means *verified*, and it's the user who decides the work is accepted.

## Model selection and fallback

Defaults are **plan → implement → review** on a top reasoning model (Fable) → a cost-efficient model (Sonnet) → a strong reviewer (Opus). The one invariant that must never break: **the review model is at least as strong as the implementation model** — a weaker reviewer can't catch a stronger implementer's mistakes. When a tier isn't available, planning and implementation may share a model, but review stays on the strongest tier you have; never let review drop below implementation. The full fallback ladder is in `references/workflow.md`.

## Cost tracking and the rollup

Every dispatch is recorded by running `scripts/record_usage.py` (see steps above and `references/cost-tracking.md`), which appends one JSON record to `worklog/usage.jsonl`. The orchestrator measures usage from the subagent's transcript *after it returns* — a subagent can't measure its own totals.

When the user asks **"what has this week cost?"**, **"how much this month?"**, or **"does this fit my plan?"**, run `scripts/report.py` (`--this-week`, `--this-month`, `--week`, `--month`, `--range`, or `--all`). It totals the period, breaks it down by phase / model / task, and projects a weekly figure to a month. Then map it to Claude Code plan tiers, framing subscriptions as usage allowances rather than dollar caps — full procedure and tier table in `references/cost-tracking.md`.

## Status and the recent-task log

When the user asks **"what's the status?"**, **"what am I in the middle of?"**, or **"what have I finished lately?"**, run `scripts/report.py --status` (the one in-flight task) or `--tasks` (a readable log of recent tasks with their outcome — ✅ approved, ⚠️ bailed, ↻ in progress, 📋 planned — dispatch count, cost, and what landed). The same dashboard is written to `CERBERUS.md` at the project root, regenerated after every dispatch (`record_usage.py` does this automatically; `report.py --write-status` regenerates it on demand). Outcomes are *derived* from each task's worklog rows (phase + `status`), so this is a read-out over the worklog, not a separate tracker. Details in `references/cost-tracking.md`.

## Reducing token usage

Users care about cost, so Cerberus should actively help lower it. When asked (or when a rollup looks high), pull specific tactics from **`references/token-tips.md`**. The headline moves:

- **Skip heads that don't earn their cost.** A trivial change doesn't need a Fable plan; a mechanical rename doesn't need an Opus review. Right-size the pipeline to the task.
- **Scope each subagent's context tightly.** Point subagents at the specific files that matter instead of letting them explore the whole tree — exploration is pure input tokens.
- **Exploit the prompt cache.** Keep the stable preamble (conventions, plan) at the front of each subagent's context so repeated reads hit cache at ~1/10th the input rate.
- **Right-size models.** Don't run Opus where Sonnet suffices; don't plan on Fable for a one-file change.
- **Batch verification.** Run the verify command once per phase, not after every micro-edit.

## Anti-patterns to avoid

- **Don't do the work in the orchestrator.** The whole point is fresh, isolated subagents per phase. If you find yourself planning or coding in this session, stop and dispatch.
- **Don't commit the worklog.** It's local cost bookkeeping. Confirm `worklog/` is git-ignored before writing rows.
- **Don't confuse "compiles" with "verified".** The verification command must actually *run* tests and you must read the output. A green build with zero tests run is a failure, not a pass — in both head 2 and head 3.
- **Don't let review be weaker than implementation.** The reviewer exists to catch the implementer; a weaker model can't. Keep review at the strongest available tier.
- **Don't skip the worklog row on a bounce or bail.** A failed attempt still cost real tokens; record it with `--status bounce`/`--status bail` or the user's cost picture is wrong.
- **Don't let a subagent self-report its token usage, and don't hand-sum or hand-price transcripts.** A subagent can't see its own totals; run `scripts/record_usage.py` after it returns, which dedupes by request and prices from the cache.
- **Don't hardcode prices.** Prices live only in the dated `worklog/model-pricing.json` cache, refreshed from the pricing page. Prose numbers go stale.
- **Don't create per-task markdown.** Cerberus tracks no tickets — the task lives in the session and only the worklog is written to disk.
