"use strict";
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const menu = document.getElementById("menu");
const nav = document.getElementById("nav");
if (menu && nav) {
  menu.addEventListener("click", function () {
    const open = nav.classList.toggle("open");
    menu.setAttribute("aria-expanded", open ? "true" : "false");
  });
}
if (!reduce) {
  window.addEventListener("pointermove", function (e) {
    document.documentElement.style.setProperty("--mx", e.clientX + "px");
    document.documentElement.style.setProperty("--my", e.clientY + "px");
  });
}

let sessionToken = "";
async function ensureToken() {
  const field = document.getElementById("tok");
  if (field && field.value) return field.value;
  if (sessionToken) return sessionToken;
  const response = await fetch("/v1/demo", {cache: "no-store"});
  if (!response.ok) return "";
  const body = await response.json();
  sessionToken = body.token || "";
  if (field) field.value = sessionToken;
  const banner = document.getElementById("demo-banner");
  if (banner) banner.hidden = false;
  return sessionToken;
}

async function agentAsk(message) {
  const out = document.getElementById("agent-out");
  const token = await ensureToken();
  if (!token) {
    out.textContent = "Paste the admin token on the console. This page does not keep a token of its own.";
    return;
  }
  const response = await fetch("/v1/agent", {
    method: "POST",
    headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    body: JSON.stringify({message: message}),
  });
  const body = await response.json();
  if (!response.ok) {
    out.textContent = body.error || "The agent could not do that.";
    return;
  }
  out.textContent = body.reply || "";
  (body.actions || []).forEach(function (action) {
    if (action.op === "navigate" && action.href) window.location.assign(action.href);
    if (action.op === "refresh") document.dispatchEvent(new Event("cmo-refresh"));
    if (action.op === "browse") document.dispatchEvent(new CustomEvent("cmo-browse", {detail: action.name}));
  });
}

const agentForm = document.getElementById("agent-form");
if (agentForm) {
  agentForm.addEventListener("submit", function (e) {
    e.preventDefault();
    agentAsk(document.getElementById("agent-q").value);
  });
  document.querySelectorAll("[data-ask]").forEach(function (button) {
    button.addEventListener("click", function () {
      document.getElementById("agent-q").value = button.getAttribute("data-ask");
      agentAsk(button.getAttribute("data-ask"));
    });
  });
}

const versionButton = document.getElementById("show-version");
if (versionButton) {
  versionButton.addEventListener("click", async function () {
    const slot = document.getElementById("version-out");
    try {
      const response = await fetch("/v1/integration", {cache: "no-store"});
      const body = await response.json();
      slot.textContent = body.name + " " + body.version + " (api " + body.api + ")";
    } catch (e) {
      slot.textContent = "The version endpoint did not answer.";
    }
  });
}

window.CMO = {ensureToken: ensureToken};
