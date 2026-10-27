"""Phone server: talk to JARVIS from your phone.

Run:  python server.py
Then on your phone (same Wi-Fi, or anywhere via Tailscale):
  http://<your-laptop-ip>:8765

The home page is a small mobile-friendly chat UI — no app to install.
"""
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import memory
from brain import ask
from config import NAME, SERVER_HOST, SERVER_PORT, SERVER_TOKEN

app = FastAPI(title=NAME)

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS</title><style>
body{font-family:system-ui;background:#0b1220;color:#e2e8f0;margin:0;padding:16px}
#log{max-width:600px;margin:0 auto 90px}
.msg{padding:10px 14px;border-radius:14px;margin:8px 0;white-space:pre-wrap}
.you{background:#1e40af;margin-left:40px}
.jarvis{background:#1e293b;margin-right:40px}
#bar{position:fixed;bottom:0;left:0;right:0;background:#0b1220;padding:12px;display:flex;gap:8px}
#inp{flex:1;padding:12px;border-radius:12px;border:1px solid #334155;background:#1e293b;color:#fff;font-size:16px}
button{padding:12px 18px;border-radius:12px;border:0;background:#2563eb;color:#fff;font-size:16px}
</style></head><body>
<div id="log"></div>
<div id="bar"><input id="inp" placeholder="Talk to JARVIS..." autocomplete="off"><button onclick="send()">Send</button></div>
<script>
const log=document.getElementById('log'), inp=document.getElementById('inp');
function add(t,c){const d=document.createElement('div');d.className='msg '+c;d.textContent=t;log.appendChild(d);window.scrollTo(0,document.body.scrollHeight);}
async function send(){
  const m=inp.value.trim(); if(!m) return; inp.value='';
  add(m,'you');
  const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+(localStorage.tok||'')},body:JSON.stringify({message:m})});
  const j=await r.json(); add(j.reply,'jarvis');
}
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
</script></body></html>
"""


def auth(authorization: str = Header(default="")):
    """If JARVIS_TOKEN is set, every API call must send 'Authorization: Bearer <token>'."""
    if SERVER_TOKEN and authorization != f"Bearer {SERVER_TOKEN}":
        raise HTTPException(401, "bad token")


class Ask(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


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


@app.get("/status")
def status():
    return {"name": NAME, "status": "online"}


if __name__ == "__main__":
    import uvicorn
    print(f"{NAME} server on http://{SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
