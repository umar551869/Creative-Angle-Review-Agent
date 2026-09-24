"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 24.
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
def run_ocr(engine, manifest: dict, frames_dir: Path, cfg: OCRConfig, verbose=True) -> dict:
    t0 = time.time()
    frames = select_ocr_frames(manifest, cfg)

    detections, per_frame, masked_out = [], [], []
    last_sig, last_lines, last_frame_id = None, [], None
    n_ocr_calls, n_skipped, n_dropped_conf, n_spaces_restored = 0, 0, 0, 0
    n_words_merged, n_lines_merged = 0, 0
    skip_run, n_forced_rereads = 0, 0        # consecutive skips, and cap activations

    for f in frames:
        img_path = frames_dir / f'{f["frame_id"]}.jpg'
        img = cv2.imread(str(img_path))
        if img is None:
            per_frame.append({'frame_id': f['frame_id'], 'status': 'READ_FAILED'})
            continue
        h, w = img.shape[:2]

        # ---- near-duplicate skip -------------------------------------------
        sig = frame_signature(img, cfg.duplicate_signature_size)
        reused = False
        if (cfg.skip_duplicates and last_sig is not None
                and skip_run < cfg.duplicate_max_run):          # hard cap, see config
            dup, n_changed = is_near_duplicate(sig, last_sig, cfg.duplicate_pixel_delta,
                                               cfg.duplicate_min_changed_px)
            if dup:
                lines, reused = last_lines, True
                n_skipped += 1
                skip_run += 1
        if not reused and skip_run >= cfg.duplicate_max_run:
            n_forced_rereads += 1                                # the cap fired

        if not reused:
            lines = engine(img)
            n_ocr_calls += 1
            skip_run = 0
            last_sig, last_lines, last_frame_id = sig, lines, f['frame_id']

        # ---- region masks ---------------------------------------------------
        masks = build_masks(w, h, cfg)
        lines, removed = apply_masks(lines, masks)
        masked_out += [{**r, 'frame_id': f['frame_id'], 'timestamp': f['actual_time']}
                       for r in removed]

        # ---- drop junk BEFORE merging -----------------------------------------
        # Order matters. If a 0.35-confidence garbage line is still present when
        # blocks are formed, it can join a 0.9 caption and contaminate the whole
        # block -- which then fails the caption cross-check on every measure.
        clean = []
        for line in lines:
            if len(line.text.strip()) < cfg.min_text_length:
                continue
            if line.confidence < cfg.drop_below_confidence:
                n_dropped_conf += 1
                continue
            clean.append(line)

        # ---- group boxes: WORDS -> lines -> blocks ---------------------------
        # AFTER masking and AFTER the confidence filter, so neither a masked box
        # nor a junk box can ever be merged into a surviving group.
        #
        # WORDS FIRST. PP-OCR splits 'CODE SAVE20' into two boxes on ONE row, and
        # vertical line-merging cannot fix that -- they are side by side, not
        # stacked. Without this pass no interval ever contains the whole phrase.
        n_boxes_raw = len(clean)
        rows_ = merge_words_into_lines(clean, cfg)
        n_words_merged += max(0, n_boxes_raw - len(rows_))
        lines = merge_lines_into_blocks(rows_, cfg)
        n_lines_merged += max(0, len(rows_) - len(lines))

        # ---- emit detections -------------------------------------------------
        frame_dets = []
        for line in lines:
            text_raw = line.text.strip()
            # ---- repair run-together output HERE, once, at ingest ------------
            # Everything downstream (dedupe, caption check, search, the report)
            # then works on clean text. text_raw is retained: we never destroy
            # what the model actually returned.
            text, spaces_restored = restore_spaces(text_raw, cfg)
            if spaces_restored:
                n_spaces_restored += 1
            det = {
                'frame_id': f['frame_id'],
                'timestamp': f['actual_time'],
                'reason': f['reason'],
                'text': text,
                'text_raw': text_raw,
                'spaces_restored': spaces_restored,
                'norm_text': normalize_text(text),
                'confidence': round(float(line.confidence), 4),
                'low_confidence': bool(line.confidence < cfg.min_confidence),
                'bbox': [round(v, 1) for v in line.bbox],
                'quad': [[round(float(x), 1), round(float(y), 1)] for x, y in line.quad],
                'frame_width': int(w), 'frame_height': int(h),
                # Phase 1 stored the transform so boxes map back to original coords (spec 24)
                'resize_scale': f.get('resize_scale', 1.0),
                'rotation_applied_ccw': f.get('rotation_applied_ccw', 0),
                'inherited_from': last_frame_id if reused else None,
            }
            frame_dets.append(det)
        detections += frame_dets

        per_frame.append({'frame_id': f['frame_id'], 'timestamp': f['actual_time'],
                          'reason': f['reason'], 'n_lines': len(frame_dets),
                          'ocr_run': not reused, 'status': 'OK'})

    elapsed = time.time() - t0
    if verbose:
        print(f'  frames considered : {len(frames)}')
        print(f'  OCR calls         : {n_ocr_calls}  ({n_skipped} skipped as near-duplicates, '
              f'{100*n_skipped/max(1,len(frames)):.0f}% saved)')
        print(f'  forced re-reads   : {n_forced_rereads} (the {cfg.duplicate_max_run}-skip cap firing -- '
              f'bounds how long stale text can persist)')
        print(f'  raw detections    : {len(detections)}')
        print(f'  words merged      : {n_words_merged} side-by-side box(es) folded into lines')
        print(f'  lines merged      : {n_lines_merged} stacked line(s) folded into blocks')
        print(f'  spaces restored   : {n_spaces_restored} detection(s) repaired'
              f'{"" if _wordninja else "  (wordninja NOT installed - disabled)"}')
        print(f'  masked out        : {len(masked_out)}')
        print(f'  dropped (low conf): {n_dropped_conf}')
        print(f'  elapsed           : {elapsed:.1f}s  ({elapsed/max(1,n_ocr_calls):.2f}s per OCR call)')

    return {
        'detections': detections,
        'per_frame': per_frame,
        'masked_out': masked_out,
        'stats': {
            'frames_considered': len(frames), 'ocr_calls': n_ocr_calls,
            'frames_skipped_duplicate': n_skipped,
            'duplicate_skip_rate': round(n_skipped / max(1, len(frames)), 3),
            'forced_rereads': n_forced_rereads,
            'duplicate_max_run': cfg.duplicate_max_run,
            'raw_detections': len(detections), 'masked_out': len(masked_out),
            'dropped_low_confidence': n_dropped_conf,
            'spaces_restored': n_spaces_restored,
            'words_merged': n_words_merged,
            'lines_merged': n_lines_merged,
            'space_restoration_available': _wordninja is not None,
            'ocr_seconds': round(elapsed, 2),
        },
    }


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 148: print('run.py loaded')
