#!/usr/bin/env python3
"""Record one Cerberus subagent dispatch to the worklog.

Run this right after a subagent returns. It finds that subagent's transcript,
sums its token usage (deduped correctly), prices it against the cached rates,
and appends one JSON record to ``worklog/usage.jsonl`` — the machine-readable
source of truth that ``report.py`` rolls up.

Why a script and not prose: the orchestrator would otherwise have to parse the
transcript, dedupe by request, and do floating-point cost math by hand on every
dispatch. That is exactly the kind of deterministic, error-prone work worth
doing once, in one tested place.

Usage:
    record_usage.py --task "Avatar → profile nav" --phase plan
    record_usage.py --task "Avatar → profile nav" --phase implement --status bounce
    record_usage.py --task "Docs pass" --phase review --transcript /path/to/agent-x.jsonl
    record_usage.py --task "Offline task" --phase plan --model claude-fable-5   # no transcript

The transcript is located by recency by default (the newest ``agent-*.jsonl``
under this project's Claude Code session dir). Pass --transcript to be explicit
when several subagents ran close together.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys


def project_slug(project_dir):
    """Claude Code's project-slug: '/', '.', '_' each become '-'."""
    return re.sub(r"[/._]", "-", os.path.abspath(project_dir))


def find_transcript(project_dir):
    """Newest agent-*.jsonl under this project's Claude Code session dirs."""
    slug = project_slug(project_dir)
    home = os.path.expanduser("~")
    pattern = os.path.join(home, ".claude", "projects", slug, "*", "subagents", "agent-*.jsonl")
    matches = glob.glob(pattern)
    if not matches:
        return None
    return max(matches, key=os.path.getmtime)


def parse_usage(transcript_path):
    """Sum token usage across a transcript, deduped so one API response counts once.

    A single response is written as several JSONL lines (one per content block),
    each repeating the same usage. We key by requestId, falling back to the
    assistant message id, then the line number — so a response with a missing
    requestId still collapses to one entry instead of over-counting.
    """
    seen = {}          # dedup key -> usage dict
    model_requests = {}  # model id -> number of distinct requests
    with open(transcript_path) as fh:
        for i, line in enumerate(fh):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", {})
            usage = msg.get("usage")
            if not usage:
                continue
            key = obj.get("requestId") or msg.get("id") or f"_line{i}"
            if key not in seen:
                model_requests[msg.get("model", "?")] = model_requests.get(msg.get("model", "?"), 0) + 1
            seen[key] = usage  # last line for a request wins; usage is identical across its lines

    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for u in seen.values():
        totals["input"] += u.get("input_tokens", 0) or 0
        totals["output"] += u.get("output_tokens", 0) or 0
        totals["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
        totals["cache_write"] += u.get("cache_creation_input_tokens", 0) or 0

    # The model that did the most requests is the phase's model; a fallback tier
    # would show up here as a different, less-frequent id.
    model = max(model_requests, key=model_requests.get) if model_requests else None
    return totals, model, len(seen), sorted(model_requests)


def compute_cost(totals, model, pricing_path):
    """Return (cost_or_None, pricing_date_or_None, note). None cost = can't price honestly."""
    if not os.path.exists(pricing_path):
        return None, None, "no pricing cache"
    try:
        pricing = json.load(open(pricing_path))
    except (json.JSONDecodeError, OSError):
        return None, None, "unreadable pricing cache"
    rates = pricing.get("models", {}).get(model)
    fetched = pricing.get("fetched")
    if not rates:
        return None, fetched, f"no price for {model}"
    cost = (
        totals["input"] * rates.get("input", 0)
        + totals["output"] * rates.get("output", 0)
        + totals["cache_read"] * rates.get("cache_read", 0)
        + totals["cache_write"] * rates.get("cache_write_5m", 0)
    ) / 1_000_000
    return round(cost, 2), fetched, ""


def main():
    ap = argparse.ArgumentParser(description="Append one dispatch to the Cerberus worklog.")
    ap.add_argument("--task", required=True, help="Short label for the piece of work (groups its phases).")
    ap.add_argument("--phase", required=True, choices=["plan", "implement", "review"])
    ap.add_argument("--status", default="ok", choices=["ok", "bounce", "bail"],
                    help="ok = normal; bounce = review rejected; bail = implementation gave up. All still cost tokens.")
    ap.add_argument("--note", default="", help="Optional free-text note (e.g. fallback reason, what bounced).")
    ap.add_argument("--transcript", help="Explicit transcript path; default is the newest agent-*.jsonl for this project.")
    ap.add_argument("--model", help="Model id to record when no transcript is available (other harnesses).")
    ap.add_argument("--worklog-dir", default="worklog")
    ap.add_argument("--pricing", help="Pricing cache path (default: <worklog-dir>/model-pricing.json).")
    ap.add_argument("--project-dir", default=os.getcwd(), help="Project root, for locating the transcript.")
    args = ap.parse_args()

    pricing_path = args.pricing or os.path.join(args.worklog_dir, "model-pricing.json")

    transcript = args.transcript or find_transcript(args.project_dir)
    note_parts = [args.note] if args.note else []

    if transcript and os.path.exists(transcript):
        totals, model, requests, models_seen = parse_usage(transcript)
        model = args.model or model
        cost, pricing_date, cost_note = compute_cost(totals, model, pricing_path)
        if cost_note:
            note_parts.append(cost_note)
        if len(models_seen) > 1:
            note_parts.append("multiple models in transcript: " + ", ".join(models_seen))
    else:
        # No transcript (other harness / offline). Record what we can, honestly.
        totals = {"input": None, "output": None, "cache_read": None, "cache_write": None}
        model = args.model
        requests = 0
        cost, pricing_date = None, None
        note_parts.append("no transcript found; tokens unavailable")

    today = datetime.date.today()
    iso_year, iso_week, _ = today.isocalendar()

    record = {
        "date": today.isoformat(),
        "week": f"{iso_year}-W{iso_week:02d}",
        "task": args.task,
        "phase": args.phase,
        "status": args.status,
        "model": model,
        "input": totals["input"],
        "output": totals["output"],
        "cache_read": totals["cache_read"],
        "cache_write": totals["cache_write"],
        "requests": requests,
        "cost": cost,
        "pricing_date": pricing_date,
        "note": "; ".join(p for p in note_parts if p),
    }

    os.makedirs(args.worklog_dir, exist_ok=True)
    out_path = os.path.join(args.worklog_dir, "usage.jsonl")
    with open(out_path, "a") as fh:
        fh.write(json.dumps(record) + "\n")

    # Human-readable confirmation for the orchestrator to relay.
    cost_str = f"${cost:,.2f}" if cost is not None else "— (uncosted)"
    tok = totals["input"]
    tok_str = (f"{totals['input']:,} in / {totals['output']:,} out / "
               f"{totals['cache_read']:,} cache-r / {totals['cache_write']:,} cache-w") if tok is not None else "tokens unavailable"
    warn = ""
    if cost is None:
        warn = "  [!] could not price this row — " + (record["note"] or "see pricing cache")
    print(f"Recorded {args.phase} for \"{args.task}\": {model or '?'}  {cost_str}  ({tok_str}){warn}")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
