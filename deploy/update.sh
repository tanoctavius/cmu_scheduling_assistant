#!/bin/bash
# =============================================================================
# Update the running deployment after the team pushes to GitHub.
# Usage (on the EC2 instance):  sudo bash /opt/app/deploy/update.sh
# =============================================================================
set -e
APP_DIR="/opt/app"

cd "$APP_DIR"
echo "Pulling latest code..."
git pull

echo "Syncing backend deps..."
cd "$APP_DIR/backend"
/usr/local/bin/uv sync

echo "Syncing frontend deps + rebuilding with current IP..."
cd "$APP_DIR/frontend"
npm install
/usr/local/bin/refresh-ip.sh

echo "Restarting services..."
systemctl restart scheduler-backend scheduler-frontend

sleep 3
echo ""
echo "Backend health:"
curl -s http://localhost:8000/health || echo "(backend not responding yet — check: journalctl -u scheduler-backend -n 50)"
echo ""
echo "✓ Update complete."
