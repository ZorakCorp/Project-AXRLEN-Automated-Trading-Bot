import websocket
import json
import threading
import time
import logging
from typing import Dict, List, Optional, Any
import os
from config import (
    HYPERLIQUID_API_KEY,
    HYPERLIQUID_API_SECRET,
    MARKET_SYMBOL,
    validate_hyperliquid_config,
)

logger = logging.getLogger(__name__)

class HyperliquidWebSocketClient:
    """WebSocket client for Hyperliquid live trading"""

    def __init__(self):
        validate_hyperliquid_config()
        self.api_key = HYPERLIQUID_API_KEY
        self.api_secret = HYPERLIQUID_API_SECRET
        self.symbol = MARKET_SYMBOL
        self.ws_url = "wss://api.hyperliquid.xyz/ws"
        self.ws = None
        self.connected = False
        self.message_id = 1

    def connect(self):
        """Connect to Hyperliquid WebSocket"""
        try:
            self.ws = websocket.create_connection(self.ws_url, timeout=10)
            self.connected = True
            logger.info("Connected to Hyperliquid WebSocket")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Hyperliquid: {e}")
            return False

    def disconnect(self):
        """Disconnect from WebSocket"""
        if self.ws:
            self.ws.close()
            self.connected = False

    def send_message(self, message: Dict) -> Dict:
        """Send message and wait for response"""
        if not self.connected:
            if not self.connect():
                raise Exception("Not connected to Hyperliquid")

        try:
            # Add message ID
            message['id'] = self.message_id
            self.message_id += 1

            self.ws.send(json.dumps(message))
            response = self.ws.recv()
            return json.loads(response)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            raise

    def place_order(self, side: str, size_usd: float, leverage: int = 25,
                   stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Dict:
        """Place a live order on Hyperliquid"""

        # TODO: Find the correct message format for Hyperliquid orders
        # This is a placeholder - need correct format

        message = {
            "type": "order",  # May be different
            "symbol": self.symbol,
            "side": side.upper(),
            "size": size_usd,
            "leverage": leverage,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "api_key": self.api_key,
            # Add signature if required
        }

        logger.info(f"Placing LIVE {leverage}x leveraged {side} order: ${size_usd} of {self.symbol}")
        response = self.send_message(message)

        if "error" in response:
            raise Exception(f"Order failed: {response['error']}")

        return response

    def get_positions(self) -> List[Dict]:
        """Get current positions"""
        message = {
            "type": "positions",  # May be different
            "api_key": self.api_key
        }

        response = self.send_message(message)
        return response.get("positions", [])

    def close_position(self, symbol: str = None) -> Dict:
        """Close position"""
        symbol = symbol or self.symbol

        message = {
            "type": "close_position",  # May be different
            "symbol": symbol,
            "api_key": self.api_key
        }

        response = self.send_message(message)
        return response

    def get_ticker(self, symbol: str = None) -> Dict:
        """Get ticker data"""
        symbol = symbol or self.symbol

        message = {
            "type": "ticker",  # May be different
            "symbol": symbol
        }

        response = self.send_message(message)
        return response