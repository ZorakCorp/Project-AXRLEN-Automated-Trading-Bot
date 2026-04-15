import hashlib
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
from eth_account import Account
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

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
except Exception:
    Exchange = None  # type: ignore
    Info = None  # type: ignore


class HyperliquidClient:
    def __init__(self):
        self.api_key = HYPERLIQUID_API_KEY
        self.api_secret = HYPERLIQUID_API_SECRET
        self.wallet_address = HYPERLIQUID_WALLET_ADDRESS
        # Allow dry-run execution without secrets to make local/dev testing safe.
        if LIVE_TRADING:
            validate_hyperliquid_config()
            if Exchange is None or Info is None:
                raise RuntimeError(
                    "hyperliquid-python-sdk is required for LIVE_TRADING. Install it (pip install hyperliquid-python-sdk)."
                )
        self._session = self._build_session()

        self.info = None
        self.exchange = None
        if Info is not None:
            # skip_ws=True to avoid background threads in the bot loop
            self.info = Info(HYPERLIQUID_API_BASE, skip_ws=True, timeout=10.0)
        if LIVE_TRADING and Exchange is not None:
            wallet = Account.from_key(self.api_secret)
            self.exchange = Exchange(
                wallet=wallet,
                base_url=HYPERLIQUID_API_BASE,
                account_address=self.wallet_address,
                timeout=10.0,
            )

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

    def validate_tradable_symbol(self) -> None:
        if self.info is None:
            if LIVE_TRADING:
                raise RuntimeError("Hyperliquid Info client not available in LIVE_TRADING mode.")
            return
        try:
            _ = self.info.name_to_asset(MARKET_SYMBOL)
        except Exception as e:
            raise ValueError(f"Unsupported MARKET_SYMBOL={MARKET_SYMBOL} for Hyperliquid.") from e
        if LIVE_TRADING and not HYPERLIQUID_EXECUTION_VERIFIED:
            raise RuntimeError(
                "Refusing LIVE_TRADING: Hyperliquid execution in this repo is not verified. "
                "After you confirm signing/order formats against official docs, set HYPERLIQUID_EXECUTION_VERIFIED=true."
            )

    def fetch_history(self, symbol: str = MARKET_SYMBOL, limit: int = 300) -> dict:
        if self.info is None:
            dates = pd.date_range("2024-01-01", periods=limit, freq="1min")
            return {
                "candles": [
                    {
                        "timestamp": int(d.timestamp() * 1000),
                        "open": 100.0,
                        "high": 100.0,
                        "low": 100.0,
                        "close": 100.0,
                        "volume": 0,
                    }
                    for d in dates
                ]
            }

        end_ms = int(time.time() * 1000)
        start_ms = end_ms - limit * 60_000
        candles = self.info.candles_snapshot(symbol, interval="1m", startTime=start_ms, endTime=end_ms)
        normalized = []
        for c in candles:
            normalized.append(
                {
                    "timestamp": int(c.get("t") or 0),
                    "open": float(c.get("o") or 0),
                    "high": float(c.get("h") or 0),
                    "low": float(c.get("l") or 0),
                    "close": float(c.get("c") or 0),
                    "volume": float(c.get("v") or 0),
                }
            )
        return {"candles": normalized}

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
        if leverage > MAX_LEVERAGE:
            logger.warning(
                "Requested leverage %s exceeds MAX_LEVERAGE=%s; clamping to MAX_LEVERAGE",
                leverage,
                MAX_LEVERAGE,
            )
            leverage = MAX_LEVERAGE

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

        if self.exchange is None or self.info is None:
            raise RuntimeError("Hyperliquid exchange client not initialized.")

        coin = MARKET_SYMBOL
        mids = self.info.all_mids()
        mid = float(mids[self.info.name_to_coin[coin]])
        asset = self.info.name_to_asset(coin)
        # Hyperliquid enforces tick size rules for prices:
        # - up to 5 significant figures
        # - no more than (MAX_DECIMALS - szDecimals) decimal places (MAX_DECIMALS=6 for perps, 8 for spot)
        # - integer prices always allowed
        # Ref: Hyperliquid docs + SDK examples/rounding.py
        max_decimals = 6  # perps default
        sz_decimals_map = {}
        try:
            meta = self.info.meta()
            for asset_info in (meta.get("universe", []) if isinstance(meta, dict) else []):
                if isinstance(asset_info, dict) and "name" in asset_info and "szDecimals" in asset_info:
                    sz_decimals_map[str(asset_info["name"])] = int(asset_info["szDecimals"])
        except Exception:
            sz_decimals_map = {}

        def _round_px(value: float) -> float:
            px_val = float(value)
            if px_val > 100_000:
                return float(round(px_val))
            sz_decimals_for_coin = int(sz_decimals_map.get(coin, 0))
            decimals = max(0, max_decimals - sz_decimals_for_coin)
            # First limit to 5 significant figures, then enforce decimal places
            return round(float(f"{px_val:.5g}"), decimals)

        sz = float(size_usd) / max(mid, 1e-9)
        sz_decimals = int(self.info.asset_to_sz_decimals[asset])
        sz = float(f"{sz:.{sz_decimals}f}")
        if sz <= 0:
            raise ValueError("Calculated order size is zero after rounding.")

        is_buy = side.lower() == "buy"
        self.exchange.update_leverage(leverage=leverage, name=coin, is_cross=True)

        slippage = float(os.getenv("ORDER_SLIPPAGE", "0.01"))
        px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
        px = _round_px(px)

        orders = [
            {
                "coin": coin,
                "is_buy": is_buy,
                "sz": sz,
                "limit_px": float(px),
                "order_type": {"limit": {"tif": "Ioc"}},
                "reduce_only": False,
            }
        ]

        have_protection = stop_loss is not None and take_profit is not None
        if not have_protection and not ALLOW_UNPROTECTED_POSITIONS:
            raise RuntimeError(
                "Refusing live order without TP/SL. Set ALLOW_UNPROTECTED_POSITIONS=true to trade without protection."
            )

        if have_protection:
            sl_px = _round_px(float(stop_loss))
            tp_px = _round_px(float(take_profit))
            orders.append(
                {
                    "coin": coin,
                    "is_buy": (not is_buy),
                    "sz": sz,
                    "limit_px": sl_px,
                    "order_type": {"trigger": {"triggerPx": sl_px, "isMarket": True, "tpsl": "sl"}},
                    "reduce_only": True,
                }
            )
            orders.append(
                {
                    "coin": coin,
                    "is_buy": (not is_buy),
                    "sz": sz,
                    "limit_px": tp_px,
                    "order_type": {"trigger": {"triggerPx": tp_px, "isMarket": True, "tpsl": "tp"}},
                    "reduce_only": True,
                }
            )
            result = self.exchange.bulk_orders(orders, grouping="normalTpsl")
        else:
            result = self.exchange.bulk_orders(orders, grouping="na")

        return {
            "order_id": f"hl_{idempotency_key or str(uuid.uuid4())[:8]}",
            "status": "placed",
            "symbol": coin,
            "side": side,
            "leverage": leverage,
            "size_usd": float(size_usd),
            "size_coin": float(sz),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "response": result,
        }

    def get_positions(self) -> dict:
        """Get user positions via REST API"""
        if not LIVE_TRADING:
            return {"positions": []}
        if self.info is None:
            return {"positions": []}
        result = self.info.user_state(self.wallet_address)
        positions = []
        for asset_pos in result.get("assetPositions", []):
            pos = asset_pos.get("position", {}) or {}
            if not pos:
                continue
            szi = float(pos.get("szi", 0) or 0)
            if szi == 0:
                continue
            positions.append(
                {
                    "id": f"{pos.get('coin', '')}_{szi}",
                    "symbol": pos.get("coin", ""),
                    "size": szi,
                    "entry_price": float(pos.get("entryPx", 0) or 0),
                    "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                    "leverage": float((pos.get("leverage", {}) or {}).get("value", 1) or 1),
                    "status": "open",
                }
            )
        return {"positions": positions}

    def close_position(self, position_id: str) -> dict:
        """Close position via REST API"""
        if not LIVE_TRADING:
            return {"status": "dry_run", "position_id": position_id}
        if self.exchange is None:
            raise RuntimeError("Hyperliquid exchange client not initialized.")
        coin = position_id.split("_")[0] if "_" in position_id else MARKET_SYMBOL
        resp = self.exchange.market_close(coin)
        return {"status": "closed", "position_id": position_id, "response": resp}


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
        requested_leverage = int(os.getenv("ORDER_LEVERAGE", "25"))
        leverage = min(max(1, requested_leverage), MAX_LEVERAGE)
        if leverage != requested_leverage:
            logger.warning(
                "ORDER_LEVERAGE=%s is outside allowed range; using leverage=%s (MAX_LEVERAGE=%s)",
                requested_leverage,
                leverage,
                MAX_LEVERAGE,
            )

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
            leverage=leverage,
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
