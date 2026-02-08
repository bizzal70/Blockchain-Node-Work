publish_heartbeat() {
        ts="$(date '+%Y-%m-%d %H:%M:%S')"
        line="[wallet-guard] OK $ts $EXPECTED_WALLET"
        echo "$line" > "$HEARTBEAT_WEB"
        echo "$line" >> "$HEARTBEAT_LOG"


        #line="$1"
        #dir="$(dirname "$HEARTBEAT_WEB")"
        #tmp="$dir/heartbeat.$$.$RANDOM.tmp"
        #printf "%s\n" "$line" > "$tmp"
        #mv -f "$tmp" "$HEARTBEAT_WEB"
}

publish_heartbeat "$FOUND_WALLET"

# ---- Runtime wallet sentry ----
(
while true; do
sleep "$CHECK_INTERVAL"

CURRENT_WALLET=$(grep -oE '"address"\s*:\s*"[^"]+"' "$CONFIG_FILE" | head -n1 | cut -d'"' -f4)

if [ "$CURRENT_WALLET" != "$EXPECTED_WALLET" ]; then
echo "🔥 RUNTIME WALLET CHANGE DETECTE"
echo "Expected: $EXPECTED_WALLET"
echo "Found: $CURRENT_WALLET"
echo "🛑 KILLING MININGCORE"
kill -TERM 1
exit 1
fi

#Heartbeat
HB_LINE="[wallet-guard] OK $(date '+%Y-%m-%d %H:%M:%S') $CURRENT_WALLET"

echo "======================================="
echo "$HB_LINE"
echo "======================================="

publish_heartbeat "$HB_LINE"

done
) &

# ---- Start Miningcore (PID 1) ----
exec /app/Miningcore -c "$CONFIG_FILE"
