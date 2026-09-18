#!/usr/bin/env python3
"""Safe edits to the task list, for use by the scheduled task.

The board joins two files: tasks.json holds the wording, Home.md holds the state.
An item only appears if it exists in BOTH with the same key. Hand-editing two
files in step is exactly the sort of thing an unattended run gets wrong, so do it
through here instead.

    python3 sync.py list                      # what is on the board now, as JSON
    python3 sync.py add --title "..." --workstream "..." [--tag "..."] [...]
    python3 sync.py set-status --key KEY --status done
    python3 sync.py note --key KEY --text "..."
    python3 sync.py edit --key KEY [--workstream "..."] [--add-tag "..."] [--remove-tag "..."]

Tags are free text, not a fixed list — anyone (this script, the board's web UI) can
put any word on a task. There is no registry of "valid" tags to keep in step;
whatever string is on a task is the tag.

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


def cmd_list(args):
    payload = homedash.build_payload()
    rows = [{k: t[k] for k in
             ("key", "title", "status", "workstream", "priority", "due", "tags", "refs")}
            for t in payload["tasks"]]
    print(json.dumps({"week": payload["meta"]["week"], "tasks": rows}, ensure_ascii=False, indent=2))


def cmd_add(args):
    data = homedash.read_tasks()
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
        "tags": list(dict.fromkeys(args.tag or [])),   # de-duplicate, keep order
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
    homedash.write_tasks(data)  # only after Home.md succeeded, so the two cannot drift
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


def cmd_edit(args):
    """Correct the wording-side fields (workstream, tags, detail) on an existing task.

    Unlike `add`, this can change a task already on the board — for when the
    workstream was guessed wrong, a tag needs adding or removing, or the detail
    text goes stale after a recategorisation. Same tasks.json fields the web UI
    edits, through the same atomic write.
    """
    data = homedash.read_tasks()
    task = next((t for t in data["tasks"] if t["key"] == args.key), None)
    if task is None:
        sys.exit(f"no such task: {args.key}")

    if args.workstream is not None:
        allowed = data.get("workstreams") or []
        if allowed and args.workstream not in allowed:
            sys.exit(f"--workstream must be one of: {', '.join(allowed)}")

    tags = list(task.get("tags") or [])
    for t in args.add_tag or []:
        if t not in tags:
            tags.append(t)
    for t in args.remove_tag or []:
        tags = [x for x in tags if x != t]

    changed = []
    if args.workstream is not None and args.workstream != task["workstream"]:
        changed.append(f"workstream: {task['workstream']} -> {args.workstream}")
    if tags != (task.get("tags") or []):
        changed.append(f"tags: {task.get('tags') or []} -> {tags}")
    if args.detail is not None and args.detail != task.get("detail", ""):
        changed.append("detail: updated")

    if not changed:
        print(f"unchanged: {args.key}")
        return

    homedash.set_task_fields(
        args.key,
        workstream=args.workstream if args.workstream is not None else None,
        tags=tags,
        detail=args.detail,
    )
    print(f"{args.key}: " + "; ".join(changed))


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
    a.add_argument("--tag", action="append", help="free text, repeatable")
    a.add_argument("--key", default=None, help="defaults to a slug of the title")
    a.set_defaults(fn=cmd_add)

    s = sub.add_parser("set-status", help="move a task between columns")
    s.add_argument("--key", required=True)
    s.add_argument("--status", required=True,
                   choices=["todo", "doing", "blocked", "done", "not_my_task"])
    s.set_defaults(fn=cmd_set_status)

    n = sub.add_parser("note", help="write a note onto a task")
    n.add_argument("--key", required=True)
    n.add_argument("--text", default="")
    n.set_defaults(fn=cmd_note)

    e = sub.add_parser("edit", help="correct workstream, tags and/or detail on an existing task")
    e.add_argument("--key", required=True)
    e.add_argument("--workstream", default=None)
    e.add_argument("--add-tag", action="append", help="free text, repeatable")
    e.add_argument("--remove-tag", action="append", help="free text, repeatable")
    e.add_argument("--detail", default=None)
    e.set_defaults(fn=cmd_edit)

    args = p.parse_args()
    due = getattr(args, "due", None)      # only `add` has one
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        p.error(f"--due must be YYYY-MM-DD, got {due!r}")
    args.fn(args)


if __name__ == "__main__":
    main()
