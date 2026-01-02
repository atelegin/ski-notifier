"""Telegram bot sender."""

import os
import sys

import requests

# Telegram API endpoint
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


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
