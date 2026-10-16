"use strict";
// julz approver page. SECURITY.md threats 31 to 37.
// Spec text is written by a maybe injected julz: it is only ever set with textContent,
// never parsed as HTML (threat 34). The CSP forbids inline script, so this file is all there is.

const $ = (id) => document.getElementById(id);

function dec(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  return Uint8Array.from(atob(s), (ch) => ch.charCodeAt(0));
}

function enc(buf) {
  let s = "";
  for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function status(text, bad) {
  const s = $("status");
  s.textContent = text;
  s.className = bad ? "bad" : "";
}

async function api(path, body) {
  const init = body === undefined
    ? { cache: "no-store" }
    : { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) };
  const r = await fetch(path, init);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// ---------- WebAuthn JSON <-> browser objects ----------

function ids(list) {
  return (list || []).map((c) => ({ ...c, id: dec(c.id) }));
}

function requestOptions(o) {
  return { ...o, challenge: dec(o.challenge), allowCredentials: ids(o.allowCredentials) };
}

function creationOptions(o) {
  return { ...o, challenge: dec(o.challenge), user: { ...o.user, id: dec(o.user.id) },
           excludeCredentials: ids(o.excludeCredentials) };
}

function assertionJSON(c) {
  const r = c.response;
  return { id: c.id, rawId: enc(c.rawId), type: c.type,
           response: { clientDataJSON: enc(r.clientDataJSON),
                       authenticatorData: enc(r.authenticatorData),
                       signature: enc(r.signature),
                       userHandle: r.userHandle ? enc(r.userHandle) : null } };
}

function attestationJSON(c) {
  const r = c.response;
  return { id: c.id, rawId: enc(c.rawId), type: c.type,
           response: { clientDataJSON: enc(r.clientDataJSON),
                       attestationObject: enc(r.attestationObject) } };
}

// ---------- page ----------

function card(spec) {
  const c = el("article", undefined, "card");
  c.append(el("h2", spec.project), el("p", spec.name, "muted"), el("pre", spec.text),
           el("p", `sha256 ${spec.sha256}`, "hash"));
  const row = el("div", undefined, "row");
  const yes = el("button", "Approve", "approve");
  const no = el("button", "Reject", "reject");
  yes.type = no.type = "button";
  const body = { name: spec.name, sha256: spec.sha256 };
  yes.addEventListener("click", () => act("approve", body, [yes, no]));
  no.addEventListener("click", () => act("reject", body, [yes, no]));
  row.append(yes, no);
  c.append(row);
  return c;
}

// A blocked task: I do what Claude asked on the laptop, then sign "done", or stop the task.
// The text I sign comes from host task state and names the exact need shown here.
function needCard(n) {
  const c = el("article", undefined, "card need");
  c.append(el("h2", `Claude needs you, ${n.project}, step ${n.step}`), el("p", n.goal, "muted"),
           el("p", `need: ${n.need}`, "needline"), el("p", `why: ${n.why}`),
           el("p", `/work on the laptop is ${n.work}`, "hash"),
           el("p", "Tap Done only after you did it on the laptop.", "bad"),
           el("pre", n.text), el("p", `sha256 ${n.sha256}`, "hash"));
  const row = el("div", undefined, "row");
  const yes = el("button", "Done, continue", "approve");
  const no = el("button", "Stop task", "reject");
  yes.type = no.type = "button";
  const body = { root: n.root, sha256: n.sha256 };
  yes.addEventListener("click", () => act("continue", body, [yes, no]));
  no.addEventListener("click", () => act("stop", body, [yes, no]));
  row.append(yes, no);
  c.append(row);
  return c;
}

// The run going now. Stop kills Claude's sandbox; the work copy stays for me to look at.
function runningCard(r) {
  const c = el("article", undefined, "card need");
  c.append(el("h2", `Running now, ${r.project}, step ${r.step}`), el("p", r.goal, "muted"),
           el("p", `started ${r.started}`, "hash"), el("pre", r.text),
           el("p", `sha256 ${r.text_sha256}`, "hash"));
  const row = el("div", undefined, "row");
  const stop = el("button", "Stop run", "reject");
  stop.type = "button";
  stop.addEventListener("click",
    () => act("halt", { run: r.sha256, sha256: r.text_sha256 }, [stop]));
  row.append(stop);
  c.append(row);
  return c;
}

async function load() {
  let s;
  try {
    s = await api("/api/state");
  } catch (e) {
    status(e.message, true);
    return;
  }
  $("enroll").hidden = s.enrolled;
  $("queue").hidden = !s.enrolled;
  const list = $("specs");
  list.replaceChildren();
  if (!s.specs.length && !s.needs.length && !s.running) {
    list.append(el("p", "Nothing waiting.", "muted"));
  }
  if (s.running) list.append(runningCard(s.running));
  for (const n of s.needs) list.append(needCard(n));
  for (const spec of s.specs) list.append(card(spec));
  $("waiting").textContent = s.waiting ? `${s.waiting} more waiting, shown after these` : "";
  const refused = $("refused");
  refused.replaceChildren();
  for (const r of s.refused) refused.append(el("p", `refused ${r.name}: ${r.reason}`, "bad"));
}

async function act(action, body, buttons) {
  buttons.forEach((b) => (b.disabled = true));
  status(`Touch the sensor to ${action}.`);
  try {
    const b = await api("/api/begin", { action, ...body });
    const cred = await navigator.credentials.get({ publicKey: requestOptions(b.publicKey) });
    const r = await api("/api/finish", { action, nonce: b.nonce, credential: assertionJSON(cred) });
    status(`${r.done} ${r.sha256.slice(0, 12)}`);
  } catch (e) {
    status(e.message, true);
  }
  load();
}

async function enroll() {
  const btn = $("enroll-btn");
  btn.disabled = true;
  try {
    const b = await api("/api/enroll/begin", { code: $("code").value });
    const cred = await navigator.credentials.create({ publicKey: creationOptions(b.publicKey) });
    await api("/api/enroll/finish", { credential: attestationJSON(cred) });
    status("passkey registered");
  } catch (e) {
    status(e.message, true);
  }
  btn.disabled = false;
  load();
}

$("reload").addEventListener("click", () => { status(""); load(); });
$("enroll-btn").addEventListener("click", enroll);
load();
