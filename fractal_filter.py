import math
from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class FractalFilterResult:
    fidelity: float
    confidence: float
    aligned: bool
    trend_micro: int
    trend_meso: int
    trend_macro: int
    allow_long: bool
    allow_short: bool


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _calc_fractal_fidelity(closes: pd.Series, lb: int) -> float:
    """
    Port of Pine calcFractalFidelity(lb).
    Computes correlation between micro closes and a downsampled macro close (every 5 bars),
    expressed as a percentage [-100, 100].
    """
    if closes is None or len(closes) < (lb * 5 + 2):
        return 0.0

    # micro: close[i] for i in [0..lb-1] (most recent backwards)
    micro = [_safe_float(closes.iloc[-1 - i]) for i in range(lb)]
    macro = [_safe_float(closes.iloc[-1 - (i * 5)]) for i in range(lb)]

    mean_micro = sum(micro) / lb
    mean_macro = sum(macro) / lb

    numer = 0.0
    denom_micro = 0.0
    denom_macro = 0.0
    for i in range(lb):
        diff_micro = micro[i] - mean_micro
        diff_macro = macro[i] - mean_macro
        numer += diff_micro * diff_macro
        denom_micro += diff_micro * diff_micro
        denom_macro += diff_macro * diff_macro

    if denom_micro <= 0 or denom_macro <= 0:
        return 0.0

    corr = numer / math.sqrt(denom_micro * denom_macro)
    return float(corr * 100.0)


def _resample_last_close(df: pd.DataFrame, rule: str) -> Optional[pd.Series]:
    if df is None or len(df) == 0 or "close" not in df.columns:
        return None
    if "timestamp" in df.columns:
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        s = pd.Series(df["close"].astype(float).to_numpy(), index=idx)
    else:
        # Best-effort: treat index as already datetime-like
        s = pd.Series(df["close"].astype(float).to_numpy(), index=df.index)
    return s.resample(rule).last().dropna()


def compute_fractal_filter(
    df_1m: pd.DataFrame,
    *,
    fractal_lookback: int = 30,
    min_fidelity: float = 70.0,
    min_confidence: float = 65.0,
) -> FractalFilterResult:
    """
    Computes the same alignment/confidence concepts as the TradingView script, and returns
    allow_long/allow_short gates.
    """
    closes = df_1m["close"].astype(float) if df_1m is not None and "close" in df_1m.columns else pd.Series([], dtype=float)

    fidelity = _calc_fractal_fidelity(closes, int(fractal_lookback))

    # Trend alignment
    trend_micro = 1 if len(closes) > 10 and _safe_float(closes.iloc[-1]) > _safe_float(closes.iloc[-11]) else -1

    htf15 = _resample_last_close(df_1m, "15min")
    htf60 = _resample_last_close(df_1m, "60min")

    trend_meso = 1
    if htf15 is not None and len(htf15) > 5:
        trend_meso = 1 if _safe_float(htf15.iloc[-1]) > _safe_float(htf15.iloc[-6]) else -1
    trend_macro = 1
    if htf60 is not None and len(htf60) > 3:
        trend_macro = 1 if _safe_float(htf60.iloc[-1]) > _safe_float(htf60.iloc[-4]) else -1

    aligned = (trend_micro == trend_meso) and (trend_meso == trend_macro)

    base_confidence = fidelity * 0.4 + (40.0 if aligned else 0.0) + 20.0
    confidence = float(base_confidence)

    allow_long = bool(confidence > float(min_confidence) and trend_micro == 1 and fidelity > float(min_fidelity) and aligned)
    allow_short = bool(confidence > float(min_confidence) and trend_micro == -1 and fidelity > float(min_fidelity) and aligned)

    return FractalFilterResult(
        fidelity=float(fidelity),
        confidence=float(confidence),
        aligned=bool(aligned),
        trend_micro=int(trend_micro),
        trend_meso=int(trend_meso),
        trend_macro=int(trend_macro),
        allow_long=allow_long,
        allow_short=allow_short,
    )

