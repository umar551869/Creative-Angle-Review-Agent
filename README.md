# Creative Angle Review Agent

Audits short-form social video against a content brief.

You give it **video links** (or the video files) and **one content brief**.
It returns, per video: a score, a timestamped verdict for every requirement
the brief states, a self-contained HTML report, and **which of the brief's own
creative angles the video actually fits**.

```
POST /analyze         { video_urls: [...], brief_url: "https://docs.google…" }
POST /analyze/upload  files=@clip.mp4 …   brief_url=…      (you send the bytes)
      │
      ├─ brief      fetch the Google Doc → compile to requirements → FREEZE
      ├─ ingest     yt-dlp each URL into this job's inbox
      │             (uploads skip this: the files are already there)
      ├─ phase 1    ffprobe → preflight → scene detect → sample → frames+audio
      ├─ phase 2    faster-whisper ASR, RapidOCR on selected frames
      ├─ phase 3    frames → Gemini → timestamped visual events
      ├─ phase 5    normalise speech + OCR + visual onto ONE timeline
      ├─ phase 6    per requirement: L1 deterministic → L2 embedding → L3 LLM
      │             + hook, claims, creative angle, standing
      └─ phase 7    score BY ARITHMETIC → recommendations → HTML report
      │
      ▼
GET /jobs/{id} → verdicts, score, creative angle, report links
```

Runs are long — a cold single-video job is about 4–6 minutes — so `/analyze`
returns a job id and you poll.

---

## What makes it different from "ask a model if the video is good"

The system is built so that **no model ever writes a number**, and so that
every claim traces back to a timestamp. These rules are not aspirational; they
are enforced in code and in tests.

| Rule | What it means |
|---|---|
| **No model writes a number** | Scores are arithmetic over verdicts. A test asserts the scoring module contains no model call. |
| **Compliance ≠ achievement** | `headline` can be *below* `literal_headline`. Following the instruction and serving the intent are scored separately. |
| **UNCERTAIN is abstention** | It lowers `coverage`; it does not score zero. "We could not tell" and "she did not do it" are different answers. |
| **NOT_APPLICABLE leaves the denominator** | An option she did not take off a menu is not a failure. |
| **Bands, not false precision** | When coverage is thin, `lead_with_band` is true and the band is the answer. |
| **Everything traces** | Every verdict cites evidence ids resolvable to a timestamp. |
| **Degrade, never block** | A missing embedder, a failed OCR pass, an absent chart library — each degrades one rung and says so. |
| **Two independent things must agree, or abstain** | A requirement needing `visual_and_speech` cannot be satisfied by one modality. |
| **Bump the stage version in the same edit** | Changing a stage's output without bumping it replays stale cached results forever. |

### The creative angle is a description, not a score

A brief usually names a few creative concepts. The audit reports which one the
video actually is, as a percentage split over that closed list, plus
`"none of the listed angles"` when the creator made something off-menu.
**Scoring never reads it.** It answers "what did she make", not "is it good".

---

## Layout

```
Backend/
  app/          FastAPI layer: routes, jobs, config, media resolution
  auditor/      the pipeline itself, 86 modules
  tools/        check_deps, audit_backend, check_production, smoke_api, …
  tests/        196 tests
  docs/         architecture, parity, deployment, frontend integration
  deploy/       Oracle Cloud and Hugging Face deployment helpers
  Dockerfile, docker-compose.yml, requirements.txt
```

`auditor/` was generated from a Jupyter notebook that is no longer in this
repository. **It is now the source of truth and is edited directly.** Two files
carry deliberate hand-edits and say so in their headers; the notebook-parity
checks skip themselves, loudly, when the notebook is absent.

---

## Quick start

Requires **Python 3.11+** and **ffmpeg/ffprobe** (not pip-installable).

```bash
cd Backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu

cp .env.example .env          # set GEMINI_API_KEY, and AUDITOR_API_KEYS
python tools/check_deps.py    # every package + both binaries
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then `GET /ready` — it names the ffmpeg paths and refuses to claim ready
without them.

Docker: `docker compose up -d --build`. On Windows this needs WSL2
(`wsl --install`, then reboot), and the image bakes ~1.8 GB of model weights so
the first build is long. See `Backend/docs/06_frontend_integration.md` §1c.

**No GPU required.** Vision is hosted; Whisper runs CPU int8 and BGE runs on
CPU.

---

## Measured performance

One 60–70 s video, on a CPU laptop, no cache:

| Stage | Time |
|---|---|
| ingest (download) | 6–9 s |
| phase 1 decode + sample | 25–27 s |
| phase 2 ASR + OCR | 176–186 s |
| phase 3 hosted vision | 16–60 s |
| phases 5–7 audit, score, report | 38–45 s |
| **total, brief reused** | **~4.5–5.5 min** |
| brief compile, when not reused | **+59 s** (3 consensus runs) |

Phase 2 dominates and is mostly ASR. Phase 3 varies with Gemini latency and
retries. About 25–33 s of phase 2 is a one-off Whisper model load per process,
so a second video in the same job is cheaper.

---

## API

| Method | Path | Auth | |
|---|---|---|---|
| `POST` | `/analyze` | key | queue an audit from video **URLs** |
| `POST` | `/analyze/upload` | key | queue an audit from uploaded **files** |
| `GET` | `/jobs/{id}` | key | status, progress, results |
| `GET` | `/jobs` | key | recent jobs |
| `GET` | `/jobs/{id}/report/{video_id}.html` | key | the report |
| `GET` | `/jobs/{id}/reports.zip` | key | every report from the job |
| `POST` | `/briefs/compile` | key | compile a brief alone, to inspect it |
| `GET` | `/health` | open | liveness — point restart policies here |
| `GET` | `/ready` | open | readiness — 503 until it can serve |
| `GET` | `/metrics` | open | Prometheus text |
| `GET` | `/config` | key | effective settings, keys as lengths |

Auth is `x-api-key`, **off until `AUDITOR_API_KEYS` is set** — `/ready` reports
`auth: OPEN` so an unprotected deployment is visible rather than assumed.

Reports are also filed, under readable names, in `<data_root>/reports/`.

Full frontend guide, including **why a Vercel deployment cannot reach a
localhost backend** and what to do about it:
[`Backend/docs/06_frontend_integration.md`](Backend/docs/06_frontend_integration.md).

---

## The one thing that will bite you

**The brief compiler is not deterministic.** The same document has produced
20, 27 and 28 requirements across runs at temperature 0. The requirement set
*is* the contract a score means something against.

So the first compile of a brief is **frozen** and reused, recorded by an
explicit `FROZEN.json` pointer. Two videos submitted days apart are measured
against the same contract and their scores mean the same thing.

`AUDITOR_ALWAYS_RECOMPILE_BRIEF=true` or `recompile: true` turns that off
deliberately. After it, scores are no longer comparable with earlier ones —
and nothing in the output says so, because nothing can.

If the server runs with no persistent disk (`AUDITOR_EPHEMERAL=true`), the job
returns `compiled_brief`; store it and pass it back on later jobs to keep
comparability with no server state.

---

## Verifying a change

```bash
cd Backend
python -m pytest tests -q          # 196 tests
python tools/check_deps.py         # packages + ffmpeg
python tools/audit_backend.py      # structure, entry points, design rules
python tools/check_production.py   # secrets, operability, data safety
python tools/smoke_api.py          # every route, validation shapes
```

---

## Known limits

- **Band thresholds and dimension weights are placeholders.** The report says
  so. Calibrating them needs a labelled benchmark set, which does not exist
  yet.
- **The vision model is pinned** (`AUDITOR_VISION_MODEL`) because the probe
  ranks by measured speed and a different leader is a different cache key.
- **URL ingestion is the least reliable stage.** TikTok refuses anonymous
  downloads from datacentre IPs far more often than residential ones — which
  is the best argument for running this on your own machine, and why
  `/analyze/upload` exists.
- **Free-tier Gemini 503s are routine.** The model ladder retries and falls
  through; the artifact records which model actually answered.
