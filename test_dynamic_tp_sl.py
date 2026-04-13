#!/usr/bin/env python3
"""
Smoke test for dynamic TP/SL context wiring.

This repo previously had a different class layout; this script is kept as a lightweight
sanity check that `RawDataIngestion.build_context()` produces bounded TP/SL fields.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from raw_data_engine import RawDataIngestion


def test_dynamic_tp_sl_context() -> bool:
    print("Building context...")
    engine = RawDataIngestion()
    context = engine.build_context(symbol="BRENTUSD")

    tp_sl = context.get("tp_sl_recommendation")
    if not isinstance(tp_sl, dict):
        print("ERROR: tp_sl_recommendation missing or not a dict")
        return False

    tp = tp_sl.get("take_profit_percentage")
    sl = tp_sl.get("stop_loss_percentage")
    print(f"TP/SL recommendation: {tp_sl}")

    ok = True
    if not isinstance(tp, (int, float)) or not (0.1 <= float(tp) <= 5.0):
        print(f"ERROR: take_profit_percentage out of bounds: {tp}")
        ok = False
    if not isinstance(sl, (int, float)) or not (0.1 <= float(sl) <= 2.0):
        print(f"ERROR: stop_loss_percentage out of bounds: {sl}")
        ok = False

    return ok


if __name__ == "__main__":
    success = test_dynamic_tp_sl_context()
    raise SystemExit(0 if success else 1)