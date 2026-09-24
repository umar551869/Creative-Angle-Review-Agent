"""Apply the Phase 6 correctness fixes to phases_1_to_6_gemini_vision.ipynb.

WHY A PATCHER AND NOT AN EDIT
-----------------------------
Phases 1-6 have no source-cell directory the way Phase 7 does -- the notebook IS
the source. Hand-editing a 9.4 MB .ipynb is not reviewable and not repeatable,
so every change to Phase 6 goes through this file: one function per fix, each
one idempotent, each one asserting it actually matched something.

Run it, then run Phase 7/verify/build_notebook.py to rebuild the Phase 7
notebook on top of the corrected Phase 6.

THE FOUR FIXES  (found on the 5f18775d x Aurelia audit, 2026-09-21)
-------------------------------------------------------------------
The video is 12.35s, music-only, and has no CTA at all. It closes on the caption
"All you need is one routine clinically tested and proven to support hair
growth" -- a product claim, not a call to action. Four separate defects turned
that into a report that was about to say PASS.

1. LABELS COLLIDE. make_label() spent its whole word budget on the boilerplate
   directive prefix every group member shares, so two different CTA options both
   printed "Deliver Call Action I m" -- and the apostrophe in "I'm" was being
   split into a bare "m".

2. group_intent WAS SUBJECT-FREE. "Conclude the video with an approved call to
   action encouraging viewer engagement or purchase" names a POSITION, not a
   thing to look for. L3 judges alignment against the intent, so any closing
   sentence aligned -- which is how a product claim rated `strong`.
   PHASE_7_PLAN.md S.0.1 predicted this exact failure; S.10 carried it forward.

3. THE WINDOW WAS UNCHECKED. The model supplied window_start_expr =
   "duration - 15"; the brief says nothing about 15 seconds. validate_time_expr
   only checks that an expression PARSES. The rule-based cross-check existed but
   fired only when the model supplied NOTHING, so a model-supplied wrong number
   passed silently. (The system's own default is 5.0, not 15 -- this was the
   model's number, not a default.)

4. THE PROMOTION HID IT.  _SUBSTANCE = {'exact':'PASS','strong':'PASS', ...}
   overwrote a literal FAIL with PASS whenever alignment was strong. With the
   speech-absent fix now permitting a real FAIL here, the re-run would have
   reported the CTA as PASS on a video with no CTA -- the false-positive PASS
   that plan.md calls the most damaging error class.

   This was the only place in the system that let ONE number from ONE model call
   change a verdict with no cross-check. Everything else requires two
   independent things to agree, or abstains. The fix is not to delete the
   signal: it is to stop BLENDING it. Literal status and alignment are now
   reported side by side, the same treatment `standing` and the decomposed mean
   already get.

STAGE VERSIONS
--------------
Fixes 1-3 change the brief artifact   -> BRIEF_STAGE_VERSION  1.12.0 -> 1.13.0
Fix 4 changes the verdict artifact    -> VERDICT_STAGE_VERSION 1.11.0 -> 1.12.0
The prompt text changed               -> BRIEF_PROMPT_VERSION  v4 -> v5

Without those bumps the cache key is unchanged, the stale artifact matches, and
the pipeline silently returns data computed by the old code. That exact failure
cost a session on 2026-09-21; see complete.md S.6.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(r'C:\Users\Umar Ilyas\creative project')
NB = ROOT / 'Phase 6' / 'phases_1_to_6_gemini_vision.ipynb'
BAK = ROOT / 'Phase 6' / 'phases_1_to_6_gemini_vision.prefix.ipynb'

S = '\u00a7'
applied, skipped = [], []

# Every (name, marker) pair the run registered, checked after the write.
#
# A marker is a claim: "if this string is here, the fix is in." Nothing used to
# check the claim, so a marker naming text the fix never emits made the fix
# report itself as pending forever -- and the run AFTER the one that applied it
# died, because by then the old anchor was gone too. Fixes 4 and 6 both shipped
# that way (`_SUBSTANCE_ALIGNMENT` for a constant actually called
# `_SUBSTANCE_STATUS`). The post-condition below makes the claim falsifiable:
# after a successful run every marker MUST be present, or the patcher failed
# and says so.
MARKERS = []


def _src(cell) -> str:
    return ''.join(cell['source'])


def _set(cell, text: str) -> None:
    cell['source'] = text.splitlines(keepends=True)


def patch(cells, name, marker, fn):
    """Apply fn to the first cell that needs it. `marker` proves idempotency:
    if it is already present anywhere, the fix is in and we do not touch it."""
    MARKERS.append((name, marker))
    whole = ''.join(_src(c) for c in cells if c['cell_type'] == 'code')
    if marker in whole:
        skipped.append(name)
        return
    for c in cells:
        if c['cell_type'] != 'code':
            continue
        before = _src(c)
        after = fn(before)
        if after is not None and after != before:
            _set(c, after)
            applied.append(name)
            return
    raise SystemExit(f'FIX DID NOT MATCH: {name} -- the notebook has moved; '
                     f'fix the patcher rather than the notebook.')


def patch_all(cells, name, marker, fn):
    """Like patch(), but applies to EVERY cell that matches.

    The version constants do not share a cell, and patch() stops at the first
    hit -- so bumping BRIEF left VERDICT untouched and the run reported success.
    A stage version that silently fails to bump is the exact failure this whole
    patch set exists to prevent.
    """
    MARKERS.append((name, marker))
    whole = ''.join(_src(c) for c in cells if c['cell_type'] == 'code')
    if marker in whole:
        skipped.append(name)
        return
    hits = 0
    for c in cells:
        if c['cell_type'] != 'code':
            continue
        before = _src(c)
        after = fn(before)
        if after is not None and after != before:
            _set(c, after)
            hits += 1
    if not hits:
        raise SystemExit(f'FIX DID NOT MATCH: {name}')
    applied.append(f'{name}  ({hits} cell(s))')


# ---------------------------------------------------------------------------
# Fix 1 -- make_label: never spend the budget on shared boilerplate
# ---------------------------------------------------------------------------
NEW_MAKE_LABEL = '''# A directive preamble is boilerplate: "Deliver the Call to Action:" is
# IDENTICAL across every member of a choice group, so spending the word budget
# on it makes every member's label read the same. Two labels that name
# different requirements must never be the same string -- the review table and
# the group-resolution line both print this, and "Not the option satisfied ...
# \\"Deliver Call Action I m\\" was (UNCERTAIN, ...)" is unreadable.
_LABEL_PREAMBLE = re.compile(
    r'^\\s*(?:deliver|include|show|use|open|close|end|finish|mention|state|'
    r'feature|demonstrate|add|ensure|make\\s+sure|do\\s+not|don.t|avoid)\\b'
    r'[^:]{0,60}:\\s*', re.I)

# Straight and curly double quotes only. The ASCII apostrophe is NOT a quote
# delimiter here -- "I'm" must survive as a word.
_LABEL_QUOTED = re.compile(r'["\\u201c]([^"\\u201d]{3,})["\\u201d]')

# Apostrophes are kept INSIDE words. Stripping them turned "I'm" into "I m",
# which is where the stray "m" in the old labels came from.
_LABEL_STRIP = re.compile(r"[^\\w\\s%$@#'\\u2019-]")


def make_label(text: str, max_words: int = 8) -> str:
    """A short name for the review table. Not an identifier.

    Order matters: drop the shared directive preamble, then prefer the quoted
    thing the creator is actually asked to say, and only THEN fall back to
    dropping stopwords to fit. Dropping stopwords first is what produced
    "Deliver Call Action I m" for two different requirements.
    """
    raw = (text or '').strip()
    body = _LABEL_PREAMBLE.sub('', raw, count=1).strip() or raw
    quoted = _LABEL_QUOTED.findall(body)
    if quoted:
        body = max(quoted, key=len).strip()
    words = _LABEL_STRIP.sub(' ', body).split()
    if not words:
        words = _LABEL_STRIP.sub(' ', raw).split()
    if len(words) > max_words:
        drop = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'in', 'on', 'at',
                'with', 'that', 'this', 'please', 'must', 'should'}
        kept = [w for w in words if w.lower() not in drop]
        # Never let stopword-dropping shred a short label into initials.
        if len(kept) >= 3:
            words = kept
    return ' '.join(words[:max_words]).strip() or 'requirement'
'''


def fix1(s):
    m = re.search(r'def make_label\(text: str, max_words: int = 5\) -> str:'
                  r'.*?return \' \'\.join\(keep\[:max_words\]\)\.strip\(\) '
                  r'or \'requirement\'\n', s, re.S)
    if not m:
        return None
    return s[:m.start()] + NEW_MAKE_LABEL + s[m.end():]


# ---------------------------------------------------------------------------
# Fix 2 -- group_intent must name the SUBJECT, not the position
# ---------------------------------------------------------------------------
OLD_INTENT_GUIDE = '''          Give every member the SAME "group_intent": one sentence saying what
          KIND of ask these options are examples of. Not a summary of the list --
          the ask behind it. For twelve hooks about hair damage that might be
          "Open by naming a hair problem the viewer recognises and creating
          enough doubt that they keep watching."
'''

NEW_INTENT_GUIDE = '''          Give every member the SAME "group_intent": one sentence saying what
          KIND of ask these options are examples of. Not a summary of the list --
          the ask behind it. For twelve hooks about hair damage that might be
          "Open by naming a hair problem the viewer recognises and creating
          enough doubt that they keep watching."

          The intent MUST name the OBSERVABLE THING, not just where it goes.
          Alignment is judged against this sentence, so an intent that names
          only a position matches anything in that position. "Conclude the
          video with a call to action" matches ANY closing sentence, including
          a product claim -- write "Ask the viewer to take a specific next
          step: follow, comment, click the link, or buy" instead. A group_intent
          that would still be true of a video that never did the thing is
          wrong. Name the act, the words, or the object to look for.
'''

OLD_INTENT_SCHEMA = '''          "group_intent": "<for an ALTERNATIVES item: one sentence naming what
                            KIND of ask these options are examples of. Identical
                            for every member of the group. Empty otherwise.>",
'''

NEW_INTENT_SCHEMA = '''          "group_intent": "<for an ALTERNATIVES item: one sentence naming what
                            KIND of ask these options are examples of, and the
                            OBSERVABLE THING to look for -- not only where in
                            the video it belongs. Identical for every member of
                            the group. Empty otherwise.>",
'''


def fix2a(s):
    if OLD_INTENT_GUIDE not in s:
        return None
    return s.replace(OLD_INTENT_GUIDE, NEW_INTENT_GUIDE, 1)


def fix2b(s):
    if OLD_INTENT_SCHEMA not in s:
        return None
    return s.replace(OLD_INTENT_SCHEMA, NEW_INTENT_SCHEMA, 1)


# A prompt cannot be trusted to have obeyed, so the compile also MEASURES it.
INTENT_AUDIT = '''

# ---------------------------------------------------------------------------
# An intent that shares no content word with any of its own members is not
# describing them. L3 judges alignment against the intent, so a subject-free
# intent rates anything in the right POSITION as aligned -- that is how a
# product claim scored `strong` against "Conclude the video with an approved
# call to action". This is a measurement, not a word blacklist: it asks whether
# the intent and the options it supposedly summarises talk about the same
# things.
# ---------------------------------------------------------------------------
_INTENT_STOP = {
    'the', 'a', 'an', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'with',
    'that', 'this', 'for', 'be', 'is', 'are', 'it', 'its', 'as', 'by', 'from',
    'video', 'viewer', 'viewers', 'clip', 'content', 'creator', 'approved',
    'one', 'any', 'their', 'them', 'they', 'you', 'your', 'must', 'should',
    'open', 'opens', 'opening', 'close', 'closes', 'closing', 'conclude',
    'concludes', 'end', 'ends', 'ending', 'start', 'starts', 'begin', 'begins',
    'first', 'last', 'final', 'finally', 'then', 'while', 'during', 'within',
    'seconds', 'second', 'sec', 'secs', 'time', 'point', 'place', 'position',
}


def _content_words(text: str) -> set:
    return {w for w in re.sub(r"[^\\w\\s'\\u2019-]", ' ', (text or '').lower()).split()
            if len(w) > 2 and w not in _INTENT_STOP}


def _member_body(text: str) -> str:
    """The DISTINGUISHING part of a requirement, for comparison.

    The shared directive preamble has to come off first. "Deliver the Call to
    Action: ..." shares `call` and `action` with the very intent
    ("Conclude the video with an approved call to action") that fails to
    describe it -- so comparing raw text finds a match and the subject-free
    intent goes unflagged. The boilerplate that broke the labels defeats this
    check the same way, for the same reason.
    """
    body = _LABEL_PREAMBLE.sub('', (text or '').strip(), count=1).strip() or (text or '')
    quoted = _LABEL_QUOTED.findall(body)
    return max(quoted, key=len) if quoted else body


def audit_group_intents(reqs: list) -> list:
    """Flag groups whose intent does not describe its own members.

    Returns [(group_id, intent, n_members)] for every group flagged, and writes
    GROUP_INTENT_SUBJECT_FREE onto each member so the flag travels with the
    requirement into the verdict and onto the report.
    """
    by_group = {}
    for r in reqs:
        g = _req_field(r, 'group')
        if g:
            by_group.setdefault(g, []).append(r)
    flagged = []
    for g, members in by_group.items():
        intent = str(_req_field(members[0], 'group_intent') or '').strip()
        if not intent:
            continue
        iw = _content_words(intent)
        if not iw:
            continue
        mw = set()
        for m in members:
            mw |= _content_words(_member_body(
                str(_req_field(m, 'requirement') or '')
                or str(_req_field(m, 'text') or '')))
        if iw & mw:
            continue
        flagged.append((g, intent, len(members)))

        # REPAIR THE REFERENCE, do not just flag it.
        #
        # L3 is the layer that can actually judge whether two different
        # sentences mean the same thing -- that is what it is for. It failed on
        # the CTA group not because it judges badly, but because we handed it
        # "Conclude the video with a call to action", which any closing
        # sentence satisfies. Given a bad reference, a good judge returns a bad
        # answer.
        #
        # So give it the real one. The options ARE the ask: appending their
        # distinguishing bodies turns a positional intent into a concrete one,
        # deterministically, inventing nothing. The flag stays, so the repair
        # is visible and the brief can still be fixed at source.
        _opts = []
        for m in members:
            _b = _member_body(str(_req_field(m, 'requirement') or '')
                              or str(_req_field(m, 'text') or '')).strip()
            if _b and _b not in _opts:
                _opts.append(_b)
        _repaired = intent
        if _opts:
            _repaired = (f'{intent} Specifically, the video should do one of '
                         f'these, in her own words: '
                         + '; '.join(f'"{o[:120]}"' for o in _opts[:8]))
        for m in members:
            if isinstance(m, dict):
                m.setdefault('flags', [])
                if 'GROUP_INTENT_SUBJECT_FREE' not in m['flags']:
                    m['flags'].append('GROUP_INTENT_SUBJECT_FREE')
                if _opts:
                    m['group_intent_original'] = intent
                    m['group_intent'] = _repaired[:1200]
                    if 'GROUP_INTENT_REPAIRED' not in m['flags']:
                        m['flags'].append('GROUP_INTENT_REPAIRED')
    return flagged
'''


def fix2c(s):
    anchor = 'def normalise_group_intents(reqs: list) -> list:'
    if anchor not in s:
        return None
    return s.replace(anchor, INTENT_AUDIT.lstrip('\n') + '\n\n' + anchor, 1)


# ---------------------------------------------------------------------------
# Fix 3 -- cross-check the model's window in BOTH directions
# ---------------------------------------------------------------------------
OLD_WINDOW = """        if rule_t['window_start_expr'] and not ws_expr and ws_abs is None:
"""

NEW_WINDOW = """        # The cross-check used to run in ONE direction only: it fired when the
        # model supplied NOTHING. A model that supplied a WRONG number passed
        # silently, because validate_time_expr only checks that an expression
        # parses. On the 5f18775d audit the model produced "duration - 15" for
        # every CTA requirement while the brief never mentions 15 seconds, and
        # on a 12.35s video that clamps to 0 -- so the constraint did nothing
        # and nothing said so.
        if rule_t['window_start_expr'] and ws_expr and \\
                rule_t['window_start_expr'] != ws_expr:
            f.append(f'WINDOW_DISAGREES_WITH_BRIEF:model={ws_expr};'
                     f'rules={rule_t["window_start_expr"]}')
        # A number the brief never states is the model's invention. The brief
        # text is the only authority for a number that constrains the creator.
        if ws_expr and not rule_t['window_start_expr']:
            _nums = re.findall(r'\\d+(?:\\.\\d+)?', str(ws_expr))
            _unsupported = [n for n in _nums
                            if not re.search(r'\\b' + re.escape(n.rstrip('.0') or n)
                                             + r'\\b', text or '')]
            if _unsupported:
                f.append(f'WINDOW_UNSUPPORTED_BY_BRIEF:{ws_expr};'
                         f'not_in_brief={",".join(_unsupported)}')
        if rule_t['window_start_expr'] and not ws_expr and ws_abs is None:
"""


def fix3(s):
    if OLD_WINDOW not in s:
        return None
    return s.replace(OLD_WINDOW, NEW_WINDOW, 1)


# ---------------------------------------------------------------------------
# Fix 4 -- stop blending literal status with alignment
# ---------------------------------------------------------------------------
OLD_PROMOTE_HEAD = "    _SUBSTANCE = {'exact': 'PASS', 'strong': 'PASS', 'partial': 'PARTIAL'}"

NEW_PROMOTE = '''    # ---- substance counts, but only when the alignment can be trusted -----
    # THE PRODUCT RULE: the brief is a REFERENCE, not a script. The creator has
    # to talk about the same things; the hooks, CTAs and explanations may be
    # her own. So a requirement met in her own words is MET, and literal
    # matching is not the standard.
    #
    # That is what the old promotion tried to do, and it was right in intent
    # and unsafe in mechanism: it trusted one uncross-checked model call, it
    # judged alignment against a group_intent that often named only a POSITION
    # ("conclude the video with a call to action" -- which any closing sentence
    # satisfies), and it OVERWROTE the literal status so nothing downstream
    # could tell the two apart. On a 12.35s video with no CTA at all, that
    # printed PASS.
    #
    # Three things changed, so the credit can now be granted safely:
    #   1. audit_group_intents() detects the subject-free intent that made the
    #      Aurelia alignment meaningless. That is the guard that would have
    #      caught it.
    #   2. An alignment citing no record is an assertion, not a finding, and
    #      earns nothing.
    #   3. The literal status is KEPT on the verdict, so Phase 7 reports a
    #      literal score beside the credited one. Nothing is hidden, and the
    #      two are never merged into one opaque number.
    # Where the alignment cannot be trusted, the literal FAIL stands.
    _SUBSTANCE_STATUS = {'exact': 'PASS', 'strong': 'PASS', 'partial': 'PARTIAL'}
    # This block used to overwrite a literal FAIL with PASS whenever alignment
    # was `strong` or `exact`. It was the only place in the system where ONE
    # number from ONE model call changed a verdict with no cross-check --
    # everywhere else two independent things must agree, or the system
    # abstains. On a 12.35s music-only video with no CTA at all, L3 returned
    # FAIL + alignment `strong` against a subject-free group_intent, and this
    # promoted it to PASS: the false-positive PASS plan.md calls the most
    # damaging error class.
    #
    # The signal is not discarded -- it is carried alongside, the same
    # treatment `standing` and the decomposed mean already get. Phase 7 scores
    # the literal status and reports alignment beside it, so a reader sees
    # "FAIL literally, strong alignment" and can judge. A single blended number
    # cannot be un-blended downstream.
    for v in verdicts:
        if v.status != 'FAIL':
            continue
        # A forbidden rule FAILs because the prohibited thing was FOUND, and a
        # FAIL from positive evidence is the same shape. Neither is a creator
        # phrasing something her own way.
        if (v.evidence_mode and any(str(f).startswith('FAIL_FROM_POSITIVE_EVIDENCE')
                                    for f in v.flags)):
            continue
        _rd = next((r for r in reqs if r.get('id') == v.requirement_id), None)
        if (_rd or {}).get('polarity') == 'forbidden':
            continue
        _lvl = v.alignment or ''
        if _lvl not in _SUBSTANCE_STATUS:
            continue
        v.flags.append(f'SUBSTANCE_ALIGNMENT:{_lvl}')

        # ---- the two gates -------------------------------------------------
        # A subject-free intent that was REPAIRED at compile time is fine: L3
        # judged against the repaired reference, which names the options
        # themselves. The gate exists to catch an alignment judged against a
        # reference that could not distinguish anything -- not to punish a
        # group for how the model first worded its summary.
        _rflags = (_rd or {}).get('flags') or []
        _subject_free = ('GROUP_INTENT_SUBJECT_FREE' in _rflags
                         and 'GROUP_INTENT_REPAIRED' not in _rflags)
        _cites = bool(getattr(v, 'evidence_ids', None))
        if _subject_free or not _cites:
            _why = ('subject_free_intent' if _subject_free else 'cites_no_record')
            v.flags.append(f'SUBSTANCE_ALIGNMENT_UNTRUSTED:{_why}')
            # NOT a FAIL. The alignment says she may well have done something
            # relevant; what we cannot do is CHECK it -- because OUR compiler
            # wrote a subject-free intent, or because the judgement cited no
            # record. Scoring that 0 penalises the creator for our defect.
            #
            # UNCERTAIN is exactly this case: "we could not tell", an
            # abstention that leaves the numerator instead of counting as a
            # failure (design rule 3). Coverage drops, which is the honest
            # report -- and it is visible, so the brief can be fixed.
            v.flags.append('UNDECIDABLE_ALIGNMENT')
            v.status = 'UNCERTAIN'
            v.reason = (
                f'Cannot be decided. She may have done this in her own words -- '
                f'alignment {_lvl} -- but '
                + ('the group intent it was judged against names only a '
                   'position in the video, not a thing to look for, so that '
                   'alignment cannot be checked. Fix the brief\\'s wording for '
                   'this group and it becomes decidable.'
                   if _subject_free else
                   'it cites no record, so there is nothing to check it '
                   'against.')
                + f' Not counted against her. {v.reason}')[:600]
            continue

        # ---- credited: she made her own version, and it checks out ---------
        v.flags.append(f'LITERAL_STATUS_WAS:FAIL/{_lvl}')
        v.flags.append('SATISFIED_IN_SUBSTANCE')
        v.status = _SUBSTANCE_STATUS[_lvl]
        v.reason = (
            f'Met in substance, not in the brief\\'s wording: {_lvl} alignment '
            f'with what this requirement asks for, cited to the record where '
            f'she says it her own way. The brief is a reference, not a script. '
            f'Literal match: no. {v.reason}')[:600]
'''


def fix4(s):
    i = s.find(OLD_PROMOTE_HEAD)
    if i < 0:
        return None
    end = s.find('    verdicts = _resolve_groups(verdicts, cfg)', i)
    if end < 0:
        return None
    return s[:i] + NEW_PROMOTE + '\n' + s[end:]


# ---------------------------------------------------------------------------
# Fix 6 -- the §73 hand-off counted a promotion that can no longer happen
# ---------------------------------------------------------------------------
OLD_HANDOFF_HEAD = """    _subst = [v for v in vs
              if any(str(f) == 'SATISFIED_IN_SUBSTANCE' for f in v.get('flags') or [])]"""

NEW_HANDOFF = '''    # The brief is a reference, not a script: a requirement met in the
    # creator's own words is MET. So the question is no longer "was anything
    # promoted" -- it is "was every promotion EARNED", and the two gates are
    # what earns it.
    _subst = [v for v in vs
              if any(str(f).startswith('SUBSTANCE_ALIGNMENT:')
                     for f in v.get('flags') or [])]
    _untrusted = [v for v in _subst
                  if any(str(f).startswith('SUBSTANCE_ALIGNMENT_UNTRUSTED')
                         for f in v.get('flags') or [])]
    _credited = [v for v in _subst
                 if any(str(f) == 'SATISFIED_IN_SUBSTANCE'
                        for f in v.get('flags') or [])]
    crit('every credited verdict kept its literal finding',
         all(any(str(f).startswith('LITERAL_STATUS_WAS')
                 for f in v.get('flags') or []) for v in _credited),
         f'{len(_credited)} credited; the literal FAIL travels with each one')
    crit('nothing untrusted was credited',
         not (set(id(v) for v in _untrusted) & set(id(v) for v in _credited)),
         'a subject-free intent or an uncited alignment earns no PASS')
    crit('an undecidable alignment is UNCERTAIN, never a FAIL',
         all(v.get('status') in ('UNCERTAIN', 'NOT_APPLICABLE')
             for v in _untrusted),
         f'{len(_untrusted)} could not be checked -- abstained, not counted '
         f'against her')
    crit('every credited verdict cites a record',
         all(v.get('evidence_ids') for v in _credited),
         'an alignment with nothing to check it against is an assertion')
    crit('no forbidden rule was credited',
         not any(v.get('polarity') == 'forbidden' for v in _subst),
         'a forbidden FAIL means the prohibited thing was found')
    if _credited:
        L.append(f'  NOTE  {len(_credited)} requirement(s) were met in her own '
                 f'words, not the brief\\'s.')
        L.append('        The brief is a reference, not a script. Each kept its '
                 'literal finding,')
        L.append('        and Phase 7 reports a literal-only score beside the '
                 'credited one.')
    if _untrusted:
        L.append(f'  WARN  {len(_untrusted)} alignment(s) could not be CHECKED '
                 f'-- the group intent names')
        L.append('        only a position, or nothing was cited. Those are '
                 'UNCERTAIN, not FAIL:')
        L.append('        she is not marked down for a defect in the compiled '
                 'brief. Fix the')
        L.append('        brief wording for those groups and they become '
                 'decidable.')
'''


def fix6(s):
    i = s.find(OLD_HANDOFF_HEAD)
    if i < 0:
        return None
    end = s.find("    _decided = [v for v in vs if v['status'] in", i)
    if end < 0:
        return None
    return s[:i] + NEW_HANDOFF + '\n' + s[end:]


# ---------------------------------------------------------------------------
# Fix 7 -- WIRE THE AUDIT IN.  A function nobody calls measures nothing.
#
# audit_group_intents() was defined and never called, which made the whole
# subject-free half of fix 2 inert -- and with it the SUBSTANCE_ALIGNMENT_-
# UNTRUSTED path in fix 4 and the two warning tags on the report. Everything
# tested green because every test asserted the function BEHAVED correctly, and
# none asserted it RAN.
# ---------------------------------------------------------------------------
OLD_CALL_A = """    try:
        normalise_group_intents(compiled['requirements'])
    except Exception:
        pass
"""

NEW_CALL_A = """    try:
        normalise_group_intents(compiled['requirements'])
        audit_group_intents(compiled['requirements'])
    except Exception:
        pass
"""

OLD_CALL_B = """        _fixed_intents = normalise_group_intents(out['requirements'])
"""

NEW_CALL_B = """        _fixed_intents = normalise_group_intents(out['requirements'])
        # One group, one ask -- and the ask has to describe its own options.
        _blind_intents = audit_group_intents(out['requirements'])
        if _blind_intents:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'GROUP_INTENT_SUBJECT_FREE',
                'detail': f'{len(_blind_intents)} group(s) carry an intent that '
                          f'shares no content word with their own options: '
                          f'{[g for g, _i, _n in _blind_intents][:4]}'}]
            if verbose:
                print(f'  WARN  {len(_blind_intents)} group intent(s) name a '
                      f'POSITION, not a thing to look for:')
                for _g, _i, _n in _blind_intents[:3]:
                    print(f'     {_g} ({_n} options): "{_i[:70]}"')
                print('    L3 judges alignment against this sentence, so it '
                      'will rate anything')
                print('    in the right position as aligned. Those alignments '
                      'are marked untrusted.')
"""


def fix7a(s):
    if OLD_CALL_A not in s:
        return None
    return s.replace(OLD_CALL_A, NEW_CALL_A, 1)


def fix7b(s):
    if OLD_CALL_B not in s:
        return None
    return s.replace(OLD_CALL_B, NEW_CALL_B, 1)


# ---------------------------------------------------------------------------
# Fix 8 -- put the model that actually serves FIRST in the ladder
#
# Phase 3 measured this and acted on it:
#     gemini-flash-latest        503 UNAVAILABLE (overloaded, intermittent)
#     gemini-flash-lite-latest   OK in 2s   <-- the only one that serves
# ... and set DEFAULT_MODELS = ('gemini-flash-lite-latest',). Phase 4/6 kept
# the old order, so EVERY brief-compile and EVERY L3 adjudication burned two
# dead round trips -- plus transient back-off sleeps -- before reaching the
# model that works. On a 21-requirement audit with hook, claims, angle and
# standing calls on top, that is minutes of pure latency per run, which reads
# as a hang and gets the cell killed.
#
# The dead models stay in the ladder as fallback (a 429 is a quota, not a
# tombstone -- they may serve again tomorrow). They are simply no longer FIRST.
# This changes no output, so no stage version moves: it is ordering only.
# ---------------------------------------------------------------------------
OLD_LADDER = """    hosted_model: str = 'gemini-flash-latest'
    hosted_model_ladder: tuple = ('gemini-flash-latest', 'gemini-pro-latest',
                                  'gemini-flash-lite-latest')"""

NEW_LADDER = """    # ORDER IS MEASURED, NOT ALPHABETICAL. Phase 3 found flash-lite to be the
    # only model that reliably serves on a free key; flash-latest returns 503
    # UNAVAILABLE and pro-latest 429 RESOURCE_EXHAUSTED. Putting either first
    # costs two dead round trips on every single call, which on a full audit
    # is minutes of latency that looks exactly like a hang.
    # They stay in the ladder -- a 429 is a quota, not a tombstone -- but they
    # are tried AFTER the one that works.
    hosted_model: str = 'gemini-flash-lite-latest'
    hosted_model_ladder: tuple = ('gemini-flash-lite-latest',
                                  'gemini-flash-latest', 'gemini-pro-latest')"""


def fix8(s):
    if OLD_LADDER not in s:
        return None
    return s.replace(OLD_LADDER, NEW_LADDER, 1)


# ---------------------------------------------------------------------------
# Fix 9 -- the repaired intent needs somewhere to live, and Requirement()
#          must stop exploding on a field it has not met
#
# The repair in fix 2 writes `group_intent_original` onto the requirement dict.
# Requirement is a dataclass with a fixed field set, so resolve_brief_for_video
# died with `unexpected keyword argument 'group_intent_original'` -- AFTER the
# brief had compiled and cached, i.e. in the middle of a paid audit run.
#
# Two parts, and the second is the one that matters:
#   a) give the provenance a real home in the schema
#   b) construct Requirement the way EvidenceRecord is ALREADY constructed --
#      filtering to known fields. That idiom exists five cells away and was
#      never applied here, which is why adding one field upstream could take
#      down the audit. Unknown keys are recorded on the requirement rather than
#      silently dropped, so nothing disappears without saying so.
# ---------------------------------------------------------------------------
OLD_FIELD = """    group_intent: str = ''
"""

NEW_FIELD = """    group_intent: str = ''
    # When the compiled intent named only a POSITION ("conclude the video
    # with a call to action" -- which any closing sentence satisfies), it is
    # repaired from the group's own options before L3 judges against it. The
    # wording the model first produced is kept here, so the repair is
    # auditable and the brief can still be fixed at source.
    group_intent_original: str = ''
"""

OLD_CTOR = """        r = Requirement(**rd)"""

NEW_CTOR = """        # Filter to known fields, exactly as EvidenceRecord is built. A brief
        # artifact compiled by a newer version carries fields this dataclass
        # has not met, and an audit is the worst possible place to discover
        # that: the compile has already happened and been paid for.
        _known = {k: v for k, v in rd.items()
                  if k in Requirement.__dataclass_fields__}
        _dropped = sorted(set(rd) - set(_known))
        r = Requirement(**_known)
        if _dropped:
            # Recorded, not swallowed. A field that vanishes silently is how a
            # schema drifts without anyone noticing.
            r.flags = list(r.flags or []) + [f'UNKNOWN_FIELD_DROPPED:{",".join(_dropped)}']"""


def fix9a(s):
    if OLD_FIELD not in s:
        return None
    return s.replace(OLD_FIELD, NEW_FIELD, 1)


def fix9b(s):
    if OLD_CTOR not in s:
        return None
    return s.replace(OLD_CTOR, NEW_CTOR, 1)


# ---------------------------------------------------------------------------
# Fix 10 -- the brief's SUBSTANCE must be scored, not just its hooks and CTAs
#
# Measured on a live run: a video scored 100 / APPROVED while the brief's
# "Key talking points + Product features" -- Ceramosides, shine and softness,
# fewer split ends, 27% hair-loss reduction -- was never checked at all.
#
# 21 requirements collapsed to THREE scoring units, because the brief was three
# one_of groups (hooks, creative concepts, CTAs) and a one_of group is one
# decision. The seven talking points contributed nothing: a claims section
# compiled to an allowlist and produced no requirements, so the score answered
# "did she use a hook, a concept and a CTA?" and never "did she talk about the
# product?".
#
# The allowlist is still right for what it does -- it is how the forbidden rule
# knows which figures are accurate. It is just not the ONLY thing a claims
# section is. The talking points are the substance the creator was asked to
# communicate, and the product rule is that she must talk about the same stuff
# in her own words.
#
# So claims sections now ALSO flow through the ordinary non-alternatives path:
# each line becomes its own requirement, ungrouped, hence its own scoring unit.
# Coverage is then real -- three of seven talking points is 43% of Messaging,
# not an invisible zero. Nothing is demanded verbatim: substance credit still
# applies, so saying "it made my hair shiny" satisfies "adds shine and
# softness".
#
# Dimension weighting keeps this balanced on its own. Seven messaging
# requirements average among themselves and Messaging then contributes its own
# share, so a long talking-points list cannot swamp the hook or the CTA.
#
# extract_approved_claims() reads parse_brief_sections() independently, so the
# allowlist and the figure-fidelity rule are untouched by this.
# ---------------------------------------------------------------------------
OLD_SKIP = """        if sec.kind in ('context', 'claims'):
            continue"""

NEW_SKIP = """        # context produces nothing -- "Purpose: this guide helps creators..."
        # is background, and no video can satisfy it.
        #
        # claims sections DO produce requirements now. They also still produce
        # the allowlist, via extract_approved_claims() on its own pass; the two
        # readings are independent and both are wanted. A brief's talking
        # points are the substance it is asking the creator to communicate, and
        # a score that ignores them says 100 for a video that never mentioned
        # the product's benefits.
        if sec.kind == 'context':
            continue"""


def fix10(s):
    if OLD_SKIP not in s:
        return None
    return s.replace(OLD_SKIP, NEW_SKIP, 1)


# decomposition_health counts "lines that could BECOME a requirement", to catch
# a 3-line brief exploding into 12 requirements. Claims lines can become one
# now, so they belong in that denominator -- leaving them out would report the
# extra talking-point requirements as over-decomposition.
OLD_DECOMP = """        lines = [l for s in parse_brief_sections(brief_text)
                 if s.kind not in ('context', 'claims') for l in s.lines]"""

NEW_DECOMP = """        # claims lines DO become requirements now (fix 10), so they count
        # toward the denominator. Excluding them would read the talking-point
        # requirements as over-decomposition of a brief that never got credit
        # for those lines in the first place.
        lines = [l for s in parse_brief_sections(brief_text)
                 if s.kind != 'context' for l in s.lines]"""


def fix10b(s):
    if OLD_DECOMP not in s:
        return None
    return s.replace(OLD_DECOMP, NEW_DECOMP, 1)


# ---------------------------------------------------------------------------
# Fix 11 -- §47 still asserted that claims produce nothing
#
# Two Phase 4 tests encoded the OLD rule and failed the moment fix 10 landed,
# which is exactly what they were there for. They are updated to the new rule
# rather than deleted: a claims section is no longer allowlist-ONLY.
#
# Worth recording, because it was already in the notebook and dormant:
# normalize_requirements ALREADY groups any claim-backed requirement as
# `approved_talking_points` / any_of --
#
#     "a talking point, not an obligation. Group them as any_of: the video
#      must cover at least one, not every single one."
#
# That machinery could never fire while brief_units skipped claims sections,
# because no talking-point requirement was ever emitted to group. Fix 10 feeds
# it, so the talking points now arrive as ONE any_of scoring unit -- the
# "middle option" the design had already chosen, not the per-point coverage
# first assumed.
# ---------------------------------------------------------------------------
OLD_T1 = """    check('benefit bullets produce no requirement to perform them',
          not any('Ceramosides' in t for t in texts),
          'they are things the creator MAY say, not must')"""

NEW_T1 = """    # Fix 10: a claims section is no longer allowlist-ONLY. Its lines become
    # requirements as well, so the score can ask whether she actually talked
    # about the product -- a video that mentions none of the brief's benefits
    # used to score 100. normalize_requirements then groups anything
    # claim-backed as `approved_talking_points` / any_of, so the ask is "cover
    # at least one", not "recite them all".
    check('benefit bullets DO become requirements now',
          any('Ceramosides' in t for t in texts),
          'the brief asked her to talk about this, so the score must check it')
    check('...and the allowlist is still built from the same section',
          any('Ceramosides' in c['text'] for c in extract_approved_claims(secs)),
          'both readings of a claims section are wanted')"""

OLD_T2 = """    check('claims are still an allowlist, not requirements',
          not any('27%' in t for t in ptexts))"""

NEW_T2 = """    check('claims lines become requirements here too',
          any('27%' in t for t in ptexts),
          'plain-text briefs get the same treatment as markdown ones')"""


def fix11a(s):
    if OLD_T1 not in s:
        return None
    return s.replace(OLD_T1, NEW_T1, 1)


def fix11b(s):
    if OLD_T2 not in s:
        return None
    return s.replace(OLD_T2, NEW_T2, 1)


# ---------------------------------------------------------------------------
# Fix 12 -- the fuzzy match leaves the SCORING path and stays on the
#           REPORTING path
#
# §43 grouped a claim-backed requirement as `approved_talking_points` / any_of
# -- one scoring unit, "cover at least one" -- but ONLY when _claim_backed()
# managed to match its brief_span back to an approved claim. On the 2026-09-21
# run that match missed, so the talking points stayed ungrouped and scored
# individually. Messaging read 50% instead of 100%, which is the more useful
# answer, but it happened by accident.
#
# That is the real defect: the same brief could score two different ways
# depending on whether a string match happened to hit. A fuzzy match is fine
# for "which brief claim did this come from" -- provenance, best-effort, no
# harm if it misses. It is not good enough to decide HOW MANY SCORING UNITS
# EXIST. An unstable verdict semantics would poison every Phase 8 label.
#
# So the grouping goes and the FLAG stays. Claims-derived requirements are now
# ALWAYS individual scoring units, whatever _claim_backed does, and the flag
# still records the source claim so the report can say which talking points
# were covered and which were missed.
#
# Per-point was also the recoverable choice: "did she cover at least one" can
# be computed from individual verdicts at any time, while per-point coverage
# can never be recovered from a single any_of unit. If it proves too harsh,
# the lever is PRIORITY (weight), not grouping -- a weight is safe to retune
# after labelling begins; a semantics change is not.
# ---------------------------------------------------------------------------
OLD_TP_GROUP = """            if _src_claim:
                group, gmode = 'approved_talking_points', 'any_of'
                f.append(f'FROM_APPROVED_CLAIMS:{_src_claim[:48]}')"""

NEW_TP_GROUP = """            if _src_claim:
                # PROVENANCE ONLY -- this must not change the scoring shape.
                # Grouping here made the unit count depend on a fuzzy match.
                f.append(f'FROM_APPROVED_CLAIMS:{_src_claim[:48]}')"""


def fix12(s):
    if OLD_TP_GROUP not in s:
        return None
    return s.replace(OLD_TP_GROUP, NEW_TP_GROUP, 1)


# The §47 block that asserted the grouping now asserts the opposite: the flag
# is provenance, and the scoring shape does not depend on it.
OLD_TP_TESTS = """    tp_grouped = [r for r in tp_reqs if r.group == 'approved_talking_points']
    check('talking-point requirements are grouped', len(tp_grouped) == 2,
          str([(r.label, r.group) for r in tp_reqs]))
    check('...as any_of, not one_of',
          all(r.group_mode == 'any_of' for r in tp_grouped),
          'the video must cover at least one, not exactly one')
    check('...and each says which claim it came from',
          all(any(f.startswith('FROM_APPROVED_CLAIMS') for f in r.flags)
              for r in tp_grouped))
    check('a genuine requirement is NOT swept into the group',
          any(r.group is None and 'first 5 seconds' in r.requirement for r in tp_reqs),
          str([(r.requirement[:34], r.group) for r in tp_reqs]))
    check('the group is one scoring unit, not two',
          sum(1 for u in scoring_units(tp_reqs) if u['kind'] == 'group') == 1,
          str(scoring_units(tp_reqs)))"""

NEW_TP_TESTS = """    tp_flagged = [r for r in tp_reqs
                  if any(f.startswith('FROM_APPROVED_CLAIMS') for f in r.flags)]
    check('a claim-backed requirement says which claim it came from',
          len(tp_flagged) == 2,
          str([(r.label, [f for f in r.flags
                          if f.startswith('FROM_APPROVED_CLAIMS')])
               for r in tp_reqs]))
    check('...but the flag does NOT group it',
          all(r.group is None for r in tp_flagged),
          'provenance may be fuzzy; the scoring shape may not be')
    check('...so each talking point is its own scoring unit',
          len([u for u in scoring_units(tp_reqs)]) == len(tp_reqs),
          str(scoring_units(tp_reqs)))
    check('no approved_talking_points group is created any more',
          not any(r.group == 'approved_talking_points' for r in tp_reqs),
          'the unit count must not depend on a string match')
    check('a requirement with no matching claim is unaffected',
          any(r.group is None and 'first 5 seconds' in r.requirement
              for r in tp_reqs),
          str([(r.requirement[:34], r.group) for r in tp_reqs]))"""


def fix12b(s):
    if OLD_TP_TESTS not in s:
        return None
    return s.replace(OLD_TP_TESTS, NEW_TP_TESTS, 1)


# ---------------------------------------------------------------------------
# Fix 13 -- L2 crashed the moment it actually matched something
#
#     AttributeError: 'dict' object has no attribute 'id'
#
# l2_similarities() returns [(candidate, cosine)] where a candidate is a DICT
# carrying a 'record'. The function knows this -- two lines above it writes
# `rec = best['record']`, and _conjunctive_shortfall(rd, top) is correctly
# handed those dicts. Only the evidence_ids expression forgot, and reached for
# `.id` on the wrapper instead of the record inside it.
#
# WHY IT SURVIVED THIS LONG: the bug is in the branch taken only when the best
# cosine clears high_threshold_PLACEHOLDER -- L2 deciding a requirement
# outright. Until claims sections started producing requirements (fix 10),
# almost everything either resolved at L1 or escalated past L2 to L3, so the
# PASS/PARTIAL branch was never taken on real data. Making the brief's
# substance scoreable is what finally sent a requirement down it.
#
# Both call sites are wrong in the same way, so both are fixed.
# ---------------------------------------------------------------------------
OLD_L2_IDS = "'L2', evidence_ids=[c.id for c in top],"
NEW_L2_IDS = ("'L2', evidence_ids=[c['record'].id for c in top],"
              "   # a candidate is a DICT around a record")


def fix13(s):
    if OLD_L2_IDS not in s:
        return None
    return s.replace(OLD_L2_IDS, NEW_L2_IDS)          # BOTH occurrences


# ---------------------------------------------------------------------------
# Fix 14 -- a section the brief calls REQUIREMENTS is not a menu
#
# Measured on the Back-to-School brief:
#
#   Creative Concepts            alternatives  11 lines
#   Back to School Campaign      requirements   8 lines   <-- eight ASKS
#   Hooks                        alternatives  10 lines
#   Key Talking Points/Features  claims         8 lines
#   Call to Actions              requirements   5 lines   <-- five ASKS
#
#   -> 19 requirements, "4 choice groups covering 18 alternatives",
#      FIVE scoring units. Exactly ONE requirement was left ungrouped.
#
# So eight campaign requirements collapsed into one decision: satisfy any one
# of them and the group scores as met. The brief's substance -- the campaign
# asks and the talking points -- ended up as two units out of five, while
# "did she use an approved hook" and "did she use an approved CTA" took the
# rest. That is why the scores read wrong: the score was measuring FORM.
#
# brief_units() gets this right already -- `alt = sec.kind == 'alternatives'`,
# so a requirements section yields group=None, group_mode='all_of'. The group
# is then thrown away, because normalize_requirements reads `group` and
# `group_mode` from the MODEL'S JSON instead, and the only checks on it are
# enum-shape ones. Nothing ever compared the group against the section the
# requirement came from.
#
# Design rule: a prompt instruction is a request, not a guarantee -- so measure
# it. The document's own structure is the authority here, the same way §75
# reads the brief's grouping rather than trusting the compiler's `type`.
#
# CONSERVATIVE BY CONSTRUCTION: a group is stripped only when the requirement
# can be POSITIVELY placed in a non-alternatives section AND matches no
# alternatives line. A requirement we cannot place keeps whatever the model
# said, so a paraphrased hook option is never torn out of its group.
# ---------------------------------------------------------------------------
STRUCTURE_GUARD = '''

# ---------------------------------------------------------------------------
# The brief's STRUCTURE decides what is a choice. The model only proposes.
# ---------------------------------------------------------------------------
def _norm_line(s: str) -> str:
    return re.sub(r'[^a-z0-9 ]+', ' ', (s or '').lower()).strip()


def _heading_matched(heading: str, kind: str) -> bool:
    """Did this heading actually MATCH a cue for `kind`, or just default to it?

    THE DISTINCTION THAT MAKES THIS SAFE. `requirements` is the fallback kind:
    a heading matching no cue at all lands there. Measured on a live brief,
    "Call to Actions" and "Back to School Campaign" match nothing, defaulted to
    `requirements`, and the guard below then ungrouped four alternative CTA
    phrasings into four separate mandatory asks -- so a creator who used one
    approved CTA, correctly, failed three. One video fell from 86 to 30.

    A DEFAULT IS NOT EVIDENCE. Only a heading that positively matched a cue is
    allowed to overrule the model's grouping; everything else keeps whatever
    the model decided, which is the safer half of the trade.
    """
    h = (heading or '').lower()
    for k, pats in SECTION_KIND_CUES:
        if k != kind:
            continue
        return any(re.search(p, h) for p in pats)
    return False


def _section_index(brief_text: str) -> tuple:
    """(alternatives_lines, fixed_lines) as normalised strings.

    `fixed` means a section the brief EXPLICITLY presented as asks in their own
    right -- a heading that really matched a `requirements` or `claims` cue.
    Their members are not options in a menu.
    """
    alt, fixed = set(), set()
    try:
        for sec in parse_brief_sections(brief_text or ''):
            if sec.kind == 'alternatives':
                bucket = alt
            elif (sec.kind in ('requirements', 'claims')
                  and _heading_matched(sec.heading, sec.kind)):
                bucket = fixed
            else:
                bucket = None          # defaulted, or context: not authoritative
            if bucket is None:
                continue
            for ln in sec.lines:
                n = _norm_line(ln)
                if len(n) >= 4:
                    bucket.add(n)
    except Exception:
        pass
    return alt, fixed


def _placed_in(needle: str, lines: set) -> bool:
    """Is this requirement recognisably one of those lines?

    EXACT equality counts at any length; SUBSTRING containment needs 12+
    characters. The length guard exists to stop a short fragment matching half
    the brief -- it must not stop a short LINE matching itself. Real CTA lines
    are short: "Link in bio" normalises to 11 characters and was being skipped,
    so a CTA the brief lists as an ask kept a group it should never have had.
    """
    n = _norm_line(needle)
    if len(n) < 4:
        return False
    if n in lines:
        return True
    if len(n) < 12:
        return False
    return any(n in ln or ln in n for ln in lines)


def ungroup_non_alternatives(reqs: list, brief_text: str) -> list:
    """Strip a choice group the document does not support. Returns what changed.

    A model that groups eight campaign requirements as `one_of` turns eight
    asks into one decision, and the score stops measuring seven of them.
    """
    alt, fixed = _section_index(brief_text)
    if not fixed:
        return []
    changed = []
    for r in reqs:
        g = _req_field(r, 'group')
        if not g or _req_field(r, 'group_mode') not in ('one_of', 'any_of'):
            continue
        span = str(_req_field(r, 'brief_span') or '')
        text = str(_req_field(r, 'requirement') or _req_field(r, 'text') or '')
        # Only act when we can positively place it OUTSIDE an alternatives
        # section. Anything we cannot place keeps the model's grouping.
        in_fixed = _placed_in(span, fixed) or _placed_in(text, fixed)
        in_alt = _placed_in(span, alt) or _placed_in(text, alt)
        if not in_fixed or in_alt:
            continue
        changed.append((_req_field(r, 'id') or '?', g,
                        (text or span)[:60]))
        if isinstance(r, dict):
            r['group'], r['group_mode'] = None, 'all_of'
            r.setdefault('flags', [])
            r['flags'].append(f'UNGROUPED_BY_STRUCTURE:{g}')
        else:
            r.group, r.group_mode = None, 'all_of'
            r.flags = list(r.flags or []) + [f'UNGROUPED_BY_STRUCTURE:{g}']
    return changed
'''


def fix14a(s):
    anchor = 'def normalise_group_intents(reqs: list) -> list:'
    if anchor not in s:
        return None
    return s.replace(anchor, STRUCTURE_GUARD.lstrip('\n') + '\n\n' + anchor, 1)


OLD_CALL_C = """        _fixed_intents = normalise_group_intents(out['requirements'])"""

NEW_CALL_C = """        # The document decides what is a choice, before intents are reconciled
        # -- reconciling the intent of a group that should not exist is work
        # thrown away.
        _ungrouped = ungroup_non_alternatives(out['requirements'],
                                              brief_text)
        if _ungrouped:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'UNGROUPED_BY_STRUCTURE',
                'detail': f'{len(_ungrouped)} requirement(s) were grouped as a '
                          f'choice by the model, but the brief lists them in a '
                          f'requirements/claims section: '
                          f'{[g for _i, g, _t in _ungrouped][:4]}'}]
            if verbose:
                print(f'  {len(_ungrouped)} requirement(s) UNGROUPED -- the '
                      f'brief presents them as asks, not options:')
                for _i, _g, _t in _ungrouped[:6]:
                    print(f'     was {_g}: "{_t}"')
                print('    A one_of group is ONE scoring unit, so grouping '
                      'eight asks would have')
                print('    scored seven of them as satisfied by the first.')
        _fixed_intents = normalise_group_intents(out['requirements'])"""


def fix14b(s):
    if OLD_CALL_C not in s:
        return None
    return s.replace(OLD_CALL_C, NEW_CALL_C, 1)


# ---------------------------------------------------------------------------
# Fix 15 -- the cue list had no word for "a list of CTAs"
#
# Measured across three compiles of ONE brief:
#
#     Call to Actions          5 lines   matched NO cue -> fell through
#     Back to School Campaign  8 lines   matched NO cue -> fell through
#
# Aurelia's equivalent section was titled "Call to action (CTA) Ideas" and
# matched `\\bideas?\\b`, so it was correctly read as a menu. Title the same
# section "Call to Actions" and nothing matches, the kind is decided by
# fallback, and the model is left to invent a grouping -- which it did
# differently on every run (4 groups/18, then 2/12, then 3/18).
#
# So add the words. A section headed "Call to Actions" listing four CTA
# phrasings is a menu, exactly as "CTA Ideas" is. Same for a campaign section
# whose items are "Concept 1", "Concept 2" -- `\\bconcepts?\\b` already covers
# the heading form, and the ITEM form is what this misses.
#
# This is the honest fix. The structure guard (fix 14) was patching around a
# misclassification instead of correcting it, and swung the score from 5 units
# to 8 to 3 across three runs of the same document without ever being right.
# ---------------------------------------------------------------------------
OLD_ALT_CUES = (r"('alternatives', (r'\boptions?\b', r'\bsamples?\b', "
                r"r'\bexamples?\b', r'\bconcepts?\b',")

NEW_ALT_CUES = (
    "('alternatives', (r'\\boptions?\\b', r'\\bsamples?\\b', "
    "r'\\bexamples?\\b', r'\\bconcepts?\\b',\n"
    "                      # A section headed \"Call to Actions\" listing four\n"
    "                      # phrasings is a MENU. Without these it matched no\n"
    "                      # cue at all, fell through to the fallback kind, and\n"
    "                      # left the grouping to the model -- which chose\n"
    "                      # differently on every compile of the same brief.\n"
    "                      r'\\bcall[- ]?to[- ]?actions?\\b', r'\\bCTAs?\\b',\n"
    "                      r'\\bcampaigns?\\b', r'\\bthemes?\\b',")


def fix15(s):
    if OLD_ALT_CUES not in s:
        return None
    return s.replace(OLD_ALT_CUES, NEW_ALT_CUES, 1)


# ---------------------------------------------------------------------------
# Fix 16 -- the product claims become requirements DETERMINISTICALLY
#
# THE PROBLEM, measured over five compiles of the Biostime brief:
#
#   Key Talking Points/Features   8 lines   ->  0 scoring units, every time
#
# Those eight lines are the only part of the brief that says anything about
# the PRODUCT: melatonin-free, magnesium and chamomile, 1.5 billion CFUs, under
# 1g sugar, free from the Top 9 allergens. One of them literally reads
# "(Include as talking point)". The audit never checked any of them.
#
# The score was therefore: did she pick a concept, a hook and a CTA. On the
# last run that gave FIVE of seven videos APPROVED, two of them scoring 86 and
# 93 from a LITERAL score of 0.0 -- every point coming from alignment, with
# nothing about the product verified at all.
#
# WHY THEY VANISHED -- confirmed, not guessed:
#   * is_descriptive_example() keeps all 8, so no filter drops them
#   * the model emits them in roughly ONE of three compile runs
#   * BRIEF_KEEP_THRESHOLD = 0.5, so 0.33 < 0.5 and consensus drops them
#
# So stop asking the model. extract_approved_claims() already returns exactly
# 8, stably, on EVERY run -- that number never moved across five compiles while
# everything else did. It is parsed from the document, not generated.
#
# Each approved claim becomes one requirement, ungrouped, so each is its own
# scoring unit and coverage is a real ratio. Substance credit still applies:
# "these are melatonin-free" satisfies the melatonin-free claim without
# quoting the brief. And provenance is exact by construction -- no fuzzy
# _claim_backed() match -- so `talking points N/8` finally means something.
#
# A claim the model ALREADY turned into a requirement is not duplicated.
# ---------------------------------------------------------------------------
CLAIMS_TO_REQS = '''

# ---------------------------------------------------------------------------
# The brief's product claims are parsed, not generated -- so they are turned
# into requirements here rather than being asked for and hoped for.
# ---------------------------------------------------------------------------
def _claim_headline(text: str) -> str:
    """The label half of "Label: explanation", else the first clause.

    Brief features are written "Gentle & Non-Habit-Forming: Melatonin-free
    formula ensures safe nightly use". The half before the colon is the ask;
    the rest is the brand explaining it to the creator.
    """
    t = (text or '').strip()
    head = t.split(':', 1)[0].strip() if ':' in t[:80] else t
    head = re.sub(r'\\s*\\(include as [^)]*\\)\\s*', ' ', head, flags=re.I)
    head = re.sub(r'[*\\u2022]+', ' ', head)
    return ' '.join(head.split())[:120] or t[:120]


def requirements_from_claims(reqs: list, claims: list) -> list:
    """One requirement per approved claim. Returns the ones it added.

    Deterministic: the claims come from parse_brief_sections, so the same
    document always yields the same requirements. No model call, no consensus
    threshold, nothing to be unstable.
    """
    if not claims:
        return []
    have = []
    for r in reqs:
        have.append(_norm_line(str(_req_field(r, 'brief_span') or ''))
                    + ' ' + _norm_line(str(_req_field(r, 'requirement') or '')))
    added = []
    for c in claims:
        ctext = str((c or {}).get('text') or '').strip()
        if len(ctext) < 8:
            continue
        head = _claim_headline(ctext)
        key = _norm_line(head)
        # Already covered by something the model produced? Leave it alone.
        if key and any(key in h for h in have):
            continue
        text = f'Mention the product feature: {head}'
        rid = requirement_id(text, 'speech_or_text')
        if any(_req_field(r, 'id') == rid for r in reqs):
            continue
        reqs.append({
            'id': rid, 'ordinal': len(reqs) + 1, 'label': make_label(text),
            'requirement': text, 'type': 'speech_or_text',
            'priority': 'medium', 'weight': PRIORITY_WEIGHT['medium'],
            'polarity': 'required', 'evidence_mode': 'speech_or_text',
            'machine_checkable': True,
            # Ungrouped ON PURPOSE: each claim is its own scoring unit, so
            # "3 of 8 covered" is a real number rather than "she mentioned
            # at least one thing".
            'group': None, 'group_mode': 'all_of', 'group_label': '',
            'group_intent': '', 'group_intent_original': '',
            'deadline_seconds': None, 'window_start_expr': None,
            'window_end_expr': None, 'brief_span': ctext[:300],
            'confidence': 1.0, 'source': 'approved_claims',
            # NO MATCH HINTS, DELIBERATELY.
            #
            # l1_phrase() fuzzy-matches any hint and _term_hit returns 100 for
            # a single plain word. The notebook already records where that
            # leads: "twelve hook options each matched the word 'hair' at 100,
            # all twelve returned PASS". Handing it the claim's keywords
            # reproduced it exactly -- measured on a live report, all eight
            # talking points PASSED with alignment `exact` on:
            #     "Gentle & Non-Habit-Forming"  <- OCR "MELATONIN"
            #     "Allergen-Friendly"           <- OCR "Dietary Supplement"
            #     "Clean & Safe Formula"        <- the word "added"
            #     "Delicious Fruity Taste"      <- the PRODUCT NAME "Fruity Bites"
            # The melatonin one is the worst: the claim is melatonin-FREE, and
            # seeing the word "melatonin" is at best no evidence and at worst
            # evidence of the opposite.
            #
            # "Did she claim this product is melatonin-free" is a question
            # about MEANING, not about whether a word appeared. An empty hint
            # list makes l1_phrase return None -- "let L2/L3 try paraphrase" --
            # which sends it to the layer that can actually judge it.
            'claim_classes': [], 'match_hints': [],
            'flags': [f'FROM_APPROVED_CLAIMS:{head[:48]}',
                      'SYNTHESISED_FROM_CLAIMS'],
        })
        added.append(head)
    return added
'''


def fix16a(s):
    anchor = 'def normalise_group_intents(reqs: list) -> list:'
    if anchor not in s:
        return None
    return s.replace(anchor, CLAIMS_TO_REQS.lstrip('\n') + '\n\n' + anchor, 1)


OLD_CALL_D = """        # The document decides what is a choice, before intents are reconciled"""

NEW_CALL_D = """        # The brief's PRODUCT CLAIMS become requirements here, from the
        # parsed document rather than from the model. They are the only part
        # of the brief that says anything about the product, and asking the
        # model for them produced them in one run of three -- below the
        # consensus threshold, so they were dropped every time.
        _from_claims = requirements_from_claims(out['requirements'],
                                                out.get('approved_claims') or [])
        if _from_claims:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'REQUIREMENTS_FROM_CLAIMS',
                'detail': f'{len(_from_claims)} product claim(s) became '
                          f'requirements: {_from_claims[:4]}'}]
            if verbose:
                print(f'  {len(_from_claims)} talking point(s) -> requirements '
                      f'(parsed from the brief, not generated):')
                for _c in _from_claims[:8]:
                    print(f'     {_c[:66]}')
                print('    Each is its own scoring unit, so coverage is a real '
                      'ratio. Her own')
                print('    wording still counts -- substance credit applies as '
                      'usual.')

        # The document decides what is a choice, before intents are reconciled"""


def fix16b(s):
    if OLD_CALL_D not in s:
        return None
    return s.replace(OLD_CALL_D, NEW_CALL_D, 1)


# ---------------------------------------------------------------------------
# Fix 17 -- a music-only video can still be judged
#
# evaluate_standing() and evaluate_creative_angle() both hard-returned on the
# absence of SPEECH specifically:
#
#     if not [r for r in records if r.modality == 'speech']:
#         flags=['STANDING_NO_SPEECH']; return out
#
# So `test_changing_text.mp4` -- a video whose entire point is on-screen text
# -- got standing=None and angle=None, and its 0.0 REJECTED had no whole-video
# read behind it at all.
#
# But the digest those functions feed the model already builds THREE blocks:
#
#     WHAT SHE SAYS (full transcript, in order)   <- speech
#     TEXT ON SCREEN                              <- ocr
#     WHAT IS VISIBLE                             <- visual
#
# and its own docstring says "The whole video as the model sees it: every
# modality, in time order". A silent video with captions and a product on
# screen is perfectly judgeable from the other two blocks. The guard was the
# only thing stopping it.
#
# So: abstain when there is NO usable evidence at all, not when there is no
# speech. When speech is missing but text or visuals are present, judge -- and
# flag it, because a reader should know the whole-video read was made without
# hearing anything. The digest header already says "0 spoken segment(s)", so
# the model is told too.
#
# This matters beyond one test clip: music-only and text-driven UGC is a real
# format, and a system that silently refuses to judge it reports REJECTED for
# every such video with nothing to back the number.
# ---------------------------------------------------------------------------
OLD_STANDING_GATE = """    if not [r for r in records if r.modality == 'speech']:
        out.update(reasoning='No speech evidence, so where the video stands '
                             'cannot be judged. This is UNJUDGED, not off_brief.',
                   flags=['STANDING_NO_SPEECH'], layer='L1')
        return out"""

NEW_STANDING_GATE = """    # ANY usable evidence, not speech specifically. The digest below builds
    # WHAT SHE SAYS / TEXT ON SCREEN / WHAT IS VISIBLE, so a silent video with
    # captions and a visible product has two of three blocks to judge from.
    _usable = [r for r in records if r.modality in ('speech', 'ocr', 'visual')]
    if not _usable:
        out.update(reasoning='No speech, text or visual evidence, so where the '
                             'video stands cannot be judged. This is UNJUDGED, '
                             'not off_brief.',
                   flags=['STANDING_NO_EVIDENCE'], layer='L1')
        return out
    _silent = not [r for r in _usable if r.modality == 'speech']
    if _silent:
        # Judged, but the reader must know it was judged without audio.
        out['flags'].append('STANDING_WITHOUT_SPEECH')"""

OLD_ANGLE_GATE = """    speech = [r for r in records if r.modality == 'speech']
    if not speech:
        out.update(angle=None, reason=(
            'No speech evidence, so the creative angle cannot be characterised. '
            'This is UNCERTAIN, not "no angle".'),
            flags=['ANGLE_NO_SPEECH'], layer='L1')
        return out"""

NEW_ANGLE_GATE = """    # Same rule as standing: an angle is carried by what the video SHOWS as
    # much as by what it says. A silent routine-integration video is still a
    # routine-integration video.
    speech = [r for r in records if r.modality == 'speech']
    _usable = [r for r in records if r.modality in ('speech', 'ocr', 'visual')]
    if not _usable:
        out.update(angle=None, reason=(
            'No speech, text or visual evidence, so the creative angle cannot '
            'be characterised. This is UNCERTAIN, not "no angle".'),
            flags=['ANGLE_NO_EVIDENCE'], layer='L1')
        return out
    if not speech:
        out['flags'].append('ANGLE_WITHOUT_SPEECH')"""


def fix17a(s):
    if OLD_STANDING_GATE not in s:
        return None
    return s.replace(OLD_STANDING_GATE, NEW_STANDING_GATE, 1)


def fix17b(s):
    if OLD_ANGLE_GATE not in s:
        return None
    return s.replace(OLD_ANGLE_GATE, NEW_ANGLE_GATE, 1)


# ---------------------------------------------------------------------------
# Fix 18 -- §71 still asserted the speech-only gate
#
# The test passes an EMPTY record list, so the OUTCOME is unchanged -- angle is
# None and the module abstains. Only the flag moved: `ANGLE_NO_SPEECH` became
# `ANGLE_NO_EVIDENCE`, because "no speech" and "nothing at all" are now
# different findings.
#
# The test is updated rather than deleted, and a second one is added for the
# capability fix 17 introduced: a silent video that HAS text or visuals must be
# judged, not refused.
# ---------------------------------------------------------------------------
OLD_ANGLE_TEST = """    _ns = evaluate_creative_angle([], {'requirements': []}, {}, None, P6, False)
    check('no speech yields UNCERTAIN, not "no angle"',
          _ns['angle'] is None and 'ANGLE_NO_SPEECH' in _ns['flags'])"""

NEW_ANGLE_TEST = """    _ns = evaluate_creative_angle([], {'requirements': []}, {}, None, P6, False)
    check('NO EVIDENCE AT ALL yields UNCERTAIN, not "no angle"',
          _ns['angle'] is None and 'ANGLE_NO_EVIDENCE' in _ns['flags'])

    # fix 17: a silent video is not an unjudgeable one. The digest builds
    # TEXT ON SCREEN and WHAT IS VISIBLE as well as WHAT SHE SAYS, so a
    # music-only video with captions has two of three blocks to judge from.
    # Refusing it reported REJECTED with no whole-video read behind the number.
    #
    # Built with _rec(), the suite's own factory, NOT a hand-rolled stub: it
    # returns a real EvidenceRecord, so every field the digest reaches for --
    # time_tolerance_seconds among them -- is actually there. A stub that
    # carries only the attributes I remembered fails on the first one I did not.
    _SIL_OCR = _rec('ev_sil_o', 'ocr', 'on_screen_text', 1.0, 2.0,
                    'MELATONIN FREE', indep='confirmed_independent')
    _SIL_VIS = _rec('ev_sil_v', 'visual', 'product_held', 1.0, 2.0,
                    'a jar of gummies held to camera')

    # A FAKE backend, not None. With records present and L3 enabled the
    # function reaches `backend = backend or make_brief_backend(...)`, which
    # would build a real client and make a LIVE API call -- in a suite whose
    # header promises no GPU, no network, no API key. The old test never hit
    # that path because empty records returned early.
    _silent_json = json.dumps({'angle': 'demonstration',
                               'summary': 'Shows the product on screen.',
                               'reason': 'Product shown, nothing spoken.',
                               'evidence_ids': ['ev_sil_o']})
    _silent = evaluate_creative_angle([_SIL_OCR, _SIL_VIS],
                                      {'requirements': []}, {},
                                      _FakeL3Backend(_silent_json), P6, False)
    check('a SILENT video with text/visuals is not refused outright',
          'ANGLE_NO_EVIDENCE' not in _silent['flags'],
          str(_silent['flags'])[:70])
    check('...and it is flagged as judged without speech',
          'ANGLE_WITHOUT_SPEECH' in _silent['flags'],
          str(_silent['flags'])[:70])"""


def fix18(s):
    if OLD_ANGLE_TEST not in s:
        return None
    return s.replace(OLD_ANGLE_TEST, NEW_ANGLE_TEST, 1)


# A later `out.update(flags=[...])` REPLACES the list, silently dropping
# anything recorded earlier -- including WITHOUT_SPEECH, which is exactly the
# context a reader needs to interpret the abstention. Preserve what is already
# there. (In production L3 is enabled so these branches rarely fire, which is
# precisely why the loss would have gone unnoticed.)
FLAG_PRESERVE = (
    ("flags=['ANGLE_NOT_JUDGED'], layer='L1')",
     "flags=out['flags'] + ['ANGLE_NOT_JUDGED'], layer='L1')"),
    ("flags=['ANGLE_MODEL_FAILED'])",
     "flags=out['flags'] + ['ANGLE_MODEL_FAILED'])"),
    ("flags=['STANDING_NOT_JUDGED'], layer='L1')",
     "flags=out['flags'] + ['STANDING_NOT_JUDGED'], layer='L1')"),
)


def fix18b(s):
    out = s
    for old, new in FLAG_PRESERVE:
        if old in out:
            out = out.replace(old, new)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 19 -- L3 had no word for "she simply did not do it"
#
# Measured: 5-7 UNCERTAIN per video on the talking points, with reasons that
# are not uncertain at all --
#
#     "There is no mention of Biostime being verified as the World's #1 brand."
#     "The evidence does not mention gentle and non-habit-forming properties."
#     "Digestive health is not mentioned in the provided evidence."
#
# Those are confident absences. They landed as UNCERTAIN because the prompt
# defines the two statuses like this:
#
#     FAIL       - the evidence CONTRADICTS the requirement
#     UNCERTAIN  - the evidence is insufficient to decide
#     Prefer UNCERTAIN over guessing.
#
# A creator who never mentions allergens does not CONTRADICT "mention
# allergen-friendly" -- so under those definitions UNCERTAIN was the only
# honest answer available. The model was obeying its instructions exactly.
#
# I first blamed can_fail_on downgrading a FAIL. That was wrong: this run
# printed no blocked channels at all, because none are degraded. The gate
# never fired; the prompt simply had no category for absence.
#
# THE LAYERING THIS RESTORES, which the system already believes in:
#   L3 decides "it is not in the evidence I was shown"
#   _fail_allowed() decides "were we entitled to assert that"
# Phase 5's can_fail_on is the guard against asserting absence on a modality
# that did not look properly -- and it still runs after this. So L3 can safely
# be told to call an absence what it is.
# ---------------------------------------------------------------------------
OLD_L3_STATUSES = """3. Use exactly these statuses:
   PASS       - the cited evidence satisfies the requirement
   PARTIAL    - satisfied weakly, late, or in only one of two required modalities
   FAIL       - the evidence CONTRADICTS the requirement
   UNCERTAIN  - the evidence is insufficient to decide
   Prefer UNCERTAIN over guessing. An unsupported verdict is worse than none."""

NEW_L3_STATUSES = """3. Use exactly these statuses:
   PASS       - the cited evidence satisfies the requirement
   PARTIAL    - satisfied weakly, late, or in only one of two required modalities
   FAIL       - the requirement is NOT met by the evidence you were shown.
                TWO ways that happens, and both are FAIL:
                  (a) the evidence CONTRADICTS the requirement, or
                  (b) the requirement asks for something and, having read all
                      the evidence offered, it is simply NOT THERE.
                "She never mentions it" is a FAIL, not an UNCERTAIN. You looked
                and it was absent -- that is a finding about the video.
   UNCERTAIN  - you genuinely CANNOT TELL from what you were given: the
                evidence is garbled, truncated, ambiguous, or too sparse to
                read. Not "the thing is missing" -- that is FAIL -- but "I
                cannot see well enough to say either way".
   The difference is about YOUR ABILITY TO SEE, not about how the video did.
   A clean transcript with no mention of allergens supports a FAIL. A garbled
   one does not.
   Prefer UNCERTAIN over guessing. An unsupported verdict is worse than none."""


def fix19(s):
    if OLD_L3_STATUSES not in s:
        return None
    return s.replace(OLD_L3_STATUSES, NEW_L3_STATUSES, 1)


# ---------------------------------------------------------------------------
# Fix 20 -- a HOSTED vision model was being throttled by local VRAM
#
# This notebook sends frames to Gemini. make_vision_backend says so itself:
#
#     "'auto' prefers Gemini ... because the hosted path has NO VRAM CEILING
#      and therefore NEVER DEGRADES THE FRAME BUDGET."
#
# But run_vision_stage applies the affordability pre-filter unconditionally --
# it never asks which provider is running:
#
#     _afford = vision_token_budget(free_vram_gb(), cfg.vision)
#     _viable = [r for r in ladder if estimate_tokens(r) <= _afford]
#     ladder  = _viable            # rungs skipped UNATTEMPTED
#
# and vision_token_budget floors at 2000 tokens:
#
#     usable = max(0.0, free_gb - vram_safety_gb)
#     return max(2000, int(usable * tokens_per_gb))
#
# On a Colab runtime with no GPU, or one where Whisper/OCR/the L2 embedder hold
# the VRAM, free_gb collapses and the budget lands near that 2000 floor. Every
# worthwhile rung is then "unaffordable" and the run drops to the smallest one
# -- so a 48-frame video is analysed at 12 frames, by a model that never
# touches the GPU being measured.
#
# The frames are the evidence. A quarter of the frames is a quarter of what the
# audit can see, and it degraded silently on every video in the batch.
#
# The OOM ladder itself STAYS. A hosted backend simply never raises CUDA OOM,
# so it runs the top rung and stops. Nothing about the local path changes: when
# provider == 'local' the filter applies exactly as before.
# ---------------------------------------------------------------------------
OLD_AFFORD = """    try:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _afford = vision_token_budget(free_vram_gb(), cfg.vision)"""

NEW_AFFORD = """    # ONLY a local model is limited by local VRAM. Gemini holds none of it, and
    # make_vision_backend's own contract is that the hosted path never degrades
    # the frame budget -- but this filter never asked which provider was
    # running, so a hosted run was cut to the smallest rung by a GPU it does
    # not use. `_p3_local` is resolved once, up by the ladder (fix 21).
    if not _p3_local and verbose:
        print(f'  hosted vision provider '
              f'({getattr(cfg.vision, "provider", "?")}): keeping the full '
              f'{ladder[0][0]}-frame budget -- local VRAM does not limit it')
    try:
        if not _p3_local:
            raise _SkipAffordability()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _afford = vision_token_budget(free_vram_gb(), cfg.vision)"""


def fix20a(s):
    if OLD_AFFORD not in s:
        return None
    return s.replace(OLD_AFFORD, NEW_AFFORD, 1)


# The sentinel is caught by the existing bare `except`, which already says "a
# bad reading must never prevent the ladder from running" -- the same handling
# this wants, so no new except clause is needed.
SKIP_SENTINEL = '''

class _SkipAffordability(Exception):
    """Raised to bypass the VRAM affordability filter on a hosted provider.

    The filter's existing `except` already falls through to the full ladder on
    any bad reading, so reusing that path keeps one exit instead of two.
    """
'''


def fix20b(s):
    anchor = 'def run_vision_stage('
    if anchor not in s or '_SkipAffordability' in s.split(anchor)[0]:
        return None
    return s.replace(anchor, SKIP_SENTINEL.lstrip('\n') + '\n\n' + anchor, 1)


# ---------------------------------------------------------------------------
# Fix 21 -- a DEGRADED cached visual is not a valid hit on a hosted run
#
# Fix 20 stops the throttling. It does NOT undo it. Every video already
# processed has its artifact filed under a REDUCED rung, and the cache scan
# walks every rung of the ladder and returns the first artifact it finds -- so
# the next run serves the 12-frame result back and fix 20 changes nothing that
# anyone can see. A fix that only applies to videos you have never run is not a
# fix; it is a note about the future.
#
# The rule is narrow and it comes from the backend's own physics: a hosted
# backend has no VRAM ceiling and therefore never raises CUDA OOM, so a
# DEGRADED hosted artifact cannot have come from an OOM. It came from the
# affordability filter, which is the bug. Re-run it.
#
# On a LOCAL provider NOTHING changes. There the degradation was real, the
# artifact is the best that GPU can produce, and refusing the hit would mean
# re-OOMing on every single run -- which is the exact waste the scan was
# written to prevent.
#
# In this notebook the predicate is exact rather than a guess: its own
# make_vision_backend refuses to fall back to Qwen ("NO SILENT FALL BACK"), so
# provider != 'local' really does mean hosted. The second clause mirrors, line
# for line, how `backend` is chosen further down, so the two cannot disagree
# about which path is running.
# ---------------------------------------------------------------------------
P3_LOCAL_DECL = """    # Which path will actually describe the frames. Resolved ONCE, here,
    # because BOTH the cache scan below and the affordability filter further
    # down turn on it. The second clause mirrors how `backend` is chosen below,
    # so the two can never disagree about which path is running.
    _p3_local = (getattr(cfg.vision, 'provider', 'local') == 'local'
                 or not callable(globals().get('make_vision_backend')))

    # ---- the frame-budget ladder ---"""

OLD_SCAN = """    # Check EVERY rung's cache before running anything: an earlier run may have
    # succeeded at a reduced budget, and re-OOMing at 24 just to rediscover that
    # wastes a minute per video on every re-run.
    if not force:
        for n_frames, acfg in ladder:
            p = vdir / f'visual__{_key_for(acfg)}.json'
            if p.exists():
                if verbose:
                    note = ('' if (acfg.max_frames, acfg.max_pixels)
                            == (vcfg.max_frames, vcfg.max_pixels)
                            else f' [degraded: {acfg.max_frames} frames @ {acfg.max_pixels}px]')
                    print(f'  VISUAL CACHE HIT ({_key_for(acfg)}){note}')
                return VisualEvidence.model_validate(read_json(p))"""

NEW_SCAN = """    # Check EVERY rung's cache before running anything: an earlier run may have
    # succeeded at a reduced budget, and re-OOMing at 24 just to rediscover that
    # wastes a minute per video on every re-run.
    #
    # ONE exception, and it is the whole point of fix 21. A hosted backend has
    # no VRAM ceiling and never OOMs, so a DEGRADED hosted artifact cannot have
    # come from an OOM -- it came from the affordability filter below, which
    # used to throttle hosted runs by a GPU they never touch. Serving one from
    # cache would describe a quarter of the frames the audit is supposed to see
    # and would make fix 20 invisible on every video already processed.
    #
    # On a LOCAL provider this branch never fires: there the degradation was
    # real, and refusing the hit would mean re-OOMing on every run.
    if not force:
        for n_frames, acfg in ladder:
            p = vdir / f'visual__{_key_for(acfg)}.json'
            if not p.exists():
                continue
            _degraded = ((acfg.max_frames, acfg.max_pixels)
                         != (vcfg.max_frames, vcfg.max_pixels))
            if _degraded and not _p3_local:
                if verbose:
                    print(f'  ignoring a DEGRADED cached visual '
                          f'({acfg.max_frames} frames @ {acfg.max_pixels}px): '
                          f'hosted vision is not limited by local VRAM, so the '
                          f'full {vcfg.max_frames}-frame budget is re-run')
                continue
            if verbose:
                note = ('' if not _degraded
                        else f' [degraded: {acfg.max_frames} frames '
                             f'@ {acfg.max_pixels}px]')
                print(f'  VISUAL CACHE HIT ({_key_for(acfg)}){note}')
            return VisualEvidence.model_validate(read_json(p))"""

# The line fix 20 used to insert, now owned by P3_LOCAL_DECL. Removed only if
# present, so this runs identically on a pristine notebook and on one that
# already carries fix 20.
STALE_P3_LOCAL = (
    "    # not use.\n"
    "    _p3_local = getattr(cfg.vision, 'provider', 'local') == 'local'\n")
FRESH_P3_LOCAL = (
    "    # not use. `_p3_local` is resolved once, up by the ladder (fix 21).\n")


def fix21(s):
    if 'def run_vision_stage(' not in s or OLD_SCAN not in s:
        return None
    out = s.replace(STALE_P3_LOCAL, FRESH_P3_LOCAL, 1)
    out = out.replace('    # ---- the frame-budget ladder ---', P3_LOCAL_DECL, 1)
    out = out.replace(OLD_SCAN, NEW_SCAN, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 22 -- the readers never learned the key they were reading
#
# run_vision_stage FILES the artifact under
#
#     {'vision': asdict(c), 'prompt': PROMPT_VERSION, 'vlm': _planned_vlm}
#
# The 'vlm' component was added in VLM_STAGE_VERSION 1.11.0 so a Gemini
# artifact could never collide with a Qwen one. _visual_keys REBUILDS that key
# to decide which files Phase 5/7 may accept -- and it was never told about
# 'vlm'. So every key it computed was missing a component, NONE of the rungs
# could ever match a real file, and the resolver fell through to its
# newest-file fallback on every video of every run:
#
#     WARNING visual: none of the 6 key(s) the current config accepts is on
#     disk; using the newest of 1 (visual__69421b92daa1fe83.json)
#
# That warning was never about a stale artifact. The artifact was current, the
# reader was wrong. With one file per video the fallback picked the right file,
# so no report was ever wrong because of it -- what was lost is the GUARANTEE,
# which is the whole point of content-addressing. `visual_stale` was true on
# every row, so the one signal that would announce a genuinely mismatched
# artifact was already saturated and could not warn about anything.
#
# This changes no artifact -- only which files a reader recognises. NO stage
# version bump: bumping would invalidate the very artifacts this teaches it to
# find.
# ---------------------------------------------------------------------------
OLD_VKEY = """    out = []
    for n, p in g['vision_ladder'](vcfg):"""

NEW_VKEY = """    # The key run_vision_stage actually writes under carries the RESOLVED
    # model as well (VLM 1.11.0), so that a hosted artifact and a local one can
    # never collide. Rebuilding the key without it produced six keys that could
    # not match anything on disk, on every video, forever -- and the fallback
    # quietly covered for it. plan_vlm_load is deterministic here: a hosted
    # provider returns its model outright, and the local path keys on TOTAL
    # VRAM, which is a stable property of the card rather than a reading that
    # drifts between runs.
    _planned_vlm = list((g['plan_vlm_load'](vcfg) or [(None, None)])[0])
    out = []
    for n, p in g['vision_ladder'](vcfg):"""

OLD_VKEY_CALL = """        out.append(stage_key('visual', g['VLM_STAGE_VERSION'], [vh, ph],
                             {'vision': asdict(c), 'prompt': g['PROMPT_VERSION']}))"""

NEW_VKEY_CALL = """        out.append(stage_key('visual', g['VLM_STAGE_VERSION'], [vh, ph],
                             {'vision': asdict(c), 'prompt': g['PROMPT_VERSION'],
                              'vlm': _planned_vlm}))"""

OLD_SPEC = """    ('visual', _visual_keys, ('VLM_STAGE_VERSION', 'PROMPT_VERSION', 'P3',
                              'resolve_vision_config', 'vision_ladder',
                              'scene_count_of')),"""

NEW_SPEC = """    ('visual', _visual_keys, ('VLM_STAGE_VERSION', 'PROMPT_VERSION', 'P3',
                              'resolve_vision_config', 'vision_ladder',
                              'scene_count_of', 'plan_vlm_load')),"""


def fix22(s):
    if 'def _visual_keys' not in s or OLD_VKEY_CALL not in s:
        return None
    out = s.replace(OLD_VKEY, NEW_VKEY, 1)
    out = out.replace(OLD_VKEY_CALL, NEW_VKEY_CALL, 1)
    out = out.replace(OLD_SPEC, NEW_SPEC, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 23 -- unranked retrieval is a TIME FILTER wearing retrieval's clothes
#
# Found 2026-09-22 by the user, who watched the video and read the report:
# "it says she didn't say delicious fruity taste while I watched the video she
# clearly says it has a fruity taste."
#
# She does. The transcript has it. Phase 5 has it:
#
#     ev_e188a6d2b7  speech  0:16
#     "passion flower my kids love the fruity taste they just call them
#      their night night gummies"
#
# And the verdict says:
#
#     L3 FAIL  Delicious Fruity Taste  -- "The evidence does not mention the
#     taste of the gummies."   cites: ev_ce5a98aa84
#
# ev_ce5a98aa84 is the speech record at 0:00. Every one of the four claim
# FAILs cites that one record, and every one is plotted at x=0.0s. L3 answered
# honestly about the evidence it was shown; it was never shown 0:16.
#
# WHY. candidates_for() ranks on ONE signal:
#
#     out.sort(key=lambda c: (-c['hint_score'], c['record'].start_seconds))
#     return out[:rc.top_k]
#
# Fix 16 removed match_hints from claim requirements -- correctly, because a
# single plain word scored 100 and passed everything ("Delicious Fruity Taste"
# <- the PRODUCT NAME "Fruity Bites"). But that left those requirements with
# NO ranking signal at all, so hint_score is 0 for every record, the sort
# collapses to the tiebreak, and `top_k` of a 121-record video becomes "the
# first ten records" -- the opening seconds. The judge is asked "did she ever
# say this?" while being shown only the start of the video.
#
# That is the other half of fix 16, and it interacts with fix 19: absence is
# now a FAIL, and fix 19 is only sound if retrieval actually offered the
# evidence. Unranked retrieval plus absence-is-FAIL produces CONFIDENT FALSE
# FAILS -- the error class plan.md ranks worst after a false PASS.
#
# THE FIX: when nothing carries a hint, rank by MEANING, using the same
# embedder L2 already uses. "Did she describe the taste" is a question about
# meaning; it was being answered by a clock.
#
# If the embedder is unavailable, spread the sample across the video instead
# of taking the opening. A judge shown ten records from throughout can say
# "not there" far more honestly than one shown ten from the first 3 seconds --
# degrade, never block, and never silently.
# ---------------------------------------------------------------------------
OLD_RANK = """    # Best hint first; then the earliest, because "first seen" questions are
    # common and an early record is usually the one being asked about.
    out.sort(key=lambda c: (-c['hint_score'], c['record'].start_seconds))
    return out[:rc.top_k]"""

NEW_RANK = '''    # Best hint first; then the earliest, because "first seen" questions are
    # common and an early record is usually the one being asked about.
    out.sort(key=lambda c: (-c['hint_score'], c['record'].start_seconds))

    # ---- no hint signal at all -> rank by MEANING, not by the clock --------
    # With every hint_score at 0 the sort above ranks nothing, and the
    # tiebreak becomes the entire selection rule: top_k of a 121-record video
    # is "the first ten", and a requirement asking "did she ever say this"
    # gets answered from the opening seconds. That is how a FAIL was written
    # for "Delicious Fruity Taste" on a video whose transcript says "my kids
    # love the fruity taste" at 0:16 -- see fix 23's note above.
    #
    # Claim requirements carry no match_hints BY DESIGN (fix 16), so this is
    # their normal path, not an edge case.
    if out and len(out) > rc.top_k and not any(c['hint_score'] for c in out):
        _sim = globals().get('l2_similarities')
        _ranked = []
        if callable(_sim):
            try:
                _ranked = _sim(rd, out, cfg) or []
            except Exception:
                _ranked = []        # a ranker that fails must not lose evidence
        if _ranked:
            for _c, _s in _ranked:
                _c['why'] += f', meaning:{_s:.2f}'
                _c['semantic_rank_score'] = float(_s)
            out = [_c for _c, _s in _ranked]
        else:
            # L2 unavailable. Sample ACROSS the video rather than taking its
            # opening -- being wrong about where to look is recoverable, only
            # ever looking at the first seconds is not.
            out = spread_sample(out, rc.top_k)
            for _c in out:
                _c['why'] += ', spread (no hint, no embedder)'
    return out[:rc.top_k]'''

SPREAD_FN = '''def spread_sample(cands: list, k: int) -> list:
    """An even sample across the list, order preserved.

    Used only when there is no way to RANK candidates. `cands` is already in
    time order at that point (every hint score is 0, so the sort collapsed to
    its tiebreak), so an even sample of the list is an even sample of the
    video -- which is the honest thing to show a judge that is about to be
    asked whether something appears anywhere in it.
    """
    if k <= 0 or len(cands) <= k:
        return list(cands)
    step = len(cands) / float(k)
    picked, seen = [], set()
    for i in range(k):
        j = min(len(cands) - 1, int(i * step))
        if j not in seen:
            seen.add(j)
            picked.append(cands[j])
    return picked


'''


def fix23a(s):
    if 'def candidates_for(' not in s or OLD_RANK not in s:
        return None
    out = s.replace(OLD_RANK, NEW_RANK, 1)
    out = out.replace('def candidates_for(', SPREAD_FN + 'def candidates_for(', 1)
    return out if out != s else None


# The same record text is embedded once per requirement that needs ranking:
# eight claim requirements over ~120 records is ~1000 embeddings per video,
# all of them repeats. A dict keyed on the prepared string makes fix 23 nearly
# free. Values are identical either way -- this changes speed, not results.
OLD_EMBED = """def _embed(texts: list, is_query: bool, cfg: L2Config = None):
    cfg = cfg or P6.l2
    m = l2_model(cfg, verbose=False)
    if m is None or not texts:
        return None
    pre = cfg.query_prefix if is_query else cfg.passage_prefix
    prepped = [(pre + (t or ''))[:cfg.max_chars] for t in texts]
    return m.encode(prepped, batch_size=cfg.batch_size,
                    normalize_embeddings=True, show_progress_bar=False)"""

NEW_EMBED = """_EMBED_CACHE = {}


def _embed(texts: list, is_query: bool, cfg: L2Config = None):
    cfg = cfg or P6.l2
    m = l2_model(cfg, verbose=False)
    if m is None or not texts:
        return None
    import numpy as _np
    pre = cfg.query_prefix if is_query else cfg.passage_prefix
    prepped = [(pre + (t or ''))[:cfg.max_chars] for t in texts]
    # Cached on the PREPARED string, so the prefix and the truncation are part
    # of the identity and a query can never collide with a passage. Fix 23
    # re-ranks every record for every hint-less requirement, which means the
    # same ~120 record texts are embedded eight times per video; without this
    # that is the slowest thing in Phase 6, and with it, it happens once.
    _missing = [t for t in dict.fromkeys(prepped) if t not in _EMBED_CACHE]
    if _missing:
        _vecs = m.encode(_missing, batch_size=cfg.batch_size,
                         normalize_embeddings=True, show_progress_bar=False)
        for _t, _v in zip(_missing, _vecs):
            _EMBED_CACHE[_t] = _v
    return _np.stack([_EMBED_CACHE[t] for t in prepped])"""


def fix23b(s):
    if OLD_EMBED not in s:
        return None
    return s.replace(OLD_EMBED, NEW_EMBED, 1)


# ---------------------------------------------------------------------------
# Fix 24 -- the §60 stub must cover what _visual_keys now reads
#
# Fix 22 taught _visual_keys to include the resolved model in the key, which
# means it now calls plan_vlm_load(). The §60 test replaces P3 with a minimal
# fake and stubs resolve_vision_config / vision_ladder / scene_count_of -- but
# NOT plan_vlm_load, so the REAL one ran against a fake config and died:
#
#     AttributeError: '_FakeVision' object has no attribute 'model_id'
#
# Caught only in Colab, on a live run. Every local check passed, because the
# local harness EXTRACTS functions and runs them; it never executes the
# notebook's own test cells. That gap is real and is recorded in complete.md.
#
# Stubbed rather than fleshing out _FakeVision, for consistency: every other
# collaborator in this test is stubbed, the stub keeps the test hermetic, and
# the subject here is key COMPUTATION, not model planning. The value is shaped
# exactly like plan_vlm_load's hosted return -- a (model, quantization) pair --
# so the key still has the same structure it has in production.
# ---------------------------------------------------------------------------
OLD_STUB = """    _NAMES = ('P2', 'P3', 'ASR_STAGE_VERSION', 'OCR_STAGE_VERSION',
              'VLM_STAGE_VERSION', 'PROMPT_VERSION', 'resolve_vision_config',
              'vision_ladder', 'scene_count_of')"""

NEW_STUB = """    _NAMES = ('P2', 'P3', 'ASR_STAGE_VERSION', 'OCR_STAGE_VERSION',
              'VLM_STAGE_VERSION', 'PROMPT_VERSION', 'resolve_vision_config',
              'vision_ladder', 'scene_count_of',
              # _visual_keys calls this since fix 22: the resolved model is
              # part of the visual cache key, so a reader that omits it can
              # never match a file the writer produced.
              'plan_vlm_load')"""

OLD_UPD = """               'vision_ladder': lambda v: list(_FAKE_RUNGS),
               'scene_count_of': lambda m: 2})"""

NEW_UPD = """               'vision_ladder': lambda v: list(_FAKE_RUNGS),
               'scene_count_of': lambda m: 2,
               # Shaped like the hosted return: [(model, quantization)].
               'plan_vlm_load': lambda c, *a, **k: [('gemini:test-model',
                                                     'hosted')]})"""


def fix24(s):
    if OLD_STUB not in s or OLD_UPD not in s:
        return None
    return s.replace(OLD_STUB, NEW_STUB, 1).replace(OLD_UPD, NEW_UPD, 1)


# ---------------------------------------------------------------------------
# Fix 25 -- re-measured 2026-09-22: flash-lite is not down, it is SLOW
#
# Fix 8 put flash-lite first because Phase 3 measured it as "the only model
# that serves". That measurement is now nine months stale, and a fresh one on
# the user's own key says something different. One-word prompt, same key,
# same minute:
#
#     gemini-3.5-flash           3.3s   OK
#     gemini-flash-lite-latest  25.1s   OK        <- the incumbent
#     gemini-3.5-flash-lite     36.4s   OK
#     gemini-3.1-flash-lite       --    503 UNAVAILABLE (high demand)
#     gemini-3.8-flash            --    503 UNAVAILABLE (high demand)
#     gemini-2.5-flash            --    404 no longer available
#     gemini-2.5-flash-lite       --    404 no longer available
#
# flash-lite was never down. It takes 25 SECONDS to say "Ok". A real L3 call
# carries ~11k input and ~2k output, so that latency is multiplied, and it is
# a large part of why a 7-video batch took an hour twice over. gemini-3.5-flash
# answers the same prompt in 3.3s -- roughly 8x -- and is a more capable judge
# than the cheapest tier, which is what L3 adjudication actually wants.
#
# The ladder is now the three models MEASURED working, fastest first. The 503s
# are left out deliberately: unlike a 429, a model that is 503-ing right now
# costs three attempts and 3s of back-off on EVERY call, and OpenAI is already
# the real safety net underneath.
#
# NO STAGE VERSION BUMP -- and this still invalidates the brief. hosted_model
# is inside asdict(bc), which goes into stage_key('brief', ...). So the brief
# recompiles, its cache_key changes, and every verdict key downstream changes
# with it: a full re-audit. That is correct, not incidental -- a different
# judge IS different output, and the design has said so since VLM 1.11.0.
#
# VISION IS NOT TOUCHED. VisionConfig.gemini_models stays flash-lite, because
# changing it invalidates every visual artifact and re-runs the whole vision
# pass. That is a separate, deliberate decision with a real bill attached.
# ---------------------------------------------------------------------------
OLD_LADDER_8 = """    hosted_model: str = 'gemini-flash-lite-latest'
    hosted_model_ladder: tuple = ('gemini-flash-lite-latest',
                                  'gemini-flash-latest', 'gemini-pro-latest')"""

NEW_LADDER_25 = """    # RE-MEASURED 2026-09-22 on a live key, one-word prompt, same minute:
    #     gemini-3.5-flash           3.3s  OK
    #     gemini-flash-lite-latest  25.1s  OK   <- the old default
    #     gemini-3.5-flash-lite     36.4s  OK
    #     gemini-3.1-flash-lite / gemini-3.8-flash    503 high demand
    #     gemini-2.5-flash / gemini-2.5-flash-lite    404 retired
    # flash-lite was never down; it is 8x slower to say one word, and an L3
    # call carries ~11k in / ~2k out. Only measured-working models are in the
    # ladder: a 503 model costs three attempts and 3s of back-off per call,
    # and OpenAI is the safety net underneath.
    hosted_model: str = 'gemini-3.5-flash'
    hosted_model_ladder: tuple = ('gemini-3.5-flash', 'gemini-3.5-flash-lite',
                                  'gemini-flash-lite-latest')"""


def fix25(s):
    if OLD_LADDER_8 not in s:
        return None
    return s.replace(OLD_LADDER_8, NEW_LADDER_25, 1)


# ---------------------------------------------------------------------------
# Fix 26 -- NO LIVE KEY IN THE SOURCE
#
# §37a hardcoded a Gemini key and a PAID OpenAI key, with a comment saying
# "Hardcoded deliberately for testing... rotate it when testing is done" and,
# four lines later, "a printed key outlives the session and travels wherever
# the file goes." Both were true. The key travelled:
#
#     Phase 6/phases_1_to_6_gemini_vision.ipynb        (source)
#     Phase 6/phases_1_to_6_gemini_vision.bak.ipynb
#     Phase 6/phases_1_to_6_gemini_vision.prefix.ipynb
#     Phase 6/phases_1_to_6_full_pipeline.ipynb
#     Phase 6/phases_1_to_6_full_pipeline.bak.ipynb
#     Phase 7/phases_1_to_7_gemini_vision.ipynb        (generated)
#     Phase 7/phases_1_to_7_BATCH.ipynb                (generated)
#
# Seven files, uploaded to Colab and downloaded again. The OpenAI one is a
# paid `sk-proj-` key. Both must be ROTATED -- removing them from the files
# does not un-share them.
#
# This fix only stops it recurring. _get_secret() already reads the
# environment first and Colab secrets second, so nothing downstream changes;
# this block just hoists the secret into os.environ, because Phase 3 sits
# above Phase 4 here and reads os.environ directly.
#
# The key VALUES never appear in this patcher: the block is located by line,
# not matched by content, so the secret does not move from one file into
# another one that also gets shared.
# ---------------------------------------------------------------------------
NEW_KEY_BLOCK = """# NO KEY IN THIS FILE, EVER.
#
# Add them as Colab secrets instead -- key icon in the left sidebar -- named
# GEMINI_API_KEY and OPENAI_API_KEY, with "Notebook access" enabled. Outside
# Colab, export them as environment variables.
#
# A key hardcoded here does not stay here. It is copied into the Phase 7
# builds, into every .bak, and into the file you upload and re-download. There
# is no version of "just for testing" that survives contact with a build step.
try:
    from google.colab import userdata          # noqa: F401
    for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):
        if not os.environ.get(_n):
            try:
                _v = userdata.get(_n)
                if _v and _v.strip():
                    os.environ[_n] = _v.strip()
            except Exception:
                pass          # secret absent, or notebook access not granted
except Exception:
    pass                      # not Colab -- real environment variables apply
"""


def fix26(s):
    if "os.environ['GEMINI_API_KEY'] = '" not in s:
        return None
    lines = s.split('\n')
    start = next((i for i, l in enumerate(lines)
                  if l.startswith('# Hardcoded deliberately for testing')), None)
    if start is None:
        start = next(i for i, l in enumerate(lines)
                     if l.startswith("os.environ['GEMINI_API_KEY']"))
    end = next(i for i, l in enumerate(lines)
               if l.startswith("os.environ['OPENAI_API_KEY']"))
    # The OpenAI assignment is a parenthesised concatenation over several
    # lines; walk to the line that closes it rather than assuming a count.
    depth = 0
    for j in range(end, len(lines)):
        depth += lines[j].count('(') - lines[j].count(')')
        if depth <= 0:
            end = j
            break
    return '\n'.join(lines[:start] + NEW_KEY_BLOCK.split('\n') + lines[end + 1:])


# ---------------------------------------------------------------------------
# Fix 27 -- probe the models once, then pick a working one automatically
#
# Fix 25's order is a MEASUREMENT, and a measurement goes stale -- that is
# exactly how fix 8's order came to be wrong. A hardcoded ladder is a guess
# about the state of someone else's servers at a moment that has passed.
#
# So: probe the candidates ONCE per session, in parallel, with a short
# timeout, and order the ladder by what actually answered. Parallel because
# seven serial probes against a 25s model is two minutes before any real work
# starts; in parallel the whole probe costs about one timeout.
#
# WHAT THIS COSTS, said plainly: hosted_model is inside asdict(bc), which is
# inside stage_key('brief', ...). A model chosen from live network conditions
# therefore makes the brief's cache key depend on the network. That is the
# honest encoding -- the key names the judge that actually ran, which is what
# the design has wanted since VLM 1.11.0 -- but it does mean two runs on
# different days can legitimately produce different keys.
#
# PIN_HOSTED_MODEL exists for when that matters. Set it and no probe runs, the
# key is fixed, and the run is reproducible. Use it for the Phase 8 labelling
# corpus, where one judge across the whole set is the entire point.
# ---------------------------------------------------------------------------
PROBE_BLOCK = '''

# ---------------------------------------------------------------------------
# Which hosted model is actually serving RIGHT NOW
#
# A hardcoded ladder is a measurement, and measurements go stale: this
# notebook shipped one ordering ("flash-lite is the only model that serves")
# that was later measured at 25 SECONDS to answer a one-word prompt, while
# gemini-3.5-flash answered the same prompt in 3.3s on the same key in the
# same minute. Probing costs one tiny call per candidate and removes the guess.
#
# Set PIN_HOSTED_MODEL to skip probing entirely. Do that whenever the cache key
# must be reproducible -- notably the Phase 8 labelling corpus, where the whole
# point is ONE judge across every video.
# ---------------------------------------------------------------------------
PIN_HOSTED_MODEL = None          # e.g. 'gemini-3.5-flash' -> no probe, fixed key

HOSTED_PROBE_CANDIDATES = (
    'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite',
    'gemini-3.8-flash', 'gemini-flash-lite-latest', 'gemini-flash-latest',
    'gemini-pro-latest',
)
HOSTED_PROBE_TIMEOUT_S = 20      # a model too slow to say "ok" is too slow to judge
_HOSTED_PROBE_CACHE = {}         # probe once per session, not once per call


def probe_hosted_models(candidates=None, timeout_s: float = None,
                        verbose: bool = True) -> list:
    """[(seconds, model)] that answered, fastest first. Never raises.

    Run in PARALLEL: seven serial probes against a 25s model is two minutes
    before any real work begins, and the probe exists to SAVE time.
    """
    import concurrent.futures as _cf
    import time as _t
    candidates = tuple(candidates or HOSTED_PROBE_CANDIDATES)
    timeout_s = float(timeout_s or HOSTED_PROBE_TIMEOUT_S)
    # os.environ directly, NOT _get_secret/HostedLLMBackend: both are defined
    # further down the notebook than this cell, and calling them here is a
    # NameError on a fresh kernel. §37a has already hoisted any Colab secret
    # into the environment by the time this runs, so this reads the same value.
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        if verbose:
            print('  no Gemini key -- skipping the probe')
        return []
    try:
        # The SDK is installed lazily by the backend, which has not run yet.
        _ti = globals().get('try_install')
        if callable(_ti):
            _ti('google-genai', 'google.genai')
        from google import genai
        from google.genai import types as _gt
        client = genai.Client(api_key=key, http_options=_gt.HttpOptions(
            timeout=int(timeout_s * 1000)))
    except Exception as exc:
        if verbose:
            print(f'  probe unavailable ({type(exc).__name__}) -- '
                  f'keeping the configured order')
        return []

    def _one(name):
        t0 = _t.time()
        try:
            r = client.models.generate_content(
                model=name, contents='Reply with one word: ok')
            return name, _t.time() - t0, (r.text or '').strip()[:20], None
        except Exception as exc:
            return name, _t.time() - t0, None, f'{type(exc).__name__}: {str(exc)[:70]}'

    out = []
    with _cf.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        for name, dt, text, err in ex.map(_one, candidates):
            if err is None:
                out.append((dt, name))
                if verbose:
                    print(f'    OK    {name:26} {dt:5.1f}s  {text!r}')
            elif verbose:
                print(f'    fail  {name:26} {err}')
    out.sort()
    return out


def autoselect_hosted_model(cfg=None, verbose: bool = True):
    """BriefConfig with hosted_model/ladder set to what is serving now.

    Returns the config UNCHANGED when pinned, when nothing answers, or when
    there is no key -- degrade, never block. A probe that cannot reach the
    network must not stop an audit that the call-time ladder could still run.
    """
    import dataclasses as _dc
    cfg = cfg or P4.brief
    if PIN_HOSTED_MODEL:
        if verbose:
            print(f'  hosted model PINNED to {PIN_HOSTED_MODEL} '
                  f'(no probe; cache key is reproducible)')
        return _dc.replace(cfg, hosted_model=PIN_HOSTED_MODEL,
                           hosted_model_ladder=(PIN_HOSTED_MODEL,))
    if 'ranked' not in _HOSTED_PROBE_CACHE:
        if verbose:
            print('  probing hosted models (parallel, once per session):')
        _HOSTED_PROBE_CACHE['ranked'] = probe_hosted_models(verbose=verbose)
    ranked = _HOSTED_PROBE_CACHE['ranked']
    if not ranked:
        if verbose:
            print(f'  nothing answered -- keeping the configured order '
                  f'({cfg.hosted_model} first). The call-time ladder and the '
                  f'paid fallback still apply.')
        return cfg
    order = tuple(m for _dt, m in ranked)
    if verbose:
        print(f'  hosted model -> {order[0]}  ({ranked[0][0]:.1f}s), '
              f'fallbacks {order[1:3] or "none"}')
        print('  NOTE: hosted_model is part of the brief cache key, so this '
              'choice names the judge that ran.')
        print('        Set PIN_HOSTED_MODEL for a reproducible key.')
    return _dc.replace(cfg, hosted_model=order[0], hosted_model_ladder=order)


P4 = dataclasses.replace(P4, brief=autoselect_hosted_model(P4.brief))
'''


def fix27(s):
    anchor = "print('%s37/%s38 loaded." % (S, S)
    if 'def probe_hosted_models' in s:
        return None
    # Appended to the cell that BUILDS P4, so the choice is made exactly once,
    # where the config is created, rather than at some later call site.
    if 'P4 = Phase4Config(' not in s:
        return None
    return s.rstrip('\n') + '\n' + PROBE_BLOCK


# ---------------------------------------------------------------------------
# Fix 28 -- a stale fallback default that would MIS-KEY a visual artifact
#
# plan_vlm_load's hosted branch:
#
#     _gm = (getattr(cfg, 'gemini_models', None) or ('gemini-flash-latest',))[0]
#
# The fallback names gemini-flash-latest, which this notebook has measured as
# 503 UNAVAILABLE twice now, and which is NOT VisionConfig's default. It only
# fires when a config has no gemini_models attribute -- a stub, or a future
# config shape -- but what it produces goes straight into the visual CACHE KEY.
# A wrong value here files an artifact under the name of a model that cannot
# even run. Match the real default instead of a model that does not serve.
# ---------------------------------------------------------------------------
OLD_GM_DEFAULT = ("        _gm = (getattr(cfg, 'gemini_models', None) "
                  "or ('gemini-flash-latest',))[0]")
NEW_GM_DEFAULT = (
    "        # The fallback must match VisionConfig.gemini_models, not a model\n"
    "        # measured at 503. Whatever this returns goes into the visual\n"
    "        # cache key, so a wrong name files the artifact under a model\n"
    "        # that never ran -- the exact collision 1.11.0 added it to stop.\n"
    "        _gm = (getattr(cfg, 'gemini_models', None)\n"
    "               or ('gemini-flash-lite-latest',))[0]")


def fix28(s):
    if OLD_GM_DEFAULT not in s:
        return None
    return s.replace(OLD_GM_DEFAULT, NEW_GM_DEFAULT, 1)


# ---------------------------------------------------------------------------
# Fix 29 -- Phase 3 was the last stage still pinned to the 25-second model
#
# Fix 25/27 fixed the TEXT path. Vision was still hardcoded to
# gemini-flash-lite-latest -- the model measured at 25s for a one-word reply,
# and Phase 3 sends it 19-42 FRAMES per video.
#
# A text probe is not enough to choose a vision model: a model can answer
# "ok" and still not accept images, or not honour response_mime_type=json.
# So this probe sends a real image AND asks for JSON, mirroring _once()
# exactly -- same config keys, same response type. A model that passes this
# probe can actually do the job it is being selected for.
#
# gemini_models[0] IS THE VISUAL CACHE KEY. That is deliberate (1.11.0) and it
# means choosing a different model re-runs the whole vision pass. So the probe
# says so, out loud, and says nothing at all when the winner is what is already
# configured -- no warning for a no-op. PIN_VISION_MODEL switches probing off
# entirely, which is what the Phase 8 corpus wants: one describer for every
# video, chosen once.
# ---------------------------------------------------------------------------
VISION_PROBE_BLOCK = '''

# ---------------------------------------------------------------------------
# Which hosted VISION model is serving right now
#
# Phase 3 sends 19-42 frames per video. Running that through a model measured
# at 25 seconds for a one-word text reply is the single most expensive stale
# default in the notebook.
#
# The probe sends a real IMAGE and requires JSON back, because that is what
# the stage actually needs -- a model that merely answers text would pass a
# text probe and then fail on the first real frame batch.
# ---------------------------------------------------------------------------
PIN_VISION_MODEL = None          # set a name to skip the probe and fix the key
VISION_PROBE_CANDIDATES = (
    'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-flash-lite-latest',
    'gemini-3.1-flash-lite', 'gemini-3.8-flash',
)
VISION_PROBE_TIMEOUT_S = 30
_VISION_PROBE_CACHE = {}


def probe_vision_models(candidates=None, timeout_s: float = None,
                        verbose: bool = True) -> list:
    """[(seconds, model)] that described an IMAGE and returned JSON, best first.

    Parallel, and never raises: a probe that cannot run must leave the
    configured model in place rather than stop the pipeline.
    """
    import concurrent.futures as _cf
    import time as _t
    candidates = tuple(candidates or VISION_PROBE_CANDIDATES)
    timeout_s = float(timeout_s or VISION_PROBE_TIMEOUT_S)
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        if verbose:
            print('  no Gemini key -- skipping the vision probe')
        return []
    try:
        _ti = globals().get('try_install')
        if callable(_ti):
            _ti('google-genai', 'google.genai')
        from google import genai
        from google.genai import types as _gt
        from PIL import Image as _Image
        client = genai.Client(api_key=key, http_options=_gt.HttpOptions(
            timeout=int(timeout_s * 1000)))
    except Exception as exc:
        if verbose:
            print(f'  vision probe unavailable ({type(exc).__name__}) -- '
                  f'keeping the configured model')
        return []

    _img = _Image.new('RGB', (64, 64), (200, 40, 40))

    def _one(name):
        t0 = _t.time()
        try:
            r = client.models.generate_content(
                model=name,
                contents=[_img, 'Reply with JSON: {"colour": "<the colour>"}'],
                # the same shape _once() uses, so passing here means passing there
                config={'system_instruction': 'You describe images.',
                        # generous: a 3.x model may spend tokens thinking, and
                        # an empty reply would look like a failure it is not
                        'max_output_tokens': 256,
                        'temperature': 0.0,
                        'response_mime_type': 'application/json'})
            txt = (getattr(r, 'text', '') or '').strip()
            if not txt:
                raise RuntimeError('empty response (no text returned)')
            return name, _t.time() - t0, txt[:32], None
        except Exception as exc:
            return name, _t.time() - t0, None, f'{type(exc).__name__}: {str(exc)[:70]}'

    out = []
    with _cf.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        for name, dt, text, err in ex.map(_one, candidates):
            if err is None:
                out.append((dt, name))
                if verbose:
                    print(f'    OK    {name:26} {dt:5.1f}s  {text!r}')
            elif verbose:
                print(f'    fail  {name:26} {err}')
    out.sort()
    return out


def autoselect_vision_model(cfg=None, verbose: bool = True):
    """VisionConfig using the fastest model that really described an image."""
    import dataclasses as _dc
    cfg = cfg or P3.vision
    if getattr(cfg, 'provider', 'gemini') == 'local':
        return cfg
    current = (getattr(cfg, 'gemini_models', None) or ('',))[0]
    if PIN_VISION_MODEL:
        if verbose:
            print(f'  vision model PINNED to {PIN_VISION_MODEL} (no probe)')
        return _dc.replace(cfg, gemini_models=(PIN_VISION_MODEL,))
    if 'ranked' not in _VISION_PROBE_CACHE:
        if verbose:
            print('  probing hosted VISION models (image + JSON, parallel):')
        _VISION_PROBE_CACHE['ranked'] = probe_vision_models(verbose=verbose)
    ranked = _VISION_PROBE_CACHE['ranked']
    if not ranked:
        if verbose:
            print(f'  nothing described an image -- keeping {current}')
        return cfg
    # KEEP EVERY MODEL THAT ANSWERED, fastest first -- not just the winner.
    # Returning a 1-tuple looked harmless because ranked[0] is the fastest, but
    # it deleted the fallbacks: the ladder in _generate() reaches
    # "unusable, trying the next model" and there IS no next model, so a single
    # 503 "the model is facing high demand" kills the stage. Overload is
    # per-model -- gemini-3.5-flash is often wide open while flash-lite is
    # swamped -- so the other probed models are exactly the escape hatch.
    # ranked[0] stays first, so gemini_models[0] (the visual CACHE KEY) is
    # unchanged and no existing artifact is invalidated by this.
    _ladder = tuple(n for _, n in ranked)
    winner = ranked[0][1]
    if winner == current:
        if verbose:
            print(f'  vision model -> {winner} ({ranked[0][0]:.1f}s), unchanged; '
                  f'existing visual artifacts stay valid')
            if len(_ladder) > 1:
                print(f'  fallbacks if it is overloaded: '
                      f'{", ".join(_ladder[1:])}')
        return _dc.replace(cfg, gemini_models=_ladder)
    if verbose:
        print(f'  vision model -> {winner}  ({ranked[0][0]:.1f}s, was {current})')
        print('  NOTE: gemini_models[0] IS the visual cache key, so this '
              're-runs the vision pass')
        print('        for every video. Set PIN_VISION_MODEL to keep the '
              'existing artifacts.')
        if len(_ladder) > 1:
            print(f'  fallbacks if it is overloaded: {", ".join(_ladder[1:])}')
    return _dc.replace(cfg, gemini_models=_ladder)


P3 = dataclasses.replace(P3, vision=autoselect_vision_model(P3.vision))
'''


def fix29(s):
    if 'def probe_vision_models' in s:
        return None
    if 'def make_vision_backend' not in s:
        return None
    return s.rstrip('\n') + '\n' + VISION_PROBE_BLOCK


# ---------------------------------------------------------------------------
# Fix 30 -- say whether it is the KEY or the servers
#
# The probes test models. An invalid key and a total outage both come out as
# "nothing answered", and they call for OPPOSITE actions: rotate the key, or
# wait. Guessing wrong costs an afternoon -- the user nearly created a new key
# for a 503, which a new key cannot fix.
#
# The per-model error text was already printed, but a human has to read seven
# stack-trace fragments to spot that all seven say the same thing. Classify it.
# ---------------------------------------------------------------------------
VERDICT_FN = '''

def key_failure_verdict(errors: list) -> str:
    """One line: is the KEY the problem, the quota, or the servers?

    Each has a different fix, and "nothing answered" hides which one you have.
    Only claims a cause when EVERY candidate failed the same way -- a mixed
    bag means read the individual errors, not a confident wrong summary.
    """
    errors = [str(e) for e in (errors or [])]
    if not errors:
        return ''
    def _all(*needles):
        return all(any(n in e for n in needles) for e in errors)
    if _all('API_KEY_INVALID', 'PERMISSION_DENIED', 'UNAUTHENTICATED',
            'API key not valid', '401', '403'):
        return ('THE KEY IS THE PROBLEM: every candidate refused it. '
                'Check GEMINI_API_KEY in Colab secrets.')
    if _all('RESOURCE_EXHAUSTED', '429'):
        return ('QUOTA, not the key: every candidate returned 429. A new key '
                'in the SAME project shares the same quota -- use a new '
                'project, or wait for the daily reset (midnight Pacific).')
    if _all('UNAVAILABLE', '503', 'high demand', 'overloaded'):
        return ('SERVER SIDE: every candidate returned 503. The key is fine. '
                'Retry shortly; a new key will not help.')
    if _all('NOT_FOUND', '404'):
        return ('RETIRED MODELS: every candidate 404d. The candidate list is '
                'out of date, not the key.')
    return 'MIXED failures -- read the per-model errors above.'
'''

OLD_PROBE_TAIL = """            elif verbose:
                print(f'    fail  {name:26} {err}')
    out.sort()
    return out"""

NEW_PROBE_TAIL = """            else:
                _errs.append(err)
                if verbose:
                    print(f'    fail  {name:26} {err}')
    if not out and verbose:
        # Nothing answered. Say WHICH failure this is -- rotate, wait, or
        # retry are three different actions and the raw errors bury the answer.
        _vf = globals().get('key_failure_verdict')
        _msg = _vf(_errs) if callable(_vf) else ''
        if _msg:
            print(f'    -> {_msg}')
    out.sort()
    return out"""

OLD_PROBE_INIT = """    out = []
    with _cf.ThreadPoolExecutor("""

NEW_PROBE_INIT = """    out, _errs = [], []
    with _cf.ThreadPoolExecutor("""


def fix30a(s):
    """The classifier lives with the KEY cell -- it runs before both probes."""
    if 'def key_failure_verdict' in s or 'NO KEY IN THIS FILE, EVER' not in s:
        return None
    return s.rstrip('\n') + '\n' + VERDICT_FN


def fix30b(s):
    """Both probes report the verdict. Same tail in each, so replace ALL."""
    if OLD_PROBE_TAIL not in s:
        return None
    return s.replace(OLD_PROBE_INIT, NEW_PROBE_INIT).replace(
        OLD_PROBE_TAIL, NEW_PROBE_TAIL)


# ---------------------------------------------------------------------------
# Fix 31 -- the half after the colon is the ONLY part a creator ever says
#
# _claim_headline's docstring asserts: "The half before the colon is the ask;
# the rest is the brand explaining it to the creator." That was my reasoning
# in fix 16 and it is wrong, measured across seven real videos.
#
# The brief writes its features as "Label: what it means":
#
#   Gentle & Non-Habit-Forming: MELATONIN-FREE FORMULA ensures safe nightly use
#   Clean & Safe Formula:       NO ADDED SUGARS, artificial colors, flavors
#   Allergen-Friendly:          FREE FROM THE TOP 9 ALLERGENS
#   Delicious Fruity Taste:     LESS THAN 1g SUGAR per serving
#
# Nobody says "gentle and non-habit-forming" out loud. They say "melatonin
# free". The requirement carried only the LABEL, so both the retrieval query
# (_req_query_text) and the L3 prompt were built from words no creator uses,
# and the judge was asked whether she said a phrase that exists only in the
# brand's internal vocabulary.
#
# MEASURED: across all seven videos, "Gentle & Non-Habit-Forming",
# "Allergen-Friendly" and "Clean & Safe Formula" were NOT EVIDENCED in every
# single one -- 0 for 7, three times over. Meanwhile the transcript of
# 88415c4e opens with "these magnesium MELATONIN FREE calm and sleep gummies"
# and the verdict reads "never mentions being gentle or non-habit-forming".
# A talking point that no creator in a corpus can ever hit is a broken
# measurement, not seven identical creative failures.
#
# THE FIX USES PLUMBING THAT ALREADY EXISTS. acceptance_criteria is fed into
# _req_query_text (so L2 retrieval sees it) and printed in the L3 prompt as
# "what would make this pass". Putting the definition there and NOT in
# match_hints is deliberate: match_hints goes to the fuzzy phrase matcher,
# which is exactly the trap fix 16 removed them to avoid ("MELATONIN" scoring
# 100 against a melatonin-FREE claim). Meaning belongs in the semantic path.
# ---------------------------------------------------------------------------
CLAIM_DEFN_FN = '''def _claim_definition(text: str, head: str) -> str:
    """The half AFTER the colon -- what the feature actually means.

    "Gentle & Non-Habit-Forming: Melatonin-free formula ensures safe nightly
    use" -- the creator will say "melatonin free", never the label. Judging
    her against the label alone asks whether she used the brand's internal
    vocabulary, which is not what the brief asks for and not what she was
    given the brief for.
    """
    t = (text or '').strip()
    if ':' in t[:80]:
        rest = t.split(':', 1)[1].strip()
        rest = re.sub(r'\\s*\\(include as [^)]*\\)\\s*', ' ', rest, flags=re.I)
        rest = ' '.join(rest.split())
        if len(rest) >= 8 and rest.lower() != (head or '').lower():
            return rest[:240]
    return ''


'''

OLD_CLAIM_REQ = """            'confidence': 1.0, 'source': 'approved_claims',"""
NEW_CLAIM_REQ = """            'confidence': 1.0, 'source': 'approved_claims',
            # What the brief says this feature MEANS. Fed to _req_query_text
            # (so L2 retrieves on meaning) and printed in the L3 prompt as
            # "what would make this pass". NOT match_hints -- see below.
            'acceptance_criteria': ([f'The creator communicates this feature '
                                     f'in her own words. The brief defines it '
                                     f'as: {_defn}']
                                    if _defn else []),"""

OLD_HEAD_CALL = """        head = _claim_headline(ctext)"""
NEW_HEAD_CALL = """        head = _claim_headline(ctext)
        _defn = _claim_definition(ctext, head)"""


def fix31(s):
    if 'def _claim_definition' in s:
        return None
    if 'def _claim_headline' not in s or OLD_CLAIM_REQ not in s:
        return None
    out = s.replace('def _claim_headline', CLAIM_DEFN_FN + 'def _claim_headline', 1)
    out = out.replace(OLD_HEAD_CALL, NEW_HEAD_CALL, 1)
    out = out.replace(OLD_CLAIM_REQ, NEW_CLAIM_REQ, 1)
    # the docstring that justified the bug
    out = out.replace(
        'The half before the colon is the ask; the rest is the brand '
        'explaining it to the creator.',
        'The half before the colon is the LABEL. The rest is what it MEANS, '
        'and fix 31 carries it into acceptance_criteria -- a creator says '
        '"melatonin free", never "gentle and non-habit-forming".')
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 33 -- substance credit skipped every PARTIAL
#
# The credit loop opens `if v.status != 'FAIL': continue`, so a verdict that
# landed PARTIAL could never be promoted however well it aligned. Measured on
# video a1a06e8d:
#
#   PARTIAL  Supports Digestive Health   meaning: STRONG
#            "Mentions fiber to help support digestion and probiotics"
#
# Strong alignment, cited to a record, and stuck at half marks -- because the
# literal layer happened to say PARTIAL rather than FAIL. The user's rule has
# been explicit and repeated: "if she is doing something relevant to the
# requirement she should be scored positive for that requirement."
#
# The two gates are unchanged and still apply. This only widens WHICH verdicts
# are eligible, and only ever upward: a PARTIAL is considered when the
# alignment maps to PASS, and otherwise left exactly as it was. A promotion
# that would not improve the status is skipped so nothing is re-flagged for a
# no-op.
# ---------------------------------------------------------------------------
OLD_CREDIT_GATE = """    for v in verdicts:
        if v.status != 'FAIL':
            continue"""

NEW_CREDIT_GATE = """    for v in verdicts:
        # FAIL *and* PARTIAL. A PARTIAL with `strong` alignment is the same
        # creator doing the same thing in her own words -- which literal layer
        # produced the status does not change whether she did it. Only ever
        # upward: a PARTIAL is eligible when the alignment maps to PASS.
        if v.status not in ('FAIL', 'PARTIAL'):
            continue
        if (v.status == 'PARTIAL'
                and _SUBSTANCE_STATUS.get(v.alignment or '') != 'PASS'):
            continue"""


def fix33(s):
    if OLD_CREDIT_GATE not in s:
        return None
    return s.replace(OLD_CREDIT_GATE, NEW_CREDIT_GATE, 1)


# ---------------------------------------------------------------------------
# Fix 34 -- a menu option was being presented as if it were the ask
#
# Settled on real reports, not guessed. Video a1a06e8d opens:
#
#   0:00 "In case you didn't get your new parents' manual at the hospital,"
#   0:02 "this is how you get your children to go to sleep at night."
#   0:03 "It's hard for our babies to go to sleep,"
#
# The Hooks group FAILED with alignment `none` and the reason "No speech or
# text matching the hook phrase or similar" -- CITING THOSE EXACT RECORDS. So
# retrieval was right, the evidence was right, and the brief contains three
# bedtime hooks her opening plainly belongs with. The judgement was wrong.
#
# It is not the instructions. L3_SYSTEM already carries the worked example and
# says outright: "When a CHOICE GROUP is shown above, judge alignment against
# the kind of ask the whole group describes, not against the single sentence
# of this one option." It is the FRAME. Every requirement is rendered as
#
#     text          : Open the video using the hook: "Listen! If your kid
#                     lives on nuggets and fries..."
#
# and the group note arrives three lines later. Asked ten near-identical
# questions in one batch, each headed by a different literal sentence, the
# model answers the sentence -- and its reasons say so in as many words:
# "matching the specified phrase". 097098 proves the same point from the other
# side: it scored the CONCEPT group PARTIAL, correctly recognising "he's not
# ignoring me", and then failed her on the hook-LINE group for not reciting
# one of ten example sentences.
#
# So put the ask where the model reads first, and demote the option to what
# the brief says it is: an example. Nothing about the two judgements changes
# -- status is still literal, alignment is still the second question -- and
# an UNGROUPED requirement renders exactly as before.
# ---------------------------------------------------------------------------
OLD_L3_HEAD = """        out.append(f'REQUIREMENT id={rd.get("id")}')
        out.append(f'  text          : {rd.get("requirement", "")}')
        out.append(f'  evidence_mode : {rd.get("evidence_mode")}')
        _gid = rd.get('group')
        _sibs = [r for r in (groups.get(_gid) or []) if r.get('id') != rd.get('id')]
        if _gid and _sibs:"""

NEW_L3_HEAD = """        out.append(f'REQUIREMENT id={rd.get("id")}')
        _gid = rd.get('group')
        _sibs = [r for r in (groups.get(_gid) or []) if r.get('id') != rd.get('id')]
        _gintent = str(rd.get('group_intent') or '').strip()
        # THE ASK FIRST, the example second. A menu option rendered as the
        # `text` line reads as the requirement, and the model answers it
        # literally -- measured: ten hook options, ten `alignment: none`, each
        # reason naming "the specified phrase", on a video whose opening was
        # cited correctly and plainly belonged to the group.
        if _gid and _sibs and _gintent:
            out.append(f'  THE ASK       : {_gintent}')
            out.append(f'  this option   : one EXAMPLE of that ask, worded '
                       f'"{str(rd.get("requirement", ""))[:150]}"')
            out.append('  status judges THIS option\\'s wording. alignment '
                       'judges THE ASK, in any wording.')
        else:
            out.append(f'  text          : {rd.get("requirement", "")}')
        out.append(f'  evidence_mode : {rd.get("evidence_mode")}')
        if _gid and _sibs:"""


def fix34(s):
    if OLD_L3_HEAD not in s:
        return None
    return s.replace(OLD_L3_HEAD, NEW_L3_HEAD, 1)


# Fix 34 leads with THE ASK, so the older block four lines below repeats the
# same sentence. Pure token cost, and on a ten-option hook group it is paid
# ten times per call. Also scope the hint line to the OPTION: those words
# belong to this one example, and labelling them as the ask's words is exactly
# the literal pull fix 34 exists to remove.
OLD_DUP_INTENT = """            _intent = str(rd.get('group_intent') or '').strip()
            if _intent:"""
NEW_DUP_INTENT = """            _intent = str(rd.get('group_intent') or '').strip()
            if _intent and not _gintent:"""

OLD_HINTS = """            out.append(f'  the brief counts these words as doing it: '
                       f'{", ".join(_hints[:10])}')"""
NEW_HINTS = """            out.append(f'  words that would satisfy '
                       f'{"THIS OPTION" if (_gid and _sibs) else "it"} '
                       f'literally: {", ".join(_hints[:10])}')"""


def fix34b(s):
    if 'def build_l3_prompt' not in s or OLD_DUP_INTENT not in s:
        return None
    out = s.replace(OLD_DUP_INTENT, NEW_DUP_INTENT, 1)
    out = out.replace(OLD_HINTS, NEW_HINTS, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 35 -- §37a swallowed every reason it found no key
#
# Fix 26 removed the hardcoded keys, which was right, and replaced them with a
# Colab-secrets hoist that caught EVERY failure and said nothing:
#
#     except Exception:
#         pass          # secret absent, or notebook access not granted
#
# So §37a printed one quiet "NOT set" line and the run continued, and Phase 3
# died a cell later with a RuntimeError and a traceback. The user hit exactly
# that. The old hardcoded cell could not fail; my replacement could, and I gave
# it no voice.
#
# Colab distinguishes the two cases and they need OPPOSITE actions:
#   SecretNotFoundError   the secret does not exist   -> create it
#   NotebookAccessError   it exists, access is OFF    -> flip the toggle
# Guessing between them is the difference between a 10-second fix and a
# confused half hour, so report which one happened, by name.
#
# It still does not raise. A missing OPENAI key is fine -- it only disables the
# paid fallback -- and the stage that truly needs a key says so itself, with a
# message that already names this cell. What changes is that §37a now tells you
# WHY, where you can act on it, instead of leaving a traceback to do it badly.
# ---------------------------------------------------------------------------
OLD_HOIST = """try:
    from google.colab import userdata          # noqa: F401
    for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):
        if not os.environ.get(_n):
            try:
                _v = userdata.get(_n)
                if _v and _v.strip():
                    os.environ[_n] = _v.strip()
            except Exception:
                pass          # secret absent, or notebook access not granted
except Exception:
    pass                      # not Colab -- real environment variables apply"""

NEW_HOIST = """_KEY_WHERE = {}          # name -> where it came from, or why it did not
try:
    from google.colab import userdata          # noqa: F401
    _in_colab = True
except Exception:
    userdata, _in_colab = None, False

for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):
    if os.environ.get(_n, '').strip():
        _KEY_WHERE[_n] = 'environment variable'
        continue
    if not _in_colab:
        _KEY_WHERE[_n] = 'not set (not running in Colab -- export it)'
        continue
    try:
        _v = userdata.get(_n)
        if _v and _v.strip():
            os.environ[_n] = _v.strip()
            _KEY_WHERE[_n] = 'Colab secret'
        else:
            _KEY_WHERE[_n] = 'Colab secret exists but is EMPTY'
    except Exception as _exc:
        # These two need OPPOSITE fixes, so never report them as one thing.
        _k = type(_exc).__name__
        if 'NotebookAccess' in _k:
            _KEY_WHERE[_n] = ('the secret EXISTS but this notebook may not '
                              'read it -- open the key icon and turn '
                              '"Notebook access" ON')
        elif 'SecretNotFound' in _k:
            _KEY_WHERE[_n] = ('no such Colab secret -- key icon, left '
                              'sidebar, + New secret, name it exactly '
                              f'{_n}')
        else:
            _KEY_WHERE[_n] = f'could not read the Colab secret ({_k})'"""

OLD_KEY_REPORT = """for _name, _tier in (('GEMINI_API_KEY', 'free tier, tried first'),
                     ('OPENAI_API_KEY', 'PAID, fallback only')):
    _v = os.environ.get(_name, '')
    print(f'{_name:<16} {"set" if _v else "NOT set"} ({len(_v)} chars)  -- {_tier}')"""

NEW_KEY_REPORT = """for _name, _tier in (('GEMINI_API_KEY', 'free tier, tried first'),
                     ('OPENAI_API_KEY', 'PAID, fallback only')):
    _v = os.environ.get(_name, '')
    _src = _KEY_WHERE.get(_name, 'not set')
    print(f'{_name:<16} {"set" if _v else "NOT SET"} ({len(_v)} chars)  '
          f'-- {_tier}')
    if not _v:
        print(f'                 why: {_src}')

# GEMINI is not optional here: Phase 3 sends the frames to it and this
# notebook does NOT fall back to a local model. Say that HERE, where the fix
# is, rather than letting §26b raise two cells later.
if not os.environ.get('GEMINI_API_KEY', '').strip():
    print()
    print('  ' + '!' * 68)
    print('  NO GEMINI KEY. Phase 3 (vision) and Phase 4/6 (brief, L3) both')
    print('  need it, and this notebook is hosted-only -- it will stop at')
    print('  §26b rather than quietly use a different model.')
    print('  Fix it above, re-run THIS cell, then carry on.')
    print('  ' + '!' * 68)"""


def fix35(s):
    if '_KEY_WHERE' in s or OLD_HOIST not in s:
        return None
    out = s.replace(OLD_HOIST, NEW_HOIST, 1)
    out = out.replace(OLD_KEY_REPORT, NEW_KEY_REPORT, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 36 -- OCR floods the evidence and drowns what she SAID
#
# Found by the user on bba96ac4: "she clearly said they taste like berry
# flavoured fruit snack but report says not evidenced".
#
# She does, twice, and Phase 5 caught both:
#     0:10 speech "they taste just like berry flavored fruit snacks"
#     0:15 speech "how's it taste ... what I absolutely love is"
# The verdict: "She never mentions the delicious fruity taste", CITES NOTHING.
#
# MEASURED on that video's own records:
#     counts: {'ocr': 165, 'speech': 8}
#
# The packaging is OCR'd on nearly every frame, so OCR outnumbers speech 20:1.
# Ranking is modality-blind, every one of the ten candidate slots went to
# nutrition-label fragments ("Total Sugar", "with other natural flavor",
# "includes 0g Added Sugar"), and the two sentences that answer the question
# were never offered. The judge answered honestly about what it was shown.
#
# Dedupe alone does NOT fix it -- measured, the taste line moves from rank 26
# to 19, still outside the top 10, because label fragments beat a
# conversational sentence on this embedder. What fixes it is refusing to let
# one modality take every slot: with a cap the line lands at #4.
#
# THIS IS THE POINT OF evidence_mode. `speech_or_text` means she may SAY it OR
# SHOW it. Offering ten OCR records and no speech silently turns that OR into
# an and-of-one, and the requirement is then judged on half the evidence it
# was defined to accept.
#
# Order is still best-first: the walk is in rank order and only skips a
# candidate whose modality is already full, so the top-ranked record of every
# modality always survives. With a single modality present, nothing changes.
# ---------------------------------------------------------------------------
BALANCE_FNS = '''def _dedupe_candidates(cands: list) -> list:
    """Drop repeats of the SAME text, keeping the best-ranked one.

    A label OCR'd on thirty frames is thirty records carrying one fact. They
    are all still in the evidence store and on the report timeline; what they
    must not do is spend thirty of the judge's ten slots.
    """
    seen, out = set(), []
    for c in cands:
        rec = c['record']
        key = re.sub(r'[^a-z0-9 ]+', ' ',
                     (rec.raw_text or rec.description or '').lower())
        key = f"{rec.modality}:{' '.join(key.split())}"
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _balance_modalities(cands: list, k: int, max_share: float) -> list:
    """Top-k, but no single modality may take every slot.

    MEASURED on bba96ac4: 165 OCR records against 8 speech ones, so the whole
    candidate set was packaging text and "they taste just like berry flavored
    fruit snacks" -- said out loud, twice -- was never offered to the judge.

    Rank order is preserved. A candidate is skipped only when its modality is
    already full, so the best record of each modality always survives, and a
    short list is topped up in rank order rather than returned undersized.
    """
    if k <= 0 or len(cands) <= k:
        return list(cands)
    mods = {c['record'].modality for c in cands}
    if len(mods) < 2:
        return cands[:k]
    cap = max(1, int(round(k * max_share)))
    out, counts, taken = [], {}, set()
    for i, c in enumerate(cands):
        m = c['record'].modality
        if counts.get(m, 0) >= cap:
            continue
        out.append(c)
        taken.add(i)
        counts[m] = counts.get(m, 0) + 1
        if len(out) >= k:
            return out
    for i, c in enumerate(cands):          # top up if a cap left us short
        if i not in taken:
            out.append(c)
            if len(out) >= k:
                break
    return out


'''

OLD_RETURN = """    return out[:rc.top_k]"""
NEW_RETURN = """    # One modality must not take every slot -- see _balance_modalities. The
    # dedupe runs first so the slots that survive carry DISTINCT facts.
    return _balance_modalities(_dedupe_candidates(out), rc.top_k,
                               getattr(rc, 'max_modality_share', 0.6))"""

OLD_RC = """    include_metadata: bool = False"""
NEW_RC = """    include_metadata: bool = False
    # No single modality may hold more than this share of the candidate slots.
    # Measured on a real video: 165 OCR records against 8 speech ones, so
    # every slot was packaging text and what the creator SAID was never
    # offered. 0.6 of 10 leaves at least four slots for another modality,
    # which was enough to surface it at rank 4.
    max_modality_share: float = 0.6"""


def fix36(s):
    if '_balance_modalities' in s:
        return None
    out = s
    if 'class RetrievalConfig' in s and OLD_RC in s:
        out = out.replace(OLD_RC, NEW_RC, 1)
    if 'def candidates_for(' in s and OLD_RETURN in s:
        out = out.replace('def candidates_for(', BALANCE_FNS + 'def candidates_for(', 1)
        out = out.replace(OLD_RETURN, NEW_RETURN, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 37 -- the FDA disclaimer was one of the CTA "options"
#
# Measured on ALL SEVEN videos of the 1790101872 batch:
#
#     *These statements have not been evaluated by the FDA...
#       -> Not the option satisfied for choice group 'Call to Actions'
#       -> NOT_APPLICABLE
#
# The brief prints the disclaimer directly under the Call to Actions list, so
# the compiler read it as a fifth CTA. A one_of group is ONE scoring unit: any
# video that closes with any CTA marks the disclaimer "not applicable" and it
# is NEVER CHECKED. The system reported compliance it had not tested, on every
# video, silently.
#
# It is the one genuinely mandatory line in this brief -- the asterisk on the
# "World's #1 Brand of Children's Prebiotic and Probiotic Supplements" claim
# the creators are making on camera.
#
# A compliance line is never an ALTERNATIVE to anything. It is ungrouped here
# so it becomes its own scoring unit and is actually evaluated. Its priority
# and type are left alone deliberately: what to DO about a missing disclaimer
# is a policy decision with a critical-floor lever attached, and this fix is
# only about restoring the check. Expect scores to fall on videos that omit
# it -- that is the finding, not a regression.
# ---------------------------------------------------------------------------
DISCLAIMER_FN = '''# A legal disclaimer is never one of a menu of options.
_DISCLAIMER_RE = re.compile(
    r'(have\\s+not\\s+been\\s+evaluated\\s+by\\s+the\\s+(food\\s+and\\s+drug|fda)'
    r'|not\\s+intended\\s+to\\s+(diagnose|treat|cure|prevent)'
    r'|these\\s+statements\\s+have\\s+not\\s+been)', re.I)


def ungroup_compliance_lines(reqs: list) -> list:
    """A disclaimer is mandatory, never an ALTERNATIVE. Returns what it moved.

    Measured on seven of seven videos: the FDA disclaimer sat in the 'Call to
    Actions' choice group, so every video that delivered any CTA marked the
    disclaimer NOT_APPLICABLE and it was never evaluated. A one_of group is
    ONE scoring unit; putting a compliance line in one excuses it whenever a
    sibling passes.
    """
    moved = []
    for r in reqs or []:
        txt = f"{_req_field(r, 'requirement') or ''} {_req_field(r, 'brief_span') or ''}"
        if not _DISCLAIMER_RE.search(txt):
            continue
        gid = _req_field(r, 'group')
        if not gid:
            continue
        moved.append((_req_field(r, 'id'), gid))
        # BOTH SHAPES. A requirement is a dataclass on the compile path and a
        # dict after to_dict(), and ungroup_non_alternatives -- three lines
        # below -- has always handled both. The first version of this function
        # mutated only the dict branch, so on the object path it changed
        # NOTHING while still appending to `moved`: a function reporting
        # success it had not achieved. Measured on all seven videos of the
        # 1790103374 batch -- the disclaimer stayed inside the CTA group and
        # was still NOT_APPLICABLE, with 16 of them, exactly as before.
        if isinstance(r, dict):
            r['group'], r['group_mode'] = None, 'all_of'
            r['group_label'], r['group_intent'] = '', ''
            r['flags'] = list(r.get('flags') or []) + [
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']
        else:
            r.group, r.group_mode = None, 'all_of'
            r.group_label, r.group_intent = '', ''
            r.flags = list(r.flags or []) + [
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']
    return moved


'''

OLD_UNGROUP_CALL = """        _ungrouped = ungroup_non_alternatives(out['requirements'],"""
NEW_UNGROUP_CALL = """        _compliance = ungroup_compliance_lines(out['requirements'])
        if _compliance and verbose:
            print(f'  {len(_compliance)} compliance line(s) UNGROUPED -- a '
                  f'disclaimer is mandatory, never one of a menu:')
            for _cid, _cg in _compliance[:4]:
                print(f'     {_cid} was an option in {_cg!r}')
            print('    In a one_of group it was NOT_APPLICABLE whenever any '
                  'sibling passed,')
            print('    so it was never actually checked.')
        _ungrouped = ungroup_non_alternatives(out['requirements'],"""


def fix37a(s):
    """The definition. It lives in a DIFFERENT cell from the call site."""
    if 'def ungroup_compliance_lines' in s or 'def ungroup_non_alternatives' not in s:
        return None
    return s.replace('def ungroup_non_alternatives',
                     DISCLAIMER_FN + 'def ungroup_non_alternatives', 1)


def fix37b(s):
    """...and it must actually RUN. A function nobody calls measures nothing
    -- audit_group_intents shipped defined-but-uncalled for exactly this
    reason, and every behavioural test still passed."""
    if OLD_UNGROUP_CALL not in s or '_compliance = ungroup_compliance' in s:
        return None
    return s.replace(OLD_UNGROUP_CALL, NEW_UNGROUP_CALL, 1)


# ---------------------------------------------------------------------------
# Fix 40 -- OBLIGATION: does the brief DEMAND these, or OFFER them?
#
# The system classifies sections by KIND -- what the lines are: alternatives,
# claims, requirements, context. It has no notion of OBLIGATION -- whether the
# brief demands them or offers them. Those are orthogonal, and conflating them
# is what makes the pipeline Biostime-shaped:
#
#     alternatives + optional   pick one hook            (already right)
#     claims       + optional   a menu of talking points (Biostime)
#     claims       + required   mandatory safety copy    (pharma, finance)
#     requirements + required   must do                  (already right)
#
# The talking-point collapse was hardcoded to treat EVERY claims section as a
# menu, because this brief says "showcase", "creators CAN use", "we ENCOURAGE
# creators to bring their own style". A brief that says "you MUST state all of
# the following" would be collapsed the same way, and a creator could skip
# most of a mandatory disclosure list and still score well. That is the false
# PASS the whole design exists to prevent.
#
# So read it from the brief instead of assuming it. The document's own modal
# verbs decide, per claims section, with a document-level default behind them.
#
# WHEN THERE IS NO SIGNAL, the material is treated as a MENU and the brief is
# FLAGGED. That is the deliberate choice, not an oversight: the report already
# publishes the strict per-item reading beside the credited one
# (`literal_headline`), every bullet keeps its own verdict and row, and the
# flag tells a reviewer to set it explicitly. A silent guess in either
# direction would be worse than a loud one.
# ---------------------------------------------------------------------------
OBLIGATION_FN = '''# Does the brief DEMAND this material, or OFFER it?
#
# Kind and obligation are different questions. "Key Talking Points" is a
# claims section either way; whether the creator must cover them all is what
# these words answer. Deciding it from the document is what lets one pipeline
# serve a supplement brief that invites improvisation and a pharma brief that
# does not.
_OBLIGATION_REQUIRED = (
    r'\\bmust\\b', r'\\bmandatory\\b', r'\\brequired?\\b', r'\\brequirements?\\b',
    r'\\balways\\b', r'\\bnever\\b', r'\\bensure\\b', r'\\bmake sure\\b',
    r'\\bdo not\\b', r"\\bdon'?t\\b", r'\\bshall\\b', r'\\bneeds? to\\b',
    r'\\bhave to\\b', r'\\bobligatory\\b', r'\\bnon[- ]negotiable\\b',
    r'\\bevery (?:video|post|creator)\\b', r'\\ball of the following\\b',
    r'\\bwithout exception\\b', r'\\bcompulsory\\b',
)
_OBLIGATION_OPTIONAL = (
    r'\\bmay\\b', r'\\bcan use\\b', r'\\bcan\\b', r'\\bencourage\\w*\\b',
    r'\\bfeel free\\b', r'\\bsuggestions?\\b', r'\\bexamples?\\b', r'\\bideas?\\b',
    r'\\boptions?\\b', r'\\boptional\\b', r'\\blibrary\\b', r'\\bshowcase\\b',
    r'\\binspiration\\b', r'\\bpick (?:one|from|any)\\b', r'\\bchoose\\b',
    r'\\byour own\\b', r'\\bup to you\\b', r'\\bif you (?:like|want|prefer)\\b',
    r'\\bwe recommend\\b', r'\\bfree to\\b', r'\\bwhere relevant\\b',
    r'\\bas you see fit\\b', r'\\bany of the\\b',
)


def detect_obligation(text: str) -> tuple:
    """('required'|'optional'|None, evidence) from the document's own words.

    Counts modal cues rather than matching one phrase, because a brief says
    it many times and in many ways. Returns None when neither side wins, so
    the caller can say "the brief did not tell us" instead of guessing
    silently.
    """
    t = ' ' + ' '.join(str(text or '').split()).lower() + ' '
    req = [p for p in _OBLIGATION_REQUIRED if re.search(p, t)]
    opt = [p for p in _OBLIGATION_OPTIONAL if re.search(p, t)]
    nr, no = len(req), len(opt)
    if nr == no:
        return None, {'required_cues': nr, 'optional_cues': no}
    winner = 'required' if nr > no else 'optional'
    return winner, {'required_cues': nr, 'optional_cues': no,
                    'matched': [p.replace(chr(92) + 'b', '') for p in
                                (req if winner == 'required' else opt)][:6]}


def claims_obligation_of(sections: list, brief_text: str = '') -> dict:
    """Are the brief's CLAIMS a checklist or a menu? Read, never assumed.

    Per-section first, because a brief can offer talking points in one
    section and demand disclosures in another. The document-level reading is
    the fallback, and 'optional' is the last resort -- flagged, so a reviewer
    can correct it rather than discover it in a score.
    """
    secs = [s for s in (sections or [])
            if getattr(s, 'kind', (s or {}).get('kind') if isinstance(s, dict)
                       else None) == 'claims']
    parts = []
    for s in secs:
        head = getattr(s, 'heading', None) or (s.get('heading') if isinstance(s, dict) else '')
        lines = getattr(s, 'lines', None) or (s.get('lines') if isinstance(s, dict) else []) or []
        parts.append(str(head) + ' ' + ' '.join(str(x) for x in lines))
    sec_call, sec_ev = detect_obligation(' '.join(parts)) if parts else (None, {})
    doc_call, doc_ev = detect_obligation(brief_text)
    call = sec_call or doc_call
    return {'obligation': call or 'optional',
            'determined': bool(call),
            'from': ('claims section' if sec_call else
                     'whole brief' if doc_call else 'DEFAULT (undetermined)'),
            'section_evidence': sec_ev, 'document_evidence': doc_ev}


'''

OLD_COMPILED_KEY = """        'approved_claims': approved_claims,"""
NEW_COMPILED_KEY = """        'approved_claims': approved_claims,
        # Does the brief DEMAND its claims, or OFFER them? Phase 7 scores a
        # menu as coverage and a checklist item by item, and getting that
        # from the document is what stops the pipeline being shaped by the
        # first brief it ever saw.
        'claims_obligation': claims_obligation_of(sections, brief_text),"""


def fix40a(s):
    if 'def detect_obligation' in s:
        return None
    if 'def extract_approved_claims' not in s:
        return None
    return s.replace('def extract_approved_claims',
                     OBLIGATION_FN + 'def extract_approved_claims', 1)


def fix40b(s):
    if "'claims_obligation':" in s or OLD_COMPILED_KEY not in s:
        return None
    return s.replace(OLD_COMPILED_KEY, NEW_COMPILED_KEY, 1)


# ---------------------------------------------------------------------------
# Fix 41 -- a compliance line is not an FDA line
#
# Fix 37 detected the disclaimer with wording from ONE vertical: "evaluated by
# the Food and Drug Administration", "diagnose, treat, cure or prevent". That
# restored the check for US supplements and for nothing else. A skincare,
# finance, alcohol or gambling brief has a different mandatory line, and it
# would land right back inside whatever menu it sits under and be excused.
#
# Two signals now, and either is enough:
#   WORDING   the regulated phrases of the verticals UGC actually runs in,
#             plus the disclosure lines every sponsored post needs
#   SHAPE     a footnote marker, an explicit "Disclaimer:" label, or a line
#             sitting in a section the brief itself headed Legal / Mandatory /
#             Compliance -- which is structure, and travels across verticals
#             better than any word list can.
# ---------------------------------------------------------------------------
OLD_DISC_RE = """_DISCLAIMER_RE = re.compile(
    r'(have\\s+not\\s+been\\s+evaluated\\s+by\\s+the\\s+(food\\s+and\\s+drug|fda)'
    r'|not\\s+intended\\s+to\\s+(diagnose|treat|cure|prevent)'
    r'|these\\s+statements\\s+have\\s+not\\s+been)', re.I)"""

NEW_DISC_RE = """# Regulated wording, across the verticals UGC actually runs in. A word list
# alone can never be complete, which is why _DISCLAIMER_SHAPE exists beside it.
_DISCLAIMER_RE = re.compile(
    r'('
    # health / supplements
    r'have\\s+not\\s+been\\s+evaluated\\s+by\\s+the\\s+(food\\s+and\\s+drug|fda)'
    r'|not\\s+intended\\s+to\\s+(diagnose|treat|cure|prevent)'
    r'|these\\s+statements\\s+have\\s+not\\s+been'
    r'|not\\s+(medical|health)\\s+advice|consult\\s+(your|a)\\s+'
    r'(doctor|physician|healthcare|gp|pharmacist)'
    r'|individual\\s+results|results\\s+(may|can)\\s+vary'
    r'|not\\s+a\\s+substitute\\s+for'
    # finance
    r'|past\\s+performance|capital\\s+at\\s+risk|not\\s+(financial|investment)\\s+advice'
    r'|investments?\\s+can\\s+go\\s+down|your\\s+capital\\s+is\\s+at\\s+risk'
    # age-gated / regulated goods
    r'|drink\\s+responsibly|gamble\\s+responsibly|please\\s+gamble'
    r'|\\b(18|21)\\s*\\+|over\\s+(18|21)s?\\s+only'
    # paid-partnership disclosure -- mandatory for UGC in every vertical
    r'|#\\s?ad\\b|#\\s?sponsored\\b|paid\\s+partnership|paid\\s+promotion'
    r'|sponsored\\s+by|gifted\\s+by|in\\s+partnership\\s+with'
    # generic
    r'|terms\\s+(and|&)\\s+conditions\\s+apply|t\\s?&\\s?cs?\\s+apply'
    r'|always\\s+read\\s+the\\s+label|use\\s+only\\s+as\\s+directed'
    r')', re.I)

# SHAPE, not wording. A footnote marker or an explicit label says "this is
# boilerplate the brand must carry" in any vertical and any language of
# business, and it keeps working when the word list does not.
_DISCLAIMER_SHAPE = re.compile(
    r'^\\s*(\\*+|\\u2020|\\u2021)\\s*\\S'
    r'|^\\s*(disclaimer|legal|mandatory|compliance|disclosure)\\s*[:\\-\\u2013]',
    re.I)"""

OLD_DISC_TEST = """        if not _DISCLAIMER_RE.search(txt):
            continue"""
NEW_DISC_TEST = """        _sec = str(_req_field(r, 'group_label') or '')
        _in_legal_section = bool(re.search(
            r'\\b(legal|disclaimer|compliance|mandator\\w+|disclosure|'
            r'fine\\s*print|small\\s*print)\\b', _sec, re.I))
        if not (_DISCLAIMER_RE.search(txt)
                or _DISCLAIMER_SHAPE.search(txt.lstrip())
                or _in_legal_section):
            continue"""


def fix41(s):
    if '_DISCLAIMER_SHAPE' in s or OLD_DISC_RE not in s:
        return None
    return s.replace(OLD_DISC_RE, NEW_DISC_RE, 1).replace(
        OLD_DISC_TEST, NEW_DISC_TEST, 1)


# ---------------------------------------------------------------------------
# Fix 43 -- ungroup_compliance_lines mutated only the DICT shape
#
# It ran, it matched, it appended to `moved` -- and on the compile path a
# requirement is a DATACLASS, so the dict-only branch changed nothing. The
# disclaimer stayed inside the CTA group on all seven videos of the
# 1790103374 batch, NOT_APPLICABLE exactly as before, while the function
# reported having moved it.
#
# ungroup_non_alternatives, three lines below it, has always handled both
# shapes. I wrote the sibling and did not copy the idiom that exists to stop
# precisely this.
# ---------------------------------------------------------------------------
OLD_DICT_ONLY = """        if isinstance(r, dict):
            r['group'] = None
            r['group_mode'] = 'all_of'
            r['group_label'] = ''
            r['group_intent'] = ''
            r['flags'] = list(r.get('flags') or []) + [
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']"""

NEW_BOTH_SHAPES = """        # BOTH SHAPES: a dataclass on the compile path, a dict after
        # to_dict(). The dict-only version changed nothing where it mattered.
        if isinstance(r, dict):
            r['group'], r['group_mode'] = None, 'all_of'
            r['group_label'], r['group_intent'] = '', ''
            r['flags'] = list(r.get('flags') or []) + [
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']
        else:
            r.group, r.group_mode = None, 'all_of'
            r.group_label, r.group_intent = '', ''
            r.flags = list(r.flags or []) + [
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']"""


def fix43(s):
    if OLD_DICT_ONLY not in s:
        return None
    return s.replace(OLD_DICT_ONLY, NEW_BOTH_SHAPES, 1)


# ---------------------------------------------------------------------------
# Fix 44 -- audit_group_intents had the same dict-only shape
#
# Found by the check written FOR fix 43, on its first run. Today it is a false
# alarm: both call sites pass dicts (`compiled['requirements']` is
# [r.to_dict() ...], and the consensus path does `r['ordinal'] = i` two lines
# above its call, which only works on a dict). So the repair does happen.
#
# It is fixed anyway rather than allowlisted, for two reasons. A check that
# reports a true-but-harmless finding gets ignored, and then it is no longer a
# check. And "this is only ever called with dicts" is a fact about today's
# call sites, not a property of the function -- which is exactly the sentence
# that was true of ungroup_compliance_lines right up until it silently did
# nothing on seven videos.
# ---------------------------------------------------------------------------
OLD_AGI = """        for m in members:
            if isinstance(m, dict):
                m.setdefault('flags', [])"""

NEW_AGI = """        for m in members:
            # BOTH SHAPES. A dict today at every call site -- and that is a
            # fact about the callers, not about this function. See fix 43.
            if not isinstance(m, dict):
                m.flags = list(getattr(m, 'flags', None) or [])
                if 'GROUP_INTENT_SUBJECT_FREE' not in m.flags:
                    m.flags.append('GROUP_INTENT_SUBJECT_FREE')
                if _opts:
                    m.group_intent_original = intent
                    m.group_intent = _repaired[:1200]
                    if 'GROUP_INTENT_REPAIRED' not in m.flags:
                        m.flags.append('GROUP_INTENT_REPAIRED')
                continue
            if isinstance(m, dict):
                m.setdefault('flags', [])"""


def fix44(s):
    if OLD_AGI not in s:
        return None
    return s.replace(OLD_AGI, NEW_AGI, 1)


# ---------------------------------------------------------------------------
# Fix 45 -- say it as if/else, so the invariant is in the code
#
# Fix 44 handled the object shape with an early `continue`. Correct, and
# invisible to a reader skimming for "does this handle both?" -- and to the
# check, which still reported a dict-only write.
#
# A check that a correct change cannot satisfy is a check that gets switched
# off. Saying it as if/else costs nothing, makes both branches visible in one
# glance, and lets the guard stay strict.
# ---------------------------------------------------------------------------
OLD_AGI_CONT = """                continue
            if isinstance(m, dict):
                m.setdefault('flags', [])"""

NEW_AGI_ELSE = """            else:
                m.setdefault('flags', [])"""


def fix45(s):
    if OLD_AGI_CONT not in s:
        return None
    return s.replace(OLD_AGI_CONT, NEW_AGI_ELSE, 1)


# ---------------------------------------------------------------------------
# Fix 46 -- the section classifier only knew THIS brief's vocabulary
#
# SECTION_KIND_CUES decides whether a section is a menu, a set of claims, a
# set of asks, or background. Every cue in it came from briefs we had seen.
# A section headed "Key Messages", "Mandatories", "Reasons to Believe" or
# "Do's and Don'ts" matched NOTHING and fell through to the fallback kind --
# and `requirements` being the fallback is exactly the defect that made scores
# swing 5->8->3 units on identical input (fix 14, superseded by 15).
#
# A brief we have not seen is the normal case from here on, so the cue lists
# are widened to the vocabulary marketing briefs actually use. This does not
# make the classifier complete -- no word list is -- which is why obligation
# (fix 40) is read separately and why the fallback still exists.
#
# ORDER STILL MATTERS: the tuple is tried in sequence, so 'alternatives'
# before 'claims' before 'requirements' is what makes "CTA Options" a menu
# rather than a list of asks.
# ---------------------------------------------------------------------------
CUE_ADDITIONS = {
    'alternatives': (r"\bpick[- ]?one\b", r"\bany of\b", r"\bmenu\b",
                     r"\bswipe file\b", r"\bexample scripts?\b",
                     r"\bstory ?boards?\b", r"\breference\b", r"\bmood\b",
                     r"\bstarting points?\b", r"\bprompts?\b",
                     r"\btreatments?\b", r"\bexecutions?\b",
                     r"\broutes?\b", r"\bterritor(?:y|ies)\b"),
    'claims': (r"\bkey messages?\b", r"\bmessaging\b", r"\bmessage house\b",
               r"\bproof ?points?\b", r"\breasons? to believe\b", r"\bRTBs?\b",
               r"\bpillars?\b", r"\bpropositions?\b", r"\bvalue props?\b",
               r"\bselling points?\b", r"\bproduct truths?\b",
               r"\bsubstantiation\b", r"\battributes?\b", r"\bspecs? sheet\b"),
    'requirements': (r"\bmandator(?:y|ies)\b", r"\bnon[- ]negotiables?\b",
                     r"\bmust include\b", r"\brestrictions?\b",
                     r"\bprohibit\w*\b", r"\bavoid\b", r"\bnever\b",
                     r"\blegal\b", r"\bdisclaimers?\b", r"\bdisclosures?\b",
                     r"\bobligations?\b", r"\bstandards?\b", r"\bpolic(?:y|ies)\b",
                     r"\bsafety\b", r"\bregulator\w*\b", r"\bapprovals?\b"),
    'context': (r"\bobjectives?\b", r"\bstrategy\b", r"\binsight\b",
                r"\bwho we are\b", r"\bproduct\b", r"\bcontext\b",
                r"\bchallenge\b", r"\bopportunit(?:y|ies)\b",
                r"\bpersona\w*\b", r"\bdemograph\w*\b", r"\bmarket\b",
                r"\btimeline\b", r"\bdeadlines?\b", r"\bbudget\b"),
}


def fix46(s):
    if 'reasons? to believe' in s or 'SECTION_KIND_CUES = (' not in s:
        return None
    out = s
    for kind, extra in CUE_ADDITIONS.items():
        # Append to that kind's tuple, immediately before its closing `)),`.
        m = re.search(r"\('" + kind + r"',\s*\((?:.|\n)*?\)\),", out)
        if not m:
            return None
        block = m.group(0)
        add = ',\n'.join(f"                      r'{p}'" for p in extra)
        new = block[:block.rfind('))')] + ',\n' + add + '))' + block[block.rfind('))') + 2:]
        out = out.replace(block, new, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 47 -- a word list cannot settle "Prohibited Claims"
#
# Fix 46 widened the cues and every one of 24 unseen headings then classified.
# Two classified WRONG, and adding more words could not have fixed either:
#
#     "Prohibited Claims"   -> claims       (matched `claims` first)
#     "Campaign Objectives" -> alternatives (matched `campaign` first)
#
# Both headings contain cues for two kinds, and `classify_section` returns the
# FIRST tuple that matches, so precedence decides -- not strength of signal. A
# heading that forbids something is a rule no matter what noun follows, and a
# heading about goals is background no matter what noun precedes.
#
# So: a small OVERRIDE pass first, for the markers that settle it outright.
# Deliberately small. Every entry is a word that changes what a section IS
# rather than what it is about, and the ordinary cue list still does the rest.
# ---------------------------------------------------------------------------
OVERRIDE_BLOCK = '''# Markers that settle a heading OUTRIGHT, checked before the ordinary cues.
#
# `classify_section` returns the first matching tuple, so a heading carrying
# cues for two kinds is decided by tuple order rather than by which signal is
# stronger. "Prohibited Claims" is a restriction, not a claims list;
# "Campaign Objectives" is background, not a menu of campaigns. No amount of
# extra vocabulary fixes that -- the words are all present and correct, and
# the wrong one wins on position.
#
# Small on purpose: each entry names something that changes what a section IS,
# not what it is about.
SECTION_KIND_OVERRIDES = (
    ('requirements', (r'\\bprohibit\\w*\\b', r'\\bforbidden\\b', r'\\bbanned\\b',
                      r'\\bdisallow\\w*\\b', r'\\brestrict\\w*\\b',
                      r'\\bmust not\\b', r'\\bdo not\\b', r"\\bdon'?ts?\\b",
                      r'\\bnon[- ]negotiables?\\b', r'\\bmandator\\w*\\b',
                      r'\\bcompliance\\b', r'\\blegal\\b', r'\\bdisclaimers?\\b',
                      r'\\bdisclosures?\\b', r'\\bsafety\\b')),
    ('context',      (r'\\bobjectives?\\b', r'\\bgoals?\\b', r'\\bbackground\\b',
                      r'\\boverview\\b', r'\\bpurpose\\b', r'\\btimelines?\\b',
                      r'\\bdeadlines?\\b', r'\\bbudgets?\\b', r'\\bpersona\\w*\\b',
                      r'\\bstrategy\\b', r'\\binsights?\\b')),
)


'''

OLD_CLASSIFY = """def classify_section(heading: str, lines: list = None) -> str:
    \"\"\"Heading first; when it says nothing, decide from whether the lines are imperative.\"\"\"
    h = heading or ''
    for kind, pats in SECTION_KIND_CUES:"""

NEW_CLASSIFY = """def classify_section(heading: str, lines: list = None) -> str:
    \"\"\"Heading first; when it says nothing, decide from whether the lines are imperative.

    OVERRIDES run before the ordinary cues. A heading can carry cues for two
    kinds -- "Prohibited Claims", "Campaign Objectives" -- and the plain loop
    resolves that by tuple order, which is position, not evidence.
    \"\"\"
    h = heading or ''
    for kind, pats in SECTION_KIND_OVERRIDES:
        if _has(pats, h):
            return kind
    for kind, pats in SECTION_KIND_CUES:"""


def fix47(s):
    if 'SECTION_KIND_OVERRIDES' in s or OLD_CLASSIFY not in s:
        return None
    out = s.replace('def classify_section', OVERRIDE_BLOCK + 'def classify_section', 1)
    return out.replace(OLD_CLASSIFY.replace('def classify_section', 'def classify_section', 1),
                       NEW_CLASSIFY, 1)


# ---------------------------------------------------------------------------
# Fix 48 -- the brief was pinned 102 cells deep
#
# BRIEF_SOURCE lived inside §48, and pointing the notebook at a different
# campaign meant finding it there. It cost a whole batch run: five videos for
# a NEW brief were audited against the OLD one, came back OFF_BRIEF on all
# five -- correctly, and uselessly -- and the only clue was a brief_hash in a
# header that looks identical to every other run.
#
# For a system meant to serve many briefs, WHICH BRIEF is the single most
# important parameter it takes, and it belongs beside VISION_PROVIDER at the
# top, not buried beside the code that compiles it.
#
# §0.3 becomes the one source of truth. §48 still carries a fallback so the
# cell runs standalone in a notebook where §0.3 was skipped -- but when §0.3
# has set it, §0.3 wins.
# ---------------------------------------------------------------------------
BRIEF_AT_TOP = """
# ---- WHICH BRIEF -----------------------------------------------------------
# THE parameter to change when pointing this notebook at another campaign.
#
# It used to live in §48, a hundred cells down. Five videos for a new brief
# were then audited against the old one and every single one came back
# OFF_BRIEF -- the right answer to the wrong question, and the only visible
# clue was a brief hash that looks like every other brief hash.
#
# A Google Doc URL (shared "anyone with the link can view"), a local path, or
# raw text. §48 reads THIS unless it is unset.
BRIEF_SOURCE = 'https://docs.google.com/document/d/17GGNRlfrk_pD5ucRAPssyu2_oiNQ9O75cfatPxbX7Vo/edit'
"""

OLD_PATHS_TAIL = """for name, d in DIRS.items():
    print(f'{name:10s}  {d}')"""

NEW_PATHS_TAIL = OLD_PATHS_TAIL + """
print(f'brief       {BRIEF_SOURCE[:72]}')"""


def fix48a(s):
    """Declare it in §0.3, next to VISION_PROVIDER."""
    if 'WHICH BRIEF' in s or 'VISION_PROVIDER = ' not in s:
        return None
    if OLD_PATHS_TAIL not in s:
        return None
    out = s.replace("WORK = Path('/content/work')",
                    BRIEF_AT_TOP.strip('\n') + "\n\nWORK = Path('/content/work')", 1)
    return out.replace(OLD_PATHS_TAIL, NEW_PATHS_TAIL, 1)


def fix48b(s):
    """§48 defers to it, but still runs standalone."""
    m = re.search(r"^BRIEF_SOURCE = '([^']*)'(.*)$", s, re.M)
    if not m or 'globals().get(' in (m.group(0) or ''):
        return None
    if 'WHICH BRIEF' in s:          # that is §0.3, not §48
        return None
    return s.replace(
        m.group(0),
        "# SET IN §0.3, at the top of the notebook. This is only the fallback\n"
        "# for a kernel where §0.3 was never run -- §0.3 wins when it has.\n"
        f"BRIEF_SOURCE = globals().get('BRIEF_SOURCE') or '{m.group(1)}'",
        1)


# ---------------------------------------------------------------------------
# Fix 49 -- a feature she SHOWS is a feature she communicated
#
# Fix 16 hardcoded every claim requirement to evidence_mode 'speech_or_text'.
# That mode already covers OCR, so the only channel it excludes is VISUAL --
# the VLM's description of what is on screen.
#
# On the pill-organiser brief that is the wrong exclusion. Of ten talking
# points, five are things you SEE: "Extra-large size (7x9) with 21 spacious
# compartments", "Color-coded rows", "Rainbow-colored lids", "clear weekly
# layout". A creator who holds the tray to camera and fans the lids HAS
# communicated colour-coding. Measured on fleetwoodrose: the evidence carries
# "multi-colored pill container organizer featuring pastel green, blue" at
# 0:48 and the requirement FAILed, because a visual record could not be
# offered for it.
#
# I tried infer_evidence_mode first -- it is deterministic and already exists.
# It returns None for all ten of this brief's bullets: it reads imperative
# requirement sentences ("Show the product..."), not bare feature nouns. So it
# cannot decide this, and guessing per-claim with a word list would be the
# "Prohibited Claims" mistake again.
#
# 'any' instead, and the risk is named rather than hidden: a claim like
# "BPA-free materials" cannot be shown, so a visual must not satisfy it. That
# is L3's job and it is the layer that already refuses this -- it declined to
# credit "melatonin-free" from an OCR reading "MELATONIN". can_fail_on is also
# STRICTER under 'any': a FAIL then needs every modality healthy.
#
# Reversible in one line, because which briefs this suits is a judgement:
# CLAIM_EVIDENCE_MODE = 'speech_or_text' restores the old behaviour.
# ---------------------------------------------------------------------------
OLD_CLAIM_MODE = """            'polarity': 'required', 'evidence_mode': 'speech_or_text',"""
NEW_CLAIM_MODE = """            # 'any' -- she may SAY the feature or SHOW it. See fix 49;
            # set CLAIM_EVIDENCE_MODE to 'speech_or_text' to revert.
            'polarity': 'required',
            'evidence_mode': globals().get('CLAIM_EVIDENCE_MODE', 'any'),"""

CLAIM_MODE_CONST = """# A product feature can be communicated by SAYING it or by SHOWING it.
# 'speech_or_text' already covers OCR, so the only channel it excluded was the
# VLM's view of the screen -- and on a brief whose features are colour-coded
# rows and a 21-compartment tray, that is the channel that carries them.
CLAIM_EVIDENCE_MODE = 'any'


"""


def fix49(s):
    if 'CLAIM_EVIDENCE_MODE' in s or OLD_CLAIM_MODE not in s:
        return None
    out = s.replace('def requirements_from_claims',
                    CLAIM_MODE_CONST + 'def requirements_from_claims', 1)
    return out.replace(OLD_CLAIM_MODE, NEW_CLAIM_MODE, 1)


# ---------------------------------------------------------------------------
# Fix 50 -- WHICH of the brief's named angles, and how much of each
#
# The brief names a small number of creative angles -- this one has two, "No
# judgement zone" and "Health journey" -- and the useful question about a
# video is which one it is, and how much of each.
#
# `nearest_brief_concept` could not answer it. _brief_concepts returns GROUP
# LABELS, so the answer came back "Creative Concepts": the heading the angles
# sit under, not the angles. And a single nearest match cannot express a video
# that is mostly one and partly the other.
#
# So: name the angles, and ask for a percentage split across them.
#
# THIS IS A DESCRIPTION, NOT A SCORE. It lives in the creative-angle block,
# which §76 never reads, and it carries the same disclaimer the angle does.
# The design rule is that no model writes a number that enters the score --
# not that no model may ever express a proportion. Keeping the two apart is
# what makes that rule enforceable rather than decorative.
# ---------------------------------------------------------------------------
NAMED_ANGLES_FN = '''# Group labels that mean "this group holds the creative angles".
_ANGLE_GROUP_RE = re.compile(
    r'\\b(concepts?|angles?|formats?|territor(?:y|ies)|themes?|creative|'
    r'frameworks?|treatments?|executions?|routes?|campaigns?)\\b', re.I)


def named_brief_angles(compiled: dict, limit: int = 8) -> list:
    """The brief's NAMED creative angles -- the options, not their heading.

    _brief_concepts returns group LABELS, which is the right answer for "which
    section is this nearest to" and the wrong one for "which of the two angles
    is this". A brief carries two or three angles by name -- "No judgement
    zone", "Health journey" -- and that is what a reader wants attributed.

    Only groups whose label reads like a set of creative angles are used, so a
    ten-option hook list does not become ten angles.
    """
    groups = {}
    for r in (compiled or {}).get('requirements') or []:
        g = r.get('group')
        if not g:
            continue
        d = groups.setdefault(g, {'label': str(r.get('group_label') or g),
                                  'members': []})
        lbl = str(r.get('label') or '').strip()
        if lbl and lbl not in d['members']:
            d['members'].append(lbl)
    named = []
    for g, d in groups.items():
        if not _ANGLE_GROUP_RE.search(f"{d['label']} {g}"):
            continue
        for m in d['members']:
            if m not in named:
                named.append(m)
    return named[:limit]


'''

OLD_ANGLE_SCHEMA = """ "nearest_brief_concept": "the concept name, or null if none is close",
 "anticipated_by_brief": true,
 "evidence_ids": ["..."]}\""""

NEW_ANGLE_SCHEMA = """ "nearest_brief_concept": "the concept name, or null if none is close",
 "anticipated_by_brief": true,
 "concept_fit": [{"angle": "one of the NAMED ANGLES listed below",
                  "percent": 70,
                  "why": "one sentence, grounded in the evidence"}],
 "evidence_ids": ["..."]}

3. HOW MUCH OF EACH NAMED ANGLE? The brief names a small number of creative
   angles. Give a PERCENTAGE SPLIT saying how much of THIS video belongs to
   each. Rules:
     - the percentages must sum to 100
     - use ONLY the angle names given under NAMED ANGLES; invent none
     - a video is usually mostly one angle and partly another -- say so
     - if part of it belongs to no listed angle, put that share under
       "none of the listed angles"
   This is a DESCRIPTION of what she made. It is never a score and never
   counts for or against her.\""""


def fix50a(s):
    if 'def named_brief_angles' in s or 'def _brief_concepts' not in s:
        return None
    return s.replace('def _brief_concepts', NAMED_ANGLES_FN + 'def _brief_concepts', 1)


def fix50b(s):
    if OLD_ANGLE_SCHEMA not in s:
        return None
    return s.replace(OLD_ANGLE_SCHEMA, NEW_ANGLE_SCHEMA, 1)


# ---- and the runtime half: show the angles, then check what comes back -----
OLD_ANGLE_LINES = """    lines += ['', f'Allowed angle values: {", ".join(CREATIVE_ANGLES)}']"""
NEW_ANGLE_LINES = """    lines += ['', f'Allowed angle values: {", ".join(CREATIVE_ANGLES)}']
    _named = named_brief_angles(compiled)
    out['named_angles'] = list(_named)
    if _named:
        lines += ['', 'NAMED ANGLES (use these exact names in concept_fit):']
        lines += [f'  - {a}' for a in _named]
        lines += [f'  - {NO_ANGLE_LABEL}']
    else:
        lines += ['', 'The brief names no creative angles; return an empty '
                      'concept_fit.']"""

OLD_ANGLE_OUT = """        evidence_ids=ids)"""
NEW_ANGLE_OUT = """        concept_fit=_clean_concept_fit(obj.get('concept_fit'), _named,
                                       out['flags']),
        evidence_ids=ids)"""

CONCEPT_FIT_FN = '''NO_ANGLE_LABEL = 'none of the listed angles'


def _clean_concept_fit(raw, named: list, flags: list) -> list:
    """[{angle, percent, why}] summing to 100, over the brief's OWN angles.

    A percentage from a model is still a model's opinion, so it is checked the
    way every other model output here is: against a CLOSED list, with the
    repair recorded rather than silently applied.

      - an angle the brief never named is DROPPED (the model invented it)
      - percentages are coerced, clamped, and renormalised to 100
      - a split that did not sum is flagged, not quietly fixed

    It never reaches Phase 7. This describes what she made; it is not a score
    and nothing downstream may treat it as one.
    """
    allowed = list(named) + [NO_ANGLE_LABEL]
    rows, dropped = [], []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get('angle') or item.get('concept') or '').strip()
        match = next((a for a in allowed if a.lower() == name.lower()), None)
        if match is None:
            # a near miss on wording is still the model's own label
            match = next((a for a in allowed
                          if name and (name.lower() in a.lower()
                                       or a.lower() in name.lower())), None)
        if match is None:
            if name:
                dropped.append(name[:40])
            continue
        try:
            pct = float(item.get('percent'))
        except (TypeError, ValueError):
            continue
        rows.append({'angle': match, 'percent': max(0.0, min(100.0, pct)),
                     'why': str(item.get('why') or '')[:200]})
    if dropped:
        flags.append(f'CONCEPT_FIT_NOT_IN_BRIEF:{",".join(dropped[:3])}')
    if not rows:
        return []
    # merge duplicates, then renormalise
    merged = {}
    for r in rows:
        m = merged.setdefault(r['angle'], {'angle': r['angle'], 'percent': 0.0,
                                           'why': r['why']})
        m['percent'] += r['percent']
        if not m['why']:
            m['why'] = r['why']
    rows = list(merged.values())
    total = sum(r['percent'] for r in rows)
    if total <= 0:
        return []
    if abs(total - 100.0) > 2.0:
        flags.append(f'CONCEPT_FIT_RENORMALISED:{total:.0f}->100')
    for r in rows:
        r['percent'] = round(100.0 * r['percent'] / total, 1)
    rows.sort(key=lambda r: -r['percent'])
    return rows


'''


def fix50c(s):
    if '_clean_concept_fit' in s or OLD_ANGLE_LINES not in s:
        return None
    out = s.replace('def _brief_concepts', CONCEPT_FIT_FN + 'def _brief_concepts', 1)
    out = out.replace(OLD_ANGLE_LINES, NEW_ANGLE_LINES, 1)
    return out.replace(OLD_ANGLE_OUT, NEW_ANGLE_OUT, 1)


def fix50d(s):
    """The default, so a failed call still has the key."""
    old = "'brief_concepts': concepts, 'evidence_ids': [], 'flags': [],"
    if 'concept_fit' in s and "'concept_fit': []" in s:
        return None
    if old not in s:
        return None
    return s.replace(old, "'brief_concepts': concepts, 'named_angles': [],\n"
                          "           'concept_fit': [], 'evidence_ids': [], "
                          "'flags': [],", 1)


# ---------------------------------------------------------------------------
# Fix 51 -- the model was told to stop before it was told what to do
#
# concept_fit came back empty on a live run. The plumbing was fine; the PROMPT
# was built wrong, by me, and reading it back makes it obvious:
#
#     "Answer in two steps"          <- there are three
#     1. ...  2. ...
#     "Return ONLY this JSON"        <- stop instruction
#     {... "concept_fit": [...]}
#     3. HOW MUCH OF EACH ...        <- AFTER the stop instruction
#
# The schema even said "one of the NAMED ANGLES listed below", pointing at
# text that comes after the JSON it is describing. A model that emits the JSON
# and stops has followed the prompt exactly as written.
#
# Steps first, schema last, and the count fixed. Plus an explicit line that
# concept_fit is required when NAMED ANGLES are present -- an optional-looking
# key in a long schema is the one that gets dropped.
# ---------------------------------------------------------------------------
OLD_ANGLE_TAIL = """Use ONLY the evidence given. You cannot see the video. Cite evidence ids from
the list, or none.

Return ONLY this JSON, no prose and no code fence:
{"angle": "one of the allowed values",
 "summary": "one sentence describing what the creator actually made",
 "reason": "one sentence, grounded in the evidence",
 "nearest_brief_concept": "the concept name, or null if none is close",
 "anticipated_by_brief": true,
 "concept_fit": [{"angle": "one of the NAMED ANGLES listed below",
                  "percent": 70,
                  "why": "one sentence, grounded in the evidence"}],
 "evidence_ids": ["..."]}

3. HOW MUCH OF EACH NAMED ANGLE? The brief names a small number of creative
   angles. Give a PERCENTAGE SPLIT saying how much of THIS video belongs to
   each. Rules:
     - the percentages must sum to 100
     - use ONLY the angle names given under NAMED ANGLES; invent none
     - a video is usually mostly one angle and partly another -- say so
     - if part of it belongs to no listed angle, put that share under
       "none of the listed angles"
   This is a DESCRIPTION of what she made. It is never a score and never
   counts for or against her.\""""

NEW_ANGLE_TAIL = """3. HOW MUCH OF EACH NAMED ANGLE? The input lists NAMED ANGLES -- the two or
   three creative angles this brief actually names. Give a PERCENTAGE SPLIT
   saying how much of THIS video belongs to each:
     - the percentages MUST sum to 100
     - use ONLY the names under NAMED ANGLES, spelled exactly; invent none
     - a video is usually MOSTLY one angle and PARTLY another -- say so,
       rather than putting 100 on one and nothing on the rest
     - for any share belonging to no listed angle, use the exact name
       "none of the listed angles"
   This DESCRIBES what she made. It is never a score, and it counts neither
   for nor against her.

Use ONLY the evidence given. You cannot see the video. Cite evidence ids from
the list, or none.

Return ONLY this JSON, no prose and no code fence. EVERY key below is
REQUIRED -- including concept_fit, which must not be empty whenever NAMED
ANGLES appear in the input:
{"angle": "one of the allowed values",
 "summary": "one sentence describing what the creator actually made",
 "reason": "one sentence, grounded in the evidence",
 "nearest_brief_concept": "the concept name, or null if none is close",
 "anticipated_by_brief": true,
 "concept_fit": [{"angle": "exactly one of the NAMED ANGLES",
                  "percent": 70,
                  "why": "one sentence, grounded in the evidence"},
                 {"angle": "another NAMED ANGLE",
                  "percent": 30,
                  "why": "one sentence, grounded in the evidence"}],
 "evidence_ids": ["..."]}\""""

OLD_TWO_STEPS = """offered. Answer in two steps, and do not let the second change the first."""
NEW_TWO_STEPS = """offered. Answer in THREE steps, and do not let a later step change an
earlier one."""


def fix51(s):
    if 'Answer in THREE steps' in s or OLD_ANGLE_TAIL not in s:
        return None
    return s.replace(OLD_TWO_STEPS, NEW_TWO_STEPS, 1).replace(
        OLD_ANGLE_TAIL, NEW_ANGLE_TAIL, 1)


# ---------------------------------------------------------------------------
# Fix 52 -- an empty split has TWO causes and they need opposite fixes
#
# concept_fit can be empty because the model ignored the ask, or because the
# brief named no angles to ask about -- in which case empty is CORRECT. Those
# look identical in a report and call for opposite work: fix the prompt, or
# fix the brief's headings.
#
# Same lesson as the key diagnosis in fix 35: an outcome with two causes must
# say which one it had.
# ---------------------------------------------------------------------------
OLD_NAMED_ELSE = """    else:
        lines += ['', 'The brief names no creative angles; return an empty '
                      'concept_fit.']"""
NEW_NAMED_ELSE = """    else:
        # Say so on the artifact. An empty split then means "there was
        # nothing to attribute", not "the model declined" -- and the fix is to
        # the BRIEF's structure, not to the prompt.
        out['flags'].append('NO_NAMED_ANGLES_IN_BRIEF')
        lines += ['', 'The brief names no creative angles; return an empty '
                      'concept_fit.']"""

OLD_FIT_CALL = """        concept_fit=_clean_concept_fit(obj.get('concept_fit'), _named,
                                       out['flags']),"""
NEW_FIT_CALL = """        concept_fit=_clean_concept_fit(obj.get('concept_fit'), _named,
                                       out['flags']),
        concept_fit_missing=bool(_named) and not (obj.get('concept_fit') or []),"""


def fix52(s):
    if 'NO_NAMED_ANGLES_IN_BRIEF' in s or OLD_NAMED_ELSE not in s:
        return None
    out = s.replace(OLD_NAMED_ELSE, NEW_NAMED_ELSE, 1)
    if OLD_FIT_CALL in out:
        out = out.replace(OLD_FIT_CALL, NEW_FIT_CALL, 1)
    return out if out != s else None


# ---------------------------------------------------------------------------
# Fix 53 -- a TIMEOUT is the most transient failure there is, and neither
#           classifier recognised one
#
# Measured on a live run: 16 frames, 0.5 MB, ~2048 tokens -- a small request --
# and:
#
#     attempts  : 1
#     inference : 180.15s
#     gemini-3.5-flash: ReadTimeout: The read operation timed out
#
# ONE attempt on a stage whose whole design is a retry ladder. Because:
#
#     transient = any(k in s for k in ('503','UNAVAILABLE','500',
#                                      'INTERNAL','DEADLINE'))
#
# A client-side httpx timeout says "The read operation timed out". It matches
# none of those. 'DEADLINE' catches the SERVER's gRPC DEADLINE_EXCEEDED and
# misses the client's own clock entirely. So the failure was classified as a
# hard error: no retry, no next model, stage dead.
#
# A timeout is the definitional transient failure -- the server did not refuse,
# it just did not answer yet. Both classifiers now say so. The wall-clock
# budget (LADDER_BUDGET_S) still bounds the total, so this buys retries
# without buying an unbounded wait.
# ---------------------------------------------------------------------------
OLD_TRANSIENT_VISION = """transient = any(k in s for k in ('503', 'UNAVAILABLE', '500',
                                                     'INTERNAL', 'DEADLINE'))"""
NEW_TRANSIENT_VISION = """transient = any(k in s for k in ('503', 'UNAVAILABLE', '500',
                                                     'INTERNAL', 'DEADLINE',
                                                     # the CLIENT's own clock:
                                                     # httpx says "The read
                                                     # operation timed out",
                                                     # which matched nothing
                                                     # above and killed the
                                                     # stage on attempt 1
                                                     'timed out', 'Timeout',
                                                     'timeout'))"""

OLD_TRANSIENT_TEXT = """        return any(k in s for k in ('503', 'UNAVAILABLE', '500', 'INTERNAL',
                                    '504', 'DEADLINE_EXCEEDED', 'overloaded'))"""
NEW_TRANSIENT_TEXT = """        # 'DEADLINE_EXCEEDED' is the SERVER's deadline. A client-side
        # timeout reads "The read operation timed out" and matched none of
        # these, so it was treated as a refusal: no retry, no next model.
        return any(k in s for k in ('503', 'UNAVAILABLE', '500', 'INTERNAL',
                                    '504', 'DEADLINE_EXCEEDED', 'overloaded',
                                    'timed out', 'Timeout', 'timeout'))"""


def fix53a(s):
    if OLD_TRANSIENT_VISION not in s:
        return None
    return s.replace(OLD_TRANSIENT_VISION, NEW_TRANSIENT_VISION, 1)


def fix53b(s):
    if OLD_TRANSIENT_TEXT not in s:
        return None
    return s.replace(OLD_TRANSIENT_TEXT, NEW_TRANSIENT_TEXT, 1)


# ---------------------------------------------------------------------------
# Fix 59 -- 1s then 2s is not a retry ladder, it is a formality
#
# Observed: "gemini-flash-lite-latest: transient, retrying in 1s / in 2s" then
# GENERATION_FAILED on two of three videos. The error, once printed by hand,
# was 503 -- the model is facing high demand. That is Gemini CAPACITY, and it
# clears in tens of seconds; three seconds of waiting never had a chance.
#
# Depth is the wrong axis anyway. Overload is PER MODEL, so the cheap escape
# is breadth: fix 58 restores the other probed models, and this buys enough
# patience per model for a brief spike to pass. 5 models x (4s + 8s) worst
# case is ~60s of sleeping inside a 420s LADDER_BUDGET_S that is re-checked
# every attempt, so it cannot run away.
#
# Jitter because otherwise every video in a batch retries in lockstep and
# walks into the same wall together. time.time() % 1 avoids importing random
# into a cell that does not have it.
#
# And it NAMES THE ERROR. "transient" alone cost two rounds of guessing at
# whether this was a quota wall, an overload, or our own client timeout --
# a string the code was holding the whole time.
# ---------------------------------------------------------------------------
OLD_RETRY_WAIT = """                    if transient and attempt < 2:
                        wait = 2 ** attempt
                        if self.verbose:
                            print(f'  {model_name}: transient, retrying in {wait}s')
                        time.sleep(wait)
                        continue"""
NEW_RETRY_WAIT = """                    if transient and attempt < 2:
                        # 503 "facing high demand" is capacity, and it clears
                        # in tens of seconds -- 1s then 2s was a formality.
                        # Jitter: a batch must not retry in lockstep into the
                        # same wall. Bounded by LADDER_BUDGET_S above.
                        wait = 2 ** (attempt + 2) * (1.0 + (time.time() % 1) * 0.5)
                        if self.verbose:
                            print(f'  {model_name}: transient, retrying in '
                                  f'{wait:.0f}s  [{s.strip()[:88]}]')
                        time.sleep(wait)
                        continue"""


def fix59(s):
    if OLD_RETRY_WAIT not in s:
        return None
    return s.replace(OLD_RETRY_WAIT, NEW_RETRY_WAIT, 1)


# ---------------------------------------------------------------------------
# Fix 60 -- the batch loop printed the symptom and discarded the diagnosis
#
#     [2/4] 7cbe084e3e969da0   GENERATION_FAILED  0 events
#
# run_vlm_pass1 already records the exception text as a flag DETAIL, and §71's
# describe() already prints it -- but run_vision_all, the loop you actually
# watch during a batch, printed the status and threw the reason away. Two
# rounds of diagnosis went into recovering a string this loop had in hand.
#
# `ev` is reset per iteration first. Without that, a video that raised BEFORE
# the assignment would print the PREVIOUS video's failure reason -- a message
# that is not merely unhelpful but wrong, which is worse than silence.
# ---------------------------------------------------------------------------
OLD_VA_RESET = """                tr = ocr_ = None"""
NEW_VA_RESET = """                tr = ocr_ = ev = None"""

OLD_VA_PRINT = """            print(f'[{i}/{len(videos)}] {v["video_id"]:<18s} {rows[-1]["status"]:<18s} '
                  f'{rows[-1].get("events", 0)} events')"""
NEW_VA_PRINT = """            print(f'[{i}/{len(videos)}] {v["video_id"]:<18s} {rows[-1]["status"]:<18s} '
                  f'{rows[-1].get("events", 0)} events')
            # WHY, not just THAT. The exception text is already in the
            # artifact's flags; printing only the status turns "here is what
            # killed it" into the word GENERATION_FAILED.
            if rows[-1].get('status') != 'OK':
                _ev = locals().get('ev')
                for _f in (getattr(_ev, 'flags', None) or []):
                    _d = _f.get('detail') if isinstance(_f, dict) else None
                    if _d:
                        print(f'        -> {_f.get("code")}: {str(_d)[:200]}')"""


def fix60(s):
    if 'def run_vision_all' not in s or OLD_VA_PRINT not in s:
        return None
    if OLD_VA_RESET not in s:
        return None
    return s.replace(OLD_VA_RESET, NEW_VA_RESET, 1).replace(
        OLD_VA_PRINT, NEW_VA_PRINT, 1)


# ---------------------------------------------------------------------------
# Fix 61 -- the probe buried three models for being busy for one second
#
# A real probe run:
#
#     fail  gemini-3.5-flash       ServerError: 504 DEADLINE_EXCEEDED
#     OK    gemini-3.5-flash-lite  30.0s
#     OK    gemini-flash-lite-latest 25.5s
#     fail  gemini-3.1-flash-lite  ServerError: 503 UNAVAILABLE
#     fail  gemini-3.8-flash       ServerError: 503 UNAVAILABLE
#
# Three of five were dropped for the SAME condition the stage then failed on
# minutes later: momentary overload. Busy now is not dead forever -- complete.md
# already says it about quota ("a 429 is a quota, not a tombstone") and the
# probe was not applying it. By the time a fallback is actually needed, the
# spike that hid these models has very likely passed.
#
# So a TRANSIENT probe failure demotes rather than excludes: the model goes to
# the BACK of the ladder, behind everything that measurably answered. A hard
# failure (404 NOT_FOUND, a bad key, a model that returned junk) still excludes,
# because that will not get better by waiting.
#
# Only when something DID answer. If every candidate failed transiently we have
# measured nothing, and the old "keeping {current}" path is the honest result --
# leading with a model that just failed its own probe is a guess wearing a
# measurement's clothes.
# ---------------------------------------------------------------------------
OLD_PROBE_ACC = """    out, _errs = [], []"""
NEW_PROBE_ACC = """    out, _errs, _soft = [], [], []"""

OLD_PROBE_FAIL = """            else:
                _errs.append(err)
                if verbose:
                    print(f'    fail  {name:26} {err}')"""
NEW_PROBE_FAIL = """            else:
                _errs.append(err)
                # BUSY NOW IS NOT DEAD FOREVER. A 503/504 here is the same
                # momentary overload the stage itself retries through, so it
                # demotes the model instead of deleting it.
                if any(k in err for k in ('503', '504', 'UNAVAILABLE',
                                          'DEADLINE', 'INTERNAL', '500')):
                    _soft.append(name)
                if verbose:
                    print(f'    fail  {name:26} {err}')"""

OLD_PROBE_RET = """    out.sort()
    return out"""
NEW_PROBE_RET = """    out.sort()
    # Demoted models go BEHIND every measured one. float('inf') keeps them
    # last without pretending we timed them, and only when something answered:
    # with no measurement at all, leading with a model that just failed its
    # own probe is a guess wearing a measurement's clothes.
    if out and _soft:
        if verbose:
            print(f'    (demoted, not dropped -- retried only if the '
                  f'faster ones are busy: {", ".join(_soft)})')
        out = out + [(float('inf'), n) for n in _soft]
    return out"""


# ---------------------------------------------------------------------------
# Fix 58 -- the probe measured a ladder and then threw all but one rung away
#
#     vision model -> gemini-flash-lite-latest (25.5s), unchanged
#
# ...on a probe where gemini-3.5-flash-lite ALSO answered, in 30.0s. Both
# return paths of autoselect_vision_model discarded it: one returned a 1-tuple
# of the winner, the other returned cfg untouched. So the stage ran with a
# one-model ladder, reached "unusable, trying the next model", and there was no
# next model. A single 503 then killed the video.
#
# Overload is PER MODEL, so the other probed models are precisely the escape
# hatch, and they cost nothing until the first one refuses. ranked[0] stays
# first, so gemini_models[0] -- which IS the visual cache key -- does not move
# and no existing artifact is invalidated by this.
#
# NOTE this must also live in VISION_PROBE_BLOCK above, for a notebook that
# does not have the block yet: fix29 inserts it only when absent, so the
# literal fixes fresh inserts and this fixes every notebook already patched.
# ---------------------------------------------------------------------------
OLD_AUTOSEL_SAME = """    winner = ranked[0][1]
    if winner == current:
        if verbose:
            print(f'  vision model -> {winner} ({ranked[0][0]:.1f}s), unchanged; '
                  f'existing visual artifacts stay valid')
        return cfg"""
NEW_AUTOSEL_SAME = """    # KEEP EVERY MODEL THAT ANSWERED, fastest first -- not just the winner.
    # A 1-tuple deleted the fallbacks, so one 503 "facing high demand" killed
    # the stage with four other probed models sitting unused. ranked[0] stays
    # first, so the visual CACHE KEY is unchanged.
    _ladder = tuple(n for _, n in ranked)
    winner = ranked[0][1]
    if winner == current:
        if verbose:
            print(f'  vision model -> {winner} ({ranked[0][0]:.1f}s), unchanged; '
                  f'existing visual artifacts stay valid')
            if len(_ladder) > 1:
                print(f'  fallbacks if it is overloaded: '
                      f'{", ".join(_ladder[1:])}')
        return _dc.replace(cfg, gemini_models=_ladder)"""

OLD_AUTOSEL_RET = """    return _dc.replace(cfg, gemini_models=(winner,))"""
NEW_AUTOSEL_RET = """        if len(_ladder) > 1:
            print(f'  fallbacks if it is overloaded: {", ".join(_ladder[1:])}')
    return _dc.replace(cfg, gemini_models=_ladder)"""


def fix58(s):
    if 'def autoselect_vision_model' not in s:
        return None
    if OLD_AUTOSEL_SAME not in s or OLD_AUTOSEL_RET not in s:
        return None          # already carries the ladder form
    return (s.replace(OLD_AUTOSEL_SAME, NEW_AUTOSEL_SAME, 1)
             .replace(OLD_AUTOSEL_RET, NEW_AUTOSEL_RET, 1))


# ---------------------------------------------------------------------------
# Fix 64 -- HF_TOKEN, resolved WHERE THE DOWNLOAD HAPPENS
#
# §37a is the hosted-API cell: GEMINI and OPENAI, both of which are called
# per request and one of which stops the notebook when missing. Hugging Face
# is a different thing -- it is a one-time weights download, it is optional,
# and it belongs next to the loader that performs it, not in a cell about API
# keys. Putting it in §37a also put it 46 cells away from the only code that
# cares.
#
# WHAT ACTUALLY PULLS FROM THE HUB (checked, not assumed):
#
#   cell 21  WhisperModel(name, ...)              ~1.6 GB   faster-whisper
#   cell 21  transformers Whisper fallback        ~1.6 GB
#   cell 123 SentenceTransformer(cfg.model_id)    ~130 MB   BGE, Phase 6 L2
#
# NOT OCR. RapidOCR ships its ONNX models inside the package and PaddleOCR
# pulls from Paddle's own servers -- neither touches Hugging Face. Adding a
# token call to load_ocr() would be a comment that lies.
#
# All of it is PUBLIC, so the token is optional. What it buys is download rate
# limit: anonymous pulls are throttled per IP, a Colab IP is a datacentre IP,
# and a cold runtime fetching ~1.8 GB can take a 429 that looks like a broken
# pipeline and is not.
#
# The loaders take NO token argument -- both resolve through huggingface_hub,
# which reads the process environment. So setting the variable IS the whole
# integration, and no stage version moves.
# ---------------------------------------------------------------------------
HF_HELPER = '''
# ---------------------------------------------------------------------------
# Hugging Face credentials, resolved HERE because this is where the download
# happens: WhisperModel() below, and SentenceTransformer() in Phase 6 L2.
#
# OPTIONAL. Every model fetched here is public and works anonymously. A token
# only raises the download RATE LIMIT, which is what bites on Colab: a
# datacentre IP is throttled far harder than a home connection, and a cold
# runtime pulls ~1.8 GB before the first word is transcribed.
#
# NOT used by OCR -- RapidOCR bundles its ONNX models and PaddleOCR fetches
# from Paddle, so neither goes near the Hub.
# ---------------------------------------------------------------------------
def ensure_hf_token(verbose: bool = False) -> bool:
    """Put HF_TOKEN in the environment, from a Colab secret if need be.

    Returns True when a token is in play. Never raises and never prints the
    token: notebook output is saved with the file and outlives the session.

    huggingface_hub reads HF_TOKEN; older versions and some downstream
    libraries read HUGGING_FACE_HUB_TOKEN. Both are set, because one of them
    being set is the confusing way for this to half-work.
    """
    tok = (os.environ.get('HF_TOKEN', '').strip()
           or os.environ.get('HUGGING_FACE_HUB_TOKEN', '').strip())
    if not tok:
        try:
            from google.colab import userdata
            tok = (userdata.get('HF_TOKEN') or '').strip()
        except Exception:
            tok = ''
    if not tok:
        if verbose:
            print('  HF: anonymous (fine -- these models are public). Set a '
                  'Colab secret')
            print('      HF_TOKEN if a download hits a rate limit: '
                  'huggingface.co/settings/tokens, Read scope.')
        return False
    os.environ['HF_TOKEN'] = tok
    os.environ['HUGGING_FACE_HUB_TOKEN'] = tok
    if verbose:
        print(f'  HF: token set ({len(tok)} chars) -- higher download rate '
              f'limit')
    return True

'''

OLD_ASR_ANCHOR = """# ---------------------------------------------------------------------------
# Backend A -- faster-whisper (preferred). CTranslate2, bundles Silero VAD.
# ---------------------------------------------------------------------------"""

OLD_ASR_LOAD = """        from faster_whisper import WhisperModel"""
NEW_ASR_LOAD = """        ensure_hf_token()          # before the first weights fetch
        from faster_whisper import WhisperModel"""

OLD_L2_LOAD = """        from sentence_transformers import SentenceTransformer"""
NEW_L2_LOAD = """        _hf = globals().get('ensure_hf_token')
        if callable(_hf):
            _hf()                  # BGE comes off the Hub too
        from sentence_transformers import SentenceTransformer"""


def fix64a(s):
    """Define the helper in the ASR module, and use it at both HF loads."""
    if 'def ensure_hf_token' in s:
        return None
    if OLD_ASR_ANCHOR not in s or OLD_ASR_LOAD not in s:
        return None
    return s.replace(OLD_ASR_ANCHOR, HF_HELPER.strip() + '\n\n\n'
                     + OLD_ASR_ANCHOR, 1).replace(OLD_ASR_LOAD,
                                                  NEW_ASR_LOAD, 1)


def fix64b(s):
    if OLD_L2_LOAD not in s or 'def l2_model' not in s:
        return None
    return s.replace(OLD_L2_LOAD, NEW_L2_LOAD, 1)


# ---------------------------------------------------------------------------
# Fix 64c -- REVERT: take HF_TOKEN back out of §37a
#
# An earlier pass put HF_TOKEN in §37a alongside GEMINI and OPENAI. Wrong cell.
# §37a is about hosted API keys that are read on every request and one of
# which halts the notebook; a Hugging Face token is a one-time weights
# download, optional, and belongs at the loader (fix 64a/64b).
#
# The patcher edits the notebook IN PLACE, so deleting the fix does not undo
# it -- the change is already on disk. A revert has to be explicit, which is
# also the honest record: it says a thing was done and then undone, rather
# than quietly vanishing from the file.
# ---------------------------------------------------------------------------
REVERT_37A = [
    ("for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY', 'HF_TOKEN'):",
     "for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):"),
    ("""# HF_TOKEN mirrors to the older variable name, because huggingface_hub has
# used both across versions and the loaders read whichever they were built
# against. Cheap to set both; confusing to debug when only one is set.
if os.environ.get('HF_TOKEN', '').strip():
    os.environ['HUGGING_FACE_HUB_TOKEN'] = os.environ['HF_TOKEN'].strip()

for _name, _tier in (('GEMINI_API_KEY', 'free tier, tried first'),
                     ('OPENAI_API_KEY', 'PAID, fallback only'),
                     ('HF_TOKEN', 'OPTIONAL -- raises the Hugging Face '
                                  'download rate limit')):""",
     """for _name, _tier in (('GEMINI_API_KEY', 'free tier, tried first'),
                     ('OPENAI_API_KEY', 'PAID, fallback only')):"""),
    ("""    if not _v and _name != 'HF_TOKEN':
        print(f'                 why: {_src}')
    elif not _v:
        # OPTIONAL MEANS OPTIONAL. No "why", no banner -- everything the Hub
        # serves here is public and downloads fine anonymously. Say what a
        # token would buy, once, and move on.
        print('                 fine as-is. Set it only if a model download '
              'hits a rate limit')
        print('                 (Colab is a datacentre IP, which the Hub '
              'throttles harder):')
        print('                 huggingface.co/settings/tokens -> Read scope '
              '-> Colab secret HF_TOKEN')""",
     """    if not _v:
        print(f'                 why: {_src}')"""),
]


def fix64c(s):
    if '_KEY_WHERE' not in s:
        return None
    if not any(new in s for new, _old in REVERT_37A):
        return None                      # already clean
    for new, old in REVERT_37A:
        s = s.replace(new, old, 1)
    return s


# ---------------------------------------------------------------------------
# Fix 65 -- ask the API which models exist, instead of guessing
#
# VISION_PROBE_CANDIDATES was a hand-maintained tuple of five names, and a
# hand-maintained list of model names goes stale in exactly one direction:
# Google retires a name, the probe 404s, and the ladder quietly shortens. The
# 404 branch already says so -- "RETIRED MODELS: the candidate list is out of
# date, not the key" -- which is a diagnosis nobody should have to read,
# because models.list() answers the question directly.
#
# It is also the CHEAPEST POSSIBLE KEY TEST: listing costs no tokens, so a
# dead key is caught before a single image is uploaded.
#
# WHAT IT FILTERS, AND WHY BY NAME. The listing says which models support
# generateContent, so that part is authoritative. It does NOT say which accept
# an image, and a model that cannot is not a candidate however new it is --
# so embedding / imagen / veo / tts / native-audio / live / gemma / learnlm go
# by name. Getting this wrong costs a wasted probe, not a wrong audit.
#
# THE CAP MATTERS MORE THAN IT LOOKS. probe_vision_models runs candidates in
# PARALLEL with max_workers=len(candidates). Discovery can return fifteen
# names where the tuple had five, and a fifteen-way burst against a free-tier
# per-minute limit is the probe rate-limiting ITSELF -- marking healthy models
# dead, which is the exact failure fix 61 was written to stop. So the
# discovered list is ranked and capped.
#
# RANKED CHEAP-FIRST, and not only to save money: this stage sends 16-48
# frames per video, flash-lite is the workhorse, and pro hits the per-minute
# limit sooner. Testing the cheap ones first also means a quota wall costs the
# LEAST useful result rather than the most.
#
# Degrades rather than blocks: if the listing fails for any reason, the
# hardcoded tuple is still there and the probe runs exactly as before.
# ---------------------------------------------------------------------------
DISCOVER_BLOCK = '''
VISION_PROBE_MAX = 8             # ceiling on models probed in ONE parallel
                                 # burst -- see discover_vision_models()
# Plain re.compile, NOT __import__('re').compile: the Backend extractor keeps
# a module-level constant only when its value is a literal or a call to a
# recognised builder, and `__import__('re').compile` is neither -- it would be
# dropped as a driver and this module would fail to load with a NameError.
_NOT_VISION_RE = re.compile(
    r'embedding|aqa|imagen|veo|-tts|text-to-speech|native-audio|'
    r'-audio-|live-|learnlm|gemma', re.I)


def _vision_model_rank(name: str) -> tuple:
    """Cheap and fast first. flash-lite < flash < pro, newer before older."""
    import re as _re
    n = name.lower()
    family = 0 if 'flash-lite' in n else 1 if 'flash' in n else 2
    v = _re.search(r'(\\d+)\\.(\\d+)', n)
    major, minor = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
    alias = 0 if 'latest' in n else 1
    preview = 1 if ('preview' in n or 'exp' in n) else 0
    return (family, preview, -major, -minor, alias, n)


def discover_vision_models(limit: int = None, verbose: bool = True) -> list:
    """Model names THIS key can actually see, plausible for vision, ranked.

    Returns [] when the listing cannot be had, so the caller falls back to
    VISION_PROBE_CANDIDATES rather than ending up with no candidates at all.
    Never raises.
    """
    limit = int(limit or VISION_PROBE_MAX)
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        return []
    try:
        from google import genai
        client = genai.Client(api_key=key)
        try:
            # query_base asks for base models rather than tuned ones; older
            # SDKs do not know the argument, so fall back instead of failing.
            listing = list(client.models.list(config={'query_base': True}))
        except Exception:
            listing = list(client.models.list())
    except Exception as exc:
        if verbose:
            print(f'  models.list() unavailable ({type(exc).__name__}) -- '
                  f'using the built-in candidate list')
            _v = globals().get('key_failure_verdict')
            if callable(_v):
                _m = _v([str(exc)])
                if _m:
                    print(f'    -> {_m}')
        return []

    keep, nogen, novis = [], 0, 0
    for m in listing:
        name = str(getattr(m, 'name', '') or '').replace('models/', '')
        if not name:
            continue
        acts = (getattr(m, 'supported_actions', None)
                or getattr(m, 'supported_generation_methods', None) or [])
        # The SDK renamed this field; accept either spelling, and treat an
        # empty list as "unknown", not as "no".
        can_gen = (not acts) or any(
            str(a).lower().replace('_', '') == 'generatecontent' for a in acts)
        if not can_gen:
            nogen += 1
        elif _NOT_VISION_RE.search(name):
            novis += 1
        else:
            keep.append(name)
    keep.sort(key=_vision_model_rank)
    if verbose:
        print(f'  models.list(): {len(listing)} visible, {nogen} cannot '
              f'generate, {novis} not image->text, {len(keep)} candidate(s)')
        if len(keep) > limit:
            print(f'    probing the {limit} cheapest -- a bigger parallel '
                  f'burst rate-limits the probe itself')
    return keep[:limit]

'''

OLD_PROBE_CANDS = """    candidates = tuple(candidates or VISION_PROBE_CANDIDATES)"""
NEW_PROBE_CANDS = """    # ASK, then guess. A hand-maintained name list goes stale in one
    # direction -- Google retires a name and the ladder silently shortens --
    # and listing costs no tokens, so it is also the cheapest key test there
    # is. Falls back to the built-in tuple whenever the listing cannot be had.
    if not candidates:
        _found = discover_vision_models(verbose=verbose)
        candidates = tuple(_found or VISION_PROBE_CANDIDATES)
    else:
        candidates = tuple(candidates)"""

OLD_PROBE_ANCHOR = """def probe_vision_models(candidates=None, timeout_s: float = None,"""


def fix65(s):
    if 'def discover_vision_models' in s:
        return None
    if OLD_PROBE_ANCHOR not in s or OLD_PROBE_CANDS not in s:
        return None
    return s.replace(OLD_PROBE_ANCHOR,
                     DISCOVER_BLOCK.strip() + '\n\n\n' + OLD_PROBE_ANCHOR, 1
                     ).replace(OLD_PROBE_CANDS, NEW_PROBE_CANDS, 1)


# ---------------------------------------------------------------------------
# Fix 65b -- __import__('re').compile is a constant the Backend cannot keep
#
# The first pass of fix 65 built _NOT_VISION_RE with __import__('re').compile.
# Harmless in the notebook; fatal downstream. Backend/tools/
# extract_from_notebook.py keeps a module-level constant only when its value
# is a literal or a call to a RECOGNISED builder, precisely so that importing
# the package cannot run a stage -- and `__import__('re').compile` is not on
# that list, so the constant was silently dropped and auditor/vision/gemini.py
# would fail at load with a NameError.
#
# This needed its own fix rather than a branch inside fix65, because patch()
# skips a fix whose marker is already present: fix 65's marker is
# 'def discover_vision_models', which was there, so the repair never ran. A
# marker names what a fix EMITS, so a repair needs a marker of its own.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fix 66 -- the filter, corrected against a REAL listing of 61 models
#
# A live run against a real key listed 61 models and my filter called 37 of
# them "plausible for vision + JSON". It was wrong about seven families, and
# only ranking saved it: they sort below flash, so the cap never reached them.
# With every flash model returning 503 that is exactly the run where the cap
# WOULD reach them, and a probe that spends its budget asking a music model to
# describe a frame has no budget left for one that could.
#
#   lyria-*                     music generation
#   nano-banana-*               image generation
#   *-image / *-image-preview   image GENERATION -- returns pixels, not JSON.
#                               These take an image and are the easiest thing
#                               here to mistake for vision; they are not.
#   *-transcribe                audio -> text
#   deep-research-*             research agents, not a single generate call
#   antigravity-*               coding agents
#   *-robotics-*                embodied control
#   *-computer-use-*            GUI control
#
# Still a name-based filter, because the listing genuinely does not say which
# models accept an image and return text. It says which support
# generateContent, and all of these do.
# ---------------------------------------------------------------------------
OLD_NOT_VISION = """_NOT_VISION_RE = re.compile(
    r'embedding|aqa|imagen|veo|-tts|text-to-speech|native-audio|'
    r'-audio-|live-|learnlm|gemma', re.I)"""
NEW_NOT_VISION = """_NOT_VISION_RE = re.compile(
    # not generative text at all
    r'embedding|aqa|'
    # generates PIXELS or AUDIO, does not read them
    r'imagen|veo|lyria|nano-banana|-image$|-image-|'
    r'-tts|text-to-speech|native-audio|-audio-|transcribe|'
    # agents and control surfaces, not one generate call
    r'deep-research|antigravity|robotics|computer-use|live-|'
    # separate families with their own API shape
    r'learnlm|gemma',
    re.I)"""


def fix66(s):
    if OLD_NOT_VISION not in s:
        return None
    return s.replace(OLD_NOT_VISION, NEW_NOT_VISION, 1)


# ---------------------------------------------------------------------------
# Fix 67 -- a PIN says "lead with this", not "and have nothing else"
#
# The same live run left exactly ONE model answering: gemini-3.5-flash-lite,
# and only 2 calls in 3. Everything else was 503. Pinning is the right move
# there -- it skips a probe that would spend 8 parallel calls to rediscover
# that -- but the PIN branch returned a ONE-ELEMENT tuple, which is precisely
# the shape fix 58 was written to eliminate. Pinning would have quietly
# restored the bug: one 503 on the pinned model and the video dies with four
# perfectly good fallbacks unused.
#
# The pin still goes FIRST, so gemini_models[0] -- the visual cache key -- is
# exactly what you asked for and no artifact is invalidated. The rest follow
# as fallbacks, unprobed, costing nothing until the pin refuses.
#
# Accepts a string or a sequence, so you can pin an order rather than a model.
# ---------------------------------------------------------------------------
OLD_PIN = """    if PIN_VISION_MODEL:
        if verbose:
            print(f'  vision model PINNED to {PIN_VISION_MODEL} (no probe)')
        return _dc.replace(cfg, gemini_models=(PIN_VISION_MODEL,))"""
NEW_PIN = """    if PIN_VISION_MODEL:
        # A PIN is an ORDER, not a restriction. Returning a 1-tuple here would
        # restore the exact bug fix 58 removed: the ladder reaches "unusable,
        # trying the next model" and there is no next model, so one 503 kills
        # the video. The pin leads (and so remains the cache key); everything
        # else follows as a fallback that costs nothing until it is needed.
        _pin = ((PIN_VISION_MODEL,) if isinstance(PIN_VISION_MODEL, str)
                else tuple(PIN_VISION_MODEL))
        _rest = tuple(m for m in VISION_PROBE_CANDIDATES if m not in _pin)
        if verbose:
            print(f'  vision model PINNED to {_pin[0]} (no probe)')
            if _pin[1:] + _rest:
                print(f'  fallbacks if it is overloaded: '
                      f'{", ".join(_pin[1:] + _rest)}')
        return _dc.replace(cfg, gemini_models=_pin + _rest)"""


def fix67(s):
    if OLD_PIN not in s:
        return None
    return s.replace(OLD_PIN, NEW_PIN, 1)


# ---------------------------------------------------------------------------
# Fix 68 -- the named angles were the HOOK LINES, not the angles
#
# A real run against the Apothecary brief reported:
#
#     the brief names 2 creative angle(s):
#         "I was just about refill my pill organiser"      90%
#         "Don't judge but is what my supplements look"     0%
#
# Those are hooks. The brief's actual angles are "No judgement zone" and
# "Health journey". The document is shaped like this:
#
#     Creative Concepts                 <- section heading
#     Top-performing TikTok formats...  <- lead-in sentence
#     1. No judgement zone              <- THE ANGLE
#     * Hook: "Don't judge but ..."     <- detail belonging to it
#     * Format: Skit-style video
#     2. Health journey                 <- THE ANGLE
#     * Hook options: "I was just ..."
#
# named_brief_angles read requirement LABELS out of a choice group, and the
# compiler had turned each BULLET into a requirement -- so it faithfully
# reported the bullets. It was reading the wrong level of the document.
#
# THE DISCRIMINATOR, verified against both export shapes. parse_brief_sections
# keeps the bullet marker on content lines and leaves a sub-heading bare:
#
#     '1. No judgement zone'                          <- no marker  = ANGLE
#     '* Hook: "Don\\'t judge but ..."'                <- marker     = detail
#     '● Hook: "Don\\'t judge but ..."'                <- marker     = detail
#
# A Google Docs markdown export uses '*', a plain-text export uses '●', and the
# parser normalises neither -- so the marker separates "the angle" from "what
# the angle involves" without guessing at line length or title case.
#
# GENERALISED, because the next brief will be shaped differently:
#   - numbered sub-headings win when the section has any ('1.', '2)')
#   - otherwise any bare non-sentence line in the section is a candidate
#   - a lead-in sentence is rejected: it ends in . ! or ?
#   - 'Hook:', 'Format:', 'Note:' and quoted lines are detail, never names
#   - nothing found -> the OLD group-label behaviour, unchanged
#
# AND THE MODEL NOW SEES THE DETAIL. "No judgement zone" alone is close to
# unjudgeable; the bullets under it are what make an attribution possible. The
# validated closed list stays the NAMES only, so _clean_concept_fit is
# unchanged.
# ---------------------------------------------------------------------------
ANGLE_BLOCKS = '''
# A bullet marker survives parse_brief_sections; a sub-heading does not have
# one. That single difference is what separates an angle's NAME from the lines
# describing it, and it holds for both a markdown export ('*') and a Google
# Docs plain-text export ('●').
_ANGLE_BULLET_RE = re.compile(r'^\\s*[\\*\\-\\u2022\\u25cf\\u25aa\\u2023\\u00b7\\u2013\\u2014]+\\s+')
_ANGLE_NUMBERED_RE = re.compile(r'^\\s*(\\d{1,2})\\s*[.)]\\s+(.{2,70})$')
# Lines that describe an angle rather than name one.
_ANGLE_DETAIL_CUE_RE = re.compile(
    r'^(hook|hooks|format|formats|note|notes|caption|cta|call to action|'
    r'script|example|examples|visual|audio|tone|style|length|duration|'
    r'creator|talent|deliverable)s?\\b\\s*:?', re.I)


def _looks_like_angle_name(name: str) -> bool:
    """A NAME, not a sentence and not a quoted line of script."""
    n = (name or '').strip()
    if not (2 <= len(n) <= 70):
        return False
    if n[-1] in '.!?':
        return False                       # a lead-in sentence, not a heading
    if n[0] in '"\\u201c\\'':
        return False                       # a quoted hook
    if _ANGLE_DETAIL_CUE_RE.match(n):
        return False
    return any(c.isalpha() for c in n)


def brief_angle_blocks(compiled: dict, limit: int = 8) -> list:
    """[{'name', 'detail'}] -- the brief's OWN angles, with what each involves.

    Reads the DOCUMENT, not the compiled requirements: the compiler flattens
    an angle's bullets into requirements, which is why reading labels back out
    returned hooks instead of angles.

    Returns [] when the brief is not shaped this way, so the caller can fall
    back rather than report an empty list as a finding.
    """
    text = (compiled or {}).get('brief_text') or ''
    _parse = globals().get('parse_brief_sections')
    if not text or not callable(_parse):
        return []
    blocks = []
    try:
        sections = _parse(text)
    except Exception:
        return []
    for sec in sections:
        if not _ANGLE_GROUP_RE.search(str(getattr(sec, 'heading', '') or '')):
            continue
        numbered, loose, cur = [], [], None
        for raw in (getattr(sec, 'lines', None) or []):
            line = str(raw).strip()
            if not line:
                continue
            if _ANGLE_BULLET_RE.match(line):
                if cur is not None:
                    cur['detail'].append(_ANGLE_BULLET_RE.sub('', line).strip())
                continue
            m = _ANGLE_NUMBERED_RE.match(line)
            name = (m.group(2) if m else line).strip().rstrip(':').strip()
            if not _looks_like_angle_name(name):
                continue
            cur = {'name': name, 'detail': []}
            (numbered if m else loose).append(cur)
        # NUMBERING WINS when the section uses it. Otherwise the lead-in
        # sentence and any stray line compete with the real names.
        blocks.extend(numbered or loose)
    out, seen = [], set()
    for b in blocks:
        k = b['name'].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({'name': b['name'], 'detail': b['detail'][:6]})
    return out[:limit]

'''

OLD_NBA_BODY = """    groups = {}
    for r in (compiled or {}).get('requirements') or []:
        g = r.get('group')
        if not g:
            continue
        d = groups.setdefault(g, {'label': str(r.get('group_label') or g),
                                  'members': []})
        lbl = str(r.get('label') or '').strip()
        if lbl and lbl not in d['members']:
            d['members'].append(lbl)
    named = []
    for g, d in groups.items():
        if not _ANGLE_GROUP_RE.search(f"{d['label']} {g}"):
            continue
        for m in d['members']:
            if m not in named:
                named.append(m)
    return named[:limit]"""
NEW_NBA_BODY = """    # THE DOCUMENT FIRST. An angle is a sub-heading in the brief; the
    # compiler flattens the bullets beneath it into requirements, so reading
    # requirement labels back out returns the HOOKS, not the angles. That is
    # exactly what it did: "I was just about refill my pill organiser" was
    # reported as an angle of a brief whose angles are "No judgement zone"
    # and "Health journey".
    _blocks = brief_angle_blocks(compiled, limit=limit)
    if _blocks:
        return [b['name'] for b in _blocks]

    # FALLBACK, unchanged: a brief with no angle sub-headings, where the
    # options of an angle-ish choice group genuinely are the angles.
    groups = {}
    for r in (compiled or {}).get('requirements') or []:
        g = r.get('group')
        if not g:
            continue
        d = groups.setdefault(g, {'label': str(r.get('group_label') or g),
                                  'members': []})
        lbl = str(r.get('label') or '').strip()
        if lbl and lbl not in d['members']:
            d['members'].append(lbl)
    named = []
    for g, d in groups.items():
        if not _ANGLE_GROUP_RE.search(f"{d['label']} {g}"):
            continue
        for m in d['members']:
            if m not in named:
                named.append(m)
    return named[:limit]"""

OLD_ANGLE_PROMPT = """    if _named:
        lines += ['', 'NAMED ANGLES (use these exact names in concept_fit):']
        lines += [f'  - {a}' for a in _named]
        lines += [f'  - {NO_ANGLE_LABEL}']"""
NEW_ANGLE_PROMPT = """    if _named:
        # WITH WHAT EACH ANGLE INVOLVES. "No judgement zone" on its own is
        # close to unjudgeable -- the bullets under it in the brief are what
        # make an attribution possible. The closed list validated afterwards
        # is still the NAMES only.
        _detail = {b['name']: b.get('detail') or []
                   for b in brief_angle_blocks(compiled, limit=len(_named))}
        lines += ['', 'NAMED ANGLES (use these exact names in concept_fit):']
        for a in _named:
            lines.append(f'  - {a}')
            for d in (_detail.get(a) or [])[:4]:
                lines.append(f'        {d}')
        lines += [f'  - {NO_ANGLE_LABEL}']"""


# ---------------------------------------------------------------------------
# Fix 68b -- angles that are their own sections
#
# Fix 68 reads sub-headings out of the angle section's LINES, which is right
# when they are numbered:
#
#     Creative Concepts        <- section
#     1. No judgement zone     <- a LINE in it
#
# But a brief that bolds its angle names without numbering them parses
# differently -- parse_brief_sections promotes each to a SECTION of its own:
#
#     heading='Messaging Territories'  kind=alternatives
#     heading='Quiet mornings'         kind=requirements   <- an angle
#     heading='Built for chaos'        kind=requirements   <- an angle
#     heading='Do Not'                 kind=requirements   <- NOT an angle
#
# So when an angle-ish section yields nothing from its own lines, the sections
# that FOLLOW it are the candidates, until one whose heading names a different
# topic. That stop list is the load-bearing part: without it this would
# swallow "Do Not", "Talking Points" and everything else to the end of the
# document.
#
# Only reached when the numbered form found nothing, so the Apothecary brief
# is untouched by this.
# ---------------------------------------------------------------------------
ANGLE_STOP = '''
# Headings that end a run of angles. Everything here names a DIFFERENT kind of
# instruction, so a section titled with one of them is never an angle however
# it is formatted.
_ANGLE_STOP_RE = re.compile(
    # don\\S{0,2}ts, not don'?ts: a bare apostrophe inside an r'...' literal
    # closes the string, and the emitted cell then fails to parse. It matches
    # "donts", "don'ts" and the curly-quote form without any quoting at all.
    r'\\b(do\\s*not|don\\S{0,2}ts?|dos?\\s+and|requirements?|mandator\\w*|prohibit\\w*|'
    r'talking\\s*points?|product\\s+features?|features?|deliverables?|'
    r'call\\s*to\\s*actions?|ctas?|hashtags?|captions?|hooks?|'
    r'timelines?|deadlines?|budgets?|legal|compliance|disclaimers?|'
    r'audiences?|objectives?|goals?|brand\\s+\\w+|assets?|specs?|'
    r'purpose|overview|background|summary)\\b', re.I)

'''

OLD_BLOCK_LOOP = """    for sec in sections:
        if not _ANGLE_GROUP_RE.search(str(getattr(sec, 'heading', '') or '')):
            continue
        numbered, loose, cur = [], [], None"""
NEW_BLOCK_LOOP = """    for _i, sec in enumerate(sections):
        if not _ANGLE_GROUP_RE.search(str(getattr(sec, 'heading', '') or '')):
            continue
        numbered, loose, cur = [], [], None"""

OLD_BLOCK_EXTEND = """        blocks.extend(numbered or loose)"""
NEW_BLOCK_EXTEND = """        found = numbered or loose
        if not found:
            # The angle names are SECTIONS of their own -- the shape a brief
            # takes when it bolds them without numbering. Walk forward until a
            # heading names a different topic.
            for nxt in sections[_i + 1:]:
                h = str(getattr(nxt, 'heading', '') or '').strip()
                if not h or _ANGLE_STOP_RE.search(h) \\
                        or _ANGLE_GROUP_RE.search(h):
                    break
                if not _looks_like_angle_name(h):
                    break
                _lines = [_ANGLE_BULLET_RE.sub('', str(x).strip()).strip()
                          for x in (getattr(nxt, 'lines', None) or [])]
                _lines = [x for x in _lines if x]
                if not _lines:
                    # An angle has something under it. A bare heading with no
                    # content is a divider, not a creative territory.
                    break
                found.append({'name': h, 'detail': _lines})
        blocks.extend(found)"""


# ---------------------------------------------------------------------------
# Fix 68c -- repair: an apostrophe closed the r-string
#
# Fix 68b's first pass emitted  r'\b(do\s*not|don'?ts?|...'  -- the bare
# apostrophe in don'?ts terminates the literal, and cell 127 stopped parsing
# with "'(' was never closed". Caught by running the cell rather than by
# reading it; a marker check would have passed, because the marker text WAS
# emitted -- just inside a broken statement.
#
# Its own fix, because patch() skips a fix whose marker is already present,
# and 68b's marker (_ANGLE_STOP_RE) is exactly what the broken line contains.
# Fourth time this session.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Fix 68d -- say WHERE the angles came from, and survive an older compile
#
# After fix 68 shipped, a re-run printed the hook lines again -- and there was
# no way to tell which of three causes it was:
#
#   1. the patched cell was never replaced
#   2. the verdicts artifact was a cache hit, so the OLD angles were replayed
#   3. the document path found nothing and it fell back to group labels
#
# Three different fixes, one indistinguishable symptom. That is the same
# failure as "transient, retrying" hiding a 401: the code knew and did not
# say. `angles_source` now records which path produced the list, and §90/§91
# print it.
#
# Also: an approved compile is FROZEN and reused from disk, and a compile
# written before 'brief_text' existed has none -- the document path would then
# silently find nothing forever. BRIEF_TEXT (set by §48 from the loaded
# document) is the fallback, so the angles work regardless of when the brief
# was compiled.
# ---------------------------------------------------------------------------
OLD_BLOCK_TEXT = """    text = (compiled or {}).get('brief_text') or ''"""
NEW_BLOCK_TEXT = """    # An approved compile is frozen and reused from disk. One written before
    # 'brief_text' was stored has none, and the document path would then find
    # nothing forever. §48 leaves the loaded document in BRIEF_TEXT.
    text = ((compiled or {}).get('brief_text')
            or globals().get('BRIEF_TEXT') or '')"""

OLD_ANGLE_SRC = """    _named = named_brief_angles(compiled)
    out['named_angles'] = list(_named)"""
NEW_ANGLE_SRC = """    _named = named_brief_angles(compiled)
    out['named_angles'] = list(_named)
    # WHICH PATH FOUND THEM. Without this, "the hooks came back again" has
    # three causes -- stale cell, cached verdicts, or the fallback running --
    # and one symptom. Printed by §90/§91.
    out['angles_source'] = ('document' if brief_angle_blocks(compiled)
                            else 'group_labels' if _named else 'none')"""


# ---------------------------------------------------------------------------
# The report (§79) is NOT patched here.
#
# It is a PHASE 7 cell: build_notebook.py appends it from
# Phase 7/cells/s79_report.py, so it never appears in the Phase 6 notebook
# this file edits. A fix for it registered here can only ever report
# 'FIX DID NOT MATCH' -- which is exactly what happened. Edit that source
# file and rebuild; it is the single home for the report's markup and CSS.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fix 69 -- a video that matches NONE of the brief's angles
#
# "none of the listed angles" was already in the allowed list, so the machinery
# accepted it. Nothing else did.
#
# 1. THE PROMPT ARGUED AGAINST IT. Step 3 said "a video is usually MOSTLY one
#    angle and PARTLY another -- say so, rather than putting 100 on one and
#    nothing on the rest", and mentioned "none of the listed angles" only as a
#    footnote about leftover share. A video that took an angle the brief never
#    imagined would be pushed into a 70/30 split between two angles it does
#    not resemble -- a fabricated resemblance, which is worse than an honest
#    "none" because it reads as a finding.
#
# 2. NOTHING RECORDED IT. There was no field saying "this matched none of
#    them", so no report, table or downstream consumer could ask.
#
# 3. THREE STATES RENDERED IDENTICALLY as zeros across the named angles:
#       - the model failed            (ANGLE_MODEL_FAILED)
#       - it answered but gave no split (concept_fit_missing)
#       - it answered: none of these  (a real finding)
#    The first two are pipeline problems. The third is a fact about the video.
#
# The design rule this serves is the one about UNCERTAIN: an abstention is not
# a zero. "None of the listed angles" is not an abstention either -- it is a
# decided answer, and it has to be visibly different from both.
# ---------------------------------------------------------------------------
OLD_ANGLE_STEP3 = """     - a video is usually MOSTLY one angle and PARTLY another -- say so,
       rather than putting 100 on one and nothing on the rest
     - for any share belonging to no listed angle, use the exact name
       "none of the listed angles\""""
NEW_ANGLE_STEP3 = """     - if it DOES belong to the listed angles, a video is usually MOSTLY
       one and PARTLY another -- say so, rather than putting 100 on one and
       nothing on the rest
     - IF IT BELONGS TO NONE OF THEM, say exactly that: put the share on the
       exact name "none of the listed angles". A creator who invented her own
       angle is a normal outcome and often a good video -- this brief simply
       did not anticipate it.
     - Do NOT spread percentages across the listed angles to avoid answering
       "none". A forced split claims a resemblance that is not there, and
       that is worse than the honest answer\""""

OLD_ANGLE_TAIL = """    if not ids:
        out['flags'].append('ANGLE_UNCITED')
    return out"""
NEW_ANGLE_TAIL = """    if not ids:
        out['flags'].append('ANGLE_UNCITED')

    # ---- did it match ANY of the brief's angles? -------------------------
    # Three states otherwise render identically as zeros across the named
    # angles: the model failed, the model answered with no split, and the
    # model answered "none of these". Only the last is a finding about the
    # video; the other two are pipeline problems. Keep them distinguishable.
    _off = sum(float(r.get('percent') or 0)
               for r in (out.get('concept_fit') or [])
               if str(r.get('angle')) == NO_ANGLE_LABEL)
    out['off_angle_percent'] = round(_off, 1)
    out['matched_named_angle'] = (bool(out.get('concept_fit'))
                                  and _off < 50.0)
    if out.get('concept_fit') and _off >= 50.0:
        # A FACT ABOUT THE VIDEO, not a fault in it. The flag exists so a
        # batch can count "how many creators went off-concept", which is a
        # question about the BRIEF as much as about the creators.
        out['flags'].append(f'ANGLE_NONE_OF_THE_LISTED:{_off:.0f}%')
    return out"""


# ---------------------------------------------------------------------------
# Fix 70 -- a quoted title is still a title
#
# The Biostime brief names every angle in smart quotes:
#
#     Creative Concepts
#         1. "He's Not Ignoring Me... He's Knocked Out"
#         2. "Why I Stopped Giving My Kids Melatonin"
#     Back to School Campaign
#         1. "Back to School Essentials"
#         2. "Back to School Bedtime Reset"
#
# Four angles across TWO angle-ish sections -- and brief_angle_blocks returned
# NONE of them, because _looks_like_angle_name rejects anything opening with a
# quote. That rule was written to keep quoted HOOK LINES out, and it does the
# job on the Apothecary brief. Here it throws away the answer.
#
# Quoting is not the discriminator; SENTENCE-NESS is. Strip a matching pair
# and judge what is inside:
#
#     "Back to School Essentials"          -> 25 chars, no terminal stop  KEEP
#     "Listen! If your kid lives on ... every morning."  -> ends '.'      DROP
#
# The length and terminal-punctuation rules already separate a title from a
# line of script, so the blanket quote rejection was doing nothing the other
# rules did not do better -- except losing four angles.
#
# The stored name has its quotes stripped, so reports read
# `Back to School Essentials`, and _clean_concept_fit still matches whichever
# form the model echoes (it compares case-insensitively with a substring
# fallback).
# ---------------------------------------------------------------------------
OLD_LOOKS_LIKE = """def _looks_like_angle_name(name: str) -> bool:
    \"\"\"A NAME, not a sentence and not a quoted line of script.\"\"\"
    n = (name or '').strip()
    if not (2 <= len(n) <= 70):
        return False
    if n[-1] in '.!?':
        return False                       # a lead-in sentence, not a heading
    if n[0] in '\"\\u201c\\'':
        return False                       # a quoted hook
    if _ANGLE_DETAIL_CUE_RE.match(n):
        return False
    return any(c.isalpha() for c in n)"""
NEW_LOOKS_LIKE = """def _strip_angle_quotes(name: str) -> str:
    \"\"\"A quoted title is still a title.

    The Biostime brief names every angle in smart quotes -- \"Back to School
    Essentials\" -- so rejecting anything that opens with a quote found NONE of
    its four angles. Strip the quotes and judge what is inside; a quoted HOOK
    is still excluded, by the sentence and length rules, which is what was
    actually doing the work all along.
    \"\"\"
    n = (name or '').strip()
    _PAIRS = (('\"', '\"'), ('\\u201c', '\\u201d'), (\"'\", \"'\"),
              ('\\u2018', '\\u2019'))
    for a, b in _PAIRS:
        if len(n) > 2 and n.startswith(a) and n.endswith(b):
            return n[1:-1].strip()
    # An unmatched opening quote still means the title was quoted -- a
    # document that lost its closing quote in export is not a different kind
    # of document.
    if len(n) > 1 and n[0] in '\"\\u201c\\u2018\\'':
        return n[1:].strip().rstrip('\"\\u201d\\u2019\\'')
    return n


def _looks_like_angle_name(name: str) -> bool:
    \"\"\"A NAME, not a sentence and not a line of script.

    QUOTING IS NOT THE DISCRIMINATOR -- sentence-ness is:
        \"Back to School Essentials\"                      -> KEEP
        \"Listen! If your kid lives on ... every morning.\" -> DROP, ends '.'
    \"\"\"
    n = _strip_angle_quotes(name)
    if not (2 <= len(n) <= 70):
        return False
    if n[-1] in '.!?':
        return False                       # a lead-in sentence, not a heading
    if _ANGLE_DETAIL_CUE_RE.match(n):
        return False
    return any(c.isalpha() for c in n)"""

OLD_NAME_EXTRACT = """            m = _ANGLE_NUMBERED_RE.match(line)
            name = (m.group(2) if m else line).strip().rstrip(':').strip()"""
NEW_NAME_EXTRACT = """            m = _ANGLE_NUMBERED_RE.match(line)
            name = _strip_angle_quotes(
                (m.group(2) if m else line).strip().rstrip(':').strip())"""

OLD_SIBLING_NAME = """                found.append({'name': h, 'detail': _lines})"""
NEW_SIBLING_NAME = """                found.append({'name': _strip_angle_quotes(h),
                              'detail': _lines})"""


def fix70(s):
    if 'def _strip_angle_quotes' in s:
        return None
    if OLD_LOOKS_LIKE not in s or OLD_NAME_EXTRACT not in s:
        return None
    return (s.replace(OLD_LOOKS_LIKE, NEW_LOOKS_LIKE, 1)
             .replace(OLD_NAME_EXTRACT, NEW_NAME_EXTRACT, 1)
             .replace(OLD_SIBLING_NAME, NEW_SIBLING_NAME, 1))


def fix69(s):
    if 'off_angle_percent' in s:
        return None
    if OLD_ANGLE_STEP3 not in s or OLD_ANGLE_TAIL not in s:
        return None
    return (s.replace(OLD_ANGLE_STEP3, NEW_ANGLE_STEP3, 1)
             .replace(OLD_ANGLE_TAIL, NEW_ANGLE_TAIL, 1))


def fix68d(s):
    if 'angles_source' in s:
        return None
    if OLD_BLOCK_TEXT not in s or OLD_ANGLE_SRC not in s:
        return None
    return (s.replace(OLD_BLOCK_TEXT, NEW_BLOCK_TEXT, 1)
             .replace(OLD_ANGLE_SRC, NEW_ANGLE_SRC, 1))


def fix68c(s):
    broken = "r'\\b(do\\s*not|don'?ts?|dos?\\s+and|"
    if broken not in s:
        return None
    return s.replace(
        broken,
        "# don\\S{0,2}ts, not don'?ts: a bare apostrophe inside an r'...'\n"
        "    # literal closes the string and the cell stops parsing.\n"
        "    r'\\b(do\\s*not|don\\S{0,2}ts?|dos?\\s+and|", 1)


def fix68b(s):
    if '_ANGLE_STOP_RE' in s:
        return None
    if OLD_BLOCK_LOOP not in s or OLD_BLOCK_EXTEND not in s:
        return None
    return (s.replace('_ANGLE_BULLET_RE = re.compile',
                      ANGLE_STOP.strip() + '\n\n_ANGLE_BULLET_RE = re.compile',
                      1)
             .replace(OLD_BLOCK_LOOP, NEW_BLOCK_LOOP, 1)
             .replace(OLD_BLOCK_EXTEND, NEW_BLOCK_EXTEND, 1))


def fix68(s):
    if 'def brief_angle_blocks' in s:
        return None
    if 'def named_brief_angles' not in s or OLD_NBA_BODY not in s:
        return None
    if OLD_ANGLE_PROMPT not in s:
        return None
    return (s.replace('def named_brief_angles',
                      ANGLE_BLOCKS.strip() + '\n\n\ndef named_brief_angles', 1)
             .replace(OLD_NBA_BODY, NEW_NBA_BODY, 1)
             .replace(OLD_ANGLE_PROMPT, NEW_ANGLE_PROMPT, 1))


def fix65b(s):
    if "__import__('re').compile" not in s or '_NOT_VISION_RE' not in s:
        return None
    return s.replace(
        "_NOT_VISION_RE = __import__('re').compile(",
        "# Plain re.compile, NOT __import__('re').compile: the Backend "
        "extractor keeps\n"
        "# a module-level constant only when its value is a literal or a call "
        "to a\n"
        "# recognised builder, so the __import__ form was dropped as a driver "
        "and\n"
        "# auditor/vision/gemini.py failed to load with a NameError.\n"
        "_NOT_VISION_RE = re.compile(", 1
    ).replace("__import__('re').I)", 're.I)', 1)


def fix61(s):
    if 'def probe_vision_models' not in s:
        return None
    for old in (OLD_PROBE_ACC, OLD_PROBE_FAIL, OLD_PROBE_RET):
        if old not in s:
            return None
    return (s.replace(OLD_PROBE_ACC, NEW_PROBE_ACC, 1)
             .replace(OLD_PROBE_FAIL, NEW_PROBE_FAIL, 1)
             .replace(OLD_PROBE_RET, NEW_PROBE_RET, 1))


# ---------------------------------------------------------------------------
# Fix 54 -- the vision probe measured nothing like the real request
#
# The probe sent ONE 64x64 solid-colour square, gemini-3.5-flash answered in
# a few seconds, and it was selected. The real stage then sent 16 frames and
# timed out at 180s. The probe was not wrong; it was measuring the wrong
# thing, and a selection made on an unrepresentative measurement is a guess
# wearing a number.
#
# Four frames at a realistic size, and the per-frame cost reported -- which is
# the figure that actually predicts a 16-frame request. A model that needs 5s
# per frame will not survive 16 of them inside a 180s timeout, and now that is
# visible BEFORE the run rather than after it.
# ---------------------------------------------------------------------------
OLD_PROBE_IMG = """    _img = _Image.new('RGB', (64, 64), (200, 40, 40))"""
NEW_PROBE_IMG = """    # REPRESENTATIVE, not minimal. One 64x64 square told us gemini-3.5-flash
    # was fast; 16 real frames then timed out at 180s. Four frames at roughly
    # a real frame's size measure something that predicts the real request.
    _img = [_Image.new('RGB', (256, 448),
                       (40 + 50 * _k, 90, 200 - 40 * _k)) for _k in range(4)]
    _NPROBE = len(_img)"""

OLD_PROBE_CALL = """                contents=[_img, 'Reply with JSON: {"colour": "<the colour>"}'],"""
NEW_PROBE_CALL = """                contents=_img + ['Reply with JSON: {"n": <how many images>}'],"""

OLD_PROBE_PRINT = """                if verbose:
                    print(f'    OK    {name:26} {dt:5.1f}s  {text!r}')"""
NEW_PROBE_PRINT = """                if verbose:
                    # per-frame is the number that predicts a 16-frame call
                    print(f'    OK    {name:26} {dt:5.1f}s '
                          f'({dt / max(1, _NPROBE):4.1f}s/frame '
                          f'-> ~{dt / max(1, _NPROBE) * 16:5.0f}s for 16)'
                          f'  {text!r}')"""


def fix54(s):
    if '_NPROBE' in s or OLD_PROBE_IMG not in s:
        return None
    out = s.replace(OLD_PROBE_IMG, NEW_PROBE_IMG, 1)
    out = out.replace(OLD_PROBE_CALL, NEW_PROBE_CALL, 1)
    return out.replace(OLD_PROBE_PRINT, NEW_PROBE_PRINT, 1)


# ---------------------------------------------------------------------------
# Stage versions -- the same edit that changes the output
# ---------------------------------------------------------------------------
def bump(s):
    out = s
    # 1.14.0: a subject-free group intent is REPAIRED from its own options
    # before L3 ever sees it, so the judge gets a reference that can actually
    # distinguish. The brief artifact changes, so the version does.
    out = out.replace("BRIEF_STAGE_VERSION  = '1.12.0'",
                      "BRIEF_STAGE_VERSION  = '1.22.0'")
    out = out.replace("BRIEF_PROMPT_VERSION = 'p4_brief_compile_v4'",
                      "BRIEF_PROMPT_VERSION = 'p4_brief_compile_v5'")
    # 1.13.0: substance credit is GRANTED when the alignment passes both gates
    # (intent describes its own options, and the verdict cites a record), and
    # withheld otherwise. Statuses change, so the artifact changes.
    # 1.17.0: fix 23 changes WHICH evidence the judge is shown, so it changes
    # verdicts -- the four false FAILs it exists to stop are in the artifact.
    # Both the 1.11.0 (pristine) and 1.16.0 (already-patched) spellings are
    # handled, so this run correctly on a restored notebook and on this one.
    # 1.18.0: substance credit applies to PARTIAL, not only FAIL (fix 33), and
    # a claim carries its DEFINITION into acceptance_criteria (fix 31). Both
    # change verdicts, so both change the artifact.
    # 1.21.0: fix 68 changes evaluate_creative_angle's OUTPUT -- named_angles
    # become the brief's sub-headings instead of its hook lines, concept_fit
    # is validated against that different list, and angles_source is new.
    #
    # THIS SHOULD HAVE BEEN IN THE SAME EDIT AS FIX 68, and its absence is
    # exactly the failure the rule exists to prevent: the notebook was
    # correct, the cache key was unchanged, so §90 replayed the old angles and
    # the run looked like the fix had not been applied. A user diagnosing that
    # has to know about FORCE_REAUDIT; a bumped version just re-audits.
    # 1.22.0: fix 69 adds off_angle_percent and matched_named_angle to the
    # creative-angle block and can add an ANGLE_NONE_OF_THE_LISTED flag, and
    # it changes the PROMPT -- which changes what the model answers. Bumped in
    # the same edit as the change, unlike 1.21.0, which was not and had to be
    # chased down from a run that looked like the fix had not been applied.
    for _old in ("'1.11.0'", "'1.16.0'", "'1.17.0'", "'1.18.0'", "'1.19.0'",
                 "'1.20.0'", "'1.21.0'"):
        out = out.replace(f'VERDICT_STAGE_VERSION = {_old}',
                          "VERDICT_STAGE_VERSION = '1.22.0'")
        out = out.replace(f'VERDICT_STAGE_VERSION  = {_old}',
                          "VERDICT_STAGE_VERSION  = '1.22.0'")
    return out if out != s else None


def main():
    nb = json.loads(NB.read_text(encoding='utf-8'))
    cells = nb['cells']
    if not BAK.exists():
        shutil.copy2(NB, BAK)
        print(f'  pre-fix backup -> {BAK.name}')

    patch(cells, '1  make_label: no shared-boilerplate labels',
          '_LABEL_PREAMBLE', fix1)
    patch(cells, '2a prompt: intent must name the observable thing',
          'MUST name the OBSERVABLE THING', fix2a)
    patch(cells, '2b schema: intent names the thing, not the place',
          'OBSERVABLE THING to look for', fix2b)
    patch(cells, '2c audit_group_intents(): measure it, do not trust it',
          'def audit_group_intents', fix2c)
    patch(cells, '3  window cross-check runs both directions',
          'WINDOW_DISAGREES_WITH_BRIEF', fix3)
    # A marker must name text the fix ITSELF emits. This one named
    # `_SUBSTANCE_ALIGNMENT`, which appears nowhere in NEW_PROMOTE -- the
    # constant is `_SUBSTANCE_STATUS` and the flag is `SUBSTANCE_ALIGNMENT:`.
    # So the fix reported "not applied" forever, and once OLD_PROMOTE_HEAD was
    # gone the next run died on it. Same failure shape as the '1.13.0'
    # collision below, from the opposite direction: that marker was too loose,
    # this one matched nothing at all.
    patch(cells, '4  literal status and alignment are never blended',
          '_SUBSTANCE_STATUS', fix4)
    # The marker must name the CONSTANT, not just the version string: a bare
    # "'1.13.0'" already matched VLM_STAGE_VERSION, so this fix silently
    # reported itself as already applied while the brief version stayed at
    # 1.12.0. A uniqueness check is only as good as the string it keys on.
    # Same defect as fix 4's marker: NEW_HANDOFF never writes "no verdict was
    # promoted out of its literal status" -- fix 6 REPLACED that assertion with
    # "was every promotion EARNED". Key on text the fix emits.
    patch(cells, '6  §73 hand-off reads alignment, not a promotion',
          'every credited verdict kept its literal finding', fix6)
    patch(cells, '49 a feature she SHOWS is a feature she communicated',
          'CLAIM_EVIDENCE_MODE', fix49)
    patch(cells, '50a name the brief\'s creative angles, not their heading',
          'def named_brief_angles', fix50a)
    patch(cells, '50d concept_fit exists even when the call fails',
          "'concept_fit': []", fix50d)
    patch(cells, '50c ...show them to the model and check what comes back',
          '_clean_concept_fit', fix50c)
    patch(cells, '50b ...and ask for the percentage split',
          'HOW MUCH OF EACH NAMED ANGLE', fix50b)
    # MUST follow 50b/50c: they restructure what those inserted.
    patch(cells, '53a a TIMEOUT is transient (vision ladder)',
          "'timed out', 'Timeout',", fix53a)
    patch(cells, '53b a TIMEOUT is transient (text ladder)',
          "'overloaded',\n                                    'timed out'", fix53b)
    patch(cells, '54 the vision probe measures a REAL payload',
          '_NPROBE', fix54)
    patch(cells, '64c REVERT: HF_TOKEN does not belong in §37a',
          "for _n in ('GEMINI_API_KEY', 'OPENAI_API_KEY'):", fix64c)
    patch(cells, '64a HF token resolved in the ASR module, where it downloads',
          'def ensure_hf_token', fix64a)
    patch(cells, '64b ...and before BGE, the other Hub download',
          'BGE comes off the Hub too', fix64b)
    # MUST follow 54: it rewrites the probe this one feeds candidates into.
    patch(cells, '65 ask models.list() what exists, then probe those',
          'def discover_vision_models', fix65)
    # MUST follow 65: repairs what 65's first pass emitted.
    patch(cells, '65b a constant the Backend extractor can actually keep',
          '_NOT_VISION_RE = re.compile(', fix65b)
    # MUST follow 65b: edits the constant 65b repaired.
    patch(cells, '66 filter corrected against a real 61-model listing',
          'generates PIXELS or AUDIO, does not read them', fix66)
    patch(cells, '67 a PIN leads the ladder, it does not replace it',
          'A PIN is an ORDER, not a restriction', fix67)
    # MUST follow 50a: it rewrites named_brief_angles, which this edits.
    patch(cells, '68 the brief\'s angles are its SUB-HEADINGS, not its hooks',
          'def brief_angle_blocks', fix68)
    # MUST follow 68: extends the loop 68 inserts.
    patch(cells, '68b ...and angles that parse as sections of their own',
          '_ANGLE_STOP_RE', fix68b)
    # MUST follow 68b: repairs the literal 68b's first pass emitted.
    patch(cells, '68c repair: an apostrophe closed the r-string',
          'don\\S{0,2}ts?', fix68c)
    # MUST follow 68: edits what 68 inserted.
    patch(cells, '68d say WHICH path found the angles, and survive an old '
                 'compile', 'angles_source', fix68d)
    patch(cells, '69 a video that matches NONE of the brief\'s angles',
          'off_angle_percent', fix69)
    # MUST follow 68/68b: rewrites the name test they rely on.
    patch(cells, '70 a QUOTED title is still a title',
          'def _strip_angle_quotes', fix70)
    # 69 / 69b are NOT here. §79 (the report) is a PHASE 7 cell, added by
    # build_notebook.py from Phase 7/cells/s79_report.py -- it is not in the
    # Phase 6 notebook this patcher edits, so a fix for it could never match.
    # It lives in that source file instead.
    patch(cells, '58 keep EVERY model that answered, not just the fastest',
          '_ladder = tuple(n for _, n in ranked)', fix58)
    # MUST follow 54: it rewrites the probe body this one edits.
    patch(cells, '61 a transient probe failure DEMOTES, it does not delete',
          'BUSY NOW IS NOT DEAD FOREVER', fix61)
    patch(cells, '59 overload needs patience, and the error named',
          '2 ** (attempt + 2)', fix59)
    patch(cells, '60 the batch loop says WHY a video failed',
          "_ev = locals().get('ev')", fix60)
    patch(cells, '51 steps BEFORE the schema, and the count fixed',
          'Answer in THREE steps', fix51)
    patch(cells, '52 an empty split says WHICH cause it had',
          'NO_NAMED_ANGLES_IN_BRIEF', fix52)
    patch(cells, '48a WHICH BRIEF is declared at the TOP, beside the provider',
          'WHICH BRIEF', fix48a)
    patch(cells, '48b ...and §48 defers to it',
          "BRIEF_SOURCE = globals().get('BRIEF_SOURCE')", fix48b)
    patch(cells, '47 overrides settle a heading with cues for two kinds',
          'SECTION_KIND_OVERRIDES', fix47)
    # MUST follow 15: it appends to the tuples 15 edits.
    patch(cells, '46 section cues cover briefs we have not seen',
          'reasons? to believe', fix46)
    patch(cells, '15 alternatives cues: CTA / campaign sections are menus',
          r"r'\bcall[- ]?to[- ]?actions?\b'", fix15)
    patch(cells, '14a structure guard: a requirements section is not a menu',
          'def ungroup_non_alternatives', fix14a)
    patch(cells, '14b ...and it runs on the compile',
          '_ungrouped = ungroup_non_alternatives', fix14b)
    # MUST follow 14b: it inserts ahead of the call 14b adds.
    patch(cells, '37a a disclaimer is mandatory, never a CTA alternative',
          'def ungroup_compliance_lines', fix37a)
    # The marker names the CALL, not the function: 37a's own `def
    # ungroup_compliance_lines(` would match a looser pattern and make this
    # report itself as applied while the function never ran. Same trap as
    # 30b, 20a and the '1.13.0' collision.
    # Fix 37 changes the compiled brief (a requirement leaves a choice
    # group), so the BRIEF artifact changes and its version must move IN THE
    # SAME EDIT. bump() could not do it: its marker was already satisfied by
    # the VERDICT bump, so it reported "already in" and skipped.
    patch(cells, '40a obligation: does the brief DEMAND or OFFER these?',
          'def detect_obligation', fix40a)
    patch(cells, '40b ...and the compiled brief records it',
          "'claims_obligation':", fix40b)
    # MUST follow 37a: it rewrites the regex 37a inserts.
    patch(cells, '44 audit_group_intents handles BOTH shapes too',
          "m.group_intent_original = intent", fix44)
    # MUST follow 44: it restructures what 44 inserted.
    patch(cells, '45 say the both-shapes handling as if/else',
          "            else:\n                m.setdefault('flags', [])", fix45)
    patch(cells, '43 the compliance ungroup must mutate BOTH shapes',
          'r.group_label, r.group_intent', fix43)
    patch(cells, '41 a compliance line is not only an FDA line',
          '_DISCLAIMER_SHAPE', fix41)
    patch_all(cells, '37c BRIEF_STAGE_VERSION 1.25.0 (grouping + obligation + cues)',
              "BRIEF_STAGE_VERSION  = '1.25.0'",
              lambda t: (t.replace("BRIEF_STAGE_VERSION  = '1.24.0'",
                                   "BRIEF_STAGE_VERSION  = '1.25.0'")
                         .replace("BRIEF_STAGE_VERSION = '1.24.0'",
                                  "BRIEF_STAGE_VERSION = '1.25.0'"))
              if "1.24.0" in t else None)
    patch(cells, '37b ...and it actually RUNS on the compile',
          '_compliance = ungroup_compliance_lines', fix37b)
    # 16b MUST follow 14b: it anchors on the comment 14b inserts. Scheduling
    # it earlier failed loudly rather than silently, which is the point of
    # patch() asserting its match.
    patch(cells, '16a product claims -> requirements, deterministically',
          'def requirements_from_claims', fix16a)
    patch(cells, '16b ...and it runs on the compile',
          '_from_claims = requirements_from_claims', fix16b)
    # MUST follow 16a: it edits the function 16a inserts.
    patch(cells, '31 a claim carries its DEFINITION, not just its label',
          'def _claim_definition', fix31)
    patch(cells, '33 substance credit applies to PARTIAL, not only FAIL',
          "if v.status not in ('FAIL', 'PARTIAL')", fix33)
    patch(cells, '34 L3: the ASK first, the menu option as an example',
          'THE ASK       :', fix34)
    # MUST follow 34: it suppresses the block 34 makes redundant.
    patch(cells, '34b no duplicate intent; hints are scoped to the option',
          'if _intent and not _gintent:', fix34b)
    patch(cells, '20b sentinel for the hosted-provider bypass',
          'class _SkipAffordability', fix20b)
    # The marker names text 20a ITSELF inserts. It used to name the
    # `_p3_local = ...` assignment, which fix 21 then took ownership of and
    # reworded -- and a marker that another fix can move is not a marker.
    patch(cells, '20a hosted vision is not limited by local VRAM',
          'raise _SkipAffordability()', fix20a)
    # MUST follow 20a: it rewords the line 20a inserts and owns _p3_local.
    patch(cells, '21 a degraded cached visual is not a hit on a hosted run',
          'ignoring a DEGRADED cached visual', fix21)
    patch(cells, '22 _visual_keys rebuilds the key the WRITER actually uses',
          "'vlm': _planned_vlm}))", fix22)
    # MUST follow 22: it stubs the function fix 22 made _visual_keys call.
    patch(cells, '24 §60 stub covers plan_vlm_load, which fix 22 added',
          "'plan_vlm_load': lambda c, *a, **k:", fix24)
    patch(cells, '23a no hint signal -> rank by MEANING, not by the clock',
          'def spread_sample', fix23a)
    patch(cells, '23b embeddings are cached, so re-ranking is nearly free',
          '_EMBED_CACHE', fix23b)
    # MUST follow 23a: it wraps the return 23a rewrote.
    patch_all(cells, '36 one modality may not take every candidate slot',
              '_balance_modalities', fix36)
    patch(cells, '19 L3: an absence is a FAIL, not an UNCERTAIN',
          'She never mentions it" is a FAIL', fix19)
    patch(cells, '17a standing: judge a silent video from text + visuals',
          'STANDING_WITHOUT_SPEECH', fix17a)
    patch(cells, '17b angle: same rule',
          'ANGLE_WITHOUT_SPEECH', fix17b)
    patch(cells, '18 §71: the angle test follows the new gate',
          'a SILENT video with text/visuals is not refused outright', fix18)
    patch_all(cells, '18b an abstention keeps the flags already recorded',
              "flags=out['flags'] + ['ANGLE_NOT_JUDGED']", fix18b)
    patch(cells, '13 L2 cites the record id, not the wrapper dict',
          "evidence_ids=[c['record'].id for c in top]", fix13)
    patch(cells, '10 claims sections are SCORED, not only allowlisted',
          "if sec.kind == 'context':", fix10)
    patch(cells, '10b decomposition_health counts claims lines too',
          "if s.kind != 'context' for l in s.lines", fix10b)
    patch(cells, '11a §47: benefit bullets DO become requirements',
          'benefit bullets DO become requirements now', fix11a)
    patch(cells, '11b §47: plain-text claims become requirements too',
          'claims lines become requirements here too', fix11b)
    patch(cells, '12  talking points: fuzzy match off the SCORING path',
          'PROVENANCE ONLY -- this must not change the scoring shape', fix12)
    patch(cells, '12b §47: the flag is provenance, not grouping',
          'no approved_talking_points group is created any more', fix12b)
    patch(cells, '9a Requirement carries group_intent_original',
          'group_intent_original: str', fix9a)
    patch(cells, '9b Requirement() filters unknown fields, like EvidenceRecord',
          'UNKNOWN_FIELD_DROPPED', fix9b)
    # The marker is fix 8's own COMMENT, not the model name it sets: fix 25
    # re-measures and replaces that name, which would otherwise make fix 8's
    # marker vanish and trip the post-condition.
    patch(cells, '8  model ladder tries the one that serves FIRST',
          'ORDER IS MEASURED, NOT ALPHABETICAL', fix8)
    # MUST follow 8: it supersedes the order fix 8 set, with a fresh measurement.
    patch(cells, '25 re-measured: flash-lite is not down, it is 8x slower',
          "hosted_model: str = 'gemini-3.5-flash'", fix25)
    patch(cells, '26 NO LIVE KEY IN THE SOURCE  (rotate the old ones!)',
          'NO KEY IN THIS FILE, EVER', fix26)
    # MUST follow 26: it gives 26's silent hoist a voice.
    patch(cells, '35 §37a says WHY it found no key, where you can fix it',
          '_KEY_WHERE', fix35)
    patch(cells, '27 probe the models, then pick a working one automatically',
          'def probe_hosted_models', fix27)
    patch(cells, '28 stale hosted-vision fallback would mis-key an artifact',
          "or ('gemini-flash-lite-latest',))[0]", fix28)
    patch(cells, '29 Phase 3 vision probes for a model that really sees',
          'def probe_vision_models', fix29)
    patch(cells, '30a classify a total probe failure: key / quota / servers',
          'def key_failure_verdict', fix30a)
    # patch_all: the text probe and the vision probe are in different cells
    # and share the same tail. patch() would fix one and leave the other.
    # The marker must be text 30b ITSELF inserts: 30a already defines
    # `key_failure_verdict`, so keying on that name would make 30b report
    # itself as already applied and silently skip BOTH probes.
    patch_all(cells, '30b both probes report that verdict',
              '_errs.append(err)', fix30b)
    patch(cells, '7a the audit actually runs (single-shot compile)',
          "audit_group_intents(compiled['requirements'])", fix7a)
    patch(cells, '7b the audit actually runs (consensus compile)',
          '_blind_intents', fix7b)
    patch_all(cells, '5  stage + prompt versions bumped',
              "VERDICT_STAGE_VERSION = '1.22.0'", bump)

    # ---- post-condition: every marker must now be true -------------------
    # Checked BEFORE the write, so a patcher that cannot prove its own work
    # leaves the notebook untouched rather than half-edited.
    _after = ''.join(_src(c) for c in cells if c['cell_type'] == 'code')
    _lying = [(n, mk) for n, mk in MARKERS if mk not in _after]
    if _lying:
        print('  MARKER DOES NOT HOLD AFTER APPLYING -- notebook NOT written:')
        for n, mk in _lying:
            print(f'    {n}\n      marker {mk!r} appears nowhere in the result.')
        raise SystemExit('  A marker must name text the fix itself emits. '
                         'Fix the marker, not the notebook.')

    NB.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'\n  {NB.name}')
    for a in applied:
        print(f'    APPLIED  {a}')
    for a in skipped:
        print(f'    already in  {a}')
    txt = NB.read_text(encoding='utf-8')
    moji = {m: txt.count(m) for m in ('\u00c2\u00a7', '\u00e2\u20ac\u201d')
            if txt.count(m)}
    print(f'    {NB.stat().st_size / 1e6:.2f} MB   '
          f'section signs: {txt.count(S)}   mojibake: {moji or "none"}')
    for label, pat in (('BRIEF_STAGE_VERSION', r"BRIEF_STAGE_VERSION\s*= '([\d.]+)'"),
                       ('BRIEF_PROMPT_VERSION', r"BRIEF_PROMPT_VERSION\s*= '([\w]+)'"),
                       ('VERDICT_STAGE_VERSION', r"VERDICT_STAGE_VERSION\s*= '([\d.]+)'")):
        found = re.findall(pat, txt)
        print(f'    {label:<22} {found[0] if found else "?"}')


if __name__ == '__main__':
    main()

