# 1. Notebook execution map

Generated from `phases_1_to_7_BATCH.ipynb` by static analysis (`scratchpad/gen_cellmap.py`) — not written from memory.

**148 code cells**, 111 markdown cells, 30,964 lines of code.

Legend — **Prod**: whether the cell is required for production execution.

| # | Section | Kind | Prod | Lines | I/O | Defines |
|---|---|---|---|---|---|---|
| | **Phase 0  environment, paths, input** | | | | | |
| 1 | `§0.0  Optional fallback packages -- OFF, and on Colab it must stay off` | DRIVER | replaced by the orchestrator | 70 | WX | — |
| 2 | `§0.1  Resilient install  --  Phases 1 and 2 together, Python 3.13 safe` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 157 | WRX | _write_torch_pins, try_install, record |
| 3 | `§0.2  Imports, hardware profile, backend detection` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 190 | X | _importable |
| 4 | `§0.3  Paths` | DRIVER | replaced by the orchestrator | 61 | – | — |
| 5 | `§0.4  BATCH INPUT  —  PASTE LINKS (below), or upload a .zip` | LIBRARY+DRIVER | YES (library part) | 268 | WRNX | _is_video, extract_zip_to_inbox, _ytdlp, download_videos |
| | **Phase 1  preprocessing (decode, sample, manifest)** | | | | | |
| 6 | `auditor/config.py` | LIBRARY+DRIVER | YES (library part) | 308 | – | PreflightConfig, SamplerConfig, SceneConfig, DecodeConfig, AudioConfig, PreprocessConfig … (+5) |
| 7 | `auditor/cache.py` | LIBRARY | YES | 97 | WR | sha256_file, canonical_json, stage_key, write_json, read_json, provenance … (+2) |
| 8 | `auditor/storage/discovery.py` | LIBRARY+DRIVER | YES (library part) | 69 | R | restore_exports_from_drive, discover_videos |
| 9 | `auditor/preprocessing/probe.py` | LIBRARY | YES | 160 | X | MediaMeta, _parse_rate, _extract_rotation, run_ffprobe, probe_video |
| 10 | `auditor/preprocessing/preflight.py` | LIBRARY | YES | 94 | – | PreflightResult, sniff_container, preflight |
| 11 | `auditor/preprocessing/sampler.py` | LIBRARY | YES | 114 | – | PlanTarget, global_target_count, make_uniform_targets, make_dense_window, plan_targets, enforce_budget |
| 12 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 109 | – | _run_sampler_tests |
| 13 | `auditor/preprocessing/scan.py` | LIBRARY | YES | 104 | – | FrameScan, scan_video, save_scan, load_scan |
| 14 | `auditor/preprocessing/scenes.py` | LIBRARY | YES | 59 | – | SceneAnalysis, detect_scenes |
| 15 | `auditor/preprocessing/decode.py` | LIBRARY | YES | 182 | R | resolve_rotation, _apply_rotation, _cap_long_edge, build_frame_plan, extract_frames |
| 16 | `auditor/preprocessing/audio.py` | LIBRARY | YES | 50 | X | extract_audio |
| 17 | `auditor/preprocessing/manifest.py` | LIBRARY | YES | 89 | – | build_manifest |
| 18 | `auditor/pipeline.py` | LIBRARY | YES | 156 | WR | PreprocessResult, preprocess_video |
| | **Phase 2  ASR + OCR libraries** | | | | | |
| 19 | `auditor/evidence/text.py` | LIBRARY+DRIVER | YES (library part) | 535 | – | _fold_number_words, _number_to_words, normalize_token, normalize_text, phrase_variants, build_word_index … (+19) |
| 20 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 206 | – | _run_text_tests |
| 21 | `auditor/asr/whisper.py` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 435 | – | FasterWhisperBackend, TransformersWhisperBackend, read_wav_mono16k, compression_ratio, load_vad, load_asr … (+4) |
| 22 | `auditor/ocr/engine.py` | LIBRARY | YES | 206 | – | OCRLine, RapidOCREngine, PaddleOCREngine, TesseractEngine, _quad_to_bbox, load_ocr |
| 23 | `auditor/ocr/selection.py` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 262 | – | select_ocr_frames, build_masks, apply_masks, merge_words_into_lines, merge_lines_into_blocks, frame_signature … (+2) |
| 24 | `auditor/ocr/run.py` | LIBRARY | YES | 148 | – | run_ocr |
| 25 | `auditor/evidence/dedupe.py` | LIBRARY | YES | 171 | – | frame_gap_tolerance, bbox_containment, _can_merge, build_text_intervals |
| 26 | `auditor/evidence/caption_check.py` | LIBRARY+DRIVER | YES (library part) | 232 | – | _speech_windows, _load_word_vocab, text_readability, _test_readability, cross_check_captions |
| 27 | `auditor/pipeline_p2.py` | LIBRARY | YES | 116 | WR | TextEvidenceResult, run_asr_stage, run_ocr_stage, process_text_evidence |
| | **Phase 1+2 drivers, inspection, ground-truth fixture** | | | | | |
| 28 | `—` | DRIVER | replaced by the orchestrator | 19 | W | — |
| 29 | `VIDEO_PATH = Path('/content/drive/MyDrive/tiktok-auditor/videos/originals/my_video.mp4')` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 28 | RX | — |
| 30 | `—` | DRIVER | replaced by the orchestrator | 12 | R | — |
| 31 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 6 | – | — |
| 32 | `§13.5  Phase 1 -> Phase 2 hand-off` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 34 | – | — |
| 33 | `§14.1  Manifest overview + sampling coverage plot` | DRIVER | replaced by the orchestrator | 61 | – | — |
| 34 | `§14.2  Contact sheet — LOOK AT THE FRAMES.` | LIBRARY+DRIVER | YES (library part) | 41 | – | contact_sheet |
| 35 | `§14.3  INDEPENDENT TIMESTAMP VERIFICATION` | LIBRARY | YES | 66 | X | verify_timestamps |
| 36 | `§14.4  Automated exit-criteria assertions` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 89 | – | check_exit_criteria |
| 37 | `—` | DRIVER | replaced by the orchestrator | 51 | R | — |
| 38 | `§11.1  ASR` | DRIVER | replaced by the orchestrator | 16 | – | — |
| 39 | `§11.2  Free the ASR model BEFORE loading OCR.` | DRIVER | replaced by the orchestrator | 6 | – | — |
| 40 | `§11.3  OCR  (CPU by design -- see section 5)` | DRIVER | replaced by the orchestrator | 14 | – | — |
| 41 | `§11.4  Cache contract -- both stages must be instant on a second run.` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 9 | – | — |
| 42 | `§12.1  Transcript inspection + what got filtered and why` | DRIVER | replaced by the orchestrator | 60 | – | — |
| 43 | `§12.2  WORD-TIMESTAMP VERIFICATION -- scrub and listen.` | LIBRARY | YES | 36 | X | verify_word_timestamps |
| 44 | `§12.3  OCR overlay -- did it read what you can see?` | LIBRARY+DRIVER | YES (library part) | 40 | – | draw_ocr_overlays |
| 45 | `§12.4  Dedupe: before -> after` | DRIVER | replaced by the orchestrator | 79 | R | — |
| 46 | `§12.5  Burned-in caption cross-check -- does the correctness fix fire?` | DRIVER | replaced by the orchestrator | 54 | – | — |
| 47 | `§12.6  THE UNIFIED TIMELINE` | DRIVER | replaced by the orchestrator | 42 | R | — |
| 48 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 146 | – | check_phase2_exit_criteria |
| 49 | `—` | LIBRARY+DRIVER | YES (library part) | 39 | – | sampler_variant |
| 50 | `—` | LIBRARY+DRIVER | YES (library part) | 75 | WR | preprocess_folder |
| 51 | `—` | LIBRARY+DRIVER | YES (library part) | 83 | W | process_all |
| 52 | `auditor/preprocessing/handoff.py` | LIBRARY+DRIVER | YES (library part) | 113 | – | frames_for_ocr, select_vlm_frames_preview, frames_for_vlm, build_qwen_content |
| 53 | `auditor/evaluation/matcher.py` | LIBRARY+DRIVER | YES (library part) | 100 | – | search_transcript, search_ocr, check_requirement |
| 54 | `—` | LIBRARY | YES | 21 | R | export_phase2 |
| 55 | `—` | DRIVER | replaced by the orchestrator | 39 | – | — |
| 56 | `§18.1  Build the ground-truth video` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 84 | X | _drawtext |
| 57 | `§18.2  Score the pipeline against ground truth` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 97 | – | — |
| 58 | `§18 only ever speaks about the synthetic test clip, so this is the check that` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 18 | – | — |
| | **Phase 3  vision (frames -> Gemini)** | | | | | |
| 59 | `§20.1  Install -- Phase 3 only. Phase 1 + 2 dependencies are already present.` | DRIVER | replaced by the orchestrator | 126 | – | — |
| 60 | `§20.2  GPU budget + free the Phase 2 models` | DRIVER | replaced by the orchestrator | 42 | – | — |
| 61 | `auditor/config.py` | LIBRARY+DRIVER | YES (library part) | 413 | – | VisionConfig, Phase3Config, free_vram_gb, vision_token_budget, scene_count_of, resolve_vision_config … (+1) |
| 62 | `auditor/vision/schemas.py` | LIBRARY+DRIVER | YES (library part) | 89 | – | VisualEvent, VisualEvidence |
| 63 | `auditor/vision/prompts/p1_visual_evidence.txt` | LIBRARY+DRIVER | YES (library part) | 113 | – | build_p1_instructions |
| 64 | `auditor/vision/frames.py` | LIBRARY | YES | 270 | R | _as_manifest, shot_bounds, select_vlm_frames, build_frame_table, fit_to_pixel_budget, load_frame_images |
| 65 | `auditor/vision/messages.py` | LIBRARY | YES | 72 | – | build_context_block, build_vlm_messages, estimate_vision_tokens, measure_input_tokens |
| 66 | `auditor/vision/qwen.py` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 391 | – | VLMBackend, affordable_frames, plan_vlm_load, _pick_model_class, load_vlm, free_vlm |
| 67 | `§37a  API key  --  HOISTED, because Phase 3 needs it too` | LIBRARY+DRIVER | YES (library part) | 125 | – | key_failure_verdict |
| 68 | `§26b  auditor/vision/gemini.py  --  the frames go to Gemini instead of Qwen` | LIBRARY+DRIVER | YES (library part) | 512 | WN | GeminiVLMBackend, _vision_secret, make_gemini_vlm, make_vision_backend, probe_vision_models, autoselect_vision_model |
| 69 | `auditor/vision/parsing.py` | LIBRARY | YES | 131 | – | extract_json_object, parse_model_json, looks_non_english, detect_judgment_language |
| 70 | `auditor/vision/normalize.py` | LIBRARY | YES | 415 | – | _coerce_int, _coerce_float, _same_word, adds_no_new_fact, merge_adjacent_events, normalize_visual_events … (+1) |
| 71 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 948 | – | _run_vision_tests |
| 72 | `auditor/pipeline_p3.py` | LIBRARY | YES | 345 | WR | _SkipAffordability, run_vision_stage, visual_summary |
| 73 | `§30.1  Preconditions -- fail with a useful message, not a NameError` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 35 | R | — |
| 74 | `§30.1b  VRAM diagnostic -- run this if a load OOMs` | LIBRARY+DRIVER | YES (library part) | 47 | – | vram_report |
| 75 | `§26c  Choose the vision backend, then load it` | DRIVER | replaced by the orchestrator | 37 | – | — |
| 76 | `§30.2b  DRY RUN -- measure the real input size WITHOUT generating.` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 119 | R | — |
| 77 | `§30.3  Extract visual evidence` | DRIVER | replaced by the orchestrator | 13 | – | — |
| 78 | `§30.4  Cache contract -- a second run must be instant and must not touch the GPU` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 54 | – | _NoGenerationAllowed |
| 79 | `§31.1  The evidence table` | DRIVER | replaced by the orchestrator | 44 | – | — |
| 80 | `§31.2  LOOK AT THE FRAMES THE MODEL CITED` | LIBRARY | YES | 35 | – | show_event_evidence |
| 81 | `§31.3  Visual evidence on the SAME timeline as speech and on-screen text` | DRIVER | replaced by the orchestrator | 47 | R | — |
| 82 | `—` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 99 | R | check_phase3_exit_criteria |
| 83 | `§33  Bake-off -- OFF by default. Needs VRAM, time, and more than one video.` | DRIVER | replaced by the orchestrator | 49 | – | — |
| 84 | `auditor/vision/batch.py` | LIBRARY | YES | 93 | R | run_vision_all, visual_evidence_for |
| | **Phase 3  batch driver** | | | | | |
| 85 | `§30.5  BATCH  —  the vision pass for EVERY video` | DRIVER | replaced by the orchestrator | 84 | R | — |
| 86 | `—` | DRIVER | replaced by the orchestrator | 26 | – | — |
| 87 | `—` | LIBRARY+DRIVER | YES (library part) | 305 | R | _ck, _note, _wrn |
| | **Phase 4  brief compile** | | | | | |
| 88 | `§37  PHASE 4 — configuration, versions, and where compiled briefs live` | LIBRARY+DRIVER | YES (library part) | 371 | N | BriefConfig, Phase4Config, sha256_text, probe_hosted_models, autoselect_hosted_model |
| 89 | `§37b  Load a brief from a Google Doc, a file, or raw text` | LIBRARY | YES | 97 | WRN | google_doc_id, _looks_like_html, fetch_google_doc, load_brief_text |
| 90 | `§38  The requirement schema` | LIBRARY+DRIVER | YES (library part) | 172 | – | Requirement, scoring_units, total_scoring_weight, requirement_id, make_label |
| 91 | `§39  Symbolic temporal expressions -- parsed, never eval()'d` | LIBRARY+DRIVER | YES (library part) | 192 | – | _ExprParser, _expr_tokens, validate_time_expr, resolve_time_expr, resolve_requirement_window |
| 92 | `§40  Deterministic evidence_mode and type inference` | LIBRARY+DRIVER | YES (library part) | 237 | – | _has, infer_evidence_mode, infer_polarity, infer_requirement_type, infer_priority, is_machine_checkable |
| 93 | `§40b  Document structure -- markdown, headings, sections, items` | LIBRARY+DRIVER | YES (library part) | 566 | – | BriefSection, strip_md_inline, classify_section, section_type_hint, is_plain_heading, strip_descriptive_sentences … (+8) |
| 94 | `§40c  Segmentation, temporal extraction, match hints` | LIBRARY+DRIVER | YES (library part) | 283 | – | _num, find_campaign, _looks_like_heading, _split_compound, brief_units, split_brief … (+3) |
| 95 | `§41  The prompt` | LIBRARY+DRIVER | YES (library part) | 169 | – | build_brief_prompt |
| 96 | `§42  Backends` | LIBRARY | YES | 463 | N | BriefBackend, BudgetExhausted, HostedLLMBackend, LocalTextBackend, RuleBasedBackend, _get_secret … (+1) |
| 97 | `§43  Normalise, validate, cross-check` | LIBRARY | YES | 371 | – | _as_float, _as_list_of_str, _span_in_brief, _claim_backed, normalize_requirements, pydantic_check |
| 98 | `§44  Dedupe and conflict detection` | LIBRARY+DRIVER | YES (library part) | 756 | – | _similar, dedupe_requirements, _req_field, is_figure_fidelity_requirement, adopt_stray_asks, _content_words … (+14) |
| 99 | `§45  The compile stage` | LIBRARY | YES | 977 | WR | compile_brief, load_compiled_brief, _req_fingerprint, _cluster_fingerprints, compile_brief_consensus |
| 100 | `§46  Human confirmation gate` | LIBRARY | YES | 252 | W | render_requirements_table, requirements_digest, approval_state, approve_brief, requirements_for_audit, resolve_brief_for_video |
| 101 | `§47  Phase 4 test suite -- no GPU, no network, no API key` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 776 | R | _FakeBriefBackend, _run_brief_tests |
| 102 | `§48  Compile a brief` | DRIVER | replaced by the orchestrator | 128 | R | — |
| 103 | `§48b  Human review and approval  -- product.md §73's exit criterion` | DRIVER | replaced by the orchestrator | 7 | – | — |
| 104 | `§48c  Approve  -- run this ONLY after reading the table above` | DRIVER | replaced by the orchestrator | 15 | – | — |
| 105 | `§48d  Compile a set of briefs and compare them` | DRIVER | replaced by the orchestrator | 63 | – | — |
| 106 | `§49  Phase 4 exit criteria` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 141 | – | check_phase4_exit_criteria |
| 107 | `§50  Hand-off` | DRIVER | replaced by the orchestrator | 35 | – | — |
| 108 | `§51  FULL PIPELINE DIAGNOSTIC -- run this, paste the whole output` | LIBRARY | YES | 501 | R | _load, _newest, _fmt, run_pipeline_diagnostic |
| | **Phase 5  evidence assembly** | | | | | |
| 109 | `§52  PHASE 5 — configuration, closed enums, the evidence record` | LIBRARY+DRIVER | YES (library part) | 185 | – | EvidenceConfig, Phase5Config, EvidenceRecord, evidence_id |
| 110 | `§53  Timestamp tolerance and confidence labelling` | LIBRARY+DRIVER | YES (library part) | 182 | – | manifest_frame_times, examined_frame_times, sampling_tolerance, record_tolerance, _merge_spans, span_tolerance … (+1) |
| 111 | `§54  Normalisers -- speech, OCR, visual, metadata -> EvidenceRecord` | LIBRARY | YES | 223 | X | _approx_frames, _clip, speech_records, ocr_records, visual_records, metadata_records |
| 112 | `§55  Cross-modal linking and interval merging` | LIBRARY | YES | 151 | – | _text_similar, _quoted_span, link_text_overlays, merge_visual_intervals |
| 113 | `§56 + §57  Modality health and per-modality coverage` | LIBRARY | YES | 298 | – | modality_health, can_fail_on, modes_that_can_fail, coverage_map |
| 114 | `§58  Derived aggregates and window accessors` | LIBRARY | YES | 125 | – | derive_aggregates, _in_window, speech_in_window, text_in_window, visual_in_window, words_for … (+2) |
| 115 | `§59  The evidence stage, cached` | LIBRARY | YES | 337 | WR | _stage_key_of, _asr_keys, _ocr_keys, _visual_keys, expected_stage_keys, select_artifact … (+3) |
| 116 | `§60  Phase 5 test suite -- no GPU, no network, no model` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 669 | W | _fake_manifest, _run_evidence_tests |
| 117 | `§61  Build evidence for TARGET` | DRIVER | replaced by the orchestrator | 71 | – | — |
| 118 | `§62  Phase 5 exit criteria` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 97 | – | check_phase5_exit_criteria |
| 119 | `§62b  Hand-off to Phase 6` | DRIVER | replaced by the orchestrator | 29 | – | — |
| | **Phase 6  requirement verdicts** | | | | | |
| 120 | `§63  PHASE 6 — configuration, verdict schema, closed enums` | LIBRARY+DRIVER | YES (library part) | 360 | – | RetrievalConfig, L1Config, L2Config, L3Config, HookConfig, ClaimsConfig … (+5) |
| 121 | `§64  Retrieval -- requirement -> candidate evidence` | LIBRARY | YES | 281 | – | _req_query_text, _term_hit, _hint_score, window_for, spread_sample, _dedupe_candidates … (+3) |
| 122 | `§65  L1 -- the deterministic layer` | LIBRARY+DRIVER | YES (library part) | 512 | – | _fail_allowed, _fail_or_uncertain, _fmt_t, l1_forbidden, _modalities_present, _conjunctive_shortfall … (+8) |
| 123 | `§66  L2 -- embedding similarity (CPU, optional)` | LIBRARY | YES | 169 | – | l2_model, warm_l2, _embed, l2_similarities, evaluate_l2 |
| 124 | `§67  L3 -- LLM adjudication (text only, batched, IDs validated)` | LIBRARY | YES | 332 | – | _evidence_line, build_l3_prompt, _validate_l3, evaluate_l3_batch |
| 125 | `§68  Hook module -- spec §33` | LIBRARY+DRIVER | YES (library part) | 158 | – | hook_features, evaluate_hook |
| 126 | `§69  Claims / policy module -- spec §38` | LIBRARY | YES | 177 | – | claim_candidates, evaluate_claims |
| 127 | `§69b  The creative angle  --  what she actually made, not what she missed` | LIBRARY+DRIVER | YES (library part) | 297 | – | named_brief_angles, _clean_concept_fit, _brief_concepts, evaluate_creative_angle |
| 128 | `§69c  Standing  --  the WHOLE brief against the WHOLE video, as one judgement` | LIBRARY+DRIVER | YES (library part) | 380 | – | _standing_video_digest, _standing_topic_seen_in_brief, decomposed_mean_alignment, evaluate_standing |
| 129 | `§70  The evaluate stage, cached` | LIBRARY | YES | 491 | WR | _resolve_groups, evaluate_requirements, audit_video, verdicts_for |
| 130 | `§71  Phase 6 test suite -- no GPU, no network, no API key` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 597 | – | _FakeL3Backend, _rec, _health, _req, _run_phase6_tests |
| 131 | `§72  Audit TARGET against the compiled brief` | DRIVER | replaced by the orchestrator | 172 | R | — |
| 132 | `§73  Phase 6 exit criteria` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 344 | – | check_phase6_exit_criteria |
| 133 | `§73b  Hand-off to Phase 7` | DRIVER | replaced by the orchestrator | 32 | – | — |
| 134 | `§74  FULL-PIPELINE SELF-CHECK  --  Phases 1 to 6, end to end` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 631 | R | _issue, _hdr, _row, _g, _quiet, _phase … (+6) |
| 135 | `§74a  Phase 7 dependencies` | DRIVER | replaced by the orchestrator | 40 | X | — |
| 136 | `§74b  PLAN CONFORMANCE  --  where do we actually stand, Phases 0 to 6` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 688 | R | _c, _probe, _safe, _read_or_note, _load_all, _stale_report … (+15) |
| | **Phase 7  scoring + report** | | | | | |
| 137 | `§75  PHASE 7 -- scoring configuration` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 353 | – | ScoreConfig, RecommendConfig, ReportConfig, Phase7Config, _dim_haystack, resolve_dimension … (+3) |
| 138 | `§75b  Which quantity discriminates?  --  answered WITHOUT labels` | LIBRARY+DRIVER | YES (library part) | 365 | WR | _load_controls, _save_controls, candidate_scores, _collect_audits, _compiled_briefs, make_control_audits … (+1) |
| 139 | `§76  score_audit  --  the number, by arithmetic` | LIBRARY | YES | 737 | WR | _score_weight, _unit_value, _is_safety_pass, _is_talking_point, _collapse_talking_points, _band_with_critical_floor … (+5) |
| 140 | `§78  Recommendations  --  the only model call in Phase 7` | LIBRARY+DRIVER | YES (library part) | 276 | – | _rec_violations, _rec_digest, evaluate_recommendations |
| 141 | `§79  The report  --  one HTML file, opens anywhere, no server` | LIBRARY+DRIVER | YES (library part) | 1014 | WRX | esc, _fmt_ts, _ts_link, _pill, _section, build_proxy_video … (+16) |
| 142 | `§79b  Figures  --  the geometry of dimension matching` | LIBRARY+DRIVER | YES (library part) | 636 | – | _unit_time, _trace_provenance, _fig_html, _axis_dimensions, figure_dimension_time, figure_ask_vs_delivery … (+7) |
| 143 | `§77  Phase 7 test suite  --  no GPU, no network, no model, no API key` | TEST/EXIT-CRITERIA | no  (notebook proof, not runtime) | 583 | R | _run_phase7_tests_body, _run_phase7_tests |
| 144 | `§80  Score the TARGET, and build the report` | DRIVER | replaced by the orchestrator | 231 | R | — |
| 145 | `§81  Phase 7 exit criteria` | LIBRARY | YES | 177 | – | _phase7_exit |
| 146 | `§82  Self-check addendum  --  Phase 7, on top of §74's Phases 1 to 6` | LIBRARY+DRIVER | YES (library part) | 158 | – | _p7ck |
| | **BATCH  orchestrator + outputs** | | | | | |
| 147 | `§90  THE BATCH RUN  —  every video in the inbox, against ONE brief` | DRIVER | replaced by the orchestrator | 274 | – | — |
| 148 | `§91  THE BATCH TABLE, and one zip to download` | DRIVER | replaced by the orchestrator | 255 | – | — |

I/O key: **W** writes files · **R** reads files · **N** network / model API · **X** subprocess (ffmpeg/ffprobe)
