"""Event bus: everything the agent does becomes an event.

One stream feeds every surface at once - the terminal, the phone app (long-poll),
optional voice, and optional phone push - so EDITH can "report while looking"
without each feature printing on its own.
"""
import itertools
import threading
import time
from collections import deque

import requests

from config import AGENT_NARRATE, NTFY_SERVER, NTFY_TOPIC

_RING = 500


class EventBus:
    def __init__(self):
        self._events = deque(maxlen=_RING)
        self._ids = itertools.count(1)
        self._cond = threading.Condition()
        self._sinks = []

    def emit(self, kind, text="", **data):
        """kind: task_start | say | step | tab | approval | answer_needed | done | error | info"""
        ev = {"id": next(self._ids), "t": time.time(), "kind": kind, "text": text, **data}
        with self._cond:
            self._events.append(ev)
            self._cond.notify_all()
        for sink in list(self._sinks):
            try:
                sink(ev)
            except Exception as e:           # a broken sink must never break a task
                print(f"[events] sink failed: {e}")
        return ev

    def since(self, last_id=0, wait=0.0, limit=100):
        """Events newer than last_id; optionally block up to `wait` seconds for the first one."""
        deadline = time.time() + wait
        with self._cond:
            while True:
                out = [e for e in self._events if e["id"] > last_id][:limit]
                if out or wait <= 0:
                    return out
                left = deadline - time.time()
                if left <= 0:
                    return []
                self._cond.wait(left)

    def add_sink(self, fn):
        self._sinks.append(fn)

    def remove_sink(self, fn):
        if fn in self._sinks:
            self._sinks.remove(fn)

    def last_id(self):
        with self._cond:
            return self._events[-1]["id"] if self._events else 0


BUS = EventBus()
emit = BUS.emit

# --------------------------------------------------------------------- sinks

_ICON = {"task_start": ">>", "say": "..", "step": "  ", "tab": "[]", "approval": "??",
         "answer_needed": "??", "done": "OK", "error": "!!", "info": "--"}


def console_sink(ev):
    if ev["kind"] == "step" and AGENT_NARRATE != "all":
        return
    print(f"\n[EDITH {_ICON.get(ev['kind'], '..')}] {ev['text']}", flush=True)


_speak_q = deque(maxlen=4)
_speak_lock = threading.Lock()


def _speak_async(text):
    """Speak on a worker thread so narration never blocks the browser."""
    def run():
        with _speak_lock:                    # one voice at a time
            try:
                from voice import speak
                speak(text)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def voice_sink(ev):
    if AGENT_NARRATE == "off":
        return
    key = ev["kind"] in ("task_start", "approval", "answer_needed", "done", "error")
    if key or (AGENT_NARRATE == "all" and ev["kind"] in ("say", "step")):
        _speak_async(ev["text"][:200])


_PUSH = {"approval": "EDITH needs your approval", "answer_needed": "EDITH has a question",
         "done": "EDITH finished a task", "error": "EDITH hit a problem"}


def push_sink(ev):
    """Phone push via ntfy. Only ever sends a generic line - details stay on the laptop."""
    if not NTFY_TOPIC or ev["kind"] not in _PUSH:
        return
    def go():
        try:
            requests.post(f"{NTFY_SERVER.rstrip('/')}/{NTFY_TOPIC}", data=_PUSH[ev["kind"]].encode(),
                          headers={"Title": "EDITH", "Priority": "high" if ev["kind"] == "approval" else "default"},
                          timeout=8)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


_installed = False


def install_default_sinks():
    global _installed
    if _installed:
        return
    _installed = True
    BUS.add_sink(console_sink)
    BUS.add_sink(voice_sink)
    BUS.add_sink(push_sink)
