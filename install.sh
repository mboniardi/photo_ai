#!/usr/bin/env bash
# install.sh — Photo AI Manager — Docker setup on Ubuntu 22.04
# Run as root on the target VM after git clone.
set -euo pipefail

APP_DIR="/opt/photo_ai"

# ── 0. Verifica .env ──────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: $APP_DIR/.env non trovato."
    echo "Crea il file con le variabili richieste prima di eseguire install.sh."
    echo "Esempio: cp $APP_DIR/.env.example $APP_DIR/.env && nano $APP_DIR/.env"
    exit 1
fi

# ── 1. Install Docker CE ──────────────────────────────────────────
echo "[1/2] Installing Docker CE…"
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# ── 2. Start container ────────────────────────────────────────────
echo "[2/2] Building and starting Photo AI container…"
cd "$APP_DIR"
docker compose up -d --build

# ── Done ──────────────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
PORT=$(grep '^APP_PORT=' "$APP_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 8080)
echo ""
echo "Photo AI Manager avviato su http://${IP}:${PORT}"
