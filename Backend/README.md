# Creative Audit API

A FastAPI backend around the Phase 1–7 video-compliance pipeline: video URLs
and a content brief in, timestamped verdicts, a score, an HTML report and a
creative-angle attribution out.

The pipeline itself is **not a reimplementation**. It is generated from
`Phase 7/phases_1_to_7_BATCH.ipynb`, verbatim, by
`tools/extract_from_notebook.py`. Notebook behaviour → backend behaviour was
the first objective; everything else came after.

---

## 1. What it does

```
POST /analyze  { video_urls: [...], brief_url: "https://docs.google.com/..." }
      │
      ├─ brief      fetch the Google Doc → compile to requirements → FREEZE
      ├─ ingest     yt-dlp each URL into this job's inbox
      ├─ phase 1    ffprobe → preflight → scene detect → sample → frames+audio
      ├─ phase 2    faster-whisper ASR, RapidOCR on selected frames
      ├─ phase 3    frames → Gemini → timestamped visual events
      ├─ phase 5    normalise speech+OCR+visual onto ONE timeline
      ├─ phase 6    per requirement: L1 deterministic → L2 embedding → L3 LLM
      │             + hook, claims, creative angle, standing
      └─ phase 7    score BY ARITHMETIC → recommendations → HTML report
      │
      ▼
GET /jobs/{id} → verdicts, score, creative angle, report links
```

### The rules it obeys

These are load-bearing. A change that breaks one of them is not this system.

1. **No model writes a number.** `score_audit` is arithmetic over verdicts.
   `tests/test_extraction.py` asserts that `scoring/score.py` contains no
   model call.
2. **Compliance ≠ achievement.** `status` (did she do it) and `alignment` (did
   it serve the ask) are separate axes.
3. **UNCERTAIN is an abstention, not a zero.** It lowers `coverage`; it does
   not score 0.
4. **Bands, not false precision.** When `lead_with_band` is true, the *band*
   is the answer and the headline alone overstates the evidence.
5. **Everything traces.** Every verdict cites `evidence_ids`.
6. **Degrade, never block.** A failed modality yields UNCERTAIN, not FAIL —
   `can_fail_on` refuses to assert an absence the evidence never established.
7. **The creative angle is a description, never a score.** Nothing in scoring
   reads `concept_fit`; a test asserts it.

---

## 2. Architecture

```
Backend/
  app/                      hand-written service layer
    main.py                 FastAPI routes, lifespan, model probes
    config.py               settings from env; no secret has a default
    schemas.py              request/response models
    jobs.py                 job store + worker pool (1 job at a time)
    logging_setup.py        structured logs with credential redaction
    services/
      ingest.py             video download, brief fetch, compile + freeze
      pipeline.py           the orchestrator — a translation of §90
  auditor/                  GENERATED from the notebook — do not hand-edit
    runtime.py              the shared namespace + job-scoped DIRS
    _load_order.py          notebook cell order (load-bearing, do not sort)
    config.py  cache.py  preprocessing/  asr/  ocr/  evidence/  vision/
    brief/  evidence5/  audit/  scoring/          (71 modules)
  tools/
    extract_from_notebook.py   regenerate auditor/ ← the only file to review
    check_entrypoints.py       all 58 entry points still present
    smoke_api.py               API wiring, no key needed
  tests/
  docs/                     the notebook analysis (read 02 and 03 first)
```

### Why `auditor/` is generated, not hand-ported

The notebook is ~24,000 lines across 148 cells (81 production). It runs in one
global namespace and **binds some names late on purpose** —
`globals().get('make_vision_backend')` lets a stage defined at cell 72 reach a
backend defined at cell 68 without a hard import. Reconstructing an import
graph the original never had is the fastest way to change behaviour while
believing you have not.

So the generated modules are **executed in notebook cell order into one
namespace** by `auditor/runtime.py`. Real files you can read, grep and diff;
identical semantics. `app/` is ordinary modular Python.

**Trade-off, stated plainly:** you cannot `from auditor.vision import gemini`.
Reach the pipeline through `runtime.load()` or `app.services.pipeline`. That is
the price of parity, and it is reversible later, module by module, once a
benchmark exists to prove each move safe.

### Job isolation

`artifacts/` and `briefs/` are **shared** across jobs and content-addressed —
the same video under the same config yields the same `stage_key`, so sharing
them is what makes a repeat request nearly free. `jobs/<id>/inbox` and
`jobs/<id>/reports` are **private**. `DIRS` is a `ContextVar`-backed proxy, so
the pipeline code still writes `DIRS['inbox']` and gets this job's paths.

---

## 3. Install

Requires **Python 3.11+** and **ffmpeg/ffprobe on PATH**.

```bash
cd Backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS

pip install -r requirements.txt
# GPU-free box (the normal case — vision is hosted):
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

The default torch wheel pulls ~2 GB of CUDA libraries this pipeline never
uses. Vision is hosted; Whisper and BGE both run on CPU.

**ffmpeg and ffprobe must be on PATH.** They are not pip-installable, and
without them the server starts, `/health` says ok, and every job dies in
Phase 1.

```bash
winget install Gyan.FFmpeg     # Windows
brew install ffmpeg            # macOS
apt-get install ffmpeg         # Linux
```

```bash
cp .env.example .env    # then set GEMINI_API_KEY
python tools/check_deps.py     # confirms all 21 packages + both binaries
python tools/check_key.py      # is the key live? (costs no tokens)
```

**No quotes in `.env`**, and no spaces around `=`:

```bash
GEMINI_API_KEY=AQ.Ab8RN6...     # right
GEMINI_API_KEY="AQ.Ab8RN6..."   # wrong
```

`python-dotenv` would strip those quotes, but `docker-compose`'s `env_file`
parser does **not** — it takes them literally, and a quoted key becomes a key
*containing quotes*, which fails as a `401` that looks exactly like a bad key.

`.env` is gitignored; **`.env.example` is not**. Never put a real value in the
template — a test asserts it stays empty.

---

## 4. Environment

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Vision, brief compile, L3. No local fallback. |
| `OPENAI_API_KEY` | — | Paid fallback only, bounded by `P4.brief.paid_call_budget`. |
| `HF_TOKEN` | — | **Optional.** Raises the Hugging Face download rate limit. See below. |
| `HF_HOME` | `~/.cache/huggingface` | Where model weights cache. Persist it in production. |
| `AUDITOR_DATA_ROOT` | `./data` | Put it on a persistent volume — it holds the cache. |
| `AUDITOR_MAX_VIDEOS` | `25` | Per-job ceiling (notebook `MAX_VIDEOS`). |
| `AUDITOR_BRIEF_COMPILE_RUNS` | `3` | Consensus runs (notebook `BRIEF_COMPILE_RUNS`). |
| `AUDITOR_BRIEF_KEEP_THRESHOLD` | `0.5` | Majority keep threshold. |
| `AUDITOR_MAX_CONCURRENT_JOBS` | `1` | Raise deliberately — see §7. |
| `AUDITOR_DOWNLOAD_WORKERS` | `4` | Parallel video fetches. |
| `AUDITOR_DECODE_WORKERS` | `4` | Parallel Phase 1 decode. `1` = notebook's own code path. |
| `AUDITOR_VISION_WORKERS` | `1` | Leave at 1 unless on a paid tier — see §7. |
| `AUDITOR_AUDIT_WORKERS` | `1` | As above. |
| `AUDITOR_JOB_TIMEOUT_S` | `10800` | Checked at phase boundaries. |
| `AUDITOR_KEEP_JOB_FILES_HOURS` | `72` | Sweeps `jobs/<id>/inbox` and `/reports` only. |
| `AUDITOR_COOKIES_FILE` | — | cookies.txt for TikTok. See Troubleshooting. |
| `AUDITOR_PROBE_ON_STARTUP` | `true` | Live model probe at boot, once. |
| `AUDITOR_LOG_JSON` | `false` | JSON log lines. |
| `AUDITOR_API_KEYS` | — | Comma-separated. **Empty = the API is open.** Set before exposing a port. |
| `AUDITOR_CORS_ORIGINS` | — | Empty = no CORS headers, correct for server-to-server. |
| `AUDITOR_MAX_QUEUED_JOBS` | `20` | Backpressure; `429` beyond it. |
| `AUDITOR_MAX_BODY_BYTES` | `2097152` | `413` beyond it. |
| `AUDITOR_SHUTDOWN_GRACE_S` | `20` | SIGTERM drain window. |
| `AUDITOR_KEEP_ARTIFACTS_DAYS` | `30` | Cache retention. `0` = never sweep. |
| `AUDITOR_MIN_FREE_DISK_MB` | `2048` | Logs an error below this. |

### Hugging Face token — optional, and why you might still want one

Three models are pulled from the Hub on first use:

| Model | Size | Used by |
|---|---|---|
| `faster-whisper` large-v3-turbo (CTranslate2) | ~1.6 GB | Phase 2 ASR |
| `openai/whisper-large-v3-turbo` | ~1.6 GB | ASR fallback path |
| `BAAI/bge-small-en-v1.5` | ~130 MB | Phase 6 L2 rung |

All three are **public**, so the pipeline works with no token at all. What a
token buys is a much higher download rate limit — anonymous pulls are
throttled per IP, and a datacentre IP is throttled far harder than a home
connection. On a cold container fetching ~1.8 GB that is the difference
between a slow first request and a `429` that fails the job.

Set `HF_TOKEN` if you deploy to a cloud host, if you see rate-limit errors
during model download, or if you later swap in a gated model. Get one at
[huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) —
**"Read" scope is enough**; this process never uploads anything, so a Write
token only widens the blast radius if it leaks.

`HUGGING_FACE_HUB_TOKEN` is accepted as an alias. Whichever you set, the app
exports **both** at startup, because `huggingface_hub` has used both names
across versions.

**No pipeline code changed for this.** `WhisperModel(name, …)` and
`SentenceTransformer(model_id, …)` take no token argument — all three loaders
resolve credentials through `huggingface_hub`, which reads the process
environment. Exporting the variable *is* the whole integration, which is
exactly why it costs nothing in parity.

---

## 5. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Interactive docs at `http://localhost:8000/docs`.

### Submit a job

```bash
curl -X POST http://localhost:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{
        "video_urls": [
          "https://www.tiktok.com/@autumndrews/video/7674625522189618445",
          "https://www.tiktok.com/@fleetwoodrose/video/7678124132499803422"
        ],
        "brief_url": "https://docs.google.com/document/d/1uWKQ.../edit",
        "label": "pill organiser, week 1"
      }'
```

```json
{ "job_id": "9f3c2a1b4d5e6f70", "status": "queued", "poll": "/jobs/9f3c2a1b4d5e6f70" }
```

### Poll

```bash
curl http://localhost:8000/jobs/9f3c2a1b4d5e6f70
```

```jsonc
{
  "job_id": "9f3c2a1b4d5e6f70",
  "status": "succeeded",
  "phase": "done",
  "elapsed_s": 412.8,
  "brief": {
    "brief_hash": "4a9c…", "approved": true,
    "approved_by": "api:freeze-on-first-compile",
    "scoring_units": 11,
    "named_angles": ["No judgement zone", "Health journey"]
  },
  "results": [{
    "source": "7674625522189618445.mp4",
    "status": "ok",
    "score": {
      "headline": 83.0, "literal_headline": 74.0,
      "status_band": "APPROVED", "coverage": 0.91,
      "lead_with_band": false
    },
    "standing": "ON_BRIEF",
    "creative_angle": {
      "angle": "A candid morning-routine confessional…",
      "named_angles": ["No judgement zone", "Health journey"],
      "concept_fit": [
        { "angle": "No judgement zone", "percent": 70 },
        { "angle": "Health journey",    "percent": 30 }
      ]
    },
    "verdict_mix": { "PASS": 7, "FAIL": 2, "UNCERTAIN": 2 },
    "report_html_url": "/jobs/9f3c2a1b4d5e6f70/report/7674625522189618445.html"
  }],
  "angle_distribution": [
    { "angle": "No judgement zone", "videos": 2, "mean_percent": 62.5 }
  ]
}
```

### Endpoints

| Method | Path | Auth | |
|---|---|---|---|
| `POST` | `/analyze` | key | Queue an audit. `202` + `job_id`. |
| `GET` | `/jobs/{id}` | key | Status, progress, results. |
| `GET` | `/jobs` | key | Recent jobs, including ones that survived a restart. |
| `GET` | `/jobs/{id}/report/{video_id}.html` | key | The self-contained HTML report. |
| `POST` | `/briefs/compile` | key | Compile a brief alone, to inspect requirements. |
| `GET` | `/config` | key | Effective settings. Keys appear as a length, never a value. |
| `GET` | `/health` | open | **Liveness.** Cheap, no model, no key. Point restart policies here. |
| `GET` | `/ready` | open | **Readiness.** `503` until it can serve; reports the model probe and whether auth is on. |
| `GET` | `/metrics` | open | Prometheus text format. |

Auth is by `x-api-key` (or `Authorization: Bearer`) and is **off until
`AUDITOR_API_KEYS` is set** — `/ready` says `auth: OPEN` so an unprotected
deployment is visible rather than assumed.

**Never point a restart policy at `/ready`.** It reports a missing API key as
not-ready, and a container restarted for that reason restarts forever.

---

## 6. Reading the response correctly

- **`headline` can be lower than `literal_headline`.** Credit is not the same
  as literal instruction-following.
- **If `lead_with_band` is true, show the band.** `86.0` beside `REJECTED`
  looks like a contradiction; both are correct — 86 is the best case, the band
  is what the *decided* half supports.
- **`coverage` below 1.0 means part of the weight was never decided.** Those
  requirements are UNCERTAIN, and UNCERTAIN is an abstention.
- **`can_fail_on: {"ocr": false}`** means OCR could not look well enough to
  assert an absence, so OCR-mode requirements read UNCERTAIN rather than FAIL.
- **`concept_fit` is a description.** Never rank creators by it.

---

## 7. Concurrency, GPU, performance

Measured on the real pipeline:

| Stage | Cost |
|---|---|
| ASR model load | ~50 s, **once per job** |
| Vision, per video | **72–240 s** — the dominant cost |
| Brief compile | 3 model calls, **once per brief**, then cached forever |
| Cold 3-video job | **5–12 minutes** |

That is why the API is asynchronous. It is also why
`AUDITOR_MAX_CONCURRENT_JOBS` defaults to **1**: Phase 2 loads Whisper once,
frees it, then loads OCR once, and Phase 3 loads the vision backend once.
Concurrent jobs multiply those loads and, on a GPU box, race for VRAM.

### Where parallelism is used, and where it is refused

Per stage, because the stages fail differently.

| Stage | Workers | Why |
|---|---|---|
| **Download** | 4 | Pure network wait, independent per URL, results are files on disk. Free. |
| **Phase 1 decode** | 4 | The CPU hot spot. Independent per video, content-addressed, each writing its own artifact directory. **Measured 1.83× on 4 clips / 8 cores with byte-identical manifests** (`tools/prove_parallel_decode.py`). Capped because each worker holds decoded frames. |
| **Phase 2 ASR/OCR** | 1 | Whisper loads once and is freed before OCR loads. Concurrency would multiply a ~50 s model load, not divide it. |
| **Phase 3 vision** | 1 | *Looks* like the biggest win — 72–240 s per video, nearly all of it waiting on Gemini. **Refused anyway.** |
| **Phase 6 audit** | 1 | Several model calls per video, same reason. |

The last two deserve the explanation. A live run against a real free-tier key
returned **503 "high demand" on seven of eight models and 429 on the eighth**.
Issuing those N-at-once does not make the job faster; it converts a slow job
into a failed one, and the retry ladder then spends its budget on
self-inflicted congestion. `AUDITOR_VISION_WORKERS` exists for a paid tier.
Raise it slowly.

`AUDITOR_*_WORKERS=1` runs **inline** — no threads at all — so sequential is
the notebook's code path exactly, not an imitation of it.

**One implementation note worth knowing.** `DIRS` is a `ContextVar`, and
`ThreadPoolExecutor` does *not* copy the calling context into its workers. A
naive `pool.submit` would give every worker an unset `DIRS`, silently falling
back to the shared inbox — two concurrent jobs would read each other's videos,
with no exception and no wrong-looking path. `app/parallel.py` does
`copy_context()` per task, and a test asserts it.

**No GPU is required.** Vision is hosted; Whisper runs CPU int8 and BGE runs on
CPU. A GPU only speeds up ASR.

Re-running costs almost nothing: everything is content-addressed, so a video
already processed under the same config is a cache hit.

---

## 8. Tests

```bash
.venv\Scripts\python.exe -m pytest tests -q
```

- `tests/test_extraction.py` — every entry point survives regeneration; no
  module-level statement runs a stage; every notebook cell is either mapped or
  excluded *by decision*; scoring contains no model call; `concept_fit`
  validation (drop / renormalise / preserve).
- `tests/test_api.py` — validation is specific not generic; no key reaches
  `/config` or the logs; a missing key is a `503`, not a job that fails twelve
  minutes later.

No key, no network, no model needed for either.

```bash
python tools/check_deps.py            # every dep + ffmpeg/ffprobe on PATH
python tools/check_entrypoints.py     # 58/58 entry points
python tools/audit_backend.py         # 8-section integrity audit
python tools/smoke_api.py             # API wiring
python tools/prove_parallel_decode.py # real ffmpeg: parallel == sequential
```

`audit_backend.py` is the one to run after any notebook change. It asks
whether the **generated** layer still matches the notebook — decorators,
classes and functions counted on both sides, every recent fix confirmed
present, the extracted code's *behaviour* exercised, and secret hygiene
checked. It is what caught `@dataclass` being stripped from 38 of 39
definitions while 68 tests passed.

---

## 9. Troubleshooting

**`503 GEMINI_API_KEY is not set`** — set it in `.env`. There is deliberately
no local fallback: quietly using a different model would change what every
score means.

**Every video URL fails to download** — that is one cause, not N unlucky
links. Usually TikTok refusing an anonymous request, and a datacentre IP is
refused harder than a residential one. Export cookies from a logged-in browser
("Get cookies.txt LOCALLY"), set `AUDITOR_COOKIES_FILE`. Otherwise
`pip install -U yt-dlp`.

**A video has no visual evidence** — the report still builds; visual
requirements read UNCERTAIN rather than FAIL. Check `warnings` on the job.

**`429` or a rate-limit error while a model downloads** — that is Hugging
Face throttling an anonymous IP, not your Gemini quota. Set `HF_TOKEN`. The
startup log says which mode you are in (`hugging face: anonymous` vs
`hugging face: HF_TOKEN`).

**`brief.unstable: true`** — the consensus compile disagreed across runs. The
requirement set is the majority; the disagreement is in `brief.flags`. Inspect
with `POST /briefs/compile` before running videos.

**Scores changed for the same video and brief** — check `approved_by`. If
someone called `recompile: true`, the requirement set changed, and scores
before and after are not comparable. That is why the first compile is frozen.

---

## 10. Deployment

```bash
cp .env.example .env     # GEMINI_API_KEY, and AUDITOR_API_KEYS before exposing
docker compose up -d --build
curl localhost:8000/ready
```

Full guide, including an honest ranking of **free** hosting for this workload:
**[`docs/05_deployment.md`](docs/05_deployment.md)**.

The short version. Four numbers decide it: **~4 GB working set (size for 8)**,
**ffmpeg on PATH**, **5–12 minute jobs**, **a persistent volume**. That rules
out every 512 MB free tier and every platform with a 5-minute request timeout.

- **Oracle Cloud Always Free** — 4 ARM cores / 24 GB / 200 GB, free forever.
  The only free tier that genuinely fits, and ARM64 is **verified**: every
  dependency ships a `manylinux_*_aarch64` wheel, so no source build.
  One-shot installer: **[`deploy/oracle/setup.sh`](deploy/oracle/setup.sh)**,
  guide: **[`deploy/oracle/README.md`](deploy/oracle/README.md)**.
- **Hugging Face Spaces** — free CPU is 2 vCPU / 16 GB and Docker-native, but
  storage is ephemeral and free Spaces are public, so set `AUDITOR_API_KEYS`.
- **Cloud Run** — generous free tier, scale-to-zero, service-account auth
  instead of an API key. No persistent disk without GCS FUSE.
- **A €4–7/mo VPS (Hetzner)** — better than any free tier for steady use.

**Run one worker per container.** The job store and the pipeline namespace are
in-process; scale by adding containers with a shared `AUDITOR_DATA_ROOT`, which
is safe because the artifact store is content-addressed.

Route yt-dlp through a residential proxy if URL ingestion matters in
production — this is the piece most likely to degrade quietly.

---

## 11. Regenerating after a notebook change

```bash
python tools/extract_from_notebook.py
python tools/check_entrypoints.py
.venv\Scripts\python.exe -m pytest tests -q
```

A new notebook cell must be added to **`CELL_MAP`** (extract it) or
**`EXCLUDED`** (with a reason). The extractor refuses to run if a cell is
neither, and a test asserts the same — no cell is ever silently forgotten.
