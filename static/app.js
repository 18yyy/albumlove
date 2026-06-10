const state = {
  template: null,
  currentPdf: "figurinhas",
  currentPage: 1,
  selectedId: null,
  zoom: 1.2,
  dragging: null,
  pendingZoomAnchor: null,
  viewportPan: null,
  spacePressed: false,
  centerNextLoad: false,
  photos: [],
  liveForm: {},
};

const els = {
  figurinhasPdf: document.querySelector("#figurinhasPdf"),
  albumPdf: document.querySelector("#albumPdf"),
  photosFolder: document.querySelector("#photosFolder"),
  sessionPhotosInput: document.querySelector("#sessionPhotosInput"),
  uploadSessionPhotosBtn: document.querySelector("#uploadSessionPhotosBtn"),
  assetStatus: document.querySelector("#assetStatus"),
  previewImage: document.querySelector("#previewImage"),
  overlay: document.querySelector("#overlay"),
  previewWrap: document.querySelector(".preview-wrap"),
  previewStage: document.querySelector("#previewStage"),
  emptyState: document.querySelector("#emptyState"),
  pageLabel: document.querySelector("#pageLabel"),
  zoomInput: document.querySelector("#zoom"),
  zoomValue: document.querySelector("#zoomValue"),
  fieldForm: document.querySelector("#fieldForm"),
  downloadBtn: document.querySelector("#downloadBtn"),
  toast: document.querySelector("#toast"),
  fieldCount: document.querySelector("#fieldCount"),
};

const dataInputs = ["person1", "person2", "date", "customText"];

function toast(message, error = false) {
  els.toast.textContent = message;
  els.toast.style.background = error ? "#9f2f2f" : "#26211e";
  els.toast.classList.add("show");
  window.setTimeout(() => els.toast.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Erro na requisição");
  return data;
}

function pagesFor(pdf = state.currentPdf) {
  return state.template?.pdfs?.[pdf]?.pages || [{ page: 1, width: 1, height: 1 }];
}

function currentPageInfo() {
  return pagesFor().find((p) => p.page === state.currentPage) || pagesFor()[0];
}

function fieldsOnPage() {
  return (state.template?.fields || []).filter(
    (field) => field.pdf === state.currentPdf && Number(field.page) === Number(state.currentPage),
  );
}

function selectedField() {
  return (state.template?.fields || []).find((field) => field.id === state.selectedId);
}

function pageScale() {
  const info = currentPageInfo();
  return els.previewImage.naturalWidth ? els.previewImage.naturalWidth / info.width : state.zoom;
}

function updatePreview() {
  els.pageLabel.textContent = `Página ${state.currentPage} de ${pagesFor().length}`;
  els.zoomInput.value = String(state.zoom);
  els.zoomValue.textContent = `${Math.round(state.zoom * 100)}%`;
  els.previewImage.src = `/api/preview?pdf=${state.currentPdf}&page=${state.currentPage}&zoom=${state.zoom}`;
}

function clampZoom(value) {
  return Math.min(2.2, Math.max(0.7, Number(value)));
}

function setZoom(nextZoom, anchorEvent = null) {
  const previousZoom = state.zoom;
  const zoom = clampZoom(nextZoom);
  if (Math.abs(zoom - previousZoom) < 0.001) return;

  if (anchorEvent && els.previewImage.naturalWidth && els.previewImage.naturalHeight) {
    const wrapRect = els.previewWrap.getBoundingClientRect();
    const anchorX = els.previewWrap.scrollLeft + anchorEvent.clientX - wrapRect.left - els.previewStage.offsetLeft;
    const anchorY = els.previewWrap.scrollTop + anchorEvent.clientY - wrapRect.top - els.previewStage.offsetTop;
    state.pendingZoomAnchor = {
      ratioX: anchorX / els.previewImage.naturalWidth,
      ratioY: anchorY / els.previewImage.naturalHeight,
      viewportX: anchorEvent.clientX - wrapRect.left,
      viewportY: anchorEvent.clientY - wrapRect.top,
    };
  } else {
    state.pendingZoomAnchor = null;
  }

  state.zoom = Number(zoom.toFixed(2));
  updatePreview();
}

function renderOverlay() {
  els.overlay.innerHTML = "";
  const scale = pageScale();
  const hasTemplate = Boolean(state.template);
  els.emptyState.style.display = hasTemplate ? "none" : "block";
  els.previewImage.style.display = hasTemplate ? "block" : "none";
  els.fieldCount.textContent = `${fieldsOnPage().length} campos nesta página`;
  if (!hasTemplate) return;

  for (const field of fieldsOnPage()) {
    const box = document.createElement("div");
    box.className = `field-box ${field.type} ${field.id === state.selectedId ? "selected" : ""}`;
    box.style.left = `${field.x * scale}px`;
    box.style.top = `${field.y * scale}px`;
    box.style.width = `${field.width * scale}px`;
    box.style.height = `${field.height * scale}px`;
    box.style.transform = `rotate(${Number(field.rotation || 0)}deg)`;
    box.dataset.id = field.id;

    const content = document.createElement("div");
    content.className = "field-preview";
    if (field.type === "photo") {
      const img = document.createElement("img");
      img.src = photoSource(field);
      img.alt = "";
      img.draggable = false;
      img.style.opacity = String(field.previewOpacity ?? 0.72);
      img.style.transform = photoCropTransform(field);
      content.appendChild(img);
    } else {
      content.classList.add("text-preview");
      content.textContent = previewText(field);
      content.style.background = field.bgMode === "transparent" ? "transparent" : field.bgColor || "#ffffff";
      content.style.color = field.fontColor || "#2b2523";
      content.style.fontFamily = cssFontFamily(field.fontFamily);
      content.style.fontSize = `${Math.max(6, Number(field.fontSize || 16) * scale)}px`;
      content.style.justifyContent = alignToJustify(field.align);
      content.style.textAlign = field.align || "center";
      content.style.opacity = String(field.previewOpacity ?? 0.88);
    }
    box.appendChild(content);

    const label = document.createElement("span");
    label.textContent = `${field.type}${field.type === "photo" ? ` ${Number(field.photoIndex || 0) + 1}` : ""}`;
    label.className = "field-label";
    box.appendChild(label);

    const handle = document.createElement("div");
    handle.className = "resize-handle";
    box.appendChild(handle);

    const rotateHandle = document.createElement("div");
    rotateHandle.className = "rotate-handle";
    rotateHandle.title = "Arraste para girar";
    box.appendChild(rotateHandle);

    box.addEventListener("pointerdown", (event) => startDrag(event, field, "move"));
    handle.addEventListener("pointerdown", (event) => startDrag(event, field, "resize"));
    rotateHandle.addEventListener("pointerdown", (event) => startDrag(event, field, "rotate"));
    els.overlay.appendChild(box);
  }
}

function photoUrl(index) {
  const folder = encodeURIComponent(els.photosFolder.value || "fotos");
  return `/api/photo?index=${Number(index || 0)}&folder=${folder}`;
}

function photoSource(field) {
  return field.customImageData || photoUrl(field.photoIndex || 0);
}

function photoCropTransform(field) {
  const zoom = Number(field.cropZoom || 1);
  const x = Number(field.cropX || 0) * 45;
  const y = Number(field.cropY || 0) * 45;
  return `translate(${x}%, ${y}%) scale(${zoom})`;
}

function previewText(field) {
  if (field.type === "date") return document.querySelector("#date").value || "DATA AQUI";
  if (field.type === "text") return document.querySelector("#customText").value || "TEXTO AQUI";
  const one = document.querySelector("#person1").value || "Nome 1";
  const two = document.querySelector("#person2").value || "Nome 2";
  const label = String(field.label || "").toLowerCase();
  if (label.includes("2")) return two;
  if (label.includes("1")) return one;
  return [one, two].filter(Boolean).join(" & ");
}

function cssFontFamily(font) {
  const fonts = {
    segoe: '"Segoe UI", Arial, sans-serif',
    arial: 'Arial, sans-serif',
    "arial-bold": 'Arial, sans-serif',
    calibri: 'Calibri, Arial, sans-serif',
  };
  return fonts[font] || fonts.segoe;
}

function alignToJustify(align) {
  if (align === "left") return "flex-start";
  if (align === "right") return "flex-end";
  return "center";
}

function renderInspector() {
  const field = selectedField();
  if (!field) {
    els.fieldForm.className = "field-form muted";
    els.fieldForm.textContent = "Selecione uma caixa no preview.";
    return;
  }
  els.fieldForm.className = "field-form";
  els.fieldForm.innerHTML = `
    <label>Tipo
      <select data-key="type">
        ${["photo", "name", "date", "text"].map((type) => `<option value="${type}" ${field.type === type ? "selected" : ""}>${type}</option>`).join("")}
      </select>
    </label>
      <label>Rótulo
      <input data-key="label" value="${field.label || ""}">
    </label>
    <div class="type-strip">
      ${["photo", "name", "date", "text"].map((type) => `<button type="button" data-type-button="${type}" class="${field.type === type ? "active" : ""}">${type}</button>`).join("")}
    </div>
    <div class="form-grid">
      <label>X<input type="number" step="0.5" data-key="x" value="${field.x}"></label>
      <label>Y<input type="number" step="0.5" data-key="y" value="${field.y}"></label>
      <label>Largura<input type="number" step="0.5" data-key="width" value="${field.width}"></label>
      <label>Altura<input type="number" step="0.5" data-key="height" value="${field.height}"></label>
      <label>Página<input type="number" min="1" data-key="page" value="${field.page}"></label>
      <label>Foto nº<input type="number" min="1" data-key="photoIndexDisplay" value="${Number(field.photoIndex || 0) + 1}"></label>
      <label>Rotação<input type="number" step="1" data-key="rotation" value="${Number(field.rotation || 0)}"></label>
    </div>
    ${field.type === "photo" ? `
      <div class="photo-crop-panel">
        <div class="crop-preview">
          <img src="${photoSource(field)}" alt="">
        </div>
        <label>Foto personalizada
          <input id="customPhotoInput" type="file" accept="image/*">
        </label>
        <div class="inline-actions">
          <button id="clearCustomPhotoBtn" type="button" class="secondary small">Usar foto da lista</button>
        </div>
        <p class="microcopy">${field.customImageName ? `Usando: ${field.customImageName}` : "Sem upload: usando a foto pelo número."}</p>
        <label>Zoom da foto
          <input type="range" min="1" max="4" step="0.01" data-key="cropZoom" value="${field.cropZoom || 1}">
        </label>
        <div class="form-grid">
          <label>Crop X<input type="range" min="-1" max="1" step="0.01" data-key="cropX" value="${field.cropX || 0}"></label>
          <label>Crop Y<input type="range" min="-1" max="1" step="0.01" data-key="cropY" value="${field.cropY || 0}"></label>
        </div>
        <label>Opacidade no preview
          <input type="range" min="0.2" max="1" step="0.05" data-key="previewOpacity" value="${field.previewOpacity ?? 0.72}">
        </label>
      </div>
    ` : `
      <label>Opacidade no preview
        <input type="range" min="0.2" max="1" step="0.05" data-key="previewOpacity" value="${field.previewOpacity ?? 0.88}">
      </label>
    `}
    <label>Rotação
      <input type="range" min="-180" max="180" step="1" data-key="rotation" value="${normalizeRotation(field.rotation || 0)}">
    </label>
    <div class="form-grid">
      <label>Fonte<input type="number" step="1" data-key="fontSize" value="${field.fontSize || 16}"></label>
      <label>Cor<input type="color" data-key="fontColor" value="${field.fontColor || "#2b2523"}"></label>
      <label>Fundo<input type="color" data-key="bgColor" value="${field.bgColor || "#ffffff"}"></label>
      <label>Família
        <select data-key="fontFamily">
          ${["segoe", "arial", "arial-bold", "calibri"].map((font) => `<option value="${font}" ${(field.fontFamily || "segoe") === font ? "selected" : ""}>${font}</option>`).join("")}
        </select>
      </label>
    </div>
    <label>Modo do fundo
      <select data-key="bgMode">
        ${["fill", "transparent"].map((mode) => `<option value="${mode}" ${(field.bgMode || "fill") === mode ? "selected" : ""}>${mode === "fill" ? "cobrir com cor" : "transparente"}</option>`).join("")}
      </select>
    </label>
    <button id="sampleBgBtn" class="secondary">Capturar fundo original</button>
    <label>Alinhamento
      <select data-key="align">
        ${["left", "center", "right"].map((align) => `<option value="${align}" ${field.align === align ? "selected" : ""}>${align}</option>`).join("")}
      </select>
    </label>
    <button id="removeFieldBtn" class="danger">Remover campo</button>
  `;

  els.fieldForm.querySelectorAll("[data-key]").forEach((input) => {
    input.addEventListener("input", () => {
      const key = input.dataset.key;
      if (key === "photoIndexDisplay") {
        field.photoIndex = Math.max(0, Number(input.value || 1) - 1);
      } else if (["x", "y", "width", "height", "page", "fontSize", "rotation", "cropZoom", "cropX", "cropY", "previewOpacity"].includes(key)) {
        field[key] = Number(input.value || 0);
      } else {
        field[key] = input.value;
      }
      renderOverlay();
      renderCropPreview(field);
    });
  });

  els.fieldForm.querySelectorAll("[data-type-button]").forEach((button) => {
    button.addEventListener("click", () => {
      field.type = button.dataset.typeButton;
      renderOverlay();
      renderInspector();
    });
  });

  document.querySelector("#removeFieldBtn").addEventListener("click", () => {
    state.template.fields = state.template.fields.filter((item) => item.id !== field.id);
    state.selectedId = null;
    renderOverlay();
    renderInspector();
  });

  document.querySelector("#sampleBgBtn").addEventListener("click", async () => {
    try {
      const data = await api("/api/sample-background", {
        method: "POST",
        body: JSON.stringify({ field }),
      });
      field.bgColor = data.color;
      renderOverlay();
      renderInspector();
      toast(`Fundo capturado: ${data.color}`);
    } catch (error) {
      toast(error.message, true);
    }
  });

  const customPhotoInput = document.querySelector("#customPhotoInput");
  if (customPhotoInput) {
    customPhotoInput.addEventListener("change", () => {
      const file = customPhotoInput.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.addEventListener("load", () => {
        field.customImageData = String(reader.result);
        field.customImageName = file.name;
        field.previewOpacity = field.previewOpacity ?? 0.9;
        renderOverlay();
        renderInspector();
        toast("Foto personalizada aplicada neste campo.");
      });
      reader.readAsDataURL(file);
    });
  }

  const clearCustomPhotoBtn = document.querySelector("#clearCustomPhotoBtn");
  if (clearCustomPhotoBtn) {
    clearCustomPhotoBtn.addEventListener("click", () => {
      delete field.customImageData;
      delete field.customImageName;
      renderOverlay();
      renderInspector();
      toast("Campo voltou a usar a foto da lista.");
    });
  }
}

function renderCropPreview(field) {
  const img = document.querySelector(".crop-preview img");
  if (!img || field.type !== "photo") return;
  img.src = photoSource(field);
  img.style.transform = photoCropTransform(field);
  img.style.opacity = String(field.previewOpacity ?? 0.72);
}

function startDrag(event, field, mode) {
  if (state.viewportPan) return;
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  state.selectedId = field.id;
  const scale = pageScale();
  state.dragging = {
    mode,
    id: field.id,
    startX: event.clientX,
    startY: event.clientY,
    original: { ...field },
    scale,
  };
  if (mode === "rotate") {
    const center = fieldCenterOnScreen(field, scale);
    state.dragging.centerX = center.x;
    state.dragging.centerY = center.y;
    state.dragging.startAngle = pointerAngle(event, center.x, center.y);
  }
  event.currentTarget.setPointerCapture?.(event.pointerId);
  renderOverlay();
  renderInspector();
}

window.addEventListener("pointermove", (event) => {
  if (!state.dragging) return;
  const field = selectedField();
  if (!field) return;
  const dx = (event.clientX - state.dragging.startX) / state.dragging.scale;
  const dy = (event.clientY - state.dragging.startY) / state.dragging.scale;
  if (state.dragging.mode === "move") {
    field.x = Math.max(0, Number((state.dragging.original.x + dx).toFixed(2)));
    field.y = Math.max(0, Number((state.dragging.original.y + dy).toFixed(2)));
  } else {
    if (state.dragging.mode === "rotate") {
      const angle = pointerAngle(event, state.dragging.centerX, state.dragging.centerY);
      const next = state.dragging.original.rotation + angle - state.dragging.startAngle;
      field.rotation = Number(normalizeRotation(next).toFixed(1));
      renderOverlay();
      renderInspector();
      return;
    }
    field.width = Math.max(8, Number((state.dragging.original.width + dx).toFixed(2)));
    field.height = Math.max(8, Number((state.dragging.original.height + dy).toFixed(2)));
  }
  renderOverlay();
  renderInspector();
});

function fieldCenterOnScreen(field, scale) {
  const stageRect = els.overlay.getBoundingClientRect();
  return {
    x: stageRect.left + (field.x + field.width / 2) * scale,
    y: stageRect.top + (field.y + field.height / 2) * scale,
  };
}

function pointerAngle(event, centerX, centerY) {
  return (Math.atan2(event.clientY - centerY, event.clientX - centerX) * 180) / Math.PI;
}

function normalizeRotation(value) {
  let rotation = Number(value || 0);
  while (rotation > 180) rotation -= 360;
  while (rotation < -180) rotation += 360;
  return rotation;
}

function removeSelectedField(showToast = true) {
  if (!state.template || !state.selectedId) return false;
  const field = selectedField();
  if (!field) return false;
  state.template.fields = state.template.fields.filter((item) => item.id !== field.id);
  state.selectedId = null;
  renderOverlay();
  renderInspector();
  if (showToast) toast("Campo apagado.");
  return true;
}

function rotateSelected(delta) {
  const field = selectedField();
  if (!field) return toast("Selecione um campo primeiro.", true);
  field.rotation = normalizeRotation(Number(field.rotation || 0) + delta);
  renderOverlay();
  renderInspector();
}

function duplicateSelectedField() {
  const field = selectedField();
  if (!field || !state.template) return toast("Selecione um campo primeiro.", true);
  const copy = {
    ...field,
    id: `${field.pdf}-copy-${Date.now()}`,
    x: Number(field.x) + 12,
    y: Number(field.y) + 12,
    label: `${field.label || field.type} cópia`,
  };
  state.template.fields.push(copy);
  state.selectedId = copy.id;
  renderOverlay();
  renderInspector();
}

function nudgeSelected(dx, dy) {
  const field = selectedField();
  if (!field) return;
  field.x = Math.max(0, Number((Number(field.x) + dx).toFixed(2)));
  field.y = Math.max(0, Number((Number(field.y) + dy).toFixed(2)));
  renderOverlay();
  renderInspector();
}

function isTypingTarget(target) {
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName);
}

window.addEventListener("keydown", (event) => {
  if (isTypingTarget(event.target)) return;
  if (event.code === "Space") {
    state.spacePressed = true;
    els.previewWrap.classList.add("panning");
    event.preventDefault();
    return;
  }
  if (event.key === "Delete" || event.key === "Backspace") {
    if (removeSelectedField()) event.preventDefault();
  }
  if (event.key === "r" || event.key === "R") {
    rotateSelected(event.shiftKey ? -15 : 15);
    event.preventDefault();
  }
  const step = event.shiftKey ? 10 : 1;
  if (event.key === "ArrowLeft") {
    nudgeSelected(-step, 0);
    event.preventDefault();
  } else if (event.key === "ArrowRight") {
    nudgeSelected(step, 0);
    event.preventDefault();
  } else if (event.key === "ArrowUp") {
    nudgeSelected(0, -step);
    event.preventDefault();
  } else if (event.key === "ArrowDown") {
    nudgeSelected(0, step);
    event.preventDefault();
  }
});

window.addEventListener("keyup", (event) => {
  if (event.code === "Space") {
    state.spacePressed = false;
    if (!state.viewportPan) els.previewWrap.classList.remove("panning");
  }
});

els.previewWrap.addEventListener(
  "wheel",
  (event) => {
    if (isTypingTarget(event.target)) return;
    event.preventDefault();
    if (event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      els.previewWrap.scrollLeft += event.deltaY + event.deltaX;
      return;
    }
    const direction = event.deltaY > 0 ? -1 : 1;
    const factor = event.ctrlKey ? 0.06 : 0.1;
    setZoom(state.zoom + direction * factor, event);
  },
  { passive: false },
);

els.previewWrap.addEventListener("pointerdown", (event) => {
  const shouldPan = event.button === 1 || state.spacePressed;
  if (!shouldPan) return;
  event.preventDefault();
  state.viewportPan = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: els.previewWrap.scrollLeft,
    scrollTop: els.previewWrap.scrollTop,
  };
  els.previewWrap.classList.add("panning");
  els.previewWrap.setPointerCapture?.(event.pointerId);
});

els.previewWrap.addEventListener("pointermove", (event) => {
  if (!state.viewportPan) return;
  event.preventDefault();
  els.previewWrap.scrollLeft = state.viewportPan.scrollLeft - (event.clientX - state.viewportPan.startX);
  els.previewWrap.scrollTop = state.viewportPan.scrollTop - (event.clientY - state.viewportPan.startY);
});

function stopViewportPan() {
  state.viewportPan = null;
  if (!state.spacePressed) els.previewWrap.classList.remove("panning");
}

els.previewWrap.addEventListener("pointerup", stopViewportPan);
els.previewWrap.addEventListener("pointercancel", stopViewportPan);

window.addEventListener("pointerup", () => {
  state.dragging = null;
});

async function loadStatus() {
  const data = await api("/api/status");
  state.photos = data.photos || [];
  const source = data.usingSessionPhotos ? "enviadas nesta sessão" : `em ${data.photosFolder}`;
  els.assetStatus.textContent = `${data.photoCount} fotos ${source}. PDFs base na pasta do projeto.`;
  if (data.template) {
    state.template = data.template;
    updatePreview();
    renderInspector();
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () => reject(reader.error || new Error("Falha ao ler imagem.")));
    reader.readAsDataURL(file);
  });
}

async function uploadSessionPhotos() {
  const files = Array.from(els.sessionPhotosInput.files || []);
  if (!files.length) return toast("Selecione as fotos primeiro.", true);
  try {
    toast(`Enviando ${files.length} fotos...`);
    const photos = await Promise.all(
      files.map(async (file) => ({
        name: file.name,
        data: await readFileAsDataUrl(file),
      })),
    );
    const data = await api("/api/upload-photos", {
      method: "POST",
      body: JSON.stringify({ photos }),
    });
    state.photos = data.photos || [];
    toast(`${data.photoCount} fotos carregadas para esta sessão.`);
    await loadStatus();
    renderOverlay();
  } catch (error) {
    toast(error.message, true);
  }
}

function formPayload(mode = "final") {
  return {
    figurinhasPdf: els.figurinhasPdf.value,
    albumPdf: els.albumPdf.value,
    photosFolder: els.photosFolder.value,
    person1: document.querySelector("#person1").value,
    person2: document.querySelector("#person2").value,
    date: document.querySelector("#date").value,
    customText: document.querySelector("#customText").value,
    template: state.template,
    mode,
  };
}

document.querySelector("#analyzeBtn").addEventListener("click", async () => {
  try {
    toast("Analisando PDFs...");
    const data = await api("/api/analyze", { method: "POST", body: JSON.stringify(formPayload()) });
    state.template = data.template;
    state.currentPage = 1;
    state.selectedId = null;
    state.centerNextLoad = true;
    updatePreview();
    renderInspector();
    toast("Template criado. Ajuste as caixas antes de gerar.");
  } catch (error) {
    toast(error.message, true);
  }
});

document.querySelector("#saveBtn").addEventListener("click", async () => {
  if (!state.template) return toast("Analise os PDFs primeiro.", true);
  try {
    await api("/api/template", { method: "POST", body: JSON.stringify({ template: state.template }) });
    toast("Template salvo em template.json.");
  } catch (error) {
    toast(error.message, true);
  }
});

async function generate(mode) {
  if (!state.template) return toast("Analise os PDFs primeiro.", true);
  try {
    toast(mode === "base" ? "Gerando PDF base editável..." : "Gerando PDFs finais...");
    await api("/api/template", { method: "POST", body: JSON.stringify({ template: state.template }) });
    const data = await api("/api/generate", { method: "POST", body: JSON.stringify(formPayload(mode)) });
    els.downloadBtn.href = data.zip;
    els.downloadBtn.classList.remove("disabled");
    toast("Arquivos gerados na pasta output.");
  } catch (error) {
    toast(error.message, true);
  }
}

document.querySelector("#generateBtn").addEventListener("click", () => generate("final"));
document.querySelector("#baseBtn").addEventListener("click", () => generate("base"));
els.uploadSessionPhotosBtn.addEventListener("click", uploadSessionPhotos);
document.querySelector("#rotateLeftBtn").addEventListener("click", () => rotateSelected(-15));
document.querySelector("#rotateRightBtn").addEventListener("click", () => rotateSelected(15));
document.querySelector("#deleteFieldBtn").addEventListener("click", () => removeSelectedField());
document.querySelector("#duplicateFieldBtn").addEventListener("click", duplicateSelectedField);

document.querySelector("#addFieldBtn").addEventListener("click", () => {
  if (!state.template) return toast("Analise os PDFs primeiro.", true);
  const info = currentPageInfo();
  const field = {
    id: `${state.currentPdf}-manual-${Date.now()}`,
    pdf: state.currentPdf,
    page: state.currentPage,
    type: "photo",
    label: "Manual",
    x: Math.round(info.width * 0.25),
    y: Math.round(info.height * 0.25),
    width: Math.round(info.width * 0.25),
    height: Math.round(info.height * 0.18),
    rotation: 0,
    align: "center",
    fontSize: 16,
    fontColor: "#2b2523",
    bgColor: "#ffffff",
    bgMode: "fill",
    fontFamily: "segoe",
    cropZoom: 1,
    cropX: 0,
    cropY: 0,
    previewOpacity: 0.72,
    photoIndex: 0,
  };
  state.template.fields.push(field);
  state.selectedId = field.id;
  renderOverlay();
  renderInspector();
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    state.currentPdf = tab.dataset.pdf;
    state.currentPage = 1;
    state.selectedId = null;
    state.centerNextLoad = true;
    updatePreview();
    renderInspector();
  });
});

document.querySelector("#prevPage").addEventListener("click", () => {
  state.currentPage = Math.max(1, state.currentPage - 1);
  state.selectedId = null;
  state.centerNextLoad = true;
  updatePreview();
  renderInspector();
});

document.querySelector("#nextPage").addEventListener("click", () => {
  state.currentPage = Math.min(pagesFor().length, state.currentPage + 1);
  state.selectedId = null;
  state.centerNextLoad = true;
  updatePreview();
  renderInspector();
});

document.querySelector("#zoom").addEventListener("input", (event) => {
  setZoom(Number(event.target.value));
});

els.previewImage.addEventListener("load", () => {
  els.overlay.style.width = `${els.previewImage.naturalWidth}px`;
  els.overlay.style.height = `${els.previewImage.naturalHeight}px`;
  if (state.pendingZoomAnchor) {
    const anchor = state.pendingZoomAnchor;
    els.previewWrap.scrollLeft = els.previewStage.offsetLeft + anchor.ratioX * els.previewImage.naturalWidth - anchor.viewportX;
    els.previewWrap.scrollTop = els.previewStage.offsetTop + anchor.ratioY * els.previewImage.naturalHeight - anchor.viewportY;
    state.pendingZoomAnchor = null;
  } else if (state.centerNextLoad || !els.previewWrap.dataset.centeredOnce) {
    els.previewWrap.scrollLeft = Math.max(0, els.previewStage.offsetLeft - 64);
    els.previewWrap.scrollTop = Math.max(0, els.previewStage.offsetTop - 32);
    els.previewWrap.dataset.centeredOnce = "true";
    state.centerNextLoad = false;
  }
  renderOverlay();
});

dataInputs.forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("input", renderOverlay);
});

els.photosFolder.addEventListener("change", renderOverlay);

loadStatus().catch((error) => toast(error.message, true));
