"""Proof: what the management team can see in the database and storage.

    python tests/management_view.py --data data/cluster --original samples/IMG_0420.jpg --out proof

Finds the stored object for the original photo (matched by its size, because
the server cannot read file names - they are encrypted), and builds a
side-by-side page: the real photo vs. the bytes actually stored in the cloud.
"""
import argparse
import base64
import hashlib
import html
import io
import json
import math
import os
import sqlite3

from PIL import Image


def bytes_as_image(data, width=480):
    """Draw raw bytes as grey pixels, so anyone can SEE they are noise."""
    side = min(width, int(math.sqrt(len(data))))
    px = data[: side * side]
    img = Image.frombytes("L", (side, side), px).resize((width, width), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def hexdump(data, n=96):
    rows = []
    for i in range(0, n, 16):
        chunk = data[i:i + 16]
        rows.append(f"{i:08x}  " + " ".join(f"{b:02x}" for b in chunk))
    return "\n".join(rows)


def main(data_dir, original, out):
    with open(original, "rb") as fh:
        orig = fh.read()
    db = sqlite3.connect(os.path.join(data_dir, "local.db"))
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM media WHERE size_bytes = ? ORDER BY created_at LIMIT 1",
                     (len(orig),)).fetchone()
    if not row:
        raise SystemExit("No stored object with that size; upload the photo first.")
    row = dict(row)
    with open(os.path.join(data_dir, "storage", row["object_path"]), "rb") as fh:
        stored = fh.read()

    orig_b64 = base64.b64encode(orig).decode()
    noise_b64 = bytes_as_image(stored)
    shown_row = {k: row[k] for k in ("id", "user_id", "folder", "name_enc", "mime_type",
                                     "size_bytes", "stored_bytes", "object_path", "thumb_path")}
    facts = {
        "Original file": os.path.basename(original),
        "Original starts with (JPEG header)": orig[:4].hex(" "),
        "Stored object starts with": stored[:4].hex(" "),
        "Original SHA-256": hashlib.sha256(orig).hexdigest()[:24] + "…",
        "Stored SHA-256": hashlib.sha256(stored).hexdigest()[:24] + "…",
        "Size difference": f"{len(stored) - len(orig)} bytes (12-byte IV + 16-byte tag)",
    }
    page = f"""<!doctype html><meta charset=utf-8><title>What management sees</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;background:#f6f7fb;color:#1e293b;margin:0;padding:28px}}
h1{{margin:0 0 4px;font-size:26px}} .muted{{color:#64748b;margin:0 0 20px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px}}
.tag{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}}
.ok{{color:#059669}} .bad{{color:#4f46e5}}
img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px;display:block;margin-top:10px}}
pre{{background:#0f172a;color:#e2e8f0;border-radius:10px;padding:12px;font-size:12px;overflow:auto;white-space:pre-wrap;word-break:break-all}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td{{border-top:1px solid #e2e8f0;padding:6px 8px;vertical-align:top}}
td:first-child{{color:#64748b;width:42%}}
</style>
<h1>What the management team can see</h1>
<p class=muted>The same photo: on the left as the owner sees it in PhotoForYou, on the right exactly what is stored in the cloud bucket and database.</p>
<div class=grid>
 <div class=card><div class="tag ok">Owner's browser (after decrypting with the vault key)</div>
   <img src="data:image/jpeg;base64,{orig_b64}"></div>
 <div class=card><div class="tag bad">Cloud storage: object {html.escape(row['object_path'])}</div>
   <img src="data:image/png;base64,{noise_b64}" style="image-rendering:pixelated"></div>
</div>
<div class=grid style="margin-top:20px">
 <div class=card><div class="tag bad">Database row (table media)</div>
   <pre>{html.escape(json.dumps(shown_row, indent=2))}</pre>
   <p class=muted style="margin:0">The file name is stored only as encrypted text (name_enc).</p></div>
 <div class=card><div class="tag bad">First bytes of the stored object</div>
   <pre>{hexdump(stored)}</pre>
   <table>{''.join(f'<tr><td>{html.escape(k)}</td><td>{html.escape(v)}</td></tr>' for k, v in facts.items())}</table></div>
</div>"""
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "management-view.html")
    with open(path, "w") as fh:
        fh.write(page)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cluster")
    ap.add_argument("--original", required=True)
    ap.add_argument("--out", default="proof")
    a = ap.parse_args()
    print(main(a.data, a.original, a.out))
