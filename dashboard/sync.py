#!/usr/bin/env python3
"""Safe edits to the task list, for use by the scheduled task.

The board joins two files: tasks.json holds the wording, Home.md holds the state.
An item only appears if it exists in BOTH with the same key. Hand-editing two
files in step is exactly the sort of thing an unattended run gets wrong, so do it
through here instead.

    python3 sync.py list                      # what is on the board now, as JSON
    python3 sync.py add --title "..." --workstream "..." [...]
    python3 sync.py set-status --key KEY --status done
    python3 sync.py note --key KEY --text "..."

Every command prints what it did. `add` is idempotent on the key, so re-running a
sync does not create duplicates.
"""

import argparse
import json
import re
import sys
import unicodedata

import homedash

NEW_HEADING = "### New this week"


def workstreams():
    """The allowed workstreams, taken from tasks.json — not hardcoded here."""
    data = json.loads(homedash.TASKS_JSON.read_text())
    listed = data.get("workstreams")
    if listed:
        return listed
    seen = []
    for task in data["tasks"]:                       # fall back to whatever is in use
        if task["workstream"] not in seen:
            seen.append(task["workstream"])
    return seen


def slugify(text, existing):
    base = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()[:48] or "task"
    key, n = base, 2
    while key in existing:
        key, n = f"{base}-{n}", n + 1
    return key


def load_tasks():
    return json.loads(homedash.TASKS_JSON.read_text())


def save_tasks(data):
    homedash.TASKS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def cmd_list(args):
    payload = homedash.build_payload()
    rows = [{k: t[k] for k in ("key", "title", "status", "workstream", "priority", "due", "refs")}
            for t in payload["tasks"]]
    print(json.dumps({"week": payload["meta"]["week"], "tasks": rows}, ensure_ascii=False, indent=2))


def cmd_add(args):
    data = load_tasks()
    existing = {t["key"] for t in data["tasks"]}

    key = args.key or slugify(args.title, existing)
    if key in existing:
        print(f"skip: {key} already exists")
        return

    refs = []
    for raw in args.ref or []:
        if "=" not in raw:
            sys.exit(f"--ref must be LABEL=URL, got {raw!r}")
        label, url = raw.split("=", 1)
        refs.append({"label": label, "url": url})

    task = {
        "key": key,
        "title": args.title,
        "detail": args.detail or "",
        "workstream": args.workstream,
        "priority": args.priority,
        "due": args.due,
        "status": "todo",
        "source": args.source,
        "refs": refs,
    }
    data["tasks"].append(task)

    # Home.md line, under a "New this week" heading so additions are obvious.
    link = "".join(f" — [{r['label']}]({r['url']})" for r in refs)
    line = f"- [ ] {args.title}{link}  ^{key}"

    lines = homedash.HOME_MD.read_text().split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(homedash.SECTION_START))
        end = next(i for i, l in enumerate(lines) if l.startswith(homedash.SECTION_END))
    except StopIteration:
        sys.exit("Could not find the week section in Home.md — aborting without writing.")

    heading = next((i for i in range(start, end) if lines[i].strip() == NEW_HEADING), None)
    if heading is None:
        tail = end
        while tail > start and not lines[tail - 1].strip():
            tail -= 1
        lines[tail:tail] = ["", NEW_HEADING, "", line]
    else:
        insert = heading + 1
        while insert < end and (lines[insert].startswith("- [") or not lines[insert].strip()):
            insert += 1
        while insert > heading + 1 and not lines[insert - 1].strip():
            insert -= 1
        lines[insert:insert] = [line]

    homedash.write_home(lines)
    save_tasks(data)     # only after Home.md succeeded, so the two cannot drift
    print(f"added: {key} ({args.workstream}, {args.priority}, due {args.due or 'none'})")


def cmd_set_status(args):
    _, found = homedash.read_home()
    if args.key not in found:
        sys.exit(f"no such task: {args.key}")
    before = found[args.key]["status"]
    if before == args.status:
        print(f"unchanged: {args.key} already {args.status}")
        return
    homedash.apply_change(args.key, status=args.status)
    print(f"{args.key}: {before} -> {args.status}")


def cmd_note(args):
    _, found = homedash.read_home()
    if args.key not in found:
        sys.exit(f"no such task: {args.key}")
    homedash.apply_change(args.key, note=args.text)
    print(f"{args.key}: note {'set' if args.text else 'cleared'}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="print the current board as JSON").set_defaults(fn=cmd_list)

    a = sub.add_parser("add", help="add a task to tasks.json and Home.md together")
    a.add_argument("--title", required=True)
    a.add_argument("--workstream", required=True, choices=workstreams())
    a.add_argument("--priority", required=True, choices=["high", "medium", "low"])
    a.add_argument("--detail", default="")
    a.add_argument("--due", default=None, help="YYYY-MM-DD")
    a.add_argument("--source", default="jira", choices=["jira", "email", "teams", "calendar"])
    a.add_argument("--ref", action="append", metavar="LABEL=URL")
    a.add_argument("--key", default=None, help="defaults to a slug of the title")
    a.set_defaults(fn=cmd_add)

    s = sub.add_parser("set-status", help="move a task between columns")
    s.add_argument("--key", required=True)
    s.add_argument("--status", required=True, choices=["todo", "doing", "blocked", "done"])
    s.set_defaults(fn=cmd_set_status)

    n = sub.add_parser("note", help="write a note onto a task")
    n.add_argument("--key", required=True)
    n.add_argument("--text", default="")
    n.set_defaults(fn=cmd_note)

    args = p.parse_args()
    due = getattr(args, "due", None)      # only `add` has one
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        p.error(f"--due must be YYYY-MM-DD, got {due!r}")
    args.fn(args)


if __name__ == "__main__":
    main()
