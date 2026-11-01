"""Phone server: talk to EDITH from your phone.

Run:  python server.py
Then on your phone (same Wi-Fi, or anywhere via Tailscale):
  http://<your-laptop-ip>:8765

The home page is a small mobile-friendly chat UI — no app to install.
"""
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

import memory
from brain import ask
from config import NAME, SERVER_HOST, SERVER_PORT, SERVER_TOKEN

app = FastAPI(title=NAME)

WEB = Path(__file__).resolve().parent / "web"

ICON = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='#0b1220'/>"
        "<circle cx='32' cy='32' r='15' fill='none' stroke='#38bdf8' stroke-width='4'/><circle cx='32' cy='32' r='5' fill='#38bdf8'/></svg>")

MANIFEST = {"name": "EDITH", "short_name": "EDITH", "start_url": "/", "display": "standalone",
            "background_color": "#0b1220", "theme_color": "#0b1220",
            "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]}


def auth(authorization: str = Header(default=""), token: str = ""):
    """If EDITH_TOKEN is set, API calls send 'Authorization: Bearer <token>' (images may use ?token=)."""
    if SERVER_TOKEN and authorization != f"Bearer {SERVER_TOKEN}" and token != SERVER_TOKEN:
        raise HTTPException(401, "bad token")


class Ask(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def home():
    return (WEB / "app.html").read_text(encoding="utf-8")


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


@app.get("/icon.svg")
def icon():
    return Response(ICON, media_type="image/svg+xml")


@app.post("/ask")
def ask_endpoint(body: Ask, _=Depends(auth)):
    history = memory.recent_history(10)
    messages = [{"role": r, "content": t} for r, t in history]
    messages.append({"role": "user", "content": body.message})
    reply = ask(messages)
    memory.log("user", body.message)
    memory.log("assistant", reply)
    return {"reply": reply}


@app.get("/api/dashboard")
def api_dashboard(_=Depends(auth)):
    from integrations.personal import dashboard_data
    return dashboard_data()


class Approve(BaseModel):
    ok: bool
    id: int | None = None


class Answer(BaseModel):
    text: str
    id: int | None = None


@app.get("/api/events")
def api_events(since: int = 0, wait: float = 0, _=Depends(auth)):
    """Long-poll: new events, plus anything EDITH is waiting on you for."""
    from edith_agent import approvals
    from edith_agent.events import BUS, install_default_sinks
    from edith_agent.runner import MANAGER
    install_default_sinks()
    evs = BUS.since(since, wait=min(max(wait, 0), 25))
    return {"events": evs, "last": evs[-1]["id"] if evs else since,
            "pending": approvals.pending(), "question": approvals.open_question(),
            "status": MANAGER.status()}


@app.post("/api/approve")
def api_approve(body: Approve, _=Depends(auth)):
    from edith_agent import approvals
    return {"resolved": approvals.resolve(body.ok, body.id)}


@app.post("/api/answer")
def api_answer(body: Answer, _=Depends(auth)):
    from edith_agent import approvals
    return {"resolved": approvals.answer(body.text, body.id)}


@app.post("/api/cancel")
def api_cancel(_=Depends(auth)):
    from edith_agent.runner import MANAGER
    t = MANAGER.cancel()
    return {"cancelled": t.id if t else None}


@app.get("/api/shot")
def api_shot(_=Depends(auth)):
    """A fresh screenshot of the active browser tab (only if the browser is already running)."""
    from edith_agent import browser as B
    if B._default is None or B._default._loop is None:
        raise HTTPException(404, "The browser isn't running yet.")
    try:
        path = B._default.screenshot()
    except Exception as e:
        raise HTTPException(404, str(e).splitlines()[0][:120])
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/status")
def status():
    return {"name": NAME, "status": "online"}


if __name__ == "__main__":
    import uvicorn
    from edith_agent.events import install_default_sinks
    install_default_sinks()
    print(f"{NAME} server on http://{SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
