# Photo AI Manager — Deploy Guide

This guide covers deploying Photo AI Manager to a Hyper-V VM running Ubuntu 22.04.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 10/11 Pro or Server with **Hyper-V** enabled | Enable via *Turn Windows features on or off* |
| **WSL2** with a Ubuntu distro | `wsl --install` — must have `qemu-utils` and `genisoimage` installed inside WSL |
| **Windows ADK** (optional but recommended) | Provides `oscdimg.exe` for creating the cloud-init ISO; download from [Microsoft](https://learn.microsoft.com/en-us/windows-hardware/get-started/adk-install). If not installed, `mkisofs` via WSL2 is used as fallback. |
| PowerShell 7+ | `winget install Microsoft.PowerShell` |
| Run as **Administrator** | Required for Hyper-V cmdlets |

Install WSL2 dependencies (run once inside WSL2):
```bash
sudo apt-get install -y qemu-utils genisoimage
```

---

## One-time Google OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → *APIs & Services* → *Credentials*.
2. Create an **OAuth 2.0 Client ID** (Web application).
3. Add the following Authorized redirect URI:
   ```
   http://<VM_STATIC_IP>:8080/auth/callback
   ```
4. Copy the **Client ID** and **Client Secret** into your `deploy.config.ps1`.

---

## Configuration

1. Copy the example config:
   ```powershell
   Copy-Item deploy\deploy.config.ps1.example deploy\deploy.config.ps1
   ```
2. Edit `deploy\deploy.config.ps1` and set:
   - `$VM_STATIC_IP` — the fixed LAN IP for the VM
   - `$VM_GATEWAY`, `$VM_DNS` — your router/DNS
   - `$HYPERV_SWITCH` — name of your Hyper-V virtual switch
   - `$NAS_PHOTOS_PATH`, `$NAS_DATA_PATH`, `$NAS_USER`, `$NAS_PASSWORD`
   - `$APP_GIT_REPO` — URL of your photo_ai git repository
   - `$GOOGLE_CLIENT_ID`, `$GOOGLE_CLIENT_SECRET`
   - `$GEMINI_API_KEY`
   - `$AUTHORIZED_EMAILS` — list of Gmail addresses allowed to log in

> **IMPORTANT:** `deploy.config.ps1` contains secrets and MUST NOT be committed to git.
> It is listed in `.gitignore` — verify it stays there.

---

## Running the deploy

Open **PowerShell 7+ as Administrator**, then:

```powershell
cd C:\path\to\photo_ai
.\deploy\deploy.ps1
```

The script performs 8 phases automatically:

| Phase | Action |
|-------|--------|
| 1 | Load config, check Hyper-V and WSL2, generate VM name |
| 2 | Download (and cache) Ubuntu 22.04 cloud image, convert to VHDX |
| 3 | Generate cloud-init `meta-data` + `user-data`, create ISO |
| 4 | Create Hyper-V Gen2 VM, attach disk and cloud-init ISO |
| 5 | Start VM, wait for `/health` endpoint (up to `$HEALTH_TIMEOUT_SEC`) |
| 6 | Smoke test `/health` and `/auth/login` |
| 7 | SSH into VM, apply static IP via netplan |
| 8 | Final health check on static IP, remove old VM |

---

## Rollback

If the health check times out in Phase 5, the script automatically stops and removes the new VM and exits with code 1. The old VM (if any) is left running.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `qemu-img: not found` | Run `sudo apt-get install -y qemu-utils` inside WSL2 |
| `mkisofs: not found` | Run `sudo apt-get install -y genisoimage` inside WSL2 |
| Health check times out | SSH into VM as `photoai` and check `journalctl -u photo_ai -n 50` |
| SSH key rejected in Phase 7 | The deploy uses password-less sudo — ensure cloud-init completed successfully |
| Static IP unreachable after Phase 7 | The SSH session is interrupted when netplan changes the IP; this is expected. Wait ~15s and retry. |

---

## Files in this directory

| File | Purpose |
|------|---------|
| `deploy.ps1` | Main deploy script (Hyper-V) |
| `deploy.config.ps1.example` | Config template — safe to commit |
| `deploy.config.ps1` | Your local config with secrets — **never commit** |
| `README_DEPLOY.md` | This file |
| `cache/` | Downloaded image cache (auto-created, git-ignored) |
| `vms/` | Working VHDXs and cloud-init ISOs (auto-created, git-ignored) |
