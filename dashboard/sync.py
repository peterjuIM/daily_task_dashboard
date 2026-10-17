#!/usr/bin/env python3
"""Safe edits to the task list, for use by the scheduled task.

The board joins two files: tasks.json holds the wording, Home.md holds the state.
An item only appears if it exists in BOTH with the same key. Hand-editing two
files in step is exactly the sort of thing an unattended run gets wrong, so do it
through here instead.

    python3 sync.py list                      # what is on the board now, as JSON
    python3 sync.py add --title "..." --workstream "..." [--tag "..."] [...]
    python3 sync.py set-status --key KEY --status done
    python3 sync.py note --key KEY --text "..."            # appends a line
    python3 sync.py note --key KEY --text "..." --replace  # overwrites every note line
    python3 sync.py edit --key KEY [--workstream "..."] [--add-tag "..."] [--remove-tag "..."]
                                   [--detail "..."] [--due YYYY-MM-DD|none] [--add-ref LABEL=URL]
    python3 sync.py week                      # does the board cover the current week?
    python3 sync.py week --roll               # if not, move it to the current week
    python3 sync.py notice add --title "..." --text "..." [--issued-by "..."] [--since YYYY-MM-DD]
    python3 sync.py notice retire --id ID --recorded-in "where it is written down now"
    python3 sync.py notice list
    python3 sync.py away add --who "..." --from YYYY-MM-DD --to YYYY-MM-DD [--note "..."]
    python3 sync.py away remove --id ID
    python3 sync.py away list

Important notices and who's away sit at the top of the board and are not tied
to a week. A notice stays until someone retires it, and retiring needs
--recorded-in: where the rule is written down now. An away-entry shows until the
day after its last day; the week roll moves ended ones to past_away.

The board is labelled with a week (tasks.json's week/week_start/week_end, and the
"## This week — ..." heading in Home.md). Nothing moves that label on its own, so
`list` reports `week_check` and warns when it is stale, and `week --roll` brings
it up to the current ISO week. Rolling only relabels: every task, status and note
stays where it is. Last week's "worth knowing" notes are kept under past_notes.

`note` APPENDS by default. Earlier notes are history (evidence for why a task was
ticked, what was promised, when) and an unattended run must never wipe them by
accident. Pass --replace only when you mean to rewrite them all; --replace with
an empty --text clears the note.

Tags are free text, not a fixed list — anyone (this script, the board's web UI) can
put any word on a task. There is no registry of "valid" tags to keep in step;
whatever string is on a task is the tag.

Every command prints what it did. `add` is idempotent on the key, so re-running a
sync does not create duplicates.

`set-status --status blocked` stamps the task with today's date; `list` then
reports `days_blocked` and `stale_blocked` (true past 3 days) so a task that's
been stuck doesn't quietly sit there.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, timedelta

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


def actual_week(today=None):
    """The current ISO week as (label, monday, friday), e.g. ("2026-W42", 12 Oct, 16 Oct)."""
    today = today or date.today()
    year, week, weekday = today.isocalendar()
    monday = today - timedelta(days=weekday - 1)
    return f"{year}-W{week:02d}", monday, monday + timedelta(days=4)


def week_check(data=None):
    data = data or homedash.read_tasks()
    label, monday, friday = actual_week()
    return {
        "board": data.get("week"),
        "board_start": data.get("week_start"),
        "board_end": data.get("week_end"),
        "actual": label,
        "actual_start": monday.isoformat(),
        "actual_end": friday.isoformat(),
        "current": data.get("week") == label,
    }


def week_heading(label, monday, friday):
    """Home.md's section heading, e.g. '## This week — 12–16 Oct (2026-W42)'."""
    if monday.month == friday.month:
        span = f"{monday.day}–{friday.day} {friday:%b}"
    else:
        span = f"{monday.day} {monday:%b}–{friday.day} {friday:%b}"
    return f"{homedash.SECTION_START} — {span} ({label})"


def cmd_list(args):
    payload = homedash.build_payload()
    rows = [{k: t[k] for k in
             ("key", "title", "status", "workstream", "priority", "due", "tags", "refs",
              "days_blocked", "stale_blocked")}
            for t in payload["tasks"]]
    check = week_check()
    if not check["current"]:
        print(f"warning: board is labelled {check['board']} but this is {check['actual']} "
              f"— run `sync.py week --roll`", file=sys.stderr)
    print(json.dumps({"week": payload["meta"]["week"], "week_check": check,
                      "notices": payload["meta"]["notices"], "away": payload["meta"]["away"],
                      "tasks": rows},
                     ensure_ascii=False, indent=2))


def cmd_week(args):
    data = homedash.read_tasks()
    check = week_check(data)
    if not args.roll or check["current"]:
        print(json.dumps(check, indent=2))
        if args.roll:
            print(f"unchanged: board already covers {check['actual']}")
        return

    label, monday, friday = actual_week()

    # Home.md first: if its section heading can't be found, stop before touching
    # tasks.json, so the two never disagree about which week it is.
    lines = homedash.HOME_MD.read_text().split("\n")
    heading = next((i for i, l in enumerate(lines) if l.startswith(homedash.SECTION_START)), None)
    if heading is None:
        sys.exit(f"Could not find the '{homedash.SECTION_START}' heading in Home.md — aborting without writing.")
    old_heading = lines[heading]
    lines[heading] = week_heading(label, monday, friday)
    homedash.write_home(lines)

    # "Worth knowing this week" notes belong to the old week; keep them as
    # history rather than deleting them or showing them as current.
    old_week = data.get("week")
    if data.get("notes"):
        data.setdefault("past_notes", {})[old_week or "unknown"] = data["notes"]
    data["notes"] = []
    # Away-entries that ended before the new week are history; keep them, out of sight.
    ended = [a for a in data.get("away", []) if a["to"] < monday.isoformat()]
    if ended:
        data.setdefault("past_away", []).extend(ended)
        data["away"] = [a for a in data["away"] if a not in ended]
    # Notices are deliberately untouched: only a person retires one.
    data["week"] = label
    data["week_start"] = monday.isoformat()
    data["week_end"] = friday.isoformat()
    data["generated_from"] = f"Rolled forward from {old_week} on {date.today().isoformat()}"
    homedash.write_tasks(data)

    print(f"rolled: {old_week} -> {label} ({monday.isoformat()} to {friday.isoformat()})")
    print(f"Home.md heading: {old_heading!r} -> {lines[heading]!r}")
    if old_week in data.get("past_notes", {}):
        print(f"kept {len(data['past_notes'][old_week])} 'worth knowing' note(s) from {old_week} under past_notes")


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
        # Step over task lines AND their indented "- note:" lines, so the new
        # task never lands between an existing task and its notes (which would
        # silently re-attach those notes to the new task).
        while insert < end and (lines[insert].startswith("- [")
                                or homedash.NOTE_RE.match(lines[insert])
                                or not lines[insert].strip()):
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
    existing = found[args.key].get("note", "")
    text = args.text.strip()

    if args.replace:
        homedash.apply_change(args.key, note=text)
        print(f"{args.key}: note {'replaced' if text else 'cleared'}")
        return
    if not text:
        sys.exit("--text is empty; use --replace --text '' to clear a note")
    if text in existing.split("\n"):
        print(f"unchanged: {args.key} already has that note")
        return
    combined = f"{existing}\n{text}" if existing else text
    homedash.apply_change(args.key, note=combined)
    print(f"{args.key}: note appended ({len(combined.splitlines())} line(s) now)")


def cmd_edit(args):
    """Correct the wording-side fields (workstream, tags, detail, due, refs) on an existing task.

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

    due = homedash._UNSET
    if args.due is not None:
        due = None if args.due.lower() == "none" else args.due
        if due != task.get("due"):
            changed.append(f"due: {task.get('due') or 'none'} -> {due or 'none'}")
        else:
            due = homedash._UNSET

    refs = list(task.get("refs") or [])
    for raw in args.add_ref or []:
        if "=" not in raw:
            sys.exit(f"--add-ref must be LABEL=URL, got {raw!r}")
        label, url = raw.split("=", 1)
        if not any(r["url"] == url for r in refs):
            refs.append({"label": label, "url": url})
            changed.append(f"ref added: {label}")

    if not changed:
        print(f"unchanged: {args.key}")
        return

    homedash.set_task_fields(
        args.key,
        workstream=args.workstream if args.workstream is not None else None,
        tags=tags,
        detail=args.detail,
        due=due,
        refs=refs if refs != (task.get("refs") or []) else None,
    )
    print(f"{args.key}: " + "; ".join(changed))


def cmd_notice(args):
    try:
        if args.action == "add":
            n, new = homedash.add_notice(args.title, args.text, issued_by=args.issued_by,
                                         since=args.since, source=args.source, notice_id=args.id)
            print(f"{'added' if new else 'skip: already exists'}: notice {n['id']}")
        elif args.action == "retire":
            n, changed = homedash.retire_notice(args.id, args.recorded_in)
            print(f"{'retired' if changed else 'unchanged: already retired'}: notice {n['id']} "
                  f"(recorded in: {n['recorded_in']})")
        else:
            print(json.dumps(homedash.active_notices(homedash.read_tasks()), ensure_ascii=False, indent=2))
    except homedash.BoardError as e:
        sys.exit(str(e))


def cmd_away(args):
    try:
        if args.action == "add":
            a, new = homedash.add_away(args.who, args.start, args.end, note=args.note, source=args.source)
            print(f"{'added' if new else 'skip: already exists'}: away {a['id']}")
        elif args.action == "remove":
            a = homedash.remove_away(args.id)
            print(f"removed: away {a['id']}")
        else:
            print(json.dumps(homedash.current_away(homedash.read_tasks()), ensure_ascii=False, indent=2))
    except homedash.BoardError as e:
        sys.exit(str(e))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="print the current board as JSON").set_defaults(fn=cmd_list)

    w = sub.add_parser("week", help="check whether the board covers the current week")
    w.add_argument("--roll", action="store_true",
                   help="if it doesn't, relabel the board to the current week (tasks are untouched)")
    w.set_defaults(fn=cmd_week)

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

    n = sub.add_parser("note", help="append a note line to a task (--replace to overwrite)")
    n.add_argument("--key", required=True)
    n.add_argument("--text", default="")
    n.add_argument("--replace", action="store_true",
                   help="overwrite all existing note lines instead of appending")
    n.set_defaults(fn=cmd_note)

    e = sub.add_parser("edit", help="correct workstream, tags, detail, due or refs on an existing task")
    e.add_argument("--key", required=True)
    e.add_argument("--workstream", default=None)
    e.add_argument("--add-tag", action="append", help="free text, repeatable")
    e.add_argument("--remove-tag", action="append", help="free text, repeatable")
    e.add_argument("--detail", default=None)
    e.add_argument("--due", default=None, help="YYYY-MM-DD, or 'none' to clear")
    e.add_argument("--add-ref", action="append", metavar="LABEL=URL",
                   help="attach a link (e.g. a Jira key); repeatable")
    e.set_defaults(fn=cmd_edit)

    no = sub.add_parser("notice", help="important notices pinned to the top of the board")
    nos = no.add_subparsers(dest="action", required=True)
    x = nos.add_parser("add", help="pin a notice (idempotent on id)")
    x.add_argument("--title", required=True)
    x.add_argument("--text", default="")
    x.add_argument("--issued-by", default="")
    x.add_argument("--since", default=None, help="YYYY-MM-DD, defaults to today")
    x.add_argument("--source", default="", help="where it came from, e.g. 'Teams, 11 Sep'")
    x.add_argument("--id", default=None, help="defaults to a slug of the title")
    x = nos.add_parser("retire", help="take a notice off once it is recorded somewhere")
    x.add_argument("--id", required=True)
    x.add_argument("--recorded-in", required=True, help="where the rule is written down now")
    nos.add_parser("list", help="active notices as JSON")
    no.set_defaults(fn=cmd_notice)

    aw = sub.add_parser("away", help="who is out of office, shown at the top of the board")
    aws = aw.add_subparsers(dest="action", required=True)
    x = aws.add_parser("add", help="record someone away (idempotent on who+dates)")
    x.add_argument("--who", required=True)
    x.add_argument("--from", dest="start", required=True, help="first day away, YYYY-MM-DD")
    x.add_argument("--to", dest="end", required=True, help="last day away, YYYY-MM-DD")
    x.add_argument("--note", default="", help="e.g. 'public holiday', 'back Mon 19'")
    x.add_argument("--source", default="calendar")
    x = aws.add_parser("remove", help="delete an entry added by mistake or a cancelled leave")
    x.add_argument("--id", required=True)
    aws.add_parser("list", help="current and upcoming entries as JSON")
    aw.set_defaults(fn=cmd_away)

    args = p.parse_args()
    due = getattr(args, "due", None)      # `add` and `edit` have one
    if due and due.lower() != "none" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        p.error(f"--due must be YYYY-MM-DD, got {due!r}")
    args.fn(args)


if __name__ == "__main__":
    main()
