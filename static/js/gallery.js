/* Gallery: download encrypted thumbnails, decrypt them here, render folders. */
document.addEventListener("DOMContentLoaded", async () => {
  "use strict";
  const V = PFY.vault;
  const key = await V.requireKey();
  const $ = (id) => document.getElementById(id);
  const foldersEl = $("folders");
  const thumbUrls = new Map();   // media id -> decrypted thumbnail object URL
  const fullBlobs = new Map();   // media id -> decrypted original Blob
  let items = [];
  let usage = { used: 0, quota: 1 };

  // ------------------------------------------------------------- loading
  async function load() {
    try {
      const data = await PFY.api("/api/media");
      usage = data.usage;
      items = await Promise.all(data.items.map(async (it) => {
        try { it.name = await V.decryptText(key, it.name_enc); }
        catch (e) { it.name = "(cannot decrypt: wrong vault?)"; }
        return it;
      }));
      $("loading").hidden = true;
      render();
    } catch (err) {
      $("loading").textContent = err.message;
    }
  }

  // ------------------------------------------------------------- render
  function sortItems(list) {
    const mode = $("sort").value;
    const by = {
      newest: (a, b) => b.created_at.localeCompare(a.created_at),
      oldest: (a, b) => a.created_at.localeCompare(b.created_at),
      name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }),
      largest: (a, b) => b.size - a.size,
    }[mode];
    return list.slice().sort(by);
  }

  function renderUsage() {
    const pct = Math.min(100, (usage.used / usage.quota) * 100);
    $("usage").hidden = false;
    $("usage-fill").style.width = pct.toFixed(1) + "%";
    $("usage-fill").className = pct > 90 ? "full" : "";
    $("usage-text").textContent = PFY.formatBytes(usage.used) + " of " + PFY.formatBytes(usage.quota) +
      " used · " + items.length + " file" + (items.length === 1 ? "" : "s");
  }

  function render() {
    renderUsage();
    $("empty").hidden = items.length > 0;
    $("toolbar").hidden = items.length === 0;
    const q = $("search").value.trim().toLowerCase();
    const shown = items.filter((it) => !q || it.name.toLowerCase().includes(q));
    const groups = new Map();
    for (const it of sortItems(shown)) {
      if (!groups.has(it.folder)) groups.set(it.folder, []);
      groups.get(it.folder).push(it);
    }
    const names = [...groups.keys()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    foldersEl.innerHTML = "";
    if (q && shown.length === 0) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "No files match “" + q + "”.";
      foldersEl.appendChild(p);
    }
    for (const name of names) foldersEl.appendChild(folderSection(name, groups.get(name)));
    $("folder-list").innerHTML = "";
    [...new Set(items.map((i) => i.folder))].forEach((f) => {
      const o = document.createElement("option");
      o.value = f;
      $("folder-list").appendChild(o);
    });
  }

  function folderSection(name, list) {
    const sec = document.createElement("section");
    sec.className = "folder";
    const head = document.createElement("div");
    head.className = "folder-head";
    const h = document.createElement("h2");
    h.textContent = name;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = list.length;
    h.appendChild(count);
    const add = document.createElement("a");
    add.className = "btn small";
    add.href = "/upload?folder=" + encodeURIComponent(name);
    add.textContent = "+ Add";
    head.append(h, add);
    const grid = document.createElement("div");
    grid.className = "grid";
    list.forEach((it) => grid.appendChild(tile(it)));
    sec.append(head, grid);
    return sec;
  }

  function tile(it) {
    const card = document.createElement("article");
    card.className = "tile";
    const thumb = document.createElement("button");
    thumb.type = "button";
    thumb.className = "thumb";
    thumb.setAttribute("aria-label", "Open " + it.name);
    thumb.addEventListener("click", () => openViewer(it));
    if (it.thumb_url) {
      const img = document.createElement("img");
      img.alt = "";
      if (thumbUrls.has(it.id)) img.src = thumbUrls.get(it.id);
      else queueThumb(it, img);
      thumb.appendChild(img);
    } else {
      const ph = document.createElement("span");
      ph.className = "placeholder";
      ph.textContent = it.kind === "video" ? "VIDEO" : (it.mime.split("/")[1] || "FILE").toUpperCase();
      thumb.appendChild(ph);
    }
    if (it.kind === "video") {
      const b = document.createElement("span");
      b.className = "badge";
      b.textContent = "▶ Video";
      thumb.appendChild(b);
    }
    const body = document.createElement("div");
    body.className = "tile-body";
    const nm = document.createElement("p");
    nm.className = "tile-name";
    nm.textContent = it.name;
    nm.title = it.name;
    const meta = document.createElement("p");
    meta.className = "tile-meta";
    meta.textContent = PFY.formatBytes(it.size) + " · " + new Date(it.created_at).toLocaleDateString();
    body.append(nm, meta);

    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.className = "menu-btn";
    menuBtn.setAttribute("aria-label", "More actions");
    menuBtn.textContent = "⋮";
    const menu = document.createElement("div");
    menu.className = "menu";
    menu.hidden = true;
    [["View", () => openViewer(it)], ["Download original", () => download(it)],
     ["Rename", () => rename(it)], ["Move to folder", () => move(it)],
     ["Delete", () => askDelete(it), "danger"]].forEach(([label, fn, cls]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      if (cls) b.className = cls;
      b.addEventListener("click", () => { menu.hidden = true; fn(); });
      menu.appendChild(b);
    });
    menuBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      document.querySelectorAll(".menu").forEach((m) => { if (m !== menu) m.hidden = true; });
      menu.hidden = !menu.hidden;
    });
    body.append(menuBtn, menu);
    card.append(thumb, body);
    return card;
  }
  document.addEventListener("click", () => document.querySelectorAll(".menu").forEach((m) => (m.hidden = true)));

  // --------------------------------------- thumbnail loader (6 at a time)
  const pending = [];
  let active = 0;
  function queueThumb(it, img) { pending.push([it, img]); pump(); }
  function pump() {
    while (active < 6 && pending.length) {
      const [it, img] = pending.shift();
      active++;
      fetch(it.thumb_url)
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })
        .then((buf) => V.decryptBytes(key, buf))
        .then((plain) => {
          const url = URL.createObjectURL(new Blob([plain], { type: "image/jpeg" }));
          thumbUrls.set(it.id, url);
          img.src = url;
        })
        .catch(() => { img.replaceWith(Object.assign(document.createElement("span"), { className: "placeholder", textContent: "?" })); })
        .finally(() => { active--; pump(); });
    }
  }

  // --------------------------------------------------- open / download
  async function getOriginal(it) {
    if (fullBlobs.has(it.id)) return fullBlobs.get(it.id);
    const { url } = await PFY.api("/api/media/" + it.id + "/url");
    const res = await fetch(url);
    if (!res.ok) throw new Error("Could not download the file (" + res.status + ").");
    const plain = await V.decryptBytes(key, await res.arrayBuffer());
    const blob = new Blob([plain], { type: it.mime });
    fullBlobs.set(it.id, blob);
    return blob;
  }

  let viewing = null;
  async function openViewer(it) {
    viewing = it;
    const body = $("viewer-body");
    $("viewer-name").textContent = it.name;
    body.innerHTML = "<p class='muted'>Decrypting…</p>";
    $("viewer").showModal();
    try {
      const url = URL.createObjectURL(await getOriginal(it));
      body.innerHTML = "";
      let el;
      if (it.kind === "video") {
        el = document.createElement("video");
        el.controls = true;
        el.playsInline = true;
      } else {
        el = document.createElement("img");
        el.alt = it.name;
      }
      el.onerror = () => {
        body.innerHTML = "";
        const p = document.createElement("p");
        p.className = "muted";
        p.textContent = "This browser cannot preview this format (" + it.mime +
          "). Your original is safe. Use “Download original” to open it.";
        body.appendChild(p);
      };
      el.src = url;
      body.appendChild(el);
    } catch (err) {
      body.textContent = err.message;
    }
  }
  $("viewer-close").addEventListener("click", () => $("viewer").close());
  $("viewer-download").addEventListener("click", () => viewing && download(viewing));

  async function download(it) {
    try {
      const blob = await getOriginal(it);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = it.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      alertBox(err.message);
    }
  }

  // --------------------------------------------------- rename / move
  let editing = null;
  function openEdit(it, mode) {
    editing = { it, mode };
    $("edit-title").textContent = mode === "rename" ? "Rename file" : "Move to folder";
    $("edit-label").textContent = mode === "rename" ? "New name" : "Folder";
    const input = $("edit-input");
    input.value = mode === "rename" ? it.name : it.folder;
    if (mode === "rename") input.removeAttribute("list"); else input.setAttribute("list", "folder-list");
    $("edit-dialog").showModal();
    input.select();
  }
  const rename = (it) => openEdit(it, "rename");
  const move = (it) => openEdit(it, "move");
  $("edit-cancel").addEventListener("click", () => $("edit-dialog").close());
  $("edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const { it, mode } = editing;
    let value = $("edit-input").value.trim();
    if (!value) return;
    try {
      if (mode === "rename") {
        const ext = it.name.includes(".") ? it.name.slice(it.name.lastIndexOf(".")) : "";
        if (ext && !value.toLowerCase().endsWith(ext.toLowerCase())) value += ext;
        await PFY.api("/api/media/" + it.id, { method: "PATCH", json: { name_enc: await V.encryptText(key, value) } });
        it.name = value;
      } else {
        const res = await PFY.api("/api/media/" + it.id, { method: "PATCH", json: { folder: value } });
        it.folder = res.folder;
      }
      $("edit-dialog").close();
      render();
    } catch (err) {
      alertBox(err.message);
    }
  });

  // --------------------------------------------------- delete
  let deleting = null;
  function askDelete(it) {
    deleting = it;
    $("delete-name").textContent = it.name;
    $("delete-dialog").showModal();
  }
  $("delete-cancel").addEventListener("click", () => $("delete-dialog").close());
  $("delete-confirm").addEventListener("click", async () => {
    const it = deleting;
    try {
      await PFY.api("/api/media/" + it.id, { method: "DELETE" });
      items = items.filter((x) => x.id !== it.id);
      usage.used -= it.size;
      $("delete-dialog").close();
      render();
    } catch (err) {
      $("delete-dialog").close();
      alertBox(err.message);
    }
  });

  function alertBox(msg) {
    const div = document.createElement("div");
    div.className = "alert toast";
    div.textContent = msg;
    document.body.appendChild(div);
    setTimeout(() => div.remove(), 5000);
  }

  $("search").addEventListener("input", render);
  $("sort").addEventListener("change", render);
  load();
});
