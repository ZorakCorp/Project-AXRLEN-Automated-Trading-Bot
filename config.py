import os
from dotenv import load_dotenv

load_dotenv()

def _normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    # Users often paste ".../v1" from docs; this project constructs "/exchange" and "/info" paths.
    # Normalize to the host root to avoid double "/v1/exchange" style paths.
    if url.endswith("/v1"):
        url = url[: -len("/v1")]
    return url


HYPERLIQUID_API_KEY = os.getenv("HYPERLIQUID_API_KEY", "")
HYPERLIQUID_API_SECRET = os.getenv("HYPERLIQUID_API_SECRET", "")
HYPERLIQUID_WALLET_ADDRESS = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
# Cheapest GPT-4-class default; override via OPENAI_API_MODEL in Railway variables.
OPENAI_API_MODEL = os.getenv("OPENAI_API_MODEL", "gpt-4.1-mini")
MARKET_SYMBOL = os.getenv("MARKET_SYMBOL", "ETH")
CAPITAL_USD = float(os.getenv("CAPITAL_USD", "100000"))
MODEL_PATH = os.getenv("MODEL_PATH", "model.joblib")
HYPERLIQUID_API_BASE = _normalize_base_url(os.getenv("HYPERLIQUID_API_BASE", "https://api.hyperliquid.xyz"))

# Safety controls
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
MAX_NOTIONAL_PCT = float(os.getenv("MAX_NOTIONAL_PCT", "0.10"))  # max position notional as % of capital
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "10"))
ALLOW_UNPROTECTED_POSITIONS = os.getenv("ALLOW_UNPROTECTED_POSITIONS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
HYPERLIQUID_EXECUTION_VERIFIED = os.getenv("HYPERLIQUID_EXECUTION_VERIFIED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

# Default TP/SL bounds (percent of price)
# Backwards compatible aliases:
# - TP_PERCENT / SL_PERCENT (older configs)
DEFAULT_TAKE_PROFIT_PCT = float(os.getenv("DEFAULT_TAKE_PROFIT_PCT", os.getenv("TP_PERCENT", "0.5")))
DEFAULT_STOP_LOSS_PCT = float(os.getenv("DEFAULT_STOP_LOSS_PCT", os.getenv("SL_PERCENT", "0.3")))

# OANDA (optional / not used by main entrypoint)
OANDA_API_KEY = os.getenv("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_ENVIRONMENT = os.getenv("OANDA_ENVIRONMENT", "practice")
OANDA_INSTRUMENT = os.getenv("OANDA_INSTRUMENT", "BCO_USD")


def validate_hyperliquid_config() -> None:
    if not HYPERLIQUID_API_KEY or not HYPERLIQUID_API_SECRET or not HYPERLIQUID_WALLET_ADDRESS:
        raise RuntimeError("Please set HYPERLIQUID_API_KEY, HYPERLIQUID_API_SECRET, and HYPERLIQUID_WALLET_ADDRESS in your environment.")


def validate_openai_config() -> None:
    if not OPENAI_API_KEY:
        raise RuntimeError("Please set OPENAI_API_KEY in your environment.")


def validate_oanda_config() -> None:
    if not OANDA_API_KEY or not OANDA_ACCOUNT_ID:
        raise RuntimeError("Please set OANDA_API_KEY and OANDA_ACCOUNT_ID in your environment.")
