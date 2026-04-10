import os
import logging
from typing import Dict, List, Optional, Any
from oandapyV20 import API
from oandapyV20.exceptions import V20Error
from oandapyV20.endpoints.pricing import PricingStream
from oandapyV20.endpoints.orders import OrderCreate
from oandapyV20.endpoints.positions import OpenPositions
from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.endpoints.instruments import InstrumentsCandles
import oandapyV20.endpoints.positions as positions
import pandas as pd
from datetime import datetime, timedelta
from config import (
    OANDA_API_KEY,
    OANDA_ACCOUNT_ID,
    OANDA_ENVIRONMENT,
    OANDA_INSTRUMENT,
    validate_oanda_config,
)

logger = logging.getLogger(__name__)

class OandaClient:
    def __init__(self):
        # For testing without real API keys, use dummy mode
        self.api_key = OANDA_API_KEY
        self.account_id = OANDA_ACCOUNT_ID
        self.environment = OANDA_ENVIRONMENT
        self.instrument = OANDA_INSTRUMENT

        if self.api_key == "your_oanda_api_key_here" or not self.api_key:
            logger.warning("OANDA API key not configured. Using dummy data mode.")
            self.dummy_mode = True
        else:
            self.dummy_mode = False
            validate_oanda_config()
            self.api = API(access_token=self.api_key, environment=self.environment)

    def get_account_summary(self) -> Dict:
        """Get account balance and summary"""
        if self.dummy_mode:
            return {
                "account": {
                    "balance": "100000.00",
                    "marginAvailable": "90000.00",
                    "marginUsed": "10000.00"
                }
            }

        try:
            r = AccountSummary(accountID=self.account_id)
            response = self.api.request(r)
            return response
        except V20Error as e:
            logger.error(f"OANDA API error: {e}")
            raise

    def fetch_history(self, symbol: str = None, limit: int = 300) -> Dict:
        """Fetch historical candle data"""
        if self.dummy_mode:
            # Return dummy data for testing
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

        instrument = symbol or self.instrument

        # Calculate start time (limit * 1 minute ago)
        start_time = (datetime.utcnow() - timedelta(minutes=limit)).isoformat() + "Z"

        params = {
            "count": limit,
            "granularity": "M1",  # 1-minute candles
            "from": start_time
        }

        try:
            r = InstrumentsCandles(instrument=instrument, params=params)
            response = self.api.request(r)

            # Convert to format expected by the bot
            candles = []
            for candle in response.get('candles', []):
                if candle['complete']:  # Only complete candles
                    candles.append({
                        'timestamp': int(datetime.fromisoformat(candle['time'].replace('Z', '+00:00')).timestamp() * 1000),
                        'open': float(candle['mid']['o']),
                        'high': float(candle['mid']['h']),
                        'low': float(candle['mid']['l']),
                        'close': float(candle['mid']['c']),
                        'volume': int(candle['volume'])
                    })

            return {'candles': candles}

        except V20Error as e:
            logger.error(f"Failed to fetch candles: {e}")
            raise

    def place_order(self, side: str, size: float, price: Optional[float] = None,
                   take_profit: Optional[float] = None, stop_loss: Optional[float] = None) -> Dict:
        """Place a market or limit order"""
        if self.dummy_mode:
            logger.info(f"DUMMY ORDER: {side} {size} units of {self.instrument}, TP: {take_profit}, SL: {stop_loss}")
            return {
                "orderCreateTransaction": {
                    "id": "dummy_order_id",
                    "instrument": self.instrument,
                    "units": str(size) if side.upper() == "BUY" else str(-size),
                    "type": "MARKET"
                }
            }

        instrument = self.instrument

        # Convert side to OANDA format
        oanda_side = "BUY" if side.upper() == "LONG" else "SELL"

        order_data = {
            "order": {
                "instrument": instrument,
                "units": str(int(size)) if oanda_side == "BUY" else str(-int(size)),
                "type": "MARKET",
                "positionFill": "DEFAULT"
            }
        }

        # Add take profit and stop loss if provided
        if take_profit or stop_loss:
            order_data["order"]["takeProfitOnFill"] = {
                "price": str(take_profit) if take_profit else None
            }
            order_data["order"]["stopLossOnFill"] = {
                "price": str(stop_loss) if stop_loss else None
            }

        try:
            r = OrderCreate(accountID=self.account_id, data=order_data)
            response = self.api.request(r)
            return response
        except V20Error as e:
            logger.error(f"Failed to place order: {e}")
            raise

    def get_open_positions(self) -> List[Dict]:
        """Get current open positions"""
        if self.dummy_mode:
            return []  # No open positions in dummy mode

        try:
            r = OpenPositions(accountID=self.account_id)
            response = self.api.request(r)
            return response.get('positions', [])
        except V20Error as e:
            logger.error(f"Failed to get positions: {e}")
            raise

    def close_position(self, instrument: str = None) -> Dict:
        """Close all positions for an instrument"""
        if self.dummy_mode:
            logger.info(f"DUMMY CLOSE: Closing position for {instrument or self.instrument}")
            return {"dummy": "position_closed"}

        instrument = instrument or self.instrument

        try:
            r = positions.PositionClose(accountID=self.account_id, instrument=instrument)
            response = self.api.request(r)
            return response
        except V20Error as e:
            logger.error(f"Failed to close position: {e}")
            raise

    def get_current_price(self, instrument: str = None) -> Dict:
        """Get current market price"""
        instrument = instrument or self.instrument

        try:
            params = {"instruments": instrument}
            r = PricingStream(accountID=self.account_id, params=params)
            # For streaming, we'd need to handle the stream
            # For now, get a snapshot
            response = self.api.request(r)
            return response
        except V20Error as e:
            logger.error(f"Failed to get price: {e}")
            raise