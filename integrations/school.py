"""School: Canvas (official API, fast) + Infinite Campus (saved browser login).

Canvas   - set CANVAS_BASE_URL and sign in through ClassLink with ic-login.
           A Canvas API token is optional; the shared browser session is used.
Infinite - set IC_BASE_URL. Canvas - set CANVAS_BASE_URL. Both use the
           same visible ClassLink sign-in and saved browser profile. A Canvas
           token is optional. No password is stored in code or chat.

Grade and assignment reads are read-only. Portal navigation opens a visible tab.
"""
import datetime as dt
import json
import re
import sys
import time
from contextlib import contextmanager

import requests

from config import (CANVAS_BASE_URL, CANVAS_TOKEN, CLASSLINK_URL, DATA_DIR,
                    EDITH_CHROME_CDP_URL, IC_BASE_URL, STUDENT_SUPPORT_TIME_URL)
from integrations._common import tool

CACHE = DATA_DIR / "school_cache.json"
SCHOOL_PROFILE = DATA_DIR / "school_profile"
IC_PROFILE = SCHOOL_PROFILE  # compatibility with the previous Infinite Campus profile
_CDP_PLAYWRIGHT = None
_CDP_BROWSER = None


def _school_context(pw=None, headless=True):
    """Use EDITH's dedicated Chrome session when configured; else local Playwright profile."""
    global _CDP_PLAYWRIGHT, _CDP_BROWSER
    if EDITH_CHROME_CDP_URL:
        if _CDP_BROWSER is not None and not _CDP_BROWSER.is_connected():
            try:
                _CDP_PLAYWRIGHT.stop()
            except Exception:
                pass
            _CDP_PLAYWRIGHT = None
            _CDP_BROWSER = None
        if _CDP_BROWSER is None:
            from playwright.sync_api import sync_playwright
            _CDP_PLAYWRIGHT = sync_playwright().start()
            try:
                _CDP_BROWSER = _CDP_PLAYWRIGHT.chromium.connect_over_cdp(EDITH_CHROME_CDP_URL)
            except Exception:
                _CDP_PLAYWRIGHT.stop()
                _CDP_PLAYWRIGHT = None
                raise RuntimeError("EDITH Chrome is not running. Start it with start_edith_browser.bat.")
        if not _CDP_BROWSER.contexts:
            raise RuntimeError("Connected EDITH Chrome has no browser context.")
        return _CDP_BROWSER.contexts[0], False
    if pw is None:
        raise RuntimeError("Playwright is not available.")
    return pw.chromium.launch_persistent_context(str(SCHOOL_PROFILE), headless=headless), True


@contextmanager
def _school_session(headless=True):
    """Yield the shared CDP context or own and close a local Playwright context."""
    if EDITH_CHROME_CDP_URL:
        ctx, _ = _school_context(headless=headless)
        yield ctx
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx, owned = _school_context(pw, headless=headless)
        try:
            yield ctx
        finally:
            if owned:
                ctx.close()

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
    if not CANVAS_BASE_URL:
        raise RuntimeError("Canvas not set up: put CANVAS_BASE_URL in .env and sign in through ClassLink.")
    if not CANVAS_TOKEN and not EDITH_CHROME_CDP_URL and not SCHOOL_PROFILE.exists():
        raise RuntimeError("No saved ClassLink session. Start EDITH Chrome and run ic-login.")


def _portal_get(url, params=None, headers=None):
    """GET with the shared ClassLink browser cookies, optionally using a Canvas token."""
    with _school_session(headless=True) as ctx:
        response = ctx.request.get(url, params=params, headers=headers or {}, timeout=20000)
        if response.status == 401:
            raise RuntimeError("School portal rejected the saved ClassLink session (401). Run ic-login again.")
        if not response.ok:
            raise RuntimeError(f"School portal request failed (HTTP {response.status}).")
        return {"status": response.status, "headers": dict(response.headers), "data": response.json()}


def _canvas_get(path, params=None, pages=3):
    if not CANVAS_BASE_URL:
        raise RuntimeError("Canvas not set up: put CANVAS_BASE_URL in .env.")
    url = CANVAS_BASE_URL.rstrip("/") + "/api/v1" + path
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"} if CANVAS_TOKEN else {}
    out = []
    for _ in range(pages):
        response = _portal_get(url, params=params, headers=headers)
        data = response["data"]
        out.extend(data if isinstance(data, list) else [data])
        link = response["headers"].get("link", "")
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if not match:
            break
        url, params = match.group(1), None
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


def grade_extreme(direction="lowest"):
    """Return the highest or lowest numeric current grade without LLM arithmetic."""
    if direction not in ("lowest", "highest"):
        return "Choose lowest or highest."
    try:
        rows = ic_grades()
    except Exception:
        rows = []
    if not rows:
        try:
            rows = canvas_grades()
        except Exception:
            rows = []
    numeric = []
    for row in rows:
        try:
            score = float(str(row.get("score", "")).rstrip("%"))
        except (TypeError, ValueError):
            continue
        numeric.append((score, row))
    if not numeric:
        return "No numeric current grades are available."
    score, row = (min if direction == "lowest" else max)(numeric, key=lambda item: item[0])
    letter = row.get("letter")
    suffix = f" ({letter})" if letter else ""
    return f"{direction.title()} current grade: {row['course']} — {score:.1f}%{suffix} [{row['source']}]."


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
    if not EDITH_CHROME_CDP_URL and not IC_PROFILE.exists():
        raise RuntimeError("No saved Infinite Campus login. Start EDITH Chrome and run ic-login.")


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
    r = _portal_get(IC_BASE_URL.rstrip("/") + "/campus/resources/portal/grades")
    if "json" not in r["headers"].get("content-type", ""):
        raise RuntimeError("Infinite Campus session expired - run: python -m integrations.school ic-login")
    rows = _walk_ic(r["data"])
    # keep only the latest grading task per course (the current term)
    latest = {}
    for row in rows:
        latest[row["course"]] = row
    return list(latest.values())


def ic_login():
    """Use EDITH Chrome, let the user navigate from ClassLink, then verify portal access."""
    if not IC_BASE_URL and not CANVAS_BASE_URL:
        print("Set IC_BASE_URL and/or CANVAS_BASE_URL in .env first.")
        return False
    SCHOOL_PROFILE.mkdir(parents=True, exist_ok=True)
    with _school_session(headless=False) as ctx:
        page = next((p for p in ctx.pages if "classlink.com" in p.url), None)
        if page is None:
            page = ctx.new_page()
            page.goto(CLASSLINK_URL, wait_until="domcontentloaded")
        print("Sign in to ClassLink, then use the cursor to open Canvas and Infinite Campus from its dashboard.")
        print("Leave the school tabs open. EDITH will verify read-only access after you continue.")
        print("Do not share your password or MFA code in chat.")
        input("When you have opened both services, press Enter here...")
        checks = []
        if IC_BASE_URL:
            try:
                r = ctx.request.get(IC_BASE_URL.rstrip("/") + "/campus/resources/portal/grades", timeout=20000)
                checks.append(("Infinite Campus", r.status == 200 and "json" in r.headers.get("content-type", "")))
            except Exception:
                checks.append(("Infinite Campus", False))
        if CANVAS_BASE_URL:
            try:
                r = ctx.request.get(CANVAS_BASE_URL.rstrip("/") + "/api/v1/courses",
                                    params={"enrollment_state": "active", "per_page": 1}, timeout=20000)
                checks.append(("Canvas", r.status == 200 and "json" in r.headers.get("content-type", "")))
            except Exception:
                checks.append(("Canvas", False))
        for service, ready in checks:
            print(f"{service}: {'ready' if ready else 'not verified'}")
    return bool(checks) and all(ready for _, ready in checks)


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


def upcoming_work(days=7, course=""):
    try:
        items = canvas_upcoming(days)
        if course:
            match = find_course(course)
            if not match:
                return f"No Canvas class matches '{course}'."
            name = match["name"].lower()
            items = [i for i in items if name in i["course"].lower()
                     or i["course"].lower() in name]
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


def open_school_portal(portal):
    """Open a configured school service in a new visible EDITH Chrome tab."""
    key = re.sub(r"[^a-z]+", " ", str(portal).lower()).strip()
    portals = {
        "classlink": ("ClassLink", CLASSLINK_URL),
        "canvas": ("Canvas", CANVAS_BASE_URL),
        "infinite campus": ("Infinite Campus", IC_BASE_URL),
        "ic": ("Infinite Campus", IC_BASE_URL),
        "student support time": ("Student Support Time", STUDENT_SUPPORT_TIME_URL),
        "dawg time": ("Student Support Time", STUDENT_SUPPORT_TIME_URL),
    }
    target = portals.get(key)
    if target is None:
        return "Choose ClassLink, Canvas, Infinite Campus, or Student Support Time."
    name, url = target
    if not url:
        return f"{name} is not configured in .env."
    from integrations.browser import browser_open
    return browser_open(url)


def support_time_status(date=""):
    """Read the selected Dawg Time date, available sessions, and existing sign-ups."""
    from integrations.browser import _STATE, _page

    page = _page()
    context = _STATE["context"]
    pages = [p for p in context.pages if "forsyth.studentsupporttime.com" in p.url]
    if not pages:
        opened = open_school_portal("Student Support Time")
        page = _STATE["page"]
        if not page:
            return opened
    else:
        page = pages[-1]
        _STATE["page"] = page
        page.bring_to_front()

    try:
        page.wait_for_function("document.body && document.body.innerText.includes('Dawg Time')", timeout=15000)
        page.locator("li.list-group-item.clearfix.hover").first.wait_for(state="attached", timeout=10000)
    except Exception:
        return "Student Support Time is open, but its dashboard is not ready. Sign in through ClassLink and try again."

    if date:
        query = re.sub(r"\s+", " ", str(date).strip().lower())
        try:
            parsed = dt.date.fromisoformat(query)
            query = f"{parsed.strftime('%b').lower()} {parsed.day}"
        except ValueError:
            pass
        matches = []
        for link in page.locator("a.btn-wide").all():
            if not link.is_visible():
                continue
            label = re.sub(r"\s+", " ", (link.text_content() or "").strip().lower())
            if query in label:
                matches.append(link)
        if not matches:
            return f"I couldn't find '{date}' in the visible Student Support Time calendar."
        matches[0].click(timeout=5000)
        page.wait_for_timeout(700)

    selected_date = "the currently selected day"
    for link in page.locator("a.btn-wide").all():
        if not link.is_visible():
            continue
        classes = link.get_attribute("class") or ""
        if "text-bold" in classes and "btn-o" not in classes:
            selected_date = re.sub(r"\s+", " ", (link.text_content() or "").strip())
            selected_date = re.sub(r"^DT\s*", "", selected_date, flags=re.I)
            break

    sessions = []
    for card in page.locator("li.list-group-item.clearfix.hover").all():
        if not card.is_visible():
            continue
        lines = [line.strip() for line in card.inner_text().splitlines() if line.strip()]
        if not lines or "No Session" in lines:
            continue
        detail = " — ".join(lines[1:]) if len(lines) > 1 else lines[0]
        sessions.append(detail[:260])

    signed_up = set()
    for card in page.locator("li.openSession").all():
        if not card.is_visible():
            continue
        lines = [line.strip() for line in card.inner_text().splitlines() if line.strip()]
        if lines and "Signed Up" in lines[0]:
            detail = " — ".join(line for line in lines[1:3] if line and line != "Details")
            if detail:
                signed_up.add(detail[:180])

    output = [f"Dawg Time — {selected_date}"]
    if sessions:
        output.append("Sessions shown:")
        output.extend(f"- {item}" for item in sessions)
    else:
        output.append("No sessions are shown for this date.")
    if signed_up:
        output.append("Already signed up:")
        output.extend(f"- {item}" for item in sorted(signed_up))
        check_ins = [button for button in page.locator("li.openSession button").all() if button.is_visible()]
        output.append(f"Check-in controls visible: {len(check_ins)}")
    return "\n".join(output)


TOOLS = [
    tool("get_grades", "Current grades (Infinite Campus + Canvas). Optionally one class, e.g. 'chem'.",
         {"course": {"type": "string"}}, [], grades),
    tool("grade_extreme", "Accurately find the highest or lowest current numeric grade.",
         {"direction": {"type": "string", "enum": ["lowest", "highest"]}},
         ["direction"], grade_extreme),
    tool("upcoming_work", "Assignments due in the next N days across all classes or one named class (Canvas).",
         {"days": {"type": "integer"}, "course": {"type": "string"}}, [], upcoming_work),
    tool("class_check", "One class: grade, work due, latest announcement. Use for 'check chem'.",
         {"course": {"type": "string", "description": "chem, csa, lang, apush, physics, stats, precalc"}},
         ["course"], class_check),
    tool("class_materials", "Modules and recent files for a class (Canvas).",
         {"course": {"type": "string"}}, ["course"], class_materials),
    tool("open_school_portal", "Open a school service in a new visible EDITH Chrome tab.",
         {"portal": {"type": "string", "enum": ["ClassLink", "Canvas", "Infinite Campus", "Student Support Time"]}},
         ["portal"], open_school_portal),
    tool("support_time_status", "Read the selected Student Support Time date, session availability, and existing sign-ups. This does not change sign-ups.",
         {"date": {"type": "string", "description": "Optional visible date, for example Oct 30 or 2026-10-30"}},
         [], support_time_status),
]

if __name__ == "__main__":
    if sys.argv[1:] == ["ic-login"]:
        ic_login()
    else:
        print(grades())
