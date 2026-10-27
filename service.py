"""Always-on JARVIS service:
Runs both the Web / Phone Server AND the Voice Wake-Word Engine in the background.
Includes an auto-reconnect watchdog loop so it never crashes or stops.
"""
import sys
import threading
import time
import os
from pathlib import Path

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding="utf-8") if sys.stdout else None

import memory
from voice import voice_loop, speak
from server import app
from config import SERVER_PORT, NAME


def run_web_server():
    """Runs the FastAPI phone server."""
    import uvicorn
    print(f"[{NAME} Service] Starting Web Server on http://0.0.0.0:{SERVER_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="warning")


def main():
    print(f"==================================================")
    print(f"       {NAME} ALWAYS-ON BACKGROUND SERVICE         ")
    print(f"==================================================")

    # 1. Start web server in background thread
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    time.sleep(1)
    print(f"[{NAME} Service] Web UI is active at http://localhost:{SERVER_PORT}")
    print(f"[{NAME} Service] Initializing Voice Wake Word ('Hey Jarvis')...")

    # 2. Run Voice Watchdog loop
    while True:
        try:
            voice_loop()
        except KeyboardInterrupt:
            print(f"[{NAME} Service] Stopping service...")
            speak("Powering down background service.")
            break
        except Exception as e:
            print(f"[{NAME} Service] Encountered error: {e}. Restarting voice loop in 3s...")
            time.sleep(3)


if __name__ == "__main__":
    main()
