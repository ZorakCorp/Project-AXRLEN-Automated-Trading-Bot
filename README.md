# AXRLEN-TRADING

Automated trading bot framework (Hyperliquid + OpenAI) with safety-first defaults.

## Attribution

This was developed by `#HouseOfAsher` & Zorak Corp Research & Development team and open-sourced for all of humanity.

## What this repo is

- **Signal engine** that outputs `LONG` / `SHORT` / `FLAT`
- **Risk sizing** with notional caps
- **Execution adapter** for Hyperliquid (uses the official `hyperliquid-python-sdk`)
- **OpenAI integration** for structured signal/context enrichment (JSON-only outputs)

## Safety model (read this)

- **Dry-run by default**: the bot will not place real orders unless `LIVE_TRADING=true`.
- **Live trading is locked**: even if `LIVE_TRADING=true`, the bot refuses to trade unless you explicitly set `HYPERLIQUID_EXECUTION_VERIFIED=true`.
- **No “fake success”**: if a live order fails, the bot raises instead of pretending it executed.
- **Protective orders**: when TP/SL are provided, the bot places reduce-only trigger TP/SL orders on Hyperliquid using the SDK.

## Local setup (optional)

1) Copy `.env.example` to `.env` and fill in values.

2) Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3) Run (dry-run):

```bash
python main.py run
```

## Deploy on Railway (recommended)

Railway is the simplest way to run this bot 24/7 without installing Python locally. This repo includes a `Dockerfile` and `railway.toml`.

### Step 1: Create an OpenAI API key

1) Go to the OpenAI dashboard and create an API key.
2) Copy the key value.

Notes:
- Pricing/credits change over time; check your OpenAI billing dashboard for current rates.
- Treat the key like a password. Don’t commit it to git, don’t paste it into chats.

### Step 2: Create Hyperliquid API credentials

1) Sign in to Hyperliquid: [Hyperliquid](https://hyperliquid.xyz/)
2) In the app, go to **API** settings and create an **API wallet / API key** (Hyperliquid terminology varies by UI version).
3) You will need:
   - your main wallet address (public) as `HYPERLIQUID_WALLET_ADDRESS`
   - the API wallet **private key** as `HYPERLIQUID_API_SECRET`

### Step 2.5: Fund your Hyperliquid account (add money)

Hyperliquid is funded via **onchain deposits**. Do this carefully:

1) In the Hyperliquid web app, open **Deposit** (usually under Portfolio/Wallet).
2) Copy the **deposit address** Hyperliquid shows you.
3) From your exchange (Coinbase/Binance) or self-custody wallet (MetaMask/Rabby), **send funds to that deposit address**.
4) **Use the exact network shown on the Hyperliquid deposit screen** (do not guess). If you use the wrong network, funds can be lost.
5) Start with a **small test deposit**, confirm it arrives, then deposit the full amount.

Notes:
- Depositing funds is separate from creating an API wallet. Your bot will trade against the Hyperliquid account that the UI associates with your `HYPERLIQUID_WALLET_ADDRESS` and API permissions.
- If you fund one wallet but configure the bot to use a different wallet/address, you may see no tradable balance.

### Step 3: Create a Railway project

1) Go to [Railway](https://railway.app/)
2) Create a **New Project**
3) Choose **Deploy from GitHub repo**
4) Select your repo (e.g. `shep95/Aureon_Automated_Trading_Bot`)

Railway will detect the `Dockerfile` and build it automatically.

### Step 4: Add environment variables in Railway

In Railway, open your service → **Variables** → add:

Core:
- `MARKET_SYMBOL=ETH`
- `CAPITAL_USD=100000`

OpenAI:
- `OPENAI_API_KEY=<your key>`
- `OPENAI_API_BASE=https://api.openai.com/v1`
- `OPENAI_API_MODEL=gpt-4.1-mini`

Hyperliquid:
- `HYPERLIQUID_WALLET_ADDRESS=<0x...>`
- `HYPERLIQUID_API_SECRET=<0x... private key>`
- `HYPERLIQUID_API_BASE=https://api.hyperliquid.xyz`

Safety (start safe, then loosen only if you understand the risks):
- `LIVE_TRADING=false`
- `HYPERLIQUID_EXECUTION_VERIFIED=false`
- `MAX_NOTIONAL_PCT=0.10`
- `MAX_LEVERAGE=10`
- `ALLOW_UNPROTECTED_POSITIONS=false`

Execution (optional):
- `ORDER_LEVERAGE=10` (requested order leverage; the bot clamps this to `MAX_LEVERAGE`)
- `ACTIVE_POSITION_CHECK_SECONDS=3600` (when a position is open, only check TP/SL closure once per hour)
- `POST_TRADE_COOLDOWN_SECONDS=3600` (after a position closes, wait 1 hour before the next prediction/entry)
- `ORDER_SUBMIT_COOLDOWN_SECONDS=120` (prevents duplicate order submissions)
- `ENTRY_ORDER_MODE=immediate` (`immediate` enters right away; `limit_wait` places a resting limit entry and attaches TP/SL after fill)
- `ENTRY_LIMIT_OFFSET_PCT=0.00` (for `limit_wait`: how far from current price to place the entry limit)
- `ENTRY_USE_AI_OFFSET=true` (for `limit_wait`: if true, uses the AI-provided `entry_limit_offset_pct` instead of `ENTRY_LIMIT_OFFSET_PCT`)
- `ENTRY_WAIT_SECONDS=3600` (for `limit_wait`: cancel entry if not filled within this time)
- `ENTRY_CHECK_SECONDS=60` (for `limit_wait`: poll cadence while waiting for fill)

Optional gates:
- `DISABLE_RED_DAY_GATE=true` (disables the astrology “red day” trading halt)

State/logging (optional):
- `BOT_STATE_PATH=bot_state.json`
- `BOT_JOURNAL_PATH=bot_journal.jsonl`

### Step 5: First run in dry-run

Leave:
- `LIVE_TRADING=false`

Deploy. Then check Railway logs. You should see a startup summary and periodic evaluations.

### Step 6: Enable live trading (only after you confirm everything)

When you are ready:

1) Set:
   - `HYPERLIQUID_EXECUTION_VERIFIED=true`
2) Set:
   - `LIVE_TRADING=true`

If you want to force the bot to trade *without* protective TP/SL (not recommended), you must also set:
- `ALLOW_UNPROTECTED_POSITIONS=true`

## Troubleshooting

- **Docker builds but OpenAI fails**: confirm `OPENAI_API_KEY` is valid and your project has billing enabled.
- **Hyperliquid refuses live trading**: confirm `HYPERLIQUID_EXECUTION_VERIFIED=true` and your wallet/secret are correct.
- **Nothing happens**: the bot may classify `FLAT` and skip trades; check logs for `classification`.

## Key environment variables (reference)

- `MARKET_SYMBOL` (recommended: `ETH`)
- `CAPITAL_USD`
- `LIVE_TRADING` (default `false`)
- `HYPERLIQUID_EXECUTION_VERIFIED` (default `false`)
- `ALLOW_UNPROTECTED_POSITIONS` (default `false`)
- `MAX_NOTIONAL_PCT` (default `0.10`)
- `MAX_LEVERAGE` (default `10`)
- `ORDER_LEVERAGE` (default `25`, clamped to `MAX_LEVERAGE`)
- `ACTIVE_POSITION_CHECK_SECONDS` (default `3600`)
- `POST_TRADE_COOLDOWN_SECONDS` (default `3600`)
- `ORDER_SUBMIT_COOLDOWN_SECONDS` (default `120`)
- `ENTRY_ORDER_MODE` (default `immediate`)
- `ENTRY_LIMIT_OFFSET_PCT` (default `0.00`)
- `ENTRY_USE_AI_OFFSET` (default `true`)
- `ENTRY_WAIT_SECONDS` (default `3600`)
- `ENTRY_CHECK_SECONDS` (default `60`)

State/logging:

- `BOT_STATE_PATH` (default `bot_state.json`)
- `BOT_JOURNAL_PATH` (default `bot_journal.jsonl`)

## Notes

- If you pasted real API keys into chat or into git history, rotate/revoke them immediately.
- Before enabling live trading, replace the Hyperliquid signing/order payload logic with a verified implementation from official docs.

