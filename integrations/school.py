"""School: Canvas (official API, fast) + Infinite Campus (saved browser login).

Canvas   - set CANVAS_BASE_URL (e.g. https://forsyth.instructure.com) and
           CANVAS_TOKEN (Canvas > Account > Settings > New Access Token).
Infinite - set IC_BASE_URL (your portal host, e.g. https://campus.forsyth.k12.ga.us)
Campus     then run ONCE:  python -m integrations.school ic-login
           You sign in yourself in a real window; the session is saved in
           data/ic_profile and reused headlessly. No password is ever stored
           in code, .env, or chat.

Nothing here clicks or submits anything: every tool is read-only.
"""
import datetime as dt
import json
import re
import sys
import time

import requests

from config import CANVAS_BASE_URL, CANVAS_TOKEN, DATA_DIR, IC_BASE_URL
from integrations._common import tool

CACHE = DATA_DIR / "school_cache.json"
IC_PROFILE = DATA_DIR / "ic_profile"

# spoken nicknames -> words that appear in the real course name
ALIASES = {
    "chem": "chemistry", "csa": "computer science", "cs": "computer science",
    "lang": "language", "apush": "history", "history": "history",
    "physics": "physics", "stats": "statistics", "stat": "statistics",
    "precalc": "precalculus", "pre-calc": "precalculus", "calc": "precalculus",
    "english": "language",
}


# ------------------------------------------------------------------ cache

def _load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(**kv):
    c = _load_cache()
    c.update(kv, ts=time.time())
    CACHE.write_text(json.dumps(c, indent=2), encoding="utf-8")


def cached_grades():
    return _load_cache().get("grades", [])


def cached_due():
    return _load_cache().get("due", [])


# ----------------------------------------------------------------- Canvas

def _canvas_ready():
    if not (CANVAS_BASE_URL and CANVAS_TOKEN):
        raise RuntimeError("Canvas not set up: put CANVAS_BASE_URL and CANVAS_TOKEN in .env "
                           "(Canvas > Account > Settings > New Access Token).")


def _canvas_get(path, params=None, pages=3):
    _canvas_ready()
    url = CANVAS_BASE_URL.rstrip("/") + "/api/v1" + path
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    out = []
    for _ in range(pages):
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 401:
            raise RuntimeError("Canvas rejected the token (401) - make a new one.")
        r.raise_for_status()
        data = r.json()
        out.extend(data if isinstance(data, list) else [data])
        nxt = r.links.get("next", {}).get("url")
        if not nxt:
            break
        url, params = nxt, None
    return out


def _courses():
    cs = _canvas_get("/courses", {"enrollment_state": "active", "include[]": ["total_scores"],
                                  "per_page": 50})
    return [c for c in cs if c.get("name") and not c.get("access_restricted_by_date")]


def find_course(query, courses=None):
    """Fuzzy course lookup: 'chem' -> AP Chemistry."""
    courses = courses or _courses()
    q = query.lower().strip()
    raw = set(re.findall(r"[a-z0-9\-]+", q)) - {"ap", "class", "the"}
    best, best_score = None, 0
    for c in courses:
        name = (c["name"] + " " + (c.get("course_code") or "")).lower()
        # a word counts if it, or its spoken-nickname expansion, appears in the course name
        score = sum(1 for w in raw if w in name or ALIASES.get(w, w) in name)
        if score > best_score:
            best, best_score = c, score
    return best


def canvas_grades():
    rows = []
    for c in _courses():
        enr = next((e for e in c.get("enrollments", []) if e.get("type") == "student"), {})
        score = enr.get("computed_current_score")
        if score is not None:
            rows.append({"course": c["name"], "score": score,
                         "letter": enr.get("computed_current_grade") or "", "source": "Canvas"})
    return rows


def canvas_upcoming(days=7):
    start = dt.date.today()
    items = _canvas_get("/planner/items", {
        "start_date": start.isoformat(),
        "end_date": (start + dt.timedelta(days=int(days))).isoformat(),
        "per_page": 50})
    out = []
    for it in items:
        p = it.get("plannable") or {}
        sub = it.get("submissions")
        done = isinstance(sub, dict) and (sub.get("submitted") or sub.get("excused"))
        due = p.get("due_at") or p.get("todo_date") or it.get("plannable_date")
        if not due or done or it.get("plannable_type") in ("announcement",):
            continue
        out.append({"course": it.get("context_name", "?"), "title": p.get("title", "?"),
                    "due": due, "points": p.get("points_possible")})
    return sorted(out, key=lambda x: x["due"])


# -------------------------------------------------------- Infinite Campus

def _ic_ready():
    if not IC_BASE_URL:
        raise RuntimeError("Infinite Campus not set up: put IC_BASE_URL in .env, then run "
                           "'python -m integrations.school ic-login' once.")
    if not IC_PROFILE.exists():
        raise RuntimeError("No saved Infinite Campus login. Run: python -m integrations.school ic-login")


def _walk_ic(node, term="", out=None):
    """Pull (course, task, percent, score) out of IC's portal JSON, whatever the nesting."""
    out = [] if out is None else out
    if isinstance(node, list):
        for x in node:
            _walk_ic(x, term, out)
    elif isinstance(node, dict):
        term = node.get("termName") or term
        if "courseName" in node and isinstance(node.get("gradingTasks"), list):
            for t in node["gradingTasks"]:
                pct = t.get("progressPercent", t.get("percent"))
                if pct is None and t.get("progressScore") is None and t.get("score") is None:
                    continue
                out.append({"course": node["courseName"], "term": term,
                            "task": t.get("taskName", ""), "score": pct,
                            "letter": t.get("progressScore") or t.get("score") or "", "source": "IC"})
        else:
            for v in node.values():
                _walk_ic(v, term, out)
    return out


def ic_grades():
    _ic_ready()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(IC_PROFILE), headless=True)
        try:
            r = ctx.request.get(IC_BASE_URL.rstrip("/") + "/campus/resources/portal/grades", timeout=20000)
            ctype = r.headers.get("content-type", "")
            if r.status != 200 or "json" not in ctype:
                raise RuntimeError("Infinite Campus session expired - run: "
                                   "python -m integrations.school ic-login")
            rows = _walk_ic(r.json())
        finally:
            ctx.close()
    # keep only the latest grading task per course (the current term)
    latest = {}
    for row in rows:
        latest[row["course"]] = row
    return list(latest.values())


def ic_login():
    """Open a real window so YOU sign in once; the session is saved for headless use."""
    if not IC_BASE_URL:
        print("Set IC_BASE_URL in .env first.")
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(IC_PROFILE), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(IC_BASE_URL.rstrip("/") + "/campus/")
        input("Sign in to Infinite Campus in the window, then press Enter here...")
        ctx.close()
    print("Saved. JARVIS can now read your grades.")


# -------------------------------------------------------------- tool glue

def _fmt_grade(r):
    s = r["score"]
    s = f"{s:.1f}%" if isinstance(s, (int, float)) else str(s)
    return f"{r['course']}: {s} {r.get('letter') or ''} [{r['source']}]".replace("  ", " ")


def grades(course=""):
    """Official grades. IC is the real gradebook; Canvas fills in or backs it up."""
    rows, errs = [], []
    for name, fn in (("Infinite Campus", ic_grades), ("Canvas", canvas_grades)):
        try:
            rows += fn()
        except Exception as e:
            errs.append(f"{name}: {e}")
    if rows:
        _save_cache(grades=rows)
    if course:
        raw = set(re.findall(r"[a-z0-9]+", course.lower())) - {"ap", "class"}
        rows = [r for r in rows if any(
            w in r["course"].lower() or ALIASES.get(w, w) in r["course"].lower() for w in raw)]
    out = "\n".join(_fmt_grade(r) for r in rows) or "No grades found."
    return out + ("\n\nProblems:\n" + "\n".join(errs) if errs else "")


def upcoming_work(days=7):
    try:
        items = canvas_upcoming(days)
    except Exception as e:
        return f"Couldn't fetch assignments: {e}"
    _save_cache(due=items)
    if not items:
        return f"Nothing due in the next {int(days)} days."
    return "\n".join(f"{i['due'][:10]} {i['course']}: {i['title']}"
                     + (f" ({i['points']} pts)" if i.get("points") else "") for i in items)


def class_check(course):
    """One class: its grade, upcoming work, and latest announcement."""
    try:
        cs = _courses()
        c = find_course(course, cs)
        if not c:
            return f"No class matches '{course}'. I see: " + ", ".join(x["name"] for x in cs)
        parts = [f"== {c['name']} =="]
        parts.append("Grade: " + (grades(course).split("\n\n")[0] or "n/a"))
        due = [i for i in canvas_upcoming(14) if c["name"] in i["course"] or i["course"] in c["name"]]
        parts.append("Due next 14 days:\n" + ("\n".join(f"  {i['due'][:10]} {i['title']}" for i in due)
                                               or "  nothing"))
        ann = _canvas_get("/announcements", {"context_codes[]": f"course_{c['id']}", "per_page": 1}, pages=1)
        if ann:
            txt = re.sub(r"<[^>]+>", " ", ann[0].get("message") or "")
            parts.append(f"Latest announcement: {ann[0].get('title')} - {' '.join(txt.split())[:300]}")
        return "\n".join(parts)
    except Exception as e:
        return f"class_check failed: {e}"


def class_materials(course):
    """Modules and recent files for a class (names + links, nothing downloaded)."""
    try:
        c = find_course(course)
        if not c:
            return f"No class matches '{course}'."
        mods = _canvas_get(f"/courses/{c['id']}/modules", {"include[]": "items", "per_page": 20}, pages=1)
        lines = [f"== {c['name']} - materials =="]
        for m in mods[:8]:
            lines.append(f"{m['name']}:")
            for it in (m.get("items") or [])[:6]:
                lines.append(f"  - {it.get('title')} ({it.get('type')})")
        try:
            files = _canvas_get(f"/courses/{c['id']}/files",
                                {"sort": "updated_at", "order": "desc", "per_page": 8}, pages=1)
            if files:
                lines.append("Recent files:")
                lines += [f"  - {f['display_name']}: {f.get('url', '').split('?')[0]}" for f in files]
        except Exception:
            pass  # many teachers hide the Files tab
        return "\n".join(lines)
    except Exception as e:
        return f"class_materials failed: {e}"


TOOLS = [
    tool("get_grades", "Current grades (Infinite Campus + Canvas). Optionally one class, e.g. 'chem'.",
         {"course": {"type": "string"}}, [], grades),
    tool("upcoming_work", "Assignments due in the next N days across all classes (Canvas).",
         {"days": {"type": "integer"}}, [], upcoming_work),
    tool("class_check", "One class: grade, work due, latest announcement. Use for 'check chem'.",
         {"course": {"type": "string", "description": "chem, csa, lang, apush, physics, stats, precalc"}},
         ["course"], class_check),
    tool("class_materials", "Modules and recent files for a class (Canvas).",
         {"course": {"type": "string"}}, ["course"], class_materials),
]

if __name__ == "__main__":
    if sys.argv[1:] == ["ic-login"]:
        ic_login()
    else:
        print(grades())
