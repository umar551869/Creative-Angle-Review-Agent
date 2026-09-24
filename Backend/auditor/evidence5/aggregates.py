"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 114.
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
PRODUCT_TYPES = ('product_visible', 'product_held', 'product_opened',
                 'product_applied', 'demonstration')

def derive_aggregates(records: list, duration: float, cfg: EvidenceConfig = None) -> dict:
    """Computed once here; Phase 6 asks for these on nearly every requirement."""
    cfg = cfg or P5.evidence
    prod = [r for r in records if r.modality == 'visual' and r.type in PRODUCT_TYPES]
    spans = _merge_spans([[r.start_seconds, r.end_seconds] for r in prod],
                         gap=cfg.merge_gap_seconds)
    total = sum(b - a for a, b in spans)
    longest = max((b - a for a, b in spans), default=0.0)

    first = min((r for r in prod), key=lambda r: r.start_seconds, default=None)
    last = max((r for r in prod), key=lambda r: r.end_seconds, default=None)

    demos = {}
    for r in records:
        if r.modality != 'visual':
            continue
        for f in r.flags:
            if f.startswith('ACTION:'):
                demos.setdefault(f[7:], []).append([r.start_seconds, r.end_seconds])
    demos = {k: _merge_spans(v, cfg.merge_gap_seconds) for k, v in demos.items()}

    cuts = [r for r in records if r.type == 'scene_cut']
    sp = [r for r in records if r.modality == 'speech']
    # union, not sum -- see modality_health()
    spoken = sum(b - a for a, b in
                 _merge_spans([[r.start_seconds, r.end_seconds] for r in sp]))

    return {
        # first_seen carries its OWN tolerance: a deadline check on a bare number
        # is where a confident wrong answer comes from.
        'product_first_seen': (round(first.start_seconds, 3) if first else None),
        'product_first_seen_tolerance': (first.time_tolerance_seconds if first else None),
        'product_last_seen': (round(last.end_seconds, 3) if last else None),
        'product_visible_seconds': round(total, 3),
        'product_longest_interval': round(longest, 3),
        'product_intervals': [[round(a, 3), round(b, 3)] for a, b in spans],
        'demonstration_intervals': demos,
        'cut_count': len(cuts),
        'cut_density_per_second': (round(len(cuts) / duration, 4) if duration else None),
        'speech_seconds': round(spoken, 3),
        'speech_ratio': (round(spoken / duration, 3) if duration else None),
        'records_by_modality': {m: sum(1 for r in records if r.modality == m)
                                for m in MODALITIES},
        'records_by_type': {t: sum(1 for r in records if r.type == t)
                            for t in sorted({r.type for r in records})},
    }

def _in_window(records: list, t0: float, t1: float, modality: str = None,
               types: tuple = None, mode: str = None, slack: float = 0.0) -> list:
    out = []
    for r in records:
        if modality and r.modality != modality:
            continue
        if types and r.type not in types:
            continue
        if mode and not r.can_satisfy(mode):
            continue
        if r.overlaps(t0, t1, slack):
            out.append(r)
    return sorted(out, key=lambda r: r.start_seconds)

def speech_in_window(records: list, t0: float, t1: float, slack: float = 0.0) -> list:
    return _in_window(records, t0, t1, modality='speech', slack=slack)

def text_in_window(records: list, t0: float, t1: float, mode: str = None,
                   slack: float = 0.0) -> list:
    """On-screen text. Pass mode='ocr_only' to get ONLY independent intervals."""
    return _in_window(records, t0, t1, modality='ocr', mode=mode, slack=slack)

def visual_in_window(records: list, t0: float, t1: float, types: tuple = None,
                     slack: float = 0.0) -> list:
    return _in_window(records, t0, t1, modality='visual', types=types, slack=slack)

def words_for(record) -> list:
    """Word timings for one utterance. They live ON the record, so this works
    after a cache hit and cannot be clobbered by building another video."""
    return list(getattr(record, 'words', None) or [])

def words_in_window(records: list, t0: float, t1: float) -> list:
    """Every spoken word overlapping [t0, t1] -- what a phrase match needs."""
    out = []
    for r in records:
        if r.modality != 'speech':
            continue
        for w in (r.words or []):
            try:
                ws, we = float(w.get('start', 0.0)), float(w.get('end', 0.0))
            except (TypeError, ValueError):
                continue
            if ws <= t1 and we >= t0:
                out.append(dict(w, record_id=r.id))
    return sorted(out, key=lambda w: w.get('start', 0.0))

def coverage_in_window(coverage: dict, t0: float, t1: float, modality: str,
                       cfg: EvidenceConfig = None) -> float:
    """Fraction of [t0,t1] where this modality produced ANY evidence."""
    cfg = cfg or P5.evidence
    c = (coverage or {}).get(modality) or {}
    gaps = c.get('gaps') or []
    span = max(0.0, t1 - t0)
    if span <= 0:
        return 1.0
    uncovered = 0.0
    for a, b in gaps:
        uncovered += max(0.0, min(t1, b) - max(t0, a))
    return round(max(0.0, 1.0 - uncovered / span), 3)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 125: print('§58 aggregates and accessors loaded.')
