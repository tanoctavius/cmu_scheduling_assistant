#!/bin/bash
# =============================================================================
# EC2 User Data — CMU Scheduling Assistant (FastAPI + React/Vite stack)
# Paste into "Advanced details → User data" when launching the instance.
# Runs ONCE on first boot. Ubuntu 24.04, t3.small recommended.
#
# BEFORE PASTING: set REPO_URL to your repo. If private, use a GitHub
# fine-grained token: https://<TOKEN>@github.com/tanoctavius/cmu_scheduling_assistant.git
# =============================================================================
set -e
exec > /var/log/user-data.log 2>&1   # everything logged here for debugging

REPO_URL="https://github.com/tanoctavius/cmu_scheduling_assistant.git"
APP_DIR="/opt/app"

# --- Base packages -----------------------------------------------------------
apt-get update -y
apt-get install -y git curl ca-certificates

# --- Node 20 (Ubuntu 24.04 repo version is too old) --------------------------
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g serve

# --- uv (manages Python 3.11 + backend deps per their pyproject) -------------
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# --- Clone -------------------------------------------------------------------
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

# --- Backend deps (uv downloads the right Python automatically) --------------
cd "$APP_DIR/backend"
uv sync
# The LLM stub is the default and needs nothing extra. For a real model, write
# LLM_PROVIDER/LLM_MODEL/GROQ_API_KEY into backend/.env (systemd loads it via
# EnvironmentFile below) — no additional dependency is required.

# --- Frontend deps -----------------------------------------------------------
cd "$APP_DIR/frontend"
npm install

# --- Install deploy scripts from the repo (or inline copies) -----------------
# refresh-ip.sh rewrites VITE_BACKEND_URL with the CURRENT public IP and
# rebuilds the frontend. It runs on EVERY boot because the IP changes
# every Learner Lab session.
cat > /usr/local/bin/refresh-ip.sh << 'SCRIPT'
#!/bin/bash
set -e
APP_DIR="/opt/app"

# EC2 metadata (IMDSv2) → current public IP
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4)

echo "Current public IP: $PUBLIC_IP"

# Point the frontend at the backend on this IP, rebuild
echo "VITE_BACKEND_URL=http://$PUBLIC_IP:8000" > "$APP_DIR/frontend/.env"
cd "$APP_DIR/frontend"
npm run build

echo "Frontend rebuilt for $PUBLIC_IP"
SCRIPT
chmod +x /usr/local/bin/refresh-ip.sh

# --- systemd: backend (FastAPI via uv/uvicorn on :8000) ----------------------
cat > /etc/systemd/system/scheduler-backend.service << 'EOF'
[Unit]
Description=CMU Scheduler backend (FastAPI)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/app/backend
ExecStart=/usr/local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
# Real LLM key goes in this file later (stub runs fine without it):
EnvironmentFile=-/opt/app/backend/.env

[Install]
WantedBy=multi-user.target
EOF

# --- systemd: IP refresh (oneshot, every boot, before frontend) --------------
cat > /etc/systemd/system/scheduler-refresh.service << 'EOF'
[Unit]
Description=Rebuild frontend with current public IP
After=network-online.target
Wants=network-online.target
Before=scheduler-frontend.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/refresh-ip.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# --- systemd: frontend (serves built dist on :80) -----------------------------
cat > /etc/systemd/system/scheduler-frontend.service << 'EOF'
[Unit]
Description=CMU Scheduler frontend (static build)
After=scheduler-refresh.service
Requires=scheduler-refresh.service

[Service]
Type=simple
ExecStart=/usr/bin/npx serve -s /opt/app/frontend/dist -l 80
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable scheduler-backend scheduler-refresh scheduler-frontend
systemctl start scheduler-backend
systemctl start scheduler-refresh
systemctl start scheduler-frontend

echo "=== DONE. Frontend on :80, backend on :8000. ==="
echo "=== Check: curl http://localhost:8000/health ==="
