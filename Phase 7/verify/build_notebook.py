"""Assemble phases_1_to_7_gemini_vision.ipynb.

Phases 1-6 come from the validated gemini notebook, unchanged. Phase 7 is
appended as new cells. Outputs are cleared: this notebook is meant to be RUN,
and outputs from a different run would describe a state that no longer exists.

Cell ORDER is execution order, which is not always numeric order. S.77 tests
build_report_html and build_figures, so it is placed after S.79/S.79b and says
so in its own header. A number is documentation; position is behaviour.

EVERY read and write here names encoding='utf-8' explicitly. An earlier build
lost that on a round trip through another tool and turned every section sign
into mojibake -- which parses, tests green, and looks like nothing until a
human reads the page.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path(r'C:\Users\Umar Ilyas\creative project')
SRC = ROOT / 'Phase 6' / 'phases_1_to_6_gemini_vision.ipynb'
CELLS = ROOT / 'Phase 7' / 'cells'
CONF = ROOT / 'Phase 6' / 'phase_conformance_cell.py'
DST = ROOT / 'Phase 7' / 'phases_1_to_7_gemini_vision.ipynb'

S = '\u00a7'          # section sign, by codepoint so no encoding can bend it
EM = '\u2014'         # em dash


def code_cell(src: str) -> dict:
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {},
            'outputs': [], 'source': src.rstrip('\n').splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {'cell_type': 'markdown', 'metadata': {},
            'source': src.rstrip('\n').splitlines(keepends=True)}


def from_file(p: Path) -> dict:
    return code_cell(p.read_text(encoding='utf-8'))


nb = json.loads(SRC.read_text(encoding='utf-8'))
n_src_code = sum(1 for c in nb['cells'] if c['cell_type'] == 'code')

# Clear outputs. A fresh notebook carrying another run's output is a notebook
# that lies about its own state.
for c in nb['cells']:
    if c['cell_type'] == 'code':
        c['outputs'] = []
        c['execution_count'] = None

DEPS = f'''# ============================================================================
# {S}74a  Phase 7 dependencies
#
# One library Phase 7 wants and Phases 1-6 never needed. It is usually already
# present in Colab; this installs it only if missing, and does so under the
# SAME torch constraints as {S}0.1 -- an unguarded pip here is exactly how a
# working runtime becomes a broken one.
#
# It is not allowed to be load-bearing: without plotly, {S}79b degrades to
# notes and the report still renders, scores and all.
#
# Jinja2 is deliberately NOT used. The report is built with explicit escaping
# through esc(), which for a compliance document is more auditable than
# autoescaping -- and it keeps the deliverable dependency-free.
# ============================================================================
# importlib.util, NOT bare importlib: `import importlib` does not bind the
# `util` submodule, so `importlib.util.find_spec` raises AttributeError in a
# clean interpreter. It usually works in Colab only because some other library
# imported it first -- which is luck, and this is the first Phase 7 cell to run.
import importlib.util
import subprocess
import sys

_p7_need = [m for m in ('plotly',) if importlib.util.find_spec(m) is None]
if not _p7_need:
    print('{S}74a  Phase 7 dependencies already present: plotly')
else:
    _cmd = [sys.executable, '-m', 'pip', 'install', '-q'] + _p7_need
    if 'TORCH_PINS' in globals() and Path(TORCH_PINS).exists():
        _cmd += ['-c', str(TORCH_PINS)]      # pip may NOT move torch for this
    print(f'{S}74a  installing {{_p7_need}} ...')
    _r = subprocess.run(_cmd, capture_output=True, text=True)
    print(f'  pip exit {{_r.returncode}}')
    if _r.returncode != 0:
        print('  Phase 7 does not need this to produce a score or a report.')
        print('  The figures will be skipped and the report will say so.')
for _m in ('plotly',):
    _spec = importlib.util.find_spec(_m)
    print(f'  {{_m:<10}} '
          f'{{"present" if _spec else "MISSING -- figures will be skipped"}}')
'''

BRIDGE_MD = f'''---

# Phase 6 {EM}> Phase 7 bridge

Three cells that belong to neither phase: the dependency Phase 7 adds, a
mechanical check of every `plan.md` exit criterion for Phases 0{EM}6, and
{EM} once {S}75 has defined the constants {EM} the experiment that decides
which quantity the score should be built on.
'''

P7_MD = f'''---

# PHASE 7 {EM} Deterministic scoring and reporting

**Objective (plan.md {S}7, spec {S}39/{S}40/{S}75):** a score computed by
arithmetic, never by a model, and a report a creator manager can act on faster
than watching the video.

## What Phase 6 measured, and what it changed here

| measured in Phase 6 | consequence for Phase 7 |
|---|---|
| The **alignment mean does not discriminate** {EM} 0.72 on-brief vs 0.68 off-brief, ranges overlapping across almost their whole span | it cannot be the headline; {S}75b measures the alternatives against a pre-registered rule before anything is built on one |
| **`standing` separated perfectly**, six runs, zero variance | it travels with every score as a cross-check that is allowed to contradict it |
| A forbidden rule passing vacuously **scored 1.0 and contributed 65%** of an off-brief video's score | `PASS_FROM_ABSENCE` is held out of achievement entirely and reported as *"no violations found: N of N"* |
| 26 requirements collapse to **3 scored units** | the band is the main output, never a decimal place, and the unit count sits beside the number |
| L3 sampling moved the mean **0.34 on identical inputs** | "deterministic" means reproducible *from a named verdict artifact*, not stable across runs {EM} so every report names the `verdicts__*.json` it scored |

## The order of this phase

| {S} | what | model calls |
|---|---|---|
| {S}74a | Phase 7 dependencies | {EM} |
| {S}74b | Plan conformance, Phases 0{EM}6 | {EM} |
| {S}75 | Scoring configuration {EM} every constant, in code | {EM} |
| {S}75b | **Which quantity discriminates?** Answer before trusting a number | {EM} |
| {S}76 | `score_audit` {EM} the number, by arithmetic | {EM} |
| {S}78 | Recommendations | **one** |
| {S}79 | The report: one self-contained HTML file | {EM} |
| {S}79b | Figures {EM} the geometry of dimension matching | {EM} |
| {S}77 | Phase 7 test suite (placed after what it tests) | {EM} |
| {S}80 | Score the TARGET, render, write the artifacts | {EM} |
| {S}81 | Phase 7 exit criteria | {EM} |
| {S}82 | Self-check addendum, Phases 1{EM}7 | {EM} |

**The design rule for the report:** every number on the page traces to a
requirement, and every requirement traces to an evidence id. If something
cannot be traced, it does not go on the page.

**The three rules {S}73b hands over, which nothing here may break:**

1. `UNCERTAIN` is an abstention, not a low score. Averaging it as 0 turns
   "we did not look" into "they failed".
2. `NOT_APPLICABLE` leaves the denominator. A twelve-option hook list is one
   decision, not eleven failures.
3. Claims output is assistive, and carries its disclaimer onto the page.
'''

NEXT_MD = f'''---

## Next: Phase 8 {EM} benchmark, review UI, metrics

Everything green here means the machinery is sound and every claim is
traceable. It does **not** mean the verdicts are right, and it does not mean
85 is the line between approved and not.

Both of those need **labels**, not more code. That is Phase 8, and `plan.md`
is explicit that it must not be skipped or deferred.
'''

nb['cells'] += [
    md_cell(BRIDGE_MD),
    code_cell(DEPS),
    from_file(CONF),
    md_cell(P7_MD),
    from_file(CELLS / 's75_config.py'),
    # 75b reads 75's constants, so it runs after them -- and still before 76,
    # which is what "decide before you build the scorer" actually requires.
    from_file(CELLS / 's75b_discriminate.py'),
    from_file(CELLS / 's76_score.py'),
    from_file(CELLS / 's78_recommend.py'),
    from_file(CELLS / 's79_report.py'),
    from_file(CELLS / 's79b_figures.py'),
    from_file(CELLS / 's77_tests.py'),
    from_file(CELLS / 's80_run.py'),
    from_file(CELLS / 's81_exit.py'),
    from_file(CELLS / 's82_selfcheck.py'),
    md_cell(NEXT_MD),
]

DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding='utf-8')

code = [c for c in nb['cells'] if c['cell_type'] == 'code']
txt = DST.read_text(encoding='utf-8')
MOJI = ('\u00c2\u00a7', '\u00e2\u20ac\u201d', '\u00e2\u20ac\u2122',
        '\u00e2\u20ac\u0153', '\u00c3\u0083')
found = {m: txt.count(m) for m in MOJI if txt.count(m)}
print(f'  wrote {DST.name}')
print(f'    {len(nb["cells"])} cells ({len(code)} code, '
      f'{len(nb["cells"]) - len(code)} markdown)')
print(f'    Phases 1-6 contributed {n_src_code} code cells, Phase 7 adds '
      f'{len(code) - n_src_code}')
print(f'    {DST.stat().st_size / 1e6:.2f} MB (outputs cleared)')
print(f'    section signs: {txt.count(S)}   mojibake: {found or "none"}')
