## AXRLEN-TRADING

Automated trading bot skeleton (Hyperliquid + Gemini) with safety guardrails.

### Overview

This repository is a Python trading bot framework that combines:

- a layered “signal engine” that outputs `LONG/SHORT/FLAT`
- deterministic risk sizing
- an exchange execution adapter (currently **placeholder** for Hyperliquid signing/order formats)
- Gemini as an intelligence layer that returns **structured JSON**

### Safety defaults (important)

- **Dry-run by default**: `LIVE_TRADING=false` means the bot never places real orders.
- **No fake-success**: if live order placement fails, the bot raises instead of silently “simulating success”.
- **Symbol validation**: live trading refuses unsupported placeholder symbols (e.g. `BRENTUSD`).
- **Leverage cap**: `MAX_LEVERAGE` limits requested leverage.
- **Notional cap**: `MAX_NOTIONAL_PCT` caps position notional vs capital.

### Setup

1) Copy `.env.example` to `.env` and fill in keys.

2) Install:

```bash
python -m pip install -r requirements.txt
```

3) Run (dry-run):

```bash
python main.py run
```

### Configuration (env)

Core:

- `MARKET_SYMBOL` (recommended: `ETH`)
- `CAPITAL_USD`
- `MODEL_PATH`

Safety:

- `LIVE_TRADING` (default `false`)
- `MAX_NOTIONAL_PCT` (default `0.10`)
- `MAX_LEVERAGE` (default `10`)
- `ALLOW_UNPROTECTED_POSITIONS` (default `false`)

### Notes / current limitations

- The Hyperliquid execution code in `trading_bot.py` contains **placeholder signing/order assumptions**. You must update it using Hyperliquid’s official API documentation before enabling `LIVE_TRADING=true`.
- TP/SL are computed, but **protective orders are not guaranteed enforced on-exchange** in this implementation. This is why the live path refuses to trade unless you explicitly set `ALLOW_UNPROTECTED_POSITIONS=true`.

## Overview

This repository contains a Python-based automated trading bot for Brent oil trading on Hyperliquid.

The system uses a layered prediction engine driven by a "hive mind" of intelligence brains. These brains encode:

- Vedic astrological timing and Vedha logic
- Commodity-specific Brent oil astrology and Nadi systems
- Leader Mahadasha geopolitical timing
- AI intelligence via Gemini API
- Sentiment analysis and dark pool flows
- Probability aggregation, risk sizing, and idempotent execution

## Key Features

- **Aggressive Risk Management**: 90% capital allocation per trade with profit compounding
- **Single Position Trading**: Only one active trade at a time
- **Red Day Gates**: Trading halts on astrological Red Days (e.g., full/new moon)
- **Layered Signal Brains**: Astrology, AI, sentiment, leadership, and dark pool signals
- **Calibration Mode**: Analyze trade logs and adjust signal weights
- **24/7 Operation**: Designed for Railway hosting with continuous monitoring

## Setup for Live Trading

### 1. Get Hyperliquid API Access
- Sign up at [Hyperliquid](https://hyperliquid.xyz/)
- Generate API keys from your account settings
- Note your API key and secret

### 2. Get Gemini AI API Key
- Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
- Generate API key for Gemini 1.5 Flash

### 3. Configure Environment
Update your `.env` file with real API credentials:

```bash
# Hyperliquid API Configuration
HYPERLIQUID_API_KEY=your_real_hyperliquid_key
HYPERLIQUID_API_SECRET=your_real_hyperliquid_secret

# Gemini AI API Configuration
GEMINI_API_KEY=your_real_gemini_key

# Trading Configuration
MARKET_SYMBOL=BRENTUSD
CAPITAL_USD=100000
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Test the Bot
```bash
python main.py run
```

## Usage

### Training the AI Model
```bash
python main.py train --csv historical_data.csv
```

### Running the Trading Bot
```bash
python main.py run
```

### Calibration Analysis
```bash
python main.py calibrate
```

## Architecture

### Signal Brains (No Technical Analysis)
- **Astrology Brain**: Vedic planetary positions & Vedha calculations
- **AI Brain**: Gemini API interpretation of market conditions
- **Sentiment Brain**: OPEC news & geopolitical analysis
- **Leadership Brain**: Mahadasha timing for world leaders
- **Dark Pool Brain**: Institutional flow analysis

### Risk Management
- 90% capital allocation per trade
- Kelly Criterion scaling
- Single position at a time
- Red Day trading halts
- Dynamic take profit/stop loss (AI-determined)

## Deployment

The bot is configured for Railway deployment with Docker. Update `railway.toml` and push to GitHub for automatic deployment.

## Important Notes

- **Risk Warning**: This bot uses aggressive 90% capital allocation - use at your own risk
- **API Limits**: Respect rate limits for both Hyperliquid and Gemini APIs
- **Market Hours**: Brent oil futures trade nearly 24/5
- **Test First**: Always test with small amounts before full deployment</content>
<parameter name="filePath">/workspaces/AXRLEN-TRADING/README.md# AXRLEN-TRADING
Automated Brent Oil Prediction Trading Bot for Hyperliquid

## Overview

This repository contains a Python-based automated trading bot for Brent oil trading on Hyperliquid.

The system uses a layered prediction engine driven by a "hive mind" of intelligence brains. These brains encode:

- Vedic astrological timing and Vedha logic
- Commodity-specific Brent oil astrology and Nadi systems
- Leader Mahadasha geopolitical timing
- AI intelligence via Gemini API
- Sentiment analysis and dark pool flows
- Probability aggregation, risk sizing, and idempotent execution

## Key Features

- **Aggressive Risk Management**: 90% capital allocation per trade with profit compounding
- **Single Position Trading**: Only one active trade at a time
- **Red Day Gates**: Trading halts on astrological Red Days (e.g., full/new moon)
- **Layered Signal Brains**: Astrology, AI, sentiment, leadership, and dark pool signals
- **Calibration Mode**: Analyze trade logs and adjust signal weights
- **24/7 Operation**: Designed for Railway hosting with continuous monitoring

## Setup for Live Trading

### 1. Get OANDA API Access
1. Create an account at [OANDA](https://www.oanda.com/)
2. Generate an API token at: https://www.oanda.com/account/tpa/personal_token
3. Note your Account ID from the OANDA dashboard

### 2. Get Gemini AI API Key
1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key for Gemini

### 3. Configure Environment
Update your `.env` file with real API credentials:

```bash
# OANDA API Configuration
OANDA_API_KEY=your_actual_oanda_api_key
OANDA_ACCOUNT_ID=your_actual_account_id
OANDA_ENVIRONMENT=practice  # Change to 'live' for real money trading
OANDA_INSTRUMENT=BC  # Brent Crude

# Gemini AI API Configuration
GEMINI_API_KEY=your_actual_gemini_api_key

# Trading Configuration
CAPITAL_USD=100000  # Your account balance
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Test the Bot
```bash
# Run in practice mode first
python main.py run
```

## Usage

### Training the AI Model
```bash
python main.py train --csv historical_data.csv
```

### Running the Trading Bot
```bash
python main.py run
```

### Calibration Analysis
```bash
python main.py calibrate
```

## Architecture

### Signal Brains (No Technical Analysis)
- **Astrology Brain**: Vedic planetary positions and Vedha calculations
- **AI Brain**: Gemini API interpretation of market conditions
- **Sentiment Brain**: OPEC news and geopolitical analysis
- **Leadership Brain**: Mahadasha timing for world leaders
- **Dark Pool Brain**: Institutional flow analysis

### Risk Management
- 90% capital allocation per trade
- Kelly Criterion scaling
- Single position at a time
- Red Day trading halts
- Dynamic take profit/stop loss (AI-determined)

## Deployment

The bot is configured for Railway deployment with Docker. Update `railway.toml` and push to GitHub for automatic deployment.

## Important Notes

- **Start with Practice Account**: Always test with OANDA's practice environment first
- **Risk Warning**: This bot uses aggressive 90% capital allocation - use at your own risk
- **API Limits**: Respect rate limits for both OANDA and Gemini APIs
- **Market Hours**: Brent oil CFDs trade 24/5, but be aware of liquidity during off-hours
- Layer 9: Feedback/calibration loop in `main.py` (calibrate command)

## Usage

### Training the AI Model
```bash
python main.py train --csv path/to/historical_data.csv
```

### Running the Bot
```bash
python main.py run
```

### Calibration Analysis
```bash
python main.py calibrate
```

## Brain Files

The root of the repository also contains the brain content files. Each file represents a distinct intelligence domain:

- `Aureon Philosphy Counsiouns Brain`
- `Data Analytics Brain`
- `Mahadashas Brain`
- `Vadic Global Brain`
- `Zophiel Trading Brain`
- `Nexus Prime + Occultism Algorithm`
- `Aspects + Congunctions`

These are the conceptual layers that should feed the core signal engine.

## Gemini API Role

Gemini is used as an intelligence layer, not as the trading execution engine. It is called from the bot for:

- News and sentiment classification in Layer 0
- World leader Dasha context interpretation in Layer 3
- Historical pattern scouting via Gemini Flash
- Monthly calibration diagnostics in Layer 9
- Daily macro bias statement synthesis in Layer 5/8

Gemini returns structured JSON for signal weights and human-readable bias statements, while the bot retains all deterministic risk, execution, and Vedha math.

## Setup

1. Copy `.env.example` to `.env` and set your Hyperliquid API credentials.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Train the model using historical candle data:

```bash
python main.py train --csv path/to/brent_historical.csv
```

4. Run the bot:

```bash
python main.py run
```

## Railway Deployment

Railway can run the bot 24/7 using the `Dockerfile` and `railway.toml`.

1. Push this repo to Railway.
2. Set environment variables in Railway from `.env`.
3. Use `python main.py run` as the start command.

## Notes

- The Hyperliquid client in `trading_bot.py` uses placeholder endpoints and signing logic.
- You must verify and update the endpoint URLs and authentication method using Hyperliquid API docs.
- Trading carries risk. Backtest thoroughly before using live capital.
