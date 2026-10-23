"use strict";

const $ = (id) => document.getElementById(id);
const els = {
  messages: $("messages"), welcome: $("welcome"), input: $("input"), composer: $("composer"),
  send: $("btn-send"), stop: $("btn-stop"), chips: $("chips"), fileInput: $("file-input"),
  dropzone: $("dropzone"), status: $("status-pill"), scene: $("scene"), sliceState: $("slice-state"),
  sliceBar: $("slice-bar"), sliceResult: $("slice-result"), files: $("files"), settings: $("settings"),
  settingsForm: $("settings-form"), settingsMsg: $("settings-msg"), keyHint: $("key-hint"),
  summaryLine: $("summary-line"), dropTarget: $("drop-target"),
};
let sceneSummary = "Слайсер: загрузка…";
let sliceSummary = "";
let firstBatchDone = false;

function renderSummary() {
  els.summaryLine.textContent = sceneSummary + (sliceSummary ? " · " + sliceSummary : "");
}

function updateSendState() {
  els.composer.classList.toggle("empty", !els.input.value.trim() && !attachments.length);
}

const TOOL_LABELS = {
  get_scene_info: ["🔎", "Состояние слайсера"], list_profiles: ["📋", "Список профилей"],
  set_profile: ["🎚", "Профиль качества"], create_profile: ["💾", "Новый профиль"],
  list_materials: ["🧵", "Список материалов"], set_material: ["🧵", "Материал"],
  recommend_materials: ["🧪", "Подбор материала по ТЗ"], material_properties: ["🧪", "Свойства материала"],
  get_settings: ["⚙", "Чтение настроек"], find_settings: ["⚙", "Поиск настроек"],
  set_settings: ["🛠", "Изменение настроек"], reset_settings: ["↺", "Сброс настроек"],
  set_print_mode: ["🌀", "Режим печати 3D/5D"], load_model: ["📦", "Загрузка модели"],
  list_objects: ["📦", "Объекты на столе"], analyze_model: ["📐", "Анализ геометрии"],
  orient_model: ["🧭", "Ориентация"], transform_model: ["↔", "Перемещение/поворот"],
  arrange_all: ["▦", "Авторасстановка"], delete_objects: ["🗑", "Удаление"],
  slice: ["🔪", "Слайсинг"], slice_status: ["⏱", "Статус слайсинга"],
  export_gcode: ["📄", "Экспорт G-code"], save_project: ["💾", "Сохранение 3MF"],
  validate_gcode: ["✅", "Проверка G-code"], set_extruder_enabled: ["🔌", "Экструдер вкл/выкл"],
  save_profile: ["💾", "Сохранение профиля"], compare_variants: ["⚖", "Сравнение вариантов"],
};
const MODE_LABELS = { classic: "3D", cylindrical: "5D Spiral", cylindrical_full: "5D" };

let lastEventId = 0;
let busy = false;
let typingEl = null;
const pendingTools = {};
const attachments = []; // {id, name, el, ready}

// ------------------------------------------------------------------ helpers
async function api(path, options = {}) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function inline(s) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
}

// Small markdown renderer: headings, lists, tables, code blocks, paragraphs.
function markdown(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  let html = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      html += "<pre><code>" + escapeHtml(code.join("\n")) + "</code></pre>";
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const row = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = row(line);
      i += 2;
      let body = "";
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        body += "<tr>" + row(lines[i]).map((c) => "<td>" + inline(c) + "</td>").join("") + "</tr>";
        i++;
      }
      html += "<table><thead><tr>" + head.map((c) => "<th>" + inline(c) + "</th>").join("") + "</tr></thead><tbody>" + body + "</tbody></table>";
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { html += "<h" + h[1].length + ">" + inline(h[2]) + "</h" + h[1].length + ">"; i++; continue; }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      let items = "";
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items += "<li>" + inline(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "")) + "</li>";
        i++;
      }
      html += ordered ? "<ol>" + items + "</ol>" : "<ul>" + items + "</ul>";
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*([-*•]|\d+[.)])\s+|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    html += "<p>" + para.map(inline).join("<br>") + "</p>";
  }
  return html;
}

function scrollDown() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function addMessage(kind, html) {
  els.welcome.classList.add("hidden");
  const div = document.createElement("div");
  div.className = "msg " + kind;
  div.innerHTML = html;
  els.messages.insertBefore(div, typingEl && typingEl.parentNode ? typingEl : null);
  scrollDown();
  return div;
}

function setTyping(on) {
  if (on && !typingEl) {
    typingEl = document.createElement("div");
    typingEl.className = "typing";
    typingEl.textContent = "Ассистент думает";
    els.messages.appendChild(typingEl);
    scrollDown();
  } else if (!on && typingEl) {
    typingEl.remove();
    typingEl = null;
  }
}

function setBusy(value) {
  busy = value;
  els.send.classList.toggle("hidden", value);
  els.stop.classList.toggle("hidden", !value);
  els.status.textContent = value ? "работает" : "готов";
  els.status.className = "pill " + (value ? "busy" : "idle");
  setTyping(value);
}

function summarizeArgs(args) {
  if (!args || !Object.keys(args).length) return "";
  return Object.entries(args).map(([k, v]) => k + "=" + (typeof v === "object" ? JSON.stringify(v) : v)).join(", ");
}

// ------------------------------------------------------------------ events
function handleEvent(ev) {
  switch (ev.type) {
    case "reset":
      els.messages.querySelectorAll(".msg, .tool").forEach((n) => n.remove());
      els.welcome.classList.remove("hidden");
      break;
    case "user_message": {
      const atts = (ev.attachments || []).map((a) => '<span class="att">📎 ' + escapeHtml(a.name) + "</span>").join("");
      addMessage("user", escapeHtml(ev.text || "") + (atts ? "<div>" + atts + "</div>" : ""));
      break;
    }
    case "assistant_message":
      addMessage("assistant", markdown(ev.text));
      break;
    case "assistant_note":
      addMessage("note", markdown(ev.text));
      break;
    case "warning":
      addMessage("warning", "⚠ " + escapeHtml(ev.text));
      break;
    case "error":
      addMessage("error", "Ошибка: " + escapeHtml(ev.text));
      els.status.className = "pill error";
      break;
    case "status":
      setBusy(ev.state !== "idle");
      if (ev.state === "idle") refreshState();
      break;
    case "tool_call": renderToolCall(ev); break;
    case "tool_result": renderToolResult(ev); break;
    case "slice_state":
      els.sliceState.textContent = { processing: "идёт слайсинг…", done: "готово", error: "ошибка", not_started: "не запускался" }[ev.state] || ev.state;
      if (ev.state === "processing") { els.sliceBar.style.width = "2%"; sliceSummary = "слайсинг…"; renderSummary(); }
      if (ev.state === "error") { sliceSummary = "ошибка слайсинга"; renderSummary(); }
      if (ev.state === "done") els.sliceBar.style.width = "100%";
      break;
    case "slice_progress":
      els.sliceBar.style.width = Math.max(2, Math.round(ev.progress * 100)) + "%";
      els.sliceState.textContent = "идёт слайсинг… " + Math.round(ev.progress * 100) + "%";
      sliceSummary = "слайсинг " + Math.round(ev.progress * 100) + "%"; renderSummary();
      break;
    case "slice_result": renderSliceResult(ev); break;
    case "open_settings": if (firstBatchDone) openSettings(); break;
  }
}

function renderToolCall(ev) {
  els.welcome.classList.add("hidden");
  const [ico, label] = TOOL_LABELS[ev.name] || ["🔧", ev.name];
  const det = document.createElement("details");
  det.className = "tool";
  det.innerHTML =
    '<summary><span class="ico">' + ico + '</span><span class="name">' + escapeHtml(label) + "</span>" +
    '<span class="args">' + escapeHtml(summarizeArgs(ev.arguments)) + "</span>" +
    (ev.source && ev.source !== "agent" ? '<span class="src">' + escapeHtml(ev.source) + "</span>" : "") +
    '<span class="st run">выполняется…</span></summary>' +
    "<pre>" + escapeHtml(ev.name + " " + JSON.stringify(ev.arguments || {}, null, 2)) + "</pre>";
  els.messages.insertBefore(det, typingEl && typingEl.parentNode ? typingEl : null);
  pendingTools[ev.id] = det;
  scrollDown();
}

function renderToolResult(ev) {
  const det = pendingTools[ev.call_id];
  if (!det) return;
  const st = det.querySelector(".st");
  st.className = "st " + (ev.is_error ? "err" : "ok");
  st.textContent = ev.is_error ? "ошибка" : "✓";
  det.classList.add(ev.is_error ? "err" : "ok");
  const pre = document.createElement("pre");
  pre.textContent = "→ " + JSON.stringify(ev.result, null, 2);
  det.appendChild(pre);
  if (ev.is_error) {
    det.open = true;
  }
  if (!ev.is_error && ev.result && ev.result.path) addFile(ev.name, ev.result.path);
  if (["set_print_mode", "set_material", "set_profile", "load_model", "orient_model", "transform_model", "delete_objects", "arrange_all", "set_settings"].includes(ev.name)) {
    refreshState();
  }
  delete pendingTools[ev.call_id];
}

function renderSliceResult(r) {
  els.sliceState.textContent = "готово (" + (r.backend || "") + ")";
  els.sliceBar.style.width = "100%";
  const rows = [
    ["Время печати", r.print_time],
    ["Материал", (r.material_total_g || 0) + " г; " + (r.material_length_m || []).join(" / ") + " м"],
    ["Слайсинг", (r.slicing_seconds || "?") + " с"],
  ];
  els.sliceResult.innerHTML = rows.map(([k, v]) => "<dt>" + k + "</dt><dd>" + escapeHtml(v) + "</dd>").join("");
  sliceSummary = (r.print_time || "") + (r.material_total_g != null ? " · " + r.material_total_g + " г" : "");
  renderSummary();
}

function addFile(kind, path) {
  if (els.files.querySelector(".muted")) els.files.innerHTML = "";
  const li = document.createElement("li");
  li.textContent = (kind === "save_project" ? "3MF: " : kind === "export_gcode" ? "G-code: " : "") + path;
  els.files.appendChild(li);
}

async function poll() {
  while (true) {
    try {
      const data = await api("/api/events?after=" + lastEventId);
      for (const ev of data.events) {
        lastEventId = Math.max(lastEventId, ev.id);
        handleEvent(ev);
      }
      firstBatchDone = true;
    } catch (e) {
      els.status.textContent = "нет связи";
      els.status.className = "pill error";
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
}

async function refreshState() {
  try {
    const { scene } = await api("/api/state");
    const objects = (scene.objects || []).map((o) => o.name + (o.size_mm ? " (" + o.size_mm.x + "×" + o.size_mm.y + "×" + o.size_mm.z + " мм)" : "")).join("<br>") || "—";
    const rows = [
      ["Принтер", scene.printer],
      ["Режим", (MODE_LABELS[scene.print_mode] || scene.print_mode) + (scene.five_axis ? " · база Ø" + scene.five_axis.cylindrical_mode_base_diameter + " мм" : "")],
      ["Профиль", scene.profile_name + (scene.quality_type ? " (" + scene.quality_type + ")" : "")],
      ["Материал", scene.material && scene.material.name],
      ["Модели", objects],
      ["Изменено", Object.keys(scene.changed_settings || {}).length + " настроек"],
    ];
    els.scene.innerHTML = rows.map(([k, v]) => "<dt>" + k + "</dt><dd>" + (k === "Модели" ? v : escapeHtml(v == null ? "—" : v)) + "</dd>").join("");
    sceneSummary = [MODE_LABELS[scene.print_mode] || scene.print_mode, scene.material && scene.material.name, scene.profile_name]
      .filter(Boolean).join(" · ") || "Слайсер";
    renderSummary();
  } catch (e) {
    els.scene.innerHTML = "<dt>Ошибка</dt><dd>" + escapeHtml(e.message) + "</dd>";
    sceneSummary = "Нет связи со слайсером";
    renderSummary();
  }
}

// ------------------------------------------------------------------ attachments
function renderChips() {
  els.chips.innerHTML = "";
  attachments.forEach((a, idx) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (a.ready ? "" : " loading");
    chip.innerHTML = "📎 " + escapeHtml(a.name) + (a.ready ? "" : " …") + ' <button type="button" title="Убрать">✕</button>';
    chip.querySelector("button").onclick = () => { attachments.splice(idx, 1); renderChips(); };
    els.chips.appendChild(chip);
  });
  updateSendState();
}

async function addFiles(fileList) {
  for (const file of fileList) {
    const entry = { name: file.name, ready: false, id: null };
    attachments.push(entry);
    renderChips();
    try {
      const info = await api("/api/upload?name=" + encodeURIComponent(file.name), { method: "POST", body: file });
      entry.id = info.id;
      entry.ready = true;
    } catch (e) {
      attachments.splice(attachments.indexOf(entry), 1);
      addMessage("error", "Не удалось загрузить " + escapeHtml(file.name) + ": " + escapeHtml(e.message));
    }
    renderChips();
  }
}

// ------------------------------------------------------------------ send
async function send(text) {
  if (busy) return;
  if (attachments.some((a) => !a.ready)) {
    addMessage("warning", "Дождитесь окончания загрузки файлов");
    return;
  }
  if (!text.trim() && !attachments.length) return;
  const ids = attachments.map((a) => a.id);
  try {
    await api("/api/message", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, attachments: ids }) });
    attachments.length = 0;
    renderChips();
    els.input.value = "";
    autosize();
  } catch (e) {
    addMessage("error", escapeHtml(e.message));
  }
}

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(180, els.input.scrollHeight) + "px";
  updateSendState();
}

// ------------------------------------------------------------------ settings
async function openSettings() {
  const s = await api("/api/settings");
  const f = els.settingsForm;
  f.base_url.value = s.base_url || "";
  f.model.value = s.model || "";
  f.output_dir.value = s.output_dir || "";
  f.api_key.value = "";
  els.keyHint.textContent = s.has_key ? "Ключ сохранён (" + s.key_hint + "). Оставьте поле пустым, чтобы не менять." : "Ключ не задан.";
  els.settingsMsg.textContent = "";
  $("mcp-url").textContent = location.origin + "/mcp";
  els.settings.showModal();
}

async function saveSettings() {
  const f = els.settingsForm;
  const body = { base_url: f.base_url.value, model: f.model.value, output_dir: f.output_dir.value };
  if (f.api_key.value) body.api_key = f.api_key.value;
  return api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ------------------------------------------------------------------ wiring
els.composer.addEventListener("submit", (e) => { e.preventDefault(); send(els.input.value); });
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(els.input.value); }
});
els.input.addEventListener("input", autosize);
els.stop.addEventListener("click", () => api("/api/stop", { method: "POST" }));
els.fileInput.addEventListener("change", () => { addFiles(els.fileInput.files); els.fileInput.value = ""; });
els.dropTarget.addEventListener("click", () => els.fileInput.click());
document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", () => { els.input.value = b.textContent; autosize(); els.input.focus(); }));
$("btn-new").addEventListener("click", async () => {
  try { await api("/api/reset", { method: "POST" }); } catch (e) { addMessage("error", escapeHtml(e.message)); }
});
$("btn-refresh").addEventListener("click", refreshState);
$("btn-settings").addEventListener("click", openSettings);
$("btn-save").addEventListener("click", async (e) => {
  e.preventDefault();
  try { await saveSettings(); els.settings.close(); } catch (err) { els.settingsMsg.textContent = "Ошибка: " + err.message; }
});
$("btn-test").addEventListener("click", async () => {
  els.settingsMsg.textContent = "Проверяю…";
  try {
    await saveSettings();
    const r = await api("/api/test_llm", { method: "POST" });
    els.settingsMsg.textContent = r.ok ? "✓ LLM отвечает за " + r.latency_s + " с: «" + r.reply + "»" : "✗ " + r.error;
  } catch (err) { els.settingsMsg.textContent = "✗ " + err.message; }
});

let dragDepth = 0;
window.addEventListener("dragenter", (e) => { e.preventDefault(); dragDepth++; els.dropzone.classList.remove("hidden"); });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; els.dropzone.classList.add("hidden"); } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  els.dropzone.classList.add("hidden");
  if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});

(async function init() {
  updateSendState();
  refreshState();
  try {
    const s = await api("/api/settings");
    if (!s.has_key || location.hash === "#settings") openSettings();
  } catch (e) { /* server not ready */ }
  poll();
})();
