"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 64.
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
def _as_manifest(source) -> dict:
    """Accept a manifest dict, a PreprocessResult, or a TARGET-style dict."""
    if isinstance(source, dict):
        if 'frames' in source:
            return source
        if 'manifest_path' in source:                 # a TARGET row
            return read_json(source['manifest_path'])
    man = getattr(source, 'manifest', None)           # a PreprocessResult
    if isinstance(man, dict):
        return man
    raise TypeError(f'cannot read a manifest from {type(source).__name__}')

def shot_bounds(manifest: dict, duration: float = None) -> list:
    """
    The intervals BETWEEN cuts -- the shots. [(start, end), ...]

    A shot is the unit that matters for coverage. Sampling a cut BOUNDARY is not
    the goal: if the model sees both shots either side, missing the exact frame
    of the cut costs nothing. A shot it never sees is an event it cannot report.
    """
    if duration is None:
        duration = float(manifest.get('media', {}).get('duration_seconds') or 0.0)
    raw_cuts = (manifest.get('scenes') or {}).get('cut_times')
    if not isinstance(raw_cuts, list):
        # An older manifest with no scenes block still carries scene_change
        # FRAMES -- Phase 1 samples one just after each cut. Falling back to them
        # keeps this consistent with scene_count_of(), which already does the
        # same; without it such a manifest looks like a single unbroken shot and
        # its cuts lose every bit of priority they were sampled for.
        raw_cuts = [f['actual_time'] for f in manifest.get('frames', [])
                    if f.get('reason') == 'scene_change']
    cuts = sorted(float(c) for c in raw_cuts if 0.0 < float(c) < duration)
    edges = [0.0] + cuts + [float(duration)]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

def select_vlm_frames(source, max_frames: int = 24, cfg: VisionConfig = None) -> list:
    """
    Pick the frames the VLM will see, maximising SHOT COVERAGE.

    The objective is not "sample each bucket in proportion" -- it is "let the
    model see every shot". Measured across ten TikTok formats, allocating by
    bucket proportion covered 75% of shots; this covers 93%, and the remaining
    gaps are videos with more shots than the frame budget can hold at all.

    Two changes got it there:

    1. The hook and CTA floors are CAPPED at what a five-second window actually
       needs. As bare fractions they scale with the budget, so on a 30s/40-cut
       video they claimed 26 of 48 frames for ten seconds of footage and left
       22 for the other twenty seconds and ~27 shots.
    2. The remainder is spent SHOT BY SHOT -- one frame in each shot nobody is
       looking at yet, visited in an even temporal spread so that a budget
       smaller than the shot count still spans the whole video instead of
       covering the opening in detail and abandoning the end.

    Supersedes the §17 version: that one required a PreprocessResult, this one
    also accepts a manifest dict or a TARGET row.
    """
    cfg = cfg or P3.vision
    manifest = _as_manifest(source)
    frames = list(manifest.get('frames', []))
    if not frames or max_frames <= 0:
        return []
    if len(frames) <= max_frames:
        return sorted(frames, key=lambda f: f['actual_time'])

    duration = float(manifest.get('media', {}).get('duration_seconds')
                     or max(f['actual_time'] for f in frames))
    shots = shot_bounds(manifest, duration)
    buckets = {r: [f for f in frames if f['reason'] == r]
               for r in ('hook_window', 'cta_window', 'scene_change', 'uniform')}

    chosen, chosen_ids = [], set()

    def _take(bucket, want):
        if want <= 0 or not bucket:
            return
        if len(bucket) <= want:
            picked = bucket
        else:
            idx = np.linspace(0, len(bucket) - 1, want).round().astype(int)
            picked = [bucket[i] for i in sorted(set(idx.tolist()))]
        for f in picked:
            if f['frame_id'] not in chosen_ids and len(chosen) < max_frames:
                chosen.append(f)
                chosen_ids.add(f['frame_id'])

    def _window_target(reason, share):
        """What a critical window would like, if the budget allows it."""
        bucket = buckets[reason]
        if not bucket:
            return 0
        # derive the cap from the window's OWN span, so it tracks Phase 1's
        # hook_window_s / cta_window_s without duplicating the constant here
        span = max(f['actual_time'] for f in bucket) - min(f['actual_time'] for f in bucket)
        cap = max(cfg.min_window_frames,
                  int(math.ceil(span / max(0.05, cfg.window_frame_interval))) + 1)
        return min(len(bucket), cap, max(1, int(round(max_frames * share))))

    # ---- 1. a MINIMUM presence in each compliance-critical window ----------
    # Only the minimum, not the full target. Filling these to their cap FIRST is
    # what starved the middle of the video: on a 60s/35-cut clip it spent 18 of
    # 42 frames on ten seconds of footage and left six shots entirely unseen.
    # An unseen shot is a total blind spot, whereas a coarser hook still answers
    # the hook question -- to +/-1.5s instead of +/-0.55s.
    for reason in ('hook_window', 'cta_window'):
        if buckets[reason]:
            _take(buckets[reason], min(len(buckets[reason]), cfg.min_window_frames))

    # ---- 2. one frame in every shot nobody is looking at yet ----------------
    def _uncovered():
        return [(s, e) for s, e in shots
                if not any(s <= f['actual_time'] < e for f in chosen)]

    gaps = _uncovered()
    budget_left = max_frames - len(chosen)
    if gaps and budget_left > 0:
        if len(gaps) <= budget_left:
            order = list(range(len(gaps)))
        else:
            # more shots than frames: spread the visits across the timeline
            order = sorted(set(np.linspace(0, len(gaps) - 1, budget_left)
                               .round().astype(int).tolist()))
        for gi in order:
            if len(chosen) >= max_frames:
                break
            s, e = gaps[gi]
            cands = [f for f in frames
                     if f['frame_id'] not in chosen_ids and s <= f['actual_time'] < e]
            if not cands:
                continue
            mid = (s + e) / 2.0
            # a scene_change frame is the one sampled just AFTER the cut, so it
            # is the most representative view of the shot; otherwise take the
            # frame nearest the middle
            cands.sort(key=lambda f: (0 if f['reason'] == 'scene_change' else 1,
                                      abs(f['actual_time'] - mid)))
            chosen.append(cands[0])
            chosen_ids.add(cands[0]['frame_id'])

    # ---- 3. now densify the critical windows, BALANCED ---------------------
    # Step up whichever window is furthest below its own target. Filling the hook
    # to its cap and giving the CTA the remainder left the CTA on 3 frames while
    # the hook had 9 -- an artefact of loop order, not a decision anyone made.
    targets, have = {}, {}
    for reason, share in (('hook_window', cfg.quota_hook), ('cta_window', cfg.quota_cta)):
        if buckets[reason]:
            targets[reason] = _window_target(reason, share)
            have[reason] = sum(1 for f in chosen if f['reason'] == reason)

    _guard = 0
    while len(chosen) < max_frames and _guard < 500:
        _guard += 1
        behind = [r for r in targets if have[r] < targets[r]]
        if not behind:
            break
        # ties broken by name so the selection stays byte-identical across runs
        reason = sorted(behind, key=lambda r: (-(targets[r] - have[r]), r))[0]
        before = len(chosen)
        _take(buckets[reason], have[reason] + 1)
        have[reason] = sum(1 for f in chosen if f['reason'] == reason)
        if len(chosen) == before:
            targets[reason] = have[reason]      # this bucket has nothing new to give

    # ---- 4. anything left over: spread evenly across the timeline -----------
    if len(chosen) < max_frames:
        rest = sorted((f for f in frames if f['frame_id'] not in chosen_ids),
                      key=lambda f: f['actual_time'])
        need = max_frames - len(chosen)
        if rest and need > 0:
            idx = np.linspace(0, len(rest) - 1, min(need, len(rest))).round().astype(int)
            for i in sorted(set(idx.tolist())):
                if len(chosen) >= max_frames:
                    break
                chosen.append(rest[i])
                chosen_ids.add(rest[i]['frame_id'])

    chosen.sort(key=lambda f: f['actual_time'])
    if len(chosen) > max_frames:
        # Backstop, and PRIORITY-AWARE: keep hook and CTA before scene changes,
        # and scene changes before uniform fill. REASON_PRIORITY is Phase 1's,
        # so thinning here agrees with how the manifest was thinned to begin with.
        chosen.sort(key=lambda f: (REASON_PRIORITY.get(f['reason'], 9), f['actual_time']))
        chosen = chosen[:max_frames]
        chosen.sort(key=lambda f: f['actual_time'])
    return chosen

def build_frame_table(frames: list) -> list:
    """
    index -> (frame_id, timestamp). THE timestamp authority for this phase.

    The model is shown indices and answers with indices. Every second that reaches
    the evidence store is looked up here, so the model cannot invent one.
    """
    return [{'index': i,
             'frame_id': f['frame_id'],
             'timestamp': round(float(f['actual_time']), 3),
             'reason': f.get('reason', 'uniform'),
             'is_approximate_ts': bool(f.get('is_approximate_ts', False))}
            for i, f in enumerate(frames)]

def fit_to_pixel_budget(img, max_pixels: int, min_pixels: int = 0, patch: int = 28):
    """
    Resize an image to fit a pixel budget, preserving aspect ratio.

    We do this OURSELVES rather than trusting processor.max_pixels, because that
    attribute does not exist on every image processor and setting it with
    hasattr() guards fails SILENTLY when it does not. The failure mode is brutal:
    a 1080x1920 frame is ~2,645 vision tokens instead of ~250, so 24 frames
    become ~63,000 tokens instead of ~6,000 and prefill OOMs in a few seconds --
    with an error that says "tried to allocate 48 MiB" and mentions nothing
    about resolution. Resizing here cannot silently not-happen.

    Dimensions are floored to a multiple of `patch` (28 px for Qwen VL), so the
    result is always <= max_pixels and needs no awkward padding.
    """
    w, h = img.size
    n = max(1, w * h)
    if n > max_pixels:
        scale, growing = (max_pixels / n) ** 0.5, False
    elif min_pixels and n < min_pixels:
        scale, growing = (min_pixels / n) ** 0.5, True
    else:
        scale, growing = 1.0, False

    def snap(v: float) -> int:
        # Ceil when growing toward a minimum, floor when shrinking under a
        # maximum. Flooring both ways loses a whole 28px patch to float error:
        # 100 * 2.2399... = 223.99 floors to 196, not the 224 intended. The
        # epsilon absorbs the same error in the other direction (1080 * 448/1440
        # is exactly 336.0 in theory and 335.99999996 in practice).
        q = v / patch
        k = math.ceil(q - 1e-6) if growing else math.floor(q + 1e-6)
        return max(patch, int(k) * patch)

    nw, nh = snap(w * scale), snap(h * scale)
    # Hard invariant, whatever the rounding did: never exceed the budget.
    while nw * nh > max_pixels and (nw > patch or nh > patch):
        if nw >= nh:
            nw = max(patch, nw - patch)
        else:
            nh = max(patch, nh - patch)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.LANCZOS)
    return img

def load_frame_images(frames: list, frames_dir: Path, cfg: VisionConfig = None) -> tuple:
    """Returns (images, missing_frame_ids). A missing file is dropped, not fatal."""
    cfg = cfg or P3.vision
    images, missing = [], []
    for f in frames:
        p = Path(frames_dir) / f'{f["frame_id"]}.jpg'
        try:
            img = Image.open(p).convert('RGB')
            images.append(fit_to_pixel_budget(img, cfg.max_pixels, cfg.min_pixels))
        except Exception:
            missing.append(f['frame_id'])
    return images, missing


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 270: print('frames.py loaded')
