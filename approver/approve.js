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
  // My note for Claude (threat 93): the server checks it and signs it with the spec, so what
  // I type here is what Claude gets, or the approval is refused before the passkey prompt
  const label = el("label", "Note for Claude ", "note-label");
  label.append(el("span", "· optional"));
  const note = el("input", undefined, "answer");
  note.maxLength = 280;
  note.autocomplete = "off";
  note.placeholder = "for example: use port 8080";
  label.htmlFor = note.id = `note-${spec.sha256.slice(0, 12)}`;
  c.append(label, note, el("p", "Plain text, sent with your approval. No links.", "note-help"));
  const row = el("div", undefined, "row");
  const yes = el("button", "Approve with passkey", "approve");
  const no = el("button", "Deny", "reject");
  yes.type = no.type = "button";
  const body = { name: spec.name, sha256: spec.sha256 };
  yes.addEventListener("click", () => act("approve", { ...body, note: note.value }, [yes, no]));
  no.addEventListener("click", () => act("reject", body, [yes, no]));
  row.append(yes, no);
  c.append(row);
  return c;
}

// A blocked task: I do what Claude asked on the laptop, then sign "done", or stop the task.
// The text I sign comes from host task state and names the exact need shown here.
// A stopped run waits the same way: Continue carries on, Delete removes the work copy.
function needCard(n) {
  const c = el("article", undefined, "card need");
  const title = n.stopped ? `Stopped, ${n.project}, next step ${n.step}`
                          : `Claude needs you, ${n.project}, step ${n.step}`;
  c.append(el("h2", title), el("p", n.goal, "muted"));
  if (n.stopped) {
    c.append(el("p", n.need, "needline"), el("p", n.why),
             el("p", `work copy on the laptop: ${n.work}`, "hash"));
  } else {
    c.append(el("p", `need: ${n.need}`, "needline"), el("p", `why: ${n.why}`),
             el("p", `/work on the laptop is ${n.work}`, "hash"),
             el("p", "Tap Done only after you did it on the laptop.", "bad"));
  }
  const pre = el("pre", n.text);
  const sha = el("p", `sha256 ${n.sha256}`, "hash");
  c.append(pre, sha);
  // One green button that follows the box (threats 50, 51): empty means Done or Continue,
  // text means Send answer. The server checks the line and builds the text I sign around
  // it, so the page only sends this one value. The text shown is updated as I type.
  const box = el("input", undefined, "answer");
  box.type = "text";
  box.maxLength = 300;
  box.autocomplete = "off";
  box.enterKeyHint = "send";
  box.placeholder = n.stopped ? "tell Claude something, or leave empty to continue"
                              : "answer the need above, or leave empty for Done";
  const row = el("div", undefined, "row");
  const done = n.stopped ? "Continue" : "Done, continue";
  const yes = el("button", done, "approve");
  const no = el("button", n.stopped ? "Delete" : "Stop task", "reject");
  yes.type = no.type = "button";
  const body = { root: n.root, sha256: n.sha256 };
  box.addEventListener("input", () => {
    const typed = box.value.trim();
    yes.textContent = typed ? "Send answer" : done;
    pre.textContent = typed ? n.text.replace(/answer: done\n$/, () => `answer: ${typed}\n`) : n.text;
    sha.hidden = Boolean(typed);
  });
  const go = () => {
    const typed = box.value.trim();
    if (typed) act("answer", { ...body, answer: typed }, [yes, no]);
    else act("continue", body, [yes, no]);
  };
  yes.addEventListener("click", go);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  no.addEventListener("click", () => act(n.stopped ? "discard" : "stop", body, [yes, no]));
  row.append(yes, no);
  c.append(box, row, el("p", "Never type a password, token or key here. Claude reads it.", "bad"));
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

// Approved and waiting for the runner. It says when it will start, so an approval held by a
// cap (threat 28) never looks lost. A first run held by the soft cap can be let through
// once with a signed Run now (threat 52); the hard ceiling has no button.
function at(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function queuedCard(q, s) {
  const c = el("article", undefined, "card");
  const step = q.step > 1 ? `, step ${q.step}` : "";
  c.append(el("h2", `Approved, waiting to run${step}`), el("p", q.goal, "muted"));
  let when = s.running ? "starts after the run going now" : "starts within 10 minutes";
  if (s.cap.hard_slot) {
    when = `hard ceiling ${s.cap.all} of ${s.cap.hard} in 2 hours, ` +
           `next slot about ${at(s.cap.hard_slot)}`;
  } else if (q.overridden) {
    when = s.running ? "Run now signed, starts after the run going now"
                     : "Run now signed, starting";
  } else if (q.kind === "spec" && s.cap.next_slot) {
    when = `run cap ${s.cap.used} of ${s.cap.max} in 2 hours, ` +
           `next slot about ${at(s.cap.next_slot)}`;
  }
  c.append(el("p", when));
  if (!q.override) {
    c.append(el("p", `sha256 ${q.sha256}`, "hash"));
    return c;
  }
  c.append(el("pre", q.override.text), el("p", `sha256 ${q.override.sha256}`, "hash"));
  const row = el("div", undefined, "row");
  const now = el("button", "Run now, past the cap", "approve");
  now.type = "button";
  now.addEventListener("click",
    () => act("override", { item: q.sha256, sha256: q.override.sha256 }, [now]));
  row.append(now);
  c.append(row);
  return c;
}

// A done task with notes Claude wrote (threats 54 to 57). Code picked and checked the files;
// I skim them, type a topic and sign. The page sends only the topic, the server builds the
// text I sign around the manifest shown here.
const TOPIC = /^[a-z0-9][a-z0-9-]{0,39}$/;

// Phone keyboards add a space after a word, capitalize the first letter or turn - into a
// dash. Space and case are fixed here; anything else is shown, so I see why Keep stays off.
function cleanTopic(raw) {
  return raw.trim().toLowerCase();
}

function topicProblem(t) {
  if (!t) return "";
  if (TOPIC.test(t)) return "";
  const odd = [...new Set([...t].filter((ch) => !/[a-z0-9-]/.test(ch)))];
  if (odd.length) {
    return "not allowed: " + odd.map((ch) =>
      `'${ch}' U+${ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")}`).join(", ");
  }
  return t.length > 40 ? "at most 40 characters" : "start with a letter or digit";
}

function keepCard(k, topics) {
  const c = el("article", undefined, "card");
  c.append(el("h2", `Done, keep Claude's notes? ${k.project}`), el("p", k.goal, "muted"),
           el("p", "Tick the files to keep:"));
  // All ticked to start. The server builds the signed list from these names (threat 57)
  const ticks = [];
  for (const f of k.files) {
    const label = el("label", undefined, "pick");
    const tick = el("input");
    tick.type = "checkbox";
    tick.checked = true;
    tick.value = f.path;
    ticks.push(tick);
    label.append(tick, el("span", ` ${f.path}  ${f.size} bytes`, "hash"));
    c.append(label);
  }
  // Two different things: what the checks refused (fixed), and what I leave out (live)
  const left = el("p", "", "muted");
  c.append(left);
  c.append(el("p", k.rejected.length ? "Refused by the checks, cannot be kept:"
                                     : "Refused by the checks: none",
              k.rejected.length ? "bad" : "muted"));
  for (const r of k.rejected) c.append(el("p", `${r.path}: ${r.reason}`, "hash"));
  if (k.rejected_count > k.rejected.length) {
    c.append(el("p", `and ${k.rejected_count - k.rejected.length} more`, "hash"));
  }
  if (k.stopped) c.append(el("p", k.stopped, "bad"));
  c.append(el("p", "Skim them on the laptop first: julz reads kept notes again and again. " +
                   "One Keep per task: files you untick cannot be kept later.", "bad"));
  const picked = () => ticks.filter((t) => t.checked).map((t) => t.value);
  const unpicked = () => ticks.filter((t) => !t.checked).map((t) => t.value);
  const text = (topic) => `keep: ${k.root}\ntopic: ${topic}\nmanifest: ${k.sha256}\n` +
                          `pick: ${picked().join(" ")}\n`;
  const pre = el("pre");
  const hint = el("p", "", "bad");
  const box = el("input", undefined, "answer");
  box.type = "text";
  box.maxLength = 60;
  box.autocomplete = "off";
  box.autocapitalize = "none";
  box.spellcheck = false;
  box.enterKeyHint = "done";
  box.placeholder = "topic, like network-plus";
  const row = el("div", undefined, "row");
  const yes = el("button", "Keep", "approve");
  yes.type = "button";
  const where = el("p", "", "hash");
  const update = () => {
    const t = cleanTopic(box.value);
    const ok = TOPIC.test(t);
    const n = picked().length;
    const out = unpicked();
    left.textContent = out.length ? `Left out by you: ${out.join(", ")}` : "Left out by you: none";
    where.textContent = `files go to julz-mem/Claude/${ok ? t : "<folder>"}/${k.root.slice(0, 8)}/`;
    yes.disabled = !ok || n === 0;
    yes.textContent = `Keep ${n} of ${k.files.length}`;
    hint.textContent = n === 0 ? "tick at least one file" : topicProblem(t);
    pre.textContent = text(ok ? t : "<topic>");
  };
  box.addEventListener("input", update);
  ticks.forEach((t) => t.addEventListener("change", update));
  const go = () => {
    const t = cleanTopic(box.value);
    if (TOPIC.test(t) && picked().length) {
      act("keep", { root: k.root, sha256: k.sha256, topic: t, pick: picked() }, [yes]);
    }
  };
  yes.addEventListener("click", go);
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  row.append(yes);
  // The topic is the folder the files go to, so runs on one subject end up together.
  // Folders used before are one tap away; they come from earlier Keeps, never the vault
  const label = el("label", "Folder in Claude/ (groups notes by subject)");
  label.htmlFor = box.id = `topic-${k.root.slice(0, 8)}`;
  c.append(label);
  if (topics.length) {
    const chips = el("div", undefined, "chips");
    for (const t of topics) {
      const chip = el("button", t, "chip");
      chip.type = "button";
      chip.addEventListener("click", () => { box.value = t; update(); });
      chips.append(chip);
    }
    c.append(chips);
  }
  c.append(box, hint, where, pre, el("p", `manifest sha256 ${k.sha256}`, "hash"), row);
  update();
  return c;
}

// Auto reload: the page asks for the state every few seconds while it is visible, and draws
// again only when something changed, so a card never moves under my thumb.
let busy = false;
let shown = "";
let page = null; // the page files this script came with, from the first state

async function load(force = true) {
  let s;
  try {
    s = await api("/api/state");
  } catch (e) {
    if (force) status(e.message, true);
    return;
  }
  // The approver was restarted with new page files: this script is stale, load the new one
  if (page === null) page = s.page;
  else if (s.page !== page) { location.reload(); return; }
  $("page").textContent = `page ${s.page}`;
  const key = JSON.stringify(s);
  if (!force && key === shown) return;
  shown = key;
  $("enroll").hidden = s.enrolled;
  $("queue").hidden = !s.enrolled;
  const list = $("specs");
  list.replaceChildren();
  if (!s.specs.length && !s.needs.length && !s.running && !s.queued.length && !s.keeps.length) {
    list.append(el("p", "Nothing waiting.", "muted"));
  }
  if (s.running) list.append(runningCard(s.running));
  for (const n of s.needs) list.append(needCard(n));
  for (const spec of s.specs) list.append(card(spec));
  for (const q of s.queued) list.append(queuedCard(q, s));
  for (const k of s.keeps) list.append(keepCard(k, s.topics || []));
  $("waiting").textContent = s.waiting ? `${s.waiting} more waiting, shown after these` : "";
  const refused = $("refused");
  refused.replaceChildren();
  for (const r of s.refused) refused.append(el("p", `refused ${r.name}: ${r.reason}`, "bad"));
  const recent = $("recent-list");
  recent.replaceChildren();
  if (!s.recent.length) recent.append(el("p", "No runs yet.", "muted"));
  for (const r of s.recent) {
    const line = el("p", undefined, "recent");
    // The same 8 characters as the push ("julz: run done 1a2b3c4d") and the log
    line.append(el("span", r.time, "hash"), el("span", ` ${r.status} `, `st-${r.status}`),
                el("span", `${r.sha256.slice(0, 8)} `, "hash"), el("span", r.goal || ""));
    recent.append(line);
  }
}

const LABELS = { approve: "approve", reject: "reject", continue: "continue", answer: "send it",
                 stop: "stop the task", halt: "stop the run", discard: "delete",
                 override: "run it now, past the cap", keep: "keep these notes" };

async function act(action, body, buttons) {
  busy = true;
  buttons.forEach((b) => (b.disabled = true));
  status(`Touch the sensor to ${LABELS[action] || action}.`);
  try {
    const b = await api("/api/begin", { action, ...body });
    const cred = await navigator.credentials.get({ publicKey: requestOptions(b.publicKey) });
    const r = await api("/api/finish", { action, nonce: b.nonce, credential: assertionJSON(cred) });
    status(`${r.done} ${r.sha256.slice(0, 12)}`);
  } catch (e) {
    status(e.message, true);
  }
  busy = false;
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
// A redraw would wipe an answer I am typing, so auto reload waits until the box is empty
function drafting() {
  // A typed box, or a Keep file I unticked: a redraw would tick it again behind my back
  return [...document.querySelectorAll("input.answer")]
    .some((b) => b.value || b === document.activeElement) ||
    [...document.querySelectorAll("label.pick input")].some((t) => !t.checked);
}
setInterval(() => {
  if (!busy && !drafting() && document.visibilityState === "visible") load(false);
}, 5000);
document.addEventListener("visibilitychange", () => {
  if (!busy && !drafting() && document.visibilityState === "visible") load(false);
});
$("enroll-btn").addEventListener("click", enroll);
load();
