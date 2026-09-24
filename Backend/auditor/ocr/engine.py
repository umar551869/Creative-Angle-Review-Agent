"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 22.
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
@dataclass
class OCRLine:
    text: str
    confidence: float
    bbox: list          # [x1, y1, x2, y2] in the coordinates of the frame processed
    quad: list          # [[x,y] x4] original polygon, for accurate overlay drawing

def _quad_to_bbox(quad) -> list:
    pts = np.asarray(quad, dtype=np.float32).reshape(-1, 2)
    return [float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max())]

class RapidOCREngine:
    name = 'rapidocr'

    def __init__(self, cfg: OCRConfig):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            from rapidocr import RapidOCR      # newer package name
        kwargs = dict(cfg.rapidocr_kwargs)
        try:
            self.engine = RapidOCR(**kwargs) if kwargs else RapidOCR()
        except TypeError as exc:
            print(f'  RapidOCR rejected rapidocr_kwargs ({str(exc)[:80]}) -> using defaults')
            self.engine = RapidOCR()
        self.cfg = cfg

    def __call__(self, image_bgr: np.ndarray) -> list:
        out = self.engine(image_bgr)
        # shape 1: (result, elapse) where result = [[quad, text, score], ...]
        if isinstance(out, tuple):
            result = out[0]
            if not result:
                return []
            lines = []
            for row in result:
                quad, text, score = row[0], row[1], row[2]
                lines.append(OCRLine(str(text), float(score), _quad_to_bbox(quad),
                                     np.asarray(quad).reshape(-1, 2).tolist()))
            return lines
        # shape 2: an object exposing .boxes / .txts / .scores
        boxes = getattr(out, 'boxes', None)
        txts = getattr(out, 'txts', None)
        scores = getattr(out, 'scores', None)
        if boxes is None or txts is None:
            return []
        lines = []
        for quad, text, score in zip(boxes, txts, scores if scores is not None else [1.0] * len(txts)):
            lines.append(OCRLine(str(text), float(score), _quad_to_bbox(quad),
                                 np.asarray(quad).reshape(-1, 2).tolist()))
        return lines

class PaddleOCREngine:
    name = 'paddleocr'

    def __init__(self, cfg: OCRConfig):
        from paddleocr import PaddleOCR
        self.cfg = cfg
        for kwargs in ({'lang': cfg.language, 'use_angle_cls': True, 'show_log': False},
                       {'lang': cfg.language, 'use_textline_orientation': True},
                       {'lang': cfg.language}):
            try:
                self.engine = PaddleOCR(**kwargs)
                return
            except (TypeError, ValueError):
                continue
        raise RuntimeError('PaddleOCR could not be constructed with any known signature')

    def __call__(self, image_bgr: np.ndarray) -> list:
        # --- v3-style .predict() -> [{'rec_texts', 'rec_scores', 'dt_polys'}] ---
        if hasattr(self.engine, 'predict'):
            try:
                res = self.engine.predict(image_bgr)
                lines = []
                for page in (res or []):
                    d = page if isinstance(page, dict) else getattr(page, 'json', {}) or {}
                    texts = d.get('rec_texts', []); scores = d.get('rec_scores', [])
                    polys = d.get('dt_polys', [])
                    for quad, text, score in zip(polys, texts, scores):
                        lines.append(OCRLine(str(text), float(score), _quad_to_bbox(quad),
                                             np.asarray(quad).reshape(-1, 2).tolist()))
                if lines:
                    return lines
            except Exception:
                pass
        # --- v2-style .ocr() -> [[[quad, (text, score)], ...]] ------------------
        for call in (lambda: self.engine.ocr(image_bgr, cls=True),
                     lambda: self.engine.ocr(image_bgr)):
            try:
                res = call()
            except (TypeError, ValueError):
                continue
            lines = []
            for page in (res or []):
                for row in (page or []):
                    quad, payload = row[0], row[1]
                    text, score = (payload[0], payload[1]) if isinstance(payload, (list, tuple)) else (payload, 1.0)
                    lines.append(OCRLine(str(text), float(score), _quad_to_bbox(quad),
                                         np.asarray(quad).reshape(-1, 2).tolist()))
            return lines
        return []

class TesseractEngine:
    """
    Python 3.13 fallback. The tesseract BINARY does the work, so there is no
    native Python wheel to be missing -- pytesseract is a thin subprocess wrapper.

    Quality on stylized TikTok fonts is below PP-OCR. Accept it as a working
    floor, and record in the decision log that the benchmark ran on tesseract.
    """
    name = 'tesseract'

    def __init__(self, cfg: OCRConfig):
        import pytesseract
        from pytesseract import Output
        self.pt, self.Output, self.cfg = pytesseract, Output, cfg
        self.pt.get_tesseract_version()          # raises if the binary is absent
        # psm 11 = "sparse text": find as much text as possible, no layout
        # assumptions. Correct for scattered video overlays; psm 3 (the default)
        # assumes a page of prose and misses isolated captions.
        self.config = f'--oem 3 --psm {cfg.tesseract_psm}'

    def __call__(self, image_bgr: np.ndarray) -> list:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        scale = 1.0
        if max(h, w) < self.cfg.tesseract_min_upscale_edge:
            scale = self.cfg.tesseract_min_upscale_edge / max(h, w)
            gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_CUBIC)

        d = self.pt.image_to_data(gray, lang=self.cfg.tesseract_lang,
                                  config=self.config, output_type=self.Output.DICT)

        # tesseract returns WORDS; group them into lines via block/par/line ids
        groups = {}
        for i in range(len(d['text'])):
            txt = (d['text'][i] or '').strip()
            try:
                conf = float(d['conf'][i])
            except (TypeError, ValueError):
                conf = -1.0
            if not txt or conf < 0:
                continue
            key = (d['block_num'][i], d['par_num'][i], d['line_num'][i])
            x, y, bw, bh = d['left'][i], d['top'][i], d['width'][i], d['height'][i]
            g = groups.setdefault(key, {'words': [], 'confs': [],
                                        'x1': 1e9, 'y1': 1e9, 'x2': -1e9, 'y2': -1e9})
            g['words'].append(txt)
            g['confs'].append(conf / 100.0)      # tesseract conf is 0-100
            g['x1'] = min(g['x1'], x);        g['y1'] = min(g['y1'], y)
            g['x2'] = max(g['x2'], x + bw);   g['y2'] = max(g['y2'], y + bh)

        lines = []
        for g in groups.values():
            # map coordinates back to the ORIGINAL frame scale
            x1, y1 = g['x1'] / scale, g['y1'] / scale
            x2, y2 = g['x2'] / scale, g['y2'] / scale
            lines.append(OCRLine(
                ' '.join(g['words']), float(np.mean(g['confs'])),
                [x1, y1, x2, y2],
                [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            ))
        return lines

def load_ocr(cfg: OCRConfig):
    """Returns an engine exposing __call__(image_bgr) -> list[OCRLine]."""
    order = {'auto': ['rapidocr', 'paddleocr', 'tesseract'],
             'rapidocr': ['rapidocr'],
             'paddleocr': ['paddleocr'],
             'tesseract': ['tesseract']}[cfg.backend]
    # skip backends §0.1 already reported as unavailable
    _avail = {'rapidocr': BACKENDS.get('rapidocr'), 'paddleocr': BACKENDS.get('paddleocr'),
              'tesseract': BACKENDS.get('pytesseract')}
    if cfg.backend == 'auto':
        order = [b for b in order if _avail.get(b)]
    errors = []
    for backend in order:
        t0 = time.time()
        try:
            engine = {'rapidocr': RapidOCREngine, 'paddleocr': PaddleOCREngine,
                      'tesseract': TesseractEngine}[backend](cfg)
            # smoke test on a synthetic white image -- catches broken model downloads
            probe = np.full((64, 256, 3), 255, dtype=np.uint8)
            cv2.putText(probe, 'SHOP NOW', (10, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
            lines = engine(probe)
            print(f'OCR ready: {backend} on {cfg.device} '
                  f'({time.time() - t0:.1f}s, smoke test read {len(lines)} line(s): '
                  f'{[l.text for l in lines]})')
            return engine
        except Exception as exc:
            errors.append(f'{backend}: {type(exc).__name__}: {str(exc)[:140]}')
    raise RuntimeError('No OCR backend available.\n  ' + '\n  '.join(errors))


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 206: print('engine.py loaded')
