import json
import logging
import re
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import GEMINI_API_BASE, GEMINI_API_KEY, GEMINI_API_MODEL

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.base_url = base_url or GEMINI_API_BASE
        self.model = model or GEMINI_API_MODEL
        self._session = self._build_session()
        self._ensure_api_key()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        return session

    def _ensure_api_key(self):
        if not self.api_key:
            raise RuntimeError("Please set GEMINI_API_KEY in your environment.")

    def _parse_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return text

    def _extract_text(self, data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            return ""
        candidates = data.get("candidates") or []
        if candidates and isinstance(candidates, list):
            first = candidates[0]
            content = first.get("content")
            if isinstance(content, dict):
                parts = content.get("parts", [])
                if parts and isinstance(parts, list):
                    part = parts[0]
                    if isinstance(part, dict):
                        return part.get("text", "")
        return ""

    def call(self, system_prompt: str, user_message: str, model: Optional[str] = None, timeout: int = 30) -> Any:
        model_name = model or self.model
        # Some Gemini API responses include fully-qualified model names like "models/xyz".
        # Normalize to avoid "models/models/..." mistakes.
        model_name = model_name.replace("models/", "")
        endpoint = f"{self.base_url}/models/{model_name}:generateContent?key={self.api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"{system_prompt}\n\n{user_message}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 1024
            }
        }
        response = self._session.post(endpoint, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout)
        if response.status_code == 404 and model_name != "gemini-flash-latest":
            # Model names change over time. Retry once with a stable alias.
            fallback = "gemini-flash-latest"
            endpoint = f"{self.base_url}/models/{fallback}:generateContent?key={self.api_key}"
            response = self._session.post(endpoint, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout)

        if response.status_code >= 400:
            # Don't leak request details; return concise error context.
            raise RuntimeError(f"Gemini API request failed (status={response.status_code}): {response.text[:500]}")
        data = response.json()
        text = self._extract_text(data)
        if text:
            return self._parse_json(text)
        return self._parse_json(json.dumps(data))

    def classify_news_sentiment(self, text: str) -> Dict[str, Any]:
        system_prompt = (
            "You are a structured signal extractor for oil trading. "
            "Return only JSON with no markdown or explanation. "
            "The fields must be: direction (bullish, bearish, neutral), magnitude (1-10), "
            "category (supply disruption, demand change, geopolitical friction, sanctions, weather event, other), "
            "one_sentence_reason."
        )
        user_message = f"Classify this news item for Brent oil: {text}"
        result = self.call(system_prompt, user_message)
        return {
            "direction": result.get("direction", "neutral"),
            "magnitude": float(result.get("magnitude", 0)) if result.get("magnitude") is not None else 0.0,
            "category": result.get("category", "other"),
            "reason": result.get("one_sentence_reason", ""),
        }

    def interpret_leader_dasha(self, leader_context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a geopolitical analyst for oil trading. "
            "Return only JSON with no markdown or explanation. "
            "The output fields must be: likely_action, probability (0-100), "
            "risk_category (supply_cut, military_posturing, policy_stability, neutral), one_sentence_summary."
        )
        user_message = f"Leader Dasha context: {json.dumps(leader_context)}"
        result = self.call(system_prompt, user_message)
        return {
            "likely_action": result.get("likely_action", "neutral"),
            "probability": float(result.get("probability", 0)) if result.get("probability") is not None else 0.0,
            "risk_category": result.get("risk_category", "neutral"),
            "summary": result.get("one_sentence_summary", ""),
        }

    def macro_bias_statement(self, macro_context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a macro bias synthesizer for Brent oil. "
            "Return only JSON with no markdown or explanation. "
            "The output fields must be: statement, direction (bullish, bearish, neutral), "
            "confidence (1-10)."
        )
        user_message = f"Macro context: {json.dumps(macro_context)}"
        result = self.call(system_prompt, user_message)
        return {
            "statement": result.get("statement", ""),
            "direction": result.get("direction", "neutral"),
            "confidence": float(result.get("confidence", 0)) if result.get("confidence") is not None else 0.0,
        }

    def calibration_diagnostic(self, report: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a calibration analyst for a Vedic oil trading system. "
            "Return only JSON with no markdown or explanation. "
            "The output fields must be: diagnostic_summary, "
            "weight_adjustments (list of {domain, adjustment, reason}), "
            "recommendation_level (low, medium, high)."
        )
        user_message = f"Calibration report: {json.dumps(report)}"
        result = self.call(system_prompt, user_message)
        return {
            "diagnostic_summary": result.get("diagnostic_summary", ""),
            "weight_adjustments": result.get("weight_adjustments", []),
            "recommendation_level": result.get("recommendation_level", "low"),
        }

    def flash_scout(self, query: str, dataset_context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a fast scout model that filters historical records for relevance. "
            "Return only JSON with no markdown or explanation. "
            "The output fields must be: relevant_items (list of ids or short summaries)."
        )
        user_message = f"Query: {query}. Dataset: {json.dumps(dataset_context)}"
        return self.call(system_prompt, user_message)

    def get_tp_sl_levels(self, context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a professional trading risk manager. "
            "Return only JSON with no markdown or explanation. "
            "Based on market context, determine optimal take profit and stop loss percentages. "
            "The fields must be: take_profit_percentage (0.1-5.0), stop_loss_percentage (0.1-2.0), "
            "rationale (one sentence)."
        )
        user_message = f"Market context: {json.dumps(context)}"
        result = self.call(system_prompt, user_message)
        def _safe_float(value: Any, default: float) -> float:
            try:
                if value is None:
                    return float(default)
                return float(value)
            except Exception:
                return float(default)

        tp = _safe_float(result.get("take_profit_percentage", 0.5) if isinstance(result, dict) else 0.5, 0.5)
        sl = _safe_float(result.get("stop_loss_percentage", 0.3) if isinstance(result, dict) else 0.3, 0.3)

        # Hard bounds to prevent prompt-injection / malformed outputs from causing extreme risk.
        tp = max(0.1, min(5.0, tp))
        sl = max(0.1, min(2.0, sl))

        rationale = ""
        if isinstance(result, dict):
            rationale = str(result.get("rationale", ""))[:500]

        return {
            "take_profit_percentage": tp,
            "stop_loss_percentage": sl,
            "rationale": rationale or "AI-determined levels",
        }