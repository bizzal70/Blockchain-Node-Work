#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------
# Miningcore wallet-guard startup wrapper
# ---------------------------------------
# Runs as PID 1 (via docker-compose command) so it:
# 1) Verifies payout wallet before Miningcore starts
# 2) Emits a heartbeat line periodically
# 3) Kills the container if the wallet ever changes at runtime
#
# Override any of these via environment variables if you want.
# ---------------------------------------

CONFIG_FILE="${CONFIG_FILE:-/data/pool/config/miningcore.json}"

# Your known-good DigiByte legacy address:
EXPECTED_WALLET="${EXPECTED_WALLET:-DM2frgUqF3PhXfThFC3wQppdn6DNCaDr3U}"

CHECK_INTERVAL="${CHECK_INTERVAL:-30}"

# Where to publish heartbeat for nginx/static serving (adjust to your setup)
HEARTBEAT_WEB="${HEARTBEAT_WEB:-/walletguard/www/heartbeat.txt}"
HEARTBEAT_LOG="${HEARTBEAT_LOG:-/walletguard/www/heartbeat.log}"

die() {
  echo "[wallet-guard] ❌ $*" >&2
  exit 1
}

# Atomic write so the web file is never half-written
publish_heartbeat() {
  local line="$1"
  local dir tmp
  dir="$(dirname "$HEARTBEAT_WEB")"
  mkdir -p "$dir"
  tmp="$dir/heartbeat.$$.$RANDOM.tmp"
  printf "%s\n" "$line" > "$tmp"
  mv -f "$tmp" "$HEARTBEAT_WEB"
  printf "%s\n" "$line" >> "$HEARTBEAT_LOG"
}

read_wallet_from_config() {
  # Extract first "address": "..." in the file (simple + dependency-free)
  grep -oE '"address"\s*:\s*"[^"]+"' "$CONFIG_FILE" | head -n1 | cut -d'"' -f4 || true
}

echo "[wallet-guard] Starting..."
echo "[wallet-guard] Config: $CONFIG_FILE"
echo "[wallet-guard] Expected wallet: $EXPECTED_WALLET"
echo "[wallet-guard] Check interval: ${CHECK_INTERVAL}s"
echo "[wallet-guard] Heartbeat web: $HEARTBEAT_WEB"
echo "[wallet-guard] Heartbeat log: $HEARTBEAT_LOG"

[ -f "$CONFIG_FILE" ] || die "Config file not found: $CONFIG_FILE"

FOUND_WALLET="$(read_wallet_from_config)"
[ -n "$FOUND_WALLET" ] || die "Could not read payout wallet from config (no address field found)"

# ---- Startup enforcement ----
if [ "$FOUND_WALLET" != "$EXPECTED_WALLET" ]; then
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  publish_heartbeat "[wallet-guard] 🔥 STARTUP WALLET MISMATCH $ts expected=$EXPECTED_WALLET found=$FOUND_WALLET"
  die "Startup wallet mismatch. expected=$EXPECTED_WALLET found=$FOUND_WALLET"
fi

ts="$(date '+%Y-%m-%d %H:%M:%S')"
publish_heartbeat "[wallet-guard] OK $ts $FOUND_WALLET"

# ---- Runtime wallet sentry (background) ----
(
  while true; do
    sleep "$CHECK_INTERVAL"

    CURRENT_WALLET="$(read_wallet_from_config)"

    if [ "$CURRENT_WALLET" != "$EXPECTED_WALLET" ]; then
      ts="$(date '+%Y-%m-%d %H:%M:%S')"
      publish_heartbeat "[wallet-guard] 🔥 RUNTIME WALLET CHANGE $ts expected=$EXPECTED_WALLET found=$CURRENT_WALLET — KILLING"
      echo "[wallet-guard] 🔥 RUNTIME WALLET CHANGE DETECTED"
      echo "Expected: $EXPECTED_WALLET"
      echo "Found:    $CURRENT_WALLET"
      echo "[wallet-guard] 🛑 KILLING MININGCORE (PID 1)"
      kill -TERM 1
      exit 1
    fi

    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    HB_LINE="[wallet-guard] OK $ts $CURRENT_WALLET"
    echo "$HB_LINE"
    publish_heartbeat "$HB_LINE"
  done
) &

# ---- Start Miningcore (PID 1) ----
exec /app/Miningcore -c "$CONFIG_FILE"
