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


def set_task_fields(key, workstream=None, tags=None, detail=None):
    """Update the wording-side fields (workstream, tags, detail) for one task.

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
    _, found = read_home()
    return found.get(key)


def build_payload():
    meta = json.loads(TASKS_JSON.read_text())
    _, found = read_home()

    tasks = []
    for t in meta["tasks"]:
        entry = found.get(t["key"])
        tasks.append({
            **{k: t.get(k) for k in
               ("key", "title", "detail", "workstream", "priority", "due", "source", "refs")},
            "tags": t.get("tags") or [],
            "status": entry["status"] if entry else t.get("status", "todo"),
            "note": entry["note"] if entry else "",
            "in_home": entry is not None,
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
