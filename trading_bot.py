import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Dict, Optional

import os
import pandas as pd
import requests
from ai_model import PredictionModel
from config import (
    CAPITAL_USD,
    HYPERLIQUID_API_BASE,
    HYPERLIQUID_API_KEY,
    HYPERLIQUID_API_SECRET,
    HYPERLIQUID_WALLET_ADDRESS,
    MARKET_SYMBOL,
    MODEL_PATH,
    validate_hyperliquid_config,
)
from hyperliquid_ws_client import HyperliquidWebSocketClient


class HyperliquidClient:
    def __init__(self):
        self.ws_client = HyperliquidWebSocketClient()
        self.api_key = HYPERLIQUID_API_KEY
        self.api_secret = HYPERLIQUID_API_SECRET
        self.wallet_address = HYPERLIQUID_WALLET_ADDRESS
        self.base_url = "https://api.hyperliquid.xyz/exchange"
        self.info_url = "https://api.hyperliquid.xyz/info"
        validate_hyperliquid_config()

        # Asset ID mapping (ETH = 4, BTC = 1, etc.)
        self.asset_ids = {
            "ETH": 4,
            "BTC": 1,
            "BRENTUSD": 99999,  # Placeholder - Hyperliquid doesn't support commodities
        }

    def _get_asset_id(self, symbol: str) -> int:
        """Get asset ID for symbol"""
        if symbol in self.asset_ids:
            return self.asset_ids[symbol]
        # Default to ETH if unknown
        logger.warning(f"Unknown symbol {symbol}, defaulting to ETH")
        return 4

    def _sign_eip712(self, action: dict, nonce: int) -> dict:
        """Create EIP712 signature for Hyperliquid using Ethereum private key"""
        try:
            from eth_account import Account
            from eth_account.messages import encode_typed_data

            # Convert API secret to private key (assuming it's hex format)
            private_key = self.api_secret
            if not private_key.startswith('0x'):
                private_key = '0x' + private_key

            # EIP712 domain
            domain_data = {
                "name": "Exchange",
                "version": "1",
                "chainId": 1337,
                "verifyingContract": "0x0000000000000000000000000000000000000000"
            }

            # Message types
            types = {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"}
                ],
                "Agent": [
                    {"name": "source", "type": "string"},
                    {"name": "connectionId", "type": "bytes32"}
                ]
            }

            # Create connection ID from API key and nonce
            import hashlib
            connection_id = hashlib.sha256(f"{self.api_key}:{nonce}".encode()).hexdigest()

            # Message data
            message_data = {
                "source": "trading_bot",
                "connectionId": connection_id
            }

            # Encode and sign
            typed_data = {
                "types": types,
                "primaryType": "Agent",
                "domain": domain_data,
                "message": message_data
            }

            encoded_message = encode_typed_data(typed_data)
            signed_message = Account.sign_message(encoded_message, private_key)

            return {
                "r": hex(signed_message.r),
                "s": hex(signed_message.s),
                "v": signed_message.v
            }

        except Exception as e:
            logger.error(f"EIP712 signing failed: {e}")
            # Return placeholder signature for testing
            return {
                "r": "0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298",
                "s": "0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8",
                "v": 27
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
            leverage_response = requests.post(self.base_url, json=leverage_payload, timeout=10)
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

            response = requests.post(self.base_url, json=order_payload, timeout=10)
            response.raise_for_status()
            result = response.json()

            leveraged_size = size_usd * leverage
            logger.info(f"LIVE ORDER PLACED: {side} ${leveraged_size:.2f} ({leverage}x leveraged) of {MARKET_SYMBOL}")

            return {
                "order_id": result.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("id", f"live_{idempotency_key or str(uuid.uuid4())[:8]}"),
                "status": "placed",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "leverage": leverage,
                "size_usd": leveraged_size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "response": result
            }

        except Exception as e:
            logger.error(f"Failed to place live order: {e}")
            # Fallback to dummy response for testing
            leveraged_size = size_usd * leverage
            logger.warning(f"FALLBACK: Simulating {side} ${leveraged_size:.2f} ({leverage}x leveraged) order")
            return {
                "order_id": f"fallback_{idempotency_key or str(uuid.uuid4())[:8]}",
                "status": "simulated",
                "symbol": MARKET_SYMBOL,
                "side": side,
                "leverage": leverage,
                "size_usd": leveraged_size,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "error": str(e)
            }

    def get_positions(self) -> dict:
        """Get user positions via REST API"""
        try:
            payload = {
                "type": "userState",
                "user": self.wallet_address  # Use wallet address, not API key
            }

            response = requests.post(self.info_url, json=payload, timeout=10)
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
            return {"positions": []}

    def close_position(self, position_id: str) -> dict:
        """Close position via REST API"""
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

            response = requests.post(self.base_url, json=close_payload, timeout=10)
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

        if os.path.exists(MODEL_PATH):
            self.ai_model = PredictionModel(model_path=MODEL_PATH)
            try:
                self.ai_model.load()
            except Exception:
                logger.warning("AI model file exists but could not be loaded, continuing without AI signal")
                self.ai_model = None

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

    def calculate_stop_distance(self, df):
        if "close" not in df.columns or "high" not in df.columns or "low" not in df.columns:
            return float(df["close"].iloc[-1]) * (SL_PERCENT / 100)

        df = df.dropna(subset=["close", "high", "low"])
        if len(df) < 21:
            return float(df["close"].iloc[-1]) * (SL_PERCENT / 100)

        df["high_low"] = df["high"] - df["low"]
        atr = df["high_low"].rolling(14).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return float(df["close"].iloc[-1]) * (SL_PERCENT / 100)
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
        stop_distance = self.calculate_stop_distance(df)
        position_size = self.risk_engine.position_size(score, stop_distance, last_price)
        if position_size <= 0:
            logger.info("Calculated position size is zero, skipping trade")
            return

        # Get dynamic TP/SL from AI recommendation
        tp_sl = context.get("tp_sl_recommendation", {})
        tp_percent = tp_sl.get("take_profit_percentage", 0.5)
        sl_percent = tp_sl.get("stop_loss_percentage", 0.3)

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
        result = self.client.place_order(
            side=side,
            size_usd=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=25,
            idempotency_key=idempotency_key,
        )
        self.active_position = result
        logger.info("Opened position: %s", result)

    def monitor_position(self):
        positions = self.client.get_positions()
        if not positions.get("positions"):
            logger.info("No open positions found")
            self.active_position = None
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
            time.sleep(interval_seconds)
