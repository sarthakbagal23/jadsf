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
        out = brain._openai_loop(f"http://127.0.0.1:{port}/v1", "dummy",
                                 "mock-model",
                                 [{"role": "user", "content": "what time is it"}])
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
              "integrations.computer", "integrations.browser"]:
        try:
            importlib.import_module(m)
        except RuntimeError:
            pass  # expected: integration skipped (no keys / flag off)
        except ImportError as e:
            # missing optional dep on this Linux box
            if any(k in str(e) for k in ("pyttsx3", "discord", "google",
                                         "playwright", "sounddevice",
                                         "pvporcupine", "faster_whisper")):
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


print()
failed = [r for r in results if r[1] == "FAIL"]
print(f"{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
