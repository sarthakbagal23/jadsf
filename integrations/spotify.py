"""Spotify — play, steer, and read the user's music via the Web API.

Follows PersonalJarvis's spotify_rest.py approach: REST, not MCP —
Spotify publishes no MCP server, only the Web API. Same three rules
their plugin learned the hard way:

* The Web API produces no audio. It drives Spotify Connect, so it can
  only command a device already running Spotify. With nothing open,
  playback answers 404 NO_ACTIVE_DEVICE — reported plainly, never
  retried blindly.
* Controlling playback needs Premium (403 otherwise). Reading what is
  playing works on a free account.
* Player commands return 204 with an empty body on success.

Auth: OAuth refresh-token flow. Run `python -m integrations.spotify_auth`
once to get a refresh token, then set SPOTIFY_CLIENT_ID,
SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN in .env. Tokens
auto-refresh from then on.
"""
import base64
import time

import requests

from config import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REFRESH_TOKEN,
)
from integrations._common import tool

if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET and SPOTIFY_REFRESH_TOKEN):
    raise RuntimeError("Spotify not configured (need CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)")

API = "https://api.spotify.com/v1"
_token, _token_exp = None, 0.0


def _access_token():
    global _token, _token_exp
    if _token and time.time() < _token_exp - 60:
        return _token
    auth = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}"},
        data={"grant_type": "refresh_token", "refresh_token": SPOTIFY_REFRESH_TOKEN},
        timeout=15)
    r.raise_for_status()
    d = r.json()
    _token = d["access_token"]
    _token_exp = time.time() + d.get("expires_in", 3600)
    return _token


def _api(method, path, **kw):
    try:
        r = requests.request(
            method, API + path,
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=15, **kw)
    except requests.RequestException as e:
        return {"error": str(e)}
    if r.status_code == 204:
        return {}
    if r.status_code == 404:
        return {"error": "NO_ACTIVE_DEVICE"}
    if r.status_code == 403:
        return {"error": "NEEDS_PREMIUM"}
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        return {"error": str(e)}
    return r.json()


def _check(r):
    """Translate API error dicts into plain user-facing messages."""
    if isinstance(r, dict) and r.get("error") == "NO_ACTIVE_DEVICE":
        return ("Spotify isn't open anywhere, so there's nothing to play on. "
                "Open Spotify on your laptop or phone and try again.")
    if isinstance(r, dict) and r.get("error") == "NEEDS_PREMIUM":
        return ("Spotify only allows remote control with Premium — that's "
                "Spotify's rule. Reading what's playing still works.")
    if isinstance(r, dict) and r.get("error"):
        return f"Spotify error: {r['error']}"
    return None


def now_playing():
    d = _api("GET", "/me/player/currently-playing")
    if (msg := _check(d)) or not d or "item" not in d:
        return msg or "Nothing is playing right now."
    it = d["item"]
    artists = ", ".join(a["name"] for a in it["artists"])
    return (f"Now playing: {it['name']} by {artists} "
            f"({'playing' if d.get('is_playing') else 'paused'}).")


def play(query=None, type="track"):
    """Play by name (searches, plays top hit) or resume with no query."""
    if query:
        res = _api("GET", "/search", params={"q": query, "type": type, "limit": 1})
        if msg := _check(res):
            return msg
        items = res.get(f"{type}s", {}).get("items", [])
        if not items:
            return f"Couldn't find '{query}' on Spotify."
        top = items[0]
        if type == "track":
            body = {"uris": [top["uri"]]}
            name = f"{top['name']} by {', '.join(a['name'] for a in top['artists'])}"
        else:
            body = {"context_uri": top["uri"]}
            name = top["name"]
        r = _api("PUT", "/me/player/play", json=body)
        if msg := _check(r):
            return msg
        return f"Playing {name}."
    r = _api("PUT", "/me/player/play")
    if msg := _check(r):
        return msg
    return "Resumed playback."


def pause():
    r = _api("PUT", "/me/player/pause")
    if msg := _check(r):
        return msg
    return "Paused."


def next_track():
    r = _api("POST", "/me/player/next")
    if msg := _check(r):
        return msg
    return "Skipped to next track."


def previous_track():
    r = _api("POST", "/me/player/previous")
    if msg := _check(r):
        return msg
    return "Back to previous track."


def set_volume(percent):
    r = _api("PUT", "/me/player/volume", params={"volume_percent": max(0, min(100, int(percent)))})
    if msg := _check(r):
        return msg
    return f"Volume set to {percent}%."


TOOLS = [
    tool("spotify_now_playing", "What song is currently playing on Spotify.",
         {}, [], now_playing),
    tool("spotify_play", "Play a song/artist/album/playlist by name, or resume with no query.",
         {"query": {"type": "string", "description": "Name to search for (omit to resume)"},
          "type": {"type": "string", "description": "track, artist, album or playlist"}},
         [], play),
    tool("spotify_pause", "Pause Spotify playback.", {}, [], pause),
    tool("spotify_next", "Skip to the next track.", {}, [], next_track),
    tool("spotify_previous", "Go back to the previous track.", {}, [], previous_track),
    tool("spotify_volume", "Set Spotify volume 0-100.",
         {"percent": {"type": "integer"}}, ["percent"], set_volume),
]
