"""Run §60's THREE new fixtures through the REAL modality_health.

Loads the actual cells that define EvidenceConfig, _merge_spans and
modality_health, so this exercises shipped code rather than a paraphrase of it.
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
NB = Path(r'C:\Users\Umar Ilyas\creative project\Phase 6'
          r'\phases_1_to_6_gemini_vision.ipynb')
cells = [''.join(c['source']) for c in
         json.loads(NB.read_text(encoding='utf-8'))['cells']
         if c['cell_type'] == 'code']
R = []


def check(label, cond, detail=''):
    R.append((label, bool(cond)))
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'   {detail}' if detail else ''))


# ---- load the real definitions --------------------------------------------
ns = {'__name__': '__cellenv__'}
import dataclasses, math, statistics, collections, itertools, hashlib, time, os  # noqa
ns.update({'dataclass': dataclasses.dataclass, 'field': dataclasses.field,
           'asdict': dataclasses.asdict, 'replace': dataclasses.replace,
           'math': math, 'statistics': statistics, 're': re, 'json': json,
           'Path': Path, 'Optional': __import__('typing').Optional,
           'Counter': collections.Counter, 'defaultdict': collections.defaultdict,
           'hashlib': hashlib, 'time': time, 'os': os})

# The whole of cell 106: EVIDENCE_STAGE_VERSION is defined above EvidenceConfig
# and referenced inside it, so slicing at @dataclass loses it.
exec(compile(cells[106], 'cell106', 'exec'), ns)
check('EvidenceConfig / P5 loaded', 'P5' in ns and hasattr(ns['P5'], 'evidence'))
ev = ns['P5'].evidence
print(f'     thin_speech_words={ev.thin_speech_words}  '
      f'absent_ratio={ev.absent_speech_ratio_PLACEHOLDER}  '
      f'absent_max_words={ev.absent_speech_max_words}')

m = re.search(r'def _merge_spans.*?(?=\ndef |\nclass |\n@)', cells[107], re.S)
exec(compile(m.group(0), 'merge', 'exec'), ns)

# The whole cell: modality_health is defined BEFORE can_fail_on, so slicing
# from can_fail_on drops the very function under test.
exec(compile(cells[110], 'cell110', 'exec'), ns)
modality_health, can_fail_on = ns['modality_health'], ns['can_fail_on']
check('modality_health / can_fail_on loaded', callable(modality_health))

# ---- the same supporting artifacts §60 uses -------------------------------
DUR = 6.0
man = {'frames': [{'index': i, 'timestamp': round(i * 0.5, 2)} for i in range(13)]}
ocr_art = {'backend': 'rapidocr', 'intervals': [
    {'id': 0, 'start': 1.0, 'end': 2.0, 'text': 'LINK IN BIO',
     'independence': 'confirmed_independent', 'confidence': 0.9}]}
vis_art = {'status': 'OK', 'events': [], 'flags': [],
           'stats': {'n_frames_sent': 12},
           'sampling': {'n_frames_sent': 12, 'frame_budget': 12},
           'model': {'name': 'gemini', 'quantization': 'hosted'}}

print()
print('=' * 74)
print('THE THREE FIXTURES §60 NOW USES')
print('=' * 74)

absent_tr = {'backend': 'x', 'segments': [
    {'id': 0, 'start': 1.2, 'end': 1.7, 'text': 'You', 'words': [{'word': 'You'}]}]}
h = modality_health(absent_tr, ocr_art, vis_art, man, DUR)['speech']
print(f'  music-only : ratio {h["speech_ratio"]}  words {h["words"]}  '
      f'-> absent={h["absent"]} degraded={h["degraded"]}')
check('a music-only transcript is ABSENT, not degraded',
      h['absent'] is True and h['degraded'] is False)
check('...so a speech FAIL IS permitted -- absence is established',
      can_fail_on({'speech': h}, 'speech'))
check('...and it says so in words, not just a flag',
      'established' in (h['reason'] or ''), str(h['reason'])[:60])

thin_tr = {'backend': 'x', 'segments': [
    {'id': 0, 'start': 1.0, 'end': 5.0, 'text': 'er and um so yeah',
     'words': [{'word': w} for w in ('er', 'and', 'um', 'so', 'yeah')]}]}
h2 = modality_health(thin_tr, ocr_art, vis_art, man, DUR)['speech']
print(f'  sparse     : ratio {h2["speech_ratio"]}  words {h2["words"]}  '
      f'-> absent={h2["absent"]} degraded={h2["degraded"]}')
check('a sparse transcript over real voiced audio is DEGRADED, not absent',
      h2['degraded'] is True and h2['absent'] is False)
check('...so a speech FAIL is not permitted',
      not can_fail_on({'speech': h2}, 'speech'),
      'plan.md §6.2 holds, on the case it actually applies to')

broken_tr = {'backend': 'x', 'degraded': True,
             'degradation_reason': 'ASR fell back to a smaller model',
             'segments': [{'id': 0, 'start': 1.2, 'end': 1.7, 'text': 'You',
                           'words': [{'word': 'You'}]}]}
h3 = modality_health(broken_tr, ocr_art, vis_art, man, DUR)['speech']
print(f'  ASR failed : ratio {h3["speech_ratio"]}  words {h3["words"]}  '
      f'-> absent={h3["absent"]} degraded={h3["degraded"]}')
check('a self-reported ASR failure is never ABSENT', h3['absent'] is False)
check('...it stays degraded, and no speech FAIL is permitted',
      h3['degraded'] is True and not can_fail_on({'speech': h3}, 'speech'))

print()
print('=' * 74)
print('AND THE HEALTHY CASE §60 ALREADY HAD')
print('=' * 74)
tr = {'backend': 'faster-whisper', 'segments': [
    {'id': 0, 'start': 0.2, 'end': 1.8, 'text': 'this is the easiest thing',
     'avg_logprob': -0.31,
     'words': [{'word': w, 'start': 0.2, 'end': 0.4}
               for w in 'this is the easiest thing added to my routine and more'.split()]},
    {'id': 1, 'start': 2.0, 'end': 5.0, 'text': 'added to my routine',
     'avg_logprob': -0.22,
     'words': [{'word': w} for w in 'added to my routine again now today ok'.split()]}]}
h4 = modality_health(tr, ocr_art, vis_art, man, DUR)['speech']
print(f'  talking    : ratio {h4["speech_ratio"]}  words {h4["words"]}  '
      f'-> absent={h4["absent"]} degraded={h4["degraded"]}')
check('a normal talking video is neither absent nor degraded',
      h4['absent'] is False and h4['degraded'] is False)
check('...and a speech FAIL is permitted', can_fail_on({'speech': h4}, 'speech'))

print()
bad = [l for l, g in R if not g]
print(f'{len(R) - len(bad)}/{len(R)} checks pass')
print('ALL PASS' if not bad else 'FAILED:\n   ' + '\n   '.join(bad))
raise SystemExit(1 if bad else 0)
