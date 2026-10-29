"""Send a short alert to WhatsApp (CallMeBot, free for personal use) and/or Telegram, whichever is configured.
Secrets (GitHub repo settings -> Secrets and variables -> Actions), never in code or chat:
  WHATSAPP_PHONE    your WhatsApp number with country code, digits only (e.g. 61400000000)
  CALLMEBOT_APIKEY  the key CallMeBot sends you on WhatsApp after you message it
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  (optional)"""
import os
import sys
import time
import urllib.parse

import requests


def whatsapp(text: str) -> bool:
    phone, key = os.environ.get("WHATSAPP_PHONE", "").strip(), os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if not phone or not key:
        return False
    ok = True
    # CallMeBot accepts ~1000 characters per message; split long alerts
    parts = [text[i:i + 900] for i in range(0, min(len(text), 2700), 900)]
    for p in parts:
        url = ("https://api.callmebot.com/whatsapp.php?phone=" + urllib.parse.quote(phone) + "&text="
               + urllib.parse.quote(p) + "&apikey=" + urllib.parse.quote(key))
        try:
            r = requests.get(url, timeout=30)
            ok = ok and r.status_code == 200
            if r.status_code != 200:
                print("whatsapp failed:", r.status_code, file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            ok = False
            print("whatsapp failed:", type(e).__name__, file=sys.stderr)
        time.sleep(3)
    return ok


def telegram(text: str) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=20)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        print("telegram failed:", type(e).__name__, file=sys.stderr)
        return False


def send(text: str) -> None:
    """Send to every configured channel."""
    whatsapp(text)
    telegram(text)
