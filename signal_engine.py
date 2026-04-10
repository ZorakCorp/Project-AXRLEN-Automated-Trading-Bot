import logging
from dataclasses import dataclass
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
        strength = 0.2
        if direction == "bullish":
            strength = min(1.0, 0.4 + confidence / 10)
        elif direction == "bearish":
            strength = min(1.0, 0.3 + confidence / 10)

        return [
            Signal(name="Macro Bias Direction", domain="astrology", strength=strength, weight=0.35),
            Signal(name="Day Timing Trigger", domain="astrology", strength=0.2 if direction == "neutral" else 0.4, weight=0.35),
        ]


class BrentOilVedhaBrain(BrainBase):
    name = "Brent Oil Vedha"

    def evaluate(self, context: Dict) -> List[Signal]:
        oil_signals = context.get("oil_astro", {})
        strength = 0.2
        if oil_signals.get("mars_in_scorpio_aries"):
            strength += 0.35
        if oil_signals.get("saturn_in_dahana_nadi"):
            strength += 0.25
        if oil_signals.get("jupiter_retro_cancer"):
            strength += 0.15
        return [
            Signal(
                name="Brent Oil Vedha Signal",
                domain="astrology",
                strength=min(1.0, strength),
                weight=0.35,
            )
        ]


class LeaderDashaBrain(BrainBase):
    name = "Leader Dasha"

    def evaluate(self, context: Dict) -> List[Signal]:
        leaders = context.get("leader_dasha_contexts", [])
        signals: List[Signal] = []
        for leader in leaders:
            probability = float(leader.get("probability", 50)) if leader.get("probability") is not None else 50.0
            signal_strength = min(1.0, max(0.0, probability / 100))
            signals.append(
                Signal(
                    name=f"Leader Dasha {leader.get('leader', 'unknown')}",
                    domain="leadership",
                    strength=signal_strength,
                    weight=0.1,
                )
            )
        if not signals:
            signals.append(Signal(name="Leader Dasha Neutral", domain="leadership", strength=0.1, weight=0.1))
        return signals


class TechnicalConfirmationBrain(BrainBase):
    name = "Technical Confirmation"

    @staticmethod
    def _compute_indicators(df: pd.DataFrame) -> Dict[str, float]:
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
        result["trend_strength"] = 0.8 if ema9 > ema21 > ema50 else 0.35

        delta = close.diff().fillna(0.0)
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean().iloc[-1]
        avg_loss = loss.rolling(14).mean().iloc[-1]
        rs = avg_gain / max(avg_loss, 1e-9)
        rsi = 100 - 100 / (1 + rs)
        result["momentum_strength"] = 0.8 if rsi < 30 or rsi > 70 else 0.5

        obv = (pd.Series(np.where(delta > 0, volume, -volume)).cumsum()).iloc[-1] if len(volume) > 0 else 0.0
        result["volume_strength"] = 0.7 if obv > 0 else 0.4
        return result

    def evaluate(self, context: Dict) -> List[Signal]:
        df = context.get("price_history")
        indicators = self._compute_indicators(df) if df is not None else {}
        return [
            Signal(
                name="EMA Trend Confirmation",
                domain="technical",
                strength=indicators.get("trend_strength", 0.2),
                weight=0.15,
            ),
            Signal(
                name="RSI/MACD Momentum",
                domain="technical",
                strength=indicators.get("momentum_strength", 0.2),
                weight=0.15,
            ),
            Signal(
                name="Volume Confirmation",
                domain="technical",
                strength=indicators.get("volume_strength", 0.2),
                weight=0.1,
            ),
        ]


class AIMLBrain(BrainBase):
    name = "AI Model"

    def evaluate(self, context: Dict) -> List[Signal]:
        prediction = context.get("ai_prediction")
        if prediction == "LONG":
            strength = 0.75
        elif prediction == "SHORT":
            strength = 0.25
        else:
            strength = 0.1
        return [
            Signal(name="Machine Learning Signal", domain="ai", strength=strength, weight=0.1),
        ]


class DarkPoolBrain(BrainBase):
    name = "Dark Pool"

    def evaluate(self, context: Dict) -> List[Signal]:
        flow = context.get("dark_pool", {}).get("institutional_flow", [])
        strength = 0.5
        if isinstance(flow, dict):
            net = flow.get("net_long", 0) - flow.get("net_short", 0)
            strength = 0.6 if net > 0 else 0.4
        return [
            Signal(name="Institutional Flow Divergence", domain="dark_pool", strength=strength, weight=0.25),
        ]


class SentimentBrain(BrainBase):
    name = "Sentiment"

    def evaluate(self, context: Dict) -> List[Signal]:
        sentiment = context.get("opec_sentiment", {})
        magnitude = float(sentiment.get("magnitude", 0) or 0)
        direction = sentiment.get("direction", "neutral")
        strength = 0.0
        if direction == "bullish":
            strength = min(1.0, 0.2 + magnitude / 10)
        elif direction == "bearish":
            strength = -min(1.0, 0.2 + magnitude / 10)
        return [
            Signal(name="Oil Fear/Greed Sentiment", domain="sentiment", strength=strength, weight=0.1),
        ]


class HistoricalCrashBrain(BrainBase):
    name = "Historical Crash"

    def evaluate(self, context: Dict) -> List[Signal]:
        signal_strength = 0.1
        if context.get("flash_scout", {}).get("relevant_items"):
            signal_strength = 0.35
        return [
            Signal(name="Historical Crash Pattern Match", domain="historical", strength=signal_strength, weight=0.1),
        ]


class ProbabilityEngine:
    def __init__(self):
        self.domain_weights = {
            "astrology": 0.35,
            "technical": 0.0,  # Disabled - focus on astrology and fundamentals
            "dark_pool": 0.25,
            "ai": 0.1,
            "sentiment": 0.1,
            "historical": 0.1,
            "leadership": 0.1,
        }

    @staticmethod
    def temporal_multiplier(signal: Signal) -> float:
        if "Mars-Saturn Vedha" in signal.name or "Samasaptaka" in signal.name:
            return 100.0
        if "Retrograde" in signal.name and "Jupiter" in signal.name:
            return 50.0
        if "Eclipse" in signal.name or "Oil region" in signal.name:
            return 100.0
        if "Dasha" in signal.name:
            return 10.0
        return signal.multiplier

    def aggregate(self, signals: List[Signal]) -> float:
        total_score = 0.0
        for signal in signals:
            weight = self.domain_weights.get(signal.domain, 0.0)
            multiplier = self.temporal_multiplier(signal)
            total_score += signal.strength * weight * multiplier
        max_score = 100.0 * len(signals)
        normalized = total_score / max_score * 100 if max_score > 0 else 0.0
        return min(normalized, 100.0)

    @staticmethod
    def classify(confidence_score: float, vedha_bias: str = None) -> str:
        adjusted = confidence_score
        if vedha_bias == "bullish":
            adjusted += 10  # Increased bonus for bullish vedha
        elif vedha_bias == "bearish":
            adjusted -= 10
        if adjusted >= 60:  # Lowered threshold for LONG
            return "LONG"
        if adjusted <= 40:  # Raised threshold for SHORT
            return "SHORT"
        return "FLAT"


class RiskEngine:
    def __init__(self, capital: float = 100000.0):
        self.capital = capital
        self.max_risk_pct = 0.02

    def position_size(self, confidence_score: float, stop_distance: float, price: float) -> float:
        if stop_distance <= 0 or price <= 0:
            return 0.0
        kelly_pct = min(self.max_risk_pct, confidence_score / 100 * 0.02)
        risk_amount = self.capital * kelly_pct
        return round(risk_amount, 2)

    def update_capital(self, pnl: float):
        self.capital += pnl
        logger.info("Updated capital to %s after PnL %s", self.capital, pnl)


def build_signals(context: Dict) -> List[Signal]:
    brains = [
        AstroTimingBrain(),
        BrentOilVedhaBrain(),
        LeaderDashaBrain(),
        # TechnicalConfirmationBrain(),  # Removed as per user request
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
    vedha_bias = context.get("macro_bias", {}).get("direction")
    score = engine.aggregate(signals)
    classification = engine.classify(score, vedha_bias=vedha_bias)
    return {
        "score": score,
        "classification": classification,
        "signals": signals,
    }
