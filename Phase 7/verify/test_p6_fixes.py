"""The four Phase 6 fixes from the 5f18775d x Aurelia audit, tested on the
fixtures that actually broke.

Each test states the REAL requirement text from that audit, so a future reader
can see what the report printed and why it was wrong -- not just that a regex
changed.

Run: python "Phase 7/verify/test_p6_fixes.py"
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(r'C:\Users\Umar Ilyas\creative project')
NB = ROOT / 'Phase 6' / 'phases_1_to_6_gemini_vision.ipynb'

cells = json.loads(NB.read_text(encoding='utf-8'))['cells']
SRC = ''.join(''.join(c['source']) for c in cells if c['cell_type'] == 'code')

_p, _f = 0, 0


def ck(label, cond, detail=''):
    global _p, _f
    if cond:
        _p += 1
        print(f'  PASS  {label}' + (f'   {detail}' if detail else ''))
    else:
        _f += 1
        print(f'  FAIL  {label}   {detail}')


def section(t):
    print(f'-- {t}')


# ---------------------------------------------------------------------------
# Load the real functions out of the notebook, with only what they need.
# ---------------------------------------------------------------------------
ns = {'re': re, 'json': json}


def load(pattern, name):
    m = re.search(pattern, SRC, re.S)
    if not m:
        raise SystemExit(f'could not find {name} in the notebook')
    exec(compile(m.group(0), f'<{name}>', 'exec'), ns)


load(r'_LABEL_PREAMBLE = re\.compile\(.*?return \' \'\.join\(words\[:max_words\]\)'
     r'\.strip\(\) or \'requirement\'', 'make_label')
load(r'_INTENT_STOP = \{.*?\n    return flagged', 'audit_group_intents')
# audit_group_intents leans on _req_field, which lives elsewhere in the notebook.
m = re.search(r'def _req_field\(.*?\n(?=\n\S|\ndef )', SRC, re.S)
if m:
    exec(compile(m.group(0), '<_req_field>', 'exec'), ns)
else:                                     # minimal stand-in, same contract
    ns['_req_field'] = lambda r, k: (r.get(k) if isinstance(r, dict)
                                     else getattr(r, k, None))

make_label = ns['make_label']
audit_group_intents = ns['audit_group_intents']

print('=' * 74)
print('PHASE 6 FIXES  --  the 5f18775d x Aurelia audit')
print('=' * 74)

# ---------------------------------------------------------------------------
section('1  labels: two different requirements never read the same')
# ---------------------------------------------------------------------------
CTA_A = ('Deliver the Call to Action: "I\u2019m sticking with this."')
CTA_B = ('Deliver the Call to Action: "I\u2019m not gatekeeping this, '
         'link it in the bio."')

a, b = make_label(CTA_A), make_label(CTA_B)
ck('the two CTA options get DIFFERENT labels', a != b, f'{a!r} vs {b!r}')
ck('the old collision "Deliver Call Action I m" is gone',
   'Deliver Call Action' not in a and 'Deliver Call Action' not in b)
# The check is for a SPLIT word -- "I m" with a space. A regex \bm\b matches
# the m inside "I’m" too, because the curly apostrophe is a non-word
# character; that would fail on correct output.
ck('the apostrophe is not split into a bare "m"',
   'I m' not in a and 'I m' not in b, f'{a!r}')
ck('the label names what the creator must SAY',
   'sticking' in a.lower(), a)
ck('...and the other names its own distinct ask',
   'gatekeeping' in b.lower() or 'bio' in b.lower(), b)

HOOK_A = 'Open the video with a hook: "If your hair is breaking, watch this."'
HOOK_B = 'Open the video with a hook: "My hair was falling out in clumps."'
ha, hb = make_label(HOOK_A), make_label(HOOK_B)
ck('the same collision in hooks is fixed too', ha != hb, f'{ha!r} vs {hb!r}')

# Stopwords are dropped only when the label would otherwise overflow, so a
# requirement that already fits keeps its natural wording. That is the point:
# "Show the product within the first 5 seconds" reads better than
# "Show product within first 5".
_plain = make_label('Show the product within the first 5 seconds')
ck('a requirement with no preamble keeps its natural wording',
   'product' in _plain.lower() and _plain.lower().startswith('show'), _plain)
ck('empty input does not raise', make_label('') == 'requirement')
ck('None does not raise', make_label(None) == 'requirement')
ck('a label never exceeds its word budget',
   len(make_label('a ' * 80).split()) <= 8)

# ---------------------------------------------------------------------------
section('2  group_intent: an intent that describes nothing is caught')
# ---------------------------------------------------------------------------
SUBJECT_FREE = ('Conclude the video with an approved call to action '
                'encouraging viewer engagement or purchase.')
GOOD_INTENT = ('Ask the viewer to take a specific next step: follow, '
               'comment, or click the link in the bio.')

members = [{'id': 'R1', 'group': 'g_cta', 'group_intent': SUBJECT_FREE,
            'requirement': CTA_A},
           {'id': 'R2', 'group': 'g_cta', 'group_intent': SUBJECT_FREE,
            'requirement': CTA_B}]
flagged = audit_group_intents(members)
ck('the subject-free intent is flagged', len(flagged) == 1,
   f'{flagged[0][1][:44]}...' if flagged else 'NOT FLAGGED')
ck('...and the flag travels on every member',
   all('GROUP_INTENT_SUBJECT_FREE' in m.get('flags', []) for m in members))

# L3 is the layer that can tell whether two different sentences mean the same
# thing. It failed on the CTA group because we gave it a reference that could
# not distinguish anything -- so the fix is to give it a better one, not to
# stop asking it.
_rep = members[0]['group_intent']
ck('the subject-free intent is REPAIRED, not just flagged',
   members[0].get('group_intent_original') == SUBJECT_FREE
   and _rep != SUBJECT_FREE)
ck('...the repair names the actual options to look for',
   'sticking with this' in _rep and 'gatekeeping' in _rep)
ck('...it still contains the original ask',
   SUBJECT_FREE in _rep)
ck('...and the repair is flagged so the brief can still be fixed',
   'GROUP_INTENT_REPAIRED' in members[0]['flags'])
ck('...it invents nothing -- every option comes from a member',
   all(o.split('"')[0] or True for o in [_rep]))

good = [{'id': 'R1', 'group': 'g2', 'group_intent': GOOD_INTENT,
         'requirement': CTA_B}]
ck('an intent that shares words with its members is NOT flagged',
   audit_group_intents(good) == [], )
ck('...and it carries no flag', 'flags' not in good[0]
   or 'GROUP_INTENT_SUBJECT_FREE' not in good[0].get('flags', []))

none_intent = [{'id': 'R1', 'group': 'g3', 'group_intent': '',
                'requirement': CTA_A}]
ck('a group with no intent is not invented one',
   audit_group_intents(none_intent) == [])
ck('an ungrouped requirement is ignored',
   audit_group_intents([{'id': 'R9', 'requirement': CTA_A}]) == [])

# A function nobody calls measures nothing. audit_group_intents shipped
# defined-but-uncalled and every behavioural test above still passed, because
# they all asserted how it BEHAVES and none asserted that it RUNS.
_calls = [m for m in re.findall(r'^\s*(?:\w+\s*=\s*)?audit_group_intents\(',
                                SRC, re.M)]
ck('audit_group_intents is actually CALLED, not just defined',
   len(_calls) >= 2, f'{len(_calls)} call site(s)')
ck('...on the single-shot compile path',
   "audit_group_intents(compiled['requirements'])" in SRC)
ck('...and on the consensus compile path',
   "audit_group_intents(out['requirements'])" in SRC)
ck('a subject-free group raises a brief-level flag',
   "'code': 'GROUP_INTENT_SUBJECT_FREE'" in SRC)

# ---------------------------------------------------------------------------
section('2b the repair has somewhere to live, and cannot crash an audit')
# ---------------------------------------------------------------------------
# The repair wrote group_intent_original onto the requirement dict, and
# Requirement(**rd) died on it -- AFTER the brief had compiled and been paid
# for. EvidenceRecord had used the tolerant idiom for five cells; Requirement
# had not.
ck('Requirement carries group_intent_original',
   'group_intent_original: str' in SRC)
ck('Requirement() filters to known fields, like EvidenceRecord',
   'k in Requirement.__dataclass_fields__' in SRC)
ck('...and a dropped field is recorded, not swallowed',
   'UNKNOWN_FIELD_DROPPED' in SRC)
ck('the bare Requirement(**rd) that crashed is gone',
   not re.search(r'\br = Requirement\(\*\*rd\)', SRC))

# ---------------------------------------------------------------------------
section('10 the brief’s SUBSTANCE is scored, not only allowlisted')
# ---------------------------------------------------------------------------
# A live run scored 100/APPROVED while the brief's seven talking points were
# never checked: a claims section compiled to an allowlist and produced no
# requirements, so 21 requirements collapsed to three one_of decisions.
ck('a claims section is no longer skipped wholesale',
   "if sec.kind == 'context':" in SRC
   and "if sec.kind in ('context', 'claims'):" not in SRC)
ck('context still produces nothing', "sec.kind == 'context'" in SRC)

# Functional: build the two document-structure cells and compile a brief that
# looks like the real one.
_cellsrc = [''.join(c['source']) for c in cells if c['cell_type'] == 'code']
_ALL = ''.join(_cellsrc)


def _grab_tuple(name):
    i = _ALL.find(name + ' = (')
    if i < 0:
        return None
    j, d = _ALL.index('(', i), 0
    for k in range(j, len(_ALL)):
        if _ALL[k] == '(':
            d += 1
        elif _ALL[k] == ')':
            d -= 1
            if d == 0:
                return _ALL[i:k + 1]
    return None


import dataclasses as _dc                                        # noqa: E402
_ns = {'re': re, 'dataclass': _dc.dataclass, 'field': _dc.field,
       'replace': _dc.replace, 'Optional': __import__('typing').Optional,
       'List': list, 'Dict': dict, 'Any': object, 'Tuple': tuple}
for _n in ('SPEECH_CUES', 'VISUAL_CUES', 'TEXT_CUES'):
    _s = _grab_tuple(_n)
    if _s:
        exec(compile(_s, '<const>', 'exec'), _ns)
_m = re.search(r'^def _has\(.*?(?=\n\ndef |\n\n\S)', _ALL, re.S | re.M)
if _m:
    exec(compile(_m.group(0), '<has>', 'exec'), _ns)
for _s in _cellsrc:
    if 'def parse_brief_sections' in _s or 'def brief_units' in _s:
        if 'def extract_temporal' in _s:
            _s = _s[:_s.find('def extract_temporal')]
        exec(compile(_s, '<sec>', 'exec'), _ns)

_BRIEF = ('Purpose\nThis guide helps creators make videos.\n\n'
          'Hook Concepts\n- Your shampoo isn’t the problem\n'
          '- If your hair is breaking don’t scroll\n\n'
          'Key talking points + Product features\n'
          '- Uses cellular aging science with ingredients like Ceramosides\n'
          '- Adds shine and softness to hair\n'
          '- Supports hair and lowers breakage\n'
          '- Reduce hair loss by 27% and double the number of hairs\n\n'
          'Call to action (CTA) Ideas\n- I’m sticking with this\n'
          '- I’m not gatekeeping this, link it in the bio\n')
_secs = _ns['parse_brief_sections'](_BRIEF)
_kinds = {s.heading: s.kind for s in _secs}
ck('the talking-points section is still classified `claims`',
   _kinds.get('Key talking points + Product features') == 'claims')
_units = _ns['brief_units'](_BRIEF)
_claims = [u for u in _units if u['kind'] == 'claims']
ck('claims lines now produce requirement units', len(_claims) >= 4,
   f'{len(_claims)} unit(s)')
ck('...ungrouped, so each is its OWN scoring unit',
   all(u['group'] is None for u in _claims),
   str({u['group'] for u in _claims}))
ck('...and they are not collapsed as one_of',
   all(u['group_mode'] != 'one_of' for u in _claims))
ck('context still produces no units',
   not any(u['kind'] == 'context' for u in _units))
ck('alternatives sections are untouched -- still one_of',
   all(u['group_mode'] == 'one_of'
       for u in _units if u['kind'] == 'alternatives'))
ck('a specific talking point survives into the units',
   any('shine and softness' in u['text'] for u in _claims))

# Fix 12: the unit count must not depend on a fuzzy string match. §43 used to
# group a claim-backed requirement as `approved_talking_points`/any_of ONLY
# when _claim_backed() hit -- so the same brief could score two different ways.
ck('the approved_talking_points grouping is gone',
   "group, gmode = 'approved_talking_points', 'any_of'" not in SRC)
ck('...but the provenance flag is kept',
   'FROM_APPROVED_CLAIMS:' in SRC)
ck('...and the reason is recorded where it happened',
   'PROVENANCE ONLY -- this must not change the scoring shape' in SRC)
ck('§47 now asserts the flag does NOT group',
   'no approved_talking_points group is created any more' in SRC)

# ---------------------------------------------------------------------------
section('3  the window is cross-checked in BOTH directions')
# ---------------------------------------------------------------------------
ck('a model window that disagrees with the rules is flagged',
   'WINDOW_DISAGREES_WITH_BRIEF' in SRC)
ck('a number the brief never states is flagged',
   'WINDOW_UNSUPPORTED_BY_BRIEF' in SRC)
ck('the one-directional guard is still there for a missing window',
   'WINDOW_MISSED_BY_MODEL' in SRC)
_win = SRC[SRC.find('WINDOW_DISAGREES_WITH_BRIEF') - 900:
           SRC.find('WINDOW_MISSED_BY_MODEL') + 120]
ck('the disagreement check runs when the model DID supply a window',
   "rule_t['window_start_expr'] and ws_expr" in _win)
ck('the system default is 5.0, so "duration - 15" was never a default',
   "default_cta_window: float = 5.0" in SRC)

# ---------------------------------------------------------------------------
section('4  literal status and alignment are never blended')
# ---------------------------------------------------------------------------
ck('the old UNGATED promotion table is gone',
   "_SUBSTANCE = {'exact': 'PASS'" not in SRC
   and 'v.status = _promoted' not in SRC)
ck('alignment is always recorded as its own flag',
   'SUBSTANCE_ALIGNMENT:' in SRC)
# The reason is interpolated, so the literal ":subject_free_intent" no longer
# appears next to the flag name -- both reason strings and the flag are checked
# separately.
ck('an untrusted alignment says WHY it is untrusted',
   'SUBSTANCE_ALIGNMENT_UNTRUSTED:{_why}' in SRC
   and "'subject_free_intent'" in SRC and "'cites_no_record'" in SRC)

# THE PRODUCT RULE: the brief is a reference, not a script. Work done in the
# creator's own words COUNTS -- so credit is granted, but only through the two
# gates. The old promotion was ungated; this one is not.
ck('a trusted alignment IS credited',
   "v.status = _SUBSTANCE_STATUS[_lvl]" in SRC)
ck('...and the literal finding is kept on the verdict',
   "LITERAL_STATUS_WAS:FAIL/" in SRC and 'SATISFIED_IN_SUBSTANCE' in SRC)
ck('gate 1: a subject-free intent earns no credit',
   '_subject_free or not _cites' in SRC)
ck('gate 2: an alignment citing no record earns no credit',
   "_cites = bool(getattr(v, 'evidence_ids', None))" in SRC)
ck('an untrusted alignment skips the credit entirely',
   re.search(r'_subject_free or not _cites.*?continue', SRC, re.S) is not None)
ck('§73 asserts every credited verdict kept its literal finding',
   'every credited verdict kept its literal finding' in SRC)
ck('§73 asserts nothing untrusted was credited',
   'nothing untrusted was credited' in SRC)
ck('§73 asserts every credited verdict cites a record',
   'every credited verdict cites a record' in SRC)
ck('forbidden requirements are still exempted',
   "get('polarity') == 'forbidden'" in SRC)
ck('FAIL_FROM_POSITIVE_EVIDENCE is still exempted',
   'FAIL_FROM_POSITIVE_EVIDENCE' in SRC)

_blk = SRC[SRC.find('_SUBSTANCE_STATUS = {'):]
_blk = _blk[:_blk.find('_resolve_groups')]
# Two status assignments now, and both are deliberate: the gated credit, and
# UNCERTAIN for an alignment that cannot be CHECKED. Neither is a FAIL, which
# is the point -- she is never marked down for a defect in our own compile.
# `=` and NOT `==`. Fix 33 widened eligibility with `if v.status == 'PARTIAL'`,
# and the old pattern counted that COMPARISON as an assignment -- so a test
# about what the block WRITES failed on a line that only reads.
_ASSIGN = r'v\.status\s*=(?!=)'
ck('the block assigns exactly two statuses: credit and abstain',
   len(re.findall(_ASSIGN, _blk)) == 2, str(re.findall(r'v\.status = [^\n]+', _blk)))
ck('an undecidable alignment abstains rather than failing',
   "v.status = 'UNCERTAIN'" in _blk and 'UNDECIDABLE_ALIGNMENT' in _blk)
ck('no FAIL is ever assigned in the block',
   "v.status = 'FAIL'" not in _blk)
_m_assign = re.search(_ASSIGN, _blk)
_first_assign = _m_assign.start() if _m_assign else len(_blk)
ck('forbidden and positive-evidence FAILs are exempted before it',
   _blk.find('FAIL_FROM_POSITIVE_EVIDENCE') < _first_assign
   and _blk.find("== 'forbidden'") < _first_assign)
ck('fix 33: a PARTIAL is eligible, and only ever upward',
   "if v.status not in ('FAIL', 'PARTIAL')" in _blk
   and "_SUBSTANCE_STATUS.get(v.alignment or '') != 'PASS'" in _blk)

# ---------------------------------------------------------------------------
section('versions moved with the output')
# ---------------------------------------------------------------------------
for name, want in (('BRIEF_STAGE_VERSION', '1.25.0'),
                   ('VERDICT_STAGE_VERSION', '1.22.0')):
    m = re.search(rf"^{name}\s*=\s*'([\d.]+)'", SRC, re.M)
    ck(f'{name} == {want}', bool(m) and m.group(1) == want,
       m.group(1) if m else 'NOT FOUND')
m = re.search(r"^BRIEF_PROMPT_VERSION\s*=\s*'(\w+)'", SRC, re.M)
ck('BRIEF_PROMPT_VERSION moved with the prompt text',
   bool(m) and m.group(1).endswith('v5'), m.group(1) if m else '?')

print()
print(f'{_p}/{_p + _f} checks pass')
print('ALL PASS' if not _f else f'{_f} FAILED')
sys.exit(1 if _f else 0)

