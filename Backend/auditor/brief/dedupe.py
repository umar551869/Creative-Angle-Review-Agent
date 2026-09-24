"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 98.
Regenerate with:  python Backend/tools/extract_from_notebook.py

Bodies are VERBATIM. The only removal is the notebook's driver
statements (the lines that run a stage and print a table); those
are listed at the foot of this file and are replaced by
Backend/app/services/.

This file is LOADED BY auditor.runtime, not imported directly.
The notebook shares one global namespace and binds some names
late (globals().get(...)), so the loader reproduces that exactly
rather than guessing an import graph that the original never had.
"""
# More specific beats less specific when two requirements merge.
_MODE_SPECIFICITY = {'any': 0, 'speech_or_text': 1, 'ocr_only': 2,
                     'visual_only': 2, 'speech_only': 2, 'visual_and_speech': 3}

def _similar(a: str, b: str, min_ratio: int) -> bool:
    try:
        from rapidfuzz import fuzz
        if fuzz.ratio(a.lower(), b.lower()) >= min_ratio:
            return True
    except Exception:
        pass
    try:
        ta, tb = set(content_tokens(a)), set(content_tokens(b))
    except Exception:
        ta = set(re.findall(r'[a-z0-9]{3,}', a.lower()))
        tb = set(re.findall(r'[a-z0-9]{3,}', b.lower()))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.8

def dedupe_requirements(reqs: list, cfg: BriefConfig = None) -> tuple:
    """
    (kept, flags). Merging is LOSSLESS -- the same lesson as Phase 3's event merge,
    where keeping only the longest description destroyed facts a requirement could
    turn on. Absorbed requirements are recorded in merged_from.
    """
    cfg = cfg or P4.brief
    kept, flags = [], []
    for r in reqs:
        dup = None
        # Alternatives are SUPPOSED to resemble each other -- three CTA lines all
        # say roughly "buy this". Merging them would collapse a choice into a
        # single mandatory line and reintroduce the false-FAIL this fixes.
        if not (r.group and r.group_mode in ('one_of', 'any_of')):
            for k in kept:
                if k.group and k.group_mode in ('one_of', 'any_of'):
                    continue
                if k.type == r.type and _similar(k.requirement, r.requirement,
                                                 cfg.dedupe_min_ratio):
                    dup = k
                    break
        if dup is None:
            kept.append(r)
            continue
        # keep the STRICTER of the two on every axis
        if PRIORITY_WEIGHT[r.priority] > PRIORITY_WEIGHT[dup.priority]:
            dup.priority, dup.weight = r.priority, r.weight
        if _MODE_SPECIFICITY.get(r.evidence_mode, 0) > _MODE_SPECIFICITY.get(dup.evidence_mode, 0):
            dup.evidence_mode = r.evidence_mode
        if r.deadline_seconds is not None:
            dup.deadline_seconds = (r.deadline_seconds if dup.deadline_seconds is None
                                    else min(dup.deadline_seconds, r.deadline_seconds))
        if r.window_start_expr and not dup.window_start_expr:
            dup.window_start_expr, dup.window_end_expr = r.window_start_expr, r.window_end_expr
        for h in r.match_hints:
            if h not in dup.match_hints:
                dup.match_hints.append(h)
        for c in r.acceptance_criteria:
            if c not in dup.acceptance_criteria:
                dup.acceptance_criteria.append(c)
        for c in r.claim_classes:
            if c not in dup.claim_classes:
                dup.claim_classes.append(c)
        dup.flags.append(f'MERGED_FROM:{r.id}')
        flags.append({'code': 'DUPLICATE_MERGED',
                      'detail': f'{r.id} ({r.label}) into {dup.id} ({dup.label})'})
    # A one_of group with a single member is a no-op that reads like a choice.
    # It happens when a model collapses twelve hooks into one requirement but
    # still tags it with a group id. Left alone it inflates the group count,
    # makes the review table claim "CHOOSE ONE of 1", and tells Phase 6 that a
    # lone mandatory requirement is optional.
    sizes = {}
    for r in kept:
        if r.group:
            sizes[r.group] = sizes.get(r.group, 0) + 1
    for r in kept:
        if r.group and sizes.get(r.group, 0) < 2:
            r.flags.append(f'GROUP_OF_ONE:{r.group}->all_of')
            flags.append({'code': 'GROUP_OF_ONE',
                          'detail': f'{r.id} was the only member of "{r.group}"; '
                                    f'demoted to all_of -- a choice needs alternatives'})
            r.group, r.group_mode, r.group_label = None, 'all_of', ''

    for i, r in enumerate(kept, 1):
        r.ordinal = i
    return kept, flags

def _req_field(r, key: str, default=''):
    """Read a requirement field whether it is a Requirement or a plain dict.

    compile_brief holds Requirement objects; the consensus artifact holds the
    dicts they became. Conflicts have to be computed in BOTH places -- once on
    the run, once on the merged set that actually ships -- so the detector has
    to accept either.
    """
    if isinstance(r, dict):
        return r.get(key, default)
    return getattr(r, key, default)

def is_figure_fidelity_requirement(r) -> bool:
    """A 'figures must match the brief' rule, as opposed to a word blacklist.

    The distinction is visible in the hints: a figures rule's hints are numbers,
    a medical-claims rule's hints are words. Phase 6's l1_figure_fidelity uses
    the same test on the same field; the two are deliberately trivial so they
    cannot drift.
    """
    if (_req_field(r, 'polarity', 'required') or 'required') != 'forbidden':
        return False
    hints = [str(h) for h in (_req_field(r, 'match_hints', None) or [])]
    if not hints:
        return False
    numeric = [h for h in hints if any(c.isdigit() for c in h)]
    return len(numeric) * 2 >= len(hints)

def adopt_stray_asks(reqs: list, sections: list) -> list:
    """An ask written outside the list it belongs to joins that list's group.

    A brief lists twelve sample hooks under one heading and then says "use a
    hook like these" in a sentence elsewhere. The list becomes a one_of group
    and collapses to its best member. The loose sentence becomes an ORDINARY
    requirement and is scored as independently mandatory, so a creator who used
    one good hook FAILs the stray for not also using it.

    brief_span records the sentence each requirement was built from. If that
    sentence sits inside a section that already produced a choice group, the
    requirement is another way of making that same choice.

    Conservative: it joins only when the span is found in EXACTLY one section,
    so ambiguity changes nothing. Idempotent: an already-grouped requirement is
    skipped, which is what lets it run again on the merged consensus set.

    Accepts Requirement objects or their dicts, because it runs in both places.
    """
    groups_by_heading = {}
    for r in reqs:
        if _req_field(r, 'group') and _req_field(r, 'group_label'):
            groups_by_heading.setdefault(_req_field(r, 'group_label'), r)
    if not groups_by_heading:
        return []
    sec_text = {s.heading: normalize_text(' '.join(s.lines)) for s in sections}
    adopted = []
    for r in reqs:
        if _req_field(r, 'group') or not _req_field(r, 'brief_span'):
            continue
        span = normalize_text(_req_field(r, 'brief_span'))[:70]
        if len(span) < 12:
            continue
        # The length guard is the partial_ratio asymmetry again: rapidfuzz
        # slides the SHORTER string over the longer, so a section shorter than
        # the span would become the pattern and match almost anything.
        hits = [h for h, t in sec_text.items()
                if span in t or (len(t) >= len(span)
                                 and fuzz.partial_ratio(span, t) >= 92)]
        if len(hits) != 1:
            continue
        host = groups_by_heading.get(hits[0])
        if host is None:
            continue
        for _f in ('group', 'group_mode', 'group_label', 'group_intent'):
            _v = _req_field(host, _f)
            if isinstance(r, dict):
                r[_f] = _v
            else:
                setattr(r, _f, _v)
        _fl = list(_req_field(r, 'flags') or []) + [
            f'ADOPTED_INTO_GROUP:{str(_req_field(host, "group_label"))[:40]}']
        if isinstance(r, dict):
            r['flags'] = _fl
        else:
            r.flags = _fl
        adopted.append(r)
    return adopted

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
    return {w for w in re.sub(r"[^\w\s'\u2019-]", ' ', (text or '').lower()).split()
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
            else:
                m.setdefault('flags', [])
                if 'GROUP_INTENT_SUBJECT_FREE' not in m['flags']:
                    m['flags'].append('GROUP_INTENT_SUBJECT_FREE')
                if _opts:
                    m['group_intent_original'] = intent
                    m['group_intent'] = _repaired[:1200]
                    if 'GROUP_INTENT_REPAIRED' not in m['flags']:
                        m['flags'].append('GROUP_INTENT_REPAIRED')
    return flagged

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

# A legal disclaimer is never one of a menu of options.
# Regulated wording, across the verticals UGC actually runs in. A word list
# alone can never be complete, which is why _DISCLAIMER_SHAPE exists beside it.
_DISCLAIMER_RE = re.compile(
    r'('
    # health / supplements
    r'have\s+not\s+been\s+evaluated\s+by\s+the\s+(food\s+and\s+drug|fda)'
    r'|not\s+intended\s+to\s+(diagnose|treat|cure|prevent)'
    r'|these\s+statements\s+have\s+not\s+been'
    r'|not\s+(medical|health)\s+advice|consult\s+(your|a)\s+'
    r'(doctor|physician|healthcare|gp|pharmacist)'
    r'|individual\s+results|results\s+(may|can)\s+vary'
    r'|not\s+a\s+substitute\s+for'
    # finance
    r'|past\s+performance|capital\s+at\s+risk|not\s+(financial|investment)\s+advice'
    r'|investments?\s+can\s+go\s+down|your\s+capital\s+is\s+at\s+risk'
    # age-gated / regulated goods
    r'|drink\s+responsibly|gamble\s+responsibly|please\s+gamble'
    r'|\b(18|21)\s*\+|over\s+(18|21)s?\s+only'
    # paid-partnership disclosure -- mandatory for UGC in every vertical
    r'|#\s?ad\b|#\s?sponsored\b|paid\s+partnership|paid\s+promotion'
    r'|sponsored\s+by|gifted\s+by|in\s+partnership\s+with'
    # generic
    r'|terms\s+(and|&)\s+conditions\s+apply|t\s?&\s?cs?\s+apply'
    r'|always\s+read\s+the\s+label|use\s+only\s+as\s+directed'
    r')', re.I)

# SHAPE, not wording. A footnote marker or an explicit label says "this is
# boilerplate the brand must carry" in any vertical and any language of
# business, and it keeps working when the word list does not.
_DISCLAIMER_SHAPE = re.compile(
    r'^\s*(\*+|\u2020|\u2021)\s*\S'
    r'|^\s*(disclaimer|legal|mandatory|compliance|disclosure)\s*[:\-\u2013]',
    re.I)

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
        _sec = str(_req_field(r, 'group_label') or '')
        _in_legal_section = bool(re.search(
            r'\b(legal|disclaimer|compliance|mandator\w+|disclosure|'
            r'fine\s*print|small\s*print)\b', _sec, re.I))
        if not (_DISCLAIMER_RE.search(txt)
                or _DISCLAIMER_SHAPE.search(txt.lstrip())
                or _in_legal_section):
            continue
        gid = _req_field(r, 'group')
        if not gid:
            continue
        moved.append((_req_field(r, 'id'), gid))
        # BOTH SHAPES: a dataclass on the compile path, a dict after
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
                f'UNGROUPED_COMPLIANCE_LINE:{gid}']
    return moved

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

# ---------------------------------------------------------------------------
# The brief's product claims are parsed, not generated -- so they are turned
# into requirements here rather than being asked for and hoped for.
# ---------------------------------------------------------------------------
def _claim_definition(text: str, head: str) -> str:
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
        rest = re.sub(r'\s*\(include as [^)]*\)\s*', ' ', rest, flags=re.I)
        rest = ' '.join(rest.split())
        if len(rest) >= 8 and rest.lower() != (head or '').lower():
            return rest[:240]
    return ''

def _claim_headline(text: str) -> str:
    """The label half of "Label: explanation", else the first clause.

    Brief features are written "Gentle & Non-Habit-Forming: Melatonin-free
    formula ensures safe nightly use". The half before the colon is the ask;
    the rest is the brand explaining it to the creator.
    """
    t = (text or '').strip()
    head = t.split(':', 1)[0].strip() if ':' in t[:80] else t
    head = re.sub(r'\s*\(include as [^)]*\)\s*', ' ', head, flags=re.I)
    head = re.sub(r'[*\u2022]+', ' ', head)
    return ' '.join(head.split())[:120] or t[:120]

# A product feature can be communicated by SAYING it or by SHOWING it.
# 'speech_or_text' already covers OCR, so the only channel it excluded was the
# VLM's view of the screen -- and on a brief whose features are colour-coded
# rows and a 21-compartment tray, that is the channel that carries them.
CLAIM_EVIDENCE_MODE = 'any'

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
        _defn = _claim_definition(ctext, head)
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
            # 'any' -- she may SAY the feature or SHOW it. See fix 49;
            # set CLAIM_EVIDENCE_MODE to 'speech_or_text' to revert.
            'polarity': 'required',
            'evidence_mode': globals().get('CLAIM_EVIDENCE_MODE', 'any'),
            'machine_checkable': True,
            # Ungrouped ON PURPOSE: each claim is its own scoring unit, so
            # "3 of 8 covered" is a real number rather than "she mentioned
            # at least one thing".
            'group': None, 'group_mode': 'all_of', 'group_label': '',
            'group_intent': '', 'group_intent_original': '',
            'deadline_seconds': None, 'window_start_expr': None,
            'window_end_expr': None, 'brief_span': ctext[:300],
            'confidence': 1.0, 'source': 'approved_claims',
            # What the brief says this feature MEANS. Fed to _req_query_text
            # (so L2 retrieves on meaning) and printed in the L3 prompt as
            # "what would make this pass". NOT match_hints -- see below.
            'acceptance_criteria': ([f'The creator communicates this feature '
                                     f'in her own words. The brief defines it '
                                     f'as: {_defn}']
                                    if _defn else []),
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

def normalise_group_intents(reqs: list) -> list:
    """One group, one ASK. Returns the labels it had to reconcile.

    group_intent is what L3 judges alignment against -- "what KIND of ask are
    these options examples of". It is a property of the GROUP, so every member
    must carry the same one.

    Measured on a live compile: stats reported choice_groups=3 while the
    artifact carried four distinct (group_label, group_intent) pairs, so one
    group id held two intents. Two members of one choice group were asked
    different questions and then compared to pick a winner, which is not a
    comparison.

    The winner is the most common wording, then the longest -- a truncation
    loses to the full sentence. Deterministic, and it never invents an intent
    for a group that had none.
    """
    by_group = {}
    for r in reqs:
        g = _req_field(r, 'group')
        if g:
            by_group.setdefault(g, []).append(r)
    reconciled = []
    for g, members in by_group.items():
        for field in ('group_intent', 'group_label'):
            vals = [str(_req_field(m, field) or '').strip() for m in members]
            seen = [v for v in vals if v]
            if len(set(seen)) <= 1:
                continue
            best = max(set(seen), key=lambda s: (seen.count(s), len(s)))
            for m in members:
                if isinstance(m, dict):
                    m[field] = best
                else:
                    setattr(m, field, best)
            reconciled.append(f'{g}:{field}({len(set(seen))} variants)')
    return reconciled

def detect_conflicts(reqs: list) -> list:
    """
    Contradictions the compiler cannot resolve, surfaced for the human.

    A brief assembled from a marketing template plus a legal appendix genuinely
    can say "mention the discount" and "do not mention pricing". That is an
    ambiguity in the SOURCE, so it is reported, never silently resolved.

    Accepts Requirement objects or their dicts, because it runs twice: once on
    a single compile, and again on the merged set consensus actually ships.
    """
    # Words that co-occur in any two sentences about the same product and carry
    # no subject at all. Sharing these is not evidence of anything -- on a hair
    # brief, "even" and "everyday" matched two unrelated lines and produced a
    # contradiction that a human then has to read and dismiss. A conflict
    # detector that cries wolf gets ignored, and a real conflict walks through.
    _WEAK = {'even', 'everyday', 'every', 'day', 'days', 'thing', 'things', 'know',
             'like', 'just', 'get', 'got', 'make', 'made', 'really', 'also',
             'video', 'videos', 'creator', 'creators', 'content', 'product',
             'products', 'brand', 'use', 'used', 'using', 'one', 'way', 'time'}
    out = []
    for i, a in enumerate(reqs):
        for b in reqs[i + 1:]:
            pa = _req_field(a, 'polarity', 'required') or 'required'
            pb = _req_field(b, 'polarity', 'required') or 'required'
            if pa == pb:
                continue
            # A figure-fidelity rule constrains HOW a figure is stated, never
            # WHETHER a subject is mentioned, so it cannot contradict a
            # requirement to state that figure -- the two are written to work
            # together. Measured on a live compile: "state 1500 home studies,
            # 21 days, 86% satisfaction" and "any figure you state must match
            # 1500, 21 days, 86%" were reported as a contradiction because they
            # share the figures. They agree; sharing the numbers is the point.
            #
            # An ordinary prohibition is still checked: "do not mention
            # pricing" carries word hints, not numeric ones, so it does not
            # take this exit.
            if is_figure_fidelity_requirement(a) or is_figure_fidelity_requirement(b):
                continue
            ra = _req_field(a, 'requirement', '') or ''
            rb = _req_field(b, 'requirement', '') or ''
            try:
                ta, tb = set(content_tokens(ra)), set(content_tokens(rb))
            except Exception:
                ta = set(re.findall(r'[a-z0-9]{3,}', ra.lower()))
                tb = set(re.findall(r'[a-z0-9]{3,}', rb.lower()))
            ta, tb = ta - _WEAK, tb - _WEAK
            shared = ta & tb
            if not ta or not tb:
                continue
            # Proportion, not count. Two long sentences share two words by
            # accident; two short ones sharing most of their content words are
            # talking about the same thing.
            overlap = len(shared) / min(len(ta), len(tb))
            if len(shared) >= 2 and overlap >= 0.5:
                req, forb = (a, b) if pa == 'required' else (b, a)
                rid, fid = _req_field(req, 'id'), _req_field(forb, 'id')
                out.append({'code': 'POLARITY_CONFLICT',
                            'detail': f'{rid} requires and {fid} forbids '
                                      f'overlapping subject: {sorted(shared)[:4]} '
                                      f'({overlap:.0%} of the shorter requirement)',
                            'requirement_ids': [rid, fid]})
    # same id twice would break every downstream join
    seen = {}
    for r in reqs:
        rid, lbl = _req_field(r, 'id'), _req_field(r, 'label')
        if rid in seen:
            out.append({'code': 'DUPLICATE_ID',
                        'detail': f'{rid} used by "{seen[rid]}" and "{lbl}"',
                        'requirement_ids': [rid]})
        seen[rid] = lbl
    return out

def decomposition_health(reqs: list, brief_text: str, cfg: BriefConfig = None) -> dict:
    """A 3-line brief that became 12 requirements triple-counts one ask in the score."""
    cfg = cfg or P4.brief
    # Count only lines that could BECOME a requirement. Counting a document's
    # headings and its Purpose paragraph inflates the denominator and hides real
    # over-decomposition behind a brief that simply had a lot of prose in it.
    try:
        # claims lines DO become requirements now (fix 10), so they count
        # toward the denominator. Excluding them would read the talking-point
        # requirements as over-decomposition of a brief that never got credit
        # for those lines in the first place.
        lines = [l for s in parse_brief_sections(brief_text)
                 if s.kind != 'context' for l in s.lines]
    except Exception:
        lines = [l for l in (brief_text or '').splitlines()
                 if l.strip() and not _looks_like_heading(l)]
    n_lines = max(1, len(lines))
    ratio = len(reqs) / n_lines
    flags = []
    if ratio > cfg.over_decomposition_ratio:
        flags.append({'code': 'OVER_DECOMPOSED',
                      'detail': f'{len(reqs)} requirements from {n_lines} brief lines '
                                f'(ratio {ratio:.1f} > {cfg.over_decomposition_ratio})'})
    if len(reqs) < n_lines * 0.4:
        flags.append({'code': 'UNDER_DECOMPOSED',
                      'detail': f'only {len(reqs)} requirements from {n_lines} brief lines'})
    return {'brief_lines': n_lines, 'requirements': len(reqs),
            'ratio': round(ratio, 2), 'flags': flags}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 756: print('§44 dedupe + conflict detection loaded.')
