#!/usr/bin/env python3
"""
Smoke test: ephemeris Vedic snapshot + optional full RawDataIngestion when OPENAI_API_KEY is set.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_swiss_reference_april_2026() -> bool:
    """Regression: Swiss sidereal signs for a fixed instant (Drik / Lahiri cross-check)."""
    try:
        import swisseph as swe  # noqa: F401
    except ImportError:
        print("SKIP: pyswisseph not installed — reference test skipped")
        return True

    from ephemeris_engine import EphemerisEngine

    e = EphemerisEngine()
    if not e._swiss_available:
        print("SKIP: Swiss ephemeris disabled — reference test skipped")
        return True

    e.current_date = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)
    sid = e.get_sidereal_positions()
    checks = (
        ("Jupiter", "Gemini"),
        ("Mars", "Pisces"),
        ("Saturn", "Pisces"),
        ("Rahu", "Aquarius"),
        ("Sun", "Aries"),
        ("Moon", "Aries"),
        ("Mercury", "Pisces"),
        ("Venus", "Aries"),
    )
    for planet, expect_sign in checks:
        got = (sid.get(planet) or {}).get("sign")
        if got != expect_sign:
            print(f"ERROR: {planet} sign {got!r} != {expect_sign!r} (full row={sid.get(planet)})")
            return False
    print("Swiss reference OK (2026-04-17 12:00 UTC sidereal signs)")
    return True


def test_ephemeris_vedic() -> bool:
    from ephemeris_engine import EphemerisEngine

    e = EphemerisEngine()
    vs = e.get_vedic_snapshot()
    if not isinstance(vs, dict) or "moon_nakshatra" not in vs:
        print("ERROR: vedic_snapshot malformed")
        return False
    ca = e.get_crypto_astro_signals()
    if not isinstance(ca, dict) or "jupiter_air_bull_window" not in ca:
        print("ERROR: crypto_astro malformed")
        return False
    print(f"Vedic: nakshatra={vs.get('moon_nakshatra')} tithi={vs.get('tithi')} hora={vs.get('hora_lord')} latta={vs.get('latta_active')}")
    return True


def test_build_context_if_openai() -> bool:
    if not os.getenv("OPENAI_API_KEY"):
        print("SKIP: OPENAI_API_KEY unset — skipping RawDataIngestion.build_context()")
        return True

    from raw_data_engine import RawDataIngestion

    engine = RawDataIngestion()
    context = engine.build_context(symbol="ETH")
    vs = context.get("vedic_snapshot")
    if not isinstance(vs, dict):
        print("ERROR: context missing vedic_snapshot")
        return False
    tp_sl = context.get("tp_sl_recommendation")
    if not isinstance(tp_sl, dict):
        print("ERROR: tp_sl_recommendation missing")
        return False
    dq = context.get("data_quality", {})
    if dq.get("blocking_placeholders") or dq.get("placeholders"):
        print("ERROR: expected non-blocking data_quality")
        return False
    use_ai = os.getenv("USE_AI_TP_SL", "false").lower() in {"1", "true", "yes", "y", "on"}
    if use_ai:
        tp = tp_sl.get("take_profit_percentage")
        if not isinstance(tp, (int, float)) or not (0.1 <= float(tp) <= 5.0):
            print(f"ERROR: take_profit_percentage out of bounds: {tp}")
            return False
    elif not tp_sl.get("_unavailable"):
        print("ERROR: expected _unavailable when USE_AI_TP_SL is false")
        return False
    print(f"build_context OK | TP object keys={list(tp_sl.keys())}")
    return True


if __name__ == "__main__":
    ok = test_swiss_reference_april_2026() and test_ephemeris_vedic() and test_build_context_if_openai()
    raise SystemExit(0 if ok else 1)
