"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 122.
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
def _fail_allowed(rd: dict, health: dict) -> bool:
    """
    May a FAIL be asserted for this requirement's evidence_mode at all?

    plan.md §6.2: a FAIL asserts something, so it needs positive grounds. If the
    modality was degraded or never ran, absence is not evidence of absence.
    """
    return bool(modes_that_can_fail(health or {}).get(
        rd.get('evidence_mode') or 'any', False))

def _fail_or_uncertain(rd: dict, health: dict, reason_fail: str,
                       reason_uncertain: str, layer: str,
                       ids=None, **kw) -> Verdict:
    """
    THE only way a FAIL is constructed anywhere in Phase 6.

    Routing the decision through one function is what makes the guarantee
    checkable: there is no second place where a FAIL could be written without
    consulting can_fail_on.
    """
    if _fail_allowed(rd, health):
        return _blank_verdict(rd, 'FAIL', reason_fail, layer,
                              evidence_ids=list(ids or []), **kw)
    mode = rd.get('evidence_mode') or 'any'
    bad = [m for m in MODALITIES
           if m != 'metadata' and not can_fail_on(health or {}, m)]
    return _blank_verdict(
        rd, 'UNCERTAIN',
        f'{reason_uncertain} A FAIL is not supportable: evidence_mode '
        f'{mode!r} needs {", ".join(bad) or "a modality"} to have run cleanly, '
        f'and it did not.',
        layer, evidence_ids=list(ids or []),
        flags=['FAIL_BLOCKED_BY_MODALITY_HEALTH'], **kw)

def _fmt_t(rec) -> str:
    tol = rec.time_tolerance_seconds or 0.0
    return f'{rec.start_seconds:.2f}s' + (f' +-{tol:.2f}s' if tol else '')

def l1_forbidden(rd: dict, cands: list, health: dict,
                 cfg: Phase6Config = None) -> Optional[Verdict]:
    """
    A `forbidden` requirement is inverted: finding the thing is the FAILURE.

    Note the asymmetry -- finding forbidden text is POSITIVE evidence and can
    always FAIL, regardless of modality health, because we are not reasoning
    from absence. Not finding it is the absence case, and that is gated.
    """
    cfg = cfg or P6
    if (rd.get('polarity') or 'required') != 'forbidden':
        return None
    terms = [t for t in (list(rd.get('forbidden_evidence') or [])
                         + list(rd.get('match_hints') or []))
             if len((t or '').strip()) >= cfg.l1.min_hint_len]
    hits = []
    for c in cands:
        rec = c['record']
        hay = f'{rec.norm_text} {rec.description}'.lower()
        for t in terms:
            matched, r = _term_hit(t, hay, cfg.l1.forbidden_fuzzy_min)
            if matched:
                hits.append((rec, t, r))
                break
    if hits:
        rec, t, r = hits[0]
        # Finding something is POSITIVE evidence, not an argument from absence,
        # so the mode-wide gate does not apply -- but the modality that carried
        # it still has to be trustworthy. A degraded OCR pass that misreads a
        # word must not be able to assert a policy breach.
        if not can_fail_on(health or {}, rec.modality):
            return _blank_verdict(
                rd, 'UNCERTAIN',
                f'Possible forbidden content: {t!r} appears in {rec.modality} '
                f'evidence at {_fmt_t(rec)}, but that modality was degraded, so '
                f'the reading is not reliable enough to assert a breach.',
                'L1', evidence_ids=[h[0].id for h in hits],
                flags=['FORBIDDEN_HIT_ON_DEGRADED_MODALITY'],
                candidates_considered=len(cands))
        return _blank_verdict(
            rd, 'FAIL',
            f'Forbidden content found: {t!r} matches {rec.modality} evidence at '
            f'{_fmt_t(rec)} ({r}% match): '
            f'"{(rec.raw_text or rec.description)[:90]}"',
            'L1', evidence_ids=[h[0].id for h in hits],
            confidence=r / 100.0, confidence_kind='derived',
            # Marks a FAIL grounded in evidence we HAVE rather than evidence we
            # looked for and did not find. §73 treats the two differently.
            flags=[f'FAIL_FROM_POSITIVE_EVIDENCE:{rec.modality}'],
            candidates_considered=len(cands))
    # Absence of the forbidden thing -- THIS is reasoning from absence.
    #
    # Cite the records that were EXAMINED. "Nothing forbidden here" is a claim
    # about a specific set of evidence, and without the ids nobody can check
    # which set. Measured in a live run: this PASS came back with no citations
    # at all and tripped §73's "every PASS cites at least one record".
    checked = [c['record'].id for c in cands]
    if not checked:
        # Nothing was examined, so "nothing forbidden is present" is not a
        # finding -- it is silence. A PASS here would also be uncitable, which
        # is the same defect wearing a different hat.
        return _blank_verdict(
            rd, 'UNCERTAIN',
            f'No admissible {rd.get("evidence_mode")} evidence was retrieved, so '
            f'the absence of forbidden content cannot be established.',
            'L1', flags=['NOTHING_EXAMINED'], candidates_considered=0)
    if not _fail_allowed(rd, health):
        return _fail_or_uncertain(
            rd, health,
            reason_fail='',                   # never reached: absence here is a PASS
            reason_uncertain=f'No forbidden content was found across '
                             f'{len(cands)} retrieved record(s).',
            layer='L1', ids=checked[:5], candidates_considered=len(cands))
    return _blank_verdict(
        rd, 'PASS',
        f'No forbidden content found across {len(cands)} candidate record(s) in '
        f'a modality that ran cleanly'
        + (f'; checked {", ".join(checked[:3])}'
           + (f' and {len(checked) - 3} more' if len(checked) > 3 else '')
           if checked else ' -- no admissible evidence was retrieved'),
        'L1', evidence_ids=checked[:5],
        # Earned by ABSENCE, not by anything the creator did. §70 uses this to
        # refuse an alignment: there is nothing here to be close to.
        flags=['PASS_FROM_ABSENCE'],
        candidates_considered=len(cands))

# Modes that require evidence in MORE THAN ONE modality, and which.
# product.md §37 / plan.md §6.5: visual_and_speech means both were asked for, so
# one of them is a PARTIAL, not a PASS.
CONJUNCTIVE_MODES = {'visual_and_speech': ('visual', 'speech')}

def _modalities_present(cands: list) -> set:
    return {c['record'].modality for c in cands}

def _conjunctive_shortfall(rd: dict, cands: list) -> tuple:
    """
    (missing, required) for a mode that needs two modalities. ((), ()) otherwise.

    Without this, a `visual_and_speech` requirement PASSes on a single spoken
    word, because Phase 5 marks a speech record as ABLE to satisfy the mode --
    correctly, since it can CONTRIBUTE to it. What a record may contribute to
    and what a requirement needs are different questions, and only the second
    one is being asked here.
    """
    need = CONJUNCTIVE_MODES.get(rd.get('evidence_mode') or '')
    if not need:
        return (), ()
    have = _modalities_present(cands)
    return tuple(m for m in need if m not in have), need

def l1_phrase(rd: dict, cands: list, health: dict,
              cfg: Phase6Config = None) -> Optional[Verdict]:
    """Fuzzy phrase match on match_hints. Answers PASS/PARTIAL, or escalates."""
    cfg = cfg or P6
    hints = [h for h in (rd.get('match_hints') or [])
             if len((h or '').strip()) >= cfg.l1.min_hint_len]
    if not hints:
        return None
    best = [c for c in cands if c['hint_score'] >= cfg.l1.fuzzy_min]
    if not best:
        return None                            # let L2/L3 try paraphrase
    c = best[0]
    # A hint that cannot tell two options apart must not decide between them.
    #
    # _hint_score describes itself as "a ranking signal, never an exclusion",
    # and it is right to score generously: _term_hit returns 100 for a plain
    # word-boundary match, which is what makes it useful for ORDERING
    # candidates. Turning that same 100 into a PASS is the mistake.
    #
    # Measured: the compiler writes match_hints as the option's sentence on some
    # runs and as keywords on others -- one artifact carried 46 single-word
    # hints out of 48. On a keyword run, twelve hook options each matched the
    # word "hair" at 100, all twelve returned PASS, _L1_ALIGNMENT labelled every
    # one of them `exact` ("the requirement's own wording was matched"), and the
    # group then picked its winner on confidence, which was a tie. The audit
    # reported a hook the creator never used, with a healthy-looking score.
    #
    # Inside a one_of/any_of group the entire job is telling near-identical
    # options apart, so L1 requires a PHRASE. A single word sends the group to
    # L3, which is what earlier runs did -- and those came back with
    # differentiated strong/tangential readings instead of twelve identical
    # exacts. Outside a group there is nothing to discriminate between: "say the
    # brand name" is honestly satisfied by one word, so that path is unchanged.
    if (rd.get('group') and rd.get('group_mode') in ('one_of', 'any_of')
            and ' ' not in (c.get('hint') or '').strip()):
        return None
    rec = c['record']
    ids = [r['record'].id for r in best[:3]]
    missing, need = _conjunctive_shortfall(rd, best)
    if missing:
        return _blank_verdict(
            rd, 'PARTIAL',
            f'{rec.modality} evidence at {_fmt_t(rec)} matches {c["hint"]!r} '
            f'({c["hint_score"]}%), but this requirement asks for '
            f'{" and ".join(need)} and no {" or ".join(missing)} evidence '
            f'supports it: "{(rec.raw_text or rec.description)[:90]}"',
            'L1', evidence_ids=ids,
            confidence=c['hint_score'] / 100.0, confidence_kind='derived',
            flags=[f'MODE_SHORTFALL:{",".join(missing)}'],
            candidates_considered=len(cands))
    return _blank_verdict(
        rd, 'PASS',
        f'{rec.modality} evidence at {_fmt_t(rec)} matches {c["hint"]!r} '
        f'({c["hint_score"]}%): "{(rec.raw_text or rec.description)[:110]}"',
        'L1', evidence_ids=ids,
        confidence=c['hint_score'] / 100.0, confidence_kind='derived',
        candidates_considered=len(cands))

def l1_presence(rd: dict, cands: list, health: dict,
                cfg: Phase6Config = None) -> Optional[Verdict]:
    """
    Is there ANY admissible evidence in the window at all?

    The last deterministic move. If nothing can satisfy this requirement's mode
    inside its window, the answer is FAIL or UNCERTAIN -- and which one is not
    ours to choose.
    """
    if cands:
        return None
    t0, t1, bounded = window_for(rd, float(rd.get('_duration') or 0.0))
    where = f' in {t0:.1f}-{t1:.1f}s' if bounded else ''
    return _fail_or_uncertain(
        rd, health,
        reason_fail=f'No {rd.get("evidence_mode")} evidence exists{where}, and '
                    f'every modality that could carry it ran cleanly.',
        reason_uncertain=f'No {rd.get("evidence_mode")} evidence was retrieved{where}.',
        layer='L1', ids=[], candidates_considered=0)

def l1_timing(rd: dict, cands: list, health: dict,
              cfg: Phase6Config = None) -> Optional[Verdict]:
    """
    Deadline and window arithmetic, honest about tolerance.

    "First seen at 2.0s +-5.0s" against a 3.0s deadline is not a PASS and not a
    FAIL. The interval [0, 7] straddles the deadline, so the measurement cannot
    decide it, and saying otherwise would turn Phase 5's tolerance work into a
    coin-flip wearing a verdict's clothes.
    """
    cfg = cfg or P6
    res = rd.get('resolved') or {}
    deadline = res.get('deadline_seconds')
    if deadline is None or not cands:
        return None
    deadline = float(deadline)
    slack = cfg.l1.deadline_straddle_slack

    inside = [c for c in cands
              if c['record'].start_seconds - (c['record'].start_tolerance_seconds or 0.0)
              <= deadline + slack]
    if not inside:
        first = min(cands, key=lambda c: c['record'].start_seconds)['record']
        return _fail_or_uncertain(
            rd, health,
            reason_fail=f'Earliest admissible evidence is at {_fmt_t(first)}, '
                        f'after the {deadline:.1f}s deadline.',
            reason_uncertain=f'Earliest admissible evidence is at {_fmt_t(first)}, '
                             f'after the {deadline:.1f}s deadline.',
            layer='L1', ids=[first.id], candidates_considered=len(cands))

    # TIMING IS NECESSARY, NOT SUFFICIENT.
    #
    # Candidates are retrieved generously -- _hint_score is documented as "a
    # ranking signal, never an exclusion" -- so `inside` holds every record that
    # starts before the deadline, related to this requirement or not. Asserting
    # PASS from that answers "was anything early?" while reporting it as "was
    # THIS early?".
    #
    # Measured on a pill-organiser video audited against a hair-supplement
    # brief: twelve hook options each carried a 3s deadline, each found OCR at
    # ~0.5s, and each returned PASS at L1. _L1_ALIGNMENT then stamped all twelve
    # `exact`, the choice group picked a winner from a twelve-way tie, and the
    # video scored 0.85-0.95 against a brief it has nothing to do with.
    #
    # A deadline can RULE A REQUIREMENT OUT -- nothing was there in time -- but
    # it cannot rule one in. So the PASS path needs a record that is both early
    # AND about this requirement; anything else escalates, and L2/L3 decide on
    # content. The FAIL path above is untouched: it fires only when NOTHING at
    # all precedes the deadline, which is a timing fact on its own.
    relevant = [c for c in inside if c['hint_score'] >= cfg.l1.fuzzy_min]
    if not relevant:
        return None

    # The onset that matters is when the REQUIRED content first appears, not
    # when the video first shows anything.
    first = min(relevant, key=lambda c: c['record'].start_seconds)['record']
    lo = first.start_seconds - (first.start_tolerance_seconds or 0.0)
    hi = first.start_seconds + (first.start_tolerance_seconds or 0.0)
    if lo <= deadline <= hi:
        return _blank_verdict(
            rd, 'UNCERTAIN',
            f'Matching evidence at {_fmt_t(first)} places the true onset in '
            f'[{max(0.0, lo):.2f}, {hi:.2f}]s, which straddles the {deadline:.1f}s '
            f'deadline. The measurement cannot decide this either way.',
            'L1', evidence_ids=[first.id],
            flags=['TOLERANCE_STRADDLES_DEADLINE'],
            candidates_considered=len(cands))
    if hi <= deadline:
        return _blank_verdict(
            rd, 'PASS',
            f'{first.modality} evidence matching this requirement at '
            f'{_fmt_t(first)} is within the {deadline:.1f}s deadline even at the '
            f'far edge of its tolerance.',
            'L1', evidence_ids=[first.id],
            confidence=1.0, confidence_kind='derived',
            candidates_considered=len(cands))
    return None

METRIC_UNITS = {
    '%': 'pct', 'percent': 'pct', 'pct': 'pct',
    'day': 'days', 'days': 'days', 'week': 'weeks', 'weeks': 'weeks',
    'month': 'months', 'months': 'months', 'year': 'years', 'years': 'years',
    'hour': 'hours', 'hours': 'hours', 'minute': 'minutes', 'minutes': 'minutes',
    'x': 'times', 'times': 'times',
}

# The word-boundary applies to the SPELLED units only.
#
# Written as `(...)?\b` it silently broke every percentage: '%' is not a word
# character, so there is no boundary between '%' and the following space, the
# group backtracked to empty, and '27%' parsed as the bare number 27. Percent
# was then never policed at all -- and the test that caught it was the one
# asserting a contradicting '90%' gets FAILed.
_FIGURE_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*'
    r'(?:(%)|(percent|pct|days?|weeks?|months?|years?|hours?|minutes?|times?|x)\b)?',
    re.I)

def parse_figures(text: str) -> list:
    """Every figure in a piece of text, as (value, canonical unit).

    Unit is '' for a bare number. A bare number is never policed: "I've used it
    3 times" must not collide with an approved count of 1500 home studies.
    """
    out = []
    for m in _FIGURE_RE.finditer(text or ''):
        raw = m.group(1)
        unit = (m.group(2) or m.group(3) or '').lower()
        try:
            val = float(raw.replace(',', ''))
        except ValueError:
            continue
        out.append((val, METRIC_UNITS.get(unit, '')))
    return out

def approved_figure_index(hints) -> dict:
    """{unit: {approved values}} from the brief's own figures.

    '3months' and '3 months' are the same approved figure; the claim extractor
    emits the first form and a compiler the second.
    """
    idx = {}
    for h in hints or []:
        for val, unit in parse_figures(str(h)):
            idx.setdefault(unit, set()).add(val)
    return idx

def is_figure_fidelity_rule(rd: dict) -> bool:
    """A 'figures must match the brief' rule, as opposed to a word blacklist.

    The distinction is visible in the hints: a figures rule's hints are numbers,
    a medical-claims rule's hints are words.
    """
    if (rd.get('polarity') or 'required') != 'forbidden':
        return False
    hints = [str(h) for h in (rd.get('match_hints') or [])]
    if not hints:
        return False
    numeric = [h for h in hints if any(ch.isdigit() for ch in h)]
    return len(numeric) * 2 >= len(hints)

def l1_figure_fidelity(rd: dict, cands: list, health: dict,
                       cfg: Phase6Config = None) -> Optional[Verdict]:
    """
    "Any figure you state must match the brief" -- checked the right way round.

    This rule used to be handed to l1_forbidden, which searches for the terms in
    match_hints and FAILs when it finds one. For this rule those hints are the
    APPROVED figures, so the check was inverted: a creator who correctly said
    "27% after 3 months" was reported for forbidden content, while "90% in a
    week" -- the actual violation -- matched no hint and passed unnoticed.
    Measured on one run: three such rules, three FAILs, on a video that states
    no wrong figure at all.

    The violation is a CONTRADICTION: a figure in a dimension the brief speaks
    to, carrying a different value. Three deliberate restrictions keep that from
    becoming a new source of false FAILs:

      * only units the brief itself states are policed. The brief says 27% and
        3 months, so percentages and months are checked; "2 weeks" is not a
        contradiction of anything the brief claims.
      * bare numbers are never policed. "I've used it 3 times" must not collide
        with "1500 home studies".
      * only SPEECH and OCR count. A number inside a vision model's prose
        description is the model's word, not the creator's.
    """
    cfg = cfg or P6
    if not is_figure_fidelity_rule(rd):
        return None
    # THE BRIEF'S FIGURES, not one compile's sample of them.
    #
    # match_hints is whatever the model chose to list. Measured: one compile
    # wrote ['27%', 'hair loss', 'growth phase', '3 months'] and an earlier one
    # wrote ['27%', '1500', '21 days', '86%', '3 months'] for the same
    # document, so a creator quoting "an 86% satisfaction rate" straight out of
    # the brief PASSed one week and was reported for contradicting it the next.
    #
    # "Any figure you state must match the brief" can only be judged against the
    # brief. _brief_figures is every figure in the document, attached in
    # evaluate_requirements. The hints stay in the union so a hint naming a
    # figure the extractor missed still counts.
    approved = approved_figure_index(rd.get('match_hints'))
    for _val, _unit in (rd.get('_brief_figures') or []):
        approved.setdefault(_unit, set()).add(_val)
    policed = {u: v for u, v in approved.items() if u}
    if not policed:
        return None                      # nothing dimensioned to compare against

    examined, bad = [], []
    for c in cands:
        rec = c['record']
        if rec.modality not in ('speech', 'ocr'):
            continue
        examined.append(rec.id)
        text = f'{rec.raw_text or ""} {rec.norm_text or ""}'
        for val, unit in parse_figures(text):
            if unit in policed and val not in policed[unit]:
                bad.append((rec, val, unit))

    if bad:
        rec, val, unit = bad[0]
        want = ', '.join(f'{v:g}' for v in sorted(policed[unit]))
        # Finding a contradicting figure is POSITIVE evidence, so it may FAIL
        # whatever the health of the other modalities -- the same asymmetry
        # l1_forbidden documents.
        return _blank_verdict(
            rd, 'FAIL',
            f'Stated figure does not match the brief: {val:g} {unit} in '
            f'{rec.modality} evidence at {_fmt_t(rec)}, where the brief states '
            f'{want} {unit}: "{(rec.raw_text or rec.norm_text)[:90]}"',
            'L1', evidence_ids=[b[0].id for b in bad][:5],
            confidence=1.0, confidence_kind='derived',
            flags=[f'FAIL_FROM_POSITIVE_EVIDENCE:{rec.modality}',
                   f'FIGURE_CONTRADICTION:{val:g}{unit}'],
            candidates_considered=len(cands))

    if not examined:
        return _blank_verdict(
            rd, 'UNCERTAIN',
            'No speech or on-screen text was retrieved, so whether the stated '
            'figures match the brief cannot be established.',
            'L1', flags=['NOTHING_EXAMINED'], candidates_considered=len(cands))
    if not _fail_allowed(rd, health):
        return _fail_or_uncertain(
            rd, health, reason_fail='',       # never reached: agreement is a PASS
            reason_uncertain=f'Every figure stated across {len(examined)} '
                             f'record(s) matches the brief.',
            layer='L1', ids=examined[:5], candidates_considered=len(cands))
    return _blank_verdict(
        rd, 'PASS',
        f'Every figure stated across {len(examined)} record(s) matches the '
        f'brief, in units the brief speaks to ({", ".join(sorted(policed))}); '
        f'checked {", ".join(examined[:3])}'
        + (f' and {len(examined) - 3} more' if len(examined) > 3 else ''),
        'L1', evidence_ids=examined[:5],
        flags=['PASS_FROM_ABSENCE'],      # no contradicting figure was stated
        candidates_considered=len(cands))

# figure fidelity runs FIRST. Left to l1_forbidden, a figures rule has its
# approved values searched for as though they were banned words.
L1_CHECKS = (l1_figure_fidelity, l1_forbidden, l1_presence, l1_timing,
             l1_phrase)

def evaluate_l1(rd: dict, cands: list, health: dict,
                cfg: Phase6Config = None) -> Optional[Verdict]:
    """First check that fires, wins. None means INCONCLUSIVE -- escalate."""
    for check in L1_CHECKS:
        try:
            v = check(rd, cands, health, cfg)
        except Exception as exc:
            return _blank_verdict(
                rd, 'UNCERTAIN',
                f'L1 check {check.__name__} raised {type(exc).__name__}: '
                f'{str(exc)[:110]}',
                'L1', flags=['L1_CHECK_RAISED'],
                candidates_considered=len(cands))
        if v is not None:
            return v
    return None


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 512: print('§65 L1 loaded.  Every FAIL routes through _fail_or_uncertain().')
