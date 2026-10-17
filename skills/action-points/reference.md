# Reference

Connector behaviour that produces a *wrong* answer rather than an error, and the
rules for board mode. All of it was learned the hard way.

## Jira

**Ask for specific fields.** The default field set on a search of 30-plus issues is
large enough to be truncated before you see it. Request only what you need:
`key, summary, status, priority, issuetype, updated, duedate, project`.

**"Awaiting customer" is not the same as "awaiting internal".** This is the single
most useful distinction in the whole list:

- A ticket in an *internal* response state is a real action. The ball is the user's.
- A ticket *awaiting customer response* is a chase at most. Do not present it as
  work to do.

A queue can easily be two-thirds customer-waiting. Say so — "21 of 38 are waiting on
customers" is more useful than 38 undifferentiated rows.

**Only issues assigned to the user appear.** Issues where they are a watcher,
reporter or commenter will not. Mention this if the user seems to expect otherwise.

**A third state: "Feature / Change / Defect".** This status usually means the
ticket has been forwarded to another team (development, product) to pick up —
it is a wait, just not on the customer. It does **not** mean "nobody is chasing
this, park it." Keep the ticket in its real customer/project workstream — moving
it to a generic bucket erases exactly the context (which customer, which product
area) that made it findable. Where you're confident it's genuinely sitting with
another team, add the tag `Feature/Defect/Request` (see **Tags** below) instead
of changing its workstream. Don't tag it on every ticket in this status by
reflex — if a ticket has clearly gone stale with nobody on either side looking at
it, leave it untagged and say so.

## Outlook

**Search results are summaries, and they truncate.** A status thread with a table of
issues, owners and due dates will show you the first two rows and cut off exactly
where the substance starts. When a thread looks like it carries a list, open the
full message body.

**Read the calendar for out-of-office and holidays.** All-day entries from
colleagues are not noise — they decide whether a plan is possible at all. A task
assigned to someone who is away for the week is already blocked, and the user should
hear that now rather than on Wednesday.

**Only the user's own mailbox is searched** unless they have delegate access to
another and name it.

## Teams

**Coverage is partial, and it fails quietly.** A dated search scans a bounded number
of recent chats and stops on rate limits. It does **not** read channel posts at all.

Always state what was covered. "Reached 28 of 50 chats before a rate limit, and
channel posts are not included" is honest. Silence implies completeness you do not
have.

**The user's own messages are the richest source.** People write their commitments
down in chat and then forget them. Search hardest for first-person phrasing:
"action point on me", "I'll do X", "I'll share the steps", "leave it with me".

## Board mode

A board is two files that must stay in step: `tasks.json` holds the wording,
`Home.md` (or equivalent) holds the state. An item exists only if it is in **both**
with the same key.

**Never edit those files directly.** Use the helper in the board directory:

```
python3 sync.py list
python3 sync.py add --title "..." --workstream "..." --priority high|medium|low \
    --detail "..." --due YYYY-MM-DD --source jira|email|teams|calendar --ref LABEL=URL
python3 sync.py set-status --key KEY --status todo|doing|blocked|done
python3 sync.py note --key KEY --text "..."     # appends one line
python3 sync.py week --roll                     # relabel the board to the current week
```

Run `list` **first**, every time. It prints what is already there. Never add
something that is on the board under different wording.

### Keeping the week current

The board is labelled with a week, and nothing moves that label on its own.
`list` returns a `week_check` block; when `week_check.current` is false, run
`python3 sync.py week --roll` straight after `list`, before anything else.

Rolling only relabels: tasks, statuses and notes stay exactly where they are,
and last week's "worth knowing" notes are kept under `past_notes` rather than
deleted. Important notices are left alone, and away-entries that ended before
the new week move to `past_away`. It is safe to run every time — on a current
board it changes nothing. Say in the report that you rolled the week, and from
which week.

### Who's away

The top of the board lists who is out, grouped into this week, next week and
later. It is not tied to a week: an entry shows until the day after its last
day. Keep it filled on **every** run:

```
python3 sync.py away add --who "Full Name" --from YYYY-MM-DD --to YYYY-MM-DD --note "back Mon 19 · cover: Alex"
python3 sync.py away list
```

- Add every all-day out-of-office, leave or public holiday in the calendar
  window, including the user's own (their name followed by "(you)"). Add
  out-of-office auto-replies too, using the return date they state.
- `--to` is the **last day away**, not the return day. A calendar all-day event
  ending at 00:00 on the 19th means the last day is the 18th.
- A team-wide holiday is one entry ("Pune office", note "Public holiday").
- `add` is idempotent on who + dates, so re-adding is harmless. If the dates
  change, add the new range and say in the report that the old one may need
  removing. Never run `away remove` yourself; the person does that from the board.

### Important notices

A notice is a standing rule, not a task: something to keep following until it
is withdrawn ("tell customers yourself when cloud restarts their scoring",
"route Customer X tickets through Sam while I'm away"). Notices sit pinned at
the very top of the board, every week, until the person takes one off.

```
python3 sync.py notice add --title "..." --text "the rule in plain words" \
    --issued-by "Full Name" --since YYYY-MM-DD --source "Teams, 11 Sep"
python3 sync.py notice list
```

- Add one only when someone states a standing rule or process change in
  writing. Quote their wording in `--text`. A one-off request is a task, not a
  notice.
- **Never retire a notice.** Taking one off is the person's call, made from the
  board's "Recorded → take off" button. It requires saying where the rule is now
  recorded (Important Notices.md, a wiki page, the team runbook), so nothing drops
  off without being written down. Like `not_my_task`, this is never done by an
  unattended run.
- List the active notices in one line at the top of the report, so the person
  sees them whether or not they open the board.

`set-status --status blocked` stamps the day the task became blocked. `list`
then reports `days_blocked`, and `stale_blocked: true` once that passes 3 days.
List every stale blocked task in the report, with the name of the person it is
waiting on — that is exactly the "ball has been in someone's court for days"
signal the user needs.

### Not my task

A task can carry the status `not_my_task`. The person sets this by hand from the
board's UI — a `→ Not my task` button on the card — when something landed on the
board but genuinely isn't theirs to do. It is never something this skill sets or
clears on its own.

Leave any `not_my_task` item exactly as it is: don't change its status, don't
re-evaluate whether it's "really" done or still open, and don't fold its content
into another task. It won't come back as a duplicate on its own — `sync.py add`
is idempotent on the key — so there is nothing to do here except leave it alone.

### Notes are a log — append, never overwrite

`note` **appends** a line to whatever notes the task already has. Earlier notes
are evidence: why something was ticked, what the user promised, what changed on
which day. Start each note with the date (`15 Oct: ...`) so the log reads in
order. Re-sending the exact same line is a no-op, so a re-run does not pile up
duplicates.

`--replace` overwrites every note line on the task. An unattended run should
almost never need it. Use it only to repair a note you yourself just wrote
wrongly in this same run, and say so in the report.

### Backlog category

`Backlog` is a workstream for Jira tickets that sit in a backlog or
feature-request state — **not** a catch-all for anything that doesn't fit.
A ticket belongs there when its Jira status says it has left support's hands
for good: a status such as "Backlog", "Feature Request", "Forward to
development" or "On-hold" pending a product decision, with no customer or
internal reply due.

- A ticket in **"Feature / Change / Defect"** is *not* Backlog by default. It
  stays in its customer/project workstream with the `Feature/Defect/Request`
  tag (see **Tags**), because someone is still chasing it.
- Move a ticket to Backlog only when the Jira status itself is a backlog /
  feature-request state, or the ticket has clearly been parked with no date and
  no one waiting on it. Say in the report which ones you moved and why.
- Never move a ticket out of Backlog just because it is old. Move it back to its
  customer workstream only when it comes alive again (a new customer comment, a
  status change back into an active state).
- Backlog items are low priority unless a date or a customer escalation says
  otherwise.

If the user's board has no `Backlog` workstream, don't invent one — keep the
ticket in its customer workstream with the tag.

### Marking things done

Only on clear evidence:

- The linked Jira issue is now in a **Done** status category, or
- Mail or Teams shows the user did the thing — they sent the email, they posted the
  answer on the thread.

Record the evidence in a note when you tick something.

A ticket moving to "Awaiting Customer Response" is **not** done. Neither is a
promising-looking discussion.

**If unsure, leave it open and say so.** An unattended run that wrongly ticks
something is worse than one that leaves it. The user can tick a box in a second;
they cannot recover work they never knew was still outstanding.

### Tags

Tasks carry a `tags` list — free text, not a fixed vocabulary. There's no
registry to keep in step; whatever string is on a task is the tag. Anyone can
add one: this script, the board's web UI (each card has a "+ tag" control and an
× on each existing tag when expanded), or you.

Use the tag `Feature/Defect/Request` for a ticket whose Jira status is
"Feature / Change / Defect" **and** you're confident it's genuinely sitting with
another team (see **A third state** under Jira above) — not as a blanket label
for every ticket in that status. Keep the task in its real customer/project
workstream; the tag carries the "waiting on someone else" signal, the workstream
still says who the work is for.

```
python3 sync.py add --title "..." --workstream "..." --priority low --tag "Feature/Defect/Request" [...]
python3 sync.py edit --key KEY --add-tag "Feature/Defect/Request"
python3 sync.py edit --key KEY --remove-tag "..."
```

### Correcting workstream, tags, detail, due date or links on an existing task

`add` only creates — it never edits an item already on the board. For a
miscategorised workstream, a tag to add or remove, detail text that's gone
stale, a deadline that moved, or a Jira key that turned up later, use `edit`:

```
python3 sync.py edit --key KEY --workstream "..."
python3 sync.py edit --key KEY --add-tag "..." --remove-tag "..."
python3 sync.py edit --key KEY --detail "..."
python3 sync.py edit --key KEY --due YYYY-MM-DD      # or --due none to clear
python3 sync.py edit --key KEY --add-ref "CSSAS-123=https://.../browse/CSSAS-123"
```

Only move a due date on a **stated** new date (a customer cutoff, a rescheduled
meeting). Record where the new date came from in a note. When a task gains a
Jira ticket after it was added, attach it with `--add-ref` rather than adding a
second task for the same work.

This writes straight to `tasks.json` through the same atomic write `add` uses —
never hand-edit that file. `Home.md` never stores workstream, tags, detail, due
or refs (only the checkbox mark, the title and notes), so editing them through
`edit` can't drift the two files out of step.

If you get a workstream wrong, don't be shy about using `edit` to fix it once
you have better evidence (a project label, a customer name in the ticket) —
that's exactly what it's for. When you're not confident which workstream a
ticket belongs to, say so in your report rather than guessing; the person can
always fix it from the board themselves.

### When something is wrong

If the helper fails, or the state file has no task section, **stop and report it**.
Do not try to repair the files.
