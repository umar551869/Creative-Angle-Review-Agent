# 5. Deployment

## 5.1 What this workload actually needs

Deployment options are decided by these four numbers, not by preference.

| Constraint | Value | Consequence |
|---|---|---|
| **Memory** | ~4 GB working set, **size for 8 GB** | Rules out every 512 MB free tier |
| **Disk** | ~2.5 GB models + artifacts that grow | Needs a persistent volume, or cold starts re-download |
| **Job duration** | 5–12 min cold, up to ~25 min for 25 videos | Rules out anything with a 5-minute request timeout |
| **Binaries** | `ffmpeg` + `ffprobe` on PATH | Rules out pure-Python "just push your repo" platforms |

**No GPU is required.** Vision is hosted; Whisper runs CPU int8 and BGE runs on
CPU. A GPU only speeds up ASR, which is not the bottleneck — the hosted vision
call is, at 72–240 s per video, and that is network wait.

**Uploads remove the worst deployment risk.** `POST /analyze/upload` takes the
video files directly, so the server never calls TikTok. URL ingestion is the
least reliable stage of a hosted run — anonymous downloads are refused from
datacentre IP ranges far more often than from residential ones, and no amount
of retrying fixes an IP-range block. A frontend that downloads locally and
uploads makes the backend's network profile just "Gemini and Google Docs",
which every host on this page can do. It also removes the cookies.txt
operational burden entirely.

**CPU cores pay off**: Phase 1 decode is parallel (measured 1.83× on 4 clips /
8 cores), and Whisper's CTranslate2 backend scales with threads.

---

## 5.2 Free hosting — honest ranking

Free tiers are built for small stateless web apps. This is a 4 GB, ffmpeg-
dependent, 10-minute-job, stateful pipeline. **Most free tiers cannot run it at
all**, and it is worth saying which and why rather than listing logos.

### Recommended: Oracle Cloud — Always Free

The only genuinely free-forever option that actually fits.

- **4 ARM cores (Ampere A1), 24 GB RAM, 200 GB block storage** — not a trial
- Full VM: install ffmpeg, mount a disk, run Docker, no platform limits
- No request timeout, because you own the box

**ARM64 is verified, not assumed.** Every dependency publishes a
`manylinux_*_aarch64` wheel — including the two that could have blocked it,
`ctranslate2` (behind faster-whisper) and `onnxruntime` (behind RapidOCR) —
so it installs from wheels with no compiler and no source build. The
Dockerfile and `setup.sh` are arch-aware: on x86 they ask for the CPU-only
torch index to avoid ~2 GB of unused CUDA; on aarch64 they use the PyPI wheel,
which is already CPU-only and which the CPU index does not reliably carry.

**→ Step-by-step guide: [`deploy/oracle/README.md`](../deploy/oracle/README.md)**
**→ One-shot installer: [`deploy/oracle/setup.sh`](../deploy/oracle/setup.sh)**

```bash
scp -r Backend ubuntu@<PUBLIC_IP>:~/creative-audit/
ssh ubuntu@<PUBLIC_IP>
cd ~/creative-audit/Backend && bash deploy/oracle/setup.sh
```

Two Oracle-specific traps the guide covers, because both produce the same
silent symptom (connection times out, nothing in any log):

1. **Two firewalls.** The VCN Security List *and* the instance's own iptables.
   An OCI Ubuntu image ships rules that REJECT inbound traffic regardless of
   what the console says. `setup.sh` handles the second; the first is a
   console click.
2. **"Out of host capacity".** A1 is popular and regions run dry. Try another
   availability domain, or 1 OCPU first and resize. Do **not** fall back to the
   AMD Always Free shape — it is 1 GB of RAM and will be OOM-killed in Phase 2
   rather than failing cleanly.

### Hugging Face Spaces — NOT free for this. Needs PRO.

**Corrected 2026-09-24, against the live API.** Creating a Docker Space
returns:

```
402 Payment Required
Static Spaces are free for everyone, but hosting Gradio and Docker
Spaces on free cpu-basic requires a PRO subscription.
```

Tried **public and private**; both refused. Only **Static** Spaces (plain
HTML/JS) are free, and a FastAPI backend cannot be one. An earlier version of
this document said the free CPU tier worked — it does not.

**With PRO (~$9/mo)** it is a good fit: 2 vCPU / 16 GB, Docker-native, free
HTTPS, built-in secrets. But at $9 a Hetzner VPS is €6.50 for 4 vCPU, 80 GB,
a real disk and no sleeping — so PRO only makes sense if you already have it.

Remaining caveats if you do: storage is **ephemeral** (use
`AUDITOR_EPHEMERAL=true` and hold the `compiled_brief` client-side), Spaces
**sleep** after inactivity, and HF's IP ranges are among the worst for TikTok
downloads.

Guide, still accurate given PRO: [`deploy/huggingface/README.md`](../deploy/huggingface/README.md)

### Workable: Google Cloud Run

- Generous free tier (2M requests, 360k vCPU-s/month), scale-to-zero
- Same cloud as Gemini → **service-account auth instead of an API key**
- Up to 60 min request timeout; **Cloud Run Jobs** up to 24 h

**Caveats:** no persistent disk — mount GCS with Cloud Storage FUSE or accept
cold re-downloads. Set `--min-instances=1` to avoid cold starts and you leave
the free tier. Best fit if you want to move to a queue + worker split later.

### Not recommended, and why

| Platform | Why not |
|---|---|
| **Render free** | 512 MB RAM. torch alone exceeds it. |
| **Railway / Fly.io** | Trial credit, not a free tier; both bill after it. |
| **Koyeb / Vercel / Netlify** | 512 MB and/or no ffmpeg and/or short function timeouts. |
| **Heroku free** | Discontinued. |
| **AWS free tier** | `t2.micro` is 1 GB and expires after 12 months. |

### The honest summary

> If free is a hard requirement, **Oracle Always Free** is the only option that
> genuinely works — 4 ARM cores, 24 GB, 200 GB, no sleep, no expiry.
> **Cloud Run** is the fallback if you would rather not run a VM, at the cost
> of no persistent disk. **HF Spaces is not an option without PRO** — verified
> against the live API, a Docker Space returns 402 on free cpu-basic.
>
> For steady industrial use, a **€4–7/month VPS (Hetzner CX22/CX32)** still
> beats every free tier: 4 vCPU / 8 GB, x86, a real disk, and no sleep.

---

## 5.3 Deploy

```bash
cp .env.example .env
# REQUIRED: GEMINI_API_KEY
# STRONGLY RECOMMENDED before exposing a port: AUDITOR_API_KEYS
docker compose up -d --build
curl localhost:8000/health     # liveness
curl localhost:8000/ready      # readiness + what is missing
```

The image is ~2.5 GB, mostly torch plus baked model weights. Pass
`--build-arg BAKE_MODELS=false` to trade image size for cold-start time.

### Scaling

**Run one worker per container.** The job store and the pipeline namespace live
in-process; `--workers 4` gives four independent stores and four model loads.
Startup logs an error if `WEB_CONCURRENCY > 1`.

Scale by adding **containers** that share `AUDITOR_DATA_ROOT`. The artifact
store is content-addressed, so concurrent containers cooperate rather than
collide: the same video under the same config resolves to the same key, and
whichever gets there first pays for it.

The current job store is **per-process**, so a load balancer must use sticky
sessions, or callers must poll the instance that accepted the job. For a true
multi-instance deployment the next step is Redis or Postgres behind
`JobStore` — the interface (`create` / `get` / `list` / `submit`) is already
the seam.

---

## 5.4 Operations

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | open | **Liveness.** Cheap, no model, no key. Point restart policies here. |
| `GET /ready` | open | **Readiness.** 503 until the namespace is loaded and configuration is valid. Reports the model probe and whether auth is on. |
| `GET /metrics` | open | Prometheus text: `audit_up`, `audit_jobs_total{status}`, `audit_videos_completed_total`. |
| `GET /config` | key | Effective settings, keys as lengths. |

**Never point a restart policy at `/ready`.** It reports a missing API key as
not-ready, and a container restarted for that reason restarts forever.

### Startup sequence

1. Settings logged (redacted), auth mode stated
2. Pipeline namespace loaded (~4 s) → `/ready` namespace: ready
3. Model probe starts **in a background thread** (25–30 s of live API calls)
   — deliberately off the startup path, so a health check does not fail while
   it runs

### Shutdown

SIGTERM stops intake, then waits `AUDITOR_SHUTDOWN_GRACE_S` (default 20 s) for
running jobs. Anything still running is marked failed on disk with a message
saying it was interrupted — **a job killed mid-stage leaves half-written
artifacts that a content-addressed cache cannot distinguish from complete
ones**, so an interrupted job must never come back claiming to be in progress.
Phase 1–3 artifacts already written are kept, so re-submitting resumes.

### Retention

| What | Setting | Default | Notes |
|---|---|---|---|
| Job workspaces (`jobs/<id>/inbox`, `/reports`) | `AUDITOR_KEEP_JOB_FILES_HOURS` | 72 | The job **record** is kept — a few KB of conclusions outliving the video it concluded from. |
| Artifact cache | `AUDITOR_KEEP_ARTIFACTS_DAYS` | 30 | Whole per-video directories, by last touch. Never partial. |
| Logs | — | 20 MB × 5 | Rotating. |

Both sweeps run at most hourly, triggered by a job start — no timer thread to
supervise. Low disk is logged **before** it corrupts a write, because a short
write surfaces as a corrupt artifact rather than "the disk is full".

---

## 5.5 Security posture

- **Auth is optional and off by default.** Right for a laptop, wrong for a
  public address. `/ready` reports `auth: OPEN` and startup logs a warning, so
  an unprotected deployment is visible rather than assumed.
- Keys compared with `hmac.compare_digest` — `==` short-circuits and leaks the
  prefix to anyone willing to time responses.
- `/health`, `/ready`, `/metrics` bypass auth: a load balancer cannot present
  a key.
- Request bodies capped (2 MB default). Every endpoint takes a small JSON
  document; without a ceiling an unauthenticated caller can make the process
  buffer arbitrary bytes.
- Queue depth capped (20). An unbounded queue turns "too much work" into
  "nothing finishes and memory grows".
- Logs redact `AIza…`, `sk-…`, `hf_…`, bearer tokens and `key=`/`token=`
  patterns, on both stdout and file.
- Container runs as **non-root** (uid 10001).
- CORS is **off** unless `AUDITOR_CORS_ORIGINS` is set.

### Still open, and worth knowing

- **No per-caller rate limiting.** `AUDITOR_MAX_QUEUED_JOBS` bounds total work
  but not one caller's share. Put it behind a gateway if the callers are not
  all trusted.
- **No audit log of who submitted what.** Request ids correlate logs; they do
  not identify a principal beyond which key was used.
- **Reports are served to any holder of a valid key** — there is no per-job
  ownership model. Fine for one team, not for multi-tenant.

---

## 5.6 Before you go live

```bash
python tools/check_deps.py         # deps + ffmpeg/ffprobe
python tools/check_production.py   # deployment posture
python tools/audit_backend.py      # generated layer matches the notebook
python -m pytest tests -q          # 108 tests
```

Then, once: set `AUDITOR_API_KEYS`, confirm `/ready` returns 200, submit one
job, and confirm the report renders. The parity run against a known-good video
(`docs/04_parity_checklist.md` §4.5) is the last gate before trusting a score.
