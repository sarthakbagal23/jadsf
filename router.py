"""Speed + reliability layer in front of the LLM.

1. fast_path(): simple, unambiguous commands ("what time is it", "open
   chrome", "check chem", "pause") run the tool directly - no model call,
   so they answer in milliseconds and cannot fail on a bad tool choice.
2. select_tools(): everything else only sends the model the few tools that
   could matter, instead of all ~45. Smaller menu = faster, cheaper, and far
   fewer wrong tool picks.
"""
import re

CORE = ["get_time", "remember_fact", "recall_fact", "take_note"]

GROUPS = [
    (r"weather|rain|temperature|forecast|cold|hot outside|umbrella", ["get_weather"]),
    (r"\bopen\b|launch|battery|cpu|ram\b|system|laptop", ["open_app", "system_info", "start_workflow"]),
    (r"grade|gpa|class|homework|assignment|due|canvas|infinite|campus|school|test|quiz|exam|"
     r"material|syllabus|chem|csa|\blang|apush|history|physics|stat|precalc|calc|weekend|plan",
     ["get_grades", "upcoming_work", "class_check", "class_materials", "weekend_plan",
      "morning_briefing", "study_summary"]),
    (r"countdown|days (until|till|left)|how long until|\bsat\b|deadline|competition|deca|tsa",
     ["countdowns", "add_countdown", "remove_countdown"]),
    (r"study|focus|timer|pomodoro|usaco|session", ["study_start", "study_stop", "study_summary"]),
    (r"mode|workflow|get (me )?(set|ready)|start (my )?(coding|school|study)",
     ["start_workflow"]),
    (r"brief|good morning|my day|what.s today|agenda", ["morning_briefing", "countdowns", "get_weather"]),
    (r"play|song|music|spotify|pause|skip|volume|playing|playlist|album|artist",
     ["spotify_now_playing", "spotify_play", "spotify_pause", "spotify_next",
      "spotify_previous", "spotify_volume"]),
    (r"notion|workspace|my pages|database", ["search_notion", "read_notion_page",
                                             "create_notion_page", "query_notion_database"]),
    (r"github|repo|issue|commit|anchor|pull request|code on",
     ["github_repos", "github_issues", "github_create_issue", "github_read_file", "github_search_code"]),
    (r"mail|gmail|calendar|event|meeting|schedule|invite",
     ["gmail_search", "gmail_read", "calendar_events", "calendar_create"]),
    (r"click|screen|window|scroll|type into|on my computer",
     ["see_screen", "computer_click", "computer_double_click", "computer_type", "computer_key",
      "computer_hotkey", "computer_scroll", "computer_focus_window"]),
    (r"website|browser|http|\.com|\.org|go to|log ?in|sign ?in|fill|webpage",
     ["browser_open", "browser_text", "browser_click", "browser_fill", "browser_screenshot"]),
    (r"search|look up|google|who |what is|latest|news|price|score", ["web_search"]),
]
FALLBACK = ["web_search", "countdowns"]


def select_tools(messages, all_tools):
    """Return the subset of `all_tools` relevant to the last two user messages."""
    users = [m["content"] for m in messages if m.get("role") == "user"][-2:]
    text = " ".join(users).lower()
    wanted = set(CORE)
    for pattern, names in GROUPS:
        if re.search(pattern, text):
            wanted.update(names)
    if wanted == set(CORE):
        wanted.update(FALLBACK)
    chosen = [t for t in all_tools if t["schema"]["function"]["name"] in wanted]
    return chosen or all_tools


# ---------------------------------------------------------------- fast path

def _course_words():
    from integrations.school import ALIASES
    return set(ALIASES) | {"ap", "chemistry", "physics", "statistics", "precalculus",
                           "language", "csa"}


def fast_path(text, tool_map):
    """Run a tool directly for crisp commands. Returns reply text, or None."""
    t = re.sub(r"[?!.,]", "", text.lower()).strip()
    t = re.sub(r"^(hey |ok |okay )?(jarvis|please)\s*,?\s*", "", t).strip()
    if not t or len(t.split()) > 9:
        return None

    def run(name, **kw):
        fn = tool_map.get(name)
        if fn is None:
            return None
        try:
            return str(fn(**kw))
        except Exception as e:
            return f"{name} failed: {e}"

    if re.fullmatch(r"(what('s| is) )?(the )?(current )?(time|date)( is it)?|what time is it|what day is it( today)?", t):
        return run("get_time")
    if re.fullmatch(r"(what('s| is) )?(the )?weather( (like|today|outside|now))?|how('s| is) the weather", t):
        return run("get_weather")
    if re.fullmatch(r"(how (many )?days (until|till|to|left (until|till)) (the )?sat|sat countdown|countdowns?)", t):
        return run("countdowns")
    m = re.fullmatch(r"start (a |the )?(study|focus) (timer|session)( for ([a-z0-9 ]+?))?( for (\d+) min(ute)?s?)?", t)
    if m:
        return run("study_start", subject=m.group(5) or "study", minutes=int(m.group(7) or 0))
    if re.fullmatch(r"(stop|end|finish) (the |my )?(study |focus )?(timer|session)", t):
        return run("study_stop")
    if re.fullmatch(r"(open|launch|start) ([a-z0-9 ]+)", t):
        m = re.fullmatch(r"(open|launch|start) ([a-z0-9 ]+)", t)
        name = m.group(2).strip()
        if name.endswith(" mode") or name in ("coding", "school", "study", "usaco", "sat", "deca"):
            return run("start_workflow", name=name)
        from tools import APPS
        if name in APPS:  # unknown names go to the model, not to a blind `start <junk>`
            return run("open_app", name=name)
        return None
    m = re.fullmatch(r"(coding|school|study|usaco|sat|deca) mode|(start|enter) (coding|school|study|usaco|sat|deca)( mode)?", t)
    if m:
        return run("start_workflow", name=next(g for g in m.groups() if g in
                                                ("coding", "school", "study", "usaco", "sat", "deca")))
    if re.fullmatch(r"(how (much|long) (have i|did i) studied?( today| this week)?|study (summary|stats))", t):
        return run("study_summary")
    if re.fullmatch(r"(what are )?(my )?grades|(check |what('s| is) )?my grades|grade check", t):
        return run("get_grades")
    m = re.fullmatch(r"(what('s| is) )?(my )?grade in ([a-z0-9 ]+)|grades? (for|in) ([a-z0-9 ]+)", t)
    if m:
        return run("get_grades", course=(m.group(4) or m.group(6)).strip())
    m = re.fullmatch(r"check( on)?( my)? ([a-z0-9 ]+?)( class)?", t)
    if m and set(m.group(3).split()) & _course_words():
        return run("class_check", course=m.group(3).strip())
    if re.fullmatch(r"(what('s| is) )?(due|my homework)( (today|tomorrow|this week|soon))?|what do i have due( (today|tomorrow|this week))?", t):
        days = 1 if "today" in t else 2 if "tomorrow" in t else 7
        return run("upcoming_work", days=days)
    if re.fullmatch(r"(pause|stop)( the)?( music| song| spotify)?", t):
        return run("spotify_pause")
    if re.fullmatch(r"(skip|next)( the)?( song| track)?|skip", t):
        return run("spotify_next")
    if re.fullmatch(r"(previous|go back|last)( song| track)?", t):
        return run("spotify_previous")
    if re.fullmatch(r"(what('s| is) )?(this song|playing|now playing|what song is this|what('s| is) playing)", t):
        return run("spotify_now_playing")
    m = re.fullmatch(r"play ([a-z0-9' &\-]+)", t)
    if m and "spotify_play" in tool_map:
        return run("spotify_play", query=m.group(1).strip())
    return None
