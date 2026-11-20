"""All settings come from environment variables, so the same code runs
locally, on every Render instance and in tests without changes."""
import os
import secrets


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Core -------------------------------------------------------------
    # Every app instance behind the load balancer MUST share the same
    # SECRET_KEY, otherwise a login made on instance A is rejected by B.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "local")

    # "supabase" in production, "local" for running/testing on a laptop
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "supabase")

    # --- Supabase -----------------------------------------------------------
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
    # Use the service_role key. It stays on the server and is never sent
    # to the browser; the browser only ever receives short-lived signed URLs.
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
    SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "vault")

    # --- Local backend (development / load testing) -------------------------
    LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
    # Adds an artificial delay to every database/storage call, to imitate
    # the network round trip to a real cloud database during load tests.
    LOCAL_LATENCY_MS = int(os.environ.get("LOCAL_LATENCY_MS", "0"))

    # --- Limits -------------------------------------------------------------
    MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "50"))        # Supabase free plan: 50 MB per file
    USER_QUOTA_MB = int(os.environ.get("USER_QUOTA_MB", "200"))   # Supabase free plan: 1 GB in total
    MAX_CONTENT_LENGTH = (MAX_FILE_MB + 5) * 1024 * 1024          # file + encrypted thumbnail
    SIGNED_URL_TTL = int(os.environ.get("SIGNED_URL_TTL", "3600"))

    # --- Rate limits (per client IP, per instance) ---------------------------
    RATE_LIMIT_ENABLED = _bool("RATE_LIMIT_ENABLED", True)
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    REGISTER_RATE_LIMIT = os.environ.get("REGISTER_RATE_LIMIT", "5 per minute")
    UPLOAD_RATE_LIMIT = os.environ.get("UPLOAD_RATE_LIMIT", "60 per minute")

    # Number of proxies in front of the app that add X-Forwarded-For
    # (nginx load balancer = 1). Needed to see the real client IP.
    TRUST_PROXY_HOPS = int(os.environ.get("TRUST_PROXY_HOPS", "1"))
    # Shared secret between the nginx load balancer and the app instances.
    # The app only believes the "X-Client-IP" header when this token matches.
    LB_TOKEN = os.environ.get("LB_TOKEN", "")

    # --- Cookies --------------------------------------------------------------
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)  # True on Render (HTTPS)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8 hours

    WTF_CSRF_TIME_LIMIT = None  # token valid for the whole session
    # Behind the load balancer the app sees its own Render host name, while the
    # browser's Referer shows the load balancer's host name. The strict HTTPS
    # Referer check would reject every form, so it is off; the CSRF TOKEN check
    # (plus SameSite=Lax cookies) still protects every POST/PATCH/DELETE.
    WTF_CSRF_SSL_STRICT = False
