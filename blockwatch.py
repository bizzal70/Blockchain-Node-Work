#!/usr/bin/env python3

import os
import re
import subprocess
import threading
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

# ---------------- CONFIG ----------------

API_URL = "http://127.0.0.1:4000/api/pools"
POLL_INTERVAL = 30  # seconds

BASE_DIR = Path(__file__).resolve().parent.parent / "www"
STATE_FILE = BASE_DIR / ".blockwatch_state.json"
STATUS_FILE = BASE_DIR / "blockfound.txt"
LOG_FILE = BASE_DIR / "bf_log.txt"
PRIMARY_POOL_ID = "dgb-sha256-1"

MININGCORE_CONTAINER = "willitmod-dev-dgb_miningcore_1"

HEIGHT_STATUS_FILE = BASE_DIR / "height.txt"
POOLBLOCK_STATUS_FILE = BASE_DIR / "poolblock.txt"

RE_DETECTED = re.compile(r"\[([^\]]+)\].*Detected new block (\d+)")
RE_SUBMIT = re.compile(r"Submitting block (\d+) \[([0-9a-fA-F]+)\]")
RE_ACCEPT = re.compile(r"Daemon accepted block (\d+) \[([0-9a-fA-F]+)\].*submitted by (\S+)")



# ---------------- HELPERS ----------------

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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
    STATE_FILE.write_text(json.dumps(state, indent=2))

def logwatch_miningcore():
    log_line(f"Logwatch starting (pid={os.getpid()}) container={MININGCORE_CONTAINER}")
    
    HEIGHT_STATUS_FILE.write_text("MININGCORE HEARTBEAT: waiting for next block...\n")

    # Tail logs from "now" so we don't re-alert old wins after restarts
    cmd = ["docker", "logs", "-f", "--since", "0s", MININGCORE_CONTAINER]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

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
                HEIGHT_STATUS_FILE.write_text(msg + "\n")
                log_line(msg)
            continue


        # True win: submit + accept
        m = RE_SUBMIT.search(s)
        if m:
            height = int(m.group(1))
            hsh = m.group(2)
            msg = f"POOL BLOCK SUBMITTED: height={height} hash={hsh}"
            POOLBLOCK_STATUS_FILE.write_text(msg + "\n")
            log_line(msg)
            continue

        m = RE_ACCEPT.search(s)
        if m:
            height = int(m.group(1))
            hsh = m.group(2)
            who = m.group(3)
            msg = f"POOL BLOCK ACCEPTED: height={height} hash={hsh} by={who}"
            POOLBLOCK_STATUS_FILE.write_text(msg + "\n")
            log_line(msg)
            continue

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
