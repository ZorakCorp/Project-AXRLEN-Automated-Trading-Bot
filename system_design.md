# AXRLEN-TRADING System Design

This document captures the layered architecture of the bot as described by the "brains" concept.

## Core Insight

The system is not a standard price-reactive algorithmic trading bot. It is a layered prediction engine where astrological timing is the primary framework and every other signal layer confirms, weights, and shapes the prediction.

## Layers

1. Raw Data Ingestion
   - Brent price feeds
   - EIA inventory and supply data
   - NLP on OPEC and geopolitical news
   - Dark pool and institutional flow
   - AIS shipping route telemetry
   - Social sentiment on energy keywords

2. Vedic Temporal Grid
   - Macro timing: monthly Jupiter/Saturn bias, Samasaptaka, Rahu/Ketu activations
   - Swing timing: Sun/Mars transits, lunar Tithi, New/Full Moon staging windows
   - Day trade timing: Moon Nakshatra, Hora windows, Vedha and retrograde logic
   - Gemini is used for macro bias statement synthesis from calculated ephemeris answers

3. Brent Oil Vedha Matrix
   - Commodity-specific signals for oil based on sign affinity and planetary formations
   - Bull signals: Mars in Scorpio/Aries with Rahu, Saturn in Dahana Nadi, Jupiter retrograde in watery signs
   - Bear signals: Saturn Vedha on Cancer/Scorpio, Ketu affliction, malefic Watery triangle

4. World Leader Temporal Engine
   - Mahadasha/Antar/Pratyaantar Dasha mapping for key oil leaders
   - Aggressive/protective tendencies ahead of policy shifts
   - 72-96 hour advance window for regime-driven supply decisions
   - Gemini interprets leader Dasha context into probability-weighted supply shock signals

5. Technical Confirmation
   - EMA stack (9, 21, 50)
   - RSI, MACD divergence
   - ATR for volatility and stop placement
   - OBV, VWAP for volume confirmation
   - Granger causality validation of signal leading behavior

6. NEXUS-PRIME Probability Engine
   - Weighted aggregate signal score
   - Domain weights: Sarvatobhadra Vedha 40%, dark pool 25%, retrograde 15%, sentiment 10%, historical 10%
   - Temporal multipliers for eclipses, retrogrades, dasha transitions

7. Signal Classification
   - Longer-term directional state: Long, Flat, Short
   - Score thresholds determine posture and position sizing

8. Risk Management Engine
   - Kelly-based position sizing with 2% capital cap
   - ATR-based hard stops
   - Red Day and double restriction gating via Tithi and Nakshatra
   - Daily and weekly drawdown circuit breakers

9. Execution Engine
   - Idempotent, limit-order-first execution
   - Entry gates require Hora + macro bias + restricted-day checks
   - Venus Hora scaling out, Saturn Hora exits

10. Feedback and Calibration Loop
    - Monthly performance review and Bayesian weight updates
    - Granger causality update to refine signal lag mapping
    - Trade logging by astrological conditions and outcome
    - Gemini produces diagnostic weight adjustment recommendations from the calibration report

## Current Code Status

- `raw_data_engine.py` provides a Layer 0 raw ingestion interface for future price, supply, news, and flow feeds.
- `signal_engine.py` now encodes Layers 1-6 with astro timing, Vedha matrix, leadership dasha, technical confirmation, dark pool, sentiment, and historical signal domains.
- `trading_bot.py` now uses `signal_engine.py` output in the execution path and handles stop-based position sizing.
- `main.py` now runs the layered probability engine rather than only the placeholder AI model for live execution.

## Next Implementation Steps

1. Build the astrological timing engine and retrograde Vedha logic.
2. Add a Mahadasha engine and world leader schedule database.
3. Implement Dark Pool, sentiment, and technical confirmation feeds.
4. Connect the `signal_engine` score output to the trade execution path.
5. Add monthly calibration, Granger causality tests, and logging.
