# Token usage, cost, and the weekly rollup

How Cerberus records what each phase spent and rolls it up so the user can see weekly or monthly cost against their Claude Code plan. Usage is recorded by the **orchestrator** after a subagent returns — a subagent can't measure its own totals (its transcript is still growing while it works, and it doesn't know its own transcript filename).

Two bundled scripts do the mechanical work, so the orchestrator never parses transcripts or does cost arithmetic by hand:

- **`scripts/record_usage.py`** — run once after each subagent returns. Finds that subagent's transcript, sums its token usage (deduped correctly), prices it against the cached rates, and appends one record to `worklog/usage.jsonl`.
- **`scripts/report.py`** — run when the user asks about cost. Aggregates `usage.jsonl` over a week, a month, or a date range, broken down by phase, model, and task.

The pipeline dispatches a subagent in **three phases** — planning, implementation, review — so a single task normally produces at least three worklog rows, plus one for every bounce or retry. Record usage after *each* subagent returns; the command is identical for all three.

Everything here lives under a **git-ignored `worklog/` folder** in the user's project. Nothing about cost tracking enters source control. Confirm `git check-ignore -q worklog/` exits 0 before writing.

## Layout

```
worklog/
├── model-pricing.json   # cached per-MTok prices, refreshed at most once/day
└── usage.jsonl          # one JSON record per subagent dispatch — the source of truth
```

`usage.jsonl` is machine-readable on purpose: the rollup reads structured records and computes exact totals, instead of a human summing markdown tables by eye. Human-readable weekly/monthly reports are *generated on demand* by `report.py` (optionally as markdown) rather than maintained by hand.

## The pricing cache (`worklog/model-pricing.json`)

Anthropic doesn't expose pricing through an API endpoint — prices are published on the docs site. The orchestrator fetches once per day (a WebFetch the script can't do itself) and caches, so a series of tasks doesn't re-fetch per dispatch. `record_usage.py` reads this cache to price each row.

### Schema

```json
{
  "fetched": "2026-07-08",
  "source": "https://docs.claude.com/en/docs/about-claude/pricing",
  "currency": "USD per MTok",
  "models": {
    "claude-fable-5":    { "input": 5.00, "output": 25.00, "cache_write_5m": 6.25, "cache_read": 0.50 },
    "claude-opus-4-8":   { "input": 5.00, "output": 25.00, "cache_write_5m": 6.25, "cache_read": 0.50 },
    "claude-sonnet-4-6": { "input": 3.00, "output": 15.00, "cache_write_5m": 3.75, "cache_read": 0.30 }
  }
}
```

All rates are **USD per million tokens**, keyed to match the four token counts in each transcript usage record. The numbers above are illustrative — never trust them over a fresh fetch. Include every model the pipeline actually uses (under the defaults: the planning, implementation, and review tiers); add any that shows up missing on the next refresh.

### Daily refresh

Before the first subagent dispatch of a session:

1. Read `worklog/model-pricing.json`. If it exists and `fetched` equals today's date, use it as-is.
2. Otherwise, fetch `https://docs.claude.com/en/docs/about-claude/pricing` with WebFetch and extract, per current model: input, output, cache-write (5-minute), and cache-read rates per MTok. Rewrite the cache with today's date.
3. **If the fetch fails** (offline, page moved), keep using the stale cache — `record_usage.py` will still price rows against it and stamp each row with the `pricing_date` it used, so a rollup can flag that the figure is an estimate. With no cache at all, the script records tokens with a null cost; `report.py` reports those as uncosted rows rather than guessing.

## How `record_usage.py` gets exact token counts

When Claude Code spawns a subagent, its full transcript is written to:

```
~/.claude/projects/<project-slug>/<session-id>/subagents/agent-<id>.jsonl
```

`<project-slug>` is the working directory with `/`, `.`, and `_` each replaced by `-`. The script locates the newest `agent-*.jsonl` for the project (or an explicit `--transcript` path) and sums each assistant turn's `message.usage`:

| Usage field | Meaning | Priced at |
|---|---|---|
| `input_tokens` | uncached input | `input` rate |
| `output_tokens` | generated output | `output` rate |
| `cache_read_input_tokens` | input served from prompt cache | `cache_read` rate |
| `cache_creation_input_tokens` | input written into the cache | `cache_write_5m` rate |

`message.model` on those lines is the exact model id — the script records *this*, not the intended default, so a fallback tier shows up truthfully.

**Dedupe is handled for you.** One API response is written as several JSONL lines (one per content block), each repeating the same `usage`. Summing every line over-counts (~30% of lines can be duplicates). The script keys by `requestId` — falling back to the assistant message id, then line number — so each response counts once even when `requestId` is absent. This was the single fiddliest bit of the old hand-run recipe; it now lives in one tested place.

### Recording a dispatch

Right after a subagent returns, run:

```bash
python3 cerberus/scripts/record_usage.py --task "Avatar → profile nav" --phase plan
```

- `--task` is a short label repeated across a task's rows so its phases group in the rollup. Cerberus writes no ticket id, so this label is the only grouping key.
- `--phase` is `plan`, `implement`, or `review`.
- `--status` defaults to `ok`; pass `bounce` (review rejected) or `bail` (implementation gave up) so failed attempts are visible in the rollup. Record them either way — a failed attempt still burned tokens.
- `--transcript PATH` pins the exact transcript when several subagents ran close together and recency is ambiguous.
- `--model ID` records the model when no transcript is available (see below).
- `--note` adds free text (e.g. why a fallback tier was used).

The script prints a one-line confirmation and the JSON record it appended. It computes cost with:

```
cost = (input × input_rate
      + output × output_rate
      + cache_read × cache_read_rate
      + cache_write × cache_write_5m_rate) / 1,000,000
```

rounded to the cent. Cache reads usually dominate the token count but cost a tenth of the input rate — don't be alarmed by multi-million cache-read counts.

### The record schema

Each line of `usage.jsonl` is one dispatch:

```json
{"date":"2026-07-08","week":"2026-W28","task":"Avatar → profile nav","phase":"plan",
 "status":"ok","model":"claude-fable-5","input":84,"output":6102,"cache_read":512400,
 "cache_write":41200,"requests":2,"cost":0.58,"pricing_date":"2026-07-08","note":""}
```

`cost` is `null` when the row couldn't be priced honestly (no pricing cache, or the model isn't in it); `pricing_date` records which day's prices were used, so a stale-priced row is auditable.

### When transcripts aren't available

The transcript layout is a Claude Code implementation detail; the skill also runs under other harnesses. If no `agent-*.jsonl` exists, still record the dispatch with `--model` so the row shows work happened:

```bash
python3 cerberus/scripts/record_usage.py --task "…" --phase review --model claude-opus-4-8
```

The script writes null token counts and a null cost with an explanatory note — never fabricated numbers. If the harness reported a token total on return, put it in `--note`. `null` is the honest value.

## The weekly (or monthly) rollup

When the user asks "what has this week cost?", "how much this month?", or "does this fit my plan?", run `report.py`:

```bash
python3 cerberus/scripts/report.py --this-week      # or --this-month, --week 2026-W28,
python3 cerberus/scripts/report.py --this-month      #    --month 2026-07, --range A B, --all
python3 cerberus/scripts/report.py --this-week --markdown   # markdown instead of plain text
```

It prints the total, a breakdown **by phase, by model, and by task**, and — for a weekly report — a monthly projection (× 4.3). It also surfaces how many rows were uncosted and how many were bounces/bails, so failed attempts aren't hidden.

Then help the user judge fit against their plan:

| Plan | Monthly price | Rough fit signal |
|---|---|---|
| Pro | ~$20/mo | Light, intermittent pipeline use |
| Max 5× | ~$100/mo | Regular daily use |
| Max 20× | ~$200/mo | Heavy, all-day use |
| API / pay-as-you-go | metered | You pay the measured cost directly |

**Frame subscriptions as usage limits, not dollar caps.** A Pro or Max subscription doesn't bill per token — it grants a usage allowance. The rollup's dollar figure is the *API-equivalent value* of what the pipeline consumed; comparing that estimate to a tier's price tells the user whether their plan is comfortable or tight. If projected monthly spend sits well under a tier's price, that tier is comfortable; if it approaches or exceeds it, they're likely hitting usage limits and should consider the next tier or the tactics in `token-tips.md`. Verify current plan names and prices at the pricing page if precision matters — plans change. If the rollup looks high, proactively offer those tactics.

## Anti-patterns

- **Don't commit the worklog.** Confirm `worklog/` is git-ignored before writing.
- **Don't reconstruct the token-counting or cost math by hand.** Run `record_usage.py` — it dedupes by request and prices from the cache. Hand-summing over-counts and hand-arithmetic drifts.
- **Don't hardcode prices in prose or code.** Prices live only in the dated cache file, which the script reads.
- **Don't let the subagent self-report usage.** It can't see its own totals; the orchestrator measures after return.
- **Don't skip the row on a bail or bounce.** Failed attempts cost real money and belong in the tally — record them with `--status bail` / `--status bounce`.
- **Don't record the intended default model** — the script records the actual one from the transcript, in case a fallback tier was used.
