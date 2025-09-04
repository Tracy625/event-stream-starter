import os
import json
import time
import requests
from pathlib import Path
from typing import Dict, Any, Optional

from api.metrics import log_json, timeit
from api.cache import get_redis_client

class TelegramNotifier:
    """Minimal Telegram notification service"""
    
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.redis = get_redis_client()
        self.timeout = 10  # seconds
        
    def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False
    ) -> Dict[str, Any]:
        """
        Send message to Telegram chat
        Returns: {"success": bool, "message_id": str, "error": str}
        """
        
        if not self.bot_token:
            log_json(
                stage="telegram.error",
                error="TELEGRAM_BOT_TOKEN not configured"
            )
            return {"success": False, "error": "Bot token not configured"}
        
        try:
            # Rate limiting check
            if self.redis:
                rate_key = f"telegram:rate:{chat_id}"
                rate_count = self.redis.incr(rate_key)
                
                if rate_count == 1:
                    self.redis.expire(rate_key, 60)  # Reset every minute
                
                if rate_count > 30:  # Max 30 messages per minute
                    log_json(
                        stage="telegram.ratelimit",
                        chat_id=chat_id,
                        count=rate_count
                    )
                    return {"success": False, "error": "Rate limit exceeded"}
            
            # Prepare request
            url = f"{self.base_url}/sendMessage"
            
            payload = {
                "chat_id": chat_id,
                "text": text[:4096],  # Telegram message limit
                "parse_mode": parse_mode,
                "disable_notification": disable_notification
            }
            
            # Send request
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            # Parse response
            data = response.json()
            
            if data.get("ok"):
                message_id = data["result"]["message_id"]
                
                log_json(
                    stage="telegram.sent",
                    chat_id=chat_id,
                    message_id=message_id,
                    text_length=len(text)
                )
                
                return {
                    "success": True,
                    "message_id": str(message_id)
                }
            else:
                error = data.get("description", "Unknown error")
                
                log_json(
                    stage="telegram.api_error",
                    chat_id=chat_id,
                    error=error,
                    error_code=data.get("error_code")
                )
                
                return {"success": False, "error": error}
                
        except requests.exceptions.Timeout:
            log_json(
                stage="telegram.timeout",
                chat_id=chat_id
            )
            return {"success": False, "error": "Request timeout"}
            
        except requests.exceptions.RequestException as e:
            log_json(
                stage="telegram.request_error",
                chat_id=chat_id,
                error=str(e)
            )
            return {"success": False, "error": f"Request failed: {str(e)}"}
            
        except Exception as e:
            log_json(
                stage="telegram.error",
                chat_id=chat_id,
                error=str(e)
            )
            return {"success": False, "error": str(e)}
    
    def get_updates(self, offset: Optional[int] = None) -> Dict[str, Any]:
        """Get updates from Telegram (for testing)"""
        
        if not self.bot_token:
            return {"success": False, "error": "Bot token not configured"}
        
        try:
            url = f"{self.base_url}/getUpdates"
            
            params = {}
            if offset:
                params["offset"] = offset
            
            response = requests.get(
                url,
                params=params,
                timeout=self.timeout
            )
            
            data = response.json()
            
            if data.get("ok"):
                return {
                    "success": True,
                    "updates": data.get("result", [])
                }
            else:
                return {
                    "success": False,
                    "error": data.get("description", "Unknown error")
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def test_connection(self) -> Dict[str, Any]:
        """Test bot connection"""
        
        if not self.bot_token:
            return {"success": False, "error": "Bot token not configured"}
        
        try:
            url = f"{self.base_url}/getMe"
            
            response = requests.get(url, timeout=self.timeout)
            data = response.json()
            
            if data.get("ok"):
                bot_info = data.get("result", {})
                
                log_json(
                    stage="telegram.connected",
                    bot_username=bot_info.get("username"),
                    bot_id=bot_info.get("id")
                )
                
                return {
                    "success": True,
                    "bot_username": bot_info.get("username"),
                    "bot_id": bot_info.get("id")
                }
            else:
                return {
                    "success": False,
                    "error": data.get("description", "Unknown error")
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}


# Module-level convenience functions for Day9.1 verification
MODE = os.getenv("TELEGRAM_MODE", "mock").lower()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_SANDBOX_CHAT_ID")
MOCK_PATH = Path(os.getenv("TELEGRAM_MOCK_PATH", "/tmp/telegram_sandbox.jsonl"))


def _now_iso() -> str:
    """Get current ISO timestamp"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _push_mock(text: str) -> Dict:
    """Push to mock file for testing"""
    rec = {"ok": True, "mock": True, "text": text, "ts": _now_iso()}
    MOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MOCK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log_json(stage="telegram.mock", path=str(MOCK_PATH), text_len=len(text))
    return rec


def _push_real(text: str) -> Dict:
    """Push to real Telegram"""
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_SANDBOX_CHAT_ID not set"}
    
    notifier = TelegramNotifier()
    result = notifier.send_message(
        chat_id=CHAT_ID,
        text=text,
        parse_mode="Markdown"
    )
    
    return {
        "ok": result.get("success", False),
        "message_id": result.get("message_id"),
        "error": result.get("error")
    }


def push_topic_card(text: str) -> Dict:
    """
    Minimal adapter for Day9.1 verification.
    Respect TELEGRAM_MODE: mock | real.
    """
    if MODE == "real":
        return _push_real(text)
    return _push_mock(text)