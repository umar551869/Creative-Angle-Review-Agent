"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 25.
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
def frame_gap_tolerance(manifest: dict, cfg: DedupeConfig) -> dict:
    """
    How large a gap may separate two detections of the SAME text before we call
    them two separate appearances?

    It MUST be derived from the SPARSEST part of the sampling, not the median.
    Phase 1's sampler is deliberately non-uniform: ~0.25s inside the hook and CTA
    windows, ~0.6s through the middle. Half the frame gaps are therefore tiny, so
    a median-based tolerance is dominated by the dense windows -- and in the
    sparse middle EVERY consecutive frame exceeds it. Each detection then becomes
    its own interval and dedupe does almost nothing.

    Using the WIDEST gap guarantees that two adjacent sampled frames always merge,
    which is the actual requirement. The ceiling stops one pathological jump
    (a long static stretch) from making the tolerance meaningless.
    """
    ts = sorted(f['actual_time'] for f in manifest['frames'])
    if len(ts) < 2:
        return {'max_gap': 1.0, 'median_spacing': 0.0, 'widest_spacing': 0.0}
    diffs = np.diff(ts)
    widest = float(np.max(diffs))
    max_gap = min(max(cfg.gap_tolerance_multiplier * widest, 0.35), cfg.max_gap_ceiling_s)
    return {'max_gap': round(max_gap, 3),
            'median_spacing': round(float(np.median(diffs)), 3),
            'widest_spacing': round(widest, 3)}

def bbox_containment(inner: list, outer: list) -> float:
    """Fraction of `inner`'s area that lies inside `outer`."""
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area = max(1e-6, (inner[2] - inner[0]) * (inner[3] - inner[1]))
    return inter / area

def _can_merge(det: dict, iv: dict, cfg: DedupeConfig) -> tuple:
    """
    Should this detection extend this interval? Returns (ok, kind).
      kind='same'    -- the same text, jitter-tolerant, in the same place
      kind='growing' -- a caption being revealed word by word
    """
    a, b = det['norm_text'], iv['norm_text']

    # 0. numbers differ -> two different pieces of information, never one interval
    if cfg.digit_guard and digits_conflict(a, b):
        return False, None

    # 1. same text in the same place
    if (robust_ratio(a, b) >= cfg.text_similarity_threshold
            and bbox_iou(det['bbox'], iv['bbox']) >= cfg.bbox_iou_threshold):
        return True, 'same'

    # 2. growing caption: the shorter is a prefix of the longer, and the shorter's
    #    box sits inside the longer's. (IoU fails here: the box widens per word.)
    if cfg.merge_growing_text:
        if len(despace(a)) <= len(despace(b)):
            short_t, long_t, short_box, long_box = a, b, det['bbox'], iv['bbox']
        else:
            short_t, long_t, short_box, long_box = b, a, iv['bbox'], det['bbox']
        if (is_growing_text(short_t, long_t)
                and bbox_containment(short_box, long_box) >= cfg.growing_containment_min):
            return True, 'growing'

    return False, None

def build_text_intervals(detections: list, manifest: dict, cfg: DedupeConfig) -> list:
    """Per-frame detections -> temporal intervals. The core of section 8."""
    if not detections:
        return []

    tol = frame_gap_tolerance(manifest, cfg)
    max_gap = tol['max_gap']

    dets = sorted(detections, key=lambda d: (d['timestamp'], -d['confidence']))
    open_intervals, closed = [], []

    for det in dets:
        placed = False
        for iv in open_intervals:
            if det['timestamp'] - iv['last_seen'] > max_gap:
                continue
            ok, kind = _can_merge(det, iv, cfg)
            if not ok:
                continue
            iv['last_seen'] = det['timestamp']
            iv['detections'].append(det)
            if kind == 'growing':
                # keep the FULLY revealed caption, and the box that covers it
                iv['growing'] = True
                if len(despace(det['norm_text'])) > len(despace(iv['norm_text'])):
                    iv['text'], iv['norm_text'] = det['text'], det['norm_text']
                iv['bbox'] = [min(iv['bbox'][0], det['bbox'][0]), min(iv['bbox'][1], det['bbox'][1]),
                              max(iv['bbox'][2], det['bbox'][2]), max(iv['bbox'][3], det['bbox'][3])]
                iv['max_confidence'] = max(iv['max_confidence'], det['confidence'])
            elif det['confidence'] > iv['max_confidence']:
                iv['max_confidence'] = det['confidence']
                # never let a higher-confidence PARTIAL replace a revealed caption
                if (not iv.get('growing')
                        or len(despace(det['norm_text'])) >= len(despace(iv['norm_text']))):
                    iv['text'], iv['norm_text'], iv['bbox'] = det['text'], det['norm_text'], det['bbox']
            placed = True
            break
        if not placed:
            open_intervals.append({
                'text': det['text'], 'norm_text': det['norm_text'],
                'first_seen': det['timestamp'], 'last_seen': det['timestamp'],
                'bbox': det['bbox'], 'max_confidence': det['confidence'],
                'detections': [det],
            })

        # close intervals that can no longer be extended
        still_open = []
        for iv in open_intervals:
            if det['timestamp'] - iv['last_seen'] > max_gap:
                closed.append(iv)
            else:
                still_open.append(iv)
        open_intervals = still_open

    closed += open_intervals
    closed.sort(key=lambda iv: (iv['first_seen'], iv['bbox'][1]))

    # ---- survival: 2+ sightings, OR one sighting read with high confidence ----
    survivors = []
    for iv in closed:
        n = len(iv['detections'])
        best = max(d['confidence'] for d in iv['detections'])
        if n >= cfg.min_interval_detections or best >= cfg.single_sighting_min_confidence:
            survivors.append(iv)

    out = []
    for i, iv in enumerate(survivors):          # ids numbered AFTER filtering: no gaps
        confs = [d['confidence'] for d in iv['detections']]
        out.append({
            'id': f'ocr_{i:03d}',
            'text': iv['text'],
            'norm_text': iv['norm_text'],
            'first_seen': round(iv['first_seen'], 3),
            'last_seen': round(iv['last_seen'], 3),
            'duration': round(iv['last_seen'] - iv['first_seen'], 3),
            'n_detections': len(iv['detections']),
            'max_confidence': round(max(confs), 4),
            'mean_confidence': round(float(np.mean(confs)), 4),
            'low_confidence': bool(max(confs) < 0.50),
            'bbox': iv['bbox'],
            'frame_ids': [d['frame_id'] for d in iv['detections']],
            'reasons': sorted({d['reason'] for d in iv['detections']}),
            'growing': bool(iv.get('growing', False)),      # revealed word by word
            'single_sighting': len(iv['detections']) == 1,  # kept on confidence alone
            # --- filled in by section 9 --------------------------------------
            # `independence` is the field Phase 6 must read, NOT derived_from_speech.
            #   'unknown'               -> too short to compare; NOT proof of independence
            #   'confirmed_independent' -> compared against speech and genuinely differs
            #   'derived_from_speech'   -> a burned-in caption; NOT independent evidence
            #   'unreadable'            -> OCR returned something that is not words
            'derived_from_speech': False,
            'speech_match_score': None,
            'independence': 'unknown',
            'readable': True,
            'readability': None,
        })
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 171: print('dedupe.py loaded')
