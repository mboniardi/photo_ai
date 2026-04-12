# Photo AI Manager — Deploy Guide

Deploy Photo AI Manager on a Hyper-V VM running Ubuntu 22.04.

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
| `$NAS_SERVER` | Hostname o IP del server SMB (es. `dl380.boniardi.org`) |
| `$NAS_SHARE` | Nome della share SMB (es. `Media`) |
| `$NAS_PHOTOS_SUBDIR` | Sottocartella dentro la share con le foto (es. `photos`). Lascia vuoto se le foto sono nella root. |
| `$NAS_USER` / `$NAS_PASSWORD` | Credenziali SMB — scritte in `/etc/nas-credentials` (chmod 600) |
| `$APP_GIT_REPO` | `https://github.com/mboniardi/photo_ai.git` |
| `$GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `$GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `$GEMINI_API_KEY` | From Google AI Studio |
| `$AUTHORIZED_EMAILS` | `@("you@gmail.com")` — who can log in |
| `$CONSOLE_PASSWD` | Password for SSH/console access to the VM during testing |
| `$HEALTH_TIMEOUT_SEC` | `900` — first boot installs packages, takes 5-15 min |

> **IMPORTANT:** `deploy.config.ps1` contains secrets. It is in `.gitignore` — never commit it.

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
| 1 | Load config, check Hyper-V + WSL2, **stop any existing PhotoAI VMs** (same static IP — must stop before new one starts) |
| 2 | Download and cache Ubuntu 22.04 cloud image, convert to VHDX, resize |
| 3 | Generate cloud-init ISO with static IP (netplan), .env, authorized emails |
| 4 | Create Hyper-V Gen2 VM, disable Secure Boot (Linux compatible), attach disks |
| 5 | Start VM, poll `http://$VM_STATIC_IP:$APP_PORT/health` until ready (first boot takes 5-15 min) |
| 6 | Smoke test `/health` and `/auth/login` |
| 7 | Remove old PhotoAI VMs and their VHDX files |

### First deploy timeline
- Phase 2: ~5 min (downloads ~600 MB Ubuntu image — cached on subsequent deploys)
- Phase 5: 5-15 min (Ubuntu installs packages, clones repo, sets up venv)
- Re-deploy (cached image): ~8-12 min total

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

If SSH asks for password auth but is rejected, the VM was provisioned with an older
cloud-init that had `lock_passwd: true`. Re-deploy to get `ssh_pwauth: true`.

Terminal type fix (if commands show "unknown terminal"):
```bash
export TERM=xterm-256color
```

---

## Verifying the app

```bash
# On the VM:
systemctl status photo_ai
journalctl -u photo_ai --no-pager -n 30

# From Windows browser:
http://172.x.x.x:8080/health   # should return {"status":"ok",...}
http://your-hostname:8080       # login page
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `Get-WindowsFeature not recognized` | You are on Windows 11 — script uses `Get-Service vmms` instead (already fixed) |
| `execution policy` error | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| Script requires PowerShell 7 | `winget install Microsoft.PowerShell`, open the black PowerShell icon as Admin |
| `qemu-img not found` | `wsl sudo apt-get install -y qemu-utils` |
| `mkisofs not found` | `wsl sudo apt-get install -y genisoimage` |
| VM gets no IP (DHCP timeout) | Static IP is configured via cloud-init — script polls static IP directly, no DHCP needed |
| apt fails with IPv6 errors | Already fixed: cloud-init writes `/etc/apt/apt.conf.d/99force-ipv4` |
| `python3.11-venv not found` | Already fixed: cloud-init runs `add-apt-repository universe` before apt install |
| Interactive apt dialog blocks install | Already fixed: `DEBIAN_FRONTEND=noninteractive` in `install.sh` |
| `photo_ai.service` fails with `invalid port` | Already fixed: `install.sh` uses `$APP_PORT` (not bash `${VAR:-default}`) in systemd unit |
| `.env` missing after deploy | Already fixed: written to `/tmp/photo_ai.env` and moved after git clone |
| Google OAuth `redirect_uri_mismatch` | Use a hostname (not raw IP) in the redirect URI — Google blocks private IPs |
| Google OAuth `invalid_request` (private IP) | Same as above — use DNS or hosts file entry |
| SSH `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` | `ssh-keygen -R <VM_IP>` then reconnect |
| Old VM not removed | Script now detects by name prefix `PhotoAI-*` (not IP) and stops before new VM starts |

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
