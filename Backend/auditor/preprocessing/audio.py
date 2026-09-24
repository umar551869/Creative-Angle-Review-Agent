"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 16.
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
AUDIO_STAGE_VERSION = '1.0.0'

def extract_audio(video_path, out_path, meta: MediaMeta, cfg: AudioConfig) -> dict:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not meta.has_audio:
        return {'audio_path': None, 'has_audio': False,
                'reason': 'no audio stream in container', 'duration_seconds': 0.0,
                'extract_seconds': 0.0}

    t0 = time.time()
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-i', str(video_path),
        '-vn',
        '-ac', str(cfg.channels),
        '-ar', str(cfg.sample_rate),
        '-c:a', cfg.codec,
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not out_path.exists():
        return {'audio_path': None, 'has_audio': False,
                'reason': f'ffmpeg failed: {res.stderr.strip()[:300]}',
                'duration_seconds': 0.0, 'extract_seconds': round(time.time() - t0, 3)}

    n_bytes = out_path.stat().st_size
    # 16-bit mono PCM: bytes / (2 * channels * sample_rate) == seconds (minus a 44-byte header)
    seconds = max(0.0, (n_bytes - 44) / (2 * cfg.channels * cfg.sample_rate))

    return {
        'audio_path': str(out_path),
        'has_audio': True,
        'sample_rate': cfg.sample_rate,
        'channels': cfg.channels,
        'codec': cfg.codec,
        'file_bytes': n_bytes,
        'duration_seconds': round(seconds, 3),
        'duration_delta_vs_video': round(seconds - meta.duration_seconds, 3),
        'extract_seconds': round(time.time() - t0, 3),
    }


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 50: print('audio.py loaded')
