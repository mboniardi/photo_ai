#Requires -Version 7.0
<#
.SYNOPSIS
    Photo AI Manager — Hyper-V deploy script.
    Creates a new Ubuntu 22.04 VM from cloud image, provisions it via
    cloud-init, waits for the app to be healthy, swaps to static IP,
    and removes the previous VM.
.NOTES
    Prerequisites: Hyper-V, WSL2, Windows ADK (oscdimg.exe or mkisofs in WSL2)
    Run as Administrator from the repo root:
        .\deploy\deploy.ps1
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function ConvertTo-WslPath([string]$winPath) {
    $drive = $winPath[0].ToString().ToLower()
    $rest  = $winPath.Substring(2) -replace '\\', '/'
    return "/mnt/$drive$rest"
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — Preparation
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 1] Preparation" -ForegroundColor Cyan

# Load config
$configPath = "$PSScriptRoot\deploy.config.ps1"
if (-not (Test-Path $configPath)) {
    Write-Error "Config file not found: $configPath`nCopy deploy.config.ps1.example to deploy.config.ps1 and fill in your values."
    exit 1
}
. $configPath

# Check Hyper-V via vmms service (fast — works on Windows 10/11 and Server)
Write-Host "  Checking Hyper-V…"
$vmms = Get-Service -Name vmms -ErrorAction SilentlyContinue
if (-not $vmms) {
    Write-Error "Hyper-V is not enabled. Run as Admin: Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All"
    exit 1
}

# Check WSL2
Write-Host "  Checking WSL2…"
try {
    $wslStatus = wsl --status 2>&1
} catch {
    $wslStatus = wsl --list 2>&1
}
if ($LASTEXITCODE -ne 0 -and -not $wslStatus) {
    Write-Error "WSL2 is not available. Install WSL2 before running this script."
    exit 1
}

# Check for existing VM with same IP (for cleanup in Phase 8)
Write-Host "  Checking for existing VMs with IP $VM_STATIC_IP…"
$oldVM = $null
Get-VM | ForEach-Object {
    $vmObj = $_
    $ips = (Get-VMNetworkAdapter $vmObj).IPAddresses
    if ($ips -contains $VM_STATIC_IP) {
        $oldVM = $vmObj
        Write-Host "  Found existing VM: $($vmObj.Name) — will be removed after deploy."
    }
}

# Generate unique VM name, secret key, and temporary console password
$VM_NAME        = "$VM_NAME_PREFIX-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$SECRET_KEY     = -join ((0..31) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
$CONSOLE_PASSWD = -join ((1..16) | ForEach-Object { [char](Get-Random -Min 65 -Max 91) })
Write-Host "  New VM name: $VM_NAME"

# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — Ubuntu cloud image
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 2] Ubuntu cloud image" -ForegroundColor Cyan

$IMG_URL   = "https://cloud-images.ubuntu.com/releases/22.04/release/ubuntu-22.04-server-cloudimg-amd64.img"
$CACHE_DIR = "$PSScriptRoot\cache"
$VMS_DIR   = "$PSScriptRoot\vms"

New-Item -ItemType Directory -Force -Path $CACHE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $VMS_DIR   | Out-Null

$imgFile      = "$CACHE_DIR\ubuntu.img"
$baseVhdx     = "$CACHE_DIR\ubuntu-base.vhdx"
$workingVhdx  = "$VMS_DIR\$VM_NAME.vhdx"

# Download if not cached
if (-not (Test-Path $imgFile)) {
    Write-Host "  Downloading Ubuntu 22.04 cloud image…"
    Invoke-WebRequest $IMG_URL -OutFile $imgFile
} else {
    Write-Host "  Using cached image: $imgFile"
}

# Convert .img (qcow2) → .vhdx via WSL2 qemu-img
if (-not (Test-Path $baseVhdx)) {
    Write-Host "  Converting to VHDX (this may take a few minutes)…"
    $imgWsl  = ConvertTo-WslPath $imgFile
    $baseWsl = ConvertTo-WslPath $baseVhdx
    wsl qemu-img convert -f qcow2 -O vhdx "$imgWsl" "$baseWsl"
    if ($LASTEXITCODE -ne 0) { Write-Error "qemu-img convert failed."; exit 1 }
} else {
    Write-Host "  Using cached VHDX: $baseVhdx"
}

# Copy and resize to working VHDX
Write-Host "  Copying and resizing VHDX to ${VM_DISK_GB}GB…"
Copy-Item $baseVhdx $workingVhdx
Resize-VHD -Path $workingVhdx -SizeBytes ($VM_DISK_GB * 1GB)

# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — Cloud-Init ISO
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 3] Cloud-Init ISO" -ForegroundColor Cyan

$ciDir  = "$PSScriptRoot\vms\cloud-init-$VM_NAME"
$ciIso  = "$VMS_DIR\$VM_NAME-cloud-init.iso"
New-Item -ItemType Directory -Force -Path $ciDir | Out-Null

$authorizedEmailsStr = ($AUTHORIZED_EMAILS | ForEach-Object { "  - $_" }) -join "`n"

# meta-data
$instanceId = "photo-ai-$(Get-Date -Format 'yyyyMMddHHmmss')"
@"
instance-id: $instanceId
local-hostname: photoai
"@ | Set-Content "$ciDir\meta-data" -Encoding UTF8

# user-data (cloud-config)
$authorizedEmailsWriteFile = ($AUTHORIZED_EMAILS | ForEach-Object { $_ }) -join "`n"
@"
#cloud-config
hostname: photoai
locale: it_IT.UTF-8
timezone: Europe/Rome
ssh_pwauth: true

users:
  - name: photoai
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: $CONSOLE_PASSWD
    ssh_authorized_keys: []

# Static IP configured from first boot — no DHCP phase needed
write_files:
  - path: /etc/netplan/01-static.yaml
    permissions: '0600'
    content: |
      network:
        version: 2
        ethernets:
          eth0:
            addresses: [$VM_STATIC_IP/$VM_NETMASK]
            routes:
              - to: default
                via: $VM_GATEWAY
            nameservers:
              addresses: [$VM_DNS]

  - path: /opt/photo_ai/.env
    permissions: '0600'
    owner: root:root
    content: |
      GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
      GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
      SECRET_KEY=$SECRET_KEY
      GEMINI_API_KEY=$GEMINI_API_KEY
      AUTHORIZED_EMAILS_PATH=/mnt/nas/photo_ai_data/authorized_emails.txt
      APP_DATA_PATH=/mnt/nas/photo_ai_data
      LOCAL_DB=/opt/photo_ai/data/photo_ai.db
      NAS_CIFS_USER=$NAS_USER
      NAS_CIFS_PASSWORD=$NAS_PASSWORD
      APP_PORT=$APP_PORT

package_update: true
packages:
  - git
  - curl
  - python3.11
  - python3.11-venv
  - python3-pip
  - libheif-dev
  - libraw-dev
  - rsync
  - openssh-server

runcmd:
  - netplan apply
  - mkdir -p /opt/photo_ai
  - git clone $APP_GIT_REPO -b $APP_GIT_BRANCH /opt/photo_ai
  - cp /opt/photo_ai/.env /opt/photo_ai/.env.bak || true
  - bash /opt/photo_ai/install.sh
  - mkdir -p /mnt/nas/photo_ai_data
  - "printf '$authorizedEmailsWriteFile\n' > /mnt/nas/photo_ai_data/authorized_emails.txt || true"
"@ | Set-Content "$ciDir\user-data" -Encoding UTF8

# Create ISO — try oscdimg (Windows ADK) first, fall back to WSL2 mkisofs
$oscdimg = "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
if (Test-Path $oscdimg) {
    Write-Host "  Creating ISO with oscdimg…"
    & $oscdimg -j2 -lcidata "$ciDir" "$ciIso"
    if ($LASTEXITCODE -ne 0) { Write-Error "oscdimg failed."; exit 1 }
} else {
    Write-Host "  oscdimg not found — using WSL2 mkisofs…"
    $ciDirWsl = ConvertTo-WslPath $ciDir
    $ciIsoWsl = ConvertTo-WslPath $ciIso
    wsl mkisofs -output "$ciIsoWsl" -volid cidata -joliet -rational-rock "$ciDirWsl"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "mkisofs failed. Install 'genisoimage' in WSL2: sudo apt-get install -y genisoimage"
        exit 1
    }
}
Write-Host "  Cloud-init ISO: $ciIso"

# ═══════════════════════════════════════════════════════════════════
# PHASE 4 — Create VM
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 4] Creating Hyper-V VM" -ForegroundColor Cyan

$vm = New-VM -Name $VM_NAME `
             -MemoryStartupBytes ($VM_RAM_GB * 1GB) `
             -Generation $VM_GEN `
             -SwitchName $HYPERV_SWITCH

Set-VMProcessor $vm -Count $VM_CPU_COUNT
Add-VMHardDiskDrive $vm -Path $workingVhdx
Add-VMDvdDrive $vm -Path $ciIso

# Secure boot with UEFI CA (required for Ubuntu Gen2)
Set-VMFirmware $vm -SecureBootTemplate MicrosoftUEFICertificateAuthority

# Set boot order: DVD first so cloud-init ISO is read on first boot
$bootDvd  = Get-VMDvdDrive $vm
$bootDisk = Get-VMHardDiskDrive $vm
Set-VMFirmware $vm -BootOrder $bootDvd, $bootDisk

Write-Host "  VM '$VM_NAME' created."

# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — Start and wait for health check
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 5] Starting VM and waiting for health check" -ForegroundColor Cyan

Start-VM -Name $VM_NAME
Write-Host "  VM started. Static IP configured: $VM_STATIC_IP"
Write-Host "  Polling http://${VM_STATIC_IP}:${APP_PORT}/health (timeout: ${HEALTH_TIMEOUT_SEC}s)…"
Write-Host "  (First boot installs packages — typically 5-10 minutes)" -ForegroundColor DarkGray

$resp = $null
$healthy = $false
$elapsed = 0
do {
    Start-Sleep -Seconds $HEALTH_INTERVAL_SEC
    $elapsed += $HEALTH_INTERVAL_SEC
    try {
        $resp = Invoke-WebRequest "http://${VM_STATIC_IP}:${APP_PORT}/health" `
                                  -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "  Health check passed after ${elapsed}s."
            break
        }
    } catch {
        Write-Host "  [${elapsed}s] Not ready yet…" -ForegroundColor DarkGray
    }
} while ($elapsed -lt $HEALTH_TIMEOUT_SEC)

if (-not $healthy) {
    Write-Warning "Health check timeout after ${HEALTH_TIMEOUT_SEC}s."
    Write-Warning "The VM may still be installing packages. Check http://${VM_STATIC_IP}:${APP_PORT}/health manually."
    Write-Warning "To remove it manually: Stop-VM '$VM_NAME' -Force; Remove-VM '$VM_NAME' -Force -ErrorAction SilentlyContinue; Remove-Item '$workingVhdx' -Force"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 6 — Smoke tests
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 6] Smoke tests" -ForegroundColor Cyan

# GET /health → status == "ok" or "degraded" (NAS may not be mounted yet)
$healthBody = $resp.Content | ConvertFrom-Json
if ($healthBody.status -notin @("ok", "degraded")) {
    Write-Error "Unexpected /health status: $($healthBody.status)"
    exit 1
}
Write-Host "  /health → $($healthBody.status) (version: $($healthBody.version))"

# GET /auth/login → must not be 5xx
try {
    $loginResp = Invoke-WebRequest "http://${VM_STATIC_IP}:${APP_PORT}/auth/login" `
                                   -UseBasicParsing -TimeoutSec 10 -MaximumRedirection 0
    $loginStatus = $loginResp.StatusCode
} catch [System.Net.WebException] {
    $loginStatus = [int]$_.Exception.Response.StatusCode
} catch {
    $loginStatus = 0
}
if ($loginStatus -ge 500) {
    Write-Error "/auth/login returned $loginStatus — server error, aborting."
    exit 1
}
Write-Host "  /auth/login → $loginStatus (redirect to Google is OK)"

# ═══════════════════════════════════════════════════════════════════
# PHASE 7 — Cleanup
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 7] Cleanup" -ForegroundColor Cyan

# Remove old VM and its disk
if ($oldVM) {
    Write-Host "  Stopping and removing old VM: $($oldVM.Name)…"
    $oldVhdx = (Get-VMHardDiskDrive $oldVM).Path
    Stop-VM -Name $oldVM.Name -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Remove-VM -Name $oldVM.Name -Force -ErrorAction SilentlyContinue
    if ($oldVhdx) { Remove-Item $oldVhdx -Force -ErrorAction SilentlyContinue }
    Write-Host "  Old VM removed."
}

# Clean up cloud-init staging directory
Remove-Item $ciDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Deploy complete!" -ForegroundColor Green
Write-Host " VM:  $VM_NAME" -ForegroundColor Green
Write-Host " URL: http://${VM_STATIC_IP}:${APP_PORT}" -ForegroundColor Green
Write-Host " Console login: user=photoai  password=$CONSOLE_PASSWD" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
