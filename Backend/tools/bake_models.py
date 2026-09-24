"""Download the model weights ahead of first use.

Run at image BUILD time (see Dockerfile) so a cold container does not spend
its first request fetching ~1.8 GB from Hugging Face -- which on a
scale-to-zero platform dominates the runtime and looks like a hung job.

Also useful locally: run it once and the first real audit is not waiting on a
download.

NEVER FATAL. A Hub outage must not break an image build, and the runtime
downloads on demand anyway, so every failure here is a warning and exit 0.
Pass --strict to fail the build instead.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

STRICT = '--strict' in sys.argv


def _hf_token() -> None:
    """Optional, but it raises the download rate limit -- which is exactly
    what bites when pulling ~1.8 GB from a datacentre IP."""
    tok = (os.environ.get('HF_TOKEN', '')
           or os.environ.get('HUGGING_FACE_HUB_TOKEN', '')).strip()
    if tok:
        os.environ['HF_TOKEN'] = tok
        os.environ['HUGGING_FACE_HUB_TOKEN'] = tok
        print(f'  HF token set ({len(tok)} chars)')
    else:
        print('  HF: anonymous (fine -- these models are public, just '
              'rate-limited)')


def bake_whisper() -> bool:
    from faster_whisper import WhisperModel
    WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
    return True


def bake_bge() -> bool:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer('BAAI/bge-small-en-v1.5', device='cpu')
    return True


def bake_ocr() -> bool:
    """RapidOCR ships its ONNX models inside the wheel -- nothing to fetch.
    Instantiating it proves they are present and loadable."""
    from rapidocr_onnxruntime import RapidOCR
    RapidOCR()
    return True


TARGETS = [
    ('faster-whisper large-v3-turbo', '~1.6 GB', bake_whisper),
    ('BAAI/bge-small-en-v1.5', '~130 MB', bake_bge),
    ('RapidOCR (bundled, no download)', '-', bake_ocr),
]


def main() -> int:
    print('=' * 68)
    print('  MODEL BAKE')
    print(f'  HF_HOME = {os.environ.get("HF_HOME") or "(default ~/.cache)"}')
    print('=' * 68)
    _hf_token()
    failures = []
    for name, size, fn in TARGETS:
        t0 = time.time()
        print(f'\n  {name}  {size}')
        try:
            fn()
            print(f'    OK in {time.time() - t0:.0f}s')
        except Exception as exc:
            failures.append(name)
            print(f'    FAILED after {time.time() - t0:.0f}s: '
                  f'{type(exc).__name__}: {str(exc)[:160]}')

    print('\n' + '=' * 68)
    if failures:
        print(f'  {len(failures)} model(s) not cached: {", ".join(failures)}')
        print('  They will be downloaded on first use instead.')
        print('=' * 68)
        return 1 if STRICT else 0
    print('  All model weights cached.')
    print('=' * 68)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
