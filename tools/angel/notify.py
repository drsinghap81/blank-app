"""Telegram: messages, Approve/Skip buttons, phone buttons (Status / Stop / Square off) and commands.
Only messages from your own TELEGRAM_CHAT_ID are obeyed."""
from __future__ import annotations

import json
import os
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


class AppChannel:
    """Same interface as Telegram, but talks to the Trend Desk app through files that the live server
    (tools/live_server/app.py, /api/tb/...) reads and writes:
      messages.jsonl  bot -> app   (feed)
      pending.json    bot -> app   (approvals / choices waiting for an answer)
      answers.json    app -> bot   ({key: true | false | "value"})
      commands.json   app -> bot   (["/status", "/stop", "/flat"])
      status.json     bot -> app   (plan, position, last price)"""

    def __init__(self, folder: str, log=print):
        self.dir, self.log = folder, log
        os.makedirs(folder, exist_ok=True)

    on = True

    def _p(self, name):
        return os.path.join(self.dir, name)

    def _read(self, name, default):
        try:
            with open(self._p(name), encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return default

    def _write(self, name, obj):
        tmp = self._p(name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, self._p(name))

    def send(self, text, buttons=None):
        with open(self._p("messages.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(t=time.time(), text=text[:4000])) + "\n")

    def ask(self, key, text, options=None):
        P = self._read("pending.json", {})
        if key not in P and self.get(key) is None:
            P[key] = dict(text=text, t=time.time(), options=options)
            self._write("pending.json", P)

    def get(self, key):
        return self._read("answers.json", {}).get(key)

    def used(self, key):
        """forget an answer once its level has been traded / replaced."""
        A = self._read("answers.json", {}); A.pop(key, None); self._write("answers.json", A)
        P = self._read("pending.json", {}); P.pop(key, None); self._write("pending.json", P)

    def poll(self):
        cmds = self._read("commands.json", [])
        if cmds:
            self._write("commands.json", [])
        return cmds

    def keyboard(self, text):
        self.send(text)

    def choose(self, key, text, options, deadline, extra_poll=None):
        self.ask(key, text, options=[[lbl, val] for lbl, val in options])
        while time.time() < deadline:
            v = self.get(key)
            if v is not None:
                self.used(key); return v
            time.sleep(2)
        P = self._read("pending.json", {}); P.pop(key, None); self._write("pending.json", P)
        return None

    def wait_code(self, prompt, deadline, digits=6):
        self.send(prompt + " (code login isn't supported in app mode; use login_mode onetap)")
        return None

    def status(self, d: dict):
        self._write("status.json", dict(d, t=time.time()))

    def prune(self, keep_keys):
        """drop pending approvals for levels that no longer exist (keep_keys = today's keys)."""
        P = self._read("pending.json", {})
        P2 = {k: v for k, v in P.items() if k in keep_keys or v.get("options")}
        if P2 != P:
            self._write("pending.json", P2)
