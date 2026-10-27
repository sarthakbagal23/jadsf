"""Smoke tests for the JARVIS scaffold. Run:  python test_smoke.py

Tests what can be verified without keys or Windows: memory, live web
tools, the Groq/OpenAI tool loop (against a mock server), and module
imports. Windows-only parts (pyautogui, mic, Playwright browser) can only
be syntax-checked on Linux — run this file on your laptop to check those.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

results = []


def check(name, fn):
    try:
        fn()
        results.append((name, "PASS", ""))
        print(f"PASS: {name}")
    except Exception as e:
        results.append((name, "FAIL", str(e)))
        print(f"FAIL: {name} -> {e}")


# --- 1. memory round-trip (temp DB, not the real one) ---
def t_memory():
    import memory
    memory.MEMORY_DB = Path("/tmp/jarvis_test.db")
    if memory.MEMORY_DB.exists():
        memory.MEMORY_DB.unlink()
    assert "December 5" in memory.remember("sat date", "December 5")
    assert memory.recall("sat date") == "December 5"
    assert memory.recall("nope") is None
    memory.add_note("test note")
    memory.log("user", "hello")
    memory.log("assistant", "hi")
    hist = memory.recent_history(10)
    assert hist == [("user", "hello"), ("assistant", "hi")], hist
    assert len(memory.list_facts()) == 1


check("memory remember/recall/notes/history", t_memory)


# --- 2. live web tools (real network) ---
def t_weather():
    import tools
    out = tools.get_weather("Cumming")
    assert "F" in out and "Cumming" in out, out


check("get_weather live (Open-Meteo)", t_weather)


def t_search():
    import tools
    out = tools.web_search("Ballon d'Or 2026 winner")
    assert len(out) > 50, out[:200]


check("web_search live (DuckDuckGo lite)", t_search)


def t_time():
    import tools
    assert "2026" in tools.get_time()


check("get_time", t_time)


# --- 3. Groq/OpenAI tool loop vs a mock server ---
class MockHandler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        MockHandler.calls += 1
        if MockHandler.calls == 1:
            # first turn: model calls get_time
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "get_time", "arguments": "{}"}}]}
            # sanity: tool schema was sent
            assert body.get("tools"), "no tools sent to model"
        else:
            msg = {"role": "assistant", "content": "The time is mocked o'clock."}
        payload = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def t_openai_loop():
    import brain
    srv = HTTPServer(("127.0.0.1", 0), MockHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import tools
        out = brain._openai_loop(f"http://127.0.0.1:{port}/v1", "dummy",
                                 "mock-model",
                                 [{"role": "user", "content": "what time is it"}],
                                 tools.TOOLS)
        assert "mocked" in out, out
        assert MockHandler.calls == 2, f"expected 2 model calls, got {MockHandler.calls}"
    finally:
        srv.shutdown()


check("Groq/OpenAI tool loop (mock server, get_time dispatch)", t_openai_loop)


# --- 4. all modules import cleanly with no keys set ---
def t_imports():
    import importlib
    for m in ["config", "memory", "tools", "brain", "voice", "server",
              "jarvis", "integrations", "integrations._common",
              "integrations.notion", "integrations.spotify",
              "integrations.spotify_auth", "integrations.github",
              "integrations.google", "integrations.discord_bot",
              "integrations.computer", "integrations.browser",
              "persona", "router", "integrations.personal", "integrations.school", "widget"]:
        try:
            importlib.import_module(m)
        except RuntimeError:
            pass  # expected: integration skipped (no keys / flag off)
        except ImportError as e:
            # missing optional dep on this Linux box
            if any(k in str(e) for k in ("pyttsx3", "discord", "google",
                                         "playwright", "sounddevice",
                                         "pvporcupine", "faster_whisper", "tkinter")):
                pass
            else:
                raise


check("all modules import (or skip cleanly with no keys)", t_imports)


# --- 5. integration loader: no keys -> core tools only, no crash ---
def t_loader():
    import tools
    names = [t["schema"]["function"]["name"] for t in tools.TOOLS]
    assert "get_time" in names and "web_search" in names, names
    assert "search_notion" not in names, "notion loaded without a key!"
    assert "spotify_play" not in names, "spotify loaded without keys!"
    assert "see_screen" not in names, "computer use loaded while off!"


check("plugin loader skips everything with no keys", t_loader)


# --- 6. personalization: router, countdowns, study timer, school ---
def _names():
    import tools
    return {t["schema"]["function"]["name"] for t in tools.TOOLS}


def t_personal_loaded():
    n = _names()
    for need in ("countdowns", "study_start", "start_workflow", "morning_briefing",
                 "weekend_plan", "get_grades", "class_check", "class_materials"):
        assert need in n, f"{need} missing from {sorted(n)}"


check("personal + school tools load with no keys", t_personal_loaded)


def t_fast_path():
    import tools
    from router import fast_path
    tm = {t["schema"]["function"]["name"]: t["function"] for t in tools.TOOLS}
    assert "2026" in fast_path("what time is it?", tm)
    assert "SAT" in fast_path("how many days until SAT", tm)
    assert fast_path("explain recursion to me", tm) is None
    assert fast_path("open the pod bay doors", tm) is None      # unknown app -> model, not `start junk`
    assert fast_path("Jarvis, what's the date", tm) is not None  # wake-word prefix stripped
    # the long, vague stuff must go to the model
    assert fast_path("plan my weekend around my chem test and usaco", tm) is None


check("router fast path: crisp commands instant, vague ones go to the model", t_fast_path)


def t_select_tools():
    import tools
    from router import select_tools
    full = len(tools.TOOLS)
    pick = lambda q: {t["schema"]["function"]["name"] for t in select_tools(
        [{"role": "user", "content": q}], tools.TOOLS)}
    g = pick("what are my grades in chem and what's due")
    assert "get_grades" in g and "class_check" in g and "browser_open" not in g
    assert len(g) < full
    assert "countdowns" in pick("anything else going on")         # fallback still useful
    assert "get_time" in pick("zzz")                              # core always present


check("router sends a small tool subset per request", t_select_tools)


def t_countdown_and_study():
    import tempfile
    import integrations.personal as P
    P.DATA_DIR = Path(tempfile.mkdtemp())
    rows = P.countdown_rows()
    assert rows and rows[0][0] == "SAT"
    assert "Added" in P.add_countdown("DECA ICDC", "2027-04-25")
    assert "YYYY-MM-DD" in P.add_countdown("bad", "tomorrow")
    assert "Removed" in P.remove_countdown("deca icdc")
    assert "Timer started" in P.study_start("USACO")
    assert "Already timing" in P.study_start("again")
    assert "Logged" in P.study_stop("test")
    assert "USACO" in P.study_summary(7)
    assert "No timer" in P.study_stop()


check("countdowns + study timer persist and validate", t_countdown_and_study)


def t_school():
    import integrations.school as S
    cs = [{"id": 1, "name": "AP Chemistry"}, {"id": 2, "name": "AP Computer Science A", "course_code": "APCSA"},
          {"id": 3, "name": "AP English Language"}, {"id": 4, "name": "AP United States History"},
          {"id": 5, "name": "AP Physics 1"}, {"id": 6, "name": "AP Statistics"}, {"id": 7, "name": "Precalculus"}]
    f = lambda q: S.find_course(q, cs)["id"]
    assert f("chem") == 1 and f("csa") == 2 and f("lang") == 3
    assert f("physics") == 5 and f("stats") == 6 and f("precalc") == 7
    assert "not set up" in S.grades().lower() or "Problems" in S.grades()   # no keys: clear message, no crash
    ic = S._walk_ic({"students": [{"terms": [{"termName": "Q2", "courses": [
        {"courseName": "AP Chemistry", "gradingTasks": [{"taskName": "Q2", "progressPercent": 87.4,
                                                          "progressScore": "B"}]}]}]}]})
    assert ic and ic[0]["score"] == 87.4 and ic[0]["course"] == "AP Chemistry"


check("school: fuzzy class names, IC parsing, graceful when unconfigured", t_school)


def t_brain_fast_and_dedupe():
    import brain
    called = []
    orig = brain._openai_loop
    brain._openai_loop = lambda *a, **k: called.append(1) or "model"
    try:
        out = brain.ask([{"role": "user", "content": "what time is it"}])
        assert "2026" in out and not called, "fast path should not call the model"
    finally:
        brain._openai_loop = orig
    n = {"c": 0}
    def f(x=""):
        n["c"] += 1
        return "ok"
    cache = {}
    r = brain._run_calls([("f", {"x": "1"}), ("f", {"x": "1"})], {"f": f}, cache)
    r2 = brain._run_calls([("f", {"x": "1"})], {"f": f}, cache)
    assert n["c"] <= 2 and "do not repeat" in r2[0], (n, r2)
    assert "no tool called" in brain._run_calls([("nope", {})], {}, {})[0]
    assert "bad arguments" in brain._run_calls([("f", "oops")], {"f": f}, {})[0]


check("brain: fast path skips the model; repeat/unknown/bad-arg calls handled", t_brain_fast_and_dedupe)


def t_server_auth():
    from fastapi.testclient import TestClient
    import server
    server.SERVER_TOKEN = "secret"
    c = TestClient(server.app)
    assert c.post("/ask", json={"message": "hi"}).status_code == 401
    assert c.get("/api/dashboard").status_code == 401
    d = c.get("/api/dashboard", headers={"Authorization": "Bearer secret"})
    assert d.status_code == 200 and "countdowns" in d.json(), d.text[:200]


check("server: token auth blocks grades/dashboard without the token", t_server_auth)


def t_canvas_mock():
    import datetime as dt
    import integrations.school as S

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer tok", "token not sent"
            due = (dt.date.today() + dt.timedelta(days=2)).isoformat() + "T23:59:00Z"
            path = self.path.split("?")[0]
            data = {
                "/api/v1/courses": [
                    {"id": 1, "name": "AP Chemistry", "enrollments": [
                        {"type": "student", "computed_current_score": 87.4, "computed_current_grade": "B"}]},
                    {"id": 2, "name": "AP Statistics", "enrollments": [
                        {"type": "student", "computed_current_score": 84.0, "computed_current_grade": "B"}]}],
                "/api/v1/planner/items": [
                    {"context_name": "AP Chemistry", "plannable_type": "assignment",
                     "plannable": {"title": "Titration Lab", "due_at": due, "points_possible": 50},
                     "submissions": {"submitted": False}},
                    {"context_name": "AP Statistics", "plannable_type": "assignment",
                     "plannable": {"title": "Done HW", "due_at": due},
                     "submissions": {"submitted": True}}],
                "/api/v1/announcements": [{"title": "Lab Friday", "message": "<p>Bring goggles</p>"}],
            }.get(path, [])
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    S.CANVAS_BASE_URL, S.CANVAS_TOKEN = f"http://127.0.0.1:{srv.server_address[1]}", "tok"
    try:
        assert "87.4" in S.canvas_grades()[0]["score"].__str__()
        out = S.upcoming_work(7)
        assert "Titration Lab" in out and "Done HW" not in out, out    # submitted work is hidden
        cc = S.class_check("chem")
        assert "AP Chemistry" in cc and "Titration Lab" in cc and "Bring goggles" in cc, cc
        assert "No class matches" in S.class_check("underwater basket weaving")
    finally:
        srv.shutdown()


check("school: Canvas grades/due/class_check against a mock Canvas API", t_canvas_mock)


print()
failed = [r for r in results if r[1] == "FAIL"]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
