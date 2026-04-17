"""
Deterministic macro bias from structured Vedic/crypto flags (no LLM).
Used as the primary ``macro_bias`` for scoring unless USE_LLM_MACRO_BIAS is enabled.
"""

from typing import Any, Dict, List


def compute_deterministic_macro_bias(
    *,
    crypto_astro: Dict[str, Any],
    vedha: Dict[str, Any],
    vedic_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    score = 0.0
    reasons: List[str] = []

    if crypto_astro.get("jupiter_air_bull_window"):
        score += 0.45
        reasons.append("Jupiter in air (bull window)")
    if crypto_astro.get("saturn_earth_cardinal_winter"):
        score -= 0.40
        reasons.append("Saturn earth/cardinal (winter)")
    if crypto_astro.get("rahu_taurus_scorpio_exchange_axis"):
        score -= 0.28
        reasons.append("Rahu Taurus/Scorpio axis stress")
    if vedha.get("mars_saturn_vedha"):
        score -= 0.18
        reasons.append("Mars–Saturn vedha")
    if vedic_snapshot.get("mars_saturn_samasaptaka_approx"):
        score -= 0.22
        reasons.append("Mars–Saturn samasaptaka (opposition)")
    if vedic_snapshot.get("saturn_latta"):
        score -= 0.15
        reasons.append("Saturn Latta")
    if vedic_snapshot.get("mars_latta"):
        reasons.append("Mars Latta (volatility; neutral on bias)")

    if score > 0.18:
        direction = "bullish"
        confidence = min(10.0, 4.0 + score * 8.0)
    elif score < -0.18:
        direction = "bearish"
        confidence = min(10.0, 4.0 + abs(score) * 8.0)
    else:
        direction = "neutral"
        confidence = max(1.0, 3.0 * (1.0 - abs(score) / 0.18))

    stmt = "; ".join(reasons) if reasons else "Sidereal regime neutral / mixed."
    return {
        "statement": stmt,
        "direction": direction,
        "confidence": round(float(confidence), 2),
        "_source": "deterministic",
    }
