#!/usr/bin/env python3
"""Week action-point dashboard, backed by Home.md.

Home.md is the source of truth. The page reads the checkbox lines anchored with
Obsidian block ids (^task-key) and writes changes straight back to them, so
ticking in the browser and ticking in Obsidian are the same act.

    python3 homedash.py          # serve on http://127.0.0.1:8765

Task wording, due dates, priorities and Jira links come from tasks.json and are
never written back - edit those in tasks.json, edit state in Home.md or the page.
"""

import json
import os
import re
import sys
import tempfile
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent

# Defaults suit a vault laid out as <vault>/99 Meta/task-dashboard/. Override any
# of them with environment variables to use a different layout.
VAULT = Path(os.environ.get("BOARD_VAULT", HERE.parent.parent)).resolve()
HOME_MD = Path(os.environ.get("BOARD_NOTE", VAULT / "Home.md")).resolve()
PAGE = Path(os.environ.get("BOARD_PAGE", VAULT / "Week Action Points.html")).resolve()
TASKS_JSON = Path(os.environ.get("BOARD_TASKS", HERE / "tasks.json")).resolve()
PORT = int(os.environ.get("BOARD_PORT", "8765"))

SECTION_START = os.environ.get("BOARD_SECTION_START", "## This week")
SECTION_END = os.environ.get("BOARD_SECTION_END", "## Open tasks across the vault")

# Obsidian keeps whatever character sits between the brackets, so the five
# states round-trip cleanly. Anything unrecognised is treated as "todo".
# "not_my_task" is set by hand from the page (or in Obsidian with `- [-]`) when
# an item lands on the board but isn't actually the user's to do — the scheduled
# refresh must never set or clear it itself, only the person does.
MARK_TO_STATUS = {" ": "todo", "/": "doing", "!": "blocked", "x": "done", "X": "done",
                  "-": "not_my_task"}
STATUS_TO_MARK = {"todo": " ", "doing": "/", "blocked": "!", "done": "x",
                   "not_my_task": "-"}

# A task blocked longer than this needs a nudge — see _record_blocked_transition
# and build_payload's "days_blocked".
BLOCKED_WARN_DAYS = 3

# A task that has been done for longer than this moves from Done to the Archive
# lane — see _record_done_transition and build_payload's "archived". Archive is
# derived from the date, not a checkbox state, so Home.md still just says [x].
ARCHIVE_AFTER_DAYS = 7
# done_since for tasks ticked before the date was tracked: the real day is
# unknown, so they count as already archived.
DONE_DATE_UNKNOWN = "unknown"

TASK_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<mark>.)\] (?P<text>.*?)\s*\^(?P<key>[\w-]+)\s*$")
NOTE_RE = re.compile(r"^\s+- note:\s?(?P<note>.*)$")


class HomeMdError(RuntimeError):
    pass


def read_tasks():
    return json.loads(TASKS_JSON.read_text())


def write_tasks(data):
    """Replace tasks.json atomically, same trick as write_home."""
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(TASKS_JSON.parent), prefix=".tasks.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, TASKS_JSON)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_UNSET = object()


def set_task_fields(key, workstream=None, tags=None, detail=None, due=_UNSET, refs=None):
    """Update the wording-side fields (workstream, tags, detail, due, refs) for one task.

    `due` uses a sentinel rather than None so a caller can clear a due date by
    passing None explicitly.

    These live in tasks.json, not Home.md — they aren't a checkbox state, they're
    part of how the task is described. Editable from the web UI so a miscategorised
    workstream or a tag doesn't require hand-editing JSON.
    """
    data = read_tasks()
    task = next((t for t in data["tasks"] if t["key"] == key), None)
    if task is None:
        return None
    if workstream is not None:
        task["workstream"] = workstream
    if tags is not None:
        task["tags"] = tags
    if detail is not None:
        task["detail"] = detail
    if due is not _UNSET:
        task["due"] = due
    if refs is not None:
        task["refs"] = refs
    write_tasks(data)
    return task


def read_home():
    """Return (lines, {key: {...}}) parsed from the week section of Home.md."""
    if not HOME_MD.exists():
        raise HomeMdError(f"{HOME_MD} not found")
    lines = HOME_MD.read_text().split("\n")

    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(SECTION_START))
        end = next(i for i, l in enumerate(lines) if l.startswith(SECTION_END))
    except StopIteration:
        raise HomeMdError(
            f"Could not find the '{SECTION_START}' ... '{SECTION_END}' section in Home.md"
        )

    found = {}
    for i in range(start, end):
        m = TASK_RE.match(lines[i])
        if not m:
            continue
        note_lines = []
        j = i + 1
        while j < end and NOTE_RE.match(lines[j]):
            note_lines.append(NOTE_RE.match(lines[j]).group("note"))
            j += 1
        found[m.group("key")] = {
            "line": i,
            "status": MARK_TO_STATUS.get(m.group("mark"), "todo"),
            "text": m.group("text"),
            "note": "\n".join(note_lines).strip(),
            "note_lines": (i + 1, j),
        }
    return lines, found


def write_home(lines):
    """Replace Home.md atomically so a crash can never leave it half-written."""
    body = "\n".join(lines)
    fd, tmp = tempfile.mkstemp(dir=str(HOME_MD.parent), prefix=".board.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, HOME_MD)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _record_blocked_transition(key, old_status, new_status):
    """Stamp or clear tasks.json's blocked_since when status crosses into/out of blocked.

    Home.md has no room for a timestamp on a checkbox line, so this lives in
    tasks.json instead — the same file that already holds the other fields the
    person doesn't hand-edit. build_payload turns it into "days_blocked" so the
    board (and the scheduled refresh) can flag a task that's been stuck too long.
    """
    if old_status == new_status:
        return
    became_blocked = new_status == "blocked" and old_status != "blocked"
    left_blocked = old_status == "blocked" and new_status != "blocked"
    if not (became_blocked or left_blocked):
        return

    data = read_tasks()
    task = next((t for t in data["tasks"] if t["key"] == key), None)
    if task is None:
        return
    task["blocked_since"] = date.today().isoformat() if became_blocked else None
    write_tasks(data)


def _record_done_transition(key, old_status, new_status):
    """Stamp or clear tasks.json's done_since when status crosses into/out of done."""
    if old_status == new_status:
        return
    became_done = new_status == "done"
    left_done = old_status == "done"
    if not (became_done or left_done):
        return

    data = read_tasks()
    task = next((t for t in data["tasks"] if t["key"] == key), None)
    if task is None:
        return
    task["done_since"] = date.today().isoformat() if became_done else None
    write_tasks(data)


def _stamp_unseen_done(found):
    """Give a done_since to done tasks that have none — ticked in Obsidian, say.

    The board only learns about such a tick when it next reads Home.md, so the
    first day it sees the [x] is the best date available. A date or "unknown"
    already there is never overwritten.
    """
    data = read_tasks()
    today = date.today().isoformat()
    changed = False
    for t in data["tasks"]:
        entry = found.get(t["key"])
        if entry and entry["status"] == "done" and t.get("done_since") is None:
            t["done_since"] = today
            changed = True
    if changed:
        write_tasks(data)
    return data


def _days_since(iso):
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def apply_change(key, status=None, note=None):
    lines, found = read_home()
    if key not in found:
        return None
    entry = found[key]
    i = entry["line"]

    if status is not None:
        m = TASK_RE.match(lines[i])
        lines[i] = f"{m.group('indent')}- [{STATUS_TO_MARK[status]}] {m.group('text')}  ^{key}"

    if note is not None:
        note_start, note_end = entry["note_lines"]
        indent = "    "
        replacement = [f"{indent}- note: {l}" for l in note.split("\n") if l.strip()]
        lines[note_start:note_end] = replacement

    write_home(lines)
    if status is not None:
        _record_blocked_transition(key, entry["status"], status)
        _record_done_transition(key, entry["status"], status)
    _, found = read_home()
    return found.get(key)


def build_payload():
    _, found = read_home()
    meta = _stamp_unseen_done(found)

    tasks = []
    for t in meta["tasks"]:
        entry = found.get(t["key"])
        status = entry["status"] if entry else t.get("status", "todo")

        days_blocked = None
        if status == "blocked" and t.get("blocked_since"):
            try:
                since = date.fromisoformat(t["blocked_since"])
                days_blocked = (date.today() - since).days
            except ValueError:
                days_blocked = None

        done_since = t.get("done_since")
        archived = False
        if status == "done":
            if done_since == DONE_DATE_UNKNOWN:
                archived = True
            else:
                days_done = _days_since(done_since)
                archived = days_done is not None and days_done >= ARCHIVE_AFTER_DAYS

        tasks.append({
            **{k: t.get(k) for k in
               ("key", "title", "detail", "workstream", "priority", "due", "source", "refs")},
            "tags": t.get("tags") or [],
            "status": status,
            "note": entry["note"] if entry else "",
            "in_home": entry is not None,
            "blocked_since": t.get("blocked_since"),
            "days_blocked": days_blocked,
            "stale_blocked": days_blocked is not None and days_blocked > BLOCKED_WARN_DAYS,
            "done_since": done_since,
            "archived": archived,
        })

    order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(key=lambda t: ((t["due"] or "9999"), order.get(t["priority"], 9)))

    missing = [t["key"] for t in tasks if not t["in_home"]]
    return {
        "tasks": tasks,
        "meta": {k: meta[k] for k in ("week", "week_start", "week_end", "generated_from", "notes")
                 if k in meta} | {"workstreams": meta.get("workstreams", [])},
        "source": str(HOME_MD),
        "missing": missing,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {fmt % args}\n")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/tasks":
            try:
                self._json(200, build_payload())
            except HomeMdError as e:
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})

    def do_PATCH(self):
        m = re.fullmatch(r"/api/tasks/([\w-]+)", urlparse(self.path).path)
        if not m:
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return

        status = body.get("status")
        note = body.get("note")
        workstream = body.get("workstream")
        tags = body.get("tags")

        if status is not None and status not in STATUS_TO_MARK:
            self._json(400, {"error": "invalid status"})
            return
        if workstream is not None:
            allowed = read_tasks().get("workstreams") or []
            if workstream not in allowed:
                self._json(400, {"error": f"workstream must be one of: {', '.join(allowed)}"})
                return
        if tags is not None:
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                self._json(400, {"error": "tags must be a list of strings"})
                return
            tags = [t.strip() for t in tags if t.strip()][:20]
        if status is None and note is None and workstream is None and tags is None:
            self._json(400, {"error": "nothing to update"})
            return
        if note is not None:
            note = str(note)[:2000]

        key = m.group(1)

        if workstream is not None or tags is not None:
            if set_task_fields(key, workstream=workstream, tags=tags) is None:
                self._json(404, {"error": f"no such task: {key}"})
                return

        if status is not None or note is not None:
            try:
                updated = apply_change(key, status, note)
            except HomeMdError as e:
                self._json(500, {"error": str(e)})
                return
            if updated is None:
                self._json(404, {"error": f"no ^{key} anchor in Home.md"})
                return

        payload = build_payload()
        task = next((t for t in payload["tasks"] if t["key"] == key), None)
        if task is None:
            self._json(404, {"error": f"no such task: {key}"})
            return
        self._json(200, {"key": key, "status": task["status"], "note": task["note"],
                          "workstream": task["workstream"], "tags": task["tags"]})


def main():
    try:
        payload = build_payload()
    except HomeMdError as e:
        sys.exit(f"Cannot start: {e}")

    n = len(payload["tasks"])
    linked = sum(1 for t in payload["tasks"] if t["in_home"])
    print(f"Source of truth : {HOME_MD}")
    print(f"Tasks           : {linked} of {n} linked to Home.md")
    if payload["missing"]:
        print(f"  no anchor for : {', '.join(payload['missing'])}")
    print(f"Dashboard       : http://127.0.0.1:{PORT}")
    print("Ctrl+C to stop.\n")

    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
