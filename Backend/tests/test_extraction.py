"""The extraction's own tests: does auditor/ still mean what the notebook meant?

These are the tests that catch a bad regeneration. They need no key and no
network -- which is the point: every one of them can run in CI on every commit.
"""
import ast
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from auditor import runtime  # noqa: E402

NB = ROOT / 'Phase 7' / 'phases_1_to_7_BATCH.ipynb'


@pytest.fixture(scope='module')
def ns():
    return runtime.load()


# ---------------------------------------------------------------------------
# every entry point survives
# ---------------------------------------------------------------------------
ENTRY_POINTS = [
    'download_videos', 'load_brief_text', 'fetch_google_doc',
    'stage_key', 'read_json', 'write_json', 'sha256_text',
    'preprocess_video', 'preprocess_folder', 'discover_videos',
    'load_asr', 'run_asr_stage', 'load_ocr', 'run_ocr_stage', 'process_all',
    'make_vision_backend', 'run_vision_stage', 'run_vision_all',
    'compile_brief', 'compile_brief_consensus', 'requirements_for_audit',
    'build_evidence', 'load_records', 'expected_stage_keys',
    'select_artifact', 'modality_health', 'can_fail_on',
    'audit_video', 'named_brief_angles', 'evaluate_creative_angle',
    'score_audit', 'evaluate_recommendations', 'build_figures',
    'write_report', 'talking_point_coverage',
]


@pytest.mark.parametrize('name', ENTRY_POINTS)
def test_entry_point_exists(ns, name):
    assert ns.get(name) is not None, (
        f'{name} is missing. Either its notebook cell is absent from '
        f'CELL_MAP, or a definition was misclassified as a driver.')


@pytest.mark.parametrize('name', ['CFG', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'])
def test_config_singleton_exists(ns, name):
    assert ns.get(name) is not None


# ---------------------------------------------------------------------------
# loading must be inert -- no stage may run at import
# ---------------------------------------------------------------------------
def test_loading_runs_no_stage(ns):
    """A module-level driver would preprocess a directory on import.

    This happened: `batch_df = preprocess_folder(...)` was kept because the
    word `tuple(` appeared inside the call, and loading the package ran
    Phase 1. Every module-level Assign is now checked to be a constant.
    """
    # IMPORTED, not restated. A second copy of this rule drifted from the
    # first the moment the extractor learned about chained calls, and the
    # test then failed on code the extractor had correctly kept.
    sys.path.insert(0, str(HERE / 'tools'))
    from extract_from_notebook import (CONSTANT_BUILDERS, SAFE_CONSTANT_CALLS,
                                       _call_root)

    pkg = HERE / 'auditor'
    offenders = []
    allowed = CONSTANT_BUILDERS | SAFE_CONSTANT_CALLS
    for path in sorted(pkg.rglob('*.py')):
        if path.name in ('runtime.py', '_load_order.py', '__init__.py'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                offenders.append(f'{path.name}:{node.lineno} bare call')
            if isinstance(node, ast.Assign) and isinstance(node.value,
                                                           ast.Call):
                head = _call_root(node.value)
                if head not in allowed and not head.endswith('Config'):
                    offenders.append(f'{path.name}:{node.lineno} = {head}(...)')
    assert not offenders, (
        'module-level statements that DO something:\n  '
        + '\n  '.join(offenders))


def test_decorators_survive_extraction():
    """@dataclass was silently dropped from 38 of 39 decorated definitions.

    ast reports `lineno` for a decorated class at the `class` keyword, not at
    the decorator, so slicing from node.lineno lost every `@dataclass`. The
    classes still parsed, still imported and still instantiated -- and every
    field was a dataclasses.Field object instead of its value. Nothing raised
    until something tried to USE a threshold.
    """
    nb_dec = sum(len(re.findall(r'^@\w', s, re.M))
                 for s in [''.join(c['source'])
                           for c in json.loads(NB.read_text(encoding='utf-8'))
                           ['cells'] if c['cell_type'] == 'code'])
    pkg_dec = sum(len(re.findall(r'^@\w', p.read_text(encoding='utf-8'), re.M))
                  for p in (HERE / 'auditor').rglob('*.py'))
    assert pkg_dec >= 38, (
        f'only {pkg_dec} module-level decorators in the package; the notebook '
        f'has {nb_dec}. Decorators are being stripped.')


@pytest.mark.parametrize('name', ['CFG', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7'])
def test_config_singletons_are_real_dataclass_instances(ns, name):
    """The symptom the dropped decorator produced, asserted directly.

    `ns['P3'] is not None` passed the whole time the config was broken --
    presence is not correctness.
    """
    import dataclasses
    obj = ns[name]
    assert dataclasses.is_dataclass(obj) and not isinstance(obj, type), (
        f'{name} is {type(obj).__name__}, not a dataclass INSTANCE -- '
        f'@dataclass was lost in extraction')


def test_config_fields_hold_values_not_field_objects(ns):
    """A Field object where a threshold should be is the real failure."""
    import dataclasses
    checks = [
        ('P3.vision.gemini_models', ns['P3'].vision.gemini_models, tuple),
        ('P6.retrieval.top_k', ns['P6'].retrieval.top_k, int),
        ('P2.asr.backend', ns['P2'].asr.backend, str),
    ]
    for label, value, want in checks:
        assert not isinstance(value, dataclasses.Field), (
            f'{label} is a dataclasses.Field, not a value')
        assert isinstance(value, want), f'{label} is {type(value).__name__}'


def test_notebook_namespace_is_a_real_module():
    """@dataclass resolves annotations via sys.modules[cls.__module__].

    Exec'ing into a bare dict gives every class a __module__ that sys.modules
    has never heard of, and the decorator dies with
    "'NoneType' object has no attribute '__dict__'".
    """
    import sys as _sys
    runtime.load()
    mod = _sys.modules.get('auditor.notebook')
    assert mod is not None, 'the namespace is not registered in sys.modules'
    assert mod.__dict__ is runtime.NS, 'the module and NS have diverged'


def test_every_notebook_cell_is_a_decision():
    """No cell may be silently forgotten."""
    sys.path.insert(0, str(HERE / 'tools'))
    from extract_from_notebook import CELL_MAP, EXCLUDED

    n_cells = len([c for c in json.loads(NB.read_text(encoding='utf-8'))
                   ['cells'] if c['cell_type'] == 'code'])
    decided = set(CELL_MAP) | set(EXCLUDED)
    missing = [n for n in range(1, n_cells + 1) if n not in decided]
    assert not missing, f'cells neither mapped nor excluded: {missing}'
    assert not (set(CELL_MAP) & set(EXCLUDED)), 'a cell is both'


def test_generated_modules_match_load_order():
    from auditor._load_order import LOAD_ORDER

    for rel in LOAD_ORDER:
        assert (HERE / 'auditor' / rel).is_file(), f'{rel} is missing'


# ---------------------------------------------------------------------------
# the design rules, asserted on the real code
# ---------------------------------------------------------------------------
def test_scoring_is_arithmetic_not_a_model_call(ns):
    """Design rule 1: no model writes a number.

    If score.py ever grows a model call, that rule has been broken and the
    whole system's claim to be auditable goes with it.
    """
    src = (HERE / 'auditor' / 'scoring' / 'score.py').read_text(
        encoding='utf-8')
    for forbidden in ('generate_content', 'client.models', 'OpenAI(',
                      'chat.completions'):
        assert forbidden not in src, (
            f'{forbidden} appears in score.py -- a model must never write '
            f'the number')


def test_creative_angle_is_not_read_by_scoring():
    """concept_fit is a DESCRIPTION. Scoring must not consume it."""
    src = (HERE / 'auditor' / 'scoring' / 'score.py').read_text(
        encoding='utf-8')
    assert 'concept_fit' not in src


def test_concept_fit_drops_an_angle_the_brief_never_named(ns):
    """The model may not invent an angle. Signature: (raw, named, flags)."""
    clean = ns['_clean_concept_fit']
    named = ['No judgement zone', 'Health journey']
    flags: list = []
    rows = clean([{'angle': 'Unboxing haul', 'percent': 100}], named, flags)
    assert not any(r.get('angle') == 'Unboxing haul' for r in rows), (
        'an angle the brief never named must be dropped')
    assert any('NOT_IN_BRIEF' in str(f) for f in flags), (
        'and the drop must be RECORDED, not silent')


def test_concept_fit_renormalises_and_says_so(ns):
    """A split that does not sum is repaired, with the repair recorded."""
    clean = ns['_clean_concept_fit']
    named = ['No judgement zone', 'Health journey']
    flags: list = []
    rows = clean([{'angle': 'No judgement zone', 'percent': 60},
                  {'angle': 'Health journey', 'percent': 30}], named, flags)
    total = sum(float(r.get('percent') or 0) for r in rows)
    assert abs(total - 100) < 0.5, f'renormalised to {total}, expected 100'
    assert any('RENORMALISED' in str(f) for f in flags)


def test_concept_fit_preserves_a_clean_split(ns):
    """A valid 70/30 must pass through untouched and unflagged."""
    clean = ns['_clean_concept_fit']
    named = ['No judgement zone', 'Health journey']
    flags: list = []
    rows = clean([{'angle': 'No judgement zone', 'percent': 70},
                  {'angle': 'Health journey', 'percent': 30}], named, flags)
    got = {r['angle']: float(r['percent']) for r in rows}
    assert got == {'No judgement zone': 70.0, 'Health journey': 30.0}
    assert not [f for f in flags if 'RENORMALISED' in str(f)
                or 'NOT_IN_BRIEF' in str(f)]
