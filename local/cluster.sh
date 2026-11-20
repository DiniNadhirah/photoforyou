#!/usr/bin/env bash
# Start a local cluster: 3 app instances (A, B, C) + nginx load balancer.
#   ./local/cluster.sh start [instances]    e.g. start 3
#   ./local/cluster.sh stop
#   ./local/cluster.sh kill B                (simulate an instance crash)
#   ./local/cluster.sh revive B
# Open http://localhost:8080
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/data/run"
export STORAGE_BACKEND=local
export LOCAL_DATA_DIR="$ROOT/data/cluster"
export SECRET_KEY="${SECRET_KEY:-local-cluster-shared-secret}"
export LB_TOKEN="${LB_TOKEN:-local-lb-token}"
export WEB_CONCURRENCY="${WEB_CONCURRENCY:-1}"
export THREADS="${THREADS:-4}"
export LOCAL_LATENCY_MS="${LOCAL_LATENCY_MS:-0}"
NAMES=(A B C); PORTS=(8001 8002 8003)

start_instance() {
  local i=$1
  cd "$ROOT"
  INSTANCE_NAME="${NAMES[$i]}" PORT="${PORTS[$i]}" \
    setsid nohup gunicorn app:app --pid "$RUN/app-${NAMES[$i]}.pid" \
    >>"$RUN/app-${NAMES[$i]}.log" 2>&1 </dev/null &
  disown || true
}

case "${1:-start}" in
  start)
    N="${2:-3}"
    mkdir -p "$RUN/tmp" "$LOCAL_DATA_DIR"
    for ((i=0; i<N; i++)); do start_instance $i; done
    sed -e "s#__RUN__#$RUN#g" -e "s#__LB_TOKEN__#$LB_TOKEN#g" \
        "$ROOT/local/nginx.conf.template" > "$RUN/nginx.conf"
    # When started as root, keep nginx workers as root so they can use the cache folder
    [ "$(id -u)" = "0" ] && sed -i '1i user root;' "$RUN/nginx.conf"
    if [ "$N" -lt 3 ]; then          # remove servers that are not running
      for ((i=N; i<3; i++)); do sed -i "/127.0.0.1:${PORTS[$i]}/d" "$RUN/nginx.conf"; done
    fi
    nginx -c "$RUN/nginx.conf" -p "$RUN"
    sleep 2
    echo "Cluster up: $N instance(s) behind nginx -> http://localhost:8080"
    ;;
  stop)
    [ -f "$RUN/nginx.pid" ] && nginx -c "$RUN/nginx.conf" -p "$RUN" -s quit || true
    for n in "${NAMES[@]}"; do [ -f "$RUN/app-$n.pid" ] && kill "$(cat "$RUN/app-$n.pid")" 2>/dev/null || true; done
    sleep 1; echo "Cluster stopped."
    ;;
  kill)
    pkill -9 -f "app-$2.pid" || true      # master + worker processes
    echo "Instance $2 killed."
    ;;
  revive)
    for i in 0 1 2; do [ "${NAMES[$i]}" = "$2" ] && start_instance $i; done
    sleep 2; echo "Instance $2 restarted."
    ;;
esac
