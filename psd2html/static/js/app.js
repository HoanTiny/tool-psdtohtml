let filesD = [],
  filesM = [],
  filesP = [];
let JOB = null,
  MAN = null,
  curTab = "desktop";
const disabled = { desktop: new Set(), mobile: new Set() };
let groupMode = false;
const groupSel = { desktop: new Set(), mobile: new Set() };
const collapsed = { desktop: new Set(), mobile: new Set() }; // folder dang gap trong cay layer
let sel = null,
  curScale = 1; // layer dang chon (thao tac canvas) + he so scale preview
let layerQuery = ""; // tu khoa tim trong danh sach layer
let curSec = -1; // section dang xem rieng (-1 = tat ca)
let previewZoom = 1; // he so phong khung xem truoc (1 = vua be rong cot)
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
      return;
    }
  } catch (e) {
    parseStep.textContent = "Loi tai len: " + e;
    goParse.disabled = false;
    return;
  }
  if (r.error) {
    parseStep.textContent = "Loi: " + r.error;
    goParse.disabled = false;
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
  if (s.status === "done" && s.manifest) {
    MAN = s.manifest;
    goParse.disabled = false;
    parsePanel.classList.remove("show");
    openEditor();
    return;
  }
  if (s.status === "error") {
    parseErr.textContent = (s.error || "") + "\n" + (s.trace || "");
    goParse.disabled = false;
    return;
  }
  setTimeout(pollParse, 1500);
}

// ---- BUOC 2: editor ----
// State theo TAB (desktop/mobile/popup:<id>) -> tao Set moi cho moi tab khi mo editor.
function resetTabState(tabList) {
  [disabled, groupSel, collapsed].forEach((o) => {
    Object.keys(o).forEach((k) => delete o[k]);
    tabList.forEach((t) => (o[t] = new Set()));
  });
}
// Danh sach popup dang co (dung cho tab + dropdown 'Mo popup')
function popupsList() {
  return MAN && MAN.popups ? MAN.popups : [];
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
        render();
      };
      tabs.appendChild(b);
    });
  }
  // Co PSD popup -> he popup dung tu PSD (auto bat khi xuat), bao cho user biet
  const popChk = document.getElementById("popups");
  if (popChk) {
    const popLbl = popChk.parentElement.querySelector("span");
    if (popupsList().length) {
      popChk.checked = true;
      popChk.disabled = true;
      if (popLbl)
        popLbl.textContent =
          "Popup từ PSD (" +
          popupsList().length +
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
}

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
      off = dis.has(l.id) ? " off" : "",
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
  // sắp đúng thứ tự PSD: order lớn = lớp TRÊN (front) -> hiện trước; xen kẽ folder/layer đúng vị trí
  Object.keys(kids).forEach((k) =>
    kids[k].sort((a, b) => (b.n.order || 0) - (a.n.order || 0)),
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
    const kept = leaves.filter((l) => !dis.has(l.id)).length;
    const open = !col.has(g.id);
    const row = document.createElement("div");
    row.className = "frow";
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
      const allOn = leaves.every((l) => !dis.has(l.id));
      leaves.forEach((l) => {
        if (allOn) dis.add(l.id);
        else dis.delete(l.id);
      });
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
    on = !dis.has(l.id);
  const it = document.createElement("div");
  it.dataset.id = l.id;
  it.className =
    "item lrow" +
    (on ? "" : " off") +
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
    (l.group ? '<span class="gbadge">gộp ' + l.count + "</span>" : "") +
    "</span>" +
    (l.group
      ? '<span class="untie" title="Tách nhóm">&#9986; tách</span>'
      : "");
  it.querySelector(".eye").onclick = (e) => {
    e.stopPropagation();
    if (dis.has(l.id)) dis.delete(l.id);
    else dis.add(l.id);
    const off = dis.has(l.id);
    it.classList.toggle("off", off);
    it.querySelector(".eye").classList.toggle("off", off);
    it.querySelector(".eye").innerHTML = off ? "&#128584;" : "&#128065;";
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
  return it;
}
// đồng bộ ẩn/hiện lên preview (sau khi bật/tắt cả folder)
function applyVis() {
  const dis = disabled[curTab];
  document.querySelectorAll("#stage .lyr").forEach((im) => {
    im.classList.toggle("off", dis.has(im.dataset.id));
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
function updInfo() {
  const v = variant(),
    dis = disabled[curTab],
    tot = v.layers.length,
    kept =
      tot - [...dis].filter((id) => v.layers.some((l) => l.id === id)).length;
  document.getElementById("selInfo").textContent =
    "Giữ " + kept + "/" + tot + " ảnh";
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
function renderSecNav() {
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
function bringFront() {
  const l = curLayer();
  if (!l) return;
  l.z = Math.max(0, ...variant().layers.map((x) => x.z || 0)) + 1;
  saveEdit(l.id, { z: l.z });
  render();
  selectLayer(l.id);
}
function sendBack() {
  const l = curLayer();
  if (!l) return;
  l.z = Math.min(0, ...variant().layers.map((x) => x.z || 0)) - 1;
  saveEdit(l.id, { z: l.z });
  render();
  selectLayer(l.id);
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
  const pops = curTab.indexOf("popup:") === 0 ? [] : popupsList();
  const popupOptions = pops
    .map(
      (popup) => `<option value="${esc(popup.id)}"${(lk.popup || "") === popup.id ? " selected" : ""}>${esc(popup.name)}</option>`,
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
        <button class="sm" id="sFront" title="Đưa layer lên trên cùng">↑ Trên cùng</button>
        <button class="sm ghost" id="sBack" title="Đưa layer xuống dưới cùng">↓ Dưới cùng</button>
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
function saveEdit(id, patch) {
  fetch("/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      job_id: JOB,
      variant: curTab,
      patch: { [id]: patch },
    }),
  }).catch(() => {});
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
    return;
  }
  if (r.error) {
    reviewStep.textContent = "Lỗi: " + r.error;
    goReview.disabled = false;
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
  if (s.status === "done" && s.phase === "preview" && s.preview) {
    reviewUrl = s.preview + "?t=" + Date.now();
    reviewBar.style.display = "none";
    reviewFrame.style.display = "block";
    reviewFrame.src = reviewUrl;
    reviewStep.textContent = "\u2713 Bản xem thử (theo ảnh đang chọn)";
    reviewOpen.style.display = "inline-block";
    goReview.disabled = false;
    return;
  }
  if (s.status === "error" && s.phase === "preview") {
    reviewBar.style.display = "none";
    reviewErr.textContent = (s.error || "") + "\n" + (s.trace || "");
    goReview.disabled = false;
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
    return;
  }
  if (r.error) {
    exStep.textContent = "Lỗi: " + r.error;
    goExport.disabled = false;
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
  if (s.status === "done" && s.phase === "export") {
    showResult(s);
    goExport.disabled = false;
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
    return;
  }
  if (r.error) {
    step.textContent = "Lỗi: " + r.error;
    gb.disabled = false;
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
  if (b.status === "done" && b.url) {
    buildUrl = b.url;
    bar.style.display = "none";
    frame.style.display = "block";
    frame.src = buildUrl;
    openBtn.style.display = "inline-block";
    openBtn.href = buildUrl;
    if (gb) gb.disabled = false;
    return;
  }
  if (b.status === "error") {
    bar.style.display = "none";
    if (b.log) {
      log.style.display = "block";
      log.textContent = (b.error || "") + "\n\n" + b.log;
    } else step.textContent = "Lỗi: " + (b.error || "");
    if (gb) gb.disabled = false;
    return;
  }
  setTimeout(pollBuild, 1500);
}
