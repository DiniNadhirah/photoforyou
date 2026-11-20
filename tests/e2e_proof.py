"""End-to-end browser test + proof screenshots (Playwright, Chromium).

    python tests/e2e_proof.py --base http://localhost:8080 --samples ./samples --out ./proof

Drives the real app like a user: sign up, create vault, upload photos and
videos, view, rename, move, delete, download (checks the downloaded file is
byte-for-byte identical), and a second user who must NOT see the first
user's files. Every step saves a screenshot into <out>/screenshots.
"""
import argparse
import glob
import hashlib
import json
import os
import time

from playwright.sync_api import expect, sync_playwright

PASSWORD = "Password123!"
VAULT_A = "blue-mango-river-42"
VAULT_B = "quiet-orchid-lamp-77"


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class Proof:
    def __init__(self, out):
        self.dir = os.path.join(out, "screenshots")
        os.makedirs(self.dir, exist_ok=True)
        self.steps = []

    def shot(self, page, name, caption, full=False):
        path = os.path.join(self.dir, name + ".png")
        page.screenshot(path=path, full_page=full)
        self.steps.append({"file": f"screenshots/{name}.png", "caption": caption})
        print("  ✓", name, "-", caption)


def signup(page, base, user):
    page.goto(base + "/register")
    page.fill("#username", user)
    page.fill("#password", PASSWORD)
    page.fill("#confirm", PASSWORD)


def wait_thumbs(page):
    page.wait_for_function(
        "() => { const imgs=[...document.querySelectorAll('.thumb img')];"
        " return imgs.length>0 && imgs.every(i => i.complete && i.naturalWidth > 0); }",
        timeout=30000)


def run(base, samples, out, headless=True):
    proof = Proof(out)
    images = sorted(glob.glob(os.path.join(samples, "*.jpg")))
    videos = sorted(glob.glob(os.path.join(samples, "*.webm"))) + sorted(glob.glob(os.path.join(samples, "*.mp4")))
    stamp = time.strftime("%H%M%S")
    user_a, user_b = f"rara_{stamp}", f"sarah_{stamp}"
    results = {"base": base, "user_a": user_a, "user_b": user_b, "checks": []}

    def check(name, ok, detail=""):
        results["checks"].append({"check": name, "passed": bool(ok), "detail": detail})
        print(("  PASS " if ok else "  FAIL ") + name, detail)
        assert ok, name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1366, "height": 860}, device_scale_factor=1,
                                  accept_downloads=True)
        page = ctx.new_page()

        # ---------------------------------------------------------- user A
        signup(page, base, user_a)
        proof.shot(page, "01-register", "Sign up form (password rules, CSRF-protected form)")
        page.click("button[type=submit]")
        page.wait_for_url("**/unlock")
        page.fill("#passphrase", VAULT_A)
        page.fill("#passphrase2", VAULT_A)
        page.check("#understand")
        proof.shot(page, "02-vault-setup", "Vault passphrase: the encryption key is created on this device only")
        page.click("#vault-btn")
        page.wait_for_url(base + "/")
        expect(page.locator("#empty")).to_be_visible(timeout=20000)
        proof.shot(page, "03-gallery-empty", "Empty gallery for a new user")

        # upload: photos into two folders + videos
        page.goto(base + "/upload")
        page.fill("#folder", "Holiday 2026")
        page.set_input_files("#files", images[:4] + videos[:1])
        proof.shot(page, "04-upload-queue", "Multiple photos and a video selected for one upload")
        page.click("#upload-btn")
        page.wait_for_selector(".upload-summary", timeout=60000)
        proof.shot(page, "05-upload-done", "Every file encrypted in the browser and uploaded, with progress")
        page.goto(base + "/upload?folder=Family")
        page.set_input_files("#files", images[4:] + videos[1:])
        page.click("#upload-btn")
        page.wait_for_selector(".upload-summary", timeout=60000)
        page.goto(base + "/upload")
        page.fill("#folder", "  family ")              # different case and spaces
        page.set_input_files("#files", images[:1])
        page.click("#upload-btn")
        page.wait_for_selector(".upload-summary", timeout=60000)

        page.goto(base + "/")
        wait_thumbs(page)
        folders = page.locator(".folder-head h2").all_inner_texts()
        check("folders merged case-insensitively ('family' joined 'Family')",
              len(folders) == 2, str(folders))
        proof.shot(page, "06-gallery", "Gallery: folders A–Z, decrypted thumbnails, storage bar, search and sort", full=True)

        # viewer: photo
        page.locator(".thumb").first.click()
        page.wait_for_function("() => { const i=document.querySelector('#viewer-body img'); return i && i.naturalWidth>0; }")
        proof.shot(page, "07-viewer-photo", "Full photo, downloaded encrypted and decrypted in the browser")
        page.click("#viewer-close")

        # viewer: video (webm plays in Chromium)
        page.locator(".tile", has_text=".webm").locator(".thumb").click()
        page.wait_for_function("() => { const v=document.querySelector('#viewer-body video'); return v && v.readyState>=2; }", timeout=20000)
        proof.shot(page, "08-viewer-video", "Videos are supported too (encrypted the same way)")
        page.click("#viewer-close")

        # download original and compare hash
        first = page.locator(".tile").filter(has_text=os.path.basename(images[0])).first
        first.locator(".menu-btn").click()
        proof.shot(page, "09-menu", "Actions: view, download original, rename, move, delete")
        with page.expect_download() as dl:
            first.locator(".menu button", has_text="Download original").click()
        dl_path = os.path.join(out, "downloaded_" + dl.value.suggested_filename)
        dl.value.save_as(dl_path)
        same = sha256(dl_path) == sha256(images[0])
        check("downloaded file is byte-for-byte identical to the original (SHA-256)",
              same, sha256(dl_path)[:16] + "…")
        os.remove(dl_path)

        # rename
        tile = page.locator(".tile").filter(has_text=os.path.basename(images[1])).first
        tile.locator(".menu-btn").click()
        tile.locator(".menu button", has_text="Rename").click()
        page.fill("#edit-input", "Sunset at the beach")
        proof.shot(page, "10-rename", "Rename: the new name is encrypted before it is sent")
        page.click("#edit-form button[type=submit]")
        expect(page.locator(".tile-name", has_text="Sunset at the beach.jpg")).to_be_visible()

        # move
        tile = page.locator(".tile").filter(has_text="Sunset at the beach.jpg").first
        tile.locator(".menu-btn").click()
        tile.locator(".menu button", has_text="Move to folder").click()
        page.fill("#edit-input", "Favourites")
        page.click("#edit-form button[type=submit]")
        expect(page.locator(".folder-head h2", has_text="Favourites")).to_be_visible()

        # search + sort
        page.fill("#search", "IMG_04")
        page.select_option("#sort", "name")
        proof.shot(page, "11-search-sort", "Search by name and sort (name A–Z)", full=True)
        page.fill("#search", "")

        # delete
        before = page.locator(".tile").count()
        tile = page.locator(".tile").last
        tile.locator(".menu-btn").click()
        tile.locator(".menu button", has_text="Delete").click()
        proof.shot(page, "12-delete-confirm", "Delete asks for confirmation inside the page")
        page.click("#delete-confirm")
        page.wait_for_function(f"() => document.querySelectorAll('.tile').length === {before - 1}")
        check("delete removes the file", True, f"{before} → {before - 1} files")

        # collect A's media for the isolation test
        a_media = page.evaluate("fetch('/api/media').then(r => r.json())")
        a_first_id = a_media["items"][0]["id"]
        proof.shot(page, "13-gallery-after", "Gallery after rename, move and delete", full=True)

        # lock + wrong passphrase
        page.click("#lock-btn")
        page.wait_for_url("**/unlock")
        page.fill("#passphrase", "wrong-passphrase")
        page.click("#vault-btn")
        expect(page.locator("#vault-error")).to_be_visible(timeout=20000)
        proof.shot(page, "14-wrong-passphrase", "Wrong vault passphrase: photos stay locked")
        page.fill("#passphrase", VAULT_A)
        page.click("#vault-btn")
        page.wait_for_url(base + "/")

        # ---------------------------------------------------------- user B
        ctx_b = browser.new_context(viewport={"width": 1366, "height": 860})
        pb = ctx_b.new_page()
        signup(pb, base, user_b)
        pb.click("button[type=submit]")
        pb.wait_for_url("**/unlock")
        pb.fill("#passphrase", VAULT_B)
        pb.fill("#passphrase2", VAULT_B)
        pb.check("#understand")
        pb.click("#vault-btn")
        pb.wait_for_url(base + "/")
        pb.goto(base + "/upload")
        pb.fill("#folder", "Study")
        pb.set_input_files("#files", images[-1:])
        pb.click("#upload-btn")
        pb.wait_for_selector(".upload-summary", timeout=60000)
        pb.goto(base + "/")
        wait_thumbs(pb)
        b_count = pb.locator(".tile").count()
        check("user B sees only their own 1 file (not user A's files)", b_count == 1, f"B sees {b_count}")
        proof.shot(pb, "15-user-b-isolated", f"Second account ({user_b}) sees only their own photo")

        r = pb.goto(base + f"/api/media/{a_first_id}/url")
        check("user B gets 404 when requesting user A's file", r.status == 404, f"HTTP {r.status}")
        proof.shot(pb, "16-user-b-blocked", "User B tries to open user A's file by ID: 404 Not found")
        pb.goto(base + "/")
        st = pb.evaluate(f"""fetch('/api/media/{a_first_id}', {{method:'DELETE',
                 headers:{{'X-CSRFToken': document.querySelector('meta[name=csrf-token]').content}}}})
                 .then(r => r.status)""")
        check("user B cannot delete user A's file", st == 404, f"HTTP {st}")

        # mobile view
        ctx_m = browser.new_context(**p.devices["iPhone 13"])
        pm = ctx_m.new_page()
        pm.goto(base + "/login")
        pm.fill("#username", user_a)
        pm.fill("#password", PASSWORD)
        pm.click("button[type=submit]")
        pm.wait_for_url("**/unlock")
        pm.fill("#passphrase", VAULT_A)
        pm.click("#vault-btn")
        pm.wait_for_url(base + "/")
        wait_thumbs(pm)
        proof.shot(pm, "17-mobile-gallery", "Phone layout (iPhone 13 size)")

        # load balancer: footer shows which instance answered
        seen = []
        for i in range(6):
            pg = ctx.new_page()
            resp = pg.goto(base + "/login")
            seen.append(resp.headers.get("x-instance"))
            if i < 3:
                pg.locator(".footer").screenshot(path=os.path.join(proof.dir, f"_footer{i}.png"))
            pg.close()
        check("load balancer spreads requests over instances", len(set(seen)) > 1, " → ".join(seen))
        results["instances_seen"] = seen

        browser.close()

    results["screenshots"] = proof.steps
    with open(os.path.join(out, "e2e-results.json"), "w") as fh:
        json.dump(results, fh, indent=2)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--samples", default="samples")
    ap.add_argument("--out", default="proof")
    a = ap.parse_args()
    res = run(a.base.rstrip("/"), a.samples, a.out)
    print(f"\nAll {len(res['checks'])} checks passed. Screenshots in {a.out}/screenshots")
