# Implementation Plan — AI TikTok Video Brief Compliance & Creative Audit System

**Target environment:** Google Colab, Python 3.12
**Team size:** 1 engineer
**Optimization objective:** maximum evaluation accuracy per GPU-hour and per human-hour
**Companion document:** [product.md](product.md) — this plan implements that spec; where it deviates, the deviation is stated and justified.

---

## 0. How to read this plan

This document is a build order, not a design essay. Each phase has:

| Field | Meaning |
|---|---|
| **Objective** | The single thing the phase must make true |
| **Why here** | Why this phase sits at this point in the order |
| **Build** | Modules/files produced |
| **Technical detail** | Every library, model, parameter and algorithm involved, and why it was chosen over alternatives |
| **Challenges** | The specific ways this phase fails in practice |
| **Resource budget** | GPU/VRAM/wall-clock cost and how to keep it down |
| **Exit criteria** | Objective, checkable conditions to move on |
| **Effort** | Realistic solo estimate at ~15–20 h/week |

Do not start a phase until the previous phase's exit criteria are met. The single most common way a project like this dies is building the fun part (the VLM prompting) on top of an unreliable part (frame timestamps), then spending six weeks debugging the wrong layer.

**No code is written in this document by design.** Everything here is the specification you implement from.

---

## 1. Reality check — what changes because it is Colab and because you are alone

`product.md` describes a production system: FastAPI, Postgres, S3, Redis, Celery, Next.js, vLLM, Qdrant. All of that is correct as a destination and wrong as a starting point for a single person on Colab. Building it early would consume 60–70% of your time on infrastructure that produces zero evaluation accuracy.

### 1.1 Constraint inventory

| Constraint | Consequence | Mitigation strategy |
|---|---|---|
| Colab sessions are ephemeral (free tier ~12h max, ~90 min idle disconnect) | Anything not written to Drive is lost | Aggressive artifact caching to Drive; every stage resumable from cache |
| Colab local disk is fast, Drive is slow for many small files | Writing 3,000 JPEG frames to Drive takes minutes | Work in `/content/work`, tar and sync to Drive at stage boundaries only |
| Every session re-installs dependencies (3–8 min) | Wasted time, and version drift between sessions | A single pinned `requirements.lock` + one bootstrap cell + wheel cache on Drive |
| Free tier GPU is T4 (Turing, sm_75): 16 GB, **no bf16**, **no FlashAttention-2** | An 8B model in fp16 (16 GB) will not fit | fp16 + `sdpa` attention; 4B at fp16, or 8B at 4-bit |
| Pro tier gives L4 (24 GB, Ada) or A100 (40 GB) | bf16 and FA2 available; 8B fits comfortably | Do development on T4/4B, run benchmark sweeps on L4/A100 |
| Compute units are money | Idle notebooks and repeated inference burn budget | Cache-first design; never re-run a completed stage |
| One person | No parallel workstreams; every hour of infra is an hour not spent on accuracy | Defer FastAPI/Next.js/Postgres/Redis/Qdrant entirely to Phase 10+ |
| No labeled dataset exists | You cannot measure anything at the start | Build a 40-video labeled benchmark by Phase 8 and stop guessing |

### 1.2 Deliberate deviations from `product.md`

These are engineering calls, each with a reason. Everything else in the spec is followed.

| Spec says | This plan says | Reason |
|---|---|---|
| Postgres + S3 + Redis | Google Drive as object store; **SQLite** (or plain JSONL + Parquet) for metadata | Same relational schema, zero ops. Migrating SQLite→Postgres later is a mechanical change if you use SQL and not ORM-specific features. |
| FastAPI + Next.js UI | **Self-contained HTML report** + **Gradio** review app | The report is the product output; a static HTML file with an embedded proxy video and clickable timestamps delivers 90% of the UI value at 2% of the cost. Gradio covers human review. FastAPI comes in Phase 10. |
| Celery/RQ job queue | Python function pipeline + content-hash cache | A queue solves concurrency you do not have. The cache solves the actual problem (don't recompute). |
| OpenCV `VideoCapture` for decoding | **PyAV** as canonical decoder, OpenCV for image ops only | OpenCV gives you a frame index and an averaged FPS. PyAV gives you the true presentation timestamp (PTS) per frame. The spec (§10) explicitly warns that `frame_index / fps` is unreliable on VFR video — PyAV *solves* that rather than warning about it. This is the single most important correctness decision in the preprocessing layer. |
| `openai-whisper` | **faster-whisper** (CTranslate2) | 3–5× faster, ~50% less VRAM, same models, same word timestamps, plus built-in Silero VAD which materially reduces hallucination on music-heavy TikToks. |
| PaddleOCR | PaddleOCR **or RapidOCR (ONNX)** — decided by an install test in Phase 0 | PaddlePaddle GPU wheels are pinned to specific CUDA versions and routinely conflict with the CUDA that PyTorch ships in the Colab image. RapidOCR runs the same PP-OCR models on ONNXRuntime with no Paddle dependency. Pick whichever installs cleanly; the accuracy is equivalent. |
| BGE-M3 + Qdrant | `bge-small-en-v1.5` + a NumPy cosine matrix | You will have hundreds of vectors, not millions. A vector database at this scale is pure overhead. Upgrade to BGE-M3 only when you need multilingual; add Qdrant only past ~100k vectors. |
| Build preprocessing fully, then ASR, then OCR, then VLM | Same order, but insert **Milestone A: a working end-to-end audit with no VLM at all** after Phase 2 | Proves the brief→evidence→verdict join before the most expensive component is introduced. Transcript + OCR alone can already adjudicate speech, on-screen-text, CTA-in-text and forbidden-phrase requirements. |
| vLLM for serving | Transformers for development; vLLM **offline batch API** only for Phase 9 sweeps | You have no concurrent users. vLLM's value here is batched throughput during ablation runs, not serving. |

---

## 2. The resource strategy — the eight levers, in ROI order

Internalize this list. Every time you are about to spend GPU time, check it against this.

1. **Content-hash caching (biggest win by far).** A video is decoded once, transcribed once, OCR'd once, and VLM-analyzed once *ever* — across all sessions, all briefs, all evaluator versions. Auditing the same video against a second brief must cost ~2 seconds, not 40. This is spec §54/§55 and it is non-negotiable.
2. **Stage isolation in VRAM.** Never hold Whisper, OCR and Qwen3-VL resident simultaneously. Load → run → `del model` → `gc.collect()` → `torch.cuda.empty_cache()`. On a T4 this is the difference between working and OOM.
3. **Frame budget discipline.** Vision tokens dominate VLM cost, and cost scales linearly with frames. 32 well-chosen frames beat 128 uniform ones. Prove this with the Phase 9 ablation instead of assuming it.
4. **Deterministic-before-semantic.** Exact/fuzzy string matching, timestamp arithmetic and regex resolve a large fraction of requirements at zero GPU cost. Only escalate to embeddings, and only then to an LLM, when the cheaper layer is inconclusive. Instrument the escalation rate.
5. **Model-size ladder.** Start at Qwen3-VL-4B. Escalate to 8B only where the benchmark shows a measured, material gap. "Bigger is probably better" is not evidence.
6. **Text-only passes are cheap.** Pass 2 (requirement adjudication) takes no images. Run it on the already-resident VLM in text-only mode, or on a hosted API for a fraction of a cent. Do not load a second local model for it.
7. **Quantization where it does not hurt.** 4-bit NF4 or AWQ turns 8B from "doesn't fit on a T4" into "fits with room for 48 frames". Validate quality loss on the benchmark, do not assume it.
8. **Batch the benchmark, not the demo.** Interactive single-video runs are for debugging. Ablations run overnight as one batched job over the whole benchmark set.

---

## 3. Revised architecture for the Colab MVP

```
                          ┌──────────────────────────────────────┐
                          │  Google Drive (durable artifacts)    │
                          │  cache/ · benchmark/ · reports/      │
                          └───────────────┬──────────────────────┘
                                          │ (tar sync at stage boundaries)
  video.mp4 ─────────────────────┐        │
                                 ▼        ▼
                    ┌────────────────────────────────┐
                    │ STAGE 1  probe + preflight      │  ffprobe / PyAV
                    │          → media_meta.json      │  key = sha256(bytes)
                    └───────────────┬────────────────┘
                                    ▼
                    ┌────────────────────────────────┐
                    │ STAGE 2  sampling plan          │  pure Python, no I/O
                    │          → frame_plan.json      │  key = video+sampler_cfg
                    └───────────────┬────────────────┘
                                    ▼
        ┌───────────────────────────┴──────────────────────────┐
        ▼                                                      ▼
┌───────────────────┐                              ┌───────────────────────┐
│ STAGE 3  audio     │ ffmpeg → 16 kHz mono WAV     │ STAGE 4  frames        │ PyAV single pass
│  → audio.wav       │                              │  → frames/ + manifest  │ true PTS per frame
└─────────┬─────────┘                              └───────────┬───────────┘
          ▼                                                     │
┌───────────────────┐                            ┌──────────────┴─────────────┐
│ STAGE 5  ASR       │ faster-whisper             ▼                            ▼
│  → transcript.json │ (VAD, word ts)   ┌──────────────────┐      ┌────────────────────┐
└─────────┬─────────┘                   │ STAGE 6  OCR      │      │ STAGE 7  VLM Pass 1 │
          │                             │  → ocr.json       │      │  → visual_ev.json   │
          │                             │ PP-OCR / RapidOCR │      │ Qwen3-VL, no verdict│
          │                             └─────────┬────────┘      └──────────┬─────────┘
          └────────────────────┬──────────────────┴──────────────────────────┘
                               ▼
                 ┌──────────────────────────────┐
                 │ STAGE 8  evidence normalizer  │  one timeline, one schema
                 │  → evidence.json  (REUSABLE)  │  ← the durable asset
                 └───────────────┬──────────────┘
                                 │
   brief.txt ──► STAGE 9 brief compiler ──► requirements.json
                                 │           (LLM + Pydantic, cached by brief hash)
                                 ▼
                 ┌──────────────────────────────┐
                 │ STAGE 10 requirement evaluator│  L1 rules → L2 embeddings → L3 LLM
                 │  → requirement_results.json   │  + hook module + claims module
                 └───────────────┬──────────────┘
                                 ▼
                 ┌──────────────────────────────┐
                 │ STAGE 11 deterministic scoring│  pure arithmetic, no model
                 └───────────────┬──────────────┘
                                 ▼
                 ┌──────────────────────────────┐
                 │ STAGE 12 report (JSON + HTML) │  clickable evidence timeline
                 └───────────────┬──────────────┘
                                 ▼
                       Gradio human review ──► corrections.jsonl ──► benchmark
```

The critical structural property: **stages 1–8 depend only on the video. Stages 9–12 depend on the brief.** One video, N briefs = one expensive run plus N cheap runs.

---

## 4. Project layout and the stage contract

### 4.1 Code lives in a real repo, not in notebook cells

Non-negotiable. Notebook-cell code cannot be tested, versioned meaningfully, diffed, or migrated to FastAPI later. Structure:

```
tiktok-auditor/                      ← GitHub repo, cloned into Colab each session
├── auditor/
│   ├── config.py                    ← all tunables in one dataclass, versioned
│   ├── cache.py                     ← content-hash cache (the heart of the system)
│   ├── preprocessing/
│   │   ├── probe.py                 ← ffprobe wrapper → MediaMeta
│   │   ├── preflight.py             ← quality gates (spec §52)
│   │   ├── sampler.py               ← timestamp planning (pure, unit-testable)
│   │   ├── decode.py                ← PyAV frame extraction at exact PTS
│   │   ├── audio.py                 ← ffmpeg audio extraction
│   │   └── scenes.py                ← shot boundary detection
│   ├── asr/whisper.py
│   ├── ocr/engine.py                ← thin interface over PaddleOCR | RapidOCR
│   ├── vision/
│   │   ├── qwen.py                  ← model loading, VRAM lifecycle, generation
│   │   ├── prompts/                 ← versioned .txt/.jinja files, NEVER inline strings
│   │   └── schemas.py
│   ├── brief/{parser.py,taxonomy.py,schemas.py}
│   ├── evidence/{normalizer.py,timeline.py,dedupe.py}
│   ├── evaluation/{matcher.py,rules.py,adjudicator.py,hook.py,claims.py,scoring.py}
│   ├── reports/{json_report.py,html_report.py,templates/}
│   └── pipeline.py                  ← orchestrates stages, honours the cache
├── notebooks/
│   ├── 00_bootstrap.ipynb           ← install + mount + smoke test
│   ├── 01_single_video.ipynb        ← interactive debugging
│   ├── 02_batch_run.ipynb           ← benchmark sweeps
│   └── 03_review_ui.ipynb           ← Gradio labeling/correction app
├── tests/                           ← pytest; runs on CPU in seconds
├── benchmark/                       ← labels, metrics scripts, ablation configs
├── prompts/                         ← prompt registry with semantic versions
├── requirements.lock
└── README.md
```

In Colab: `git clone`, then `pip install -e .`. Edit locally, push, pull in Colab — or edit in Colab with `%load_ext autoreload` for tight loops and push at the end of the session. Never let the notebook become the source of truth.

### 4.2 Drive layout (durable state only)

```
MyDrive/tiktok-auditor/
├── videos/originals/{sha256[:16]}.mp4     ← immutable, content-addressed
├── cache/
│   ├── media_meta/{video_hash}.json
│   ├── frames/{video_hash}__{sampler_hash}.tar     ← tarball, not loose files
│   ├── audio/{video_hash}.wav
│   ├── transcript/{video_hash}__{asr_cfg_hash}.json
│   ├── ocr/{video_hash}__{sampler_hash}__{ocr_cfg_hash}.json
│   ├── visual/{video_hash}__{sampler_hash}__{model_hash}__{prompt_ver}.json
│   ├── evidence/{video_hash}__{pipeline_ver}.json
│   └── requirements/{brief_hash}__{parser_ver}.json
├── benchmark/{videos.jsonl, labels.jsonl, corrections.jsonl}
├── runs/{run_id}/  ← observability logs, ablation outputs, metrics
└── reports/{audit_id}.html
```

### 4.3 The stage contract (implement this once, in `cache.py`)

Every stage is a pure function of an explicit key:

```
key = sha256(canonical_json({
    "stage":        "asr",
    "stage_version": "1.2.0",       # bump when the stage's logic changes
    "inputs":       [video_hash],    # hashes of upstream artifacts
    "config":       {...}            # every parameter that affects output
}))
```

Rules:
- If `cache/<stage>/<key>.json` exists, load it and skip. Log `cache_hit`.
- Every artifact embeds its own `key`, `stage_version`, library versions, model id + **pinned revision SHA**, prompt version, and wall-clock duration. This is spec §45 and §65, and it is what makes the Phase 9 ablations interpretable.
- `--force` flag to bypass, for debugging.
- Never mutate a cached artifact. Bump the version instead.

Get this right in Phase 0. Retrofitting it later is painful and you will not do it.

---

# PHASE 0 — Environment, dependency resolution, and the cache harness

**Effort:** 3–5 days. **Do not rush this phase.** Dependency conflicts on Colab will otherwise ambush you in week 6, mid-experiment.

## Objective
One Colab notebook that, from a cold runtime, installs everything, loads each of the three model families in isolation, runs a smoke test on one sample video, and demonstrates a cache hit on a second run.

## Why here
Every downstream phase depends on a reproducible environment. Python 3.12 + CUDA + PyTorch + PaddlePaddle + ONNXRuntime + CTranslate2 in one runtime is a genuinely hostile dependency graph, and you need to know *now* which combination works.

## Technical detail

### 0.1 Baseline probe
First, record what the Colab image actually gives you — do not assume:
- Python version (`sys.version`), and confirm it is 3.12
- `nvidia-smi`: GPU model, driver, VRAM
- `torch.__version__`, `torch.version.cuda`, `torch.cuda.get_device_capability()`
- **Compute capability is the branch point:**
  - `sm_75` (T4): fp16 only, **no bf16**, no FlashAttention-2 → use `attn_implementation="sdpa"`, `torch_dtype=torch.float16`
  - `sm_80` (A100) / `sm_89` (L4): bf16 and FA2 available → `torch.bfloat16`, optionally `flash_attention_2`
- Free disk in `/content` (models + frames need 30–50 GB headroom)

Write this into `auditor/config.py` as an auto-detected `HardwareProfile` so the same code runs on T4 and A100 without edits. Do not hardcode dtype anywhere else.

### 0.2 Dependency set, with the reasoning for each

**System (apt):**
- `ffmpeg` — usually preinstalled on Colab. Verify `ffmpeg -version` and `ffprobe -version`. This is the authoritative container/metadata inspector (spec §7).

**Core:**
- `torch`, `torchvision` — preinstalled; **do not reinstall**. Reinstalling torch on Colab is the #1 cause of a broken CUDA runtime. Build everything else around the preinstalled version.
- `av` (PyAV) — FFmpeg bindings. Canonical decoder. Gives real PTS timestamps. Ships manylinux wheels for 3.12; no compilation.
- `opencv-python-headless` — image ops only (resize, color conversion, histograms, JPEG encode). Use `headless`: the full package pulls GUI deps you cannot use in Colab.
- `numpy`, `pillow`, `pydantic` (v2), `pydantic-settings`

**ASR:**
- `faster-whisper` → pulls `ctranslate2`, `onnxruntime` (for the Silero VAD), `tokenizers`, `av`.
  - Version-pin note: CTranslate2 wheels are built against a specific CUDA/cuDNN. If GPU inference fails with a cuDNN symbol error, install the matching `nvidia-cudnn-cu12` version or fall back to `compute_type="int8"` on CPU (a 30-second clip on CPU with a `small` model is ~10–20 s — survivable).
  - Alternative if faster-whisper fights you: `transformers` `WhisperForConditionalGeneration` with `return_timestamps="word"`. Slower and more VRAM, but uses the torch stack you already have — zero new native dependencies. Keep this as a documented fallback.

**OCR — run the bake-off in this phase:**
- Option A: `paddleocr` (3.x) + `paddlepaddle` (CPU) or `paddlepaddle-gpu`.
  - Risks: Python 3.12 wheel availability; CUDA version mismatch with torch; Paddle and torch both grabbing VRAM; Paddle's own model-download step.
  - **If you use it, prefer the CPU build.** TikTok caption text is large and high-contrast; CPU PP-OCR on ~40 frames takes seconds to a couple of minutes, and you completely avoid the CUDA conflict class of bugs.
- Option B: `rapidocr-onnxruntime` (or the current `rapidocr` package) — PP-OCR detection/recognition models converted to ONNX, running on ONNXRuntime. No Paddle at all. Nearly identical accuracy, trivially installable, CPU or GPU.
- **Decision rule:** try A for 45 minutes. If the GPU build does not import cleanly alongside torch, take B and move on. Record the decision in the decision log. Either way, hide it behind `auditor/ocr/engine.py` with a two-method interface (`detect_and_recognize(image) -> list[OCRLine]`) so swapping costs an afternoon.

**Vision-language model:**
- `transformers` — needs a version new enough to include the Qwen3-VL model classes. Check `Qwen3VLForConditionalGeneration` imports; if not, install from the git main branch as the Qwen model card instructs.
- `accelerate` — for `device_map="auto"` and offload.
- `qwen-vl-utils` — Qwen's official preprocessing helper (video reading, dynamic resolution, `sample_fps` handling). **Important:** it performs its own resizing; the Qwen repo explicitly warns against double-resizing (spec §20). Decide one owner per path and document it.
- **Video reader backend caveat:** `qwen-vl-utils` can use decord, torchvision or torchcodec. **Decord has no reliable Python 3.12 wheels and is effectively unmaintained** — do not use it. Set the backend to `torchvision` or `torchcodec` via the library's env var. In practice you will mostly bypass this anyway, because your canonical path (Architecture B) feeds a pre-decoded frame list rather than a video file.
- `bitsandbytes` — 4-bit NF4 quantization, needed to fit 8B on a T4.
- Optional: `autoawq` if a pre-quantized AWQ checkpoint of the model exists — better throughput than bnb-NF4 on Turing.
- **Do not install `flash-attn`.** On T4 it will not work at all; even on L4/A100 it compiles for 20+ minutes per session unless a prebuilt wheel matches exactly. `sdpa` is the right default and is memory-efficient enough at this frame count.

**Semantic matching:**
- `sentence-transformers` + `BAAI/bge-small-en-v1.5` (33M params, 384-dim, ~130 MB). Loads in seconds, runs on CPU acceptably.

**Utility:**
- `scenedetect` (PySceneDetect) — shot boundary detection
- `rapidfuzz` — fast fuzzy string matching for phrase requirements
- `json-repair` — salvages near-miss JSON from LLM output (removes an entire class of retry logic)
- `jinja2` — HTML report templating
- `gradio` — human review UI (Phase 8)
- `pandas`, `pyarrow` — benchmark tables
- `pytest` — the unit tests that keep the sampler honest
- `huggingface_hub[hf_transfer]` + `HF_HUB_ENABLE_HF_TRANSFER=1` — significantly faster weight downloads

### 0.3 Session bootstrap design

Target: cold runtime → ready in under 6 minutes.

1. `nvidia-smi` + hardware profile detection
2. Mount Drive at `/content/drive`
3. `git clone` (or `git pull`) the repo into `/content/tiktok-auditor`; `pip install -e . --no-deps` then install pinned deps
4. Set env: `HF_HOME=/content/hf_cache` (**local disk, not Drive**)
5. `sys.path` / `%load_ext autoreload`
6. Assert-based smoke test: ffmpeg present, torch sees GPU, each model class imports

**On caching model weights to Drive — a trap worth naming:** it is tempting to set `HF_HOME` to a Drive path so you never re-download 8–16 GB. In practice Drive read throughput makes loading large weights *slower* than re-downloading them from the HF CDN into Colab's local disk. **Recommendation: keep `HF_HOME` local and re-download each session** (with `hf_transfer` this is a few minutes for a 4B model). Cache *artifacts* on Drive, not weights. Reconsider only if you measure otherwise for your specific account.

### 0.4 Build `cache.py` now
Canonical JSON serialization (sorted keys, fixed float formatting), SHA-256 keying, artifact envelope with provenance metadata, `--force`, and structured logging of hit/miss. Write its unit tests. This is ~200 lines that will save you tens of GPU-hours.

### 0.5 Sample video set
Collect 5 videos by hand covering: (a) normal talking-head + product, (b) fast-cut montage, (c) heavy burned-in captions, (d) music-only / no speech, (e) portrait video with rotation metadata. These five are your smoke-test corpus for the next five phases.

## Challenges and how to handle them

| Challenge | Approach |
|---|---|
| PaddlePaddle ↔ torch CUDA conflict | Timeboxed bake-off; prefer Paddle-CPU or RapidOCR-ONNX. Hide behind an interface. |
| A `pip install` silently upgrading torch and breaking CUDA | Pin torch out of the resolver (`--no-deps` for the offenders); after every install, re-assert `torch.cuda.is_available()` |
| Transformers not yet exposing Qwen3-VL classes | Install from git main as the model card specifies; pin the commit SHA in `requirements.lock` |
| bf16 code silently producing garbage on T4 | Never hardcode dtype — read it from `HardwareProfile`. Add an assertion that fails loudly on unsupported dtype. |
| Non-reproducible installs across sessions | `pip freeze > requirements.lock`, commit it, install from it. Re-freeze deliberately, never accidentally. |

## Resource budget
Negligible GPU. Mostly download bandwidth and patience.

## Exit criteria
- [ ] Cold runtime → smoke test green in < 8 minutes
- [ ] Each of ffprobe/PyAV, faster-whisper, the chosen OCR engine, and Qwen3-VL-4B loads and produces output on a sample, **each in an isolated cell with VRAM freed after**
- [ ] `requirements.lock` reproduces the environment in a fresh runtime
- [ ] `cache.py` demonstrates a hit: second run of an artificial stage returns in <100 ms
- [ ] `HardwareProfile` correctly reports dtype/attention for the current GPU
- [ ] OCR engine decision recorded with reasoning

---

# PHASE 1 — Preflight and deterministic preprocessing

**Effort:** 1.5 weeks. This is the phase `product.md` §93 correctly identifies as the real foundation.

## Objective
For any input video, produce a `frame_manifest.json` where **every frame carries a timestamp you can defend**, plus a normalized 16 kHz mono WAV — reproducibly, with quality gates.

## Why here
Every timestamp in the final report traces back to this layer. If frame timestamps drift by 0.4 s, a "product visible within 5 s" verdict becomes a coin flip and you will misdiagnose it as a VLM problem.

## Build
`probe.py`, `preflight.py`, `sampler.py`, `decode.py`, `audio.py`, `scenes.py`

## Technical detail

### 1.1 Probe (`ffprobe`)
Invoke `ffprobe -v error -print_format json -show_format -show_streams`. Parse into a Pydantic `MediaMeta` model covering everything in spec §7.1. Specific fields that matter more than they look:

- **Duration:** take it from the *format* section, cross-check against the video stream. They disagree more often than you would expect. Store both; use the format duration as canonical, and flag a discrepancy > 0.2 s.
- **VFR detection:** compare `r_frame_rate` (the container's nominal rate) with `avg_frame_rate` (frames ÷ duration). A meaningful divergence means variable frame rate. Set `is_vfr=True` and make sure the report knows timestamps came from PTS, not from index arithmetic. TikTok exports are frequently VFR — this is not an edge case.
- **Rotation:** two sources — the legacy `tags.rotate` and the modern `side_data_list` display matrix. Read both. Modern FFmpeg auto-applies rotation on decode; older paths do not. **You must empirically verify which happens in your PyAV build** on a video that has rotation metadata (sample video (e) exists for this). Getting this wrong silently produces sideways frames for OCR and the VLM, and OCR failure on rotated text is confusing to debug.
- **Audio presence:** absence of an audio stream is a legitimate state (spec §64), not an error. Set `has_audio=False` and let downstream stages degrade gracefully.
- `nb_frames` is frequently absent or wrong. Never rely on it. Do not use `-count_frames` (it decodes the entire file).

### 1.2 Preflight gates (spec §52)
Reject before spending GPU time: file opens, duration in `[0.5 s, MAX]`, resolution sane and non-zero, codec decodable, first frame decodes, file size under cap, MIME actually video (check magic bytes, not the extension — spec §66). Failure → status `FAILED_PREPROCESSING` with a specific reason code. Fail loudly and early; never pass broken assets downstream.

### 1.3 The sampler — a pure function, and the most testable module in the system

`plan_frames(duration, fps, config) -> list[TimestampPlan]`. **No I/O, no video, no decoding.** Just timestamps and reasons. This makes it exhaustively unit-testable, which matters because it encodes product policy.

Implementing spec §13–§16:

**Level 1 — global coverage.** Duration-tiered target frame counts (spec §14):

| Duration | Global target | Effective FPS |
|---|---|---|
| 0–10 s | 20–30 | ~2.5 |
| 10–30 s | 30–60 | ~1.5–2 |
| 30–60 s | 60–90 | ~1.5 |
| 60–180 s | 90–180 | ~1.0 |
| > 180 s | hard cap ~180 | adaptive |

Treat these as *initial* values in config, and hold them until the Phase 9 ablation gives you evidence. My prior: for 15–40 s TikToks the accuracy plateau will land around 24–40 frames, and everything past ~64 is wasted tokens. Prove it, don't assume it.

**Level 2 — critical windows.** Hook window `[0, min(5, duration)]` at 0.25 s spacing → 20 frames. CTA window `[max(0, duration-5), duration]` at 0.25 s spacing → 20 frames. Rationale (spec §15): text overlays can appear for 0.3 s; at 1 FPS you will miss them entirely, and hook detection is a headline feature of the product.

**Level 3 — adaptive refinement.** After shot boundary detection, add frames at `boundary + 0.15 s` (post-cut, once the new shot has settled — sampling exactly on the boundary often lands on a transition/blend frame that is useless to both OCR and the VLM).

**Merge and cap.** Union all timestamps, sort, deduplicate within a tolerance of ~half the minimum frame interval, then enforce a hard budget. When over budget, **thin the global tier first, never the critical windows** — that priority ordering is the whole point of hybrid sampling.

Every planned timestamp carries a `reason` enum: `hook_window` | `cta_window` | `uniform` | `scene_change` | `adaptive`. This is spec §18 and it is what lets you debug "why did the model miss the product" in minutes instead of hours.

Unit tests to write: 0.5 s video (windows overlap completely), 3 s video (hook window covers the entire video), 300 s video (cap engages), duration exactly equal to a boundary, hook and CTA windows overlapping on a 6 s video, budget enforcement preserving critical windows.

### 1.4 Decoding with PyAV — the correctness core

**The problem** (spec §10): `frame_index / fps` is wrong on VFR video, wrong when B-frames reorder presentation, and wrong when the container's nominal FPS is an approximation.

**The approach:**
1. Open the container with PyAV, take `stream = container.streams.video[0]`, note `stream.time_base`.
2. Decode sequentially (one pass, not N seeks). For each frame, true seconds = `frame.pts * float(stream.time_base)`. If `pts` is None, fall back to `frame.time`, then to interpolation, and **mark the frame's timestamp as approximate** — surfacing that flag in the evidence record (spec §64: "insufficient timestamp precision → mark evidence as approximate").
3. Walk the sorted target-timestamp list in lockstep with the decode. Keep the frame whose actual PTS is nearest each target.
4. Record **both** the requested timestamp and the actual PTS timestamp. **Use the actual one everywhere downstream.** The gap between them is a diagnostic you will be glad to have.

Why single-pass over per-timestamp seek: seeking is keyframe-based, so `-ss` before `-i` is fast but inaccurate and `-ss` after `-i` is accurate but decodes from the start anyway. For 15–60 s TikToks, one full sequential decode takes 1–3 seconds and gives exact timestamps for every frame. There is no reason to be cleverer.

For long videos (> 3 min), add a keyframe-seek optimization: seek to the nearest preceding keyframe per cluster of targets, then decode forward. Only build this if you actually have long videos.

**Orientation** (spec §19): normalize to upright once, right here. Store the applied transform in the manifest so bounding boxes can be mapped back to original coordinates (spec §24). Do not silently rotate.

**Resize policy** (spec §20) — designate one owner per path, and write it down:
```
PyAV/OpenCV  → orientation normalization + JPEG encode ONLY. No content-driven resize.
OCR engine   → owns its own preprocessing/upscaling
Qwen processor → owns vision-token budgeting via min_pixels/max_pixels
```
Store frames at native resolution (or capped at 1080 on the long edge) as JPEG quality ~92. Frames are cheap disk; text detail is not recoverable once destroyed.

### 1.5 Audio extraction
`ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le out.wav` (spec §21). 16 kHz mono PCM is what Whisper's frontend wants; supplying anything else just means an internal resample. Handle "no audio stream" by writing no file and setting the flag. Consider `-af loudnorm` only if you observe transcription problems on quiet audio — do not add it preemptively, since it changes the signal and slows extraction.

### 1.6 Shot boundary detection
PySceneDetect `ContentDetector` (HSV-space frame delta, threshold ~27 as a starting point) plus `AdaptiveDetector` for fast-cut content. Run it on a downscaled decode (e.g. 320 px wide) — you are detecting cuts, not reading text, and this cuts the cost by an order of magnitude.

Cheap alternative if you want zero extra dependencies: downscale each already-decoded frame to 64×64 grayscale, compute mean absolute difference or histogram correlation between consecutive frames, threshold adaptively (e.g. mean + 3σ). Given you are already decoding every frame in the PyAV pass, this is nearly free and integrates cleanly. **Recommendation: build the cheap version first inside the existing decode pass; add PySceneDetect only if the cheap one misses cuts on your fast-cut sample.** Fewer dependencies, fewer decodes.

Note the failure modes: fast whip-pan transitions register as cuts; crossfades do not register at all; TikTok's own flash/zoom transitions produce spurious boundaries. Cap the number of adaptive frames so a strobing video cannot blow your budget.

### 1.7 Frame manifest (spec §50)
Per frame: `frame_id`, `requested_timestamp`, `actual_timestamp`, `pts`, `source_index`, `path`, `width`, `height`, `reason`, `is_approximate_ts`, `orientation_transform`. Plus a manifest header with the `MediaMeta`, sampler config hash, and total counts by reason.

## Challenges and approaches

| Challenge | Approach |
|---|---|
| VFR video → wrong timestamps | PyAV PTS as ground truth; never index arithmetic; flag `is_vfr` |
| Rotation double-applied or not applied | Empirically verify PyAV behavior on a known-rotated file in Phase 0; assert on frame dimensions matching expected orientation |
| Duration disagreement between container and stream | Store both, flag divergence > 0.2 s, use format duration |
| Blank/black frames at video start | Detect near-zero variance frames; if the first frame is blank, shift that sample by one frame interval — this matters specifically because the hook window is the most important region |
| Decode failure mid-file | Catch per-frame, keep what decoded, mark the run degraded; do not lose the whole video for one bad packet |
| Drive I/O on thousands of small JPEGs | Write to `/content/work`, tar the frame directory, sync one file to Drive |
| Budget blown by a strobing/high-cut video | Hard cap adaptive frames; thin global tier first |

## Resource budget
CPU only. 30 s video: probe < 0.5 s, full decode + 40 frame extraction 2–5 s, audio ~1 s, scene detection ~1–2 s. **No GPU.** Batch 100 videos in a few minutes.

## Exit criteria
- [ ] 20 varied videos processed with zero corrupt outputs
- [ ] Hook and CTA windows present in every manifest (assert this in code, not by eye)
- [ ] Frame timestamps validated: for 3 videos, hand-verify by scrubbing a player to the manifest timestamp and confirming the saved frame matches
- [ ] VFR video handled correctly and flagged
- [ ] Rotated video produces upright frames with the transform recorded
- [ ] Silent video produces `has_audio=False` without an exception
- [ ] Sampler unit tests all green
- [ ] Corrupt file rejected at preflight with a specific reason code

---

# PHASE 2 — ASR and OCR: the text evidence layer

**Effort:** 1.5 weeks.

## Objective
Timestamped transcript (segment + word level) and timestamped, deduplicated on-screen text, both anchored to the same timeline as the frames.

## Why here
This is the highest-accuracy-per-FLOP evidence in the entire system. Whisper's word timestamps and OCR text are both far more reliable than anything the VLM will tell you, and together they can already adjudicate several requirement types. Build them before the VLM so the VLM has context to work with — and so Milestone A can prove the join.

## Build
`asr/whisper.py`, `ocr/engine.py`, `evidence/dedupe.py`

## Technical detail — ASR

### 2.1 Model choice
`faster-whisper` (CTranslate2 runtime). Options, in descending order of my recommendation for this project:

| Model | Params | VRAM (fp16) | Speed | Notes |
|---|---|---|---|---|
| **`large-v3-turbo`** | ~809M | ~1.5–2 GB | very fast | Pruned decoder; near-large-v3 quality on clear English speech. **Default choice.** |
| `distil-large-v3` | ~756M | ~1.5 GB | very fast | English-only, strong; good alternative |
| `large-v3` | 1.55B | ~3 GB | baseline | Use if the benchmark shows turbo losing accuracy on your content |
| `medium` / `small` | 769M / 244M | ~1.5 GB / 0.6 GB | fast | Fallback if VRAM is contested |

TikTok audio is a hard case: music beds, compressed audio, fast speech, slang, brand names. Validate on your own clips, not on published WER numbers. **Specifically check brand-name and ingredient-term recognition** — those are exactly the words your requirements will hinge on, and generic ASR benchmarks tell you nothing about them.

`compute_type="float16"` on GPU, `"int8"` on CPU fallback. On a T4 this loads in ~10 s and transcribes 30 s of audio in 2–5 s.

### 2.2 Parameters that matter, and why

- `word_timestamps=True` — essential. Requirements like "mention hydration within 10 seconds" need word-level precision (spec §22). Whisper derives these via cross-attention + DTW alignment; they are typically accurate to ~±100 ms, which is fine here. Do not treat them as frame-exact.
- `vad_filter=True` with Silero VAD — **the single most valuable setting.** Music-only and silent stretches are where Whisper hallucinates fluent text out of nothing ("Thanks for watching!", subtitle-site credits). VAD removes those regions before decoding. Tune `min_silence_duration_ms` (~500) and `speech_pad_ms` (~200–400); too aggressive padding removal clips word onsets and corrupts your timestamps.
- `condition_on_previous_text=False` — prevents repetition loops. Costs a little coherence on long-form content; TikToks are short and this trade is clearly correct.
- `language="en"` when known — skips detection, saves time, avoids misdetection on music intros.
- `beam_size=5` — default; drop to 1 for a speed pass during development.
- `temperature=0` with fallback temperatures disabled where possible — you want reproducibility (spec §45).
- Post-filter on `no_speech_prob` (drop segments above ~0.6) and `avg_logprob` (drop below ~-1.0), and reject segments whose `compression_ratio` exceeds ~2.4 (a classic degenerate-repetition signature).

### 2.3 Transcript artifact
Store: full text, segments (`start`, `end`, `text`, `avg_logprob`, `no_speech_prob`, `compression_ratio`), words (`word`, `start`, `end`, `probability`), detected language + probability, plus a **normalized text index** — lowercased, punctuation-stripped, numbers/percentages normalized (`twenty percent` → `20%`, `20 % off` → `20% off`) with a character-offset → word-index map so a match in normalized space maps back to a timestamp. Without that map, exact-phrase requirements degrade into fuzzy guessing.

### 2.4 ASR challenges

| Challenge | Approach |
|---|---|
| Hallucinated text over music | VAD + `no_speech_prob` + compression-ratio filtering; if a segment survives all three and still looks wrong, log it as a regression case |
| Brand names transcribed phonetically | Maintain a per-brand vocabulary; fuzzy-match with `rapidfuzz` at ~85 similarity against known brand/product terms; optionally pass the brand name in Whisper's `initial_prompt` to bias decoding (measure — it can also cause the model to insert the term spuriously) |
| Multiple speakers | Out of scope for MVP. Note as a limitation. Diarization (WhisperX + pyannote) is a Phase 9+ decision, and pyannote requires HF gated-model acceptance. |
| Loud music suppressing speech | Optional source separation (Demucs) is expensive and rarely worth it. Log low-confidence transcripts and let the evaluator return `UNCERTAIN` rather than guessing. |
| Word timestamps off during fast speech | Accept ~±150 ms. Never build a rule with a tolerance tighter than that. |

## Technical detail — OCR

### 2.5 Which frames to OCR (spec §23)
Not all of them. Priority order:
1. All hook-window frames (dense — text appears and vanishes fast here)
2. All CTA-window frames (discount codes, "link in bio")
3. All scene-change frames
4. Global uniform frames — for a short video, just do all of them
5. Skip near-duplicates: hash-compare consecutive frames (perceptual hash or downscaled MAE); if a frame is nearly identical to the previous one, copy its OCR result forward instead of re-running.

That last item typically eliminates 40–60% of OCR calls at zero accuracy cost, because TikTok captions persist across many frames.

### 2.6 Region masking — the detail most people miss
Raw TikTok video (as opposed to a clean export) has platform chrome burned in or overlaid: `@username`, the caption block, the "Follow" button, the sound ticker, sidebar icons. OCR will happily read all of it, and your evaluator will then "find" the brand name in the username and pass a requirement it should have failed.

**Approach:** define normalized-coordinate exclusion masks (fractions of width/height, so they survive resolution changes) for the bottom band (~last 15–20% of height) and the right rail (~last 15% of width). Make them configurable and **off by default for clean uploads**, on for scraped content. Log how many OCR lines each mask removed, so you can tell when it is over-aggressive.

### 2.7 Deduplication and temporal merging
Raw OCR across 40 frames gives you the same caption 12 times. Convert detections into **intervals**:

1. Group by normalized text (lowercase, whitespace-collapsed, `rapidfuzz` similarity ≥ ~90 to absorb OCR jitter like `SH0P` vs `SHOP`).
2. Within a group, require spatial consistency (bounding-box IoU ≥ ~0.5) so two different on-screen elements with the same word do not merge.
3. Merge consecutive frame occurrences into `[start, end]` intervals, allowing a gap of up to ~2 sample intervals (text can flicker or be briefly occluded).
4. Emit one evidence record per interval with `first_seen`, `last_seen`, max confidence, and the representative bbox.

This turns hundreds of noisy detections into 5–15 clean, timestamped text events. Do this in `evidence/dedupe.py`; it is shared logic, not OCR-specific.

### 2.8 The burned-in-caption problem — call this out explicitly
Most TikToks display auto-captions that duplicate the speech. Your OCR evidence and transcript evidence will then say the same thing, and a naive evaluator will count it as two independent confirmations — inflating confidence and corrupting any `speech_or_text` vs `speech_only` distinction (spec §37).

**Approach:** after both stages complete, cross-check each OCR interval against the transcript within a ±1.5 s window using normalized-text similarity. If they match strongly, tag the OCR evidence `derived_from_speech=True`. The evaluator then knows that a `speech_only` requirement is not satisfied by that OCR line, and that the two are not independent evidence. This is a genuine correctness issue, not a nicety.

### 2.9 Other OCR challenges

| Challenge | Approach |
|---|---|
| Stylized fonts, outlined/shadowed text, emoji | Accept lower recall; PP-OCR handles common TikTok fonts well. Log low-confidence detections rather than dropping them. |
| Tiny text (ingredient lists, disclaimers) | Run OCR at native resolution — never on VLM-downscaled frames. Optionally upscale small detected regions and re-run recognition. |
| Text over busy video | Confidence threshold ~0.5; below that, keep the record but mark it low-confidence so the evaluator can return `UNCERTAIN` |
| Language/script mix | Configure the recognition language set; start English-only, widen only if your corpus needs it |
| Cost | Near-duplicate skipping + region masking + OCR-only-the-priority-frames |

## Resource budget
- ASR: ~2–5 s per 30 s video on GPU with turbo; ~15–25 s on CPU with `small`
- OCR: ~0.1–0.4 s per frame on GPU, ~0.3–1.5 s per frame on CPU. With dedupe skipping, ~20 real OCR calls per video → 5–30 s
- Peak VRAM if run separately: < 3 GB. **Free the ASR model before loading OCR.**

## Exit criteria
- [ ] 20 videos transcribed; manual spot-check confirms the transcript is usable for requirement matching (spec §71)
- [ ] Zero hallucinated transcripts on the music-only sample video
- [ ] Word timestamps verified against the video on 3 clips (scrub and listen)
- [ ] OCR captures every CTA and discount code you can see by eye across the sample set
- [ ] Dedupe reduces raw detections to clean intervals; hand-verify on one caption-heavy video
- [ ] `derived_from_speech` correctly flags burned-in captions
- [ ] Both stages cache correctly: a second run is instant

---

# ★ MILESTONE A — End-to-end audit with no VLM (3 days)

**Do this before Phase 3.** It is not in `product.md`, and it is the highest-leverage 3 days in the plan.

## Objective
A complete `video + brief → scored report` path using only transcript, OCR and metadata. Requirements are hand-written JSON (no LLM brief parser yet). Matching is exact/fuzzy string + timestamp arithmetic only.

## Why
It de-risks the *integration*, which is where projects actually break, while the expensive component is still absent. You will discover the real shape of the evidence schema, the timeline model, the scoring edge cases, and the report format in an environment where every run is free and instant. When Qwen3-VL arrives in Phase 3 it plugs into a proven socket instead of a hypothesis.

You can genuinely adjudicate these requirement types with zero vision:
- `speech` — "mention hydration" → word-level transcript search
- `ocr` — "show 20% OFF" → OCR interval search
- `speech_or_text` — union of both
- `timing` — "CTA in final 5 seconds" → interval arithmetic
- `policy` (lexical subset) — forbidden-phrase gazetteer over transcript + OCR

That is roughly half of a typical brief.

## Build
Minimal `evidence/normalizer.py`, `evidence/timeline.py`, `evaluation/matcher.py`, `evaluation/rules.py`, `evaluation/scoring.py`, `reports/html_report.py`

## Exit criteria
- [ ] One video + one hand-written requirement set → an HTML report with per-requirement verdicts, timestamps and a clickable evidence timeline
- [ ] The score arithmetic is verifiable by hand
- [ ] `UNCERTAIN` appears where evidence is genuinely absent, rather than a forced FAIL
- [ ] Second audit of the same video against a different brief takes < 3 seconds (proves cache separation, spec §55)

---

# PHASE 3 — Qwen3-VL evidence extraction (Pass 1)

**Effort:** 2 weeks. The most technically demanding phase.

## Objective
Given a controlled frame sequence, produce structured, timestamped, **factual** visual evidence — scenes, actions, product visibility, demonstration verbs, hook characteristics, visual CTA. Explicitly **no compliance judgment** (spec §26, §72).

## Why here
The evidence contract, the cache, and the report are all proven. Now you add the expensive, unreliable, high-value component into a socket that already works.

## Build
`vision/qwen.py`, `vision/prompts/`, `vision/schemas.py`

## Technical detail

### 3.1 Model loading and the VRAM arithmetic

| Config | Weights | Practical VRAM w/ ~32 frames | T4 16 GB | L4 24 GB | A100 40 GB |
|---|---|---|---|---|---|
| 4B fp16 | ~8.0 GB | ~10–12 GB | ✅ | ✅ | ✅ |
| 4B NF4 (4-bit) | ~2.8 GB | ~5–6 GB | ✅ comfortable | ✅ | ✅ |
| 8B fp16/bf16 | ~16.0 GB | ~19–22 GB | ❌ | ✅ tight | ✅ |
| 8B NF4 (4-bit) | ~5.5 GB | ~8–10 GB | ✅ | ✅ | ✅ |
| 8B AWQ int4 | ~5.5 GB | ~8–10 GB | ✅ faster than NF4 | ✅ | ✅ |

Loading parameters:
- `torch_dtype`: `float16` on T4 (**bf16 is unsupported on sm_75 — it will not error usefully, it will be slow or wrong**); `bfloat16` on L4/A100
- `attn_implementation="sdpa"` everywhere; `"flash_attention_2"` only on sm_80+ and only if a prebuilt wheel is available
- `device_map="cuda:0"` — avoid `"auto"` on a single GPU; CPU offload is catastrophically slow and will make you think the model is broken
- `revision="<commit sha>"` — **pin it.** Spec §45 requires this and it is what makes your ablations comparable across weeks.
- `low_cpu_mem_usage=True` — Colab's host RAM is finite too

4-bit via `BitsAndBytesConfig`: `load_in_4bit=True`, `bnb_4bit_quant_type="nf4"`, `bnb_4bit_compute_dtype=float16`, `bnb_4bit_use_double_quant=True`. Note NF4 on Turing is memory-efficient but not especially fast — expect a throughput hit vs fp16, traded for the model fitting at all.

**VRAM lifecycle discipline:** wrap loading in a context manager that deletes the model and processor, runs `gc.collect()`, and calls `torch.cuda.empty_cache()` on exit. Without this you will OOM on the third video in a batch loop and lose an hour to a phantom bug.

### 3.2 Input strategy — Architecture B is canonical (spec §25)

Feed a **pre-decoded frame list** with explicit timestamps, not the raw MP4. Reasons, per the spec: complete control over sampling, guaranteed hook/CTA density, reproducibility, and archived evidence frames. Auditability beats convenience for an audit product.

Keep Architecture A (hand Qwen the video file, let `qwen-vl-utils` sample at `sample_fps`) as a **benchmark comparison path** in Phase 9. It might win; measure it.

### 3.3 The timestamp injection problem — the crux of this phase

Give a VLM 32 images and ask "when does the product appear," and it will invent a number. It has no idea what second any frame represents unless you tell it.

Three mechanisms, use **all three**:

1. **Interleave timestamp text with frames in the message content.** Structure the multimodal message as `[text "0.00s"] [image] [text "0.25s"] [image] ...`. Verbose but unambiguous, and it is how Qwen's own temporal-grounding evaluation code establishes frame timing.
2. **Ask for frame indices, not seconds.** Instruct the model to answer with `frame_start` / `frame_end` indices into the sequence you provided. Then *you* map indices → timestamps from the manifest, deterministically. This eliminates arithmetic hallucination entirely. **This is the most robust option — prefer it.**
3. **Provide the frame index → timestamp table in the system prompt** as a compact reference the model can consult.

Then **validate**: any timestamp the model emits that falls outside `[0, duration]`, or that is inconsistent with the frame it cited, gets clamped and flagged `timestamp_unreliable`. Never pass unvalidated model timestamps into the evaluator. Test this deliberately — feed a video and check whether reported product-appearance times actually match the frames.

### 3.4 Vision token budgeting
Qwen-VL family models use dynamic resolution: an image becomes patches, patches are merged spatially (2×2), and in video mode consecutive frames are merged temporally. Rough working estimate: **~28×28 original pixels per vision token**, halved again by temporal merging in video mode.

Example: 32 frames at 448×448 → (448/28)² = 256 tokens/frame → ÷2 temporal merge ≈ 128 tokens/frame ≈ **4,100 vision tokens**. Comfortable. The same 32 frames at 1080×1920 would be ~1,300 tokens/frame ≈ 42,000 tokens — that will OOM a T4 and add nothing, because the model's useful spatial resolution is far below native.

**Control it explicitly** via the processor's `min_pixels` / `max_pixels` (or `total_pixels`) arguments. Do not leave it to defaults and hope.

**Verify the estimate rather than trusting it:** run the processor on a real batch and print the actual number of vision tokens in the input ids. Do this once in Phase 3 and record the real numbers in your config comments.

Budget guidance: keep total vision tokens under ~8k on a T4, under ~16k on L4/A100. If you need more temporal coverage, add frames at lower resolution rather than fewer frames at high resolution — for event detection, temporal coverage beats spatial detail. Fine spatial detail is OCR's job, and OCR already ran on native-resolution frames.

### 3.5 Prompt design (spec §62)
Separate, versioned, narrow prompts in `prompts/` as files. Never inline strings — you must be able to diff prompt v3 against v4 when accuracy moves.

**P1 — visual evidence extraction (the Phase 3 deliverable):**
- Role: neutral observer. Explicit instruction: *describe only what is visibly present; do not evaluate compliance; do not infer intent.*
- Provide context: transcript (compact, with timestamps) and OCR intervals. **Test this both ways in Phase 9.** My expectation is it helps substantially — the model grounds visual observations against known speech — but it also risks the model parroting the transcript instead of looking at the images. This is a real ablation, not a rhetorical one.
- Request a fixed JSON schema: list of events with `frame_start`, `frame_end`, `type` (closed enum), `description`, `confidence`, `objects`.
- Closed event-type enum: `scene`, `product_visible`, `product_held`, `product_opened`, `product_applied`, `product_used`, `demonstration`, `person_speaking_to_camera`, `text_overlay`, `before_after`, `cta_visual`, `transition`. Closed enums are the difference between mergeable evidence and free-text soup.
- **Demonstration verbs matter** (spec §35): `shown` / `held` / `opened` / `mixed` / `applied` / `used` / `compared` / `explained`. "Product visible" ≠ "product demonstrated," and a brief distinguishes them.
- Few-shot: one worked example with the exact output shape. Keep it short — examples consume context that frames need.

Generation params: `do_sample=False` (greedy), `temperature=0`, `max_new_tokens` ~1024–2048, and `repetition_penalty` left at 1.0 (penalties corrupt JSON structure).

### 3.6 Structured output enforcement
Three tiers, in increasing cost:
1. **Prompt + `json_repair` + one retry** — handles ~95% of cases at zero overhead. **Start here.**
2. **Pydantic validation with an error-feedback retry** — return the validation error to the model and ask for a correction. One retry maximum; then emit an empty evidence set with `status=parse_failed` rather than looping.
3. **Constrained decoding** (`outlines` / `xgrammar`, or vLLM's guided JSON) — a hard guarantee, at the cost of another dependency and some speed. Adopt only if tier 1+2 failure rate exceeds ~5% on the benchmark.

Always log raw model output alongside the parsed result. When accuracy is strange, the raw text tells you whether it was a model problem or a parser problem.

### 3.7 The 4B vs 8B bake-off (spec §46)
Run on a fixed set of 10 videos, identical frames, identical prompt, greedy decoding. Compare:
- Event detection recall against hand-labeled events
- Product first-appearance timestamp MAE
- Demonstration verb accuracy
- Hook type agreement with your own judgment
- JSON parse success rate
- Latency and peak VRAM

Configurations: 4B fp16, 4B NF4, 8B NF4, and 8B bf16 if you have an L4/A100 session. **Decide on evidence, not size** (spec §46). A plausible outcome is that 4B handles the structured extraction fine and 8B only wins on subtle semantic judgments — in which case use 4B for Pass 1 and 8B (or an API) for Pass 2 adjudication. That split would be a genuinely good result.

Also note: the **Thinking** variants exist and trade latency for reasoning quality. For structured extraction they are usually not worth it; for Pass 2 adjudication they might be. Test only if Pass 2 accuracy is the bottleneck.

## Challenges and approaches

| Challenge | Approach |
|---|---|
| Timestamp hallucination | Frame-index output + deterministic mapping + range validation + `timestamp_unreliable` flag |
| Product misidentification (similar-looking bottles) | Pass the product name and a reference description in the prompt; ask the model to state what it sees before asserting identity; escalate to `UNCERTAIN`. If systematic, that is the trigger for Grounding DINO in Phase 11 (spec §34) — **not before**. |
| Non-JSON output | json_repair → schema-feedback retry → log and degrade |
| OOM on 8B | NF4/AWQ, reduce `max_pixels`, reduce frames, strict VRAM lifecycle |
| Temporal reasoning is weak on fast cuts | This is a known VLM limitation. Lean on OCR/transcript for those windows; return `UNCERTAIN` rather than fabricating. |
| Frame-order confusion in long sequences | Explicit "Frame 12 (3.00s):" labels; cap the sequence length |
| Non-reproducible outputs | Greedy decode, fixed seed, pinned revision. Accept that different GPU models can still differ slightly at the bit level — store outputs, do not expect cross-hardware bit-identity. |
| Slow iteration | Cache aggressively; keep a 5-video dev subset; never sweep the full set while iterating on a prompt |

## Resource budget
- 4B fp16 on T4, 32 frames: load ~40–90 s (once per session), inference ~15–30 s/video
- 8B NF4 on T4: load ~60–120 s, inference ~25–50 s/video
- On L4/A100 roughly 2–3× faster
- **Load the model once per session and loop over videos.** Model loading dominates otherwise.

## Exit criteria
- [ ] For 10 videos, a human can map each emitted evidence item back to what is actually on screen (spec §72)
- [ ] Timestamps validated: reported product-appearance times match the video within ~±0.5 s on 5 videos
- [ ] JSON parse success ≥ 95%
- [ ] 4B vs 8B comparison table complete, with a written decision and reasoning
- [ ] Pass-1 output contains **no compliance judgments** (grep the outputs for "should", "compliant", "requirement" — if present, the prompt is leaking task boundaries)
- [ ] VRAM lifecycle verified: 10 videos in a loop with no OOM and stable peak memory

---

# PHASE 4 — Brief compiler

**Effort:** 1 week.

## Objective
Natural-language brief → validated, deterministic `requirements.json` a human agrees with (spec §28, §73).

## Technical detail

### 4.1 Model choice for this task
This is a text-only task, executed **once per brief** and cached forever by brief hash. Options:

1. **Hosted API (Claude / GPT).** Best quality on structured extraction, zero GPU, effectively free at this volume (a handful of calls per brief, fractions of a cent). **Recommended default** unless the project has a hard requirement to stay fully local.
2. **Reuse the already-loaded Qwen3-VL in text-only mode.** No second model, no extra VRAM. Recommended if staying local.
3. A separate local text LLM (`Qwen3-4B-Instruct` or similar). Only if you have a reason — otherwise it is a second model load for no gain.

Because it is cached by brief hash, this stage's cost is irrelevant to per-video economics. Optimize for quality, not speed.

### 4.2 The schema (spec §28) — extend it
Beyond the spec's `Requirement` model, add fields you will otherwise need to bolt on later:

- `evidence_mode`: `speech_only` | `visual_only` | `ocr_only` | `speech_or_text` | `visual_and_speech` — **critical.** Spec §37 shows exactly why: "show 20% off" and "say 20% off" have identical text and different evidence requirements. Get this out of the LLM at parse time, not out of the evaluator at match time.
- `polarity`: `required` | `forbidden` — negative constraints are structurally different and need `FAIL`-if-found logic (spec §38)
- `weight`: derived from `priority` (critical 3.0, high 2.0, medium 1.0, low 0.5)
- `match_hints`: exact phrases, synonyms, semantic paraphrases — pre-computed by the LLM at parse time so the evaluator can do cheap lexical matching before escalating. Genuinely valuable optimization: "mention hydration" → `["hydrat*", "moistur*", "dewy", "quench", "dry skin", "skin barrier"]`.
- `acceptance_criteria`: natural-language conditions, passed verbatim to the LLM adjudicator when escalation is needed

### 4.3 Parsing approach
1. **Segment** the brief into atomic requirements. Briefs use bullets, run-on sentences, and compound asks ("show the product and say the name") that must be split. Ask for a split-and-enumerate step explicitly.
2. **Classify** each into `RequirementType` and `evidence_mode` (closed enums).
3. **Extract temporal constraints** — "within the first 5 seconds" → `deadline_seconds: 5.0`; "end with" → `window_start: duration - 5`. Note that some windows are relative to duration and cannot be resolved until a video is known: **store them symbolically** (`window_start_expr: "duration - 5"`) and resolve at audit time. Hardcoding an absolute number at parse time silently breaks when the same brief meets a video of a different length.
4. **Generate match hints.**
5. **Validate** with Pydantic; on failure, feed the error back once.
6. **Deduplicate** near-identical requirements.

### 4.4 Human-in-the-loop confirmation (spec §73's exit criterion)
Render compiled requirements as a readable table and require explicit approval before an audit runs. If the compiler misreads the brief, every downstream verdict is wrong and no amount of VLM accuracy saves you. This check costs 60 seconds per brief and prevents entire categories of confusing failure.

## Challenges

| Challenge | Approach |
|---|---|
| Vague briefs ("make it feel premium") | Emit with `priority: low` and `machine_checkable: false`; report separately as "not automatically assessed." Do not pretend to evaluate it. |
| Compound requirements | Explicit split step; the human review catches misses |
| Implicit requirements ("obviously show the brand") | Optional inference with `source: inferred` so a human can reject it |
| Over-decomposition (12 requirements from a 3-line brief) | Instruct a target count band; deduplicate; the human review catches it |
| Duration-relative windows | Symbolic expressions resolved at audit time |
| Brief in another language | Detect and note; MVP scope is English |

## Resource budget
Negligible. One call per unique brief, cached forever.

## Exit criteria
- [ ] 5 real briefs compiled; you read each requirement set and confirm it accurately represents the brief (spec §73)
- [ ] `evidence_mode` correct on the "say X" vs "show X" distinction — test this specifically
- [ ] Temporal constraints extracted correctly, including duration-relative ones
- [ ] Schema validation catches malformed output
- [ ] Cached by brief hash; recompilation is instant

---

# PHASE 5 — Evidence normalizer and the unified timeline

**Effort:** 4 days.

## Objective
One `evidence.json` per video: every observation from every modality, on one timeline, in one schema, deduplicated and cross-linked (spec §30, §51).

## Why here
This is the data contract between models and evaluation, and the artifact that makes one video reusable across many briefs (spec §55). It is small, unglamorous, and load-bearing.

## Technical detail

### 5.1 Unified evidence record
Per spec §63, plus fields experience says you will need:
```
id, modality (visual|speech|ocr|metadata), type (closed enum),
start_seconds, end_seconds, description, confidence, source (model id),
source_run_id, frame_ids[], bbox?, raw_text?,
is_approximate_ts, derived_from_speech, timestamp_unreliable
```

### 5.2 Cross-modal linking and dedupe
- **Speech ↔ OCR:** the burned-in-caption check from §2.8, applied here as the canonical location.
- **Visual ↔ OCR:** a VLM `text_overlay` event and an OCR interval at the same time are the same phenomenon. Prefer the OCR record for text content (higher accuracy) and the VLM record for context. Link them; do not emit both as independent.
- **Visual ↔ visual:** merge overlapping `product_visible` events from the VLM into intervals rather than leaving fragments.

### 5.3 Derived aggregates
Compute once and store, because the evaluator asks for these constantly:
- `product_first_seen`, `product_last_seen`, total visible duration, longest continuous interval
- Demonstration intervals by verb
- `text_in_window(t0, t1)`, `speech_in_window(t0, t1)` accessors
- Cut density per second (a hook-strength feature and a fast-cut indicator)
- Silence/speech ratio
- Evidence coverage per second — regions with no evidence at all, which is a useful `UNCERTAIN` signal

### 5.4 Confidence normalization
The three sources produce non-comparable numbers: OCR confidence is a calibrated recognition score, Whisper's `probability` is a token likelihood, and a VLM's self-reported confidence is close to meaningless. **Do not average them.** Keep them per-modality, and define comparison rules per modality with thresholds you calibrate against the Phase 8 benchmark. Treat VLM self-confidence as a weak ordinal signal at best.

## Exit criteria
- [ ] One evidence file per video, schema-validated
- [ ] All timestamps within `[0, duration]`
- [ ] Burned-in captions correctly flagged
- [ ] Derived aggregates match manual inspection on 3 videos
- [ ] Auditing one video against 3 different briefs re-runs **only** stages 9–12

---

# PHASE 6 — Requirement evaluator, hook module, claims module

**Effort:** 2 weeks. This is where product value is actually created.

## Objective
For every requirement: a status, cited evidence IDs, and a reason (spec §31, §74).

## Technical detail

### 6.1 The three-layer escalation ladder
Cost-ordered. **Instrument the escalation rate at each layer** — it is a direct measure of how much GPU you are spending on semantics.

**L1 — deterministic (free, ~50–60% of requirements):**
- Exact and fuzzy phrase matching (`rapidfuzz`, threshold ~85) over normalized transcript and OCR text, using `match_hints`
- Timestamp arithmetic: `product_first_seen <= deadline`, `cta_interval.start >= duration - 5` (spec §32)
- Forbidden-phrase gazetteer
- Presence/absence of a closed-enum evidence type

L1 answers with `PASS`, `FAIL`, or **`INCONCLUSIVE` — which is an internal routing signal, not a user-facing status.** Keep these separate; conflating "the cheap check didn't fire" with "we genuinely don't know" is a classic bug that manifests as unexplainable FAILs.

**L2 — embedding similarity (cheap, ~25% of requirements):**
- `bge-small-en-v1.5` over transcript sentences and OCR intervals vs. requirement text + hints
- Cosine similarity, top-k retrieval, threshold **calibrated on the benchmark** — do not pick 0.7 because it looks round. Note the model's asymmetric query/passage prefix convention and apply it consistently.
- Above the high threshold → PASS with a cited sentence. Below the low threshold → FAIL. Between → escalate to L3. Two thresholds, not one.

**L3 — LLM adjudication (expensive, ~15–25%):**
- **Text-only.** No frames. Input: the requirement, its acceptance criteria, and the top-k retrieved evidence candidates from L1/L2 — *not* the whole evidence set. Retrieval-then-adjudicate keeps the prompt small and the decision focused (spec §32).
- Answers the genuinely semantic questions: does "my skin feels less tight" satisfy "mention improved hydration"? Is this opening a hook or an introduction?
- Output: `status`, `evidence_ids[]`, `reason`, `confidence`
- **Hard constraint: the model may only cite evidence IDs that were provided.** Validate this in code and reject responses that invent IDs. This is your anti-hallucination guarantee, and it is enforceable deterministically.
- Model: the resident Qwen3-VL in text-only mode, or a hosted API. Batch all escalated requirements for one video into a single call where the prompt fits — it is much cheaper than one call per requirement.

### 6.2 Status semantics — write these down and enforce them
- `PASS` — evidence satisfies the requirement, cited
- `PARTIAL` — satisfied weakly, late, or only in one of two required modalities
- `FAIL` — evidence exists and contradicts, **or** required evidence is confidently absent
- `UNCERTAIN` — insufficient or degraded evidence (no audio, OCR failed, VLM parse failed, low-confidence transcript). **Not** a synonym for "hard case."
- `NOT_APPLICABLE` — requirement does not apply to this video

The `FAIL` vs `UNCERTAIN` boundary is the one that determines whether users trust the system. A FAIL asserts something; you need positive grounds for it. Rule of thumb: FAIL requires that the relevant modality ran successfully and the evidence is simply not there. If the modality was degraded, it is UNCERTAIN.

### 6.3 Hook module (spec §33)
A dedicated component, because it is the product differentiator.

Inputs: transcript for `[0, 3–5 s]`, dense hook-window frames, OCR in that window, cut density, VLM Pass-1 events in that window.

Cheap features to compute first: does speech start before 1.0 s? Does the first sentence contain a question, a number, a negation, a second-person pronoun? Is there a text overlay in the first second? How many cuts in the first 3 seconds? Is there a face at camera?

Then a **dedicated prompt (P2)** producing the spec §33 output: `hook_present`, `hook_type` (closed taxonomy of 11 values), `start`, `end`, `strength`, `transcript`, `visual`, `within_required_window`, `reason`.

**Keep presence separate from strength** (spec §33). And make strength **ordinal with written anchors** — define in the prompt what makes a hook weak vs medium vs strong, with an example of each. A bare "rate the strength" produces noise; anchored ordinal ratings are reproducible enough to benchmark. Never emit a numeric hook score from the model.

Hook detection is inherently subjective. Expect this to be your lowest inter-rater-agreement metric, and **measure your own self-agreement** by labeling 10 videos twice, a week apart. If you agree with yourself only 70% of the time, that is the ceiling on what the model can be measured against, and you should say so in the report rather than chasing a number you cannot define.

### 6.4 Claims / policy module (spec §38)
Two-stage, for recall then precision:
1. **Candidate extraction (high recall, free):** gazetteer + regex over transcript and OCR — `cure`, `heal`, `treat`, `eliminate`, `prevent`, `clinically proven`, `dermatologist approved`, `FDA`, `guaranteed`, `permanent`, `100%`, `overnight`, plus per-brand forbidden terms from the brief.
2. **Classification (precision, LLM):** each candidate sentence classified into `medical_claim` | `cure_claim` | `guarantee_claim` | `unsupported_outcome` | `prohibited_wording` | `not_a_claim`, with a risk level and the surrounding context.

Do not try to prove a global negative (spec §38). Detect defined classes and report them as an assistive review signal. **Every claim output must carry an explicit "not legal advice / requires human review" disclaimer in the report.** Design for high recall and accept false positives here — a missed medical claim is a far more expensive error than an extra flag a human dismisses in two seconds.

### 6.5 Evidence-mode enforcement (spec §37)
The evaluator must respect `evidence_mode` strictly:
- `speech_only` → transcript evidence only; OCR flagged `derived_from_speech` does **not** count
- `ocr_only` → OCR intervals only
- `speech_or_text` → union
- `visual_and_speech` → both required; only one present → `PARTIAL`

## Challenges

| Challenge | Approach |
|---|---|
| Semantic equivalence ("less tight" ≈ "hydrated") | L2/L3 escalation; log every L3 decision as a benchmark candidate |
| LLM inventing evidence | Only provided IDs are citable; validate in code and reject violations |
| Threshold calibration | Do it on the benchmark in Phase 8. Until then, thresholds are placeholders — label them as such in config. |
| Requirement–evidence retrieval missing the right candidate | Retrieve generously (top 8–10); recall at retrieval matters more than precision, since the LLM filters |
| PARTIAL overused, making scores mushy | Define PARTIAL narrowly with written rules; audit its frequency on the benchmark |
| Everything returning UNCERTAIN | Track the UNCERTAIN rate as a first-class metric. Above ~20%, the evidence layer is the problem, not the evaluator. |

## Exit criteria
- [ ] Every requirement in the benchmark set produces a status, evidence IDs and a reason
- [ ] Zero fabricated evidence IDs across the full benchmark (assert in code)
- [ ] L1/L2/L3 escalation rates logged; L3 handles < 30% of requirements
- [ ] Hook module produces the full spec §33 output
- [ ] Claims module flags all planted test claims (build 5 videos/scripts with deliberate claims)
- [ ] `speech_only` vs `ocr_only` distinction verified on a burned-in-caption video

---

# PHASE 7 — Deterministic scoring and reporting

**Effort:** 1 week.

## Objective
A score computed by arithmetic (never by a model) and a report a creator manager can act on faster than watching the video (spec §39, §40, §75).

## Technical detail

### 7.1 Scoring (spec §39)
Status values: `PASS` 1.0, `PARTIAL` 0.5, `FAIL` 0.0. Weights from requirement priority. `NOT_APPLICABLE` excluded from both numerator and denominator.

**`UNCERTAIN` is the interesting case, and the spec leaves it open. Resolve it like this:** report a **score band** plus a coverage figure.
- `score_pessimistic` — UNCERTAIN counted as 0.0
- `score_optimistic` — UNCERTAIN excluded from the denominator
- `coverage` — fraction of total weight that is not UNCERTAIN

A video reported as **"78–91, 82% coverage"** is honest and actionable. A single number that silently buries three UNCERTAINs is not. Show the single (optimistic) number as the headline only when coverage exceeds ~90%; otherwise lead with the band. This directly implements Principle 4 (spec §3) instead of quietly working around it.

Also emit per-dimension subscores using the spec §39 dimension weights (hook 20%, product presence 15%, demonstration 15%, messaging 20%, audience 10%, CTA 10%, brand/format 10%), normalized over the dimensions the brief actually covers.

Status bands: `APPROVED` / `NEEDS_MINOR_REVISION` / `NEEDS_MAJOR_REVISION` / `REJECTED`, with any critical-priority FAIL forcing at minimum `NEEDS_MAJOR_REVISION` regardless of the numeric score. A brief's critical requirement is not something a good average should be able to paper over.

### 7.2 Recommendations (P7)
Generated from failed and partial requirements, and **grounded in what already worked** — "add one sentence on barrier support after the application shot at 0:11, without changing the opening" is useful; "improve messaging" is not. Feed the LLM the failure list plus the passing evidence, and constrain it to concrete, minimal, timestamp-anchored edits.

### 7.3 Report artifacts
**JSON** (spec §84): the machine contract. Full provenance — model IDs, revisions, prompt versions, stage durations, cache hits, config hash.

**Self-contained HTML** — the human deliverable, and the reason you can skip a web stack for months:
- An embedded low-bitrate proxy video (re-encode to ~480p, CRF ~30, so a 30 s clip is 1–2 MB) as a base64 data URI, or a relative file reference
- Score band + coverage, dimension bars, requirement list with status icons and timestamps
- **Clickable timestamps that seek the player** (`video.currentTime = t`) — spec §40's key interaction, achievable in ~20 lines of vanilla JS
- Evidence timeline strip: a horizontal bar per modality showing where evidence exists
- Hook card, claims section with the human-review disclaimer, recommendations
- Collapsible raw-evidence appendix for debugging

One file, opens anywhere, emailable, no server. This covers spec §76's UI requirements at a fraction of the cost. Jinja2 templating.

## Exit criteria
- [ ] Score reproducible by hand from the requirement results
- [ ] No model output ever writes a numeric score (grep for it)
- [ ] HTML report opens standalone; timestamp clicks seek correctly
- [ ] A person who has not seen the video can act on the report (test this on someone)
- [ ] Reviewing a report is faster than watching the video (time it)

---

# PHASE 8 — Benchmark dataset, human review UI, metrics harness

**Effort:** 1.5 weeks. **Do not skip or defer this.** Everything after it is guesswork without it.

## Objective
A labeled benchmark and a metrics harness, so Phase 9 optimization is measured rather than felt.

## Technical detail

### 8.1 Dataset size for one person
Spec §60 suggests 10 products × 10 videos. For a solo developer that is a month of labeling. **Start with 40 videos**, which at ~8 requirements each gives ~320 labeled decisions — statistically thin but enough to expose systematic failures, which is the actual goal (spec §60).

Stratify deliberately (spec §61): ~22 normal cases, ~18 hard cases covering fast cuts, captions occluding the product, tiny text, poor lighting, partially obscured product, multiple similar products, speech/visual disagreement, subtle hook, no hook, CTA only in text, CTA only in speech, long intro, silent video, music-heavy, multiple speakers, and paraphrased-rather-than-literal required phrases.

**Hard cases are worth ~5× normal cases** for finding bugs. Weight your collection accordingly. Grow to 100 videos opportunistically as real work produces them.

### 8.2 Labeling
Per video: brief, expected hook window + type + strength, product first appearance, demonstration intervals, required-speech presence/timestamps, CTA presence/modality/timestamp, planted claims, and a per-requirement ground-truth status with a reason.

Budget ~6–8 min/video → ~5 hours. Do it in two sittings to limit drift, and **re-label 10 videos a week later to measure your own self-consistency.** That number is the ceiling on measurable system accuracy and belongs in every accuracy claim you make.

### 8.3 Gradio review app
In-Colab with `share=True`. Layout: video player, requirement table with model status, a human-status dropdown, a reason field, evidence display, and a save button writing `corrections.jsonl` to Drive (spec §58).

**Timestamp seeking in Gradio is awkward.** The practical solution is better than fixing it: **pre-cut 3-second evidence clips** with ffmpeg (`-ss t-1 -t 3`) plus a contact sheet of the cited evidence frames. Reviewing a 3-second clip is faster than scrubbing anyway, and it removes the JS integration problem entirely.

Corrections are dual-purpose: they are the accuracy metric today and the fine-tuning dataset later (spec §57).

### 8.4 Metrics harness
Three evaluation levels (spec §59):

**A. Model capability**
- Product first-appearance MAE (seconds) and % within ±1.0 s
- Event detection precision/recall against labeled events
- Hook presence accuracy; hook type accuracy; strength ordinal agreement (use weighted Cohen's κ, not raw accuracy — ordinal agreement needs an ordinal metric)
- OCR: character error rate on a hand-transcribed 10-video subset; CTA/discount-code recall
- ASR: WER on a hand-transcribed 5-video subset; brand-term recall

**B. Requirement evaluation accuracy**
- Macro-F1 over `{PASS, PARTIAL, FAIL, UNCERTAIN}`
- Binary F1 with PARTIAL collapsed to PASS, and separately to FAIL (the gap between these two is informative about how much PARTIAL is doing)
- Per-requirement-type breakdown — **this is the actionable one.** "Speech requirements 0.91 F1, visual requirements 0.62" tells you exactly where to spend the next two weeks.
- Confusion matrix; UNCERTAIN rate; false-positive PASS rate (the most damaging error class — it tells a brand a video is compliant when it is not)

**C. Product usefulness**
- Review time vs. manual watching
- Human override rate
- Recommendation acceptance rate

**Plus a cost/latency table per stage** (spec §87), since Phase 9 optimizes against it.

Store every run under `runs/{run_id}/` with the full config hash, so any number in any report is traceable to the exact configuration that produced it.

## Exit criteria
- [ ] 40 videos labeled, stratified as designed
- [ ] Gradio app functional; a full review takes < 5 min/video
- [ ] Metrics harness produces all three levels from a single command
- [ ] **Baseline numbers recorded and committed** — this is the number every future change is measured against
- [ ] Self-consistency measured on the 10 re-labeled videos

---

# PHASE 9 — Measured optimization

**Effort:** 2 weeks. Now, and only now, tune.

## Objective
Improve accuracy per GPU-second using the benchmark as the arbiter.

## Ablations, in ROI order

1. **Frame budget:** 8 / 16 / 24 / 32 / 48 / 64 frames. Find the accuracy plateau. Likely your biggest cost lever. Expect the plateau well below 64 for short videos.
2. **Transcript+OCR context in the VLM prompt:** on vs. off. Expect a large effect. Also test "transcript only" — it may capture most of the gain at a fraction of the prompt length.
3. **Sampling strategy:** uniform-only vs. hybrid (hook/CTA windows) vs. hybrid + adaptive. This validates the entire Phase 1 design; it deserves a direct test rather than an assumption.
4. **Hook window density:** 0.25 s vs. 0.5 s vs. 1.0 s spacing.
5. **Model:** 4B fp16 / 4B NF4 / 8B NF4 / 8B bf16, and the Thinking variant on Pass 2 only.
6. **Architecture A vs. B:** direct video input vs. controlled frames (spec §25) — a real question, answered with numbers.
7. **One-pass vs. two-pass** (spec §26/§27). Expect two-pass to win on debuggability and probably on accuracy; confirm.
8. **L2 similarity thresholds:** sweep against the benchmark; pick the operating point that minimizes false-positive PASS.
9. **OCR frame selection:** all frames vs. priority-only vs. dedupe-skipping.
10. **Prompt versions:** every prompt change is an ablation with a version bump.

**Protocol:** change one variable, run the full benchmark, record to `runs/`, compare against baseline. Batch overnight. Never eyeball two videos and conclude.

## vLLM — where it actually helps
Not for serving. For **batched offline inference** during these sweeps: 40 videos × 10 configurations = 400 inference runs, and vLLM's continuous batching plus PagedAttention can cut that from hours to tens of minutes.

Costs to weigh: engine startup is slow (1–3 min), it wants a large VRAM fraction, and multimodal support for a specific model version may lag Transformers. Verify Qwen3-VL is supported in the vLLM version you can install on Colab before committing. **If it fights you for more than half a day, skip it** — Transformers with a persistent loaded model and a simple loop is perfectly adequate at this scale.

## Other optimizations (spec §88)
- Remove redundant frame processing (double-resize audit — verify no path resizes twice)
- Verify the cache is achieving high hit rates in real use; log the ratio
- Batch multiple videos per VLM call only if the context budget allows (usually it does not)
- Reduce `max_new_tokens` to the observed p99 output length

## Exit criteria
- [ ] Ablation table complete with benchmark metrics and cost per configuration
- [ ] Chosen configuration documented with the numbers that justified it
- [ ] Cost per video reduced or accuracy improved vs. baseline — with evidence
- [ ] Config frozen as `v1.0` and recorded in the decision log

---

# PHASE 10 — Productionization (optional, demand-driven)

**Effort:** 2–3 weeks. **Only build this when someone other than you needs to use the system.**

Follow spec §41–§44, §68:
- FastAPI with the spec §41 contract (`POST /videos`, `/briefs`, `/audits`; `GET /audits/{id}`)
- Async jobs: start with FastAPI `BackgroundTasks` + SQLite job table; add Redis + Arq/RQ only under real concurrency (spec §42 — "do not prematurely introduce Kubernetes," and equally, do not prematurely introduce Celery)
- SQLite → Postgres migration using the spec §44 schema. Write plain SQL from the start and this is a connection-string change plus type fixes.
- Object storage: Drive → S3/R2/GCS behind a storage interface you defined in Phase 0
- GPU hosting: Colab is not a server. Options are Modal / RunPod / Replicate (serverless GPU, pay-per-second, cold starts) or a persistent small GPU instance. Modal fits this workload well — bursty, GPU-bound, containerized.
- Next.js frontend only if the HTML report proves genuinely insufficient
- Security (spec §66): MIME validation by magic bytes, size caps, sandboxed decoding, path-traversal prevention, no execution of embedded metadata, retention policy

**Deliberately deferred:** TikTok URL acquisition (spec §67). Keep the adapter interface so it can be added, but note that platform terms of service and access restrictions are a legal question, not an engineering one. Upload-first remains correct.

---

# PHASE 11 — Specialized detectors (trigger-gated)

**Effort:** 1–2 weeks. **Do not start without a measured trigger** (spec §78).

| Trigger from the Phase 8 metrics | Add |
|---|---|
| Product first-appearance MAE > ~1.5 s, or product-ID confusion on similar items | **Grounding DINO** (open-vocabulary, text-conditioned — matches "the blue moisturizer tube" without training) or **YOLO-World**. Prefer these over YOLO, which would need a labeled product dataset you do not have. |
| Missed cuts damaging adaptive sampling | A dedicated shot-boundary model, or a tuned TransNetV2 |
| Poor audience-alignment judgments | A dedicated classifier, or accept the limitation and report it |
| High claim false-negative rate | A fine-tuned claim classifier (a small text model — cheap and effective) |

The gate (spec §78): *does this materially improve benchmark performance at acceptable latency, cost and complexity?* Measure before and after on the same benchmark.

---

# PHASE 12 — RAG and fine-tuning (late, evidence-driven)

## 12.1 RAG (spec §56, §77)
Only when you have many brands and reusable knowledge: approved/forbidden claim language, brand voice rules, recurring audience requirements, campaign templates. Then `bge-m3` (multilingual, multi-granularity) or `bge-large-en-v1.5` + Qdrant, feeding the **brief compiler** — retrieving rules and context, never "watching the video" (spec §56). Below ~100k vectors, a NumPy matrix still beats a vector database on total complexity.

## 12.2 Fine-tuning (spec §57, §79)
**Preconditions, all of them:**
- ≥ 300–500 human corrections in `corrections.jsonl`
- A stable baseline benchmark
- A *systematic, measurable* error pattern — not scattered noise
- Prompt engineering, few-shot examples and rule-based post-processing already exhausted

**Then:** LoRA/QLoRA via PEFT + TRL, or Unsloth (notably faster and lower-VRAM, with vision model support). Target the **narrow task** with the worst measured accuracy — hook classification or requirement adjudication — not "the whole pipeline."

Colab constraints: a 4B vision LoRA is tight on a T4 and comfortable on an L4/A100. QLoRA (4-bit base + LoRA adapters) with gradient checkpointing, rank 16–32, on the alpha=2×rank convention. Split train/val/test by *video*, never by requirement — requirements from the same video leak.

**Always A/B against the pretrained baseline on the held-out test set.** Fine-tuning that improves training loss and not benchmark accuracy is a waste of a week (spec §57: do not fine-tune because the project is "an AI project").

---

# 13. Cross-cutting concerns

## 13.1 Prompt registry
Files under `prompts/`, semantically versioned (`p1_visual_evidence_v3.txt`). Every artifact records the prompt version. Every prompt change is an ablation. **Never inline a prompt in Python.**

## 13.2 Determinism (spec §45)
Greedy decoding, `temperature=0`, fixed seeds, pinned model revisions, pinned library versions in `requirements.lock`, canonical JSON serialization for hashing. Accept that different GPU architectures can produce slightly different outputs even greedily — store outputs, do not expect cross-hardware bit-identity.

## 13.3 Observability (spec §65)
Every stage logs: `video_id`, `run_id`, stage, start/end, duration, cache hit/miss, model + revision, prompt version, frame count, token counts, peak VRAM, error. Structured JSONL to `runs/{run_id}/log.jsonl`. This is what makes the performance budget (spec §87) real rather than aspirational.

## 13.4 Testing (spec §86)
- **Unit (CPU, fast):** sampler windows, timestamp conversion, dedupe/merge logic, scoring arithmetic, schema validation, cache keying. Should run in seconds on every push.
- **Integration:** one tiny sample video through each stage; mock the models where possible so it runs without a GPU.
- **Regression:** every bug becomes a benchmark case with the exact failing video (spec §86). This is how a solo project retains institutional memory.

## 13.5 Failure handling (spec §64)
| Failure | Behavior |
|---|---|
| Cannot decode | `FAILED_PREPROCESSING`, specific reason code |
| No audio | Continue video-only; speech requirements → `UNCERTAIN` (not FAIL) |
| OCR unavailable | Continue, mark OCR layer degraded, OCR requirements → `UNCERTAIN` |
| VLM timeout/OOM | Retry once with reduced frames; then `FAILED_VISION_INFERENCE` |
| VLM unparseable output | Repair → one retry → empty evidence, `parse_failed` |
| Imprecise timestamps | Flag evidence approximate; widen tolerance in temporal rules |
| Model uncertain | `UNCERTAIN`, never a fabricated verdict |

Partial results are always better than a failed run. Every degradation must be visible in the report — a silently degraded audit is worse than no audit.

---

# 14. Schedule

| Phase | Effort | Cumulative | Milestone |
|---|---|---|---|
| 0 — Environment + cache | 4 days | wk 1 | Everything loads; cache works |
| 1 — Preprocessing | 1.5 wk | wk 2.5 | Trustworthy timestamps |
| 2 — ASR + OCR | 1.5 wk | wk 4 | Text evidence |
| ★ A — Skeleton audit | 3 days | wk 4.5 | **First end-to-end report** |
| 3 — Qwen3-VL Pass 1 | 2 wk | wk 6.5 | Visual evidence + model decision |
| 4 — Brief compiler | 1 wk | wk 7.5 | Briefs → requirements |
| 5 — Evidence normalizer | 4 days | wk 8 | Unified reusable evidence |
| 6 — Evaluator + hook + claims | 2 wk | wk 10 | Full adjudication |
| 7 — Scoring + report | 1 wk | wk 11 | **Demo-ready MVP** |
| 8 — Benchmark + review UI | 1.5 wk | wk 12.5 | **Measurable accuracy** |
| 9 — Optimization | 2 wk | wk 14.5 | **v1.0 frozen config** |
| 10 — Productionization | 2–3 wk | on demand | API + hosting |
| 11 — Detectors | 1–2 wk | trigger-gated | |
| 12 — RAG / fine-tuning | 2–4 wk | trigger-gated | |

**~14 weeks to a measured, defensible v1.0** at 15–20 h/week. Phases 10–12 are demand- and evidence-driven, not scheduled.

The three checkpoints that matter: **week 4.5** (integration proven), **week 11** (demoable), **week 14.5** (measured).

---

# 15. Decision log — defaults and upgrade triggers

| Decision | Default | Upgrade trigger |
|---|---|---|
| Decoder | **PyAV** (true PTS) | — |
| Image ops | OpenCV headless | — |
| ASR | faster-whisper `large-v3-turbo`, VAD on, word timestamps | WER on brand terms; multi-speaker need → WhisperX + pyannote |
| OCR | PaddleOCR-CPU **or** RapidOCR-ONNX (Phase 0 bake-off) | Text failure cases in the benchmark |
| VLM | Qwen3-VL-4B-Instruct fp16 (T4) / bf16 (L4+) | Benchmark gap → 8B NF4/AWQ |
| VLM input | Controlled frame list (Architecture B) | Phase 9 ablation may favor direct video |
| Frame budget | 32 for ≤30 s, 48 for 30–60 s | Phase 9 plateau analysis |
| Hook window | `[0, 5 s]` @ 0.25 s | Ablation |
| Timestamp output | Frame indices → deterministic mapping | — |
| Structured output | Prompt + json_repair + 1 retry | > 5% parse failure → constrained decoding |
| Brief parser LLM | Hosted API, or resident VLM text-only | — |
| Adjudicator | Resident VLM text-only, retrieval-then-adjudicate | Accuracy gap → 8B / Thinking / API |
| Embeddings | `bge-small-en-v1.5` + NumPy | Multilingual → BGE-M3; >100k vectors → Qdrant |
| Storage | Drive + SQLite | Multi-user → S3 + Postgres |
| UI | Self-contained HTML + Gradio | External users → FastAPI + Next.js |
| Serving | Transformers, persistent load | Phase 9 sweeps → vLLM offline batch |
| Scoring | Deterministic band (pessimistic/optimistic) + coverage | — |
| Fine-tuning | None | ≥300 corrections + systematic error |

---

# 16. Risk register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| PaddlePaddle/CUDA conflict blocks OCR | High | **High** | RapidOCR-ONNX fallback decided in Phase 0, behind an interface |
| VLM timestamps unreliable | High | **High** | Frame-index output + validation + `timestamp_unreliable` flag |
| 8B doesn't fit; 4B is insufficient | Med | Med | NF4/AWQ; Pass-1/Pass-2 model split; Colab Pro for L4 |
| Whisper hallucination on music | Med | Med | VAD + confidence + compression-ratio filters |
| Burned-in captions double-count evidence | Med | **High** | `derived_from_speech` cross-check in Phase 2 |
| Colab session limits break long runs | Med | High | Cache-first design; every stage resumable |
| Benchmark too small to be conclusive | Med | Med | Stratify toward hard cases; report confidence intervals; grow opportunistically |
| Hook "strength" is unmeasurably subjective | Med | **High** | Anchored ordinal rubric; measure self-consistency; report it as the ceiling |
| Scope creep into FastAPI/Next.js/Qdrant early | **High** | **High** | This plan. Phases 10–12 are gated. |
| Prompt changes silently regress accuracy | Med | High | Versioned prompts; benchmark every change |
| False-positive PASS erodes trust | **High** | Med | Track it as a first-class metric; bias thresholds against it |
| Claims module treated as legal advice | High | Low | Explicit disclaimer in every report; assistive framing throughout |

---

# 17. What NOT to build (and when to reconsider)

| Do not build | Reconsider when |
|---|---|
| TikTok scraper/downloader | The core evaluator is proven **and** the legal question is answered |
| Postgres / Redis / Celery / Kubernetes | Real concurrent users exist |
| Qdrant or any vector DB | > ~100k vectors |
| Next.js frontend | The HTML report is demonstrably insufficient |
| YOLO / Grounding DINO | Phase 8 metrics show a product-detection gap |
| Fine-tuning | ≥300 corrections **and** a systematic error pattern |
| Speaker diarization | Multi-speaker videos are a measured failure source |
| Virality prediction | Never, as a hard truth (spec §2.2) |
| A custom video model | Never |
| vLLM serving | Concurrent inference demand exists |
| Multi-language support | The corpus demands it |

---

# 18. The definition of done for the MVP

Per spec §89, success is not "the AI understands every TikTok perfectly." It is:

> For a stratified 40-video benchmark of real brand videos, the system produces useful, timestamped, explainable compliance judgments that a human can correct and audit — reproducibly, on a single Colab GPU, for under a minute of compute per video.

Concretely, at the end of Phase 9 you should be able to answer, for any video (spec §93):

- What is the exact duration? → `MediaMeta`
- Which frames were analyzed, and **why each one**? → frame manifest with `reason`
- What timestamp does each frame represent, and how confident are we? → PTS + `is_approximate_ts`
- What did Whisper hear, and when? → transcript with word timestamps
- What on-screen text appeared, and when? → OCR intervals with `derived_from_speech`
- What did Qwen3-VL observe, and when? → validated visual evidence
- Which requirement failed, and on what evidence? → requirement results with cited IDs
- Why is the score what it is? → deterministic arithmetic you can reproduce by hand
- How accurate is any of this? → the Phase 8 benchmark, with its stated ceiling

When those nine answers are reliable, this stops being a black-box AI experiment and becomes a tractable engineering system — which is the entire thesis of `product.md` §93.

---

## Immediate next actions

1. Create the GitHub repo with the Phase 0 skeleton
2. Collect the 5 sample videos (normal / fast-cut / caption-heavy / silent / rotated)
3. Open a Colab notebook and run the hardware + dependency probe
4. **Timebox the PaddleOCR vs RapidOCR bake-off to 45 minutes** and record the decision
5. Build `cache.py` and its tests before anything else touches a model
