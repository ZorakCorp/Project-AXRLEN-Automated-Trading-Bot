import hashlib
import hmac
import json
import logging
import time
import uuid
import signal
from datetime import datetime, timezone
from typing import Dict, Optional

import os
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ai_model import PredictionModel
from config import (
    CAPITAL_USD,
    HYPERLIQUID_API_BASE,
    HYPERLIQUID_API_KEY,
    HYPERLIQUID_API_SECRET,
    HYPERLIQUID_WALLET_ADDRESS,
    LIVE_TRADING,
    MAX_NOTIONAL_PCT,
    MAX_LEVERAGE,
    ALLOW_UNPROTECTED_POSITIONS,
    HYPERLIQUID_EXECUTION_VERIFIED,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    MARKET_SYMBOL,
    MODEL_PATH,
    validate_hyperliquid_config,
)
from raw_data_engine import RawDataIngestion
from signal_engine import RiskEngine, run_probability
from state_store import append_jsonl, load_json, save_json

logger = logging.getLogger(__name__)


class HyperliquidClient:
    def __init__(self):
        self.api_key = HYPERLIQUID_API_KEY
        self.api_secret = HYPERLIQUID_API_SECRET
        self.wallet_address = HYPERLIQUID_WALLET_ADDRESS
        self.base_url = f"{HYPERLIQUID_API_BASE}/exchange"
        self.info_url = f"{HYPERLIQUID_API_BASE}/info"
        # Allow dry-run execution without secrets to make local/dev testing safe.
        if LIVE_TRADING:
            validate_hyperliquid_config()
        self._session = self._build_session()

        # Asset ID mapping (ETH = 4, BTC = 1, etc.)
        self.asset_ids = {
            "ETH": 4,
            "BTC": 1,
            "BRENTUSD": 99999,  # Placeholder - Hyperliquid doesn't support commodities
        }

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

    def _get_asset_id(self, symbol: str) -> int:
        """Get asset ID for symbol"""
        if symbol in self.asset_ids:
            return self.asset_ids[symbol]
        raise ValueError(f"Unsupported MARKET_SYMBOL={symbol}. Supported: {sorted(self.asset_ids.keys())}")

    def validate_tradable_symbol(self) -> None:
        asset_id = self.asset_ids.get(MARKET_SYMBOL)
        if asset_id is None:
            raise ValueError(f"Unsupported MARKET_SYMBOL={MARKET_SYMBOL}. Supported: {sorted(self.asset_ids.keys())}")
        if LIVE_TRADING and (MARKET_SYMBOL == "BRENTUSD" or asset_id == 99999):
            raise RuntimeError(
                "Refusing LIVE_TRADING: MARKET_SYMBOL=BRENTUSD is configured as a placeholder and is not tradable on Hyperliquid."
            )
        if LIVE_TRADING and not HYPERLIQUID_EXECUTION_VERIFIED:
            raise RuntimeError(
                "Refusing LIVE_TRADING: Hyperliquid execution in this repo is not verified. "
                "After you confirm signing/order formats against official docs, set HYPERLIQUID_EXECUTION_VERIFIED=true."
            )

    def _sign_eip712(self, action: dict, nonce: int) -> dict:
        """Create EIP712 signature for Hyperliquid using Ethereum private key"""
        try:
            from eth_account import Account
            from eth_account.messages import encode_structured_data

            private_key = self.api_secret
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key

            # EIP712 domain and message structure
            full_message = {
                "domain": {
                    "name": "Exchange",
                    "version": "1",
                    "chainId": 1337,
                    "verifyingContract": "0x0000000000000000000000000000000000000000",
                },
                "types": {
                    "EIP712Domain": [
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "chainId", "type": "uint256"},
                        {"name": "verifyingContract", "type": "address"},
                    ],
                    "Agent": [
                        {"name": "source", "type": "string"},
                        {"name": "connectionId", "type": "bytes32"},
                    ],
                },
                "primaryType": "Agent",
                "message": {
                    "source": "trading_bot",
                    "connectionId": f"0x{hashlib.sha256(f'{self.api_key}:{nonce}'.encode()).hexdigest()}",
                },
            }

            # Encode and sign
            signed_message = Account.sign_message(
                encode_structured_data(primitive=full_message), private_key
            )

            return {
                "r": hex(signed_message.r),
                "s": hex(signed_message.s),
                "v": signed_message.v,
            }

        except Exception as e:
            logger.error(f"EIP712 signing failed: {e}")
            # Return placeholder signature for testing
            return {
                "r": "0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298",
                "s": "0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8",
                "v": 27,
            }

    def fetch_history(self, symbol: str = MARKET_SYMBOL, limit: int = 300) -> dict:
        # For now, use dummy data until we confirm the correct API endpoint
        import pandas as pd
        dates = pd.date_range('2024-01-01', periods=limit, freq='1min')
        return {
            'candles': [
                {
                    'timestamp': int(d.timestamp() * 1000),
                    'open': 85.0 + (i % 10 - 5) * 0.1,
                    'high': 85.5 + (i % 10 - 5) * 0.1,
                    'low': 84.5 + (i % 10 - 5) * 0.1,
                    'close': 85.0 + (i % 10 - 5) * 0.1,
                    'volume': 1000 + i * 10
                } for i, d in enumerate(dates)
            ]
        }

    def place_order(
        self,
        side: str,
        size_usd: float,
        stop_loss: float,
        take_profit: float,
        leverage: int = 25,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Place live order on Hyperliquid via REST API"""
        if not LIVE_TRADING:
            # Explicit dry-run mode: never silently place real orders.
            logger.warning(
                "DRY_RUN: LIVE_TRADING is disabled; simulating %s order size_usd=%s for %s",
                side,
                size_usd,
                MARKET_SYMBOL,
            )
            return {
                "order_id": f"dryrun_{idempotency_key or str(uuid.uuid4())[:8]}",
                "status": "simulated",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "leverage": leverage,
                "size_usd": float(size_usd),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "dry_run": True,
            }

        self.validate_tradable_symbol()

        if leverage > MAX_LEVERAGE:
            raise ValueError(f"Requested leverage {leverage} exceeds MAX_LEVERAGE={MAX_LEVERAGE}")

        # This implementation currently does NOT place protective TP/SL orders on-exchange.
        # Refuse to trade live unless explicitly allowed.
        if not ALLOW_UNPROTECTED_POSITIONS and (stop_loss is not None or take_profit is not None):
            raise RuntimeError(
                "Refusing live order: protective TP/SL are not enforced on-exchange in this implementation. "
                "Set ALLOW_UNPROTECTED_POSITIONS=true only if you understand the risk."
            )

        try:
            asset_id = self._get_asset_id(MARKET_SYMBOL)
            nonce = int(time.time() * 1000)

            # First, update leverage
            leverage_action = {
                "type": "updateLeverage",
                "asset": asset_id,
                "isCross": True,
                "leverage": leverage
            }

            leverage_payload = {
                "action": leverage_action,
                "nonce": nonce,
                "signature": self._sign_eip712(leverage_action, nonce),
                "vaultAddress": None
            }

            # Update leverage first
            leverage_response = self._session.post(self.base_url, json=leverage_payload, timeout=10)
            leverage_response.raise_for_status()
            logger.info(f"Leverage updated to {leverage}x for {MARKET_SYMBOL}")

            # Now place the order
            is_buy = side.lower() == "buy"
            order_action = {
                "type": "order",
                "orders": [
                    {
                        "a": asset_id,  # asset ID
                        "b": is_buy,    # is buy
                        "p": "0",       # price (0 for market order)
                        "s": str(size_usd),  # size as string
                        "r": False,     # reduce only
                        "t": {
                            "limit": {
                                "tif": "Ioc"  # Immediate or Cancel for market-like execution
                            }
                        }
                    }
                ],
                "grouping": "na"
            }

            order_payload = {
                "action": order_action,
                "nonce": nonce + 1,  # Increment nonce
                "signature": self._sign_eip712(order_action, nonce + 1),
                "vaultAddress": None
            }

            response = self._session.post(self.base_url, json=order_payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict):
                raise ValueError(f"Unexpected API response: {result}")

            logger.info(
                "LIVE ORDER PLACED: %s notional_usd=%.2f leverage=%sx symbol=%s",
                side,
                float(size_usd),
                leverage,
                MARKET_SYMBOL,
            )

            return {
                "order_id": result.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("oid", f"live_{idempotency_key or str(uuid.uuid4())[:8]}"),
                "status": "placed",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "leverage": leverage,
                "size_usd": float(size_usd),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "response": result
            }

        except Exception as e:
            logger.error(f"Failed to place live order: {e}")
            # In live mode, never pretend we placed an order.
            raise

    def get_positions(self) -> dict:
        """Get user positions via REST API"""
        if not LIVE_TRADING:
            return {"positions": []}
        try:
            payload = {
                "type": "userState",
                "user": self.wallet_address  # Use wallet address, not API key
            }

            response = self._session.post(self.info_url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            positions = []
            for asset_pos in result.get("assetPositions", []):
                pos = asset_pos.get("position", {})
                if pos:
                    positions.append({
                        "id": f"{pos.get('coin', '')}_{pos.get('szi', 0)}",
                        "symbol": pos.get("coin", ""),
                        "size": float(pos.get("szi", 0)),
                        "entry_price": float(pos.get("entryPx", 0)),
                        "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                        "leverage": pos.get("leverage", {}).get("value", 1),
                        "status": "open"
                    })

            return {"positions": positions}

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response body: {e.response.text}")
            return {"positions": []}

    def close_position(self, position_id: str) -> dict:
        """Close position via REST API"""
        if not LIVE_TRADING:
            return {"status": "dry_run", "position_id": position_id}
        try:
            # Parse position details from ID
            # This is a simplified implementation
            asset_id = self._get_asset_id(MARKET_SYMBOL)
            nonce = int(time.time() * 1000)

            # Get current position to determine close size
            positions = self.get_positions()["positions"]
            position = next((p for p in positions if p["id"] == position_id), None)

            if not position:
                logger.error(f"Position {position_id} not found")
                return {"status": "error", "position_id": position_id}

            # Create close order (opposite side, reduce only)
            is_buy = position["size"] < 0  # If negative size, need to buy to close short
            close_size = abs(position["size"])

            close_action = {
                "type": "order",
                "orders": [
                    {
                        "a": asset_id,
                        "b": is_buy,
                        "p": "0",  # Market order
                        "s": str(close_size),
                        "r": True,  # Reduce only
                        "t": {
                            "limit": {
                                "tif": "Ioc"
                            }
                        }
                    }
                ],
                "grouping": "na"
            }

            close_payload = {
                "action": close_action,
                "nonce": nonce,
                "signature": self._sign_eip712(close_action, nonce),
                "vaultAddress": None
            }

            response = self._session.post(self.base_url, json=close_payload, timeout=10)
            response.raise_for_status()

            logger.info(f"Position {position_id} closed")
            return {"status": "closed", "position_id": position_id}

        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            return {"status": "error", "position_id": position_id, "error": str(e)}


class TradeManager:
    def __init__(self, client: HyperliquidClient):
        self.client = client
        self.active_position = None
        self.data_engine = RawDataIngestion()
        self.risk_engine = RiskEngine(capital=CAPITAL_USD)
        self.daily_loss = 0.0
        self.weekly_loss = 0.0
        self.trade_log = []
        self.ai_model = None
        self._shutdown_requested = False

        self.state_path = os.getenv("BOT_STATE_PATH", "bot_state.json")
        self.journal_path = os.getenv("BOT_JOURNAL_PATH", "bot_journal.jsonl")
        self._load_state()

        if os.path.exists(MODEL_PATH):
            self.ai_model = PredictionModel(model_path=MODEL_PATH)
            try:
                self.ai_model.load()
            except Exception:
                logger.warning("AI model file exists but could not be loaded, continuing without AI signal")
                self.ai_model = None

        self._install_signal_handlers()
        self._log_startup_summary()

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            logger.warning("Shutdown requested (signal=%s). Will exit after current iteration.", signum)
            self._shutdown_requested = True

        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is None:
                continue
            try:
                signal.signal(sig, _handler)
            except Exception:
                pass

    def _log_startup_summary(self) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "startup",
            "symbol": MARKET_SYMBOL,
            "capital_usd": CAPITAL_USD,
            "live_trading": LIVE_TRADING,
            "max_notional_pct": MAX_NOTIONAL_PCT,
            "max_leverage": MAX_LEVERAGE,
            "allow_unprotected_positions": ALLOW_UNPROTECTED_POSITIONS,
            "execution_verified": HYPERLIQUID_EXECUTION_VERIFIED,
            "model_loaded": self.ai_model is not None,
            "state_path": self.state_path,
            "journal_path": self.journal_path,
        }
        append_jsonl(self.journal_path, event)
        logger.info(
            "Startup: symbol=%s live=%s verified=%s model_loaded=%s caps(max_notional_pct=%s max_leverage=%s)",
            MARKET_SYMBOL,
            LIVE_TRADING,
            HYPERLIQUID_EXECUTION_VERIFIED,
            self.ai_model is not None,
            MAX_NOTIONAL_PCT,
            MAX_LEVERAGE,
        )

    def _load_state(self) -> None:
        try:
            state = load_json(self.state_path, default={})
        except Exception as e:
            logger.warning("Failed to load state file %s: %s", self.state_path, e)
            state = {}

        self.daily_loss = float(state.get("daily_loss", 0.0) or 0.0)
        self.weekly_loss = float(state.get("weekly_loss", 0.0) or 0.0)
        self.trade_log = list(state.get("trade_log", []) or [])
        self.active_position = state.get("active_position")
        capital_override = state.get("capital_usd")
        if capital_override is not None:
            try:
                self.risk_engine.capital = float(capital_override)
            except Exception:
                pass

    def _save_state(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "symbol": MARKET_SYMBOL,
            "capital_usd": self.risk_engine.capital,
            "daily_loss": self.daily_loss,
            "weekly_loss": self.weekly_loss,
            "trade_log": self.trade_log[-1000:],
            "active_position": self.active_position,
        }
        try:
            save_json(self.state_path, state)
        except Exception as e:
            logger.warning("Failed to save state file %s: %s", self.state_path, e)

    def evaluate_market(self):
        raw = self.client.fetch_history()
        candles = raw.get("candles", [])
        if not candles:
            raise RuntimeError("No candle data returned from Hyperliquid")

        df = pd.DataFrame(candles)
        if "close" not in df.columns:
            raise RuntimeError("Unexpected candle payload from Hyperliquid")

        context = self.data_engine.build_context(MARKET_SYMBOL)
        context["price_history"] = df
        if self.ai_model is not None:
            context["ai_prediction"] = self.ai_model.predict_label(df)
            context["ai_prediction_raw"] = int(self.ai_model.predict(df))
        else:
            context["ai_prediction"] = None
            context["ai_prediction_raw"] = None

        probability = run_probability(context)
        logger.info(
            "Probability output: score=%s classification=%s",
            probability["score"],
            probability["classification"],
        )
        return probability, df, context

    def calculate_stop_distance(self, df, sl_percent: float) -> float:
        """Return a price-distance for the stop, in quote currency units."""
        if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
            return float(df["close"].iloc[-1]) * (sl_percent / 100)

        df = df.dropna(subset=["close", "high", "low"])
        if len(df) < 21:
            return float(df["close"].iloc[-1]) * (sl_percent / 100)

        df["high_low"] = df["high"] - df["low"]
        atr = df["high_low"].rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return float(df["close"].iloc[-1]) * (sl_percent / 100)
        return float(atr) * 2

    def should_halt_trading(self) -> bool:
        if self.daily_loss <= -0.05 * CAPITAL_USD:
            logger.warning("Daily drawdown limit reached: %s", self.daily_loss)
            return True
        if self.weekly_loss <= -0.15 * CAPITAL_USD:
            logger.warning("Weekly drawdown limit reached: %s", self.weekly_loss)
            return True
        return False

    def record_trade_result(self, pnl: float) -> None:
        self.trade_log.append(pnl)
        self.daily_loss += pnl if pnl < 0 else 0
        self.weekly_loss += pnl if pnl < 0 else 0
        self.risk_engine.update_capital(pnl)
        append_jsonl(
            self.journal_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "pnl",
                "symbol": MARKET_SYMBOL,
                "pnl": float(pnl),
                "daily_loss": float(self.daily_loss),
                "weekly_loss": float(self.weekly_loss),
                "capital_usd": float(self.risk_engine.capital),
            },
        )
        self._save_state()

    def execute_signal(self, probability: Dict, df, context: Dict):
        classification = probability["classification"]
        score = probability["score"]

        if self.should_halt_trading():
            logger.info("Halting new trades due to drawdown limit")
            return

        if self.active_position:
            logger.info("Active position already open, checking for close conditions")
            self.monitor_position()
            return

        if classification == "FLAT":
            logger.info("Market state is FLAT, observation only")
            return

        red_day = context.get("red_day", False)
        if red_day:
            logger.info("Red Day Gate active, skipping new positions")
            return

        last_price = float(df["close"].iloc[-1])
        # Get dynamic TP/SL from AI recommendation
        tp_sl = context.get("tp_sl_recommendation", {}) or {}
        tp_percent = float(tp_sl.get("take_profit_percentage", DEFAULT_TAKE_PROFIT_PCT) or DEFAULT_TAKE_PROFIT_PCT)
        sl_percent = float(tp_sl.get("stop_loss_percentage", DEFAULT_STOP_LOSS_PCT) or DEFAULT_STOP_LOSS_PCT)
        sl_percent = max(0.01, min(5.0, sl_percent))
        tp_percent = max(0.01, min(10.0, tp_percent))

        stop_distance = self.calculate_stop_distance(df, sl_percent=sl_percent)
        position_size = self.risk_engine.position_size(score, stop_distance, last_price)
        position_size = min(position_size, CAPITAL_USD * MAX_NOTIONAL_PCT)
        if position_size <= 0:
            logger.info("Calculated position size is zero, skipping trade")
            return

        stop_loss = round(last_price - stop_distance if classification == "LONG" else last_price + stop_distance, 2)
        take_profit = round(
            last_price + last_price * (tp_percent / 100)
            if classification == "LONG"
            else last_price - last_price * (tp_percent / 100),
            2,
        )
        side = "buy" if classification == "LONG" else "sell"
        idempotency_key = str(uuid.uuid4())

        logger.info(
            "Submitting %s order, size=%s, stop=%s, tp=%s, idempotency=%s",
            side,
            position_size,
            stop_loss,
            take_profit,
            idempotency_key,
        )
        append_jsonl(
            self.journal_path,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "submit_order",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "classification": classification,
                "score": float(score),
                "size_usd": float(position_size),
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "idempotency_key": idempotency_key,
                "live_trading": LIVE_TRADING,
            },
        )
        result = self.client.place_order(
            side=side,
            size_usd=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=25,
            idempotency_key=idempotency_key,
        )
        self.active_position = result
        self._save_state()
        logger.info("Opened position: %s", result)

    def monitor_position(self):
        positions = self.client.get_positions()
        if not positions.get("positions"):
            logger.info("No open positions found")
            self.active_position = None
            self._save_state()
            return

        latest = positions["positions"][0]
        self.active_position = latest
        logger.info("Monitoring active position %s", latest.get("id"))

        if latest.get("unrealized_pnl") is not None:
            logger.info("Position PnL: %s", latest.get("unrealized_pnl"))

        if latest.get("status") != "open":
            realized_pnl = latest.get("realized_pnl")
            if realized_pnl is not None:
                self.record_trade_result(float(realized_pnl))
            logger.info("Position closed by exchange: %s", latest.get("status"))
            self.active_position = None

    def run(self, interval_seconds: int = 60):
        logger.info("Starting trade loop for %s", MARKET_SYMBOL)
        while True:
            try:
                probability, df, context = self.evaluate_market()
                self.execute_signal(probability, df, context)
            except Exception as exc:
                logger.exception("Error during trade loop: %s", exc)
                append_jsonl(
                    self.journal_path,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event": "loop_error",
                        "symbol": MARKET_SYMBOL,
                        "error": str(exc)[:500],
                    },
                )
            finally:
                self._save_state()

            if self._shutdown_requested:
                append_jsonl(
                    self.journal_path,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "event": "shutdown",
                        "symbol": MARKET_SYMBOL,
                    },
                )
                logger.info("Shutdown complete.")
                return
            time.sleep(interval_seconds)
