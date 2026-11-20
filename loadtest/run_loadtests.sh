#!/usr/bin/env bash
# Runs the load-test experiments on the local cluster and saves results.
#   ./loadtest/run_loadtests.sh scaling     1 instance vs 3 instances
#   ./loadtest/run_loadtests.sh failover    kill instance B in the middle
#   ./loadtest/run_loadtests.sh ratelimit   one client hammering the login
#   ./loadtest/run_loadtests.sh charts      draw the charts
# Every database/storage call gets LOCAL_LATENCY_MS of delay to imitate the
# network trip to a cloud database (Supabase) - see docs/LOAD-TESTING.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/loadtest/results"
USERS="${USERS:-150}"; RATE="${RATE:-15}"; TIME="${TIME:-90s}"
export LOCAL_LATENCY_MS="${LOCAL_LATENCY_MS:-50}"
mkdir -p "$OUT"
cd "$ROOT"

fresh_cluster() {   # $1 = number of instances
  ./local/cluster.sh stop >/dev/null 2>&1 || true
  rm -rf data/cluster data/run
  ./local/cluster.sh start "$1"
}

run_locust() {      # $1 = name, $2 = users, $3 = time
  INSTANCE_CSV="$OUT/$1_instances.csv" locust -f loadtest/locustfile.py --headless \
    -u "$2" -r "$RATE" -t "$3" --host http://localhost:8080 \
    --csv "$OUT/$1" --csv-full-history --html "$OUT/$1_report.html" --only-summary \
    --stop-timeout 5 2>&1 | tail -25 | tee "$OUT/$1_summary.txt" || true   # locust exits 1 if any request failed
  cp data/run/access.log "$OUT/$1_nginx_access.log"
}

case "${1:-all}" in
  scaling)
    fresh_cluster 1; run_locust one_instance "$USERS" "$TIME"
    fresh_cluster 3; run_locust three_instances "$USERS" "$TIME"
    ;;
  failover)
    fresh_cluster 3
    ( sleep 30; date +%s > "$OUT/failover_kill_time"; ./local/cluster.sh kill B
      sleep 25; date +%s > "$OUT/failover_revive_time"; ./local/cluster.sh revive B ) &
    run_locust failover 80 80s
    wait
    ;;
  ratelimit)
    fresh_cluster 3
    python loadtest/ratelimit_check.py --base http://localhost:8080 --out "$OUT/ratelimit.json"
    ;;
  charts)
    python loadtest/make_charts.py --results "$OUT" --out "$ROOT/proof/charts"
    ;;
esac
./local/cluster.sh stop >/dev/null 2>&1 || true
