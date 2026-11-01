"""Privacy policy: school data never goes to a cloud model.

Mirrors the rule brain.ask already enforces for chat: anything touching school
sites or school topics is handled by the LOCAL Ollama model only. Page text from
Canvas / Infinite Campus / ClassLink / Student Support Time is never sent to
Groq or OpenRouter, and neither are screenshots of those pages.
"""
import re
from urllib.parse import urlsplit

from config import (CANVAS_BASE_URL, CLASSLINK_URL, IC_BASE_URL, OLLAMA_HOST,
                    STUDENT_SUPPORT_TIME_URL)
import router

_BUILTIN_HOSTS = ("instructure.com", "infinitecampus.org", "classlink.com",
                  "studentsupporttime.com", "forsyth.k12.ga.us")


def _host(url):
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def school_hosts():
    hosts = set(_BUILTIN_HOSTS)
    for u in (CANVAS_BASE_URL, IC_BASE_URL, CLASSLINK_URL, STUDENT_SUPPORT_TIME_URL):
        if u:
            hosts.add(_host(u))
    return {h for h in hosts if h}


def is_school_url(url):
    h = _host(url)
    return bool(h) and any(h == s or h.endswith("." + s) for s in school_hosts())


def is_school_text(text):
    return bool(re.search(router.SCHOOL_PATTERN, text or "", re.I))


def local_llm_available():
    host = _host(OLLAMA_HOST)
    return host in ("localhost", "127.0.0.1", "::1")


class PrivacyError(RuntimeError):
    pass
