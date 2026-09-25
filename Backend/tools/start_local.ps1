# Bring the local backend and its public tunnel back up after a reboot.
#
#     powershell -ExecutionPolicy Bypass -File tools\start_local.ps1
#
# The tunnel dies with the machine; Docker restarts itself (restart:
# unless-stopped) once Docker Desktop is up. The public URL is a fixed ngrok
# domain, so it is the same every time.
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
# 2. Tunnel -- ngrok, FIXED hostname
# ---------------------------------------------------------------------------
# The free ngrok account comes with one permanent dev domain, so this URL is
# the same after every reboot and Vercel's AUDIT_API_URL never has to change.
# The authtoken lives in ngrok's own config (%LOCALAPPDATA%\ngrok\ngrok.yml,
# set once with `ngrok config add-authtoken`), not in this repo.
#
# Browsers get a one-time ngrok interstitial page; server-side calls (Vercel's
# route handler) do not. Sending `ngrok-skip-browser-warning: 1` skips it
# everywhere.
$Domain = 'atlantic-canine-hurling.ngrok-free.dev'
$url = "https://$Domain"

$ng = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse `
        -Filter "ngrok.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1).FullName
if (-not $ng) {
    Write-Host "`nngrok not found. Backend is up on http://127.0.0.1:8000"
    Write-Host "Install with: winget install Ngrok.Ngrok, then: ngrok update"
    exit 0
}

Get-Process -Name ngrok -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Start-Process -FilePath $ng `
    -ArgumentList "http","http://127.0.0.1:8000","--url",$url, `
                  "--log","stdout","--log-format","logfmt" `
    -RedirectStandardOutput "ngrok.log" `
    -RedirectStandardError  "ngrok.err.log" `
    -WindowStyle Hidden
Write-Host "tunnel starting..."

$ok = 0
foreach ($i in 1..6) {
    Start-Sleep -Seconds 5
    try {
        Invoke-RestMethod -Uri "$url/health" -TimeoutSec 30 `
            -Headers @{ 'ngrok-skip-browser-warning' = '1' } | Out-Null
        $ok++
    } catch { }
}

Write-Host "`n=============================================================="
Write-Host " AUDIT_API_URL = $url"
Write-Host " reachable on $ok/6 probes$(if ($ok -eq 0) {'  -- see ngrok.log'})"
Write-Host "=============================================================="
Write-Host " Same hostname as always; nothing to update in Vercel."
Write-Host " The API key is unchanged (AUDITOR_API_KEYS in .env)."
Write-Host "==============================================================`n"
