# Token usage, cost, and the weekly rollup

How Cerberus records what each phase spent and rolls it up so the user can see weekly cost against their Claude Code plan. Usage is recorded by the **orchestrator** after a subagent returns — a subagent can't measure its own totals (its transcript is still growing while it works, and it doesn't know its own transcript filename).

The pipeline dispatches a subagent in **three phases** — planning (Fable), implementation (Sonnet), review (Opus) — so a single task normally produces at least three worklog rows, plus one for every bounce or retry. Record usage after *each* subagent returns; the recipe below is identical for all three.

Everything here lives under a **git-ignored `worklog/` folder** in the user's project. Nothing about cost tracking enters source control. Confirm `git check-ignore -q worklog/` exits 0 before writing.

## Layout

```
worklog/
├── model-pricing.json   # cached per-MTok prices, refreshed at most once/day
├── 2026-W28.md          # one file per ISO week; one table row per subagent dispatch
└── 2026-W29.md
```

Weekly files are named by **ISO week**: `YYYY-Www.md` (e.g. `2026-W28.md`). Grouping by week makes the rollup a single-file read. Derive the ISO week from your `currentDate` context — e.g. 2026-07-08 falls in week 28, so `2026-W28.md`.

## The pricing cache (`worklog/model-pricing.json`)

Anthropic doesn't expose pricing through an API endpoint — prices are published on the docs site. Fetch once per day and cache, so a series of tasks doesn't re-fetch per dispatch.

### Schema

```json
{
  "fetched": "2026-07-08",
  "source": "https://docs.claude.com/en/docs/about-claude/pricing",
  "currency": "USD per MTok",
  "models": {
    "claude-fable-5": {
      "input": 5.00,
      "output": 25.00,
      "cache_write_5m": 6.25,
      "cache_read": 0.50
    },
    "claude-opus-4-8": {
      "input": 5.00,
      "output": 25.00,
      "cache_write_5m": 6.25,
      "cache_read": 0.50
    },
    "claude-sonnet-4-6": {
      "input": 3.00,
      "output": 15.00,
      "cache_write_5m": 3.75,
      "cache_read": 0.30
    }
  }
}
```

All rates are **USD per million tokens**. The four rates map onto the four token counts in each transcript usage record. The numbers above are illustrative — never trust them over a fresh fetch.

### Daily refresh

Before the first subagent dispatch of a session:

1. Read `worklog/model-pricing.json`. If it exists and `fetched` equals today's date, use it as-is.
2. Otherwise, fetch `https://docs.claude.com/en/docs/about-claude/pricing` with WebFetch and extract, per current model: input, output, cache-write (5-minute), and cache-read rates per MTok. Rewrite the cache with today's date.
3. **If the fetch fails** (offline, page moved), keep using the stale cache and append ` (pricing as of <fetched date>)` to the cost cell of rows you write. A stale price is an estimate; say so. With no cache at all, record tokens and model but put `—` in the cost column.

Include the models this pipeline actually uses — under the defaults that's the top model for planning (Fable), plus Sonnet and Opus for implementation and review. Add any model that shows up missing on the next refresh.

## Getting exact token counts for a subagent

When Claude Code spawns a subagent, its full transcript is written to:

```
~/.claude/projects/<project-slug>/<session-id>/subagents/agent-<id>.jsonl
```

`<project-slug>` is the working directory with `/`, `.`, and `_` each replaced by `-` (e.g. `/Users/brennan/Developer/MyApp` → `-Users-brennan-Developer-MyApp`). Every assistant turn carries a `message.usage` object:

| Usage field | Meaning | Priced at |
|---|---|---|
| `input_tokens` | uncached input | `input` rate |
| `output_tokens` | generated output | `output` rate |
| `cache_read_input_tokens` | input served from prompt cache | `cache_read` rate |
| `cache_creation_input_tokens` | input written into the cache | `cache_write_5m` rate |

`message.model` on the same lines is the exact model id (e.g. `claude-opus-4-8`) — record *this*, not the intended default.

**Critical: dedupe by `requestId`.** One API response can be written as several JSONL lines (one per content block), each repeating the same `usage`. Summing every line over-counts — count each `requestId` once.

### Recipe

Right after the subagent returns, locate its transcript — the most recently modified agent file — and sum the usage. Because Cerberus writes no task id to disk, identify the subagent's transcript by recency rather than by grepping for a ticket number: take the newest `agent-*.jsonl` modified since you dispatched.

```bash
SLUG=$(pwd | tr '/._' '---')
FILE=$(ls -t ~/.claude/projects/$SLUG/*/subagents/agent-*.jsonl 2>/dev/null | head -1)
python3 - "$FILE" <<'EOF'
import json, sys
seen, models = {}, set()
for line in open(sys.argv[1]):
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        continue
    msg = obj.get("message", {})
    u = msg.get("usage")
    if not u:
        continue
    models.add(msg.get("model", "?"))
    seen[obj.get("requestId")] = u   # dedupe: last line per request wins
t = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
for u in seen.values():
    t["input"] += u.get("input_tokens", 0)
    t["output"] += u.get("output_tokens", 0)
    t["cache_read"] += u.get("cache_read_input_tokens", 0)
    t["cache_write"] += u.get("cache_creation_input_tokens", 0)
print(json.dumps({"models": sorted(models), "requests": len(seen), **t}))
EOF
```

If several subagents ran close together and recency is ambiguous, widen with `ls -t … | head -5` and pick the file whose `message.model` and turn count match the phase you just dispatched.

### Cost formula

```
cost = (input × input_rate
      + output × output_rate
      + cache_read × cache_read_rate
      + cache_write × cache_write_5m_rate) / 1,000,000
```

Round to the cent. Cache reads usually dominate the token count but cost a tenth of the input rate — don't be alarmed by multi-million cache-read counts.

### When transcripts aren't available

The transcript layout is a Claude Code implementation detail; the skill also runs under other harnesses. If no `agent-*.jsonl` exists:

1. If the harness reported a token total when the subagent returned (e.g. a "Done (… tokens …)" summary), record that total in the `Output` column with a `(total, breakdown unavailable)` note and leave cost `—` or a rough estimate marked `~`.
2. If nothing is available, still record the date, task, phase, and model with `—` for tokens and cost. A row with a model and no numbers still shows work happened.

Never fabricate counts. `—` is the honest value.

## The weekly worklog file (`worklog/YYYY-Www.md`)

One table row per subagent dispatch, appended as work happens. Create the file on the week's first dispatch with a header; append thereafter.

```markdown
# Work log — 2026-W28 (Jul 6–12)

| Date | Task | Phase | Model | Input | Output | Cache read | Cache write | Cost |
|---|---|---|---|---|---|---|---|---|
| 2026-07-08 | Avatar → profile nav | plan | claude-fable-5 | 84 | 6,102 | 512,400 | 41,200 | $0.58 |
| 2026-07-08 | Avatar → profile nav | implement | claude-sonnet-4-6 | 120 | 18,530 | 2,904,110 | 98,400 | $1.12 |
| 2026-07-08 | Avatar → profile nav | review | claude-opus-4-8 | 96 | 9,240 | 1,331,200 | 44,800 | $1.05 |

**Week total: $2.75**
```

Rules:

- **One row per dispatch**, including **bails** and review **bounces** — a failed or rejected attempt still burned tokens, and the week's true cost must reflect it.
- **Task** is a short label for the piece of work (a few words), repeated across that task's rows so the three phases group visually. Cerberus has no ticket number, so this label is the only grouping key.
- **Phase** is `plan` / `implement` / `review`. Keep it on every row.
- Token cells use thousands separators.
- **Week total** is the running sum of the Cost column — update it whenever a row is appended.
- Don't reformat existing rows when appending — diff-friendly edits (even though the file is git-ignored, the user reads these diffs).

## The weekly rollup

When the user asks "what has this week cost?", "how much have I spent?", or "does this fit my plan?":

1. **Sum this week.** Read the current `worklog/YYYY-Www.md` and report the Week total. For a range ("this month", "last 4 weeks"), read the relevant week files and sum across them.
2. **Break it down** if useful: by phase (plan/implement/review) and by model, so the user sees where the money goes. Review and planning on the top tier usually dominate; that's expected.
3. **Project to a month.** Multiply a representative week by ~4.3 to estimate monthly spend. Note it's a projection from recent usage, not a guarantee.
4. **Map to Claude Code plan tiers** so the user can judge fit:

   | Plan | Monthly price | Rough fit signal |
   |---|---|---|
   | Pro | ~$20/mo | Light, intermittent pipeline use |
   | Max 5× | ~$100/mo | Regular daily use |
   | Max 20× | ~$200/mo | Heavy, all-day use |
   | API / pay-as-you-go | metered | You pay the measured cost directly |

   **Frame subscriptions as usage limits, not dollar caps.** A Pro or Max subscription doesn't bill per token — it grants a usage allowance. The worklog's dollar figure is the *API-equivalent value* of what the pipeline consumed; comparing that estimate to a tier's price tells the user whether their current plan is comfortable or tight. If projected monthly API-equivalent spend sits well under a tier's price, that tier is comfortable; if it approaches or exceeds it, they're likely hitting usage limits and should consider the next tier or the token-saving tactics in `token-tips.md`. Verify current plan names and prices at the pricing page rather than trusting this table if precision matters — plans change.

5. **Offer to reduce spend.** If the rollup looks high, proactively surface tactics from `token-tips.md`.

## Anti-patterns

- **Don't commit the worklog.** Confirm `worklog/` is git-ignored before writing.
- **Don't sum every JSONL line.** Dedupe by `requestId` or totals over-count (~30% of lines can be duplicates).
- **Don't hardcode prices in prose or code.** Prices live only in the dated cache file.
- **Don't price cache reads at the input rate.** They're ~10× cheaper; conflating them inflates cache-heavy sessions dramatically.
- **Don't let the subagent self-report usage.** It can't see its own totals; the orchestrator measures after return.
- **Don't skip the row on a bail or bounce.** Failed attempts cost real money and belong in the tally.
- **Don't record the default model id — record the actual one** the transcript shows, in case a fallback tier was used.
