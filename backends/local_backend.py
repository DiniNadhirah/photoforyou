"""Local backend: SQLite for the tables and a folder for the files.

Several app instances on one machine can share the same data folder, so it
behaves like one shared cloud database + bucket behind a load balancer.
Signed URLs are imitated with an HMAC signature and an expiry time."""
import hashlib
import hmac
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from . import Backend

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    vault_salt    TEXT,
    vault_check   TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    folder       TEXT NOT NULL,
    name_enc     TEXT NOT NULL,
    mime_type    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    stored_bytes INTEGER NOT NULL,
    object_path  TEXT NOT NULL,
    thumb_path   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_user ON media(user_id, created_at);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


class LocalBackend(Backend):
    def __init__(self, data_dir, secret, latency_ms=0, signed_url_ttl=3600):
        super().__init__(signed_url_ttl)
        self.data_dir = os.path.abspath(data_dir)
        self.files_dir = os.path.join(self.data_dir, "storage")
        os.makedirs(self.files_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "local.db")
        self.secret = secret.encode()
        self.latency = latency_ms / 1000.0
        with self._db() as db:
            db.executescript(SCHEMA)

    # ---- helpers -------------------------------------------------------------
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _wait(self):
        if self.latency:
            time.sleep(self.latency)       # imitate the network round trip

    def _q(self, sql, args=(), one=False, write=False):
        self._wait()
        with self._db() as db:
            cur = db.execute(sql, args)
            if write:
                return cur.rowcount
            rows = [dict(r) for r in cur.fetchall()]
        return (rows[0] if rows else None) if one else rows

    # ---- users ---------------------------------------------------------------
    def get_user_by_username(self, username):
        return self._q("SELECT * FROM users WHERE username = ?", (username,), one=True)

    def get_user(self, user_id):
        return self._q("SELECT * FROM users WHERE id = ?", (user_id,), one=True)

    def create_user(self, username, password_hash):
        self._wait()
        with self._db() as db:
            try:
                cur = db.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?,?,?)",
                                 (username, password_hash, _now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("username taken") from exc
            return {"id": cur.lastrowid, "username": username}

    def set_vault(self, user_id, salt, check):
        self._q("UPDATE users SET vault_salt = ?, vault_check = ? WHERE id = ?",
                (salt, check, user_id), write=True)

    # ---- media ---------------------------------------------------------------
    def list_media(self, user_id):
        return self._q("SELECT * FROM media WHERE user_id = ? ORDER BY created_at DESC", (str(user_id),))

    def get_media(self, user_id, media_id):
        return self._q("SELECT * FROM media WHERE user_id = ? AND id = ?",
                       (str(user_id), media_id), one=True)

    def insert_media(self, row):
        row = dict(row)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", _now())
        cols = ",".join(row)
        self._q(f"INSERT INTO media ({cols}) VALUES ({','.join('?' * len(row))})",
                tuple(row.values()), write=True)
        return row

    def update_media(self, user_id, media_id, fields):
        sets = ", ".join(f"{k} = ?" for k in fields)
        n = self._q(f"UPDATE media SET {sets} WHERE user_id = ? AND id = ?",
                    (*fields.values(), str(user_id), media_id), write=True)
        return n > 0

    def delete_media(self, user_id, media_id):
        n = self._q("DELETE FROM media WHERE user_id = ? AND id = ?", (str(user_id), media_id), write=True)
        return n > 0

    def usage_bytes(self, user_id):
        row = self._q("SELECT COALESCE(SUM(size_bytes), 0) AS total FROM media WHERE user_id = ?",
                      (str(user_id),), one=True)
        return int(row["total"])

    def ping(self):
        self._q("SELECT 1")
        return True

    # ---- storage -------------------------------------------------------------
    def _file(self, path):
        full = os.path.abspath(os.path.join(self.files_dir, path))
        if not full.startswith(self.files_dir + os.sep):
            raise ValueError("bad path")
        return full

    def put_object(self, path, data, content_type="application/octet-stream"):
        self._wait()
        full = self._file(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)

    def remove_objects(self, paths):
        self._wait()
        for p in paths:
            try:
                os.remove(self._file(p))
            except FileNotFoundError:
                pass
        self.forget_urls(paths)

    def _sign(self, path, exp):
        return hmac.new(self.secret, f"{path}|{exp}".encode(), hashlib.sha256).hexdigest()

    def _create_signed_urls(self, paths, ttl):
        self._wait()
        exp = int(time.time()) + ttl
        return {p: f"/_local_storage/{p}?exp={exp}&sig={self._sign(p, exp)}" for p in paths}

    def open_signed(self, path, exp, sig):
        """Used by the /_local_storage route. Returns a file path or None."""
        try:
            exp = int(exp)
        except (TypeError, ValueError):
            return None
        if exp < time.time() or not hmac.compare_digest(self._sign(path, exp), sig or ""):
            return None
        full = self._file(path)
        return full if os.path.exists(full) else None
