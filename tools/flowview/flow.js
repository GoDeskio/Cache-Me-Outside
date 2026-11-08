// Animated data-flow view (plan #130). Dots per second follow the /v1/flow rates.
"use strict";
const NS = "http://www.w3.org/2000/svg";
const lanes = {req: "req", near_hit: "near", cache_hit: "hit", miss: "miss", db: "db"};
const pathOf = {req: "p-req", near: "p-near", hit: "p-hit", miss: "p-miss", db: "p-db"};
let rates = {}, dots = [], acc = {};
const MAX_DOTS = 400, SCALE = 0.05, SPEED = 0.6; // dots per request, path fraction/s
function spawn(cls) {
  if (dots.length >= MAX_DOTS) return;
  const c = document.createElementNS(NS, "circle");
  c.setAttribute("class", "dot " + cls); c.setAttribute("r", 4);
  document.getElementById("dots").appendChild(c);
  dots.push({el: c, p: document.getElementById(pathOf[cls]), t: 0});
}
let last = performance.now();
function tick(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  for (const [k, cls] of Object.entries(lanes)) {
    acc[k] = (acc[k] || 0) + (rates[k] || 0) * SCALE * dt;
    while (acc[k] >= 1) { spawn(cls); acc[k] -= 1; }
  }
  dots = dots.filter(d => {
    d.t += SPEED * dt;
    if (d.t >= 1) { d.el.remove(); return false; }
    const L = d.p.getTotalLength(), pt = d.p.getPointAtLength(d.t * L);
    d.el.setAttribute("cx", pt.x); d.el.setAttribute("cy", pt.y); return true;
  });
  requestAnimationFrame(tick);
}
async function poll() {
  try {
    const r = await fetch("/v1/flow", {cache: "no-store"});
    rates = await r.json();
    const hr = rates.hit_ratio == null ? "–" : (rates.hit_ratio * 100).toFixed(1) + "%";
    document.getElementById("stats").textContent =
      `req/s ${rates.req}  near ${rates.near_hit}  hit ${rates.cache_hit}  miss ${rates.miss}  db ${rates.db}  hit ratio ${hr}`;
  } catch (e) { document.getElementById("stats").textContent = "feed unavailable"; }
}
poll(); setInterval(poll, 1000);
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) requestAnimationFrame(tick);
