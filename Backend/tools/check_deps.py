"""Can this machine actually run the pipeline, or only import the API?

Imports every runtime dependency and probes for the two BINARIES that are not
pip-installable. A missing ffmpeg is the classic one: everything imports, the
server starts, /health says ok, and the first job dies in Phase 1.
"""
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# (import name, what it is for, required?)
DEPS = [
    ('fastapi', 'API layer', True),
    ('uvicorn', 'ASGI server', True),
    ('pydantic', 'request/response models', True),
    ('numpy', 'everywhere', True),
    ('pandas', 'stage tables', True),
    ('cv2', 'Phase 1 decode (opencv)', True),
    ('av', 'Phase 1 decode (PyAV)', True),
    ('PIL', 'frames -> JPEG for the vision call', True),
    ('rapidfuzz', 'text matching', True),
    ('faster_whisper', 'Phase 2 ASR (CTranslate2)', True),
    ('rapidocr_onnxruntime', 'Phase 2 OCR', True),
    ('google.genai', 'Gemini: vision, brief compile, L3', True),
    ('sentence_transformers', 'Phase 6 L2 embedding rung', True),
    ('torch', 'backs sentence-transformers', True),
    ('yt_dlp', 'video ingestion', True),
    ('requests', 'Google Doc fetch', True),
    ('matplotlib', 'imported by notebook cell 3', True),
    ('openai', 'PAID fallback only', False),
    ('wordninja', 'OCR space restoration (degrades without)', False),
    ('transformers', 'ASR fallback path', False),
]

BINARIES = [
    ('ffmpeg', 'Phase 1 audio extraction and remux'),
    ('ffprobe', 'Phase 1 container probe -- the FIRST thing a job does'),
]


def main() -> int:
    print('=' * 70)
    print('  DEPENDENCY CHECK')
    print('=' * 70)
    print(f'  python {sys.version.split()[0]}   {sys.executable}')
    print()
    missing_req, missing_opt = [], []
    for mod, what, required in DEPS:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, '__version__', '')
            print(f'  OK     {mod:<26} {str(ver)[:12]:<14} {what}')
        except Exception as exc:
            (missing_req if required else missing_opt).append(mod)
            tag = 'MISSING' if required else 'absent '
            print(f'  {tag}  {mod:<26} {"":<14} {what}')
            if required:
                print(f'           {type(exc).__name__}: {str(exc)[:70]}')

    print()
    # THE SAME RESOLVER THE SERVER USES. Checking with a bare shutil.which()
    # here made the tool disagree with the running app: on Windows, winget
    # installs ffmpeg and appends its directory to the USER PATH, so a shell
    # that predates the install reports MISSING while a new terminal -- and a
    # server that ran app.media.status() -- finds it. Two answers to one
    # question is worse than either answer.
    from app.media import status as media_status

    _media = media_status()
    if _media['added']:
        print(f'  note   ffmpeg is not on the inherited PATH; found it in\n'
              f'         {_media["added"]}\n'
              f'         The server does this too, so jobs will run. Open a '
              f'new terminal to get it in your shell.')

    missing_bin = []
    for exe, what in BINARIES:
        path = shutil.which(exe)
        if path:
            try:
                out = subprocess.run([exe, '-version'], capture_output=True,
                                     text=True, timeout=20)
                ver = (out.stdout or out.stderr).splitlines()[0][:44]
            except Exception:
                ver = '(version unreadable)'
            print(f'  OK     {exe:<26} {ver}')
        else:
            missing_bin.append(exe)
            print(f'  MISSING  {exe:<24} {what}')

    # The pipeline namespace is the real integration test of all of it.
    print()
    try:
        from auditor import runtime
        ns = runtime.load()
        print(f'  OK     pipeline namespace loads  ({len(ns)} names)')
    except Exception as exc:
        print(f'  FAILED pipeline namespace: {type(exc).__name__}: {exc}')
        missing_req.append('auditor namespace')

    print()
    print('=' * 70)
    if missing_req or missing_bin:
        if missing_req:
            print(f'  {len(missing_req)} REQUIRED package(s) missing: '
                  f'{", ".join(missing_req)}')
            print(f'     pip install -r requirements.txt')
        if missing_bin:
            print(f'  {len(missing_bin)} BINARY missing: '
                  f'{", ".join(missing_bin)}')
            print('     ffmpeg is NOT pip-installable. Without it every job')
            print('     dies in Phase 1 while /health still says ok.')
            print('     Windows: winget install Gyan.FFmpeg')
            print('     macOS:   brew install ffmpeg')
            print('     Linux:   apt-get install ffmpeg')
        print('=' * 70)
        return 1
    if missing_opt:
        print(f'  optional, absent: {", ".join(missing_opt)} '
              f'(each degrades, none blocks)')
    print('  READY -- every required dependency is present.')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
