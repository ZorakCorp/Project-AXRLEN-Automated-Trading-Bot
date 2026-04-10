import os
from dotenv import load_dotenv

load_dotenv()

HYPERLIQUID_API_KEY = os.getenv("HYPERLIQUID_API_KEY", "")
HYPERLIQUID_API_SECRET = os.getenv("HYPERLIQUID_API_SECRET", "")
HYPERLIQUID_WALLET_ADDRESS = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_BASE = os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_API_MODEL = os.getenv("GEMINI_API_MODEL", "gemini-1.5-flash")
MARKET_SYMBOL = os.getenv("MARKET_SYMBOL", "BRENTUSD")
CAPITAL_USD = float(os.getenv("CAPITAL_USD", "100000"))
MODEL_PATH = os.getenv("MODEL_PATH", "model.joblib")
HYPERLIQUID_API_BASE = os.getenv("HYPERLIQUID_API_BASE", "https://api.hyperliquid.xyz/v1")


def validate_hyperliquid_config() -> None:
    if not HYPERLIQUID_API_KEY or not HYPERLIQUID_API_SECRET or not HYPERLIQUID_WALLET_ADDRESS:
        raise RuntimeError("Please set HYPERLIQUID_API_KEY, HYPERLIQUID_API_SECRET, and HYPERLIQUID_WALLET_ADDRESS in your environment.")


def validate_gemini_config() -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("Please set GEMINI_API_KEY in your environment.")
