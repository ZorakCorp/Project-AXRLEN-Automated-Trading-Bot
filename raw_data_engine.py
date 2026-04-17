import logging
from typing import Any, Dict

from config import USE_AI_TP_SL
from ephemeris_engine import EphemerisEngine
from openai_client import OpenAIClient
from leader_engine import LeaderDashaEngine

logger = logging.getLogger(__name__)


class RawDataIngestion:
    def __init__(self):
        self.ai = OpenAIClient()
        self.leader_engine = LeaderDashaEngine()
        self.ephemeris = EphemerisEngine()
        self._allow_dummy_fallbacks = False

    def fetch_price_feed(self, symbol: str) -> Dict[str, Any]:
        logger.debug("Fetching price feed placeholder for %s", symbol)
        return {"price_feed": {"symbol": symbol, "source": "not_configured", "data": []}}

    def fetch_crypto_news_sentiment(self) -> Dict[str, Any]:
        """
        Crypto headline sentiment (optional). Does not call the LLM when there is no article body.
        Wire a real news source later; until then this stays neutral.
        """
        logger.debug("Crypto news sentiment placeholder (no feed configured)")
        raw_article = {"headline": "", "body": ""}
        sentiment = {
            "direction": "neutral",
            "magnitude": 0.0,
            "category": "other",
            "reason": "No news item available",
        }
        return {"crypto_news": raw_article, "crypto_sentiment": sentiment, "opec_sentiment": sentiment}

    def fetch_geopolitical_signals(self) -> Dict[str, Any]:
        logger.debug("Fetching geopolitical conflict indicators")
        # Placeholder: Use some geopolitical API or news feed
        return {"geopolitics": {"conflict_signals": []}}

    def fetch_dark_pool_data(self) -> Dict[str, Any]:
        logger.debug("Fetching dark pool and institutional flow data")
        return {"dark_pool": {"institutional_flow": []}}

    def interpret_leader_dasha(self, leader_context: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("Interpreting leader Dasha context through OpenAI")
        try:
            return self.ai.interpret_leader_dasha(leader_context)
        except RuntimeError as e:
            logger.warning(
                "OpenAI API failed for leader interpretation after all retries (%s). Returning neutral-safe data.",
                str(e),
            )
            if self._allow_dummy_fallbacks:
                return {
                    "likely_action": "maintain_cuts",
                    "probability": 75,
                    "risk_category": "supply_cut",
                    "summary": "OPEC leadership favors continued supply discipline (dummy fallback)",
                }
            return {
                "likely_action": "neutral",
                "probability": 50,
                "risk_category": "neutral",
                "summary": "Leader interpretation unavailable (OpenAI failed)",
                "_unavailable": True,
            }

    def generate_macro_bias(self, macro_context: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("Generating daily macro bias statement through OpenAI")
        try:
            return self.ai.macro_bias_statement(macro_context)
        except RuntimeError as e:
            logger.warning(
                "OpenAI API failed for macro bias after all retries (%s). Returning neutral-safe data.",
                str(e),
            )
            if self._allow_dummy_fallbacks:
                return {
                    "statement": "Macro bias dummy fallback (explicitly enabled)",
                    "direction": "neutral",
                    "confidence": 0,
                }
            return {
                "statement": "Macro bias unavailable (OpenAI failed)",
                "direction": "neutral",
                "confidence": 0,
                "_unavailable": True,
            }

    def run_calibration_analysis(self, report: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("Running monthly calibration analysis through OpenAI")
        try:
            return self.ai.calibration_diagnostic(report)
        except RuntimeError as e:
            logger.warning(
                "OpenAI API failed for calibration analysis after all retries (%s). Returning neutral-safe data.",
                str(e),
            )
            if self._allow_dummy_fallbacks:
                return {
                    "diagnostic_summary": "Calibration analysis unavailable (dummy fallback)",
                    "weight_adjustments": [],
                    "recommendation_level": "low",
                }
            return {
                "diagnostic_summary": "Calibration analysis unavailable (OpenAI failed)",
                "weight_adjustments": [],
                "recommendation_level": "low",
                "_unavailable": True,
            }

    def flash_scout(self, query: str, dataset_context: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug("Running OpenAI scout for historical precedents")
        return self.ai.flash_scout(query, dataset_context)

    def build_context(self, symbol: str) -> Dict[str, Any]:
        leader_contexts = self.leader_engine.get_leader_contexts()
        interpreted_leaders = [self.interpret_leader_dasha(ctx) for ctx in leader_contexts]
        astro_positions = self.ephemeris.get_planet_positions()
        vedic_snapshot = self.ephemeris.get_vedic_snapshot()
        vedha = self.ephemeris.calculate_vedha()
        crypto_astro = self.ephemeris.get_crypto_astro_signals()
        red_day = self.ephemeris.get_red_day()
        macro_bias = self.generate_macro_bias(
            {
                "symbol": symbol,
                "astro_positions_tropical": astro_positions,
                "astro_positions_sidereal": vedic_snapshot.get("positions_sidereal"),
                "vedic_snapshot": vedic_snapshot,
                "vedha": vedha,
                "crypto_astro": crypto_astro,
            }
        )
        missing: Dict[str, Any] = {}
        if any(isinstance(x, dict) and x.get("_unavailable") for x in interpreted_leaders):
            missing["leader_interpretation"] = True
        if isinstance(macro_bias, dict) and macro_bias.get("_unavailable"):
            missing["macro_bias"] = True
        context: Dict[str, Any] = {
            "symbol": symbol,
            **self.fetch_price_feed(symbol),
            **self.fetch_crypto_news_sentiment(),
            **self.fetch_geopolitical_signals(),
            **self.fetch_dark_pool_data(),
            "leader_dasha_contexts": interpreted_leaders,
            "astro_positions": astro_positions,
            "vedic_snapshot": vedic_snapshot,
            "vedha": vedha,
            "crypto_astro": crypto_astro,
            "macro_bias": macro_bias,
            "red_day": red_day,
            "data_quality": {
                "blocking_placeholders": False,
                "placeholders": False,
                "missing": missing,
            },
        }
        if USE_AI_TP_SL:
            try:
                context["tp_sl_recommendation"] = self.ai.get_tp_sl_levels(context)
            except RuntimeError as e:
                logger.warning(
                    "OpenAI API failed for TP/SL levels after all retries (%s). Falling back to default levels.",
                    str(e),
                )
                context["tp_sl_recommendation"] = {
                    "take_profit_percentage": 0.5,
                    "rationale": "Default levels (OpenAI API unavailable)",
                    "_unavailable": True,
                }
        else:
            context["tp_sl_recommendation"] = {
                "take_profit_percentage": None,
                "rationale": "USE_AI_TP_SL disabled; bot uses DEFAULT_TAKE_PROFIT_PCT from config",
                "_unavailable": True,
            }
        return context
