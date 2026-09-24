"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 110.
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
def manifest_frame_times(manifest: dict) -> list:
    """Sorted actual_time of every extracted frame. The sampling grid."""
    ts = []
    for f in (manifest or {}).get('frames', []) or []:
        t = f.get('actual_time')
        if t is not None:
            try:
                ts.append(float(t))
            except (TypeError, ValueError):
                pass
    return sorted(ts)

def examined_frame_times(artifact: dict, manifest: dict, modality: str) -> list:
    """
    The grid the modality ACTUALLY looked at, which is not the plan.

    Two stages examine fewer frames than Phase 1 extracted, for different
    reasons, and both were measured on real artifacts:

      visual  Phase 3's OOM ladder sends a subset. On the 84 s video it sent
              12 of 96 frames. Against the 96-frame plan the first sighting of
              the product reported +-1.37 s, but the model was only shown a
              frame every ~5 s, so +-5 s is the honest number.
      ocr     Phase 2 skips frames it judges duplicates of the previous one.
              On the 28 s text video it ran on 27 of 80 and forced 14 rereads,
              so its worst real gap was 2.83 s against a 0.77 s plan gap.

    A bound like "first seen at 29.0 s" means "absent on the previous frame I
    examined, present on this one". The uncertainty is therefore the spacing of
    the EXAMINED frames. Understating it is the direction that produces
    confident wrong answers, so the examined grid wins and the plan is only the
    fallback for an artifact that does not record what it looked at.
    """
    rows, key = (), 'timestamp'
    if modality == 'visual':
        rows = (artifact or {}).get('frame_table') or ()
    elif modality == 'ocr':
        rows = [r for r in ((artifact or {}).get('per_frame') or ()) if r.get('ocr_run')]
    ts = []
    for r in rows:
        t = r.get(key, r.get('actual_time'))
        if t is None:
            continue
        try:
            ts.append(float(t))
        except (TypeError, ValueError):
            pass
    return sorted(ts) or manifest_frame_times(manifest)

def sampling_tolerance(frame_times: list, t: float, cfg: EvidenceConfig = None) -> float:
    """
    How imprecise is a timestamp that came from SAMPLED frames?

    "First seen at 3.20 s" means: absent on the previous sampled frame, present
    on this one. The true onset is somewhere in between, so the gap BACK to the
    previous sample is the honest bound.

    Computed per timestamp, never as a global average -- Phase 1 samples densely
    in the hook and CTA windows and sparsely in the middle, so one average number
    would be wrong nearly everywhere.
    """
    cfg = cfg or P5.evidence
    if not frame_times:
        return cfg.max_tolerance_seconds
    # The timestamp almost always IS a sampled frame time -- an OCR interval's
    # first_seen is read off a frame. So the neighbour to measure against is the
    # nearest DISTINCT one; using the raw nearest neighbour gives a gap of zero
    # and collapses every tolerance to the floor, which is the same as not
    # having the function at all.
    eps = 1e-9
    i = bisect.bisect_left(frame_times, t)
    j = i
    while j > 0 and frame_times[j - 1] >= t - eps:
        j -= 1
    prev_gap = (t - frame_times[j - 1]) if j > 0 else None
    k = i
    while k < len(frame_times) and frame_times[k] <= t + eps:
        k += 1
    next_gap = (frame_times[k] - t) if k < len(frame_times) else None
    gaps = [g for g in (prev_gap, next_gap) if g is not None and g > eps]
    if not gaps:
        return cfg.max_tolerance_seconds
    # The WIDER neighbour, not the nearer one. A start bound is uncertain back to
    # the previous frame and an end bound forward to the next; one function
    # serves both only if it takes the conservative side. Under-stating
    # uncertainty is the direction that produces confident wrong answers.
    return round(max(cfg.min_tolerance_seconds,
                     min(cfg.max_tolerance_seconds, max(gaps))), 3)

def record_tolerance(modality: str, frame_times: list, start: float,
                     is_approx: bool = False, unreliable: bool = False,
                     cfg: EvidenceConfig = None) -> float:
    """One number Phase 6 can do arithmetic with, per record."""
    cfg = cfg or P5.evidence
    if modality == 'speech':
        tol = cfg.word_tolerance_seconds
    elif modality == 'metadata':
        tol = cfg.min_tolerance_seconds
    else:
        tol = sampling_tolerance(frame_times, start, cfg)
    if is_approx:
        # Phase 1 could not read a true PTS and interpolated it. That is a
        # different kind of wrong from sampling, so the two add rather than
        # one hiding the other.
        tol += cfg.word_tolerance_seconds
    if unreliable:
        # Phase 3 said this bound is not a measurement (a far-out clamp).
        tol = max(tol, cfg.unreliable_tolerance_seconds)
    return round(min(cfg.max_tolerance_seconds, tol), 3)

def _merge_spans(spans: list, gap: float = 0.0) -> list:
    """
    Union of [start, end] spans, merging anything closer than gap.

    Defined here rather than beside the aggregates because §56's speech_ratio
    needs it too -- and a helper used by two cells belongs before both of them,
    not resolved by luck at call time.
    """
    if not spans:
        return []
    spans = sorted([list(s) for s in spans], key=lambda s: s[0])
    out = [spans[0]]
    for s in spans[1:]:
        if s[0] - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], s[1])
        else:
            out.append(s)
    return out

def span_tolerance(modality: str, frame_times: list, start: float, end: float,
                   is_approx: bool = False, unreliable: bool = False,
                   cfg: EvidenceConfig = None) -> tuple:
    """
    (start_tol, end_tol, worst). Each bound measured where it actually sits.

    A record from 1.0 s to 9.0 s on a grid that is dense early and sparse late
    has a precise start and a vague end. Reporting one number for both either
    overstates the start or understates the end, and understating is the
    direction that produces confident wrong answers.
    """
    s = record_tolerance(modality, frame_times, start, is_approx, unreliable, cfg)
    e = record_tolerance(modality, frame_times, end, is_approx, unreliable, cfg)
    return s, e, max(s, e)

def modes_for(modality: str, independence: str = '') -> tuple:
    """
    What can this record legitimately prove?

    The OCR policy is the subtle one and it lives here, once: only a
    confirmed_independent interval can satisfy an ocr_only requirement, because
    a burned-in caption repeating the voiceover is not independent evidence
    (product.md §37), and `unknown` is not proof of anything.
    """
    if modality == 'speech':
        return SPEECH_MODES
    if modality == 'visual':
        return VISUAL_MODES
    if modality == 'ocr':
        return INDEPENDENCE_MODES.get(independence or 'unknown', ('any',))
    return METADATA_MODES


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 173: print('§53 tolerance and mode policy loaded.')
#   line 174: _ft = [0.0, 0.25, 0.5, 2.3, 3.2, 3.45]
#   line 175: for _t in (0.3, 3.2, 5.0):
#   line 178: print(f'  a spoken word                       ->  tolerance {P5.evidence.wor
#   line 180: for _m, _i in (('ocr', 'confirmed_independent'), ('ocr', 'unknown'), ('ocr',
