"""Cross-check phases_1_to_7_gemini_vision.ipynb, end to end.

The expensive bug in a notebook is ORDER: a cell that uses a name an earlier
cell never defined runs fine in a warm kernel and dies on a fresh one. That is
what most of this checks, plus the things that would quietly make the Phase 7
exit criteria untrue.
"""
import ast
import builtins
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
# The batch notebook is a generated COPY of this one, so it gets exactly the
# same scrutiny: pass a path to check that instead of the default.
NB = (Path(sys.argv[1]) if len(sys.argv) > 1
      else Path(r'C:\Users\Umar Ilyas\creative project\Phase 7'
                r'\phases_1_to_7_gemini_vision.ipynb'))
R = []


def ck(label, ok, detail=''):
    R.append((label, bool(ok), detail))
    print(f'  {"PASS" if ok else "FAIL"}  {label}' + (f'   {detail}' if detail else ''))


print('=' * 78)
print('1  THE FILE')
print('=' * 78)
raw = NB.read_text('utf-8')
nb = json.loads(raw)
ck('valid JSON', True, f'{len(raw) / 1e6:.2f} MB')
ck('nbformat 4', nb.get('nbformat') == 4, str(nb.get('nbformat')))
ck('has kernelspec / language_info',
   bool(nb.get('metadata', {}).get('kernelspec')
        or nb.get('metadata', {}).get('language_info')),
   str(sorted(nb.get('metadata', {}).keys())))
cells = nb['cells']
code = [(i, ''.join(c['source'])) for i, c in enumerate(cells)
        if c['cell_type'] == 'code']
ck('every cell has a valid type',
   all(c['cell_type'] in ('code', 'markdown', 'raw') for c in cells))
ck('every code cell has the required keys',
   all({'source', 'outputs', 'execution_count', 'metadata'} <= set(c)
       for c in cells if c['cell_type'] == 'code'))
ck('outputs cleared everywhere',
   all(not c.get('outputs') for c in cells if c['cell_type'] == 'code'))
ck('no stale execution counts',
   all(c.get('execution_count') is None for c in cells
       if c['cell_type'] == 'code'))
ck('source stored as a list of lines',
   all(isinstance(c['source'], list) for c in cells))
ck('no cell ends mid-line without a newline problem',
   all(not any('\r' in l for l in c['source']) for c in cells), 'no CR')
# UTF-8 read back as latin-1 and re-encoded. It parses, it tests green, and it
# looks like nothing until a human reads the page. A build of this notebook
# really did lose every section sign this way.
MOJIBAKE = {'Ã‚Â§': 'A-circumflex before a section sign',
            'â€”': 'mangled em dash',
            'Ã¢â‚¬â„¢': 'mangled apostrophe',
            'Ã¢â‚¬Å“': 'mangled quote',
            'ÃƒÂ©': 'mangled accented e'}
_moji = {k: raw.count(k) for k in MOJIBAKE if raw.count(k)}
ck('no mojibake anywhere in the file', not _moji,
   str({MOJIBAKE[k]: v for k, v in _moji.items()}) if _moji
   else f'{raw.count(chr(0xa7))} section signs intact')

print()
print('=' * 78)
print('2  EVERY CODE CELL PARSES')
print('=' * 78)
bad = []
for i, s in code:
    try:
        ast.parse(s)
    except SyntaxError as e:
        bad.append((i, e.lineno, e.msg))
ck(f'all {len(code)} code cells parse', not bad, str(bad[:3]))

print()
print('=' * 78)
print('3  DEFINITION ORDER  (the fresh-kernel killer)')
print('=' * 78)


def defined_names(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            out |= {a.arg for a in n.args.args + n.args.kwonlyargs
                    + n.args.posonlyargs} if hasattr(n, 'args') else set()
            if getattr(getattr(n, 'args', None), 'vararg', None):
                out.add(n.args.vararg.arg)
            if getattr(getattr(n, 'args', None), 'kwarg', None):
                out.add(n.args.kwarg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, ast.Global):
            out |= set(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For,
                            ast.AsyncFor, ast.comprehension, ast.withitem,
                            ast.NamedExpr)):
            tgts = ([n.targets[0]] if isinstance(n, ast.Assign) and n.targets
                    else [getattr(n, 'target', None)] if hasattr(n, 'target')
                    else [getattr(n, 'optional_vars', None)])
            for t in tgts:
                if t is None:
                    continue
                for nn in ast.walk(t):
                    if isinstance(nn, ast.Name):
                        out.add(nn.id)
        elif isinstance(n, ast.Lambda):
            out |= {a.arg for a in n.args.args}
    return out


def loaded_names(tree):
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


BUILTIN = set(dir(builtins)) | {'__name__', '__file__', '__doc__', '_'}
# Names the Colab kernel provides, or that a cell deliberately probes for with
# globals().get before use.
AMBIENT = {'get_ipython', 'display', 'files', 'drive', 'userdata', 'In', 'Out'}


def globals_guarded(src):
    """Names a cell probes for before using: if 'X' in globals(), globals().get('X').
    Using one of those is deliberate optional behaviour, not a missing import."""
    return set(re.findall(r"""globals\(\)\.get\(['\"](\w+)""", src)) | set(
        re.findall(r"""['\"](\w+)['\"]\s+in\s+globals\(\)""", src))
def split_uses(tree):
    """
    Module-level uses vs uses inside a function body.

    They fail differently and must be judged differently. A module-level use
    of a name defined in a later cell is fatal on a fresh kernel. The same
    name inside a `def` is a DEFERRED reference: Python resolves it when the
    function is CALLED, so it only needs to exist by then. Phases 1-6 use that
    deliberately -- extract_approved_claims references rule_match_hints, which
    the next cell defines, and the first call is two cells later still.
    """
    deferred = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            deferred |= loaded_names(n)
    return loaded_names(tree) - deferred, deferred


seen = set(BUILTIN) | AMBIENT
missing, deferred_uses = [], []
all_defined, first_call = {}, {}
for i, s in code:
    try:
        t = ast.parse(s)
    except SyntaxError:
        continue
    now, later = split_uses(t)
    defd = defined_names(t) | globals_guarded(s)
    for name in sorted(now - defd - seen):
        missing.append((i, name))
    for name in sorted(later - defd - seen):
        deferred_uses.append((i, name))
    for name in defd:
        all_defined.setdefault(name, i)
    seen |= defd

ck('no name is used at MODULE level before it is defined', not missing,
   str(missing[:8]) if missing else f'{len(code)} cells checked in order')

# A deferred reference is only safe if the definition lands before the
# enclosing function is first CALLED. Approximate the call site as the first
# later cell that mentions the name outside a def -- conservative, and enough
# to catch a genuine ordering break.
unsafe = []
for i, name in deferred_uses:
    d = all_defined.get(name)
    if d is None:
        unsafe.append((i, name, 'never defined anywhere'))
    elif d <= i:
        continue
    else:
        callers = [j for j, s2 in code if j > i
                   and re.search(rf'\b{re.escape(name)}\b', s2)]
        if callers and min(callers) < d:
            unsafe.append((i, name, f'defined in {d}, reachable from {min(callers)}'))
ck('every deferred (in-function) reference is defined before it can be called',
   not unsafe, str(unsafe[:5]) if unsafe
   else f'{len(deferred_uses)} forward reference(s), all resolved in time')

print()
print('=' * 78)
print('4  SECTION NUMBERING')
print('=' * 78)
secs = []
for i, s in code:
    m = re.search(r'^# §([\w.]+)\b(.*)$', s, re.M)
    if m:
        secs.append((i, m.group(1), m.group(2).strip()[:54]))
dupes = [s for s in {x[1] for x in secs}
         if sum(1 for y in secs if y[1] == s) > 1]
ck('no duplicate section numbers', not dupes, str(dupes))
p7 = [s for s in secs if re.match(r'^(7[4-9]|8[0-2])', s[1])]
print('     Phase 6â†’7 bridge and Phase 7 sections, in notebook order:')
for i, n, t in p7:
    print(f'       cell {i:>3}  §{n:<5} {t}')
ck('§77 is placed after §79b, which it tests',
   [n for _i, n, _t in p7].index('77') > [n for _i, n, _t in p7].index('79b'),
   'position is execution order; the number is documentation')
ck('§80 runs after everything it uses',
   [n for _i, n, _t in p7].index('80') > [n for _i, n, _t in p7].index('77'))

print()
print('=' * 78)
print('5  PHASE 7 CONTENT INVARIANTS')
print('=' * 78)
def strip_comments(src):
    """A rule quoted in a comment is documentation, not a violation. An earlier
    version of this checker flagged the very comment explaining why 'cdn' is
    never used."""
    out = []
    for line in src.splitlines():
        q = None
        buf = ''
        for ch in line:
            if q:
                buf += ch
                if ch == q:
                    q = None
            elif ch in '\'"':
                q = ch
                buf += ch
            elif ch == '#':
                break
            else:
                buf += ch
        out.append(buf)
    return '\n'.join(out)


S = ''.join(s for _i, s in code)
P7SRC = ''.join(s for i, s in code if i >= min(x[0] for x in p7))
for sym in ('SCORE_STAGE_VERSION', 'STATUS_SCORE', 'DIMENSIONS',
            'TYPE_TO_DIMENSION', 'BAND_THRESHOLDS_PLACEHOLDER', 'Phase7Config',
            'score_audit', 'evaluate_recommendations', 'build_figures',
            'build_report_html', 'write_report', '_run_phase7_tests',
            'candidate_scores', 'run_discrimination'):
    ck(f'{sym} defined', re.search(rf'^\s*(def |class )?{sym}\b\s*[=(:]', S, re.M)
       is not None)

ck('PRIORITY_WEIGHT is defined once, in Phase 4',
   len(re.findall(r'^PRIORITY_WEIGHT\s*=', S, re.M)) == 1,
   f'{len(re.findall(r"^PRIORITY_WEIGHT\s*=", S, re.M))} definition(s)')
_ss = re.search(r'STATUS_SCORE = \{[^}]*\}', P7SRC)
ck('UNCERTAIN has no entry in STATUS_SCORE',
   bool(_ss) and 'UNCERTAIN' not in _ss.group(0), _ss.group(0) if _ss else 'not found')
ck('NOT_APPLICABLE has no entry in STATUS_SCORE',
   bool(_ss) and 'NOT_APPLICABLE' not in _ss.group(0))
ck('band thresholds are named PLACEHOLDER', 'BAND_THRESHOLDS_PLACEHOLDER' in P7SRC)
ck('the score artifact declares model_free', 'model_free=True' in P7SRC)
ck('plotly div ids are explicit (determinism)', 'div_id=div_id' in P7SRC)
_P7CODE = strip_comments(P7SRC)
ck('plotly is embedded, never from a CDN',
   'include_plotlyjs=(True if first else False)' in _P7CODE
   and "'cdn'" not in _P7CODE)
ck('the report escapes every insertion through esc()',
   P7SRC.count('esc(') > 40, f'{P7SRC.count("esc(")} call(s)')
ck('timestamp links carry data-t and a seek handler',
   'data-t=' in P7SRC and 'currentTime' in P7SRC)
ck('recommendations validate cited ids',
   'FABRICATED_EVIDENCE_ID' in P7SRC and 'ANCHOR_NOT_IN_CITED_EVIDENCE' in P7SRC)
ck('recommendations reject numbers and status words',
   '_rec_violations' in P7SRC and 'FORBIDDEN_WORDING' in P7SRC)
ck('word-boundary matching, not substring (the shoulder lesson)',
   r'(?<!\w){re.escape' in P7SRC)
ck('PASS_FROM_ABSENCE is held out of achievement',
   '_is_safety_pass' in P7SRC and 'PASS_FROM_ABSENCE' in P7SRC)
ck('contradictions use token_set_ratio, not partial_ratio',
   'token_set_ratio' in P7SRC and 'fuzz.partial_ratio' not in P7SRC)
ck('the score names the verdict artifact it scored', 'scored_from' in P7SRC)

print()
print('=' * 78)
print('6  PHASES 1-6 ARRIVED INTACT')
print('=' * 78)
SRC6 = json.loads((Path(r'C:\Users\Umar Ilyas\creative project\Phase 6'
                        r'\phases_1_to_6_gemini_vision.ipynb')).read_text('utf-8'))
old = [''.join(c['source']) for c in SRC6['cells'] if c['cell_type'] == 'code']
new = [s for _i, s in code]
ck('every Phase 1-6 code cell is present and byte-identical',
   new[:len(old)] == old, f'{len(old)} cells compared')
ck('Phase 7 appended, nothing spliced into Phase 1-6',
   len(new) == len(old) + 12, f'{len(new) - len(old)} new code cells')
for name, want in (('ASR_STAGE_VERSION', '1.0.0'), ('OCR_STAGE_VERSION', '1.3.0'),
                   ('VLM_STAGE_VERSION', '1.13.0'),
                   # 1.14.0: labels drop shared boilerplate; a subject-free
                   # group_intent is repaired from its own options before L3
                   # judges against it; window cross-checked both ways
                   ('BRIEF_STAGE_VERSION', '1.25.0'),
                   # 1.7.0: speech `absent` vs `degraded` in modality_health
                   ('EVIDENCE_STAGE_VERSION', '1.7.0'),
                   # 1.14.0: substance credit when both gates pass; an
                   # alignment that cannot be CHECKED abstains as UNCERTAIN
                   # rather than counting against the creator
                   ('VERDICT_STAGE_VERSION', '1.22.0')):
    m = re.search(rf"^{name}\s*=\s*'([\d.]+)'", S, re.M)
    ck(f'{name} == {want}', bool(m) and m.group(1) == want,
       m.group(1) if m else 'NOT FOUND')

print()
print('=' * 78)
print('7  HYGIENE')
print('=' * 78)
for pat, label in ((r'\bTODO\b', 'TODO'), (r'\bFIXME\b', 'FIXME'),
                   (r'\bXXX\b', 'XXX'), (r'\bHACK\b', 'HACK')):
    n = len(re.findall(pat, P7SRC))
    ck(f'no {label} left in Phase 7', n == 0, f'{n} found' if n else '')
ck('no bare "except:" in Phase 7', not re.search(r'except\s*:', P7SRC))
ck('no print of a secret', not re.search(r'print\([^)]*(api_key|API_KEY|secret)',
                                         P7SRC))
# Measured house style across Phases 1-6: 12.2% of lines over 79 chars,
# 3.0% over 88, longest 152. The bar is "no looser than the code it joins",
# not a number invented for this check.
_p7_first = min(x[0] for x in p7)
_mine = [len(l) for i, s in code if i > _p7_first for l in s.splitlines()]
_over88 = sum(1 for x in _mine if x > 88) / max(1, len(_mine))
ck('Phase 7 is no looser than the house style (3.0% over 88, max 152)',
   _over88 <= 0.030 and max(_mine) <= 152,
   f'{_over88:.2%} over 88, longest {max(_mine)}')
tabs = [i for i, s in code if '\t' in s]
ck('no tab characters', not tabs, str(tabs[:3]))
ck('no trailing whitespace in Phase 7',
   not [1 for i, s in code if i >= min(x[0] for x in p7)
        for l in s.splitlines() if l != l.rstrip()])

print()
print('=' * 78)
print('8  NO LIVE KEY IS WIRED IN')
print('=' * 78)
# This section used to assert the OPPOSITE -- that a hardcoded Gemini key and
# a paid `sk-proj-` OpenAI key were present, because that was convenient for
# testing. The harness was guarding the wrong invariant: it would have FAILED
# the moment someone removed a secret from a file that gets copied into two
# generated notebooks, three backups, and every Colab upload.
#
# Both keys have been removed and must be treated as compromised and rotated.
# Keys now come from Colab secrets / the environment, which is what §37a says.
_KEY_SHAPES = (
    (r"AQ\.[A-Za-z0-9_\-]{20,}", 'a Google AI Studio key'),
    (r"sk-proj-[A-Za-z0-9_\-]{20,}", 'a paid OpenAI project key'),
    (r"sk-[A-Za-z0-9]{32,}", 'an OpenAI key'),
    (r"AIza[A-Za-z0-9_\-]{20,}", 'a Google API key'),
)
_leaked = [what for rx, what in _KEY_SHAPES if re.search(rx, S)]
ck('no live API key is embedded in the notebook', not _leaked,
   f'FOUND {_leaked} -- rotate it, then remove it' if _leaked else 'clean')
ck('keys are read from Colab secrets / the environment',
   'NO KEY IN THIS FILE, EVER' in S and 'userdata.get(_n)' in S)
ck('paid fallback is budgeted, not unlimited', 'paid_call_budget' in S)
ck('the hosted model is probed, not assumed',
   'def probe_hosted_models' in S and 'PIN_HOSTED_MODEL' in S)

print()
bad_ = [l for l, ok, _d in R if not ok]
print('=' * 78)
print(f'{len(R) - len(bad_)}/{len(R)} checks pass')
print('ALL PASS' if not bad_ else 'FAILED:\n   ' + '\n   '.join(bad_))
print('=' * 78)

