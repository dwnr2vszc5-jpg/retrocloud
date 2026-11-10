// Two-session isolation test (Phase 2 preview):
//  * two sessions, two browser pages, each with its own token
//  * input sent in page A moves only A's square
//  * session A's token cannot open session B's signaling socket
//  * stopping session A does not interrupt session B
//   node tests/e2e_isolation.mjs <base_url> <worker_token> [seconds]
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright");

const [base = "http://127.0.0.1:8080", token = process.env.RC_WORKER_TOKEN, secs = "20"] = process.argv.slice(2);
const H = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
const checks = {};
const check = (n, ok, detail) => { checks[n] = { ok: !!ok, detail }; };
const mk = async (owner) => (await fetch(`${base}/api/sessions`, { method: "POST", headers: H, body: JSON.stringify({ game_id: "testpad", owner }) })).json();
const A = await mk("alice"), B = await mk("bob");
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const out = { checks, samples: [] };

const SQUARE = () => {
  const v = document.getElementById("video");
  const c = document.createElement("canvas"); c.width = 320; c.height = 180;
  const g = c.getContext("2d", { willReadFrequently: true });
  window.__square = () => {
    g.drawImage(v, 0, 0, c.width, c.height);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let sx = 0, n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i + 1] > 200 && d[i + 2] > 200) { sx += (i / 4) % c.width; n++; }
    return n ? sx / n : null;
  };
};
async function open(sess) {
  const p = await browser.newPage({ viewport: { width: 960, height: 540 } });
  await p.goto(`${base}${sess.play_path}`);
  await p.waitForFunction(() => window.__rcStats?.connected && document.getElementById("video").currentTime > 0.5, null, { timeout: 20000 });
  await p.evaluate(SQUARE);
  return p;
}
try {
  const [pa, pb] = await Promise.all([open(A), open(B)]);
  check("both_connected", true);

  const a0 = await pa.evaluate(() => window.__square()), b0 = await pb.evaluate(() => window.__square());
  await pa.keyboard.down("ArrowRight"); await pa.waitForTimeout(600); await pa.keyboard.up("ArrowRight");
  await pa.waitForTimeout(400);
  const a1 = await pa.evaluate(() => window.__square()), b1 = await pb.evaluate(() => window.__square());
  check("input_isolated", a1 > a0 + 5 && Math.abs(b1 - b0) < 1, { a0, a1, b0, b1 });

  // wrong-token attempt on B's socket using A's token, from page A's origin
  const denied = await pa.evaluate(async ([sid, tok]) => new Promise((res) => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${sid}`);
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: tok }));
    ws.onclose = (e) => res(e.code);
  }), [B.id, A.token]);
  check("cross_token_rejected", denied === 4401, { close_code: denied });

  // load sample with both streaming
  for (let i = 0; i < Number(secs); i++) {
    await pa.waitForTimeout(1000);
    const ma = await (await fetch(`${base}/api/sessions/${A.id}/metrics`, { headers: H })).json();
    const mb = await (await fetch(`${base}/api/sessions/${B.id}/metrics`, { headers: H })).json();
    const sa = await pa.evaluate(() => ({ ...window.__rcStats })), sb = await pb.evaluate(() => ({ ...window.__rcStats }));
    out.samples.push({ ma, mb, sa, sb });
  }

  // stop A, B must keep receiving frames
  const fb0 = await pb.evaluate(() => window.__rcStats.framesDecoded);
  await fetch(`${base}/api/sessions/${A.id}?purge=1`, { method: "DELETE", headers: H });
  await pb.waitForTimeout(3000);
  const fb1 = await pb.evaluate(() => window.__rcStats.framesDecoded);
  check("stop_A_keeps_B", fb1 - fb0 > 60, { frames_in_3s: fb1 - fb0 });
  const sessions = await (await fetch(`${base}/api/sessions`, { headers: H })).json();
  check("only_B_left", sessions.length === 1 && sessions[0].id === B.id, sessions.map((s) => s.id));
} catch (e) {
  check("exception", false, String(e));
} finally {
  await browser.close();
  for (const s of [A, B]) await fetch(`${base}/api/sessions/${s.id}?purge=1`, { method: "DELETE", headers: H });
}
const avg = (a) => (a.length ? +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(1) : null);
const S = out.samples.slice(2);
out.summary = {
  a_fps: avg(S.map((s) => s.sa.fps)), b_fps: avg(S.map((s) => s.sb.fps)),
  a_kbps: avg(S.map((s) => s.sa.videoKbps)), b_kbps: avg(S.map((s) => s.sb.videoKbps)),
  a_retroarch_cpu: avg(S.map((s) => s.ma.processes.retroarch?.cpu_pct)),
  b_retroarch_cpu: avg(S.map((s) => s.mb.processes.retroarch?.cpu_pct)),
  xvfb_cpu_each: avg(S.map((s) => s.ma.processes.xvfb?.cpu_pct)),
  worker_cpu_total: avg(S.map((s) => s.ma.processes.worker?.cpu_pct)),
  host_load1_last: S.at(-1)?.ma.host.load1,
  mem_available_mb_last: S.at(-1)?.ma.host.mem_available_mb,
};
delete out.samples;
out.passed = Object.values(checks).every((c) => c.ok);
console.log(JSON.stringify(out, null, 2));
process.exit(out.passed ? 0 : 1);
