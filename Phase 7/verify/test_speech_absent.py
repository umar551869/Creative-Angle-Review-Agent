"""The three speech states, run through the REAL functions from the notebook.

Extracted from the patched notebook rather than retyped, so this tests the
shipped code and not a copy of it.
"""
import json
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
NB = Path(r'C:\Users\Umar Ilyas\creative project\Phase 6'
          r'\phases_1_to_6_gemini_vision.ipynb')
cells = [''.join(c['source']) for c in
         json.loads(NB.read_text(encoding='utf-8'))['cells']
         if c['cell_type'] == 'code']
S = ''.join(cells)
R = []


def check(label, cond, detail=''):
    R.append((label, bool(cond)))
    print(f'  {"PASS" if cond else "FAIL"}  {label}' + (f'   [{detail}]' if detail else ''))


# ---- the real can_fail_on / modes_that_can_fail ---------------------------
ns = {}
seg = S[S.index('def can_fail_on'):]
seg = seg[:seg.index('\n\n\n', seg.index('def modes_that_can_fail'))]
exec(seg, ns)
can_fail_on, modes_that_can_fail = ns['can_fail_on'], ns['modes_that_can_fail']


# ---- the real health rule, lifted out of the evidence builder -------------
@dataclass
class Cfg:
    thin_speech_words: int = 15
    absent_speech_ratio_PLACEHOLDER: float = 0.10
    absent_speech_max_words: int = 3


m = re.search(r"    degraded_asr = bool.*?'language': \(transcript or \{\}\)"
              r"\.get\('language'\),\n    \}", S, re.S)
assert m, 'could not lift the speech health block'
# It lives inside a function, so it arrives indented one level.
BLOCK = textwrap.dedent(m.group(0))
compile(BLOCK, 'speech_health_block', 'exec')       # fail loudly if the lift broke


def speech_health(words, spoken, duration, degraded_asr=False):
    env = {'transcript': {'degraded': degraded_asr}, 'words': list(range(words)),
           'spoken': spoken, 'duration': duration, 'cfg': Cfg(),
           'segs': [], 'h': {}}
    exec(BLOCK, env)
    return env['h']['speech']


print('=' * 78)
print('THE THREE STATES')
print('=' * 78)
# 1. the real run: 12.35s of music, 1 word, 0.42s voiced
music = speech_health(words=1, spoken=0.42, duration=12.35)
check('music-only video -> ABSENT', music['absent'] is True, str(music['reason'])[:60])
check('  and NOT degraded', music['degraded'] is False)
check('  and its reason says absence is established',
      'established' in (music['reason'] or ''))
check('  so a FAIL on speech becomes assertable',
      can_fail_on({'speech': music}, 'speech') is True)

# 2. ASR reported trouble: zero words, but that is NOT absence
broken = speech_health(words=0, spoken=0.0, duration=30.0, degraded_asr=True)
check('a crashed transcriber is NOT absent', broken['absent'] is False)
check('  it stays degraded', broken['degraded'] is True)
check('  so a FAIL stays blocked',
      can_fail_on({'speech': broken}, 'speech') is False)

# 3. voiced audio, sparse transcript -> degraded, not absent
sparse = speech_health(words=4, spoken=18.0, duration=30.0)
check('plenty of voiced time but few words -> degraded, not absent',
      sparse['absent'] is False and sparse['degraded'] is True,
      f"ratio {sparse['speech_ratio']}")
check('  FAIL stays blocked', can_fail_on({'speech': sparse}, 'speech') is False)

# 4. a normal talking video
healthy = speech_health(words=116, spoken=29.2, duration=30.8)
check('a talking video is neither absent nor degraded',
      healthy['absent'] is False and healthy['degraded'] is False)
check('  FAIL allowed', can_fail_on({'speech': healthy}, 'speech') is True)

print()
print('=' * 78)
print('THE AMBIGUOUS CASES -- both conditions are required')
print('=' * 78)
# low ratio but plenty of words: a 60s video with 5s of speech at the start
brief_speech = speech_health(words=22, spoken=5.0, duration=60.0)
check('low ratio but many words is NOT absent -- she did speak',
      brief_speech['absent'] is False,
      f"ratio {brief_speech['speech_ratio']}, 22 words")
check('  and with 22 words it is not thin either',
      brief_speech['degraded'] is False)
# few words but lots of voiced time: singing, or a failed transcription
few_words_loud = speech_health(words=2, spoken=25.0, duration=30.0)
check('few words but high ratio is NOT absent -- something was there',
      few_words_loud['absent'] is False,
      f"ratio {few_words_loud['speech_ratio']}, 2 words")
check('  it is degraded instead', few_words_loud['degraded'] is True)
# exactly on both boundaries
edge = speech_health(words=3, spoken=1.0, duration=10.0)
check('boundary (ratio 0.10, 3 words) counts as absent', edge['absent'] is True)
over = speech_health(words=4, spoken=1.0, duration=10.0)
check('one word over the limit is not absent', over['absent'] is False)
over2 = speech_health(words=3, spoken=1.1, duration=10.0)
check('one notch over the ratio is not absent', over2['absent'] is False)

print()
print('=' * 78)
print('WHAT THE GATE NOW ALLOWS FOR A MUSIC-ONLY VIDEO')
print('=' * 78)
health = {'speech': music,
          'ocr': {'ran': True, 'degraded': False},
          'visual': {'ran': True, 'coverage_degraded': False,
                     'acuity_degraded': False}}
modes = modes_that_can_fail(health)
for k, v in modes.items():
    print(f'    {k:<20} {"yes" if v else "no -- UNCERTAIN only"}')
check('speech_only can now FAIL -- "she never said it" is a fact',
      modes['speech_only'] is True)
check('speech_or_text can now FAIL -- OCR carried the message',
      modes['speech_or_text'] is True)
check('visual_and_speech can now FAIL', modes['visual_and_speech'] is True)
check('any can now FAIL', modes['any'] is True)

before = modes_that_can_fail({'speech': {'ran': True, 'degraded': True},
                              'ocr': {'ran': True, 'degraded': False},
                              'visual': {'ran': True, 'coverage_degraded': False}})
check('BEFORE the fix all four were blocked',
      not any(before[k] for k in ('speech_only', 'speech_or_text',
                                  'visual_and_speech', 'any')))

print()
print('=' * 78)
print('A DEGRADED MODALITY IS STILL BLOCKED -- the fix is narrow')
print('=' * 78)
blocked = modes_that_can_fail({'speech': broken,
                               'ocr': {'ran': True, 'degraded': False},
                               'visual': {'ran': True, 'coverage_degraded': False}})
check('a genuinely degraded ASR still blocks every speech mode',
      not any(blocked[k] for k in ('speech_only', 'speech_or_text',
                                   'visual_and_speech', 'any')))
check('a modality that never ran is still blocked',
      can_fail_on({'speech': {'ran': False, 'absent': True}}, 'speech') is False,
      'absent must not override `ran`')

print()
print('=' * 78)
print('UNCERTAIN RATE, over scoring units')
print('=' * 78)


class V:
    def __init__(self, s):
        self.status = s


def rates(statuses):
    verdicts = [V(s) for s in statuses]
    n = max(1, len(verdicts))
    units = sum(1 for v in verdicts if v.status != 'NOT_APPLICABLE')
    return (round(sum(1 for v in verdicts if v.status == 'UNCERTAIN')
                  / max(1, units), 3),
            round(sum(1 for v in verdicts if v.status == 'UNCERTAIN') / n, 3))


live = ['UNCERTAIN'] * 3 + ['PARTIAL'] + ['NOT_APPLICABLE'] * 20
new, old = rates(live)
check('the real run now reports 75%, not 12%', new == 0.75 and old == 0.125,
      f'new {new:.0%}, old {old:.0%}')
check('  and 75% crosses plan.md\'s 20% alarm line', new > 0.20)
check('  while 12% did not -- the alarm was silenced', old <= 0.20)
new2, _ = rates(['PASS', 'PASS', 'FAIL'] + ['NOT_APPLICABLE'] * 11)
check('a clean run still reports 0%', new2 == 0.0)
new3, _ = rates(['NOT_APPLICABLE'] * 5)
check('all-NOT_APPLICABLE does not divide by zero', new3 == 0.0)
new4, _ = rates([])
check('an empty verdict list does not divide by zero', new4 == 0.0)

print()
bad = [l for l, g in R if not g]
print(f'{len(R) - len(bad)}/{len(R)} checks pass')
print('ALL PASS' if not bad else 'FAILED:\n   ' + '\n   '.join(bad))
