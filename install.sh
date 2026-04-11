#!/usr/bin/env bash
# install.sh — Photo AI Manager — Ubuntu 22.04 server setup
# Run as root on the target VM.
set -euo pipefail

APP_DIR="/opt/photo_ai"
VENV="$APP_DIR/venv"
SERVICE_FILE="/etc/systemd/system/photo_ai.service"
APP_USER="photoai"

# ── 1. System packages ────────────────────────────────────────────
echo "[1/6] Updating system packages…"
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    libheif-dev libraw-dev \
    git curl

# ── 2. Create system user ─────────────────────────────────────────
echo "[2/6] Creating system user '$APP_USER'…"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    echo "  User '$APP_USER' created."
else
    echo "  User '$APP_USER' already exists — skipping."
fi

# ── 3. Deploy application files ───────────────────────────────────
echo "[3/6] Deploying application files to $APP_DIR…"
mkdir -p "$APP_DIR"
# Copy project files from the current directory (excluding .git, venv, __pycache__)
rsync -a --exclude='.git' --exclude='venv' --exclude='.venv' \
      --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' \
      "$(cd "$(dirname "$0")" && pwd)/" "$APP_DIR/"

# Create local data directory
mkdir -p "$APP_DIR/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ── 4. Python virtual environment ────────────────────────────────
echo "[4/6] Creating Python venv and installing requirements…"
python3.11 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── 5. Write .env from environment (cloud-init passes vars here) ──
echo "[5/6] Writing /opt/photo_ai/.env…"

# Source /etc/environment if it exists (cloud-init may write vars there)
if [ -f /etc/environment ]; then
    set -o allexport
    # shellcheck disable=SC1091
    source /etc/environment || true
    set +o allexport
fi

if [ -n "${GOOGLE_CLIENT_ID:-}" ]; then
    cat > "$APP_DIR/.env" <<EOF
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}
SECRET_KEY=${SECRET_KEY:-$(python3.11 -c "import secrets; print(secrets.token_hex(32))")}
GEMINI_API_KEY=${GEMINI_API_KEY:-}
AUTHORIZED_EMAILS_PATH=${AUTHORIZED_EMAILS_PATH:-/mnt/nas/photo_ai_data/authorized_emails.txt}
APP_DATA_PATH=${APP_DATA_PATH:-/mnt/nas/photo_ai_data}
LOCAL_DB=${LOCAL_DB:-/opt/photo_ai/data/photo_ai.db}
NAS_CIFS_USER=${NAS_CIFS_USER:-}
NAS_CIFS_PASSWORD=${NAS_CIFS_PASSWORD:-}
APP_PORT=${APP_PORT:-8080}
EOF
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    echo "  .env written from environment variables."
elif [ -f "$APP_DIR/.env" ]; then
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
    echo "  Existing .env found — keeping it."
else
    echo "  WARNING: No GOOGLE_CLIENT_ID in environment and no .env found."
    echo "  Create $APP_DIR/.env manually before starting the service."
fi

# ── 6. Systemd service ────────────────────────────────────────────
echo "[6/6] Installing systemd service…"
cat > "$SERVICE_FILE" <<'UNIT'
[Unit]
Description=Photo AI Manager
After=network.target
Wants=network.target

[Service]
Type=simple
User=photoai
WorkingDirectory=/opt/photo_ai
EnvironmentFile=/opt/photo_ai/.env
ExecStart=/opt/photo_ai/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${APP_PORT:-8080}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=photo_ai

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable photo_ai
systemctl start photo_ai

# ── Done ──────────────────────────────────────────────────────────
VM_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "✅ Photo AI Manager avviato su http://${VM_IP}:${APP_PORT:-8080}"
