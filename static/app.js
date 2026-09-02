"use strict";

const SLOTS = 10;                       // nº de caixas fixas
const grid = document.getElementById("grid");
const tpl = document.getElementById("slot-tpl");
const selected = new Set();             // udids marcados
let devicesById = new Map();
let busy = new Set();

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function fmt(v, suf = "") {
  return v === null || v === undefined ? "—" : v + suf;
}

/* ---------- render ---------- */

function makeSlot(i) {
  const node = tpl.content.firstElementChild.cloneNode(true);
  node.dataset.slot = i;
  node.querySelector(".slot-n").textContent = "Slot " + (i + 1);
  node.querySelector(".btn-print").addEventListener("click", (e) => {
    e.stopPropagation();
    printOne(node.dataset.udid);
  });
  node.querySelector(".btn-pair").addEventListener("click", (e) => {
    e.stopPropagation();
    pair(node.dataset.udid);
  });
  node.querySelector(".btn-cmd").addEventListener("click", (e) => {
    e.stopPropagation();
    showCmd(node.dataset.udid);
  });
  node.addEventListener("click", () => {
    if (!node.classList.contains("filled")) return;
    const u = node.dataset.udid;
    selected.has(u) ? selected.delete(u) : selected.add(u);
    syncSelection();
  });
  grid.appendChild(node);
  return node;
}

function ensureSlots(n) {
  while (grid.children.length < n) makeSlot(grid.children.length);
}

function fillSlot(node, dev) {
  node.classList.add("filled");
  node.dataset.udid = dev.udid;

  let st = dev.status || "lendo";
  if (st === "ok" && !dev.serial) st = "lendo";     // ainda sem dados => lendo
  node.dataset.st = st;                              // lendo | ok | pareamento | erro

  const q = (s) => node.querySelector(s);
  const modelTxt = dev.model_name || dev.model || (dev.status === "lendo" ? "lendo…" : "aparelho");
  q(".dev-model").textContent = modelTxt;
  q(".dev-cap").textContent = dev.capacity || "";
  q(".dev-color").textContent = dev.color_name || "";
  q(".dev-ios").textContent = dev.ios
    ? ((dev.model || "").startsWith("iPad") ? "iPadOS " : "iOS ") + dev.ios : "";
  q(".dev-serial").textContent = dev.serial || (dev.status === "lendo" ? "lendo…" : "—");
  q(".m-bt").textContent = fmt(dev.battery_health, "%");
  q(".m-cc").textContent = fmt(dev.cycle_count);
  q(".m-charge").textContent = fmt(dev.battery_charge, "%");
  q(".dev-note").textContent = (dev.notes || []).join(" ");

  const needPair = dev.status === "pareamento" || dev.paired === false;
  q(".btn-pair").classList.toggle("hidden", !needPair);
  q(".btn-print").disabled = !dev.serial || busy.has(dev.udid);
}

function clearSlot(node) {
  node.classList.remove("filled", "selected");
  delete node.dataset.udid;
  delete node.dataset.st;
  node.querySelector(".print-msg").textContent = "";
}

function syncSelection() {
  for (const node of grid.children) {
    const u = node.dataset.udid;
    node.classList.toggle("selected", !!u && selected.has(u));
  }
  $("n-sel").textContent = selected.size;
  const conn = [...devicesById.values()].filter((d) => d.serial).length;
  $("n-conn").textContent = conn;
  $("print-sel").disabled = selected.size === 0 || busy.size > 0;
  $("print-all").disabled = conn === 0 || busy.size > 0;
}

/* ---------- polling ---------- */

async function poll() {
  let data;
  try { data = await api("/api/devices"); } catch { return; }

  const langEff = data.language_effective ? ` · ${data.language_effective.toUpperCase()}` : "";
  $("printer").textContent = "impressora: " + (data.printer || "—") + langEff;
  const secs = data.last_scan
    ? Math.max(0, Math.round(Date.now() / 1000 - data.last_scan)) : null;
  $("scan").textContent = secs === null ? "aguardando leitura…"
    : "última leitura há " + secs + "s";

  if (data.label) {
    window.labelCfg = data.label;
    window.printerName = data.printer || "";
    window.langEff = data.language_effective || "";
  }

  const devs = data.devices || [];
  devicesById = new Map(devs.map((d) => [d.udid, d]));

  // limpa seleção de quem sumiu
  for (const u of [...selected]) if (!devicesById.has(u)) selected.delete(u);

  ensureSlots(Math.max(SLOTS, devs.length));
  for (let i = 0; i < grid.children.length; i++) {
    const node = grid.children[i];
    const dev = devs[i];
    if (dev) fillSlot(node, dev);
    else clearSlot(node);
  }
  syncSelection();
}

/* ---------- ações ---------- */

function setMsg(node, text, kind) {
  const el = node.querySelector(".print-msg");
  el.className = "print-msg" + (kind ? " " + kind : "");
  el.textContent = text;
}

function slotOf(udid) {
  for (const n of grid.children) if (n.dataset.udid === udid) return n;
  return null;
}

async function printOne(udid) {
  const node = slotOf(udid);
  if (!node) return;
  busy.add(udid); syncSelection();
  setMsg(node, "enviando…");
  try {
    const r = await api("/api/print", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udid, copies: copiesVal() }),
    });
    setMsg(node, r.ok ? "✓ enviada" : "erro: " + (r.msg || ""), r.ok ? "ok" : "err");
  } catch (e) {
    setMsg(node, "erro: " + e, "err");
  } finally {
    busy.delete(udid); syncSelection();
  }
}

async function printMany(udids) {
  if (!udids.length) return;
  udids.forEach((u) => { busy.add(u); const n = slotOf(u); if (n) setMsg(n, "na fila…"); });
  syncSelection();
  $("bulk-msg").textContent = `imprimindo ${udids.length}…`;
  try {
    const r = await api("/api/print-bulk", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ udids, copies: copiesVal() }),
    });
    let ok = 0;
    for (const res of r.results || []) {
      const n = slotOf(res.udid);
      if (n) setMsg(n, res.ok ? "✓ enviada" : "erro: " + (res.msg || ""), res.ok ? "ok" : "err");
      if (res.ok) ok++;
    }
    $("bulk-msg").textContent = `pronto: ${ok}/${(r.results || []).length} enviadas`;
  } catch (e) {
    $("bulk-msg").textContent = "erro: " + e;
  } finally {
    udids.forEach((u) => busy.delete(u));
    syncSelection();
  }
}

async function pair(udid) {
  const node = slotOf(udid);
  if (node) setMsg(node, "confirme CONFIAR no aparelho…");
  const r = await api("/api/pair", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ udid }),
  });
  if (node) setMsg(node, r.msg || (r.ok ? "pareado" : "não pareou"), r.ok ? "ok" : "err");
  poll();
}

const dlg = $("cmd-dlg");
async function showCmd(udid) {
  const txt = await api(`/api/label?udid=${encodeURIComponent(udid)}&copies=${copiesVal()}`);
  $("cmd-text").textContent = txt;
  dlg.showModal();
}
$("cmd-close").onclick = () => dlg.close();
$("cmd-copy").onclick = () => navigator.clipboard.writeText($("cmd-text").textContent);

function copiesVal() {
  return Math.max(1, Math.min(50, parseInt($("copies").value || "1", 10)));
}

/* ---------- botões ---------- */

$("btn-refresh").onclick = async () => { await api("/api/refresh", { method: "POST" }); poll(); };

$("sel-all").onclick = () => {
  for (const d of devicesById.values()) if (d.serial) selected.add(d.udid);
  syncSelection();
};
$("sel-none").onclick = () => { selected.clear(); syncSelection(); };

$("print-sel").onclick = () => printMany([...selected].filter((u) => devicesById.get(u)?.serial));
$("print-all").onclick = () =>
  printMany([...devicesById.values()].filter((d) => d.serial).map((d) => d.udid));

/* ---------- engrenagem / configurações ---------- */

const cfg = $("cfg-dlg");

async function loadPrinters(selectName) {
  const r = await api("/api/printers");
  const sel = $("cf-printer");
  sel.innerHTML = "";
  for (const name of r.printers || []) {
    const o = document.createElement("option");
    o.value = o.textContent = name;
    sel.appendChild(o);
  }
  const want = selectName || r.current || "";
  if (want && ![...sel.options].some((o) => o.value === want)) {
    const o = document.createElement("option");
    o.value = o.textContent = want + "  (não encontrada)";
    o.dataset.raw = want; sel.appendChild(o);
  }
  sel.value = want;
  return r;
}

function refreshLangEff() {
  $("cf-lang-eff").textContent =
    $("cf-lang").value === "auto" && window.langEff
      ? `→ usando ${window.langEff.toUpperCase()}` : "";
}

async function openCfg() {
  const L = window.labelCfg || {};
  $("cf-scale").value = Math.round((L.element_scale ?? 0.8) * 100);
  $("cf-ox").value = L.offset_x ?? 0;
  $("cf-oy").value = L.offset_y ?? 0;
  $("cf-dark").value = L.darkness ?? 10;
  $("cf-lang").value = L.language || "auto";
  $("cf-flip").checked = L.flip_180 !== false;
  $("cf-bold").checked = L.text_bold === true;
  $("cf-labels").checked = L.bottom_labels !== false;
  $("cf-color").checked = L.show_color !== false;
  $("cf-msg").textContent = "";
  cfg.showModal();
  await loadPrinters();
  refreshLangEff();
}

function cfgPayload() {
  const sel = $("cf-printer");
  const opt = sel.selectedOptions[0];
  return {
    printer_name: (opt && opt.dataset.raw) || sel.value,
    language: $("cf-lang").value,
    element_scale: Math.max(0.4, Math.min(1.5, (parseInt($("cf-scale").value || "80", 10) / 100))),
    offset_x: parseInt($("cf-ox").value || "0", 10),
    offset_y: parseInt($("cf-oy").value || "0", 10),
    darkness: Math.max(0, Math.min(15, parseInt($("cf-dark").value || "10", 10))),
    flip_180: $("cf-flip").checked,
    text_bold: $("cf-bold").checked,
    bottom_labels: $("cf-labels").checked,
    show_color: $("cf-color").checked,
  };
}

async function saveCfg() {
  const r = await api("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfgPayload()),
  });
  if (r.label) window.labelCfg = r.label;
  if (r.language_effective) window.langEff = r.language_effective;
  $("cf-msg").textContent = r.ok ? "salvo ✓" : "erro ao salvar";
  refreshLangEff();
  poll();
}

$("btn-gear").onclick = openCfg;
$("cf-save").onclick = saveCfg;
$("cf-printer-reload").onclick = () => loadPrinters($("cf-printer").value);
$("cf-lang").onchange = refreshLangEff;
$("cf-test").onclick = async () => {
  $("cf-msg").textContent = "salvando e imprimindo teste…";
  await api("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfgPayload()),
  });
  const r = await api("/api/test-print", { method: "POST" });
  $("cf-msg").textContent = r.ok ? "teste enviado" : "erro: " + (r.msg || "");
  poll();
};

/* ---------- start ---------- */
ensureSlots(SLOTS);
poll();
setInterval(poll, 2500);
