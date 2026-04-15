import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests
import websocket

from stats_service import iter_pnls_from_journal, summarize_pnl

logger = logging.getLogger(__name__)


class DiscordDMCommandBot:
    """
    Minimal Discord Gateway client for 1:1 DM commands (no discord.py).

    Commands (send these to the bot in DM):
    - /pnl day|3d|week|month|year|ytd|all
    - /winrate day|3d|week|month|year|ytd|all
    - /help
    """

    def __init__(self, journal_path: str):
        self.enabled = os.getenv("DISCORD_COMMANDS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
        self.bot_token = (os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
        self.user_id = (os.getenv("DISCORD_USER_ID", "") or "").strip()
        self.journal_path = journal_path
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dm_channel_id: Optional[str] = None
        self._seq: Optional[int] = None

    def start(self) -> None:
        if not self.enabled:
            return
        if not (self.bot_token and self.user_id):
            logger.warning("Discord commands enabled but DISCORD_BOT_TOKEN/DISCORD_USER_ID not set.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="discord-dm-commands", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _api_headers(self) -> dict:
        return {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}

    def _get_or_create_dm_channel_id(self) -> Optional[str]:
        if self._dm_channel_id:
            return self._dm_channel_id
        resp = requests.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers=self._api_headers(),
            json={"recipient_id": self.user_id},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning("Discord DM channel create failed (status=%s): %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        ch_id = data.get("id")
        if ch_id:
            self._dm_channel_id = str(ch_id)
        return self._dm_channel_id

    def _send_dm(self, content: str) -> None:
        ch_id = self._get_or_create_dm_channel_id()
        if not ch_id:
            return
        url = f"https://discord.com/api/v10/channels/{ch_id}/messages"
        requests.post(url, headers=self._api_headers(), json={"content": content[:1900]}, timeout=10)

    def _handle_command(self, text: str) -> None:
        parts = (text or "").strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        arg = parts[1].lower() if len(parts) > 1 else "day"
        if cmd in {"/help", "help"}:
            self._send_dm("Commands: `/pnl day|3d|week|month|year|ytd|all`, `/winrate day|3d|week|month|year|ytd|all`")
            return
        if cmd not in {"/pnl", "/winrate"}:
            return
        if arg not in {"day", "3d", "week", "month", "year", "ytd", "all"}:
            self._send_dm("Invalid window. Use: day, 3d, week, month, year, ytd, all")
            return

        pnls = iter_pnls_from_journal(self.journal_path)
        summary = summarize_pnl(pnls, now=datetime.now(timezone.utc), window=arg)
        if cmd == "/pnl":
            self._send_dm(
                f"PnL ({arg}): {summary['pnl']:.4f} USD | trades={summary['trades']} | wins={summary['wins']} losses={summary['losses']}"
            )
        else:
            self._send_dm(
                f"Winrate ({arg}): {summary['winrate_pct']:.2f}% | trades={summary['trades']} | pnl={summary['pnl']:.4f} USD"
            )

    def _run(self) -> None:
        # Read gateway URL
        gw = requests.get("https://discord.com/api/v10/gateway/bot", headers=self._api_headers(), timeout=10)
        if gw.status_code >= 400:
            logger.warning("Discord gateway fetch failed (status=%s): %s", gw.status_code, gw.text[:200])
            return
        url = gw.json().get("url")
        if not url:
            return
        ws_url = f"{url}?v=10&encoding=json"

        def on_message(_ws, message: str):
            if self._stop.is_set():
                return
            try:
                payload = json.loads(message)
            except Exception:
                return
            if isinstance(payload, dict) and payload.get("s") is not None:
                try:
                    self._seq = int(payload["s"])
                except Exception:
                    pass
            op = payload.get("op") if isinstance(payload, dict) else None
            t = payload.get("t") if isinstance(payload, dict) else None
            d = payload.get("d") if isinstance(payload, dict) else None
            if op == 10 and isinstance(d, dict):
                hb_interval_ms = int(d.get("heartbeat_interval", 45000))
                threading.Thread(target=heartbeat, args=(hb_interval_ms,), daemon=True).start()
                identify()
                return
            if t == "MESSAGE_CREATE" and isinstance(d, dict):
                author = d.get("author") or {}
                author_id = str(author.get("id", ""))
                channel_type = d.get("channel_type")
                content = str(d.get("content", "") or "")
                # Only respond to the configured user, and only in DMs (type 1).
                if author_id == str(self.user_id) and channel_type == 1 and content.startswith("/"):
                    self._handle_command(content)

        def on_error(_ws, error):
            logger.warning("Discord WS error: %s", str(error))

        def on_close(_ws, close_status_code, close_msg):
            logger.info("Discord WS closed: %s %s", close_status_code, close_msg)

        def heartbeat(interval_ms: int):
            while not self._stop.is_set():
                try:
                    ws.send(json.dumps({"op": 1, "d": self._seq}))
                except Exception:
                    return
                time.sleep(max(1.0, interval_ms / 1000.0))

        def identify():
            intents = 512  # DIRECT_MESSAGES
            # MESSAGE_CONTENT intent may be required depending on bot settings
            if os.getenv("DISCORD_MESSAGE_CONTENT_INTENT", "true").strip().lower() in {"1", "true", "yes", "y", "on"}:
                intents |= 1 << 15  # MESSAGE_CONTENT
            ws.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": self.bot_token,
                            "intents": intents,
                            "properties": {"os": "linux", "browser": "axrlen", "device": "axrlen"},
                        },
                    }
                )
            )

        while not self._stop.is_set():
            ws = websocket.WebSocketApp(ws_url, on_message=on_message, on_error=on_error, on_close=on_close)
            ws.run_forever(ping_interval=0, ping_timeout=None)
            if not self._stop.is_set():
                time.sleep(5)

