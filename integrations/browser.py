"""Browser control — exact, reliable web automation via Playwright.

Use this instead of screen-clicking whenever the task is on the web:
selectors never miss, unlike vision coordinates.

Install:  pip install playwright
          playwright install chromium
"""
from integrations._common import tool

try:
    import playwright  # noqa: F401  (checked at load so the loader can skip us)
except ImportError:
    raise RuntimeError("playwright not installed — pip install playwright && playwright install chromium")

_STATE = {"pw": None, "browser": None, "page": None}


def _page():
    if _STATE["page"] is not None:
        return _STATE["page"]
    from playwright.sync_api import sync_playwright
    from config import DATA_DIR
    pw = sync_playwright().start()
    # persistent profile: logins (Canvas, Google...) survive between runs
    browser = pw.chromium.launch_persistent_context(
        str(DATA_DIR / "browser_profile"), headless=False)
    page = browser.pages[0] if browser.pages else browser.new_page()
    _STATE.update(pw=pw, browser=browser, page=page)
    return page


def browser_open(url):
    p = _page()
    p.goto(url, wait_until="domcontentloaded", timeout=20000)
    return f"Opened {url}. Title: {p.title()}"


def browser_text():
    return _page().inner_text("body")[:5000]


def browser_click(selector):
    _page().click(selector, timeout=5000)
    return f"Clicked {selector}."


def browser_fill(selector, text):
    _page().fill(selector, text, timeout=5000)
    return f"Filled {selector}."


def browser_screenshot():
    from config import DATA_DIR
    path = DATA_DIR / "screenshots" / "browser.png"
    path.parent.mkdir(exist_ok=True)
    _page().screenshot(path=str(path))
    return f"Screenshot saved to {path}."


TOOLS = [
    tool("browser_open", "Open a URL in a real Chrome window.",
         {"url": {"type": "string"}}, ["url"], browser_open),
    tool("browser_text", "Read the visible text of the current page.",
         {}, [], browser_text),
    tool("browser_click", "Click an element by CSS selector.",
         {"selector": {"type": "string"}}, ["selector"], browser_click),
    tool("browser_fill", "Fill a form field by CSS selector.",
         {"selector": {"type": "string"}, "text": {"type": "string"}},
         ["selector", "text"], browser_fill),
    tool("browser_screenshot", "Screenshot the current page to a file.",
         {}, [], browser_screenshot),
]
