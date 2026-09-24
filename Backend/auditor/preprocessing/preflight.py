"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 10.
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
class PreflightResult(BaseModel):
    passed: bool
    failures: list = Field(default_factory=list)   # [{code, detail}] -> hard stop
    warnings: list = Field(default_factory=list)   # [{code, detail}] -> continue, but record

    def add_failure(self, code: str, detail: str = ''):
        self.failures.append({'code': code, 'detail': detail}); self.passed = False

    def add_warning(self, code: str, detail: str = ''):
        self.warnings.append({'code': code, 'detail': detail})

_VIDEO_MAGIC_CHECKS = (
    ('mp4/mov', lambda b: len(b) >= 12 and b[4:8] == b'ftyp'),
    ('matroska/webm', lambda b: b[:4] == b'\x1a\x45\xdf\xa3'),
    ('avi', lambda b: b[:4] == b'RIFF' and b[8:12] == b'AVI '),
    ('mpeg-ts', lambda b: b[:1] == b'\x47'),
    ('flv', lambda b: b[:3] == b'FLV'),
)

def sniff_container(path) -> Optional[str]:
    with open(path, 'rb') as fh:
        head = fh.read(16)
    for name, test in _VIDEO_MAGIC_CHECKS:
        try:
            if test(head):
                return name
        except Exception:
            continue
    return None

def preflight(video_path, meta: Optional[MediaMeta], cfg: PreflightConfig) -> PreflightResult:
    res = PreflightResult(passed=True)
    p = Path(video_path)

    # ---- file-level gates ---------------------------------------------------
    if not p.exists():
        res.add_failure('FILE_MISSING', str(p));  return res
    size = p.stat().st_size
    if size == 0:
        res.add_failure('FILE_EMPTY');            return res
    if size > cfg.max_file_bytes:
        res.add_failure('FILE_TOO_LARGE', f'{size/1024**2:.1f} MB > {cfg.max_file_bytes/1024**2:.0f} MB')
        return res
    if sniff_container(p) is None:
        res.add_warning('UNRECOGNISED_CONTAINER_MAGIC', 'header did not match a known video container')

    if meta is None:
        res.add_failure('PROBE_FAILED');          return res

    # ---- stream gates -------------------------------------------------------
    if meta.duration_seconds <= 0:
        res.add_failure('ZERO_DURATION');         return res
    if meta.duration_seconds < cfg.min_duration_s:
        res.add_failure('DURATION_TOO_SHORT', f'{meta.duration_seconds:.2f}s')
    if meta.duration_seconds > cfg.max_duration_s:
        res.add_failure('DURATION_TOO_LONG', f'{meta.duration_seconds:.1f}s')
    if min(meta.width, meta.height) < cfg.min_dimension:
        res.add_failure('INVALID_RESOLUTION', f'{meta.width}x{meta.height}')

    # ---- decode probe: can we actually get a frame out of it? ---------------
    try:
        with av.open(str(p)) as container:
            stream = container.streams.video[0]
            got = next(container.decode(stream), None)
            if got is None:
                res.add_failure('DECODE_FAILED', 'no frame decoded from first packets')
    except Exception as exc:
        res.add_failure('DECODE_FAILED', f'{type(exc).__name__}: {exc}')

    # ---- warnings (non-fatal, but they travel with the evidence) -----------
    if not meta.has_audio:
        res.add_warning('NO_AUDIO', 'speech requirements will resolve to UNCERTAIN')
    if meta.is_vfr:
        res.add_warning('VFR_DETECTED', f'r={meta.r_frame_rate:.3f} avg={meta.avg_frame_rate:.3f}')
    if meta.duration_mismatch_seconds > cfg.duration_mismatch_tolerance_s:
        res.add_warning('DURATION_MISMATCH', f'{meta.duration_mismatch_seconds:.3f}s between format and stream')
    if not meta.is_vertical:
        res.add_warning('NOT_VERTICAL', f'{meta.display_width}x{meta.display_height} — unusual for TikTok')
    if meta.rotation != 0:
        res.add_warning('ROTATION_METADATA', f'rotation={meta.rotation} -> apply {meta.apply_rotation_ccw} deg CCW')
    if min(meta.display_width, meta.display_height) < 480:
        res.add_warning('LOW_RESOLUTION', 'OCR of small on-screen text may be unreliable')

    return res


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 94: print('preflight.py loaded')
