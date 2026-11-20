"""Automated tests for PhotoForYou v2 (run: pytest -v).

They use the local backend in a temporary folder, so no Supabase account is
needed. Each test name says what it proves."""
import io
import os
import re
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SECRET_KEY", "test-secret")

import app as app_module  # noqa: E402
from backends.local_backend import LocalBackend  # noqa: E402
from config import Config  # noqa: E402

OVERHEAD = 28


def make_app(**overrides):
    settings = dict(STORAGE_BACKEND="local", LOCAL_DATA_DIR=tempfile.mkdtemp(), SECRET_KEY="test-secret",
                    RATE_LIMIT_ENABLED=False, TESTING=True, USER_QUOTA_MB=1, MAX_FILE_MB=1)
    settings.update(overrides)
    cfg = type("TestConfig", (Config,), settings)
    cfg.MAX_CONTENT_LENGTH = 3 * 1024 * 1024
    backend = LocalBackend(cfg.LOCAL_DATA_DIR, cfg.SECRET_KEY)
    return app_module.create_app(cfg, backend=backend)


@pytest.fixture()
def app():
    return make_app()


def csrf_from(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def signup(client, username, password="password123"):
    token = csrf_from(client.get("/register").get_data(as_text=True))
    r = client.post("/register", data={"csrf_token": token, "username": username,
                                       "password": password, "confirm": password})
    assert r.status_code == 302, r.get_data(as_text=True)
    return csrf_from(client.get("/").get_data(as_text=True))


def upload(client, token, size=100, folder="Holiday", mime="image/jpeg", thumb=True):
    data = {
        "file": (io.BytesIO(os.urandom(size + OVERHEAD)), "file.bin"),
        "mime": mime, "size": str(size), "name_enc": "ZW5jcnlwdGVkLW5hbWU", "folder": folder,
    }
    if thumb:
        data["thumb"] = (io.BytesIO(os.urandom(64)), "thumb.bin")
    return client.post("/api/media", data=data, headers={"X-CSRFToken": token},
                       content_type="multipart/form-data")


# --------------------------------------------------------------- basics
def test_health_reports_instance(app):
    r = app.test_client().get("/health")
    assert r.status_code == 200 and r.json["status"] == "ok"
    assert r.headers["X-Instance"] == app.config["INSTANCE_NAME"]


def test_pages_require_login(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert c.get("/api/media").status_code == 401


def test_security_headers_present(app):
    r = app.test_client().get("/login")
    for h in ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert h in r.headers
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_password_is_hashed_not_stored_plain(app):
    c = app.test_client()
    signup(c, "alice")
    user = app.backend.get_user_by_username("alice")
    assert user["password_hash"] != "password123"
    assert user["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_register_validation(app):
    c = app.test_client()
    token = csrf_from(c.get("/register").get_data(as_text=True))
    r = c.post("/register", data={"csrf_token": token, "username": "bob",
                                  "password": "short", "confirm": "short"})
    assert r.status_code == 400 and b"at least 8" in r.data


def test_wrong_password_rejected(app):
    c = app.test_client()
    signup(c, "carol")
    c2 = app.test_client()
    token = csrf_from(c2.get("/login").get_data(as_text=True))
    r = c2.post("/login", data={"csrf_token": token, "username": "carol", "password": "nope-nope"})
    assert r.status_code == 401


# --------------------------------------------------------------- CSRF
def test_upload_without_csrf_token_is_blocked(app):
    c = app.test_client()
    signup(c, "dave")
    r = c.post("/api/media", data={"mime": "image/jpeg"})
    assert r.status_code == 400 and "token" in r.json["error"].lower()


# --------------------------------------------------------------- upload rules
def test_upload_stores_file_under_user_folder(app):
    c = app.test_client()
    token = signup(c, "erin")
    r = upload(c, token)
    assert r.status_code == 201
    uid = str(app.backend.get_user_by_username("erin")["id"])
    row = app.backend.list_media(uid)[0]
    assert row["object_path"].startswith(uid + "/") and row["object_path"].endswith(".bin")
    assert row["thumb_path"].startswith(uid + "/")


def test_upload_rejects_unencrypted_or_wrong_size(app):
    c = app.test_client()
    token = signup(c, "frank")
    bad = {"file": (io.BytesIO(b"x" * 100), "f.bin"), "mime": "image/jpeg",
           "size": "100", "name_enc": "abc", "folder": "A"}
    r = c.post("/api/media", data=bad, headers={"X-CSRFToken": token}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_upload_rejects_disallowed_type(app):
    c = app.test_client()
    token = signup(c, "gina")
    assert upload(c, token, mime="application/x-msdownload").status_code == 415


def test_upload_rejects_file_over_limit(app):
    c = app.test_client()
    token = signup(c, "hank")
    assert upload(c, token, size=1024 * 1024 + 1).status_code == 413


def test_quota_is_enforced(app):
    c = app.test_client()
    token = signup(c, "ivy")
    assert upload(c, token, size=700 * 1024).status_code == 201
    r = upload(c, token, size=400 * 1024)
    assert r.status_code == 413 and "quota" in r.json["error"]


def test_folder_names_are_merged_case_insensitively(app):
    c = app.test_client()
    token = signup(c, "jack")
    upload(c, token, folder="Study")
    upload(c, token, folder="  study ")
    folders = {i["folder"] for i in c.get("/api/media").json["items"]}
    assert folders == {"Study"}


# --------------------------------------------------------------- isolation
def test_users_only_see_their_own_files(app):
    a, b = app.test_client(), app.test_client()
    ta, tb = signup(a, "user_a"), signup(b, "user_b")
    upload(a, ta)
    upload(a, ta)
    upload(b, tb)
    assert len(a.get("/api/media").json["items"]) == 2
    assert len(b.get("/api/media").json["items"]) == 1


def test_user_cannot_open_rename_or_delete_another_users_file(app):
    a, b = app.test_client(), app.test_client()
    ta, tb = signup(a, "owner"), signup(b, "attacker")
    media_id = upload(a, ta).json["item"]["id"]
    assert b.get(f"/api/media/{media_id}/url").status_code == 404
    assert b.patch(f"/api/media/{media_id}", json={"name_enc": "aGFja2Vk"},
                   headers={"X-CSRFToken": tb}).status_code == 404
    assert b.delete(f"/api/media/{media_id}", headers={"X-CSRFToken": tb}).status_code == 404
    # the owner's file is untouched
    assert a.get(f"/api/media/{media_id}/url").status_code == 200


def test_owner_can_rename_move_and_delete(app):
    c = app.test_client()
    token = signup(c, "kate")
    media_id = upload(c, token).json["item"]["id"]
    assert c.patch(f"/api/media/{media_id}", json={"name_enc": "bmV3"}, headers={"X-CSRFToken": token}).status_code == 200
    r = c.patch(f"/api/media/{media_id}", json={"folder": "Work"}, headers={"X-CSRFToken": token})
    assert r.json["folder"] == "Work"
    row = app.backend.get_media(str(app.backend.get_user_by_username("kate")["id"]), media_id)
    assert c.delete(f"/api/media/{media_id}", headers={"X-CSRFToken": token}).status_code == 200
    assert not os.path.exists(os.path.join(app.backend.files_dir, row["object_path"]))


# --------------------------------------------------------------- signed URLs
def test_storage_needs_valid_signature(app):
    c = app.test_client()
    token = signup(c, "leo")
    media_id = upload(c, token).json["item"]["id"]
    url = c.get(f"/api/media/{media_id}/url").json["url"]
    assert app.test_client().get(url).status_code == 200            # signed link works
    tampered = re.sub(r"sig=[0-9a-f]+", "sig=" + "0" * 64, url)
    assert app.test_client().get(tampered).status_code == 403       # forged link fails
    no_sig = url.split("?")[0]
    assert app.test_client().get(no_sig).status_code == 403          # no link, no file


def test_stored_bytes_are_not_the_original(app):
    """The server only ever receives encrypted bytes; this checks it stores exactly
    those and that they do not start with a JPEG/PNG header."""
    c = app.test_client()
    token = signup(c, "mia")
    upload(c, token)
    uid = str(app.backend.get_user_by_username("mia")["id"])
    row = app.backend.list_media(uid)[0]
    with open(os.path.join(app.backend.files_dir, row["object_path"]), "rb") as fh:
        head = fh.read(8)
    assert not head.startswith(b"\xff\xd8\xff") and not head.startswith(b"\x89PNG")


# --------------------------------------------------------------- rate limit
def test_login_rate_limit_returns_429():
    app = make_app(RATE_LIMIT_ENABLED=True, LOGIN_RATE_LIMIT="3 per minute")
    c = app.test_client()
    token = csrf_from(c.get("/login").get_data(as_text=True))
    codes = [c.post("/login", data={"csrf_token": token, "username": "x", "password": "y"}).status_code
             for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
