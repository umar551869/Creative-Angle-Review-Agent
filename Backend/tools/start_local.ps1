# Bring the local backend and its public tunnel back up after a reboot.
#
#     powershell -ExecutionPolicy Bypass -File tools\start_local.ps1
#
# Both processes die with the machine, and the quick tunnel is issued a NEW
# hostname every time it starts -- so the frontend's AUDIT_API_URL has to be
# updated after every reboot. This prints the new URL at the end.
#
# Layout: Docker serves :8000 and is what the tunnel exposes. The local .venv
# backend runs on :8001 for testing only. Never put the local one on 8000: on
# Windows its 127.0.0.1 bind beats Docker's 0.0.0.0 bind, so the tunnel would
# silently reach it instead of the container.

$ErrorActionPreference = 'Continue'
$Backend = Split-Path -Parent $PSScriptRoot
Set-Location $Backend

Write-Host "`n=== Creative Angle Review Agent - local start ===`n"

function Wait-Ready($port, $log) {
    foreach ($i in 1..36) {
        Start-Sleep -Seconds 5
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/ready" -TimeoutSec 5
            if ($r.ready) {
                Write-Host "  :$port READY   ffmpeg=$(if ($r.ffmpeg) {'found'} else {'MISSING'})  auth=$($r.auth)"
                return $true
            }
        } catch { }
    }
    Write-Host "  :$port did not become ready; see $log" -ForegroundColor Red
    return $false
}

# ---------------------------------------------------------------------------
# 1. Docker backend on :8000 (the one the tunnel serves)
# ---------------------------------------------------------------------------
docker compose up -d
Write-Host "docker backend starting (~30-60s)..."
if (-not (Wait-Ready 8000 "docker logs backend-api-1")) { exit 1 }

# ---------------------------------------------------------------------------
# 1b. Local .venv backend on :8001 (testing only, not tunnelled)
# ---------------------------------------------------------------------------
$busy = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "port 8001 already in use (pid $($busy[0].OwningProcess)) - stopping it"
    Stop-Process -Id $busy[0].OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1", `
                  "--port","8001","--timeout-graceful-shutdown","25" `
    -RedirectStandardOutput "server8001.out.log" `
    -RedirectStandardError  "server8001.err.log" `
    -WindowStyle Hidden

Write-Host "local backend starting (loads the pipeline namespace, ~10-20s)..."
# Not fatal: the tunnel only needs Docker.
Wait-Ready 8001 "server8001.err.log" | Out-Null

# ---------------------------------------------------------------------------
# 2. Tunnel
# ---------------------------------------------------------------------------
# --protocol http2 on purpose: QUIC (UDP 7844) is blocked on this network, so
# the default transport fails its precheck and the tunnel is unreachable even
# though it reports as connected. TCP 443 works, and http2 uses it.
$cf = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse `
        -Filter "cloudflared.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1).FullName
if (-not $cf) {
    Write-Host "`ncloudflared not found. Backend is up on http://127.0.0.1:8000"
    Write-Host "Install with: winget install Cloudflare.cloudflared"
    exit 0
}

Get-Process -Name cloudflared -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item "tunnel.log" -ErrorAction SilentlyContinue

$url = $null
foreach ($try in 1..3) {
    Start-Process -FilePath $cf `
        -ArgumentList "tunnel","--no-autoupdate","--protocol","http2", `
                      "--url","http://127.0.0.1:8000" `
        -RedirectStandardError "tunnel.log" `
        -RedirectStandardOutput "tunnel.out.log" `
        -WindowStyle Hidden
    Write-Host "tunnel starting (attempt $try)..."
    foreach ($i in 1..18) {
        Start-Sleep -Seconds 5
        $m = Select-String -Path "tunnel.log" `
             -Pattern "https://[a-z0-9]+(-[a-z0-9]+){2,}\.trycloudflare\.com" `
             -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
    if ($url) { break }
    Get-Process -Name cloudflared -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

if (-not $url) {
    Write-Host "`ntunnel could not be provisioned. Backend is up locally." -ForegroundColor Yellow
    Write-Host "trycloudflare has no uptime guarantee; retry, or use a named tunnel."
    exit 0
}

$ok = 0
foreach ($i in 1..6) {
    Start-Sleep -Seconds 10
    try { Invoke-RestMethod -Uri "$url/health" -TimeoutSec 30 | Out-Null; $ok++ } catch { }
}

Write-Host "`n=============================================================="
Write-Host " AUDIT_API_URL = $url"
Write-Host " reachable on $ok/6 probes"
Write-Host "=============================================================="
Write-Host " This hostname is NEW. Update it in Vercel and tell the frontend"
Write-Host " dev, or they will debug their own code against a dead URL."
Write-Host " The API key is unchanged (AUDITOR_API_KEYS in .env)."
Write-Host "==============================================================`n"
