"""
Deterministic replay over historical OHLCV: advances ephemeris clock per bar and prints score/classification.

Usage:
  python backtest_replay.py --csv path/to/eth_candles.csv --max-rows 300
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import load_csv
from ephemeris_engine import EphemerisEngine
from raw_data_engine import RawDataIngestion
from signal_engine import run_probability


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay signals over CSV (deterministic context, no OpenAI macro).")
    parser.add_argument("--csv", required=True, help="CSV with timestamp, open, high, low, close, volume")
    parser.add_argument("--max-rows", type=int, default=400, help="Only process the last N rows")
    parser.add_argument("--symbol", default="ETH")
    args = parser.parse_args()

    df = load_csv(args.csv).sort_values("timestamp").tail(int(args.max_rows)).reset_index(drop=True)
    ingest = RawDataIngestion()

    for i in range(len(df)):
        row = df.iloc[i]
        rts = pd.Timestamp(row["timestamp"])
        if rts.tzinfo is None:
            rts = rts.tz_localize("UTC")
        ingest.ephemeris.current_date = rts.to_pydatetime()
        ctx = ingest.build_context_light(args.symbol)
        sub = df.iloc[: i + 1].tail(120)
        if len(sub) < 22:
            continue
        ctx["price_history"] = sub
        out = run_probability(ctx)
        print(
            f"{rts.isoformat()} score={out['score']:.2f} class={out['classification']}",
        )


if __name__ == "__main__":
    main()
