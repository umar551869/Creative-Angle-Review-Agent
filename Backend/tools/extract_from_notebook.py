"""Generate Backend/auditor/ from phases_1_to_7_BATCH.ipynb.

WHY A GENERATOR AND NOT A HAND-PORT
-----------------------------------
The notebook is ~24,000 lines across 148 cells, 81 of them production. The
stated first objective is "notebook behavior -> reliable backend behavior", and
hand-retyping that much interdependent code is the single most reliable way to
introduce silent drift. So the pipeline layer is GENERATED, verbatim, and this
file is the only thing that has to be reviewed for correctness.

Re-run it whenever the notebook changes:

    python Backend/tools/extract_from_notebook.py

WHAT IT KEEPS
-------------
Definitions only -- imports, functions, classes, dataclasses, module-level
constants. It drops the notebook's DRIVER statements (the lines that actually
run a stage and print a table), because those are exactly what app/ replaces.
Every dropped statement is reported, so nothing disappears quietly.

WHAT IT DOES NOT DO
-------------------
It does not reformat, rename, or "improve" a single line of pipeline logic.
A diff between a generated module and its source cell must show only the
removal of driver statements.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[2]
NB = ROOT / 'Phase 7' / 'phases_1_to_7_BATCH.ipynb'
PKG = ROOT / 'Backend' / 'auditor'

# ---------------------------------------------------------------------------
# THE CELL MAP.
#
# Cells 6-84 carry their own intended path in the header comment -- the
# notebook declares its module layout and we obey it. Phases 4-7 predate that
# convention and are mapped here by section, one module per coherent unit.
#
# A cell absent from this map is NOT extracted. Those are the notebook's test
# suites, exit-criteria proofs, inspection plots and single-video drivers:
# real work, none of it runtime.
# ---------------------------------------------------------------------------
CELL_MAP: dict[int, str] = {
    # ---- Phase 0: imports and shared primitives ---------------------------
    3:   'bootstrap.py',           # §0.2 imports + hardware profile
    5:   'ingest/video.py',        # §0.4 download_videos / yt-dlp / zip
    # ---- Phase 1 ----------------------------------------------------------
    6:   'config.py',
    7:   'cache.py',
    8:   'storage/discovery.py',
    9:   'preprocessing/probe.py',
    10:  'preprocessing/preflight.py',
    11:  'preprocessing/sampler.py',
    13:  'preprocessing/scan.py',
    14:  'preprocessing/scenes.py',
    15:  'preprocessing/decode.py',
    16:  'preprocessing/audio.py',
    17:  'preprocessing/manifest.py',
    18:  'pipeline.py',
    50:  'pipeline.py',            # preprocess_folder (driver stripped)
    # ---- Phase 2 ----------------------------------------------------------
    19:  'evidence/text.py',
    21:  'asr/whisper.py',
    22:  'ocr/engine.py',
    23:  'ocr/selection.py',
    24:  'ocr/run.py',
    25:  'evidence/dedupe.py',
    26:  'evidence/caption_check.py',
    27:  'pipeline_p2.py',
    51:  'pipeline_p2.py',         # process_all (driver stripped)
    52:  'preprocessing/handoff.py',
    53:  'evaluation/matcher.py',
    # ---- Phase 3 ----------------------------------------------------------
    61:  'vision/config.py',
    62:  'vision/schemas.py',
    63:  'vision/prompts.py',
    64:  'vision/frames.py',
    65:  'vision/messages.py',
    66:  'vision/qwen.py',         # local path: extracted, left unwired
    67:  'secrets.py',             # §37a key resolution
    68:  'vision/gemini.py',
    69:  'vision/parsing.py',
    70:  'vision/normalize.py',
    72:  'pipeline_p3.py',
    84:  'vision/batch.py',
    # ---- Phase 4: brief compile -------------------------------------------
    88:  'brief/config.py',
    89:  'brief/loader.py',
    90:  'brief/schema.py',
    91:  'brief/temporal.py',
    92:  'brief/inference.py',
    93:  'brief/structure.py',
    94:  'brief/segmentation.py',
    95:  'brief/prompt.py',
    96:  'brief/backends.py',
    97:  'brief/validate.py',
    98:  'brief/dedupe.py',
    99:  'brief/compile.py',
    100: 'brief/approval.py',
    # ---- Phase 5: evidence -------------------------------------------------
    109: 'evidence5/config.py',
    110: 'evidence5/tolerance.py',
    111: 'evidence5/normalizers.py',
    112: 'evidence5/linking.py',
    113: 'evidence5/health.py',
    114: 'evidence5/aggregates.py',
    115: 'evidence5/stage.py',
    # ---- Phase 6: verdicts -------------------------------------------------
    120: 'audit/config.py',
    121: 'audit/retrieval.py',
    122: 'audit/l1.py',
    123: 'audit/l2.py',
    124: 'audit/l3.py',
    125: 'audit/hook.py',
    126: 'audit/claims.py',
    127: 'audit/creative_angle.py',
    128: 'audit/standing.py',
    129: 'audit/stage.py',
    # ---- Phase 7: scoring and report --------------------------------------
    137: 'scoring/config.py',
    139: 'scoring/score.py',
    140: 'scoring/recommend.py',
    141: 'scoring/report.py',
    142: 'scoring/figures.py',
}

# Cells deliberately NOT extracted, with the reason. Printed at the end so the
# exclusion is a decision on the record rather than an omission.
EXCLUDED = {
    1: 'optional fallback installs (OFF)', 2: 'pip install ladder',
    4: '§0.3 paths -- replaced by app.config (job-scoped DIRS)',
    12: 'sampler unit tests', 20: 'text unit tests',
    28: 'single-video driver', 29: 'single-video driver',
    30: 'single-video driver', 31: 'single-video driver',
    32: 'Phase 1->2 hand-off proof', 33: 'sampling coverage plot',
    34: 'contact sheet (visual inspection)', 35: 'timestamp verification',
    36: 'Phase 1 exit criteria', 37: 'driver', 38: 'driver', 39: 'driver',
    40: 'driver', 41: 'cache-contract proof', 42: 'transcript inspection',
    43: 'word-timestamp verification', 44: 'OCR overlay plot',
    45: 'dedupe before/after', 46: 'caption cross-check display',
    47: 'unified timeline display', 48: 'Phase 2 exit criteria',
    49: 'sampler ablation (writes extra manifests)',
    54: 'export_phase2 to Drive', 55: 'driver',
    56: 'ground-truth fixture builder', 57: 'fixture scoring',
    58: 'fixture commentary', 59: 'Phase 3 installs',
    60: 'GPU budget driver', 71: 'Phase 3 test suite',
    73: 'preconditions', 74: 'VRAM diagnostic', 75: 'backend choice driver',
    76: 'dry run', 77: 'single-video driver', 78: 'cache contract',
    79: 'evidence table display', 80: 'cited-frame display',
    81: 'timeline display', 82: 'Phase 3 exit criteria', 83: 'bake-off (OFF)',
    85: '§30.5 driver -- replaced by the orchestrator', 86: 'driver',
    87: 'cross-phase checks', 101: 'Phase 4 test suite',
    102: '§48 compile driver -- replaced by app.services.brief',
    103: 'approval display', 104: 'approval driver', 105: 'brief comparison',
    106: 'Phase 4 exit criteria', 107: 'hand-off', 108: 'pipeline diagnostic',
    116: 'Phase 5 test suite', 117: 'single-video driver',
    118: 'Phase 5 exit criteria', 119: 'hand-off',
    130: 'Phase 6 test suite', 131: 'single-video driver',
    132: 'Phase 6 exit criteria', 133: 'hand-off',
    134: 'full-pipeline self-check', 135: 'Phase 7 dependency installs',
    136: 'plan conformance report', 138: 'discrimination study',
    143: 'Phase 7 test suite', 144: 'single-video driver',
    145: 'Phase 7 exit criteria', 146: 'self-check addendum',
    147: '§90 batch driver -- replaced by app.services.pipeline',
    148: '§91 batch table + zip -- replaced by the API response',
}


# Calls that BUILD a constant rather than run a stage. One definition, shared
# with tools/audit_backend.py -- two copies of this rule would disagree.
CONSTANT_BUILDERS = {
    're.compile', 'frozenset', 'set', 'dict', 'tuple', 'list',
    'textwrap.dedent', 'Counter', 'defaultdict', 'str', 'int', 'float',
    'sorted', 'min', 'max', 'len', 'sum', 'abs', 'round', 'range', 'bool',
}

# Calls that are a DATA LOAD, not a stage. Each is a decision on the record
# rather than a widened rule:
#   _load_word_vocab  reads a word list off disk so text_readability can score
#                     OCR output. Dropping it left that function calling an
#                     undefined global -- the OCR readability gate would have
#                     failed on the first video with on-screen text.
SAFE_CONSTANT_CALLS = {'_load_word_vocab'}


def _call_root(node: ast.AST) -> str:
    """The LEFTMOST callable in a chain.

        textwrap.dedent(x).strip()  ->  'textwrap.dedent'
        preprocess_folder(...)      ->  'preprocess_folder'

    Checking the outermost `func` instead lost every chained constant: for
    `textwrap.dedent(...).strip()` the outer func is the entire
    `textwrap.dedent(...)` expression, which matches no builder name. That
    silently dropped PROMPT_P4_INSTRUCTIONS -- the Phase 4 compile prompt --
    and the first real job died on `NameError` the moment it tried to compile
    a brief.
    """
    while True:
        if isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Attribute) and isinstance(
                node.value, (ast.Call, ast.Attribute)):
            node = node.value
        else:
            break
    try:
        return ast.unparse(node)
    except Exception:
        return ''


def is_definition(node: ast.stmt) -> bool:
    """Keep definitions and constants; drop statements that DO something."""
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                         ast.AsyncFunctionDef, ast.ClassDef)):
        return True
    if isinstance(node, ast.AnnAssign):
        return True
    if isinstance(node, ast.Assign):
        # STRICT, because the failure mode is silent. `batch_df =
        # preprocess_folder(DIRS['inbox'], patterns=tuple(...))` is a DRIVER
        # that runs Phase 1 on import; an early version of this rule kept it
        # because the word `tuple(` appeared somewhere inside, and loading the
        # package preprocessed a directory. A module-level name is kept only
        # when it is plainly a CONSTANT.
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets and len(node.targets) == 1 and isinstance(
                node.targets[0], ast.Tuple) and isinstance(
                    node.value, ast.Tuple):
            # CONSTANT TUPLE-UNPACK: `_TICK, _CROSS, _WARN = ('[x]', ...)`.
            # Rejecting these dropped _WARN, and render_requirements_table --
            # the human review table the whole approval gate depends on --
            # would have died on NameError the first time a brief was shown.
            names = [e.id for e in node.targets[0].elts
                     if isinstance(e, ast.Name)]
            if (len(names) == len(node.targets[0].elts)
                    and len(names) == len(node.value.elts)
                    and all(isinstance(e, ast.Constant)
                            for e in node.value.elts)):
                targets = names
        if not targets or (len(node.targets) != 1
                           and len(targets) != len(node.targets)):
            return False                      # attribute/subscript unpack
        const_name = all(
            re.fullmatch(r'_?[A-Z][A-Z0-9_]*', t) or re.fullmatch(r'P\d', t)
            for t in targets)
        if not const_name:
            return False
        # Named like a constant. Now the VALUE must be one: a literal, a
        # container of literals, a lambda, or a call to a recognised builder
        # AT THE TOP LEVEL (not merely somewhere inside the expression).
        v = node.value
        if isinstance(v, (ast.Constant, ast.JoinedStr, ast.Lambda,
                          ast.UnaryOp, ast.BinOp, ast.Tuple, ast.List,
                          ast.Set, ast.Dict, ast.Name, ast.Attribute,
                          ast.IfExp, ast.Subscript,
                          # A comprehension over other constants is a DERIVED
                          # constant. Rejecting them dropped NUMBER_WORDS_INV,
                          # _COMPOUND_WORDS, _GAZ and DIMENSION_LABEL -- the
                          # number-word table, the gazetteer index and the
                          # dimension labels the report prints.
                          ast.DictComp, ast.SetComp, ast.ListComp,
                          ast.GeneratorExp)):
            return True
        if isinstance(v, ast.Call):
            head = _call_root(v)
            if head in CONSTANT_BUILDERS or head in SAFE_CONSTANT_CALLS:
                return True
            # Config singletons -- CFG = PreprocessConfig(), P6 = Phase6Config()
            if re.fullmatch(r'\w*Config', head) or head.endswith('Config'):
                return True
        return False
    if isinstance(node, ast.Try):
        # `try: import x / except ImportError: x = None` is a definition.
        body = getattr(node, 'body', [])
        return all(isinstance(b, (ast.Import, ast.ImportFrom, ast.Assign))
                   for b in body)
    if isinstance(node, ast.If):
        # Keep TYPE_CHECKING / platform guards that only define things.
        def defines_only(stmts):
            return stmts and all(
                isinstance(s, (ast.Import, ast.ImportFrom, ast.Assign,
                               ast.FunctionDef, ast.ClassDef, ast.Pass))
                for s in stmts)
        return defines_only(node.body) and (not node.orelse
                                            or defines_only(node.orelse))
    return False


def main() -> int:
    nb = json.loads(NB.read_text(encoding='utf-8'))
    code = [''.join(c['source'])
            for c in nb['cells'] if c['cell_type'] == 'code']
    print(f'  notebook: {len(code)} code cells')

    unmapped = [n for n in range(1, len(code) + 1)
                if n not in CELL_MAP and n not in EXCLUDED]
    if unmapped:
        print(f'  !! {len(unmapped)} cells are neither mapped nor excluded: '
              f'{unmapped}')
        print('     Every cell must be a decision. Add it to CELL_MAP or '
              'EXCLUDED.')
        return 1

    by_module: dict[str, list[tuple[int, str]]] = defaultdict(list)
    dropped_total = 0
    for n, rel in sorted(CELL_MAP.items()):
        src = code[n - 1]
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            print(f'  !! cell {n} does not parse: {e}')
            return 1
        keep, drop = [], []
        for node in tree.body:
            (keep if is_definition(node) else drop).append(node)
        dropped_total += len(drop)
        segments = []
        lines = src.splitlines(keepends=True)
        for node in keep:
            # DECORATORS FIRST. ast reports `lineno` for a decorated class or
            # function at the `class`/`def` keyword, NOT at the decorator --
            # so slicing from node.lineno silently dropped every `@dataclass`
            # in the notebook (38 of 39). The classes still parsed, still
            # imported, and still answered isinstance checks, but every field
            # was a `dataclasses.Field` object instead of its value: P3.vision
            # was a Field, P6.retrieval was a Field, every threshold in the
            # system was a Field. Nothing raised until something tried to USE
            # a config value.
            start = node.lineno - 1
            decs = getattr(node, 'decorator_list', None) or []
            if decs:
                start = min(d.lineno for d in decs) - 1
            # carry the comment block immediately above
            while start > 0 and lines[start - 1].lstrip().startswith('#'):
                start -= 1
            segments.append(''.join(lines[start:node.end_lineno]))
        body = '\n'.join(s.rstrip() + '\n' for s in segments)
        dropped_desc = [
            (getattr(d, 'lineno', 0),
             (ast.unparse(d).splitlines() or [''])[0][:76])
            for d in drop]
        by_module[rel].append((n, body))
        if drop:
            by_module[rel].append((-n, '\n'.join(
                f'#   line {ln}: {t}' for ln, t in dropped_desc)))

    PKG.mkdir(parents=True, exist_ok=True)
    written = 0
    for rel, parts in sorted(by_module.items()):
        dest = PKG / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        cells = sorted({n for n, _ in parts if n > 0})
        head = [
            '"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by '
            'hand.',
            '',
            f'Source: code cell(s) {", ".join(str(c) for c in cells)}.',
            'Regenerate with:  python Backend/tools/extract_from_notebook.py',
            '',
            'Bodies are VERBATIM. The only removal is the notebook\'s driver',
            'statements (the lines that run a stage and print a table); those',
            'are listed at the foot of this file and are replaced by',
            'Backend/app/services/.',
            '',
            'This file is LOADED BY auditor.runtime, not imported directly.',
            'The notebook shares one global namespace and binds some names',
            'late (globals().get(...)), so the loader reproduces that exactly',
            'rather than guessing an import graph that the original never had.',
            '"""',
        ]
        bodies = [b for n, b in parts if n > 0]
        drops = [b for n, b in parts if n < 0 and b.strip()]
        text = '\n'.join(head) + '\n' + '\n\n'.join(bodies)
        if drops:
            text += ('\n\n# ' + '-' * 74
                     + '\n# DRIVER STATEMENTS REMOVED (they belong to app/'
                       'services, not the library):\n'
                     + '\n'.join(drops) + '\n')
        dest.write_text(text, encoding='utf-8')
        written += 1

    # ---- THE LOAD ORDER IS THE NOTEBOOK'S CELL ORDER ----------------------
    # Not alphabetical, not dependency-sorted: cell order. Phase 3 sits above
    # Phase 4 in the notebook for a real reason (the vision backend needs the
    # API key hoisted), and reordering would break the same things reordering
    # the notebook breaks.
    order, seen = [], set()
    for n, rel in sorted(CELL_MAP.items()):
        if rel not in seen:
            seen.add(rel)
            order.append((n, rel))
    (PKG / '_load_order.py').write_text(
        '"""GENERATED. The order auditor.runtime executes the modules in.\n\n'
        'This is the NOTEBOOK CELL ORDER, which is load-bearing: the key is\n'
        'hoisted above the vision backend, and the vision stage is defined\n'
        'above the brief compiler. Do not sort this.\n"""\n'
        'LOAD_ORDER = [\n'
        + ''.join(f'    {rel!r},{" " * max(1, 34 - len(rel))}# cell {n}\n'
                  for n, rel in order)
        + ']\n', encoding='utf-8')

    # package markers
    for d in {PKG} | {p.parent for p in PKG.rglob('*.py')}:
        init = d / '__init__.py'
        if not init.exists():
            init.write_text('', encoding='utf-8')

    print(f'  wrote {written} modules under {PKG.relative_to(ROOT)}')
    print(f'  dropped {dropped_total} driver statements (each listed in its '
          f'module)')
    print(f'  excluded {len(EXCLUDED)} cells by decision')

    # ---- POST-CONDITION: nothing structural may go missing ----------------
    # A dropped decorator does not raise. `@dataclass` disappears, the class
    # still defines, still imports, still instantiates -- and every field is a
    # Field object instead of its value. That shipped once. It cannot ship
    # twice: count what the mapped cells declare and demand the same count
    # back out, before anything downstream trusts this package.
    want_dec = want_cls = want_def = 0
    for n in CELL_MAP:
        for node in ast.parse(code[n - 1]).body:
            if not is_definition(node):
                continue
            want_dec += len(getattr(node, 'decorator_list', None) or [])
            want_cls += isinstance(node, ast.ClassDef)
            want_def += isinstance(node, (ast.FunctionDef,
                                          ast.AsyncFunctionDef))
    got_dec = got_cls = got_def = 0
    for rel in sorted(by_module):
        for node in ast.parse((PKG / rel).read_text(encoding='utf-8')).body:
            got_dec += len(getattr(node, 'decorator_list', None) or [])
            got_cls += isinstance(node, ast.ClassDef)
            got_def += isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))
    print()
    bad = False
    for label, want, got in (('module-level decorators', want_dec, got_dec),
                             ('classes', want_cls, got_cls),
                             ('functions', want_def, got_def)):
        ok = want == got
        bad |= not ok
        print(f'  {"OK  " if ok else "LOST"}  {label:<24} '
              f'notebook {want:>4}  package {got:>4}')
    if bad:
        print('\n  STRUCTURE LOST IN EXTRACTION. The package is not a faithful'
              '\n  copy and must not be used. Fix the slicing, not the count.')
        return 1

    # A KEPT module-level assignment is the risky direction: if the rule is
    # too loose, importing the package RUNS a stage. List every one, so the
    # judgement is reviewable instead of buried.
    kept = []
    for n, rel in sorted(CELL_MAP.items()):
        for node in ast.parse(code[n - 1]).body:
            if isinstance(node, ast.Assign) and is_definition(node):
                try:
                    kept.append((n, rel, ast.unparse(node)[:72]))
                except Exception:
                    pass
    print(f'\n  module-level constants kept ({len(kept)}) -- none of these may '
          f'run a stage:')
    for n, rel, text in kept:
        print(f'    cell {n:>4}  {rel:<26} {text}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
