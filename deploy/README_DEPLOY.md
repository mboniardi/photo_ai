# Photo AI Manager — Deploy Guide

Deploy Photo AI Manager on a Hyper-V VM running Ubuntu 22.04 with Docker.

---

## Prerequisites (one-time setup)

### Windows
| Requirement | How |
|---|---|
| **Hyper-V** enabled | *Turn Windows features on or off* → Hyper-V, then reboot |
| **PowerShell 7+** | `winget install Microsoft.PowerShell` — open as **Administrator** |
| **Git** | `winget install Git.Git` |
| **WSL2** | `wsl --install`, then reboot |

### WSL2 (run once inside WSL2)
```bash
sudo apt-get update
sudo apt-get install -y qemu-utils genisoimage
```

### Execution policy (run once in PowerShell 7)
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Google OAuth setup (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → *APIs & Services* → *Credentials*
2. Create an **OAuth 2.0 Client ID** — type: **Web application**
3. Add Authorized redirect URI:
   ```
   http://<your-hostname-or-domain>:<APP_PORT>/auth/callback
   ```
   Use a hostname, not a raw IP — Google blocks OAuth redirects to private IP addresses (192.168.x.x, 172.x.x.x, 10.x.x.x).
   Options:
   - A real DNS record pointing to the VM IP (e.g. `photoai.yourdomain.org`)
   - A Windows hosts file entry: `172.x.x.x  photoai.local`
4. Copy **Client ID** and **Client Secret** into `deploy.config.ps1`

---

## Gemini API setup (one-time)

1. Go to [aistudio.google.com](https://aistudio.google.com) → *Get API key*
2. Create an API key and copy it into `deploy.config.ps1` as `$GEMINI_API_KEY`
3. The free tier works with rate limits — billing not required
4. Default model: `gemini-2.5-flash` (configurable via `GEMINI_MODEL` in `.env`)
5. Embedding is disabled by default (`GEMINI_EMBED_MODEL=`) as most free-tier accounts lack access

---

## Configuration

```powershell
Copy-Item deploy\deploy.config.ps1.example deploy\deploy.config.ps1
notepad deploy\deploy.config.ps1
```

Key fields:

| Field | Description |
|---|---|
| `$VM_STATIC_IP` | Fixed LAN IP for the VM (e.g. `172.24.24.67`) |
| `$VM_GATEWAY` | Your router IP |
| `$VM_DNS` | DNS server (usually same as gateway) |
| `$VM_NETMASK` | Subnet prefix length (e.g. `24`) |
| `$HYPERV_SWITCH` | Hyper-V virtual switch name — use `Get-VMSwitch` to list |
| `$NAS_SERVER` | Hostname or IP of the SMB server (e.g. `dl380.boniardi.org`) |
| `$NAS_SHARE` | SMB share name (e.g. `Media`) |
| `$NAS_PHOTOS_SUBDIR` | Subfolder inside the share with photos. Leave empty if photos are at the root. |
| `$NAS_USER` / `$NAS_PASSWORD` | SMB credentials — written to `/etc/nas-credentials` (chmod 600) |
| `$APP_GIT_REPO` | `https://github.com/mboniardi/photo_ai.git` |
| `$GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `$GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `$GEMINI_API_KEY` | From Google AI Studio |
| `$AUTHORIZED_EMAILS` | `@("you@gmail.com")` — who can log in |
| `$EXCLUDED_EXTS` | File extensions to skip during scan (e.g. `".cr3"` to skip RAW files) |
| `$CONSOLE_PASSWD` | Password for SSH/console access to the VM during testing |
| `$HEALTH_TIMEOUT_SEC` | `900` — first boot installs Docker and pulls images, takes 5-15 min |

> **IMPORTANT:** `deploy.config.ps1` contains secrets. It is in `.gitignore` — never commit it.

### Additional `.env` variables (set manually on VM if needed)

These are not in `deploy.config.ps1` but can be set in `/opt/photo_ai/.env` on the VM:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini vision model |
| `GEMINI_EMBED_MODEL` | _(empty)_ | Embedding model — leave empty on free tier |
| `EXCLUDED_EXTS` | _(from config)_ | Comma-separated extensions to skip (e.g. `.cr3,.nef`) |
| `MAX_SIDE_PX` | `1280` | Max image side before sending to AI |
| `JPEG_QUALITY` | `85` | JPEG quality for AI uploads |
| `TARGET_MAX_KB` | `800` | Max KB for AI image — quality auto-reduced if exceeded |

---

## Running the deploy

Open **PowerShell 7 as Administrator**:

```powershell
cd C:\photo_ai
git pull
.\deploy\deploy.ps1
```

### What the script does

| Phase | Action |
|---|---|
| 1 | Load config, check Hyper-V + WSL2, **stop any existing PhotoAI VMs** |
| 2 | Download and cache Ubuntu 22.04 cloud image, convert to VHDX, resize |
| 3 | Generate cloud-init ISO with: static IP (netplan), `.env`, authorized emails |
| 4 | Create Hyper-V Gen2 VM, disable Secure Boot (Linux compatible), attach disks |
| 5 | Start VM, poll `http://$VM_STATIC_IP:$APP_PORT/health` until ready |
| 6 | Smoke test `/health` and `/auth/login` |
| 7 | Remove old PhotoAI VMs and their VHDX files |

Cloud-init on first boot:
- Installs Docker CE via `get.docker.com`
- Clones the git repo to `/opt/photo_ai`
- Mounts NAS via SMB (photos read-only, `photo_ai_data` writable for DB backup)
- Runs `docker compose up -d --build`

### First deploy timeline
- Phase 2: ~5 min (downloads ~600 MB Ubuntu image — cached on subsequent deploys)
- Phase 5: 5-15 min (Ubuntu installs Docker, builds image, starts container)
- Re-deploy (cached image): ~8-12 min total

---

## Architecture

```
Windows Host (Hyper-V)
└── Ubuntu 22.04 VM  (/opt/photo_ai)
    └── Docker container (photo_ai)
        ├── FastAPI app  (port 8080)
        ├── SQLite DB    (/opt/photo_ai/data/photo_ai.db)
        └── NAS mount    (/mnt/nas  — read-only except photo_ai_data/)
```

**DB persistence:** The SQLite DB lives at `/opt/photo_ai/data/photo_ai.db` (inside VM, persists across container restarts). On shutdown, it's also backed up to `/mnt/nas/photo_ai_data/photo_ai.db` (NAS) — survives VM recreation.

---

## VM access

The deploy script prints at the end:
```
URL: http://172.x.x.x:8080
Console login: user=photoai  password=<CONSOLE_PASSWD from config>
```

SSH access (after deploy):
```powershell
# If same IP was used before, clear the old host key first:
ssh-keygen -R 172.x.x.x
ssh photoai@172.x.x.x
```

---

## Verifying the app

```bash
# On the VM — check container status:
docker compose -f /opt/photo_ai/docker-compose.yml ps
docker compose -f /opt/photo_ai/docker-compose.yml logs --tail=50 -f

# From Windows browser:
http://172.x.x.x:8080/health   # should return {"status":"ok",...}
http://your-hostname:8080       # login page
```

---

## Updating the app

After pushing new code to git, on the VM:

```bash
cd /opt/photo_ai && git pull && docker compose up -d --build
```

`--build` is required whenever Python code or dependencies change. For static file-only changes it's also required (files are baked into the image via `COPY . .`).

---

## Queue worker debugging

```bash
# Check queue status in DB:
docker compose exec photo_ai python3 -c "
import sqlite3
conn = sqlite3.connect('/opt/photo_ai/data/photo_ai.db')
for row in conn.execute('SELECT id, photo_id, status, attempts, error_msg FROM analysis_queue ORDER BY id DESC LIMIT 20'):
    print(row)
"

# Reset errored items back to pending:
docker compose exec photo_ai python3 -c "
import sqlite3
conn = sqlite3.connect('/opt/photo_ai/data/photo_ai.db')
r = conn.execute(\"UPDATE analysis_queue SET status='pending', attempts=0, error_msg=NULL WHERE status='error'\")
conn.commit()
print(f'Reset: {r.rowcount} items')
"
```

---

## Removing CR3/RAW files already indexed

```bash
docker compose exec photo_ai python3 -c "
import sqlite3
conn = sqlite3.connect('/opt/photo_ai/data/photo_ai.db')
r = conn.execute(\"DELETE FROM photos WHERE filename LIKE '%.cr3' OR filename LIKE '%.CR3'\")
conn.commit()
print(f'Removed: {r.rowcount} records')
"
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `Get-WindowsFeature not recognized` | You are on Windows 11 — script uses `Get-Service vmms` instead |
| `execution policy` error | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Script requires PowerShell 7 | `winget install Microsoft.PowerShell`, open as Admin |
| `qemu-img not found` | `wsl sudo apt-get install -y qemu-utils` |
| `mkisofs not found` | `wsl sudo apt-get install -y genisoimage` |
| VM gets no IP | Static IP via cloud-init — script polls static IP directly |
| apt fails with IPv6 errors | Fixed: cloud-init writes `/etc/apt/apt.conf.d/99force-ipv4` |
| Google OAuth `redirect_uri_mismatch` | Use a hostname (not raw IP) in redirect URI |
| SSH `WARNING: REMOTE HOST IDENTIFICATION` | `ssh-keygen -R <VM_IP>` then reconnect |
| `deploy.config.ps1` missing | Copy from `.example` and fill in secrets — not in git |
| DB lost after VM recreation | Fixed: `/mnt/nas/photo_ai_data` is mounted writable for DB backup |
| Embedding 404 errors | Set `GEMINI_EMBED_MODEL=` (empty) in `.env` — free tier has no embedding access |
| 503 errors from Gemini | Free tier overload — queue auto-pauses 60s and retries |
| Photos not disappearing after trash | Fixed: normal view always filters `is_trash=false` |

---

## Files in this directory

| File | Purpose |
|---|---|
| `deploy.ps1` | Main deploy script |
| `deploy.config.ps1.example` | Config template — safe to commit |
| `deploy.config.ps1` | Your config with secrets — **never commit** |
| `README_DEPLOY.md` | This file |
| `cache/` | Downloaded image cache (auto-created, git-ignored) |
| `vms/` | Working VHDXs and cloud-init ISOs (auto-created, git-ignored) |
