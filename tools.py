"""Tool registry: everything EDITH can DO.

Each tool has a JSON schema (so the LLM knows when to call it) and a
Python function that runs it. To add a new ability, write a function and
add one entry to TOOLS — the brain picks it up automatically.
"""
import datetime
import os
import re
import subprocess
import urllib.parse
import urllib.request

import psutil
import requests

import memory
from config import CITY


# ---------------------------------------------------------------- functions

def get_time():
    return datetime.datetime.now().strftime("%A, %B %d, %Y, %I:%M %p")


def get_weather(city=CITY):
    """Current weather via Open-Meteo (no API key needed)."""
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1}, timeout=10,
        ).json()
        if not geo.get("results"):
            return f"Couldn't find {city}."
        place = geo["results"][0]
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
            },
            timeout=10,
        ).json()["current"]
        return (f"{place['name']}: {w['temperature_2m']}F, "
                f"humidity {w['relative_humidity_2m']}%, wind {w['wind_speed_10m']} mph.")
    except Exception as e:
        return f"Weather lookup failed: {e}"


def web_search(query):
    """Web search via DuckDuckGo Lite (no API key needed)."""
    try:
        url = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
        results = re.findall(
            r'''class=["']result-link["'][^>]*>(.*?)</a>.*?<td class=["']result-snippet["'][^>]*>(.*?)</td>''',
            html, re.S,
        )
        out = []
        for title, snippet in results[:5]:
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            out.append(f"- {title}: {snippet}")
        return "\n".join(out) if out else "No results found."
    except Exception as e:
        return f"Search failed: {e}"


APPS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "vscode": "code",
    "code": "code",
    "spotify": "spotify",
    "notepad": "notepad",
    "calculator": "calc",
    "terminal": "wt",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
}


def open_app(name):
    """Launch a Windows app by name (chrome, vscode, spotify, notepad...)."""
    target = APPS.get(name.lower(), name)
    try:
        if os.path.isfile(target):
            subprocess.Popen([target])
        else:
            subprocess.Popen(["cmd", "/c", "start", "", target])
        return f"Opening {name}."
    except Exception as e:
        return f"Couldn't open {name}: {e}"


def system_info():
    b = psutil.sensors_battery()
    batt = f"{b.percent}% {'charging' if b.power_plugged else 'on battery'}" if b else "unknown"
    return (f"CPU {psutil.cpu_percent(interval=0.1)}%, "
            f"RAM {psutil.virtual_memory().percent}% used, battery {batt}.")


def remember_fact(key, value):
    return memory.remember(key, value)


def recall_fact(key):
    v = memory.recall(key)
    return v if v else f"I don't have anything stored for {key}."


def take_note(text):
    return memory.add_note(text)


# ---------------------------------------------------------------- registry

def _tool(name, description, properties, required, fn):
    return {
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        },
        "function": fn,
    }


TOOLS = [
    _tool("get_time", "Current date and time.",
          {}, [], get_time),
    _tool("get_weather", "Current weather for a city.",
          {"city": {"type": "string", "description": "City name"}},
          [], get_weather),
    _tool("web_search", "Search the internet for current information.",
          {"query": {"type": "string", "description": "Search query"}},
          ["query"], web_search),
    _tool("open_app", "Open an app on the laptop (chrome, vscode, spotify, notepad, calculator, terminal).",
          {"name": {"type": "string", "description": "App name"}},
          ["name"], open_app),
    _tool("system_info", "CPU, RAM, and battery status of this laptop.",
          {}, [], system_info),
    _tool("remember_fact", "Remember a fact about the user for later.",
          {"key": {"type": "string"}, "value": {"type": "string"}},
          ["key", "value"], remember_fact),
    _tool("recall_fact", "Recall a previously stored fact.",
          {"key": {"type": "string"}},
          ["key"], recall_fact),
    _tool("take_note", "Save a freeform note.",
          {"text": {"type": "string"}},
          ["text"], take_note),
]

# ---- optional integrations (Notion, Spotify, GitHub, Google) ----
# Each integration loads only if its keys are set; a missing key just
# skips that plugin. Discord runs as its own bot (integrations/discord_bot.py).
try:
    from integrations import get_integration_tools
    TOOLS = TOOLS + get_integration_tools()
except Exception as e:
    print(f"[plugins] loader failed: {e}")
