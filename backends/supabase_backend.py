"""Production backend: Supabase Postgres (tables `users`, `media`) and a
PRIVATE Supabase Storage bucket (default name `vault`).

Every query that touches media is filtered by user_id, so one account can
never read, change or delete another account's files."""
from supabase import create_client

from . import Backend


class SupabaseBackend(Backend):
    def __init__(self, url, key, bucket, signed_url_ttl=3600):
        super().__init__(signed_url_ttl)
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set "
                               "(or use STORAGE_BACKEND=local).")
        self.client = create_client(url, key)
        self.bucket = bucket

    def _store(self):
        return self.client.storage.from_(self.bucket)

    # ---- users ---------------------------------------------------------------
    def get_user_by_username(self, username):
        res = self.client.table("users").select("*").eq("username", username).limit(1).execute()
        return res.data[0] if res.data else None

    def get_user(self, user_id):
        res = self.client.table("users").select("*").eq("id", user_id).limit(1).execute()
        return res.data[0] if res.data else None

    def create_user(self, username, password_hash):
        res = self.client.table("users").insert(
            {"username": username, "password_hash": password_hash}).execute()
        return res.data[0]

    def set_vault(self, user_id, salt, check):
        self.client.table("users").update(
            {"vault_salt": salt, "vault_check": check}).eq("id", user_id).execute()

    # ---- media ---------------------------------------------------------------
    def list_media(self, user_id):
        res = (self.client.table("media").select("*")
               .eq("user_id", str(user_id))
               .order("created_at", desc=True).execute())
        return res.data

    def get_media(self, user_id, media_id):
        res = (self.client.table("media").select("*")
               .eq("user_id", str(user_id)).eq("id", media_id).limit(1).execute())
        return res.data[0] if res.data else None

    def insert_media(self, row):
        res = self.client.table("media").insert(row).execute()
        return res.data[0]

    def update_media(self, user_id, media_id, fields):
        res = (self.client.table("media").update(fields)
               .eq("user_id", str(user_id)).eq("id", media_id).execute())
        return bool(res.data)

    def delete_media(self, user_id, media_id):
        res = (self.client.table("media").delete()
               .eq("user_id", str(user_id)).eq("id", media_id).execute())
        return bool(res.data)

    def usage_bytes(self, user_id):
        res = self.client.table("media").select("size_bytes").eq("user_id", str(user_id)).execute()
        return sum(int(r["size_bytes"] or 0) for r in res.data)

    def ping(self):
        self.client.table("users").select("id").limit(1).execute()
        return True

    # ---- storage -------------------------------------------------------------
    def put_object(self, path, data, content_type="application/octet-stream"):
        self._store().upload(path=path, file=data, file_options={
            "content-type": content_type,
            "cache-control": "31536000",   # objects never change: cache for a year
        })

    def remove_objects(self, paths):
        if paths:
            self._store().remove(list(paths))
            self.forget_urls(paths)

    def _create_signed_urls(self, paths, ttl):
        items = self._store().create_signed_urls(list(paths), ttl)
        out = {}
        for item in items:
            url = item.get("signedURL") or item.get("signedUrl")
            if url and not item.get("error"):
                out[item["path"]] = url
        return out
