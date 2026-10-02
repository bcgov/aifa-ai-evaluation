#!/usr/bin/env bash
set -euo pipefail

# setup_local_forward.sh
# Usage: sudo ./setup_local_forward.sh
# This script configures dnsmasq + macOS resolver so that
# css-ai-dev-openai-east.openai.azure.com resolves to 127.0.0.1
# and starts the local azure-grader-proxy which forwards requests
# to the real Azure endpoint via the SOCKS5 proxy.

DOMAIN="css-ai-dev-openai-east.openai.azure.com"
PROXY_PORT=8002
if [ "$EUID" -eq 0 ] && [ -n "${SUDO_USER-}" ]; then
  # When run under sudo, run brew as the original user to avoid Homebrew root errors
  BREW_USER="$SUDO_USER"
  BREW_PREFIX="$(sudo -u "$BREW_USER" brew --prefix 2>/dev/null || echo /usr/local)"
  BREW_CMD_PREFIX=(sudo -u "$BREW_USER" brew)
else
  BREW_USER=""
  BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /usr/local)"
  BREW_CMD_PREFIX=(brew)
fi

DNSMASQ_CONF_DIR="$BREW_PREFIX/etc/dnsmasq.d"
DNSMASQ_CONF_FILE="$DNSMASQ_CONF_DIR/azure-grader.conf"
RESOLVER_DIR="/etc/resolver"
RESOLVER_FILE="$RESOLVER_DIR/$DOMAIN"
PROXY_SCRIPT="$(pwd)/azure-grader-proxy.js"
PIDFILE="/tmp/azure-grader-proxy.pid"

if [ "$EUID" -ne 0 ]; then
  echo "This script must be run with sudo. Re-run: sudo $0" >&2
  exit 1
fi

echo "Setting up local DNS forwarding for $DOMAIN -> 127.0.0.1"

# Check Homebrew
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Please install Homebrew from https://brew.sh and re-run." >&2
  exit 1
fi

# Ensure dnsmasq is installed (run brew as non-root user when invoked with sudo)
if ! "${BREW_CMD_PREFIX[@]}" list dnsmasq >/dev/null 2>&1; then
  echo "Installing dnsmasq via Homebrew..."
  "${BREW_CMD_PREFIX[@]}" install dnsmasq
fi

mkdir -p "$DNSMASQ_CONF_DIR"
echo "address=/$DOMAIN/127.0.0.1" > "$DNSMASQ_CONF_FILE"
echo "Wrote dnsmasq config to $DNSMASQ_CONF_FILE"

echo "Restarting dnsmasq service..."
"${BREW_CMD_PREFIX[@]}" services restart dnsmasq

mkdir -p "$RESOLVER_DIR"
cat > "$RESOLVER_FILE" <<EOF
nameserver 127.0.0.1
port 53
timeout 5
EOF
echo "Wrote resolver file $RESOLVER_FILE"

# Start azure-grader-proxy if not already running
if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" >/dev/null 2>&1; then
  echo "azure-grader-proxy already running (pid $(cat $PIDFILE))"
else
  echo "Starting azure-grader-proxy (node $PROXY_SCRIPT)..."
  # Ensure NODE env loaded from evaluation/.env if present
  if [ -f ../.env ]; then
    # shellcheck disable=SC1090
    source ../.env
  fi
  nohup node "$PROXY_SCRIPT" >/tmp/azure-grader-proxy.log 2>&1 &
  echo $! > "$PIDFILE"
  echo "Started azure-grader-proxy (pid $(cat $PIDFILE)), logs: /tmp/azure-grader-proxy.log"
fi

echo "Setup complete. To tear down, run: sudo ./teardown_local_forward.sh"
