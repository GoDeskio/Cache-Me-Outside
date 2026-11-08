"use strict";
const NS = "http://www.w3.org/2000/svg";
const lanes = {req: "req", near_hit: "near", cache_hit: "hit", miss: "miss", db: "db"};
const pathOf = {req: "p-req", near: "p-near", hit: "p-hit", miss: "p-miss", db: "p-db"};
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let rates = {};
let dots = [];
const acc = {};
const MAX_DOTS = 400;
const SCALE = 0.05;
const SPEED = 0.6;

function spawn(cls) {
  if (reduce || dots.length >= MAX_DOTS) return;
  const dot = document.createElementNS(NS, "circle");
  dot.setAttribute("class", "dot " + (cls === "db" ? "dbdot" : cls));
  dot.setAttribute("r", "4");
  document.getElementById("dots").appendChild(dot);
  dots.push({el: dot, p: document.getElementById(pathOf[cls]), t: 0});
}

let last = performance.now();
function tick(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  Object.keys(lanes).forEach(function (key) {
    acc[key] = (acc[key] || 0) + (rates[key] || 0) * SCALE * dt;
    while (acc[key] >= 1) { spawn(lanes[key]); acc[key] -= 1; }
  });
  dots = dots.filter(function (dot) {
    dot.t += SPEED * dt;
    if (dot.t >= 1 || !dot.p) { dot.el.remove(); return false; }
    const point = dot.p.getPointAtLength(dot.t * dot.p.getTotalLength());
    dot.el.setAttribute("cx", point.x);
    dot.el.setAttribute("cy", point.y);
    return true;
  });
  if (!reduce) requestAnimationFrame(tick);
}

async function poll() {
  const stats = document.getElementById("stats");
  const note = document.getElementById("flow-note");
  try {
    const response = await fetch("/v1/flow", {cache: "no-store"});
    if (!response.ok) throw new Error("feed unavailable");
    rates = await response.json();
    const ratio = rates.hit_ratio == null ? "none" : (rates.hit_ratio * 100).toFixed(1) + "%";
    stats.textContent = "req/s " + rates.req + "  near " + rates.near_hit + "  hit " + rates.cache_hit
      + "  miss " + rates.miss + "  db " + rates.db + "  hit ratio " + ratio;
    if (note) note.hidden = rates.source !== "demo";
  } catch (e) {
    stats.textContent = "feed unavailable";
  }
}
poll();
setInterval(poll, 1000);
if (!reduce) requestAnimationFrame(tick);
