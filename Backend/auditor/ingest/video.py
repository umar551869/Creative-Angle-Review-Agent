"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 5.
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
# ============================================================================
# §0.4  BATCH INPUT  —  PASTE LINKS (below), or upload a .zip
#
# TWO ways in, and the links win: fill VIDEO_URLS a few lines down and the
# notebook fetches them itself. Leave it empty and you get the upload prompt.
#
# This must run BEFORE Phase 1, because every later stage discovers its work
# from DIRS['inbox']. Either way, re-running reuses what is already there
# rather than asking again.
#
# Accepts a .zip of video files, or loose video files. Nested folders are
# fine -- the extractor walks them and flattens. macOS resource forks
# (__MACOSX, ._name) are skipped: they are not videos and ffprobe chokes on
# them with a confusing error.
# ============================================================================
import re

import shutil

import zipfile

# TikTok increasingly refuses anonymous downloads. If links fail with an
# extraction or login error, export cookies from a logged-in browser
# (extension: "Get cookies.txt LOCALLY"), upload the file to Colab, and put
# its path here. Left empty = try without cookies, which often still works.
COOKIES_FILE = ''

VIDEO_SUFFIXES = {'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}

# Set to True to clear the inbox first. OFF by default: a batch run that
# silently deletes the videos from a previous run is a bad surprise.
CLEAR_INBOX_FIRST = False

def _is_video(name: str) -> bool:
    p = Path(name)
    if p.name.startswith('._') or '__MACOSX' in name:
        return False
    return p.suffix.lower() in VIDEO_SUFFIXES

def extract_zip_to_inbox(zip_path: Path, verbose: bool = True) -> list:
    """Flatten every video out of a zip into the inbox. Returns the new paths."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir() or not _is_video(info.filename):
                continue
            # LOWERCASE THE SUFFIX. preprocess_folder() globs '*.mp4',
            # '*.mov' ... and glob is case-SENSITIVE on Linux, so a file
            # arriving as "clip.MOV" would sit in the inbox, never get a
            # Phase 1 manifest, never appear in discover_videos(), and be
            # silently missing from the batch. Renaming here is the cheapest
            # place to close that.
            _n = Path(info.filename).name
            dest = DIRS['inbox'] / (Path(_n).stem + Path(_n).suffix.lower())
            if dest.exists():
                if verbose:
                    print(f'    already present, keeping: {dest.name}')
                out.append(dest)
                continue
            with z.open(info) as fsrc, open(dest, 'wb') as fdst:
                shutil.copyfileobj(fsrc, fdst)
            out.append(dest)
            if verbose:
                print(f'    extracted: {dest.name}  '
                      f'({dest.stat().st_size / 1e6:.1f} MB)')
    return out

# ---------------------------------------------------------------------------
# Fetching the links pasted at the top of this cell.
# ---------------------------------------------------------------------------
def _ytdlp():
    """yt-dlp, installed on first use. None if it cannot be had."""
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print('  installing yt-dlp (once per runtime) ...')
        import subprocess
        subprocess.run(['pip', 'install', '-q', '--upgrade', 'yt-dlp'],
                       capture_output=True, timeout=300)
        try:
            import yt_dlp
            return yt_dlp
        except ImportError:
            return None

def download_videos(urls: list, verbose: bool = True) -> list:
    """Fetch each URL into the inbox. Returns the paths that arrived.

    NEVER RAISES, and never stops on the first failure: a private, deleted or
    region-locked link is normal in a list of twenty, and it must cost you
    that one video rather than the whole batch. Every failure is named at the
    end so you can see which link to replace.
    """
    urls = [u.strip() for u in (urls or []) if u.strip().startswith('http')]
    if not urls:
        return []
    mod = _ytdlp()
    if mod is None:
        print('  yt-dlp unavailable -- cannot fetch links. Upload the files '
              'instead.')
        return []
    # Two format strings, tried in order. 'mp4/best[ext=mp4]/best' asks for a
    # progressive mp4 and TikTok does not always offer one -- when it does
    # not, yt-dlp raises rather than taking what is there. Plain 'best' is
    # the fallback, with a browser UA because a default python UA is the
    # easiest thing in the world for a CDN to refuse.
    _UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
    _FORMATS = ['mp4/best[ext=mp4]/best', 'best']
    got, failed = [], []
    for u in urls:
        # SNAPSHOT THE INBOX, do not trust prepare_filename(). It returns the
        # name yt-dlp INTENDED before any merge or remux, so a file that
        # arrives as .mp4 after a merge can be reported missing and a
        # successful download counted as a failure. Diffing the directory
        # cannot be wrong about what actually landed.
        _before = {p.name for p in DIRS['inbox'].iterdir() if p.is_file()}
        _err, _vid = None, ''
        for _fmt in _FORMATS:
            try:
                opts = {'outtmpl': str(DIRS['inbox'] / '%(id)s.%(ext)s'),
                        'format': _fmt,
                        'quiet': True, 'no_warnings': True, 'noprogress': True,
                        'merge_output_format': 'mp4',
                        'http_headers': {'User-Agent': _UA},
                        'retries': 3, 'socket_timeout': 30}
                if COOKIES_FILE and Path(COOKIES_FILE).exists():
                    opts['cookiefile'] = COOKIES_FILE
                with mod.YoutubeDL(opts) as ydl:
                    _info = ydl.extract_info(u, download=True) or {}
                _vid = str(_info.get('id') or '')
                _err = None
                break
            except Exception as exc:
                _err = f'{type(exc).__name__}: {str(exc)[:220]}'
        _after = {p.name for p in DIRS['inbox'].iterdir() if p.is_file()}
        _new = [DIRS['inbox'] / n for n in (_after - _before) if _is_video(n)]
        _had = False
        if not _new and not _vid:
            # Every format raised, so there is no resolved id -- but the clip
            # may still be in the inbox from an earlier run, and a link you
            # already have should not fail just because TikTok started
            # refusing you today. The trailing digits of the URL are the id.
            _m = re.search(r'(\d{6,})(?:\?|$|/)', u)
            _vid = _m.group(1) if _m else ''
        if not _new and _vid:
            # NOTHING NEW IS NOT THE SAME AS NOTHING THERE. yt-dlp skips a
            # file it already has, so on a re-run it succeeds silently and the
            # directory diff is empty -- which the first version of this read
            # as a failure and reported as "no new file appeared", on three
            # videos that were sitting in the inbox the whole time. The id
            # yt-dlp resolved is the authority: if a video with that id is
            # present, the link is SATISFIED, whoever put it there.
            _new = [DIRS['inbox'] / n for n in sorted(_after)
                    if _is_video(n) and Path(n).stem == _vid]
            _had = bool(_new)
        if _new:
            got.extend(_new)
            if verbose:
                for _p in _new:
                    print(f'  {"HAVE" if _had else "OK  "}  {_p.name:<26} '
                          f'{_p.stat().st_size / 1e6:>6.1f} MB   '
                          f'{"already in the inbox" if _had else u[:44]}')
        else:
            failed.append((u, _err or 'yt-dlp reported success but no video '
                                      'with that id is in the inbox'))
            if verbose:
                print(f'  FAIL  {u}')
    if failed:
        print()
        print(f'  {len(failed)} of {len(urls)} link(s) did not download:')
        for u, why in failed:
            print(f'     {u}')
            print(f'        {why}')
        if len(failed) == len(urls):
            # ALL of them. That is not N unlucky links, it is one cause.
            print()
            print('  EVERY link failed, so this is one cause, not bad luck:')
            print('    - TikTok often needs a login/cookie now. Export cookies')
            print('      from your browser into COOKIES_FILE at the top of')
            print('      THIS cell, or')
            print('    - the runtime cannot reach TikTok, or')
            print('    - yt-dlp is out of date for TikTok\'s current site.')
            print('      Fix: !pip install -U yt-dlp   then re-run this cell.')
            print('    The full error is printed above -- it names which.')
    return got


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 27: VIDEO_URLS = '\n'.split()
#   line 79: DIRS['inbox'].mkdir(parents=True, exist_ok=True)
#   line 80: if CLEAR_INBOX_FIRST:
#   line 212: if VIDEO_URLS:
#   line 232: _existing = [f for f in DIRS['inbox'].iterdir() if f.is_file() and _is_video
#   line 234: print(f'§0.4  inbox holds {len(_existing)} video(s) already.')
#   line 236: if _existing:
#   line 261: _videos_in = sorted((f for f in DIRS['inbox'].iterdir() if f.is_file() and _
#   line 263: print()
#   line 264: print(f'  READY: {len(_videos_in)} video(s) in the inbox')
#   line 265: for _f in _videos_in:
#   line 267: if not _videos_in:
