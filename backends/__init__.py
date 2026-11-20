"""Data layer. The app talks only to a Backend object, never directly to
Supabase, so the same routes work with:

  * SupabaseBackend - production (Postgres tables + private Storage bucket)
  * LocalBackend    - laptop / load-test cluster (SQLite + a folder on disk)
"""
import threading
import time


class Backend:
    """Shared logic for both backends: signed-URL caching."""

    def __init__(self, signed_url_ttl=3600):
        self.signed_url_ttl = signed_url_ttl
        self._url_cache = {}            # object path -> (url, expires_at)
        self._url_lock = threading.Lock()

    # ---- signed URLs with a small in-memory cache --------------------------
    # Re-using the same signed URL for a while means (1) one storage API call
    # for a whole gallery page instead of one per photo, and (2) the browser
    # can cache the encrypted thumbnail because the URL does not change.
    def signed_urls(self, paths):
        now = time.time()
        result, missing = {}, []
        with self._url_lock:
            for p in paths:
                cached = self._url_cache.get(p)
                if cached and cached[1] - now > 600:      # still valid for >10 min
                    result[p] = cached[0]
                else:
                    missing.append(p)
        if missing:
            fresh = self._create_signed_urls(missing, self.signed_url_ttl)
            with self._url_lock:
                for p, url in fresh.items():
                    self._url_cache[p] = (url, now + self.signed_url_ttl)
                    result[p] = url
        return result

    def forget_urls(self, paths):
        with self._url_lock:
            for p in paths:
                self._url_cache.pop(p, None)

    def _create_signed_urls(self, paths, ttl):  # pragma: no cover - abstract
        raise NotImplementedError


def make_backend(config):
    if config.STORAGE_BACKEND == "local":
        from .local_backend import LocalBackend
        return LocalBackend(config.LOCAL_DATA_DIR, config.SECRET_KEY,
                            latency_ms=config.LOCAL_LATENCY_MS,
                            signed_url_ttl=config.SIGNED_URL_TTL)
    from .supabase_backend import SupabaseBackend
    return SupabaseBackend(config.SUPABASE_URL, config.SUPABASE_KEY,
                           config.SUPABASE_BUCKET,
                           signed_url_ttl=config.SIGNED_URL_TTL)
