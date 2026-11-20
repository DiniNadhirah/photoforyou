"""Gunicorn settings (read automatically by `gunicorn app:app`).
Each instance runs WEB_CONCURRENCY worker processes x THREADS threads, so one
instance can serve several requests at the same time."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("THREADS", "4"))
worker_class = "gthread"
timeout = 120            # large uploads on slow phone connections
graceful_timeout = 20
keepalive = 5
accesslog = "-"          # request log -> Render "Logs" tab (work proof)
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'
