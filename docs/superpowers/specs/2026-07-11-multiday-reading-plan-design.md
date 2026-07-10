# Multi-day reading-plan tasks — design

## Problem

A recurring task like "Read Backend LLD notes" that actually covers 7 distinct
chapters, one per day, doesn't fit the existing `repeat` model: repeat clones
are identical copies of the same title with no per-day content, and today's
`subtasks` array (a flat checklist with no due dates, only visible in the
detail panel) has no way to surface "today's specific chapter" in the daily
task lists.

The user wants: one task per chapter, each showing on its own day under the
parent's title, each chapter's completion independently kicking off spaced
revision (reusing the existing SRS system), and the parent task
auto-completing once every chapter is done.

## Approach

Reuse the codebase's existing idiom for time-based multiplicity: represent
each day/chapter as its own **task object**, linked to a parent by an id
field — exactly how `srsId` already chains revision clones and how `repeat`
already chains recurring clones. This is deliberately *not* an extension of
the existing `subtasks` array (which has no due dates and isn't rendered
outside the detail panel) — modeling chapters as real tasks means Today,
Upcoming, Week, drag-and-drop rescheduling, Reminders sync, and the checkbox
completion flow all work with zero new rendering paths, since they already
operate on `db.tasks` filtered by `due`.

Two alternatives considered and rejected:
- **Day-tagged entries inside the existing `subtasks` array.** Would require
  new rendering machinery to pull "today's subtask" out of a task's buried
  checklist into Today/Upcoming views — a real new code path, whereas the
  linked-task approach reuses everything that already exists.
- **No real parent object, just a shared `planId` grouping key with no
  parent task.** Simpler, but there'd be nothing to "auto-mark done" — the
  user explicitly wants a real parent task that registers as a completion
  (and counts toward daily-completion stats) once the plan finishes.

## Data model

Three new fields on the task object (`newTask()` in index.html, plus the
matching SQLite columns in stride-helper.py's `db_init`/`save_state`/
`load_state`):

- `isPlanParent` (bool, default `false`) — true on the parent task once it's
  been split into a plan.
- `planId` (string|null, default `null`) — on each chapter task, the
  parent's `id`. `null` on ordinary tasks and on the parent itself.
- `planIndex` (number|null, default `null`) — the chapter's position in the
  plan (0-based), set at creation time and never recomputed. Used for
  ordering progress dots and "next chapter" links — independent of `due`,
  which can change via rescheduling.

No stored chapter count or completion count: sibling set and progress are
always derived live via `db.tasks.filter(x => x.planId === parentId)`, so
they can't drift out of sync with reality. Pre-existing tasks loaded from
before this feature simply lack these keys — `undefined` is falsy, so every
check (`if (t.planId)`, `if (t.isPlanParent)`) treats them exactly like
ordinary tasks with no migration/backfill needed (same pattern already used
for `srs`/`srsId`/`startTime`).

## Creating a plan

A new button in the detail panel, **"Split into a day-by-day plan,"**
available on any task. Opens a modal: a textarea (one chapter title per
line) and a "Skip weekends" checkbox (default off). On confirm:

1. The current task becomes the parent: `isPlanParent = true`, `due` is
   cleared to `null`, and `repeat` is cleared if set — a one-time plan and
   an ongoing recurrence are orthogonal concepts and combining them is out
   of scope (see Non-goals).
2. One child task is created per non-empty line, `title` set to exactly
   what was typed (not prefixed with the parent title — see Display,
   below). `project` is inherited from the parent. `due` is assigned
   sequentially starting from today (or the parent's prior `due`, if it had
   one), incrementing one calendar day per chapter, skipping Saturday/Sunday
   if "Skip weekends" was checked. `planIndex` is set to the line's
   position (0-based).

## Display

The parent is naturally excluded from Today/Upcoming/Week (they filter on
`due`, which the parent has none of) and from Someday (it requires
`t.someday`, which is never set here). Inbox is the one view that would
otherwise pick it up — `isInbox` already means "no due, no someday" — so
`isInbox` gains an explicit `&& !t.isPlanParent` guard. It remains visible
via search and appears in the Done list once auto-completed.

Chapter tasks appear in Today/Upcoming/Week exactly like any other task,
filtered by their own `due`. `taskRow()` gains one change: when rendering a
task with `planId` set, it prepends the parent's title to the displayed
row — **"Read Backend LLD notes — Ch.3: Concurrency."** The underlying
`t.title` stays just "Ch.3: Concurrency" so editing it in the detail panel
isn't redundant.

## Completing a chapter

All three of the following are added to `completeTask()` itself (not
scattered across call sites), so they apply uniformly whether completion
happens via the checkbox, Focus mode's "Done" button, or Reminders sync
reporting a phone-side completion:

1. Normal completion (`t.done = true`, etc. — unchanged).
2. If `t.planId` is set and `t.srs` is not already set, call the existing
   `startRevision(t)` directly (no "Worth remembering?" prompt — asking
   once per chapter would be tedious; this reuses the exact spaced-revision
   chain and clone-dedup guard fixed earlier, unmodified).
3. Check siblings: `db.tasks.filter(x => x.planId === t.planId)`. If every
   sibling is now `done`, find the parent (`db.tasks.find(x => x.id ===
   t.planId && x.isPlanParent)`) and mark it done too (`done = true,
   doneAt = Date.now()`), which is also what makes the plan's completion
   count toward daily-completion stats/streaks in the Review tab.

Unchecking the last chapter (the existing undo/toggle-off path) symmetrically
un-completes the parent, mirroring the existing repeat-undo pattern.

## Rescheduling

Editing any **open** (not-yet-done) chapter's `due` date — via drag-and-drop
in a day view or the detail panel's due-date field — shifts every **later,
still-open** sibling (`planIndex` greater than the edited chapter's, same
`planId`, `!done`) by the same number of days the edited chapter moved.
Already-done chapters are untouched, so history isn't rewritten. This is
always-on for plan chapters; no extra UI or confirmation step.

## Viewing plan progress

Opening any chapter's detail panel adds a new "Part of a plan" section:
parent title, progress dots (reusing the exact visual style already built
for SRS lineage dots in the Revise tab's "Learning pipeline"), and a
clickable list of every chapter with its status and date. Opening the
parent itself (e.g. via search) shows the same overview.

## Non-goals for v1

- Editing a plan after creation (adding, removing, or reordering chapters).
- Recurring plans (e.g. re-reading the same 7 chapters monthly).
- Per-chapter priority/estimate defaults beyond simple inheritance from the
  parent at creation time — each chapter is a fully independent, freely
  editable task after that, same as any repeat/SRS clone today.
