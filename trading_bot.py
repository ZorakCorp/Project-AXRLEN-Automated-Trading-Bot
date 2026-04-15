import hashlib
import logging
import time
import uuid
import signal
from datetime import datetime, timezone
from typing import Dict, Optional
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

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

        def _px_decimals() -> int:
            sz_decimals_for_coin = int(sz_decimals_map.get(coin, 0))
            return max(0, max_decimals - sz_decimals_for_coin)

        def _tick_size() -> Decimal:
            d = _px_decimals()
            # 10^-d, e.g. d=2 -> 0.01
            return Decimal(1).scaleb(-d)

        def _round_px(value: float) -> float:
            px_val = float(value)
            if px_val > 100_000:
                return float(round(px_val))
            decimals = _px_decimals()
            # First limit to 5 significant figures, then enforce decimal places
            return round(float(f"{px_val:.5g}"), decimals)

        def _quantize_to_tick(value: float, *, rounding: str) -> float:
            """
            Ensure the price is divisible by tick size while keeping it on the safe side.
            rounding: "floor" or "ceil"
            """
            v = Decimal(str(float(value)))
            tick = _tick_size()
            if tick == 0:
                return float(value)
            scaled = v / tick
            if rounding == "floor":
                q = scaled.to_integral_value(rounding=ROUND_FLOOR) * tick
            else:
                q = scaled.to_integral_value(rounding=ROUND_CEILING) * tick
            return float(q)

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
        # Entry price should be a valid tick.
        px = _quantize_to_tick(px, rounding=("ceil" if is_buy else "floor"))

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
            sl_px_raw = float(stop_loss)
            tp_px_raw = float(take_profit)

            # Round to allowed precision first.
            sl_px = _round_px(sl_px_raw)
            tp_px = _round_px(tp_px_raw)

            # Then quantize to tick size with directional rounding so SL/TP don't cross the entry.
            # For a LONG (buy):
            # - SL must be BELOW entry => floor it, and enforce at least 1 tick below.
            # - TP must be ABOVE entry => ceil it, and enforce at least 1 tick above.
            # For a SHORT (sell): inverted.
            tick = float(_tick_size())
            if is_buy:
                sl_px = _quantize_to_tick(sl_px, rounding="floor")
                tp_px = _quantize_to_tick(tp_px, rounding="ceil")
                if sl_px >= px:
                    sl_px = _quantize_to_tick(px - tick, rounding="floor")
                if tp_px <= px:
                    tp_px = _quantize_to_tick(px + tick, rounding="ceil")
            else:
                sl_px = _quantize_to_tick(sl_px, rounding="ceil")
                tp_px = _quantize_to_tick(tp_px, rounding="floor")
                if sl_px <= px:
                    sl_px = _quantize_to_tick(px + tick, rounding="ceil")
                if tp_px >= px:
                    tp_px = _quantize_to_tick(px - tick, rounding="floor")

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

        # If any leg was rejected, do NOT treat this as a placed position.
        if isinstance(result, dict) and result.get("status") == "ok":
            statuses = (((result.get("response") or {}).get("data") or {}).get("statuses")) if isinstance(result.get("response"), dict) else None
            if isinstance(statuses, list):
                errors = []
                for st in statuses:
                    if isinstance(st, dict) and st.get("error"):
                        errors.append(str(st.get("error")))
                if errors:
                    raise RuntimeError(f"Hyperliquid order rejected: {'; '.join(errors)[:500]}")

        return {
            "order_id": f"hl_{idempotency_key or str(uuid.uuid4())[:8]}",
            "status": "placed",
            "symbol": coin,
            "side": side,
            "leverage": leverage,
            "size_usd": float(size_usd),
            "size_coin": float(sz),
            "stop_loss": float(sl_px) if have_protection else stop_loss,
            "take_profit": float(tp_px) if have_protection else take_profit,
            "response": result,
        }

    def place_entry_limit(
        self,
        *,
        side: str,
        size_usd: float,
        limit_price: float,
        leverage: int,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """
        Place a resting limit entry order (no TP/SL attached).
        The TradeManager is responsible for adding TP/SL after the position is confirmed open.
        """
        if leverage > MAX_LEVERAGE:
            logger.warning(
                "Requested leverage %s exceeds MAX_LEVERAGE=%s; clamping to MAX_LEVERAGE",
                leverage,
                MAX_LEVERAGE,
            )
            leverage = MAX_LEVERAGE

        if not LIVE_TRADING:
            logger.warning(
                "DRY_RUN: LIVE_TRADING is disabled; simulating resting %s limit entry size_usd=%s at px=%s for %s",
                side,
                size_usd,
                limit_price,
                MARKET_SYMBOL,
            )
            return {
                "order_id": f"dryrun_entry_{idempotency_key or str(uuid.uuid4())[:8]}",
                "status": "simulated",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "leverage": leverage,
                "size_usd": float(size_usd),
                "limit_price": float(limit_price),
                "dry_run": True,
            }

        self.validate_tradable_symbol()
        if self.exchange is None or self.info is None:
            raise RuntimeError("Hyperliquid exchange client not initialized.")

        coin = MARKET_SYMBOL
        asset = self.info.name_to_asset(coin)

        mids = self.info.all_mids()
        mid = float(mids[self.info.name_to_coin[coin]])
        sz = float(size_usd) / max(mid, 1e-9)
        sz_decimals = int(self.info.asset_to_sz_decimals[asset])
        sz = float(f"{sz:.{sz_decimals}f}")
        if sz <= 0:
            raise ValueError("Calculated order size is zero after rounding.")

        is_buy = side.lower() == "buy"
        self.exchange.update_leverage(leverage=leverage, name=coin, is_cross=True)

        # Reuse the same tick/side-safe quantization logic as place_order.
        max_decimals = 6  # perps default
        sz_decimals_map = {}
        try:
            meta = self.info.meta()
            for asset_info in (meta.get("universe", []) if isinstance(meta, dict) else []):
                if isinstance(asset_info, dict) and "name" in asset_info and "szDecimals" in asset_info:
                    sz_decimals_map[str(asset_info["name"])] = int(asset_info["szDecimals"])
        except Exception:
            sz_decimals_map = {}

        def _px_decimals() -> int:
            sz_decimals_for_coin = int(sz_decimals_map.get(coin, 0))
            return max(0, max_decimals - sz_decimals_for_coin)

        def _tick_size() -> Decimal:
            return Decimal(1).scaleb(-_px_decimals())

        def _round_px(value: float) -> float:
            px_val = float(value)
            if px_val > 100_000:
                return float(round(px_val))
            return round(float(f"{px_val:.5g}"), _px_decimals())

        def _quantize_to_tick(value: float, *, rounding: str) -> float:
            v = Decimal(str(float(value)))
            tick = _tick_size()
            if tick == 0:
                return float(value)
            scaled = v / tick
            if rounding == "floor":
                q = scaled.to_integral_value(rounding=ROUND_FLOOR) * tick
            else:
                q = scaled.to_integral_value(rounding=ROUND_CEILING) * tick
            return float(q)

        px = _round_px(float(limit_price))
        px = _quantize_to_tick(px, rounding=("ceil" if is_buy else "floor"))

        result = self.exchange.order(coin, is_buy, sz, px, {"limit": {"tif": "Gtc"}})

        if isinstance(result, dict) and result.get("status") == "ok":
            statuses = (((result.get("response") or {}).get("data") or {}).get("statuses")) if isinstance(result.get("response"), dict) else None
            if isinstance(statuses, list) and statuses:
                first = statuses[0]
                if isinstance(first, dict) and first.get("error"):
                    raise RuntimeError(f"Hyperliquid entry order rejected: {str(first.get('error'))[:500]}")

        resting_oid = None
        try:
            statuses = (((result.get("response") or {}).get("data") or {}).get("statuses")) if isinstance(result, dict) else None
            if isinstance(statuses, list) and statuses:
                st = statuses[0]
                if isinstance(st, dict) and isinstance(st.get("resting"), dict):
                    resting_oid = st["resting"].get("oid")
        except Exception:
            resting_oid = None

        return {
            "order_id": f"hl_entry_{idempotency_key or str(uuid.uuid4())[:8]}",
            "status": "resting" if resting_oid is not None else "submitted",
            "symbol": coin,
            "side": side,
            "leverage": leverage,
            "size_usd": float(size_usd),
            "size_coin": float(sz),
            "limit_price": float(px),
            "resting_oid": resting_oid,
            "response": result,
        }

    def place_protection_orders(
        self,
        *,
        side: str,
        size_coin: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        """Place reduce-only TP/SL trigger orders for an existing position."""
        if not LIVE_TRADING:
            return {"status": "dry_run", "note": "protection orders skipped in dry-run"}
        if self.exchange is None or self.info is None:
            raise RuntimeError("Hyperliquid exchange client not initialized.")

        coin = MARKET_SYMBOL
        is_buy = side.lower() == "buy"

        # Use the same tick-safe rounding as in place_order.
        max_decimals = 6
        sz_decimals_map = {}
        try:
            meta = self.info.meta()
            for asset_info in (meta.get("universe", []) if isinstance(meta, dict) else []):
                if isinstance(asset_info, dict) and "name" in asset_info and "szDecimals" in asset_info:
                    sz_decimals_map[str(asset_info["name"])] = int(asset_info["szDecimals"])
        except Exception:
            sz_decimals_map = {}

        def _px_decimals() -> int:
            return max(0, max_decimals - int(sz_decimals_map.get(coin, 0)))

        def _tick_size() -> Decimal:
            return Decimal(1).scaleb(-_px_decimals())

        def _round_px(value: float) -> float:
            px_val = float(value)
            if px_val > 100_000:
                return float(round(px_val))
            return round(float(f"{px_val:.5g}"), _px_decimals())

        def _quantize_to_tick(value: float, *, rounding: str) -> float:
            v = Decimal(str(float(value)))
            tick = _tick_size()
            if tick == 0:
                return float(value)
            scaled = v / tick
            if rounding == "floor":
                q = scaled.to_integral_value(rounding=ROUND_FLOOR) * tick
            else:
                q = scaled.to_integral_value(rounding=ROUND_CEILING) * tick
            return float(q)

        sl_px = _quantize_to_tick(_round_px(float(stop_loss)), rounding=("floor" if is_buy else "ceil"))
        tp_px = _quantize_to_tick(_round_px(float(take_profit)), rounding=("ceil" if is_buy else "floor"))

        orders = [
            {
                "coin": coin,
                "is_buy": (not is_buy),
                "sz": float(size_coin),
                "limit_px": float(sl_px),
                "order_type": {"trigger": {"triggerPx": float(sl_px), "isMarket": True, "tpsl": "sl"}},
                "reduce_only": True,
            },
            {
                "coin": coin,
                "is_buy": (not is_buy),
                "sz": float(size_coin),
                "limit_px": float(tp_px),
                "order_type": {"trigger": {"triggerPx": float(tp_px), "isMarket": True, "tpsl": "tp"}},
                "reduce_only": True,
            },
        ]
        result = self.exchange.bulk_orders(orders, grouping="normalTpsl")
        if isinstance(result, dict) and result.get("status") == "ok":
            statuses = (((result.get("response") or {}).get("data") or {}).get("statuses")) if isinstance(result.get("response"), dict) else None
            if isinstance(statuses, list):
                errors = []
                for st in statuses:
                    if isinstance(st, dict) and st.get("error"):
                        errors.append(str(st.get("error")))
                if errors:
                    raise RuntimeError(f"Hyperliquid protection orders rejected: {'; '.join(errors)[:500]}")
        return {"status": "ok", "response": result, "stop_loss": float(sl_px), "take_profit": float(tp_px)}

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

    def cancel_order(self, *, coin: str, oid: int) -> dict:
        if not LIVE_TRADING:
            return {"status": "dry_run", "coin": coin, "oid": oid}
        if self.exchange is None:
            raise RuntimeError("Hyperliquid exchange client not initialized.")
        return self.exchange.cancel(coin, oid)


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
        self.last_trade_closed_at_ts = 0  # unix seconds
        self.last_order_submit_at_ts = 0  # unix seconds (prevents duplicate submits)
        self.pending_entry = None  # {created_at_ts, side, size_usd, limit_price, resting_oid, stop_loss, take_profit, size_coin?}
        self.protection_placed_for_entry_id = ""  # idempotency marker for protections after limit fill

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
        self.pending_entry = state.get("pending_entry")
        self.protection_placed_for_entry_id = str(state.get("protection_placed_for_entry_id", "") or "")
        try:
            self.last_trade_closed_at_ts = int(state.get("last_trade_closed_at_ts", 0) or 0)
        except Exception:
            self.last_trade_closed_at_ts = 0
        try:
            self.last_order_submit_at_ts = int(state.get("last_order_submit_at_ts", 0) or 0)
        except Exception:
            self.last_order_submit_at_ts = 0
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
            "last_trade_closed_at_ts": int(self.last_trade_closed_at_ts),
            "last_order_submit_at_ts": int(self.last_order_submit_at_ts),
            "pending_entry": self.pending_entry,
            "protection_placed_for_entry_id": self.protection_placed_for_entry_id,
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
        # Start the post-trade cooldown window.
        self.last_trade_closed_at_ts = int(time.time())
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

        # If the container restarted or local state is stale, reconcile against live exchange state
        # to avoid placing duplicate entry+TP/SL bundles.
        if not self.active_position:
            try:
                positions = self.client.get_positions()
                if positions.get("positions"):
                    self.active_position = positions["positions"][0]
                    self._save_state()
            except Exception:
                pass

        if self.active_position:
            logger.info("Active position already open, checking for close conditions")
            self.monitor_position()
            return

        if self.pending_entry:
            logger.info("Pending entry order exists, checking fill/timeout")
            self.monitor_pending_entry()
            return

        if classification == "FLAT":
            logger.info("Market state is FLAT, observation only")
            return

        red_day = context.get("red_day", False)
        if red_day:
            logger.info("Red Day Gate active, skipping new positions")
            return

        # Cooldown after a completed trade (defaults to 1 hour).
        post_trade_cooldown_seconds = int(os.getenv("POST_TRADE_COOLDOWN_SECONDS", "3600"))
        now_ts = int(time.time())
        if self.last_trade_closed_at_ts and post_trade_cooldown_seconds > 0:
            remaining = (self.last_trade_closed_at_ts + post_trade_cooldown_seconds) - now_ts
            if remaining > 0:
                logger.info("Post-trade cooldown active (%ss remaining), skipping new entry", remaining)
                return

        # Short anti-duplicate guard: if we recently attempted to submit an order bundle,
        # don't immediately submit again (Hyperliquid positions can take a moment to reflect).
        submit_cooldown_seconds = int(os.getenv("ORDER_SUBMIT_COOLDOWN_SECONDS", "120"))
        if self.last_order_submit_at_ts and submit_cooldown_seconds > 0:
            remaining = (self.last_order_submit_at_ts + submit_cooldown_seconds) - now_ts
            if remaining > 0:
                logger.info("Order submit cooldown active (%ss remaining), skipping duplicate submit", remaining)
                return

        last_price = float(df["close"].iloc[-1])
        # Get dynamic TP/SL from AI recommendation
        tp_sl = context.get("tp_sl_recommendation", {}) or {}
        tp_percent = float(tp_sl.get("take_profit_percentage", DEFAULT_TAKE_PROFIT_PCT) or DEFAULT_TAKE_PROFIT_PCT)
        sl_percent = float(tp_sl.get("stop_loss_percentage", DEFAULT_STOP_LOSS_PCT) or DEFAULT_STOP_LOSS_PCT)
        ai_entry_offset_pct = float(tp_sl.get("entry_limit_offset_pct", 0.0) or 0.0)
        sl_percent = max(0.01, min(5.0, sl_percent))
        tp_percent = max(0.01, min(10.0, tp_percent))
        ai_entry_offset_pct = max(0.0, min(1.0, ai_entry_offset_pct))

        stop_distance = self.calculate_stop_distance(df, sl_percent=sl_percent)
        position_size = self.risk_engine.position_size(score, stop_distance, last_price)
        position_size = min(position_size, CAPITAL_USD * MAX_NOTIONAL_PCT)
        if position_size <= 0:
            logger.info("Calculated position size is zero, skipping trade")
            return

        # Stop loss: place at the nearest recent swing low/high (pivot) by default,
        # falling back to ATR/% distance if no pivot is found.
        use_nearest_pivot_stop = os.getenv("STOP_USE_NEAREST_PIVOT", "true").strip().lower() in {"1", "true", "yes", "y", "on"}
        pivot_lookback = int(os.getenv("STOP_PIVOT_LOOKBACK_CANDLES", "50"))
        pivot_buffer_pct = float(os.getenv("STOP_PIVOT_BUFFER_PCT", "0.00"))

        stop_loss_val = None
        if use_nearest_pivot_stop and {"low", "high"}.issubset(set(df.columns)) and len(df) >= 3:
            lb = max(3, min(len(df), pivot_lookback))
            window = df.tail(lb).reset_index(drop=True)
            try:
                if classification == "LONG":
                    # Find the most recent pivot low below current price.
                    lows = [float(x) for x in window["low"].tolist()]
                    for i in range(len(lows) - 2, 0, -1):
                        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1] and lows[i] < last_price:
                            stop_loss_val = lows[i] * (1 - pivot_buffer_pct / 100.0)
                            break
                    # Fallback: nearest (most recent) low below price.
                    if stop_loss_val is None:
                        for i in range(len(lows) - 1, -1, -1):
                            if lows[i] < last_price:
                                stop_loss_val = lows[i] * (1 - pivot_buffer_pct / 100.0)
                                break
                else:
                    highs = [float(x) for x in window["high"].tolist()]
                    for i in range(len(highs) - 2, 0, -1):
                        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1] and highs[i] > last_price:
                            stop_loss_val = highs[i] * (1 + pivot_buffer_pct / 100.0)
                            break
                    if stop_loss_val is None:
                        for i in range(len(highs) - 1, -1, -1):
                            if highs[i] > last_price:
                                stop_loss_val = highs[i] * (1 + pivot_buffer_pct / 100.0)
                                break
            except Exception:
                stop_loss_val = None

        if stop_loss_val is None:
            stop_loss_val = last_price - stop_distance if classification == "LONG" else last_price + stop_distance

        stop_loss = round(float(stop_loss_val), 2)
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
        self.last_order_submit_at_ts = int(time.time())
        self._save_state()
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
        entry_mode = os.getenv("ENTRY_ORDER_MODE", "immediate").strip().lower()
        if entry_mode == "limit_wait":
            use_ai_offset = os.getenv("ENTRY_USE_AI_OFFSET", "true").strip().lower() in {"1", "true", "yes", "y", "on"}
            offset_pct_env = float(os.getenv("ENTRY_LIMIT_OFFSET_PCT", "0.00"))
            offset_pct = ai_entry_offset_pct if use_ai_offset else offset_pct_env
            # Bound safety
            offset_pct = max(0.0, min(1.0, float(offset_pct)))
            limit_px = last_price * (1 - offset_pct / 100.0) if side == "buy" else last_price * (1 + offset_pct / 100.0)
            entry = self.client.place_entry_limit(
                side=side,
                size_usd=position_size,
                limit_price=float(limit_px),
                leverage=leverage,
                idempotency_key=idempotency_key,
            )
            self.pending_entry = {
                "id": idempotency_key,
                "created_at_ts": int(time.time()),
                "side": side,
                "size_usd": float(position_size),
                "limit_price": float(entry.get("limit_price", limit_px)),
                "resting_oid": entry.get("resting_oid"),
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "size_coin": float(entry.get("size_coin", 0.0) or 0.0),
            }
            self._save_state()
            logger.info("Placed resting entry: %s", entry)
            return

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
            # If we thought we had a position, treat this as a closure event and start cooldown.
            if self.active_position:
                self.last_trade_closed_at_ts = int(time.time())
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

    def monitor_pending_entry(self) -> None:
        pending = self.pending_entry or {}
        created_at = int(pending.get("created_at_ts", 0) or 0)
        entry_id = str(pending.get("id", "") or "")
        now_ts = int(time.time())
        wait_seconds = int(os.getenv("ENTRY_WAIT_SECONDS", "3600"))

        # If position is open, attach protections once.
        try:
            positions = self.client.get_positions()
            if positions.get("positions"):
                latest = positions["positions"][0]
                self.active_position = latest
                self.pending_entry = None
                self._save_state()

                if entry_id and self.protection_placed_for_entry_id != entry_id:
                    # Use position size from exchange if available; fallback to pending size_coin.
                    size_coin = float(latest.get("size", 0) or 0)
                    if size_coin == 0:
                        size_coin = float(pending.get("size_coin", 0) or 0)
                    if size_coin != 0:
                        prot = self.client.place_protection_orders(
                            side=str(pending.get("side", "buy") or "buy"),
                            size_coin=abs(size_coin),
                            stop_loss=float(pending.get("stop_loss")),
                            take_profit=float(pending.get("take_profit")),
                        )
                        self.protection_placed_for_entry_id = entry_id
                        self._save_state()
                        logger.info("Placed TP/SL after entry fill: %s", prot)
                return
        except Exception as e:
            logger.warning("Pending entry check failed: %s", str(e))

        # Timeout: cancel resting order if we have an oid.
        if created_at and wait_seconds > 0 and (now_ts - created_at) > wait_seconds:
            oid = pending.get("resting_oid")
            if oid is not None:
                try:
                    cancel_resp = self.client.cancel_order(coin=MARKET_SYMBOL, oid=int(oid))
                    logger.info("Cancelled stale entry order oid=%s: %s", oid, cancel_resp)
                except Exception as e:
                    logger.warning("Failed to cancel stale entry oid=%s: %s", oid, str(e))
            self.pending_entry = None
            self._save_state()
            logger.info("Entry wait timeout reached; cleared pending entry")

    def run(self, interval_seconds: int = 60):
        logger.info("Starting trade loop for %s", MARKET_SYMBOL)
        while True:
            try:
                # When a position is open, do NOT re-evaluate constantly. We only poll for
                # TP/SL closure at a slower cadence (default: hourly).
                if self.active_position:
                    self.monitor_position()
                elif self.pending_entry:
                    self.monitor_pending_entry()
                else:
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

            # Adaptive sleep:
            # - If a position is open: check for TP/SL closure hourly.
            # - If we're in post-trade cooldown: sleep until it expires (capped).
            # - Otherwise: use the default evaluation cadence.
            now_ts = int(time.time())
            active_check_seconds = int(os.getenv("ACTIVE_POSITION_CHECK_SECONDS", "3600"))
            post_trade_cooldown_seconds = int(os.getenv("POST_TRADE_COOLDOWN_SECONDS", "3600"))
            pending_entry_check_seconds = int(os.getenv("ENTRY_CHECK_SECONDS", "60"))

            if self.active_position:
                sleep_for = max(1, active_check_seconds)
            elif self.pending_entry:
                sleep_for = max(1, pending_entry_check_seconds)
            elif self.last_trade_closed_at_ts and post_trade_cooldown_seconds > 0:
                remaining = (self.last_trade_closed_at_ts + post_trade_cooldown_seconds) - now_ts
                sleep_for = max(1, min(remaining, post_trade_cooldown_seconds)) if remaining > 0 else interval_seconds
            else:
                sleep_for = interval_seconds

            time.sleep(int(sleep_for))
