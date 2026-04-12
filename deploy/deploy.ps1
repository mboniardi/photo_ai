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

# Generate unique VM name and secret key
$VM_NAME   = "$VM_NAME_PREFIX-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$SECRET_KEY = -join ((0..31) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
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
    $imgWsl  = wsl wslpath -u "$imgFile"
    $baseWsl = wsl wslpath -u "$baseVhdx"
    wsl qemu-img convert -f qcow2 -O vhdx "$imgWsl" "$baseWsl"
    if ($LASTEXITCODE -ne 0) { Write-Error "qemu-img convert failed."; exit 1 }
} else {
    Write-Host "  Using cached VHDX: $baseVhdx"
}

# Copy and resize to working VHDX
Write-Host "  Copying and resizing VHDX to ${VM_DISK_GB}GB…"
Copy-Item $baseVhdx $workingVhdx
$workingWsl = wsl wslpath -u "$workingVhdx"
wsl qemu-img resize "$workingWsl" "${VM_DISK_GB}G"
if ($LASTEXITCODE -ne 0) { Write-Error "qemu-img resize failed."; exit 1 }

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

users:
  - name: photoai
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: true
    ssh_authorized_keys: []

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

write_files:
  - path: /opt/photo_ai/.env
    permissions: '0600'
    owner: photoai:photoai
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

runcmd:
  - mkdir -p /opt/photo_ai
  - git clone $APP_GIT_REPO -b $APP_GIT_BRANCH /opt/photo_ai
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
    $ciDirWsl = wsl wslpath -u "$ciDir"
    $ciIsoWsl = wsl wslpath -u "$ciIso"
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
Write-Host "  VM started. Waiting for IP assignment…"

# Wait for DHCP IP
$VM_TEMP_IP = $null
$ipWait = 0
while (-not $VM_TEMP_IP -and $ipWait -lt 120) {
    Start-Sleep -Seconds 5
    $ipWait += 5
    $VM_TEMP_IP = (Get-VMNetworkAdapter $vm | Select-Object -ExpandProperty IPAddresses |
                   Where-Object { $_ -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$' } |
                   Select-Object -First 1)
}
if (-not $VM_TEMP_IP) {
    Write-Error "Could not get VM IP via DHCP after 120 seconds."
    Stop-VM -Name $VM_NAME -Force
    Remove-VM -Name $VM_NAME -Force
    exit 1
}
Write-Host "  VM DHCP IP: $VM_TEMP_IP"
Write-Host "  Polling http://${VM_TEMP_IP}:${APP_PORT}/health (timeout: ${HEALTH_TIMEOUT_SEC}s)…"

$healthy = $false
$elapsed = 0
do {
    Start-Sleep -Seconds $HEALTH_INTERVAL_SEC
    $elapsed += $HEALTH_INTERVAL_SEC
    try {
        $resp = Invoke-WebRequest "http://${VM_TEMP_IP}:${APP_PORT}/health" `
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
    Write-Error "Health check timeout after ${HEALTH_TIMEOUT_SEC}s. Rollback: removing $VM_NAME"
    Stop-VM -Name $VM_NAME -Force
    Remove-VM -Name $VM_NAME -Force
    Remove-Item $workingVhdx -Force -ErrorAction SilentlyContinue
    Remove-Item $ciIso       -Force -ErrorAction SilentlyContinue
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
    $loginResp = Invoke-WebRequest "http://${VM_TEMP_IP}:${APP_PORT}/auth/login" `
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
# PHASE 7 — Swap to static IP
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 7] Configuring static IP $VM_STATIC_IP" -ForegroundColor Cyan

$netplanContent = @"
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
"@

# Escape for shell heredoc inside ssh
$netplanEscaped = $netplanContent -replace "'", "'\''"

$sshCmd = @"
sudo tee /etc/netplan/01-static.yaml > /dev/null << 'NETPLAN'
$netplanContent
NETPLAN
sudo chmod 600 /etc/netplan/01-static.yaml
sudo netplan apply
"@

Write-Host "  SSHing to photoai@$VM_TEMP_IP to apply netplan…"
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 "photoai@$VM_TEMP_IP" $sshCmd
if ($LASTEXITCODE -ne 0) {
    Write-Warning "netplan apply may have interrupted the SSH session (this is expected)."
}

# ═══════════════════════════════════════════════════════════════════
# PHASE 8 — Cleanup and final verification
# ═══════════════════════════════════════════════════════════════════
Write-Host "`n[Phase 8] Final verification and cleanup" -ForegroundColor Cyan

# Give VM a moment to come back on static IP
Start-Sleep -Seconds 15

Write-Host "  Health check on static IP http://${VM_STATIC_IP}:${APP_PORT}/health…"
$finalHealthy = $false
$elapsed2 = 0
do {
    Start-Sleep -Seconds $HEALTH_INTERVAL_SEC
    $elapsed2 += $HEALTH_INTERVAL_SEC
    try {
        $r = Invoke-WebRequest "http://${VM_STATIC_IP}:${APP_PORT}/health" `
                               -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $finalHealthy = $true; break }
    } catch { }
} while ($elapsed2 -lt 60)

if (-not $finalHealthy) {
    Write-Warning "Static IP health check did not pass — verify $VM_STATIC_IP manually."
} else {
    Write-Host "  Static IP health check passed."
}

# Remove old VM
if ($oldVM) {
    Write-Host "  Stopping and removing old VM: $($oldVM.Name)…"
    Stop-VM -Name $oldVM.Name -Force -ErrorAction SilentlyContinue
    Remove-VM -Name $oldVM.Name -Force -ErrorAction SilentlyContinue
    Write-Host "  Old VM removed."
}

# Clean up cloud-init staging directory
Remove-Item $ciDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Deploy complete!" -ForegroundColor Green
Write-Host " VM:  $VM_NAME" -ForegroundColor Green
Write-Host " URL: http://${VM_STATIC_IP}:${APP_PORT}" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
