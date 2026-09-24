"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 27, 51.
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
@dataclass
class TextEvidenceResult:
    video_hash: str
    video_id: str
    transcript: Optional[dict]
    ocr: Optional[dict]
    transcript_path: Optional[Path]
    ocr_path: Optional[Path]
    asr_cache_hit: bool = False
    ocr_cache_hit: bool = False

    def summary(self) -> str:
        t, o = self.transcript, self.ocr
        lines = [f'video: {self.video_id}']
        if t:
            s = t['stats']
            lines += [
                f"ASR   : [{t.get('backend', '?')}] {t['model']['model']} on {t['model']['device']}"
                + ('   *** DEGRADED: no VAD ***' if t.get('degraded') else ''),
                f"        vad: {t.get('vad_backend', '?')}",
                f"        {s['segments_kept']} segments kept / {s['segments_dropped']} dropped "
                f"{s['drop_reasons'] or ''}",
                f"        {s['word_count']} words, speech ratio {s['speech_ratio']:.2f}, "
                f"mean word prob {s['mean_word_probability']:.3f}",
                f"        {s['transcribe_seconds']}s  ({s['realtime_factor']}x realtime)  "
                f"cache={'HIT' if self.asr_cache_hit else 'miss'}",
            ]
        else:
            lines.append('ASR   : SKIPPED (no audio stream)')
        if o:
            s = o['stats']
            lines += [
                f"OCR   : {s['ocr_calls']} calls over {s['frames_considered']} frames "
                f"({s['duplicate_skip_rate']*100:.0f}% skipped as duplicates)",
                f"        {s['raw_detections']} raw detections -> {len(o['intervals'])} intervals",
                f"        {o['caption_check']['flagged']} interval(s) flagged derived_from_speech",
                f"        {s['ocr_seconds']}s  cache={'HIT' if self.ocr_cache_hit else 'miss'}",
            ]
        return '\n'.join(lines)

def run_asr_stage(video: dict, cfg: Phase2Config, model=None, model_info=None,
                  force=False, verbose=True) -> tuple:
    vdir = DIRS['artifacts'] / video['video_hash']
    key = stage_key('asr', ASR_STAGE_VERSION, [video['video_hash']], {'asr': asdict(cfg.asr)})
    path = vdir / f'transcript__{key}.json'

    if path.exists() and not force:
        if verbose: print(f'  ASR CACHE HIT ({key})')
        return read_json(path), path, True

    if not video['audio_path'] or not Path(video['audio_path']).exists():
        if verbose: print('  no audio -> ASR skipped (valid state, not a failure)')
        return None, None, False

    if model is None:
        model, model_info = load_asr(cfg.asr)
    tr = transcribe(model, video['audio_path'], cfg.asr, model_info)
    tr['provenance'] = provenance('asr', ASR_STAGE_VERSION, key, tr['stats']['transcribe_seconds'])
    write_json(path, tr)
    return tr, path, False

def run_ocr_stage(video: dict, cfg: Phase2Config, transcript: Optional[dict],
                  engine=None, force=False, verbose=True) -> tuple:
    vdir = DIRS['artifacts'] / video['video_hash']
    key = stage_key('ocr', OCR_STAGE_VERSION, [video['video_hash'], video['plan_hash']],
                    {'ocr': asdict(cfg.ocr), 'dedupe': asdict(cfg.dedupe)})
    path = vdir / f'ocr__{key}.json'
    manifest = read_json(video['manifest_path'])

    if path.exists() and not force:
        ocr = read_json(path)
        if verbose: print(f'  OCR CACHE HIT ({key})')
        # the caption check is cheap and pure -- always refresh it
        ocr['caption_check'] = cross_check_captions(ocr['intervals'], transcript or {}, cfg.caption)
        write_json(path, ocr)
        return ocr, path, True

    if engine is None:
        engine = load_ocr(cfg.ocr)
    raw = run_ocr(engine, manifest, video['frames_dir'], cfg.ocr, verbose=verbose)
    intervals = build_text_intervals(raw['detections'], manifest, cfg.dedupe)
    caption = cross_check_captions(intervals, transcript or {}, cfg.caption)

    ocr = {
        'schema_version': OCR_STAGE_VERSION,
        'backend': getattr(engine, 'name', cfg.ocr.backend),
        'intervals': intervals,
        'detections': raw['detections'],
        'per_frame': raw['per_frame'],
        'masked_out': raw['masked_out'],
        'caption_check': caption,
        'stats': {**raw['stats'], 'intervals': len(intervals),
                  'dedupe_compression': round(len(intervals) / max(1, raw['stats']['raw_detections']), 3)},
        'config': {'ocr': asdict(cfg.ocr), 'dedupe': asdict(cfg.dedupe)},
        'provenance': provenance('ocr', OCR_STAGE_VERSION, key, raw['stats']['ocr_seconds']),
    }
    write_json(path, ocr)
    return ocr, path, False

def process_text_evidence(video: dict, cfg: Phase2Config = P2, model=None, model_info=None,
                          engine=None, force=False, verbose=True) -> TextEvidenceResult:
    if verbose: print(f'--- {video["video_id"]} ({video["source"]}) ---')
    tr, tr_path, tr_hit = run_asr_stage(video, cfg, model, model_info, force, verbose)
    ocr, ocr_path, ocr_hit = run_ocr_stage(video, cfg, tr, engine, force, verbose)
    return TextEvidenceResult(video['video_hash'], video['video_id'], tr, ocr,
                              tr_path, ocr_path, tr_hit, ocr_hit)


def process_all(videos: list, cfg: Phase2Config = P2, force: bool = False) -> pd.DataFrame:
    rows = []

    # ---- ASR pass: load once, transcribe everything, then free -------------
    need_asr = [v for v in videos if v['has_audio']]
    model, info = (load_asr(cfg.asr) if need_asr else (None, None))
    transcripts = {}
    for i, v in enumerate(videos, 1):
        try:
            tr, _, hit = run_asr_stage(v, cfg, model, info, force, verbose=False)
            transcripts[v['video_hash']] = tr
            print(f'[ASR {i}/{len(videos)}] {v["video_id"]:<18s} '
                  f'{"cached" if hit else "computed"}  '
                  f'{len(tr["words"]) if tr else 0} words')
        except Exception as exc:
            transcripts[v['video_hash']] = None
            print(f'[ASR {i}/{len(videos)}] {v["video_id"]:<18s} FAILED: {type(exc).__name__}: {exc}')
    if model is not None:
        free_vram(model); model = None

    # ---- OCR pass: load once, run everything -------------------------------
    engine = load_ocr(cfg.ocr)
    for i, v in enumerate(videos, 1):
        t0 = time.time()
        try:
            o, _, hit = run_ocr_stage(v, cfg, transcripts.get(v['video_hash']),
                                      engine, force, verbose=False)
            tr = transcripts.get(v['video_hash'])
            rows.append({
                'video_id': v['video_id'], 'source': v['source'],
                'duration_s': v['duration_s'],
                'words': len(tr['words']) if tr else 0,
                'segments': tr['stats']['segments_kept'] if tr else 0,
                'dropped': tr['stats']['segments_dropped'] if tr else 0,
                'speech_ratio': tr['stats']['speech_ratio'] if tr else 0.0,
                'ocr_calls': o['stats']['ocr_calls'],
                'raw_det': o['stats']['raw_detections'],
                'intervals': o['stats']['intervals'],
                'from_speech': o['caption_check']['flagged'],
                'wall_s': round(time.time() - t0, 2),
                'status': 'OK',
            })
        except Exception as exc:
            traceback.print_exc()
            rows.append({'video_id': v['video_id'], 'source': v['source'],
                         'status': f'{type(exc).__name__}: {exc}'})
        print(f'[OCR {i}/{len(videos)}] {v["video_id"]:<18s} {rows[-1]["status"]}')

    df = pd.DataFrame(rows)
    write_json(DIRS['runs'] / f'phase2_batch_{time.strftime("%Y%m%d_%H%M%S")}.json',
               rows)
    return df


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 116: print('pipeline_p2.py loaded  --  backend complete')
#   line 56: VIDEOS = discover_videos()
#   line 57: batch = process_all(VIDEOS)
#   line 58: print()
#   line 59: print(batch.to_string(index=False))
#   line 64: _p2_failed = [r for r in batch.to_dict('records') if r.get('status')]
#   line 65: _p2_ok = [r for r in batch.to_dict('records') if not r.get('status')]
#   line 66: print()
#   line 67: print(f'  BATCH RECONCILE (Phase 2): {len(_p2_ok)} of {len(batch)} video(s) 
#   line 69: for _r in _p2_ok:
#   line 76: if _p2_failed:
