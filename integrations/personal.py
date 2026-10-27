"""Personal tools: countdowns, study timer, quick-launch workflows, briefings.

All state lives in data/*.json so you can hand-edit it:
  data/countdowns.json  data/study.json  data/workflows.json
"""
import datetime as dt
import json
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from config import CANVAS_BASE_URL, DATA_DIR
from integrations._common import tool

_lock = threading.Lock()


# ------------------------------------------------------------ json helpers

def _read(name, default):
    f = DATA_DIR / name
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[personal] {name} unreadable ({e}); using defaults")
    return default


def _write(name, data):
    (DATA_DIR / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


# -------------------------------------------------------------- countdowns

DEFAULT_COUNTDOWNS = [{"name": "SAT", "date": "2026-12-05"}]


def _countdowns():
    return _read("countdowns.json", DEFAULT_COUNTDOWNS)


def countdown_rows():
    """[(name, days_left)] sorted soonest first, past events dropped."""
    today = dt.date.today()
    rows = []
    for c in _countdowns():
        try:
            d = (dt.date.fromisoformat(c["date"]) - today).days
        except Exception:
            continue
        if d >= 0:
            rows.append((c["name"], d))
    return sorted(rows, key=lambda r: r[1])


def countdowns():
    rows = countdown_rows()
    if not rows:
        return "No upcoming countdowns. Add one with add_countdown."
    return "\n".join(f"{n}: {d} day{'s' if d != 1 else ''} left" for n, d in rows)


def add_countdown(name, date):
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return "Date must be YYYY-MM-DD, e.g. 2026-12-05."
    with _lock:
        items = [c for c in _countdowns() if c["name"].lower() != name.lower()]
        items.append({"name": name, "date": date})
        _write("countdowns.json", items)
    return f"Added {name} on {date}."


def remove_countdown(name):
    with _lock:
        items = _countdowns()
        keep = [c for c in items if c["name"].lower() != name.lower()]
        if len(keep) == len(items):
            return f"No countdown called {name}."
        _write("countdowns.json", keep)
    return f"Removed {name}."


# ------------------------------------------------------------- study timer

def _study():
    return _read("study.json", {"active": None, "log": []})


def _alarm(subject, minutes):
    print(f"\n[JARVIS] {minutes}-minute {subject} session is up, sir.")
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(880, 300)
    except Exception:
        pass


def study_start(subject="study", minutes=0):
    minutes = int(minutes or 0)
    with _lock:
        s = _study()
        if s["active"]:
            return (f"Already timing {s['active']['subject']} since "
                    f"{s['active']['start'][11:16]}. Stop it first.")
        s["active"] = {"subject": subject, "start": dt.datetime.now().isoformat(timespec="seconds")}
        _write("study.json", s)
    if minutes > 0:
        t = threading.Timer(minutes * 60, _alarm, args=(subject, minutes))
        t.daemon = True
        t.start()
    return f"Timer started for {subject}" + (f" ({minutes} min alarm)." if minutes else ".")


def study_stop(note=""):
    with _lock:
        s = _study()
        a = s["active"]
        if not a:
            return "No timer running."
        start = dt.datetime.fromisoformat(a["start"])
        mins = round((dt.datetime.now() - start).total_seconds() / 60, 1)
        s["log"].append({"subject": a["subject"], "date": start.date().isoformat(),
                         "minutes": mins, "note": note})
        s["active"] = None
        _write("study.json", s)
    return f"Logged {mins} min of {a['subject']}."


def study_totals(days=7):
    """({subject: minutes}, total) over the last `days` days incl. today."""
    cutoff = (dt.date.today() - dt.timedelta(days=int(days) - 1)).isoformat()
    by = {}
    for e in _study()["log"]:
        if e["date"] >= cutoff:
            by[e["subject"]] = by.get(e["subject"], 0) + e["minutes"]
    return by, sum(by.values())


def study_summary(days=7):
    by, total = study_totals(days)
    active = _study()["active"]
    head = f"Last {int(days)} day(s): {round(total)} min total."
    lines = [f"  {k}: {round(v)} min" for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    if active:
        lines.append(f"  (running now: {active['subject']} since {active['start'][11:16]})")
    return "\n".join([head] + lines)


# --------------------------------------------------------------- workflows

def _default_workflows():
    school = []
    if CANVAS_BASE_URL:
        school.append(CANVAS_BASE_URL)
    return {
        "coding": {"apps": ["vscode", "terminal"], "urls": ["https://github.com/sarthakbagal23"]},
        "school": {"apps": [], "urls": school + ["https://www.google.com/search?q=forsyth+county+infinite+campus+portal"]},
        "study": {"apps": ["spotify"], "urls": school},
        "usaco": {"apps": ["vscode"], "urls": ["https://usaco.org/", "https://usaco.guide/"]},
        "sat": {"apps": [], "urls": ["https://www.khanacademy.org/", "https://bluebook.collegeboard.org/"]},
        "deca": {"apps": ["powerpoint"], "urls": ["https://www.deca.org/"]},
    }


def workflows():
    return {**_default_workflows(), **_read("workflows.json", {})}


def start_workflow(name):
    from tools import open_app  # lazy: tools imports this package at import time
    wf = workflows()
    key = name.lower().replace(" mode", "").strip()
    if key not in wf:
        return f"No workflow called {name}. I have: {', '.join(sorted(wf))}."
    w = wf[key]
    for a in w.get("apps", []):
        open_app(a)
    for u in w.get("urls", []):
        webbrowser.open(u)
    return f"{key.title()} mode launched: {', '.join(w.get('apps', []) + w.get('urls', [])) or 'nothing configured'}."


# --------------------------------------------------------------- briefings

def _safe(fn, label):
    try:
        return fn()
    except Exception as e:
        return f"{label} unavailable ({e})"


_wx = {"t": 0.0, "v": ""}


def _weather_cached():
    """Widget refreshes every minute; weather only needs to refresh every 10."""
    import time
    import tools as T
    if time.time() - _wx["t"] > 600 or not _wx["v"]:
        _wx.update(t=time.time(), v=T.get_weather())
    return _wx["v"]


def dashboard_data():
    """Everything the widget/dashboard shows. Each part fails on its own."""
    import tools as T
    from integrations import school
    by, total = study_totals(1)
    return {
        "time": dt.datetime.now().strftime("%a %b %d  %I:%M %p"),
        "weather": _safe(_weather_cached, "weather"),
        "countdowns": countdown_rows(),
        "study_today_min": round(total),
        "study_active": _study()["active"],
        "grades": school.cached_grades(),
        "due": school.cached_due(),
    }


def morning_briefing():
    """One call, everything for the day, fetched in parallel."""
    import tools as T
    from integrations import school
    jobs = {
        "weather": lambda: T.get_weather(),
        "countdowns": countdowns,
        "due": lambda: school.upcoming_work(days=3),
        "grades": lambda: school.grades(),
        "study": lambda: study_summary(1),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(_safe, f, k) for k, f in jobs.items()}
        out = {k: f.result() for k, f in futs.items()}
    return (f"{T.get_time()}\n\nWEATHER: {out['weather']}\n\nCOUNTDOWNS:\n{out['countdowns']}\n\n"
            f"DUE SOON:\n{out['due']}\n\nGRADES:\n{out['grades']}\n\nSTUDY TODAY: {out['study']}")


def weekend_plan():
    """Everything coming up across every class, for planning the weekend."""
    from integrations import school
    return (f"{countdowns()}\n\nUPCOMING WORK (next 10 days):\n{school.upcoming_work(days=10)}\n\n"
            f"GRADES:\n{school.grades()}\n\nSTUDY LAST 7 DAYS:\n{study_summary(7)}\n\n"
            "Use this to propose a plan for each class, prioritizing the lowest grades "
            "and nearest deadlines, and leave room for SAT prep and USACO.")


TOOLS = [
    tool("countdowns", "Days left until the SAT and other saved events.", {}, [], countdowns),
    tool("add_countdown", "Save a countdown to a date.",
         {"name": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"}},
         ["name", "date"], add_countdown),
    tool("remove_countdown", "Delete a saved countdown.",
         {"name": {"type": "string"}}, ["name"], remove_countdown),
    tool("study_start", "Start the study/focus timer. Optional alarm in minutes.",
         {"subject": {"type": "string", "description": "e.g. USACO, AP Chem, SAT"},
          "minutes": {"type": "integer"}}, [], study_start),
    tool("study_stop", "Stop the study timer and log the session.",
         {"note": {"type": "string"}}, [], study_stop),
    tool("study_summary", "Study time logged over the last N days.",
         {"days": {"type": "integer"}}, [], study_summary),
    tool("start_workflow", "Launch a mode: coding, school, study, usaco, sat, deca.",
         {"name": {"type": "string"}}, ["name"], start_workflow),
    tool("morning_briefing", "Full daily briefing: weather, countdowns, due work, grades, study.",
         {}, [], morning_briefing),
    tool("weekend_plan", "Gather everything across all classes to plan the weekend.",
         {}, [], weekend_plan),
]
