"""Find ffmpeg and ffprobe, and make the server process able to run them.

WHY THIS EXISTS
---------------
ffmpeg is the one dependency that is not pip-installable, and the first thing
a job touches: Phase 1 probes the container with ffprobe before it decodes
anything. Without it every job dies in Phase 1 while `/health` cheerfully
reports 200 -- which is the worst shape a failure can take, because the
platform sees a healthy container and the operator sees jobs that fail for no
stated reason.

Two separate problems, and only one of them is "not installed":

1. NOT INSTALLED. Nothing to do but say so, clearly, at startup and on
   /ready rather than fifty seconds into a job.

2. INSTALLED BUT INVISIBLE. On Windows this is the common case and it looks
   identical from inside the process. `winget install Gyan.FFmpeg` writes the
   binaries under %LOCALAPPDATA%\\Microsoft\\WinGet\\Packages and appends that
   directory to the USER PATH -- but a shell, terminal or service that was
   already running keeps the environment it started with. So `ffmpeg -version`
   works in a new terminal and `shutil.which('ffmpeg')` returns None in the
   server, and the two observations look contradictory.

So: look on PATH first, then in the places these installers actually use, and
prepend whatever is found to this process's PATH. Subprocesses inherit it,
which is all the pipeline needs -- nothing is copied, moved or installed.

AUDITOR_FFMPEG_DIR overrides the search for an unusual install.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger('audit.media')

BINARIES = ('ffmpeg', 'ffprobe')


def _candidate_dirs() -> list[Path]:
    """Where these binaries actually land, per platform installer."""
    explicit = os.environ.get('AUDITOR_FFMPEG_DIR', '').strip()
    out: list[Path] = [Path(explicit)] if explicit else []

    if sys.platform == 'win32':
        local = Path(os.environ.get('LOCALAPPDATA', ''))
        if local.name:
            # winget unpacks into a versioned directory, so glob rather than
            # guess: ffmpeg-9.0.2-full_build/bin today, another version
            # tomorrow, and pinning the version would rot on first upgrade.
            pkgs = local / 'Microsoft' / 'WinGet' / 'Packages'
            if pkgs.is_dir():
                out += sorted(pkgs.glob('Gyan.FFmpeg*/*/bin'), reverse=True)
            out.append(local / 'Microsoft' / 'WinGet' / 'Links')
        for base in (os.environ.get('ProgramData', ''),
                     os.environ.get('ProgramFiles', '')):
            if base:
                out += [Path(base) / 'chocolatey' / 'bin',
                        Path(base) / 'ffmpeg' / 'bin']
    else:
        out += [Path('/usr/bin'), Path('/usr/local/bin'),
                Path('/opt/homebrew/bin'), Path('/snap/bin')]
    return out


def resolve() -> dict:
    """Locate both binaries, extending PATH if needed. Never raises.

    Returns {'ffmpeg': str|None, 'ffprobe': str|None, 'added': str|None,
             'missing': [names]}.
    """
    found = {b: shutil.which(b) for b in BINARIES}
    added = None
    if not all(found.values()):
        for d in _candidate_dirs():
            try:
                if not d.is_dir():
                    continue
            except OSError:
                continue
            hits = {b: shutil.which(b, path=str(d)) for b in BINARIES}
            if not any(hits.values()):
                continue
            # Prepend once. Appending would let a broken copy earlier on PATH
            # keep winning, which is the bug this is here to fix.
            os.environ['PATH'] = str(d) + os.pathsep + os.environ.get('PATH',
                                                                      '')
            added = str(d)
            found = {b: shutil.which(b) for b in BINARIES}
            if all(found.values()):
                break
    return {**found, 'added': added,
            'missing': [b for b in BINARIES if not found[b]]}


_STATUS: dict | None = None


def status(refresh: bool = False) -> dict:
    """Cached resolve(). PATH is mutated once per process, not per request."""
    global _STATUS
    if _STATUS is None or refresh:
        _STATUS = resolve()
        if _STATUS['added']:
            log.info('ffmpeg found outside PATH, added %s for this process. '
                     'Nothing was installed or moved.', _STATUS['added'])
        for name in _STATUS['missing']:
            log.error('%s NOT FOUND. Phase 1 probes and extracts audio with '
                      'it, so every job will fail there. Install it, or set '
                      'AUDITOR_FFMPEG_DIR to the directory holding it.', name)
    return _STATUS


def install_hint() -> str:
    return {'win32': 'winget install Gyan.FFmpeg',
            'darwin': 'brew install ffmpeg'}.get(
                sys.platform, 'apt-get install ffmpeg')
