/* Unlock page: create the vault (first time) or unlock it. */
document.addEventListener("DOMContentLoaded", async () => {
  "use strict";
  const box = document.getElementById("vault");
  const form = document.getElementById("vault-form");
  const errorBox = document.getElementById("vault-error");
  const status = document.getElementById("vault-status");
  const btn = document.getElementById("vault-btn");
  const { userId, salt, check, mode, next } = box.dataset;
  const V = PFY.vault;

  // Already unlocked on this device? Go straight to the gallery.
  if (mode === "unlock") {
    const saved = await V.loadKey(userId);
    if (saved && (await V.verify(saved, check))) {
      window.location.replace(next);
      return;
    }
  }

  function fail(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
    btn.disabled = false;
    status.textContent = "";
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.hidden = true;
    const pass = document.getElementById("passphrase").value;
    btn.disabled = true;
    status.textContent = "Deriving your key on this device…";
    try {
      if (mode === "setup") {
        const pass2 = document.getElementById("passphrase2").value;
        if (pass.length < 8) return fail("Use at least 8 characters.");
        if (pass !== pass2) return fail("The two passphrases do not match.");
        const newSalt = V.newSalt();
        const key = await V.deriveKey(pass, newSalt);
        const newCheck = await V.makeCheck(key);
        // Only the salt and an encrypted check value are sent, never the passphrase.
        await PFY.api("/api/vault", { method: "POST", json: { salt: newSalt, check: newCheck } });
        await V.saveKey(userId, key);
      } else {
        const key = await V.deriveKey(pass, salt);
        if (!(await V.verify(key, check))) return fail("Wrong vault passphrase.");
        await V.saveKey(userId, key);
      }
      window.location.replace(next);
    } catch (err) {
      fail(err.message || "Something went wrong.");
    }
  });
});
