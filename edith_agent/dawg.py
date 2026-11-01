"""Student Support Time ("Dawg Time"): read sessions, check in. Uses the signed-in EDITH Chrome.

The page structure (a.btn-wide date buttons, li.list-group-item sessions, li.openSession
signed-up sessions with check-in buttons) comes from school.support_time_status, which
was written against the live portal. Sign-ups go through the agent instead (see playbooks).
"""
import re
import time

from config import STUDENT_SUPPORT_TIME_URL
from edith_agent import approvals, safety
from edith_agent.browser import get_browser
from edith_agent.events import emit

HOST = "studentsupporttime.com"

_CLICK_DATE = """(q) => {
  const vis = e => { const r = e.getBoundingClientRect(); const c = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none'; };
  const tx = e => (e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const m = [...document.querySelectorAll('a.btn-wide')].filter(vis).find(a => tx(a).includes(q));
  if (!m) return false; m.click(); return true; }"""

_SCRAPE = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); const c = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && c.visibility !== 'hidden' && c.display !== 'none'; };
  const lines = e => (e.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
  let selected = '';
  for (const a of document.querySelectorAll('a.btn-wide')) {
    if (!vis(a)) continue;
    if (a.className.includes('text-bold') && !a.className.includes('btn-o')) {
      selected = (a.textContent || '').replace(/\\s+/g, ' ').trim().replace(/^DT\\s*/i, ''); break; } }
  const sessions = [];
  for (const c of document.querySelectorAll('li.list-group-item.clearfix.hover')) {
    if (!vis(c)) continue; const l = lines(c);
    if (!l.length || l.includes('No Session')) continue;
    sessions.push((l.length > 1 ? l.slice(1).join(' — ') : l[0]).slice(0, 260)); }
  const signed = [], checkins = [];
  document.querySelectorAll('li.openSession').forEach((c, i) => {
    if (!vis(c)) return; const l = lines(c);
    if (l.length && l[0].includes('Signed Up')) {
      const d = l.slice(1, 3).filter(x => x && x !== 'Details').join(' — ');
      if (d) signed.push(d.slice(0, 180)); }
    c.querySelectorAll('button').forEach((b, j) => {
      if (vis(b)) checkins.push({text: (b.textContent || '').replace(/\\s+/g, ' ').trim(), session: i, button: j,
                                 context: l.slice(0, 3).join(' — ').slice(0, 140)}); }); });
  return {ready: document.body.innerText.includes('Dawg Time'), selected, sessions, signed, checkins}; }"""

_CLICK_CHECKIN = """(arg) => {
  const c = document.querySelectorAll('li.openSession')[arg.session];
  const b = c && c.querySelectorAll('button')[arg.button];
  if (!b) return false; b.scrollIntoView({block: 'center'}); b.click(); return true; }"""


def _open():
    b = get_browser()
    tab = next((t for t in b.tabs_info() if HOST in t["url"]), None)
    if tab:
        b.activate(tab["id"])
        tid = tab["id"]
    else:
        if not STUDENT_SUPPORT_TIME_URL:
            raise RuntimeError("Student Support Time is not configured in .env.")
        tid = b.open_tab(STUDENT_SUPPORT_TIME_URL)
    end = time.time() + 15
    data = None
    while time.time() < end:
        data = b.eval_js(_SCRAPE, tab=tid)
        if data["ready"] and (data["sessions"] or data["signed"] or data["selected"]):
            return b, tid, data
        time.sleep(0.4)
    raise RuntimeError("Student Support Time is open, but its dashboard is not ready. "
                       "Sign in through ClassLink and try again.")


def _fmt(data):
    out = [f"Dawg Time — {data['selected'] or 'the currently selected day'}"]
    if data["sessions"]:
        out += ["Sessions shown:"] + [f"- {s}" for s in data["sessions"]]
    else:
        out.append("No sessions are shown for this date.")
    if data["signed"]:
        out += ["Already signed up:"] + [f"- {s}" for s in sorted(set(data["signed"]))]
        out.append(f"Check-in controls visible: {len(data['checkins'])}")
    return "\n".join(out)


def status(date=""):
    try:
        b, tid, data = _open()
        if date:
            q = re.sub(r"\s+", " ", str(date).strip().lower())
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", q)
            if m:
                import datetime as dt
                d = dt.date(int(m[1]), int(m[2]), int(m[3]))
                q = f"{d.strftime('%b').lower()} {d.day}"
            if not b.eval_js(_CLICK_DATE, q, tab=tid):
                return f"I couldn't find '{date}' in the visible Student Support Time calendar."
            time.sleep(0.8)
            data = b.eval_js(_SCRAPE, tab=tid)
        return _fmt(data)
    except Exception as e:
        return str(e)


def checkin(user_request=""):
    """Check in to the session you are signed up for. Runs only when you asked for it."""
    try:
        b, tid, data = _open()
    except Exception as e:
        return str(e)
    boxes = [c for c in data["checkins"] if re.search(r"check[ -]?in", c["text"], re.I)]
    if not boxes:
        return "I don't see a check-in button right now. " + _fmt(data)
    if len(boxes) > 1:
        return ("More than one check-in is available - tell me which:\n" +
                "\n".join(f"- {c['context']}" for c in boxes))
    c = boxes[0]
    if "checkin" not in safety.grants_from_request(user_request):
        if not approvals.request(f"Check you in: {c['context']}", "checkin"):
            return "Okay, I did not check you in."
    emit("step", f"Checking in: {c['context']}")
    if not b.eval_js(_CLICK_CHECKIN, {"session": c["session"], "button": c["button"]}, tab=tid):
        return "The check-in button disappeared before I could click it."
    time.sleep(1.2)
    after = b.eval_js(_SCRAPE, tab=tid)
    still = [x for x in after["checkins"] if re.search(r"check[ -]?in", x["text"], re.I)]
    if len(still) < len(boxes):
        return f"Checked in: {c['context']}"
    return f"I clicked check-in for {c['context']}, but the button is still showing - please verify on screen."
