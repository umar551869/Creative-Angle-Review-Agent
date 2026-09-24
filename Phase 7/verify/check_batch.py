"""Batch-readiness check for phases_1_to_7_BATCH.ipynb."""
import ast
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
NB = Path(r'C:\Users\Umar Ilyas\creative project\Phase 7'
          r'\phases_1_to_7_BATCH.ipynb')
raw = NB.read_text(encoding='utf-8')
cells = json.loads(raw)['cells']
code = [(i, ''.join(c['source'])) for i, c in enumerate(cells)
        if c['cell_type'] == 'code']
S = ''.join(s for _, s in code)

bad = []
for i, s in code:
    try:
        ast.parse(s)
    except SyntaxError as e:
        bad.append((i, str(e)[:50]))
print(f'  {NB.stat().st_size / 1e6:.2f} MB  {len(cells)} cells  '
      f'parses={"YES" if not bad else bad}')
print()

# A cell only PROMPTS if the upload call can actually be reached. Cell 51
# still contains files.upload(), but inside `if UPLOAD:` with UPLOAD = False,
# so it is dead code -- searching for the string alone would report a second
# prompt that cannot happen.
def prompts(src: str) -> bool:
    if 'files.upload(' not in src:
        return False
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name)):
            continue
        val = None
        for n2 in ast.walk(tree):
            if (isinstance(n2, ast.Assign) and n2.targets
                    and isinstance(n2.targets[0], ast.Name)
                    and n2.targets[0].id == node.test.id
                    and isinstance(n2.value, ast.Constant)):
                val = n2.value.value
        if val is False and any('files.upload('
                                in ast.get_source_segment(src, b) or ''
                                for b in node.body):
            return False
    return True


ups = [i for i, s in code if prompts(s)]
print(f'  cells that actually PROMPT for upload: {ups}   (must be exactly one)')
print()

CHECKS = [
    ('only one uploader', len(ups) == 1),
    ('single-video UPLOAD disabled', 'UPLOAD = False   # BATCH' in S),
    ('suffix lowercased on extract', 'Path(_n).suffix.lower()' in S),
    ('Phase 1 globs every suffix', 'sorted(VIDEO_SUFFIXES)' in S),
    ('...and upper case too', 's.upper()' in S),
    ('reconcile guard present', 'BATCH RECONCILE' in S),
    ('reconcile names losses', 'DID NOT PREPROCESS' in S),
    ('brief is the batch doc',
     '1uWKQMZbOZW_LcEMC5cnFPMfDUTrA19A75JnqzVPzBq8' in S),
    # The old id survives inside a named-brief dict ('aurelia_hair': ...),
    # which is a registry, not the selection. What matters is that the ACTIVE
    # BRIEF_SOURCE assignment is the batch doc and there is exactly one.
    # The invariant CHANGED when BRIEF_SOURCE was hoisted to §0.3 (fix 48):
    # there are now legitimately TWO assignments -- the top declaration, and
    # §48's guarded `globals().get('BRIEF_SOURCE') or '<fallback>'`. What must
    # still hold is that exactly one is UNGUARDED, and that every one of them
    # names the batch doc. A fallback pointing at another brief is a notebook
    # that silently audits the wrong campaign whenever §48 runs alone.
    ('exactly one UNGUARDED BRIEF_SOURCE (the §0.3 declaration)',
     len([m for m in __import__('re').findall(
         r'^[^#\n]*BRIEF_SOURCE\s*=[^\n]*', S, __import__('re').M)
         if 'globals().get(' not in m]) == 1),
    ('...and EVERY BRIEF_SOURCE names the batch doc, fallback included',
     all('1uWKQMZbOZW' in m for m in
         __import__('re').findall(r'^[^#\n]*BRIEF_SOURCE\s*=[^\n]*', S,
                                  __import__('re').M))),
    ('the guarded fallback comes AFTER the declaration, so §0.3 wins',
     (S.find("BRIEF_SOURCE = 'https") == -1)
     or (S.find("BRIEF_SOURCE = 'https")
         < S.find("BRIEF_SOURCE = globals().get("))),
    ('RECOMPILE_BRIEF False is correct', 'RECOMPILE_BRIEF = False' in S),
    ('batch loop present', '\u00a790  THE BATCH RUN' in S),
    ('summary + zip present', '\u00a791  THE BATCH TABLE' in S),
    ('report PATH not markup', "get('html_path')" in S),
    ('failures isolated per video', 'BATCH_FAILURES.append' in S),
    ('MAX_VIDEOS cap', 'MAX_VIDEOS = 25' in S),
    ('time imported for batch cells', 'import time' in S),
    ('no mojibake', raw.count('\u00c2\u00a7') == 0),
    ('outputs cleared',
     all(not c.get('outputs') for c in cells if c['cell_type'] == 'code')),
]
for label, ok in CHECKS:
    print(f'  {"PASS" if ok else "FAIL"}  {label}')
print()
print(f'  {sum(1 for _, o in CHECKS if o)}/{len(CHECKS)} batch-readiness checks')

# ---------------------------------------------------------------------------
# EVERY STAGE MUST COVER EVERY VIDEO.
#
# This is the check that matters most, and the one that caught the real bug:
# run_vision_all() was DEFINED and never CALLED, so Phase 3 ran on TARGET only.
# Ten videos would have produced ten reports, nine of them with no visual
# evidence at all -- confidently thin, with nothing saying why.
# ---------------------------------------------------------------------------
import re as _re
print()
print('  === every stage runs for EVERY video ===')
STAGES = [
    ('Phase 1  decode/frames', r'batch_df = preprocess_folder\('),
    ('Phase 2  ASR (model loaded once, loops all)',
     r'for i, v in enumerate\(videos, 1\):[\s\S]{0,400}?run_asr_stage\('),
    ('Phase 2  OCR (engine loaded once, loops all)',
     r'for i, v in enumerate\(videos, 1\):[\s\S]{0,400}?run_ocr_stage\('),
    ('Phase 2  driver called on all', r'batch = process_all\(VIDEOS\)'),
    ('Phase 3  vision on all', r'vision_df = run_vision_all\('),
    # The vision pass and the batch loop must enumerate THE SAME videos.
    # discover_videos() warns that a batch runner using unique=False
    # "would process the same video five times and the hand-off could pick a
    # thinned variant" -- and a thinned variant has no visual artifact,
    # because §30.5 ran over the unique list.
    ('Phase 3  uses the UNIQUE video list',
     r'_vision_videos = discover_videos\(\)'),
    ('batch loop uses the SAME unique list',
     r'_all_videos = discover_videos\(\)'),
    # Scoped to the §90 cell only. A pre-existing diagnostic elsewhere in the
    # notebook legitimately wants every plan (unique=False); what must never
    # happen is the BATCH LOOP using it.
    ('...and §90 never uses unique=False',
     lambda s: 'unique=False' not in next(
         (c for c in s.split('# ====') if '§90  THE BATCH RUN' in c), '')
     .split('_all_videos =')[-1][:80]),
    ('Phase 5  evidence per video', r'_ev = build_evidence\(_v'),
    ('Phase 6  audit per video', r'_res = audit_video\(_v'),
    ('Phase 7  score per video', r'_sc = score_audit\(_res'),
    ('Phase 7  report per video', r'_rp = write_report\(_v'),
]
stage_ok = True
for label, pat in STAGES:
    hit = pat(S) if callable(pat) else bool(_re.search(pat, S))
    stage_ok &= hit
    print(f'  {"PASS" if hit else "FAIL"}  {label}')

# and they must happen in an order where nothing enumerates videos too early
pos = {k: S.find(v) for k, v in (
    ('p1', 'batch_df = preprocess_folder('),
    ('p2', 'batch = process_all(VIDEOS)'),
    ('p3', 'vision_df = run_vision_all('),
    ('batch', '§90  THE BATCH RUN'))}
seq = pos['p1'] < pos['p2'] < pos['p3'] < pos['batch']
print(f'  {"PASS" if seq else "FAIL"}  order: Phase 1 -> 2 -> 3 -> batch loop')
stage_ok &= seq

# execution order that makes the batch correct
order = {}
for i, s in code:
    if 'batch_df = preprocess_folder' in s:
        order['Phase 1 on ALL'] = i
    if 'batch = process_all(VIDEOS)' in s:
        order['Phase 2 on ALL'] = i
    if 'run_vision_all(' in s and 'def ' not in s.split('run_vision_all(')[0][-8:]:
        order.setdefault('Phase 3 on ALL', i)
    if '\u00a790  THE BATCH RUN' in s:
        order['batch loop'] = i
print()
print('  cells:', ' -> '.join(f'{k}@{v}' for k, v in
                              sorted(order.items(), key=lambda kv: kv[1])))
sys.exit(0 if all(o for _, o in CHECKS) and stage_ok else 1)
