# AXRLEN-TRADING

Automated trading bot framework (Hyperliquid + Gemini) with safety-first defaults.

## What this repo is

- **Signal engine** that outputs `LONG` / `SHORT` / `FLAT`
- **Risk sizing** with notional caps
- **Execution adapter** for Hyperliquid (currently contains **placeholder assumptions** and is locked down for safety)
- **Gemini integration** for structured signal/context enrichment (JSON-only outputs)

## Safety model (read this)

- **Dry-run by default**: the bot will not place real orders unless `LIVE_TRADING=true`.
- **Live trading is locked**: even if `LIVE_TRADING=true`, the bot refuses to trade unless you explicitly set `HYPERLIQUID_EXECUTION_VERIFIED=true`.
- **No “fake success”**: if a live order fails, the bot raises instead of pretending it executed.
- **Protective orders are not guaranteed**: TP/SL are computed, but this repo does not guarantee they are enforced on-exchange. By default the bot will refuse to place live orders unless you explicitly set `ALLOW_UNPROTECTED_POSITIONS=true`.

## Setup

1) Copy `.env.example` to `.env` and fill in values.

2) Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3) Run (dry-run):

```bash
python main.py run
```

## Key environment variables

- `MARKET_SYMBOL` (recommended: `ETH`)
- `CAPITAL_USD`
- `LIVE_TRADING` (default `false`)
- `HYPERLIQUID_EXECUTION_VERIFIED` (default `false`)
- `ALLOW_UNPROTECTED_POSITIONS` (default `false`)
- `MAX_NOTIONAL_PCT` (default `0.10`)
- `MAX_LEVERAGE` (default `10`)

State/logging:

- `BOT_STATE_PATH` (default `bot_state.json`)
- `BOT_JOURNAL_PATH` (default `bot_journal.jsonl`)

## Notes

- If you pasted real API keys into chat or into git history, rotate/revoke them immediately.
- Before enabling live trading, replace the Hyperliquid signing/order payload logic with a verified implementation from official docs.

