# 4. Notebook ↔ backend parity checklist

Every pipeline component, and how it was mapped. "Verbatim" means the code is
byte-identical to the notebook cell apart from removed driver statements.

---

## 4.1 Pipeline stages

| Component | Notebook | Backend | Fidelity |
|---|---|---|---|
| Video download | cell 5 `download_videos` | `auditor/ingest/video.py` | **Verbatim** |
| Brief fetch | cell 89 `load_brief_text` | `auditor/brief/loader.py` | **Verbatim** |
| Stage keys / cache | cell 7 `stage_key` | `auditor/cache.py` | **Verbatim** |
| Probe / preflight | cells 9, 10 | `auditor/preprocessing/` | **Verbatim** |
| Sampler | cell 11 | `auditor/preprocessing/sampler.py` | **Verbatim** |
| Scan / scenes / decode | cells 13–15 | `auditor/preprocessing/` | **Verbatim** |
| Audio + manifest | cells 16, 17 | `auditor/preprocessing/` | **Verbatim** |
| Phase 1 driver | cell 18 + 50 | `auditor/pipeline.py` | **Verbatim** (driver → `app/services/pipeline.run_preprocess`) |
| ASR | cell 21 | `auditor/asr/whisper.py` | **Verbatim** |
| OCR | cells 22–24 | `auditor/ocr/` | **Verbatim** |
| Text normalisation | cell 19 | `auditor/evidence/text.py` | **Verbatim** |
| Dedupe / caption check | cells 25, 26 | `auditor/evidence/` | **Verbatim** |
| Phase 2 driver | cell 27 + 51 | `auditor/pipeline_p2.py` | **Verbatim** (driver → `run_text_stages`) |
| Vision config / schemas | cells 61, 62 | `auditor/vision/` | **Verbatim** |
| Vision prompts | cell 63 | `auditor/vision/prompts.py` | **Verbatim** — prompt text unchanged |
| Frame selection | cell 64 | `auditor/vision/frames.py` | **Verbatim** |
| Gemini backend + probe | cell 68 | `auditor/vision/gemini.py` | **Verbatim** |
| Qwen (local) backend | cell 66 | `auditor/vision/qwen.py` | **Extracted, unwired** — `AUDITOR_VISION_PROVIDER=local` is not a supported deployment |
| Vision parse / normalize | cells 69, 70 | `auditor/vision/` | **Verbatim** |
| Phase 3 stage + batch | cells 72, 84 | `auditor/pipeline_p3.py`, `vision/batch.py` | **Verbatim** (driver → `run_vision`) |
| Brief schema / temporal | cells 90, 91 | `auditor/brief/` | **Verbatim** |
| Brief structure / segmentation | cells 93, 94 | `auditor/brief/` | **Verbatim** |
| Brief prompt | cell 95 | `auditor/brief/prompt.py` | **Verbatim** — prompt text unchanged |
| Brief backends / validate / dedupe | cells 96–98 | `auditor/brief/` | **Verbatim** |
| Brief compile | cell 99 | `auditor/brief/compile.py` | **Verbatim** |
| Approval gate | cell 100 | `auditor/brief/approval.py` | **Verbatim code, new caller** — see 4.3 |
| Evidence config / records | cell 109 | `auditor/evidence5/config.py` | **Verbatim** |
| Tolerance / normalisers / linking | cells 110–112 | `auditor/evidence5/` | **Verbatim** |
| Modality health / `can_fail_on` | cell 113 | `auditor/evidence5/health.py` | **Verbatim** |
| Evidence stage | cell 115 | `auditor/evidence5/stage.py` | **Verbatim** |
| Retrieval | cell 121 | `auditor/audit/retrieval.py` | **Verbatim** |
| L1 / L2 / L3 | cells 122–124 | `auditor/audit/` | **Verbatim** — thresholds and prompts unchanged |
| Hook / claims | cells 125, 126 | `auditor/audit/` | **Verbatim** |
| **Creative angle** | cell 127 | `auditor/audit/creative_angle.py` | **Verbatim** — `ANGLE_SYSTEM`, `named_brief_angles`, `_clean_concept_fit` all unchanged |
| Standing | cell 128 | `auditor/audit/standing.py` | **Verbatim** |
| Audit stage | cell 129 | `auditor/audit/stage.py` | **Verbatim** |
| Score config | cell 137 | `auditor/scoring/config.py` | **Verbatim** — weights, bands, `talking_point_*` unchanged |
| **`score_audit`** | cell 139 | `auditor/scoring/score.py` | **Verbatim** — arithmetic, asserted model-call-free by test |
| Recommendations | cell 140 | `auditor/scoring/recommend.py` | **Verbatim** |
| Report HTML | cell 141 | `auditor/scoring/report.py` | **Verbatim** |
| Figures | cell 142 | `auditor/scoring/figures.py` | **Verbatim** |
| **Batch orchestrator** | cell 147 (§90) | `app/services/pipeline.py` | **Translated** — see 4.2 |
| Batch table + zip | cell 148 (§91) | API response + `angle_distribution` | **Replaced** |

---

## 4.2 §90 → `app/services/pipeline.py`, statement by statement

| §90 | Backend | Same? |
|---|---|---|
| `_all_videos = discover_videos()` | `ns['discover_videos']()` | identical |
| fixture exclusion by `TEST_VIDEO_NAME` | same guard | identical |
| `MAX_VIDEOS` cap | `settings.max_videos_per_job` (default 25) | identical value, config source |
| `expected_stage_keys(_v)` | same | identical |
| `select_artifact(_vd, 'transcript'…)` ×3 | same | identical |
| `_row['visual_stale'] = …` | same expression | identical |
| `build_evidence(_v, _tr, _oc, _vi, P5, verbose=False)` | same | identical |
| `load_records(_ev)` | same | identical |
| modality health extraction | same keys, same fallbacks | identical |
| `audit_video(_v, _ev, _p6_brief, P6, verbose=False, force=…)` | same | identical |
| `BRIEF_NOT_USABLE` → raise | → `PhaseError('phase6', …)` | same guard, typed error |
| creative-angle row fields | same five fields | identical |
| `GROUP_SELECTED:` scan → `chosen_options` | same | identical |
| `score_audit(_res, _p6_brief, P7, …)` | same | identical |
| `evaluate_recommendations(…)` | same | identical |
| `build_figures(_sc, _res, _recs, cfg=P7)` | same | identical |
| `write_report(…)` → `html_path` | same | identical |
| `talking_point_coverage(_res, _p6_brief)` | same | identical |
| `Counter(v['status'] …)` → `verdict_mix` | same | identical |
| standing/angle "why" diagnostics | → `row['notes']` + log | same logic, structured output |
| `except → BATCH_FAILURES.append` | same isolation, per-video | identical |
| `print(...)` throughout | `log.info/warning` | **presentation only** |

Nothing else differs.

---

## 4.3 Deliberate differences

| # | Difference | Why | Approved |
|---|---|---|---|
| 1 | **Approval is automatic and frozen on first compile** (`approved_by: "api:freeze-on-first-compile"`) instead of a human signing §48c | An HTTP API has no human. Freezing preserves the property that actually matters — the same brief always means the same requirement set — without inventing one. `recompile: true` replaces it deliberately. | **Yes** (2026-09-23) |
| 2 | **Brief input is Google Docs URL or raw text** | Exactly the notebook's `load_brief_text`, including the check that rejects a Google sign-in page returned as HTTP 200. No new ingestion. | **Yes** (2026-09-23) |
| 3 | `artifacts/` and `briefs/` are **shared** across jobs; only `inbox/` and `reports/` are per-job | Content-addressing makes sharing correct and is the entire performance story. Per-job artifacts would re-pay every 72–240 s vision pass. | Recommended in `03_decisions` §3.3 |
| 4 | `DIRS` is a ContextVar proxy | 37 cells read it as a module global. A proxy keeps every one of them unchanged. | — |
| 5 | Artifact writes use write-tmp-then-`os.replace` | Two jobs processing the *same* video would write the same path. Same content, but a torn read is possible. Safety only. | — |
| 6 | `MAX_VIDEOS`, `BRIEF_COMPILE_RUNS`, `BRIEF_KEEP_THRESHOLD` move to env vars | Same defaults, different source. | — |
| 7 | Model probes run **once at startup**, not per request | They cost live API calls. The notebook also runs them once. | — |
| 8 | Notebook test/exit-criteria and inspection cells are **not extracted** | 75 cells: test suites, plots, single-video drivers. Real work, none of it runtime. Each listed with a reason in `EXCLUDED`. | — |
| 9 | Optional `HF_TOKEN` / `HF_HOME` exported to the environment at startup | **No pipeline code changed.** `WhisperModel(name, …)` and `SentenceTransformer(model_id, …)` take no token argument; all three model loaders resolve credentials through `huggingface_hub`, which reads the process environment. Raises the anonymous download rate limit, which is what bites on a datacentre IP. Both variable spellings are set. | Requested 2026-09-23 |

---

## 4.4 What cannot be reproduced exactly, and why

| Component | Deterministic? | Comparison criterion for the integration test |
|---|---|---|
| Phases 1, 2, 5 | **Yes** | exact equality — manifests, transcripts, OCR intervals, evidence ids |
| `stage_key` / caching | **Yes** | exact equality |
| Phase 7 arithmetic | **Yes** | exact equality *given fixed verdicts* |
| Report HTML | **Yes** | exact equality given fixed inputs |
| Phase 3 vision | **No** — LLM | schema valid; event count within ±2; same event *types* present |
| Phase 4 compile | **No** — 6/9/16/21/22/24 reqs observed | mitigated by consensus **and** by freezing; compare against the frozen compile, not a fresh one |
| Phase 6 L3 | **No** — LLM | verdict *distribution* stable; individual borderline calls are not |
| Creative angle | **No** — LLM | `named_angles` exact (deterministic); `concept_fit` angles ⊆ `named_angles` and sum to 100 |
| `headline` | **Partly** | within **±5** of the notebook run on the same frozen brief |

Exact-match assertions on LLM output would be a test that fails for the wrong
reason and gets disabled within a week.

---

## 4.5 Status

| | |
|---|---|
| Entry points present | **58 / 58** (`tools/check_entrypoints.py`) |
| Automated tests | **64 passing** (no key, no network, no model) |
| Notebook cells accounted for | **148 / 148** — 73 extracted, 75 excluded by decision |
| Generated modules | **71** |
| Driver statements removed | **232**, each listed at the foot of its module |
| End-to-end run against the known-good video | **not yet run** — needs a live `GEMINI_API_KEY` |

The last line is the remaining gap. `tests/test_parity.py` is the next piece of
work: run the pill-organiser brief and the three known videos through the
backend, and diff against the notebook's recorded `BATCH_RESULTS` using the
criteria in 4.4.
