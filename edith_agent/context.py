"""What the user most recently asked - lets tools check that an action was really requested."""
import threading

_lock = threading.Lock()
_last = {"text": ""}


def set_user_text(text):
    with _lock:
        _last["text"] = text or ""


def user_text():
    with _lock:
        return _last["text"]
