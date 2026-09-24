"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 111.
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
def _approx_frames(manifest: dict, artifact: dict = None) -> set:
    """
    frame_ids whose timestamp Phase 1 had to interpolate.

    Phase 3 restates is_approximate_ts on its own frame_table, so read both:
    the manifest is the full plan, the artifact is what the stage was handed.
    """
    out = set()
    rows = list((manifest or {}).get('frames', []) or [])
    rows += list((artifact or {}).get('frame_table', []) or [])
    for f in rows:
        if f.get('is_approximate_ts') and f.get('frame_id'):
            out.add(f['frame_id'])
    return out

def _clip(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return lo

def speech_records(transcript: dict, duration: float, stage_key_: str = '',
                   cfg: EvidenceConfig = None) -> list:
    """transcript.segments[] -> utterance records. Word timings ride along."""
    cfg = cfg or P5.evidence
    out = []
    if not transcript:
        return out
    src = transcript.get('backend') or 'asr'
    for seg in transcript.get('segments', []) or []:
        text = (seg.get('text') or '').strip()
        if not text:
            continue
        s = _clip(seg.get('start', 0.0), 0.0, duration or 1e9)
        e = _clip(seg.get('end', s), 0.0, duration or 1e9)
        if e < s:
            s, e = e, s
        words = [{'word': (w.get('word') or w.get('text') or '').strip(),
                  'start': _clip(w.get('start', s), 0.0, duration or 1e9),
                  'end': _clip(w.get('end', e), 0.0, duration or 1e9)}
                 for w in (seg.get('words') or [])]
        rec = EvidenceRecord(
            id=evidence_id('speech', 'utterance', s, text),
            modality='speech', type='utterance',
            start_seconds=round(s, 3), end_seconds=round(e, 3),
            description=text,
            # NEGATIVE, and not a probability. The kind says so.
            confidence=seg.get('avg_logprob'),
            confidence_kind='asr_logprob',
            start_tolerance_seconds=cfg.word_tolerance_seconds,
            end_tolerance_seconds=cfg.word_tolerance_seconds,
            time_tolerance_seconds=cfg.word_tolerance_seconds,
            satisfies_modes=modes_for('speech'),
            raw_text=text,
            norm_text=(text or '').lower().strip(),
            source=src, source_stage_key=stage_key_,
            source_id=f"seg_{seg.get('id', len(out))}",
            words=words,
        )
        out.append(rec)
    return out

def ocr_records(ocr: dict, manifest: dict, duration: float, stage_key_: str = '',
                cfg: EvidenceConfig = None) -> list:
    """ocr.intervals[] -> on_screen_text records, carrying independence."""
    cfg = cfg or P5.evidence
    out = []
    if not ocr:
        return out
    # the frames OCR actually ran on, not the ones the dedupe skipped
    ft = examined_frame_times(ocr, manifest, 'ocr')
    approx = _approx_frames(manifest, ocr)
    src = ocr.get('backend') or 'ocr'
    for iv in ocr.get('intervals', []) or []:
        text = (iv.get('text') or '').strip()
        s = _clip(iv.get('first_seen', 0.0), 0.0, duration or 1e9)
        e = _clip(iv.get('last_seen', s), 0.0, duration or 1e9)
        if e < s:
            s, e = e, s
        indep = iv.get('independence') or (
            'derived_from_speech' if iv.get('derived_from_speech') else 'unknown')
        is_approx = bool(approx & set(iv.get('frame_ids') or []))
        _st, _et, _wt = span_tolerance('ocr', ft, s, e, is_approx, cfg=cfg)
        rec = EvidenceRecord(
            id=evidence_id('ocr', 'on_screen_text', s, text),
            modality='ocr', type='on_screen_text',
            start_seconds=round(s, 3), end_seconds=round(e, 3),
            description=text,
            confidence=iv.get('max_confidence'),
            confidence_kind='ocr_recognition',
            start_tolerance_seconds=_st, end_tolerance_seconds=_et,
            time_tolerance_seconds=_wt,
            is_approximate_ts=is_approx,
            satisfies_modes=modes_for('ocr', indep),
            raw_text=text, norm_text=iv.get('norm_text') or text.lower(),
            bbox=iv.get('bbox'), independence=indep,
            source=src, source_stage_key=stage_key_,
            source_id=iv.get('id', ''),
            frame_ids=list(iv.get('frame_ids') or []),
        )
        if iv.get('low_confidence'):
            rec.flags.append('LOW_OCR_CONFIDENCE')
        if iv.get('single_sighting'):
            rec.flags.append('SINGLE_SIGHTING')
        if iv.get('growing'):
            rec.flags.append('REVEALED_PROGRESSIVELY')
        if not rec.satisfies_modes:
            rec.flags.append('SATISFIES_NOTHING:unreadable')
        out.append(rec)
    return out

def visual_records(visual: dict, manifest: dict, duration: float, stage_key_: str = '',
                   cfg: EvidenceConfig = None) -> list:
    """visual.events[] -> records, keeping Phase 3's own closed event type."""
    cfg = cfg or P5.evidence
    out = []
    if not visual:
        return out
    # the 12 frames the VLM was shown, not the 96 Phase 1 extracted
    ft = examined_frame_times(visual, manifest, 'visual')
    approx = _approx_frames(manifest, visual)
    # Phase 3 writes {'model': model_id, 'model_class': ..., 'quantization': ...}.
    # Reading 'model_id' here returned None on every real artifact, so every
    # visual record was sourced to the literal 'vlm' and the evidence could not
    # say which model produced it. Phase 3's own accessor is
    # ev.model.get('model', 'qwen3-vl'); mirror it rather than inventing a key.
    src = (visual.get('model') or {}).get('model') or 'vlm'
    for ev in visual.get('events', []) or []:
        etype = ev.get('type') or 'other'
        if etype not in EVIDENCE_TYPES:
            etype = 'other'
        s = _clip(ev.get('start_seconds', 0.0), 0.0, duration or 1e9)
        e = _clip(ev.get('end_seconds', s), 0.0, duration or 1e9)
        if e < s:
            s, e = e, s
        desc = (ev.get('description') or '').strip()
        is_approx = bool(approx & set(ev.get('frame_ids') or []))
        unreliable = bool(ev.get('timestamp_unreliable'))
        _st, _et, _wt = span_tolerance('visual', ft, s, e, is_approx, unreliable, cfg)
        rec = EvidenceRecord(
            id=evidence_id('visual', etype, s, desc),
            modality='visual', type=etype,
            start_seconds=round(s, 3), end_seconds=round(e, 3),
            description=desc,
            # A model grading itself. plan.md §5.4: a weak ordinal signal at best.
            confidence=ev.get('confidence'),
            confidence_kind='vlm_self_report',
            start_tolerance_seconds=_st, end_tolerance_seconds=_et,
            time_tolerance_seconds=_wt,
            is_approximate_ts=is_approx,
            timestamp_unreliable=unreliable,
            satisfies_modes=modes_for('visual'),
            raw_text=desc, norm_text=desc.lower(),
            source=src, source_stage_key=stage_key_,
            source_id=ev.get('id', ''),
            frame_ids=list(ev.get('frame_ids') or []),
        )
        if ev.get('action'):
            rec.flags.append(f"ACTION:{ev['action']}")
        for f in (ev.get('flags') or []):
            rec.flags.append(str(f))
        if ev.get('objects'):
            rec.flags.append('OBJECTS:' + ','.join(str(o) for o in ev['objects'][:4]))
        out.append(rec)
    return out

def metadata_records(meta: dict, scenes: dict, duration: float,
                     cfg: EvidenceConfig = None) -> list:
    """Scene cuts and the video itself. Cheap, and Phase 6 asks for cut density."""
    cfg = cfg or P5.evidence
    out = []
    cuts = (scenes or {}).get('cut_times') or []
    for i, t in enumerate(cuts):
        try:
            tt = _clip(t, 0.0, duration or 1e9)
        except Exception:
            continue
        out.append(EvidenceRecord(
            id=evidence_id('metadata', 'scene_cut', tt, f'cut{i}'),
            modality='metadata', type='scene_cut',
            start_seconds=round(tt, 3), end_seconds=round(tt, 3),
            description=f'scene cut {i + 1}',
            confidence_kind='none',
            start_tolerance_seconds=cfg.min_tolerance_seconds,
            end_tolerance_seconds=cfg.min_tolerance_seconds,
            time_tolerance_seconds=cfg.min_tolerance_seconds,
            satisfies_modes=modes_for('metadata'),
            source='scene_detector', source_id=f'cut_{i:03d}'))
    if meta:
        out.append(EvidenceRecord(
            id=evidence_id('metadata', 'video_meta', 0.0, 'video'),
            modality='metadata', type='video_meta',
            start_seconds=0.0, end_seconds=round(float(duration or 0.0), 3),
            description=f"{meta.get('width')}x{meta.get('height')}, "
                        f"{round(float(duration or 0), 2)}s",
            confidence_kind='none',
            start_tolerance_seconds=cfg.min_tolerance_seconds,
            end_tolerance_seconds=cfg.min_tolerance_seconds,
            time_tolerance_seconds=cfg.min_tolerance_seconds,
            satisfies_modes=modes_for('metadata'),
            source='ffprobe', source_id='video_meta'))
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 223: print('§54 normalisers loaded: speech | ocr | visual | metadata')
