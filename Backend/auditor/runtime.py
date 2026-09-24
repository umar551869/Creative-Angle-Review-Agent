"""The shared namespace the pipeline modules live in.

WHY THIS EXISTS
---------------
The notebook runs 148 cells in one global namespace, and it binds some names
LATE on purpose -- `globals().get('make_vision_backend')` in pipeline_p3 is not
sloppiness, it is how a stage defined at cell 72 reaches a backend defined at
cell 68 without a hard import. Reconstructing an import graph the original
never had is the fastest way to change behaviour while believing you have not.

So the generated modules under auditor/ are executed, in notebook cell order,
into ONE namespace. That is the notebook's semantics, exactly, with the code
living in 71 reviewable files instead of one 2 MB JSON blob.

The public surface is auditor.api -- import that, not this.

JOB-SCOPED PATHS
----------------
`DIRS` is read by 37 notebook cells as a module-level dict. Per-request
isolation therefore cannot be done by passing a parameter without touching
every one of them. Instead DIRS is a mapping PROXY backed by a ContextVar: the
pipeline code keeps writing `DIRS['inbox']` and gets the paths belonging to the
job running on this task. Nothing downstream changes.

`artifacts` and `briefs` are deliberately SHARED across jobs, because they are
content-addressed: the same video under the same config produces the same
stage_key, so a private artifacts/ would throw away the cache that makes a
re-run cost nothing. `inbox` and `reports` are per-job, because a request owns
those bytes.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import types
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, Mapping

log = logging.getLogger('auditor.runtime')

# ---------------------------------------------------------------------------
# Job-scoped paths
# ---------------------------------------------------------------------------
_JOB_DIRS: ContextVar[dict[str, Path] | None] = ContextVar(
    'auditor_job_dirs', default=None)


def _data_root() -> Path:
    return Path(os.environ.get('AUDITOR_DATA_ROOT')
                or (Path.cwd() / 'data')).resolve()


def shared_dirs() -> dict[str, Path]:
    """Paths that every job shares. Content-addressed, so sharing is correct."""
    root = _data_root()
    return {
        'root': root,
        'artifacts': root / 'artifacts',
        'briefs': root / 'briefs',
        'runs': root / 'runs',
        'exports': root / 'exports',
        'inbox': root / 'inbox',        # default when no job is bound
        'reports': root / 'reports',
    }


def job_dirs(job_id: str, ephemeral: bool = False) -> dict[str, Path]:
    """Shared cache + this job's own inbox and reports.

    EPHEMERAL moves the artifact store under the job too, so the whole
    workspace can be deleted when the job ends. That is for platforms with no
    persistent volume (Hugging Face Spaces, Cloud Run without GCS).

    `briefs/` STAYS SHARED even then, and that asymmetry is the whole design:
    artifacts are an optimisation -- in production each video is audited once,
    so the cache rarely hits at all -- while the frozen brief compile is the
    only stored thing whose loss changes what a score MEANS. It is also about
    30 KB against 5-20 MB of artifacts per video.
    """
    d = shared_dirs()
    job = d['root'] / 'jobs' / job_id
    d['inbox'] = job / 'inbox'
    d['reports'] = job / 'reports'
    d['job'] = job
    if ephemeral:
        d['artifacts'] = job / 'artifacts'
        d['exports'] = job / 'exports'
        d['runs'] = job / 'runs'
    return d


class _DirsProxy(Mapping):
    """Looks and behaves like the notebook's dict. Resolves per task."""

    def _current(self) -> dict[str, Path]:
        return _JOB_DIRS.get() or shared_dirs()

    def __getitem__(self, key: str) -> Path:
        p = self._current()[key]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def __iter__(self) -> Iterator[str]:
        return iter(self._current())

    def __len__(self) -> int:
        return len(self._current())

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def setdefault(self, key: str, value: Any) -> Any:
        # Cell 88 does DIRS.setdefault('briefs', ...). shared_dirs already
        # supplies it; honour the call so the notebook line is still true.
        cur = self._current()
        if key not in cur:
            cur[key] = Path(value)
        return self[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._current()[key] = Path(value)

    def values(self):
        return [self[k] for k in self._current()]

    def items(self):
        return [(k, self[k]) for k in self._current()]

    def __repr__(self) -> str:
        return f'DIRS({ {k: str(v) for k, v in self._current().items()} })'


DIRS = _DirsProxy()


class use_job_dirs:
    """`with use_job_dirs(job_id):` binds DIRS for this task only."""

    def __init__(self, job_id: str, ephemeral: bool = False):
        self.dirs = job_dirs(job_id, ephemeral=ephemeral)
        self._token = None

    def __enter__(self) -> dict[str, Path]:
        for p in self.dirs.values():
            p.mkdir(parents=True, exist_ok=True)
        self._token = _JOB_DIRS.set(self.dirs)
        return self.dirs

    def __exit__(self, *exc) -> None:
        if self._token is not None:
            _JOB_DIRS.reset(self._token)


# ---------------------------------------------------------------------------
# The namespace
# ---------------------------------------------------------------------------
# A REAL MODULE, not a bare dict.
#
# @dataclass has to resolve annotations, and to do that it looks its own class
# up: `sys.modules.get(cls.__module__).__dict__`. Exec'ing into a plain dict
# gives every class a __module__ of 'auditor.notebook' that sys.modules has
# never heard of, so the lookup returns None and the decorator dies with
# "'NoneType' object has no attribute '__dict__'". Backing the namespace with
# an actual module object -- whose __dict__ IS the namespace -- makes the
# lookup find exactly the names the cells defined.
_NB_MODULE = types.ModuleType('auditor.notebook')
_NB_MODULE.__doc__ = ('The notebook namespace: 71 generated modules executed '
                      'in cell order.')
sys.modules['auditor.notebook'] = _NB_MODULE

NS: dict[str, Any] = _NB_MODULE.__dict__
_LOADED = False
_LOAD_LOCK = threading.Lock()
PKG_DIR = Path(__file__).resolve().parent


def _try_install(pkg: str, module: str | None = None) -> bool:
    """Is `module` importable? Never installs anything.

    The notebook's version pip-installs on demand, which is right for Colab
    and wrong for a server: a container that grows dependencies at runtime is
    one whose behaviour depends on when it was started. The dependency set is
    requirements.txt, pinned at build time.
    """
    import importlib

    name = module or pkg.replace('-', '_')
    try:
        importlib.import_module(name)
        return True
    except Exception:
        log.error('%s is not installed (import %s failed). This server does '
                  'not install packages at runtime -- add it to '
                  'requirements.txt and rebuild the image.', pkg, name)
        return False


def _seed() -> dict[str, Any]:
    """What cell 1 of the notebook would have left lying around."""
    import dataclasses
    import json as _json
    import math
    import re as _re
    import shutil
    import subprocess
    import sys
    import tempfile
    import textwrap
    import time
    import traceback
    import zipfile
    from collections import Counter, defaultdict
    from dataclasses import asdict, dataclass, field, replace
    from typing import (Any as _Any, Dict, Iterable, List, Optional, Tuple,
                        Union)

    ns: dict[str, Any] = {
        '__name__': 'auditor.notebook', '__builtins__': __builtins__,
        'os': os, 're': _re, 'json': _json, 'math': math, 'time': time,
        'sys': sys, 'shutil': shutil, 'subprocess': subprocess,
        'tempfile': tempfile, 'textwrap': textwrap, 'traceback': traceback,
        'zipfile': zipfile, 'logging': logging, 'threading': threading,
        'Path': Path, 'dataclasses': dataclasses, 'dataclass': dataclass,
        'field': field, 'asdict': asdict, 'replace': replace,
        'Counter': Counter, 'defaultdict': defaultdict,
        'Optional': Optional, 'List': List, 'Dict': Dict, 'Tuple': Tuple,
        'Any': _Any, 'Union': Union, 'Iterable': Iterable,
        'DIRS': DIRS,
        # A SERVER DOES NOT PIP-INSTALL AT RUNTIME.
        #
        # try_install() is a notebook affordance from §0.1 -- on Colab a
        # missing wheel should be fetched rather than stopping the run. That
        # cell is deliberately not extracted, but six call sites still call
        # the name DIRECTLY (l2.py, gemini.py, backends.py, config.py), and
        # without a binding each of those is a NameError waiting for the
        # first request that reaches it -- which is how the L2 rung and the
        # vision backend would have failed.
        #
        # So it is bound to something honest: check whether the module is
        # importable, and if it is not, say which package is missing and that
        # the fix is requirements.txt, not a runtime download.
        'try_install': _try_install,
        # ---- names from cells this deployment deliberately does not run ----
        # Each is read by code on a path the server never takes, and each
        # would be a NameError if that path were ever reached. Seeded with
        # the value the notebook itself has when the same path is off, so the
        # behaviour is identical rather than merely non-crashing.
        #
        # §0.3 with USE_DRIVE = False. Read by restore_exports_from_drive();
        # there is no Google Drive in a container.
        'DRIVE_ROOT': None,
        # §20.1/§20.2, the LOCAL Qwen vision path. It is extracted but
        # unwired (AUDITOR_VISION_PROVIDER=gemini), and an empty registry
        # makes an attempt to use it fail as "no local model available"
        # rather than as a missing global.
        'VLM_CLASSES': {},
        'P3_GPU_GB': 0.0,
    }
    # Optional heavy deps: the notebook imports them at cell 3 and several
    # stages degrade rather than fail when one is missing. Same here.
    for name, mod in (('np', 'numpy'), ('pd', 'pandas'), ('cv2', 'cv2'),
                      ('torch', 'torch'), ('PIL', 'PIL')):
        try:
            ns[name] = __import__(mod)
        except Exception:
            ns[name] = None
    return ns


def load(verbose: bool = False) -> dict[str, Any]:
    """Execute every generated module, in notebook cell order, once."""
    global _LOADED
    with _LOAD_LOCK:
        if _LOADED:
            return NS
        from auditor._load_order import LOAD_ORDER
        NS.update(_seed())
        for rel in LOAD_ORDER:
            path = PKG_DIR / rel
            if not path.exists():
                raise RuntimeError(
                    f'{rel} is in LOAD_ORDER but not on disk. Re-run '
                    f'Backend/tools/extract_from_notebook.py')
            src = path.read_text(encoding='utf-8')
            try:
                exec(compile(src, str(path), 'exec'), NS)
            except Exception as exc:
                raise RuntimeError(
                    f'auditor module {rel} failed to load: '
                    f'{type(exc).__name__}: {exc}') from exc
            if verbose:
                log.debug('loaded %s', rel)
        _LOADED = True
        log.info('auditor namespace loaded: %d modules, %d names',
                 len(LOAD_ORDER), len(NS))
        return NS


def get(name: str, default: Any = None) -> Any:
    """One name out of the pipeline namespace."""
    return load().get(name, default)


def require(name: str) -> Any:
    """Like get(), but says which module was supposed to define it."""
    v = load().get(name)
    if v is None:
        raise RuntimeError(
            f'{name!r} is not defined in the auditor namespace. Either the '
            f'notebook cell defining it is missing from CELL_MAP in '
            f'Backend/tools/extract_from_notebook.py, or it was dropped as a '
            f'driver statement.')
    return v
