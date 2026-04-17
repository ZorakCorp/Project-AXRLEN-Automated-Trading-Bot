import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    name: str
    domain: str
    strength: float
    weight: float = 1.0
    multiplier: float = 1.0
    tags: frozenset = field(default_factory=frozenset)

    @property
    def score(self) -> float:
        return self.strength * self.weight * self.multiplier


class BrainBase:
    name: str

    def evaluate(self, context: Dict) -> List[Signal]:
        raise NotImplementedError


class AstroTimingBrain(BrainBase):
    name = "Astro Timing"

    def evaluate(self, context: Dict) -> List[Signal]:
        bias = context.get("macro_bias", {})
        direction = bias.get("direction", "neutral")
        confidence = float(bias.get("confidence", 0) or 0)
        scale = min(1.0, 0.25 + confidence / 12.0)
        if direction == "bullish":
            strength = scale
        elif direction == "bearish":
            strength = -scale
        else:
            strength = 0.0

        return [
            Signal(name="Macro Bias Direction", domain="astrology", strength=float(strength), weight=0.22),
        ]


class CryptoVedicBrain(BrainBase):
    """Sidereal regime + vedha + Latta-style timing for ETH (replaces Brent/oil heuristics)."""

    name = "Crypto Vedic Regime"

    def evaluate(self, context: Dict) -> List[Signal]:
        c = context.get("crypto_astro") or {}
        snap = context.get("vedic_snapshot") or {}
        vedha = context.get("vedha") or {}
        signals: List[Signal] = []

        if vedha.get("mars_saturn_vedha"):
            signals.append(
                Signal(
                    name="Mars-Saturn Vedha (sidereal heuristic)",
                    domain="astrology",
                    strength=0.42,
                    weight=0.18,
                    tags=frozenset({"mars_saturn_vedha"}),
                )
            )

        if c.get("jupiter_air_bull_window"):
            signals.append(
                Signal(
                    name="Jupiter in air sign (crypto bull window)",
                    domain="astrology",
                    strength=0.48,
                    weight=0.16,
                    tags=frozenset({"jupiter_air"}),
                )
            )

        if c.get("saturn_earth_cardinal_winter"):
            signals.append(
                Signal(
                    name="Saturn earth/cardinal (risk-off / winter regime)",
                    domain="astrology",
                    strength=-0.42,
                    weight=0.16,
                    tags=frozenset({"saturn_winter"}),
                )
            )

        if c.get("rahu_taurus_scorpio_exchange_axis"):
            signals.append(
                Signal(
                    name="Rahu on Taurus/Scorpio axis (stress window)",
                    domain="astrology",
                    strength=-0.35,
                    weight=0.12,
                    tags=frozenset({"eclipse_axis"}),
                )
            )

        # Latta: Mars = volatility / decisive bar (non-directional in aggregate); Saturn = crushing pressure (bearish).
        if snap.get("mars_latta"):
            signals.append(
                Signal(
                    name="Mars Latta (Moon on Mars +3 nakshatra target; volatility)",
                    domain="astrology",
                    strength=0.0,
                    weight=0.0,
                    tags=frozenset({"latta_mars", "latta_volatility"}),
                )
            )
        if snap.get("saturn_latta"):
            signals.append(
                Signal(
                    name="Saturn Latta (Moon on Saturn +8 nakshatra target; pressure)",
                    domain="astrology",
                    strength=-0.38,
                    weight=0.14,
                    tags=frozenset({"latta_saturn", "latta_kick"}),
                )
            )

        if snap.get("mars_saturn_samasaptaka_approx"):
            signals.append(
                Signal(
                    name="Mars-Saturn Samasaptaka (180° proximity)",
                    domain="astrology",
                    strength=-0.25,
                    weight=0.10,
                    tags=frozenset({"samasaptaka"}),
                )
            )

        if context.get("eclipse_degree_trigger_active"):
            signals.append(
                Signal(
                    name="Mars/Saturn on charged solar-eclipse degree",
                    domain="astrology",
                    strength=-0.45,
                    weight=0.12,
                    tags=frozenset({"eclipse_degree_transit"}),
                )
            )

        if not signals:
            signals.append(Signal(name="Crypto Vedic neutral", domain="astrology", strength=0.0, weight=0.08))
        return signals


class LeaderDashaBrain(BrainBase):
    name = "Leader Dasha"

    def evaluate(self, context: Dict) -> List[Signal]:
        leaders = context.get("leader_dasha_contexts", [])
        signals: List[Signal] = []
        for leader in leaders:
            probability = float(leader.get("probability", 50)) if leader.get("probability") is not None else 50.0
            signal_strength = max(-1.0, min(1.0, (probability - 50.0) / 50.0))
            signals.append(
                Signal(
                    name=f"Leader Dasha {leader.get('leader', 'unknown')}",
                    domain="leadership",
                    strength=signal_strength,
                    weight=0.06,
                    tags=frozenset({"dasha"}),
                )
            )
        if not signals:
            signals.append(Signal(name="Leader Dasha Neutral", domain="leadership", strength=0.0, weight=0.04))
        return signals


class TechnicalConfirmationBrain(BrainBase):
    name = "Technical Confirmation"

    @staticmethod
    def _compute_indicators(df: pd.DataFrame) -> Dict[str, float]:
        # Signed strengths in [-1, 1] where positive favors LONG, negative favors SHORT.
        result = {"trend_strength": 0.0, "momentum_strength": 0.0, "volume_strength": 0.0}
        if len(df) < 21 or {"close", "high", "low", "volume"} - set(df.columns):
            return result

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        if ema9 > ema21 > ema50:
            result["trend_strength"] = 0.8
        elif ema9 < ema21 < ema50:
            result["trend_strength"] = -0.8
        else:
            result["trend_strength"] = 0.0

        delta = close.diff().fillna(0.0)
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean().iloc[-1]
        avg_loss = loss.rolling(14).mean().iloc[-1]
        rs = avg_gain / max(avg_loss, 1e-9)
        rsi = 100 - 100 / (1 + rs)
        # RSI > 70 is overbought (lean SHORT), RSI < 30 is oversold (lean LONG).
        if rsi < 30:
            result["momentum_strength"] = 0.6
        elif rsi > 70:
            result["momentum_strength"] = -0.6
        else:
            result["momentum_strength"] = 0.0

        obv = (pd.Series(np.where(delta > 0, volume, -volume)).cumsum()).iloc[-1] if len(volume) > 0 else 0.0
        result["volume_strength"] = 0.4 if obv > 0 else (-0.4 if obv < 0 else 0.0)
        return result

    def evaluate(self, context: Dict) -> List[Signal]:
        df = context.get("price_history")
        indicators = self._compute_indicators(df) if df is not None else {}
        return [
            Signal(
                name="EMA Trend Confirmation",
                domain="technical",
                strength=float(indicators.get("trend_strength", 0.0) or 0.0),
                weight=0.30,
            ),
            Signal(
                name="RSI/MACD Momentum",
                domain="technical",
                strength=float(indicators.get("momentum_strength", 0.0) or 0.0),
                weight=0.25,
            ),
            Signal(
                name="Volume Confirmation",
                domain="technical",
                strength=float(indicators.get("volume_strength", 0.0) or 0.0),
                weight=0.15,
            ),
        ]


class AIMLBrain(BrainBase):
    name = "AI Model"

    def evaluate(self, context: Dict) -> List[Signal]:
        prediction = context.get("ai_prediction")
        if prediction == "LONG":
            strength = 0.55
        elif prediction == "SHORT":
            strength = -0.55
        else:
            strength = 0.0
        return [
            Signal(name="Machine Learning Signal", domain="ai", strength=strength, weight=0.08),
        ]


class DarkPoolBrain(BrainBase):
    name = "Dark Pool"

    def evaluate(self, context: Dict) -> List[Signal]:
        flow = context.get("dark_pool", {}).get("institutional_flow", [])
        if not flow:
            return [Signal(name="Institutional Flow (n/a)", domain="dark_pool", strength=0.0, weight=0.08)]
        strength = 0.0
        if isinstance(flow, dict):
            net = flow.get("net_long", 0) - flow.get("net_short", 0)
            strength = 0.5 if net > 0 else (-0.5 if net < 0 else 0.0)
        return [
            Signal(name="Institutional Flow Divergence", domain="dark_pool", strength=strength, weight=0.12),
        ]


class SentimentBrain(BrainBase):
    name = "Sentiment"

    def evaluate(self, context: Dict) -> List[Signal]:
        sentiment = context.get("crypto_sentiment") or context.get("opec_sentiment") or {}
        magnitude = float(sentiment.get("magnitude", 0) or 0)
        direction = sentiment.get("direction", "neutral")
        strength = 0.0
        if direction == "bullish":
            strength = min(1.0, 0.2 + magnitude / 10)
        elif direction == "bearish":
            strength = -min(1.0, 0.2 + magnitude / 10)
        return [
            Signal(name="Crypto headline sentiment", domain="sentiment", strength=strength, weight=0.08),
        ]


class HistoricalCrashBrain(BrainBase):
    name = "Historical Crash"

    def evaluate(self, context: Dict) -> List[Signal]:
        signal_strength = 0.0
        if context.get("flash_scout", {}).get("relevant_items"):
            signal_strength = 0.25
        return [
            Signal(name="Historical Crash Pattern Match", domain="historical", strength=signal_strength, weight=0.06),
        ]


class ProbabilityEngine:
    def __init__(self):
        self.domain_weights = {
            "astrology": 0.38,
            "technical": 0.22,
            "dark_pool": 0.10,
            "ai": 0.08,
            "sentiment": 0.08,
            "historical": 0.06,
            "leadership": 0.06,
        }

    @staticmethod
    def temporal_multiplier(signal: Signal) -> float:
        tags = getattr(signal, "tags", None) or frozenset()
        if "mars_saturn_vedha" in tags:
            return 100.0
        if "samasaptaka" in tags:
            return 80.0
        if "latta_saturn" in tags:
            return 55.0
        if "latta_mars" in tags:
            return 40.0
        if "latta_kick" in tags:
            return 50.0
        if "eclipse_axis" in tags:
            return 80.0
        if "eclipse_degree_transit" in tags:
            return 70.0
        if "jupiter_air" in tags:
            return 30.0
        if "Retrograde" in signal.name and "Jupiter" in signal.name:
            return 40.0
        if "Dasha" in signal.name:
            return 10.0
        return signal.multiplier

    def aggregate(self, signals: List[Signal]) -> float:
        """
        Aggregate signals into a 0..100 score where 50 is neutral.

        - Each signal contributes: strength * signal.weight * temporal_multiplier * domain_weight
        - strength may be negative (bearish), so we map the signed score onto 0..100.
        """
        if not signals:
            return 50.0

        total = 0.0
        max_abs = 0.0
        for signal in signals:
            domain_w = float(self.domain_weights.get(signal.domain, 0.0) or 0.0)
            mult = float(self.temporal_multiplier(signal) or 1.0)
            contrib = float(signal.strength) * float(signal.weight) * float(mult) * domain_w
            total += contrib
            max_abs += abs(float(signal.weight) * float(mult) * domain_w)

        if max_abs <= 0:
            return 50.0

        signed = max(-1.0, min(1.0, total / max_abs))  # -1..1
        score = (signed + 1.0) / 2.0 * 100.0  # 0..100 with 50 neutral
        return max(0.0, min(100.0, score))

    @staticmethod
    def classify(confidence_score: float) -> str:
        """Symmetric bands around 50 (no macro bonus; vedha already in astro signals)."""
        if confidence_score >= 56:
            return "LONG"
        if confidence_score <= 44:
            return "SHORT"
        return "FLAT"


class RiskEngine:
    def __init__(self, capital: float = 100000.0):
        self.capital = capital
        self.max_risk_pct = 0.02

    def position_size(self, confidence_score: float, stop_distance: float, price: float, leverage: int = 1) -> float:
        if stop_distance <= 0 or price <= 0:
            return 0.0
        kelly_pct = min(self.max_risk_pct, confidence_score / 100 * 0.02)
        risk_amount = self.capital * kelly_pct
        # Convert risk budget into a notional size (USD) using stop distance.
        # units = risk_amount / stop_distance; notional = units * price
        units = risk_amount / stop_distance
        notional = units * price
        if os.getenv("RISK_ADJUST_NOTIONAL_FOR_LEVERAGE", "true").strip().lower() in {"1", "true", "yes", "y", "on"}:
            lev = max(1, int(leverage))
            notional = notional / float(lev)
        return round(max(notional, 0.0), 2)

    def update_capital(self, pnl: float):
        self.capital += pnl
        logger.info("Updated capital to %s after PnL %s", self.capital, pnl)


def build_signals(context: Dict) -> List[Signal]:
    brains = [
        AstroTimingBrain(),
        CryptoVedicBrain(),
        LeaderDashaBrain(),
        TechnicalConfirmationBrain(),
        AIMLBrain(),
        DarkPoolBrain(),
        SentimentBrain(),
        HistoricalCrashBrain(),
    ]
    signals: List[Signal] = []
    for brain in brains:
        signals.extend(brain.evaluate(context))
    return signals


def run_probability(context: Dict) -> Dict:
    signals = build_signals(context)
    engine = ProbabilityEngine()
    score = engine.aggregate(signals)
    classification = engine.classify(score)
    return {
        "score": score,
        "classification": classification,
        "signals": signals,
    }
