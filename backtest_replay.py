"""
Deterministic replay over historical OHLCV: advances ephemeris clock per bar, runs the signal
pipeline (no OpenAI macro), optionally simulates entries with TP/SL and reports PnL metrics.

Usage:
  python backtest_replay.py --csv path/to/eth_candles.csv --max-rows 5000
  python backtest_replay.py --csv eth.csv --max-rows 20000 --simulate --no-per-bar

Eclipse almanac: one ``refresh_eclipse_anchor_if_needed`` at the series end-JD, then
``SKIP_ECLIPSE_ALMANAC_REFRESH`` for the bar loop so ``sol_eclipse_when_glob`` is not repeated.

Simulation (``--simulate``) is a lab model: full-equity compounding, intrabar TP/SL, signal flip,
and (unless ``--no-vedic-exits``) long force-exits when ``risk_flags`` match live Pancha /
eclipse-degree rules. No exchange fees, leverage sizing, or full bot order flow.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT
from data_loader import load_csv
from ephemeris_engine import EphemerisEngine
from raw_data_engine import RawDataIngestion
from signal_engine import run_probability


def _row_ts(row: pd.Series) -> pd.Timestamp:
    rts = pd.Timestamp(row["timestamp"])
    if rts.tzinfo is None:
        rts = rts.tz_localize("UTC")
    return rts


def _mark_equity(capital: float, position: Optional[Dict[str, Any]], mark: float) -> float:
    if not position:
        return float(capital)
    entry = float(position["entry"])
    if position["side"] == "long":
        return float(capital) * (float(mark) / entry)
    return float(capital) * (2.0 - float(mark) / entry)


def _exit_long(
    h: float,
    low: float,
    c: float,
    classification: str,
    tp: float,
    sl: float,
) -> Tuple[Optional[str], Optional[float]]:
    if low <= sl and h >= tp:
        return "sl", sl
    if low <= sl:
        return "sl", sl
    if h >= tp:
        return "tp", tp
    if classification != "LONG":
        return "signal", c
    return None, None


def _exit_short(
    h: float,
    low: float,
    c: float,
    classification: str,
    tp: float,
    sl: float,
) -> Tuple[Optional[str], Optional[float]]:
    if high >= sl and low <= tp:
        return "sl", sl
    if high >= sl:
        return "sl", sl
    if low <= tp:
        return "tp", tp
    if classification != "SHORT":
        return "signal", c
    return None, None


def run_simulation(
    df: pd.DataFrame,
    *,
    symbol: str = "ETH",
    warmup: int = 120,
    initial_capital: float = 100_000.0,
    no_vedic_exits: bool = False,
    domain_weights_json: Optional[str] = None,
    quiet: bool = True,
) -> Dict[str, Any]:
    """
    Run one deterministic backtest simulation over ``df`` (OHLCV). Optionally override
    ``DOMAIN_WEIGHTS_JSON`` for this process (merged in ``ProbabilityEngine`` each bar).

    Returns metrics including ``domain_weights_json`` echo and optional ``equity_curve`` keys.
    """
    ingest = RawDataIngestion()
    tp_frac = float(DEFAULT_TAKE_PROFIT_PCT) / 100.0
    sl_frac = float(DEFAULT_STOP_LOSS_PCT) / 100.0

    from eclipse_almanac import refresh_eclipse_anchor_if_needed

    prev_weights = os.environ.pop("DOMAIN_WEIGHTS_JSON", None)
    prev_skip_saved = os.environ.pop("SKIP_ECLIPSE_ALMANAC_REFRESH", None)

    if domain_weights_json:
        os.environ["DOMAIN_WEIGHTS_JSON"] = domain_weights_json

    last_row = df.iloc[-1]
    ingest.ephemeris.current_date = _row_ts(last_row).to_pydatetime()
    refresh_eclipse_anchor_if_needed(EphemerisEngine._julian_day(ingest.ephemeris.current_date))
    os.environ["SKIP_ECLIPSE_ALMANAC_REFRESH"] = "1"

    equity_curve: List[float] = []
    ts_curve: List[pd.Timestamp] = []
    trades: List[Dict[str, Any]] = []
    position: Optional[Dict[str, Any]] = None
    capital = float(initial_capital)
    wins = 0
    peak_eq = float(initial_capital)
    max_dd = 0.0

    try:
        wu = max(22, int(warmup))
        for i in range(len(df)):
            row = df.iloc[i]
            rts = _row_ts(row)
            ingest.ephemeris.current_date = rts.to_pydatetime()
            ctx = ingest.build_context_light(symbol, slim_feeds=True, refresh_eclipse_anchor=False)
            sub = df.iloc[: i + 1].tail(wu)
            if len(sub) < 22:
                continue
            ctx["price_history"] = sub
            out = run_probability(ctx)
            score = float(out["score"])
            classification = str(out["classification"])

            hi = float(row["high"])
            low = float(row["low"])
            c = float(row["close"])

            if position is not None:
                tp = float(position["tp"])
                sl = float(position["sl"])
                reason: Optional[str] = None
                exit_px: Optional[float] = None
                if not no_vedic_exits and position.get("side") == "long":
                    rf = ctx.get("risk_flags") or {}
                    if rf.get("pancha_vedha_exit_long"):
                        reason, exit_px = "pancha", c
                    elif rf.get("eclipse_degree_trigger"):
                        reason, exit_px = "eclipse_degree", c
                if reason is None and position["side"] == "long":
                    reason, exit_px = _exit_long(hi, low, c, classification, tp, sl)
                elif reason is None:
                    reason, exit_px = _exit_short(hi, low, c, classification, tp, sl)
                if reason is not None and exit_px is not None:
                    entry = float(position["entry"])
                    side = position["side"]
                    if side == "long":
                        pnl_pct = (float(exit_px) - entry) / entry
                    else:
                        pnl_pct = (entry - float(exit_px)) / entry
                    capital *= 1.0 + pnl_pct
                    trades.append(
                        {
                            "exit_time": rts.isoformat(),
                            "side": side,
                            "reason": reason,
                            "entry": entry,
                            "exit": float(exit_px),
                            "pnl_pct": round(pnl_pct * 100.0, 4),
                            "equity_after": round(capital, 2),
                        }
                    )
                    if pnl_pct > 0:
                        wins += 1
                    position = None

            if position is None:
                if classification == "LONG":
                    position = {
                        "side": "long",
                        "entry": c,
                        "tp": c * (1.0 + tp_frac),
                        "sl": c * (1.0 - sl_frac),
                    }
                elif classification == "SHORT":
                    position = {
                        "side": "short",
                        "entry": c,
                        "tp": c * (1.0 - tp_frac),
                        "sl": c * (1.0 + sl_frac),
                    }

            eq = _mark_equity(capital, position, c)
            equity_curve.append(eq)
            ts_curve.append(rts)
            peak_eq = max(peak_eq, eq)
            max_dd = max(max_dd, (peak_eq - eq) / peak_eq if peak_eq > 0 else 0.0)

            if not quiet:
                print(f"{rts.isoformat()} score={score:.2f} class={classification}")

        n = len(trades)
        win_rate = (wins / n * 100.0) if n else 0.0
        total_ret = (capital / float(initial_capital) - 1.0) * 100.0
        sharpe = _sharpe_ratio(equity_curve, ts_curve)
        return {
            "warmup": wu,
            "bars": len(df),
            "trades": n,
            "win_rate_pct": win_rate,
            "initial_capital": initial_capital,
            "final_equity": capital,
            "total_return_pct": total_ret,
            "max_drawdown_pct": max_dd * 100.0,
            "sharpe_est": sharpe,
            "vedic_long_exits": not no_vedic_exits,
            "domain_weights_json": domain_weights_json or "",
        }
    finally:
        os.environ.pop("SKIP_ECLIPSE_ALMANAC_REFRESH", None)
        if prev_skip_saved is not None:
            os.environ["SKIP_ECLIPSE_ALMANAC_REFRESH"] = prev_skip_saved
        if prev_weights is not None:
            os.environ["DOMAIN_WEIGHTS_JSON"] = prev_weights
        elif domain_weights_json:
            os.environ.pop("DOMAIN_WEIGHTS_JSON", None)


def _sharpe_ratio(equity_series: List[float], timestamps: List[pd.Timestamp]) -> float:
    if len(equity_series) < 3 or len(timestamps) < 3:
        return float("nan")
    rets: List[float] = []
    for i in range(1, len(equity_series)):
        prev = equity_series[i - 1]
        cur = equity_series[i]
        if prev <= 0:
            continue
        rets.append(math.log(cur / prev))
    if len(rets) < 2:
        return float("nan")
    mean_r = sum(rets) / len(rets)
    var = sum((x - mean_r) ** 2 for x in rets) / max(len(rets) - 1, 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return float("nan")
    span_sec = (timestamps[-1] - timestamps[0]).total_seconds()
    years = max(span_sec / (365.25 * 86400.0), 1e-9)
    bars_per_year = len(rets) / years
    return float((mean_r / std) * math.sqrt(max(bars_per_year, 1.0)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay signals over CSV (deterministic, no OpenAI macro).")
    parser.add_argument("--csv", required=True, help="CSV with timestamp, open, high, low, close, volume")
    parser.add_argument("--max-rows", type=int, default=400, help="Only process the last N rows")
    parser.add_argument("--symbol", default="ETH")
    parser.add_argument("--warmup", type=int, default=120, help="Minimum history bars for technical brain")
    parser.add_argument("--simulate", action="store_true", help="Simulate TP/SL + signal exits and print metrics")
    parser.add_argument(
        "--no-vedic-exits",
        action="store_true",
        help="When simulating, skip long force-exits on Pancha / eclipse-degree (live bot applies these)",
    )
    parser.add_argument("--no-per-bar", action="store_true", help="Suppress per-bar score lines")
    parser.add_argument("--initial-capital", type=float, default=100_000.0, help="Starting equity for --simulate")
    args = parser.parse_args()

    df = load_csv(args.csv).sort_values("timestamp").tail(int(args.max_rows)).reset_index(drop=True)

    if args.simulate:
        metrics = run_simulation(
            df,
            symbol=args.symbol,
            warmup=args.warmup,
            initial_capital=args.initial_capital,
            no_vedic_exits=args.no_vedic_exits,
            quiet=args.no_per_bar,
        )
        print("--- backtest summary ---")
        print(
            f"bars={metrics['bars']} warmup={metrics['warmup']} trades={metrics['trades']} "
            f"win_rate={metrics['win_rate_pct']:.2f}% "
            f"vedic_long_exits={'off' if args.no_vedic_exits else 'on'}"
        )
        print(
            f"initial_capital={metrics['initial_capital']:.2f} final_equity={metrics['final_equity']:.2f} "
            f"total_return_pct={metrics['total_return_pct']:.4f}"
        )
        print(f"max_drawdown_pct={metrics['max_drawdown_pct']:.4f} sharpe_est={metrics['sharpe_est']:.4f}")
        return

    ingest = RawDataIngestion()
    from eclipse_almanac import refresh_eclipse_anchor_if_needed

    last_row = df.iloc[-1]
    ingest.ephemeris.current_date = _row_ts(last_row).to_pydatetime()
    refresh_eclipse_anchor_if_needed(EphemerisEngine._julian_day(ingest.ephemeris.current_date))
    prev_skip = os.environ.get("SKIP_ECLIPSE_ALMANAC_REFRESH")
    os.environ["SKIP_ECLIPSE_ALMANAC_REFRESH"] = "1"

    try:
        warmup = max(22, int(args.warmup))
        for i in range(len(df)):
            row = df.iloc[i]
            rts = _row_ts(row)
            ingest.ephemeris.current_date = rts.to_pydatetime()
            ctx = ingest.build_context_light(args.symbol, slim_feeds=True, refresh_eclipse_anchor=False)
            sub = df.iloc[: i + 1].tail(warmup)
            if len(sub) < 22:
                continue
            ctx["price_history"] = sub
            out = run_probability(ctx)
            score = float(out["score"])
            classification = str(out["classification"])

            if not args.no_per_bar:
                print(f"{rts.isoformat()} score={score:.2f} class={classification}")
    finally:
        if prev_skip is None:
            os.environ.pop("SKIP_ECLIPSE_ALMANAC_REFRESH", None)
        else:
            os.environ["SKIP_ECLIPSE_ALMANAC_REFRESH"] = prev_skip


if __name__ == "__main__":
    main()
