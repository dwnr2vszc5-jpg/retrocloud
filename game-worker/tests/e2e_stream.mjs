// End-to-end test: real Chromium connects to a running worker over WebRTC and checks
// video, audio, keyboard input, gamepad input and input-to-video latency.
//
//   node tests/e2e_stream.mjs <base_url> <worker_token> [seconds]
//
// It creates its own session with the TestPad ROM and deletes it at the end.
// Results are printed as JSON (consumed by scripts/benchmark.sh).
import { createRequire } from "node:module";
// works with a local `npm i playwright` or a global install found via NODE_PATH
const { chromium } = createRequire(import.meta.url)("playwright");

const [base = "http://127.0.0.1:8080", token = process.env.RC_WORKER_TOKEN, secs = "20"] = process.argv.slice(2);
const H = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
const results = { checks: {}, samples: [] };
const check = (name, ok, detail) => { results.checks[name] = { ok: !!ok, detail }; };

const r = await fetch(`${base}/api/sessions`, { method: "POST", headers: H, body: JSON.stringify({ game_id: "testpad", owner: "e2e" }) });
const sess = await r.json();
if (r.status !== 201) { console.error("session create failed", sess); process.exit(2); }

const browser = await chromium.launch({
  args: ["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.on("console", (m) => { if (m.type() === "error") console.error("[page]", m.text()); });
// Fake Gamepad API: the test toggles window.__padButtons to simulate a controller.
await page.addInitScript(() => {
  window.__padButtons = new Array(17).fill(false);
  navigator.getGamepads = () => [{
    id: "fake-standard-pad", index: 0, connected: true, mapping: "standard", axes: [0, 0, 0, 0],
    buttons: window.__padButtons.map((p) => ({ pressed: p, value: p ? 1 : 0 })),
  }];
});

try {
  await page.goto(`${base}${sess.play_path}&stats=1`);
  await page.waitForFunction(() => window.__rcStats?.connected === true, null, { timeout: 20000 });
  await page.waitForFunction(() => { const v = document.getElementById("video"); return v.videoWidth > 0 && v.currentTime > 0.5; }, null, { timeout: 15000 });
  check("webrtc_connected", true);

  // helper running in page: centroid of the white square in the current video frame
  await page.evaluate(() => {
    const v = document.getElementById("video");
    const c = document.createElement("canvas"); c.width = 320; c.height = 180;
    const g = c.getContext("2d", { willReadFrequently: true });
    window.__square = () => {
      g.drawImage(v, 0, 0, c.width, c.height);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      let sx = 0, sy = 0, n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i + 1] > 200 && d[i + 2] > 200) { const p = i / 4; sx += p % c.width; sy += (p / c.width) | 0; n++; }
      return n ? { x: sx / n, y: sy / n, n } : null;
    };
    // resolves with ms from now until the square has moved horizontally by >= 2px
    window.__waitMove = (x0) => new Promise((res) => {
      const t0 = performance.now();
      const tick = () => {
        const s = window.__square();
        if (s && Math.abs(s.x - x0) >= 2) return res(performance.now() - t0);
        if (performance.now() - t0 > 3000) return res(null);
        v.requestVideoFrameCallback(tick);
      };
      v.requestVideoFrameCallback(tick);
    });
  });

  // ---------- collect stream stats ----------
  for (let i = 0; i < Number(secs); i++) {
    await page.waitForTimeout(1000);
    const s = await page.evaluate(() => ({ ...window.__rcStats }));
    const m = await (await fetch(`${base}/api/sessions/${sess.id}/metrics`, { headers: H })).json();
    results.samples.push({ client: s, server: m });
  }
  const last = results.samples.at(-1).client;
  check("video_received", last.framesDecoded > 0 && last.width > 0, `${last.width}x${last.height} ${last.codec}`);
  check("h264", /h264/i.test(last.codec || ""), last.codec);
  check("audio_received", (last.audioKbps || 0) > 0, `${last.audioKbps} kbps ${last.audioCodec}`);

  // ---------- audio content: hold A (TestPad plays a 440 Hz tone), measure level of the received track ----------
  await page.evaluate(() => {
    const ctx = new AudioContext();
    const src = ctx.createMediaStreamSource(new MediaStream([window.__rcAudioTrack]));
    const an = ctx.createAnalyser(); an.fftSize = 2048; src.connect(an);
    const buf = new Float32Array(an.fftSize);
    window.__rms = () => { an.getFloatTimeDomainData(buf); let s = 0; for (const x of buf) s += x * x; return Math.sqrt(s / buf.length); };
  });
  await page.waitForTimeout(500);
  const rmsSilent = await page.evaluate(() => window.__rms());
  await page.keyboard.down("KeyX"); // KeyX -> A
  await page.waitForTimeout(800);
  const rmsTone = await page.evaluate(() => window.__rms());
  await page.keyboard.up("KeyX");
  check("audio_tone_on_A", rmsTone > 0.01 && rmsTone > rmsSilent * 5,
    { rms_silent: +rmsSilent.toFixed(4), rms_tone: +rmsTone.toFixed(4) });

  // ---------- keyboard input: hold Right, square must move right ----------
  const before = await page.evaluate(() => window.__square());
  const waitK = page.evaluate((x) => window.__waitMove(x), before.x);
  await page.keyboard.down("ArrowRight");
  const kbLatency = await waitK;
  await page.waitForTimeout(300);
  await page.keyboard.up("ArrowRight");
  await page.waitForTimeout(300);
  const afterK = await page.evaluate(() => window.__square());
  check("keyboard_input", afterK.x > before.x + 2, { before: before.x, after: afterK.x, first_move_ms: kbLatency });

  // ---------- gamepad input: d-pad left (button 14) ----------
  const beforeP = await page.evaluate(() => window.__square());
  const waitP = page.evaluate((x) => window.__waitMove(x), beforeP.x);
  await page.evaluate(() => { window.__padButtons[14] = true; });
  const padLatency = await waitP;
  await page.waitForTimeout(300);
  await page.evaluate(() => { window.__padButtons[14] = false; });
  await page.waitForTimeout(300);
  const afterP = await page.evaluate(() => window.__square());
  check("gamepad_input", afterP.x < beforeP.x - 2, { before: beforeP.x, after: afterP.x, first_move_ms: padLatency });

  // ---------- input->video latency, 10 repetitions (Start re-centres between runs) ----------
  const lat = [];
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Enter"); await page.waitForTimeout(400);
    const s0 = await page.evaluate(() => window.__square());
    const w = page.evaluate((x) => window.__waitMove(x), s0.x);
    await page.keyboard.down(i % 2 ? "ArrowLeft" : "ArrowRight");
    const ms = await w;
    await page.keyboard.up(i % 2 ? "ArrowLeft" : "ArrowRight");
    if (ms != null) lat.push(Math.round(ms));
    await page.waitForTimeout(200);
  }
  lat.sort((a, b) => a - b);
  results.input_to_video_ms = { samples: lat, median: lat[Math.floor(lat.length / 2)], max: lat.at(-1) };
  check("latency_measured", lat.length >= 8, results.input_to_video_ms);

  // ---------- reconnect: drop the signaling socket, player must recover and input must still work ----------
  const t0 = Date.now();
  await page.evaluate(() => { window.__rcStats.connected = false; window.__rcDebug.drop(); });
  await page.waitForFunction(() => window.__rcStats?.connected === true, null, { timeout: 20000 });
  await page.waitForTimeout(1500);
  const s1 = await page.evaluate(() => window.__square());
  await page.keyboard.down("ArrowDown"); await page.waitForTimeout(300); await page.keyboard.up("ArrowDown");
  await page.waitForTimeout(400);
  const s2 = await page.evaluate(() => window.__square());
  check("reconnect", s1 && s2 && s2.y > s1.y + 2, { reconnect_ms: Date.now() - t0, before_y: s1?.y, after_y: s2?.y });

  await page.screenshot({ path: "/tmp/e2e_player.png" });
} catch (e) {
  check("exception", false, String(e));
} finally {
  await browser.close();
  await fetch(`${base}/api/sessions/${sess.id}?purge=1`, { method: "DELETE", headers: H });
}

// summarise
const cl = results.samples.map((s) => s.client).filter((c) => c.fps);
const sv = results.samples.map((s) => s.server).filter((s) => s.stream);
const avg = (a) => (a.length ? +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(1) : null);
results.summary = {
  client_fps_avg: avg(cl.map((c) => c.fps)),
  client_video_kbps_avg: avg(cl.map((c) => c.videoKbps)),
  client_audio_kbps_avg: avg(cl.map((c) => c.audioKbps)),
  client_rtt_ms_avg: avg(cl.map((c) => c.rttMs).filter((x) => x != null)),
  client_input_rtt_ms_avg: avg(cl.map((c) => c.inputRttMs).filter((x) => x != null)),
  client_decode_ms_avg: avg(cl.map((c) => c.decodeMsPerFrame).filter((x) => x != null)),
  client_jitter_buffer_ms_avg: avg(cl.map((c) => c.jitterBufferMs).filter((x) => x != null)),
  packets_lost_last: cl.at(-1)?.packetsLost,
  frames_dropped_last: cl.at(-1)?.framesDropped,
  server_encoded_fps_avg: avg(sv.map((s) => s.stream.video_fps)),
  server_video_kbps_avg: avg(sv.map((s) => s.stream.video_kbps)),
  retroarch_cpu_pct_avg: avg(sv.map((s) => s.processes.retroarch?.cpu_pct).filter((x) => x != null)),
  xvfb_cpu_pct_avg: avg(sv.map((s) => s.processes.xvfb?.cpu_pct).filter((x) => x != null)),
  pulse_cpu_pct_avg: avg(sv.map((s) => s.processes.pulse?.cpu_pct).filter((x) => x != null)),
  retroarch_rss_mb: sv.at(-1)?.processes.retroarch?.rss_mb,
  host: sv.at(-1)?.host,
};
delete results.samples;
results.passed = Object.values(results.checks).every((c) => c.ok);
console.log(JSON.stringify(results, null, 2));
process.exit(results.passed ? 0 : 1);
