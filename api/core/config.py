"""Telegram configuration module (Day20+21)"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import find_dotenv, load_dotenv

# 只在本地（未注入环境时）加载根目录 .env，且不覆盖已有变量
load_dotenv(find_dotenv(usecwd=True), override=False)


@dataclass
class TelegramConfig:
    """Telegram bot configuration"""

    bot_token: str
    channel_id: int
    rate_limit: int
    timeout_secs: int
    https_proxy: Optional[str]
    no_proxy: str
    sandbox: bool
    sandbox_channel_id: Optional[int]
    sandbox_thread_id: Optional[int]

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        """Load configuration from environment variables"""
        bot_token = os.getenv("TG_BOT_TOKEN", "")
        ch_raw = os.getenv("TG_CHANNEL_ID", "").strip()
        try:
            channel_id = int(ch_raw) if ch_raw else 0
        except ValueError:
            channel_id = 0
        rate_limit = int(os.getenv("TG_RATE_LIMIT", "20"))
        timeout_secs = int(os.getenv("TG_TIMEOUT_SECS", "6"))
        https_proxy = os.getenv("HTTPS_PROXY", "") or None
        no_proxy = os.getenv("NO_PROXY", "localhost,127.0.0.1,db,redis")

        # Sandbox config
        sandbox_env = os.getenv("TG_SANDBOX", "").lower()
        sandbox = sandbox_env in ("1", "true", "yes")

        sandbox_ch_raw = os.getenv("TG_SANDBOX_CHANNEL_ID", "").strip()
        try:
            sandbox_channel_id = int(sandbox_ch_raw) if sandbox_ch_raw else None
        except ValueError:
            sandbox_channel_id = None

        sandbox_th_raw = os.getenv("TG_SANDBOX_THREAD_ID", "").strip()
        try:
            sandbox_thread_id = int(sandbox_th_raw) if sandbox_th_raw else None
        except ValueError:
            sandbox_thread_id = None

        # Log configuration (mask token)
        if bot_token:
            if len(bot_token) > 8:
                masked_token = f"{bot_token[:4]}...{bot_token[-4:]}"
            else:
                masked_token = "****"
            effective_ch = (
                sandbox_channel_id if sandbox and sandbox_channel_id else channel_id
            )
            print(
                f"[TelegramConfig] bot_token={masked_token}, channel_id={channel_id}, "
                f"rate_limit={rate_limit}, timeout_secs={timeout_secs}, "
                f"https_proxy={https_proxy or 'none'}, no_proxy={no_proxy}, "
                f"sandbox={sandbox}, effective_channel={effective_ch}"
            )
        else:
            print("[TelegramConfig] No bot token configured")

        return cls(
            bot_token=bot_token,
            channel_id=channel_id,
            rate_limit=rate_limit,
            timeout_secs=timeout_secs,
            https_proxy=https_proxy,
            no_proxy=no_proxy,
            sandbox=sandbox,
            sandbox_channel_id=sandbox_channel_id,
            sandbox_thread_id=sandbox_thread_id,
        )

    def effective_channel_id(self) -> int:
        """Get effective channel ID considering sandbox mode"""
        return (
            self.sandbox_channel_id
            if self.sandbox and self.sandbox_channel_id
            else self.channel_id
        )

    def effective_thread_id(self) -> Optional[int]:
        """Get effective thread ID considering sandbox mode"""
        return self.sandbox_thread_id if self.sandbox else None
