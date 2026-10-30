"""One-time Spotify login. Run:  python -m integrations.spotify_auth

1. Create an app at developer.spotify.com/dashboard, set its Redirect URI
   to http://127.0.0.1:8888/callback, and put the Client ID + Secret in .env.
2. This script prints a URL — open it, log in, approve.
3. Paste the URL you get redirected to back here.
4. It prints your refresh token — paste it into .env as
   SPOTIFY_REFRESH_TOKEN. Done forever (tokens auto-refresh).
"""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import threading
import urllib.parse
import webbrowser

import requests

from config import BASE_DIR, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-read-currently-playing")


def save_refresh_token(refresh_token):
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "SPOTIFY_REFRESH_TOKEN=" in content:
            import re
            content = re.sub(r"SPOTIFY_REFRESH_TOKEN=.*", f"SPOTIFY_REFRESH_TOKEN={refresh_token}", content)
        else:
            content += f"\nSPOTIFY_REFRESH_TOKEN={refresh_token}\n"
        env_path.write_text(content, encoding="utf-8")
        print(f"[spotify] Saved refresh token to {env_path}")


def exchange_code(code):
    auth = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}"},
        data={"grant_type": "authorization_code", "code": code,
              "redirect_uri": REDIRECT},
        timeout=15)
    r.raise_for_status()
    d = r.json()
    token = d["refresh_token"]
    save_refresh_token(token)
    return token


class CallbackHandler(BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            CallbackHandler.code = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Spotify Connected to EDITH!</h1><p>You can close this window now.</p>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def main():
    if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET):
        print("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env first.")
        return

    params = urllib.parse.urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "scope": SCOPES,
    })
    auth_url = f"https://accounts.spotify.com/authorize?{params}"

    # Try automatic local server callback first
    try:
        server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
        print("Opening Spotify authorization in your browser...")
        print(f"URL: {auth_url}\n")
        webbrowser.open(auth_url)
        print("Waiting for you to click 'Agree' in Spotify...")
        server.handle_request()
        if CallbackHandler.code:
            token = exchange_code(CallbackHandler.code)
            print("\nSUCCESS! Spotify is now connected to EDITH.")
            print(f"SPOTIFY_REFRESH_TOKEN={token}")
            return
    except Exception as e:
        print(f"(Automatic callback listener note: {e})")

    # Manual fallback
    print("If browser didn't open automatically, open:\n", auth_url)
    redirected = input("\nPaste the full URL you were redirected to: ").strip()
    code = urllib.parse.parse_qs(urllib.parse.urlparse(redirected).query).get("code", [None])[0]
    if code:
        token = exchange_code(code)
        print("\nSUCCESS! Spotify is now connected to EDITH.")
        print(f"SPOTIFY_REFRESH_TOKEN={token}")
    else:
        print("No authorization code found in URL.")


if __name__ == "__main__":
    main()
