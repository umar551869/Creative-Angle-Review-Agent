"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 15.
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
DECODE_STAGE_VERSION = '1.1.0'

def resolve_rotation(meta: MediaMeta, cfg: DecodeConfig,
                     first_frame_hw: Optional[tuple] = None) -> tuple:
    """
    Returns (apply_ccw_degrees, explanation).
    Metadata + an empirical check against the decoder's actual output.
    """
    if cfg.force_rotation_ccw is not None:
        return int(cfg.force_rotation_ccw) % 360, 'forced by DecodeConfig.force_rotation_ccw'

    apply_ccw = meta.apply_rotation_ccw
    if apply_ccw == 0:
        return 0, 'no rotation metadata'

    if first_frame_hw is None:
        return apply_ccw, f'from metadata rotation={meta.rotation} (unverified)'

    fh, fw = first_frame_hw
    if apply_ccw in (90, 270):
        if (fh, fw) == (meta.height, meta.width):
            return apply_ccw, f'metadata rotation={meta.rotation}; decoder did NOT autorotate -> applying {apply_ccw} CCW'
        if (fh, fw) == (meta.width, meta.height):
            return 0, f'metadata rotation={meta.rotation}; decoder ALREADY autorotated -> applying 0 (avoiding double rotation)'
    return apply_ccw, f'metadata rotation={meta.rotation}; dims inconclusive -> applying {apply_ccw} CCW'

def _apply_rotation(img: np.ndarray, apply_ccw: int) -> np.ndarray:
    if apply_ccw == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if apply_ccw == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if apply_ccw == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return img

def _cap_long_edge(img: np.ndarray, max_long_edge: int) -> tuple:
    h, w = img.shape[:2]
    long_edge = max(h, w)
    if max_long_edge <= 0 or long_edge <= max_long_edge:
        return img, 1.0
    scale = max_long_edge / long_edge
    out = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                     interpolation=cv2.INTER_AREA)   # INTER_AREA is correct for downscale
    return out, scale

def build_frame_plan(scan: FrameScan,
                     scenes: SceneAnalysis,
                     meta: MediaMeta,
                     cfg: SamplerConfig) -> list:
    """
    Snap plan targets to real frames, dedupe by frame index, avoid blanks,
    enforce the budget. Returns a list of plan dicts sorted by actual_time.
    """
    targets = plan_targets(meta.duration_seconds, cfg,
                           scene_cut_times=scenes.cut_times if cfg.scene_refine else None)

    blank = set(scenes.blank_indices)
    by_index: dict = {}

    for tgt in targets:
        idx = scan.nearest_index(tgt.time)

        # ---- blank avoidance: shift to a non-blank neighbour -----------------
        if cfg.avoid_blank_frames and idx in blank:
            for offset in (1, -1, 2, -2, 3, -3):
                cand = idx + offset
                if 0 <= cand < scan.n_frames and cand not in blank:
                    idx = cand
                    break

        entry = {
            'scan_index': int(idx),
            'source_index': int(scan.indices[idx]),
            'requested_time': round(float(tgt.time), 6),
            'actual_time': round(float(scan.times[idx]), 6),
            'snap_error': round(abs(float(scan.times[idx]) - float(tgt.time)), 6),
            'reason': tgt.reason,
            'is_approximate_ts': bool(scan.approx_mask[idx]),
        }

        # ---- dedupe by frame index, keeping the HIGHEST-priority reason ------
        prev = by_index.get(idx)
        if prev is None or REASON_PRIORITY[tgt.reason] < REASON_PRIORITY[prev['reason']]:
            if prev is not None:
                entry['also_requested_as'] = sorted(
                    set(prev.get('also_requested_as', []) + [prev['reason']]))
            by_index[idx] = entry
        else:
            prev.setdefault('also_requested_as', [])
            if tgt.reason not in prev['also_requested_as']:
                prev['also_requested_as'].append(tgt.reason)

    items = sorted(by_index.values(), key=lambda e: e['actual_time'])
    items = enforce_budget(items, cfg.max_total_frames)
    return items

def extract_frames(video_path,
                   plan_items: list,
                   meta: MediaMeta,
                   cfg: DecodeConfig,
                   out_dir: Path) -> tuple:
    """
    One sequential decode pass; writes only the planned frames as JPEG.
    Returns (frame_records, decode_info).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob('*.jpg'):
        stale.unlink()

    # Key on SOURCE (decode-order) index, not scan_index. The scan re-sorts by time
    # when pts are non-monotonic, so scan_index != decode position on such files.
    wanted = {item['source_index']: item for item in plan_items}
    records: list = []
    apply_ccw, rotation_note = resolve_rotation(meta, cfg, None)
    rotation_resolved = False
    t0 = time.time()

    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'
        time_base = stream.time_base

        decode_pos = 0
        for frame in container.decode(stream):
            if not rotation_resolved:
                apply_ccw, rotation_note = resolve_rotation(
                    meta, cfg, (frame.height, frame.width))
                rotation_resolved = True

            item = wanted.get(decode_pos)
            if item is not None:
                img = frame.to_ndarray(format='rgb24')
                img = _apply_rotation(img, apply_ccw)
                img, scale = _cap_long_edge(img, cfg.max_long_edge)
                h, w = img.shape[:2]

                frame_id = f'f{len(records):05d}'
                rel = f'frames/{frame_id}.jpg'
                cv2.imwrite(str(out_dir / f'{frame_id}.jpg'),
                            cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                            [int(cv2.IMWRITE_JPEG_QUALITY), cfg.jpeg_quality])

                rec = dict(item)
                rec.update({
                    'frame_id': frame_id,
                    'path': rel,
                    'width': int(w),
                    'height': int(h),
                    'resize_scale': round(float(scale), 6),
                    'rotation_applied_ccw': int(apply_ccw),
                    'pts': int(frame.pts) if frame.pts is not None else None,
                    'pts_time': (round(float(frame.pts * time_base), 6)
                                 if frame.pts is not None and time_base is not None else None),
                })
                records.append(rec)
            decode_pos += 1

    records.sort(key=lambda r: r['actual_time'])
    for i, rec in enumerate(records):          # renumber after sorting
        rec['manifest_position'] = i

    info = {
        'rotation_applied_ccw': int(apply_ccw),
        'rotation_note': rotation_note,
        'frames_planned': len(plan_items),
        'frames_extracted': len(records),
        'decode_seconds': round(time.time() - t0, 3),
    }
    return records, info


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 182: print('decode.py loaded')
