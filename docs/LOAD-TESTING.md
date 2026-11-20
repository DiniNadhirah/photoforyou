# Load testing: method and results

## Setup
| Item | Value |
|---|---|
| Tool | [Locust](https://locust.io) 2.32 (open source), headless |
| Where | Local test cluster on one Linux machine (2 CPU cores, 7 GB RAM): nginx 1.24 load balancer + up to 3 app instances (gunicorn, 1 worker × 4 threads each, like a small free-plan instance) |
| Storage | Local backend (SQLite + disk). Every database/storage call is delayed by **50 ms** (`LOCAL_LATENCY_MS=50`) to imitate the network round trip to a cloud database like Supabase |
| Users | 150 simulated users, started at 15 per second, 90 seconds per run. Each signs up, creates a vault and uploads 3 files, then browses with 1–3 s pauses: gallery page, media list, thumbnails, open original, occasional upload, health check |
| Clients | Each simulated user has its own IP (via `X-Forwarded-For`), so rate limits treat them as different people |

## Results

### 1 instance vs 3 instances behind the load balancer
| | 1 instance | 3 instances | Change |
|---|---|---|---|
| Throughput | 111 req/s | 235 req/s | **2.1× more** |
| Average response | 786 ms | 90 ms | **8.7× faster** |
| 95th percentile | 4,000 ms | 530 ms | **7.5× faster** |
| Failed requests | 0 of 10,040 | 0 of 21,005 | none |

With one instance, requests queue up (all 4 threads busy), so response times climb into seconds.
With three, the queue disappears and the same users get answers quickly.
Requests were spread almost exactly evenly: A 7,069 · B 7,063 · C 7,072 (round robin).

### Failover
80 users, 80 s. Instance B was killed (`kill -9`) at second 30 and restarted at second 55.
- 10,982 requests, **1 failed (0.01%)**. It was an upload that was being processed by B at the moment it died.
- nginx detected B as down, sent all traffic to A and C, and put B back into rotation when it returned.
- See `proof/charts/04-failover-timeline.png`.

### Rate limiting
One client (one IP):
- 40 rapid login attempts: **6 allowed, 34 blocked** (HTTP 429)
- 300 rapid requests: **44 allowed, 256 blocked**
- Another user at the same time: **not affected** (HTTP 200)

## Be honest about this in the presentation
- These numbers come from a **local cluster with simulated cloud latency**, not from Render. Render's free instances are much smaller (0.1 CPU), so the absolute numbers there will be lower. The **comparison** (1 vs 3 instances, failover, rate limits) is what the test shows.
- In this local test, encrypted thumbnails are served by the app itself. On Render/Supabase they come straight from Supabase Storage, which takes even more load off the app.
- To get real cloud numbers, run the small Render test in `docs/DEPLOY.md` step 5.

## Re-run
```bash
pip install -r requirements-dev.txt          # Linux / Mac / WSL with nginx installed
./loadtest/run_loadtests.sh scaling
./loadtest/run_loadtests.sh failover
./loadtest/run_loadtests.sh ratelimit
./loadtest/run_loadtests.sh charts           # -> proof/charts/*.png
```
