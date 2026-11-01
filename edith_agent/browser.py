"""EDITH's browser engine.

* ONE owner for the browser. Async Playwright runs on a dedicated thread, so any
  caller (chat loop, phone server worker, background task, parallel tool calls)
  can use it safely. Playwright's sync API breaks across threads; this doesn't.
* Attaches to the user's EDITH Chrome over CDP (shared ClassLink/Canvas/IC logins)
  and starts that Chrome itself if it isn't running. Falls back to an isolated
  Playwright profile when no CDP URL is configured.
* Tabs are first-class: open many in parallel, name them t1/t2/..., switch, close.
* Pages are read as numbered elements (observe.py), not screenshots.
* Hard rule: it never types into password / one-time-code fields.

Use the sync facade:  from edith_agent.browser import get_browser;  b = get_browser()
Every coroutine method on Engine is callable synchronously on the facade.
"""
import asyncio
import inspect
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from config import (BROWSER_HEADLESS, CLASSLINK_URL, DATA_DIR, EDITH_CHROME_CDP_URL)
from edith_agent.observe import OBSERVE_JS

SHOT_DIR = DATA_DIR / "screenshots"
SCHOOL_PROFILE = DATA_DIR / "school_profile"
CHROME_PROFILE = DATA_DIR / "edith_chrome_profile"


class BrowserUnavailable(RuntimeError):
    pass


class CredentialField(RuntimeError):
    """Raised instead of typing into a password / MFA field."""


class StaleElement(RuntimeError):
    pass


def web_url(url):
    """Validate a user/model-supplied URL: http(s) only, no embedded credentials."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ValueError("Provide a web URL up to 2048 characters.")
    url = url.strip()
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", url)
    host_with_port = re.match(r"^[^:/?#]+:\d+(?:/|$)", url)
    if scheme and scheme.group(1).lower() not in ("http", "https") and not host_with_port:
        raise ValueError("Only http and https web URLs are supported.")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http and https web URLs are supported.")
    if parts.username or parts.password:
        raise ValueError("Do not put sign-in credentials in a URL.")
    return url


def safe_url(url):
    """URL without query string/fragment - what we are willing to print or log."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


_SECRET_NAME = re.compile(r"(^|[^a-z])(pass(word|code)?|pwd|otp|mfa|2fa|verification[-_ ]?code)([^a-z]|$)", re.I)


def _no_display():
    """A server/CI box has no screen: run headless instead of failing to open a window."""
    return sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def is_secret_field(info):
    return (info.get("type") == "password" or "password" in info.get("ac", "") or "one-time" in info.get("ac", "")
            or bool(_SECRET_NAME.search(info.get("name", ""))))


def _find_chrome():
    cands = [os.path.join(os.environ.get(k, ""), *rest) for k, rest in (
        ("ProgramFiles", ("Google", "Chrome", "Application", "chrome.exe")),
        ("ProgramFiles(x86)", ("Google", "Chrome", "Application", "chrome.exe")),
        ("LOCALAPPDATA", ("Google", "Chrome", "Application", "chrome.exe")))]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


class Engine:
    """All methods that are `async def` run on the engine's own loop thread."""

    def __init__(self, cdp_url=None, profile=None, headless=None):
        self.cdp_url = EDITH_CHROME_CDP_URL if cdp_url is None else cdp_url
        self.profile = profile or SCHOOL_PROFILE
        self.headless = (BROWSER_HEADLESS or _no_display()) if headless is None else headless
        self.pw = None
        self.browser = None
        self.ctx = None
        self.tabs = {}            # "t1" -> Page
        self._ids = {}            # Page -> "t1"
        self._n = 0
        self.active = None
        self._elmap = {}          # tab id -> {element id -> Frame}
        self._lock = None

    # ------------------------------------------------------------ lifecycle
    async def _ensure(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self.ctx is not None:
                if not self.cdp_url or self.browser.is_connected():
                    return self.ctx
                self.ctx = self.browser = None          # Chrome was closed: reconnect below
                self.tabs.clear(); self._ids.clear(); self._elmap.clear(); self.active = None
            from playwright.async_api import async_playwright
            if self.pw is None:
                self.pw = await async_playwright().start()
            if self.cdp_url:
                await self._connect_cdp()
            else:
                self.profile.mkdir(parents=True, exist_ok=True)
                self.ctx = await self.pw.chromium.launch_persistent_context(
                    str(self.profile), headless=self.headless,
                    no_viewport=not self.headless, args=["--no-first-run"])
                self.browser = self.ctx.browser
            self.ctx.on("page", lambda p: self._register(p))
            await self._sync_tabs()
            return self.ctx

    async def _connect_cdp(self):
        try:
            self.browser = await self.pw.chromium.connect_over_cdp(self.cdp_url)
        except Exception:
            if not self._launch_chrome():
                raise BrowserUnavailable("EDITH Chrome is not running. Start it with start_edith_browser.bat.")
            err = None
            for _ in range(30):                       # Chrome takes a few seconds to open its port
                await asyncio.sleep(0.5)
                try:
                    self.browser = await self.pw.chromium.connect_over_cdp(self.cdp_url)
                    err = None
                    break
                except Exception as e:
                    err = e
            if err is not None:
                raise BrowserUnavailable(f"Started Chrome but couldn't attach to it: {err}")
        if not self.browser.contexts:
            raise BrowserUnavailable("Connected EDITH Chrome has no browser context.")
        self.ctx = self.browser.contexts[0]

    def _launch_chrome(self):
        """Same command as start_edith_browser.bat, so tabs open without a manual step."""
        chrome = _find_chrome()
        port = urlsplit(self.cdp_url).port or 9222
        if not chrome:
            return False
        CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        args = [chrome, "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
                f"--user-data-dir={CHROME_PROFILE}", "--no-first-run", CLASSLINK_URL]
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    async def shutdown(self):
        try:
            if self.ctx is not None and not self.cdp_url:
                await self.ctx.close()                 # never close the user's own Chrome
            if self.pw is not None:
                await self.pw.stop()
        finally:
            self.pw = self.browser = self.ctx = None
            self.tabs.clear(); self._ids.clear(); self._elmap.clear(); self.active = None

    # ----------------------------------------------------------------- tabs
    def _register(self, page):
        if page in self._ids or page.is_closed():
            return self._ids.get(page)
        self._n += 1
        tid = f"t{self._n}"
        self.tabs[tid] = page
        self._ids[page] = tid
        page.on("close", lambda _p, t=tid: self._forget(t))
        return tid

    def _forget(self, tid):
        page = self.tabs.pop(tid, None)
        self._ids.pop(page, None)
        self._elmap.pop(tid, None)
        if self.active == tid:
            self.active = next(reversed(self.tabs), None)

    async def _sync_tabs(self):
        for p in list(self.ctx.pages):
            self._register(p)
        for tid, p in list(self.tabs.items()):
            if p.is_closed():
                self._forget(tid)
        if self.active not in self.tabs:
            self.active = next(reversed(self.tabs), None)

    def _page(self, tab=None):
        tid = tab or self.active
        if tid not in self.tabs:
            raise BrowserUnavailable(f"No such tab '{tid}'. Open one first." if tab else "No tab is open.")
        return tid, self.tabs[tid]

    async def tabs_info(self):
        await self._ensure()
        await self._sync_tabs()
        out = []
        for tid, p in self.tabs.items():
            try:
                title = await p.title()
            except Exception:
                title = ""
            out.append({"id": tid, "title": title, "url": p.url, "active": tid == self.active})
        return out

    async def _settle(self, page, ms=1500):
        """Wait for the page to be usable, not for every last request to finish."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=ms)
        except Exception:
            pass

    async def open_tab(self, url, activate=True):
        url = web_url(url)
        await self._ensure()
        page = await self.ctx.new_page()
        tid = self._register(page)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            if "ERR_" in str(e) or "Timeout" in str(e):
                raise BrowserUnavailable(f"Couldn't load {safe_url(url)}: {str(e).splitlines()[0][:120]}")
            raise
        await self._settle(page, 800)
        if activate:
            self.active = tid
            try:
                await page.bring_to_front()
            except Exception:
                pass
        return tid

    async def open_tabs(self, urls, activate_last=True):
        """Open several pages at once. Returns [(tab_id | None, error | None)] in order."""
        await self._ensure()
        async def one(u):
            try:
                return (await self.open_tab(u, activate=False), None)
            except Exception as e:
                return (None, str(e).splitlines()[0][:160])
        res = await asyncio.gather(*(one(u) for u in urls))
        last_ok = next((t for t, _ in reversed(res) if t), None)
        if activate_last and last_ok:
            self.active = last_ok
            try:
                await self.tabs[last_ok].bring_to_front()
            except Exception:
                pass
        return res

    async def goto(self, url, tab=None):
        url = web_url(url)
        await self._ensure()
        tid, page = self._page(tab)
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await self._settle(page, 800)
        return tid

    async def back(self, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        await self._settle(page, 800)
        return tid

    async def activate(self, tab):
        await self._ensure()
        tid, page = self._page(tab)
        self.active = tid
        await page.bring_to_front()
        return tid

    async def close_tab(self, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        await page.close()
        self._forget(tid)
        return tid

    async def close_tabs(self, tabs):
        for t in list(tabs):
            try:
                await self.close_tab(t)
            except Exception:
                pass

    # -------------------------------------------------------------- reading
    async def observe(self, tab=None, max_elems=100):
        """Numbered, model-friendly snapshot of one tab (all frames)."""
        await self._ensure()
        await self._sync_tabs()
        tid, page = self._page(tab)
        for attempt in (0, 1):
            try:
                return await self._observe_once(tid, page, max_elems)
            except Exception as e:
                if attempt == 0 and any(k in str(e) for k in ("context", "navigat", "detached")):
                    await self._settle(page, 800)
                    continue
                raise

    async def _observe_once(self, tid, page, max_elems):
        elements, texts, elmap = [], [], {}
        start, y, ymax = 1, 0, 0
        for fi, frame in enumerate(page.frames):
            if frame.is_detached():
                continue
            try:
                r = await frame.evaluate(OBSERVE_JS, start)
            except Exception:
                continue
            if fi == 0:
                y, ymax = r["y"], r["max"]
                texts.append(r["text"])
            elif r["elements"] or len(r["text"].strip()) > 40:
                texts.append("[frame] " + r["text"])
            for e in r["elements"]:
                if len(elements) >= max_elems:
                    break
                elmap[e["id"]] = frame
                elements.append(e)
            start += len(r["elements"])
        self._elmap[tid] = elmap
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(texts)).strip()
        try:
            title = await page.title()
        except Exception:
            title = ""
        return {"tab": tid, "tabs": await self.tabs_info(), "title": title, "url": safe_url(page.url),
                "elements": elements, "text": text, "y": y, "max": ymax}

    async def read_text(self, tab=None, limit=12000):
        obs = await self.observe(tab)
        return obs["text"][:limit]

    async def screenshot(self, tab=None, path=None):
        await self._ensure()
        tid, page = self._page(tab)
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = path or str(SHOT_DIR / "latest.png")
        await page.screenshot(path=path, timeout=10000)
        return path

    # -------------------------------------------------------------- actions
    def _locator(self, tid, eid):
        frame = self._elmap.get(tid, {}).get(int(eid))
        if frame is None:
            raise StaleElement(f"Element [{eid}] is not on the page anymore - read the page again.")
        return frame.locator(f'[data-edith-id="{int(eid)}"]').first

    async def element_info(self, eid, tab=None):
        """Facts about an element, used by the safety gate before acting on it."""
        await self._ensure()
        tid, _ = self._page(tab)
        loc = self._locator(tid, eid)
        return await loc.evaluate("""e => ({
            tag: e.tagName.toLowerCase(), type: (e.type || '').toLowerCase(),
            href: (e.getAttribute && e.getAttribute('href')) || '', role: (e.getAttribute && e.getAttribute('role')) || '',
            text: (e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\\s+/g,' ').trim().slice(0,120),
            ac: (e.autocomplete || '').toLowerCase(), name: (e.name || '') + ' ' + (e.id || ''),
            inForm: !!e.form,
            submit: (e.type||'').toLowerCase()==='submit' || (e.tagName==='BUTTON' && !e.getAttribute('type') && !!e.form),
            context: ((e.closest('li,tr,form,section,article,div') || e.parentElement || e).innerText || '')
                       .replace(/\\s+/g,' ').trim().slice(0,200)})""")

    async def focused_info(self, tab=None):
        await self._ensure()
        _, page = self._page(tab)
        return await page.evaluate("""() => { const e = document.activeElement || {};
            return {tag: (e.tagName||'').toLowerCase(), type: (e.type||'').toLowerCase(), inForm: !!e.form,
                    text: (e.innerText||e.value||'').slice(0,80)} }""")

    async def _highlight(self, loc):
        try:
            await loc.evaluate("e=>{const o=e.style.outline;e.style.outline='3px solid #38bdf8';"
                               "e.scrollIntoView({block:'center'});setTimeout(()=>{e.style.outline=o},900)}")
            await asyncio.sleep(0.25)                   # long enough to be seen, short enough to be quick
        except Exception:
            pass

    async def click(self, eid, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        loc = self._locator(tid, eid)
        before = set(self.tabs)
        n_pages = len(self.ctx.pages)
        opens_tab = (await loc.get_attribute("target") or "") == "_blank"
        await self._highlight(loc)
        try:
            await loc.click(timeout=5000)
        except Exception:
            await loc.evaluate("e => e.click()")        # covered by an overlay: fall back to a DOM click
        if opens_tab:                                    # popups appear a beat after the click
            for _ in range(10):
                if len(self.ctx.pages) > n_pages:
                    break
                await asyncio.sleep(0.1)
        await self._settle(page, 1200)
        await self._sync_tabs()
        new = [t for t in self.tabs if t not in before]
        if new:
            self.active = new[-1]
            try:
                await self.tabs[new[-1]].bring_to_front()
            except Exception:
                pass
            return f"Clicked [{eid}]; it opened a new tab {new[-1]}."
        return f"Clicked [{eid}]."

    async def type_text(self, eid, text, submit=False, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        loc = self._locator(tid, eid)
        info = await self.element_info(eid, tid)
        if is_secret_field(info):
            raise CredentialField("That's a password/verification-code field. EDITH never types "
                                  "credentials - sign in yourself in the open tab, then say continue.")
        await self._highlight(loc)
        try:
            await loc.fill(text, timeout=5000)
        except Exception:
            await loc.click(timeout=3000)
            await page.keyboard.type(text)
        if submit:
            await loc.press("Enter")
            await self._settle(page, 1200)
        return f"Typed into [{eid}]" + (" and pressed Enter." if submit else ".")

    async def select(self, eid, option, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        loc = self._locator(tid, eid)
        await self._highlight(loc)
        try:
            await loc.select_option(label=option, timeout=4000)
        except Exception:
            await loc.select_option(value=option, timeout=4000)
        return f"Selected '{option}' in [{eid}]."

    async def press(self, key, tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        await page.keyboard.press(key)
        await self._settle(page, 800)
        return f"Pressed {key}."

    async def scroll(self, direction="down", tab=None):
        await self._ensure()
        tid, page = self._page(tab)
        sign = -1 if direction == "up" else 1
        pos = await page.evaluate("(s)=>{window.scrollBy(0, s*Math.round(innerHeight*0.8));return Math.round(scrollY)}", sign)
        return f"Scrolled {direction} (now at {pos})."

    async def badge(self, text, tab=None):
        """A small on-page label so you can see what EDITH is doing in that tab."""
        try:
            _, page = self._page(tab)
            await page.evaluate("""(t) => { let b = document.getElementById('__edith_badge');
                if (!b) { b = document.createElement('div'); b.id = '__edith_badge';
                  b.style.cssText = 'position:fixed;top:8px;right:8px;z-index:2147483647;background:#0b1220;' +
                    'color:#7dd3fc;font:12px system-ui;padding:6px 10px;border-radius:999px;' +
                    'border:1px solid #38bdf8;pointer-events:none;max-width:60vw;opacity:.92';
                  (document.body || document.documentElement).appendChild(b); }
                b.textContent = 'EDITH: ' + t; }""", text[:90])
        except Exception:
            pass

    async def eval_js(self, js, arg=None, tab=None):
        """Run JS in a tab's main frame (for playbooks that know a site's DOM). Not exposed to the model."""
        await self._ensure()
        _, page = self._page(tab)
        return await page.evaluate(js, arg)

    async def wait(self, seconds=1.0):
        await asyncio.sleep(min(max(float(seconds), 0), 15))
        return f"Waited {seconds}s."

    # --------------------------------------------------------- legacy/CSS API
    async def click_selector(self, selector, tab=None):
        await self._ensure()
        _, page = self._page(tab)
        await page.click(selector, timeout=5000)
        return f"Clicked {selector}."

    async def fill_selector(self, selector, text, tab=None):
        await self._ensure()
        _, page = self._page(tab)
        info = await page.locator(selector).first.evaluate(
            "e => ({type:(e.type||'').toLowerCase(), ac:(e.autocomplete||'').toLowerCase(), name:(e.name||'')+' '+(e.id||'')})",
            timeout=5000)
        if is_secret_field(info):
            raise CredentialField("That's a password/verification-code field. EDITH never types "
                                  "credentials - sign in yourself in the open tab.")
        await page.fill(selector, text, timeout=5000)
        return f"Filled {selector}."

    # ------------------------------------------------- authenticated requests
    async def request(self, url, params=None, headers=None, timeout=20000):
        """GET using the browser's cookies (so portal sessions just work). No tab needed."""
        await self._ensure()
        r = await self.ctx.request.get(url, params=params, headers=headers or {}, timeout=timeout)
        out = {"status": r.status, "ok": r.ok, "headers": dict(r.headers), "data": None}
        if "json" in r.headers.get("content-type", ""):
            try:
                out["data"] = await r.json()
            except Exception:
                pass
        return out


class Browser:
    """Thread-safe synchronous facade: b.open_tab(url), b.observe(), ..."""

    def __init__(self, **engine_kw):
        self._kw = engine_kw
        self._lock = threading.Lock()
        self._loop = None
        self._engine = None

    def _start(self):
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True, name="edith-browser").start()
                self._engine = Engine(**self._kw)
                self._loop = loop
        return self._engine, self._loop

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        engine, loop = self._start()
        fn = getattr(engine, name)
        if not inspect.iscoroutinefunction(fn):
            return fn

        def call(*a, _timeout=90, **k):
            return asyncio.run_coroutine_threadsafe(fn(*a, **k), loop).result(_timeout)
        return call

    def close(self):
        if self._loop is not None:
            try:
                self.shutdown()
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop = self._engine = None


_default = None
_default_lock = threading.Lock()


def get_browser():
    global _default
    with _default_lock:
        if _default is None:
            _default = Browser()
            import atexit
            atexit.register(_default.close)             # don't leave a driver process behind
        return _default
