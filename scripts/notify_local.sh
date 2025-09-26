#!/bin/bash
# Local notification script for alert testing

# Extract environment variables set by alerts_runner.py
MESSAGE="${ALERT_MESSAGE:-No message}"
RULE="${ALERT_RULE:-unknown}"
SEVERITY="${ALERT_SEVERITY:-info}"
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

# Output file for local notifications
OUTPUT_FILE="${NOTIFY_OUTPUT_FILE:-/tmp/alerts_notifications.log}"

# Color codes for terminal output
case "$SEVERITY" in
  critical)
    COLOR="\033[0;31m"  # Red
    EMOJI="🔴"
    ;;
  error)
    COLOR="\033[0;31m"  # Red
    EMOJI="❌"
    ;;
  warn)
    COLOR="\033[0;33m"  # Yellow
    EMOJI="⚠️"
    ;;
  *)
    COLOR="\033[0;36m"  # Cyan
    EMOJI="ℹ️"
    ;;
esac
RESET="\033[0m"

# Format notification
NOTIFICATION="[$TIMESTAMP] $EMOJI [$SEVERITY] $RULE: $MESSAGE"

# Output to console (with color)
echo -e "${COLOR}ALERT: ${NOTIFICATION}${RESET}"

# Append to log file
echo "$NOTIFICATION" >> "$OUTPUT_FILE"

# Optional: System notification (macOS)
if command -v osascript &> /dev/null; then
  osascript -e "display notification \"$MESSAGE\" with title \"Alert: $RULE\" subtitle \"Severity: $SEVERITY\"" 2>/dev/null
fi

# Optional: System notification (Linux with notify-send)
if command -v notify-send &> /dev/null; then
  notify-send -u critical "Alert: $RULE" "$MESSAGE" 2>/dev/null
fi

# Return success
exit 0