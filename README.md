# JARVIS — your own AI assistant (Windows, laptop-first)

A real, runnable starter: a local AI brain with tools, memory, voice, and a
phone interface. Built for a Windows laptop, with the phone as a remote.

## What it does

- **Talks** — text mode out of the box, full voice mode with a wake word
- **Thinks** — local Ollama model (`llama3.1:8b`), free and offline, with an
  agent loop: it decides when to use a tool, runs it, and answers from the result
- **Does things** — time, weather (no key), web search (no key), open apps,
  system stats, remember/recall facts, take notes
- **Remembers** — facts and conversation history in local SQLite
- **Phone** — a small web chat UI served from your laptop; reach it from your
  iPhone over Wi-Fi or anywhere via Tailscale

## Setup (15 min)

1. **Python 3.12+** from python.org — tick **"Add Python to PATH"** during install.
2. **Ollama** from https://ollama.com/download/windows — then in a terminal:
   ```
   ollama pull llama3.1:8b
   ```
   (~4.7 GB download, one time. This is the brain.)
3. **This project:** unzip, open the folder, double-click `setup.bat`.
4. **Run it:** double-click `run.bat`, then type. Try:
   - `what time is it`
   - `what's the weather`
   - `search the web for who won the Ballon d'Or`
   - `remember that my SAT is December 5`
   - `open spotify`

## Voice mode

```
pip install -r requirements-voice.txt
```
Get a free Picovoice key at console.picovoice.ai, copy `.env.example` to
`.env`, paste the key as `PICOVOICE_ACCESS_KEY`, then:
```
run.bat --voice
```
Say "Jarvis" and talk. Speech-to-text runs locally (faster-whisper),
speech uses the built-in Windows voice.

## Phone mode

1. Run the server: `python server.py` (in the activated venv).
2. Install **Tailscale** (free) on the laptop and your iPhone, sign in on both.
3. On your phone open `http://<laptop-tailscale-ip>:8765` — a chat UI.
   Find the laptop's Tailscale IP in the Tailscale app (looks like 100.x.x.x).

## Files

| File | What it is |
| --- | --- |
| `jarvis.py` | Entry point — text loop or `--voice` |
| `brain.py` | Agent loop: Ollama + tool calls, OpenRouter fallback |
| `tools.py` | Tool registry — add abilities here |
| `memory.py` | SQLite facts, notes, history |
| `voice.py` | Wake word, mic, STT, TTS |
| `server.py` | FastAPI phone server + mobile chat UI |
| `test_smoke.py` | Smoke tests — run `python test_smoke.py` on your laptop to verify everything works there |
| `config.py` | Settings (model, city, keys via env) |

## Adding a tool (the fun part)

In `tools.py`, write a function, then add one entry to `TOOLS` with a
description and parameters. The brain picks it up automatically — no other
changes. Ideas: read your Notion deadlines, check Gmail, control Spotify,
run a USACO timer.

## Troubleshooting

- **"can't reach my local brain"** — Ollama isn't running, or the model isn't
  pulled. Run `ollama pull llama3.1:8b`, then `ollama list` to confirm.
- **Mic not found in voice mode** — Windows Settings → Privacy → Microphone,
  allow desktop apps.
- **Slow first reply** — the model loads on first use; later replies are fast.
- **pyttsx3 silent** — check Windows volume and default audio device.

## v2: Groq brain + plugins (Notion, Spotify, GitHub, Google, Discord)

**Attribution:** integration patterns follow PersonalJarvis's open-source
plugins (Apache 2.0) — the Spotify REST approach and Notion skill guidance
come straight from their repo, and GitHub mirrors their github-mcp-server
coverage. Two honest notes: their fork ships **no Google Workspace plugin
code** (only a marketplace claim) and **no Discord** (they ship Telegram +
Slack instead) — so Google and Discord here are built fresh on the
official APIs.

### Groq brain (free, stupid fast)

Groq's free tier needs no credit card: console.groq.com → API Keys →
paste as `GROQ_API_KEY` in `.env`. That's it — `JARVIS_BRAIN=auto` uses
Groq when the key exists and falls back to local Ollama on any error or
rate limit. Free limits (Oct 2026): `llama-3.3-70b-versatile` (the
default, smart one) — 30 req/min, 1,000 req/day, 100K tokens/day;
`llama-3.1-8b-instant` (the fast one) — 30 req/min, 14,400 req/day,
500K tokens/day. Set `GROQ_MODEL=llama-3.1-8b-instant` if you want the
bigger daily budget.【6161685393491814885†L8-L15】【6161685393491814885†L42-L47】

### Plugins (each optional — a missing key just disables it)

| Plugin | What JARVIS can do | Setup |
| --- | --- | --- |
| **Notion** | Search/read/create pages, query databases | notion.so/my-integrations → New integration → `NOTION_API_KEY`. Share pages with the integration. |
| **Spotify** | Play by name, pause/skip/volume, what's playing | developer.spotify.com → app (redirect `http://127.0.0.1:8888/callback`) → `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`, then `python -m integrations.spotify_auth` once for the refresh token. Playback needs Premium; reading works free. |
| **GitHub** | List repos/issues, create issues, read files, search code | github.com/settings/tokens → classic token, `repo` scope → `GITHUB_TOKEN` |
| **Google** | Search/read Gmail, list/create calendar events | console.cloud.google.com → enable Gmail + Calendar APIs → OAuth client (Desktop) → download as `credentials.json` in this folder. First run opens a browser to sign in. |
| **Discord** | Talk to JARVIS from Discord (DMs + @mentions) | discord.com/developers → Bot → `DISCORD_BOT_TOKEN`, enable Message Content Intent, invite it to your server. Run `python -m integrations.discord_bot`. |

Try: `play lofi on Spotify`, `what's in my Notion`, `list my GitHub repos`,
`what's on my calendar this week`, `search my Gmail for SAT`.

## v3: Computer use — JARVIS sees the screen and drives it

The loop is: `see_screen` → decide → click/type → `see_screen` again to
verify. Vision runs on Groq's free multimodal model
(`meta-llama/llama-4-scout-17b-16e-instruct`, same key as the brain).

Setup:
```
pip install pyautogui pillow playwright
playwright install chromium
```
Then set `JARVIS_COMPUTER_USE=1` in `.env` (it's off by default — this
thing can click anything).

Tools: `see_screen` (description + clickable elements with 0-1000
coordinates), `computer_click` / `computer_double_click` / `computer_type`
/ `computer_key` / `computer_hotkey` / `computer_scroll` /
`computer_focus_window`, plus exact browser tools: `browser_open`,
`browser_text`, `browser_click`, `browser_fill`, `browser_screenshot`.

Rules built into the brain:
- Look before acting, verify after acting.
- Web tasks use the browser tools (exact selectors), not screen clicks.
- It must tell you what it's about to do and get a yes before clicking
  send, submit, delete, buy, or anything that changes data.
- pyautogui's failsafe is on: slam the mouse into a screen corner to abort.

Honest limit: vision coordinates are approximate — for anything precise
on the web, the browser tools never miss. Try: `open Chrome and search
for the Ballon d'Or winner`, then `click the first result`.

## v4: Personalized for Sarthak

**Speed/reliability.** Crisp commands ("what time is it", "open chrome", "check chem",
"pause", "start coding mode") now skip the model entirely. Everything else only sends
the model the few tools that matter (router.py) instead of ~45, with 30s timeouts,
one quick retry on rate limits, parallel tool calls, and no repeated identical calls.

**Persona.** `persona.py` holds who you are (school, classes, goals). Override anything
in `data/profile.json`.

**Tools** (`integrations/personal.py`, `integrations/school.py`):
`countdowns` / `add_countdown`, `study_start` / `study_stop` / `study_summary`,
`start_workflow` (coding, school, study, usaco, sat, deca - edit `data/workflows.json`),
`morning_briefing`, `weekend_plan`, `get_grades`, `upcoming_work`, `class_check`,
`class_materials`. All school tools are read-only.

**School setup.** Canvas: set `CANVAS_BASE_URL` + `CANVAS_TOKEN`. Infinite Campus: set
`IC_BASE_URL`, then once run `python -m integrations.school ic-login` and sign in yourself
in the window that opens (the session is saved locally; no password is stored).
The IC grades endpoint is read from the portal's JSON and has not been tested against
Forsyth's live portal - if it errors, send me the message.

**Desktop widget.** `start_widget.bat` (or `python widget.py`): an always-on-top card with
the clock, weather, countdowns, study time, grades and what is due. Drag to move,
right-click to close.

**Security.** The server now listens on this laptop only. Set `JARVIS_HOST` and
`JARVIS_TOKEN` together before exposing it, since it can show your grades.

## Next steps (when v1 feels good)

- HUD dashboard in the browser (your Vite stack)
- More tools: Notion, Gmail, Spotify via MCP
- Proactive routines: morning briefing, reminders
- A better voice (Fish Audio has literal JARVIS voices, free until Nov 30, 2026)
