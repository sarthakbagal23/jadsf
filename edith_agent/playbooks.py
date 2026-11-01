"""Fast, known-good flows. No model needed for the steps we already understand.

These are what make "open canvas for each odd class and tell me the grades" take
seconds: tabs open in parallel, pages are read with plain parsing, and results are
reported as each one lands. The agent runner (runner.py) is for everything open-ended.
"""
import json
import re
import time
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from config import (CANVAS_BASE_URL, CLASSLINK_URL, DATA_DIR, IC_BASE_URL,
                    STUDENT_SUPPORT_TIME_URL)
from edith_agent import insights, llm, privacy, runner
from edith_agent.browser import get_browser, web_url
from edith_agent.events import emit

SCHEDULE = DATA_DIR / "schedule.json"
SITES_FILE = DATA_DIR / "sites.json"


# ---------------------------------------------------------------- open sites

def sites():
    s = {
        "canvas": CANVAS_BASE_URL, "ic": IC_BASE_URL, "infinite campus": IC_BASE_URL,
        "classlink": CLASSLINK_URL, "dawg time": STUDENT_SUPPORT_TIME_URL,
        "student support": STUDENT_SUPPORT_TIME_URL, "student support time": STUDENT_SUPPORT_TIME_URL,
        "github": "https://github.com", "anchor": "https://github.com/sarthakbagal23/Anchor",
        "gmail": "https://mail.google.com", "email": "https://mail.google.com",
        "drive": "https://drive.google.com", "calendar": "https://calendar.google.com",
        "docs": "https://docs.google.com", "notion": "https://www.notion.so",
        "spotify": "https://open.spotify.com", "youtube": "https://www.youtube.com",
        "usaco": "https://usaco.org", "usaco guide": "https://usaco.guide",
        "cs50": "https://cs50.harvard.edu/x", "khan": "https://www.khanacademy.org",
        "collegeboard": "https://bluebook.collegeboard.org", "bluebook": "https://bluebook.collegeboard.org",
        "common app": "https://www.commonapp.org", "deca": "https://www.deca.org",
        "tsa": "https://tsaweb.org", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
    }
    try:
        s.update({k.lower(): v for k, v in json.loads(SITES_FILE.read_text(encoding="utf-8")).items()})
    except Exception:
        pass
    return {k: v for k, v in s.items() if v}


def split_names(text):
    return [p.strip() for p in re.split(r",|\band\b|&|\+|\bthen\b", text.lower()) if p.strip()]


def open_sites(names):
    """Open several sites at once, each in its own tab. `names` = list or 'canvas, github and gmail'."""
    if isinstance(names, str):
        names = split_names(names)
    known = sites()
    urls, labels, unknown = [], [], []
    for n in names:
        n = n.strip().lower()
        if n in known:
            urls.append(known[n]); labels.append(n)
        elif re.search(r"\.[a-z]{2,}(/|$)", n):
            urls.append(n); labels.append(n)
        else:
            unknown.append(n)
    if not urls:
        return f"I don't know a site called {', '.join(unknown) or 'that'}. I know: {', '.join(sorted(known))}."
    b = get_browser()
    results = b.open_tabs([web_url(u) for u in urls])
    ok = [f"{lab} ({tid})" for lab, (tid, err) in zip(labels, results) if tid]
    bad = [f"{lab}: {err}" for lab, (tid, err) in zip(labels, results) if err]
    out = "Opened " + ", ".join(ok) + "." if ok else "Couldn't open anything."
    if bad:
        out += " Problems: " + "; ".join(bad)
    if unknown:
        out += " Unknown: " + ", ".join(unknown) + "."
    return out


def list_tabs():
    tabs = get_browser().tabs_info()
    return "\n".join(f"{'*' if t['active'] else ' '}{t['id']}  {t['title'][:50]}  {t['url'][:60]}" for t in tabs) \
        or "No tabs are open."


def close_all_tabs(keep_active=False):
    b = get_browser()
    tabs = [t["id"] for t in b.tabs_info() if not (keep_active and t["active"])]
    b.close_tabs(tabs)
    return f"Closed {len(tabs)} tab(s)."


# ----------------------------------------------------- odd / even class days

def _schedule():
    try:
        return json.loads(SCHEDULE.read_text(encoding="utf-8"))
    except Exception:
        return {"odd": [], "even": []}


def set_class_day(course, day):
    """Remember which block day a class meets: odd, even, both, or clear."""
    day = day.lower().strip()
    if day not in ("odd", "even", "both", "clear"):
        return "Day must be odd, even, both, or clear."
    s = _schedule()
    c = course.lower().strip()
    for k in ("odd", "even"):
        s[k] = [x for x in s[k] if x != c]
        if day in (k, "both"):
            s[k].append(c)
    SCHEDULE.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return f"Saved. Odd: {', '.join(s['odd']) or '-'}. Even: {', '.join(s['even']) or '-'}."


def _pick_courses(which, courses):
    from integrations import school
    w = (which or "all").lower().strip()
    if w in ("", "all", "every", "everything", "all classes"):
        return courses, "all classes"
    if w in ("odd", "even"):
        names = _schedule()[w]
        if not names:
            raise ValueError(f"I don't know your {w} classes yet. Tell me, e.g. 'chem is odd' or "
                             f"'my {w} classes are chem, lang and physics'.")
        picked = [c for c in (school.find_course(n, courses) for n in names) if c]
        return list({c["id"]: c for c in picked}.values()), f"{w} classes"
    picked, missing = [], []
    for n in split_names(w):
        c = school.find_course(n, courses)
        (picked if c else missing).append(c or n)
    if missing and not picked:
        raise ValueError(f"No class matches {', '.join(missing)}.")
    return list({c['id']: c for c in picked}.values()), ", ".join(c["name"] for c in picked)


# ------------------------------------------------------------- grade sweep

_TOTAL = [r"Total[^\d\n]{0,25}(\d{1,3}(?:\.\d+)?)\s*%", r"Current Score[^\d\n]{0,25}(\d{1,3}(?:\.\d+)?)\s*%",
          r"Grade[^\d\n]{0,25}(\d{1,3}(?:\.\d+)?)\s*%"]
_sweep_tabs = []


def parse_total(text):
    for pat in _TOTAL:
        m = re.search(pat, text, re.I)
        if m:
            return float(m.group(1))
    return None


def _same_course(a, b):
    stop = {"ap", "the", "of", "and", "a", "i", "ii", "honors", "h"}
    wa = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if w not in stop}
    wb = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if w not in stop}
    return bool(wa & wb)


def grades_sweep(which="all", keep_open=True):
    """Open a Canvas grades tab per class (in parallel), read each, add Infinite Campus, show trends."""
    from integrations import school
    if not CANVAS_BASE_URL:
        return "Canvas isn't configured (CANVAS_BASE_URL in .env)."
    b = get_browser()
    global _sweep_tabs
    if _sweep_tabs:                                   # tidy up the previous sweep's tabs
        b.close_tabs(_sweep_tabs)
        _sweep_tabs = []
    emit("say", "Looking up your classes in Canvas…")
    courses = school._courses()
    chosen, label = _pick_courses(which, courses)
    if not chosen:
        return "None of those classes are in Canvas right now."
    emit("say", f"Opening {len(chosen)} class tab(s) at once ({label}).")
    base = CANVAS_BASE_URL.rstrip("/")
    opened = b.open_tabs([f"{base}/courses/{c['id']}/grades" for c in chosen])
    _sweep_tabs = [t for t, _ in opened if t]

    rows = []
    for c, (tid, err) in zip(chosen, opened):
        if runner.cancelled():
            break
        enr = next((e for e in c.get("enrollments", []) if e.get("type") == "student"), {})
        api = enr.get("computed_current_score")
        page_score = None
        if tid:
            b.activate(tid)                           # bring each tab forward as it is read
            b.badge(f"reading {c['name']}", tid)
            for _ in range(12):                       # Canvas fills the total in after load
                page_score = parse_total(b.read_text(tid))
                if page_score is not None:
                    break
                time.sleep(0.5)
        score = page_score if page_score is not None else api
        src = "Canvas page" if page_score is not None else ("Canvas API" if api is not None else "unreadable")
        rows.append({"course": c["name"], "score": score, "letter": enr.get("computed_current_grade") or "",
                     "source": src, "api": api, "page": page_score})
        emit("say", f"{c['name']}: " + (f"{score:.1f}%" if score is not None else "couldn't read") + f" ({src})")

    ic = []
    try:
        ic = school.ic_grades() if IC_BASE_URL else []
    except Exception as e:
        emit("info", f"Infinite Campus: {e}")
    for r in rows:
        match = next((g for g in ic if _same_course(r["course"], g["course"])), None)
        r["ic"] = match["score"] if match and isinstance(match["score"], (int, float)) else None

    insights.record_grades([{"course": r["course"], "score": r["ic"] if r["ic"] is not None else r["score"],
                             "source": "IC" if r["ic"] is not None else "Canvas"}
                            for r in rows if (r["ic"] is not None or r["score"] is not None)])
    tr = insights.trends()
    lines = [f"Grades - {label}:"]
    for r in rows:
        bits = [f"{r['course']}:"]
        bits.append(f"Canvas {r['score']:.1f}%" if r["score"] is not None else "Canvas ?")
        if r["letter"]:
            bits[-1] += f" ({r['letter']})"
        if r["ic"] is not None:
            bits.append(f"IC {r['ic']:.1f}%")
        t = tr.get(r["course"])
        if t and t[1]:
            bits.append(f"{'+' if t[1] > 0 else ''}{t[1]} since last check")
        if r["api"] is not None and r["page"] is not None and abs(r["api"] - r["page"]) > 0.6:
            bits.append("(page and API disagree - rounding or weighting)")
        lines.append("  " + "  |  ".join(bits))
    school._save_cache(grades=[{"course": r["course"], "score": r["ic"] if r["ic"] is not None else r["score"],
                                "letter": r["letter"], "source": "IC" if r["ic"] is not None else "Canvas"}
                               for r in rows if (r["ic"] is not None or r["score"] is not None)])
    if not keep_open:
        b.close_tabs(_sweep_tabs)
        _sweep_tabs = []
    return "\n".join(lines)


# ---------------------------------------------------- research / opportunities

_SKIP = ("pinterest.", "facebook.", "instagram.", "tiktok.", "reddit.com", "quora.com", "youtube.com", "amazon.")


def _fetch_search(query):
    r = requests.get("https://lite.duckduckgo.com/lite/", params={"q": query},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    r.raise_for_status()
    return r.text


def parse_search(html, n=8):
    """[(title, url, snippet)] from DuckDuckGo's lite page (handles its redirect links)."""
    out = []
    for m in re.finditer(r"<a\b([^>]*class=['\"]result-link['\"][^>]*)>(.*?)</a>", html, re.S):
        attrs, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        h = re.search(r"href=['\"]([^'\"]+)['\"]", attrs)
        if not h:
            continue
        href = h.group(1).replace("&amp;", "&")
        if href.startswith("//"):
            href = "https:" + href
        q = parse_qs(urlsplit(href).query)
        url = unquote(q["uddg"][0]) if "uddg" in q else href
        if not url.startswith("http") or any(s in url for s in _SKIP):
            continue
        tail = html[m.end():m.end() + 1500]
        sn = re.search(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", tail, re.S)
        out.append((title, url, re.sub(r"<[^>]+>", "", sn.group(1)).strip() if sn else ""))
    seen, uniq = set(), []
    for t, u, s in out:
        key = urlsplit(u).netloc + urlsplit(u).path.rstrip("/")
        if key not in seen:
            seen.add(key)
            uniq.append((t, u, s))
    return uniq[:n]


def search_urls(query, n=8):
    try:
        return parse_search(_fetch_search(query), n)
    except Exception as e:
        emit("info", f"Web search failed: {str(e).splitlines()[0][:100]}")
        return []


DIGEST_SYSTEM = """You extract real opportunities for a high-school student from web pages.
Return ONLY a JSON array. Each item: {"name","organization","type" (research|summer program|competition|internship|volunteering|other),
"deadline" (exactly as written on the page, or "unknown"), "eligibility", "cost", "url", "fit" (one honest sentence on why it suits an
11th grader aiming for a CS major in Georgia, or why it might not)}. Use ONLY information present in the page text - never guess a date
or a cost; write "unknown" instead. Skip pages that are not an actual opportunity."""


def research_opportunities(topic="research and extracurricular opportunities for high school students interested in computer science and data science",
                           count=6, keep_open=False):
    """Search the web, open the best pages side by side, read them, and keep a ranked shortlist."""
    b = get_browser()
    queries = [topic, f"{topic} high school application deadline 2027",
               f"{topic} Georgia high school students program"]
    emit("say", f"Searching the web for: {topic}")
    found, seen = [], set()
    for q in queries:
        for t, u, s in search_urls(q, 8):
            key = urlsplit(u).netloc
            if key in seen:
                continue
            seen.add(key)
            found.append((t, u, s))
    # trustworthy-looking sources first
    found.sort(key=lambda x: 0 if re.search(r"\.(edu|gov|org)\b", urlsplit(x[1]).netloc) else 1)
    found = found[:int(count)]
    if not found:
        return "The search returned nothing - check the internet connection and try again."
    emit("say", f"Opening {len(found)} promising pages side by side.")
    res = b.open_tabs([u for _, u, _ in found])
    pages, tabs = [], []
    for (title, url, snip), (tid, err) in zip(found, res):
        if runner.cancelled():
            break
        if not tid:
            continue
        tabs.append(tid)
        b.activate(tid)
        text = b.read_text(tid, 3500)
        emit("say", f"Reading: {title[:70]} ({urlsplit(url).netloc})")
        pages.append({"title": title, "url": url, "text": text, "snippet": snip})
    items = _digest(pages)
    if items:
        insights.save_opportunities(items)
    if not keep_open:
        b.close_tabs(tabs)
    if not items:
        return "I read the pages but couldn't confirm any specific opportunities. Pages: " + \
               "; ".join(f"{p['title'][:50]} <{p['url']}>" for p in pages)
    lines = [f"Found {len(items)} opportunities (saved to your list):"]
    for o in items:
        lines.append(f"- {o.get('name')} [{o.get('type', '?')}] - deadline: {o.get('deadline', 'unknown')}; "
                     f"{o.get('cost', 'cost unknown')}\n    {o.get('fit', '')}\n    {o.get('url')}")
    return "\n".join(lines)


def _digest(pages):
    if not pages:
        return []
    blob = "\n\n".join(f"### PAGE {i+1}: {p['title']} <{p['url']}>\n{p['text']}" for i, p in enumerate(pages))
    try:
        # public web pages + a generic profile: a cloud model is allowed here
        reply = llm.complete(DIGEST_SYSTEM, blob[:24000], private=False)
        items = llm.parse_json(reply)
    except Exception as e:
        emit("info", f"Couldn't summarize with a model ({str(e)[:80]}); listing raw results instead.")
        return [{"name": p["title"][:90], "url": p["url"], "deadline": _grab_deadline(p["text"]),
                 "type": "other", "fit": p["snippet"][:160]} for p in pages]
    by_url = {p["url"]: p["text"].lower() for p in pages}
    out = []
    for o in items if isinstance(items, list) else []:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        url = o.get("url") or ""
        text = by_url.get(url) or " ".join(by_url.values())
        d = str(o.get("deadline", "unknown"))
        if d.lower() != "unknown" and re.sub(r"\s+", " ", d.lower()) not in re.sub(r"\s+", " ", text):
            o["deadline"] = d + " (unverified)"           # model wrote a date the page doesn't contain
        out.append(o)
    return out


def _grab_deadline(text):
    m = re.search(r"(deadline|due|apply by|applications? close)[^.\n]{0,80}", text, re.I)
    return m.group(0).strip() if m else "unknown"


def list_opportunities(limit=10):
    items = insights.load_opportunities()
    if not items:
        return "No saved opportunities yet. Ask me to research some."
    return "\n".join(f"- {o.get('name')} - deadline {o.get('deadline', 'unknown')} - {o.get('url')}"
                     for o in items[-int(limit):])
