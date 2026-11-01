"""Laptop control: windows, mouse, keyboard, clipboard, and Windows UI Automation.

OFF unless EDITH_COMPUTER_USE=1 (same switch as integrations/computer.py).

Why UI Automation first: clicking a button *by name* ("Save", "Play") through Windows'
accessibility tree is exact; clicking pixel coordinates guessed from a screenshot is not.
Mouse/keyboard primitives remain for apps that expose no accessibility tree.

Guards: pyautogui's corner-abort failsafe stays on; destructive hotkeys are refused; typing
is refused while a sign-in / password-manager window is in front; and clicking something that
looks like purchase/delete/send asks first (same rules as the browser).
"""
import re
import sys
import time

from config import JARVIS_COMPUTER_USE
from edith_agent import approvals, safety

BLOCKED_HOTKEYS = {("alt", "f4"), ("ctrl", "alt", "delete"), ("ctrl", "alt", "del"), ("win", "l"),
                   ("ctrl", "shift", "delete"), ("win", "r"), ("win", "x")}
SECRET_WINDOW = re.compile(r"password|sign[ -]?in|log[ -]?in|credential|bitwarden|1password|lastpass|keepass|"
                           r"authenticator|windows security", re.I)


class DesktopDisabled(RuntimeError):
    pass


def _enabled():
    if not JARVIS_COMPUTER_USE:
        raise DesktopDisabled("Computer control is off. Set EDITH_COMPUTER_USE=1 in .env to turn it on.")


_pg_mod = None


def _pg():
    """pyautogui, loaded lazily (it needs a real screen)."""
    global _pg_mod
    if _pg_mod is None:
        import pyautogui
        pyautogui.FAILSAFE = True            # slam the mouse into a screen corner to abort
        pyautogui.PAUSE = 0.05
        _pg_mod = pyautogui
    return _pg_mod


def _uia():
    from pywinauto import Desktop
    return Desktop(backend="uia")


# ------------------------------------------------------------------ windows

def windows():
    """Titles of visible top-level windows."""
    _enabled()
    try:
        return [w.window_text() for w in _uia().windows() if w.window_text().strip() and w.is_visible()]
    except Exception:
        import pygetwindow as gw
        return [t for t in gw.getAllTitles() if t.strip()]


def foreground_title():
    _enabled()
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return w.title if w else ""
    except Exception:
        try:
            return _uia().window(active_only=True).window_text()
        except Exception:
            return ""


def focus(title):
    _enabled()
    q = title.lower()
    for w in _uia().windows():
        if q in w.window_text().lower() and w.is_visible():
            w.set_focus()
            return f"Focused '{w.window_text()}'."
    return f"No window matches '{title}'. Open: " + "; ".join(windows()[:8])


def launch(app):
    _enabled()
    from tools import open_app
    return open_app(app)


# ------------------------------------------------------------- UI Automation

def ui_list(window="", limit=60):
    """Named clickable controls in a window - what the model reads instead of a screenshot."""
    _enabled()
    win = _find_window(window)
    out = []
    for c in win.descendants():
        try:
            name = (c.window_text() or "").strip()
            kind = c.element_info.control_type
            if name and kind in ("Button", "MenuItem", "Hyperlink", "TabItem", "CheckBox", "RadioButton",
                                 "ListItem", "Edit", "ComboBox", "Text") and c.is_visible():
                out.append(f"{kind}: {name[:60]}")
        except Exception:
            continue
        if len(out) >= limit:
            break
    return "\n".join(out) or "(no named controls found)"


def _find_window(title=""):
    d = _uia()
    if not title:
        return d.window(active_only=True)
    q = title.lower()
    for w in d.windows():
        if q in w.window_text().lower():
            return w
    raise RuntimeError(f"No window matches '{title}'.")


def ui_click(name, window="", grants=frozenset()):
    _enabled()
    cat = safety.classify_text(name)
    if cat and (cat in safety.ALWAYS_CONFIRM or cat not in grants):
        if not approvals.request(f'Click "{name}" in {window or "the front window"}', cat):
            return "DENIED by the user. Do not retry this."
    win = _find_window(window)
    for c in win.descendants():
        try:
            if (c.window_text() or "").strip().lower() == name.lower() and c.is_visible():
                c.invoke() if hasattr(c, "invoke") and c.element_info.control_type == "Button" else c.click_input()
                return f"Clicked '{name}'."
        except Exception:
            continue
    raise RuntimeError(f"No control named '{name}'. Try ui_list to see what's there.")


# ------------------------------------------------------- mouse and keyboard

def click_xy(x, y, double=False):
    _enabled()
    pg = _pg()
    w, h = pg.size()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(f"({x},{y}) is off screen ({w}x{h}).")
    pg.click(x, y, clicks=2 if double else 1)
    return f"Clicked ({x},{y})."


def type_text(text):
    _enabled()
    title = foreground_title()
    if SECRET_WINDOW.search(title):
        raise PermissionError(f"The front window ('{title[:40]}') looks like a sign-in or password screen. "
                              "EDITH won't type there - type it yourself.")
    _pg().write(text, interval=0.01)
    return f"Typed {len(text)} characters."


def hotkey(keys):
    _enabled()
    keys = [k.lower() for k in keys]
    if tuple(keys) in BLOCKED_HOTKEYS:
        raise PermissionError(f"The shortcut {'+'.join(keys)} is blocked for safety.")
    _pg().hotkey(*keys)
    return f"Pressed {'+'.join(keys)}."


def press(key):
    _enabled()
    _pg().press(key.lower())
    return f"Pressed {key}."


def scroll(amount):
    _enabled()
    _pg().scroll(int(amount))
    return "Scrolled."


def screenshot(path=None):
    _enabled()
    from config import DATA_DIR
    path = path or str(DATA_DIR / "screenshots" / "desktop.png")
    (DATA_DIR / "screenshots").mkdir(exist_ok=True)
    _pg().screenshot(path)
    return path


def clipboard_get():
    _enabled()
    import tkinter
    r = tkinter.Tk(); r.withdraw()
    try:
        return r.clipboard_get()
    finally:
        r.destroy()


def clipboard_set(text):
    _enabled()
    import tkinter
    r = tkinter.Tk(); r.withdraw()
    r.clipboard_clear(); r.clipboard_append(text); r.update(); r.destroy()
    return "Copied."


# ------------------------------------------------- agent integration (runner)

def observe_text():
    """What the agent sees when working on the desktop instead of a web page."""
    _enabled()
    front = foreground_title()
    try:
        controls = ui_list("", 50)
    except Exception as e:
        controls = f"(no accessibility info: {str(e)[:60]})"
    return (f"SURFACE: desktop\nFRONT WINDOW: {front}\nOPEN WINDOWS: " + "; ".join(windows()[:10]) +
            f"\nCONTROLS IN FRONT WINDOW:\n{controls}")


def _s(name, desc, props, req=()):
    return {"schema": {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(req)}}}}


def agent_schemas():
    if not JARVIS_COMPUTER_USE:
        return []
    return [
        _s("desktop_focus", "Bring a window to the front by part of its title.", {"title": {"type": "string"}}, ["title"]),
        _s("desktop_launch", "Launch an app (chrome, vscode, spotify, notepad, calculator...).", {"app": {"type": "string"}}, ["app"]),
        _s("desktop_ui_click", "Click a named button/menu/control in a window (preferred over coordinates).",
           {"name": {"type": "string"}, "window": {"type": "string"}}, ["name"]),
        _s("desktop_click_xy", "Click screen pixel coordinates (last resort).",
           {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
        _s("desktop_type", "Type text into the focused control.", {"text": {"type": "string"}}, ["text"]),
        _s("desktop_hotkey", "Press a key combo, e.g. ['ctrl','s'].", {"keys": {"type": "array", "items": {"type": "string"}}}, ["keys"]),
        _s("desktop_press", "Press one key.", {"key": {"type": "string"}}, ["key"]),
    ]


def run(name, a, grants=frozenset()):
    if not name.startswith("desktop_"):
        raise KeyError(name)
    _enabled()
    return {
        "desktop_focus": lambda: focus(a["title"]),
        "desktop_launch": lambda: launch(a["app"]),
        "desktop_ui_click": lambda: ui_click(a["name"], a.get("window", ""), grants),
        "desktop_click_xy": lambda: click_xy(int(a["x"]), int(a["y"])),
        "desktop_type": lambda: type_text(a["text"]),
        "desktop_hotkey": lambda: hotkey(a["keys"]),
        "desktop_press": lambda: press(a["key"]),
    }[name]()
