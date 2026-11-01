"""Instant commands: crisp requests run straight away, no model, so they are quick and can't mis-route.

Returns reply text, or None to let the normal router/model handle it. Only high-confidence
patterns live here - anything ambiguous goes to the model, which has the same tools.
"""
import re

from edith_agent import approvals, context, playbooks
from edith_agent.runner import MANAGER

YES = r"(yes|yeah|yep|yup|y|ok|okay|sure|approve|approved|go ahead|do it|go for it|confirm|proceed)"
NO = r"(no|nope|nah|n|deny|denied|don't|do not|stop|skip|cancel|never ?mind|negative)"
_WORD = r"[a-z0-9' &\-]+"
_CONFIGURABLE = {"canvas", "ic", "infinite campus", "classlink", "dawg time", "student support",
                 "student support time"}     # real sites that are only 'known' once set in .env


def _course_words():
    from router import _course_words as cw
    return cw()


def _bg(label, fn, private=True):
    from edith_agent.events import install_default_sinks
    install_default_sinks()
    t = MANAGER.start_playbook(label, fn, private=private)
    return f"On it (task #{t.id})."


def match(text, tool_map=None):
    t = re.sub(r"[?!.,]", "", text.lower()).strip()
    t = re.sub(r"^(hey |ok |okay )?(edith|please)\s*,?\s*", "", t).strip()
    if not t:
        return None
    context.set_user_text(text)

    # ---- answering something EDITH asked (approval first, then open questions)
    if approvals.pending():
        if re.fullmatch(YES + r"( please| thanks)?", t):
            approvals.resolve(True)
            return "Approved."
        if re.fullmatch(NO + r"( thanks)?", t):
            approvals.resolve(False)
            return "Okay, I won't."
    q = approvals.open_question()
    if q:
        if re.fullmatch(r"(cancel|stop|never ?mind)( (it|that|the task))?", t):
            MANAGER.cancel()
            return "Cancelled."
        approvals.answer(text)
        return "Got it."

    # ---- control
    if re.fullmatch(r"(cancel|stop|abort|kill)( (the |that |this )?(current )?(task|job|it|that))?", t) and \
            (MANAGER.current or MANAGER.q):
        task = MANAGER.cancel()
        return f"Cancelled task #{task.id}." if task else "Nothing is running."
    if re.fullmatch(r"(what('s| is) )?(the )?(status|progress)|what are you (doing|working on)|how('s| is) it going", t):
        return MANAGER.status()
    if re.fullmatch(r"(list|show|what are)( my| the| all)?( open)? tabs", t):
        return playbooks.list_tabs()
    if re.fullmatch(r"close( all)?( the| my)? tabs", t):
        return playbooks.close_all_tabs()

    # ---- odd / even schedule
    m = re.fullmatch(r"(?:my )?(" + _WORD + r"?) (?:is|are|meets?)(?: an?)? (odd|even)(?: day| days)?(?: class)?", t)
    if m and len(m[1].split()) <= 4 and not re.search(r"\b(classes|days)\b", m[1]) and \
            set(m[1].split()) & _course_words():          # "what is even" must not become a class
        return playbooks.set_class_day(m[1].strip(), m[2])
    m = re.fullmatch(r"(?:my )?(odd|even)(?: day)? (?:classes|days) are (.+)", text.lower().strip(" .!?"))
    if m:                                              # use the raw text: commas separate class names
        msgs = [playbooks.set_class_day(n, m[1]) for n in playbooks.split_names(m[2])]
        return msgs[-1] if msgs else None

    # ---- grade sweep: tabs for each class
    m = re.search(r"\b(odd|even)\b.*\b(classes|class|grades?|days?)\b|\b(classes|class|grades?)\b.*\b(odd|even)\b", t)
    if m and re.search(r"\b(check|open|pull|get|show|see|grades?|canvas|look)\b", t):
        which = "odd" if "odd" in t else "even"
        return _bg(f"Grades sweep ({which})", lambda: playbooks.grades_sweep(which))
    if re.search(r"\b(open|pull up|check)\b.*\bcanvas\b.*\b(each|every|all)\b.*\b(class|classes|course)", t) or \
            re.fullmatch(r"(check|get|pull|show)( me)? (all|every|each)( of)?( my)? (class|classes|grades)( grades)?", t):
        return _bg("Grades sweep (all)", lambda: playbooks.grades_sweep("all"))

    # ---- Student Support Time
    if re.search(r"student support|dawg time|support time|\bsession\b", t) or re.fullmatch(r"check me in", t):
        if re.search(r"check( me)? in\b|checkin", t):
            req = text
            return _bg("Student Support Time check-in", lambda: __import__("edith_agent.dawg", fromlist=["x"]).checkin(req))
        if re.search(r"sign( me)? up|register( me)?|book( me)?|enroll( me)?|reserve", t):
            from edith_agent import tools as T
            return T.support_time_signup(text)

    # ---- research / ECs
    if re.search(r"\b(research|find|search|look (for|up)|hunt|dig up)\b", t) and \
            re.search(r"\bec\b|\becs\b|extracurricular|opportunit|internship|summer program|research program|"
                      r"competitions?|volunteer", t):
        topic = re.sub(r"^(please )?(can you |could you )?(research|find( me)?|search( for)?|look (for|up)|hunt for|dig up)\s*", "", t)
        topic = re.sub(r"\becs?\b", "extracurricular activities", topic)
        count = 6
        return _bg("Research: " + topic[:60], lambda: playbooks.research_opportunities(
            topic=topic if len(topic.split()) > 2 else f"{topic} for high school students interested in computer science",
            count=count), private=False)
    if re.fullmatch(r"(show|list|what are)( me)?( my)?( saved)? (opportunities|ecs?|research options)", t):
        return playbooks.list_opportunities()

    # ---- big picture
    if re.search(r"big picture|what should i (focus on|prioriti[sz]e|work on)|prioriti[sz]e (my )?(week|work)|"
                 r"where do i stand|what matters (most )?(this|today)", t):
        return _bg("Big picture", __import__("edith_agent.insights", fromlist=["x"]).big_picture)

    # ---- open one or several sites in parallel tabs
    m = re.fullmatch(r"(?:open|launch|pull up|bring up|go to|show me)(?: up)? (.+?)(?: in (?:new )?tabs?)?", t)
    if m:
        names = playbooks.split_names(m[1])
        known = playbooks.sites()
        from tools import APPS
        looks_like_site = lambda n: n in known or n in APPS or re.search(r"\.[a-z]{2,}(/|$)", n)
        if names and any(n in known for n in names) and all(looks_like_site(n) or n in _CONFIGURABLE for n in names) \
                and not all(n in APPS for n in names):
            return playbooks.open_sites(names)
    return None
