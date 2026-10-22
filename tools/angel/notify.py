"""Telegram: messages, Approve/Skip buttons, phone buttons (Status / Stop / Square off) and commands.
Only messages from your own TELEGRAM_CHAT_ID are obeyed."""
from __future__ import annotations

import json
import re
import time

import requests

# persistent phone buttons -> commands
KEYS = {"📊 Status": "/status", "⛔ Stop new trades": "/stop", "🔴 Square off": "/flat"}


class Telegram:
    def __init__(self, token: str | None, chat_id: str | None, log=print):
        self.tok, self.chat, self.log = token, str(chat_id) if chat_id else None, log
        self.offset = None
        self.answers = {}           # approval key -> True / False
        self.commands = []
        self.texts = []             # plain text replies (e.g. the 6-digit login code)

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
            if not m or str(m["chat"]["id"]) != self.chat:
                continue
            t = (m.get("text") or "").strip()
            if t in KEYS:
                cmds.append(KEYS[t])
            elif t.startswith("/"):
                cmds.append(t.split()[0].lower())
            elif t:
                self.texts.append(t)
        return cmds

    # phone controls ---------------------------------------------------------
    def keyboard(self, text):
        """show the always-visible Status / Stop / Square-off buttons under the chat."""
        kb = {"keyboard": [[{"text": k} for k in KEYS]], "resize_keyboard": True, "is_persistent": True}
        return self._call("sendMessage", chat_id=self.chat, text=text, reply_markup=json.dumps(kb))

    def choose(self, key, text, options, deadline, extra_poll=None):
        """inline buttons [(label, value)], wait until a press or the deadline (epoch seconds). Returns value or None."""
        if not self.on:
            return None
        self.send(text, buttons=[(lbl, f"ok|{key}={val}") for lbl, val in options])
        while time.time() < deadline:
            for c in self.poll():
                if extra_poll:
                    extra_poll(c)
            for k, v in list(self.answers.items()):
                if k.startswith(key + "="):
                    del self.answers[k]
                    return k.split("=", 1)[1]
            time.sleep(2)
        return None

    def wait_code(self, prompt, deadline, digits=6):
        """ask for a numeric code (e.g. Angel TOTP) and return it, or None at the deadline."""
        if not self.on:
            return None
        self.texts.clear()
        self.send(prompt)
        while time.time() < deadline:
            self.poll()
            while self.texts:
                t = self.texts.pop(0).replace(" ", "")
                if re.fullmatch(r"\d{%d}" % digits, t):
                    return t
                self.send(f"That isn't a {digits}-digit code — please send just the {digits} digits.")
            time.sleep(2)
        return None
