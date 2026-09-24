#!/usr/bin/env bash
#
# Creative Audit API -- one-shot setup on an Oracle Cloud Always Free VM.
#
#   curl -fsSL <raw-url>/setup.sh -o setup.sh && bash setup.sh
#   ...or just scp this file up and: bash setup.sh
#
# Safe to re-run. Every step checks before it acts.
#
# Tested shape: Ubuntu 22.04/24.04 on VM.Standard.A1.Flex (4 OCPU / 24 GB).
# Works on the x86 AMD Always Free shape too, but that is 1 GB of RAM and this
# needs ~4 -- the script says so rather than letting you find out in Phase 2.

set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/creative-audit}"
PORT="${PORT:-8000}"
log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*"; }
die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
log "Checking the machine"
ARCH="$(uname -m)"
MEM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024 ))
CORES="$(nproc)"
DISK_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
echo "    arch     : $ARCH"
echo "    cores    : $CORES"
echo "    memory   : ${MEM_GB} GB"
echo "    free disk: ${DISK_GB} GB"

# ~4 GB working set: CTranslate2 int8 turbo ~1 GB, torch ~1 GB resident, plus
# ONNX, decoded frames and the video itself. Below this it does not fail
# cleanly -- it OOM-kills mid-decode and leaves a half-written artifact.
if [ "$MEM_GB" -lt 5 ]; then
  warn "Only ${MEM_GB} GB of RAM. This needs ~4 GB and 8 is comfortable."
  warn "The Always Free AMD shape (VM.Standard.E2.1.Micro) is 1 GB and will"
  warn "OOM during Phase 2. Use VM.Standard.A1.Flex with 4 OCPU / 24 GB."
  read -rp "    Continue anyway? [y/N] " a; [ "$a" = y ] || exit 1
fi
[ "$DISK_GB" -lt 20 ] && warn "Only ${DISK_GB} GB free. Models are ~1.8 GB and"\
  " artifacts grow; 50+ GB recommended (the free boot volume goes to 200)."

# ---------------------------------------------------------------------------
log "Installing system packages"
sudo apt-get update -qq
# ffmpeg is NOT pip-installable and is the first thing a job touches. Without
# it the server starts, /health says ok, and every job dies in Phase 1.
sudo apt-get install -y -qq \
  python3-venv python3-pip python3-dev build-essential \
  ffmpeg git curl ca-certificates
echo "    ffmpeg : $(ffmpeg -version 2>/dev/null | head -1 | cut -c1-48)"
echo "    ffprobe: $(command -v ffprobe || echo MISSING)"
command -v ffprobe >/dev/null || die "ffprobe missing after install"

# ---------------------------------------------------------------------------
log "Getting the code into $APP_DIR"
if [ -d "$APP_DIR/Backend" ]; then
  echo "    already present"
elif [ -n "${REPO_URL:-}" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  mkdir -p "$APP_DIR"
  cat <<'EOF'
    No REPO_URL set and no code found.
    Upload the Backend/ directory to this box, then re-run, e.g. from your
    laptop:

        scp -r "Backend" ubuntu@<PUBLIC_IP>:~/creative-audit/

    (or: REPO_URL=https://github.com/you/repo.git bash setup.sh)
EOF
  exit 1
fi
cd "$APP_DIR/Backend"

# ---------------------------------------------------------------------------
log "Python environment"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip wheel

# See the note in the Dockerfile: on aarch64 the PyPI wheel is ALREADY
# CPU-only, and the /whl/cpu index does not reliably carry one -- asking for
# it turns a working install into a resolver error.
if [ "$ARCH" = "x86_64" ]; then
  echo "    torch: CPU index (avoids ~2 GB of unused CUDA)"
  ./.venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
else
  echo "    torch: PyPI aarch64 wheel (already CPU-only)"
  ./.venv/bin/pip install -q torch
fi
echo "    installing requirements (several minutes on first run) ..."
./.venv/bin/pip install -q -r requirements.txt

# ---------------------------------------------------------------------------
log "Configuration"
# `sed -i s|^KEY=.*|...|` SILENTLY DOES NOTHING when the key is absent, and
# exits 0 -- so `sed ... || echo >> .env` never reaches the fallback. An
# earlier version of this printed a generated API key and wrote none, and the
# API came up OPEN on a public IP. Set it, then VERIFY it is there.
set_env() {
  local key="$1" val="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
  grep -q "^${key}=${val}$" .env || die "could not set ${key} in .env"
}

if [ ! -f .env ]; then
  cp .env.example .env
  # An API with no key, on a public IP, spends your model quota for anyone who
  # finds it. Generate one rather than leaving it to be done later.
  KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
  set_env AUDITOR_API_KEYS "$KEY"
  set_env AUDITOR_DATA_ROOT "${APP_DIR}/data"
  set_env AUDITOR_LOG_JSON true
  echo "    wrote .env, and CONFIRMED the key landed in it"
  echo
  echo "    YOUR API KEY (save it -- it is not shown again):"
  echo "        ${KEY}"
  echo
else
  echo "    .env already exists, left alone"
fi

# Verify what is actually in the file, not what we meant to put there.
grep -q '^GEMINI_API_KEY=.\+' .env \
  || warn "GEMINI_API_KEY is empty in .env -- set it before submitting a job."
grep -q '^AUDITOR_API_KEYS=.\+' .env \
  || warn "AUDITOR_API_KEYS is empty -- the API will accept requests from
    ANYONE who can reach this port. Set it before opening the firewall."
# A quoted value is a value WITH QUOTES IN IT under docker-compose's env_file
# parser, and fails as a 401 that looks exactly like a wrong key.
grep -E '^(GEMINI_API_KEY|AUDITOR_API_KEYS)=["'"'"']' .env >/dev/null \
  && warn "a value in .env is QUOTED. Remove the quotes -- docker-compose
    takes them literally and the key will fail as a 401."

# ---------------------------------------------------------------------------
log "Pre-downloading model weights (~1.8 GB, once)"
# Otherwise the FIRST request spends ten minutes downloading and looks hung.
set +e
./.venv/bin/python tools/bake_models.py
set -e

# ---------------------------------------------------------------------------
log "Checks"
./.venv/bin/python tools/check_deps.py || die "dependency check failed"

# ---------------------------------------------------------------------------
log "systemd service"
sudo tee /etc/systemd/system/creative-audit.service >/dev/null <<EOF
[Unit]
Description=Creative Audit API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR/Backend
EnvironmentFile=$APP_DIR/Backend/.env
# ONE worker. The job store and the pipeline namespace live in this process;
# --workers N gives N independent stores and N model loads.
ExecStart=$APP_DIR/Backend/.venv/bin/uvicorn app.main:app \\
  --host 0.0.0.0 --port $PORT --workers 1 --timeout-graceful-shutdown 25
Restart=always
RestartSec=10
# A job takes minutes; give it room to finish on stop rather than being
# SIGKILLed mid-stage, which leaves half-written artifacts that a
# content-addressed cache cannot tell from complete ones.
TimeoutStopSec=60
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now creative-audit
sleep 5

# ---------------------------------------------------------------------------
log "Opening the firewall"
# THE ORACLE GOTCHA. An OCI Ubuntu image ships iptables rules that REJECT
# inbound traffic regardless of what the Security List says. Opening the port
# in the console alone leaves you with a server that answers on localhost and
# times out from anywhere else -- and nothing in any log says why.
if sudo iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
  echo "    rule already present"
else
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$PORT" -j ACCEPT
  # Persist it, or the rule is gone after the next reboot and the box becomes
  # unreachable for no visible reason.
  if ! sudo netfilter-persistent save >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      iptables-persistent >/dev/null 2>&1 || true
    sudo netfilter-persistent save >/dev/null 2>&1 \
      || sudo sh -c 'mkdir -p /etc/iptables && iptables-save > /etc/iptables/rules.v4' 2>/dev/null \
      || warn "rule is live but NOT persisted -- it will not survive a reboot"
  fi
  echo "    opened TCP $PORT on the instance firewall"
fi

# ---------------------------------------------------------------------------
log "Result"
sleep 3
if curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then
  echo "    /health : OK"
  curl -s "http://localhost:$PORT/ready" | head -c 400; echo
else
  warn "the service is not answering yet. Watch it start:"
  echo "        sudo journalctl -u creative-audit -f"
fi

IP="$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || echo '<PUBLIC_IP>')"
cat <<EOF

  ------------------------------------------------------------------
  Service : sudo systemctl status creative-audit
  Logs    : sudo journalctl -u creative-audit -f
  Local   : curl http://localhost:$PORT/ready

  STILL TO DO IN THE OCI CONSOLE -- the instance firewall above is only
  half of it. Networking > VCN > Subnet > Security List > Add Ingress:
      Source 0.0.0.0/0   IP Protocol TCP   Destination port $PORT

  Then from your laptop:
      curl http://$IP:$PORT/health
  ------------------------------------------------------------------
EOF
