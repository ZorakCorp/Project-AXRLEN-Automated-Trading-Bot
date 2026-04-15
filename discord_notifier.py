import os
import time
import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class DiscordNotifier:
    """
    Sends alerts either via:
    - Discord webhook (DISCORD_WEBHOOK_URL) OR
    - 1:1 DM using a bot token + user id (DISCORD_BOT_TOKEN + DISCORD_USER_ID)

    Uses only requests (no discord.py dependency).
    """

    def __init__(self):
        self.enabled = os.getenv("DISCORD_ALERTS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
        self.webhook_url = (os.getenv("DISCORD_WEBHOOK_URL", "") or "").strip()
        self.bot_token = (os.getenv("DISCORD_BOT_TOKEN", "") or "").strip()
        self.user_id = (os.getenv("DISCORD_USER_ID", "") or "").strip()
        self.min_interval_seconds = int(os.getenv("DISCORD_MIN_ALERT_INTERVAL_SECONDS", "30"))
        self._last_sent_at = 0.0
        self._session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        return session

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        if (now - self._last_sent_at) < float(self.min_interval_seconds):
            return False
        self._last_sent_at = now
        return True

    def _send_webhook(self, content: str) -> None:
        if not self.webhook_url:
            return
        self._session.post(
            self.webhook_url,
            json={"content": content[:1900]},
            timeout=10,
        )

    def _get_or_create_dm_channel_id(self) -> Optional[str]:
        if not self.bot_token or not self.user_id:
            return None
        headers = {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}
        resp = self._session.post(
            "https://discord.com/api/v10/users/@me/channels",
            headers=headers,
            json={"recipient_id": self.user_id},
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.warning("Discord DM channel create failed (status=%s): %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        ch_id = data.get("id")
        return str(ch_id) if ch_id else None

    def _send_dm(self, content: str) -> None:
        channel_id = self._get_or_create_dm_channel_id()
        if not channel_id:
            return
        headers = {"Authorization": f"Bot {self.bot_token}", "Content-Type": "application/json"}
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        resp = self._session.post(url, headers=headers, json={"content": content[:1900]}, timeout=10)
        if resp.status_code >= 400:
            logger.warning("Discord DM send failed (status=%s): %s", resp.status_code, resp.text[:200])

    def send(self, content: str) -> None:
        if not self.enabled:
            return
        if not (self.webhook_url or (self.bot_token and self.user_id)):
            return
        if not self._rate_limit_ok():
            return

        try:
            if self.webhook_url:
                self._send_webhook(content)
            else:
                self._send_dm(content)
        except Exception as e:
            logger.warning("Discord alert failed: %s", str(e))

