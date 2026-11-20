"""Draw PPT-ready charts from the load-test results.

    python loadtest/make_charts.py --results loadtest/results --out proof/charts
"""
import argparse
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Validated categorical palette (fixed order) + text tokens
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
INK, INK2, GRID = "#1e293b", "#52514e", "#e5e7eb"
INSTANCE_COLOR = {"A": BLUE, "B": ORANGE, "C": AQUA}
PORT_TO_INSTANCE = {"8001": "A", "8002": "B", "8003": "C"}

plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"], "font.size": 11, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK,
    "axes.titleweight": "bold", "axes.titlesize": 13, "axes.titlelocation": "left",
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False, "figure.dpi": 100,
})


def save(fig, out, name):
    path = os.path.join(out, name)
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  chart:", path)


def history(path):
    rows = [r for r in csv.DictReader(open(path)) if r["Name"] == "Aggregated"]
    t0 = int(rows[0]["Timestamp"])
    out = []
    for r in rows:
        try:
            p95 = float(r["95%"]) if r["95%"] not in ("N/A", "") else None
        except ValueError:
            p95 = None
        out.append((int(r["Timestamp"]) - t0, float(r["Requests/s"]), p95, int(r["User Count"])))
    return out


def summary(path):
    for r in csv.DictReader(open(path)):
        if r["Name"] == "Aggregated":
            return {"rps": float(r["Requests/s"]), "avg": float(r["Average Response Time"]),
                    "p95": float(r["95%"]), "requests": int(r["Request Count"]),
                    "failures": int(r["Failure Count"])}


def scaling_charts(res, out):
    one, three = history(f"{res}/one_instance_stats_history.csv"), history(f"{res}/three_instances_stats_history.csv")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2))
    for data, label, col in ((one, "1 instance", ORANGE), (three, "3 instances + load balancer", BLUE)):
        ax1.plot([d[0] for d in data], [d[1] for d in data], color=col, lw=2, label=label)
        pts = [(d[0], d[2]) for d in data if d[2]]
        ax2.plot([p[0] for p in pts], [p[1] for p in pts], color=col, lw=2, label=label)
    ax1.set_title("Throughput (requests per second)")
    ax1.set_xlabel("seconds into test")
    ax2.set_title("95th-percentile response time (ms)")
    ax2.set_xlabel("seconds into test")
    ax1.legend(loc="lower right")
    ax2.legend(loc="upper left")
    fig.suptitle("150 simulated users: one instance vs three instances behind nginx",
                 x=0.01, ha="left", color=INK, fontsize=14, fontweight="bold", y=1.04)
    save(fig, out, "01-scaling-timeline.png")

    s1, s3 = summary(f"{res}/one_instance_stats.csv"), summary(f"{res}/three_instances_stats.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    metrics = [("rps", "Throughput (req/s)  ↑ better", "{:.0f}"), ("avg", "Average response (ms)  ↓ better", "{:.0f}"),
               ("p95", "95th percentile (ms)  ↓ better", "{:.0f}")]
    for ax, (k, title, fmt) in zip(axes, metrics):
        vals = [s1[k], s3[k]]
        bars = ax.bar(["1 instance", "3 instances"], vals, color=[ORANGE, BLUE], width=0.55)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, fmt.format(v), ha="center", va="bottom", color=INK, fontweight="bold")
        ax.set_title(title, fontsize=12)
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, max(vals) * 1.18)
    fig.suptitle(f"Result: {s3['rps'] / s1['rps']:.1f}× throughput, {s1['p95'] / s3['p95']:.0f}× faster p95, "
                 f"{s1['failures'] + s3['failures']} failed requests",
                 x=0.01, ha="left", color=INK, fontsize=14, fontweight="bold", y=1.06)
    save(fig, out, "02-scaling-summary.png")
    return s1, s3


def distribution_chart(res, out):
    rows = list(csv.DictReader(open(f"{res}/three_instances_instances.csv")))
    rows = [r for r in rows if r["instance"] in INSTANCE_COLOR]
    total = sum(int(r["responses"]) for r in rows)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    bars = ax.bar([f"Instance {r['instance']}" for r in rows], [int(r["responses"]) for r in rows],
                  color=[INSTANCE_COLOR[r["instance"]] for r in rows], width=0.55)
    for b, r in zip(bars, rows):
        n = int(r["responses"])
        ax.text(b.get_x() + b.get_width() / 2, n, f"{n:,}\n({n / total:.0%})", ha="center", va="bottom", color=INK)
    ax.set_ylim(0, max(int(r["responses"]) for r in rows) * 1.25)
    ax.set_title("Requests served by each instance (round robin)")
    ax.grid(axis="x", visible=False)
    save(fig, out, "03-load-distribution.png")
    return {r["instance"]: int(r["responses"]) for r in rows}


LOG_RE = re.compile(r"^(\S+) client=\S+ upstream=(.*?) status=(\d+) upstream_status=(.*?) rt=")


def failover_chart(res, out):
    kill = int(open(f"{res}/failover_kill_time").read())
    revive = int(open(f"{res}/failover_revive_time").read())
    per_sec = defaultdict(lambda: defaultdict(int))
    errors = defaultdict(int)
    t_first = None
    for line in open(f"{res}/failover_nginx_access.log"):
        m = LOG_RE.match(line)
        if not m:
            continue
        ts = int(datetime.fromisoformat(m.group(1)).timestamp())
        t_first = ts if t_first is None else min(t_first, ts)
        last = m.group(2).split(",")[-1].strip()           # the instance that finally answered
        inst = PORT_TO_INSTANCE.get(last.rsplit(":", 1)[-1], "?")
        if int(m.group(3)) >= 500:
            errors[ts] += 1
        elif inst != "?":
            per_sec[ts][inst] += 1
    secs = list(range(t_first, max(per_sec) + 1))
    x = [s - t_first for s in secs]
    fig, ax = plt.subplots(figsize=(12, 4.4))
    stacks = [[per_sec[s].get(i, 0) for s in secs] for i in "ABC"]
    ax.stackplot(x, *stacks, colors=[BLUE, ORANGE, AQUA], labels=["Instance A", "Instance B", "Instance C"],
                 alpha=0.95, edgecolor="white", linewidth=0.6, zorder=2)
    ax.axvspan(kill - t_first, revive - t_first, color="#94a3b8", alpha=0.25, lw=0, zorder=0)
    ax.annotate("Instance B killed\n(crash simulated)", xy=(kill - t_first, ax.get_ylim()[1] * 0.92),
                xytext=(kill - t_first + 1, ax.get_ylim()[1] * 0.92), color=INK, fontsize=10, va="top")
    ax.annotate("B restarted", xy=(revive - t_first, ax.get_ylim()[1] * 0.92),
                xytext=(revive - t_first + 1, ax.get_ylim()[1] * 0.92), color=INK, fontsize=10, va="top")
    err_x = [s - t_first for s in sorted(errors)]
    if err_x:
        ax.scatter(err_x, [2] * len(err_x), color=RED, s=40, zorder=5, label=f"Failed requests ({sum(errors.values())})")
    ax.set_title("Failover: requests per second answered by each instance")
    ax.set_xlabel("seconds into test")
    ax.set_ylabel("requests / second")
    ax.legend(loc="upper left", ncol=4, bbox_to_anchor=(0, -0.16))
    save(fig, out, "04-failover-timeline.png")
    total = sum(sum(v.values()) for v in per_sec.values()) + sum(errors.values())
    return {"total_requests": total, "failed": sum(errors.values()),
            "kill_second": kill - t_first, "revive_second": revive - t_first}


def ratelimit_chart(res, out):
    d = json.load(open(f"{res}/ratelimit.json"))
    groups = [("40 rapid login attempts\n(password-guessing bot)", d["login_summary"]),
              ("300 rapid page requests\n(flood from one client)", d["flood_summary"])]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    for i, (label, summ) in enumerate(groups):
        blocked = int(summ.get("429", 0))
        allowed = sum(int(v) for k, v in summ.items() if k != "429")
        ax.barh(i, allowed, color=BLUE, height=0.5, label="Allowed through" if i == 0 else None)
        ax.barh(i, blocked, left=allowed + 0.003 * (allowed + blocked), color=RED, height=0.5,
                label="Blocked: HTTP 429" if i == 0 else None)
        ax.text(allowed + blocked, i, f"  {blocked} blocked ({blocked / (allowed + blocked):.0%})",
                va="center", color=INK, fontweight="bold")
    ax.set_yticks([0, 1], [g[0] for g in groups])
    ax.invert_yaxis()
    ax.set_xlim(0, 380)
    ax.grid(axis="y", visible=False)
    ax.set_title("Rate limiting at the load balancer")
    ax.legend(loc="lower right")
    save(fig, out, "05-rate-limiting.png")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="loadtest/results")
    ap.add_argument("--out", default="proof/charts")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    s1, s3 = scaling_charts(a.results, a.out)
    dist = distribution_chart(a.results, a.out)
    fo = failover_chart(a.results, a.out)
    rl = ratelimit_chart(a.results, a.out)
    summary_out = {"one_instance": s1, "three_instances": s3, "distribution": dist, "failover": fo,
                   "ratelimit": {"login": rl["login_summary"], "flood": rl["flood_summary"],
                                 "other_user_status": rl["other_user_status_during_attack"]}}
    with open(os.path.join(a.out, "results-summary.json"), "w") as fh:
        json.dump(summary_out, fh, indent=2)
    print(json.dumps(summary_out, indent=2))
