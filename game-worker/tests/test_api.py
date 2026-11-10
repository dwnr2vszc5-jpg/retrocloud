"""API tests against the real aiohttp app (needs GStreamer + RetroArch + Xvfb, i.e. the worker image)."""
import asyncio
import json
import shutil

import pytest

pytest.importorskip("gi")
if not (shutil.which("retroarch") and shutil.which("Xvfb") and shutil.which("pulseaudio")):
    pytest.skip("worker runtime not installed", allow_module_level=True)

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from worker.app import build_app  # noqa: E402

AUTH = {"Authorization": "Bearer test-token-0123456789"}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _with_client(fn):
    client = TestClient(TestServer(build_app()))
    await client.start_server()
    try:
        return await fn(client)
    finally:
        await client.close()


def test_health_is_public() -> None:
    async def t(c):
        r = await c.get("/health")
        assert r.status == 200 and (await r.json())["status"] == "ok"
    run(_with_client(t))


@pytest.mark.parametrize("method,path", [("GET", "/api/games"), ("GET", "/api/sessions"),
                                         ("POST", "/api/sessions"), ("DELETE", "/api/sessions/x"),
                                         ("GET", "/api/sessions/x/metrics")])
def test_api_requires_worker_token(method: str, path: str) -> None:
    async def t(c):
        r = await c.request(method, path, headers={"Authorization": "Bearer wrong"})
        assert r.status == 401
        r = await c.request(method, path)
        assert r.status == 401
    run(_with_client(t))


def test_create_rejects_unknown_and_invalid_game() -> None:
    async def t(c):
        r = await c.post("/api/sessions", headers=AUTH, json={"game_id": "nope"})
        assert r.status == 400
        r = await c.post("/api/sessions", headers=AUTH, json={"game_id": "../etc"})
        assert r.status == 400
    run(_with_client(t))


def test_session_lifecycle_capacity_and_ws_auth() -> None:
    async def t(c):
        ids = []
        for _ in range(2):
            r = await c.post("/api/sessions", headers=AUTH, json={"game_id": "testpad", "owner": "pytest"})
            body = await r.json()
            assert r.status == 201, body
            assert body["state"] == "running" and len(body["token"]) >= 32
            ids.append((body["id"], body["token"]))
        r = await c.post("/api/sessions", headers=AUTH, json={"game_id": "testpad"})
        assert r.status == 409  # RC_MAX_SESSIONS=2
        # wrong token -> 4401
        ws = await c.ws_connect(f"/ws/{ids[0][0]}")
        await ws.send_str(json.dumps({"type": "auth", "token": ids[1][1]}))
        msg = await ws.receive_json()
        assert msg["type"] == "error"
        await ws.receive()
        assert ws.close_code == 4401
        # right token -> config with ICE servers, then an SDP offer from the worker
        ws = await c.ws_connect(f"/ws/{ids[0][0]}")
        await ws.send_str(json.dumps({"type": "auth", "token": ids[0][1]}))
        assert (await ws.receive_json())["type"] == "config"
        offer = await asyncio.wait_for(ws.receive_json(), 10)
        assert offer["type"] == "offer" and "H264" in offer["sdp"] and "OPUS" in offer["sdp"].upper()
        assert "webrtc-datachannel" in offer["sdp"]
        await ws.close()
        for sid, _ in ids:
            r = await c.delete(f"/api/sessions/{sid}?purge=1", headers=AUTH)
            assert r.status == 200
        assert await (await c.get("/api/sessions", headers=AUTH)).json() == []
    run(_with_client(t))
