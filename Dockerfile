FROM python:3.11-slim

# System deps:
#   libheif-dev  → pillow-heif (HEIC/HEIF support)
#   libraw-dev   → rawpy (RAW camera files)
# `apt-get upgrade` non e' ridondante con una build --pull: l'immagine base
# viene ripubblicata a intervalli, e Debian nel frattempo pubblica patch. Al
# 2026-11-21 python:3.11-slim portava openssl 3.5.7 mentre trixie era gia' a
# 3.5.9. Senza questa riga quelle patch non entrano mai.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        libheif-dev \
        libraw-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/photo_ai

# pip e setuptools dell'immagine base sono vecchi: python:3.11-slim porta
# pip 24.0 e setuptools 79.0.1, che insieme hanno 15 advisory note
# (pip-audit, 2026-11-21). Vanno aggiornati PRIMA di installare qualunque
# cosa, perche' sono loro a fare l'installazione.
RUN pip install --no-cache-dir --upgrade pip setuptools

# Install Python deps as a separate layer (cache-friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Data directory (SQLite DB, authorized_emails.txt, backups)
# In production this path is bind-mounted from the host.
RUN mkdir -p /opt/photo_ai/data

EXPOSE 8080

# Port is fixed at 8080 inside the container.
# Use APP_PORT in docker-compose.yml to remap the host port.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
