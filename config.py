"""EDITH settings. Override with environment variables or a .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# --- identity ---
NAME = os.environ.get("EDITH_NAME", os.environ.get("JARVIS_NAME", "Even Dead, I'm The Hero"))
CITY = os.environ.get("EDITH_CITY", os.environ.get("JARVIS_CITY", "Cumming"))  # GA

# --- brain: "auto" (Groq if key set, else Ollama), "groq", or "ollama" ---
JARVIS_BRAIN = os.environ.get("EDITH_BRAIN", os.environ.get("JARVIS_BRAIN", "auto"))

# local brain
OLLAMA_MODEL = os.environ.get("EDITH_MODEL", os.environ.get("JARVIS_MODEL", "llama3.2:3b"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Groq — free tier, no card. Key from console.groq.com (starts gsk_).
# 70B: 30 req/min, 1,000 req/day, 100K tokens/day. 8B instant: 14,400 req/day.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MODEL_FAST = os.environ.get("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

# OpenRouter fallback
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

# --- voice (optional) ---
PICOVOICE_ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY", "")
WAKE_WORD = os.environ.get("EDITH_WAKE_WORD", os.environ.get("JARVIS_WAKE_WORD", "edith"))
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
ELEVENLABS_MODEL_ID = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")

# --- computer use (OFF unless set to 1 — it can click anything) ---
JARVIS_COMPUTER_USE = os.environ.get(
    "EDITH_COMPUTER_USE", os.environ.get("JARVIS_COMPUTER_USE", "")) == "1"
GROQ_VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

# --- integrations (each optional — a missing key just disables that plugin) ---
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CANVAS_BASE_URL = os.environ.get("CANVAS_BASE_URL", "")   # e.g. https://forsyth.instructure.com
CANVAS_TOKEN = os.environ.get("CANVAS_TOKEN", "")
IC_BASE_URL = os.environ.get("IC_BASE_URL", "")
CLASSLINK_URL = os.environ.get("CLASSLINK_URL", "https://launchpad.classlink.com/")
STUDENT_SUPPORT_TIME_URL = os.environ.get(
    "STUDENT_SUPPORT_TIME_URL", "https://forsyth.studentsupporttime.com/SHome")
EDITH_CHROME_CDP_URL = os.environ.get("EDITH_CHROME_CDP_URL", "")  # Local Chrome debugging endpoint
GOOGLE_CREDENTIALS = BASE_DIR / "credentials.json"   # Google OAuth client file
GOOGLE_TOKEN = BASE_DIR / "token.json"               # created on first Google sign-in

# --- phone server ---
SERVER_PORT = int(os.environ.get("EDITH_PORT", os.environ.get("JARVIS_PORT", "8765")))
# 127.0.0.1 = this laptop only. The server now exposes your grades, so it is
# NOT open to the network unless you set EDITH_HOST=0.0.0.0 (and a EDITH_TOKEN).
SERVER_HOST = os.environ.get("EDITH_HOST", os.environ.get("JARVIS_HOST", "127.0.0.1"))
SERVER_TOKEN = os.environ.get("EDITH_TOKEN", os.environ.get("JARVIS_TOKEN", ""))

MEMORY_DB = DATA_DIR / "memory.db"
