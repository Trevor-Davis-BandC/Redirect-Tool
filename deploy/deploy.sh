#!/usr/bin/env bash
# Pulls the latest code, updates dependencies, and restarts the app.
# Run as root: /home/threeohone/Redirect-Tool/deploy/deploy.sh
set -euo pipefail

APP_USER="threeohone"
APP_DIR="/home/threeohone/Redirect-Tool"
SERVICE="threeohone"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root." >&2
  exit 1
fi

echo "==> Pulling latest code..."
su - "$APP_USER" -c "cd '$APP_DIR' && git pull"

echo "==> Installing/updating dependencies..."
su - "$APP_USER" -c "cd '$APP_DIR' && .venv/bin/pip install -r requirements.txt"

echo "==> Restarting service..."
systemctl restart "$SERVICE"

sleep 2
echo "==> Status:"
systemctl status "$SERVICE" --no-pager -l
