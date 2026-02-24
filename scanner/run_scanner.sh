#!/bin/bash
# MPS Daily Scanner — shell wrapper for cron
# Runs the RSI(2) scanner after market close and logs output.
#
# Cron runs in a minimal environment (no PATH, no shell profile).
# This script sets everything up explicitly so it works unattended.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/scanner/logs"
LOG_FILE="$LOG_DIR/scanner_$(date +%Y-%m-%d).log"
PYTHON="/Applications/Xcode.app/Contents/Developer/usr/bin/python3"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Scanner started: $(date)" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$PROJECT_DIR"

# Credentials are loaded by python-dotenv inside daily_scan.py — no need to source .env here.
"$PYTHON" -m scanner.daily_scan >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "Scanner finished: $(date) | exit code: $EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
