/* Tuong tac bo sung cho workspace editor toan man hinh. */
(() => {
  const canvasDock = document.querySelector(".canvasDock");
  const fitButton = document.getElementById("fitCanvas");
  const countBadge = document.getElementById("layerCountBadge");
  if (!canvasDock || !fitButton) return;

  const baseRender = render;
  if (typeof baseRender === "function") {
    render = function renderEditorShell() {
      baseRender();
      const current = typeof variant === "function" ? variant() : null;
      const hidden = disabled[curTab];
      if (countBadge && current) {
        const hiddenCount = hidden ? hidden.size : 0;
        countBadge.textContent = `${current.layers.length - hiddenCount}/${current.layers.length}`;
      }
    };
  }

  fitButton.addEventListener("click", () => {
    previewZoom = 1;
    render();
  });

  canvasDock.addEventListener("wheel", (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    previewZoom = Math.max(
      0.5,
      Math.min(3, previewZoom + (event.deltaY < 0 ? 0.1 : -0.1)),
    );
    render();
  }, { passive: false });

  let spaceHeld = false;
  let pan = null;

  document.addEventListener("keydown", (event) => {
    if (event.code !== "Space" || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName || "")) return;
    spaceHeld = true;
    canvasDock.classList.add("spaceHeld");
    event.preventDefault();
  });

  document.addEventListener("keyup", (event) => {
    if (event.code !== "Space") return;
    spaceHeld = false;
    pan = null;
    canvasDock.classList.remove("spaceHeld", "isPanning");
  });

  canvasDock.addEventListener("pointerdown", (event) => {
    if (!spaceHeld) return;
    event.preventDefault();
    event.stopPropagation();
    pan = {
      x: event.clientX,
      y: event.clientY,
      left: canvasDock.scrollLeft,
      top: canvasDock.scrollTop,
    };
    canvasDock.setPointerCapture(event.pointerId);
    canvasDock.classList.add("isPanning");
  }, true);

  canvasDock.addEventListener("pointermove", (event) => {
    if (!pan) return;
    canvasDock.scrollLeft = pan.left - (event.clientX - pan.x);
    canvasDock.scrollTop = pan.top - (event.clientY - pan.y);
  });

  canvasDock.addEventListener("pointerup", (event) => {
    pan = null;
    canvasDock.classList.remove("isPanning");
    try {
      canvasDock.releasePointerCapture(event.pointerId);
    } catch (_) {
      // Pointer co the da duoc trinh duyet tu dong thu hoi.
    }
  });

  const editor = document.getElementById("editor");
  const layersButton = document.getElementById("toggleLayers");
  const inspectorButton = document.getElementById("toggleInspector");
  const dockStorageKey = "psd2html.editor.docks";

  function saveDockState() {
    localStorage.setItem(dockStorageKey, JSON.stringify({
      layers: editor.classList.contains("layersCollapsed"),
      inspector: editor.classList.contains("inspectorCollapsed"),
    }));
  }

  function syncDockButtons() {
    const layersClosed = editor.classList.contains("layersCollapsed");
    const inspectorClosed = editor.classList.contains("inspectorCollapsed");
    layersButton.classList.toggle("active", !layersClosed);
    inspectorButton.classList.toggle("active", !inspectorClosed);
    layersButton.setAttribute("aria-pressed", String(!layersClosed));
    inspectorButton.setAttribute("aria-pressed", String(!inspectorClosed));
  }

  function toggleDock(name) {
    editor.classList.toggle(name === "layers" ? "layersCollapsed" : "inspectorCollapsed");
    syncDockButtons();
    saveDockState();
    requestAnimationFrame(() => render());
  }

  try {
    const saved = JSON.parse(localStorage.getItem(dockStorageKey) || "null");
    if (saved?.layers) editor.classList.add("layersCollapsed");
    if (saved?.inspector) editor.classList.add("inspectorCollapsed");
    if (!saved && matchMedia("(max-width: 920px)").matches) {
      editor.classList.add("inspectorCollapsed");
    }
  } catch (_) {
    // Bo qua preference bi hong va dung bo cuc mac dinh.
  }
  syncDockButtons();

  layersButton.addEventListener("click", () => toggleDock("layers"));
  inspectorButton.addEventListener("click", () => toggleDock("inspector"));

  document.addEventListener("keydown", (event) => {
    if (/INPUT|TEXTAREA|SELECT/.test(event.target.tagName || "") || event.ctrlKey || event.metaKey) return;
    const key = event.key.toLowerCase();
    if (key === "f") {
      previewZoom = 1;
      canvasScrollIntent = "preserve";
      render();
    } else if (key === "pagedown" && typeof showCanvasSection === "function") {
      showCanvasSection(curSec + 1);
    } else if (key === "pageup" && typeof showCanvasSection === "function") {
      if (curSec >= 0) showCanvasSection(curSec - 1);
      else return;
    } else if (key === "g") {
      document.getElementById("grpMode").click();
    } else if (key === "l") {
      toggleDock("layers");
    } else if (key === "i") {
      toggleDock("inspector");
    } else {
      return;
    }
    event.preventDefault();
  });
  const canvasMeta = document.getElementById("canvasMeta");
  const saveStatus = document.getElementById("saveStatus");
  const shellRender = render;
  render = function renderWithStatus() {
    shellRender();
    const current = variant();
    if (canvasMeta && current) {
      canvasMeta.textContent = `${current.canvas.width}×${current.canvas.height}px · ${curTab}`;
    }
  };

  const baseSaveEdit = saveEdit;
  saveEdit = function saveEditWithStatus(id, patch) {
    if (saveStatus) {
      saveStatus.textContent = "● Đang lưu";
      saveStatus.classList.remove("saveReady");
      saveStatus.classList.add("saveBusy");
    }
    baseSaveEdit(id, patch);
    clearTimeout(saveEditWithStatus.timer);
    saveEditWithStatus.timer = setTimeout(() => {
      if (!saveStatus) return;
      saveStatus.textContent = "● Đã lưu";
      saveStatus.classList.remove("saveBusy");
      saveStatus.classList.add("saveReady");
    }, 550);
  };
  const leftResizer = document.getElementById("leftResizer");
  const rightResizer = document.getElementById("rightResizer");
  const sizeStorageKey = "psd2html.editor.dockSizes";
  let resizeDock = null;

  try {
    const sizes = JSON.parse(localStorage.getItem(sizeStorageKey) || "null");
    if (sizes?.left) document.documentElement.style.setProperty("--dock-left", `${sizes.left}px`);
    if (sizes?.right) document.documentElement.style.setProperty("--dock-right", `${sizes.right}px`);
  } catch (_) {
    // Dung kich thuoc mac dinh neu preference khong hop le.
  }

  function startResize(side, event) {
    resizeDock = side;
    event.currentTarget.classList.add("dragging");
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  leftResizer.addEventListener("pointerdown", (event) => startResize("left", event));
  rightResizer.addEventListener("pointerdown", (event) => startResize("right", event));
  document.addEventListener("pointermove", (event) => {
    if (!resizeDock) return;
    const width = resizeDock === "left"
      ? Math.max(220, Math.min(460, event.clientX))
      : Math.max(280, Math.min(520, innerWidth - event.clientX));
    document.documentElement.style.setProperty(`--dock-${resizeDock}`, `${width}px`);
  });
  document.addEventListener("pointerup", () => {
    if (!resizeDock) return;
    document.querySelectorAll(".dockResizer.dragging").forEach((item) => item.classList.remove("dragging"));
    const styles = getComputedStyle(document.documentElement);
    localStorage.setItem(sizeStorageKey, JSON.stringify({
      left: parseInt(styles.getPropertyValue("--dock-left"), 10),
      right: parseInt(styles.getPropertyValue("--dock-right"), 10),
    }));
    resizeDock = null;
    render();
  });
  const reviewClose = document.getElementById("reviewClose");
  const reviewModal = document.getElementById("reviewBox");
  const reviewIframe = document.getElementById("reviewFrame");

  function closeReviewModal() {
    reviewModal.style.display = "none";
    reviewIframe.style.display = "none";
    reviewIframe.src = "about:blank";
    document.getElementById("goReview").disabled = false;
  }

  reviewClose.addEventListener("click", closeReviewModal);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || reviewModal.style.display === "none") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    closeReviewModal();
  }, true);
  const exportPanelClose = document.getElementById("exportPanelClose");
  const exportResultPanel = document.getElementById("exportPanel");

  function closeExportResult() {
    exportResultPanel.classList.remove("show");
  }

  exportPanelClose.addEventListener("click", closeExportResult);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !exportResultPanel.classList.contains("show")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    closeExportResult();
  }, true);})();
