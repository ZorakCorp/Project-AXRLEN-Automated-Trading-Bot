#!/usr/bin/env python3
"""
Grid-search astrology vs technical domain weights using the same lab simulator as ``backtest_replay``.

Keeps astrology + technical = 0.60 (default combined share); other domains stay at ProbabilityEngine defaults.

Example:
  python tune_domain_weights.py --csv eth_15m.csv --max-rows 8000 --objective sharpe
"""

from __future__ import annotations

import argparse
import json
import math
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_replay import run_simulation
from data_loader import load_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-search DOMAIN_WEIGHTS_JSON overrides vs lab backtest.")
    parser.add_argument("--csv", required=True, help="OHLCV CSV (timestamp, open, high, low, close)")
    parser.add_argument("--max-rows", type=int, default=5000)
    parser.add_argument("--warmup", type=int, default=120)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--no-vedic-exits", action="store_true")
    parser.add_argument(
        "--objective",
        choices=("return", "sharpe"),
        default="return",
        help="Rank by total_return_pct or sharpe_est from the simulator",
    )
    parser.add_argument("--top", type=int, default=8, help="Print top N weight pairs")
    args = parser.parse_args()

    df = load_csv(args.csv).sort_values("timestamp").tail(int(args.max_rows)).reset_index(drop=True)

    fixed_sum = 0.38 + 0.22
    astro_grid = [0.30, 0.32, 0.34, 0.36, 0.38, 0.40, 0.42, 0.44, 0.46]
    results: list[tuple[float, str, dict]] = []

    for ast in astro_grid:
        tech = fixed_sum - ast
        if tech < 0.08 or tech > 0.35:
            continue
        dj = json.dumps({"astrology": round(ast, 4), "technical": round(tech, 4)})
        m = run_simulation(
            df,
            warmup=args.warmup,
            initial_capital=args.initial_capital,
            no_vedic_exits=args.no_vedic_exits,
            domain_weights_json=dj,
            quiet=True,
        )
        raw = float(m["total_return_pct"]) if args.objective == "return" else float(m["sharpe_est"])
        if math.isnan(raw):
            raw = float("-inf")
        results.append((raw, dj, m))

    results.sort(key=lambda x: x[0], reverse=True)

    print("--- tune_domain_weights (astro + technical sum = 0.60; other domains default) ---")
    for i, (obj, dj, m) in enumerate(results[: max(1, args.top)]):
        print(f"#{i + 1} objective={obj:.6f}")
        print(f"    DOMAIN_WEIGHTS_JSON={dj}")
        print(
            f"    return_pct={m['total_return_pct']:.4f} sharpe={m['sharpe_est']:.4f} "
            f"trades={m['trades']} max_dd_pct={m['max_drawdown_pct']:.4f}"
        )


if __name__ == "__main__":
    main()
