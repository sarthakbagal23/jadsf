"""Tools the chat brain can call to put the agent to work.

Long jobs run in the background (queued, narrated, cancellable) so the chat stays free.
Their results arrive as events - in the terminal, on the phone, and by voice.
"""
from edith_agent import approvals, context, dawg, insights, playbooks, runner, safety
from edith_agent.events import install_default_sinks
from edith_agent.runner import MANAGER


def _bg(label, fn, private=True):
    install_default_sinks()
    t = MANAGER.start_playbook(label, fn, private=private)
    return f"On it (task #{t.id}). I'll report as I go."


def browse(goal, url=""):
    """Open-ended web task in the visible browser, narrated step by step."""
    install_default_sinks()
    # what you actually said decides what is authorised - not the wording the model chose for `goal`
    grants = safety.grants_from_request(context.user_text() or goal)
    t = MANAGER.start(goal, start_url=url, grants=grants)
    return f"On it (task #{t.id}). I'll narrate what I find as I go."


def computer_task(goal):
    install_default_sinks()
    grants = safety.grants_from_request(context.user_text() or goal)
    t = MANAGER.start(goal, grants=grants, surface="desktop")
    return f"On it (task #{t.id}) - working on the desktop."


def open_sites(sites):
    return playbooks.open_sites(sites)


def grades_sweep(which="all"):
    return _bg(f"Grades sweep ({which})", lambda: playbooks.grades_sweep(which))


def research_opportunities(topic="", count=6):
    kw = {"count": int(count or 6)}
    if topic:
        kw["topic"] = topic
    return _bg("Research: " + (topic or "EC and research opportunities"),
               lambda: playbooks.research_opportunities(**kw), private=False)


def support_time_checkin():
    req = context.user_text()
    return _bg("Student Support Time check-in", lambda: dawg.checkin(req))


def support_time_signup(request):
    install_default_sinks()
    from config import STUDENT_SUPPORT_TIME_URL
    grants = safety.grants_from_request(context.user_text() or request)
    t = MANAGER.start("On Student Support Time (Dawg Time): " + request, start_url=STUDENT_SUPPORT_TIME_URL,
                      grants=grants, private=True)
    return f"On it (task #{t.id}). I'll read the sessions and only sign up for what you asked."


def task_status():
    return MANAGER.status()


def cancel_task():
    t = MANAGER.cancel()
    return f"Cancelled task #{t.id}." if t else "Nothing is running."


def big_picture():
    return _bg("Big picture", insights.big_picture)


def tool(name, description, properties, required, fn):
    return {"schema": {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}},
            "function": fn}


TOOLS = [
    tool("browse", "Do an open-ended task on the web in the visible browser (look things up, fill forms, navigate "
         "sites). Narrates while working. Use for anything the specific tools below don't cover.",
         {"goal": {"type": "string", "description": "What to accomplish, with every detail the user gave"},
          "url": {"type": "string", "description": "Optional starting URL"}}, ["goal"], browse),
    tool("computer_task", "Do a task in desktop apps on the laptop (needs computer control enabled).",
         {"goal": {"type": "string"}}, ["goal"], computer_task),
    tool("open_sites", "Open one or more sites at once, each in its own tab (canvas, ic, github, gmail, drive, "
         "notion, usaco, classlink, dawg time, or any domain).",
         {"sites": {"type": "string", "description": "e.g. 'canvas, github and gmail'"}}, ["sites"], open_sites),
    tool("list_tabs", "List the open browser tabs.", {}, [], playbooks.list_tabs),
    tool("close_tabs", "Close all browser tabs EDITH opened.", {}, [], playbooks.close_all_tabs),
    tool("grades_sweep", "Open a Canvas grades tab for each class (all, odd, even, or named classes), read them "
         "side by side with Infinite Campus, and report with trends.",
         {"which": {"type": "string", "description": "all | odd | even | class names like 'chem, lang'"}}, [], grades_sweep),
    tool("set_class_day", "Remember whether a class meets on odd or even days.",
         {"course": {"type": "string"}, "day": {"type": "string", "enum": ["odd", "even", "both", "clear"]}},
         ["course", "day"], playbooks.set_class_day),
    tool("research_opportunities", "Search the web for extracurricular, research, summer-program and internship "
         "opportunities; read the best pages in tabs and save a shortlist.",
         {"topic": {"type": "string"}, "count": {"type": "integer"}}, [], research_opportunities),
    tool("list_opportunities", "Show saved opportunities.", {}, [], playbooks.list_opportunities),
    tool("support_time_checkin", "Check the user in to their Student Support Time session. ONLY when they asked to be checked in.",
         {}, [], support_time_checkin),
    tool("support_time_signup", "Sign the user up for a Student Support Time session they described. ONLY when they asked to sign up.",
         {"request": {"type": "string", "description": "which teacher/subject/date/time"}}, ["request"], support_time_signup),
    tool("big_picture", "Prioritised overview: grades and trends, deadlines, SAT countdown, study time, opportunities.",
         {}, [], big_picture),
    tool("task_status", "What EDITH is working on / last result.", {}, [], task_status),
    tool("cancel_task", "Stop the current background task.", {}, [], cancel_task),
]
