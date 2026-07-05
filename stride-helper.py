#!/usr/bin/env python3
# Part of Stride (MIT License) · Copyright (c) 2026 Milan Niroula
"""Stride helper — tiny local connector.

Some AI providers block direct browser calls (no CORS headers). This script
listens on 127.0.0.1:8787 and forwards Stride's API requests to the provider,
adding the CORS headers the browser needs. It only accepts connections from
this machine and only forwards to the URL Stride specifies per-request.

Stride.app starts it automatically. To run it manually:  python3 stride-helper.py
"""
import json
import os
import sqlite3
import subprocess
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stride.db")
DB_LOCK = threading.Lock()
META_KEYS = ("v", "settings", "focusLog", "lastPlanDate", "celebratedDates",
             "aiReport", "aiReportDate", "aiAutoDate", "calCache", "savedAt")


def db_conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def db_init():
    with db_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, title TEXT, notes TEXT, due TEXT, priority INTEGER,
          est INTEGER, project TEXT, someday INTEGER, done INTEGER, done_at INTEGER,
          created_at INTEGER, repeat_rule TEXT, mit INTEGER, ord REAL,
          subtasks TEXT, links TEXT);
        CREATE TABLE IF NOT EXISTS habits(id TEXT PRIMARY KEY, name TEXT, log TEXT);
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT, color TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)


def save_state(state):
    """Replace the whole snapshot atomically. State is small; simplest wins."""
    saved_at = int(time.time() * 1000)
    state = dict(state, savedAt=saved_at)
    with DB_LOCK, db_conn() as c:
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM habits")
        c.execute("DELETE FROM projects")
        for t in state.get("tasks", []):
            c.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                t.get("id"), t.get("title"), t.get("notes"), t.get("due"),
                t.get("priority"), t.get("est"), t.get("project"),
                int(bool(t.get("someday"))), int(bool(t.get("done"))),
                t.get("doneAt"), t.get("createdAt"), t.get("repeat"),
                int(bool(t.get("mit"))), t.get("order"),
                json.dumps(t.get("subtasks", [])), json.dumps(t.get("links", []))))
        for h in state.get("habits", []):
            c.execute("INSERT OR REPLACE INTO habits VALUES (?,?,?)",
                      (h.get("id"), h.get("name"), json.dumps(h.get("log", []))))
        for p in state.get("projects", []):
            c.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)",
                      (p.get("id"), p.get("name"), p.get("color")))
        for k in META_KEYS:
            c.execute("INSERT OR REPLACE INTO meta VALUES (?,?)",
                      (k, json.dumps(state.get(k))))
    return saved_at


def load_state():
    with DB_LOCK, db_conn() as c:
        meta = dict(c.execute("SELECT key, value FROM meta"))
        if "savedAt" not in meta:
            return None
        state = {k: json.loads(v) for k, v in meta.items()}
        state["tasks"] = [{
            "id": r[0], "title": r[1], "notes": r[2], "due": r[3], "priority": r[4],
            "est": r[5], "project": r[6], "someday": bool(r[7]), "done": bool(r[8]),
            "doneAt": r[9], "createdAt": r[10], "repeat": r[11], "mit": bool(r[12]),
            "order": r[13], "subtasks": json.loads(r[14] or "[]"), "links": json.loads(r[15] or "[]"),
        } for r in c.execute("SELECT * FROM tasks")]
        state["habits"] = [{"id": r[0], "name": r[1], "log": json.loads(r[2] or "[]")}
                           for r in c.execute("SELECT * FROM habits")]
        state["projects"] = [{"id": r[0], "name": r[1], "color": r[2]}
                             for r in c.execute("SELECT * FROM projects")]
        return state

PORT = 8787
VERSION = 5

# Static files served so Stride runs at http://127.0.0.1:8787/ — a stable
# origin that Chrome can install as a real app (own icon, own Dock entry).
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
FORWARD_HEADERS = ("authorization", "content-type", "x-api-key",
                   "anthropic-version", "accept")
ALLOW_HEADERS = ("authorization, content-type, x-api-key, anthropic-version, "
                 "anthropic-dangerous-direct-browser-access, x-stride-target, accept")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _reply(self, code, data, ctype="application/json"):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        clean = self.path.split("?")[0]
        if clean in STATIC:
            fname, ctype = STATIC[clean]
            try:
                with open(os.path.join(APP_DIR, fname), "rb") as f:
                    self._reply(200, f.read(), ctype)
            except OSError:
                self._reply(404, b'{"error":{"message":"file not found"}}')
            return
        if self.path == "/ping":
            self._reply(200, json.dumps(
                {"ok": True, "service": "stride-helper", "version": VERSION}).encode())
        elif self.path.startswith("/calendar"):
            self._reply(200, json.dumps(get_calendar_events()).encode())
        elif self.path == "/state":
            try:
                state = load_state()
                self._reply(200, json.dumps(
                    {"exists": state is not None, "state": state}).encode())
            except Exception as e:
                self._reply(500, json.dumps({"error": {"message": str(e)}}).encode())
        elif self.path.startswith("/activity"):
            try:
                hours = 12
                if "hours=" in self.path:
                    hours = max(1, min(48, int(self.path.split("hours=")[1].split("&")[0])))
                self._reply(200, json.dumps(activity_summary(hours)).encode())
            except Exception as e:
                self._reply(500, json.dumps({"error": {"message": str(e)}}).encode())
        else:
            self.forward("GET")

    def do_POST(self):
        if self.path == "/reminders/sync":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._reply(200, json.dumps(reminders_sync(body.get("tasks") or [])).encode())
            except Exception as e:
                self._reply(500, json.dumps({"error": {"message": str(e)}}).encode())
            return
        if self.path == "/activity":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                act_set_enabled(body.get("enabled"))
                if ACT["enabled"]:
                    act_sample_once()          # immediate sample → triggers permission prompt now
                self._reply(200, json.dumps(
                    {"ok": True, "enabled": ACT["enabled"], "permission": ACT["permission"]}).encode())
            except Exception as e:
                self._reply(500, json.dumps({"error": {"message": str(e)}}).encode())
            return
        if self.path == "/state":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                saved_at = save_state(body.get("state") or {})
                self._reply(200, json.dumps({"ok": True, "savedAt": saved_at}).encode())
            except Exception as e:
                self._reply(500, json.dumps({"error": {"message": str(e)}}).encode())
            return
        self.forward("POST")

    def forward(self, method):
        target = self.headers.get("x-stride-target", "")
        if not target.startswith(("https://", "http://")):
            self._reply(400, b'{"error":{"message":"missing or invalid x-stride-target header"}}')
            return
        url = target.rstrip("/") + self.path
        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
        req = urllib.request.Request(url, data=body, method=method)
        
        # Forward all headers except hop-by-hop and local proxy headers
        skip_headers = {"host", "connection", "content-length", "x-stride-target", 
                        "origin", "accept-encoding", "user-agent",
                        "access-control-request-headers", "access-control-request-method"}
        for k, v in self.headers.items():
            if k.lower() not in skip_headers:
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data, code = r.read(), r.getcode()
                ctype = r.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            data, code = e.read(), e.code
            ctype = e.headers.get("Content-Type", "application/json")
        except Exception as e:
            data = json.dumps({"error": {"message": "helper: " + str(e)}}).encode()
            code, ctype = 502, "application/json"
        self._reply(code, data, ctype)


"""
Activity awareness (opt-in) — samples the frontmost app + window title every
few seconds so Stride's AI can remind you what you left unfinished. All data
stays in stride.db on this machine. Toggled from Stride's Settings.
Requires macOS Automation + Accessibility permission for python3 (one prompt).
"""
ACT = {"enabled": False, "stop": False, "permission": "unknown", "last_cleanup": 0.0}
ACT_INTERVAL = float(os.environ.get("STRIDE_ACT_INTERVAL", "15"))

ACT_SCRIPT = '''
tell application "System Events"
  set p to first process whose frontmost is true
  set appName to name of p
  set winTitle to ""
  try
    set winTitle to name of front window of p
  end try
end tell
appName & "|" & winTitle
'''


def get_idle_seconds():
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                return int(line.split("=")[-1].strip()) / 1e9
    except Exception:
        pass
    return 0


def act_sample_once():
    if get_idle_seconds() > 120:          # user is away — don't record
        return
    p = subprocess.run(["osascript", "-e", ACT_SCRIPT],
                       capture_output=True, text=True, timeout=15)
    if p.returncode != 0:
        err = (p.stderr or "").lower()
        ACT["permission"] = "denied" if ("not allowed" in err or "assistive" in err
                                         or "1743" in err or "-25211" in err) else "error"
        return
    ACT["permission"] = "ok"
    app, _, title = p.stdout.strip().partition("|")
    if not app.strip():
        return
    now = time.time()
    with DB_LOCK, db_conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS activity(ts INTEGER, app TEXT, title TEXT)")
        c.execute("INSERT INTO activity VALUES (?,?,?)",
                  (int(now), app.strip()[:60], title.strip()[:150]))
        if now - ACT["last_cleanup"] > 3600:
            c.execute("DELETE FROM activity WHERE ts < ?", (int(now) - 14 * 86400,))
            ACT["last_cleanup"] = now


def act_loop():
    while not ACT["stop"]:
        if ACT["enabled"]:
            try:
                act_sample_once()
            except Exception:
                pass
        time.sleep(ACT_INTERVAL)


def act_set_enabled(on):
    ACT["enabled"] = bool(on)
    with DB_LOCK, db_conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT OR REPLACE INTO meta VALUES ('activityEnabled', ?)",
                  (json.dumps(bool(on)),))


def activity_summary(hours=12):
    since = int(time.time()) - int(hours) * 3600
    with DB_LOCK, db_conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS activity(ts INTEGER, app TEXT, title TEXT)")
        rows = list(c.execute(
            "SELECT ts, app, title FROM activity WHERE ts >= ? ORDER BY ts", (since,)))
    sessions = []
    for ts, app, title in rows:
        last = sessions[-1] if sessions else None
        if last and last["app"] == app and last["title"] == title and ts - last["end"] <= 300:
            last["end"] = ts
        else:
            sessions.append({"app": app, "title": title, "start": ts, "end": ts})
    for s in sessions:
        s["mins"] = max(1, round((s["end"] - s["start"]) / 60))
    apps = {}
    for s in sessions:
        apps[s["app"]] = apps.get(s["app"], 0) + s["mins"]
    top = sorted(apps.items(), key=lambda x: -x[1])[:8]
    return {"enabled": ACT["enabled"], "permission": ACT["permission"],
            "samples": len(rows),
            "topApps": [{"app": a, "mins": m} for a, m in top],
            "sessions": [s for s in sessions if s["mins"] >= 8][-20:]}


"""
Apple Reminders sync — mirrors Stride's plan into a "Stride" list in
Reminders.app, which iCloud pushes to iPhone/iPad/Watch. Two-way: reminders
checked off on the phone are reported back so Stride can complete the task.
Requires one Automation permission prompt (python3 → Reminders).
"""

def _as_escape(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


REM_READ_SCRIPT = '''
tell application "Reminders"
  if not (exists list "Stride") then make new list with properties {name:"Stride"}
  set out to ""
  repeat with r in (reminders of list "Stride")
    set b to body of r
    if b is missing value then set b to ""
    set out to out & b & "||" & (completed of r) & "||" & (name of r) & linefeed
  end repeat
end tell
out
'''


def reminders_sync(tasks):
    """tasks: [{id, title, due(iso), offset(int days from today)}]. Returns dict."""
    # 1. read what's currently in the Stride list
    p = subprocess.run(["osascript", "-e", REM_READ_SCRIPT],
                       capture_output=True, text=True, timeout=90)
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        hint = " — allow python3 → Reminders in System Settings → Privacy → Automation" \
            if ("not allowed" in err.lower() or "-1743" in err) else ""
        return {"error": {"message": "Reminders access failed: " + err[:160] + hint}}
    existing = {}          # stride_id -> {body, completed, name, due}
    for line in p.stdout.splitlines():
        parts = line.split("||", 2)
        if len(parts) != 3 or not parts[0].startswith("stride:"):
            continue
        body, completed, name = parts
        sid = body.split("|")[0][7:]
        due = body.split("|due:")[1] if "|due:" in body else ""
        existing[sid] = {"body": body, "completed": completed.strip() == "true",
                         "name": name, "due": due}

    desired = {t["id"]: t for t in tasks if t.get("id") and t.get("title")}
    completed_ids = [sid for sid, e in existing.items() if e["completed"]]

    delete_bodies, creates = [], []
    for sid, e in existing.items():
        d = desired.get(sid)
        stale = d and (e["name"] != d["title"] or e["due"] != d["due"])
        if e["completed"] or not d or stale:
            delete_bodies.append(e["body"])
        if d and stale and not e["completed"]:
            creates.append(d)                     # recreate with fresh title/date
    for sid, d in desired.items():
        if sid not in existing and sid not in completed_ids:
            creates.append(d)

    # 2. apply the diff in one script
    ops = ['tell application "Reminders"', '  set L to list "Stride"']
    for b in delete_bodies:
        ops.append('  delete (reminders of L whose body = "%s")' % _as_escape(b))
    for i, t in enumerate(creates):
        off = max(0, int(t.get("offset") or 0))
        ops.append('  set d%d to (current date)' % i)
        ops.append('  set time of d%d to 32400' % i)          # 09:00
        ops.append('  make new reminder at end of L with properties '
                   '{name:"%s", body:"stride:%s|due:%s", due date:(d%d + (%d * days))}'
                   % (_as_escape(t["title"]), _as_escape(t["id"]),
                      _as_escape(t.get("due", "")), i, off))
    ops.append('end tell')
    if len(ops) > 3 or delete_bodies:
        p2 = subprocess.run(["osascript", "-e", "\n".join(ops)],
                            capture_output=True, text=True, timeout=120)
        if p2.returncode != 0:
            return {"error": {"message": "Reminders update failed: " + (p2.stderr or "")[:160]}}
    return {"ok": True, "completed": completed_ids,
            "created": len(creates), "deleted": len(delete_bodies), "count": len(desired)}


CAL_CACHE = {"ts": 0.0, "data": None}

CAL_SCRIPT = '''
set startD to (current date) - (1 * days)
set endD to (current date) + (14 * days)
set out to ""
tell application "Calendar"
  repeat with c in calendars
    try
      repeat with e in (every event of c whose start date is greater than or equal to startD and start date is less than or equal to endD)
        set sd to start date of e
        set dur to ((end date of e) - sd)
        set out to out & (year of sd) & "-" & ((month of sd) as integer) & "-" & (day of sd) & "|" & (time of sd) & "|" & dur & "|" & (summary of e) & linefeed
      end repeat
    end try
  end repeat
end tell
out
'''


def get_calendar_events():
    """Read the next two weeks of events from macOS Calendar.app.

    First call triggers a one-time macOS permission prompt
    ("python3 wants to control Calendar"). Results cached 15 minutes.
    """
    now = time.time()
    if CAL_CACHE["data"] is not None and now - CAL_CACHE["ts"] < 900:
        return CAL_CACHE["data"]
    try:
        p = subprocess.run(["osascript", "-e", CAL_SCRIPT],
                           capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return {"error": {"message": "osascript not found — macOS Calendar needs a Mac"}}
    except subprocess.TimeoutExpired:
        return {"error": {"message": "Calendar.app query timed out — try an ICS URL instead"}}
    if p.returncode != 0:
        return {"error": {"message": "Calendar access failed (check System Settings → Privacy → Automation): "
                                     + p.stderr.strip()[:180]}}
    events = []
    for line in p.stdout.splitlines():
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        try:
            y, m, d = [int(x) for x in parts[0].split("-")]
            secs = int(float(parts[1]))
            dur = int(float(parts[2]))
            allday = secs == 0 and dur >= 86400
            events.append({
                "date": "%04d-%02d-%02d" % (y, m, d),
                "time": None if allday else "%02d:%02d" % (secs // 3600, (secs % 3600) // 60),
                "mins": 0 if allday else min(dur // 60, 1440),
                "title": parts[3].strip()[:120],
            })
        except (ValueError, IndexError):
            continue
    data = {"events": events}
    CAL_CACHE["ts"], CAL_CACHE["data"] = now, data
    return data


if __name__ == "__main__":
    db_init()
    try:
        with DB_LOCK, db_conn() as _c:
            _r = _c.execute("SELECT value FROM meta WHERE key='activityEnabled'").fetchone()
            ACT["enabled"] = bool(json.loads(_r[0])) if _r else False
    except Exception:
        pass
    threading.Thread(target=act_loop, daemon=True).start()
    print("Stride helper listening on http://127.0.0.1:%d  (Ctrl-C to stop)" % PORT)
    print("SQLite database: %s" % DB_PATH)
    print("Activity awareness: %s" % ("ON" if ACT["enabled"] else "off (enable in Stride settings)"))
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
