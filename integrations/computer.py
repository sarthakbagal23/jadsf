"""Computer use — let EDITH see the screen and drive the mouse/keyboard.

How it works: screenshot -> Groq vision model describes the screen and
returns element coordinates (0-1000 scale) -> pyautogui clicks/types.
The loop is: see -> decide -> act -> see again to verify.

Honest limits:
- Vision coordinates are APPROXIMATE. For the web, use the browser tools
  (exact selectors) instead — they never miss.
- If the model misreads the screen, it clicks the wrong thing. That's why
  destructive actions (send, delete, buy, submit) must be confirmed with
  the user first (see the SYSTEM prompt in brain.py).

Safety: everything here is OFF unless EDITH_COMPUTER_USE=1 in .env.
pyautogui's failsafe is on: slam the mouse into a corner to abort.
"""
import base64
import io

import requests

from config import (
    DATA_DIR,
    GROQ_API_KEY,
    GROQ_VISION_MODEL,
    JARVIS_COMPUTER_USE,
)
from integrations._common import tool

if not JARVIS_COMPUTER_USE:
    raise RuntimeError("computer use is off — set EDITH_COMPUTER_USE=1 in .env")

SHOTS = DATA_DIR / "screenshots"
SHOTS.mkdir(exist_ok=True)


def _screenshot_b64(max_width=1280):
    """Screenshot as base64 JPEG + real screen size (for coordinate math)."""
    import pyautogui
    from PIL import Image

    real_w, real_h = pyautogui.size()
    img = pyautogui.screenshot()
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), real_w, real_h


def see_screen(question=None):
    """Look at the screen. Returns a description + clickable elements
    with 0-1000 coordinates."""
    if not GROQ_API_KEY:
        return "Screen vision needs GROQ_API_KEY in .env."
    b64, w, h = _screenshot_b64()
    q = question or ("Describe this screen in detail. List the important "
                     "clickable elements with approximate x,y coordinates on "
                     "a 0-1000 scale, as 'name: (x, y)'.")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                 "Content-Type": "application/json"},
        json={"model": GROQ_VISION_MODEL, "messages": [{"role": "user", "content": [
            {"type": "text", "text": q},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}]},
        timeout=120)
    r.raise_for_status()
    return (r.json()["choices"][0]["message"]["content"]
            + f"\n(Screen is {w}x{h}; coordinates are 0-1000.)")


def _to_pixels(x, y):
    import pyautogui
    w, h = pyautogui.size()
    return int(x / 1000 * w), int(y / 1000 * h)


def click(x, y):
    import pyautogui
    px, py = _to_pixels(x, y)
    pyautogui.click(px, py)
    return f"Clicked ({x}, {y})."


def double_click(x, y):
    import pyautogui
    px, py = _to_pixels(x, y)
    pyautogui.doubleClick(px, py)
    return f"Double-clicked ({x}, {y})."


def type_text(text):
    import pyautogui
    pyautogui.write(text, interval=0.02)
    return f"Typed {len(text)} characters."


def press_key(key):
    """Press one key: enter, tab, esc, up, down, space, backspace, etc."""
    import pyautogui
    pyautogui.press(key)
    return f"Pressed {key}."


def hotkey(keys):
    """Press keys together, e.g. ["ctrl", "c"] or ["alt", "tab"]."""
    import pyautogui
    pyautogui.hotkey(*keys)
    return f"Pressed {'+'.join(keys)}."


def scroll(clicks):
    import pyautogui
    pyautogui.scroll(int(clicks))
    return f"Scrolled {clicks}."


def focus_window(title):
    import pyautogui
    wins = pyautogui.getWindowsWithTitle(title)
    if not wins:
        return f"No window matching '{title}'."
    wins[0].activate()
    return f"Focused '{wins[0].title}'."


TOOLS = [
    tool("see_screen", "Look at the screen: description + clickable elements with 0-1000 coordinates.",
         {"question": {"type": "string", "description": "Optional: what to look for"}}, [], see_screen),
    tool("computer_click", "Click at 0-1000 coordinates.",
         {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"], click),
    tool("computer_double_click", "Double-click at 0-1000 coordinates.",
         {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"], double_click),
    tool("computer_type", "Type text at the current cursor/focus.",
         {"text": {"type": "string"}}, ["text"], type_text),
    tool("computer_key", "Press one key (enter, tab, esc, up, down, space, backspace...).",
         {"key": {"type": "string"}}, ["key"], press_key),
    tool("computer_hotkey", "Press keys together, e.g. ['ctrl', 'c'].",
         {"keys": {"type": "array", "items": {"type": "string"}}}, ["keys"], hotkey),
    tool("computer_scroll", "Scroll the mouse wheel (positive = up).",
         {"clicks": {"type": "integer"}}, ["clicks"], scroll),
    tool("computer_focus_window", "Bring a window to the front by title substring.",
         {"title": {"type": "string"}}, ["title"], focus_window),
]
