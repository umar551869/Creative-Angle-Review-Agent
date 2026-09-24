# Deploying on Oracle Cloud Always Free

Everything here is free, permanently — not a trial. The shape you want is
**VM.Standard.A1.Flex: 4 OCPU / 24 GB RAM / 200 GB block storage**, which is
the only genuinely free tier that fits this workload (~4 GB working set,
ffmpeg, 5–12 minute jobs, a persistent disk).

**This is ARM64 (Ampere).** Verified: `torch`, `ctranslate2`, `onnxruntime`,
`av`, `opencv`, `scipy`, `tokenizers` and every other dependency publish
`manylinux_*_aarch64` wheels, so it installs from wheels with no compiler and
no source build.

---

## 1. Create the account

<https://cloud.oracle.com/free> — needs a card for identity verification.
**It is not charged** for Always Free resources, but the verification is real,
so use a card that accepts a small temporary authorisation.

Pick your home region carefully: **it cannot be changed**, and A1 capacity
varies by region. A region near you with spare capacity beats a "better" one.

---

## 2. Create the instance

Console → **Compute → Instances → Create instance**

| Field | Value |
|---|---|
| Image | **Ubuntu 22.04** or **24.04** (not Oracle Linux — the script assumes apt) |
| Shape | **Ampere → VM.Standard.A1.Flex** |
| OCPUs | **4** |
| Memory | **24 GB** |
| Boot volume | **100–200 GB** (50 is the default; free goes to 200) |
| SSH keys | upload your public key, or let it generate one — **download it** |

### "Out of host capacity"

The single most common obstacle, and not a fault in anything you did — A1 is
popular and regions run dry. What works:

- try a **different availability domain** in the same region
- try **1 OCPU / 6 GB** first, then edit the shape upward once it exists
- retry at a different time of day; capacity is released constantly
- as a last resort, upgrade to Pay As You Go — Always Free resources stay
  free, and PAYG accounts get capacity priority

Do **not** take the AMD Always Free shape (`VM.Standard.E2.1.Micro`) as a
substitute. It is **1 GB of RAM**; this pipeline needs about four, and it will
be OOM-killed in the middle of Phase 2 rather than failing cleanly.

---

## 3. Open the port — BOTH halves

This is where almost everyone loses an hour. Oracle has **two** firewalls and
closing either one produces the same symptom: connection times out, nothing in
any log.

**(a) Security List** — Console → Networking → Virtual Cloud Networks → your
VCN → Subnets → your subnet → Security Lists → Default → **Add Ingress Rule**:

| | |
|---|---|
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `8000` |

**(b) The instance's own iptables** — an OCI Ubuntu image ships rules that
REJECT inbound traffic regardless of the Security List. `setup.sh` does this
for you; by hand it is:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

Skip (b) and the server answers on `localhost` and times out from anywhere
else, with nothing explaining why.

---

## 4. Deploy

```bash
ssh -i <your-key> ubuntu@<PUBLIC_IP>
```

Get the code up — either clone it, or from your laptop:

```bash
scp -r -i <your-key> "Backend" ubuntu@<PUBLIC_IP>:~/creative-audit/
```

Then on the box:

```bash
cd ~/creative-audit/Backend
bash deploy/oracle/setup.sh
```

It installs ffmpeg and the Python stack, creates `.env` **with a generated API
key** (printed once — save it), pre-downloads the ~1.8 GB of model weights so
the first request is not a ten-minute wait that looks like a hang, installs a
systemd unit, and opens the instance firewall.

Then add your Gemini key:

```bash
nano ~/creative-audit/Backend/.env     # GEMINI_API_KEY=...
sudo systemctl restart creative-audit
```

**No quotes, no spaces around `=`.**

---

## 5. Verify

```bash
curl http://localhost:8000/health                      # on the box
curl http://<PUBLIC_IP>:8000/health                    # from your laptop
curl -H "x-api-key: <KEY>" http://<PUBLIC_IP>:8000/ready
```

`/ready` should report `namespace: ready`, `auth: 1 key(s)`, and an empty
`problems` list. If `problems` mentions `GEMINI_API_KEY`, the key did not
load — check for quotes in `.env`.

Submit a job:

```bash
curl -X POST http://<PUBLIC_IP>:8000/analyze \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: <KEY>' \
  -d '{"video_urls":["https://www.tiktok.com/@user/video/123..."],
       "brief_url":"https://docs.google.com/document/d/.../edit"}'
```

---

## 6. Operating it

```bash
sudo systemctl status creative-audit
sudo journalctl -u creative-audit -f        # live
sudo journalctl -u creative-audit --since "1 hour ago"
sudo systemctl restart creative-audit
```

Logs are JSON (`AUDITOR_LOG_JSON=true`) and carry a `request_id` per request.
Credentials are redacted on the way out.

### Updating

```bash
cd ~/creative-audit/Backend
git pull                      # or scp the new files up
./.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart creative-audit
```

`artifacts/` and `briefs/` survive a restart — they are content-addressed, so
previously processed videos are still cache hits and cost nothing.

---

## 7. Things that will bite you

**TikTok from a datacentre IP.** Oracle's IP ranges are refused harder than a
home connection. Export cookies from a logged-in browser, put the file on the
box, and set `AUDITOR_COOKIES_FILE=/home/ubuntu/cookies.txt`. Expect to
refresh it periodically. If URL ingestion matters in production, route yt-dlp
through a residential proxy — this is the piece most likely to degrade quietly.

**No HTTPS.** Port 8000 is plain HTTP, so the API key crosses the network in
clear text. Fine for a private test; for anything real put Caddy in front:

```bash
sudo apt install -y caddy
# /etc/caddy/Caddyfile
#   audit.example.com {
#       reverse_proxy localhost:8000
#   }
sudo systemctl restart caddy    # automatic Let's Encrypt certificate
```
…then open 443 in both firewalls and close 8000.

**Disk fills.** Artifacts are the cache and grow. `AUDITOR_KEEP_ARTIFACTS_DAYS`
(default 30) sweeps whole per-video directories; `df -h` occasionally is still
worth it.

**Always Free reclamation.** Oracle may reclaim an *idle* Always Free compute
instance. A1 instances are generally exempt when actually in use; keeping the
service running and doing work is the practical defence.

---

## 8. What this does not give you

- **One instance, one job store.** The store is in-process; a second container
  would not see the first's jobs. Fine for a team, not for horizontal scale —
  that needs Redis or Postgres behind `JobStore`, and the interface is already
  the seam.
- **No per-caller rate limiting.** `AUDITOR_MAX_QUEUED_JOBS` bounds total work,
  not one caller's share.
- **No backups.** `AUDITOR_DATA_ROOT` is on the boot volume. Oracle can take
  volume backups; nothing here does it for you.
