"""Is the Backend still intact after a run of notebook changes?

Deeper than the test suite on purpose. The tests assert the contract; this
asks whether the GENERATED layer still matches the notebook it came from, and
whether anything that should have survived extraction quietly did not.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tools'))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

NB = ROOT / 'Phase 7' / 'phases_1_to_7_BATCH.ipynb'
fails: list[str] = []
warns: list[str] = []


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'  {"PASS" if ok else "FAIL"}  {label}'
          + (f'   {detail}' if detail else ''))
    if not ok:
        fails.append(label)
    return ok


print('=' * 74)
print('  BACKEND AUDIT')
print('=' * 74)

# ---------------------------------------------------------------------------
print('\n1. IS THE GENERATED LAYER CURRENT WITH THE NOTEBOOK?')
# ---------------------------------------------------------------------------
from extract_from_notebook import CELL_MAP, EXCLUDED, is_definition  # noqa

nb = json.loads(NB.read_text(encoding='utf-8'))
code = [''.join(c['source'])
        for c in nb['cells'] if c['cell_type'] == 'code']
check('every notebook cell is mapped or excluded',
      not [n for n in range(1, len(code) + 1)
           if n not in CELL_MAP and n not in EXCLUDED],
      f'{len(code)} cells, {len(CELL_MAP)} mapped, {len(EXCLUDED)} excluded')

# Re-derive each module from the notebook and compare to what is on disk.
# If they differ, the package is stale -- which is invisible until a stage
# behaves like last week's notebook.
stale = []
for n, rel in sorted(CELL_MAP.items()):
    dest = HERE / 'auditor' / rel
    if not dest.exists():
        stale.append(f'{rel} MISSING')
        continue
    on_disk = dest.read_text(encoding='utf-8')
    for node in ast.parse(code[n - 1]).body:
        if not is_definition(node):
            continue
        seg = ast.get_source_segment(code[n - 1], node) or ''
        head = seg.splitlines()[0].strip() if seg else ''
        if head and head not in on_disk:
            stale.append(f'{rel} <- cell {n}: {head[:56]}')
check('every kept definition is present on disk', not stale,
      f'{len(CELL_MAP)} cells -> {len({v for v in CELL_MAP.values()})} modules')
for s in stale[:8]:
    print(f'          {s}')

# ---------------------------------------------------------------------------
print('\n2. DOES THE NAMESPACE LOAD, AND WITH WHAT?')
# ---------------------------------------------------------------------------
from auditor import runtime  # noqa: E402

ns = runtime.load()
from auditor._load_order import LOAD_ORDER  # noqa: E402

check('all modules load', len(LOAD_ORDER) > 60,
      f'{len(LOAD_ORDER)} modules, {len(ns)} names')
check('no module missing from disk',
      all((HERE / 'auditor' / r).is_file() for r in LOAD_ORDER))

# ---------------------------------------------------------------------------
print('\n3. DID THE RECENT NOTEBOOK FIXES SURVIVE EXTRACTION?')
# ---------------------------------------------------------------------------
RECENT = [
    ('64a  ensure_hf_token defined', 'ensure_hf_token', 'callable'),
    ('65   discover_vision_models', 'discover_vision_models', 'callable'),
    ('65b  _NOT_VISION_RE constant', '_NOT_VISION_RE', 'object'),
    ('65   VISION_PROBE_MAX', 'VISION_PROBE_MAX', 'object'),
    ('58   autoselect keeps the ladder', 'autoselect_vision_model',
     'callable'),
    ('61   probe demotes, not deletes', 'probe_vision_models', 'callable'),
    ('50   named_brief_angles', 'named_brief_angles', 'callable'),
    ('50   _clean_concept_fit', '_clean_concept_fit', 'callable'),
]
for label, name, kind in RECENT:
    v = ns.get(name)
    ok = (callable(v) if kind == 'callable' else v is not None)
    check(label, ok)

src68 = (HERE / 'auditor' / 'vision' / 'gemini.py').read_text(encoding='utf-8')
src21 = (HERE / 'auditor' / 'asr' / 'whisper.py').read_text(encoding='utf-8')
src123 = (HERE / 'auditor' / 'audit' / 'l2.py').read_text(encoding='utf-8')
check('64a  ensure_hf_token() called before WhisperModel',
      'ensure_hf_token()          # before the first weights fetch' in src21)
check('64b  BGE load resolves the token too',
      'BGE comes off the Hub too' in src123)
check('64c  HF is NOT in the API-keys module',
      'HF_TOKEN' not in (HERE / 'auditor' / 'secrets.py').read_text(
          encoding='utf-8'))
check('66   filter drops image-generation families',
      'nano-banana' in src68 and '-image$' in src68)
check('67   PIN keeps a ladder', 'A PIN is an ORDER, not a restriction'
      in src68)

# ---------------------------------------------------------------------------
print('\n4. BEHAVIOUR OF THE EXTRACTED CODE (not the notebook)')
# ---------------------------------------------------------------------------
RE = ns['_NOT_VISION_RE']
drop = ['lyria-3.5', 'nano-banana-pro-preview', 'gemini-2.5-flash-image',
        'gemini-3.5-transcribe', 'deep-research-preview-04-2026',
        'antigravity-preview-latest', 'gemini-robotics-er-2-preview',
        'gemini-2.5-computer-use-preview-10-2025', 'text-embedding-004']
keep = ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-2.5-pro',
        'gemini-flash-lite-latest', 'gemini-3.8-flash']
check('filter drops every non-vision family',
      all(RE.search(m) for m in drop))
check('filter keeps every real vision model',
      not any(RE.search(m) for m in keep))

rank = ns['_vision_model_rank']
ordered = sorted(keep, key=rank)
check('ranking is cheap-first', ordered[0] == 'gemini-3.5-flash-lite'
      and ordered[-1] == 'gemini-2.5-pro', str(ordered))

check('discover_vision_models returns [] with no key (so caller falls back)',
      ns['discover_vision_models'](verbose=False) == [])

# PIN must never produce a one-model ladder again.
import dataclasses  # noqa: E402

VC = type(ns['P3'].vision)
saved = ns.get('PIN_VISION_MODEL')
try:
    ns['PIN_VISION_MODEL'] = 'gemini-3.5-flash-lite'
    out = ns['autoselect_vision_model'](ns['P3'].vision, verbose=False)
    lad = tuple(out.gemini_models)
    check('PIN leads the ladder', lad and lad[0] == 'gemini-3.5-flash-lite',
          str(lad))
    check('PIN still has fallbacks (fix 58 not undone)', len(lad) > 1)
    check('no duplicate rung', len(set(lad)) == len(lad))
finally:
    ns['PIN_VISION_MODEL'] = saved

hf = ns['ensure_hf_token']
import os  # noqa: E402
_old = os.environ.pop('HF_TOKEN', None)
os.environ.pop('HUGGING_FACE_HUB_TOKEN', None)
check('ensure_hf_token: False and no crash without a token',
      hf(verbose=False) is False)
os.environ['HF_TOKEN'] = 'hf_' + 'k' * 34
check('ensure_hf_token: mirrors to the long name',
      hf(verbose=False) is True
      and os.environ.get('HUGGING_FACE_HUB_TOKEN') == os.environ['HF_TOKEN'])
os.environ.pop('HF_TOKEN')
os.environ.pop('HUGGING_FACE_HUB_TOKEN', None)
if _old:
    os.environ['HF_TOKEN'] = _old

# ---------------------------------------------------------------------------
print('\n5. NOTHING RUNS AT IMPORT')
# ---------------------------------------------------------------------------
# The SAME rule the extractor uses, imported rather than restated. Comparing
# against the outermost func reported `textwrap.dedent(...).strip()` as a
# driver, because the outer func is the whole dedent() expression -- and two
# copies of a rule that must agree will eventually disagree.
sys.path.insert(0, str(HERE / 'tools'))
from extract_from_notebook import (CONSTANT_BUILDERS,  # noqa: E402
                                   SAFE_CONSTANT_CALLS, _call_root)

ALLOWED = CONSTANT_BUILDERS | SAFE_CONSTANT_CALLS

offenders = []
for p in sorted((HERE / 'auditor').rglob('*.py')):
    if p.name in ('runtime.py', '_load_order.py', '__init__.py'):
        continue
    for node in ast.parse(p.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            offenders.append(f'{p.name}:{node.lineno} bare call')
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            head = _call_root(node.value)
            if head not in ALLOWED and not head.endswith('Config'):
                offenders.append(f'{p.name}:{node.lineno} = {head}(...)')
check('no module-level statement does work', not offenders,
      '; '.join(offenders[:4]))

# ---------------------------------------------------------------------------
print('\n5b. EVERY NAME THE KEPT CODE USES ACTUALLY RESOLVES')
# The check that would have caught PROMPT_P4_INSTRUCTIONS being dropped.
#
# The structural counts (decorators, classes, functions) cannot see a lost
# CONSTANT, because dropping module-level assignments is exactly what the
# extractor is supposed to do to drivers. So instead: every global name the
# surviving code READS must exist in the loaded namespace. A dropped constant
# whose usage survived shows up here as an unresolved name, instead of as a
# NameError twelve minutes into the first real job.
import builtins  # noqa: E402

_KNOWN = set(dir(builtins)) | set(ns) | {
    '__name__', '__doc__', '__file__', '__builtins__', 'self', 'cls'}
unresolved: dict[str, set[str]] = {}
for path in sorted((HERE / 'auditor').rglob('*.py')):
    if path.name in ('runtime.py', '_load_order.py', '__init__.py'):
        continue
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        continue
    local: set[str] = set()
    for nd in ast.walk(tree):
        if isinstance(nd, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef, ast.Lambda)):
            # Lambda too: `sort(key=lambda x: -x[1])` was reporting `x` as an
            # unresolved global. A checker with false positives is one people
            # learn to skim.
            local.add(getattr(nd, 'name', ''))
            args = getattr(nd, 'args', None)
            if args:
                for a in (args.args + args.kwonlyargs + args.posonlyargs):
                    local.add(a.arg)
                for a in (args.vararg, args.kwarg):
                    if a:
                        local.add(a.arg)
        elif isinstance(nd, ast.Name) and isinstance(nd.ctx, (ast.Store,
                                                              ast.Del)):
            local.add(nd.id)
        elif isinstance(nd, (ast.Import, ast.ImportFrom)):
            for a in nd.names:
                local.add((a.asname or a.name).split('.')[0])
        elif isinstance(nd, ast.ExceptHandler) and nd.name:
            local.add(nd.name)
        elif isinstance(nd, (ast.comprehension,)):
            for sub in ast.walk(nd.target):
                if isinstance(sub, ast.Name):
                    local.add(sub.id)
    for nd in ast.walk(tree):
        if isinstance(nd, ast.Name) and isinstance(nd.ctx, ast.Load):
            if nd.id not in local and nd.id not in _KNOWN:
                unresolved.setdefault(path.name, set()).add(nd.id)
check('no name is used that the namespace cannot provide', not unresolved,
      '; '.join(f'{k}: {sorted(v)[:4]}' for k, v in
                list(unresolved.items())[:3]))

print('\n6. DESIGN RULES STILL ASSERTED IN CODE')
# ---------------------------------------------------------------------------
score = (HERE / 'auditor' / 'scoring' / 'score.py').read_text(encoding='utf-8')
check('no model writes the number',
      not any(k in score for k in ('generate_content', 'client.models',
                                   'OpenAI(', 'chat.completions')))
check('scoring never reads concept_fit', 'concept_fit' not in score)

# ---------------------------------------------------------------------------
print('\n7. SECRET HYGIENE')
# ---------------------------------------------------------------------------
# EVERY shape, not just AIza. This scanner passed a file containing 45
# characters of a live Google key because KEYPAT did not know the AQ. format
# -- the same gap that had just been fixed in the log redactor and not here.
# A secret scanner is only as good as its least-known vendor format, and the
# formats have to be kept in step across both places.
KEYPAT = re.compile(r'AIza[0-9A-Za-z_\-]{30,}|AQ\.[A-Za-z0-9_\-]{20,}'
                    r'|ya29\.[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9_\-]{20,}'
                    r'|hf_[A-Za-z0-9]{30,}')

# A REAL key is high-entropy. A fixture is typed by a human and shows it:
# 'abcdef', '123456', 'qrstuv', or a long run of one character. The chance of
# any of those appearing inside a genuine random key is negligible, so this
# distinguishes the two without becoming a loophole that hides a real one.
SYNTHETIC = re.compile(r'abcdef|bcdefg|123456|234567|qrstuv|wxyz|(.)\1{5,}',
                       re.I)
# .env is where a real key BELONGS and is gitignored; scanning it would make
# this check fail exactly when the deployment is configured correctly.
# .pytest_cache holds copies of test parameters, so it inherits whatever the
# tests contain rather than being a source of truth.
SKIP_PARTS = {'.venv', '__pycache__', 'data', '.pytest_cache', '.git'}
SKIP_NAMES = {'.env'}
leaked = []
for p in sorted(HERE.rglob('*')):
    if not p.is_file() or SKIP_PARTS & set(p.parts) or p.name in SKIP_NAMES:
        continue
    if p.suffix not in ('.py', '.md', '.txt', '.example', '.json', '.yaml',
                        '.toml', ''):
        continue
    try:
        t = p.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        continue
    for m in KEYPAT.finditer(t):
        if SYNTHETIC.search(m.group(0)):
            continue                     # a hand-typed test fixture
        leaked.append(f'{p.relative_to(HERE)}: {m.group(0)[:12]}...')
check('no REAL API key anywhere in Backend/', not leaked,
      '; '.join(leaked[:3]))
# And prove the detector is not simply blind: the fixtures must be FOUND and
# then classified, not missed. A check that cannot fail is not a check.
fixtures = [m.group(0) for m in KEYPAT.finditer(
    (HERE / 'tests' / 'test_api.py').read_text(encoding='utf-8'))]
check('...and the detector does see the test fixtures (then excuses them)',
      len(fixtures) >= 2 and all(SYNTHETIC.search(f) for f in fixtures),
      f'{len(fixtures)} synthetic')
check('.env is gitignored',
      '.env' in (HERE / '.gitignore').read_text(encoding='utf-8'))
check('.env.example has no value after HF_TOKEN=',
      re.search(r'^HF_TOKEN=\s*$',
                (HERE / '.env.example').read_text(encoding='utf-8'), re.M)
      is not None)

# ---------------------------------------------------------------------------
print('\n8. THE APP LAYER')
# ---------------------------------------------------------------------------
for rel in ('app/main.py', 'app/config.py', 'app/schemas.py', 'app/jobs.py',
            'app/logging_setup.py', 'app/services/pipeline.py',
            'app/services/ingest.py'):
    p = HERE / rel
    ok = p.is_file()
    if ok:
        try:
            ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError as e:
            ok, = (False,)
            warns.append(f'{rel}: {e}')
    check(f'{rel}', ok)

# Orchestrator must still call every stage the notebook's §90 calls.
pipe = (HERE / 'app' / 'services' / 'pipeline.py').read_text(encoding='utf-8')
for fn in ('expected_stage_keys', 'select_artifact', 'build_evidence',
           'load_records', 'audit_video', 'score_audit',
           'evaluate_recommendations', 'build_figures', 'write_report',
           'talking_point_coverage', 'discover_videos', 'preprocess_folder',
           'process_all', 'run_vision_all'):
    check(f'orchestrator calls {fn}', f"'{fn}'" in pipe or f'{fn}(' in pipe)

# ---------------------------------------------------------------------------
print('\n' + '=' * 74)
if warns:
    for w in warns:
        print(f'  WARN  {w}')
print(f'  {"ALL INTACT" if not fails else str(len(fails)) + " FAILURE(S)"}')
if fails:
    for f in fails:
        print(f'      - {f}')
print('=' * 74)
sys.exit(1 if fails else 0)
