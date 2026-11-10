"""WebRTC streaming of one session with GStreamer webrtcbin.

Pipeline (one per connected viewer, created on connect, destroyed on disconnect):

  ximagesrc(:N) -> videoconvert(I420) -> x264enc(zerolatency) -> rtph264pay --\
                                                                              webrtcbin <-> browser
  pulsesrc(game.monitor of the session's own PulseAudio) -> opusenc -> rtpopuspay --/
  data channel "input" (browser -> worker) -> XInputInjector(:N)

Signaling (offer/answer/ICE) is plain JSON over the session's authenticated WebSocket;
webrtcbin is the offerer. GStreamer callbacks fire on streaming threads, so every
message back to asyncio goes through loop.call_soon_threadsafe().
"""
from __future__ import annotations

import asyncio
import base64
import ctypes
import hashlib
import hmac
import json
import logging
import threading
import time
from typing import Any, Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
from gi.repository import GLib, Gst, GstSdp, GstWebRTC  # noqa: E402

from .config import Settings  # noqa: E402
from .session import Session  # noqa: E402

log = logging.getLogger("retrocloud.stream")

_glib_loop: GLib.MainLoop | None = None

_gobject = ctypes.CDLL("libgobject-2.0.so.0")
_gobject.g_object_ref.argtypes = [ctypes.c_void_p]
_gobject.g_object_ref.restype = ctypes.c_void_p


def _ice_agent(webrtc: Any) -> Any:
    """Return webrtcbin's ICE agent.

    PyGObject (3.48) drops one reference too many when reading the 'ice-agent'
    property, which frees the agent and crashes the pipeline on the first offer.
    Verified in Phase 0; we add the missing reference by hand (hash(obj) is the C pointer).
    """
    ice = webrtc.get_property("ice-agent")
    if ice is not None:
        _gobject.g_object_ref(hash(ice))
    return ice


def init_gstreamer() -> None:
    """Init GStreamer once and run a GLib main loop in a daemon thread (bus watches, timers)."""
    global _glib_loop
    if _glib_loop is not None:
        return
    Gst.init(None)
    for el in ("ximagesrc", "x264enc", "rtph264pay", "pulsesrc", "opusenc", "rtpopuspay", "webrtcbin", "nicesrc"):
        if Gst.ElementFactory.find(el) is None:
            raise SystemExit(f"GStreamer element '{el}' missing - check the worker image")
    _glib_loop = GLib.MainLoop()
    threading.Thread(target=_glib_loop.run, name="glib-main", daemon=True).start()


def public_ips(value: str) -> list[str]:
    """'34.1.2.3' or '192.168.0.15,100.64.0.7' -> list of IPv4 addresses (invalid entries dropped)."""
    out = []
    for ip in (x.strip() for x in value.split(",")):
        p = ip.split(".")
        if len(p) == 4 and all(x.isdigit() and int(x) < 256 for x in p) and ip not in out:
            out.append(ip)
    return out


def turn_credentials(secret: str, session_id: str, ttl: int = 6 * 3600) -> tuple[str, str]:
    """coturn 'use-auth-secret' (TURN REST API) credentials: short-lived, per session."""
    username = f"{int(time.time()) + ttl}:{session_id}"
    pwd = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
    return username, pwd


def ice_servers(s: Settings, session_id: str) -> tuple[list[dict[str, Any]], str | None]:
    """ICE servers for the browser and the matching TURN URI for webrtcbin."""
    servers: list[dict[str, Any]] = []
    if s.stun_url:
        servers.append({"urls": s.stun_url.replace("stun://", "stun:")})
    gst_turn = None
    if s.turn_host and s.turn_secret:
        user, pwd = turn_credentials(s.turn_secret, session_id)
        servers.append({"urls": [f"turn:{s.turn_host}?transport=udp", f"turn:{s.turn_host}?transport=tcp"],
                        "username": user, "credential": pwd})
        from urllib.parse import quote
        gst_turn = f"turn://{quote(user, safe='')}:{quote(pwd, safe='')}@{s.turn_host}"
    return servers, gst_turn


class StreamPeer:
    def __init__(self, sess: Session, settings: Settings, loop: asyncio.AbstractEventLoop,
                 send: Callable[[dict[str, Any]], None]) -> None:
        self.sess, self.s, self.loop, self._send = sess, settings, loop, send
        self.pipe: Gst.Pipeline | None = None
        self.webrtc: Any = None
        self.channel: Any = None
        self.ws: Any = None  # signaling socket owning this peer (set by app.py)
        self.closed = False
        # counters updated from pad probes (streaming threads; ints are fine under the GIL)
        self.v_bytes = self.v_frames = self.a_bytes = 0
        self._rate_t = time.monotonic()
        self._rate_v = (0, 0)
        self._rate_a = 0
        self.input_msgs = 0
        self.last_rtt_ms: float | None = None

    # ---------- helpers ----------
    def send(self, msg: dict[str, Any]) -> None:
        self.loop.call_soon_threadsafe(self._send, msg)

    def _pipeline_desc(self) -> str:
        v = self.s.video
        sock = self.sess.pulse_socket
        return (
            f"ximagesrc display-name={self.sess.display} use-damage=false show-pointer=false do-timestamp=true "
            f"! video/x-raw,framerate={v.fps}/1 "
            f"! queue max-size-buffers=1 leaky=downstream "
            f"! videoconvert n-threads=2 ! video/x-raw,format=I420 "
            f"! x264enc name=venc tune=zerolatency speed-preset={v.x264_preset} bitrate={v.bitrate_kbps} "
            f"key-int-max={v.keyint} bframes=0 threads=2 "
            f"! video/x-h264,profile=constrained-baseline,stream-format=byte-stream "
            f"! h264parse ! rtph264pay name=vpay config-interval=-1 aggregate-mode=zero-latency "
            f"! application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 "
            f"! queue ! webrtc. "
            f"pulsesrc server=unix:{sock} device=game.monitor do-timestamp=true provide-clock=false "
            f"buffer-time=40000 latency-time=10000 "
            f"! audio/x-raw,rate=48000,channels=2 ! audioconvert ! audioresample "
            f"! queue max-size-time=100000000 leaky=downstream "
            f"! opusenc name=aenc bitrate=96000 frame-size=10 audio-type=generic "
            f"! rtpopuspay ! application/x-rtp,media=audio,encoding-name=OPUS,payload=111,clock-rate=48000 "
            f"! queue ! webrtc. "
            f"webrtcbin name=webrtc bundle-policy=max-bundle latency=0"
        )

    # ---------- lifecycle ----------
    def start(self, gst_turn: str | None) -> None:
        self.pipe = Gst.parse_launch(self._pipeline_desc())
        self.webrtc = self.pipe.get_by_name("webrtc")
        if self.s.stun_url:
            self.webrtc.set_property("stun-server", self.s.stun_url)
        if gst_turn:
            self.webrtc.emit("add-turn-server", gst_turn)
        ice = _ice_agent(self.webrtc)
        if ice is not None:
            # keep media on the UDP range opened in the firewall
            ice.set_property("min-rtp-port", self.s.rtp_port_min)
            ice.set_property("max-rtp-port", self.s.rtp_port_max)
        self.webrtc.connect("on-negotiation-needed", self._on_negotiation_needed)
        self.webrtc.connect("on-ice-candidate", self._on_ice_candidate)
        self.webrtc.connect("notify::ice-connection-state", self._on_ice_state)

        venc_src = self.pipe.get_by_name("venc").get_static_pad("src")
        venc_src.add_probe(Gst.PadProbeType.BUFFER, self._count_video)
        aenc_src = self.pipe.get_by_name("aenc").get_static_pad("src")
        aenc_src.add_probe(Gst.PadProbeType.BUFFER, self._count_audio)

        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_bus_error)

        self.pipe.set_state(Gst.State.READY)
        self.channel = self.webrtc.emit("create-data-channel", "input", Gst.Structure.new_from_string(
            "config,ordered=(boolean)true"))
        if self.channel:
            self.channel.connect("on-message-string", self._on_input)
        self.pipe.set_state(Gst.State.PLAYING)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.sess.injector:
            self.sess.injector.release_all()  # never leave a button stuck after disconnect
        if self.pipe:
            self.pipe.get_bus().remove_signal_watch()
            self.pipe.set_state(Gst.State.NULL)
            self.pipe = None

    # ---------- webrtcbin callbacks (streaming threads) ----------
    def _on_negotiation_needed(self, element: Any) -> None:
        promise = Gst.Promise.new_with_change_func(self._on_offer_created, element, None)
        element.emit("create-offer", None, promise)

    def _on_offer_created(self, promise: Gst.Promise, element: Any, _: Any) -> None:
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value("offer")
        element.emit("set-local-description", offer, Gst.Promise.new())
        self.send({"type": "offer", "sdp": offer.sdp.as_text()})

    def _on_ice_candidate(self, _el: Any, mline: int, candidate: str) -> None:
        self.send({"type": "ice", "candidate": candidate, "sdpMLineIndex": mline})
        # GCE gives the VM only a private address behind 1:1 NAT. Advertising the same
        # host candidate with the public IP saves a STUN round trip and works even if
        # outbound STUN is blocked.
        # RC_PUBLIC_IP may list several addresses (e.g. LAN IP + Tailscale IP when the worker
        # runs in Docker Desktop on a Mac); each gets its own copy of the host candidate.
        if self.s.public_ip and " typ host" in candidate and " udp " in candidate.lower():
            parts = candidate.split()
            if len(parts) > 5 and ":" not in parts[4]:
                for ip in public_ips(self.s.public_ip):
                    if ip != parts[4]:
                        self.send({"type": "ice", "candidate": " ".join([*parts[:4], ip, *parts[5:]]),
                                   "sdpMLineIndex": mline})

    def _on_ice_state(self, el: Any, _pspec: Any) -> None:
        state = el.get_property("ice-connection-state")
        log.info("session %s ICE state %s", self.sess.id, state.value_nick)
        self.send({"type": "state", "ice": state.value_nick})

    def _on_bus_error(self, _bus: Any, msg: Gst.Message) -> None:
        err, dbg = msg.parse_error()
        log.error("session %s pipeline error: %s (%s)", self.sess.id, err, dbg)
        self.send({"type": "error", "message": "stream pipeline error"})

    def _count_video(self, _pad: Any, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buf = info.get_buffer()
        self.v_bytes += buf.get_size()
        self.v_frames += 1
        return Gst.PadProbeReturn.OK

    def _count_audio(self, _pad: Any, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        self.a_bytes += info.get_buffer().get_size()
        return Gst.PadProbeReturn.OK

    def _on_input(self, _ch: Any, data: str) -> None:
        inj = self.sess.injector
        if inj is None or len(data) > 512:
            return
        try:
            msg = json.loads(data)
        except ValueError:
            return
        self.input_msgs += 1
        self.sess.last_activity = time.time()
        t = msg.get("t")
        if t == "pad" and isinstance(msg.get("m"), int):
            inj.set_mask(msg["m"] & 0x3FFF)
        elif t == "btn" and isinstance(msg.get("b"), str):
            inj.set_button(msg["b"], bool(msg.get("d")))
        elif t == "ping":
            # echo for application-level input latency measurement (browser computes RTT)
            if self.channel:
                self.channel.emit("send-string", json.dumps({"t": "pong", "ts": msg.get("ts")}))

    # ---------- signaling from the browser (asyncio thread) ----------
    def handle_answer(self, sdp: str) -> None:
        _res, sdpmsg = GstSdp.SDPMessage.new()
        GstSdp.sdp_message_parse_buffer(sdp.encode(), sdpmsg)
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
        self.webrtc.emit("set-remote-description", answer, Gst.Promise.new())

    def handle_ice(self, candidate: str, mline: int) -> None:
        if candidate:
            self.webrtc.emit("add-ice-candidate", int(mline), candidate)

    # ---------- metrics ----------
    def rates(self) -> dict[str, float]:
        now = time.monotonic()
        dt = max(now - self._rate_t, 1e-6)
        vb, vf = self._rate_v
        out = {
            "video_kbps": round((self.v_bytes - vb) * 8 / dt / 1000, 1),
            "video_fps": round((self.v_frames - vf) / dt, 1),
            "audio_kbps": round((self.a_bytes - self._rate_a) * 8 / dt / 1000, 1),
            "input_msgs_total": self.input_msgs,
        }
        self._rate_t, self._rate_v, self._rate_a = now, (self.v_bytes, self.v_frames), self.a_bytes
        return out
