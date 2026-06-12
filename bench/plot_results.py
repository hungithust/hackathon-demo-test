"""Render the CPU-vs-cuOpt comparison charts from bench/results.json.

Produces (in bench/charts/):
  1. latency_scaling.png    — solve time vs #customers, 1-depot & 5-depot, log-y
  2. quality_scaling.png    — total route minutes vs #customers (lower = better)
  3. depot_1_vs_5.png       — grouped bars: latency at 1 vs 5 depots per size
  4. concurrency_1000.png   — wall-clock to clear 1000 user requests, CPU vs cuOpt
  5. speedup_table.png      — table: speedup & quality gap per size

Reads only the JSON, so you can re-style without re-running the (slow) solves.
Run:  python -m bench.plot_results
"""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results.json")
OUT = os.path.join(HERE, "charts")

CPU_C = "#1f77b4"   # blue  = CPU / OR-Tools
GPU_C = "#76b900"   # green = NVIDIA cuOpt


def _load():
    with open(RESULTS, encoding="utf-8") as f:
        return json.load(f)


def _xy(rows, key):
    return [r["n_customers"] for r in rows], [r[key] for r in rows]


def latency_scaling(data):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (title, block) in zip(
            axes, [("1 depot", data["single_depot"]),
                   ("5 depots", data["multi_depot"])]):
        x, y = _xy(block["cpu"], "latency_ms")
        ax.plot(x, y, "o-", color=CPU_C, lw=2, label="CPU — OR-Tools")
        if block.get("cuopt"):
            xg, yg = _xy(block["cuopt"], "latency_ms")
            ax.plot(xg, yg, "s-", color=GPU_C, lw=2, label="GPU — cuOpt")
        ax.set_yscale("log")
        ax.set_title(f"Solve latency — {title}")
        ax.set_xlabel("number of customers")
        ax.grid(True, which="both", ls=":", alpha=0.5)
    axes[0].set_ylabel("solve time (ms, log scale)")
    axes[0].legend()
    fig.suptitle("How fast: CPU (OR-Tools) vs GPU (cuOpt) — lower is better",
                 fontweight="bold")
    fig.tight_layout()
    p = os.path.join(OUT, "latency_scaling.png")
    fig.savefig(p, dpi=130); plt.close(fig); return p


def quality_scaling(data):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, (title, block) in zip(
            axes, [("1 depot", data["single_depot"]),
                   ("5 depots", data["multi_depot"])]):
        x, y = _xy(block["cpu"], "total_time_min")
        ax.plot(x, y, "o-", color=CPU_C, lw=2, label="CPU — OR-Tools")
        if block.get("cuopt"):
            xg, yg = _xy(block["cuopt"], "total_time_min")
            ax.plot(xg, yg, "s-", color=GPU_C, lw=2, label="GPU — cuOpt")
        ax.set_title(f"Plan quality — {title}")
        ax.set_xlabel("number of customers")
        ax.grid(True, ls=":", alpha=0.5)
    axes[0].set_ylabel("total route time (min) — lower = more optimal")
    axes[0].legend()
    fig.suptitle("How optimal: total fleet drive time — lower is better",
                 fontweight="bold")
    fig.tight_layout()
    p = os.path.join(OUT, "quality_scaling.png")
    fig.savefig(p, dpi=130); plt.close(fig); return p


def depot_1_vs_5(data):
    import numpy as np
    sizes = [r["n_customers"] for r in data["single_depot"]["cpu"]]
    cpu1 = [r["latency_ms"] for r in data["single_depot"]["cpu"]]
    cpu5 = [r["latency_ms"] for r in data["multi_depot"]["cpu"]]
    x = np.arange(len(sizes)); w = 0.35
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.bar(x - w/2, cpu1, w, color=CPU_C, label="CPU — 1 depot")
    ax.bar(x + w/2, cpu5, w, color="#a9cce3", label="CPU — 5 depots")
    if data["single_depot"].get("cuopt"):
        g1 = [r["latency_ms"] for r in data["single_depot"]["cuopt"]]
        g5 = [r["latency_ms"] for r in data["multi_depot"]["cuopt"]]
        ax.plot(x - w/2, g1, "s--", color=GPU_C, label="cuOpt — 1 depot")
        ax.plot(x + w/2, g5, "D--", color="#4d7c00", label="cuOpt — 5 depots")
    ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels(sizes)
    ax.set_xlabel("number of customers"); ax.set_ylabel("solve time (ms, log)")
    ax.set_title("1 depot vs 5 depots — solve latency", fontweight="bold")
    ax.legend(); ax.grid(True, which="both", axis="y", ls=":", alpha=0.5)
    fig.tight_layout()
    p = os.path.join(OUT, "depot_1_vs_5.png")
    fig.savefig(p, dpi=130); plt.close(fig); return p


def concurrency_1000(data):
    c = data["concurrency"]
    engines, walls, colors = [], [], []
    engines.append(f"CPU — OR-Tools\n({c['local_cores']} cores)")
    walls.append(c["cpu"]["wall_s_1000"]); colors.append(CPU_C)
    if c.get("cuopt"):
        engines.append("GPU — cuOpt\n(1 server)")
        walls.append(c["cuopt"]["wall_s_1000"]); colors.append(GPU_C)
    fig, ax = plt.subplots(figsize=(8, 5.5))
    bars = ax.bar(engines, walls, color=colors, width=0.55)
    ax.set_yscale("log")
    ax.set_ylabel("wall-clock to clear 1000 solves (s, log)")
    ax.set_title(f"1000 concurrent users — time to serve all requests\n"
                 f"(probe: {c['probe_problem']}-customer reroute each)",
                 fontweight="bold")
    for b, w in zip(bars, walls):
        lbl = f"{w:.1f}s" if w < 90 else f"{w/60:.1f} min" if w < 5400 else f"{w/3600:.1f} h"
        ax.text(b.get_x() + b.get_width()/2, w, lbl, ha="center", va="bottom",
                fontweight="bold")
    ax.grid(True, which="both", axis="y", ls=":", alpha=0.5)
    fig.tight_layout()
    p = os.path.join(OUT, "concurrency_1000.png")
    fig.savefig(p, dpi=130); plt.close(fig); return p


def speedup_table(data):
    if not data["single_depot"].get("cuopt"):
        return None
    rows = []
    for cp, gp in zip(data["single_depot"]["cpu"], data["single_depot"]["cuopt"]):
        n = cp["n_customers"]
        speed = gp["latency_ms"] / cp["latency_ms"]   # >1 => CPU faster
        qgap = (cp["total_time_min"] - gp["total_time_min"]) / gp["total_time_min"] * 100
        rows.append([
            f"{n}",
            f"{cp['latency_ms']:.0f} ms",
            f"{gp['latency_ms']/1000:.1f} s",
            f"CPU {speed:.0f}x faster" if speed >= 1 else f"cuOpt {1/speed:.1f}x faster",
            f"cuOpt {qgap:+.0f}% better" if qgap > 0 else f"CPU {-qgap:.0f}% better",
        ])
    fig, ax = plt.subplots(figsize=(11, 0.6 + 0.5 * len(rows)))
    ax.axis("off")
    cols = ["customers", "CPU time", "cuOpt time", "speed winner", "route-quality winner"]
    tbl = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(11); tbl.scale(1, 1.6)
    for j in range(len(cols)):
        tbl[0, j].set_facecolor("#222"); tbl[0, j].set_text_props(color="w", fontweight="bold")
    ax.set_title("CPU (OR-Tools) vs GPU (cuOpt) — 1 depot summary",
                 fontweight="bold", pad=14)
    fig.tight_layout()
    p = os.path.join(OUT, "speedup_table.png")
    fig.savefig(p, dpi=130); plt.close(fig); return p


def main():
    os.makedirs(OUT, exist_ok=True)
    data = _load()
    made = [latency_scaling(data), quality_scaling(data), depot_1_vs_5(data),
            concurrency_1000(data), speedup_table(data)]
    for p in made:
        if p:
            print("wrote", p)


if __name__ == "__main__":
    main()