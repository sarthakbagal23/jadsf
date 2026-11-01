"""What EDITH may do on its own, and what needs a human.

Policy (matches persona.py): when the user's own request clearly names an action
("check me in", "sign me up for ..."), EDITH proceeds with no second yes. Anything
risky that the request did NOT ask for stops and asks - and a few things always ask:
purchases and deletions. Page content can never grant permission: grants come only
from the user's own words, never from text on a web page (prompt-injection defence).
Credentials: EDITH never types passwords or verification codes (enforced in the
browser engine as well).
"""
import re
from dataclasses import dataclass, field

# category -> words on the thing being clicked. Checked in this order.
RISK = [
    ("purchase", r"\bbuy\b|purchase|checkout|check out|\bpay\b|payment|donate|place order|subscribe|upgrade"),
    ("delete", r"delete|remove|cancel|unenroll|\bdrop\b|withdraw|deactivate|erase|clear (all|data)"),
    ("checkin", r"check[ -]?(in|out)|clock[ -]?(in|out)|mark (me )?present"),
    ("signup", r"sign[ -]?up|register|enroll|reserve|\bbook\b|rsvp|join (the )?(session|class|waitlist)"),
    ("message", r"\bsend\b|\breply\b|\bpost\b|comment|publish|\bemail\b|\bshare\b"),
    ("apply", r"\bsubmit\b|\bapply\b|turn in|save changes|\bconfirm\b|finali[sz]e"),
]
ALWAYS_CONFIRM = {"purchase", "delete"}

# the user's own words -> categories they have authorised for this task
GRANT_WORDS = {
    "checkin": r"check(ing)?[ -]?(me )?in|clock (me )?in|mark me present",
    "signup": r"sign(ing)? (me )?up|register|enroll|reserve|\bbook\b|rsvp",
    "apply": r"\bsubmit\b|\bapply\b|turn in|fill (it )?(out|in)",
    "message": r"\bsend\b|\breply\b|\bpost\b|comment|\bemail\b|message",
}


def grants_from_request(text):
    t = (text or "").lower()
    return {cat for cat, pat in GRANT_WORDS.items() if re.search(pat, t)}


@dataclass
class Decision:
    verdict: str                 # allow | confirm | block
    category: str = ""
    reason: str = ""
    notes: list = field(default_factory=list)


def classify_text(label):
    for cat, pat in RISK:
        if re.search(pat, label or "", re.I):
            return cat
    return ""


def check_click(info, grants):
    """`info` comes from Engine.element_info. Returns a Decision."""
    label = info.get("text", "")
    tag, typ = info.get("tag", ""), info.get("type", "")
    href = info.get("href", "") or ""
    is_link = tag == "a" and href and not href.startswith(("#", "javascript:")) and info.get("role") != "button"
    cat = classify_text(label)
    if is_link and cat not in ALWAYS_CONFIRM:
        return Decision("allow", reason="navigation link")        # opening a page changes nothing
    if not cat and info.get("submit"):
        cat = "apply"                                              # an unlabeled form submit
    if not cat:
        return Decision("allow")
    if cat in ALWAYS_CONFIRM:
        return Decision("confirm", cat, f"'{label}' looks like a {cat} action - these always need your yes.")
    if cat in grants:
        return Decision("allow", cat, f"authorised by your request ({cat})", notes=["authorised"])
    return Decision("confirm", cat, f"'{label}' would {cat.replace('signup', 'sign you up')} - you didn't ask for that.")


def check_enter(focused, grants):
    """Pressing Enter inside a form submits it."""
    if focused.get("inForm") and focused.get("tag") in ("input", "select"):
        if "apply" in grants or "signup" in grants or "checkin" in grants or "message" in grants:
            return Decision("allow", "apply", "authorised by your request", notes=["authorised"])
        return Decision("confirm", "apply", "Pressing Enter here would submit a form.")
    return Decision("allow")
