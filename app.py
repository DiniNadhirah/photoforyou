"""PhotoForYou v2 - private photo & video vault.

Key ideas
---------
* Photos are ENCRYPTED IN THE BROWSER (static/js/vault.js) before upload.
  The server, Supabase and the management team only ever store scrambled
  bytes; only the owner's vault passphrase can unlock them.
* Every file lives at  <user_id>/<random-id>.bin  in a PRIVATE bucket and is
  only reachable through short-lived signed URLs.
* Every media query is filtered by the logged-in user_id.
* The app is stateless (signed-cookie sessions, shared database and bucket),
  so any number of instances can run behind the nginx load balancer.
"""
import functools
import logging
import os
import re
import time
import uuid

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from backends import make_backend
from config import Config

ALLOWED_TYPES = {
    "image/jpeg": "image", "image/png": "image", "image/webp": "image", "image/gif": "image",
    "image/heic": "image", "image/heif": "image",
    "video/mp4": "video", "video/quicktime": "video", "video/webm": "video",
}
ENCRYPTION_OVERHEAD = 12 + 16          # AES-GCM: 12-byte IV + 16-byte auth tag
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,40}$")
B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
STARTED = time.time()

csrf = CSRFProtect()
log = logging.getLogger("photoforyou")


def create_app(config_object=Config, backend=None):
    app = Flask(__name__)
    app.config.from_object(config_object)
    if app.config["TRUST_PROXY_HOPS"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["TRUST_PROXY_HOPS"],
                                x_proto=1, x_host=0)
    csrf.init_app(app)
    # One limiter per app. Counts are kept in memory per instance; nginx adds
    # a second, shared limit in front of all instances.
    lb_token = app.config["LB_TOKEN"]

    def client_ip():
        """Real client IP for rate limiting. Only trusts the X-Client-IP header
        when it comes from our own nginx load balancer (shared LB_TOKEN)."""
        if lb_token and request.headers.get("X-LB-Token") == lb_token:
            return request.headers.get("X-Client-IP") or get_remote_address()
        return get_remote_address()
    app.client_ip = client_ip

    limiter = Limiter(client_ip, app=app, storage_uri="memory://",
                      enabled=app.config["RATE_LIMIT_ENABLED"])
    app.limiter = limiter          # keep a strong reference
    app.backend = backend or make_backend(config_object)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    register_hooks(app)
    register_routes(app, limiter)
    return app


# ============================================================================
# Request hooks: timing log, security headers, instance header
# ============================================================================
def register_hooks(app):
    supabase_origin = app.config["SUPABASE_URL"]
    csp = "; ".join([
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' blob: data:",
        "media-src 'self' blob:",
        f"connect-src 'self' {supabase_origin}".strip(),
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])

    @app.before_request
    def _start_timer():
        g.t0 = time.perf_counter()

    @app.after_request
    def _headers(resp):
        resp.headers["X-Instance"] = app.config["INSTANCE_NAME"]
        resp.headers["Content-Security-Policy"] = csp
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.is_secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        elif "Cache-Control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-store"
        ms = (time.perf_counter() - g.get("t0", time.perf_counter())) * 1000
        if not request.path.startswith(("/static/", "/health")):
            log.info("instance=%s method=%s path=%s status=%s ms=%.1f ip=%s",
                     app.config["INSTANCE_NAME"], request.method, request.path,
                     resp.status_code, ms, app.client_ip())
        return resp

    @app.context_processor
    def _globals():
        return {"instance_name": app.config["INSTANCE_NAME"],
                "max_file_mb": app.config["MAX_FILE_MB"]}


# ============================================================================
# Helpers
# ============================================================================
def current_user_id():
    return session.get("user_id")


def login_required(api=False):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not current_user_id():
                if api:
                    return jsonify(error="Please log in again."), 401
                return redirect(url_for("login", next=request.path))
            return fn(*a, **kw)
        return wrapper
    return deco


def clean_folder(name, existing):
    """Trim + collapse spaces, and re-use an existing folder whose name only
    differs in upper/lower case, so 'study' joins 'Study'."""
    name = re.sub(r"\s+", " ", (name or "").strip())[:40]
    name = "".join(ch for ch in name if ch.isprintable())
    if not name:
        return "Uncategorized"
    for f in existing:
        if f.lower() == name.lower():
            return f
    return name


def media_json(row, thumb_url=None):
    return {
        "id": row["id"], "folder": row["folder"], "name_enc": row["name_enc"],
        "mime": row["mime_type"], "kind": row["kind"], "size": row["size_bytes"],
        "created_at": row["created_at"], "thumb_url": thumb_url,
    }


def api_error(msg, code):
    return jsonify(error=msg), code


# ============================================================================
# Routes
# ============================================================================
def register_routes(app, limiter):
    backend = app.backend
    quota = app.config["USER_QUOTA_MB"] * 1024 * 1024
    max_file = app.config["MAX_FILE_MB"] * 1024 * 1024

    # ---------------------------------------------------------------- health
    @app.get("/health")
    def health():
        """Cheap liveness check used by the load balancer and Render."""
        return jsonify(status="ok", instance=app.config["INSTANCE_NAME"],
                       pid=os.getpid(), uptime_s=int(time.time() - STARTED))

    @app.get("/ready")
    def ready():
        """Readiness check: can this instance reach the database?"""
        try:
            backend.ping()
            return jsonify(status="ready", instance=app.config["INSTANCE_NAME"])
        except Exception as exc:  # noqa: BLE001
            return jsonify(status="not ready", error=str(exc)[:200]), 503

    # ------------------------------------------------------------------ auth
    @app.route("/register", methods=["GET", "POST"])
    @limiter.limit(lambda: app.config["REGISTER_RATE_LIMIT"], methods=["POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            error = None
            if not USERNAME_RE.match(username):
                error = "Username must be 3–40 characters: letters, numbers, . _ - @"
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            elif password != confirm:
                error = "The two passwords do not match."
            elif backend.get_user_by_username(username):
                error = "That username is already taken."
            if not error:
                try:
                    user = backend.create_user(username, generate_password_hash(password))
                except Exception:  # noqa: BLE001 - unique violation race
                    error = "That username is already taken."
            if error:
                return render_template("register.html", error=error, username=username), 400
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = username
            session.permanent = True
            return redirect(url_for("unlock"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit(lambda: app.config["LOGIN_RATE_LIMIT"], methods=["POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            user = backend.get_user_by_username(username)
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session.permanent = True
                return redirect(url_for("unlock"))
            return render_template("login.html", error="Incorrect username or password.",
                                   username=username), 401
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ----------------------------------------------------------------- vault
    @app.get("/unlock")
    @login_required()
    def unlock():
        user = backend.get_user(current_user_id())
        if not user:
            session.clear()
            return redirect(url_for("login"))
        return render_template("unlock.html", user=user,
                               has_vault=bool(user.get("vault_salt")))

    @app.post("/api/vault")
    @login_required(api=True)
    def create_vault():
        """Stores the vault SALT and a CHECK value (an encrypted known text).
        The passphrase and the key itself never reach the server."""
        data = request.get_json(silent=True) or {}
        salt, check = data.get("salt", ""), data.get("check", "")
        if not (B64_RE.match(salt) and B64_RE.match(check)) or len(salt) > 64 or len(check) > 256:
            return api_error("Invalid vault data.", 400)
        user = backend.get_user(current_user_id())
        if user.get("vault_salt"):
            return api_error("Vault already exists.", 409)
        backend.set_vault(current_user_id(), salt, check)
        return jsonify(ok=True)

    # ----------------------------------------------------------------- pages
    @app.get("/")
    @login_required()
    def gallery():
        return render_template("gallery.html")

    @app.get("/upload")
    @login_required()
    def upload_page():
        folders = sorted({m["folder"] for m in backend.list_media(current_user_id())}, key=str.lower)
        return render_template("upload.html", folders=folders,
                               preset=request.args.get("folder", ""))

    # ------------------------------------------------------------------- API
    @app.get("/api/media")
    @login_required(api=True)
    def list_media():
        uid = current_user_id()
        rows = backend.list_media(uid)
        urls = backend.signed_urls([r["thumb_path"] for r in rows if r.get("thumb_path")])
        items = [media_json(r, urls.get(r.get("thumb_path"))) for r in rows]
        used = sum(int(r["size_bytes"]) for r in rows)
        return jsonify(items=items, usage={"used": used, "quota": quota},
                       instance=app.config["INSTANCE_NAME"])

    @app.post("/api/media")
    @login_required(api=True)
    @limiter.limit(lambda: app.config["UPLOAD_RATE_LIMIT"])
    def upload_media():
        uid = current_user_id()
        f = request.files.get("file")
        thumb = request.files.get("thumb")
        mime = (request.form.get("mime") or "").lower()
        name_enc = request.form.get("name_enc", "")
        try:
            size = int(request.form.get("size", "-1"))
        except ValueError:
            size = -1

        if not f:
            return api_error("No file received.", 400)
        if mime not in ALLOWED_TYPES:
            return api_error("Only photos (JPG, PNG, WEBP, GIF, HEIC) and videos (MP4, MOV, WEBM) are allowed.", 415)
        if not B64_RE.match(name_enc) or len(name_enc) > 2000:
            return api_error("Invalid file name.", 400)
        if size < 0 or size > max_file:
            return api_error(f"Each file must be {app.config['MAX_FILE_MB']} MB or smaller.", 413)

        data = f.read()
        # The browser sends only encrypted bytes; their length must match the
        # declared size plus the AES-GCM overhead, so nobody can lie about the
        # size to get around the storage quota.
        if len(data) != size + ENCRYPTION_OVERHEAD:
            return api_error("File was not encrypted correctly. Please unlock your vault and try again.", 400)
        thumb_data = thumb.read() if thumb else b""
        if len(thumb_data) > 2 * 1024 * 1024:
            return api_error("Thumbnail too large.", 413)

        rows = backend.list_media(uid)
        if sum(int(r["size_bytes"]) for r in rows) + size > quota:
            return api_error(f"Storage full: your quota is {app.config['USER_QUOTA_MB']} MB.", 413)
        folder = clean_folder(request.form.get("folder"), {r["folder"] for r in rows})

        media_id = str(uuid.uuid4())
        obj = f"{uid}/{media_id}.bin"
        thumb_obj = f"{uid}/{media_id}.thumb.bin" if thumb_data else None
        backend.put_object(obj, data)
        if thumb_obj:
            backend.put_object(thumb_obj, thumb_data)
        try:
            row = backend.insert_media({
                "id": media_id, "user_id": str(uid), "folder": folder, "name_enc": name_enc,
                "mime_type": mime, "kind": ALLOWED_TYPES[mime], "size_bytes": size,
                "stored_bytes": len(data), "object_path": obj, "thumb_path": thumb_obj,
            })
        except Exception:
            backend.remove_objects([p for p in (obj, thumb_obj) if p])   # no orphan files
            raise
        return jsonify(item=media_json(row)), 201

    @app.get("/api/media/<media_id>/url")
    @login_required(api=True)
    def media_url(media_id):
        row = backend.get_media(current_user_id(), media_id)
        if not row:
            return api_error("Not found.", 404)        # also for other users' files
        url = backend.signed_urls([row["object_path"]]).get(row["object_path"])
        return jsonify(url=url, mime=row["mime_type"], name_enc=row["name_enc"])

    @app.patch("/api/media/<media_id>")
    @login_required(api=True)
    def update_media(media_id):
        uid = current_user_id()
        row = backend.get_media(uid, media_id)
        if not row:
            return api_error("Not found.", 404)
        data = request.get_json(silent=True) or {}
        fields = {}
        if "name_enc" in data:
            if not B64_RE.match(str(data["name_enc"])) or len(data["name_enc"]) > 2000:
                return api_error("Invalid name.", 400)
            fields["name_enc"] = data["name_enc"]
        if "folder" in data:
            others = {r["folder"] for r in backend.list_media(uid)}
            fields["folder"] = clean_folder(str(data["folder"]), others)
        if not fields:
            return api_error("Nothing to change.", 400)
        backend.update_media(uid, media_id, fields)
        return jsonify(ok=True, **fields)

    @app.delete("/api/media/<media_id>")
    @login_required(api=True)
    def delete_media(media_id):
        uid = current_user_id()
        row = backend.get_media(uid, media_id)       # ownership check FIRST
        if not row:
            return api_error("Not found.", 404)
        backend.delete_media(uid, media_id)
        backend.remove_objects([p for p in (row["object_path"], row.get("thumb_path")) if p])
        return jsonify(ok=True)

    # -------------------------------------------- local backend file server
    @app.get("/_local_storage/<path:path>")
    def local_storage(path):
        opener = getattr(backend, "open_signed", None)
        if not opener:
            abort(404)
        full = opener(path, request.args.get("exp"), request.args.get("sig"))
        if not full:
            abort(403)
        resp = send_file(full, mimetype="application/octet-stream", max_age=86400)
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    # ---------------------------------------------------------------- errors
    def wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        if wants_json():
            return api_error("Security token expired. Refresh the page and try again.", 400)
        flash("Your session expired. Please try again.")
        return redirect(request.path if request.method == "GET" else url_for("login"))

    @app.errorhandler(429)
    def too_many(e):
        msg = "Too many requests. Please wait a minute and try again."
        if wants_json():
            return api_error(msg, 429)
        return render_template("error.html", code=429, title="Slow down", message=msg), 429

    @app.errorhandler(413)
    def too_large(e):
        msg = f"That file is too large. The limit is {app.config['MAX_FILE_MB']} MB."
        if wants_json():
            return api_error(msg, 413)
        return render_template("error.html", code=413, title="File too large", message=msg), 413

    @app.errorhandler(404)
    def not_found(e):
        if wants_json():
            return api_error("Not found.", 404)
        return render_template("error.html", code=404, title="Page not found",
                               message="That page does not exist."), 404

    @app.errorhandler(500)
    def server_error(e):
        if wants_json():
            return api_error("Something went wrong on our side. Please try again.", 500)
        return render_template("error.html", code=500, title="Something went wrong",
                               message="Please try again in a moment."), 500


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
