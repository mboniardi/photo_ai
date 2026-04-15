FROM python:3.11-slim

# System deps:
#   libheif-dev  → pillow-heif (HEIC/HEIF support)
#   libraw-dev   → rawpy (RAW camera files)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libheif-dev \
        libraw-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/photo_ai

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
