"""The orchestrator. A direct translation of the notebook's §13.x / §30.5 / §90.

PARITY IS THE POINT
-------------------
Every call below appears in the notebook, in this order, with these arguments.
Where the notebook prints a table, this records a field instead; where the
notebook mutates a global, this passes a value. Nothing else differs, and any
change that is not a pure print/plot removal is marked  # DIFFERS  with a
reason.

Read alongside `Phase 7/phases_1_to_7_BATCH.ipynb` cells 50, 51, 85 and 147.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Optional

from app.parallel import run_parallel
from auditor import runtime

log = logging.getLogger('audit.pipeline')

ProgressFn = Callable[[str, str], None]        # (phase, detail) -> None


class PhaseError(RuntimeError):
    """A phase failed. Carries which one, so the API can say so."""

    def __init__(self, phase: str, message: str, *,
                 video: Optional[str] = None):
        super().__init__(message)
        self.phase = phase
        self.video = video


def _noop(phase: str, detail: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Phases 1-3: multi-video by construction. Models load ONCE per batch.
# ---------------------------------------------------------------------------
def run_preprocess(force: bool = False, progress: ProgressFn = _noop,
                   workers: int = 1) -> dict:
    """Notebook cell 50. ffprobe -> preflight -> scan -> scenes -> sample ->
    decode frames -> extract audio -> manifest, for every video in the inbox.

    PARALLEL ACROSS VIDEOS when workers > 1, and this is the one stage where
    that is both safe and worth doing. It is the CPU hot spot (ffmpeg/PyAV
    decode), each video is independent, the work is content-addressed, and
    every video writes its own artifacts/<video_hash>/<plan_hash>/ directory
    -- so there is nothing to race on.

    What changes vs `preprocess_folder`: the ORDER rows complete in, and the
    batch log it writes to runs/. What does not change: the manifest, the
    frames, the audio, or any stage key. workers=1 calls preprocess_folder
    itself, so sequential is the notebook's code path exactly, not an
    imitation of it.
    """
    ns = runtime.load()
    DIRS, CFG = ns['DIRS'], ns['CFG']
    suffixes = sorted(ns['VIDEO_SUFFIXES'])
    # Both cases, because glob is case-sensitive on Linux and a file arriving
    # as clip.MOV would never get a manifest and would be silently missing.
    patterns = (tuple(f'*{s}' for s in suffixes)
                + tuple(f'*{s.upper()}' for s in suffixes))
    progress('phase1', 'decoding and sampling')
    t0 = time.time()

    if workers <= 1:
        df = ns['preprocess_folder'](DIRS['inbox'], cfg=CFG,
                                     patterns=patterns, force=force)
        rows = df.to_dict('records') if df is not None else []
    else:
        paths = sorted({p for pat in patterns
                        for p in DIRS['inbox'].glob(pat)})

        def _one(p: Path) -> dict:
            t = time.time()
            r = ns['preprocess_video'](p, cfg=CFG, force=force, verbose=False)
            row = {'file': p.name, 'status': r.status,
                   'wall_s': round(time.time() - t, 2),
                   'cache': 'HIT' if r.cache_hit else 'miss'}
            if r.status == 'OK' and r.manifest:
                m = r.manifest
                row.update({
                    'duration_s': round(m['media']['duration_seconds'], 2),
                    'frames': m['sampling']['frames_extracted'],
                    'audio': m['audio']['has_audio']})
            else:
                row['error'] = r.error
            return row

        rows = run_parallel(
            paths, _one, workers=workers, label='decode',
            # One unreadable file must not cost the other nine, exactly as
            # preprocess_folder's own try/except intends.
            on_error=lambda p, e: {'file': p.name, 'status': 'EXCEPTION',
                                   'error': f'{type(e).__name__}: {e}'})
        log.info('phase1: %d video(s) on %d worker(s) in %.1fs',
                 len(rows), workers, time.time() - t0)

    # ---- reconciliation, exactly as cell 50 does it ----------------------
    # discover_videos() reads MANIFESTS, not the inbox. A video that failed to
    # preprocess is simply absent downstream, so a batch would quietly report
    # on nine of ten videos.
    inbox = sorted(f for f in DIRS['inbox'].iterdir()
                   if f.is_file() and f.suffix.lower() in ns['VIDEO_SUFFIXES'])
    have = {v.get('source') for v in ns['discover_videos']()}
    lost = [f.name for f in inbox if f.name not in have]
    if lost:
        log.warning('phase1: %d of %d video(s) did not preprocess: %s',
                    len(lost), len(inbox), lost)
    return {'rows': rows, 'in_inbox': len(inbox), 'lost': lost,
            'seconds': round(time.time() - t0, 2)}


def run_text_stages(force: bool = False,
                    progress: ProgressFn = _noop) -> dict:
    """Notebook cell 51. ASR for everything, free the model, then OCR for
    everything. The load-once-then-loop order is deliberate and load-bearing:
    a per-video load would pay the ~50 s Whisper start-up N times."""
    ns = runtime.load()
    progress('phase2', 'transcribing and reading on-screen text')
    t0 = time.time()
    videos = ns['discover_videos']()
    if not videos:
        raise PhaseError('phase2', 'no video has a Phase 1 manifest')
    df = ns['process_all'](videos, cfg=ns['P2'], force=force)
    rows = df.to_dict('records') if df is not None else []
    failed = [r for r in rows if r.get('status') not in (None, 'OK')]
    if failed:
        log.warning('phase2: %d video(s) failed ASR/OCR; their reports will '
                    'rest on vision alone', len(failed))
    return {'rows': rows, 'failed': len(failed),
            'seconds': round(time.time() - t0, 2)}


def run_vision(force: bool = False, progress: ProgressFn = _noop) -> dict:
    """Notebook cell 85 (§30.5). The expensive stage: one hosted vision pass
    per NEW video, backend loaded once for the batch."""
    ns = runtime.load()
    progress('phase3', 'describing frames')
    t0 = time.time()
    videos = ns['discover_videos']()          # UNIQUE: one manifest per video

    # §30.5 also drops the notebook's own OCR fixture here. It cannot appear
    # in an API job (nothing writes it), but the guard is free and keeps the
    # two paths honest with each other.
    fixture = str(ns.get('TEST_VIDEO_NAME') or 'test_changing_text.mp4')
    videos = [v for v in videos if v.get('source') != fixture]

    df = ns['run_vision_all'](videos, ns['P3'], force=force)
    rows = df.to_dict('records') if df is not None else []
    novis = [r for r in rows if r.get('status') != 'OK']
    for r in novis:
        log.warning('phase3: %s -> %s (no visual evidence; visual '
                    'requirements will read UNCERTAIN, not FAIL)',
                    r.get('source'), r.get('status'))
    return {'rows': rows, 'without_vision': len(novis),
            'seconds': round(time.time() - t0, 2)}


# ---------------------------------------------------------------------------
# Phases 5-7: per video. This is cell 147 (§90), field for field.
# ---------------------------------------------------------------------------
def _verdict_out(v: dict) -> dict:
    """Notebook verdict -> VerdictOut, translating the two renamed fields.

    The notebook writes `reason` and `layer`; the schema declares `rationale`
    and `decided_by`. Pydantic drops an unmatched key SILENTLY, so every API
    response carried `rationale: ""` and `decided_by: null` on all 28 verdicts
    while the HTML report printed both from the same data -- the API looked
    like the audit had no explanation for anything it decided.

    Exactly the trap the modality_health comment above already describes. The
    notebook's names are not changed: renaming there would ripple through the
    cached artifacts and the report. The translation belongs at the API
    boundary, which is what this layer is for.
    """
    return {**v,
            'rationale': v.get('rationale') or v.get('reason') or '',
            'decided_by': v.get('decided_by') or v.get('layer'),
            # `group` is the notebook's name; the schema says `group_id`. Found
            # by auditing every field of every nested model against a live
            # response instead of reading one by hand -- which is how the two
            # above were found, one at a time.
            'group_id': v.get('group_id') or v.get('group')}


def audit_one(video: dict, brief: dict, *, force: bool = False,
              progress: ProgressFn = _noop) -> dict:
    """Evidence -> verdicts -> score -> report, for one video.

    Returns the same row §90 builds, plus the full verdict list and the
    recommendations, which §90 only wrote into the HTML.
    """
    ns = runtime.load()
    DIRS = ns['DIRS']
    P5, P6, P7 = ns['P5'], ns['P6'], ns['P7']
    vh = video['video_hash']
    name = video.get('source') or video.get('video_id') or vh[:12]
    row: dict[str, Any] = {'video_hash': vh, 'source': name,
                           'video_id': video.get('video_id') or vh[:16],
                           'status': 'ok'}

    # ---- Phase 5: evidence, resolved by EXACT stage key -------------------
    progress('phase5', name)
    vd = DIRS['artifacts'] / vh
    exp = ns['expected_stage_keys'](video)
    tr, _, _ = ns['select_artifact'](vd, 'transcript', exp.get('transcript'))
    oc, _, _ = ns['select_artifact'](vd, 'ocr', exp.get('ocr'))
    vi, _vip, vih = ns['select_artifact'](vd, 'visual', exp.get('visual'))
    # "using the newest of 1" means the visual artifact matches no key the
    # CURRENT config accepts. The result stands; what is lost is the guarantee
    # that the vision evidence came from the config this report claims.
    row['visual_stale'] = (vih not in (exp.get('visual') or [])
                           and vih != 'missing')
    row['visual_missing'] = (vih == 'missing')

    ev = ns['build_evidence'](video, tr, oc, vi, P5, verbose=False)
    recs = ns['load_records'](ev)
    row['evidence_records'] = ev['stats']['records']

    health = ((ev.get('stats') or {}).get('modality_health')
              or ev.get('modality_health') or {})
    can_fail = ev.get('can_fail_on') or {}
    # THE SCHEMA'S NAMES, not convenient local ones. VideoResultOut declares
    # `modality_health`, `evidence_records` and `talking_points_*`; a row key
    # that does not match is DROPPED by pydantic without a word, and a live
    # run returned null for all of them while the values sat right here.
    row['modality_health'] = {
        k: {'ran': (health.get(k) or {}).get('ran'),
            'absent': (health.get(k) or {}).get('absent'),
            'degraded': (health.get(k) or {}).get('degraded'),
            'reason': (health.get(k) or {}).get('reason')}
        for k in ('speech', 'ocr', 'visual') if k in health}
    row['can_fail_on'] = dict(can_fail)
    blocked = [m for m, ok in can_fail.items() if ok is False]
    if blocked:
        log.info('%s: channels that cannot assert an absence: %s -> those '
                 'requirements become UNCERTAIN, not FAIL',
                 name, ', '.join(sorted(blocked)))

    # ---- Phase 6: the audit -----------------------------------------------
    progress('phase6', name)
    res = ns['audit_video'](video, ev, brief, P6, verbose=False, force=force)
    # (see _verdict_out below -- the same naming trap as modality_health above,
    #  three more fields, caught by reading a live response rather than a test)
    if res.get('status') == 'BRIEF_NOT_USABLE':
        raise PhaseError('phase6', 'the compiled brief is not approved, so '
                                   'requirements_for_audit() refused it',
                         video=name)
    row['standing'] = (res.get('standing') or {}).get('standing')

    ca = res.get('creative_angle') or {}
    _fit = [f for f in (ca.get('concept_fit') or []) if isinstance(f, dict)]
    # "Which of the brief's angles is this video" -- the single question the
    # split exists to answer, computed once here rather than by every caller.
    _dom = (max(_fit, key=lambda f: float(f.get('percent') or 0)).get('angle')
            if _fit else None)
    row['creative_angle'] = {
        'angle': ca.get('angle'),
        'nearest_brief_concept': ca.get('nearest_brief_concept'),
        'brief_concepts': list(ca.get('brief_concepts') or []),
        'named_angles': list(ca.get('named_angles') or []),
        'concept_fit': _fit,
        'dominant_angle': _dom,
        # 'document' is the correct path (the brief's own sub-headings).
        # Anything else on a brief that names its angles means a cached audit
        # from before that path existed -- surfaced rather than left to look
        # like the extraction is broken.
        'angles_source': ca.get('angles_source'),
        'flags': [str(f) for f in (ca.get('flags') or [])],
    }

    # Which item off each MENU she actually took. The group collapse already
    # decided it; this records the winner per group.
    chosen: dict[str, Any] = {}
    for v2 in (res.get('verdicts') or []):
        sel = next((str(f) for f in (v2.get('flags') or [])
                    if str(f).startswith('GROUP_SELECTED:')), None)
        if not sel:
            continue
        gl = (v2.get('group_label')
              or sel.split(':', 1)[1].split('(')[0].strip())
        chosen[str(gl)] = {
            'option': v2.get('requirement_label') or v2.get('requirement_id'),
            'status': v2.get('status'), 'alignment': v2.get('alignment')}
    row['chosen_options'] = chosen
    row['verdicts'] = [_verdict_out(v) for v in (res.get('verdicts') or [])]
    # The audit artifact knows how long the video is; the row did not carry it,
    # so every API response reported duration_s: null while the HTML report
    # printed 54.2s from the same data.
    if res.get('duration_seconds') is not None:
        row['duration_s'] = round(float(res['duration_seconds']), 2)
    row['verdict_mix'] = dict(
        Counter(v.get('status') for v in (res.get('verdicts') or [])))

    # ---- Phase 7: score, advice, figures, report --------------------------
    progress('phase7', name)
    sc = ns['score_audit'](res, brief, P7, verbose=False, force=force)
    rec = ns['evaluate_recommendations'](res, brief, sc, recs, cfg=P7,
                                         verbose=False)
    fg = ns['build_figures'](sc, res, recs, cfg=P7)
    rp = ns['write_report'](video, res, brief, sc, recs, rec, fg, P7,
                            verbose=False)

    s = sc['score']
    tp = ns['talking_point_coverage'](res, brief)
    row.update({
        'score': {
            'headline': s.get('headline'),
            'literal_headline': s.get('literal_headline'),
            'status_band': s.get('status_band'),
            'coverage': s.get('coverage'),
            'scoring_units': s.get('scoring_units'),
            'credited_in_substance': s.get('credited_in_substance'),
            'band_low': s.get('band_low'), 'band_high': s.get('band_high'),
            'band_basis': s.get('band_basis'),
            'lead_with_band': bool(s.get('lead_with_band')),
        },
        'talking_points_covered': len(tp['covered']),
        'talking_points_total': tp['total'],
        # write_report returns BOTH 'html_path' (the file) and 'html' (the
        # whole document as a string). Keep the PATH.
        'report_html': str((rp or {}).get('html_path') or ''),
        'report_json': str((rp or {}).get('json_path') or ''),
        'recommendations': list((rec or {}).get('recommendations') or []),
    })

    # ---- WHY, when a number needs explaining ------------------------------
    # A score of 0 with standing=None is three situations wearing one face: no
    # speech to judge, a failed model call, or a video that genuinely did none
    # of it. The modules record which; surface it rather than leaving a bare 0.
    sflags = [str(f) for f in ((res.get('standing') or {}).get('flags') or [])]
    aflags = [str(f) for f in (ca.get('flags') or [])]
    why = []
    if row['standing'] is None:
        why.append('standing NOT judged: '
                   + (', '.join(sflags) if sflags else 'no reason recorded'))
    if row['creative_angle']['angle'] is None:
        why.append('angle NOT judged: '
                   + (', '.join(aflags) if aflags else 'no reason recorded'))
    if any('MODEL_FAILED' in f for f in sflags + aflags):
        why.append('A MODEL CALL FAILED -- a pipeline problem, not a finding '
                   'about the video.')
        row['status'] = 'module_failed'
    row['notes'] = why
    for w in why:
        log.warning('%s: %s', name, w)
    return row


def audit_all(brief: dict, *, max_videos: int, force: bool = False,
              progress: ProgressFn = _noop,
              deadline: Optional[float] = None) -> list[dict]:
    """Cell 147's loop. One bad video must not cost the other nine.

    SEQUENTIAL, and not an oversight. Phase 6 makes several model calls per
    video -- L3, hook, claims, angle, standing -- and those are rate-limited
    per model per minute. Fanning them out converts a slow job into a failed
    one; AUDITOR_AUDIT_WORKERS exists for a paid tier and defaults to 1.
    """
    ns = runtime.load()
    videos = ns['discover_videos']()
    fixture = str(ns.get('TEST_VIDEO_NAME') or 'test_changing_text.mp4')
    videos = [v for v in videos if v.get('source') != fixture]
    if len(videos) > max_videos:
        log.warning('%d videos found; capping at %d', len(videos), max_videos)
        videos = videos[:max_videos]

    out = []
    for n, v in enumerate(videos, 1):
        name = v.get('source') or v['video_hash'][:12]
        if deadline and time.time() > deadline:
            # Stop cleanly and SAY which videos were not reached, rather than
            # returning a short list that looks complete.
            skipped = [x.get('source') or x['video_hash'][:12]
                       for x in videos[n - 1:]]
            log.error('job deadline reached; %d video(s) not audited: %s',
                      len(skipped), skipped)
            for s_name, x in zip(skipped, videos[n - 1:]):
                out.append({
                    'video_hash': x['video_hash'], 'source': s_name,
                    'video_id': x.get('video_id') or x['video_hash'][:16],
                    'status': 'SKIPPED_DEADLINE',
                    'error': 'the job ran out of time before this video was '
                             'audited; its Phase 1-3 artifacts are cached, so '
                             'a re-run starts from here',
                    'phase': 'phase5-7'})
            break
        log.info('[%d/%d] auditing %s', n, len(videos), name)
        try:
            out.append(audit_one(v, brief, force=force, progress=progress))
        except Exception as exc:
            log.exception('[%d/%d] %s FAILED', n, len(videos), name)
            out.append({
                'video_hash': v['video_hash'], 'source': name,
                'video_id': v.get('video_id') or v['video_hash'][:16],
                'status': f'{type(exc).__name__}: {exc}'[:200],
                'error': f'{type(exc).__name__}: {exc}'[:400],
                'phase': getattr(exc, 'phase', 'phase5-7'),
            })
    return out


def angle_distribution(rows: list[dict]) -> list[dict]:
    """Across the batch: how many videos landed on each named angle.

    This is §91's table. It only exists across a batch -- "we offered four
    concepts and every creator used the same one" is a finding about the
    BRIEF, and it is invisible in any single report.
    """
    named: list[str] = []
    for r in rows:
        for a in (r.get('creative_angle') or {}).get('named_angles') or []:
            if a not in named:
                named.append(a)
    if not named:
        return []
    out = []
    for angle in named:
        videos, total, dominant = [], 0.0, []
        for r in rows:
            ca = r.get('creative_angle') or {}
            for fit in ca.get('concept_fit') or []:
                if str(fit.get('angle')) == angle and fit.get('percent'):
                    videos.append(r.get('source'))
                    total += float(fit['percent'])
            if ca.get('dominant_angle') == angle:
                dominant.append(r.get('source'))
        out.append({
            'angle': angle,
            'videos': len(videos),
            # How many videos this angle is the PRIMARY one for -- the answer
            # to "we offered three concepts, which did creators actually
            # take", which no single report can show.
            'dominant_for': len(dominant),
            'mean_percent': round(total / len(videos), 1) if videos else 0.0,
            'sources': videos,
            'unused': not videos,
        })
    return sorted(out, key=lambda d: (-d['dominant_for'], -d['videos']))
