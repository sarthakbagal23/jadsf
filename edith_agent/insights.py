"""Grade history and the "big picture". Everything here stays on this laptop."""
import datetime as dt
import json
import time

from config import DATA_DIR
from edith_agent import llm, privacy

HISTORY = DATA_DIR / "grades_history.json"
OPPS = DATA_DIR / "opportunities.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# ------------------------------------------------------------ grade history

def record_grades(rows, min_gap_hours=6):
    """Save a snapshot [{course, score, source}] unless one was saved very recently."""
    rows = [{"course": r["course"], "score": float(r["score"]), "source": r.get("source", "")}
            for r in rows if isinstance(r.get("score"), (int, float))]
    if not rows:
        return
    hist = _read(HISTORY, [])
    if hist and time.time() - hist[-1]["ts"] < min_gap_hours * 3600:
        merged = {r["course"]: r for r in hist[-1]["rows"]}   # an odd-day sweep must not erase the even classes
        merged.update({r["course"]: r for r in rows})
        hist[-1] = {"ts": time.time(), "rows": list(merged.values())}
    else:
        hist.append({"ts": time.time(), "rows": rows})
    HISTORY.write_text(json.dumps(hist[-60:], indent=1), encoding="utf-8")


def trends(min_days=2):
    """{course: (now, change)} comparing the latest snapshot with one at least `min_days` old."""
    hist = _read(HISTORY, [])
    if len(hist) < 2:
        return {}
    latest = hist[-1]
    old = next((h for h in reversed(hist[:-1]) if latest["ts"] - h["ts"] >= min_days * 86400), None)
    if not old:
        return {}
    before = {r["course"]: r["score"] for r in old["rows"]}
    return {r["course"]: (r["score"], round(r["score"] - before[r["course"]], 1))
            for r in latest["rows"] if r["course"] in before}


# ------------------------------------------------------------ opportunities

def load_opportunities():
    return _read(OPPS, [])


def save_opportunities(items):
    have = {o["url"]: o for o in load_opportunities() if o.get("url")}
    for o in items:
        if o.get("url"):
            have[o["url"]] = {**have.get(o["url"], {}), **o}
    OPPS.write_text(json.dumps(list(have.values()), indent=1), encoding="utf-8")


def _parse_date(s):
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(str(s).strip().replace("Sept", "Sep"), fmt).date()
        except ValueError:
            continue
    return None


def soonest_opportunities(days=45):
    today = dt.date.today()
    out = []
    for o in load_opportunities():
        d = _parse_date(o.get("deadline", ""))
        if d and 0 <= (d - today).days <= days:
            out.append(((d - today).days, o))
    return sorted(out, key=lambda x: x[0])


# -------------------------------------------------------------- big picture

def facts():
    """Deterministic summary - works with no model at all."""
    from integrations import personal, school
    lines = []
    grades = [g for g in school.cached_grades() if isinstance(g.get("score"), (int, float))]
    if grades:
        low = sorted(grades, key=lambda g: g["score"])[:2]
        lines.append("Lowest grades: " + "; ".join(f"{g['course']} {g['score']:.1f}%" for g in low))
    tr = trends()
    moves = [(c, now, d) for c, (now, d) in tr.items() if abs(d) >= 1.0]
    if moves:
        lines.append("Moving: " + "; ".join(f"{c} {'+' if d > 0 else ''}{d}" for c, _, d in sorted(moves, key=lambda m: m[2])))
    due = school.cached_due()[:4]
    if due:
        lines.append("Next due: " + "; ".join(f"{i['due'][5:10]} {i['course']}: {i['title']}" for i in due))
    cd = personal.countdown_rows()[:3]
    if cd:
        lines.append("Countdowns: " + ", ".join(f"{n} in {d}d" for n, d in cd))
    by, total = personal.study_totals(7)
    lines.append(f"Study logged this week: {round(total)} min" + (
        " (" + ", ".join(f"{k} {round(v)}" for k, v in by.items()) + ")" if by else ""))
    opp = soonest_opportunities(30)[:3]
    if opp:
        lines.append("Opportunity deadlines within 30 days: " + "; ".join(
            f"{o['name']} ({d}d)" for d, o in opp))
    return "\n".join(lines) or "Nothing recorded yet - run a grade check first."


def big_picture():
    f = facts()
    try:
        # this mixes grades and schedule, so it is school data: local model only
        text = llm.complete(
            "You are EDITH, a concise personal chief of staff for an 11th grader aiming for a CS major "
            "(SAT Dec 5 2026, college apps next fall). From these facts give the 4 most important priorities "
            "for the next 7 days, most urgent first, one line each with the reason. Use only the facts; "
            "do not invent numbers. No markdown.", f, private=True)
        return f"{text}\n\n--- facts ---\n{f}"
    except (privacy.PrivacyError, llm.LLMUnavailable):
        return "(No local model available for a written plan - here are the facts.)\n" + f
