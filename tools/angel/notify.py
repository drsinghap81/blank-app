"""Telegram: messages, Approve/Skip buttons, and commands (/status /stop /flat /help).
Only messages from your own TELEGRAM_CHAT_ID are obeyed."""
from __future__ import annotations

import json

import requests


class Telegram:
    def __init__(self, token: str | None, chat_id: str | None, log=print):
        self.tok, self.chat, self.log = token, str(chat_id) if chat_id else None, log
        self.offset = None
        self.answers = {}           # approval key -> True / False
        self.commands = []

    @property
    def on(self):
        return bool(self.tok and self.chat)

    def _call(self, method, **data):
        if not self.on:
            return None
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.tok}/{method}", data=data, timeout=20)
            return r.json()
        except Exception as e:  # noqa: BLE001
            self.log(f"telegram {method} failed: {e}")
            return None

    def send(self, text, buttons=None):
        data = dict(chat_id=self.chat, text=text[:4000])
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]})
        return self._call("sendMessage", **data)

    # approvals --------------------------------------------------------------
    def ask(self, key, text):
        if not self.on:
            self.log(f"(no Telegram) approval needed but cannot ask: {text}")
            return
        self.send("🟡 " + text, buttons=[("✅ Approve", f"ok|{key}"), ("❌ Skip", f"no|{key}")])

    def get(self, key):
        return self.answers.get(key)

    def poll(self):
        """read button presses and commands; call every few seconds."""
        if not self.on:
            return []
        data = dict(timeout=0)
        if self.offset:
            data["offset"] = self.offset
        r = self._call("getUpdates", **data) or {}
        cmds = []
        for u in r.get("result", []):
            self.offset = u["update_id"] + 1
            cb = u.get("callback_query")
            if cb and str(cb["message"]["chat"]["id"]) == self.chat:
                yes, key = cb["data"].split("|", 1)
                self.answers[key] = yes == "ok"
                self._call("answerCallbackQuery", callback_query_id=cb["id"], text="Approved" if yes == "ok" else "Skipped")
                self._call("editMessageText", chat_id=self.chat, message_id=cb["message"]["message_id"],
                           text=cb["message"]["text"] + ("\n→ APPROVED ✅" if yes == "ok" else "\n→ SKIPPED ❌"))
                continue
            m = u.get("message")
            if m and str(m["chat"]["id"]) == self.chat and (m.get("text") or "").startswith("/"):
                cmds.append(m["text"].split()[0].lower())
        return cmds
