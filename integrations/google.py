"""Google Workspace — Gmail + Calendar via Google's official APIs.

NOTE: PersonalJarvis's README lists Google Workspace in its marketplace,
but this fork ships no Google plugin code — so this module is built fresh
on Google's own APIs. Same idea, just honest about the source.

Setup (one time):
  1. console.cloud.google.com -> new project -> enable "Gmail API" and
     "Google Calendar API".
  2. APIs & Services -> Credentials -> Create OAuth client ID (Desktop app)
     -> download the JSON as credentials.json into this folder.
  3. First run opens a browser to sign in; the token is saved as
     token.json and reused after that.
"""
import base64
import datetime
import os

from config import GOOGLE_CREDENTIALS, GOOGLE_TOKEN
from integrations._common import tool

if not os.path.exists(GOOGLE_CREDENTIALS):
    raise RuntimeError("credentials.json missing — see README (Google setup)")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar"]


def _service(api, version):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(GOOGLE_TOKEN):
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN, "w") as f:
            f.write(creds.to_json())
    return build(api, version, credentials=creds)


def search_gmail(query, max_results=5):
    svc = _service("gmail", "v1")
    msgs = svc.users().messages().list(userId="me", q=query,
                                        maxResults=max_results).execute().get("messages", [])
    out = []
    for m in msgs:
        d = svc.users().messages().get(userId="me", id=m["id"],
                                       format="metadata",
                                       metadataHeaders=["Subject", "From", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
        out.append(f"- {headers.get('Subject', '(no subject)')} — "
                   f"{headers.get('From', '?')} ({headers.get('Date', '')}) [{m['id']}]")
    return "\n".join(out) if out else "No emails match."


def read_gmail(message_id):
    svc = _service("gmail", "v1")
    d = svc.users().messages().get(userId="me", id=message_id,
                                   format="full").execute()
    body = ""
    payload = d.get("payload", {})
    for part in payload.get("parts", [payload]):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
            break
    return (d.get("snippet", "") + "\n\n" + body)[:3000] or "(empty email)"


def list_calendar_events(days=7):
    svc = _service("calendar", "v3")
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=days)
    events = svc.events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=20).execute().get("items", [])
    out = []
    for e in events:
        start = e.get("start", {}).get("dateTime", e.get("start", {}).get("date", ""))
        out.append(f"- {start}: {e.get('summary', '(no title)')}")
    return "\n".join(out) if out else f"Nothing on your calendar for the next {days} days."


def create_calendar_event(title, start, end, description=""):
    """start/end as ISO datetimes, e.g. 2026-10-27T18:00:00-04:00."""
    svc = _service("calendar", "v3")
    e = svc.events().insert(calendarId="primary", body={
        "summary": title, "description": description,
        "start": {"dateTime": start}, "end": {"dateTime": end},
    }).execute()
    return f"Created event '{title}' ({e.get('htmlLink', '')})"


TOOLS = [
    tool("gmail_search", "Search Gmail. Returns subject, sender, date and id.",
         {"query": {"type": "string"}, "max_results": {"type": "integer"}},
         ["query"], search_gmail),
    tool("gmail_read", "Read a Gmail message by its id.",
         {"message_id": {"type": "string"}}, ["message_id"], read_gmail),
    tool("calendar_events", "List upcoming calendar events.",
         {"days": {"type": "integer"}}, [], list_calendar_events),
    tool("calendar_create", "Create a calendar event (ISO start/end datetimes).",
         {"title": {"type": "string"}, "start": {"type": "string"},
          "end": {"type": "string"}, "description": {"type": "string"}},
         ["title", "start", "end"], create_calendar_event),
]
