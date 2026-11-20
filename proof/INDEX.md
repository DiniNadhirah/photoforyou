# Proof index: CSEB5233 briefing items → evidence

Every item from the briefing slide ("80% PPT"), plus the lecturer's comment, with
the files that support it.
✅ = ready in this folder · 📸 = **you must take it yourselves** after deploying (see `docs/DEPLOY.md`).

| Briefing item | What to put in the PPT | Evidence |
|---|---|---|
| **Introduction** | iPhone users run out of iCloud space (5 GB free). PhotoForYou keeps full-quality photos and videos in the cloud, privately | ✅ `screenshots/06-gallery.png`, `screenshots/17-mobile-gallery.png` |
| **Project completion / constraint** | Completed: everything in README "What v2 adds". Constraints: README "Known limits" | ✅ `logs/e2e-browser-test-results.json` (all checks passed), `logs/pytest-results.txt` (19/19) |
| **Tools / services used** | Render (3 web services), Supabase Postgres + Storage, nginx, Flask, gunicorn, Web Crypto API, GitHub, Locust, pytest, Playwright | ✅ `diagrams/architecture-v2.png` · 📸 Render dashboard, Supabase tables and bucket |
| **Architecture diagram** | System architecture | ✅ `diagrams/architecture-v2.png` (editable source: `diagrams/source/architecture-v2.html`) |
| **Prompt log** | Summary table on one slide, full log in an appendix | ✅ `prompt-log.csv`. Add your partner's prompts and any from other AI tools |
| **Figures, steps, explanation** | One slide per feature: sign up → vault → upload → gallery → viewer → rename/move/delete | ✅ `screenshots/01` to `14` |
| **Work proof** | Deployed app, logs, tests, GitHub commits | ✅ `logs/*`, `loadtest/*_locust_report.html` · 📸 Render services + logs, Supabase, GitHub commit history, live LB URL |
| **Difficulties** | v1 bugs found and fixed + problems while building v2 | ✅ `../docs/CHANGES.md` |
| **Completeness** | Feature checklist with ticks | ✅ README "What v2 adds" + e2e checks |
| **Individual effort** | Who did what (keep it honest) | 📸 Split the work and show each person's commits or screenshots |
| **Lecturer: traffic handling / load balancing** | Load balancer, failover, rate limiting, scaling results | ✅ `charts/01` to `05`, `screenshots/19`, `screenshots/20`, `logs/nginx-access-log-sample.txt`, `logs/load-balancer-round-robin.txt`, `../docs/LOAD-TESTING.md` |
| **Privacy (your enhancement)** | Management can't see photos | ✅ `screenshots/18-management-view.png`, `screenshots/14-wrong-passphrase.png` |
| **Security** | Account isolation, headers | ✅ `screenshots/15-user-b-isolated.png`, `screenshots/16-user-b-blocked.png`, `logs/http-headers.txt` |

## Screenshots

| File | Shows |
|---|---|
| 01-register | Sign-up form |
| 02-vault-setup | Creating the vault passphrase (encryption key made on the device) |
| 03-gallery-empty | New account, empty gallery |
| 04-upload-queue | Several photos + a video selected at once |
| 05-upload-done | Each file encrypted and uploaded, with progress bars |
| 06-gallery | Folders A–Z, decrypted thumbnails, storage bar, search and sort |
| 07-viewer-photo | Full photo opened |
| 08-viewer-video | Video playing |
| 09-menu | View / Download original / Rename / Move / Delete |
| 10-rename | Rename dialog |
| 11-search-sort | Search "IMG_04", sort by name |
| 12-delete-confirm | In-page delete confirmation |
| 13-gallery-after | After rename, move (new "Favourites" folder) and delete |
| 14-wrong-passphrase | Wrong vault passphrase is rejected |
| 15-user-b-isolated | A second account sees only its own photo |
| 16-user-b-blocked | User B requesting user A's file by ID gets 404 |
| 17-mobile-gallery | Phone layout |
| 18-management-view | The real photo vs the scrambled bytes stored in the cloud |
| 19-rate-limited | Load balancer blocks a client sending too many requests |
| 20-load-balancer-footer | The same page answered by instance A, then B, then C |

## Key numbers (from `logs/loadtest-results-summary.json`)
- 150 users · **1 instance:** 111 req/s, p95 4,000 ms → **3 instances:** 235 req/s, p95 530 ms, 0 failures
- Even spread: A 7,069 · B 7,063 · C 7,072 requests
- Failover (instance B killed for 25 s): **1 failed request out of 10,982**
- Rate limit: 34 of 40 password guesses blocked, 256 of 300 flood requests blocked, other users unaffected
- These are local-cluster results with simulated cloud latency. Say so on the slide (see `../docs/LOAD-TESTING.md`)

## 📸 Checklist: take these on your own accounts
- [ ] Supabase: SQL Editor "Success" after `schema.sql`; Table Editor showing `users` and `media`; Storage showing the **private** `vault` bucket with `<user_id>` folders
- [ ] Supabase: open one `.bin` file, showing scrambled data (privacy proof on the real cloud)
- [ ] Render: dashboard with `photoforyou-a`, `photoforyou-b`, `photoforyou-lb` all "Live"
- [ ] Render: environment variables page (**hide the secret values**)
- [ ] Render: logs of A and B showing `instance=A` / `instance=B` lines
- [ ] Browser: `https://photoforyou-lb.onrender.com/health` alternating A and B
- [ ] Failover on Render: B suspended, site still works
- [ ] GitHub: commit history showing both members' commits
- [ ] Optional: small Locust run against Render (`docs/DEPLOY.md` step 5)
