#!/usr/bin/env python3

import os
import re
import subprocess
import threading
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------- CONFIG ----------------

#API_URL = "http://127.0.0.1:4000/api/pools"
#POLL_INTERVAL = 30  # seconds

# ---------------- PATHS ----------------

NOC_ROOT = Path("/home/umbrel/umbrel/app-data/NOC-Mining")

WWW_DIR = NOC_ROOT / "www" / "blockwatch"
STATE_DIR = NOC_ROOT / "state" / "blockwatch"

WWW_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = STATE_DIR / ".blockwatch_state.json"

STATUS_FILE = WWW_DIR / "blockfound.txt"
LOG_FILE = WWW_DIR / "bf_log.txt"
HEIGHT_STATUS_FILE = WWW_DIR / "height.txt"
POOLBLOCK_STATUS_FILE = WWW_DIR / "poolblock.txt"

PRIMARY_POOL_ID = "dgb-sha256-1"
MININGCORE_CONTAINER = "willitmod-dev-dgb_miningcore_1"

RE_SUBMIT = re.compile(r"Submitting block (\d+) \[([0-9a-fA-F]+)\]")
RE_ACCEPT = re.compile(r"Daemon accepted block (\d+) \[([0-9a-fA-F]+)\].*submitted by (\S+)")

# ---------------- HELPERS ----------------

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text)
    tmp.replace(path)

def log_line(msg):
    line = f"[{now_utc()}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_state(state):
    atomic_write(STATE_FILE, json.dumps(state, indent=2) + "\n")

def set_status(text: str):
    atomic_write(STATUS_FILE, text.rstrip() + "\n")

def logwatch_miningcore():
    log_line(f"Logwatch starting (pid={os.getpid()}) container={MININGCORE_CONTAINER}")

    set_status("Blockwatch: running; waiting for Miningcore events...")
    atomic_write(HEIGHT_STATUS_FILE, "MININGCORE HEARTBEAT: waiting for next block...\n")

    # Tail logs from "now" so we don't re-alert old wins after restarts
    cmd = ["docker", "logs", "-f", "--since", "0s", MININGCORE_CONTAINER]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    state = load_state()
    last_accept = state.get("last_accept", "")


    for line in p.stdout:
        s = line.strip()

        # Heartbeat: Miningcore logs this once per pool (sha256 + scrypt).
        # We only use PRIMARY_POOL_ID to avoid duplicates.
        if "Detected new block" in s:
            if f"[{PRIMARY_POOL_ID}]" not in s:
                continue

            m = re.search(r"Detected new block (\d+)", s)
            if m:
                height = int(m.group(1))
                msg = f"MININGCORE HEARTBEAT ({PRIMARY_POOL_ID}): new network block {height}"
                atomic_write(HEIGHT_STATUS_FILE, msg + "\n")
                set_status(msg)
                log_line(msg)
            continue


        # True win: submit + accept
        m = RE_SUBMIT.search(s)
        if m:
            height = int(m.group(1))
            hsh = m.group(2)
            msg = f"POOL BLOCK SUBMITTED: height={height} hash={hsh}"
            atomic_write(POOLBLOCK_STATUS_FILE, msg + "\n")
            set_status(msg)
            log_line(msg)
            continue

        #m = RE_ACCEPT.search(s)
        m = RE_ACCEPT.search(s)
        if m:
            height = int(m.group(1))
            hsh = m.group(2)
            who = m.group(3)
            msg = f"POOL BLOCK ACCEPTED: height={height} hash={hsh} by={who}"

            accept_key = f"{height}:{hsh}"
            if accept_key != last_accept:
                atomic_write(POOLBLOCK_STATUS_FILE, msg + "\n")
                set_status(msg)
                log_line(msg)

                state["last_accept"] = accept_key
                save_state(state)
                last_accept = accept_key
            else:
                # duplicate replay, ignore
                pass
            continue

    # <-- THIS IS THE ONLY CORRECT PLACE FOR THESE TWO LINES
    log_line("Log stream ended (miningcore container restarted?) — exiting logwatch thread")
    set_status("Blockwatch: log stream ended — check miningcore container")

    # Exit the whole process so systemd restarts it
    os._exit(0)

# ---------------- MAIN LOOP ----------------

def main():
    log_line("Blockwatch starting")

    t = threading.Thread(target=logwatch_miningcore, daemon=True)
    t.start()

    # Logs-only mode: Miningcore emits both heartbeat and block-win signals.
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
