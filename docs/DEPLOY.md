# Deploying PhotoForYou v2 (Render + Supabase)

About 30–40 minutes. Take a screenshot at every 📸, because those are your **work proof**.

## 1. Supabase: database and private bucket

1. Open your Supabase project, then **SQL Editor → New query**.
2. Paste all of [`schema.sql`](../schema.sql) and click **Run**. 📸 the "Success" result.
   - It keeps your existing `users` accounts and adds the vault columns.
   - It creates the new `media` table and the **private** bucket `vault`.
   - It does **not** touch the old `photos` table or the old public `Photos` bucket. Delete those yourselves once v2 works, because the old bucket is public.
3. **Storage**: check that `vault` shows as **Private**. 📸
4. **Project Settings → API**: copy the **Project URL** and the **service_role** key (not the anon key).
   The service_role key stays on Render only. It is never sent to the browser.

## 2. GitHub
Push this whole folder to your GitHub repo, in the `main` branch. 📸 the repo page.

## 3. Render: two app instances + a load balancer

### Option A: Blueprint (recommended)
1. Render dashboard → **New → Blueprint** → choose your repo. Render reads `render.yaml` and creates:
   - `photoforyou-a`: app instance A
   - `photoforyou-b`: app instance B
   - `photoforyou-lb`: nginx load balancer
2. When asked, fill in for **both** `photoforyou-a` and `photoforyou-b`:
   - `SUPABASE_URL` = your Project URL
   - `SUPABASE_KEY` = your service_role key
3. After A and B are live, copy their addresses, e.g. `photoforyou-a.onrender.com`.
   In `photoforyou-lb → Environment`, set:
   - `UPSTREAM_A_HOST` = `photoforyou-a.onrender.com` (no `https://`, no `/`)
   - `UPSTREAM_B_HOST` = `photoforyou-b.onrender.com`
   Save; the load balancer redeploys. 📸 the three services on the dashboard.

`SECRET_KEY` and `LB_TOKEN` are generated once in the shared group `photoforyou-shared`, so all services get the **same** values. This is required: a login made on A must also be valid on B.

### Option B: by hand (if you keep your old service)
Create two Python web services from the repo (build `pip install -r requirements.txt`,
start `gunicorn app:app`) and one Docker web service with root directory `lb`.
Give A and B the **same** `SECRET_KEY` and `LB_TOKEN`, plus `INSTANCE_NAME` = `A` or `B`,
`STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_KEY`, `SESSION_COOKIE_SECURE=true`.
Give the load balancer `LB_TOKEN`, `UPSTREAM_A_HOST`, `UPSTREAM_B_HOST` and `PORT=10000`.

## 4. Check it works
Use the **load balancer URL** (`https://photoforyou-lb.onrender.com`) from now on.

| Check | How | Expected |
|---|---|---|
| Wake everything | Open the A, B and LB URLs once and wait about 1 minute | Free services sleep after 15 minutes |
| Load balancing | Open `…-lb.onrender.com/health` and refresh several times | `"instance":"A"` and `"instance":"B"` alternate 📸 |
| Footer | Reload the login page a few times | "served by instance A / B" changes 📸 |
| Full flow | Sign up → create vault → upload photos and a video → gallery | Thumbnails appear 📸 each page |
| Privacy | Supabase → Storage → vault → open any `.bin` file | Unreadable scrambled data 📸 |
| Isolation | Second account in an incognito window | Sees none of the first account's photos 📸 |
| Failover | Render → photoforyou-b → **Suspend**, then use the site | It keeps working on A only 📸 Then **Resume** |
| Rate limit | Enter a wrong password 15 times quickly | "Too many requests" page 📸 |
| Logs | Render → photoforyou-a → Logs | Lines like `instance=A method=GET path=/api/media status=200 ms=…` 📸 |

## 5. Load test against Render (optional, for real cloud numbers)
Keep it small. Bandwidth counts against Render's free limits.
```bash
pip install -r requirements-dev.txt
locust -f loadtest/locustfile.py --headless -u 20 -r 2 -t 60s \
       --host https://photoforyou-lb.onrender.com --html render_report.html
```
Run it once with B suspended (1 instance) and once with both running, then compare. 📸 the report.

## 6. After the presentation
Delete the services on Render and pause or delete the Supabase project, so nothing keeps running.

## Troubleshooting
| Problem | Fix |
|---|---|
| Login works, then "Please log in again" | A and B have different `SECRET_KEY` values. Use the shared env group. |
| Load balancer shows 502 | `UPSTREAM_*_HOST` is wrong (remove `https://`), or A/B are still waking up. |
| Upload fails with 403/400 from Supabase | Using the anon key. Use the **service_role** key, and check that the `vault` bucket exists. |
| Thumbnails don't load | Look in the browser console for CSP errors. `SUPABASE_URL` must be set exactly (`https://xxxx.supabase.co`). |
| "Vault already exists" | Normal after the first setup. Unlock with the same passphrase. |
