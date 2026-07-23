let filesD = [],
  filesM = [],
  filesP = [];
let JOB = null,
  MAN = null,
  curTab = "desktop";
let BA_FLOW = null;
const disabled = { desktop: new Set(), mobile: new Set() };
// Layer an tu PSD van duoc xuat. Set nay chi bat tam de xem trong editor.
const forcedVisible = { desktop: new Set(), mobile: new Set() };
const previewHidden = { desktop: new Set(), mobile: new Set() };
let groupMode = false;
const groupSel = { desktop: new Set(), mobile: new Set() };
const collapsed = { desktop: new Set(), mobile: new Set() }; // folder dang gap trong cay layer
let sel = null,
  curScale = 1; // layer dang chon (thao tac canvas) + he so scale preview
let layerQuery = ""; // tu khoa tim trong danh sach layer
let curSec = -1; // section dang xem rieng (-1 = tat ca)
let previewZoom = 1; // he so phong khung xem truoc (1 = vua be rong cot)
let canvasScrollIntent = "top"; // top | bottom | preserve
let canvasRestoreToken = 0;
let draggedTreeItem = null;
const undoStack = [];
const redoStack = [];
const HISTORY_LIMIT = 80;
const undoBtn = document.getElementById("undoBtn");
const redoBtn = document.getElementById("redoBtn");

function cloneBBox(bbox) {
  return { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height };
}
function sameBBox(a, b) {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
}
function updateHistoryControls() {
  undoBtn.disabled = undoStack.length === 0;
  redoBtn.disabled = redoStack.length === 0;
  undoBtn.title = undoStack.length ? `Hoàn tác: ${undoStack.at(-1).label} (Ctrl+Z)` : "Không có thao tác để hoàn tác";
  redoBtn.title = redoStack.length ? `Làm lại: ${redoStack.at(-1).label} (Ctrl+Shift+Z)` : "Không có thao tác để làm lại";
}
function clearEditHistory() {
  undoStack.length = 0;
  redoStack.length = 0;
  updateHistoryControls();
}
function recordBBoxHistory(layer, before, after, label) {
  if (!layer || sameBBox(before, after)) return;
  undoStack.push({ tab: curTab, layerId: layer.id, before, after, label });
  if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
  redoStack.length = 0;
  updateHistoryControls();
}
function applyHistoryEntry(entry, bbox) {
  curTab = entry.tab;
  const layer = variant().layers.find((item) => item.id === entry.layerId);
  if (!layer) return false;
  layer.bbox = cloneBBox(bbox);
  sel = layer.id;
  recomputeSection(layer);
  saveEdit(layer.id, { bbox: layer.bbox });
  render();
  selectLayer(layer.id, true);
  return true;
}
function undoEdit() {
  const entry = undoStack.pop();
  if (!entry) return;
  if (applyHistoryEntry(entry, entry.before)) redoStack.push(entry);
  updateHistoryControls();
}
function redoEdit() {
  const entry = redoStack.pop();
  if (!entry) return;
  if (applyHistoryEntry(entry, entry.after)) undoStack.push(entry);
  updateHistoryControls();
}

undoBtn.addEventListener("click", undoEdit);
redoBtn.addEventListener("click", redoEdit);
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  if (/INPUT|TEXTAREA|SELECT/.test(event.target.tagName || "")) return;
  const key = event.key.toLowerCase();
  if (key === "z" && event.shiftKey) redoEdit();
  else if (key === "z") undoEdit();
  else if (key === "y") redoEdit();
  else return;
  event.preventDefault();
  event.stopImmediatePropagation();
});
updateHistoryControls();function setStep(n) {
  [1, 2, 3].forEach((i) => {
    const e = document.getElementById("stp" + i);
    e.classList.toggle("on", i === n);
    e.classList.toggle("done", i < n);
  });
}

function showList(nameEl, arr, unit) {
  unit = unit || "section";
  if (!arr.length) {
    nameEl.innerHTML = "";
    return;
  }
  const sorted = [...arr].sort((a, b) =>
    a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
  );
  if (sorted.length === 1) {
    nameEl.textContent = "\u2713 " + sorted[0].name;
    return;
  }
  nameEl.innerHTML =
    "\u2713 " +
    sorted.length +
    " " +
    unit +
    ":<br>" +
    sorted.map((f, i) => i + 1 + ". " + f.name).join("<br>");
}
function setupDrop(dropId, inputId, nameId, get, set, unit) {
  const drop = document.getElementById(dropId),
    input = document.getElementById(inputId),
    name = document.getElementById(nameId);
  drop.onclick = () => input.click();
  input.onchange = () => {
    if (input.files.length) {
      set([...input.files]);
      showList(name, get(), unit);
    }
  };
  ["dragover", "dragenter"].forEach((e) =>
    drop.addEventListener(e, (ev) => {
      ev.preventDefault();
      drop.classList.add("over");
    }),
  );
  ["dragleave", "drop"].forEach((e) =>
    drop.addEventListener(e, (ev) => {
      ev.preventDefault();
      drop.classList.remove("over");
    }),
  );
  drop.addEventListener("drop", (ev) => {
    const fs = [...ev.dataTransfer.files].filter((f) => /\.psd$/i.test(f.name));
    if (fs.length) {
      set(fs);
      showList(name, get(), unit);
    }
  });
}
setupDrop(
  "dropD",
  "fileD",
  "nameD",
  () => filesD,
  (a) => (filesD = a),
  "section",
);
setupDrop(
  "dropM",
  "fileM",
  "nameM",
  () => filesM,
  (a) => (filesM = a),
  "section",
);
setupDrop(
  "dropP",
  "fileP",
  "nameP",
  () => filesP,
  (a) => (filesP = a),
  "popup",
);

document.querySelectorAll("input[name=fmt]").forEach((r) =>
  r.addEventListener("change", () => {
    const f = document.querySelector("input[name=fmt]:checked").value;
    const isRN = f === "react" || f === "next";
    document.getElementById("langRow").style.display = isRN ? "flex" : "none";
    document.getElementById("reactOpts").style.display = isRN
      ? "flex"
      : "none";
    if (isRN) document.getElementById("exportAcc").open = true; // mo tuy chon de thay
  }),
);
// tim kiem layer trong danh sach
document.getElementById("layerSearch").addEventListener("input", function (e) {
  layerQuery = (e.target.value || "").trim().toLowerCase();
  render();
});
// zoom khung xem truoc
document.getElementById("zIn").onclick = () => {
  previewZoom = Math.min(3, previewZoom + 0.25);
  render();
};
document.getElementById("zOut").onclick = () => {
  previewZoom = Math.max(0.5, previewZoom - 0.25);
  render();
};
// doi be rong cua so -> ve lai khung cho vua cot
let _rzT = null;
window.addEventListener("resize", () => {
  if (!document.getElementById("editor").classList.contains("show")) return;
  clearTimeout(_rzT);
  _rzT = setTimeout(render, 150);
});

const parsePanel = document.getElementById("parsePanel"),
  parseStep = document.getElementById("parseStep"),
  parseErr = document.getElementById("parseErr"),
  editor = document.getElementById("editor"),
  exportPanel = document.getElementById("exportPanel"),
  exProgress = document.getElementById("exProgress"),
  exStep = document.getElementById("exStep"),
  result = document.getElementById("result"),
  goParse = document.getElementById("goParse"),
  goExport = document.getElementById("goExport");

let activeJobTask = null;
let jobTaskStarted = 0;
let jobTaskTimer = null;

function toast(message, type) {
  const stack = document.getElementById("toastStack");
  if (!stack) return;
  const item = document.createElement("div");
  item.className = "toastItem " + (type || "");
  item.textContent = message;
  stack.appendChild(item);
  setTimeout(() => item.remove(), 4200);
}

function formatElapsed(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, "0");
  return `${min}:${sec}`;
}

function syncJobTaskStatus() {
  const el = document.getElementById("jobTaskStatus");
  if (!el) return;
  if (!activeJobTask) return;
  el.textContent = `● ${activeJobTask.label} · ${formatElapsed(Date.now() - jobTaskStarted)}`;
}

function setEditorBusy(busy) {
  editor.classList.toggle("jobBusy", busy);
  ["goReview", "goExport", "grpMode"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
  ["stage", "secList", "selPanel", "grpBar"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.inert = busy;
  });
  if (!busy) updateHistoryControls();
}

function beginJobTask(phase, label) {
  activeJobTask = { phase, label };
  jobTaskStarted = Date.now();
  const el = document.getElementById("jobTaskStatus");
  if (el) {
    el.classList.remove("jobReady", "jobError");
    el.classList.add("jobBusy");
  }
  setEditorBusy(true);
  clearInterval(jobTaskTimer);
  jobTaskTimer = setInterval(syncJobTaskStatus, 1000);
  syncJobTaskStatus();
}

function updateJobTask(label) {
  if (!activeJobTask) return;
  activeJobTask.label = label || activeJobTask.label;
  syncJobTaskStatus();
}

function finishJobTask(message, isError) {
  clearInterval(jobTaskTimer);
  jobTaskTimer = null;
  activeJobTask = null;
  setEditorBusy(false);
  const el = document.getElementById("jobTaskStatus");
  if (!el) return;
  el.classList.remove("jobBusy", "jobReady", "jobError");
  el.classList.add(isError ? "jobError" : "jobReady");
  el.textContent = `● ${message || (isError ? "Có lỗi" : "Job sẵn sàng")}`;
  if (isError) {
    setTimeout(() => {
      if (activeJobTask) return;
      el.classList.remove("jobError");
      el.classList.add("jobReady");
      el.textContent = "● Job sẵn sàng";
    }, 5000);
  }
}

function formatBytes(value) {
  let size = Number(value) || 0;
  const units = ["B", "KB", "MB", "GB"];
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function formatJobTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

async function loadRecentJobs() {
  const list = document.getElementById("recentJobsList");
  const meta = document.getElementById("recentJobsMeta");
  if (!list || !meta) return;
  try {
    const resp = await fetch("/jobs", { cache: "no-store" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    meta.textContent = `${data.jobs.length} job gần nhất · ${
      data.ttl_days ? `tự dọn sau ${data.ttl_days} ngày` : "đã tắt tự dọn"
    }`;
    if (!data.jobs.length) {
      list.innerHTML = '<div class="recentJobsEmpty">Chưa có dự án nào.</div>';
      return;
    }
    list.innerHTML = data.jobs.map((job) => {
      const source = job.sources.length
        ? job.sources.join(", ") + (job.source_count > job.sources.length ? "…" : "")
        : "Không rõ file nguồn";
      const stateClass = job.busy ? "running" : job.status === "error" ? "error"
        : job.ready ? "" : "incomplete";
      const stateText = job.busy ? "Đang chạy" : job.status === "error" ? "Lỗi"
        : job.ready ? "Sẵn sàng" : "Dở dang";
      return `<article class="recentJob">
        <div class="recentJobMain">
          <div class="recentJobTitle"><b title="${esc(source)}">${esc(source)}</b><span class="jobState ${stateClass}">${stateText}</span></div>
          <div class="recentJobMeta"><span>${formatJobTime(job.updated_at)}</span><span>${formatBytes(job.size)}</span><span>${esc(job.phase || "")}</span></div>
          <div class="recentJobSource">${esc(job.step || "")}</div>
        </div>
        <div class="recentJobActions">
          <button class="ghost sm" data-open-job="${esc(job.id)}" ${job.ready && !job.busy ? "" : "disabled"}>Mở</button>
          <button class="ghost sm dangerBtn" data-delete-job="${esc(job.id)}" ${job.busy ? "disabled" : ""}>Xóa</button>
        </div>
      </article>`;
    }).join("");
  } catch (error) {
    meta.textContent = "Không tải được danh sách";
    list.innerHTML = `<div class="recentJobsEmpty">${esc(error.message || String(error))}</div>`;
  }
}

async function openRecentJob(jobId) {
  try {
    const resp = await fetch("/status/" + encodeURIComponent(jobId), { cache: "no-store" });
    const data = await resp.json();
    if (!resp.ok || data.error || !data.manifest) {
      throw new Error(data.error || "Job chưa sẵn sàng để mở.");
    }
    JOB = jobId;
    MAN = data.manifest;
    parsePanel.classList.remove("show");
    openEditor();
    toast("Đã mở lại dự án gần đây.", "ok");
  } catch (error) {
    toast(error.message || String(error), "error");
    loadRecentJobs();
  }
}

document.getElementById("recentJobsList").addEventListener("click", async (event) => {
  const open = event.target.closest("[data-open-job]");
  if (open) {
    openRecentJob(open.dataset.openJob);
    return;
  }
  const del = event.target.closest("[data-delete-job]");
  if (!del || !confirm("Xóa job này và toàn bộ PSD/assets/ZIP đã tạo?")) return;
  del.disabled = true;
  try {
    const resp = await fetch("/jobs/" + encodeURIComponent(del.dataset.deleteJob), {
      method: "DELETE",
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    toast("Đã xóa job.", "ok");
  } catch (error) {
    toast(error.message || String(error), "error");
  }
  loadRecentJobs();
});

document.getElementById("refreshJobs").onclick = loadRecentJobs;
document.getElementById("cleanupJobs").onclick = async () => {
  if (!confirm("Dọn các job cũ quá thời hạn? Job đang chạy sẽ được giữ lại.")) return;
  try {
    const resp = await fetch("/jobs/cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    toast(`Đã dọn ${data.removed.length} job cũ.`, "ok");
  } catch (error) {
    toast(error.message || String(error), "error");
  }
  loadRecentJobs();
};
loadRecentJobs();

// ---- BUOC 1: parse ----
goParse.onclick = async () => {
  if (!filesD.length) {
    alert("Hãy chọn file PSD Desktop trước");
    return;
  }
  const fd = new FormData();
  filesD.forEach((f) => fd.append("desktop", f));
  filesM.forEach((f) => fd.append("mobile", f));
  filesP.forEach((f) => fd.append("popup", f));
  fd.append(
    "quality",
    (document.querySelector("input[name=quality]:checked") || {}).value ||
      "balanced",
  );
  goParse.disabled = true;
  beginJobTask("parse", "Đang tải PSD");
  parsePanel.classList.add("show");
  parseErr.textContent = "";
  editor.classList.remove("show");
  parseStep.textContent = "Đang tải file lên…";
  let r;
  try {
    const resp = await fetch("/parse", { method: "POST", body: fd });
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      r = await resp.json();
    } else {
      const txt = await resp.text();
      parseStep.textContent =
        "Loi " +
        resp.status +
        ": " +
        (txt
          .replace(/<[^>]*>/g, "")
          .trim()
          .slice(0, 200) || "server khong tra JSON");
      goParse.disabled = false;
      finishJobTask("Tải PSD thất bại", true);
      return;
    }
  } catch (e) {
    parseStep.textContent = "Loi tai len: " + e;
    goParse.disabled = false;
    finishJobTask("Không kết nối được server", true);
    return;
  }
  if (r.error) {
    parseStep.textContent = "Loi: " + r.error;
    goParse.disabled = false;
    finishJobTask("Phân tích thất bại", true);
    toast(r.error, "error");
    return;
  }
  JOB = r.job_id;
  pollParse();
};

async function pollParse() {
  let s;
  try {
    s = await (await fetch("/status/" + JOB)).json();
  } catch (e) {
    setTimeout(pollParse, 1500);
    return;
  }
  parseStep.textContent = s.step || "Đang xử lý…";
  updateJobTask(s.step || "Đang phân tích PSD");
  if (s.status === "done" && s.manifest) {
    MAN = s.manifest;
    goParse.disabled = false;
    parsePanel.classList.remove("show");
    openEditor();
    finishJobTask("Job sẵn sàng");
    loadRecentJobs();
    return;
  }
  if (s.status === "error") {
    parseErr.textContent = (s.error || "") + "\n" + (s.trace || "");
    goParse.disabled = false;
    finishJobTask("Phân tích thất bại", true);
    loadRecentJobs();
    return;
  }
  setTimeout(pollParse, 1500);
}

// ---- BUOC 2: editor ----
// State theo TAB (desktop/mobile/popup:<id>) -> tao Set moi cho moi tab khi mo editor.
function resetTabState(tabList) {
  [disabled, forcedVisible, previewHidden, groupSel, collapsed].forEach((o) => {
    Object.keys(o).forEach((k) => delete o[k]);
    tabList.forEach((t) => (o[t] = new Set()));
  });
}
// Danh sach popup dang co (dung cho tab + dropdown 'Mo popup')
function popupsList() {
  return MAN && MAN.popups ? MAN.popups : [];
}
function inlinePopupsList() {
  const v = variant();
  return v && v.inlinePopups ? v.inlinePopups : [];
}
function popupChoices() {
  return popupsList().concat(inlinePopupsList());
}
function allPopupChoices() {
  return popupsList().concat((MAN && MAN.inlinePopups) || []);
}
// Map anh bi tat theo tung popup: {pid:[layerIds]} de gui khi export
function disabledPopupMap() {
  const m = {};
  popupsList().forEach((p) => {
    const s = disabled["popup:" + p.id];
    if (s && s.size) m[p.id] = [...s];
  });
  return m;
}

function openEditor() {
  document.getElementById("step1").style.display = "none";
  const tabList = [{ tab: "desktop", label: "\u{1F4BB} Desktop" }];
  if (MAN.mobile) tabList.push({ tab: "mobile", label: "\u{1F4F1} Mobile" });
  popupsList().forEach((p) =>
    tabList.push({ tab: "popup:" + p.id, label: "\u{1F9E9} " + p.name }),
  );
  resetTabState(tabList.map((t) => t.tab));
  clearEditHistory();
  groupMode = false;
  sel = null;
  curSec = -1;
  layerQuery = "";
  previewZoom = 1;
  canvasScrollIntent = "top";
  document.getElementById("stage").dataset.rendered = "";
  document.getElementById("grpMode").classList.remove("active");
  curTab = "desktop";
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = "";
  if (tabList.length > 1) {
    tabList.forEach(({ tab, label }) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.dataset.tab = tab;
      b.className = tab === curTab ? "active" : "";
      b.onclick = () => {
        curTab = tab;
        groupSel[tab].clear();
        sel = null;
        curSec = -1;
        canvasScrollIntent = "top";
        document.getElementById("stage").dataset.rendered = "";
        render();
      };
      tabs.appendChild(b);
    });
  }
  // Co PSD popup -> he popup dung tu PSD (auto bat khi xuat), bao cho user biet
  const popChk = document.getElementById("popups");
  if (popChk) {
    const popLbl = popChk.parentElement.querySelector("span");
    if (allPopupChoices().length) {
      popChk.checked = true;
      popChk.disabled = true;
      if (popLbl)
        popLbl.textContent =
          "Popup từ PSD (" +
          allPopupChoices().length +
          " popup) — bật sẵn theo file đã tải";
    } else {
      popChk.disabled = false;
      if (popLbl)
        popLbl.textContent =
          "Popup mẫu (đăng nhập / thể lệ / lịch sử / nạp đầu)";
    }
  }
  editor.classList.add("show");
  setStep(2);
  render();
  loadBAFlow();
}

const baDocument = document.getElementById("baDocument");
const baAnalyze = document.getElementById("baAnalyze");
const baApply = document.getElementById("baApply");
const baStatus = document.getElementById("baStatus");
const baFlowList = document.getElementById("baFlowList");

function setBAStatus(message, kind) {
  baStatus.textContent = message;
  baStatus.className = "baStatus" + (kind ? " " + kind : "");
}

async function loadBAFlow() {
  BA_FLOW = null;
  renderBAFlow();
  if (!JOB) return;
  try {
    const response = await fetch("/ba-flow/" + encodeURIComponent(JOB));
    const data = await response.json();
    if (response.ok && data.flow) {
      BA_FLOW = data.flow;
      document.getElementById("baFileName").textContent = BA_FLOW.source || "Tài liệu BA";
      renderBAFlow();
    }
  } catch (_) {}
}

function baLayerOptions(selected) {
  const layers = (MAN && MAN.desktop && MAN.desktop.layers) || [];
  return ['<option value="">-- Chọn layer --</option>']
    .concat(
      layers.map(
        (layer) =>
          `<option value="${esc(layer.id)}"${layer.id === selected ? " selected" : ""}>${esc(layer.name)}</option>`,
      ),
    )
    .join("");
}

function baTargetControl(item) {
  if (item.action === "unsupported") {
    return '<input class="baTarget" value="" placeholder="Cần dev/BA bổ sung cách xử lý" disabled>';
  }
  if (item.action === "popup") {
    const options = ['<option value="">-- Chọn popup --</option>'].concat(
      allPopupChoices().map(
        (popup) =>
          `<option value="${esc(popup.id)}"${popup.id === item.target ? " selected" : ""}>${esc(popup.name)}</option>`,
      ),
    );
    return `<select class="baTarget">${options.join("")}</select>`;
  }
  if (item.action === "scroll") {
    const sections = (MAN && MAN.desktop && MAN.desktop.sections) || [];
    const options = ['<option value="">-- Chọn section --</option>'].concat(
      sections.map(
        (section, index) =>
          `<option value="${index}"${String(index) === String(item.target) ? " selected" : ""}>${esc(section.name)}</option>`,
      ),
    );
    return `<select class="baTarget">${options.join("")}</select>`;
  }
  return `<input class="baTarget" value="${esc(item.target || "")}" placeholder="https://... hoặc /duong-dan">`;
}

function renderBAFlow() {
  if (!baFlowList) return;
  if (!BA_FLOW || !BA_FLOW.items || !BA_FLOW.items.length) {
    baFlowList.innerHTML =
      '<div class="baFlowEmpty">Upload tài liệu để nhận đề xuất mapping.</div>';
    baApply.disabled = true;
    if (BA_FLOW) setBAStatus("Không tìm thấy yêu cầu URL, popup hoặc scroll trong tài liệu.", "err");
    return;
  }
  baFlowList.innerHTML = "";
  BA_FLOW.items.forEach((item, index) => {
    const row = document.createElement("article");
    row.className = "baFlowItem" + (item.status === "applied" ? " applied" : "");
    row.innerHTML = `
      <div class="baFlowHead">
        <input class="baEnabled" type="checkbox"${item.enabled ? " checked" : ""}>
        <span title="${esc(item.requirement)}">${esc(item.requirement)}</span>
        <b class="baConfidence">${Math.round((item.confidence || 0) * 100)}%</b>
      </div>
      <div class="baFlowFields">
        <label>Layer<select class="baLayer">${baLayerOptions(item.layer_id)}</select></label>
        <label>Hành động
          <select class="baAction">
            <option value="url"${item.action === "url" ? " selected" : ""}>Mở URL</option>
            <option value="popup"${item.action === "popup" ? " selected" : ""}>Mở popup</option>
            <option value="scroll"${item.action === "scroll" ? " selected" : ""}>Cuộn tới section</option>
            <option value="unsupported"${item.action === "unsupported" ? " selected" : ""}>Cần dev xử lý</option>
          </select>
        </label>
        <label>Đích<span class="baTargetWrap">${baTargetControl(item)}</span></label>
      </div>
      ${item.status === "review" ? '<span class="baFlowWarn">Cần kiểm tra lại đề xuất này.</span>' : ""}
    `;
    const updateTarget = () => {
      const control = row.querySelector(".baTarget");
      item.target = control ? control.value.trim() : "";
    };
    row.querySelector(".baEnabled").onchange = (event) => {
      item.enabled = event.target.checked;
      baApply.disabled = !BA_FLOW.items.some((entry) => entry.enabled);
    };
    row.querySelector(".baLayer").onchange = (event) => {
      item.layer_id = event.target.value;
      const selected = event.target.selectedOptions[0];
      item.layer_name = selected && item.layer_id ? selected.textContent : "";
      item.enabled = Boolean(item.layer_id && item.target);
      row.querySelector(".baEnabled").checked = item.enabled;
      baApply.disabled = !BA_FLOW.items.some((entry) => entry.enabled);
    };
    row.querySelector(".baAction").onchange = (event) => {
      item.action = event.target.value;
      item.target = "";
      if (item.action === "unsupported") {
        item.enabled = false;
        row.querySelector(".baEnabled").checked = false;
      }
      row.querySelector(".baTargetWrap").innerHTML = baTargetControl(item);
      row.querySelector(".baTarget").onchange = updateTarget;
      row.querySelector(".baTarget").oninput = updateTarget;
      baApply.disabled = !BA_FLOW.items.some((entry) => entry.enabled);
    };
    row.querySelector(".baTarget").onchange = updateTarget;
    row.querySelector(".baTarget").oninput = updateTarget;
    row.dataset.index = index;
    baFlowList.appendChild(row);
  });
  const summary = BA_FLOW.summary || {};
  setBAStatus(
    `${BA_FLOW.source || "Tài liệu"} · ${BA_FLOW.items.length} yêu cầu · ${summary.needs_review || 0} cần kiểm tra`,
    "ok",
  );
  baApply.disabled = !BA_FLOW.items.some((item) => item.enabled);
}

baDocument.addEventListener("change", () => {
  document.getElementById("baFileName").textContent =
    baDocument.files[0] ? baDocument.files[0].name : "Chọn tài liệu";
});

baAnalyze.addEventListener("click", async () => {
  const file = baDocument.files[0];
  if (!JOB) return setBAStatus("Hãy phân tích PSD trước.", "err");
  if (!file) return setBAStatus("Hãy chọn tài liệu BA.", "err");
  const form = new FormData();
  form.append("job_id", JOB);
  form.append("document", file);
  baAnalyze.disabled = true;
  baApply.disabled = true;
  setBAStatus("Đang đọc tài liệu và đối chiếu layer…");
  try {
    const response = await fetch("/ba-flow/upload", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Không thể phân tích tài liệu.");
    BA_FLOW = data.flow;
    renderBAFlow();
  } catch (error) {
    setBAStatus(error.message || String(error), "err");
  } finally {
    baAnalyze.disabled = false;
  }
});

baApply.addEventListener("click", async () => {
  if (!BA_FLOW) return;
  baApply.disabled = true;
  setBAStatus("Đang áp dụng mapping vào desktop và mobile…");
  try {
    const response = await fetch("/ba-flow/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: JOB, items: BA_FLOW.items }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || "Không thể áp dụng mapping.");
    BA_FLOW = data.flow;
    MAN = data.manifest;
    render();
    renderBAFlow();
    setBAStatus(`Đã áp dụng ${data.applied} mapping. Flow-spec sẽ đi kèm bản export.`, "ok");
  } catch (error) {
    setBAStatus(error.message || String(error), "err");
    baApply.disabled = false;
  }
});

document.getElementById("baFlowBtn").addEventListener("click", () => {
  editor.classList.remove("inspectorCollapsed");
  const details = document.getElementById("baFlowAcc");
  details.open = true;
  details.scrollIntoView({ behavior: "smooth", block: "start" });
});

function variant() {
  if (curTab.indexOf("popup:") === 0) {
    const pid = curTab.slice(6);
    return popupsList().find((p) => p.id === pid);
  }
  return MAN[curTab];
}

function render() {
  document
    .querySelectorAll("#tabs button")
    .forEach((b) => (b.className = b.dataset.tab === curTab ? "active" : ""));
  const v = variant(),
    dis = disabled[curTab];
  if (sel && !v.layers.some((l) => l.id === sel)) sel = null; // sel khong con -> bo
  v.layers.sort((a, b) => (a.z || 0) - (b.z || 0)); // thu tu lop (z), stable
  // preview stage
  const stage = document.getElementById("stage");
  const canvasDock = document.querySelector(".canvasDock");
  const hadCanvas = stage.dataset.rendered === "1";
  const viewX = hadCanvas && canvasDock.scrollWidth
    ? (canvasDock.scrollLeft + canvasDock.clientWidth / 2) / canvasDock.scrollWidth
    : 0.5;
  const viewY = hadCanvas && canvasDock.scrollHeight
    ? (canvasDock.scrollTop + canvasDock.clientHeight / 2) / canvasDock.scrollHeight
    : 0;
  const restoreIntent = canvasScrollIntent;
  const restoreToken = ++canvasRestoreToken;
  canvasScrollIntent = "preserve";
  const box = document.querySelector(".prevBox");
  const avail = box ? Math.max(280, box.clientWidth - 26) : 380; // be rong kha dung cua cot preview
  const fit = Math.min(1, avail / v.canvas.width);
  curScale = Math.min(1, fit * previewZoom);
  const scale = curScale;
  const zl = document.getElementById("zLbl");
  if (zl) zl.textContent = Math.round(previewZoom * 100) + "%";
  stage.style.width = v.canvas.width * scale + "px";
  stage.style.height = v.canvas.height * scale + "px";
  let html = "";
  // DEMO hieu ung: map l.fx -> class demo trong preview (+ lop luot sang neu can)
  const FX_BASE = {
    glow: "fx-glow",
    float: "fx-float",
    "float-glow": "fx-float fx-glow",
    "shine-glow": "fx-glow",
    btn: "fx-glow",
  };
  const FX_SHINE = new Set(["shine", "shine-glow", "btn"]);
  v.layers.forEach((l) => {
    const b = l.bbox,
      off = isLayerShown(l) ? "" : " off",
      ss = sel === l.id ? " sel" : "";
    const st =
      "left:" +
      b.x * scale +
      "px;top:" +
      b.y * scale +
      "px;width:" +
      b.width * scale +
      "px;height:" +
      b.height * scale +
      "px";
    const fxc = l.fx && FX_BASE[l.fx] ? " " + FX_BASE[l.fx] : "";
    const td = l.textData;
    if (td && td.asText) {
      // chu that -> hien text ngay trong preview (WYSIWYG)
      html +=
        '<div class="lyr txt' +
        off +
        ss +
        fxc +
        '" data-id="' +
        l.id +
        '" style="' +
        st +
        ";display:flex;align-items:center;justify-content:center;text-align:center;overflow:hidden" +
        ";font-weight:700;line-height:1.15;white-space:pre-wrap;font-size:" +
        (td.size || 20) * scale +
        "px;color:" +
        (td.color || "#fff") +
        '">' +
        esc(td.content || "") +
        "</div>";
    } else {
      html +=
        '<img class="lyr' +
        off +
        ss +
        fxc +
        '" data-id="' +
        l.id +
        '" src="' +
        l.asset +
        '" loading="lazy" style="' +
        st +
        '">';
      if (!off && l.fx && FX_SHINE.has(l.fx))
        // lop anh phu luot sang (demo)
        html +=
          '<img class="lyr-fxshine" src="' + l.asset + '" style="' + st + '">';
    }
  });
  v.sections.forEach((s, i) => {
    if (i === 0) return;
    html +=
      '<div class="secmark" style="top:' +
      s.y0 * scale +
      'px"><span>' +
      esc(s.name) +
      "</span></div>";
  });
  stage.innerHTML = html;
  drawSel();
  // xem riêng 1 section: cắt khung theo chiều cao section + dịch stage lên
  const clip = document.getElementById("stageClip");
  clip.style.width = v.canvas.width * scale + "px";
  if (curSec >= 0 && v.sections[curSec]) {
    const sc = v.sections[curSec];
    clip.style.height = (sc.y1 - sc.y0) * scale + "px";
    stage.style.transform = "translateY(" + -sc.y0 * scale + "px)";
  } else {
    clip.style.height = v.canvas.height * scale + "px";
    stage.style.transform = "none";
  }
  renderSecNav();

  renderList();
  renderSug();
  updGrpBar();
  updInfo();
  if (sel && !groupMode) ensurePanel();
  else document.getElementById("selPanel").style.display = "none";
  stage.dataset.rendered = "1";
  requestAnimationFrame(() => {
    if (restoreToken !== canvasRestoreToken) return;
    const maxLeft = Math.max(0, canvasDock.scrollWidth - canvasDock.clientWidth);
    const maxTop = Math.max(0, canvasDock.scrollHeight - canvasDock.clientHeight);
    if (restoreIntent === "top" || !hadCanvas) {
      canvasDock.scrollLeft = Math.max(0, maxLeft / 2);
      canvasDock.scrollTop = 0;
    } else if (restoreIntent === "bottom") {
      canvasDock.scrollLeft = Math.max(0, maxLeft / 2);
      canvasDock.scrollTop = maxTop;
    } else {
      canvasDock.scrollLeft = Math.max(
        0, Math.min(maxLeft, viewX * canvasDock.scrollWidth - canvasDock.clientWidth / 2),
      );
      canvasDock.scrollTop = Math.max(
        0, Math.min(maxTop, viewY * canvasDock.scrollHeight - canvasDock.clientHeight / 2),
      );
    }
  });
}

function isLayerShown(layer) {
  if (disabled[curTab].has(layer.id)) return false;
  if (previewHidden[curTab].has(layer.id)) return false;
  return layer.visible !== false || forcedVisible[curTab].has(layer.id);
}

function setLayerShown(layer, shown) {
  if (shown) {
    previewHidden[curTab].delete(layer.id);
    if (layer.visible === false) forcedVisible[curTab].add(layer.id);
  } else {
    previewHidden[curTab].add(layer.id);
    forcedVisible[curTab].delete(layer.id);
  }
}

// ================= CÂY LAYER kiểu Photoshop (folder lồng nhau + ẩn/hiện) =================
function renderList() {
  const v = variant(),
    dis = disabled[curTab],
    gsel = groupSel[curTab],
    col = collapsed[curTab];
  const list = document.getElementById("secList");
  list.innerHTML = "";
  list.classList.toggle("gmode", groupMode);

  // Chế độ tìm kiếm: danh sách phẳng các ảnh khớp tên
  if (layerQuery) {
    const wrap = document.createElement("div");
    wrap.className = "tree";
    v.layers
      .filter(
        (l) =>
          (l.name || "").toLowerCase().includes(layerQuery) &&
          (curSec < 0 || l.section === curSec),
      )
      .forEach((l) => wrap.appendChild(leafRow(l, 0)));
    if (!wrap.children.length)
      wrap.innerHTML =
        '<div class="hint" style="margin:0">Không tìm thấy ảnh nào.</div>';
    list.appendChild(wrap);
    return;
  }

  // Dựng cây theo folder PSD (parent -> con)
  const kids = {};
  const add = (p, it) => {
    (kids[p || "__root"] = kids[p || "__root"] || []).push(it);
  };
  (v.nodes || []).forEach((g) => add(g.parent, { t: "g", n: g }));
  v.layers.forEach((l) => add(l.parent, { t: "l", n: l }));
  // Cay hien lop tren truoc. Rank group lay theo layer con tren cung de thu tu
  // folder tiep tuc dung sau khi keo va tai lai manifest.
  const layerRank = new Map(v.layers.map((layer, index) => [layer.id, index]));
  function itemRank(it) {
    if (it.t === "l") return layerRank.get(it.n.id) ?? it.n.order ?? 0;
    const childRanks = (kids[it.n.id] || []).map(itemRank);
    return childRanks.length ? Math.max(...childRanks) : it.n.order || 0;
  }
  Object.keys(kids).forEach((k) =>
    kids[k].sort((a, b) => itemRank(b) - itemRank(a)),
  );
  // gom id anh (là con-cháu) dưới 1 folder
  function leavesOf(gid) {
    let out = [];
    (kids[gid] || []).forEach((it) => {
      if (it.t === "g") out = out.concat(leavesOf(it.n.id));
      else out.push(it.n);
    });
    return out;
  }

  const wrap = document.createElement("div");
  wrap.className = "tree";
  (kids["__root"] || []).forEach((it) => renderNode(it, wrap, 0));
  list.appendChild(wrap);

  function renderNode(it, parentEl, depth) {
    if (it.t === "l") {
      const l = it.n;
      if (curSec >= 0 && l.section !== curSec) return;
      parentEl.appendChild(leafRow(l, depth));
      return;
    }
    // folder
    const g = it.n,
      leaves = leavesOf(g.id).filter((l) => curSec < 0 || l.section === curSec);
    if (!leaves.length) return; // ẩn folder rỗng / ngoài section
    const kept = leaves.filter(isLayerShown).length;
    const open = !col.has(g.id);
    const row = document.createElement("div");
    row.className = "frow";
    row.dataset.groupId = g.id;
    row.style.paddingLeft = 6 + depth * 15 + "px";
    row.innerHTML =
      '<span class="tw">' +
      (open ? "&#9662;" : "&#9656;") +
      "</span>" +
      '<span class="eye' +
      (kept ? "" : " off") +
      '" title="Ẩn/hiện cả nhóm">' +
      (kept ? "&#128065;" : "&#128584;") +
      "</span>" +
      '<span class="fico">&#128193;</span><span class="fname">' +
      esc(g.name) +
      "</span>" +
      '<span class="fcnt">' +
      kept +
      "/" +
      leaves.length +
      "</span>" +
      (leaves.length >= 2 && !groupMode
        ? '<span class="fgroup" title="Gộp cả folder thành 1 ảnh">&#129513; gộp</span>'
        : "");
    row.querySelector(".tw").onclick = (e) => {
      e.stopPropagation();
      if (col.has(g.id)) col.delete(g.id);
      else col.add(g.id);
      renderList();
    };
    row.querySelector(".eye").onclick = (e) => {
      e.stopPropagation();
      // Layer da bam "khong xuat" luon an, nen khong duoc dung no de quyet
      // dinh trang thai mat cua folder. Chi toggle cac layer con dang duoc xuat.
      const previewLeaves = leaves.filter((l) => !dis.has(l.id));
      const allOn = previewLeaves.length > 0 && previewLeaves.every(isLayerShown);
      previewLeaves.forEach((l) => setLayerShown(l, !allOn));
      applyVis();
      renderList();
      updInfo();
    };
    const fg = row.querySelector(".fgroup");
    if (fg)
      fg.onclick = (e) => {
        e.stopPropagation();
        doGroup(
          leaves.map((l) => l.id),
          g.name,
        );
      };
    row.onclick = () => {
      if (col.has(g.id)) col.delete(g.id);
      else col.add(g.id);
      renderList();
    };
    attachTreeDrag(row, { type: "group", id: g.id, parent: g.parent || null });
    parentEl.appendChild(row);
    if (open) {
      const childBox = document.createElement("div");
      (kids[g.id] || []).forEach((c) => renderNode(c, childBox, depth + 1));
      parentEl.appendChild(childBox);
    }
  }
}
function leafRow(l, depth) {
  const dis = disabled[curTab],
    gsel = groupSel[curTab],
    on = isLayerShown(l);
  const it = document.createElement("div");
  it.dataset.id = l.id;
  it.className =
    "item lrow" +
    (on ? "" : " off") +
    (dis.has(l.id) ? " excluded" : "") +
    (l.group ? " grp" : "") +
    (gsel.has(l.id) ? " gsel" : "") +
    (sel === l.id ? " sel" : "");
  it.style.paddingLeft = 6 + depth * 15 + "px";
  it.innerHTML =
    '<span class="eye' +
    (on ? "" : " off") +
    '" title="Ẩn/hiện ảnh">' +
    (on ? "&#128065;" : "&#128584;") +
    "</span>" +
    '<img class="th" src="' +
    l.asset +
    '" loading="lazy">' +
    '<span class="nm">' +
    esc(l.name) +
    (l.text ? '<span class="badge">T</span>' : "") +
    (l.visible === false ? '<span class="badge">PSD an</span>' : "") +
    (l.group ? '<span class="gbadge">gộp ' + l.count + "</span>" : "") +
    "</span>" +
    (l.group
      ? '<span class="untie" title="Tách nhóm">&#9986; tách</span>'
      : "") +
    '<span class="xout' +
    (dis.has(l.id) ? " active" : !on ? " suggest" : "") +
    '" title="' +
    (dis.has(l.id)
      ? "Khoi phuc vao ban xuat"
      : !on
        ? "Layer dang tat mat nhung VAN DUOC XUAT - bam de khong xuat"
        : "Khong xuat layer nay") +
    '">' +
    (dis.has(l.id) ? "&#8634;" : "&#8856;") +
    "</span>";
  it.querySelector(".eye").onclick = (e) => {
    e.stopPropagation();
    setLayerShown(l, !isLayerShown(l));
    const off = !isLayerShown(l);
    it.classList.toggle("off", off);
    it.querySelector(".eye").classList.toggle("off", off);
    it.querySelector(".eye").innerHTML = off ? "&#128584;" : "&#128065;";
    const exportBtn = it.querySelector(".xout");
    exportBtn.classList.toggle("suggest", off && !dis.has(l.id));
    exportBtn.title = dis.has(l.id)
      ? "Khoi phuc vao ban xuat"
      : off
        ? "Layer dang tat mat nhung VAN DUOC XUAT - bam de khong xuat"
        : "Khong xuat layer nay";
    const im = document.querySelector(
      '#stage .lyr[data-id="' + cssq(l.id) + '"]',
    );
    if (im) im.classList.toggle("off", off);
    updInfo();
  };
  const untie = it.querySelector(".untie");
  if (untie)
    untie.onclick = (e) => {
      e.stopPropagation();
      doUngroup(l.id);
    };
  it.querySelector(".xout").onclick = (e) => {
    e.stopPropagation();
    if (dis.has(l.id)) dis.delete(l.id);
    else {
      dis.add(l.id);
      forcedVisible[curTab].delete(l.id);
      previewHidden[curTab].delete(l.id);
    }
    applyVis();
    renderList();
    updInfo();
  };
  it.onclick = () => {
    if (groupMode) {
      if (gsel.has(l.id)) gsel.delete(l.id);
      else gsel.add(l.id);
      it.classList.toggle("gsel", gsel.has(l.id));
      updGrpBar();
      return;
    }
    selectLayer(l.id, true);
  };
  attachTreeDrag(it, { type: "layer", id: l.id, parent: l.parent || null });
  return it;
}

function clearLayerDropMarkers() {
  document
    .querySelectorAll("#secList .drop-before, #secList .drop-after")
    .forEach((row) => row.classList.remove("drop-before", "drop-after"));
}

function attachTreeDrag(row, item) {
  row.draggable = !groupMode && !layerQuery;
  if (!row.draggable) return;
  row.title = item.type === "group"
    ? "Kéo cả group để đổi thứ tự trong cùng cấp"
    : "Kéo để đổi thứ tự layer trong cùng một thư mục";
  row.addEventListener("dragstart", (e) => {
    if (e.target.closest(".eye, .tw, .fgroup, .untie")) {
      e.preventDefault();
      return;
    }
    draggedTreeItem = item;
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", `${item.type}:${item.id}`);
  });
  row.addEventListener("dragover", (e) => {
    const source = draggedTreeItem;
    if (
      !source ||
      (source.type === item.type && source.id === item.id) ||
      source.parent !== item.parent
    )
      return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    clearLayerDropMarkers();
    const before = e.clientY < row.getBoundingClientRect().top + row.offsetHeight / 2;
    row.classList.add(before ? "drop-before" : "drop-after");
    const list = document.getElementById("secList");
    const bounds = list.getBoundingClientRect();
    if (e.clientY < bounds.top + 30) list.scrollTop -= 18;
    else if (e.clientY > bounds.bottom - 30) list.scrollTop += 18;
  });
  row.addEventListener("dragleave", (e) => {
    if (!row.contains(e.relatedTarget)) row.classList.remove("drop-before", "drop-after");
  });
  row.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const place = row.classList.contains("drop-before") ? "before" : "after";
    moveTreeItemRelative(draggedTreeItem, item, place);
  });
  row.addEventListener("dragend", () => {
    draggedTreeItem = null;
    clearLayerDropMarkers();
  });
}
// đồng bộ ẩn/hiện lên preview (sau khi bật/tắt cả folder)
function applyVis() {
  const byId = new Map(variant().layers.map((layer) => [layer.id, layer]));
  document.querySelectorAll("#stage .lyr").forEach((im) => {
    const layer = byId.get(im.dataset.id);
    im.classList.toggle("off", !layer || !isLayerShown(layer));
  });
}
// goi y nhom gop (cung ten chuan hoa) + group hien co
function renderSug() {
  const box = document.getElementById("grpSug");
  const v = variant();
  if (!groupMode) {
    box.innerHTML = "";
    return;
  }
  const secName = (i) => (v.sections[i] || {}).name || "S" + (i + 1);
  const pg = v.psdGroups || [];
  const sug = (v.suggestions || []).filter((s) => s.members.length >= 2);
  let h = "";
  if (pg.length) {
    h +=
      '<div style="color:var(--muted);font-size:12px;margin-bottom:6px">&#128193; Group có sẵn trong PSD — bấm để gộp nguyên folder thành 1 ảnh:</div>';
    pg.forEach((g, i) => {
      h +=
        '<span class="sug-chip psd" data-src="psd" data-i="' +
        i +
        '">&#128193; ' +
        esc(g.name) +
        " &middot; " +
        g.n +
        ' ảnh <span style="opacity:.6">(' +
        esc(secName(g.section)) +
        ")</span></span>";
    });
  }
  if (sug.length) {
    h +=
      '<div style="color:var(--muted);font-size:12px;margin:' +
      (pg.length ? "9px" : "0") +
      ' 0 6px">&#129513; Gợi ý theo tên (ảnh trùng tên cùng section):</div>';
    sug.forEach((s, i) => {
      h +=
        '<span class="sug-chip" data-src="name" data-i="' +
        i +
        '">&#129513; ' +
        esc(s.name || "nhóm") +
        " &middot; " +
        s.members.length +
        ' ảnh <span style="opacity:.6">(' +
        esc(secName(s.section)) +
        ")</span></span>";
    });
  }
  if (!h)
    h =
      '<div style="color:var(--muted);font-size:12px">Không có group PSD / gợi ý sẵn. Bấm chọn ảnh trong danh sách rồi bấm "Gộp thành 1 ảnh".</div>';
  box.innerHTML = h;
  box.querySelectorAll(".sug-chip").forEach((c) => {
    c.onclick = () => {
      const g =
        c.dataset.src === "psd" ? v.psdGroups[+c.dataset.i] : sug[+c.dataset.i];
      if (g) doGroup(g.members, g.name);
    };
  });
}
function updGrpBar() {
  const bar = document.getElementById("grpBar");
  const gsel = groupSel[curTab];
  bar.style.display = groupMode ? "flex" : "none";
  document.getElementById("grpCount").textContent = gsel.size + " ảnh đã chọn";
}
function updInfoBase() {
  const v = variant(),
    dis = disabled[curTab],
    tot = v.layers.length,
    kept =
      tot - [...dis].filter((id) => v.layers.some((l) => l.id === id)).length;
  document.getElementById("selInfo").textContent =
    "Giữ " + kept + "/" + tot + " ảnh";
}
function updInfo() {
  updInfoBase();
  const v = variant();
  const dis = disabled[curTab];
  const refs = v.layers
    .filter((layer) => !dis.has(layer.id) && layer.asset)
    .map((layer) => layer.asset);
  const assetCounts = new Map();
  refs.forEach((asset) => assetCounts.set(asset, (assetCounts.get(asset) || 0) + 1));
  const uniqueAssets = assetCounts.size;
  const reusedLayers = Math.max(0, refs.length - uniqueAssets);
  const duplicateAssets = [...assetCounts.values()].filter((count) => count > 1).length;
  const stats = document.getElementById("assetStats");
  if (!stats) return;
  stats.classList.toggle("hasDup", reusedLayers > 0);
  stats.innerHTML =
    '<span><b>' + refs.length + "</b> layer \u1ea3nh</span>" +
    '<span><b>' + uniqueAssets + "</b> file duy nh\u1ea5t</span>" +
    '<span class="saved"><b>-' + reusedLayers + "</b> file tr\u00f9ng</span>" +
    '<span><b>' + duplicateAssets + "</b> asset d\u00f9ng l\u1eb7p</span>";
}
function esc(s) {
  return (s == null ? "" : String(s)).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
}
function cssq(s) {
  return (s || "").replace(/"/g, '\\"');
}
function renderSecNavLegacy() {
  const nav = document.getElementById("secNav");
  const v = variant();
  if (!v.sections || v.sections.length <= 1) {
    nav.innerHTML = "";
    return;
  }
  let h =
    '<button data-s="-1"' +
    (curSec < 0 ? ' class="active"' : "") +
    ">&#128196; Tất cả</button>";
  v.sections.forEach((s, i) => {
    h +=
      '<button data-s="' +
      i +
      '"' +
      (curSec === i ? ' class="active"' : "") +
      ">" +
      (i + 1) +
      ". " +
      esc(s.name || "Section " + (i + 1)) +
      "</button>";
  });
  nav.innerHTML = h;
  nav.querySelectorAll("button").forEach(
    (b) =>
      (b.onclick = () => {
        curSec = +b.dataset.s;
        render();
      }),
  );
}

function showCanvasSection(index) {
  const sections = variant().sections || [];
  const next = Math.max(-1, Math.min(sections.length - 1, Number(index)));
  curSec = Number.isFinite(next) ? next : -1;
  sel = null;
  canvasScrollIntent = "top";
  render();
}

function scrollCanvasEdge(edge) {
  const dock = document.querySelector(".canvasDock");
  if (!dock) return;
  dock.scrollTo({
    top: edge === "bottom" ? dock.scrollHeight : 0,
    behavior: "smooth",
  });
}

function fitCanvasSection() {
  const v = variant();
  if (curSec < 0 || !v.sections[curSec]) {
    previewZoom = 1;
    canvasScrollIntent = "top";
    render();
    return;
  }
  const dock = document.querySelector(".canvasDock");
  const section = v.sections[curSec];
  const sectionHeight = Math.max(1, section.y1 - section.y0);
  const availWidth = Math.max(280, dock.clientWidth - 52);
  const availHeight = Math.max(240, dock.clientHeight - 150);
  const widthScale = Math.min(1, availWidth / v.canvas.width);
  const targetScale = Math.min(1, widthScale, availHeight / sectionHeight);
  previewZoom = Math.max(
    0.5,
    Math.min(3, targetScale / Math.max(widthScale, 0.001)),
  );
  canvasScrollIntent = "top";
  render();
}

function renderSecNav() {
  const nav = document.getElementById("secNav");
  const sections = variant().sections || [];
  if (!sections.length) {
    nav.innerHTML = "";
    return;
  }
  const options = [
    `<option value="-1"${curSec < 0 ? " selected" : ""}>Tất cả section (${sections.length})</option>`,
    ...sections.map(
      (section, index) =>
        `<option value="${index}"${curSec === index ? " selected" : ""}>${index + 1}. ${esc(section.name || "Section " + (index + 1))}</option>`,
    ),
  ].join("");
  nav.innerHTML = `
    <button class="edgeBtn" data-edge="top" title="Lên đầu canvas">⇤ Đầu</button>
    <button data-step="-1" title="Section trước" ${curSec < 0 ? "disabled" : ""}>‹</button>
    <label class="sectionPicker"><span>Section</span><select id="sectionPicker">${options}</select></label>
    <button data-step="1" title="Section sau" ${curSec >= sections.length - 1 ? "disabled" : ""}>›</button>
    <button id="fitSection" ${curSec < 0 ? "disabled" : ""} title="Co section hiện tại vừa chiều cao canvas">Fit section</button>
    <button class="edgeBtn" data-edge="bottom" title="Xuống cuối canvas">Cuối ⇥</button>`;
  nav.querySelector("#sectionPicker").onchange = (event) =>
    showCanvasSection(+event.target.value);
  nav.querySelectorAll("[data-step]").forEach((button) => {
    button.onclick = () =>
      showCanvasSection(curSec + Number(button.dataset.step));
  });
  nav.querySelectorAll("[data-edge]").forEach((button) => {
    button.onclick = () => scrollCanvasEdge(button.dataset.edge);
  });
  const fitSection = nav.querySelector("#fitSection");
  if (fitSection) fitSection.onclick = fitCanvasSection;
}

// ================= THAO TAC CANVAS: chon / keo / resize / z-order / nudge =================
function curLayer() {
  return sel ? variant().layers.find((l) => l.id === sel) : null;
}
function positionImg(l) {
  const im = document.querySelector(
    '#stage .lyr[data-id="' + cssq(l.id) + '"]',
  );
  if (im) {
    const b = l.bbox;
    im.style.left = b.x * curScale + "px";
    im.style.top = b.y * curScale + "px";
    im.style.width = b.width * curScale + "px";
    im.style.height = b.height * curScale + "px";
    if (im.classList.contains("txt") && l.textData)
      im.style.fontSize = (l.textData.size || 20) * curScale + "px";
  }
}
function selectLayer(id, scrollList) {
  if (groupMode) return;
  sel = id;
  document
    .querySelectorAll("#stage .lyr.sel")
    .forEach((i) => i.classList.remove("sel"));
  const im = document.querySelector('#stage .lyr[data-id="' + cssq(id) + '"]');
  if (im) im.classList.add("sel");
  document
    .querySelectorAll(".item.sel")
    .forEach((i) => i.classList.remove("sel"));
  const it = document.querySelector('.item[data-id="' + cssq(id) + '"]');
  if (it) {
    it.classList.add("sel");
    if (scrollList) it.scrollIntoView({ block: "nearest" });
  }
  drawSel();
  ensurePanel();
}
function deselect() {
  sel = null;
  const ov = document.querySelector("#stage .selov");
  if (ov) ov.remove();
  document
    .querySelectorAll(".item.sel,#stage .lyr.sel")
    .forEach((i) => i.classList.remove("sel"));
  document.getElementById("selPanel").style.display = "none";
}
function drawSel() {
  const stage = document.getElementById("stage");
  const old = stage.querySelector(".selov");
  if (old) old.remove();
  const l = curLayer();
  if (groupMode || !l || disabled[curTab].has(l.id)) return;
  const b = l.bbox;
  const ov = document.createElement("div");
  ov.className = "selov";
  ov.style.left = b.x * curScale + "px";
  ov.style.top = b.y * curScale + "px";
  ov.style.width = b.width * curScale + "px";
  ov.style.height = b.height * curScale + "px";
  ov.innerHTML =
    '<div class="mv"></div>' +
    ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
      .map((d) => '<div class="hnd ' + d + '" data-d="' + d + '"></div>')
      .join("");
  stage.appendChild(ov);
  ov.querySelector(".mv").addEventListener("pointerdown", (e) => {
    e.stopPropagation();
    startDrag(e, "move");
  });
  ov.querySelectorAll(".hnd").forEach((h) =>
    h.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      startDrag(e, h.dataset.d);
    }),
  );
}
function startDrag(e, mode) {
  e.preventDefault();
  const l = curLayer();
  if (!l) return;
  const s = {
    x: e.clientX,
    y: e.clientY,
    bx: l.bbox.x,
    by: l.bbox.y,
    bw: l.bbox.width,
    bh: l.bbox.height,
    before: cloneBBox(l.bbox),
  };
  function mv(ev) {
    const dx = (ev.clientX - s.x) / curScale,
      dy = (ev.clientY - s.y) / curScale;
    let bx = s.bx,
      by = s.by,
      bw = s.bw,
      bh = s.bh;
    if (mode === "move") {
      bx = s.bx + dx;
      by = s.by + dy;
    } else {
      if (mode.indexOf("e") >= 0) bw = Math.max(4, s.bw + dx);
      if (mode.indexOf("s") >= 0) bh = Math.max(4, s.bh + dy);
      if (mode.indexOf("w") >= 0) {
        bw = Math.max(4, s.bw - dx);
        bx = s.bx + (s.bw - bw);
      }
      if (mode.indexOf("n") >= 0) {
        bh = Math.max(4, s.bh - dy);
        by = s.by + (s.bh - bh);
      }
    }
    l.bbox.x = Math.round(bx);
    l.bbox.y = Math.round(by);
    l.bbox.width = Math.round(bw);
    l.bbox.height = Math.round(bh);
    positionImg(l);
    drawSel();
    syncNums();
  }
  function up() {
    document.removeEventListener("pointermove", mv);
    document.removeEventListener("pointerup", up);
    recomputeSection(l);
    recordBBoxHistory(l, s.before, cloneBBox(l.bbox), mode === "move" ? "Di chuyển layer" : "Đổi kích thước layer");
    saveEdit(l.id, { bbox: l.bbox });
  }
  document.addEventListener("pointermove", mv);
  document.addEventListener("pointerup", up);
}
function recomputeSection(l) {
  const v = variant(),
    cy = l.bbox.y + l.bbox.height / 2,
    S = v.sections;
  let si = 0;
  S.forEach((s, i) => {
    if (s.y0 <= cy && cy < s.y1) si = i;
  });
  if (cy >= S[S.length - 1].y1) si = S.length - 1;
  l.section = si;
}
function normalizeLayerOrder(v) {
  v.layers.sort((a, b) => (a.z || 0) - (b.z || 0));
  assignLayerOrder(v);
}

function assignLayerOrder(v) {
  v.layers.forEach((layer, index) => {
    layer.z = index;
    layer.order = index;
  });
}

function commitLayerOrder(v) {
  const patches = {};
  v.layers.forEach((layer) => {
    patches[layer.id] = { z: layer.z };
  });
  saveEdits(patches);
}

function moveLayerToIndex(layerId, targetIndex) {
  const v = variant();
  normalizeLayerOrder(v);
  const currentIndex = v.layers.findIndex((layer) => layer.id === layerId);
  if (currentIndex < 0) return;
  targetIndex = Math.max(0, Math.min(v.layers.length - 1, targetIndex));
  if (targetIndex === currentIndex) return;
  const [layer] = v.layers.splice(currentIndex, 1);
  v.layers.splice(targetIndex, 0, layer);
  assignLayerOrder(v);
  commitLayerOrder(v);
  sel = layerId;
  render();
  selectLayer(layerId);
}

function treeItemLayerIds(v, item) {
  if (item.type === "layer") return [item.id];
  const groupIds = new Set([item.id]);
  let changed = true;
  while (changed) {
    changed = false;
    (v.nodes || []).forEach((node) => {
      if (groupIds.has(node.parent) && !groupIds.has(node.id)) {
        groupIds.add(node.id);
        changed = true;
      }
    });
  }
  return v.layers
    .filter((layer) => groupIds.has(layer.parent))
    .map((layer) => layer.id);
}

function moveTreeItemRelative(sourceItem, targetItem, place) {
  if (!sourceItem || !targetItem || sourceItem.parent !== targetItem.parent) return;
  const v = variant();
  normalizeLayerOrder(v);
  const sourceIds = new Set(treeItemLayerIds(v, sourceItem));
  const targetIds = new Set(treeItemLayerIds(v, targetItem));
  if (!sourceIds.size || !targetIds.size) return;
  const moving = v.layers.filter((layer) => sourceIds.has(layer.id));
  const remaining = v.layers.filter((layer) => !sourceIds.has(layer.id));
  const targetIndexes = remaining
    .map((layer, index) => (targetIds.has(layer.id) ? index : -1))
    .filter((index) => index >= 0);
  if (!targetIndexes.length) return;
  // Cay layer hien lop tren cung truoc, con mang canvas ve lop tren cung sau.
  const insertIndex = place === "before"
    ? Math.max(...targetIndexes) + 1
    : Math.min(...targetIndexes);
  remaining.splice(insertIndex, 0, ...moving);
  v.layers.splice(0, v.layers.length, ...remaining);
  assignLayerOrder(v);
  commitLayerOrder(v);
  draggedTreeItem = null;
  clearLayerDropMarkers();
  sel = sourceItem.type === "layer" ? sourceItem.id : null;
  render();
  if (sel) selectLayer(sel);
}

function bringFront() {
  const l = curLayer();
  if (l) moveLayerToIndex(l.id, variant().layers.length - 1);
}
function moveForward() {
  const l = curLayer();
  if (!l) return;
  normalizeLayerOrder(variant());
  moveLayerToIndex(l.id, variant().layers.indexOf(l) + 1);
}
function moveBackward() {
  const l = curLayer();
  if (!l) return;
  normalizeLayerOrder(variant());
  moveLayerToIndex(l.id, variant().layers.indexOf(l) - 1);
}
function sendBack() {
  const l = curLayer();
  if (l) moveLayerToIndex(l.id, 0);
}
const LINK_ACTIONS = [
  ["", "(khong)"],
  ["download", "Tai game"],
  ["login", "Dang nhap"],
  ["register", "Dang ky"],
  ["topup", "Nap"],
  ["gift", "Nhan qua"],
  ["rules", "The le"],
  ["history", "Lich su"],
  ["social", "Facebook"],
  ["check", "Kiem tra"],
  ["custom", "Link tuy chinh"],
];
function inp(id, val, ph, st) {
  return (
    '<input id="' +
    id +
    '" value="' +
    esc(val || "") +
    '"' +
    (ph ? ' placeholder="' + ph + '"' : "") +
    ' style="' +
    (st || "") +
    '">'
  );
}
function ensurePanel() {
  const l = curLayer();
  const p = document.getElementById("selPanel");
  if (!l) {
    p.style.display = "none";
    return;
  }
  p.style.display = "block";
  const lk = l.link || {},
    td = l.textData;
  const actionOptions = LINK_ACTIONS.map(
    (item) => `<option value="${item[0]}"${(lk.action || "") === item[0] ? " selected" : ""}>${item[1]}</option>`,
  ).join("");
  const pops = curTab.indexOf("popup:") === 0 ? [] : popupChoices();
  const popupOptions = pops
    .map(
      (popup) => `<option value="${esc(popup.id)}"${(lk.popup || "") === popup.id ? " selected" : ""}>${popup.source === "inline" ? "[Trong PSD] " : ""}${esc(popup.name)}</option>`,
    )
    .join("");
  const fdef = ((l.asset || "").split("/").pop() || "").replace(/\.[^.]+$/, "");
  const fext = ((l.asset || "").match(/\.[^.]+$/) || [".webp"])[0];
  const FX_OPTS = [
    ["", "Không có hiệu ứng"],
    ["shine", "Lướt sáng"],
    ["shine-glow", "Lướt sáng + phát sáng"],
    ["glow", "Phát sáng"],
    ["float", "Trôi nhẹ"],
    ["float-glow", "Trôi + phát sáng"],
    ["btn", "Nút: shine + hover + glow"],
  ];
  const fxOptions = FX_OPTS.map(
    (item) => `<option value="${item[0]}"${(l.fx || "") === item[0] ? " selected" : ""}>${item[1]}</option>`,
  ).join("");
  const layerKind = td ? "Text layer" : l.group ? "Merged group" : "Image layer";
  const stackIndex = variant().layers.indexOf(l);
  const atBack = stackIndex <= 0 ? " disabled" : "";
  const atFront = stackIndex >= variant().layers.length - 1 ? " disabled" : "";

  let h = `
    <header class="inspectorLayerHead">
      <span class="layerGlyph">${td ? "T" : l.group ? "G" : "◇"}</span>
      <span class="layerIdentity">
        <small>${layerKind}</small>
        <b title="${esc(l.name)}">${esc(l.name)}</b>
      </span>
      ${l.group ? `<span class="layerBadge">${l.count} lớp</span>` : ""}
    </header>

    <section class="inspectorSection">
      <div class="inspectorSectionHead"><span>01</span><b>Transform</b></div>
      <div class="transformGrid">
        <label class="inspectorField"><span>X</span><input class="num" id="sX" inputmode="numeric"></label>
        <label class="inspectorField"><span>Y</span><input class="num" id="sY" inputmode="numeric"></label>
        <label class="inspectorField"><span>W</span><input class="num" id="sW" inputmode="numeric"></label>
        <label class="inspectorField"><span>H</span><input class="num" id="sH" inputmode="numeric"></label>
      </div>
      <div class="layerOrderActions">
        <button class="sm" id="sFront" title="Đưa layer lên trên cùng"${atFront}>⇈ Trên cùng</button>
        <button class="sm" id="sForward" title="Đưa layer tiến lên một lớp"${atFront}>↑ Tiến 1 lớp</button>
        <button class="sm ghost" id="sBackward" title="Đưa layer lùi xuống một lớp"${atBack}>↓ Lùi 1 lớp</button>
        <button class="sm ghost" id="sBack" title="Đưa layer xuống dưới cùng"${atBack}>⇊ Dưới cùng</button>
        <button class="ghost sm iconAction" id="sDesel" title="Bỏ chọn layer">Esc</button>
      </div>
    </section>`;

  if (td) {
    h += `
      <section class="inspectorSection">
        <div class="inspectorSectionHead"><span>02</span><b>Nội dung chữ</b></div>
        <label class="inspectorSwitchRow">
          <span><b>Xuất chữ thật</b><small>Tốt hơn cho SEO và độ nét</small></span>
          <input type="checkbox" id="sAsText"${td.asText ? " checked" : ""}>
          <i></i>
        </label>
        <label class="inspectorField fullField"><span>Nội dung</span><textarea id="sTxt" rows="3">${esc(td.content || "")}</textarea></label>
        <div class="textStyleGrid">
          <label class="inspectorField"><span>Cỡ chữ</span><input class="num" id="sTsize" value="${esc(td.size || "")}"></label>
          <label class="inspectorField colorField"><span>Màu</span><input type="color" id="sTcolor" value="${td.color || "#ffffff"}"></label>
        </div>
      </section>`;
  }

  h += `
    <section class="inspectorSection">
      <div class="inspectorSectionHead"><span>${td ? "03" : "02"}</span><b>Interaction & SEO</b></div>
      <label class="inspectorField fullField"><span>Hành động</span><select id="sAct">${actionOptions}</select></label>
      <label class="inspectorSwitchRow compactSwitch">
        <span><b>Vai trò button</b><small>Thêm trạng thái hover và con trỏ</small></span>
        <input type="checkbox" id="sBtn"${lk.button ? " checked" : ""}>
        <i></i>
      </label>
      <label class="inspectorField fullField"><span>Đường dẫn</span><input id="sUrl" value="${esc(lk.url || "")}" placeholder="https://example.com"></label>
      ${pops.length ? `<label class="inspectorField fullField"><span>Mở popup</span><select id="sPopup"><option value="">Không mở popup</option>${popupOptions}</select></label>` : ""}
      <label class="inspectorField fullField"><span>Alt text</span><input id="sAlt" value="${esc(l.alt || "")}" placeholder="Mô tả nội dung hình ảnh"></label>
    </section>

    <section class="inspectorSection">
      <div class="inspectorSectionHead"><span>${td ? "04" : "03"}</span><b>Asset đầu ra</b></div>
      <label class="inspectorField fullField"><span>Tên file</span><span class="fileNameControl"><input id="sFname" value="${esc(l.fname || "")}" placeholder="${esc(fdef)}"><em>${esc(fext)}</em></span></label>
      <p class="fieldHelp">Để trống để giữ tên mặc định <code>${esc(fdef + fext)}</code>.</p>
    </section>

    <section class="inspectorSection effectSection">
      <div class="inspectorSectionHead"><span>${td ? "05" : "04"}</span><b>Hiệu ứng</b></div>
      <label class="inspectorField fullField"><span>Preset React/Next</span><select id="sFx">${fxOptions}</select></label>
      <p class="fieldHelp">Hiệu ứng được áp trực tiếp cho layer khi xuất project.</p>
    </section>`;

  p.innerHTML = h;
  syncNums();
  ["sX", "sY", "sW", "sH"].forEach((k) => {
    document.getElementById(k).onchange = onNumChange;
  });
  document.getElementById("sFront").onclick = bringFront;
  document.getElementById("sForward").onclick = moveForward;
  document.getElementById("sBackward").onclick = moveBackward;
  document.getElementById("sBack").onclick = sendBack;
  document.getElementById("sDesel").onclick = deselect;
  if (td) {
    const upT = () => {
      td.content = document.getElementById("sTxt").value;
      td.size = +document.getElementById("sTsize").value || td.size;
      td.color = document.getElementById("sTcolor").value;
      td.asText = document.getElementById("sAsText").checked;
      saveEdit(l.id, {
        text: {
          content: td.content,
          size: td.size,
          color: td.color,
          asText: td.asText,
        },
      });
      render();
      selectLayer(l.id);
    };
    ["sAsText", "sTxt", "sTsize", "sTcolor"].forEach(
      (k) => (document.getElementById(k).onchange = upT),
    );
  }
  const upL = () => {
    l.link = l.link || {};
    l.link.action = document.getElementById("sAct").value || null;
    l.link.url = document.getElementById("sUrl").value.trim() || null;
    l.link.button = document.getElementById("sBtn").checked;
    const sp = document.getElementById("sPopup");
    if (sp) l.link.popup = sp.value || null;
    saveEdit(l.id, {
      link: {
        action: l.link.action,
        url: l.link.url,
        button: l.link.button,
        popup: l.link.popup || null,
      },
    });
  };
  ["sAct", "sUrl", "sBtn", "sPopup"].forEach((k) => {
    const el = document.getElementById(k);
    if (el) el.onchange = upL;
  });
  document.getElementById("sAlt").onchange = () => {
    l.alt = document.getElementById("sAlt").value;
    saveEdit(l.id, { alt: l.alt });
  };
  const sf = document.getElementById("sFname");
  if (sf)
    sf.onchange = () => {
      const v = sf.value.trim();
      l.fname = v;
      saveEdit(l.id, { fname: v || null });
    };
  const sfx = document.getElementById("sFx");
  if (sfx)
    sfx.onchange = () => {
      l.fx = sfx.value;
      saveEdit(l.id, { fx: l.fx || null });
      render();
    };
}
function syncNums() {
  const l = curLayer();
  if (!l) return;
  const b = l.bbox;
  const set = (k, val) => {
    const el = document.getElementById(k);
    if (el && document.activeElement !== el) el.value = Math.round(val);
  };
  set("sX", b.x);
  set("sY", b.y);
  set("sW", b.width);
  set("sH", b.height);
}
function onNumChange() {
  const l = curLayer();
  if (!l) return;
  const before = cloneBBox(l.bbox);
  const g = (k) => Math.round(+(document.getElementById(k) || {}).value || 0);
  l.bbox.x = g("sX");
  l.bbox.y = g("sY");
  l.bbox.width = Math.max(1, g("sW"));
  l.bbox.height = Math.max(1, g("sH"));
  positionImg(l);
  drawSel();
  recomputeSection(l);
  recordBBoxHistory(l, before, cloneBBox(l.bbox), "Nhập transform");
  saveEdit(l.id, { bbox: l.bbox });
}
function saveEdits(patches) {
  fetch("/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: JOB,
      variant: curTab,
      patch: patches,
    }),
  }).catch(() => {});
}
function saveEdit(id, patch) {
  saveEdits({ [id]: patch });
}
let _saveT = null,
  _savePend = null;
function saveEditDebounced(id, patch) {
  _savePend = { id, patch };
  clearTimeout(_saveT);
  _saveT = setTimeout(() => {
    if (_savePend) saveEdit(_savePend.id, _savePend.patch);
  }, 350);
}
// click nen preview: chon layer roi press-drag di chuyen; click nen trong -> bo chon
document.getElementById("stage").addEventListener("pointerdown", function (e) {
  if (groupMode) return;
  if (e.target.closest(".selov")) return;
  const img = e.target.closest(".lyr");
  if (!img) {
    deselect();
    return;
  }
  const id = img.dataset.id;
  if (id !== sel) selectLayer(id, true);
  startDrag(e, "move");
});
// phim mui ten nhich 1px (Shift=10px), Esc bo chon
document.addEventListener("keydown", function (e) {
  if (!sel || groupMode) return;
  if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName || "")) return;
  if (e.key === "Escape") {
    deselect();
    return;
  }
  const l = curLayer();
  if (!l) return;
  const before = cloneBBox(l.bbox);
  const step = e.shiftKey ? 10 : 1;
  let m = true;
  if (e.key === "ArrowLeft") l.bbox.x -= step;
  else if (e.key === "ArrowRight") l.bbox.x += step;
  else if (e.key === "ArrowUp") l.bbox.y -= step;
  else if (e.key === "ArrowDown") l.bbox.y += step;
  else m = false;
  if (m) {
    e.preventDefault();
    positionImg(l);
    drawSel();
    syncNums();
    recomputeSection(l);
    recordBBoxHistory(l, before, cloneBBox(l.bbox), "Dịch layer bằng bàn phím");
    saveEditDebounced(l.id, { bbox: l.bbox });
  }
});

// ---- GOP LAYER ----
document.getElementById("grpMode").onclick = () => {
  groupMode = !groupMode;
  document.getElementById("grpMode").classList.toggle("active", groupMode);
  document.getElementById("edHint").textContent = groupMode
    ? "Chế độ GỘP: bấm vào các ảnh muốn gộp, rồi bấm 'Gộp thành 1 ảnh'. Bấm 'tách' để bỏ nhóm."
    : "Bấm vào ảnh để chọn → kéo để di chuyển, kéo góc để đổi kích thước, phím mũi tên để nhích. Bỏ tích = không xuất ảnh đó.";
  if (!groupMode) groupSel[curTab].clear();
  sel = null;
  render();
};
document.getElementById("grpClear").onclick = () => {
  groupSel[curTab].clear();
  render();
};
document.getElementById("grpDo").onclick = () => {
  const ids = [...groupSel[curTab]];
  const nm = document.getElementById("grpName").value.trim();
  doGroup(ids, nm);
};
async function doGroup(members, name) {
  // BO layer da AN (tat mat) khoi phep gop -> khong dinh anh an vao ban ghep
  members = (members || []).filter((id) => !disabled[curTab].has(id));
  if (members.length < 2) {
    alert("Hãy chọn ít nhất 2 ảnh (đang hiện) để gộp.");
    return;
  }
  const btn = document.getElementById("grpDo");
  if (btn) btn.disabled = true;
  try {
    const r = await fetch("/group", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: JOB,
        variant: curTab,
        members,
        name: name || "Group",
      }),
    }).then((x) => x.json());
    if (r.error) {
      alert("Lỗi gộp: " + r.error);
      return;
    }
    MAN = r.manifest;
    groupSel[curTab].clear();
    document.getElementById("grpName").value = "";
    render();
  } catch (e) {
    alert("Lỗi gộp: " + e);
  } finally {
    if (btn) btn.disabled = false;
  }
}
async function doUngroup(gid) {
  const r = await fetch("/ungroup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: JOB, variant: curTab, group_id: gid }),
  }).then((x) => x.json());
  if (r.error) {
    alert("Lỗi tách: " + r.error);
    return;
  }
  MAN = r.manifest;
  render();
}

document.getElementById("restart").onclick = () => {
  editor.classList.remove("show");
  exportPanel.classList.remove("show");
  document.getElementById("step1").style.display = "block";
  sel = null;
  layerQuery = "";
  setStep(1);
};

// ---- Xem thu web (render slices theo lua chon hien tai) ----
const goReview = document.getElementById("goReview"),
  reviewBox = document.getElementById("reviewBox"),
  reviewStep = document.getElementById("reviewStep"),
  reviewBar = document.getElementById("reviewBar"),
  reviewFrame = document.getElementById("reviewFrame"),
  reviewErr = document.getElementById("reviewErr"),
  reviewOpen = document.getElementById("reviewOpen");
let reviewUrl = null;
goReview.onclick = async () => {
  const body = {
    job_id: JOB,
    swiper: document.getElementById("swiper").checked,
    disabled_desktop: [...(disabled.desktop || [])],
    disabled_mobile: [...(disabled.mobile || [])],
  };
  goReview.disabled = true;
  beginJobTask("preview", "Đang dựng bản xem thử");
  reviewBox.style.display = "block";
  reviewErr.textContent = "";
  reviewBar.style.display = "block";
  reviewFrame.style.display = "none";
  reviewOpen.style.display = "none";
  reviewStep.textContent = "Đang gửi yêu cầu…";
  reviewBox.scrollIntoView({ behavior: "smooth", block: "start" });
  let r;
  try {
    r = await (
      await fetch("/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    ).json();
  } catch (e) {
    reviewStep.textContent = "Lỗi: " + e;
    goReview.disabled = false;
    finishJobTask("Xem thử thất bại", true);
    return;
  }
  if (r.error) {
    reviewStep.textContent = "Lỗi: " + r.error;
    goReview.disabled = false;
    finishJobTask(r.error, true);
    toast(r.error, "error");
    return;
  }
  pollReview();
};
async function pollReview() {
  let s;
  try {
    s = await (await fetch("/status/" + JOB)).json();
  } catch (e) {
    setTimeout(pollReview, 1200);
    return;
  }
  reviewStep.textContent = s.step || "Đang xử lý…";
  updateJobTask(s.step || "Đang dựng bản xem thử");
  if (s.status === "done" && s.phase === "preview" && s.preview) {
    reviewUrl = s.preview + "?t=" + Date.now();
    reviewBar.style.display = "none";
    reviewFrame.style.display = "block";
    reviewFrame.src = reviewUrl;
    reviewStep.textContent = "\u2713 Bản xem thử (theo ảnh đang chọn)";
    reviewOpen.style.display = "inline-block";
    goReview.disabled = false;
    finishJobTask("Job sẵn sàng");
    return;
  }
  if (s.status === "error" && s.phase === "preview") {
    reviewBar.style.display = "none";
    reviewErr.textContent = (s.error || "") + "\n" + (s.trace || "");
    goReview.disabled = false;
    finishJobTask("Xem thử thất bại", true);
    return;
  }
  setTimeout(pollReview, 1200);
}
reviewOpen.onclick = () => {
  if (reviewUrl) window.open(reviewUrl, "_blank");
};

// ---- BUOC 3: export ----
goExport.onclick = async () => {
  const fmt = document.querySelector("input[name=fmt]:checked").value;
  const lang =
    (document.querySelector("input[name=lang]:checked") || {}).value || "js";
  const body = {
    job_id: JOB,
    format: fmt,
    lang: lang,
    swiper: document.getElementById("swiper").checked,
    disabled_desktop: [...(disabled.desktop || [])],
    disabled_mobile: [...(disabled.mobile || [])],
    disabled_popup: disabledPopupMap(),
  };
  [
    "swiper_lib",
    "env_config",
    "nav_menu",
    "popups",
    "ai_enhance",
    "fluid",
    "fx",
    "fx_reveal",
  ].forEach((k) => (body[k] = document.getElementById(k).checked));
  goExport.disabled = true;
  beginJobTask("export", "Đang xuất web");
  exportPanel.classList.add("show");
  exProgress.style.display = "block";
  result.style.display = "none";
  exStep.textContent = "Đang gửi yêu cầu…";
  exportPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  let r;
  try {
    const resp = await fetch("/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    r = await resp.json();
  } catch (e) {
    exStep.textContent = "Lỗi: " + e;
    goExport.disabled = false;
    finishJobTask("Xuất web thất bại", true);
    return;
  }
  if (r.error) {
    exStep.textContent = "Lỗi: " + r.error;
    goExport.disabled = false;
    finishJobTask(r.error, true);
    toast(r.error, "error");
    return;
  }
  pollExport();
};

async function pollExport() {
  let s;
  try {
    s = await (await fetch("/status/" + JOB)).json();
  } catch (e) {
    setTimeout(pollExport, 1500);
    return;
  }
  exStep.textContent = s.step || "Đang xử lý…";
  updateJobTask(s.step || "Đang xuất web");
  if (s.status === "done" && s.phase === "export") {
    showResult(s);
    goExport.disabled = false;
    finishJobTask("Job sẵn sàng");
    loadRecentJobs();
    return;
  }
  if (s.status === "error") {
    exProgress.style.display = "none";
    result.style.display = "block";
    result.innerHTML =
      '<b style="color:#fca5a5">Lỗi khi xuất:</b><div class="err">' +
      (s.error || "") +
      "\n" +
      (s.trace || "") +
      "</div>";
    goExport.disabled = false;
    finishJobTask("Xuất web thất bại", true);
    loadRecentJobs();
    return;
  }
  setTimeout(pollExport, 1500);
}

function showResult(s) {
  setStep(3);
  exProgress.style.display = "none";
  result.style.display = "block";
  let html =
    '<b style="color:#4ade80;font-size:16px">\u2705 Xuất thành công!</b> ';
  if (s.download)
    html +=
      '<a class="dl" href="' + s.download + '">\u2B07 Tải ZIP kết quả</a>';
  if (s.preview) {
    html += '<iframe src="' + s.preview + "?t=" + Date.now() + '"></iframe>';
  } else if (s.files && s.files.length) {
    const isProj = s.format === "react" || s.format === "next";
    if (isProj) {
      html +=
        '<button id="goBuild" class="dl" style="border:0;cursor:pointer">\uD83D\uDD28 Build &amp; Xem trước (npm)</button>';
      html +=
        '<div id="buildBox" style="display:none;margin-top:10px">' +
        '<div id="buildBar"><div style="color:var(--muted);font-size:13px" id="buildStep"></div><div class="bar"><i></i></div></div>' +
        '<iframe id="buildFrame" style="display:none"></iframe>' +
        '<a id="buildOpen" style="display:none" class="dl" target="_blank">\u2197 Mở tab mới</a>' +
        '<pre id="buildLog" class="err" style="display:none;max-height:180px;overflow:auto"></pre>' +
        "</div>";
    }
    html +=
      '<div class="files">' +
      s.files.join("<br>") +
      "</div>" +
      '<p style="color:#94a3b8;font-size:13px">Đã tạo project ' +
      (s.format === "next" ? "Next.js" : "React") +
      ". " +
      (isProj
        ? "Bấm <b>Build &amp; Xem trước</b> để chạy ngay, hoặc giải nén ZIP rồi "
        : "Giải nén ZIP rồi ") +
      "chạy: <code>npm install &amp;&amp; npm run dev</code></p>";
  }
  result.innerHTML = html;
  const gb = document.getElementById("goBuild");
  if (gb) gb.onclick = startBuild;
}

let buildUrl = null;
async function startBuild() {
  const gb = document.getElementById("goBuild");
  const box = document.getElementById("buildBox"),
    bar = document.getElementById("buildBar"),
    step = document.getElementById("buildStep"),
    frame = document.getElementById("buildFrame"),
    openBtn = document.getElementById("buildOpen"),
    log = document.getElementById("buildLog");
  gb.disabled = true;
  beginJobTask("build", "Đang build project");
  box.style.display = "block";
  bar.style.display = "block";
  frame.style.display = "none";
  openBtn.style.display = "none";
  log.style.display = "none";
  step.textContent = "Đang gửi yêu cầu…";
  let r;
  try {
    r = await (
      await fetch("/build_preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: JOB }),
      })
    ).json();
  } catch (e) {
    step.textContent = "Lỗi: " + e;
    gb.disabled = false;
    finishJobTask("Build thất bại", true);
    return;
  }
  if (r.error) {
    step.textContent = "Lỗi: " + r.error;
    gb.disabled = false;
    finishJobTask(r.error, true);
    toast(r.error, "error");
    return;
  }
  pollBuild();
}
async function pollBuild() {
  const gb = document.getElementById("goBuild");
  const bar = document.getElementById("buildBar"),
    step = document.getElementById("buildStep"),
    frame = document.getElementById("buildFrame"),
    openBtn = document.getElementById("buildOpen"),
    log = document.getElementById("buildLog");
  let s;
  try {
    s = await (await fetch("/status/" + JOB)).json();
  } catch (e) {
    setTimeout(pollBuild, 1500);
    return;
  }
  const b = s.build || {};
  step.textContent = b.step || "Đang xử lý…";
  updateJobTask(b.step || "Đang build project");
  if (b.status === "done" && b.url) {
    buildUrl = b.url;
    bar.style.display = "none";
    frame.style.display = "block";
    frame.src = buildUrl;
    openBtn.style.display = "inline-block";
    openBtn.href = buildUrl;
    if (gb) gb.disabled = false;
    finishJobTask("Job sẵn sàng");
    loadRecentJobs();
    return;
  }
  if (b.status === "error") {
    bar.style.display = "none";
    if (b.log) {
      log.style.display = "block";
      log.textContent = (b.error || "") + "\n\n" + b.log;
    } else step.textContent = "Lỗi: " + (b.error || "");
    if (gb) gb.disabled = false;
    finishJobTask("Build thất bại", true);
    loadRecentJobs();
    return;
  }
  setTimeout(pollBuild, 1500);
}
