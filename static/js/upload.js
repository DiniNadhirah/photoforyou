/* Upload page: make a thumbnail, encrypt everything, upload one file at a time. */
document.addEventListener("DOMContentLoaded", async () => {
  "use strict";
  const V = PFY.vault;
  const key = await V.requireKey();
  const root = document.getElementById("upload");
  const MAX = Number(root.dataset.maxMb) * 1024 * 1024;
  const form = document.getElementById("upload-form");
  const input = document.getElementById("files");
  const drop = document.getElementById("dropzone");
  const list = document.getElementById("file-list");
  const btn = document.getElementById("upload-btn");
  const folderInput = document.getElementById("folder");
  let queue = [];

  const EXT_TYPES = {
    jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif",
    heic: "image/heic", heif: "image/heif", mp4: "video/mp4", m4v: "video/mp4",
    mov: "video/quicktime", webm: "video/webm",
  };
  function mimeOf(file) {
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    const t = (file.type || "").toLowerCase();
    return EXT_TYPES[ext] || (Object.values(EXT_TYPES).includes(t) ? t : "");
  }

  // ---- thumbnails (made BEFORE encryption, then encrypted too) -----------
  function drawThumb(source, w, h) {
    const scale = Math.min(1, 480 / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.8));
  }
  async function imageThumb(file) {
    try {
      const bmp = await createImageBitmap(file);
      return await drawThumb(bmp, bmp.width, bmp.height);
    } catch (e) {
      return null; // e.g. HEIC in Chrome: no thumbnail, the original is still saved
    }
  }
  function videoThumb(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const v = document.createElement("video");
      const done = (blob) => { URL.revokeObjectURL(url); resolve(blob); };
      const timer = setTimeout(() => done(null), 8000);
      v.muted = true; v.playsInline = true; v.preload = "auto"; v.src = url;
      v.addEventListener("loadeddata", () => { v.currentTime = Math.min(1, (v.duration || 2) / 4); });
      v.addEventListener("seeked", async () => {
        clearTimeout(timer);
        try { done(await drawThumb(v, v.videoWidth, v.videoHeight)); } catch (e) { done(null); }
      });
      v.addEventListener("error", () => { clearTimeout(timer); done(null); });
    });
  }

  // ---- file list -------------------------------------------------------------
  function render() {
    list.innerHTML = "";
    queue.forEach((item) => {
      const li = document.createElement("li");
      li.className = "file-row " + item.state;
      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = item.file.name;
      const meta = document.createElement("span");
      meta.className = "file-meta";
      meta.textContent = PFY.formatBytes(item.file.size) + " · " + item.message;
      const bar = document.createElement("div");
      bar.className = "progress";
      const fill = document.createElement("span");
      fill.style.width = item.progress + "%";
      bar.appendChild(fill);
      li.append(name, meta, bar);
      list.appendChild(li);
    });
    btn.disabled = !queue.some((q) => q.state === "ready");
  }

  function addFiles(files) {
    for (const file of files) {
      const mime = mimeOf(file);
      let state = "ready", message = "Ready";
      if (!mime) { state = "error"; message = "Not a supported photo or video"; }
      else if (file.size > MAX) { state = "error"; message = "Too large (max " + root.dataset.maxMb + " MB)"; }
      queue.push({ file, mime, state, message, progress: 0 });
    }
    render();
  }

  input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

  // ---- upload ------------------------------------------------------------------
  function send(formData, item) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/media");
      xhr.setRequestHeader("X-CSRFToken", PFY.csrf());
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) { item.progress = Math.round((e.loaded / e.total) * 100); render(); }
      };
      xhr.onload = () => {
        let data = {};
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
        if (xhr.status === 401) { window.location.href = "/login"; return; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.error || "Upload failed (" + xhr.status + ")"));
      };
      xhr.onerror = () => reject(new Error("Network error. Check your connection."));
      xhr.send(formData);
    });
  }

  async function uploadOne(item, folder) {
    item.state = "busy"; item.message = "Encrypting…"; render();
    const kind = item.mime.startsWith("video/") ? "video" : "image";
    const thumb = kind === "video" ? await videoThumb(item.file) : await imageThumb(item.file);
    const data = await V.encryptBytes(key, await item.file.arrayBuffer());
    const fd = new FormData();
    fd.append("file", new Blob([data]), "file.bin");
    if (thumb) fd.append("thumb", new Blob([await V.encryptBytes(key, await thumb.arrayBuffer())]), "thumb.bin");
    fd.append("mime", item.mime);
    fd.append("size", String(item.file.size));
    fd.append("name_enc", await V.encryptText(key, item.file.name));
    fd.append("folder", folder);
    item.message = "Uploading…"; render();
    await send(fd, item);
    item.state = "done"; item.progress = 100; item.message = "Saved, encrypted"; render();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const folder = folderInput.value.trim();
    if (!folder) { folderInput.focus(); return; }
    btn.disabled = true;
    for (const item of queue.filter((q) => q.state === "ready")) {
      try { await uploadOne(item, folder); }
      catch (err) { item.state = "error"; item.message = err.message; render(); }
    }
    const ok = queue.filter((q) => q.state === "done").length;
    document.querySelectorAll(".upload-summary").forEach((el) => el.remove());
    const status = document.createElement("p");
    status.className = "upload-summary";
    status.append(document.createTextNode(ok + " file(s) uploaded. "));
    const a = document.createElement("a");
    a.href = "/";
    a.textContent = "Open gallery";
    status.appendChild(a);
    list.after(status);
  });
});
