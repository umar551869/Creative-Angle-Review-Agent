# 2. What the notebook actually does

Everything here is derived from `phases_1_to_7_BATCH.ipynb` by reading it, not
from assumptions. Cell numbers are 1-based over **code cells only** (148 of
them), which is how the rest of this project refers to them.

---

## 2.1 The one-sentence version

> Videos land in a directory; each is decoded into frames + audio; ASR and OCR
> read the words; a vision model describes the frames; a brief is compiled once
> into a set of **requirements**; every requirement is judged against the
> evidence by a three-rung ladder (deterministic → embedding → LLM); the
> verdicts are turned into a number **by arithmetic, never by a model**; and an
> HTML report plus a creative-angle attribution come out the other end.

---

## 2.2 Execution flow, as the notebook really runs it

```
BRIEF_SOURCE (Google Doc URL)            VIDEO_URLS (TikTok links)
        |                                          |
        |  §37b load_brief_text                    |  §0.4 download_videos (yt-dlp)
        v                                          v
   brief text  ──────────────────────────►   DIRS['inbox']/*.mp4
        |                                          |
        |                                          |  §13.x preprocess_folder
        |                                          v
        |                          PHASE 1  ffprobe → preflight → scan →
        |                                   scene detect → sample → decode
        |                                   frames → extract audio → manifest
        |                                          |
        |                          artifacts/<video_hash>/<plan_hash>/
        |                              manifest.json + frames/*.jpg + audio.wav
        |                                          |
        |                            ┌─────────────┴─────────────┐
        |                            v                           v
        |                   PHASE 2  ASR                 PHASE 2  OCR
        |                   faster-whisper               RapidOCR on selected
        |                   large-v3-turbo               frames, masked by
        |                   (model loaded ONCE           caption regions
        |                    for the whole batch)                |
        |                            |                          |
        |                   transcript__<key>.json     ocr__<key>.json
        |                            └─────────────┬─────────────┘
        |                                          |
        |                          PHASE 3  frames → Gemini  (§30.5)
        |                                   backend loaded ONCE per batch
        |                                          v
        |                                  visual__<key>.json
        |                                    (VisualEvent list)
        v                                          |
  PHASE 4  compile_brief_consensus (3 runs, keep ≥0.5)
           → requirements__<key>.json   ← HUMAN APPROVAL GATE (§48c)
                     |                                |
                     └────────────────┬───────────────┘
                                      v
                          PHASE 5  build_evidence
                          normalise speech + OCR + visual onto ONE timeline
                          → EvidenceRecord[] with stable evidence_id
                          → modality_health / can_fail_on
                                      v
                          PHASE 6  audit_video
                          per requirement: retrieve candidates → L1 → L2 → L3
                          + hook, claims, CREATIVE ANGLE, standing
                          → verdicts__<key>.json
                                      v
                          PHASE 7  score_audit  (arithmetic only)
                          → evaluate_recommendations (the one model call)
                          → build_figures → write_report
                          → report HTML + JSON
```

---

## 2.3 The design rules the code obeys

These are load-bearing. A backend that breaks one of them is not this system.

1. **No model writes a number.** `score_audit` is arithmetic over verdicts.
2. **Compliance ≠ achievement.** `verdict` (did she do it) and `alignment`
   (did it serve the ask) are separate axes.
3. **UNCERTAIN is an abstention, not a zero.** It leaves the denominator
   through `coverage`; it does not score 0.
4. **NOT_APPLICABLE leaves the denominator.**
5. **Bands, not false precision** — `lead_with_band` when coverage is thin.
6. **Everything traces** — every verdict cites `evidence_id`s.
7. **Degrade, never block** — a failed modality yields UNCERTAIN, not FAIL.
8. **Two independent things must agree, or the system abstains** —
   `can_fail_on(health, modality)` refuses to assert an absence the evidence
   did not establish.
9. **Content-addressed everything** — `stage_key(name, version, [hashes],
   {config})`. Re-running is free; an unbumped version silently serves stale
   data.

---

## 2.4 Entry points — the real API surface

These are the functions the backend must call. Everything else is either a
library detail or notebook-only.

| Phase | Function | Defined | Returns |
|---|---|---|---|
| 0 | `download_videos(urls)` | cell 5 | list of paths in the inbox |
| 0 | `load_brief_text(source)` | cell 89 | `{text, doc_id, source, chars}` |
| 1 | `preprocess_video(path, cfg, force)` | cell 18 | `PreprocessResult` |
| 1 | `preprocess_folder(folder, cfg, patterns)` | cell 50 | DataFrame |
| 1 | `discover_videos(unique=True)` | cell 8 | list of video dicts |
| 2 | `load_asr(cfg.asr)` / `run_asr_stage(...)` | cell 27 | transcript dict |
| 2 | `load_ocr(cfg.ocr)` / `run_ocr_stage(...)` | cell 27 | ocr dict |
| 2 | `process_all(videos, cfg, force)` | cell 51 | DataFrame |
| 3 | `make_vision_backend(cfg.vision)` | cell 68 | backend object |
| 3 | `run_vision_stage(v, cfg, backend, ...)` | cell 72 | `VisualEvidence` |
| 3 | `run_vision_all(videos, cfg, force)` | cell 84 | DataFrame |
| 4 | `compile_brief_consensus(text, runs, cfg, keep_threshold)` | cell 99 | compiled brief |
| 4 | `approval_state(...)` / `requirements_for_audit(...)` | cell 100 | gate |
| 5 | `expected_stage_keys(v)` / `select_artifact(...)` | cell 115 | key resolution |
| 5 | `build_evidence(v, tr, oc, vi, P5)` | cell 115 | evidence dict |
| 5 | `load_records(ev)` | cell 115 | `EvidenceRecord[]` |
| 6 | `audit_video(v, ev, brief, P6, force)` | cell 129 | verdicts + angle + standing |
| 7 | `score_audit(res, brief, P7, force)` | cell 139 | score dict |
| 7 | `evaluate_recommendations(...)` | cell 140 | advice |
| 7 | `build_figures(sc, res, recs, cfg)` | cell 142 | figure HTML |
| 7 | `write_report(v, res, brief, sc, recs, rec, fg, P7)` | cell 141 | `{html_path, json_path, html}` |
| 7 | `talking_point_coverage(res, brief)` | cell 139 | `{covered, total}` |

---

## 2.5 Creative-angle categorization — exactly how it works today

Defined in **cell 127 (`§69b`)**, called from inside `audit_video`, surfaced as
`result['creative_angle']`.

1. `named_brief_angles(brief)` returns the brief's **own named angles** — the
   *options* inside a choice group whose label reads like a set of angles
   (`concept|angle|format|territory|theme|creative|framework|treatment|
   execution|route|campaign`). A ten-option hook list does not become ten
   angles. On the pill-organiser brief this correctly yields
   `['No judgement zone', 'Health journey']`.
2. An LLM call (`ANGLE_SYSTEM`, restructured by fix 51 into *"Answer in THREE
   steps"* with step 3 **before** the JSON schema) returns:
   - `angle` — free-text description of what she actually made
   - `nearest_brief_concept` — closest of the brief's concepts
   - `concept_fit` — **a percentage split across the named angles**
3. `_clean_concept_fit` validates that split against the closed list, exactly
   as every other model output here is validated:

| input | result |
|---|---|
| clean 70/30 | preserved |
| doesn't sum (60/30) | renormalised, flag `CONCEPT_FIT_RENORMALISED:90->100` |
| invented angle | **dropped**, flag `CONCEPT_FIT_NOT_IN_BRIEF:<name>` |
| near-miss wording | matched to the real angle |

**This is a description, never a score.** It lives in the creative-angle block,
`§76` never reads it, and the report says so in those words.

---

## 2.6 Configuration and thresholds

Seven frozen dataclass singletons, each replaced (never mutated) by drivers:

| Name | Cell | Covers |
|---|---|---|
| `CFG` (`PreprocessConfig`) | 6 | preflight, sampler, scene, decode, audio |
| `P2` (`Phase2Config`) | 6 | ASR + OCR |
| `P3` (`Phase3Config`) | 61 | vision, frame budget, VRAM |
| `P4` (`Phase4Config`) | 88 | brief compile, model ladder, spend budget |
| `P5` (`Phase5Config`) | 109 | evidence, tolerance, modality health |
| `P6` (`Phase6Config`) | 120 | retrieval, L1/L2/L3, hook, claims |
| `P7` (`Phase7Config`) | 137 | score, recommend, report |

Two are **mutated at runtime by a probe**:

- cell 68: `P3 = replace(P3, vision=autoselect_vision_model(P3.vision))`
- cell 88: `P4 = replace(P4, brief=autoselect_hosted_model(P4.brief))`

Both send a live request to pick a working model. The backend must run these
**once at startup**, not per request — they cost API calls.

### Secrets

`GEMINI_API_KEY`, `OPENAI_API_KEY` — read from `os.environ`, with a Colab
`userdata` fallback (cell 67). Already clean: the notebook has no hardcoded
key, and cell 67 is explicit that it must never have one. Gemini is
**mandatory**; OpenAI is a paid fallback bounded by
`P4.brief.paid_call_budget`.

---

## 2.7 Filesystem layout the notebook actually uses

```
WORK = /content/work            (or ./work off Colab)
  inbox/        <-- videos, named by TikTok id
  artifacts/
    <video_hash>/
      <plan_hash>/manifest.json + frames/*.jpg + audio.wav
      transcript__<stage_key>.json
      ocr__<stage_key>.json
      visual__<stage_key>.json
      evidence__<stage_key>.json
      verdicts__<stage_key>.json
      score__<stage_key>.json
      <name>__report__<hash>.html / .json
  briefs/
    <brief_text_sha256>/requirements__<cache_key>.json
  runs/         <-- observability logs
  exports/      <-- tarballs
```

`DIRS` is a module-level dict read by **37 cells**. It is the single biggest
obstacle to per-request isolation — see §3.1 of the decisions document.

---

## 2.8 Performance profile (measured, not guessed)

| Stage | Cost | Notes |
|---|---|---|
| ASR model load | ~50 s | **once per batch**, not per video |
| ASR per video | seconds | faster-whisper `large-v3-turbo`, CPU int8 |
| OCR engine load | seconds | RapidOCR ONNX |
| **Vision per video** | **72–240 s** | the dominant cost; hosted Gemini |
| Vision probe | ~25–30 s | once, at startup |
| Brief compile | 3 model calls | **once per brief**, then cached forever |
| Phase 5/6/7 | seconds | L3 is batched |

Full-batch wall clock observed across this project: **3944 s → 608 s → 190 s →
86 s** as caching filled in. A cold 3-video run is **5–12 minutes**.

**This settles the API shape: it must be asynchronous.** A 12-minute HTTP
request is not a design, it is a timeout waiting to happen.

### Concurrency

`process_all` loads ASR once → frees → loads OCR once. `run_vision_all` loads
the vision backend once. Running videos in parallel would multiply model loads
and, on a GPU box, race for VRAM. **Videos must stay sequential within a job**,
exactly as the notebook does it. Cross-job parallelism is a separate question
(see decisions §3.4).
