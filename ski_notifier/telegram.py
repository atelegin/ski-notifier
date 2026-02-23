"""Telegram API client helpers."""

import os
import sys
from typing import Any, Dict, List, Optional

import requests

# Telegram API endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_UPDATES_API_URL = "https://api.telegram.org/bot{token}/getUpdates"


def send_message(text: str, parse_mode: str = "Markdown") -> None:
    """Send message to Telegram chat.
    
    Args:
        text: Message text.
        parse_mode: Telegram parse mode (Markdown or HTML).
        
    Raises:
        RuntimeError: If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set.
        RuntimeError: If Telegram API returns non-200 response.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID environment variable not set")
    
    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        print(f"ERROR: Telegram request failed: {e}", file=sys.stderr)
        sys.exit(1)
    
    if resp.status_code != 200:
        print(f"ERROR: Telegram API returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)
    
    result = resp.json()
    if not result.get("ok"):
        print(f"ERROR: Telegram API error: {result}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Message sent successfully to chat {chat_id}")


def get_updates(offset: Optional[int] = None, timeout: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch incoming Telegram updates for this bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set")

    url = TELEGRAM_UPDATES_API_URL.format(token=token)
    params: Dict[str, Any] = {
        "timeout": timeout,
        "limit": limit,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        params["offset"] = offset

    resp = requests.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram getUpdates returned {resp.status_code}: {resp.text}")

    payload = resp.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram getUpdates error: {payload}")

    result = payload.get("result", [])
    if not isinstance(result, list):
        raise RuntimeError("Telegram getUpdates returned malformed payload")
    return result
