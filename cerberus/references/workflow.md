# The Cerberus pipeline — plan → implement → review

The canonical way a task moves from described to verified. It runs as a **three-phase pipeline**, and every phase runs in a **fresh subagent** dispatched by the orchestrator (the main session). The orchestrator never plans, codes, or reviews in its own context — it picks the task, dispatches each head, and records what each cost. Keeping the work in subagents is what keeps the orchestrator small enough to coordinate task after task without its context ballooning.

| Phase | Model (default) | Subagent does | Writes |
|---|---|---|---|
| **1. Planning** | **Fable** (top available) | Reads conventions + the task, returns an implementation plan. No code. | plan (returned to orchestrator) |
| **2. Implementation** | **Sonnet** | Follows the plan, makes the change, builds + verifies, commits code. | code + commit |
| **3. Review** | **Opus** (≥ implementation tier) | Independently re-reads the diff and re-runs verification, then approves or bounces. | verdict summary |

## Why fresh subagents, and why these models

- **Fresh context per phase is a feature.** Each subagent loads `CLAUDE.md` and the task cleanly at the start, so the moment the user changes conventions the *next* subagent picks it up — no stale context carried between phases.
- **The orchestrator stays small.** Plan, implementation, and review transcripts each grow large. Isolating them means the orchestrator only ever sees a one-line return per phase, so it can run a long series of tasks without its own context growing.
- **Model tiers match the work.** Planning is the highest-leverage, most reasoning-heavy step, so it gets the top model (**Fable**). Implementation is well-scoped once a plan exists, so **Sonnet** handles it. Review is an adversarial correctness check where a **stronger** model (**Opus**) earns its cost.
- **The top model runs *only* in a subagent.** Never invoke Fable in the orchestrator's own context — the whole point is to spend that model's tokens against a fresh, minimal context, not to inflate the coordinating session.

## Model selection and the fallback ladder

Defaults: **Fable** (plan) → **Sonnet** (implement) → **Opus** (review). The one invariant that must never break:

> **Review tier ≥ implementation tier.** A reviewer weaker than the implementer cannot catch the implementer's mistakes. This is the reason the pipeline has a third head at all.

Fallback, in order of preference:

1. **All three available** → Fable plans, Sonnet implements, Opus reviews.
2. **No Fable** → plan on the strongest available model (e.g. Opus), implement on Sonnet, review on the strongest available model. Planning and review may share the top tier.
3. **Only two tiers available** → plan and implement may share the lower tier, but review stays on the higher tier.
4. **Only one model available** → run the phases sequentially on that model in fresh subagents anyway; the fresh-context isolation and the independent re-verification still add value, even without tier separation. Note in the report that tier separation wasn't possible.

`scripts/record_usage.py` reads the *actual* model id from the transcript, so a fallback tier is recorded truthfully — you never have to pass the intended default.

## Deciding which heads to run

The full three-head pipeline is the default for tasks with real design or verification surface. Trim it when a head can't earn its cost — and say you did:

- **Trivial/mechanical change** (one-line fix, rename, obvious typo): skip planning; implement and review, or just implement inline.
- **No verifiable runtime surface** (docs, comments): planning and review add little; a single implementation pass may suffice.
- **Exploratory / "figure out how X works"**: this is planning-only — dispatch head 1 and return its findings; there may be nothing to implement yet.

When you trim, note it to the user ("skipped planning — one-line change") so the reduced pipeline is a visible choice, not a silent gap. See `token-tips.md`.

## Phase 1 — Planning (Fable)

1. **Orchestrator dispatches a fresh Fable subagent** with the task description and instructions to produce a plan, not to write code.
2. **The planner orients**, reading in order:
   - `CLAUDE.md` at the repo root, if present — binding project-wide conventions.
   - The planning doc (e.g. `PRD.md`), if the task was drawn from one — the relevant phase/task and enough surrounding context to plan it well. The planner reads it but does not edit it.
   - The specific files the task touches — enough to ground the plan in what actually exists. The planner reads code but does **not** modify it.
3. **The planner returns a plan**: the suspected root cause or the shape of the change, the files/functions likely involved, the approach in a few concrete steps, and **how the change should be verified**. The plan is guidance for the implementer, not a contract — the implementer may deviate if reality differs, and should say why.
4. **Nothing is written to disk** in this phase. The plan comes back to the orchestrator, which passes it into the head-2 dispatch — Cerberus keeps it in-session rather than persisting it to markdown.
5. **Orchestrator records the planner's usage**: `scripts/record_usage.py --task "<label>" --phase plan`. See `cost-tracking.md`.

If the planner can't produce a useful plan (task too vague, needs user input), it returns what it can plus an explicit note about what's unclear. The orchestrator relays the question to the user rather than dispatching implementation on a guess.

## Phase 2 — Implementation (Sonnet)

### Orchestrator: dispatch

1. **Refresh the pricing cache if stale** (once per session, before the first dispatch). See `cost-tracking.md`.
2. **Spawn a fresh Sonnet subagent** with the task and the plan from phase 1, plus instructions to follow the checklist below.
3. **When it returns, record its usage**: `scripts/record_usage.py --task "<label>" --phase implement --summary "<what landed>" --commit <hash>` (add `--status bail` if it bailed — a bail still gets a row). The `--summary`/`--commit` feed the task log and `CERBERUS.md`, which the script regenerates automatically.
4. Proceed to phase 3 (review) before considering the task done.

### Implementation subagent: build → verify → commit

You start with fresh context, so orient before touching anything.

1. **Orient.** Read `CLAUDE.md` (if present) for binding code/repo conventions, then the plan and the specific files it names.
2. **Make the change** required, following the plan. If you deviate, that's fine — say why in your return summary so the reviewer understands the divergence.
3. **Build *and* run the project's verification command, and confirm tests actually executed and passed.** Mandatory; cannot be skipped or shortcut.
   - **Compilation is not verification.** "It builds" / "no type errors" does not count. The verification command must actually *execute* — unit tests run, the app launches, whatever the project defines as proof. A green build with zero tests run is a failure of this step.
   - **If you wrote or modified tests, execute those specific tests and observe them pass** — confirm the names appear in the run and the result was success. A test that compiles but never ran proves nothing, so seeing it actually run is the only evidence that counts.
   - **Read the output, don't just check the exit code.** "0 tests run", "skipped", "no tests found", or "build succeeded" with no test summary are red flags even at exit code 0.
   - **If verification can't run in your environment** (missing simulator, credentials, hardware, sandbox), you have not verified. Bail per "When you can't finish" and name the step you couldn't run.
   - **If the build was already broken when you started**, note it and bail — don't fix unrelated breakage.
4. **Commit the code** (if in a git repo). Stage only the code changes. Use a short declarative message with the verb that fits (`Fix`, `Add`, `Refactor`, …), a blank line, then a paragraph of detail. Follow any convention `CLAUDE.md` or recent `git log` establishes. Capture the short hash with `git rev-parse --short HEAD`. If not in a repo, leave the change in the working tree and say so.
5. **Return a summary** to the orchestrator: what changed (one bullet per file), the exact verification command run and what you observed, the commit hash (if any), and any divergence from the plan or gotchas. This summary is what the reviewer checks against — be precise about the verification.

### When you can't finish

If the task is unreproducible, out of scope, or verification won't pass after reasonable effort:

1. **Discard or stash partial changes** so the bail doesn't leave half-done work.
2. **Return a bail summary** describing what you tried, the failure mode, and what you'd try next. The orchestrator relays it; a later attempt starts from your notes.
3. The orchestrator still records a worklog row — the attempt spent tokens.

## Phase 3 — Review (Opus)

An independent, stronger-than-the-implementer subagent is the gate between "code landed" and "verified." This separation is what makes review meaningful: the reviewer re-derives correctness instead of trusting the author.

### Orchestrator: dispatch the reviewer

After implementation returns (with a commit and a verification summary), **spawn a fresh Opus subagent** to review. When it returns, record its usage: `scripts/record_usage.py --task "<label>" --phase review` (add `--status bounce` if it bounced).

### Review subagent: verify → approve or bounce

1. **Orient**, same as the others: `CLAUDE.md`, then the task, the plan, and the implementer's summary.
2. **Inspect the diff.** Read the implementation commit (`git show <hash>`, or the working-tree diff if not committed). Check it against the plan and the task: does it actually address what was asked? Is the scope right? Any obvious correctness, security, or regression risk?
3. **Re-run verification independently.** Do **not** trust the implementer's reported verification — run the project's verification command yourself and read the output. Confirm tests actually executed and passed, to the same standard as phase 2. This independent run is the core of the review.
4. **Decide and return:**
   - **Approve** — the change is correct and verification passed. Return a terse one-line verdict (`✅ Verified — <what you ran>, <result>`) plus anything the user should know.
   - **Bounce** — verification failed, the change is wrong, or scope is off. Return a specific brief: which check failed, what you observed, and what the next implementation pass must address. Leave the commit in place unless it must be discarded (say so). The orchestrator re-dispatches phase 2 with your notes.

The reviewer verifies; it does not declare the task *accepted*. Acceptance is the user's call — the orchestrator reports the verdict and lets the user confirm.

**On approval, if the task came from a planning doc**, the orchestrator may tick that task off in the doc (check its box, optionally noting the commit) so the doc reflects reality. Do this only after review approves, keep the edit minimal, and don't restructure the doc — it's the user's. `CERBERUS.md` updates on its own from the worklog; the planning doc is the one user-owned artifact Cerberus touches.

## The bounce loop

```
task ──▶ [Fable] plan ──▶ [Sonnet] implement + verify + commit ──▶ [Opus] review
                                        ▲                                  │
                                        │                                  ├──▶ ✅ approve ──▶ report to user ──▶ user accepts
                                        └────────── bounce (notes) ◀───────┘
```

Each pass through implementation and each review is its own worklog row (mark rejected reviews `--status bounce`, abandoned implementations `--status bail`). If bounces repeat (say, 2–3 times without convergence), stop looping and surface the situation to the user with the reviewer's notes — throwing more subagent passes at a stuck task just burns tokens.

## Related references

- **`cost-tracking.md`** — recording each phase's usage and cost, the worklog layout, and the weekly rollup.
- **`token-tips.md`** — trimming the pipeline and scoping context to spend fewer tokens.
