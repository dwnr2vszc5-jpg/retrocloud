"""Game worker HTTP + WebSocket server (aiohttp).

Two kinds of credentials:
  * RC_WORKER_TOKEN  - bearer token for the control plane (create/stop sessions, metrics).
                       Players never see it.
  * session token    - random per session, returned once at creation. It authorises exactly
                       one session's signaling socket; the player page keeps it in the URL
                       fragment (never sent in HTTP requests / proxy logs) and sends it as the
                       first WebSocket message.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import time
from typing import Any

from aiohttp import WSMsgType, web
from pydantic import BaseModel, Field, ValidationError

from .config import settings
from .games import Catalog
from .metrics import ProcSampler, host_stats
from .session import SessionError, SessionManager
from .stream import StreamPeer, ice_servers, init_gstreamer

log = logging.getLogger("retrocloud.worker")

MANAGER = web.AppKey("manager", SessionManager)
PEERS = web.AppKey("peers", dict)
STATE = web.AppKey("state", dict)


class CreateSession(BaseModel):
    game_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    owner: str = Field(default="anonymous", max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")


def require_worker_token(request: web.Request) -> None:
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(token.encode(), settings.worker_token.encode()):
        raise web.HTTPUnauthorized(text=json.dumps({"error": "unauthorized"}), content_type="application/json")


def _json(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


# ---------------- routes ----------------
async def health(request: web.Request) -> web.Response:
    mgr = request.app[MANAGER]
    running = sum(1 for s in mgr.sessions.values() if s.state == "running")
    last = max([s.last_activity for s in mgr.sessions.values()] + [request.app[STATE]["last_activity"]])
    return _json({
        "status": "ok",
        "sessions_running": running,
        "capacity": settings.max_sessions,
        "idle_seconds": 0 if running else int(time.time() - last),
    })


async def list_games(request: web.Request) -> web.Response:
    require_worker_token(request)
    catalog = request.app[MANAGER].catalog
    catalog.rescan()   # pick up ROMs dropped into roms/<system>/ since the last call
    return _json(catalog.available())


async def list_systems(request: web.Request) -> web.Response:
    require_worker_token(request)
    catalog = request.app[MANAGER].catalog
    catalog.rescan()
    return _json(catalog.systems_summary())


async def list_sessions(request: web.Request) -> web.Response:
    require_worker_token(request)
    return _json([s.public() for s in request.app[MANAGER].sessions.values()])


async def create_session(request: web.Request) -> web.Response:
    require_worker_token(request)
    try:
        body = CreateSession(**(await request.json()))
    except (ValidationError, ValueError) as e:
        return _json({"error": "invalid request", "detail": str(e)[:300]}, 400)
    try:
        sess = await request.app[MANAGER].create(body.game_id, body.owner)
    except SessionError as e:
        status = 409 if "capacity" in str(e) else 400
        return _json({"error": str(e)}, status)
    request.app[STATE]["last_activity"] = time.time()
    return _json({**sess.public(), "token": sess.token,
                  "play_path": f"/play.html#sid={sess.id}&token={sess.token}"}, 201)


async def get_session(request: web.Request) -> web.Response:
    require_worker_token(request)
    sess = request.app[MANAGER].get(request.match_info["sid"])
    if not sess:
        return _json({"error": "not found"}, 404)
    return _json(sess.public())


async def delete_session(request: web.Request) -> web.Response:
    require_worker_token(request)
    sid = request.match_info["sid"]
    peer = request.app[PEERS].pop(sid, None)
    if peer:
        peer.close()
    if not request.app[MANAGER].get(sid):
        return _json({"error": "not found"}, 404)
    await request.app[MANAGER].stop(sid, purge=request.query.get("purge") == "1")
    request.app[STATE]["last_activity"] = time.time()
    return _json({"stopped": sid})


async def session_metrics(request: web.Request) -> web.Response:
    require_worker_token(request)
    sid = request.match_info["sid"]
    sess = request.app[MANAGER].get(sid)
    if not sess:
        return _json({"error": "not found"}, 404)
    peer = request.app[PEERS].get(sid)
    return _json({
        "session": sess.public(),
        # "worker" = this Python process: GStreamer capture + x264 + Opus + WebRTC of ALL sessions
        "processes": {**sess.sampler.sample(), "worker": request.app[STATE]["self_sampler"].sample().get("worker")},
        "stream": peer.rates() if peer else None,
        "host": host_stats(),
    })


async def signaling(request: web.Request) -> web.WebSocketResponse:
    sid = request.match_info["sid"]
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=64 * 1024)
    await ws.prepare(request)
    mgr: SessionManager = request.app[MANAGER]
    peers: dict[str, StreamPeer] = request.app[PEERS]
    # 1) authenticate: first message must be {"type":"auth","token":...} within 5 s
    try:
        first = await asyncio.wait_for(ws.receive(), 5)
        token = json.loads(first.data).get("token", "") if first.type == WSMsgType.TEXT else ""
    except (asyncio.TimeoutError, ValueError, AttributeError):
        token = ""
    sess = mgr.check_token(sid, str(token))
    if sess is None or sess.state != "running":
        await ws.send_json({"type": "error", "message": "unauthorized or session not running"})
        await ws.close(code=4401)
        return ws
    # 2) one viewer per session: a new connection replaces the previous one
    old = peers.pop(sid, None)
    if old:
        old.close()
        if old.ws is not None and not old.ws.closed:
            await old.ws.close(code=4409, message=b"replaced by a newer connection")
    loop = asyncio.get_running_loop()

    def send(msg: dict[str, Any]) -> None:
        if not ws.closed:
            asyncio.ensure_future(ws.send_json(msg))

    servers, gst_turn = ice_servers(settings, sid)
    await ws.send_json({"type": "config", "iceServers": servers,
                        "video": {"width": settings.video.width, "height": settings.video.height,
                                  "fps": settings.video.fps}})
    peer = StreamPeer(sess, settings, loop, send)
    peer.ws = ws
    peers[sid] = peer
    sess.viewer_connected = True
    sess.injector and sess.injector.focus_first_window()
    try:
        peer.start(gst_turn)
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue
            kind = data.get("type")
            if kind == "answer" and isinstance(data.get("sdp"), str):
                peer.handle_answer(data["sdp"])
            elif kind == "ice" and isinstance(data.get("candidate"), str):
                peer.handle_ice(data["candidate"], int(data.get("sdpMLineIndex") or 0))
    except Exception:
        log.exception("signaling error for session %s", sid)
    finally:
        if peers.get(sid) is peer:
            peers.pop(sid, None)
            sess.viewer_connected = False
        peer.close()
        sess.last_activity = time.time()
    return ws


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(settings.web_dir / "index.html")


@web.middleware
async def security_headers(request: web.Request, handler: Any) -> web.StreamResponse:
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


async def _reaper(app: web.Application) -> None:
    while True:
        await asyncio.sleep(2)
        await app[MANAGER].reap()


async def on_startup(app: web.Application) -> None:
    app[STATE]["reaper"] = asyncio.create_task(_reaper(app))


async def on_shutdown(app: web.Application) -> None:
    app[STATE]["reaper"].cancel()
    for p in list(app[PEERS].values()):
        p.close()
    await app[MANAGER].stop_all()


def build_app() -> web.Application:
    init_gstreamer()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(settings.games_file, settings.roms_dir, settings.cores_dir, settings.systems_file)
    app = web.Application(middlewares=[security_headers], client_max_size=64 * 1024)
    app[MANAGER] = SessionManager(settings, catalog)
    app[PEERS] = {}
    app[STATE] = {"last_activity": time.time(), "self_sampler": ProcSampler()}
    app[STATE]["self_sampler"].track("worker", os.getpid())
    app.router.add_get("/health", health)
    app.router.add_get("/api/games", list_games)
    app.router.add_get("/api/systems", list_systems)
    app.router.add_get("/api/sessions", list_sessions)
    app.router.add_post("/api/sessions", create_session)
    app.router.add_get("/api/sessions/{sid}", get_session)
    app.router.add_delete("/api/sessions/{sid}", delete_session)
    app.router.add_get("/api/sessions/{sid}/metrics", session_metrics)
    app.router.add_get("/ws/{sid}", signaling)
    app.router.add_get("/", index)
    app.router.add_static("/", settings.web_dir, show_index=False, follow_symlinks=False)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings.dev:
        log.warning("DEV MODE - worker token: %s", settings.worker_token)
    web.run_app(build_app(), host=settings.bind, port=settings.port, handle_signals=True,
                access_log_format='%a "%r" %s %Tfs')


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    main()
