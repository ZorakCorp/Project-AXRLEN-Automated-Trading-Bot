import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class TradePnL:
    ts: datetime
    pnl: float


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        # Expect ISO with timezone (we write UTC isoformat()).
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def iter_pnls_from_journal(journal_path: str) -> Iterable[TradePnL]:
    if not journal_path or not os.path.exists(journal_path):
        return []

    items: List[TradePnL] = []
    try:
        with open(journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("event") != "pnl":
                    continue
                ts = ev.get("ts")
                pnl = ev.get("pnl")
                if not isinstance(ts, str):
                    continue
                dt = _parse_iso(ts)
                if dt is None:
                    continue
                try:
                    pnl_f = float(pnl)
                except Exception:
                    continue
                items.append(TradePnL(ts=dt, pnl=pnl_f))
    except Exception:
        return []
    return items


def _window_bounds(now: datetime, window: str) -> Tuple[datetime, datetime]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if window == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if window == "3d":
        return now - timedelta(days=3), now
    if window == "week":
        return now - timedelta(days=7), now
    if window == "month":
        return now - timedelta(days=30), now
    if window == "year":
        return now - timedelta(days=365), now
    if window == "ytd":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if window == "all":
        return datetime(1970, 1, 1, tzinfo=timezone.utc), now
    raise ValueError("Unsupported window")


def summarize_pnl(pnls: Iterable[TradePnL], now: datetime, window: str) -> dict:
    start, end = _window_bounds(now, window)
    wins = 0
    losses = 0
    total = 0.0
    count = 0
    for t in pnls:
        if t.ts < start or t.ts > end:
            continue
        count += 1
        total += float(t.pnl)
        if t.pnl > 0:
            wins += 1
        elif t.pnl < 0:
            losses += 1
    winrate = (wins / count) * 100.0 if count else 0.0
    return {
        "window": window,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "trades": count,
        "wins": wins,
        "losses": losses,
        "winrate_pct": winrate,
        "pnl": total,
    }

