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
python3 sync.py note --key KEY --text "..."
```

Run `list` **first**, every time. It prints what is already there. Never add
something that is on the board under different wording.

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

### When something is wrong

If the helper fails, or the state file has no task section, **stop and report it**.
Do not try to repair the files.
