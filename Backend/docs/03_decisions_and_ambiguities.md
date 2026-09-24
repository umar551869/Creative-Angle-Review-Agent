# 3. Decisions I cannot make for you

You asked me to stop and explain rather than guess. These are the places where
the notebook's behaviour and an HTTP API genuinely conflict. Everything else I
can carry over unchanged.

---

## 3.1 BLOCKER — the human approval gate

**What the notebook does.** Phase 4 compiles the brief into requirements, then
a human reads the table (`§48b`) and signs it (`§48c`). `audit_video` refuses
to run against an unsigned brief:

```python
_res = audit_video(...)
if _res.get('status') == 'BRIEF_NOT_USABLE':
    raise RuntimeError('brief not usable -- approve it in §48c')
```

`requirements_for_audit()` enforces it. This is deliberate: the compiler is the
one non-deterministic stage, and **the same brief has compiled to 6, 9, 16, 21,
22 and 24 requirements across runs at temperature 0.** The signature is what
makes two videos comparable — they were measured against the *same* contract.

**Why it conflicts.** `POST /analyze` has no human in it. Something has to give.

| Option | Consequence |
|---|---|
| **A. Auto-approve** (`approved_by="api"`) | Simplest. **Silently discards the guarantee that two runs of the same brief are comparable.** A caller could get 21 requirements today and 24 tomorrow, with different scores, and nothing would say why. |
| **B. Two-step API** — `POST /briefs` returns the compiled requirements for review, `POST /briefs/{id}/approve` signs it, `POST /analyze` requires an approved brief id | Preserves the semantics exactly. Costs the caller one extra round trip, once per brief. |
| **C. Approve-on-first-compile, then freeze** | `POST /analyze` compiles + auto-approves a brief the first time it is seen, and every later request for the same brief text reuses that frozen compile. One brief = one contract, forever, with no human step. |

**My recommendation: C, with B available.** C keeps the property that actually
matters — *the same brief always means the same requirement set* — without
inventing a human. B stays for callers who want to review before committing.
A is the one I would not ship silently.

**I need your call on this.**

---

## 3.2 BLOCKER — "content brief URL" is narrower than it sounds

`load_brief_text` (cell 89) accepts exactly three things:

1. A **Google Docs** URL → fetched via the `/export?format=txt` endpoint
2. A **local file path**
3. **Raw brief text**

Any other `http(s)://` URL is refused outright, on purpose:

```python
if s.lower().startswith(('http://', 'https://')):
    raise ValueError('Only Google Docs URLs are fetched directly. ...')
```

There is also a real safety check worth keeping: a Google permission failure
returns **HTTP 200 with an HTML sign-in page**, and `_looks_like_html` catches
it — because that HTML *would* compile into requirements, which is far worse
than failing.

**Your spec says "a content brief URL".** If you mean Google Docs, we are done
and I change nothing. If you mean arbitrary URLs (Notion, Dropbox, a PDF, a raw
`.txt` on S3), that is **new ingestion code** — and each format needs its own
extractor plus its own version of the "did I get the document or a login page"
check.

**Which do you want?** I will default to preserving Google Docs + file + raw
text, and add a clearly-separate extractor layer only if you say so.

---

## 3.3 `DIRS` and job isolation — where I propose to differ from your sketch

You sketched `runs/<run_id>/{input,video,audio,frames,...}`. I recommend
against it, and this is invited ground ("design it based on the notebook's
actual intermediate artifacts").

**The notebook is content-addressed.** Artifacts live at
`artifacts/<video_hash>/<stage>__<stage_key>.json`, where the key is derived
from input hashes + config + version. Two requests for the same video produce
*the same key*. If each job gets a private `artifacts/`, then:

- every repeat request re-runs a 72–240 s vision pass that was already paid for
- the cache — the single biggest performance feature in the system — is dead

**Proposed layout instead:**

```
DATA_ROOT/
  artifacts/        SHARED, content-addressed, durable   <-- the cache
  briefs/           SHARED, keyed by brief text sha256   <-- the contracts
  jobs/<job_id>/
    inbox/          per-job: the videos this request downloaded
    reports/        per-job: the HTML/JSON this request produced
    job.json        status, timings, errors
  runs/             observability logs
```

Shared where content-addressing makes sharing correct; private where a request
genuinely owns the bytes. **Two concurrent jobs cannot collide** on `inbox` or
`reports`, and *should* share `artifacts`.

The one real hazard: two jobs processing the **same** video concurrently would
write the same artifact path. Same content, but a torn read is possible. Fix:
write to `<path>.tmp.<pid>` and `os.replace()` — atomic on POSIX and Windows.
I will add that; it is a safety fix, not a behaviour change.

**`DIRS` itself** is read by 37 cells as a module global. To make it
job-scoped I will back it with a `ContextVar` and expose the same
`DIRS['inbox']` mapping interface, so **no extracted pipeline code changes**.
That is the lowest-drift option available.

---

## 3.4 Sync vs async — not really a question

Measured: vision alone is **72–240 s per video**, ASR model load ~50 s, cold
3-video run **5–12 minutes**.

**Asynchronous, job-based.** `POST /analyze` → `202` + `job_id`;
`GET /jobs/{job_id}` → status, per-phase progress, and the result when done.
A synchronous endpoint would exceed every default proxy timeout in existence.

I will also expose `GET /jobs/{id}/report/{video_id}` to serve the HTML report
directly, since it is a self-contained file.

**Worker model:** one background worker, **videos sequential within a job**
(matching the notebook exactly), **jobs sequential by default**
(`MAX_CONCURRENT_JOBS=1`). Raising that is a config change, but it multiplies
model loads and, on GPU, races VRAM — so the default is the safe one.

---

## 3.5 Extraction strategy — how I avoid rewriting 24,000 lines

The notebook is **~24,000 lines across 148 cells**, of which **81 are
production-required**. Hand-rewriting that is weeks of work and the drift risk
is exactly what you told me to avoid.

**The notebook already declares its own module layout.** 31 cells carry their
intended path in the header comment:

```
# auditor/config.py
# auditor/cache.py
# auditor/preprocessing/probe.py
# auditor/asr/whisper.py
# auditor/vision/gemini.py
# auditor/pipeline_p2.py
...
```

So the plan is:

- **`Backend/auditor/`** — generated by an extractor that copies cell bodies
  **verbatim** into the module each cell names, resolving cross-cell globals
  into explicit imports. Phases 4–7 have no `auditor/` headers, so they map by
  `§` section to `auditor/brief/`, `auditor/evidence/`, `auditor/audit/`,
  `auditor/scoring/`. Regenerable: when the notebook changes, re-run it.
- **`Backend/app/`** — genuinely new, hand-written: FastAPI, job manager,
  ingestion, config, logging, schemas, orchestrator.

Modularity where it buys maintainability; verbatim where it buys parity.

**Parity oracle:** the extractor also emits a `notebook_namespace.py` that
`exec`s the same production cells in order into one namespace. The integration
test runs the known-good video through *both* and diffs verdicts, evidence ids,
and scores. If they disagree, the extraction is wrong — and I will know which
module.

---

## 3.6 Parity caveats I already know about

| Component | Reproducible exactly? | Why |
|---|---|---|
| Phases 1, 2, 5 | **Yes** — deterministic | ffmpeg, ASR, OCR, evidence assembly |
| `stage_key` / caching | **Yes** | pure function of content |
| Phase 7 scoring | **Yes** — arithmetic | design rule 1 |
| Report HTML | **Yes** | deterministic given inputs |
| Phase 3 vision | **No** — model output varies | same frames, different prose |
| Phase 4 compile | **No** — 6/9/16/21/22/24 reqs observed | mitigated by consensus + frozen approval |
| Phase 6 L3 | **No** — LLM adjudication | verdict *distribution* is stable; individual borderline calls are not |
| Creative angle | **No** — LLM | `concept_fit` percentages will vary |

**Comparison criteria for the integration test:** exact equality for Phases 1,
2, 5 and for scoring arithmetic *given fixed verdicts*; for model stages, assert
schema validity, flag sets, and that `headline` falls within ±5 of the notebook
run. Exact-match assertions on LLM output would be a test that fails for the
wrong reason.

---

## 3.7 Things I found that are worth fixing, but I will NOT change silently

| Finding | Why it matters | Proposed |
|---|---|---|
| `VISION_PROVIDER='local'` path exists (Qwen, cell 66) but this notebook is hosted-only | 391 lines of dead weight in the backend | Extract it, leave it unwired, config flag off |
| `MAX_VIDEOS = 25` hardcoded | A ceiling belongs in config | → env var, same default |
| `BRIEF_COMPILE_RUNS = 3`, `BRIEF_KEEP_THRESHOLD = 0.5` | Real thresholds, worth exposing | → config, same defaults |
| Dimension weights fixed; band thresholds are placeholders | Already known-open in `complete.md` | Unchanged — Phase 8's job |
| `test_changing_text.mp4` fixture | Already excluded from §30.5 and §90 | Not extracted at all |

None of these change pipeline behaviour. Each is listed so nothing is silent.
