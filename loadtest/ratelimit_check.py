"""Rate-limit test: ONE client (one IP) tries to log in 40 times in a few
seconds (like a password-guessing bot), then requests a page 300 times as
fast as possible. Records how many requests were let through vs blocked
(HTTP 429) by the load balancer / app."""
import argparse
import collections
import json
import re
import time

import requests

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8080")
ap.add_argument("--out", default="ratelimit.json")
a = ap.parse_args()

s = requests.Session()
s.headers["X-Forwarded-For"] = "203.0.113.50"          # the "attacker"
token = re.search(r'name="csrf-token" content="([^"]+)"', s.get(a.base + "/login").text).group(1)

login = []
t0 = time.time()
for i in range(40):
    r = s.post(a.base + "/login", data={"csrf_token": token, "username": "victim", "password": f"guess{i}"},
               allow_redirects=False)
    login.append({"n": i + 1, "t": round(time.time() - t0, 3), "status": r.status_code})

flood = []
t0 = time.time()
for i in range(300):
    r = s.get(a.base + "/health")
    flood.append({"n": i + 1, "t": round(time.time() - t0, 3), "status": r.status_code})

# A normal user at the same time is NOT affected
normal = requests.get(a.base + "/login", headers={"X-Forwarded-For": "198.51.100.7"}).status_code

res = {
    "login_attempts": login,
    "login_summary": dict(collections.Counter(x["status"] for x in login)),
    "flood_requests": flood,
    "flood_summary": dict(collections.Counter(x["status"] for x in flood)),
    "flood_seconds": flood[-1]["t"],
    "other_user_status_during_attack": normal,
}
with open(a.out, "w") as fh:
    json.dump(res, fh, indent=2)
print("login:", res["login_summary"], "| flood:", res["flood_summary"],
      "| other user:", normal)
