"""Web-chat endpoints.

- `WS  /ws/chat?tenant=<slug>&conversation=<ref>` — streams OutboundChunk frames
- `POST /api/chat` — non-streaming fallback (easy to curl / test)
- `GET /dev/chat` — a tiny dev-only page to type into (mounted only in dev)
"""
from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.base import TenantNotFound, handle_inbound
from ..channels.webchat import WebChatAdapter
from ..db import SessionLocal
from ..deps import get_db
from ..orchestrator.base import Orchestrator
from ..schemas.message import OutboundChunk
from ..services.redis import get_redis_client

log = logging.getLogger("concierge.webchat")
router = APIRouter()
dev_router = APIRouter()


def _orchestrator(app) -> Orchestrator:
    """The active orchestrator lives on app.state (set in create_app), so tests
    can swap in the echo or a fake without touching the network."""
    return app.state.orchestrator


class ChatRequest(BaseModel):
    tenant: str
    content: str
    conversation_ref: str | None = None


class ChatResponse(BaseModel):
    conversation_ref: str
    reply: str


@router.post("/api/chat", response_model=ChatResponse)
async def post_chat(
    req: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> ChatResponse:
    conv_ref = req.conversation_ref or uuid4().hex
    msg = WebChatAdapter.to_inbound(
        tenant_slug=req.tenant, conversation_ref=conv_ref, content=req.content
    )
    parts: list[str] = []
    try:
        async for chunk in handle_inbound(
            msg, db=db, redis=get_redis_client(), orchestrator=_orchestrator(request.app)
        ):
            if chunk.content and chunk.type in ("token", "message"):
                parts.append(chunk.content)
            elif chunk.type == "error":
                raise HTTPException(status_code=500, detail=chunk.content)
    except TenantNotFound as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ChatResponse(conversation_ref=conv_ref, reply="".join(parts))


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    tenant = websocket.query_params.get("tenant")
    if not tenant:
        await websocket.close(code=4400, reason="missing ?tenant=")
        return
    # One browser session == one conversation thread.
    conv_ref = websocket.query_params.get("conversation") or uuid4().hex

    await websocket.accept()
    await websocket.send_json(
        OutboundChunk(
            type="action", content="connected", metadata={"conversation_ref": conv_ref}
        ).model_dump(exclude_none=True)
    )
    redis = get_redis_client()

    try:
        while True:
            payload = await websocket.receive_json()
            content = (payload or {}).get("content", "").strip()
            if not content:
                continue
            msg = WebChatAdapter.to_inbound(
                tenant_slug=tenant,
                conversation_ref=conv_ref,
                content=content,
                payload=payload,
            )
            # A short-lived session per turn — a long-lived WS shouldn't pin a
            # database connection open for its whole lifetime.
            async with SessionLocal() as db:
                try:
                    async for chunk in handle_inbound(
                        msg, db=db, redis=redis, orchestrator=_orchestrator(websocket.app)
                    ):
                        await websocket.send_json(chunk.model_dump(exclude_none=True))
                except TenantNotFound as e:
                    await websocket.send_json(
                        OutboundChunk(type="error", content=str(e)).model_dump(exclude_none=True)
                    )
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        log.exception("web-chat socket failed")
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass


_DEV_PAGE = """<!doctype html>
<meta charset="utf-8"><title>PythaFlow concierge — dev chat</title>
<style>
 body{font:15px/1.5 system-ui;margin:0;background:#F3F4F1;color:#17191C}
 .wrap{max-width:640px;margin:40px auto;padding:0 16px}
 #log{border:1px solid #ddd;border-radius:12px;background:#fff;height:420px;
      overflow:auto;padding:14px;margin-bottom:12px}
 .m{margin:6px 0;padding:8px 12px;border-radius:12px;max-width:80%;white-space:pre-wrap}
 .guest{background:#17191C;color:#F3F4F1;margin-left:auto}
 .bot{background:#eceee9}
 .sys{color:#6C6F74;font-size:12px;text-align:center;background:none}
 form{display:flex;gap:8px} input{flex:1;padding:10px 12px;border:1px solid #ccc;border-radius:10px}
 button{padding:10px 16px;border:0;border-radius:10px;background:#1E6E68;color:#fff;cursor:pointer}
</style>
<div class="wrap">
  <h3>Concierge — dev chat <small style="color:#6C6F74">tenant: <code id="t"></code></small></h3>
  <div id="log"></div>
  <form id="f">
    <input id="i" placeholder="Type a message…" autocomplete="off" autofocus>
    <button>Send</button>
  </form>
</div>
<script>
const params = new URLSearchParams(location.search);
const tenant = params.get('tenant') || 'demo';
document.getElementById('t').textContent = tenant;
const log = document.getElementById('log');
function add(text, cls){
  const d = document.createElement('div');
  d.className = 'm ' + cls;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}
const ws = new WebSocket(`ws://${location.host}/ws/chat?tenant=${encodeURIComponent(tenant)}`);
ws.onopen = () => add('socket open', 'sys');
ws.onclose = () => add('socket closed', 'sys');
let botEl = null;    // the bubble the current streamed reply is growing into
let thinkEl = null;  // "thinking…" indicator shown while we wait on the model
function clearThink(){ if (thinkEl) { thinkEl.remove(); thinkEl = null; } }
ws.onmessage = (e) => {
  const c = JSON.parse(e.data);
  if (c.type === 'typing') {
    if (!thinkEl) thinkEl = add('💭 thinking…', 'sys');   // model can be slow on free tiers
  } else if (c.type === 'token') {
    clearThink();
    if (!botEl) botEl = add('', 'bot');   // one bubble per reply; tokens append
    botEl.textContent += c.content;
    log.scrollTop = log.scrollHeight;
  } else if (c.type === 'message') {
    clearThink();
    add(c.content, 'bot');
  } else if (c.type === 'done') {
    clearThink();
    botEl = null;                          // next reply starts a fresh bubble
  } else if (c.type === 'error') {
    clearThink();
    add('error: ' + c.content, 'sys'); botEl = null;
  } else if (c.type === 'action') {
    add(c.content + ' (' + (c.metadata?.conversation_ref || '') + ')', 'sys');
  }
};
document.getElementById('f').onsubmit = (e) => {
  e.preventDefault();
  const i = document.getElementById('i');
  if (!i.value.trim()) return;
  add(i.value, 'guest');
  ws.send(JSON.stringify({content: i.value}));
  i.value = '';
};
</script>
"""


@dev_router.get("/dev/chat", response_class=HTMLResponse, include_in_schema=False)
async def dev_chat() -> str:
    """Dev-only manual test page. Not mounted outside development."""
    return _DEV_PAGE


_APPROVALS_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8"><title>PythaFlow — approvals</title>
<style>
 body{font:15px/1.5 system-ui;margin:0;background:#F3F4F1;color:#17191C;padding:20px}
 h2{margin:0 0 16px}
 .card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:16px;margin-bottom:12px}
 .card h4{margin:0 0 6px}
 .meta{color:#6C6F74;font-size:13px;margin-bottom:8px}
 .note-field{width:100%;padding:6px 10px;border:1px solid #ccc;
   border-radius:8px;margin-bottom:6px;box-sizing:border-box}
 .btn{padding:8px 16px;border:0;border-radius:8px;cursor:pointer;font-weight:600}
 .btn-approve{background:#1E6E68;color:#fff}
 .btn-reject{background:#B33A3A;color:#fff}
 .btn-approve:hover,.btn-reject:hover{opacity:0.9}
 .empty{text-align:center;padding:40px;color:#6C6F74}
 #refresh{float:right;padding:6px 14px;border:1px solid #ccc;
   border-radius:8px;background:#fff;cursor:pointer}
 .flash{padding:10px;border-radius:8px;margin-bottom:12px;display:none}
 .flash.success{background:#d4edda;color:#155724;display:block}
 .flash.error{background:#f8d7da;color:#721c24;display:block}
</style>
<h2>Approvals <button id="refresh">Refresh</button></h2>
<div id="flash" class="flash"></div>
<div id="queue"></div>
<script>
const TOKEN = 'dev-token';
async function load(){
  const r=await fetch('/api/approvals',{headers:{'X-Staff-Token':TOKEN}});
  const data=await r.json();
  const q=document.getElementById('queue'); q.innerHTML='';
  const flash=document.getElementById('flash'); flash.className='flash';
  if(data.total===0){q.innerHTML='<div class="empty">No pending requests.</div>';return}
  for(const req of data.requests){
    const card=document.createElement('div'); card.className='card';
    const conf=req.confidence ? (req.confidence*100).toFixed(0)+'%' : 'N/A';
    card.innerHTML='<h4>'+(req.summary||'Untitled')+'</h4>'+
      '<div class="meta">'+req.type+' &middot; confidence: '+conf+
      ' &middot; priority: '+req.priority+' &middot; '+
      new Date(req.created_at).toLocaleString()+'</div>'+
      '<input class="note-field" placeholder="Optional note..." id="note-'+req.request_id+'">'+
      '<button class="btn btn-approve" data-id="'+req.request_id+
      '" data-d="approved">Approve</button> '+
      '<button class="btn btn-reject" data-id="'+req.request_id+
      '" data-d="rejected">Reject</button>';
    q.appendChild(card);
  }
  document.querySelectorAll('.btn').forEach(b=>b.onclick=async ()=>{
    const note=document.getElementById('note-'+b.dataset.id).value;
    const r=await fetch('/api/approvals/decide',{
      method:'POST',
      headers:{'Content-Type':'application/json','X-Staff-Token':TOKEN},
      body:JSON.stringify({request_id:b.dataset.id,decision:b.dataset.d,note:note||null}),
    });
    const flash=document.getElementById('flash');
    if(r.ok){flash.className='flash success';flash.textContent='Decision recorded.';load()}
    else{const t=await r.text();flash.className='flash error';flash.textContent='Failed: '+t}
  });
}
document.getElementById('refresh').onclick=load;
load();
</script>
"""


@dev_router.get("/dev/approvals", response_class=HTMLResponse, include_in_schema=False)
async def dev_approvals() -> str:
    """Dev-only approval management page. Not mounted outside development."""
    return _APPROVALS_PAGE
