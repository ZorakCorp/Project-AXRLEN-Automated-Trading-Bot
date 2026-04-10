#!/usr/bin/env python3
"""
Test script for dynamic TP/SL implementation
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from gemini_client import GeminiClient
from raw_data_engine import RawDataEngine
from trading_bot import TradingBot
from config import MARKET_SYMBOL, CAPITAL_USD

def test_dynamic_tp_sl():
    """Test the dynamic TP/SL functionality"""
    print("Testing dynamic TP/SL implementation...")

    # Initialize components
    gemini = GeminiClient()
    data_engine = RawDataEngine()
    bot = TradingBot()

    # Build context (this should include tp_sl_recommendation)
    print("Building context...")
    context = data_engine.build_context()
    print(f"Context keys: {list(context.keys())}")

    if 'tp_sl_recommendation' not in context:
        print("ERROR: tp_sl_recommendation not found in context!")
        return False

    tp_sl = context['tp_sl_recommendation']
    print(f"Dynamic TP/SL: {tp_sl}")

    # Test trade execution with dynamic levels
    print("Testing trade execution with dynamic TP/SL...")

    # Simulate a buy signal
    signal = {
        'direction': 'buy',
        'confidence': 0.8,
        'price': 85.50,
        'timestamp': '2024-01-15T10:00:00Z'
    }

    try:
        # This should use the dynamic TP/SL from context
        result = bot.execute_trade(signal, context)
        print(f"Trade execution result: {result}")
        return True
    except Exception as e:
        print(f"ERROR in trade execution: {e}")
        return False

if __name__ == "__main__":
    success = test_dynamic_tp_sl()
    if success:
        print("✅ Dynamic TP/SL test passed!")
    else:
        print("❌ Dynamic TP/SL test failed!")