"""First login for command-line moomoo OpenD >= 10.10 (24 Nov 2026). OpenD now asks for the account and password interactively and
can remember the password; afterwards the service runs `OpenD -login_account=<id> -login_by_remember=1`.
Run by opend_setup.sh as root:  python3 opend_login.py <OpenD binary> <cfg file> <account> <password file> <status file> <code file> [<mode file>]
The password file is read once and deleted at once. The SMS code (if OpenD asks) is taken from <code file>, which the app writes.
24 Nov 2026: typed answers arrived empty at OpenD 10.12's prompts, so the login is first given as start-up options
(-login_account, -login_pwd_md5); typing is only the fallback (whole line + CR, + LF, + CRLF on successive tries).
<mode file> gets "md5 <hash>" or "remember" so the service starts the same way."""
import hashlib
import os
import pty
import re
import select
import socket
import sys
import time

BIN, CFG, ACC, PWF, STATUS, CODEF = sys.argv[1:7]
MODEF = sys.argv[7] if len(sys.argv) > 7 else None
pw = open(PWF).read().strip(); os.remove(PWF); MD5 = hashlib.md5(pw.encode()).hexdigest()


def note(s):
    with open(STATUS, "a") as f:
        f.write(time.strftime("%H:%M:%S ") + s + "\n")


def port_open():
    try:
        with socket.create_connection(("127.0.0.1", 11111), timeout=1):
            return True
    except OSError:
        return False


pid, fd = pty.fork()
if pid == 0:
    os.chdir(os.path.dirname(BIN)); os.execv(BIN, [BIN, f"-cfg_file={CFG}", "-lang=en", f"-login_account={ACC}", f"-login_pwd_md5={MD5}"])
buf = ""; sent = set(); t0 = time.time(); ok = False; code_wait = False; tries = 0
note("OpenD started for the first login")


ENDS = [b"\r", b"\n", b"\r\n"]
typed = False


def send(txt, what):
    global typed
    typed = True; time.sleep(0.8)                     # let OpenD finish drawing its prompt
    os.write(fd, txt.encode() + ENDS[min(tries, 2)]); sent.add(what)


while time.time() - t0 < 600:
    r, _, _ = select.select([fd], [], [], 1.0)
    if r:
        try:
            chunk = os.read(fd, 4096).decode("utf-8", "replace")
        except OSError:
            break
        buf += chunk
        for line in re.split(r"[\r\n]+", chunk):
            ln = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line).strip()
            if ln and ln != ">>>" and pw not in ln:
                note("OpenD: " + ln[:200])
        low = buf[-600:].lower()
        if "login failed" in low:
            tries += 1; buf = ""; note(f"(login attempt {tries} failed{' - the start-up options were not accepted, typing instead' if not typed else ''})")
            if tries >= 4:
                note("LOGIN FAILED 3 times - check the moomoo ID / password and send the form again"); break
            sent -= {"acc", "pw", "rem"}; continue
        if re.search(r"enter (your )?(account|moomoo id|user ?id|login id|phone)", low) and "acc" not in sent:
            buf = ""; send(ACC, "acc"); continue
        if re.search(r"enter (your )?(login )?pass ?word|enter (your )?pwd", low) and "pw" not in sent:
            buf = ""; send(pw, "pw"); continue
        if "remember" in low and "rem" not in sent:
            buf = ""; send("Y", "rem"); continue
        if ("verif" in low or "verification code" in low or "sms" in low) and "code" not in sent and not code_wait:
            code_wait = True; note("WAITING FOR SMS CODE: enter it in Trend Desk > Settings > Connect moomoo"); buf = ""
        if re.search(r"login (success|succeeded|successful)|logged in|login ok|登录成功", low):
            ok = True
    if code_wait and "code" not in sent and os.path.exists(CODEF):
        c = "".join(ch for ch in open(CODEF).read() if ch.isdigit()); os.remove(CODEF)
        if c:
            send(c, "code"); note("SMS code passed to OpenD")
    if ok:
        time.sleep(5); break
pw = None
try:
    os.kill(pid, 15); time.sleep(3); os.kill(pid, 9)
except OSError:
    pass
if ok and MODEF:
    with open(MODEF, "w") as f:
        f.write("remember" if "rem" in sent else f"md5 {MD5}")
    os.chmod(MODEF, 0o600)
note("FIRST LOGIN OK - starting the OpenD service" if ok else "FIRST LOGIN NOT CONFIRMED - see the lines above")
sys.exit(0 if ok else 1)
