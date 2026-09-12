# action-points

A Claude Code skill that turns Jira, Outlook and Teams into an organised list of
what to do — grouped by customer or project, with due dates, blockers and the name
of whoever you are waiting on.

Read-only. It never sends mail, replies to anyone, or changes a ticket.

## Requirements

Two MCP connectors, both of which you probably already have:

- **Microsoft 365** — mail, calendar, Teams
- **Atlassian** — Jira

And Claude Code: the CLI, the desktop app's Code tab, or an IDE extension. If you
only use the claude.ai chat window, this skill will not appear — use the plain
prompt instead (see *Without installing* below).

## Install

```
/plugin marketplace add <this repo url>
/plugin install action-points
```

Or, without the plugin machinery, copy the skill folder:

```
cp -r skills/action-points ~/.claude/skills/
```

## Use

Ask for it in your own words — "what's on my plate this week?", "catch me up after
my week off" — or invoke it directly:

```
/action-points
```

## The workflow

The problem it solves is that work arrives in three places and none of them agrees
with the others. A ticket says one thing, the thread above it says another, and the
commitment you actually made is buried in a chat message from Tuesday.

Each run does the same four things:

**1. Gather.** Your open tickets, the mail from the window, the messages you sent
and received, and the week's calendar — including who is away, because a task
assigned to someone on holiday is already blocked.

**2. Separate the real work from the noise.** Two distinctions carry most of the
value. A ticket waiting on *you* is work; a ticket waiting on the *customer* is a
chase at most — queues are often two-thirds the latter. And anything you promised
in writing is a commitment, whether or not a ticket exists for it.

**3. Group by workstream.** By customer or project, never by which tool it came
from. Nobody thinks in inboxes. Within a group, order by due date.

**4. Say what it could not see.** Rate limits, channels not searched, mailboxes it
cannot reach. The output is a strong first draft, and it says so.

Run it ad hoc when you need it, or on a schedule so the list is waiting for you.
With the dashboard attached, each run also ticks off what got finished and adds
what is new, so the board stays current without anyone maintaining it by hand.

## Run it on a schedule

In the Claude desktop app, ask Claude to make it a scheduled task.

Two patterns work well, depending on how you plan:

**Three times a day** — start of your working day, middle, end. The first run tells
you what landed overnight, the last tells you what did not get done.

```
0 9,13,18 * * 1-5     09:00, 13:00, 18:00 on weekdays
```

**Once a week** — Friday afternoon, planning the week ahead.

```
0 16 * * 5            16:00 on Fridays
```

The pattern for the daily version is `0 <start>,<middle>,<end> * * 1-5`. Change the
hours to match your own day, and add `,6` for Saturdays.

**Cron runs in your machine's local time**, not UTC and not your team's timezone.
If you work hours that differ from your computer's clock — a shift that starts in
another timezone, or a laptop still set to where you used to live — convert the
hours first, or fix the machine clock. This is the single most common way these
schedules end up firing at the wrong time.

Two more things:

- **The app must be open.** A run due while Claude is closed happens at next launch.
  Running three times a day means a missed one rarely matters.
- **Click "Run now" once** after creating the task. The first run asks permission
  for the connectors; approving there stops later runs stalling on a prompt.

## The dashboard

By default the skill reports and stops. `dashboard/` turns that into a Kanban board
that reads and writes a markdown note, so ticking a card and ticking a checkbox in
your notes are the same act.

```
dashboard/homedash.py   local server + read/write API
dashboard/sync.py       safe add / set-status / note, used by the scheduled task
dashboard/board.html    the board: To do, Doing, Blocked, Done
example/                a working note and tasks.json to try it against
```

Try the example:

```bash
BOARD_NOTE="$PWD/example/Notes.md" \
BOARD_TASKS="$PWD/example/tasks.json" \
BOARD_PAGE="$PWD/dashboard/board.html" \
BOARD_SECTION_END="## Open tasks" \
python3 dashboard/homedash.py
```

Then open <http://127.0.0.1:8765>.

### How it joins up

Two files, joined by a key. `tasks.json` holds the wording — title, due date,
priority, ticket links. Your note holds the state, as ordinary checkboxes ending in
an Obsidian block id:

```markdown
- [ ] Write the rollout plan — [PROJ-101](...)  ^example-write-the-plan
```

States are `[ ]` to do, `[/]` doing, `[!]` blocked, `[x]` done. Only `[x]` is
standard markdown; the other two are stored faithfully but may render as a plain
empty box depending on your Obsidian theme.

Point it at your own notes with the `BOARD_*` variables above.
`BOARD_SECTION_START` and `BOARD_SECTION_END` mark the two headings it works
between — it never touches anything outside them.

### Rules that matter

**Only mark something done on clear evidence.** An unattended run that wrongly ticks
things is worse than one that leaves them open.

**Do not hand-edit `tasks.json` and the note separately.** Use `sync.py` — it writes
both together, or neither.

**Your real `tasks.json` is gitignored, deliberately.** A live board holds customer
names, ticket numbers and internal detail. Keep it out of any repo you share.

See `skills/action-points/reference.md` for the full command list.

## Without installing

The skill is just instructions. If someone cannot install it, they can paste
`skills/action-points/SKILL.md` into a chat and get most of the value — they will
miss the connector notes in `reference.md`, which is where the sharp edges are
documented.

## What it will not see

- Teams **channel** posts. Chats only.
- Mailboxes other than your own.
- Jira issues where you are a watcher or reporter but not the assignee.

Treat the output as a strong first draft of your week, not a complete record.
