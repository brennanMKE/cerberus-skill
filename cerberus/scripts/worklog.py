"""Shared worklog helpers: load records and derive task-level status.

Both record_usage.py and report.py import this so the task lifecycle is
inferred in exactly one place. The worklog (`worklog/usage.jsonl`) stays the
single source of truth — everything here is a *derived read model* over it, not
a separate tracker. There are no per-task files; the one rendered artifact is
`CERBERUS.md`, a transient, git-ignored status dashboard at the project root.
"""
import datetime
import json
import os


def load_records(worklog_dir):
    """Return the usage records in append order (oldest first). [] if none."""
    path = os.path.join(worklog_dir, "usage.jsonl")
    if not os.path.exists(path):
        return []
    records = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def money(x):
    return f"${x:,.2f}"


# Outcome markers: internal key -> (emoji, label)
OUTCOMES = {
    "approved": ("✅", "approved"),
    "bailed": ("⚠️", "bailed"),
    "in_progress": ("↻", "in progress"),
    "planned": ("📋", "planned"),
}


def _outcome(rows):
    """Infer a task's outcome from its rows, in append order.

    The worklog carries phase + status per dispatch, so the latest row tells us
    where a task stands without any extra bookkeeping:
      - a bail is a bail;
      - a review that wasn't a bounce means the reviewer approved;
      - a bounce, or an implementation with no review after it, is still open;
      - a lone plan is planned (maybe exploration, maybe awaiting a build).
    """
    last = rows[-1]
    if last.get("status") == "bail":
        return "bailed"
    phase, status = last.get("phase"), last.get("status")
    if phase == "review":
        return "approved" if status == "ok" else "in_progress"
    if phase == "implement":
        return "in_progress"  # built but not yet reviewed
    if phase == "plan":
        return "planned" if len(rows) == 1 else "in_progress"
    return "in_progress"


def _in_flight_phrase(rows):
    """Human description of where an in-progress task was left off."""
    last = rows[-1]
    phase, status = last.get("phase"), last.get("status")
    if phase == "review" and status == "bounce":
        return "review bounced, awaiting re-implementation"
    if phase == "implement":
        return "implemented, awaiting review"
    if phase == "plan":
        return "planned, awaiting implementation"
    return "in progress"


def derive_tasks(records):
    """Group records into per-task summaries, most-recently-active first."""
    order = []            # task labels in first-seen order
    rows_by_task = {}
    last_index = {}
    for i, r in enumerate(records):
        task = r.get("task") or "(unlabeled)"
        if task not in rows_by_task:
            rows_by_task[task] = []
            order.append(task)
        rows_by_task[task].append(r)
        last_index[task] = i

    tasks = []
    for task in order:
        rows = rows_by_task[task]
        costs = [r["cost"] for r in rows if r.get("cost") is not None]
        phases = []
        for r in rows:
            p = r.get("phase")
            if p and p not in phases:
                phases.append(p)
        # Prefer the most recent non-empty summary/commit a dispatch supplied.
        summary = next((r.get("summary") for r in reversed(rows) if r.get("summary")), "")
        commit = next((r.get("commit") for r in reversed(rows) if r.get("commit")), "")
        tasks.append({
            "task": task,
            "outcome": _outcome(rows),
            "dispatches": len(rows),
            "bounces": sum(1 for r in rows if r.get("status") == "bounce"),
            "bails": sum(1 for r in rows if r.get("status") == "bail"),
            "cost": sum(costs),
            "uncosted": sum(1 for r in rows if r.get("cost") is None),
            "first_date": min((r.get("date", "") for r in rows), default=""),
            "last_date": max((r.get("date", "") for r in rows), default=""),
            "phases": phases,
            "summary": summary,
            "commit": commit,
            "in_flight_phrase": _in_flight_phrase(rows),
            "_last_index": last_index[task],
        })

    tasks.sort(key=lambda t: t["_last_index"], reverse=True)
    return tasks


def in_flight(tasks):
    """The most-recently-active task that still looks unfinished, or None."""
    for t in tasks:  # tasks are already most-recent-first
        if t["outcome"] == "in_progress":
            return t
    return None


def _now_str():
    # Standalone script context — real wall-clock time is fine and useful here.
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def render_status_md(records, limit=15):
    """The CERBERUS.md dashboard: what's in flight + recent tasks."""
    out = ["# Cerberus status", ""]
    out.append(f"_Derived from `worklog/usage.jsonl` — generated {_now_str()}. "
               "A transient, git-ignored read-out, not a tracker._")
    out.append("")

    if not records:
        out.append("No dispatches recorded yet.")
        return "\n".join(out) + "\n"

    tasks = derive_tasks(records)
    flt = in_flight(tasks)
    if flt:
        out.append(f"**In flight:** {flt['task']} — {flt['in_flight_phrase']} "
                   f"({flt['dispatches']} dispatch(es), {money(flt['cost'])})")
    else:
        out.append("**In flight:** nothing — no unfinished task.")
    out.append("")

    out.append("## Recent tasks")
    out.append("")
    out.append("| Task | Outcome | Dispatches | Cost | What landed | Commit |")
    out.append("|---|---|---:|---:|---|---|")
    for t in tasks[:limit]:
        emoji, label = OUTCOMES[t["outcome"]]
        cost = money(t["cost"]) + (f" +{t['uncosted']}?" if t["uncosted"] else "")
        disp = str(t["dispatches"])
        if t["bounces"] or t["bails"]:
            disp += f" ({t['bounces']}b/{t['bails']}x)"
        summary = t["summary"] or "—"
        commit = f"`{t['commit']}`" if t["commit"] else "—"
        out.append(f"| {t['task']} | {emoji} {label} | {disp} | {cost} | {summary} | {commit} |")
    out.append("")
    out.append("_Dispatches column: `(Nb/Mx)` = N bounces, M bails. "
               "Cost `+N?` = N dispatch(es) couldn't be priced._")
    return "\n".join(out) + "\n"


def write_status_file(status_path, worklog_dir="worklog", records=None, limit=15):
    """Regenerate the CERBERUS.md dashboard. Called after each dispatch is recorded.

    status_path is where to write (default caller passes the project-root
    CERBERUS.md); worklog_dir is where usage.jsonl is read from.
    """
    if records is None:
        records = load_records(worklog_dir)
    with open(status_path, "w") as fh:
        fh.write(render_status_md(records, limit=limit))
    return status_path


def render_tasks_text(records, limit=None):
    """Plain-text task log for `report.py --tasks`."""
    if not records:
        return "No dispatches recorded yet."
    tasks = derive_tasks(records)
    if limit:
        tasks = tasks[:limit]
    lines = ["Recent tasks", "=" * 12, ""]
    flt = in_flight(tasks)
    if flt:
        lines.append(f"In flight: {flt['task']} — {flt['in_flight_phrase']} "
                     f"({flt['dispatches']} dispatch(es), {money(flt['cost'])})")
    else:
        lines.append("In flight: nothing unfinished.")
    lines.append("")
    for t in tasks:
        emoji, label = OUTCOMES[t["outcome"]]
        flags = ""
        if t["bounces"] or t["bails"]:
            flags = f"  [{t['bounces']} bounce(s), {t['bails']} bail(s)]"
        cost = money(t["cost"]) + (f" (+{t['uncosted']} uncosted)" if t["uncosted"] else "")
        lines.append(f"{emoji} {t['task']:<28} {cost:>14}  {t['dispatches']} dispatch(es){flags}")
        detail = "  ".join(x for x in (t["summary"], f"[{t['commit']}]" if t["commit"] else "") if x)
        if detail:
            lines.append(f"     {detail}")
        lines.append(f"     phases: {' → '.join(t['phases'])}   {t['first_date']}"
                     + (f"…{t['last_date']}" if t["last_date"] != t["first_date"] else ""))
    return "\n".join(lines)


def render_status_text(records):
    """One-block 'what's happening now' for `report.py --status`."""
    if not records:
        return "No dispatches recorded yet."
    tasks = derive_tasks(records)
    flt = in_flight(tasks)
    if not flt:
        done = tasks[0] if tasks else None
        base = "Nothing in flight."
        if done:
            emoji, label = OUTCOMES[done["outcome"]]
            base += f" Last task: {done['task']} — {emoji} {label} ({money(done['cost'])})."
        return base
    return (f"In flight: \"{flt['task']}\" — {flt['in_flight_phrase']} "
            f"({flt['dispatches']} dispatch(es), {money(flt['cost'])} so far).")
