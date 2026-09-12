---
name: action-points
description: Turn Jira, Outlook and Teams into an organised list of what to do — grouped by workstream, with due dates, blockers and named owners. Use when asked to plan the day or week, work out what is on my plate, review tickets and mail together, catch up after time off, or refresh a task board.
---

# Action points

Pull from Jira, Outlook and Teams, then organise what you find into things the user
can act on.

Needs two connectors: **Microsoft 365** (mail, calendar, Teams) and **Atlassian**
(Jira). Work **read-only**. Never send mail, never reply to anyone, never change a
Jira ticket.

**Read `reference.md` before you start gathering.** It holds the connector traps
that quietly produce a wrong answer rather than an error.

## 1. Gather

Default window: today and yesterday, planning the week ahead. If the user asked for
a different window, use theirs.

**Jira** — get the account and cloud id first, then search:

```
assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC
```

Ask only for these fields: `key, summary, status, priority, issuetype, updated,
duedate, project`.

**Outlook** — mail received in the window, newest first. Then the calendar for the
coming week: meetings the user organises, and every all-day out-of-office or public
holiday. Those decide what is actually possible.

**Teams** — messages in the window. Look hardest for messages where the user states
their own commitments — "action point on me", "I'll do X", "I'll share the steps" —
and for anything marked high importance.

## 2. Filter

Keep an item only if the user has to **do** something, **decide** something, or
**hit a date**.

Drop newsletters, digests, meeting accept/decline notices, and automated alerts.

## 3. Organise

Group by **workstream** — the customer or project — not by which tool it came from.
A person thinks in customers, not in inboxes. Order each group by due date.

For every item give:

- A short title in plain words. Say the thing to do. One idea per title.
- One or two plain sentences: why it matters, or what is blocking it.
- The due date, if there is one.
- A priority: high, medium or low.
- The Jira key as a link, if there is one.
- If it is blocked, the **name** of the person. Never "the team".

## 4. Rules

- Never invent due dates, ticket numbers or names. If a date is implied rather than
  stated, say that it is implied.
- Where the user already committed to something in writing, quote their own words
  back to them.
- Say plainly what you could not see: rate limits, channels not searched, mailboxes
  without access. Never imply full coverage.
- Flag anything where the ball has been in the user's court for several days.
- Write short sentences. One idea per sentence.
- Finish with the two or three things to do first, and why those.

## 5. Board mode

If the user names a board directory — one holding `sync.py` and `tasks.json` — then
maintain that board instead of only reporting: tick off what is finished, add what
is new. See **Board mode** in `reference.md` for the commands and the rules about
evidence.

Without a board directory, report and stop. Do not write to the user's files
uninvited.
