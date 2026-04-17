import json
import logging
import re
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import OPENAI_API_BASE, OPENAI_API_KEY, OPENAI_API_MODEL

logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or OPENAI_API_KEY
        self.base_url = base_url or OPENAI_API_BASE
        self.model = model or OPENAI_API_MODEL
        self._session = self._build_session()

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

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError("Please set OPENAI_API_KEY in your environment.")

    def _parse_json(self, text: str) -> Any:
        """
        Best-effort JSON parser.

        The model is instructed to return JSON, but in failure modes it may emit
        surrounding text, multiple JSON objects, or whitespace. We try to find
        the first valid JSON object/array without crashing the caller.
        """
        stripped = (text or "").strip()
        if not stripped:
            return ""

        # Fast path: whole string is JSON.
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()

        # Try to decode starting from each plausible JSON start char.
        # This avoids greedy regex extraction that can capture invalid fragments.
        for start_char in ("{", "["):
            idx = stripped.find(start_char)
            while idx != -1:
                try:
                    obj, _end = decoder.raw_decode(stripped[idx:])
                    return obj
                except json.JSONDecodeError:
                    idx = stripped.find(start_char, idx + 1)

        # Last resort: attempt to pull a single {...} block (non-greedy), then decode.
        match = re.search(r"(\{[\s\S]*?\})", stripped)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return stripped

    def _extract_text(self, data: Dict[str, Any]) -> str:
        """
        Extract assistant text from Chat Completions responses.

        Expected shape:
        {
          "choices": [{"message": {"role": "assistant", "content": "..."}, ...}],
          ...
        }
        """
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        return content
        return ""

    def call(self, system_prompt: str, user_message: str, model: Optional[str] = None, timeout: int = 30) -> Any:
        self._ensure_api_key()
        model_name = model or self.model
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            # Force valid JSON output. Chat Completions supports response_format JSON mode.
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self._session.post(endpoint, headers=headers, json=payload, timeout=timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI API request failed (status={response.status_code}): {response.text[:500]}")
        data = response.json()
        text = self._extract_text(data)
        if text:
            return self._parse_json(text)
        return self._parse_json(json.dumps(data))

    # ---- Domain helpers (kept signature-compatible with the previous Gemini client) ----
    def classify_news_sentiment(self, text: str) -> Dict[str, Any]:
        system_prompt = (
            "You are a structured signal extractor for cryptocurrency (ETH) macro headlines. "
            "Return only JSON with no markdown or explanation. "
            "The fields must be: direction (bullish, bearish, neutral), magnitude (1-10), "
            "category (rates_liquidity, regulation, security_incident, etf_flows, macro_risk_off, other), "
            "one_sentence_reason."
        )
        user_message = f"Classify this news item for ETH/crypto: {text}"
        result = self.call(system_prompt, user_message)
        return {
            "direction": result.get("direction", "neutral"),
            "magnitude": float(result.get("magnitude", 0)) if result.get("magnitude") is not None else 0.0,
            "category": result.get("category", "other"),
            "reason": result.get("one_sentence_reason", ""),
        }

    def interpret_leader_dasha(self, leader_context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = (
            "You are a policy-risk analyst for digital asset markets (ETH). "
            "Return only JSON with no markdown or explanation. "
            "The output fields must be: likely_action, probability (0-100), "
            "risk_category (liquidity_tightening, regulatory_clamp, stability, neutral), one_sentence_summary."
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
            "You are a macro bias synthesizer for ETH using structured Vedic sidereal inputs only. "
            "Do not invent planetary positions; reason only from the JSON fields provided "
            "(vedic_snapshot, vedha, crypto_astro, astro positions). "
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
            "You are a calibration analyst for a Vedic-informed ETH trading system. "
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
            "You are a professional trading risk manager for ETH perps. "
            "Return only JSON with no markdown or explanation. "
            "Using only the supplied context (no invented prices), propose a single take-profit "
            "distance as a percent of entry. Stops are computed in code from ATR/volatility. "
            "The fields must be: take_profit_percentage (0.1-5.0), rationale (one sentence)."
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

        tp = max(0.1, min(5.0, tp))

        rationale = ""
        if isinstance(result, dict):
            rationale = str(result.get("rationale", ""))[:500]

        return {
            "take_profit_percentage": tp,
            "rationale": rationale or "AI-determined levels",
        }

