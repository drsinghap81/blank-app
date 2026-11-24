"""First login for command-line moomoo OpenD >= 10.10 (24 Nov 2026). OpenD now asks for the account and password interactively and
can remember the password; afterwards the service runs `OpenD -login_account=<id> -login_by_remember=1`.
Run by opend_setup.sh as root:  python3 opend_login.py <OpenD binary> <cfg file> <account> <password file> <status file> <code file>
The password file is read once and deleted at once. The SMS code (if OpenD asks) is taken from <code file>, which the app writes."""
import os
import pty
import re
import select
import socket
import sys
import time

BIN, CFG, ACC, PWF, STATUS, CODEF = sys.argv[1:7]
pw = open(PWF).read().strip(); os.remove(PWF)


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
    os.chdir(os.path.dirname(BIN)); os.execv(BIN, [BIN, f"-cfg_file={CFG}", "-lang=en"])
buf = ""; sent = set(); t0 = time.time(); ok = False; code_wait = False
note("OpenD started for the first login")
while time.time() - t0 < 600:
    r, _, _ = select.select([fd], [], [], 1.0)
    if r:
        try:
            chunk = os.read(fd, 4096).decode("utf-8", "replace")
        except OSError:
            break
        buf += chunk
        for line in chunk.splitlines():
            ln = line.strip()
            if ln and pw not in ln:
                note("OpenD: " + ln[:200])
        low = buf[-600:].lower()
        if re.search(r"account|moomoo id|user ?id|login id|phone", low) and "acc" not in sent and not re.search(r"pass ?word|pwd", low[-120:]):
            os.write(fd, (ACC + "\n").encode()); sent.add("acc"); buf = ""; continue
        if re.search(r"pass ?word|pwd", low) and "pw" not in sent:
            time.sleep(0.3); os.write(fd, (pw + "\n").encode()); sent.add("pw"); buf = ""; continue
        if "remember" in low and "rem" not in sent:
            os.write(fd, b"y\n"); sent.add("rem"); buf = ""; continue
        if ("verif" in low or "verification code" in low or "sms" in low) and "code" not in sent:
            code_wait = True; note("WAITING FOR SMS CODE: enter it in Trend Desk > Settings > Connect moomoo"); buf = ""
        if "success" in low and "login" in low:
            ok = True
    if code_wait and "code" not in sent and os.path.exists(CODEF):
        c = "".join(ch for ch in open(CODEF).read() if ch.isdigit()); os.remove(CODEF)
        if c:
            os.write(fd, (c + "\n").encode()); sent.add("code"); note("SMS code passed to OpenD")
    if port_open() and "pw" in sent and time.time() - t0 > 8:
        ok = True
    if ok:
        time.sleep(5); break
pw = None
try:
    os.kill(pid, 15); time.sleep(3); os.kill(pid, 9)
except OSError:
    pass
note("FIRST LOGIN OK - starting the OpenD service" if ok else "FIRST LOGIN NOT CONFIRMED - see the lines above")
sys.exit(0 if ok else 1)
