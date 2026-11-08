"use strict";
const $ = function (id) { return document.getElementById(id); };
let current = "";

function limitLabel(value) {
  return value ? String(value) : "unlimited";
}

async function api(method, path, body) {
  const token = await window.CMO.ensureToken();
  const response = await fetch(path, {
    method: method,
    headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || String(response.status));
  return payload;
}

function showSecret(db) {
  const box = $("result");
  box.hidden = false;
  box.textContent = "";
  const title = document.createElement("strong");
  title.textContent = "Database " + db.name + " is ready. Copy the password now. It is shown once.";
  const host = location.hostname;
  const url = "redis://" + encodeURIComponent(db.name) + ":" + encodeURIComponent(db.password) + "@" + host + ":" + db.port;
  const input = document.createElement("input");
  input.className = "url";
  input.readOnly = true;
  input.value = url;
  input.setAttribute("aria-label", "Connection URL, shown once");
  const copy = document.createElement("button");
  copy.className = "btn";
  copy.type = "button";
  copy.textContent = "Copy URL";
  copy.addEventListener("click", async function () {
    try {
      await navigator.clipboard.writeText(url);
      copy.textContent = "Copied";
    } catch (e) {
      input.focus();
      input.select();
      copy.textContent = "Select the URL and copy";
    }
  });
  const cli = document.createElement("p");
  cli.textContent = "CLI: valkey-cli -h " + host + " -p " + db.port + " --user " + db.name + " --askpass";
  const prefix = document.createElement("p");
  prefix.textContent = "Keys must start with " + db.name + ":";
  box.append(title, input, copy, cli, prefix);
  if (db.sample_key) {
    const sample = document.createElement("p");
    sample.textContent = "Local demo sample key: " + db.sample_key;
    box.append(sample);
  }
}

function button(label, onClick) {
  const el = document.createElement("button");
  el.className = "btn";
  el.type = "button";
  el.textContent = label;
  el.addEventListener("click", onClick);
  return el;
}

async function load() {
  $("err").textContent = "";
  const list = $("dbs");
  list.textContent = "";
  try {
    const body = await api("GET", "/v1/databases");
    if (!body.databases.length) {
      const empty = document.createElement("p");
      empty.className = "fine";
      empty.textContent = "No databases yet.";
      list.append(empty);
      return;
    }
    body.databases.forEach(function (db) {
      const card = document.createElement("article");
      card.className = "card";
      const title = document.createElement("h3");
      title.textContent = db.name;
      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = "Port " + db.port
        + " · ops/s " + limitLabel(db.ops_per_sec)
        + " · connections " + limitLabel(db.max_conns)
        + " · bytes/s " + limitLabel(db.bytes_per_sec);
      const actions = document.createElement("div");
      actions.className = "row";
      actions.append(
        button("Browse", function () { browse(db.name, "0"); }),
        button("New password", async function () {
          if (!window.confirm("Replace the password for " + db.name + "? The old one stops working.")) return;
          try { showSecret(Object.assign({}, db, await api("POST", "/v1/databases/" + db.name + "/rotate-password", {}))); }
          catch (e) { $("err").textContent = e.message; }
        }),
        button("Limits", function () { limits(db); }),
        button("Delete", async function () {
          if (!window.confirm("Delete " + db.name + "? Keys under " + db.name + ": stay on the server.")) return;
          try { await api("DELETE", "/v1/databases/" + db.name); await load(); }
          catch (e) { $("err").textContent = e.message; }
        })
      );
      card.append(title, meta, actions);
      list.append(card);
    });
  } catch (e) {
    $("err").textContent = e.message;
  }
}

function limits(db) {
  const box = $("result");
  box.hidden = false;
  box.textContent = "";
  const form = document.createElement("form");
  form.id = "limits";
  const ops = field("Ops per second (0 means unlimited)", "lim-ops", db.ops_per_sec);
  const conns = field("Max connections (0 means unlimited)", "lim-conns", db.max_conns);
  const bytes = field("Bytes per second (0 means unlimited)", "lim-bytes", db.bytes_per_sec);
  const save = document.createElement("button");
  save.className = "btn p";
  save.type = "submit";
  save.textContent = "Save limits";
  form.append(ops, conns, bytes, save);
  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    try {
      await api("PATCH", "/v1/databases/" + db.name, {
        ops_per_sec: Number(ops.querySelector("input").value),
        max_conns: Number(conns.querySelector("input").value),
        bytes_per_sec: Number(bytes.querySelector("input").value),
      });
      box.hidden = true;
      await load();
    } catch (err) {
      $("err").textContent = err.message;
    }
  });
  const heading = document.createElement("h3");
  heading.textContent = "Limits for " + db.name;
  box.append(heading, form);
}

function field(label, id, value) {
  const wrap = document.createElement("label");
  wrap.className = "field";
  wrap.textContent = label;
  const input = document.createElement("input");
  input.id = id;
  input.type = "number";
  input.min = "0";
  input.required = true;
  input.value = String(value || 0);
  wrap.append(input);
  return wrap;
}

async function browse(name, cursor) {
  $("err").textContent = "";
  $("browser").hidden = false;
  $("bname").textContent = "Keys in " + name;
  if (cursor === "0") $("keys").textContent = "";
  current = name;
  try {
    const body = await api("GET", "/v1/databases/" + encodeURIComponent(name)
      + "/keys?cursor=" + encodeURIComponent(cursor)
      + "&match=" + encodeURIComponent($("bmatch").value));
    if (!body.keys.length && cursor === "0") {
      const empty = document.createElement("li");
      empty.textContent = "No keys match.";
      $("keys").append(empty);
    }
    body.keys.forEach(function (key) {
      const item = document.createElement("li");
      item.append(button(key, function () { openKey(name, key); }));
      $("keys").append(item);
    });
    $("bmore").hidden = body.cursor === "0";
    $("bmore").onclick = function () { browse(name, body.cursor); };
  } catch (e) {
    $("err").textContent = e.message;
  }
}

async function openKey(name, key) {
  try {
    const body = await api("GET", "/v1/databases/" + encodeURIComponent(name) + "/keys?key=" + encodeURIComponent(key));
    const box = $("kv");
    box.hidden = false;
    box.textContent = "";
    const meta = document.createElement("p");
    meta.textContent = body.key + " · " + body.type + " · TTL " + (body.ttl < 0 ? "none" : body.ttl + "s")
      + (body.size !== undefined ? " · size " + body.size : "")
      + (body.truncated ? " · first 100 shown" : "");
    const pre = document.createElement("pre");
    const real = JSON.stringify(body.value, null, 2);
    pre.textContent = "hidden";
    const eye = document.createElement("button");
    eye.className = "btn";
    eye.type = "button";
    eye.textContent = "Show value";
    eye.setAttribute("aria-pressed", "false");
    eye.addEventListener("click", function () {
      const on = eye.getAttribute("aria-pressed") !== "true";
      eye.setAttribute("aria-pressed", on ? "true" : "false");
      pre.textContent = on ? real : "hidden";
      eye.textContent = on ? "Hide value" : "Show value";
    });
    box.append(meta, eye, pre);
  } catch (e) {
    $("err").textContent = e.message;
  }
}

$("load").addEventListener("click", load);
$("create").addEventListener("submit", async function (e) {
  e.preventDefault();
  $("err").textContent = "";
  const name = $("name").value;
  if (!/^[a-z][a-z0-9-]{1,30}$/.test(name)) {
    $("err").textContent = "Name: 2-31 characters, a lowercase letter, then letters, digits, or dashes.";
    return;
  }
  const body = {name: name};
  ["ops", "conns", "bytes"].forEach(function (id) {
    const raw = $(id).value;
    if (raw === "") return;
    const key = {ops: "ops_per_sec", conns: "max_conns", bytes: "bytes_per_sec"}[id];
    body[key] = Number(raw);
  });
  try {
    showSecret(await api("POST", "/v1/databases", body));
    $("name").value = "";
    await load();
  } catch (err) {
    $("err").textContent = err.message;
  }
});
$("bform").addEventListener("submit", function (e) {
  e.preventDefault();
  if (current) browse(current, "0");
});
document.addEventListener("cmo-refresh", load);
document.addEventListener("cmo-browse", function (e) {
  if (e.detail) browse(e.detail, "0");
});
window.CMO.ensureToken().then(function (token) { if (token) load(); });
