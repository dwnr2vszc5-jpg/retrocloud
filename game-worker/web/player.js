// RetroCloud browser player: WebRTC receiver + keyboard/gamepad/touch input sender.
// Credentials come from the URL fragment (#sid=...&token=...), which browsers never send to servers.
"use strict";
(() => {
  // Must match worker/input.py BUTTON_ORDER
  const ORDER = ["up","down","left","right","a","b","x","y","l","r","l2","r2","start","select"];
  const BIT = Object.fromEntries(ORDER.map((b, i) => [b, 1 << i]));
  const KEYMAP = { ArrowUp:"up", ArrowDown:"down", ArrowLeft:"left", ArrowRight:"right",
    KeyX:"a", KeyZ:"b", KeyS:"x", KeyA:"y", KeyQ:"l", KeyW:"r", KeyE:"l2", KeyR:"r2",
    Enter:"start", ShiftRight:"select", ShiftLeft:"select", Backspace:"select" };
  // W3C "standard" gamepad layout -> retro pad (south=B, east=A, west=Y, north=X like SNES)
  const PADMAP = { 0:"b", 1:"a", 2:"y", 3:"x", 4:"l", 5:"r", 6:"l2", 7:"r2", 8:"select", 9:"start",
    12:"up", 13:"down", 14:"left", 15:"right" };

  const frag = new URLSearchParams(location.hash.slice(1));
  const sid = frag.get("sid"), token = frag.get("token");
  const $ = (id) => document.getElementById(id);
  const video = $("video"), statusEl = $("status"), statsEl = $("stats"), startBtn = $("start");

  let ws = null, pc = null, dc = null, retry = 0, stopped = false;
  let keyMask = 0, touchMask = 0, padMask = 0, sentMask = -1, lastSend = 0;
  let pingRtt = null;
  const stats = { connected: false };
  window.__rcStats = stats; // read by automated tests
  // lets tests (or a "reconnect" button) drop the connection; the player then recovers by itself
  window.__rcDebug = { drop: () => ws?.close() };

  const setStatus = (t, ok = false) => { statusEl.textContent = t; statusEl.classList.toggle("ok", ok); };

  if (!sid || !token) { setStatus("Oturum bilgisi eksik (sid/token)."); return; }

  function connect() {
    if (stopped) return;
    setStatus(retry ? `Yeniden bağlanıyor (deneme ${retry})…` : "Bağlanıyor…");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(sid)}`);
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => onSignal(JSON.parse(ev.data));
    ws.onclose = (ev) => {
      teardown();
      if (ev.code === 4401) { stopped = true; setStatus("Yetkisiz veya oturum çalışmıyor."); return; }
      if (ev.code === 4409) { stopped = true; setStatus("Bu oturum başka bir pencerede açıldı."); return; }
      scheduleReconnect();
    };
  }
  function scheduleReconnect() {
    if (stopped) return;
    retry += 1;
    setTimeout(connect, Math.min(10000, 500 * 2 ** Math.min(retry, 5)));
  }
  function teardown() {
    stats.connected = false;
    if (dc) try { dc.close(); } catch {}
    if (pc) try { pc.close(); } catch {}
    pc = dc = null; sentMask = -1;
    video.srcObject = null; // drop ended tracks so the next connection starts clean
  }

  async function onSignal(msg) {
    if (msg.type === "config") {
      pc = new RTCPeerConnection({ iceServers: msg.iceServers || [], bundlePolicy: "max-bundle" });
      pc.ontrack = (ev) => {
        if ("jitterBufferTarget" in ev.receiver) ev.receiver.jitterBufferTarget = 0;
        else if ("playoutDelayHint" in ev.receiver) ev.receiver.playoutDelayHint = 0;
        if (!video.srcObject) video.srcObject = new MediaStream();
        video.srcObject.addTrack(ev.track);
        if (ev.track.kind === "audio") window.__rcAudioTrack = ev.track; // tests analyse it
        video.play().catch(() => { startBtn.hidden = false; });
      };
      pc.ondatachannel = (ev) => {
        dc = ev.channel;
        dc.onopen = () => { sentMask = -1; flushInput(true); };
        dc.onmessage = (e) => {
          const m = JSON.parse(e.data);
          if (m.t === "pong") pingRtt = performance.now() - m.ts;
        };
      };
      pc.onicecandidate = (ev) => {
        if (ev.candidate && ws?.readyState === 1)
          ws.send(JSON.stringify({ type: "ice", candidate: ev.candidate.candidate, sdpMLineIndex: ev.candidate.sdpMLineIndex }));
      };
      pc.onconnectionstatechange = () => {
        const s = pc?.connectionState;
        if (s === "connected") { retry = 0; stats.connected = true; setStatus("Bağlı", true); }
        if (s === "failed") { setStatus("Bağlantı koptu"); ws?.close(); }
      };
    } else if (msg.type === "offer") {
      await pc.setRemoteDescription({ type: "offer", sdp: msg.sdp });
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      ws.send(JSON.stringify({ type: "answer", sdp: answer.sdp }));
    } else if (msg.type === "ice") {
      try { await pc.addIceCandidate({ candidate: msg.candidate, sdpMLineIndex: msg.sdpMLineIndex }); } catch {}
    } else if (msg.type === "error") {
      setStatus("Sunucu: " + msg.message);
    }
  }

  // ---------- input ----------
  function flushInput(force = false) {
    const mask = keyMask | touchMask | padMask;
    const now = performance.now();
    if (dc?.readyState !== "open") return;
    if (force || mask !== sentMask || now - lastSend > 1000) {
      dc.send(JSON.stringify({ t: "pad", m: mask }));
      sentMask = mask; lastSend = now;
    }
  }
  addEventListener("keydown", (e) => {
    const b = KEYMAP[e.code]; if (!b) return;
    e.preventDefault(); keyMask |= BIT[b]; flushInput();
  });
  addEventListener("keyup", (e) => {
    const b = KEYMAP[e.code]; if (!b) return;
    e.preventDefault(); keyMask &= ~BIT[b]; flushInput();
  });
  addEventListener("blur", () => { keyMask = 0; touchMask = 0; flushInput(); });

  function pollPads() {
    let m = 0;
    for (const gp of (navigator.getGamepads ? navigator.getGamepads() : [])) {
      if (!gp) continue;
      gp.buttons.forEach((btn, i) => { if (PADMAP[i] && (btn.pressed || btn.value > 0.5)) m |= BIT[PADMAP[i]]; });
      const [x = 0, y = 0] = gp.axes;
      if (x < -0.5) m |= BIT.left; if (x > 0.5) m |= BIT.right;
      if (y < -0.5) m |= BIT.up;   if (y > 0.5) m |= BIT.down;
    }
    padMask = m; flushInput();
    // handheld-style hotkey: hold SELECT+START (pad, keyboard or touch) ~1.2 s to leave the game
    const all = keyMask | touchMask | padMask, combo = BIT.select | BIT.start;
    if ((all & combo) === combo) { exitHeld ??= performance.now(); if (performance.now() - exitHeld > 1200) exitGame(); }
    else exitHeld = null;
    requestAnimationFrame(pollPads);
  }
  requestAnimationFrame(pollPads);
  // keep a heartbeat even when the tab is hidden (rAF pauses there)
  setInterval(() => flushInput(), 1000);

  // touch controls
  if (matchMedia("(pointer: coarse)").matches) $("touch").hidden = false;
  document.querySelectorAll("#touch [data-b]").forEach((el) => {
    const b = el.dataset.b;
    const on = (e) => { e.preventDefault(); touchMask |= BIT[b]; el.classList.add("on"); flushInput(); };
    const off = (e) => { e.preventDefault(); touchMask &= ~BIT[b]; el.classList.remove("on"); flushInput(); };
    el.addEventListener("pointerdown", on);
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, off));
  });

  // ---------- leave the game: stop the session (launcher token, same tab) and go back ----------
  let exitHeld = null, exiting = false;
  async function exitGame() {
    if (exiting) return; exiting = true; stopped = true;
    setStatus("Çıkılıyor…");
    let wt = ""; try { wt = sessionStorage.getItem("rc_tok") || ""; } catch {}
    try { ws?.close(); pc?.close(); } catch {}
    if (wt) {
      try { await fetch(`/api/sessions/${encodeURIComponent(sid)}`, { method: "DELETE", headers: { Authorization: "Bearer " + wt } }); } catch {}
    }
    location.href = "/";
  }
  $("btn-exit").onclick = exitGame;

  // ---------- UI ----------
  startBtn.onclick = () => { video.muted = false; video.play(); startBtn.hidden = true; };
  video.addEventListener("click", () => { if (video.muted) { video.muted = false; video.play(); } });
  $("btn-fs").onclick = () => document.fullscreenElement ? document.exitFullscreen() : $("stage").requestFullscreen();
  $("btn-stats").onclick = () => { statsEl.hidden = !statsEl.hidden; };
  if (frag.get("stats") === "1") statsEl.hidden = false;

  // ---------- stats ----------
  let prev = {};
  setInterval(async () => {
    if (!pc) return;
    if (dc?.readyState === "open") dc.send(JSON.stringify({ t: "ping", ts: performance.now() }));
    const report = await pc.getStats();
    report.forEach((r) => {
      if (r.type === "inbound-rtp" && r.kind === "video") {
        const dt = (r.timestamp - (prev.vts || r.timestamp)) / 1000;
        stats.videoKbps = dt > 0 ? Math.round(((r.bytesReceived - prev.vbytes) * 8) / dt / 1000) : 0;
        stats.fps = r.framesPerSecond || 0;
        stats.framesDecoded = r.framesDecoded;
        stats.framesDropped = r.framesDropped || 0;
        stats.packetsLost = r.packetsLost;
        stats.jitterMs = Math.round((r.jitter || 0) * 1000);
        stats.width = r.frameWidth; stats.height = r.frameHeight;
        stats.codec = report.get(r.codecId)?.mimeType;
        stats.decodeMsPerFrame = r.framesDecoded ? +((r.totalDecodeTime / r.framesDecoded) * 1000).toFixed(2) : null;
        stats.jitterBufferMs = r.jitterBufferEmittedCount ? Math.round((r.jitterBufferDelay / r.jitterBufferEmittedCount) * 1000) : null;
        prev.vts = r.timestamp; prev.vbytes = r.bytesReceived;
      } else if (r.type === "inbound-rtp" && r.kind === "audio") {
        const dt = (r.timestamp - (prev.ats || r.timestamp)) / 1000;
        stats.audioKbps = dt > 0 ? Math.round(((r.bytesReceived - prev.abytes) * 8) / dt / 1000) : 0;
        stats.audioCodec = report.get(r.codecId)?.mimeType;
        prev.ats = r.timestamp; prev.abytes = r.bytesReceived;
      } else if (r.type === "candidate-pair" && r.nominated && r.state === "succeeded") {
        stats.rttMs = r.currentRoundTripTime != null ? Math.round(r.currentRoundTripTime * 1000) : null;
        const local = report.get(r.localCandidateId);
        stats.candidateType = local?.candidateType;
      }
    });
    stats.inputRttMs = pingRtt != null ? +pingRtt.toFixed(1) : null;
    statsEl.textContent =
      `${stats.width}x${stats.height} @ ${stats.fps} fps  ${stats.codec || ""}\n` +
      `video ${stats.videoKbps} kbps  audio ${stats.audioKbps} kbps\n` +
      `RTT ${stats.rttMs} ms  input RTT ${stats.inputRttMs} ms\n` +
      `jitter ${stats.jitterMs} ms  jbuf ${stats.jitterBufferMs} ms  decode ${stats.decodeMsPerFrame} ms\n` +
      `lost ${stats.packetsLost}  dropped ${stats.framesDropped}  path ${stats.candidateType}`;
  }, 1000);

  connect();
})();
