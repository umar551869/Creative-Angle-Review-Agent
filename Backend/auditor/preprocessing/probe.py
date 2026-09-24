"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 9.
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
class MediaMeta(BaseModel):
    # identity
    video_hash: str
    path: str
    file_bytes: int
    container_format: str = ''
    # timing
    duration_seconds: float = 0.0
    format_duration_seconds: Optional[float] = None
    stream_duration_seconds: Optional[float] = None
    duration_mismatch_seconds: float = 0.0
    # video stream
    width: int = 0
    height: int = 0
    coded_width: int = 0
    coded_height: int = 0
    display_width: int = 0          # after rotation is applied
    display_height: int = 0
    aspect_ratio: float = 0.0       # display_width / display_height
    is_vertical: bool = False
    r_frame_rate: float = 0.0       # container nominal fps
    avg_frame_rate: float = 0.0     # frames / duration
    is_vfr: bool = False
    nb_frames_declared: Optional[int] = None
    video_codec: str = ''
    pix_fmt: str = ''
    rotation: float = 0.0           # raw value from ffprobe
    apply_rotation_ccw: int = 0     # degrees CCW to apply to a decoded frame
    # audio stream
    has_audio: bool = False
    audio_codec: str = ''
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None
    # provenance
    probe_raw: dict = Field(default_factory=dict)

def _parse_rate(value) -> float:
    """ffprobe gives rates as 'num/den' strings, e.g. '30000/1001'."""
    if not value or value in ('0/0', 'N/A'):
        return 0.0
    try:
        if '/' in str(value):
            num, den = str(value).split('/')
            den = float(den)
            return float(num) / den if den else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0

def _extract_rotation(vstream: dict) -> float:
    """
    Two sources, checked in order of modernity.
    ffprobe's displaymatrix `rotation` is the angle by which the transform rotates
    the frame counter-clockwise; a portrait phone video typically reports -90.
    """
    for sd in (vstream.get('side_data_list') or []):
        if 'rotation' in sd:
            try:
                return float(sd['rotation'])
            except (TypeError, ValueError):
                pass
    tags = vstream.get('tags') or {}
    for key in ('rotate', 'Rotate', 'ROTATE'):
        if key in tags:
            try:
                return float(tags[key])
            except (TypeError, ValueError):
                pass
    return 0.0

def run_ffprobe(video_path) -> dict:
    cmd = [
        'ffprobe', '-v', 'error',
        '-print_format', 'json',
        '-show_format', '-show_streams',
        str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f'ffprobe failed: {res.stderr.strip()[:400]}')
    return json.loads(res.stdout)

def probe_video(video_path, video_hash: Optional[str] = None) -> MediaMeta:
    video_path = Path(video_path)
    raw = run_ffprobe(video_path)

    streams = raw.get('streams', [])
    fmt = raw.get('format', {})
    vstreams = [s for s in streams if s.get('codec_type') == 'video']
    astreams = [s for s in streams if s.get('codec_type') == 'audio']
    if not vstreams:
        raise RuntimeError('NO_VIDEO_STREAM')
    # Pick the largest video stream; some files carry a cover-art "video" stream.
    v = max(vstreams, key=lambda s: int(s.get('width') or 0) * int(s.get('height') or 0))

    fmt_dur = float(fmt['duration']) if fmt.get('duration') not in (None, 'N/A') else None
    str_dur = float(v['duration']) if v.get('duration') not in (None, 'N/A') else None
    duration = fmt_dur if fmt_dur is not None else (str_dur or 0.0)
    mismatch = abs(fmt_dur - str_dur) if (fmt_dur is not None and str_dur is not None) else 0.0

    r_fps = _parse_rate(v.get('r_frame_rate'))
    a_fps = _parse_rate(v.get('avg_frame_rate'))
    is_vfr = bool(r_fps > 0 and a_fps > 0 and abs(r_fps - a_fps) / r_fps > CFG.preflight.vfr_relative_tolerance)

    width  = int(v.get('width') or 0)
    height = int(v.get('height') or 0)
    rotation = _extract_rotation(v)
    apply_ccw = int((-rotation) % 360)
    if apply_ccw not in (0, 90, 180, 270):
        apply_ccw = int(round(apply_ccw / 90.0) * 90) % 360

    # Display dimensions swap when the rotation is a quarter turn.
    if apply_ccw in (90, 270):
        disp_w, disp_h = height, width
    else:
        disp_w, disp_h = width, height

    nb = v.get('nb_frames')
    a = astreams[0] if astreams else {}

    return MediaMeta(
        video_hash=video_hash or sha256_file(video_path),
        path=str(video_path),
        file_bytes=video_path.stat().st_size,
        container_format=fmt.get('format_name', ''),
        duration_seconds=duration,
        format_duration_seconds=fmt_dur,
        stream_duration_seconds=str_dur,
        duration_mismatch_seconds=round(mismatch, 4),
        width=width, height=height,
        coded_width=int(v.get('coded_width') or width),
        coded_height=int(v.get('coded_height') or height),
        display_width=disp_w, display_height=disp_h,
        aspect_ratio=round(disp_w / disp_h, 4) if disp_h else 0.0,
        is_vertical=bool(disp_h > disp_w),
        r_frame_rate=round(r_fps, 6),
        avg_frame_rate=round(a_fps, 6),
        is_vfr=is_vfr,
        nb_frames_declared=int(nb) if nb not in (None, 'N/A') else None,
        video_codec=v.get('codec_name', ''),
        pix_fmt=v.get('pix_fmt', ''),
        rotation=rotation,
        apply_rotation_ccw=apply_ccw,
        has_audio=bool(astreams),
        audio_codec=a.get('codec_name', ''),
        audio_sample_rate=int(a['sample_rate']) if a.get('sample_rate') else None,
        audio_channels=int(a['channels']) if a.get('channels') else None,
        probe_raw={'format': fmt, 'video_stream': v, 'audio_stream': a},
    )


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 160: print('probe.py loaded')
