"""Load Phase 7 cells into a namespace carrying the notebook's real globals.

The point is to exercise the cells against the SAME names and shapes the
notebook provides, so a mismatch shows up here rather than in Colab.
"""
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
try:
    from rapidfuzz import fuzz
except ImportError:                                   # pragma: no cover
    from thefuzz import fuzz

CELLS = Path(r'C:\Users\Umar Ilyas\creative project\Phase 7\cells')

# ---- the notebook's real constants, copied verbatim from the notebook ------
PIPELINE_VERSION = '1.0.0'
PRIORITY_WEIGHT = {'critical': 3.0, 'high': 2.0, 'medium': 1.0, 'low': 0.5}
REQUIREMENT_TYPES = ('hook', 'visual', 'speech', 'speech_or_text',
                     'demonstration', 'audience', 'cta', 'policy', 'brand',
                     'timing', 'other')
VERDICT_STATUSES = ('PASS', 'PARTIAL', 'FAIL', 'UNCERTAIN', 'NOT_APPLICABLE')
EVAL_LAYERS = ('L1', 'L2', 'L3', 'gate')
ALIGNMENT_LEVELS = ('none', 'tangential', 'partial', 'strong', 'exact')
ALIGNMENT_WEIGHTS = {'exact': 1.0, 'strong': 0.85, 'partial': 0.55,
                     'tangential': 0.25, 'none': 0.0}
BRIEF_STANDING_LEVELS = ('off_brief', 'tangential', 'partial', 'on_brief',
                         'exemplary')
BRIEF_STANDING_WEIGHTS = {'exemplary': 1.0, 'on_brief': 0.85, 'partial': 0.55,
                          'tangential': 0.25, 'off_brief': 0.0}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)


def stage_key(stage, stage_version, inputs, config) -> str:
    import hashlib
    payload = {'stage': stage, 'stage_version': stage_version,
               'pipeline_version': PIPELINE_VERSION,
               'inputs': sorted(inputs), 'config': config}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:16]


def provenance(stage, stage_version, key, duration_s, **extra) -> dict:
    p = {'stage': stage, 'stage_version': stage_version,
         'pipeline_version': PIPELINE_VERSION, 'cache_key': key,
         'duration_seconds': round(duration_s, 4),
         'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    p.update(extra)
    return p


def write_json(path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), 'utf-8')


def read_json(path):
    """COPIED VERBATIM from the notebook. It RAISES on a missing file.

    An earlier version of this stub returned None instead, which is kinder
    than the real thing -- and that kindness hid a FileNotFoundError that
    crashed §75b on the user's first Colab run. A stub that is more forgiving
    than what it stands in for does not test the code, it tests the stub.
    """
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def make_ns(work: Path) -> dict:
    ns = dict(globals())
    ns['DIRS'] = {'root': work, 'artifacts': work / 'artifacts',
                  'inbox': work / 'inbox', 'runs': work / 'runs',
                  'exports': work / 'exports', 'briefs': work / 'briefs'}
    # The notebook imports `re` at cell 4, so every later cell has it. A
    # harness that withholds it tests a kernel that does not exist -- the same
    # mistake as the forgiving read_json. Provided here so no individual suite
    # has to remember.
    ns['re'] = re
    return ns


def load(ns: dict, *names) -> dict:
    for n in names:
        src = (CELLS / n).read_text('utf-8')
        try:
            exec(compile(src, n, 'exec'), ns)
        except Exception as exc:
            print(f'  !! {n} raised {type(exc).__name__}: {exc}')
            raise
    return ns
