"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 52.
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
def frames_for_ocr(res: PreprocessResult, limit: Optional[int] = None) -> list:
    """Native-resolution frame paths for Phase 2 OCR, in priority order."""
    frames = sorted(res.manifest['frames'],
                    key=lambda f: (REASON_PRIORITY[f['reason']], f['actual_time']))
    if limit:
        frames = frames[:limit]
    return [{'frame_id': f['frame_id'],
             'path': str(res.frames_dir / f'{f["frame_id"]}.jpg'),
             'timestamp': f['actual_time'],
             'reason': f['reason'],
             'width': f['width'], 'height': f['height'],
             'resize_scale': f['resize_scale']}
            for f in frames]

def select_vlm_frames_preview(res: PreprocessResult, max_frames: int = 32) -> list:
    """
    PREVIEW ONLY -- Phase 3 defines the real selector.

    Renamed from `select_vlm_frames`: Phase 3 supersedes that name with a version
    that takes a manifest dict and allocates the budget proportionally to what the
    video actually contains. While both were called `select_vlm_frames`, re-running
    THIS cell after Phase 3 had loaded silently replaced Phase 3's selector with
    one that demands a PreprocessResult and uses fixed quotas -- a failure that
    only appears later, as a TypeError or as quietly worse frame coverage.

    Proportional selection that GUARANTEES critical-window representation
    instead of taking the first N. Quotas: hook 30%, cta 25%, scenes 15%, uniform rest.
    """
    frames = res.manifest['frames']
    if len(frames) <= max_frames:
        return list(frames)

    quotas = {'hook_window': 0.30, 'cta_window': 0.25, 'scene_change': 0.15, 'uniform': 0.30}
    chosen: list = []
    for reason, share in quotas.items():
        bucket = [f for f in frames if f['reason'] == reason]
        if not bucket:
            continue
        want = max(1, int(round(max_frames * share)))
        if len(bucket) <= want:
            chosen += bucket
        else:
            idx = np.linspace(0, len(bucket) - 1, want).round().astype(int)
            chosen += [bucket[i] for i in sorted(set(idx.tolist()))]

    # top up / trim to exactly max_frames, evenly across the timeline
    chosen.sort(key=lambda f: f['actual_time'])
    if len(chosen) > max_frames:
        idx = np.linspace(0, len(chosen) - 1, max_frames).round().astype(int)
        chosen = [chosen[i] for i in sorted(set(idx.tolist()))]
    elif len(chosen) < max_frames:
        remaining = [f for f in frames if f not in chosen]
        remaining.sort(key=lambda f: f['actual_time'])
        need = max_frames - len(chosen)
        if remaining and need > 0:
            idx = np.linspace(0, len(remaining) - 1, min(need, len(remaining))).round().astype(int)
            chosen += [remaining[i] for i in sorted(set(idx.tolist()))]
            chosen.sort(key=lambda f: f['actual_time'])
    return chosen

def frames_for_vlm(res: PreprocessResult, max_frames: int = 32) -> list:
    """
    Returns [(PIL.Image, timestamp_seconds), ...] -- drop-in compatible with the
    downsample_video() output shape used by the VLM-Video-Understanding repo,
    but with REAL presentation timestamps underneath.
    """
    return [(Image.open(res.frames_dir / f'{f["frame_id"]}.jpg').convert('RGB'),
             f['actual_time'])
            for f in select_vlm_frames_preview(res, max_frames)]

def build_qwen_content(pairs: list, question: str) -> list:
    """
    Preview of the Phase 3 interleaved message structure.
    Timestamp text BEFORE each image is what prevents the VLM from inventing times.
    """
    content = [{'type': 'text',
                'text': f'This video has {len(pairs)} sampled frames. '
                        f'Each image is preceded by its exact timestamp.'}]
    for i, (_img, ts) in enumerate(pairs):
        content.append({'type': 'text', 'text': f'Frame {i} ({ts:.2f}s):'})
        content.append({'type': 'image'})     # Phase 3 substitutes the PIL image here
    content.append({'type': 'text', 'text': question})
    return content


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 94: ocr_frames = frames_for_ocr(result)
#   line 95: print(f'Phase 2 / OCR : {len(ocr_frames)} frames, priority order')
#   line 96: for f in ocr_frames[:5]:
#   line 99: vlm_pairs = frames_for_vlm(result, max_frames=32)
#   line 100: sel = select_vlm_frames_preview(result, 32)
#   line 101: counts = {}
#   line 102: for f in sel:
#   line 104: print(f"\nPhase 3 / VLM : {len(vlm_pairs)} frames from {len(result.manifest[
#   line 105: print(f'   composition: {counts}')
#   line 106: print(f'   timestamps : {[round(t, 2) for _, t in vlm_pairs[:8]]} …')
#   line 107: print(f'   first 3s   : {sum((1 for _, t in vlm_pairs if t <= 3.0))} frames 
#   line 109: preview = build_qwen_content(vlm_pairs, 'Describe the observable events. Do 
#   line 110: print(f'\nQwen message preview ({len(preview)} content blocks):')
#   line 111: for blk in preview[:6]:
#   line 113: print('    …')
