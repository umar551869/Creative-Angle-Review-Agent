"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 23.
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
REASON_PRIORITY = {'hook_window': 0, 'cta_window': 1, 'scene_change': 2, 'uniform': 3}

def select_ocr_frames(manifest: dict, cfg: OCRConfig) -> list:
    frames = [f for f in manifest['frames'] if f['reason'] in cfg.frame_reasons]
    frames.sort(key=lambda f: (REASON_PRIORITY.get(f['reason'], 9), f['actual_time']))
    if cfg.max_frames:
        frames = frames[:cfg.max_frames]
    frames.sort(key=lambda f: f['actual_time'])     # process in temporal order
    return frames

def build_masks(width: int, height: int, cfg: OCRConfig) -> list:
    """Exclusion rectangles in PIXEL coords, derived from normalized fractions."""
    if not cfg.apply_region_masks:
        return []
    masks = []
    if cfg.mask_bottom_fraction > 0:
        masks.append({'name': 'bottom_band',
                      'rect': [0, int(height * (1 - cfg.mask_bottom_fraction)), width, height]})
    if cfg.mask_right_fraction > 0:
        masks.append({'name': 'right_rail',
                      'rect': [int(width * (1 - cfg.mask_right_fraction)), 0, width, height]})
    if cfg.mask_top_fraction > 0:
        masks.append({'name': 'top_band',
                      'rect': [0, 0, width, int(height * cfg.mask_top_fraction)]})
    return masks

def apply_masks(lines: list, masks: list) -> tuple:
    """Drop lines whose bbox CENTRE falls inside a mask. Returns (kept, removed)."""
    if not masks:
        return lines, []
    kept, removed = [], []
    for line in lines:
        cx = (line.bbox[0] + line.bbox[2]) / 2.0
        cy = (line.bbox[1] + line.bbox[3]) / 2.0
        hit = next((m['name'] for m in masks
                    if m['rect'][0] <= cx <= m['rect'][2] and m['rect'][1] <= cy <= m['rect'][3]),
                   None)
        if hit:
            removed.append({'text': line.text, 'mask': hit,
                            'confidence': round(float(line.confidence), 3)})
        else:
            kept.append(line)
    return kept, removed

def merge_words_into_lines(lines: list, cfg: OCRConfig) -> list:
    """
    Group boxes that sit SIDE BY SIDE on the same row into one line.

    PP-OCR's detector returns one box per text REGION, and with large bold fonts
    it splits a single line into separate words:

        'CODE SAVE20'  ->  ['CODE', 'SAVE20']

    Vertical line-merging cannot repair that -- these boxes are neighbours on one
    row, not stacked rows. Measured on the ground-truth test video: the phrase
    never appeared in any interval, because no interval ever held both words.

    Same guards as the vertical merge, so two genuinely separate elements that
    happen to sit side by side are not welded together: they must share a row,
    have similar height, similar confidence, and only a word-sized gap.
    """
    if not cfg.merge_words or len(lines) < 2:
        return lines

    items = sorted(lines, key=lambda l: l.bbox[0])          # left to right
    rows: list = []

    for line in items:
        h = max(1.0, line.bbox[3] - line.bbox[1])
        placed = False
        for row in rows:
            last = row['lines'][-1]                          # rightmost so far
            lh = max(1.0, last.bbox[3] - last.bbox[1])
            rx1, ry1, rx2, ry2 = row['bbox']

            # 1. same row: vertical overlap, as a fraction of the shorter box
            ov = max(0.0, min(line.bbox[3], ry2) - max(line.bbox[1], ry1))
            if ov / min(h, max(1.0, ry2 - ry1)) < cfg.word_merge_min_voverlap:
                continue
            # 2. similar font size
            if not (cfg.line_merge_height_ratio_min <= h / lh <= cfg.line_merge_height_ratio_max):
                continue
            # 3. similar confidence -- clean text must not absorb garbage
            if abs(line.confidence - last.confidence) > cfg.line_merge_max_conf_delta:
                continue
            # 4. a word gap, not a layout gap (and not heavily overlapping)
            gap = line.bbox[0] - rx2
            if gap > cfg.word_merge_max_hgap_ratio * max(h, lh) or gap < -0.5 * max(h, lh):
                continue

            row['lines'].append(line)
            row['bbox'] = [min(rx1, line.bbox[0]), min(ry1, line.bbox[1]),
                           max(rx2, line.bbox[2]), max(ry2, line.bbox[3])]
            placed = True
            break
        if not placed:
            rows.append({'lines': [line], 'bbox': list(line.bbox)})

    out = []
    for row in rows:
        ls = row['lines']
        if len(ls) == 1:
            out.append(ls[0])
            continue
        text = ' '.join(l.text.strip() for l in ls if l.text.strip())   # already L->R
        conf = float(np.mean([l.confidence for l in ls]))
        x1, y1, x2, y2 = row['bbox']
        out.append(OCRLine(text, conf, [x1, y1, x2, y2],
                           [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]))
    return out

def merge_lines_into_blocks(lines: list, cfg: OCRConfig) -> list:
    """
    Group vertically-stacked, horizontally-overlapping text lines into one block.

    PP-OCR detects per LINE, so a three-line title card arrives as three separate
    detections. Downstream that becomes three intervals with three independently
    computed derived_from_speech flags, for what a viewer sees as one element --
    and a multi-line phrase can never be matched as a whole.
    """
    if not cfg.merge_lines or len(lines) < 2:
        return lines

    lines = sorted(lines, key=lambda l: l.bbox[1])          # top to bottom
    # Each block tracks its OWN bounding box. The previous version compared each
    # new line against only the last line added, so A joined B, B joined C, and a
    # chain ran down the whole frame -- 225 merges on ~96 frames, welding captions
    # to mirrored product text. Comparing against the block's bbox stops that.
    blocks: list = []

    for line in lines:
        h = max(1.0, line.bbox[3] - line.bbox[1])
        placed = False
        for blk in blocks:
            if len(blk['lines']) >= cfg.line_merge_max_lines:
                continue
            last = blk['lines'][-1]
            lh = max(1.0, last.bbox[3] - last.bbox[1])
            bx1, by1, bx2, by2 = blk['bbox']

            # 1. similar font size -- a title card's lines match; a label does not
            if not (cfg.line_merge_height_ratio_min <= h / lh <= cfg.line_merge_height_ratio_max):
                continue
            # 2. similar confidence -- clean caption text must not absorb garbage
            if abs(line.confidence - last.confidence) > cfg.line_merge_max_conf_delta:
                continue
            # 3. vertically adjacent to the BOTTOM OF THE BLOCK
            vgap = line.bbox[1] - by2                       # negative == overlapping rows
            if not (-0.5 * lh <= vgap <= cfg.line_merge_max_vgap_ratio * max(h, lh)):
                continue
            # 4. horizontal overlap against the BLOCK, as a fraction of the narrower
            ox = max(0.0, min(line.bbox[2], bx2) - max(line.bbox[0], bx1))
            narrower = min(line.bbox[2] - line.bbox[0], bx2 - bx1)
            if ox / max(1.0, narrower) < cfg.line_merge_min_xoverlap:
                continue

            blk['lines'].append(line)
            blk['bbox'] = [min(bx1, line.bbox[0]), min(by1, line.bbox[1]),
                           max(bx2, line.bbox[2]), max(by2, line.bbox[3])]
            placed = True
            break
        if not placed:
            blocks.append({'lines': [line], 'bbox': list(line.bbox)})

    out = []
    for blk in blocks:
        ls = blk['lines']
        if len(ls) == 1:
            out.append(ls[0])
            continue
        text = ' '.join(l.text.strip() for l in ls if l.text.strip())
        conf = float(np.mean([l.confidence for l in ls]))
        x1, y1, x2, y2 = blk['bbox']
        out.append(OCRLine(text, conf, [x1, y1, x2, y2],
                           [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]))
    return out

def frame_signature(image_bgr: np.ndarray, size: int = 256) -> np.ndarray:
    g = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (size, size), interpolation=cv2.INTER_AREA).astype(np.int16)

def is_near_duplicate(sig_a: np.ndarray, sig_b: np.ndarray,
                      pixel_delta: int = 15, min_changed_px: int = 6) -> tuple:
    """
    Duplicate iff almost NO PIXEL changed meaningfully.

    Counting changed pixels, NOT averaging a difference -- over the frame or over
    tiles. Averages hide small changes, and a small change is precisely what must
    be caught: a caption going 'STEP 1' -> 'STEP 2' alters one glyph, which at
    1080x1920 with 80px text is a handful of pixels in the signature. Miss it and
    OCR is skipped, so the OLD caption is recorded on a frame showing the NEW one.

    Counting is alignment-free (no tile can split the evidence in half) and
    scale-aware (raise the signature size and a glyph covers proportionally more
    pixels). Codec and JPEG noise is averaged away by the downscale and clears
    almost nothing above `pixel_delta`.

    Returns (is_duplicate, n_changed_pixels).
    """
    diff = np.abs(sig_a.astype(np.int16) - sig_b.astype(np.int16))
    changed = int((diff >= pixel_delta).sum())
    return changed < min_changed_px, changed

# ---- self-test: the one property this module exists for ---------------------
# Lives HERE, next to is_near_duplicate, so it can never run before the function
# it tests is defined.
def _test_duplicate_detection():
    """
    FAITHFUL test: render text at real scale on a real frame size and compare
    THROUGH frame_signature.

    The previous version modelled the signature directly and made the caption 8px
    of a 128px signature -- 6% of frame height. A real 80px caption on a 1920px
    frame is 4%, and its changed glyph is a few pixels. That test passed while the
    pipeline failed on the §18 ground-truth video. Test what actually runs.
    """
    cfg = OCRConfig()
    H, W = 1920, 1080
    base = np.full((H, W), 48, dtype=np.uint8)

    def _frame(text, jitter=0):
        img = base.copy()
        cv2.putText(img, text, (240, 900), cv2.FONT_HERSHEY_SIMPLEX, 3.5, 255, 8, cv2.LINE_AA)
        if jitter:
            noise = np.random.default_rng(0).integers(-jitter, jitter + 1, (H, W))
            img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    s1 = frame_signature(_frame('STEP 1'), cfg.duplicate_signature_size)
    s2 = frame_signature(_frame('STEP 2'), cfg.duplicate_signature_size)
    sn = frame_signature(_frame('STEP 1', jitter=3), cfg.duplicate_signature_size)

    dup_glyph, n_glyph = is_near_duplicate(s2, s1, cfg.duplicate_pixel_delta,
                                           cfg.duplicate_min_changed_px)
    dup_noise, n_noise = is_near_duplicate(sn, s1, cfg.duplicate_pixel_delta,
                                           cfg.duplicate_min_changed_px)
    whole_mean = float(np.abs(s2 - s1).mean())

    assert not dup_glyph, (
        f'ONE GLYPH changed and the frame was still called a duplicate '
        f'({n_glyph} px over delta). OCR would be skipped and the OLD caption '
        f'written onto the new frame -- this is the fabrication bug.')
    assert dup_noise, f'codec-level noise was treated as a real change ({n_noise} px)'
    print(f'  duplicate self-test PASS  -- STEP 1 -> STEP 2: {n_glyph} px changed (re-read). '
          f'Noise: {n_noise} px (duplicate). Whole-frame mean is only {whole_mean:.2f}, '
          f'which is why any averaging misses it.')


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 261: _test_duplicate_detection()
#   line 262: print('selection.py loaded')
