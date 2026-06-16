#!/bin/bash
set -e

echo "=== Content Machine 2000 Setup ==="

# Update & install Python
apt-get update -y
apt-get install -y python3 python3-venv python3-pip

# Create app directory and copy files
APP_DIR=/opt/content-machine
mkdir -p $APP_DIR
cp -r . $APP_DIR/
cd $APP_DIR

# Virtual environment
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# Data directory
mkdir -p $APP_DIR/data

# Write .env (keys filled in by deploy.sh)
if [ ! -f $APP_DIR/.env ]; then
cat > $APP_DIR/.env << 'ENVEOF'
APIFY_API_TOKEN=REPLACE_ME
ANTHROPIC_API_KEY=REPLACE_ME
LINKEDIN_PROFILE_URL=https://www.linkedin.com/in/wericmason/
DASHBOARD_PASSWORD=content2000
ENVEOF
echo "!! Edit $APP_DIR/.env with your API keys before starting the service."
fi

# Systemd service
cat > /etc/systemd/system/content-machine.service << 'SVCEOF'
[Unit]
Description=Content Machine 2000
After=network.target

[Service]
User=root
WorkingDirectory=/opt/content-machine
EnvironmentFile=/opt/content-machine/.env
ExecStart=/opt/content-machine/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable content-machine

echo ""
echo "=== Setup complete ==="
echo "Next: edit /opt/content-machine/.env then run: systemctl start content-machine"
echo "Dashboard will be at: http://$(hostname -I | awk '{print $1}'):8000"
