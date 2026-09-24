"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 84.
Regenerate with:  python Backend/tools/extract_from_notebook.py

Bodies are VERBATIM. The only removal is the notebook's driver
statements (the lines that run a stage and print a table); those
are listed at the foot of this file and are replaced by
Backend/app/services/.

This file is LOADED BY auditor.runtime, not imported directly.
The notebook shares one global namespace and binds some names
late (globals().get(...)), so the loader reproduces that exactly
rather than guessing an import graph that the original never had.
"""
def run_vision_all(videos: list, cfg: Phase3Config = None, force: bool = False) -> 'pd.DataFrame':
    """Model loaded ONCE, then a loop. Resumable: cached videos cost nothing."""
    cfg = cfg or P3
    rows, backend = [], None
    try:
        for i, v in enumerate(videos, 1):
            key = stage_key('visual', VLM_STAGE_VERSION, [v['video_hash'], v['plan_hash']],
                            {'vision': asdict(cfg.vision), 'prompt': PROMPT_VERSION})
            cached = (DIRS['artifacts'] / v['video_hash'] / f'visual__{key}.json').exists()
            if backend is None and not (cached and not force):
                # the configured provider, not always the local model.
                # Hardcoding load_vlm here loads Qwen even when
                # provider='gemini', and this is the batch path -- the one place
                # nobody is watching the output.
                _mk = globals().get('make_vision_backend')
                backend = (_mk(cfg.vision) if callable(_mk)
                           else load_vlm(cfg.vision))   # load lazily, once
            try:
                tr = ocr_ = ev = None
                _t = next((x for x in discover_videos() if x['video_hash'] == v['video_hash']), v)
                tr, _, _ = run_asr_stage(_t, P2, None, None, False, verbose=False)
                ocr_, _, _ = run_ocr_stage(_t, P2, tr, None, False, verbose=False)
                ev = run_vision_stage(v, cfg, backend=backend, transcript_obj=tr,
                                      ocr_obj=ocr_, force=force, verbose=False)
                s = ev.stats
                rows.append({'video_id': v['video_id'], 'source': v['source'],
                             'status': ev.status, 'events': len(ev.events),
                             'flagged': s.get('events_with_flags'),
                             'attempts': s.get('attempts'),
                             'leaks': len(ev.judgment_leakage),
                             'infer_s': s.get('inference_seconds')})
            except Exception as exc:
                traceback.print_exc()
                rows.append({'video_id': v['video_id'], 'source': v['source'],
                             'status': f'{type(exc).__name__}', 'events': 0})
            print(f'[{i}/{len(videos)}] {v["video_id"]:<18s} {rows[-1]["status"]:<18s} '
                  f'{rows[-1].get("events", 0)} events')
            # WHY, not just THAT. The exception text is already in the
            # artifact's flags; printing only the status turns "here is what
            # killed it" into the word GENERATION_FAILED.
            if rows[-1].get('status') != 'OK':
                _ev = locals().get('ev')
                for _f in (getattr(_ev, 'flags', None) or []):
                    _d = _f.get('detail') if isinstance(_f, dict) else None
                    if _d:
                        print(f'        -> {_f.get("code")}: {str(_d)[:200]}')
    finally:
        free_vlm(backend)          # ALWAYS, even on an exception
    return pd.DataFrame(rows)

def visual_evidence_for(video_hash: str, cfg: Phase3Config = None) -> list:
    """
    Phase 5 accessor: visual events in the SAME shape as transcript segments and
    OCR intervals, so the evidence normaliser can merge all three on one timeline.
    """
    cfg = cfg or P3
    v = next((x for x in discover_videos() if x['video_hash'] == video_hash), None)
    if v is None:
        return []
    key = stage_key('visual', VLM_STAGE_VERSION, [v['video_hash'], v['plan_hash']],
                    {'vision': asdict(cfg.vision), 'prompt': PROMPT_VERSION})
    path = DIRS['artifacts'] / video_hash / f'visual__{key}.json'
    if not path.exists():
        return []
    ev = VisualEvidence.model_validate(read_json(path))
    return [{
        'id': e['id'], 'modality': 'visual', 'type': e['type'], 'action': e['action'],
        'start_seconds': e['start_seconds'], 'end_seconds': e['end_seconds'],
        'description': e['description'], 'objects': e['objects'],
        # the granular observations behind a merged span -- Phase 6 evaluates the
        # span, but a requirement about a specific moment needs these
        'segments': e.get('segments') or [],
        'merged_count': e.get('merged_count', 1),
        'confidence': e['confidence'],
        'source': ev.model.get('model', 'qwen3-vl'),
        'source_run_id': ev.provenance.get('cache_key'),
        'frame_ids': e['frame_ids'],
        'is_approximate_ts': e['timestamp_unreliable'],
        'flags': e['flags'],
    } for e in ev.events]


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 88: _sample = visual_evidence_for(TARGET['video_hash'])
#   line 89: print(f'batch.py loaded  --  visual_evidence_for() returns {len(_sample)} no
#   line 90: if _sample:
