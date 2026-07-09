#!/usr/bin/env python3
"""Roll up the Cerberus worklog into a weekly or monthly report.

Reads ``worklog/usage.jsonl`` (written by record_usage.py) and aggregates spend
by phase, model, and task over a chosen period. Because the worklog is
structured data rather than hand-formatted markdown, the rollup is exact and
regenerable — no summing tables by eye.

Usage:
    report.py --this-week
    report.py --this-month
    report.py --week 2026-W28
    report.py --month 2026-07
    report.py --range 2026-06-01 2026-06-30
    report.py --all
    report.py --this-month --markdown      # emit a markdown report instead of plain text

A weekly report also projects to a month (× 4.3) so the figure can be compared
against a subscription tier.
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

import worklog  # co-located: shared loader, cost formatting, and task-status derivation
from worklog import money


def load_records(worklog_dir):
    records = worklog.load_records(worklog_dir)
    if not records:
        sys.exit(f"No worklog at {os.path.join(worklog_dir, 'usage.jsonl')}. Nothing recorded yet.")
    return records


def iso_week_label(date_str):
    y, w, _ = datetime.date.fromisoformat(date_str).isocalendar()
    return f"{y}-W{w:02d}"


def select(records, args):
    """Return (filtered_records, human_period_label, is_week_period)."""
    if args.all:
        return records, "all time", False
    if args.week:
        return [r for r in records if r.get("week") == args.week], args.week, True
    if args.this_week:
        y, w, _ = datetime.date.today().isocalendar()
        label = f"{y}-W{w:02d}"
        return [r for r in records if r.get("week") == label], f"{label} (this week)", True
    if args.month:
        return [r for r in records if str(r.get("date", "")).startswith(args.month)], args.month, False
    if args.this_month:
        label = datetime.date.today().strftime("%Y-%m")
        return [r for r in records if str(r.get("date", "")).startswith(label)], f"{label} (this month)", False
    if args.range:
        start, end = args.range
        return ([r for r in records if start <= str(r.get("date", "")) <= end],
                f"{start} … {end}", False)
    # Default: this week.
    y, w, _ = datetime.date.today().isocalendar()
    label = f"{y}-W{w:02d}"
    return [r for r in records if r.get("week") == label], f"{label} (this week)", True


def group(records, key):
    agg = defaultdict(lambda: {"cost": 0.0, "rows": 0, "uncosted": 0})
    for r in records:
        bucket = agg[r.get(key) or "?"]
        bucket["rows"] += 1
        if r.get("cost") is None:
            bucket["uncosted"] += 1
        else:
            bucket["cost"] += r["cost"]
    return agg


def summarize(records):
    total = sum(r["cost"] for r in records if r.get("cost") is not None)
    uncosted = sum(1 for r in records if r.get("cost") is None)
    bounces = sum(1 for r in records if r.get("status") == "bounce")
    bails = sum(1 for r in records if r.get("status") == "bail")
    return total, uncosted, bounces, bails


def render_text(records, label, is_week):
    if not records:
        return f"No worklog rows for {label}."
    total, uncosted, bounces, bails = summarize(records)
    lines = [f"Cerberus worklog — {label}", "=" * (len(label) + 20), ""]
    lines.append(f"Total: {money(total)} across {len(records)} dispatch(es)")
    if uncosted:
        lines.append(f"  ({uncosted} row(s) uncosted — pricing unavailable when recorded)")
    if bounces or bails:
        lines.append(f"  ({bounces} bounce(s), {bails} bail(s) — failed attempts still counted)")
    lines.append("")

    for title, key in (("By phase", "phase"), ("By model", "model"), ("By task", "task")):
        lines.append(f"{title}:")
        agg = group(records, key)
        for name, b in sorted(agg.items(), key=lambda kv: kv[1]["cost"], reverse=True):
            extra = f"  ({b['uncosted']} uncosted)" if b["uncosted"] else ""
            lines.append(f"  {name:<28} {money(b['cost']):>12}  {b['rows']} row(s){extra}")
        lines.append("")

    if is_week:
        lines.append(f"Projected month (× 4.3): {money(total * 4.3)}")
        lines.append("  A projection from this week's usage, not a guarantee. Subscription tiers")
        lines.append("  are usage allowances, not per-token bills — compare this API-equivalent")
        lines.append("  figure to a tier's price to judge whether the plan is comfortable or tight.")
    return "\n".join(lines)


def render_markdown(records, label, is_week):
    if not records:
        return f"# Cerberus worklog — {label}\n\nNo rows recorded."
    total, uncosted, bounces, bails = summarize(records)
    out = [f"# Cerberus worklog — {label}", ""]
    out.append(f"**Total: {money(total)}** across {len(records)} dispatch(es).")
    if uncosted:
        out.append(f"_{uncosted} row(s) uncosted (pricing unavailable when recorded)._")
    if bounces or bails:
        out.append(f"_{bounces} bounce(s), {bails} bail(s) — failed attempts still counted._")
    out.append("")

    for title, key in (("By phase", "phase"), ("By model", "model"), ("By task", "task")):
        out.append(f"## {title}")
        out.append("")
        out.append("| " + key.capitalize() + " | Cost | Rows |")
        out.append("|---|---:|---:|")
        agg = group(records, key)
        for name, b in sorted(agg.items(), key=lambda kv: kv[1]["cost"], reverse=True):
            out.append(f"| {name} | {money(b['cost'])} | {b['rows']} |")
        out.append("")

    out.append("## Detail")
    out.append("")
    out.append("| Date | Task | Phase | Model | Input | Output | Cache read | Cache write | Cost |")
    out.append("|---|---|---|---|---:|---:|---:|---:|---:|")
    for r in sorted(records, key=lambda r: (r.get("date", ""), r.get("task", ""))):
        def num(v):
            return f"{v:,}" if isinstance(v, int) else "—"
        cost = money(r["cost"]) if r.get("cost") is not None else "—"
        out.append(f"| {r.get('date','')} | {r.get('task','')} | {r.get('phase','')} | "
                   f"{r.get('model','')} | {num(r.get('input'))} | {num(r.get('output'))} | "
                   f"{num(r.get('cache_read'))} | {num(r.get('cache_write'))} | {cost} |")
    out.append("")
    if is_week:
        out.append(f"**Projected month (× 4.3): {money(total * 4.3)}.** A projection from this "
                   "week's usage. Subscription tiers are usage allowances, not per-token bills.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Roll up the Cerberus worklog.")
    ap.add_argument("--worklog-dir", default="worklog")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--this-week", action="store_true")
    g.add_argument("--this-month", action="store_true")
    g.add_argument("--week", help="ISO week, e.g. 2026-W28")
    g.add_argument("--month", help="Calendar month, e.g. 2026-07")
    g.add_argument("--range", nargs=2, metavar=("START", "END"), help="Inclusive YYYY-MM-DD dates")
    g.add_argument("--all", action="store_true")
    g.add_argument("--status", action="store_true", help="Show what task is in flight now.")
    g.add_argument("--tasks", action="store_true", help="Show a readable log of recent tasks and their outcomes.")
    g.add_argument("--write-status", action="store_true", help="(Re)write the CERBERUS.md dashboard file and exit.")
    ap.add_argument("--status-file", default="CERBERUS.md", help="Path for --write-status (default: CERBERUS.md).")
    ap.add_argument("--markdown", action="store_true", help="Emit markdown instead of plain text.")
    args = ap.parse_args()

    records = load_records(args.worklog_dir)

    # Task-level views (derived): current status and the recent-tasks log.
    if args.status:
        print(worklog.render_status_md(records) if args.markdown else worklog.render_status_text(records))
        return
    if args.tasks:
        print(worklog.render_status_md(records) if args.markdown else worklog.render_tasks_text(records))
        return
    if args.write_status:
        path = worklog.write_status_file(args.status_file, worklog_dir=args.worklog_dir, records=records)
        print(f"Wrote {path}")
        return

    # Cost rollup views (default): totals over a period, by phase/model/task.
    selected, label, is_week = select(records, args)
    if args.markdown:
        print(render_markdown(selected, label, is_week))
    else:
        print(render_text(selected, label, is_week))


if __name__ == "__main__":
    main()
