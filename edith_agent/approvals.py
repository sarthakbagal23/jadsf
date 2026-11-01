"""Blocking approvals and questions, answerable from the terminal, voice, or phone."""
import itertools
import threading
import time

from edith_agent.events import emit

_ids = itertools.count(1)
_lock = threading.Lock()
_pending = []          # approvals, oldest first
_questions = []        # open questions to the user


class _Item:
    def __init__(self, text, kind, **extra):
        self.id = next(_ids)
        self.text = text
        self.kind = kind
        self.extra = extra
        self.event = threading.Event()
        self.result = None
        self.created = time.time()

    def public(self):
        return {"id": self.id, "kind": self.kind, "text": self.text, **self.extra}


def request(summary, category="", timeout=180):
    """Ask the user to approve an action. Blocks the task thread; denies on timeout."""
    item = _Item(summary, "approval", category=category)
    with _lock:
        _pending.append(item)
    emit("approval", f"Approval needed: {summary}  (say yes / no)", approval=item.public())
    ok = item.event.wait(timeout) and bool(item.result)
    with _lock:
        if item in _pending:
            _pending.remove(item)
    if not item.event.is_set():
        emit("info", "No answer - I skipped that action.")
    return ok


def ask(question, timeout=300):
    """Ask the user a free-form question. Returns their answer or None."""
    item = _Item(question, "question")
    with _lock:
        _questions.append(item)
    emit("answer_needed", f"Question: {question}", question=item.public())
    got = item.event.wait(timeout)
    with _lock:
        if item in _questions:
            _questions.remove(item)
    return item.result if got else None


def pending():
    with _lock:
        return _pending[0].public() if _pending else None


def open_question():
    with _lock:
        return _questions[0].public() if _questions else None


def resolve(ok, approval_id=None):
    """Answer the oldest (or a specific) pending approval. Returns True if one was waiting."""
    with _lock:
        item = next((i for i in _pending if approval_id in (None, i.id)), None)
        if item:
            _pending.remove(item)
    if not item:
        return False
    item.result = bool(ok)
    item.event.set()
    emit("info", ("Approved." if ok else "Denied.") + f" ({item.text[:60]})")
    return True


def answer(text, question_id=None):
    with _lock:
        item = next((i for i in _questions if question_id in (None, i.id)), None)
        if item:
            _questions.remove(item)
    if not item:
        return False
    item.result = text
    item.event.set()
    return True


def cancel_all():
    """Release anything waiting (used when a task is cancelled)."""
    with _lock:
        items = _pending + _questions
        _pending.clear(); _questions.clear()
    for i in items:
        i.result = False if i.kind == "approval" else None
        i.event.set()
