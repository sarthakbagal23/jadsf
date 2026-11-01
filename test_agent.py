"""Tests for the EDITH agent layer. Run:  python test_agent.py

Drives a REAL headless Chromium against a mock school website (tests/mock_site.py), so the
browser engine, the safety gate, the agent loop, the playbooks and the phone endpoints are
exercised for real. Only the language model is scripted. Windows-only desktop control is
tested with a fake pyautogui.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["EDITH_BROWSER_HEADLESS"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

import mock_site  # noqa: E402

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "PASS"))
        print(f"PASS: {name}")
    except Exception as e:
        import traceback
        results.append((name, "FAIL"))
        print(f"FAIL: {name} -> {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)


TMP = Path(tempfile.mkdtemp())
SRV, BASE = mock_site.start()

from edith_agent import approvals, browser as BR, context, dawg, desktop, events, insights  # noqa: E402
from edith_agent import intents, llm, playbooks, privacy, runner, safety  # noqa: E402
from edith_agent.observe import fmt_observation  # noqa: E402

B = BR.Browser(cdp_url="", profile=TMP / "profile", headless=True)
BR._default = B                       # everything below (and school.py) shares this one browser


def ids(obs=None):
    return {e["label"]: e["id"] for e in (obs or B.observe())["elements"]}


# ------------------------------------------------------------------ engine
def t_parallel_tabs():
    t0 = time.time()
    res = B.open_tabs([f"{BASE}/courses/{i}/grades" for i in (1, 2, 3, 4)])
    assert all(t for t, _ in res), res
    titles = sorted(t["title"] for t in B.tabs_info() if t["title"].startswith("Grades"))
    assert len(titles) == 4, titles
    assert time.time() - t0 < 8, "parallel open should be fast"
    B.close_tabs([t for t, _ in res])


check("engine: opens 4 tabs in parallel", t_parallel_tabs)


def t_observe_and_act():
    B.open_tab(BASE + "/form")
    obs = B.observe()
    text = fmt_observation(obs)
    assert '"Sign Up"' in text and "untrusted" in text
    i = ids(obs)
    assert "Typed" in B.type_text(i["Your note"], "hello")
    assert "Clicked" in B.click(i["Sign Up"])
    time.sleep(0.3)
    assert mock_site.STATE["signups"], "click did not reach the page"
    assert "Scrolled" in B.scroll("down")


check("engine: reads numbered elements, types, clicks, scrolls", t_observe_and_act)


def t_iframe_popup():
    B.open_tab(BASE + "/frame")
    o = B.observe()
    inner = [e for e in o["elements"] if e["label"] == "Inner Button"]
    assert inner, "element inside an iframe should be visible"
    mock_site.STATE["clicks"].clear()
    B.click(inner[0]["id"])
    time.sleep(0.3)
    assert mock_site.STATE["clicks"] == ["/far"]
    B.goto(BASE + "/popup")
    msg = B.click(B.observe()["elements"][0]["id"])
    assert "new tab" in msg, msg
    assert B.observe()["title"].startswith("Grades")


check("engine: iframes work; target=_blank popups become the active tab", t_iframe_popup)


def t_password_block():
    B.open_tab(BASE + "/form")
    i = ids()
    try:
        B.type_text(i["Password"], "hunter2")
        raise AssertionError("typed into a password field!")
    except BR.CredentialField:
        pass
    try:
        B.fill_selector("input[type=password]", "hunter2")
        raise AssertionError("CSS fill typed into a password field!")
    except BR.CredentialField:
        pass
    assert B.eval_js("() => document.querySelector('input[type=password]').value") == ""


check("engine: never types into password fields (by id or by CSS selector)", t_password_block)


def t_url_rules():
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "https://user:pw@example.com", ""):
        try:
            BR.web_url(bad)
            raise AssertionError(f"accepted {bad!r}")
        except ValueError:
            pass
    assert BR.web_url("example.com/x") == "https://example.com/x"
    assert BR.safe_url("https://a.com/p?token=secret#x") == "https://a.com/p"


check("engine: URL validation blocks file:/javascript:/embedded credentials", t_url_rules)


def t_threads():
    """The bug this engine exists to fix: sync Playwright dies when used from several threads."""
    out, errs = [], []

    def work(n):
        try:
            tid = B.open_tab(f"{BASE}/courses/{n}/grades")
            out.append(B.observe(tid)["title"])
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=work, args=(n,)) for n in (1, 2, 3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(out) == 3, (out, errs)


check("engine: safe to call from many threads at once", t_threads)


def t_cdp():
    """Attach to an already-running Chrome over CDP (how EDITH uses your signed-in Chrome)."""
    from playwright.sync_api import sync_playwright
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with sync_playwright() as pw:
        exe = pw.chromium.executable_path
    proc = subprocess.Popen([exe, "--headless=new", "--no-sandbox", f"--remote-debugging-port={port}",
                             f"--user-data-dir={TMP / 'cdp'}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        b = BR.Browser(cdp_url=f"http://127.0.0.1:{port}")
        for _ in range(40):
            try:
                tid = b.open_tab(BASE + "/form")
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise AssertionError("never attached over CDP")
        assert b.observe(tid)["title"] == "Student Support"
        b.close()
        assert proc.poll() is None, "closing EDITH must not close the user's own Chrome"
    finally:
        proc.terminate()


check("engine: attaches to a running Chrome over CDP and leaves it open", t_cdp)


# ------------------------------------------------------------------ safety
def t_safety():
    g = safety.grants_from_request
    assert g("sign me up for chem help") == {"signup"}
    assert g("check me in") == {"checkin"}
    assert g("what's on the page") == set()

    def click(label, **kw):
        return safety.check_click({"text": label, "tag": "button", **kw}, set())
    assert click("Sign Up").verdict == "confirm"
    assert safety.check_click({"text": "Sign Up", "tag": "button"}, {"signup"}).verdict == "allow"
    assert safety.check_click({"text": "Delete Account", "tag": "button"}, {"signup", "apply"}).verdict == "confirm"
    assert click("Buy now").verdict == "confirm" and click("Pay $5").category == "purchase"
    assert click("Dashboard").verdict == "allow"
    assert click("Save", submit=True).category == "apply"
    assert safety.check_click({"text": "Sign Up", "tag": "a", "href": "/signup"}, set()).verdict == "allow"  # plain link
    assert safety.check_click({"text": "Delete", "tag": "a", "href": "/x"}, set()).verdict == "confirm"
    assert safety.check_enter({"inForm": True, "tag": "input"}, set()).verdict == "confirm"
    assert safety.check_enter({"inForm": True, "tag": "input"}, {"checkin"}).verdict == "allow"


check("safety: grants come from the user's words; purchases/deletes always ask", t_safety)


# ------------------------------------------------------------------ approvals / events
def t_approvals():
    res = {}
    th = threading.Thread(target=lambda: res.update(ok=approvals.request("Click Sign Up", "signup", timeout=5)))
    th.start()
    for _ in range(50):
        if approvals.pending():
            break
        time.sleep(0.05)
    assert approvals.pending()["text"] == "Click Sign Up"
    assert intents.match("yes") == "Approved."
    th.join()
    assert res["ok"] is True and approvals.pending() is None
    th = threading.Thread(target=lambda: res.update(ok=approvals.request("x", timeout=0.2)))
    th.start(); th.join()
    assert res["ok"] is False, "no answer must deny"
    qres = {}
    th = threading.Thread(target=lambda: qres.update(a=approvals.ask("Which teacher?", timeout=5)))
    th.start()
    for _ in range(50):
        if approvals.open_question():
            break
        time.sleep(0.05)
    assert intents.match("Mr. Smith") == "Got it."
    th.join()
    assert qres["a"] == "Mr. Smith"
    assert intents.match("yes") is None, "'yes' with nothing pending is just a normal message"


check("approvals: yes/no and free-form answers reach the waiting task", t_approvals)


def t_event_bus():
    bus = events.EventBus()
    bus.emit("say", "one")
    got = []
    th = threading.Thread(target=lambda: got.extend(bus.since(1, wait=3)))
    th.start()
    time.sleep(0.2)
    bus.emit("done", "two")
    th.join()
    assert [e["text"] for e in got] == ["two"]
    assert bus.since(99, wait=0.1) == []


check("events: long-poll wakes on new events", t_event_bus)


# ------------------------------------------------------------------ runner
def scripted(*plan):
    it = iter(plan)
    calls = []

    def chat(messages, tools=None, private=False):
        calls.append(private)
        kind, arg = next(it)
        state = messages[-1]["content"]
        if kind == "click":
            m = re.search(r'\[(\d+)\] \w+ (?:\w+ )?"%s"' % re.escape(arg), state)
            assert m, f"{arg!r} not on the page:\n{state[-500:]}"
            return {"content": "Clicking it.", "calls": [{"name": "click", "args": {"id": int(m.group(1))}}]}
        if kind == "raw":
            return {"content": "", "calls": [{"name": arg[0], "args": arg[1]}]}
        return {"content": "", "calls": [{"name": "done", "args": {"summary": arg, "success": True}}]}
    return chat, calls


def run_task(goal, url, plan, answer=None, max_steps=6):
    chat, calls = scripted(*plan)
    llm.chat = chat
    task = runner.Task(goal=goal, start_url=url, grants=safety.grants_from_request(goal),
                       private=privacy.is_school_text(goal), max_steps=max_steps)
    if answer is not None:
        def responder():
            for _ in range(100):
                if approvals.pending():
                    approvals.resolve(answer)
                    return
                time.sleep(0.05)
        threading.Thread(target=responder, daemon=True).start()
    ok, summary = runner.AgentRunner(task, B).run()
    return ok, summary, calls


def t_runner_safety():
    S = mock_site.STATE
    S.update(signups=[], deleted=0)
    ok, _, _ = run_task("sign me up on the page", BASE + "/form", [("click", "Sign Up"), ("done", "ok")])
    assert ok and len(S["signups"]) == 1, "an explicit request needs no second yes"
    run_task("look at the page", BASE + "/form", [("click", "Sign Up"), ("done", "ok")], answer=False)
    assert len(S["signups"]) == 1, "an action nobody asked for must wait for approval - and be denied"
    run_task("look at the page", BASE + "/form", [("click", "Sign Up"), ("done", "ok")], answer=True)
    assert len(S["signups"]) == 2, "approved -> it proceeds"
    run_task("delete my account please", BASE + "/form", [("click", "Delete Account"), ("done", "x")], answer=False)
    assert S["deleted"] == 0, "deletes ask even when you mention them"
    run_task("read the news", BASE + "/inject", [("click", "Delete Account"), ("done", "x")], answer=False)
    assert S["deleted"] == 0, "a web page's instructions must never authorise anything"


check("runner: explicit request proceeds; unrequested/delete/injected actions are stopped", t_runner_safety)


def t_runner_privacy():
    _, _, calls = run_task("check my canvas grades", BASE + "/", [("done", "x")])
    assert calls == [True], calls                           # school goal -> local model only
    _, _, calls = run_task("look up the weather page", BASE + "/popup", [("done", "x")])
    assert calls == [False], calls
    # and the privacy door itself: school work can't fall back to a cloud model
    import importlib
    import requests
    importlib.reload(llm)                                  # undo the scripted chat() used above
    old_post, old_host, old_key = requests.post, privacy.OLLAMA_HOST, llm.GROQ_API_KEY
    requests.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("cloud call made with school data!"))
    privacy.OLLAMA_HOST, llm.GROQ_API_KEY = "http://some-remote-host:11434", "gsk_test"
    try:
        llm.chat([{"role": "user", "content": "grades"}], None, private=True)
        raise AssertionError("private chat should refuse a remote model")
    except privacy.PrivacyError:
        pass
    finally:
        requests.post, privacy.OLLAMA_HOST, llm.GROQ_API_KEY = old_post, old_host, old_key
        importlib.reload(llm)


check("privacy: school goals/pages stay on the local model; remote hosts refused", t_runner_privacy)


def t_runner_loop_guard():
    ok, summary, _ = run_task("go", BASE + "/form", [("raw", ("scroll", {"direction": "down"}))] * 8, max_steps=8)
    assert not ok and "stuck" in summary, summary


check("runner: stops itself when it repeats the same action", t_runner_loop_guard)


def t_login_wall():
    chat, _ = scripted(("done", "ok"))
    llm.chat = chat
    task = runner.Task(goal="look", start_url=BASE + "/login", max_steps=3)
    res = {}
    th = threading.Thread(target=lambda: res.update(r=runner.AgentRunner(task, B).run()))
    th.start()
    for _ in range(100):
        if approvals.open_question():
            break
        time.sleep(0.05)
    q = approvals.open_question()
    assert q and "sign in" in q["text"].lower() and "never type passwords" in q["text"].lower()
    approvals.answer("continue")
    th.join()
    assert res["r"][0] is True


check("runner: pauses at a sign-in page and waits for you (never types credentials)", t_login_wall)


def t_task_manager():
    m = runner.TaskManager()
    seen = []
    events.BUS.add_sink(lambda e: seen.append(e["kind"]))
    t = m.start_playbook("demo", lambda: "all done")
    m.wait(t, 10)
    assert t.status == "done" and t.result == "all done" and "done" in seen
    slow = m.start_playbook("slow", lambda: [time.sleep(0.1) for _ in range(50)] and "x")
    for _ in range(50):
        if m.current:
            break
        time.sleep(0.05)
    assert m.cancel().id == slow.id
    m.wait(slow, 10)
    assert slow.status in ("cancelled", "done")


check("task manager: runs, reports, and cancels background tasks", t_task_manager)


# ------------------------------------------------------------------ playbooks
def _setup_school():
    from integrations import school
    school.CANVAS_BASE_URL = playbooks.CANVAS_BASE_URL = BASE
    school.CANVAS_TOKEN = ""
    school.CACHE = TMP / "school_cache.json"
    playbooks.SCHEDULE = TMP / "schedule.json"
    insights.HISTORY = TMP / "grades_history.json"
    insights.OPPS = TMP / "opps.json"
    return school


def t_open_sites():
    playbooks.sites = lambda: {"canvas": BASE + "/", "github": BASE + "/form"}
    out = playbooks.open_sites("canvas, github and nonsense")
    assert "canvas" in out and "github" in out and "Not set up: nonsense" in out, out
    assert len(B.tabs_info()) >= 2


check("playbook: opens several sites in parallel tabs, reports unknown ones", t_open_sites)


def t_grades_sweep():
    _setup_school()
    playbooks.close_all_tabs()                                 # earlier tests left tabs around
    assert "Day must be" in playbooks.set_class_day("chem", "sometimes")
    playbooks.set_class_day("chem", "odd")
    playbooks.set_class_day("csa", "odd")
    playbooks.set_class_day("lang", "even")
    playbooks.set_class_day("precalc", "even")
    out = playbooks.grades_sweep("odd")
    assert "AP Chemistry: Canvas 87.4%" in out and "Computer Science" in out, out
    assert "English" not in out and "Precalculus" not in out, "odd sweep must skip even classes"
    out_even = playbooks.grades_sweep("even")
    assert "AP English Language: Canvas 92.1%" in out_even and "Chemistry" not in out_even, out_even
    grades_tabs = [t for t in B.tabs_info() if t["title"].startswith("Grades -")]
    assert len(grades_tabs) == 2, "previous sweep's tabs are tidied up"
    # a second look after a grade change reports the trend
    mock_site.COURSES[0]["total"] = 88.9
    mock_site.COURSES[0]["enrollments"][0]["computed_current_score"] = 88.9
    hist = json.loads(insights.HISTORY.read_text())
    hist[-1]["ts"] -= 3 * 86400                               # pretend the first snapshot is 3 days old
    for h in hist:
        h["ts"] -= 3 * 86400
    insights.HISTORY.write_text(json.dumps(hist))
    out2 = playbooks.grades_sweep("odd")
    assert "+1.5 since last check" in out2, out2
    try:
        playbooks.set_class_day("chem", "clear")
        playbooks.set_class_day("csa", "clear")
        playbooks.grades_sweep("odd")
        raise AssertionError("expected a helpful error when no odd classes are known")
    except ValueError as e:
        assert "don't know your odd classes" in str(e)


check("playbook: odd/even grade sweep reads each class tab, filters, tracks trends", t_grades_sweep)


def t_parse_total():
    assert playbooks.parse_total("Total   87.4%") == 87.4
    assert playbooks.parse_total("Current Score: 91%") == 91.0
    assert playbooks.parse_total("nothing here") is None


check("playbook: grade parsing", t_parse_total)


def t_search_parse():
    html = """<tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example.edu%2Fsummer%3Fy%3D2027&amp;rut=abc" class='result-link'>Summer Research <b>2027</b></a></td></tr>
<tr><td class='result-snippet'>Apply by <b>March 1</b>.</td></tr>
<tr><td><a class="result-link" href="https://www.pinterest.com/x">pin</a></td></tr>
<tr><td><a class='result-link' rel="nofollow" href="https://girlswhocode.com/summer">GWC</a></td></tr>
<tr><td><a class='result-link' href="https://girlswhocode.com/summer/">dup</a></td></tr>"""
    r = playbooks.parse_search(html)
    assert [x[1] for x in r] == ["https://www.example.edu/summer?y=2027", "https://girlswhocode.com/summer"], r
    assert r[0][0] == "Summer Research 2027" and "March 1" in r[0][2]


check("playbook: search-result parsing (redirects, dedupe, junk sites)", t_search_parse)


def t_research():
    _setup_school()
    page = BASE + "/courses/1/grades"
    playbooks.search_urls = lambda q, n=8: [("Summer CS Research Program", BASE + "/courses/1/grades", "snippet")]
    replies = [json.dumps([{"name": "Summer CS Research Program", "organization": "Mock U", "type": "research",
                            "deadline": "March 1, 2027", "eligibility": "juniors", "cost": "free",
                            "url": page, "fit": "Matches CS interest"}])]
    llm.complete = lambda system, user, private=False: replies[0]
    out = playbooks.research_opportunities("test topic", count=2)
    assert "Summer CS Research Program" in out and "(unverified)" in out, out   # page doesn't contain that date
    assert insights.load_opportunities()[0]["name"] == "Summer CS Research Program"
    assert "Summer CS Research" in playbooks.list_opportunities()
    llm.complete = lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("no model"))
    out = playbooks.research_opportunities("test topic", count=2)
    assert "opportunities" in out.lower()                                  # still useful without a model


check("playbook: research reads pages, flags dates the page doesn't contain, works without a model", t_research)


def t_dawg():
    dawg.HOST = BASE.split("//")[1] + "/dawg"             # only the dawg tab matches
    dawg.STUDENT_SUPPORT_TIME_URL = BASE + "/dawg"
    s = dawg.status()
    assert "Dawg Time — Oct 29" in s and "Mr. Smith - Chemistry help" in s and "Already signed up" in s, s
    assert "Check-in controls visible: 1" in s
    assert "couldn't find" in dawg.status("Dec 25")
    mock_site.STATE["checkins"].clear()
    out = dawg.checkin("check me in please")                       # asked -> no second yes
    assert out.startswith("Checked in") and len(mock_site.STATE["checkins"]) == 1, out
    assert "don't see a check-in" in dawg.checkin("check me in")   # the button is gone now


check("dawg time: reads sessions; check-in runs only on request and verifies the result", t_dawg)


def t_dawg_asks_when_not_requested():
    dawg.STUDENT_SUPPORT_TIME_URL = BASE + "/dawg"
    for t in B.tabs_info():
        if "/dawg" in t["url"]:
            B.close_tab(t["id"])
    B.open_tab(BASE + "/dawg")
    mock_site.STATE["checkins"].clear()
    res = {}
    th = threading.Thread(target=lambda: res.update(out=dawg.checkin("what's the weather")))
    th.start()
    for _ in range(100):
        if approvals.pending():
            break
        time.sleep(0.05)
    assert approvals.pending() and "Check you in" in approvals.pending()["text"]
    approvals.resolve(False)
    th.join()
    assert "did not check you in" in res["out"] and not mock_site.STATE["checkins"]


check("dawg time: without a request it asks first (and respects 'no')", t_dawg_asks_when_not_requested)


# ------------------------------------------------------------------ intents
def t_intents():
    calls = []

    class T:
        id = 1
    old = (playbooks.set_class_day, playbooks.open_sites, runner.MANAGER.start_playbook, runner.MANAGER.start)
    playbooks.set_class_day = lambda c, d: calls.append(("day", c, d)) or "saved"
    playbooks.open_sites = lambda n: calls.append(("open", tuple(n))) or "opened"
    runner.MANAGER.start_playbook = lambda label, fn, private=True: calls.append(("bg", label)) or T()
    runner.MANAGER.start = lambda *a, **k: calls.append(("agent", a[0])) or T()
    try:
        def m(q):
            calls.clear()
            r = intents.match(q)
            return calls[0] if calls else r
        assert m("chem is odd") == ("day", "chem", "odd")
        assert m("what is even") is None
        assert calls == [] and m("my odd classes are chem, lang and physics") == ("day", "chem", "odd")
        assert m("open canvas and github")[0] == "open"
        assert m("check the odd classes") == ("bg", "Grades sweep (odd)")
        assert m("check the even classes") == ("bg", "Grades sweep (even)")
        assert m("open canvas for each class") == ("bg", "Grades sweep (all)")
        assert m("check me in for student support time") == ("bg", "Student Support Time check-in")
        assert m("sign me up for dawg time with mr smith tomorrow")[0] == "agent"
        assert m("find me summer research opportunities")[0] == "bg"
        assert m("what should i focus on this week") == ("bg", "Big picture")
        assert m("explain recursion") is None
        assert m("open the pod bay doors") is None
    finally:
        playbooks.set_class_day, playbooks.open_sites, runner.MANAGER.start_playbook, runner.MANAGER.start = old


check("intents: instant commands route correctly and ignore look-alikes", t_intents)


def t_context_grants():
    context.set_user_text("check me in")
    from edith_agent import tools as T
    assert "checkin" in safety.grants_from_request(context.user_text())
    names = {t["schema"]["function"]["name"] for t in T.TOOLS}
    assert {"browse", "grades_sweep", "open_sites", "support_time_checkin"} <= names


check("tools: registered; grants read from the user's real message", t_context_grants)


# ------------------------------------------------------------------ insights
def t_insights():
    insights.HISTORY = TMP / "h2.json"
    now = time.time()
    insights.HISTORY.write_text(json.dumps([{"ts": now - 5 * 86400, "rows": [{"course": "AP Chem", "score": 90.0}]}]))
    insights.record_grades([{"course": "AP Chem", "score": 87.0, "source": "IC"}])
    assert insights.trends() == {"AP Chem": (87.0, -3.0)}
    f = insights.facts()
    assert "Moving: AP Chem -3.0" in f and "Countdowns" in f, f


check("insights: grade trends and a model-free fact summary", t_insights)


# ------------------------------------------------------------------ desktop
def t_desktop():
    try:
        desktop.windows()
        raise AssertionError("desktop control must be off by default")
    except desktop.DesktopDisabled:
        pass
    desktop.JARVIS_COMPUTER_USE = True
    typed, pressed = [], []

    class FakePG:
        FAILSAFE = True
        def size(self): return (1920, 1080)
        def click(self, x, y, clicks=1): pressed.append(("click", x, y))
        def write(self, t, interval=0): typed.append(t)
        def hotkey(self, *k): pressed.append(k)
    desktop._pg_mod = FakePG()
    try:
        desktop.hotkey(["alt", "f4"])
        raise AssertionError("alt+f4 must be blocked")
    except PermissionError:
        pass
    assert "Pressed ctrl+s" in desktop.hotkey(["ctrl", "s"])
    try:
        desktop.click_xy(5000, 5)
        raise AssertionError("off-screen click accepted")
    except ValueError:
        pass
    desktop.foreground_title = lambda: "Sign in to your account - Edge"
    try:
        desktop.type_text("secret")
        raise AssertionError("typed into a sign-in window")
    except PermissionError:
        pass
    desktop.foreground_title = lambda: "Notepad"
    assert "Typed 5" in desktop.type_text("hello") and typed == ["hello"]
    assert len(desktop.agent_schemas()) >= 6
    desktop.JARVIS_COMPUTER_USE = False


check("desktop: off by default; blocks alt+f4, off-screen clicks, typing into sign-in windows", t_desktop)


# ------------------------------------------------------------------ phone server
def t_server():
    from fastapi.testclient import TestClient
    import server
    server.SERVER_TOKEN = "tok"
    c = TestClient(server.app)
    assert c.get("/").status_code == 200 and "EDITH" in c.get("/").text
    assert c.get("/manifest.webmanifest").json()["display"] == "standalone"
    assert c.get("/api/events").status_code == 401
    h = {"Authorization": "Bearer tok"}
    events.BUS.emit("say", "hello phone")
    j = c.get("/api/events?since=0", headers=h).json()
    assert any(e["text"] == "hello phone" for e in j["events"]) and "status" in j
    res = {}
    th = threading.Thread(target=lambda: res.update(ok=approvals.request("Click Sign Up", "signup", timeout=5)))
    th.start()
    for _ in range(50):
        if approvals.pending():
            break
        time.sleep(0.05)
    j = c.get("/api/events?since=0", headers=h).json()
    assert j["pending"]["text"] == "Click Sign Up"
    assert c.post("/api/approve", json={"ok": True, "id": j["pending"]["id"]}, headers=h).json()["resolved"]
    th.join()
    assert res["ok"] is True
    assert c.get("/api/shot?token=nope").status_code == 401
    assert c.get("/api/shot?token=tok").status_code in (200, 404)


check("phone server: app, manifest, token auth, live events, approve from the phone", t_server)


# ------------------------------------------------------------------ wrap up
B.close()
SRV.shutdown()
print()
failed = [r for r in results if r[1] == "FAIL"]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
