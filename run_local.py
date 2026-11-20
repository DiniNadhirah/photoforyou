"""Run PhotoForYou on your own computer WITHOUT Supabase (Windows, Mac, Linux).

    pip install -r requirements.txt
    python run_local.py
Then open http://localhost:5000

Data is saved in the ./data/dev folder (SQLite database + encrypted files).
"""
import os

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("LOCAL_DATA_DIR", os.path.join(os.path.dirname(__file__), "data", "dev"))
os.environ.setdefault("SECRET_KEY", "dev-only-secret-change-me")
os.environ.setdefault("INSTANCE_NAME", "dev")

from app import app  # noqa: E402  (import after the settings above)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"PhotoForYou running on http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
