#!/usr/bin/env bash
set -euo pipefail

# teardown_local_forward.sh
# Usage: sudo ./teardown_local_forward.sh

DOMAIN="css-ai-dev-openai-east.openai.azure.com"
DNSMASQ_CONF_DIR="$(brew --prefix 2>/dev/null || echo /usr/local)/etc/dnsmasq.d"
DNSMASQ_CONF_FILE="$DNSMASQ_CONF_DIR/azure-grader.conf"
RESOLVER_DIR="/etc/resolver"
RESOLVER_FILE="$RESOLVER_DIR/$DOMAIN"
PIDFILE="/tmp/azure-grader-proxy.pid"

if [ "$EUID" -ne 0 ]; then
  echo "This script must be run with sudo. Re-run: sudo $0" >&2
  exit 1
fi

echo "Stopping azure-grader-proxy if running..."
if [ -f "$PIDFILE" ]; then
  kill "$(cat $PIDFILE)" 2>/dev/null || true
  rm -f "$PIDFILE"
fi

if [ -f "$DNSMASQ_CONF_FILE" ]; then
  rm -f "$DNSMASQ_CONF_FILE"
  echo "Removed $DNSMASQ_CONF_FILE"
  brew services restart dnsmasq || true
fi

if [ -f "$RESOLVER_FILE" ]; then
  rm -f "$RESOLVER_FILE"
  echo "Removed resolver $RESOLVER_FILE"
fi

echo "Teardown complete."
