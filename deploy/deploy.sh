#!/usr/bin/env bash
# Pulls the latest code, updates dependencies, and restarts the app.
# Run as the threeohone user (which has passwordless sudo for the
# systemctl step): /home/threeohone/Redirect-Tool/deploy/deploy.sh
set -euo pipefail

APP_DIR="/home/threeohone/Redirect-Tool"
SERVICE="threeohone"

cd "$APP_DIR"

echo "==> Pulling latest code..."
git pull

echo "==> Installing/updating dependencies..."
.venv/bin/pip install -r requirements.txt

echo "==> Restarting service..."
sudo systemctl restart "$SERVICE"

sleep 2
echo "==> Status:"
sudo systemctl status "$SERVICE" --no-pager -l
