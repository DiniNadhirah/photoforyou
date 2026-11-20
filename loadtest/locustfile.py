"""Load test for PhotoForYou (Locust, open source).

Each simulated user signs up, creates a vault, uploads a few (encrypted-size)
files, then browses: opens the gallery, lists media, loads thumbnails, opens
originals and sometimes uploads another file.

    locust -f loadtest/locustfile.py --host http://localhost:8080
    (or headless: see loadtest/run_loadtests.sh)

Every simulated user sends a different X-Forwarded-For address so the load
balancer treats them as different people (real users have different IPs).
"""
import collections
import csv
import os
import random
import re
import uuid

from locust import HttpUser, between, events, task

INSTANCE_COUNTS = collections.Counter()
OVERHEAD = 28
CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


@events.request.add_listener
def count_instance(response=None, exception=None, **_):
    if response is not None and exception is None:
        INSTANCE_COUNTS[response.headers.get("X-Instance", "?")] += 1


@events.quitting.add_listener
def save_instance_counts(environment, **_):
    path = os.environ.get("INSTANCE_CSV")
    if path:
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["instance", "responses"])
            for name, n in sorted(INSTANCE_COUNTS.items()):
                w.writerow([name, n])


class PhotoUser(HttpUser):
    wait_time = between(1, 3)     # a real person pauses between clicks

    def on_start(self):
        ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        self.client.headers["X-Forwarded-For"] = ip
        self.username = "load_" + uuid.uuid4().hex[:10]
        page = self.client.get("/register", name="/register [page]")
        token = CSRF_RE.search(page.text).group(1)
        self.client.post("/register", name="/register [submit]", data={
            "csrf_token": token, "username": self.username,
            "password": "LoadTest123!", "confirm": "LoadTest123!"})
        page = self.client.get("/", name="/ [gallery page]")
        self.token = CSRF_RE.search(page.text).group(1)
        self.client.headers["X-CSRFToken"] = self.token
        self.client.post("/api/vault", json={"salt": "c2FsdHNhbHRzYWx0c2FsdA", "check": "Y2hlY2tjaGVja2NoZWNr"})
        self.ids = []
        for _ in range(3):
            self.upload()

    def upload(self):
        size = random.randint(20_000, 80_000)
        files = {"file": ("file.bin", os.urandom(size + OVERHEAD)),
                 "thumb": ("thumb.bin", os.urandom(6_000))}
        data = {"mime": "image/jpeg", "size": str(size), "name_enc": "bG9hZHRlc3Q",
                "folder": random.choice(["Holiday", "Family", "Study"])}
        with self.client.post("/api/media", files=files, data=data, name="/api/media [upload]",
                              catch_response=True) as r:
            if r.status_code == 201:
                self.ids.append(r.json()["item"]["id"])
                r.success()
            else:
                r.failure(f"upload {r.status_code}")

    @task(4)
    def browse_gallery(self):
        self.client.get("/", name="/ [gallery page]")
        r = self.client.get("/api/media", name="/api/media [list]")
        if r.ok:
            thumbs = [i["thumb_url"] for i in r.json()["items"] if i["thumb_url"]][:4]
            for url in thumbs:
                self.client.get(url, name="[thumbnail via signed URL]")

    @task(2)
    def open_original(self):
        if self.ids:
            r = self.client.get(f"/api/media/{random.choice(self.ids)}/url", name="/api/media/[id]/url")
            if r.ok:
                self.client.get(r.json()["url"], name="[original via signed URL]")

    @task(1)
    def upload_more(self):
        self.upload()

    @task(1)
    def health(self):
        self.client.get("/health", name="/health")
