/* PhotoForYou vault: end-to-end encryption in the browser.
 *
 *   passphrase --PBKDF2 (600,000 rounds, SHA-256, per-user salt)--> AES-256-GCM key
 *
 * - The passphrase and the key NEVER leave this device.
 * - Every file, thumbnail and file name is encrypted with a fresh random
 *   12-byte IV before upload:  stored bytes = IV (12) + ciphertext + tag (16).
 * - The key is kept in this browser's IndexedDB as a NON-EXTRACTABLE CryptoKey
 *   (scripts can use it but cannot read it out) until the user clicks Lock or
 *   Log out.
 * Uses only the built-in Web Crypto API, no external libraries.
 */
(function () {
  "use strict";
  const PFY = (window.PFY = window.PFY || {});
  const enc = new TextEncoder();
  const dec = new TextDecoder();
  const CHECK_TEXT = "photoforyou-vault-check-v1";
  const ITERATIONS = 600000;

  // ---------- base64url ---------------------------------------------------
  PFY.b64 = {
    encode(bytes) {
      bytes = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
      let s = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    },
    decode(str) {
      str = str.replace(/-/g, "+").replace(/_/g, "/");
      while (str.length % 4) str += "=";
      const bin = atob(str);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    },
  };

  // ---------- IndexedDB key storage ----------------------------------------
  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open("photoforyou", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("keys");
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function idbDo(mode, fn) {
    const db = await idb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("keys", mode);
      const req = fn(tx.objectStore("keys"));
      tx.oncomplete = () => resolve(req && req.result);
      tx.onerror = () => reject(tx.error);
    });
  }

  // ---------- crypto --------------------------------------------------------
  const vault = {
    newSalt() {
      return PFY.b64.encode(crypto.getRandomValues(new Uint8Array(16)));
    },
    async deriveKey(passphrase, saltB64) {
      const base = await crypto.subtle.importKey("raw", enc.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
      return crypto.subtle.deriveKey(
        { name: "PBKDF2", salt: PFY.b64.decode(saltB64), iterations: ITERATIONS, hash: "SHA-256" },
        base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    },
    async encryptBytes(key, data) {
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data));
      const out = new Uint8Array(12 + ct.length);
      out.set(iv, 0);
      out.set(ct, 12);
      return out;
    },
    async decryptBytes(key, data) {
      const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
      return crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes.subarray(0, 12) }, key, bytes.subarray(12));
    },
    async encryptText(key, text) {
      return PFY.b64.encode(await vault.encryptBytes(key, enc.encode(text)));
    },
    async decryptText(key, b64) {
      return dec.decode(await vault.decryptBytes(key, PFY.b64.decode(b64)));
    },
    async makeCheck(key) {
      return vault.encryptText(key, CHECK_TEXT);
    },
    async verify(key, checkB64) {
      try { return (await vault.decryptText(key, checkB64)) === CHECK_TEXT; }
      catch (e) { return false; }
    },
    async saveKey(userId, key) {
      await idbDo("readwrite", (s) => s.put(key, "user:" + userId));
    },
    async loadKey(userId) {
      try { return (await idbDo("readonly", (s) => s.get("user:" + userId))) || null; }
      catch (e) { return null; }
    },
    async clear() {
      try { await idbDo("readwrite", (s) => s.clear()); } catch (e) { /* ignore */ }
    },
    /** Returns the key for the logged-in user, or sends them to /unlock. */
    async requireKey() {
      const userId = PFY.userId();
      const key = userId && (await vault.loadKey(userId));
      if (!key) {
        window.location.href = "/unlock";
        throw new Error("vault locked");
      }
      return key;
    },
  };
  PFY.vault = vault;

  // ---------- small helpers --------------------------------------------------
  PFY.userId = () => {
    const m = document.querySelector('meta[name="user-id"]');
    return m ? m.content : null;
  };
  PFY.csrf = () => document.querySelector('meta[name="csrf-token"]').content;

  /** fetch() wrapper: sends the CSRF token, parses JSON, turns errors into messages. */
  PFY.api = async function (url, opts = {}) {
    opts.headers = Object.assign({ "X-CSRFToken": PFY.csrf() }, opts.headers || {});
    if (opts.json !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    opts.credentials = "same-origin";
    const res = await fetch(url, opts);
    let data = {};
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (res.status === 401) { window.location.href = "/login"; throw new Error("Please log in again."); }
    if (!res.ok) throw new Error(data.error || "Request failed (" + res.status + ").");
    return data;
  };

  PFY.formatBytes = (n) => {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
  };

  // ---------- Lock / Log out forget the key on this device -----------------
  document.addEventListener("DOMContentLoaded", () => {
    const logout = document.getElementById("logout-form");
    if (logout) {
      logout.addEventListener("submit", async (e) => {
        e.preventDefault();
        await vault.clear();
        logout.submit();
      });
    }
    const lock = document.getElementById("lock-btn");
    if (lock) {
      lock.addEventListener("click", async () => {
        await vault.clear();
        window.location.href = "/unlock";
      });
    }
  });
})();
