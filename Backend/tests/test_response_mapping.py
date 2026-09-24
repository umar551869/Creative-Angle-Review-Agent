"""Every field the orchestrator computes must survive into the response.

pydantic DROPS unknown keys silently. A live run returned null for
modality_health, evidence_records and both talking-point counts while the
values sat in the row object under different names -- no error, no warning,
just absent data that a front end would render as "unknown".
"""
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.schemas import JobOut, VideoResultOut  # noqa: E402

PIPE = (HERE / 'app' / 'services' / 'pipeline.py').read_text(encoding='utf-8')
JOBS = (HERE / 'app' / 'jobs.py').read_text(encoding='utf-8')


# Computed on the row but deliberately NOT returned. These are absolute paths
# on the server's filesystem; the client gets report_html_url instead, which
# jobs.py derives from them.
SERVER_ONLY = {'report_html', 'report_json'}


def _row_keys() -> set[str]:
    """Top-level keys on a result row, by AST.

    A regex over the file pulled in nested dicts -- every key of the `score`
    sub-object, and of angle_distribution's rows -- and reported twenty
    phantom orphans. Walking the tree asks the question actually being asked:
    what ends up at the TOP level of a row.
    """
    tree = ast.parse(PIPE)
    fns = [n for n in tree.body
           if isinstance(n, ast.FunctionDef)
           and n.name in ('audit_one', 'audit_all')]
    keys: set[str] = set()
    for fn in fns:
        for node in ast.walk(fn):
            # row['x'] = ...
            if (isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Subscript)
                    and isinstance(node.targets[0].value, ast.Name)
                    and node.targets[0].value.id == 'row'
                    and isinstance(node.targets[0].slice, ast.Constant)):
                keys.add(node.targets[0].slice.value)
            # row.update({...}) and out.append({...}) -- TOP level only
            if isinstance(node, ast.Call) and node.args:
                f = node.func
                name = (f.attr if isinstance(f, ast.Attribute) else
                        getattr(f, 'id', ''))
                if name in ('update', 'append') and isinstance(node.args[0],
                                                              ast.Dict):
                    for k in node.args[0].keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value,
                                                                      str):
                            keys.add(k.value)
    # jobs.py decorates the row after the fact
    keys |= set(re.findall(r"r\['(\w+)'\]\s*=", JOBS))
    return keys - SERVER_ONLY


def test_no_result_field_is_silently_dropped():
    declared = set(VideoResultOut.model_fields)
    produced = _row_keys()
    orphans = sorted(produced - declared)
    assert not orphans, (
        f'audit_one produces {orphans} but VideoResultOut does not declare '
        f'them -- pydantic will drop them without a word. Either add the '
        f'field or stop computing it.')


def test_the_four_that_were_actually_lost_are_now_mapped():
    """Regression: these were computed and never reached a caller."""
    for f in ('modality_health', 'evidence_records', 'talking_points_covered',
              'talking_points_total', 'notes'):
        assert f in VideoResultOut.model_fields, f'{f} missing from the schema'
        assert f in _row_keys(), f'{f} is declared but nothing sets it'


def test_the_notebook_verdict_names_are_translated():
    """The SAME defect one level down, which the top-level check cannot see.

    `verdicts` is a list of VerdictOut, so the row-key test above passes while
    every field INSIDE each verdict is dropped. The notebook writes `reason`
    and `layer`; the schema declares `rationale` and `decided_by`. A live run
    returned rationale:"" and decided_by:null on all 28 verdicts -- the API
    claiming the audit had no explanation for anything it decided.
    """
    from app.schemas import VerdictOut
    from app.services.pipeline import _verdict_out

    raw = {'requirement_id': 'r_1', 'requirement_label': 'Name the product',
           'status': 'PASS', 'alignment': 'exact', 'confidence': 1.0,
           'layer': 'L3', 'reason': 'she names it at 0:12',
           'evidence_ids': ['ev_1'], 'flags': [], 'group_label': 'Claims'}
    out = VerdictOut(**_verdict_out(raw))
    assert out.rationale == 'she names it at 0:12', (
        'the "why" must reach the caller; the report already shows it')
    assert out.decided_by == 'L3', 'which rung decided it must survive'


def test_verdict_translation_prefers_an_explicit_schema_name():
    """If the notebook ever adopts the schema's names, do not clobber them."""
    from app.services.pipeline import _verdict_out

    out = _verdict_out({'rationale': 'already right', 'reason': 'older name',
                        'decided_by': 'L1', 'layer': 'L2'})
    assert out['rationale'] == 'already right'
    assert out['decided_by'] == 'L1'


def test_duration_reaches_the_response():
    """The report printed 54.2s while the API said duration_s: null."""
    assert "row['duration_s'] = round(float(res['duration_seconds'])" in PIPE
    assert 'duration_s' in VideoResultOut.model_fields


def test_job_level_fields_survive_too():
    declared = set(JobOut.model_fields)
    produced = set(re.findall(r"'(\w+)':\s*self\.", JOBS))
    orphans = sorted(k for k in produced - declared if not k.startswith('_'))
    assert not orphans, f'Job.to_dict emits {orphans}, JobOut drops them'


def test_notes_is_where_a_failed_module_explains_itself():
    """status='module_failed' with nothing saying why is the same defect one
    level up -- the code knows and does not say."""
    assert "row['status'] = 'module_failed'" in PIPE
    assert "row['notes']" in PIPE
    assert 'notes' in VideoResultOut.model_fields


def test_audit_one_builds_a_row_the_schema_accepts():
    """Construct the model from a realistic row and assert the values land."""
    row = {
        'video_id': 'abc123', 'video_hash': 'a' * 16, 'source': 'v.mp4',
        'status': 'ok', 'evidence_records': 412, 'duration_s': 22.8,
        'talking_points_covered': 7, 'talking_points_total': 9,
        'notes': ['standing NOT judged: STANDING_MODEL_FAILED'],
        'modality_health': {'speech': {'ran': True, 'absent': False,
                                       'degraded': False, 'reason': None}},
        'can_fail_on': {'speech_only': True},
    }
    out = VideoResultOut(**row)
    assert out.evidence_records == 412
    assert out.talking_points_covered == 7
    assert out.talking_points_total == 9
    assert out.duration_s == 22.8
    assert out.notes and 'STANDING_MODEL_FAILED' in out.notes[0]
    assert out.modality_health['speech'].ran is True
