"use strict";

/* ====================== estado ====================== */
const grid = document.getElementById("grid");
const tpl = document.getElementById("slot-tpl");
const $ = (id) => document.getElementById(id);

const selected = new Set();          // udids marcados
const busyU = new Set();             // udids sendo impressos
const jobState = new Map();          // udid -> "printing" | "sent" | "fail"
const jobTimers = new Map();
let devById = new Map();
let prevStatus = new Map();          // udid -> status anterior (transições)
let slotOfUdid = new Map();          // udid -> nº do slot (para logs de desconexão)
let seenUdids = new Set();

let SLOTS = 10;
let printCount = 0;
let printerStatus = "offline";
let pollTimer = null;

const LS = {
  get(k, d) { try { const v = localStorage.getItem("nslabel." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("nslabel." + k, JSON.stringify(v)); } catch {} },
};
let autoUpdate = LS.get("auto", true);
let intervalSec = LS.get("interval", 2.5);

/* ====================== helpers ====================== */
async function api(path, opts) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
function copiesVal() {
  return Math.max(1, Math.min(50, parseInt($("copies").value || "1", 10)));
}
function battTier(h) {
  if (h === null || h === undefined) return "b-na";
  if (h >= 90) return "b-good";
  if (h >= 80) return "b-ok";
  if (h >= 70) return "b-low";
  return "b-bad";
}
function icon(name) { return `<svg class="ic"><use href="#i-${name}"/></svg>`; }

/* ====================== som ====================== */
let soundOn = LS.get("sound", true);
let audioCtx = null;
function beep(freqs, dur = 0.13, vol = 0.22) {
  if (!soundOn) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    let t = audioCtx.currentTime + 0.01;
    for (const f of freqs) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = "triangle"; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(vol, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g); g.connect(audioCtx.destination);
      o.start(t); o.stop(t + dur);
      t += dur * 0.85;
    }
  } catch {}
}
const soundReady = () => beep([880, 1174.7]);          // "pronto" — sobe
const soundError = () => beep([440, 330], 0.16, 0.16); // "erro" — desce, mais baixo
window.addEventListener("pointerdown", () => {          // libera o áudio no 1º clique
  try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch {}
}, { once: true });

/* ====================== toast ====================== */
function toast(msg, kind = "info", ms = 2600) {
  const t = document.createElement("div");
  t.className = "t " + kind;
  t.innerHTML = icon(kind === "ok" ? "ok-circle" : kind === "err" ? "alert" : "zap") +
    `<span>${msg}</span>`;
  $("toast").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transform = "translateY(8px)"; }, ms);
  setTimeout(() => t.remove(), ms + 300);
}

/* ====================== atividade ====================== */
const activity = [];
function logAct(txt, kind = "info") {
  const now = new Date();
  const time = now.toLocaleTimeString("pt-BR", { hour12: false });
  activity.unshift({ time, txt, kind });
  if (activity.length > 120) activity.pop();
  renderActivity();
}
function renderActivity() {
  const latest = activity[0];
  $("act-latest").textContent = latest ? latest.txt : "Pronto para operar";
  const c = $("act-count");
  c.textContent = activity.length;
  c.hidden = activity.length === 0;
  const ul = $("act-list");
  ul.innerHTML = activity.slice(0, 60).map((a) => {
    const cls = a.kind === "ok" ? "a-ok" : a.kind === "err" ? "a-err"
      : a.kind === "work" ? "a-work" : "a-info";
    const ic = a.kind === "ok" ? "ok-circle" : a.kind === "err" ? "alert"
      : a.kind === "work" ? "loader" : "zap";
    return `<li class="${cls}">${icon(ic)}<span class="a-time">${a.time}</span><span class="a-txt">${a.txt}</span></li>`;
  }).join("");
}
$("act-toggle").onclick = () => {
  const a = $("activity");
  a.classList.toggle("collapsed");
  $("act-toggle").setAttribute("aria-expanded", String(!a.classList.contains("collapsed")));
};

/* ====================== slots ====================== */
function makeSlot(i) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.dataset.slot = i;
  node.querySelectorAll(".slot-n").forEach((el) => (el.textContent = String(i + 1).padStart(2, "0")));

  const stop = (fn) => (e) => { e.stopPropagation(); fn(e); };
  node.querySelector(".btn-print").addEventListener("click", stop(() => printOne(node.dataset.udid)));
  node.querySelector(".btn-pair").addEventListener("click", stop(() => pair(node.dataset.udid)));
  node.querySelector(".btn-more").addEventListener("click", stop(() => toggleMenu(node)));
  node.querySelector(".btn-cmd").addEventListener("click", stop(() => { showCmd(node.dataset.udid); closeMenus(); }));
  node.querySelector(".btn-copy").addEventListener("click", stop(() => copySerial(node)));
  node.querySelector(".btn-copy2").addEventListener("click", stop(() => { copySerial(node); closeMenus(); }));
  node.querySelector(".btn-restart").addEventListener("click", stop(() => { closeMenus(); powerOne(node.dataset.udid, "restart"); }));
  node.querySelector(".btn-power").addEventListener("click", stop(() => { closeMenus(); powerOne(node.dataset.udid, "shutdown"); }));

  const toggle = () => {
    if (!node.classList.contains("filled")) return;
    const u = node.dataset.udid;
    selected.has(u) ? selected.delete(u) : selected.add(u);
    syncSelection();
  };
  node.addEventListener("click", (e) => {
    if (e.target.closest("button, input, .slot-menu")) return;
    toggle();
  });
  node.addEventListener("keydown", (e) => {
    if ((e.key === " " || e.key === "Enter") && !e.target.closest("button")) { e.preventDefault(); toggle(); }
  });

  grid.appendChild(node);
  return node;
}
function ensureSlots(n) {
  while (grid.children.length < n) makeSlot(grid.children.length);
  while (grid.children.length > n && !grid.lastElementChild.classList.contains("filled")) {
    grid.lastElementChild.remove();
  }
}
function toggleMenu(node) {
  const m = node.querySelector(".slot-menu");
  const open = m.hidden;
  closeMenus();
  m.hidden = !open;
}
function closeMenus() {
  document.querySelectorAll(".slot-menu").forEach((m) => (m.hidden = true));
}
document.addEventListener("click", closeMenus);

function copySerial(node) {
  const s = node.querySelector(".dev-serial").textContent.trim();
  if (s && s !== "—") { navigator.clipboard.writeText(s); toast("Nº de série copiado", "ok", 1600); }
}

function fillSlot(node, dev, slotNo) {
  const wasNew = !node.classList.contains("filled");
  node.classList.add("filled");
  node.dataset.udid = dev.udid;
  slotOfUdid.set(dev.udid, slotNo);

  let st = dev.status || "lendo";
  if (st === "ok" && !dev.serial) st = "lendo";
  node.dataset.st = st;

  const job = jobState.get(dev.udid);
  if (job) node.dataset.job = job; else node.removeAttribute("data-job");

  const q = (s) => node.querySelector(s);
  const isPad = (dev.model || "").startsWith("iPad");

  // status pill text
  q(".sp-text").textContent = job === "printing" ? "Imprimindo"
    : job === "sent" ? "Enviada"
      : job === "fail" ? "Falhou"
        : st === "lendo" ? "Lendo"
          : st === "pareamento" ? "Confiar"
            : st === "erro" ? "Erro"
              : st === "desligando" ? "Desligando" : "Pronta";

  q(".dev-model").textContent = dev.model_name || dev.model || (st === "lendo" ? "Lendo dispositivo" : "Dispositivo");
  q(".dev-cap-badge").textContent = dev.capacity || "";

  const spec = [];
  if (dev.color_name) spec.push(dev.color_name);
  if (dev.ios) spec.push((isPad ? "iPadOS " : "iOS ") + dev.ios);
  q(".dev-spec").innerHTML = spec.map((s) => `<span>${s}</span>`).join("");

  q(".dev-serial").textContent = dev.serial || (st === "lendo" ? "lendo…" : "—");

  const reading = st === "lendo";
  const h = dev.battery_health;
  const batt = q(".batt");
  batt.className = "batt " + (reading || h === null || h === undefined ? "b-na" : battTier(h));
  const lvl = reading || h === null || h === undefined ? 2.5 : Math.max(2.5, 19 * h / 100);
  q(".bt-lvl").setAttribute("width", lvl.toFixed(1));
  q(".batt-pct").textContent = reading ? "··"
    : (h === null || h === undefined ? "N/D" : h + "%");
  q(".m-cc").textContent = reading ? "—"
    : (dev.cycle_count === null || dev.cycle_count === undefined ? "N/D" : dev.cycle_count);

  q(".dev-note").textContent = (dev.notes || []).join(" ");

  const needPair = dev.status === "pareamento" || dev.paired === false;
  q(".btn-pair").classList.toggle("hidden", !needPair);
  q(".btn-print").disabled = !dev.serial || busyU.has(dev.udid);

  node.classList.toggle("selected", selected.has(dev.udid));

  if (wasNew && dev.serial) {
    node.classList.add("just-in");
    node.addEventListener("animationend", () => node.classList.remove("just-in"), { once: true });
  }
}

function clearSlot(node) {
  if (node.classList.contains("filled")) {
    const u = node.dataset.udid;
    if (u) { selected.delete(u); jobState.delete(u); }
  }
  node.classList.remove("filled", "selected", "just-in");
  node.removeAttribute("data-st");
  node.removeAttribute("data-job");
  delete node.dataset.udid;
}

function slotOf(udid) {
  for (const n of grid.children) if (n.dataset.udid === udid) return n;
  return null;
}

/* ====================== seleção / KPIs ====================== */
function connectedCount() {
  return [...devById.values()].filter((d) => d.serial).length;
}
function syncSelection() {
  for (const node of grid.children) {
    const on = node.classList.contains("filled") && selected.has(node.dataset.udid);
    node.classList.toggle("selected", on);
    const lbl = node.querySelector(".sel-label");
    if (lbl) lbl.textContent = on ? "Selecionado" : "Selecionar";
  }
  const conn = connectedCount();
  $("n-sel").textContent = selected.size;
  $("n-conn").textContent = conn;
  $("kpi-sel").textContent = selected.size;
  $("kpi-dev").textContent = `${devById.size} / ${SLOTS}`;
  $("kpi-print").textContent = printCount;
  $("print-sel").disabled = selected.size === 0 || busyU.size > 0;
  $("print-all").disabled = conn === 0 || busyU.size > 0;
  $("power-all").disabled = conn === 0 || busyU.size > 0;
}

function setPrinter(name, status, langEff) {
  printerStatus = status || "offline";
  $("kpi-printer-name").textContent = name || "não configurada";
  $("kpi-printer").dataset.s = printerStatus;
  const txt = printerStatus === "online" ? "Conectada"
    : printerStatus === "busy" ? "Ocupada" : "Desconectada";
  $("pstat-txt").textContent = langEff ? `${txt} · ${langEff.toUpperCase()}` : txt;
  const sys = $("sys-status");
  sys.className = printerStatus === "offline" ? "brand-sub down"
    : printerStatus === "busy" ? "brand-sub warn" : "brand-sub";
  const sysTxt = printerStatus === "offline" ? "Impressora desconectada"
    : printerStatus === "busy" ? "Impressora ocupada" : "Sistema online";
  sys.innerHTML = `<i class="pip"></i> ${sysTxt}`;
}

/* ====================== polling ====================== */
async function poll() {
  let data;
  try { data = await api("/api/devices"); } catch { return; }

  if (data.ui && typeof data.ui.slots === "number") SLOTS = data.ui.slots;
  window.serverUi = data.ui || {};
  window.labelCfg = data.label || window.labelCfg || {};
  window.langEff = data.language_effective || "";
  window.printerName = data.printer || "";

  setPrinter(data.printer, data.printer_status, data.language_effective);

  const secs = data.last_scan ? Math.max(0, Math.round(Date.now() / 1000 - data.last_scan)) : null;
  $("last-read").innerHTML = icon("clock") + (secs === null ? " —" : ` há ${secs}s`);

  const devs = data.devices || [];
  const now = new Map(devs.map((d) => [d.udid, d]));

  // transições: desconexão
  for (const u of devById.keys()) {
    if (!now.has(u)) {
      const n = slotOfUdid.get(u) || "?";
      logAct(`Slot ${String(n).padStart(2, "0")} · dispositivo desconectado`, "info");
      slotOfUdid.delete(u); prevStatus.delete(u); seenUdids.delete(u);
    }
  }
  devById = now;
  for (const u of [...selected]) if (!devById.has(u)) selected.delete(u);

  ensureSlots(Math.max(SLOTS, devs.length));
  for (let i = 0; i < grid.children.length; i++) {
    const dev = devs[i];
    if (dev) {
      fillSlot(grid.children[i], dev, i + 1);
      // transições: conexão + leitura concluída
      const prev = prevStatus.get(dev.udid);
      if (!seenUdids.has(dev.udid)) {
        seenUdids.add(dev.udid);
        logAct(`Slot ${String(i + 1).padStart(2, "0")} · dispositivo conectado`, "work");
      } else if (prev === "lendo" && dev.status === "ok" && dev.serial) {
        logAct(`Slot ${String(i + 1).padStart(2, "0")} · ${dev.model_name || "leitura"} — pronta`, "ok");
        soundReady();
      } else if (prev !== "erro" && dev.status === "erro") {
        logAct(`Slot ${String(i + 1).padStart(2, "0")} · falha na leitura`, "err");
        soundError();
      } else if (prev !== "pareamento" && dev.status === "pareamento") {
        soundError();
      }
      prevStatus.set(dev.udid, dev.status);
    } else {
      clearSlot(grid.children[i]);
    }
  }
  syncSelection();
}
function startPolling() {
  stopPolling();
  if (autoUpdate) pollTimer = setInterval(poll, Math.max(1000, intervalSec * 1000));
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

/* ====================== impressão ====================== */
function setJob(udid, state) {
  const node = slotOf(udid);
  if (state) jobState.set(udid, state); else jobState.delete(udid);
  if (node) {
    if (state) node.dataset.job = state; else node.removeAttribute("data-job");
    const t = node.querySelector(".sp-text");
    if (t) {
      const st = node.dataset.st;
      t.textContent = state === "printing" ? "Imprimindo"
        : state === "sent" ? "Enviada"
          : state === "fail" ? "Falhou"
            : st === "lendo" ? "Lendo" : st === "pareamento" ? "Confiar"
              : st === "erro" ? "Erro" : "Pronta";
    }
    node.querySelector(".btn-print").disabled = state === "printing" || busyU.has(udid);
  }
  clearTimeout(jobTimers.get(udid));
  if (state === "sent" || state === "fail") {
    jobTimers.set(udid, setTimeout(() => setJob(udid, null), 4500));
  }
}

async function printOne(udid) {
  if (!udid || busyU.has(udid)) return;
  const n = slotOfUdid.get(udid) || "?";
  const tag = `Slot ${String(n).padStart(2, "0")}`;
  busyU.add(udid); setJob(udid, "printing"); syncSelection();
  logAct(`${tag} · enviando etiqueta…`, "work");
  try {
    const r = await api("/api/print", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udid, copies: copiesVal() }),
    });
    if (r.ok) {
      printCount++; setJob(udid, "sent");
      logAct(`${tag} · etiqueta enviada`, "ok"); toast(`${tag} · etiqueta enviada`, "ok", 1800);
    } else {
      setJob(udid, "fail"); logAct(`${tag} · falha: ${r.msg || "erro"}`, "err");
      toast(`${tag} · falha na impressão`, "err", 3500);
    }
  } catch (e) {
    setJob(udid, "fail"); logAct(`${tag} · erro: ${e}`, "err"); toast("Falha na impressão", "err");
  } finally {
    busyU.delete(udid); syncSelection();
  }
}

async function printMany(udids) {
  udids = udids.filter((u) => devById.get(u)?.serial && !busyU.has(u));
  if (!udids.length) return;
  udids.forEach((u) => { busyU.add(u); setJob(u, "printing"); });
  syncSelection();
  logAct(`Impressão em lote · ${udids.length} etiqueta(s)…`, "work");
  try {
    const r = await api("/api/print-bulk", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udids, copies: copiesVal() }),
    });
    let ok = 0;
    for (const res of r.results || []) {
      const n = slotOfUdid.get(res.udid) || "?";
      const tag = `Slot ${String(n).padStart(2, "0")}`;
      if (res.ok) { ok++; printCount++; setJob(res.udid, "sent"); logAct(`${tag} · etiqueta enviada`, "ok"); }
      else { setJob(res.udid, "fail"); logAct(`${tag} · falha: ${res.msg || "erro"}`, "err"); }
    }
    const total = (r.results || []).length;
    toast(`${ok}/${total} etiqueta(s) enviada(s)`, ok === total ? "ok" : "err", 3000);
  } catch (e) {
    toast("Falha na impressão em lote", "err");
    udids.forEach((u) => setJob(u, "fail"));
  } finally {
    udids.forEach((u) => busyU.delete(u));
    syncSelection();
  }
}

async function powerOne(udid, action) {
  if (!udid) return;
  const n = slotOfUdid.get(udid) || "?";
  const tag = `Slot ${String(n).padStart(2, "0")}`;
  const verbo = action === "restart" ? "Reiniciar" : "Desligar";
  logAct(`${tag} · ${verbo.toLowerCase()}ando…`, "work");
  try {
    const r = await api("/api/power", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udid, action }),
    });
    if (r.ok) { toast(`${tag} · ${verbo.toLowerCase()} enviado`, "ok"); logAct(`${tag} · ${verbo.toLowerCase()} ok`, "ok"); }
    else { toast(`${tag} · ${r.msg || "falhou"}`, "err", 4000); logAct(`${tag} · falha ao ${verbo.toLowerCase()}: ${r.msg || ""}`, "err"); }
  } catch (e) { toast("Falha ao " + verbo.toLowerCase(), "err"); }
  poll();
}

async function pair(udid) {
  const n = slotOfUdid.get(udid) || "?";
  logAct(`Slot ${String(n).padStart(2, "0")} · pareando (confirme no aparelho)…`, "work");
  const r = await api("/api/pair", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ udid }),
  });
  toast(r.msg || (r.ok ? "Pareado" : "Não pareou"), r.ok ? "ok" : "err");
  poll();
}

const cmdDlg = $("cmd-dlg");
async function showCmd(udid) {
  if (!udid) return;
  const txt = await api(`/api/label?udid=${encodeURIComponent(udid)}&copies=${copiesVal()}`);
  $("cmd-text").textContent = typeof txt === "string" ? txt : JSON.stringify(txt, null, 2);
  cmdDlg.showModal();
}
$("cmd-close").onclick = () => cmdDlg.close();
$("cmd-copy").onclick = () => { navigator.clipboard.writeText($("cmd-text").textContent); toast("Comando copiado", "ok", 1500); };

/* ====================== toolbar ====================== */
$("btn-refresh").onclick = async () => {
  logAct("Releitura manual solicitada", "work");
  await api("/api/refresh", { method: "POST" }); poll();
};
$("sel-all").onclick = () => { for (const d of devById.values()) if (d.serial) selected.add(d.udid); syncSelection(); };
$("sel-none").onclick = () => { selected.clear(); syncSelection(); };
$("print-sel").onclick = () => printMany([...selected]);
$("print-all").onclick = () => printMany([...devById.values()].filter((d) => d.serial).map((d) => d.udid));

$("power-all").onclick = async () => {
  const btn = $("power-all");
  const conn = [...devById.values()].filter((d) => d.serial);
  if (!conn.length) { toast("Nenhum aparelho conectado", "info", 1800); return; }
  if (btn.disabled) return;

  btn.disabled = true;
  $("bulk-msg").textContent = `desligando ${conn.length}…`;
  logAct(`Desligando todos (${conn.length})…`, "work");
  try {
    const r = await api("/api/power-all", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "shutdown" }),
    });
    const ok = (r.results || []).filter((x) => x.ok).length;
    $("bulk-msg").textContent = `${ok}/${(r.results || []).length} desligado(s)`;
    for (const x of r.results || []) if (!x.ok) {
      const n = slotOfUdid.get(x.udid) || "?";
      logAct(`Slot ${String(n).padStart(2, "0")} · não desligou: ${x.msg || ""}`, "err");
    }
    toast(`${ok} aparelho(s) desligado(s)`, ok ? "ok" : "err");
  } catch (e) { $("bulk-msg").textContent = "erro: " + e; }
  btn.disabled = false;
  poll();
};
document.querySelectorAll(".stepper button[data-step]").forEach((b) => {
  b.onclick = () => {
    const i = $("copies");
    i.value = Math.max(1, Math.min(50, (parseInt(i.value || "1", 10) || 1) + Number(b.dataset.step)));
  };
});

/* ====================== tema / escala ====================== */
function applyTheme(t) {
  const r = document.documentElement;
  if (t === "light" || t === "dark") r.dataset.theme = t;
  else r.removeAttribute("data-theme");
}
function applyUiScale(pct) {
  document.documentElement.style.setProperty("--ui-scale", (Math.max(70, Math.min(140, pct)) / 100));
}
let themeVal = LS.get("theme", null);
let uiScaleVal = LS.get("uiscale", null);
applyTheme(themeVal || "system");
applyUiScale(uiScaleVal || 100);

/* ====================== configurações ====================== */
const cfg = $("cfg-dlg");

function segSet(id, v) {
  document.querySelectorAll(`#${id} button`).forEach((b) => b.classList.toggle("active", b.dataset.v === String(v)));
}

async function loadPrinters(want) {
  const r = await api("/api/printers");
  const sel = $("cf-printer");
  sel.innerHTML = "";
  for (const name of r.printers || []) {
    const o = document.createElement("option");
    o.value = o.textContent = name;
    sel.appendChild(o);
  }
  const target = want || r.current || "";
  if (target && ![...sel.options].some((o) => o.value === target)) {
    const o = document.createElement("option");
    o.textContent = target + "  (não encontrada)";
    o.value = "__raw__"; o.dataset.raw = target;
    sel.appendChild(o);
  }
  sel.value = target && [...sel.options].some((o) => o.value === target) ? target : (sel.options[0] ? sel.options[0].value : "");
  return r;
}
function refreshLangEff() {
  $("cf-lang-eff").textContent = $("cf-lang").value === "auto" && window.langEff
    ? `Detectado: ${window.langEff.toUpperCase()}` : "";
}

async function openCfg() {
  const L = window.labelCfg || {};
  const ui = window.serverUi || {};
  $("cf-dark").value = L.darkness ?? 10;
  $("cf-flip").checked = L.flip_180 !== false;
  $("cf-bold").checked = L.text_bold === true;
  $("cf-color").checked = L.show_color !== false;
  $("cf-labels").checked = L.bottom_labels !== false;
  $("cf-scale").value = Math.round((L.element_scale ?? 0.8) * 100);
  $("cf-ox").value = L.offset_x ?? 0;
  $("cf-oy").value = L.offset_y ?? 0;
  $("cf-copies").value = L.copies_default ?? 1;
  $("cf-h-mm").value = L.height_mm ?? 40;
  $("cf-w-mm").value = L.width_mm ?? 60;
  $("cf-slots").value = ui.slots ?? SLOTS;
  $("cf-auto").checked = autoUpdate;
  $("cf-interval").value = intervalSec;
  $("cf-autoupd").checked = autoUpd;
  $("cf-sound").checked = soundOn;
  $("cf-lang").value = L.language || "auto";
  segSet("cf-theme", themeVal || "system");
  segSet("cf-uiscale", uiScaleVal || 100);
  $("cf-msg").textContent = "";
  cfg.showModal();
  showTab("printer");
  await loadPrinters();
  refreshLangEff();
}

function showTab(name) {
  document.querySelectorAll(".cfg-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".cfg-scroll section").forEach((s) => (s.hidden = s.dataset.panel !== name));
}
document.querySelectorAll(".cfg-tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

function cfgPayload() {
  const sel = $("cf-printer");
  const opt = sel.selectedOptions[0];
  return {
    printer_name: (opt && opt.dataset.raw) || sel.value,
    language: $("cf-lang").value,
    darkness: Math.max(0, Math.min(15, parseInt($("cf-dark").value || "10", 10))),
    flip_180: $("cf-flip").checked,
    text_bold: $("cf-bold").checked,
    show_color: $("cf-color").checked,
    bottom_labels: $("cf-labels").checked,
    element_scale: Math.max(0.4, Math.min(1.5, (parseInt($("cf-scale").value || "80", 10) / 100))),
    offset_x: parseInt($("cf-ox").value || "0", 10),
    offset_y: parseInt($("cf-oy").value || "0", 10),
    copies_default: Math.max(1, Math.min(50, parseInt($("cf-copies").value || "1", 10))),
    height_mm: Math.max(8, Math.min(200, parseFloat($("cf-h-mm").value) || 40)),
    width_mm: Math.max(10, Math.min(200, parseFloat($("cf-w-mm").value) || 60)),
    ui: {
      slots: Math.max(2, Math.min(24, parseInt($("cf-slots").value || "10", 10))),
      theme: themeVal || "system",
      scale: uiScaleVal || 100,
    },
  };
}

async function saveCfg(silent) {
  autoUpdate = $("cf-auto").checked; LS.set("auto", autoUpdate);
  intervalSec = Math.max(1, Math.min(15, parseInt($("cf-interval").value || "3", 10)));
  LS.set("interval", intervalSec);
  autoUpd = $("cf-autoupd").checked; LS.set("autoupd", autoUpd);
  if (autoUpd && verInfo && verInfo.update_available) scheduleAutoUpdate();
  soundOn = $("cf-sound").checked; LS.set("sound", soundOn);
  startPolling();

  const r = await api("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfgPayload()),
  });
  if (r.label) window.labelCfg = r.label;
  if (r.ui) { window.serverUi = r.ui; if (typeof r.ui.slots === "number") SLOTS = r.ui.slots; }
  if (r.language_effective) window.langEff = r.language_effective;
  if (!silent) { $("cf-msg").textContent = r.ok ? "Configurações salvas ✓" : "Erro ao salvar"; logAct("Configurações salvas", "info"); }
  refreshLangEff();
  poll();
  return r;
}

$("btn-gear").onclick = openCfg;
$("kpi-printer").onclick = () => { openCfg(); };
$("cf-close").onclick = () => cfg.close();
$("cf-save").onclick = () => saveCfg(false);
$("cf-printer-reload").onclick = () => loadPrinters($("cf-printer").value);
$("cf-lang").onchange = refreshLangEff;
$("cf-test").onclick = async () => {
  $("cf-msg").textContent = "Salvando e imprimindo teste…";
  await saveCfg(true);
  const r = await api("/api/test-print", { method: "POST" });
  $("cf-msg").textContent = r.ok ? "Etiqueta de teste enviada ✓" : "Erro: " + (r.msg || "");
  logAct("Etiqueta de teste " + (r.ok ? "enviada" : "falhou"), r.ok ? "ok" : "err");
};
document.querySelectorAll("#cf-theme button").forEach((b) => (b.onclick = () => {
  themeVal = b.dataset.v; LS.set("theme", themeVal); applyTheme(themeVal); segSet("cf-theme", themeVal);
}));
document.querySelectorAll("#cf-uiscale button").forEach((b) => (b.onclick = () => {
  uiScaleVal = Number(b.dataset.v); LS.set("uiscale", uiScaleVal); applyUiScale(uiScaleVal); segSet("cf-uiscale", uiScaleVal);
}));
$("cf-sound-test").onclick = (e) => { e.stopPropagation(); const s = soundOn; soundOn = true; soundReady(); soundOn = s; };
$("cf-testnotif").onclick = () => { cfg.close(); demoNotif(); };

/* ====================== atualização ====================== */
let verInfo = null;
let updating = false;
let autoUpd = LS.get("autoupd", true);
let autoUpdTimer = null;
let notifTimer = null;
let notifDemo = false;

function bellState() {
  const bell = $("btn-bell");
  const up = notifDemo || (verInfo && verInfo.update_available);
  bell.classList.toggle("has-update", !!up);
  bell.querySelector(".bell-dot").hidden = !up;
  const v = verInfo || {};
  bell.title = up
    ? `Atualização ${notifDemo ? "(exemplo)" : v.latest} disponível — clique`
    : `NS Label v${v.current || "—"}${v.checked === false ? " · sem internet" : " · atualizado"}`;
}

async function checkVersion(force) {
  try {
    verInfo = await api("/api/version" + (force ? "?force=1" : ""));
  } catch { return null; }
  const cur = verInfo.current || "—";
  $("cf-ver").textContent = verInfo.update_available
    ? `Versão ${cur} · nova: ${verInfo.latest}`
    : `Versão ${cur} · atualizado` + (verInfo.checked ? "" : " (sem internet?)");
  if (!notifDemo) bellState();

  clearTimeout(notifTimer);
  if (verInfo.update_available) {
    notifyUpdate(true);
    scheduleAutoUpdate();
  }
  return verInfo;
}

function notifyUpdate(first) {
  if (!verInfo || !verInfo.update_available) return;
  const seen = sessionStorage.getItem("nslabel.updSeen");
  if (first && seen === verInfo.latest) { scheduleRenotify(); return; }
  sessionStorage.setItem("nslabel.updSeen", verInfo.latest);
  toast(`🔔 Nova versão ${verInfo.latest} disponível`, "info", 7000);
  logAct(`Atualização ${verInfo.latest} disponível — clique no sino`, "info");
  scheduleRenotify();
}
function scheduleRenotify() {
  clearTimeout(notifTimer);
  // re-avisa a cada 10 min enquanto pendente (ex.: auto-update desligado)
  notifTimer = setTimeout(() => {
    if (verInfo && verInfo.update_available && !updating) {
      toast(`🔔 Atualização ${verInfo.latest} pendente`, "info", 6000);
      scheduleRenotify();
    }
  }, 10 * 60 * 1000);
}

function scheduleAutoUpdate() {
  if (!autoUpd || updating || autoUpdTimer) return;
  logAct(`Atualização automática para ${verInfo.latest} em ~20s…`, "info");
  toast(`Atualizando para ${verInfo.latest} em instantes — clique no sino p/ ver as novidades`, "info", 8000);
  autoUpdTimer = setTimeout(tryAutoUpdate, 20000);
}
function tryAutoUpdate() {
  autoUpdTimer = null;
  if (!autoUpd || updating || !verInfo || !verInfo.update_available) return;
  if (busyU.size > 0) {                 // nao interrompe impressao
    autoUpdTimer = setTimeout(tryAutoUpdate, 8000);
    return;
  }
  toast(`Atualizando para ${verInfo.latest}…`, "info", 4000);
  runUpdate();
}

// mostra como fica um aviso de atualização (para o operador ver o sino vermelho)
function demoNotif() {
  notifDemo = true;
  bellState();
  toast("🔔 Exemplo: nova versão disponível (é assim que avisa)", "info", 5000);
  logAct("Teste de aviso de atualização", "info");
  setTimeout(() => { notifDemo = false; bellState(); }, 15000);
}

const updDlg = $("upd-dlg");
$("btn-bell").onclick = () => {
  if (notifDemo) { toast("🔔 Exemplo de aviso (Config → Interface para testar de novo)", "info", 3000); return; }
  if (!verInfo || !verInfo.update_available) {
    toast(`Você já está na versão mais recente (v${(verInfo && verInfo.current) || "—"})`, "ok", 2500);
    return;
  }
  clearTimeout(autoUpdTimer); autoUpdTimer = null;   // pausa o auto enquanto a janela ta aberta
  $("upd-from").textContent = verInfo.current;
  $("upd-to").textContent = verInfo.latest;
  $("upd-notes").textContent = verInfo.notes || "";
  updDlg.showModal();
};
$("upd-close").onclick = () => { updDlg.close(); scheduleAutoUpdate(); };
$("upd-later").onclick = () => { updDlg.close(); scheduleAutoUpdate(); };
$("upd-go").onclick = () => { updDlg.close(); runUpdate(); };

$("cf-check").onclick = async () => {
  $("cf-ver").textContent = "verificando…";
  const v = await checkVersion(true);
  if (v && v.update_available) { toast(`Nova versão ${v.latest} disponível`, "info"); return; }
  if (confirm("Você já está na versão mais recente.\nReinstalar mesmo assim? (baixa e troca os arquivos de novo)")) {
    cfg.close();
    runUpdate(true);
  }
};

async function runUpdate(reinstall) {
  if (updating) return;
  updating = true;
  clearTimeout(autoUpdTimer); autoUpdTimer = null;
  $("updating").classList.remove("hidden");
  $("updating-txt").textContent = reinstall ? "Reinstalando…" : "Baixando atualização…";
  stopPolling();
  let r;
  try {
    r = await api("/api/update", { method: "POST" });
  } catch { r = { ok: false, msg: "sem resposta" }; }
  if (!r.ok) {
    $("updating-txt").textContent = "Falha: " + (r.msg || "erro");
    logAct("Atualização falhou: " + (r.msg || ""), "err");
    setTimeout(() => { $("updating").classList.add("hidden"); updating = false; startPolling(); }, 5000);
    return;
  }
  $("updating-txt").textContent = "Instalando e reiniciando…";
  waitForRestart(verInfo ? verInfo.current : null);
}

async function waitForRestart(oldVer) {
  const started = Date.now();
  let sawDown = false;
  const tick = async () => {
    if (Date.now() - started > 120000) {
      $("updating-txt").textContent = "Demorou mais que o esperado — recarregue a página (F5).";
      return;
    }
    try {
      const v = await api("/api/version");
      if (v && v.current && (v.current !== oldVer || sawDown)) {
        $("updating-txt").textContent = "Concluído — recarregando…";
        setTimeout(() => location.reload(), 700);
        return;
      }
    } catch { sawDown = true; }
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 4000);
}

/* ====================== start ====================== */
ensureSlots(SLOTS);
renderActivity();
poll();
startPolling();
checkVersion();
setInterval(() => checkVersion(), 20 * 60 * 1000);
