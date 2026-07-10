# Multi-day Reading Plan Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a task be split into a day-by-day plan (one chapter per day), where each day's chapter is its own linked task with its own spaced-revision chain, and the parent auto-completes once every chapter is done.

**Architecture:** Each chapter becomes a real task object linked to its parent via `planId`/`planIndex`, following the exact pattern already used for `srsId` revision chains and `repeat` clones — no new rendering machinery, since Today/Upcoming/Week/drag-and-drop/Reminders sync already work by filtering `db.tasks` on `due`.

**Tech Stack:** Vanilla JS in `index.html` (no framework, no build step), Python 3 stdlib `stride-helper.py` (SQLite persistence).

## Global Constraints

- No new dependencies — stdlib Python only, no npm packages, no build step (per CLAUDE.md).
- `stride.db*` holds real user data — never commit it, and treat direct sqlite3 edits to the user's live `stride.db` (if any are needed during manual verification) with the same care used in the earlier bug-fix session (inspect before writing, use transactions).
- **Never POST to the running helper's live `/state` endpoint as part of a verification step.** `save_state()` deletes and fully replaces the `tasks`/`habits`/`projects` tables from whatever payload it's given — it is not additive. A verification POST containing only test rows silently destroys all real data (this happened once during this plan's execution and required restoring from an out-of-date backup; see the fixed version of Task 2's Step 5 for the safe pattern: import `save_state`/`load_state` directly and redirect `DB_PATH` to a throwaway temp file). Any check that needs to exercise `stride-helper.py`'s persistence code must run against an isolated scratch database, never against `stride.db` or the live `/state` endpoint.
- This repo has **no automated test suite, linter, or build pipeline** (per CLAUDE.md). Every task's verification step is therefore a concrete manual procedure — a Node one-liner to catch syntax errors immediately (fast, catches typos before touching a browser), followed by exercising the actual behavior in a running browser (per the project's own `verify` skill convention) or a direct `sqlite3` inspection for the Python-side task. This is the adaptation of red/green/commit to a project that has deliberately stayed dependency-free.
- Adding a task field requires three things to stay in sync: `newTask()` in `index.html`, the SQLite schema + column tuples in `stride-helper.py`'s `db_init`/`save_state`/`load_state`, and (only if a non-`undefined`-safe default is needed) `mergeState()` — per CLAUDE.md's "Task shape" note. This plan's new fields (`isPlanParent`, `planId`, `planIndex`) are all falsy-by-default and every check on them is a truthiness check, so no `mergeState()` change is needed — tasks saved before this feature existed will simply read as "not part of a plan," exactly like `srs`/`srsId` already behave for pre-SRS tasks.
- Follow the codebase's existing idiom: time-based multiplicity (recurrence, revision, and now day-plans) is represented as separate task objects linked by an id field, never as buried per-task state that only renders inside a detail panel.

---

### Task 1: Task model — add `isPlanParent` / `planId` / `planIndex`

**Files:**
- Modify: `index.html:763-772` (`newTask()`)
- Modify: `index.html:776` (`isInbox`)

**Interfaces:**
- Produces: `newTask()` now returns objects with `isPlanParent: false, planId: null, planIndex: null`. Every later task in this plan reads/writes these three fields with these exact names.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

Run:
```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
new Function(m[1] + '; if (typeof newTask !== \"function\") throw new Error(\"newTask missing\"); const t = newTask({}); console.log(JSON.stringify({isPlanParent: t.isPlanParent, planId: t.planId, planIndex: t.planIndex}));')();
"
```
Expected: `{"isPlanParent":undefined,"planId":undefined,"planIndex":undefined}` — the fields don't exist yet.

- [ ] **Step 2: Add the fields to `newTask()`**

In `index.html`, find:
```javascript
function newTask(p) {
  return Object.assign({
    id: uid(), title: "", notes: "", due: null, priority: 0, est: 0,
    project: null, someday: false, done: false, doneAt: null, createdAt: Date.now(),
    subtasks: [], links: [], repeat: null, mit: false, order: Date.now(),
    srs: null, srsId: null,           // srs: {stage:0..4}; srsId links a learning item to its revisions
    srsAsked: false,                  // user already decided about revision for this task — don't ask again
    startTime: null                   // "HH:MM" time block, e.g. "14:30"
  }, p);
}
```
Replace with:
```javascript
function newTask(p) {
  return Object.assign({
    id: uid(), title: "", notes: "", due: null, priority: 0, est: 0,
    project: null, someday: false, done: false, doneAt: null, createdAt: Date.now(),
    subtasks: [], links: [], repeat: null, mit: false, order: Date.now(),
    srs: null, srsId: null,           // srs: {stage:0..4}; srsId links a learning item to its revisions
    srsAsked: false,                  // user already decided about revision for this task — don't ask again
    startTime: null,                  // "HH:MM" time block, e.g. "14:30"
    isPlanParent: false,              // true once split into a day-by-day plan (see Task 4)
    planId: null,                     // on a plan's chapter tasks: the parent's id
    planIndex: null                   // on a plan's chapter tasks: 0-based day order
  }, p);
}
```

- [ ] **Step 3: Exclude plan parents from Inbox**

Find:
```javascript
const isInbox = t => !t.done && !t.due && !t.someday;
```
Replace with:
```javascript
const isInbox = t => !t.done && !t.due && !t.someday && !t.isPlanParent;
```
(Today/Upcoming/Week/Someday already require `t.due` or `t.someday`, neither of which a plan parent ever has, so they need no change — see the design doc's Display section for why.)

- [ ] **Step 4: Re-run the check from Step 1**

Same command as Step 1. Expected: `{"isPlanParent":false,"planId":null,"planIndex":null}`.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add isPlanParent/planId/planIndex fields to the task model

Foundation for day-by-day plans: chapters become linked task objects
following the same id-linking idiom already used for srsId/repeat,
rather than the existing due-date-less subtasks checklist.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: SQLite schema for the new fields

**Files:**
- Modify: `stride-helper.py:136-205` (`db_init`, `save_state`, `load_state`)

**Interfaces:**
- Consumes: task objects from Task 1 with `isPlanParent`/`planId`/`planIndex` keys (may be absent on tasks saved before Task 1 shipped — treat as falsy).
- Produces: `save_state`/`load_state` round-trip these three fields losslessly under the JS camelCase names `isPlanParent`/`planId`/`planIndex`.

- [ ] **Step 1: Confirm current column count (pre-change baseline)**

```bash
sqlite3 stride.db ".schema tasks"
```
Expected: 19 columns, ending `... srs TEXT, srs_id TEXT, srs_asked INTEGER)` — no `plan_id`/`plan_index`/`is_plan_parent`.

- [ ] **Step 2: Add the migration + schema columns**

In `stride-helper.py`, find:
```python
def db_init():
    with db_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, title TEXT, notes TEXT, due TEXT, priority INTEGER,
          est INTEGER, project TEXT, someday INTEGER, done INTEGER, done_at INTEGER,
          created_at INTEGER, repeat_rule TEXT, mit INTEGER, ord REAL,
          subtasks TEXT, links TEXT, srs TEXT, srs_id TEXT, srs_asked INTEGER);
        CREATE TABLE IF NOT EXISTS habits(id TEXT PRIMARY KEY, name TEXT, log TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, color TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        # migrate databases created before spaced repetition existed
        for col in ("srs TEXT", "srs_id TEXT", "srs_asked INTEGER"):
            try:
                c.execute("ALTER TABLE tasks ADD COLUMN " + col)
            except sqlite3.OperationalError:
                pass
```
Replace with:
```python
def db_init():
    with db_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, title TEXT, notes TEXT, due TEXT, priority INTEGER,
          est INTEGER, project TEXT, someday INTEGER, done INTEGER, done_at INTEGER,
          created_at INTEGER, repeat_rule TEXT, mit INTEGER, ord REAL,
          subtasks TEXT, links TEXT, srs TEXT, srs_id TEXT, srs_asked INTEGER,
          plan_id TEXT, plan_index INTEGER, is_plan_parent INTEGER);
        CREATE TABLE IF NOT EXISTS habits(id TEXT PRIMARY KEY, name TEXT, log TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, color TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        # migrate databases created before spaced repetition existed
        for col in ("srs TEXT", "srs_id TEXT", "srs_asked INTEGER",
                     "plan_id TEXT", "plan_index INTEGER", "is_plan_parent INTEGER"):
            try:
                c.execute("ALTER TABLE tasks ADD COLUMN " + col)
            except sqlite3.OperationalError:
                pass
```

- [ ] **Step 3: Extend `save_state`'s INSERT**

Find:
```python
        for t in state.get("tasks", []):
            c.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                t.get("id"), t.get("title"), t.get("notes"), t.get("due"),
                t.get("priority"), t.get("est"), t.get("project"),
                int(bool(t.get("someday"))), int(bool(t.get("done"))),
                t.get("doneAt"), t.get("createdAt"), t.get("repeat"),
                int(bool(t.get("mit"))), t.get("order"),
                json.dumps(t.get("subtasks", [])), json.dumps(t.get("links", [])),
                json.dumps(t.get("srs")) if t.get("srs") else None, t.get("srsId"),
                int(bool(t.get("srsAsked")))))
```
Replace with:
```python
        for t in state.get("tasks", []):
            c.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                t.get("id"), t.get("title"), t.get("notes"), t.get("due"),
                t.get("priority"), t.get("est"), t.get("project"),
                int(bool(t.get("someday"))), int(bool(t.get("done"))),
                t.get("doneAt"), t.get("createdAt"), t.get("repeat"),
                int(bool(t.get("mit"))), t.get("order"),
                json.dumps(t.get("subtasks", [])), json.dumps(t.get("links", [])),
                json.dumps(t.get("srs")) if t.get("srs") else None, t.get("srsId"),
                int(bool(t.get("srsAsked"))),
                t.get("planId"), t.get("planIndex"), int(bool(t.get("isPlanParent")))))
```
(19 `?` placeholders became 22; 19 tuple values became 22.)

- [ ] **Step 4: Extend `load_state`'s row mapping**

Find:
```python
        state["tasks"] = [{
            "id": r[0], "title": r[1], "notes": r[2], "due": r[3], "priority": r[4],
            "est": r[5], "project": r[6], "someday": bool(r[7]), "done": bool(r[8]),
            "doneAt": r[9], "createdAt": r[10], "repeat": r[11], "mit": bool(r[12]),
            "order": r[13], "subtasks": json.loads(r[14] or "[]"), "links": json.loads(r[15] or "[]"),
            "srs": json.loads(r[16]) if len(r) > 16 and r[16] else None,
            "srsId": r[17] if len(r) > 17 else None,
            "srsAsked": bool(r[18]) if len(r) > 18 else False,
        } for r in c.execute("SELECT * FROM tasks")]
```
Replace with:
```python
        state["tasks"] = [{
            "id": r[0], "title": r[1], "notes": r[2], "due": r[3], "priority": r[4],
            "est": r[5], "project": r[6], "someday": bool(r[7]), "done": bool(r[8]),
            "doneAt": r[9], "createdAt": r[10], "repeat": r[11], "mit": bool(r[12]),
            "order": r[13], "subtasks": json.loads(r[14] or "[]"), "links": json.loads(r[15] or "[]"),
            "srs": json.loads(r[16]) if len(r) > 16 and r[16] else None,
            "srsId": r[17] if len(r) > 17 else None,
            "srsAsked": bool(r[18]) if len(r) > 18 else False,
            "planId": r[19] if len(r) > 19 else None,
            "planIndex": r[20] if len(r) > 20 else None,
            "isPlanParent": bool(r[21]) if len(r) > 21 else False,
        } for r in c.execute("SELECT * FROM tasks")]
```

- [ ] **Step 5: Verify — round-trip a plan-shaped task against an isolated scratch database**

```bash
python3 -c "import ast; ast.parse(open('stride-helper.py').read())" && echo "syntax OK"
```
Expected: `syntax OK`.

**Do not use the running helper's `/state` endpoint for this check — it replaces the *entire* live `tasks` table (delete-then-reinsert), so posting a small test payload to it destroys real data.** Instead, import `save_state`/`load_state`/`db_init` directly and point them at a throwaway temp file by reassigning the module's `DB_PATH` global — this exercises the exact same code with zero risk to `stride.db`:

```bash
python3 -c "
import importlib.util, tempfile, os

spec = importlib.util.spec_from_file_location('stride_helper', 'stride-helper.py')
sh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sh)

sh.DB_PATH = os.path.join(tempfile.mkdtemp(), 'scratch.db')
sh.db_init()
sh.save_state({
    'tasks': [
        {'id': 'planparent1', 'title': 'Read LLD notes', 'isPlanParent': True},
        {'id': 'planchild1', 'title': 'Ch.1', 'planId': 'planparent1', 'planIndex': 0, 'due': '2026-07-12'},
    ],
    'habits': [], 'projects': [],
})
loaded = sh.load_state()
parent = next(t for t in loaded['tasks'] if t['id'] == 'planparent1')
child = next(t for t in loaded['tasks'] if t['id'] == 'planchild1')
print('parent.isPlanParent:', parent['isPlanParent'], '(expect True)')
print('child.planId:', child['planId'], '(expect planparent1)')
print('child.planIndex:', child['planIndex'], '(expect 0)')
"
```
Expected: `parent.isPlanParent: True`, `child.planId: planparent1`, `child.planIndex: 0`. The scratch database lives in a temp directory and is never connected to the running helper or `stride.db` — nothing further to clean up.

- [ ] **Step 6: Commit**

```bash
git add stride-helper.py
git commit -m "$(cat <<'EOF'
Add plan_id/plan_index/is_plan_parent columns to the tasks table

Mirrors the JS-side isPlanParent/planId/planIndex fields so day-plans
round-trip through SQLite the same way srs/srsId already do.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Display — prepend parent title on chapter rows

**Files:**
- Modify: `index.html:1051-1088` (`taskRow`)

**Interfaces:**
- Consumes: `t.planId`, `findTask(id)` (existing, `index.html:1363` at time of writing — a plain `db.tasks.find`).
- Produces: no new exported symbols; `taskRow(t, opts)`'s rendered title changes when `t.planId` is set.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
db.tasks = [
  {id:'p1', title:'Read LLD notes', isPlanParent:true, planId:null, planIndex:null, done:false, doneAt:null, due:null, priority:0, est:0, project:null, someday:false, subtasks:[], links:[], repeat:null, mit:false, order:1, srs:null, srsId:null, srsAsked:false, startTime:null, notes:''},
  {id:'c1', title:'Ch.1: Intro', isPlanParent:false, planId:'p1', planIndex:0, done:false, doneAt:null, due:'2026-07-12', priority:0, est:0, project:null, someday:false, subtasks:[], links:[], repeat:null, mit:false, order:2, srs:null, srsId:null, srsAsked:false, startTime:null, notes:''}
];
const row = taskRow(db.tasks[1]);
const hasParentTitle = row.includes('Read LLD notes') && row.includes('Ch.1: Intro');
console.log('row includes parent+child title:', hasParentTitle);
\`;
new Function(src)();
" 2>&1 | tail -5
```
Expected: `row includes parent+child title: false` (only "Ch.1: Intro" appears today).

*Note: this harness evaluates the whole script, which registers many `document.addEventListener` calls against a Node.js global — that's fine, they just won't fire; only the pure `taskRow` call matters here. If this errors on a DOM API stride-helper's script assumes exists, wrap the relevant globals (`document`, `localStorage`, `fetch`) with no-op stubs before the `new Function(...)()` call, matching whatever the error names.*

- [ ] **Step 2: Prepend the parent title**

Find:
```javascript
    <div class="task-body">
      <div class="task-title">${esc(t.title) || "<i style='color:var(--faint)'>Untitled</i>"}</div>
      ${chips ? `<div class="task-meta">${chips}</div>` : ""}${triage}
    </div>
```
Replace with:
```javascript
    <div class="task-body">
      <div class="task-title">${t.title ? (t.planId && findTask(t.planId) ? esc(findTask(t.planId).title) + " — " + esc(t.title) : esc(t.title)) : "<i style='color:var(--faint)'>Untitled</i>"}</div>
      ${chips ? `<div class="task-meta">${chips}</div>` : ""}${triage}
    </div>
```

- [ ] **Step 3: Re-run the check from Step 1**

Same command. Expected: `row includes parent+child title: true`.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Prepend parent title on plan-chapter task rows

A chapter task's row now reads "Read LLD notes — Ch.1: Intro" instead
of just the chapter title, so it's identifiable in Today/Upcoming
without opening its detail panel. The stored title stays just the
chapter name so editing it isn't redundant.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Plan creation — "Split into a day-by-day plan"

**Files:**
- Modify: `index.html:1390-1393` (add helper functions after `setDue`)
- Modify: `index.html:1474-1526` (`renderDetail`'s template + event wiring)

**Interfaces:**
- Consumes: `newTask()` (Task 1), `showModal`/`closeModal` (`index.html:1821-1822`), `addDays`/`parseISO`/`todayStr` (`index.html:655-658`).
- Produces: `firstPlanDay(iso, skipWeekends)`, `addPlanDay(iso, skipWeekends)`, `splitIntoPlan(t, lines, skipWeekends)`, `openSplitPlan(t)` — all consumed by no other task in this plan except Task 4 itself, but `splitIntoPlan`'s field-writes (`isPlanParent`, `due=null`, `repeat=null`, and children with `planId`/`planIndex`) are exactly what Tasks 5–7 read.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

```bash
grep -c "splitIntoPlan\|openSplitPlan\|dSplitPlan" index.html
```
Expected: `0`.

- [ ] **Step 2: Add the date-math and creation helpers**

In `index.html`, find:
```javascript
function setDue(t, v) {
  t.someday = false;
  t.due = v === "0" ? todayStr() : v === "1" ? addDays(todayStr(), 1) : v === "wk" ? addDays(todayStr(), 7) : v || null;
}
```
Replace with:
```javascript
function setDue(t, v) {
  t.someday = false;
  t.due = v === "0" ? todayStr() : v === "1" ? addDays(todayStr(), 1) : v === "wk" ? addDays(todayStr(), 7) : v || null;
}
function firstPlanDay(iso, skipWeekends) {
  let d = iso;
  while (skipWeekends && [0, 6].includes(parseISO(d).getDay())) d = addDays(d, 1);
  return d;
}
function addPlanDay(iso, skipWeekends) {
  let d = addDays(iso, 1);
  while (skipWeekends && [0, 6].includes(parseISO(d).getDay())) d = addDays(d, 1);
  return d;
}
function splitIntoPlan(t, lines, skipWeekends) {
  let due = firstPlanDay(t.due || todayStr(), skipWeekends);
  t.isPlanParent = true; t.due = null; t.repeat = null;
  lines.forEach((title, i) => {
    if (i > 0) due = addPlanDay(due, skipWeekends);
    db.tasks.push(newTask({ title, project: t.project, due, planId: t.id, planIndex: i }));
  });
}
function openSplitPlan(t) {
  showModal(`
    <div class="modal-head"><h2>Split into a day-by-day plan</h2>
      <p>One line per day. Each becomes its own task, shown on its day under “${esc(t.title.slice(0, 60))}.”</p></div>
    <div class="modal-body">
      <textarea id="mPlanLines" placeholder="Ch.1: Introduction&#10;Ch.2: Processes&#10;Ch.3: Concurrency" style="min-height:160px"></textarea>
      <label class="set-row" style="gap:10px;font-size:13px;border-bottom:none;padding:10px 0 0">
        <input type="checkbox" id="mPlanSkipWeekends" style="width:16px;height:16px;accent-color:var(--accent);flex:none">
        <span>Skip weekends</span>
      </label>
    </div>
    <div class="modal-foot"><button class="pill-btn ghost" id="mPlanCancel">Cancel</button><button class="pill-btn" id="mPlanGo">Create plan</button></div>`);
  $("#mPlanCancel").onclick = closeModal;
  $("#mPlanGo").onclick = () => {
    const lines = $("#mPlanLines").value.split("\n").map(l => l.trim()).filter(Boolean);
    if (!lines.length) { toast("Add at least one line"); return; }
    const skipWeekends = $("#mPlanSkipWeekends").checked;
    splitIntoPlan(t, lines, skipWeekends);
    closeModal(); state.selected = t.id; save(); render();
    toast(`Plan created — ${lines.length} day${lines.length > 1 ? "s" : ""}`);
  };
}
```
(`.modal-head`, `.modal-body`, `.modal-foot`, `.set-row`, `.pill-btn` are existing classes already used by `openRevisionOffer`/`openReadCapture` — no new CSS.)

- [ ] **Step 3: Add the button to the detail panel**

Find:
```javascript
      <div class="detail-row"><label>Repeat</label>
        <select id="dRep">${["", "daily", "weekdays", "weekly", "monthly"].map(r => `<option value="${r}" ${t.repeat === r || (!t.repeat && !r) ? "selected" : ""}>${r || "—"}</option>`).join("")}</select></div>
    </div>
    <div class="detail-row"><label>Spaced review · every 2 days</label>
```
Replace with:
```javascript
      <div class="detail-row"><label>Repeat</label>
        <select id="dRep">${["", "daily", "weekdays", "weekly", "monthly"].map(r => `<option value="${r}" ${t.repeat === r || (!t.repeat && !r) ? "selected" : ""}>${r || "—"}</option>`).join("")}</select></div>
    </div>
    ${!t.isPlanParent && !t.planId ? `<div class="detail-row"><label>Day-by-day plan</label>
      <button class="add-sub" id="dSplitPlan">✎ Split into a day-by-day plan</button>
    </div>` : ""}
    <div class="detail-row"><label>Spaced review · every 2 days</label>
```

- [ ] **Step 4: Wire the button's click handler**

Find (near the other `renderDetail` event wiring):
```javascript
  $("#dDelete").addEventListener("click", () => {
    const idx = db.tasks.indexOf(t); db.tasks.splice(idx, 1); state.selected = null; save(); render();
    toast("Task deleted", "Undo", () => { db.tasks.splice(idx, 0, t); save(); render(); });
  });
}
```
Replace with:
```javascript
  $("#dDelete").addEventListener("click", () => {
    const idx = db.tasks.indexOf(t); db.tasks.splice(idx, 1); state.selected = null; save(); render();
    toast("Task deleted", "Undo", () => { db.tasks.splice(idx, 0, t); save(); render(); });
  });
  $("#dSplitPlan")?.addEventListener("click", () => openSplitPlan(t));
}
```

- [ ] **Step 5: Syntax check**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
new Function(m[1]);
console.log('syntax OK');
"
```
Expected: `syntax OK`.

- [ ] **Step 6: Verify `splitIntoPlan`'s date math directly**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const t = newTask({ id:'p1', title:'Read LLD notes', due:'2026-07-11' }); // a Saturday
db.tasks = [t];
splitIntoPlan(t, ['Ch.1','Ch.2','Ch.3'], true);
console.log('parent.isPlanParent:', t.isPlanParent, 'parent.due:', t.due, 'parent.repeat:', t.repeat);
const kids = db.tasks.filter(x => x.planId === t.id).sort((a,b)=>a.planIndex-b.planIndex);
console.log(kids.map(k => k.title + ' due ' + k.due + ' (planIndex ' + k.planIndex + ')').join('; '));
\`;
new Function(src)();
"
```
Expected: `parent.isPlanParent: true parent.due: null parent.repeat: null`, then three chapters — since 2026-07-11 is a Saturday and "skip weekends" is on, Ch.1 should land on Monday 2026-07-13, Ch.2 on Tuesday 2026-07-14, Ch.3 on Wednesday 2026-07-15 (verify against an actual calendar for the literal dates — the important checks are: no chapter falls on a Sat/Sun, and each chapter is exactly one weekday after the previous).

- [ ] **Step 7: Manual browser verification**

Start the app (`python3 stride-helper.py`, open `http://127.0.0.1:8787/`), open any task's detail panel, click **"✎ Split into a day-by-day plan,"** enter 3 lines, leave "Skip weekends" unchecked, click **"Create plan."** Confirm: the modal closes, a toast says "Plan created — 3 days," and the original task's row disappears from Inbox/Today (it's now the parent). Open the detail panel of one of the 3 new chapter tasks (findable via search or Today/Upcoming depending on today's weekday) and confirm its title shows as "`<original title>` — `<chapter title>`" in the task list.

- [ ] **Step 8: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add plan creation: "Split into a day-by-day plan"

New detail-panel button turns a task into a plan parent and spawns
one linked chapter-task per line, sequential by day with an optional
weekend skip.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Completion — auto-revision per chapter, auto-complete the parent

**Files:**
- Modify: `index.html:1364-1389` (`completeTask`)
- Modify: `index.html:1435-1453` (toggle click handler's complete/undo branches)
- Modify: `index.html:1724` (Focus mode's "Done" button)

**Interfaces:**
- Consumes: `startRevision(t)` (existing, `index.html:2417` at time of writing), `t.planId`/`t.isPlanParent` (Task 1), `maybeOfferRevision(t)` (existing, `index.html:2436`).
- Produces: no new symbols; `completeTask(t)` now also starts revision and may auto-complete `t`'s plan parent when `t.planId` is set; unchecking the last chapter un-completes the parent.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const parent = newTask({ id:'p1', title:'Read LLD notes', isPlanParent:true });
const c1 = newTask({ id:'c1', title:'Ch.1', planId:'p1', planIndex:0, due:'2026-07-12' });
db.tasks = [parent, c1];
completeTask(c1);
console.log('c1.done:', c1.done, 'c1.srs:', JSON.stringify(c1.srs), 'parent.done:', parent.done);
\`;
new Function(src)();
"
```
Expected: `c1.done: true c1.srs: null parent.done: false` — no revision starts, parent never completes.

- [ ] **Step 2: Add the plan branch to `completeTask`**

Find:
```javascript
  if (t.repeat) {
    const nxt = newTask({ title: t.title, notes: t.notes, priority: t.priority, est: t.est, project: t.project, repeat: t.repeat, subtasks: t.subtasks.map(s => ({ ...s, done: false })), due: nextOccurrence(t), links: [...t.links], startTime: t.startTime });
    t.repeat = null; db.tasks.push(nxt);
  }
  maybeCelebrate();
}
```
Replace with:
```javascript
  if (t.repeat) {
    const nxt = newTask({ title: t.title, notes: t.notes, priority: t.priority, est: t.est, project: t.project, repeat: t.repeat, subtasks: t.subtasks.map(s => ({ ...s, done: false })), due: nextOccurrence(t), links: [...t.links], startTime: t.startTime });
    t.repeat = null; db.tasks.push(nxt);
  }
  if (t.planId) {
    // every chapter gets its own spaced-revision chain, started automatically —
    // asking "worth remembering?" once per chapter would be tedious
    if (!t.srs) startRevision(t);
    const siblings = db.tasks.filter(x => x.planId === t.planId);
    if (siblings.every(x => x.done)) {
      const parent = db.tasks.find(x => x.id === t.planId && x.isPlanParent);
      if (parent && !parent.done) { parent.done = true; parent.doneAt = Date.now(); }
    }
  }
  maybeCelebrate();
}
```

- [ ] **Step 3: Suppress the redundant "Worth remembering?" offer for plan chapters**

`completeTask` now auto-starts revision for plan chapters, so the existing offer modal (triggered by `maybeOfferRevision`, which checks `t.srs.stage === 0`) would immediately re-offer the exact thing that just happened automatically. Skip the call for plan chapters at both existing call sites.

Find (toggle click handler):
```javascript
        else {
          completeTask(t);
          maybeOfferRevision(t);
        }
```
Replace with:
```javascript
        else {
          completeTask(t);
          if (!t.planId) maybeOfferRevision(t);
        }
```

Find (Focus mode Done button):
```javascript
  $("#fDone").onclick = () => { const t2 = findTask(focus.taskId); logFocus(); completeTask(t2); maybeOfferRevision(t2); save(); nextFocus(); };
```
Replace with:
```javascript
  $("#fDone").onclick = () => { const t2 = findTask(focus.taskId); logFocus(); completeTask(t2); if (!t2.planId) maybeOfferRevision(t2); save(); nextFocus(); };
```

- [ ] **Step 4: Un-complete the parent symmetrically on undo**

Find:
```javascript
          // remove any SRS revision tasks that were spawned for this completion
          const srsId = t.srsId || t.id;
          db.tasks = db.tasks.filter(x => !(x !== t && !x.done && x.srs && x.srsId === srsId && x.srs.stage === (t.srs ? t.srs.stage + 1 : 1)));
          t.srs = null;
        }
```
Replace with:
```javascript
          // remove any SRS revision tasks that were spawned for this completion
          const srsId = t.srsId || t.id;
          db.tasks = db.tasks.filter(x => !(x !== t && !x.done && x.srs && x.srsId === srsId && x.srs.stage === (t.srs ? t.srs.stage + 1 : 1)));
          t.srs = null;
          if (t.planId) {
            const parent = db.tasks.find(x => x.id === t.planId && x.isPlanParent);
            if (parent && parent.done) { parent.done = false; parent.doneAt = null; }
          }
        }
```

- [ ] **Step 5: Re-run the check from Step 1, plus the all-siblings-done case**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const parent = newTask({ id:'p1', title:'Read LLD notes', isPlanParent:true });
const c1 = newTask({ id:'c1', title:'Ch.1', planId:'p1', planIndex:0, due:'2026-07-12' });
const c2 = newTask({ id:'c2', title:'Ch.2', planId:'p1', planIndex:1, due:'2026-07-13' });
db.tasks = [parent, c1, c2];
completeTask(c1);
console.log('after c1: c1.done', c1.done, 'c1.srs.stage', c1.srs && c1.srs.stage, 'parent.done', parent.done, '(expect true, 0, false)');
const revisionClone = db.tasks.find(x => x.srsId === 'c1' && x.srs.stage === 1);
console.log('revision clone spawned:', !!revisionClone, '(expect true)');
completeTask(c2);
console.log('after c2: parent.done', parent.done, 'parent.doneAt set', !!parent.doneAt, '(expect true, true)');
\`;
new Function(src)();
"
```
Expected: `after c1: c1.done true c1.srs.stage 0 parent.done false (expect true, 0, false)`, `revision clone spawned: true (expect true)`, `after c2: parent.done true parent.doneAt set true (expect true, true)`.

- [ ] **Step 6: Manual browser verification**

Using the plan created in Task 4's Step 7: check off each chapter one at a time. Confirm after the last one that (a) a toast about the parent doesn't appear (there's no special toast — just confirm the parent now shows in the Today view's "Done" section if you navigate to it, findable since it now has `doneAt` set today) and (b) each completed chapter's detail panel shows a "Spaced review" section reading "Review 1/4" without you having clicked anything to start it, and no "Worth remembering?" modal popped up.

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Auto-start revision per chapter and auto-complete the plan parent

Completing a plan chapter now kicks off its own spaced-revision chain
automatically (no per-chapter prompt) and, once every chapter is
done, marks the parent task done too. Unchecking the last chapter
un-completes the parent symmetrically.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Rescheduling — cascade a due-date change to later chapters

**Files:**
- Modify: `index.html:1390-1393` area (add `shiftPlanSiblings` alongside the Task 4 helpers)
- Modify: `index.html:1350-1360` (drop handler)
- Modify: `index.html:1530` (`$("#dDue")` change handler in `renderDetail`)

**Interfaces:**
- Consumes: `daysDiff(iso)`, `addDays(iso, n)` (existing, `index.html:658-659`).
- Produces: `shiftPlanSiblings(t, deltaDays)` — shifts every later, still-open sibling of `t` (same `planId`, greater `planIndex`, `!done`) by `deltaDays`.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const c1 = newTask({ id:'c1', title:'Ch.1', planId:'p1', planIndex:0, due:'2026-07-12' });
const c2 = newTask({ id:'c2', title:'Ch.2', planId:'p1', planIndex:1, due:'2026-07-13' });
db.tasks = [c1, c2];
console.log(typeof shiftPlanSiblings);
\`;
new Function(src)();
" 2>&1 | tail -3
```
Expected: a `ReferenceError: shiftPlanSiblings is not defined` (or `undefined` if caught) — the function doesn't exist yet.

- [ ] **Step 2: Add `shiftPlanSiblings`**

Find (the block added in Task 4, Step 2):
```javascript
function splitIntoPlan(t, lines, skipWeekends) {
  let due = firstPlanDay(t.due || todayStr(), skipWeekends);
  t.isPlanParent = true; t.due = null; t.repeat = null;
  lines.forEach((title, i) => {
    if (i > 0) due = addPlanDay(due, skipWeekends);
    db.tasks.push(newTask({ title, project: t.project, due, planId: t.id, planIndex: i }));
  });
}
```
Replace with:
```javascript
function splitIntoPlan(t, lines, skipWeekends) {
  let due = firstPlanDay(t.due || todayStr(), skipWeekends);
  t.isPlanParent = true; t.due = null; t.repeat = null;
  lines.forEach((title, i) => {
    if (i > 0) due = addPlanDay(due, skipWeekends);
    db.tasks.push(newTask({ title, project: t.project, due, planId: t.id, planIndex: i }));
  });
}
function shiftPlanSiblings(t, deltaDays) {
  if (!t.planId || !deltaDays) return;
  db.tasks.filter(x => x.planId === t.planId && x.planIndex > t.planIndex && !x.done && x.due)
    .forEach(x => x.due = addDays(x.due, deltaDays));
}
```

- [ ] **Step 3: Cascade on detail-panel due-date edits**

Find:
```javascript
  $("#dDue").addEventListener("change", e => commit(() => { t.due = e.target.value || null; if (t.due) t.someday = false; }));
```
Replace with:
```javascript
  $("#dDue").addEventListener("change", e => commit(() => {
    const oldDue = t.due;
    t.due = e.target.value || null;
    if (t.due) t.someday = false;
    if (t.planId && oldDue && t.due) shiftPlanSiblings(t, daysDiff(t.due) - daysDiff(oldDue));
  }));
```

- [ ] **Step 4: Cascade on drag-and-drop reschedule**

Find:
```javascript
document.addEventListener("drop", e => {
  const el = e.target.closest?.(".task"); if (!el || !dragId) return;
  e.preventDefault();
  const src = db.tasks.find(t => t.id === dragId), dst = db.tasks.find(t => t.id === el.dataset.id);
  if (!src || !dst || src === dst) return;
  const above = e.clientY < el.getBoundingClientRect().top + el.offsetHeight / 2;
  if (src.due !== dst.due && dst.due) src.due = dst.due;      // dragging across day groups reschedules
  src.order = dst.order + (above ? -0.5 : 0.5);
  db.tasks.filter(t => true).sort((a, b) => a.order - b.order).forEach((t, i) => t.order = i + 1);
  save(); render();
});
```
Replace with:
```javascript
document.addEventListener("drop", e => {
  const el = e.target.closest?.(".task"); if (!el || !dragId) return;
  e.preventDefault();
  const src = db.tasks.find(t => t.id === dragId), dst = db.tasks.find(t => t.id === el.dataset.id);
  if (!src || !dst || src === dst) return;
  const above = e.clientY < el.getBoundingClientRect().top + el.offsetHeight / 2;
  if (src.due !== dst.due && dst.due) {                       // dragging across day groups reschedules
    if (src.planId) shiftPlanSiblings(src, daysDiff(dst.due) - daysDiff(src.due));
    src.due = dst.due;
  }
  src.order = dst.order + (above ? -0.5 : 0.5);
  db.tasks.filter(t => true).sort((a, b) => a.order - b.order).forEach((t, i) => t.order = i + 1);
  save(); render();
});
```

- [ ] **Step 5: Re-run the check from Step 1, and confirm the shift + the "already-done siblings are untouched" rule**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const c1 = newTask({ id:'c1', title:'Ch.1', planId:'p1', planIndex:0, due:'2026-07-11', done:true, doneAt:1 }); // already done
const c2 = newTask({ id:'c2', title:'Ch.2', planId:'p1', planIndex:1, due:'2026-07-12' });
const c3 = newTask({ id:'c3', title:'Ch.3', planId:'p1', planIndex:2, due:'2026-07-13' });
db.tasks = [c1, c2, c3];
shiftPlanSiblings(c1, 3); // pretend c1's due moved 3 days later (even though it's done, this call simulates editing a later chapter)
console.log('c1.due unchanged:', c1.due === '2026-07-11', '(expect true — shiftPlanSiblings never touches the edited task itself)');
console.log('c2.due shifted:', c2.due, '(expect 2026-07-15)');
console.log('c3.due shifted:', c3.due, '(expect 2026-07-16)');
const c2b = newTask({ id:'c2b', title:'Ch.2', planId:'p1', planIndex:1, due:'2026-07-12', done:true });
db.tasks = [c1, c2b, c3];
shiftPlanSiblings(c1, 3);
console.log('done sibling untouched:', c2b.due === '2026-07-12', '(expect true)');
\`;
new Function(src)();
"
```
Expected: `c1.due unchanged: true`, `c2.due shifted: 2026-07-15`, `c3.due shifted: 2026-07-16`, `done sibling untouched: true`.

- [ ] **Step 6: Manual browser verification**

Open a not-yet-completed chapter from the Task 4 plan, change its due date forward by 2 days in the detail panel. Confirm the later, still-open chapters' due dates (visible by reopening each, or seeing them move in Upcoming) shifted forward by 2 days too, and any already-completed chapter kept its original date.

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Cascade due-date changes to later, still-open plan chapters

Editing a chapter's due date (detail panel or drag-and-drop) now
shifts every later chapter in the same plan that isn't done yet by
the same delta, so moving the plan's start date moves the whole
remaining schedule with it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Detail panel — "Part of a plan" progress section

**Files:**
- Modify: `index.html` (add `renderPlanSection` near `taskRow`, e.g. directly above `renderDetail` at `index.html:1474` at time of writing)
- Modify: `index.html:1474-1526` (`renderDetail`'s template + event wiring)

**Interfaces:**
- Consumes: `findTask(id)`, `esc(s)`, `fmtDue(iso)` (all existing).
- Produces: `renderPlanSection(t)` returning an HTML string; no other task depends on it.

- [ ] **Step 1: Confirm current behavior (pre-change baseline)**

```bash
grep -c "renderPlanSection\|dPlanDays" index.html
```
Expected: `0`.

- [ ] **Step 2: Add `renderPlanSection`**

In `index.html`, immediately before `function renderDetail() {` (`index.html:1474` at time of writing), insert:
```javascript
function renderPlanSection(t) {
  const parentId = t.isPlanParent ? t.id : t.planId;
  const parent = t.isPlanParent ? t : findTask(parentId);
  if (!parent) return "";
  const days = db.tasks.filter(x => x.planId === parentId).sort((a, b) => a.planIndex - b.planIndex);
  const doneCount = days.filter(x => x.done).length;
  return `<div class="detail-row"><label>Day-by-day plan</label>
    <div class="srs-row" style="margin-bottom:10px">
      <span class="srs-dots">${days.map(d => `<i class="${d.done ? "on" : ""}"></i>`).join("")}</span>
      <span class="srs-title">${esc(parent.title)}</span>
      <span class="srs-meta">${doneCount}/${days.length} done</span>
    </div>
    <div id="dPlanDays">${days.map(d => `
      <div class="subtask ${d.done ? "done" : ""}" data-plan-jump="${d.id}" style="cursor:${d.id === t.id ? "default" : "pointer"}">
        <span style="flex:1">${d.planIndex + 1}. ${esc(d.title)}</span>
        <span class="srs-meta">${d.due ? fmtDue(d.due) : ""}</span>
      </div>`).join("")}</div>
  </div>`;
}
```
(`.srs-row`, `.srs-dots`, `.srs-title`, `.srs-meta` are the existing classes the Revise tab's "Learning pipeline" already uses for SRS lineage progress — no new CSS. `.subtask` is the existing checklist-row class.)

- [ ] **Step 3: Show it instead of the "Split" button for parents/chapters**

Find (the block added in Task 4, Step 3):
```javascript
    ${!t.isPlanParent && !t.planId ? `<div class="detail-row"><label>Day-by-day plan</label>
      <button class="add-sub" id="dSplitPlan">✎ Split into a day-by-day plan</button>
    </div>` : ""}
    <div class="detail-row"><label>Spaced review · every 2 days</label>
```
Replace with:
```javascript
    ${t.isPlanParent || t.planId ? renderPlanSection(t) : `<div class="detail-row"><label>Day-by-day plan</label>
      <button class="add-sub" id="dSplitPlan">✎ Split into a day-by-day plan</button>
    </div>`}
    <div class="detail-row"><label>Spaced review · every 2 days</label>
```

- [ ] **Step 4: Wire click-to-jump between chapters**

Find:
```javascript
  $("#dSplitPlan")?.addEventListener("click", () => openSplitPlan(t));
}
```
Replace with:
```javascript
  $("#dSplitPlan")?.addEventListener("click", () => openSplitPlan(t));
  $("#dPlanDays")?.addEventListener("click", e => {
    const row = e.target.closest("[data-plan-jump]"); if (!row) return;
    state.selected = row.dataset.planJump; render();
  });
}
```

- [ ] **Step 5: Syntax check**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
new Function(m[1]);
console.log('syntax OK');
"
```
Expected: `syntax OK`.

- [ ] **Step 6: Verify `renderPlanSection`'s output directly**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
const src = m[1] + \`
const parent = newTask({ id:'p1', title:'Read LLD notes', isPlanParent:true });
const c1 = newTask({ id:'c1', title:'Ch.1', planId:'p1', planIndex:0, due:'2026-07-12', done:true });
const c2 = newTask({ id:'c2', title:'Ch.2', planId:'p1', planIndex:1, due:'2026-07-13' });
db.tasks = [parent, c1, c2];
const html1 = renderPlanSection(c2);
console.log('shows parent title:', html1.includes('Read LLD notes'));
console.log('shows progress 1/2:', html1.includes('1/2 done'));
console.log('shows both chapter titles:', html1.includes('Ch.1') && html1.includes('Ch.2'));
\`;
new Function(src)();
"
```
Expected: `shows parent title: true`, `shows progress 1/2: true`, `shows both chapter titles: true`.

- [ ] **Step 7: Manual browser verification**

Open any chapter task from the Task 4 plan (some done, some not). Confirm the detail panel shows a "Day-by-day plan" section with progress dots, an "N/M done" count, and every chapter listed with its due date — clicking a different chapter in that list jumps the detail panel to it. Open the parent task itself (search for its title) and confirm the same section renders there too.

- [ ] **Step 8: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add plan progress view to the detail panel

Opening any chapter (or the parent) now shows the whole plan: title,
progress dots, and every chapter with its status and date, reusing
the same progress-dots styling the Revise tab already uses for
spaced-revision lineages. Clicking a chapter jumps the panel to it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage** — every section of `docs/superpowers/specs/2026-07-11-multiday-reading-plan-design.md` maps to a task:
- Data model → Task 1 (index.html) + Task 2 (SQLite)
- Creating a plan → Task 4
- Display → Task 3
- Completing a chapter (revision + auto-complete) → Task 5
- Rescheduling → Task 6
- Viewing plan progress → Task 7
- Non-goals — deliberately not built; no task references editing-after-creation, recurring plans, or per-chapter priority defaults beyond inheritance.

**Placeholder scan** — no TBD/TODO; every step has literal code or an exact command with an exact expected result.

**Type/name consistency** — `isPlanParent`/`planId`/`planIndex` (camelCase, matching the rest of the JS task shape) are used identically across Tasks 1, 3, 4, 5, 6, 7. `plan_id`/`plan_index`/`is_plan_parent` (snake_case, matching existing SQLite column naming) are used identically across Task 2's three functions. `firstPlanDay`, `addPlanDay`, `splitIntoPlan`, `openSplitPlan`, `shiftPlanSiblings`, `renderPlanSection` are each defined once (Task 4 or 6 or 7) and referenced with the same name and argument order everywhere they're called.
