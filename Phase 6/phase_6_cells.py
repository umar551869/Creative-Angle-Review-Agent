# ============================================================================
# §63  PHASE 6 — configuration, verdict schema, closed enums
# ============================================================================

# Imported here rather than relied on from an earlier cell. Phase 2 already
# imports rapidfuzz at module level, so this is a no-op in the full notebook --
# but a phase that silently depends on a name defined 60 cells earlier breaks
# the moment anyone runs it on its own, and the failure reads as a Phase 6 bug.
from collections import Counter
from dataclasses import replace
try:
    from rapidfuzz import fuzz
except ImportError:                               # pragma: no cover
    try_install('rapidfuzz', 'rapidfuzz')
    from rapidfuzz import fuzz

VERDICT_STAGE_VERSION = '1.0.0'
ADJUDICATE_PROMPT_VERSION = 'p6_adjudicate_v1'
HOOK_PROMPT_VERSION = 'p6_hook_v1'
CLAIMS_PROMPT_VERSION = 'p6_claims_v1'

# ---------------------------------------------------------------------------
# Status semantics -- plan.md §6.2
# ---------------------------------------------------------------------------
# These five are the whole contract with a reader. Adding a sixth is a product
# decision, not a coding convenience.
VERDICT_STATUSES = (
    'PASS',            # evidence satisfies it, and the evidence is cited
    'PARTIAL',         # satisfied weakly, late, or in one of two required modalities
    'FAIL',            # evidence contradicts, OR required evidence is confidently absent
    'UNCERTAIN',       # insufficient or degraded evidence -- NOT "hard case"
    'NOT_APPLICABLE',  # does not apply to this video (an unselected one_of option)
)

# INCONCLUSIVE is deliberately NOT in that tuple. L1 and L2 return it to mean
# "escalate"; it is a routing signal inside the ladder. A verdict carrying it
# would be telling a user that our cheap check did not fire, which is not a
# fact about their video.
ROUTING_ONLY = ('INCONCLUSIVE',)

EVAL_LAYERS = ('L1', 'L2', 'L3', 'gate')   # 'gate' = decided by can_fail_on alone

# Where a verdict's confidence number came from. Same discipline as Phase 5's
# confidence_kind: never average an LLM's self-report against a fuzzy match
# ratio, because they are not the same quantity.
VERDICT_CONFIDENCE_KINDS = ('derived', 'llm_self_report', 'none')


@dataclass(frozen=True)
class RetrievalConfig:
    """How candidate evidence is found for one requirement."""
    top_k: int = 10                   # retrieve GENEROUSLY -- the LLM is the filter
    # Requirement text is short and evidence records are short. partial_ratio
    # compares the shorter string against windows of the longer, which is what
    # we want when a 4-word hint sits inside a 30-word utterance.
    hint_match_min: int = 85          # rapidfuzz partial_ratio, plan.md §6.1
    # A window is widened by each record's OWN tolerance before testing overlap,
    # so a record whose bound is uncertain is still considered. Phase 5 measured
    # those tolerances; ignoring them here would throw that work away.
    use_record_tolerance: bool = True
    # Metadata records (cut_count, duration) are evidence ABOUT the video, not
    # IN it. They answer questions like "is the cut density high" and should not
    # crowd out real observations in the top-k.
    include_metadata: bool = False


@dataclass(frozen=True)
class L1Config:
    """The deterministic layer. Free, and it should answer most requirements."""
    fuzzy_min: int = 85               # phrase match threshold, rapidfuzz
    # A deadline comparison is only decidable if the record's tolerance does not
    # straddle it. 0.0 means "any overlap with the deadline is a straddle" --
    # the strictest reading, and the right default when a wrong FAIL is costly.
    deadline_straddle_slack: float = 0.0
    forbidden_fuzzy_min: int = 90     # higher bar: a false forbidden hit is loud
    min_hint_len: int = 3             # a 2-character hint matches everything


@dataclass(frozen=True)
class L2Config:
    """Embeddings. Cheap, CPU-only, and OFF until a model is actually present."""
    enabled: bool = True
    model_id: str = 'BAAI/bge-small-en-v1.5'
    # CPU on purpose. Qwen3-VL is the binding constraint on this machine and a
    # 133 MB retrieval model must never compete with it for VRAM.
    device: str = 'cpu'
    # BGE is asymmetric: the instruction goes on the QUERY only. Putting it on
    # both sides, or neither, degrades retrieval silently -- there is no error,
    # the numbers are just quietly worse.
    query_prefix: str = 'Represent this sentence for searching relevant passages: '
    passage_prefix: str = ''
    # TWO thresholds, not one. A single cut-off forces a coin-flip on exactly
    # the cases that deserve L3.
    #
    # MEASURED on 28 real requirements from two real briefs against real
    # evidence: every best-match cosine landed between 0.461 and 0.688, mean
    # 0.556. Both thresholds sit outside that range, so 100% escalate and L2
    # currently decides nothing.
    #
    # Do NOT just lower `high` to 0.60 to make the number look better. In the
    # same measurement the single HIGHEST score, 0.688, was a wrong match
    # ("do your favourite hairstyle to camera" against "capsules a day is all
    # you need"), while a correct one ("mention hydration and barrier support"
    # against "protective barrier. AURELTA") scored 0.632. The ranking does not
    # separate right from wrong on this data, so moving the line would trade
    # "escalates everything" for "passes things wrongly", which is worse.
    #
    # The compression has a visible cause: evidence records are individually
    # tiny OCR fragments ("more", "shine to your hair"), and bge-small scores
    # any two short English strings about hair around 0.5. Fixing that is a
    # retrieval change -- give L2 more context per passage -- not a threshold
    # change, and it belongs with the Phase 8 calibration that will have labels
    # to check it against.
    #
    # Escalating is not the disaster the percentage suggests: L3 batches up to
    # max_requirements_per_call, so 21 requirements cost 2 calls, not 21.
    high_threshold_PLACEHOLDER: float = 0.72   # >= this -> PASS
    low_threshold_PLACEHOLDER: float = 0.35    # <= this -> FAIL (if allowed)
    batch_size: int = 32
    max_chars: int = 512


@dataclass(frozen=True)
class L3Config:
    """LLM adjudication. Text only -- Phase 3 already looked at the pixels."""
    enabled: bool = True
    # Every escalated requirement for one video in ONE call. Per-requirement
    # calls cost ~20x for no accuracy gain.
    batch: bool = True
    max_requirements_per_call: int = 12
    max_candidates_per_requirement: int = 8
    # A model that cites an id it was not given is rejected once and retried.
    # Twice would be paying for the same hallucination.
    max_repair_retries: int = 1
    temperature: float = 0.0
    max_new_tokens: int = 4096


@dataclass(frozen=True)
class HookConfig:
    """spec §33. Presence and strength are SEPARATE questions."""
    window_seconds: float = 3.0
    max_window_seconds: float = 5.0
    speech_onset_good: float = 1.0    # speech starting later than this is a weak signal
    dense_cut_count: int = 2          # cuts inside the window that count as "dense"
    use_llm: bool = True
    # Strength is ordinal with written anchors, defined in the prompt. A bare
    # "rate the strength" produces noise; never emit a numeric score from a model.
    strengths: tuple = ('weak', 'medium', 'strong')


@dataclass(frozen=True)
class ClaimsConfig:
    """
    spec §38. OFF by default -- advertising-policy screening is not the current
    goal, and a module nobody is acting on is noise in every report it appears in.

    This is NOT the same thing as a `forbidden` requirement in a brief. If a
    brief says "do not make medical claims", that is brief compliance and stays
    switched on: it runs through l1_forbidden like any other requirement. What
    is off here is the STANDALONE policy scan that runs whether or not the brief
    asked for it.

    Turn it back on with:
        P6 = replace(P6, claims=replace(P6.claims, enabled=True))

    Kept tuned for RECALL for when it comes back: a missed claim is a far more
    expensive error than a flag a human dismisses in two seconds.
    """
    enabled: bool = False
    use_llm: bool = True
    context_chars: int = 240
    # Deliberately broad. A false positive costs a human two seconds; a false
    # negative costs a regulatory problem.
    gazetteer: tuple = (
        'cure', 'cures', 'cured', 'heal', 'heals', 'healing', 'treat', 'treats',
        'treatment', 'eliminate', 'eliminates', 'prevent', 'prevents', 'reverse',
        'reverses', 'clinically proven', 'clinically-proven', 'dermatologist approved',
        'dermatologist-approved', 'dermatologist recommended', 'fda', 'fda approved',
        'guaranteed', 'guarantee', 'permanent', 'permanently', '100%', 'overnight',
        'instantly', 'miracle', 'medical grade', 'medical-grade', 'prescription',
        'anti-aging', 'detox', 'detoxify', 'toxins', 'chemical free', 'chemical-free',
        'no side effects', 'risk free', 'risk-free', 'scientifically proven',
    )
    # 'unclassified' is a real answer: the wording matched, but no model judged
    # it. Reporting such a candidate as 'unsupported_outcome' would assert a
    # class nobody determined -- the same overclaiming the rest of the system
    # spends its effort avoiding.
    classes: tuple = ('medical_claim', 'cure_claim', 'guarantee_claim',
                      'unsupported_outcome', 'prohibited_wording', 'not_a_claim',
                      'unclassified')
    risk_levels: tuple = ('low', 'medium', 'high')
    DISCLAIMER = ('Automated detection of defined claim classes. NOT legal advice. '
                  'Every flag requires human review, and absence of a flag is not '
                  'evidence of compliance.')


@dataclass(frozen=True)
class Phase6Config:
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    l1: L1Config = field(default_factory=L1Config)
    l2: L2Config = field(default_factory=L2Config)
    l3: L3Config = field(default_factory=L3Config)
    hook: HookConfig = field(default_factory=HookConfig)
    claims: ClaimsConfig = field(default_factory=ClaimsConfig)


P6 = Phase6Config()


@dataclass
class Verdict:
    """
    One requirement, one video, one answer.

    `evidence_ids` is the load-bearing field: a status without citations cannot
    be checked by a human, and an unverifiable verdict is an opinion.
    """
    requirement_id: str
    status: str                       # VERDICT_STATUSES
    evidence_ids: list = field(default_factory=list)
    reason: str = ''
    layer: str = 'L1'                 # EVAL_LAYERS -- which layer decided it
    confidence: Optional[float] = None
    confidence_kind: str = 'none'     # VERDICT_CONFIDENCE_KINDS
    # Everything below is for auditing the evaluator itself, not for the reader.
    # What the verdict RELIES on is evidence_ids. What it was EVALUATED
    # AGAINST is this. Keeping them apart matters: a live FAIL read "the OCR
    # evidence only captures day labels like TUE and SA" and cited nothing, so
    # nobody could tell which OCR records it meant. Auto-filling evidence_ids
    # would have fixed the traceability by destroying the meaning of a citation.
    examined_ids: list = field(default_factory=list)
    requirement_label: str = ''
    evidence_mode: str = ''
    priority: str = 'medium'
    weight: float = 1.0
    group: Optional[str] = None
    group_mode: str = 'all_of'
    group_label: str = ''             # the human name of the choice, for the reason
    candidates_considered: int = 0
    escalated_from: list = field(default_factory=list)
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['evidence_ids'] = list(self.evidence_ids)
        return d


def _blank_verdict(rd: dict, status: str, reason: str, layer: str = 'gate',
                   **kw) -> Verdict:
    """A verdict carrying the requirement's identity, however it was decided."""
    return Verdict(
        requirement_id=rd.get('id', ''),
        status=status, reason=reason, layer=layer,
        requirement_label=rd.get('label') or rd.get('requirement', '')[:60],
        evidence_mode=rd.get('evidence_mode', 'any'),
        priority=rd.get('priority', 'medium'),
        weight=float(rd.get('weight', 1.0) or 1.0),
        group=rd.get('group'), group_mode=rd.get('group_mode', 'all_of'),
        group_label=rd.get('group_label', '') or '',
        **kw)


print('§63 Phase 6 config loaded.')
print(f'  statuses     : {", ".join(VERDICT_STATUSES)}')
print(f'  layers       : {", ".join(EVAL_LAYERS)}')
print(f'  L2 model     : {P6.l2.model_id} on {P6.l2.device}')
print(f'  thresholds   : high={P6.l2.high_threshold_PLACEHOLDER} '
      f'low={P6.l2.low_threshold_PLACEHOLDER}  '
      f'(PLACEHOLDER -- calibrate in Phase 8)')
print(f'  claims terms : {len(P6.claims.gazetteer)} in the gazetteer')


# ============================================================================
# §64  Retrieval -- requirement -> candidate evidence
# ============================================================================

def _req_query_text(rd: dict) -> str:
    """Everything about a requirement that describes what to look for."""
    bits = [rd.get('requirement', ''), rd.get('label', '')]
    bits += list(rd.get('acceptance_criteria') or [])
    bits += list(rd.get('match_hints') or [])
    seen, out = set(), []
    for b in bits:
        b = (b or '').strip()
        if b and b.lower() not in seen:
            seen.add(b.lower())
            out.append(b)
    return ' '.join(out)


SHORT_TERM_CHARS = 8          # below this, a single word must match as a WORD


def _term_hit(term: str, hay: str, min_ratio: int) -> tuple:
    """
    (matched, ratio). Word boundaries first; fuzzy only for longer phrases.

    `partial_ratio` scores a SUBSTRING 100, which is right for "20% off" inside
    a sentence and badly wrong for a short word inside a longer one. Measured on
    a real video: the forbidden term 'heal' scored 100 against "your hair looks
    so healthy and shiny", and the audit reported a medical claim in a
    compliment. A single short word therefore has to match on word boundaries;
    multi-word phrases keep the fuzzy path, where they earn it.
    """
    t = (term or '').strip().lower()
    if not t or not hay:
        return False, 0
    # Inflections count, unrelated words do not. 'heal' must catch heals,
    # healed and healing -- a brief writes the stem and the creator conjugates
    # it -- while 'healthy' has to stay clear, because "your hair looks healthy"
    # is a compliment and not a medical claim.
    try:
        if re.search(r'\b' + re.escape(t) + r'(?:s|es|ed|d|ing)?\b', hay):
            return True, 100
    except re.error:
        if t in hay:
            return True, 100
    if len(t) < SHORT_TERM_CHARS and ' ' not in t:
        return False, 0                       # 'heal' is not 'healthy'
    try:
        r = int(fuzz.partial_ratio(t, hay))
    except Exception:
        r = 0
    return r >= min_ratio, r


def _hint_score(hints: list, rec, cfg: L1Config = None) -> tuple:
    """(best ratio, the hint that matched). Ranking signal, never an exclusion."""
    cfg = cfg or P6.l1
    hay = f'{rec.norm_text} {rec.description}'.strip().lower()
    if not hay:
        return 0, ''
    best, which = 0, ''
    for h in hints or []:
        h = (h or '').strip().lower()
        if len(h) < cfg.min_hint_len:
            continue
        _hit, r = _term_hit(h, hay, cfg.fuzzy_min)
        if r > best:
            best, which = r, h
    return best, which


def window_for(rd: dict, duration: float) -> tuple:
    """
    (t0, t1, is_bounded). The window this requirement is about.

    Phase 4 already resolved symbolic expressions per video, so read `resolved`
    rather than re-deriving -- a second implementation of "duration - 5" is a
    second thing that can disagree.
    """
    res = rd.get('resolved') or {}
    t0 = res.get('window_start_seconds')
    t1 = res.get('window_end_seconds')
    dl = res.get('deadline_seconds')
    if dl is not None and t1 is None:
        # "within N seconds" is a window [0, N], not a point
        return 0.0, float(dl), True
    if t0 is None and t1 is None:
        return 0.0, float(duration or 0.0), False
    return (float(t0 if t0 is not None else 0.0),
            float(t1 if t1 is not None else (duration or 0.0)), True)


def candidates_for(rd: dict, records: list, duration: float,
                   cfg: Phase6Config = None) -> list:
    """
    [{record, hint_score, hint, in_window, why}] -- best first.

    Never raises and never returns None: a requirement with no candidates is a
    real and common answer, and the layers above must be able to say so.
    """
    cfg = cfg or P6
    rc = cfg.retrieval
    mode = rd.get('evidence_mode') or 'any'
    t0, t1, bounded = window_for(rd, duration)
    hints = list(rd.get('match_hints') or [])

    out = []
    for rec in records or []:
        if rec.modality == 'metadata' and not rc.include_metadata:
            continue
        # 1. may this record prove this KIND of thing at all?
        if not rec.can_satisfy(mode):
            continue
        # 2. is it in the window? widened by the record's own uncertainty.
        slack = (max(rec.start_tolerance_seconds, rec.end_tolerance_seconds)
                 if rc.use_record_tolerance else 0.0)
        in_win = rec.overlaps(t0, t1, slack=slack)
        if bounded and not in_win:
            continue
        # 3. rank -- never exclude -- on hint overlap
        score, hit = _hint_score(hints, rec, cfg.l1)
        why = []
        if hit:
            why.append(f'hint:{hit}({score})')
        if bounded:
            why.append(f'in {t0:.1f}-{t1:.1f}s')
        why.append(f'mode:{mode}')
        out.append({'record': rec, 'hint_score': score, 'hint': hit,
                    'in_window': in_win, 'why': ', '.join(why)})

    # Best hint first; then the earliest, because "first seen" questions are
    # common and an early record is usually the one being asked about.
    out.sort(key=lambda c: (-c['hint_score'], c['record'].start_seconds))
    return out[:rc.top_k]


def candidate_ids(cands: list) -> list:
    return [c['record'].id for c in cands]


print('§64 retrieval loaded.  candidates_for(requirement, records, duration)')


# ============================================================================
# §65  L1 -- the deterministic layer
# ============================================================================

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


# ---------------------------------------------------------------------------
# the four deterministic checks
# ---------------------------------------------------------------------------

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
        'L1', evidence_ids=checked[:5], candidates_considered=len(cands))


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

    first = min(inside, key=lambda c: c['record'].start_seconds)['record']
    lo = first.start_seconds - (first.start_tolerance_seconds or 0.0)
    hi = first.start_seconds + (first.start_tolerance_seconds or 0.0)
    if lo <= deadline <= hi:
        return _blank_verdict(
            rd, 'UNCERTAIN',
            f'Evidence at {_fmt_t(first)} places the true onset in '
            f'[{max(0.0, lo):.2f}, {hi:.2f}]s, which straddles the {deadline:.1f}s '
            f'deadline. The measurement cannot decide this either way.',
            'L1', evidence_ids=[first.id],
            flags=['TOLERANCE_STRADDLES_DEADLINE'],
            candidates_considered=len(cands))
    if hi <= deadline:
        return _blank_verdict(
            rd, 'PASS',
            f'{first.modality} evidence at {_fmt_t(first)} is within the '
            f'{deadline:.1f}s deadline even at the far edge of its tolerance.',
            'L1', evidence_ids=[first.id],
            confidence=1.0, confidence_kind='derived',
            candidates_considered=len(cands))
    return None


L1_CHECKS = (l1_forbidden, l1_presence, l1_timing, l1_phrase)


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


print('§65 L1 loaded.  Every FAIL routes through _fail_or_uncertain().')


# ============================================================================
# §66  L2 -- embedding similarity (CPU, optional)
# ============================================================================

_L2_STATE = {'model': None, 'tried': False, 'available': False, 'reason': ''}


def l2_model(cfg: L2Config = None, verbose: bool = True,
             allow_install: bool = False):
    """
    Load bge-small once, on CPU. Returns None if unavailable -- never raises.

    allow_install defaults to FALSE on purpose. This function is reached lazily,
    from inside the per-requirement loop, and an unattended pip install of
    sentence-transformers there stalls an audit for minutes at an unpredictable
    moment with no explanation. Expensive, surprising work belongs at a visible
    point: warm_l2() does the install, and §72 calls it before auditing.

    A retrieval model that cannot load is a reason to skip a layer, not a reason
    to fail an audit.
    """
    cfg = cfg or P6.l2
    if _L2_STATE['tried']:
        return _L2_STATE['model']
    if not cfg.enabled:
        _L2_STATE['tried'] = True
        _L2_STATE['reason'] = 'disabled in config'
        return None
    try:
        if allow_install:
            try_install('sentence-transformers', 'sentence_transformers')
        from sentence_transformers import SentenceTransformer
        _L2_STATE['model'] = SentenceTransformer(cfg.model_id, device=cfg.device)
        _L2_STATE['available'] = True
        _L2_STATE['tried'] = True
        if verbose:
            print(f'  L2: {cfg.model_id} on {cfg.device}')
    except ImportError:
        # Not an error -- just not installed yet. Stay un-tried so that a later
        # warm_l2() can still succeed instead of being short-circuited by this
        # lazy attempt having already given up.
        _L2_STATE['reason'] = ('sentence-transformers is not installed; run '
                               'warm_l2() to fetch it')
        if verbose:
            print(f'  L2 skipped: {_L2_STATE["reason"]}')
    except Exception as exc:
        _L2_STATE['tried'] = True
        _L2_STATE['reason'] = f'{type(exc).__name__}: {str(exc)[:120]}'
        if verbose:
            print(f'  L2 unavailable ({_L2_STATE["reason"]}) -- '
                  f'requirements escalate straight to L3')
    return _L2_STATE['model']


def warm_l2(cfg: L2Config = None, verbose: bool = True):
    """
    Install and load the embedding model NOW, with the wait visible.

    ~90 MB of wheels plus a 133 MB model on a cold Colab runtime. Doing it here
    means the cost is attributable; doing it inside the evaluation loop means an
    audit that mysteriously takes four minutes once and is instant thereafter.
    """
    cfg = cfg or P6.l2
    if not cfg.enabled:
        print('  L2 is disabled in config.')
        return None
    if verbose:
        print(f'  warming L2: {cfg.model_id} on {cfg.device} '
              f'(first run downloads ~130 MB)')
    m = l2_model(cfg, verbose=verbose, allow_install=True)
    print('  L2 ready.' if m is not None
          else f'  L2 unavailable: {_L2_STATE["reason"]}  '
               f'-- requirements will escalate straight to L3')
    return m


def _embed(texts: list, is_query: bool, cfg: L2Config = None):
    cfg = cfg or P6.l2
    m = l2_model(cfg, verbose=False)
    if m is None or not texts:
        return None
    pre = cfg.query_prefix if is_query else cfg.passage_prefix
    prepped = [(pre + (t or ''))[:cfg.max_chars] for t in texts]
    return m.encode(prepped, batch_size=cfg.batch_size,
                    normalize_embeddings=True, show_progress_bar=False)


def l2_similarities(rd: dict, cands: list, cfg: Phase6Config = None) -> list:
    """[(candidate, cosine)] best first, or [] when L2 is unavailable."""
    cfg = cfg or P6
    if not cands:
        return []
    q = _embed([_req_query_text(rd)], is_query=True, cfg=cfg.l2)
    if q is None:
        return []
    passages = [f'{c["record"].raw_text or c["record"].description}'.strip()
                or c['record'].type for c in cands]
    p = _embed(passages, is_query=False, cfg=cfg.l2)
    if p is None:
        return []
    sims = [float((q[0] * row).sum()) for row in p]      # both L2-normalised
    pairs = list(zip(cands, sims))
    pairs.sort(key=lambda x: -x[1])
    return pairs


def evaluate_l2(rd: dict, cands: list, health: dict,
                cfg: Phase6Config = None) -> Optional[Verdict]:
    """PASS above the high threshold, FAIL/UNCERTAIN below the low one, else None."""
    cfg = cfg or P6
    pairs = l2_similarities(rd, cands, cfg)
    if not pairs:
        return None
    best, sim = pairs[0]
    rec = best['record']
    if sim >= cfg.l2.high_threshold_PLACEHOLDER:
        top = [p[0] for p in pairs[:3]]
        # The same two-modality rule as L1. A paraphrase found in one modality
        # is no more able to satisfy visual_and_speech than a literal match was.
        missing, need = _conjunctive_shortfall(rd, top)
        if missing:
            return _blank_verdict(
                rd, 'PARTIAL',
                f'{rec.modality} evidence at {_fmt_t(rec)} is semantically close '
                f'(cosine {sim:.2f}), but this requirement asks for '
                f'{" and ".join(need)} and no {" or ".join(missing)} evidence '
                f'supports it.',
                'L2', evidence_ids=[c.id for c in top],
                confidence=sim, confidence_kind='derived',
                flags=['L2_THRESHOLD_PLACEHOLDER',
                       f'MODE_SHORTFALL:{",".join(missing)}'],
                candidates_considered=len(cands))
        return _blank_verdict(
            rd, 'PASS',
            f'{rec.modality} evidence at {_fmt_t(rec)} is semantically close to '
            f'the requirement (cosine {sim:.2f}): '
            f'"{(rec.raw_text or rec.description)[:110]}"',
            'L2', evidence_ids=[c.id for c in top],
            confidence=sim, confidence_kind='derived',
            candidates_considered=len(cands),
            flags=['L2_THRESHOLD_PLACEHOLDER'])
    if sim <= cfg.l2.low_threshold_PLACEHOLDER:
        return _fail_or_uncertain(
            rd, health,
            reason_fail=f'The closest evidence scores only {sim:.2f} against the '
                        f'requirement, well below the match threshold, in '
                        f'modalities that ran cleanly.',
            reason_uncertain=f'The closest evidence scores only {sim:.2f} against '
                             f'the requirement.',
            layer='L2', ids=[rec.id], candidates_considered=len(cands),
            flags=['L2_THRESHOLD_PLACEHOLDER'])
    return None                                            # escalate to L3


print('§66 L2 loaded.  warm_l2() installs and loads it; absence disables the layer.')


# ============================================================================
# §67  L3 -- LLM adjudication (text only, batched, IDs validated)
# ============================================================================

L3_SYSTEM = """You are a compliance adjudicator for short-form video briefs.

You are given REQUIREMENTS and, for each, a numbered list of EVIDENCE records
extracted from one video by an automated pipeline. Decide whether the evidence
satisfies each requirement.

RULES, in order of importance:
1. Cite ONLY evidence ids that appear in that requirement's candidate list.
   Never invent an id. If nothing fits, cite nothing.
2. The evidence is all you have. You cannot see the video. Do not infer what
   probably happened between the moments the evidence describes.
3. Use exactly these statuses:
   PASS       - the cited evidence satisfies the requirement
   PARTIAL    - satisfied weakly, late, or in only one of two required modalities
   FAIL       - the evidence CONTRADICTS the requirement
   UNCERTAIN  - the evidence is insufficient to decide
   Prefer UNCERTAIN over guessing. An unsupported verdict is worse than none.
4. `reason` is one sentence a human can check against the evidence you cited.
   Quote the wording you relied on. Do not restate the requirement.

Return ONLY a JSON object, no prose and no code fence:
{"verdicts": [{"requirement_id": "...", "status": "...",
               "evidence_ids": ["..."], "reason": "...",
               "confidence": 0.0}]}"""


def _evidence_line(rec) -> str:
    """One evidence record, as the model sees it."""
    t = f'{rec.start_seconds:.2f}-{rec.end_seconds:.2f}s'
    tol = rec.time_tolerance_seconds or 0.0
    if tol:
        t += f' (+-{tol:.2f}s)'
    body = (rec.raw_text or rec.description or '').strip().replace('\n', ' ')
    extra = ''
    if rec.modality == 'ocr' and rec.independence:
        extra = f' [independence:{rec.independence}]'
    if rec.modality == 'visual':
        extra = f' [type:{rec.type}]'
    return f'  - id={rec.id} [{rec.modality}] {t}{extra}: "{body[:200]}"'


def build_l3_prompt(batch: list, duration: float) -> str:
    """batch = [(requirement_dict, candidates)]."""
    out = [f'VIDEO DURATION: {duration:.2f}s', '']
    for rd, cands in batch:
        out.append(f'REQUIREMENT id={rd.get("id")}')
        out.append(f'  text          : {rd.get("requirement", "")}')
        out.append(f'  evidence_mode : {rd.get("evidence_mode")}')
        res = rd.get('resolved') or {}
        if res.get('deadline_seconds') is not None:
            out.append(f'  deadline      : within {res["deadline_seconds"]}s')
        if res.get('window_start_seconds') is not None:
            out.append(f'  window        : {res.get("window_start_seconds")}'
                       f'-{res.get("window_end_seconds")}s')
        for ac in (rd.get('acceptance_criteria') or [])[:4]:
            out.append(f'  accept if     : {ac}')
        if cands:
            out.append('  CANDIDATE EVIDENCE:')
            out.extend(_evidence_line(c['record']) for c in cands)
        else:
            out.append('  CANDIDATE EVIDENCE: (none retrieved)')
        out.append('')
    return '\n'.join(out)


def _validate_l3(obj: dict, allowed: dict, batch_ids: set) -> tuple:
    """
    (verdict dicts, violations). THE anti-hallucination check.

    Two ways a response can lie about provenance: cite an id that does not
    exist, or cite a real id that belonged to a DIFFERENT requirement. Both are
    rejected -- the second is subtler and would attribute one requirement's
    evidence to another.
    """
    good, bad = [], []
    for v in (obj or {}).get('verdicts') or []:
        if not isinstance(v, dict):
            bad.append('non-object verdict')
            continue
        rid = str(v.get('requirement_id') or '')
        if rid not in batch_ids:
            bad.append(f'unknown requirement_id {rid!r}')
            continue
        ids = [str(i) for i in (v.get('evidence_ids') or [])]
        allow = allowed.get(rid, set())
        invented = [i for i in ids if i not in allow]
        if invented:
            bad.append(f'{rid}: cited {invented[:3]} which were not offered')
            continue
        st = str(v.get('status') or '').upper()
        if st not in VERDICT_STATUSES:
            bad.append(f'{rid}: status {st!r} is not a valid verdict')
            continue
        good.append({'requirement_id': rid, 'status': st, 'evidence_ids': ids,
                     'reason': str(v.get('reason') or '')[:400],
                     'confidence': v.get('confidence')})
    return good, bad


def evaluate_l3_batch(batch: list, health: dict, duration: float,
                      backend=None, cfg: Phase6Config = None,
                      verbose: bool = True) -> tuple:
    """
    ({requirement_id: Verdict}, stats). Never raises.

    A backend failure is a degraded audit, not a crashed one: everything in the
    batch comes back UNCERTAIN with a flag saying why.
    """
    cfg = cfg or P6
    stats = {'calls': 0, 'violations': [], 'backend': None, 'repaired': 0}
    if not batch:
        return {}, stats
    if not cfg.l3.enabled:
        return ({rd['id']: _blank_verdict(rd, 'UNCERTAIN',
                                          'L3 is disabled; no layer could decide this.',
                                          'L3', flags=['L3_DISABLED'])
                 for rd, _ in batch}, stats)

    allowed = {rd['id']: set(candidate_ids(c)) for rd, c in batch}
    batch_ids = set(allowed)
    user = build_l3_prompt(batch, duration)
    bcfg = replace(P4.brief, temperature=cfg.l3.temperature,
                   max_new_tokens=cfg.l3.max_new_tokens)

    out, notes = {}, []
    for attempt in range(cfg.l3.max_repair_retries + 1):
        try:
            backend = backend or make_brief_backend(bcfg, verbose=verbose)
            gen = backend.complete(L3_SYSTEM, user, bcfg)
            stats['calls'] += 1
            stats['backend'] = getattr(backend, 'name', 'unknown')
        except Exception as exc:
            notes.append(f'{type(exc).__name__}: {str(exc)[:140]}')
            break
        obj, perr, _method = parse_model_json(gen.get('text', '') or '')
        if obj is None:
            notes.append(f'unparseable response: {perr}')
            user += ('\n\nYour previous reply was not valid JSON. Return ONLY the '
                     'JSON object described above.')
            continue
        good, bad = _validate_l3(obj, allowed, batch_ids)
        stats['violations'].extend(bad)
        for v in good:
            rd = next(r for r, _ in batch if r['id'] == v['requirement_id'])
            conf = v['confidence']
            out[v['requirement_id']] = _blank_verdict(
                rd, v['status'], v['reason'] or 'Adjudicated by the language model.',
                'L3', evidence_ids=v['evidence_ids'],
                confidence=(float(conf) if isinstance(conf, (int, float)) else None),
                confidence_kind='llm_self_report',
                candidates_considered=len(allowed[v['requirement_id']]))
        if not bad and len(out) == len(batch_ids):
            break
        if bad and attempt < cfg.l3.max_repair_retries:
            stats['repaired'] += 1
            user += ('\n\nYour previous reply cited evidence ids that were not '
                     'offered for that requirement. Cite ONLY ids from that '
                     "requirement's candidate list, or none at all.")

    # A FAIL from the model still has to pass the health gate -- the model does
    # not get to overrule a degraded modality just because it sounded confident.
    for rid, v in list(out.items()):
        rd = next(r for r, _ in batch if r['id'] == rid)
        if v.status == 'FAIL' and not _fail_allowed(rd, health):
            out[rid] = _blank_verdict(
                rd, 'UNCERTAIN',
                f'The model judged this a FAIL ({v.reason[:150]}) but the '
                f'modality it relies on was degraded, so the absence is not '
                f'evidence.',
                'L3', evidence_ids=v.evidence_ids,
                flags=['FAIL_BLOCKED_BY_MODALITY_HEALTH', 'L3_FAIL_DOWNGRADED'],
                candidates_considered=v.candidates_considered)

    for rd, cands in batch:                      # anything the model skipped
        if rd['id'] not in out:
            out[rd['id']] = _blank_verdict(
                rd, 'UNCERTAIN',
                'The adjudicator returned no usable verdict for this requirement. '
                + ('; '.join(notes[:2]) if notes else ''),
                'L3', flags=['L3_NO_VERDICT'],
                candidates_considered=len(cands))
    if stats['violations'] and verbose:
        print(f'  L3 rejected {len(stats["violations"])} citation violation(s): '
              f'{stats["violations"][:2]}')
    return out, stats


print('§67 L3 loaded.  Only offered evidence ids are citable; violations are rejected.')


# ============================================================================
# §68  Hook module -- spec §33
# ============================================================================

HOOK_TYPES = (
    'question', 'bold_claim', 'problem_statement', 'result_reveal',
    'curiosity_gap', 'direct_address', 'demonstration', 'social_proof',
    'negative_warning', 'humour', 'none',
)

_Q_WORDS = ('what', 'why', 'how', 'when', 'where', 'who', 'which', 'did', 'do',
            'does', 'are', 'is', 'can', 'ever', 'would', 'have')
_NEG_WORDS = ('not', "n't", 'never', 'no', 'stop', 'avoid', 'mistake', 'wrong',
              'worst', 'without', 'nobody', 'don', 'doesn')
_YOU_WORDS = ('you', 'your', "you're", 'yours', 'yourself')

HOOK_SYSTEM = """You judge the opening hook of a short-form video.

A HOOK is an opening that gives a viewer a reason to keep watching. An
INTRODUCTION ("hi guys, welcome back") is not a hook.

Answer two SEPARATE questions. Do not let one decide the other:
1. Is a hook present at all?
2. If present, how strong is it?

STRENGTH ANCHORS -- use these, not your own scale:
  weak    - technically a hook, but generic and easily scrolled past.
            e.g. "Let's talk about hair care."
  medium  - a specific reason to stay, but no tension or stakes.
            e.g. "This is the product I use every morning."
  strong  - creates curiosity, stakes, or a promise that demands resolution.
            e.g. "I ruined my hair for two years doing this one thing."

Use ONLY the evidence given. You cannot see the video.
Return ONLY this JSON, no prose and no code fence:
{"hook_present": true, "hook_type": "one of the listed types",
 "strength": "weak|medium|strong", "reason": "one sentence",
 "evidence_ids": ["..."]}"""


def hook_features(records: list, duration: float, cuts: int,
                  cfg: HookConfig = None) -> dict:
    """Free, deterministic signals from the opening window."""
    cfg = cfg or P6.hook
    w = min(cfg.window_seconds, duration or cfg.window_seconds)
    speech = speech_in_window(records, 0.0, w)
    text = text_in_window(records, 0.0, 1.0)
    vis = visual_in_window(records, 0.0, w)
    all_speech = [r for r in records if r.modality == 'speech']
    onset = min((r.start_seconds for r in all_speech), default=None)
    first = ''
    if speech:
        first = (min(speech, key=lambda r: r.start_seconds).raw_text or '').strip()
    low = first.lower()
    toks = re.findall(r"[a-z']+", low)
    return {
        'window_seconds': round(w, 2),
        'speech_onset': (round(onset, 3) if onset is not None else None),
        'speech_starts_early': bool(onset is not None and onset <= cfg.speech_onset_good),
        'first_sentence': first[:200],
        'has_question': ('?' in first) or bool(toks and toks[0] in _Q_WORDS),
        'has_number': bool(re.search(r'\d', first)),
        'has_negation': any(n in low for n in _NEG_WORDS),
        'has_second_person': any(t in _YOU_WORDS for t in toks),
        'text_overlay_in_first_second': bool(text),
        'cuts_in_window': sum(1 for r in records
                              if r.type == 'scene_cut' and r.start_seconds <= w),
        'cut_density_per_second': round(cuts / duration, 4) if duration else 0.0,
        'face_at_camera': any(r.type == 'person_speaking_to_camera' for r in vis),
        'speech_records': len(speech), 'visual_records': len(vis),
    }


def evaluate_hook(records: list, duration: float, cuts: int, health: dict,
                  backend=None, cfg: Phase6Config = None,
                  verbose: bool = True) -> dict:
    """spec §33's full output. Presence and strength stay separate throughout."""
    cfg = cfg or P6
    f = hook_features(records, duration, cuts, cfg.hook)
    w = f['window_seconds']
    cands = [r for r in records
             if r.modality in ('speech', 'ocr', 'visual')
             and r.overlaps(0.0, w, slack=0.25)][:cfg.retrieval.top_k]

    out = {'hook_present': None, 'hook_type': 'none', 'start': 0.0,
           'end': round(w, 2), 'strength': None, 'transcript': f['first_sentence'],
           'visual': '', 'within_required_window': None, 'reason': '',
           'features': f, 'evidence_ids': [c.id for c in cands],
           'layer': 'L1', 'flags': []}
    vis = [c for c in cands if c.modality == 'visual']
    if vis:
        out['visual'] = (vis[0].description or '')[:200]

    if not can_fail_on(health or {}, 'speech'):
        out.update(hook_present=None, reason=(
            'Speech evidence was degraded or absent, so hook presence cannot be '
            'judged. This is UNCERTAIN, not "no hook".'),
            flags=['HOOK_UNCERTAIN_DEGRADED_SPEECH'])
        return out
    if not f['speech_records'] and not f['text_overlay_in_first_second']:
        out.update(hook_present=False, hook_type='none', strength=None,
                   within_required_window=False,
                   reason=f'No speech or on-screen text in the first {w:.1f}s of a '
                          f'video whose speech track ran cleanly.')
        return out

    if not (cfg.hook.use_llm and cfg.l3.enabled):
        out.update(hook_present=True, hook_type='direct_address',
                   within_required_window=True, layer='L1',
                   reason=f'Speech begins at {f["speech_onset"]}s; hook TYPE and '
                          f'STRENGTH need the language model, which is disabled.',
                   flags=['HOOK_TYPE_NOT_JUDGED'])
        return out

    lines = [f'VIDEO DURATION: {duration:.2f}s',
             f'HOOK WINDOW: 0.00-{w:.2f}s', '',
             'DETERMINISTIC SIGNALS:']
    for k in ('speech_onset', 'has_question', 'has_number', 'has_negation',
              'has_second_person', 'text_overlay_in_first_second',
              'cuts_in_window', 'face_at_camera'):
        lines.append(f'  {k} = {f[k]}')
    lines += ['', 'EVIDENCE IN THE WINDOW:']
    lines += [_evidence_line(c) for c in cands] or ['  (none)']
    lines += ['', f'Allowed hook_type values: {", ".join(HOOK_TYPES)}']

    bcfg = replace(P4.brief, temperature=0.0, max_new_tokens=1024)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(HOOK_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _ = parse_model_json(gen.get('text', '') or '')
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'
    if not isinstance(obj, dict):
        out.update(hook_present=None,
                   reason=f'The hook model returned nothing usable ({perr}).',
                   layer='L3', flags=['HOOK_MODEL_FAILED'])
        return out

    ht = str(obj.get('hook_type') or 'none')
    st = str(obj.get('strength') or '').lower()
    ids = [i for i in (obj.get('evidence_ids') or []) if i in set(out['evidence_ids'])]
    out.update(
        hook_present=bool(obj.get('hook_present')),
        hook_type=(ht if ht in HOOK_TYPES else 'none'),
        strength=(st if st in cfg.hook.strengths else None),
        reason=str(obj.get('reason') or '')[:300],
        evidence_ids=ids, layer='L3')
    if ht not in HOOK_TYPES:
        out['flags'].append(f'HOOK_TYPE_OUT_OF_ENUM:{ht[:30]}')
    if out['hook_present'] and out['strength'] is None:
        out['flags'].append('HOOK_STRENGTH_MISSING')
    out['within_required_window'] = bool(
        out['hook_present'] and (f['speech_onset'] is None
                                 or f['speech_onset'] <= cfg.hook.max_window_seconds))
    return out


print('§68 hook module loaded.  Presence and strength are judged separately.')


# ============================================================================
# §69  Claims / policy module -- spec §38
# ============================================================================

_CLAIM_PATTERNS = (
    (r'\b(cures?|cured|curing)\b', 'cure_claim'),
    (r'\b(heals?|healing)\b', 'cure_claim'),
    (r'\b(treats?|treatment for|treating)\b', 'medical_claim'),
    (r'\b(prevents?|preventing)\b', 'medical_claim'),
    (r'\b(clinically|scientifically|dermatologist)[\s-]*(proven|approved|tested|recommended)\b',
     'unsupported_outcome'),
    (r'\bfda[\s-]*(approved|cleared)?\b', 'prohibited_wording'),
    (r'\b(guarantee[ds]?|guaranteed results?)\b', 'guarantee_claim'),
    (r'\b(100\s*%|permanent(ly)?|forever)\b', 'guarantee_claim'),
    (r'\b(overnight|instantly|in (just )?\d+\s*(second|minute|day)s?)\b',
     'unsupported_outcome'),
    (r'\b(no side effects|risk[\s-]free|chemical[\s-]free|toxin[\s-]free)\b',
     'unsupported_outcome'),
    (r'\b(miracle|medical[\s-]grade|prescription[\s-]strength)\b', 'medical_claim'),
)

CLAIMS_SYSTEM = """You classify sentences from a short-form video for
advertising-policy risk.

For each candidate, choose exactly one class:
  medical_claim       - asserts a health/medical effect
  cure_claim          - asserts it cures, heals or eliminates a condition
  guarantee_claim     - promises a guaranteed or permanent result
  unsupported_outcome - a specific outcome presented as fact without support
  prohibited_wording  - regulated wording (e.g. FDA) used as endorsement
  not_a_claim         - ordinary description, opinion, or clearly hyperbolic

and a risk level: low | medium | high.

Judge the SENTENCE AS USED. "This cured my boredom" is not_a_claim.
Being unsure is a reason to classify it as a claim, not to dismiss it: a missed
claim is far more costly than an extra flag a human dismisses.

Return ONLY this JSON, no prose and no code fence:
{"claims": [{"candidate_id": "...", "claim_class": "...", "risk": "...",
             "reason": "one short sentence"}]}"""


def claim_candidates(records: list, cfg: ClaimsConfig = None) -> list:
    """High recall, zero cost. Gazetteer + regex over speech and OCR."""
    cfg = cfg or P6.claims
    out = []
    for rec in records or []:
        if rec.modality not in ('speech', 'ocr'):
            continue
        text = (rec.raw_text or rec.description or '').strip()
        if not text:
            continue
        low = text.lower()
        hits, guess = [], None
        for term in cfg.gazetteer:
            # _term_hit, not `in`: a plain substring test flags "your hair looks
            # so healthy" as a healing claim, and noise like that is what makes
            # people stop reading the flags. Inflections still match, so real
            # uses are not lost -- this trades nothing for the recall that
            # matters.
            matched, _r = _term_hit(term, low, 90)
            if matched:
                hits.append(term)
        for pat, klass in _CLAIM_PATTERNS:
            if re.search(pat, low):
                guess = guess or klass
                m = re.search(pat, low)
                if m and m.group(0) not in hits:
                    hits.append(m.group(0))
        if not hits:
            continue
        out.append({
            'candidate_id': f'cand_{len(out):03d}',
            'evidence_id': rec.id, 'modality': rec.modality,
            'start_seconds': rec.start_seconds, 'end_seconds': rec.end_seconds,
            'text': text[:cfg.context_chars],
            'matched_terms': sorted(set(hits))[:6],
            'regex_class': guess,
        })
    return out


def evaluate_claims(records: list, backend=None, cfg: Phase6Config = None,
                    verbose: bool = True) -> dict:
    """
    Candidates, classified. Never asserts the absence of claims.

    `checked` says what we looked at, so a reader can tell "we found nothing in
    what we examined" apart from "there is nothing" -- which this cannot know.
    """
    cfg = cfg or P6
    # The `enabled` flag used to exist and do nothing -- a config field that
    # silently has no effect is worse than no field, because it tells you the
    # module is off while it runs anyway.
    if not cfg.claims.enabled:
        return {'enabled': False, 'candidates': 0, 'claims': [],
                'disclaimer': cfg.claims.DISCLAIMER, 'layer': 'off', 'flags': [],
                'note': ('Policy/claims screening is switched off. Nothing was '
                         'examined, so this is NOT a finding of compliance. '
                         'Forbidden-content requirements FROM THE BRIEF are '
                         'unaffected and still evaluated.')}
    cands = claim_candidates(records, cfg.claims)
    out = {'enabled': True,
           'candidates': len(cands), 'claims': [], 'disclaimer': cfg.claims.DISCLAIMER,
           'checked': {'speech_records': sum(1 for r in records if r.modality == 'speech'),
                       'ocr_records': sum(1 for r in records if r.modality == 'ocr')},
           'layer': 'L1', 'flags': []}
    if not cands:
        out['note'] = ('No candidate wording matched the gazetteer. This is NOT a '
                       'finding of compliance -- only defined classes are detected.')
        return out

    if not (cfg.claims.use_llm and cfg.l3.enabled):
        out['claims'] = [dict(c, claim_class=c['regex_class'] or 'unsupported_outcome',
                              risk='medium', reason='Matched the gazetteer; not '
                              'classified because the language model is disabled.')
                         for c in cands]
        out['flags'].append('CLAIMS_NOT_CLASSIFIED')
        return out

    lines = ['CANDIDATES:']
    for c in cands:
        lines.append(f'  id={c["candidate_id"]} [{c["modality"]} '
                     f'{c["start_seconds"]:.1f}s] matched={c["matched_terms"]}')
        lines.append(f'    "{c["text"]}"')
    bcfg = replace(P4.brief, temperature=0.0, max_new_tokens=2048)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(CLAIMS_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _ = parse_model_json(gen.get('text', '') or '')
        out['layer'] = 'L3'
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'

    by_id = {c['candidate_id']: c for c in cands}
    classified = {}
    for v in ((obj or {}).get('claims') or []):
        if not isinstance(v, dict):
            continue
        cid = str(v.get('candidate_id') or '')
        if cid not in by_id:
            out['flags'].append(f'CLAIMS_UNKNOWN_CANDIDATE:{cid[:20]}')
            continue
        k = str(v.get('claim_class') or '')
        classified[cid] = {
            'claim_class': k if k in cfg.claims.classes else 'unsupported_outcome',
            'risk': (str(v.get('risk') or 'medium').lower()
                     if str(v.get('risk') or '').lower() in cfg.claims.risk_levels
                     else 'medium'),
            'reason': str(v.get('reason') or '')[:240],
        }
        if k not in cfg.claims.classes:
            out['flags'].append(f'CLAIMS_CLASS_OUT_OF_ENUM:{k[:24]}')

    for c in cands:
        got = classified.get(c['candidate_id'])
        if got is None:
            # Kept, because a missed claim is the costly error -- but marked
            # 'unclassified' rather than given a class nobody determined.
            got = {'claim_class': 'unclassified',
                   'regex_suggests': c['regex_class'],
                   'risk': 'medium',
                   'reason': f'Matched {c["matched_terms"][:3]} but was not '
                             f'classified ({perr or "no verdict"}); kept for '
                             f'review because a missed claim is the costly error.'}
            out['flags'].append('CLAIMS_UNCLASSIFIED_KEPT')
        out['claims'].append(dict(c, **got))

    out['by_class'] = dict(Counter(c['claim_class'] for c in out['claims']))
    out['flagged'] = sum(1 for c in out['claims'] if c['claim_class'] != 'not_a_claim')
    out['unclassified'] = sum(1 for c in out['claims']
                              if c['claim_class'] == 'unclassified')
    return out


print('§69 claims module loaded.  High recall; never asserts the absence of claims.')


# ============================================================================
# §70  The evaluate stage, cached
# ============================================================================

_STATUS_RANK = {'PASS': 0, 'PARTIAL': 1, 'UNCERTAIN': 2, 'FAIL': 3,
                'NOT_APPLICABLE': 4}


def _resolve_groups(verdicts: list, cfg: Phase6Config = None) -> list:
    """
    Collapse one_of / any_of groups to their best member.

    A brief that offers 12 hooks is not asking for 12 hooks. Treating each
    option as separately required is the single most effective way to produce a
    page of false FAILs, so the losers become NOT_APPLICABLE -- visible, and
    explained, rather than quietly dropped.
    """
    by_group = {}
    for v in verdicts:
        if v.group and v.group_mode in ('one_of', 'any_of'):
            by_group.setdefault(v.group, []).append(v)
    for gid, members in by_group.items():
        best = min(members, key=lambda v: (_STATUS_RANK.get(v.status, 9),
                                           -(v.confidence or 0.0)))
        for v in members:
            if v is best:
                v.flags.append(f'GROUP_SELECTED:{gid}({len(members)} options)')
                continue
            v.status = 'NOT_APPLICABLE'
            v.reason = (f'Not the option satisfied for choice group '
                        f'{v.group_label or gid!r}: '
                        f'"{best.requirement_label}" was ({best.status}).')
            v.flags.append(f'GROUP_NOT_SELECTED:{gid}')
    return verdicts


def evaluate_requirements(video: dict, evidence: dict, compiled: dict,
                          cfg: Phase6Config = None, backend=None,
                          force: bool = False, verbose: bool = True,
                          allow_unapproved: bool = False) -> dict:
    """
    One video x one brief -> a verdict per requirement. Never raises.

    The brief is an INPUT to the cache key, never part of the video's identity,
    so three briefs against one video re-run only this stage.
    """
    cfg = cfg or P6
    t0 = time.time()
    vh = video['video_hash']
    vdir = DIRS['artifacts'] / vh
    duration = float(evidence.get('duration_seconds') or video.get('duration_s') or 0.0)

    key = stage_key('verdicts', VERDICT_STAGE_VERSION,
                    [vh, evidence.get('cache_key', ''),
                     compiled.get('brief_hash', ''), compiled.get('cache_key', '')],
                    {'p6': asdict(cfg)})
    path = vdir / f'verdicts__{key}.json'
    if path.exists() and not force:
        if verbose:
            print(f'  VERDICTS CACHE HIT ({key})')
        return read_json(path)

    try:
        reqs = resolve_brief_for_video(compiled, duration, allow_unapproved)
    except (ValueError, PermissionError) as exc:
        return {'status': 'BRIEF_NOT_USABLE', 'verdicts': [], 'cache_key': key,
                'flags': [{'code': 'BRIEF_NOT_USABLE', 'detail': str(exc)[:200]}]}

    records = load_records(evidence)
    health = evidence.get('modality_health') or {}
    can_fail = evidence.get('can_fail_on') or modes_that_can_fail(health)

    verdicts, escalate, cand_map = [], [], {}
    for rd in reqs:
        rd = dict(rd)
        rd['_duration'] = duration
        cands = candidates_for(rd, records, duration, cfg)
        cand_map[rd['id']] = cands
        v = evaluate_l1(rd, cands, health, cfg)
        if v is not None:
            v.candidates_considered = v.candidates_considered or len(cands)
            verdicts.append(v)
            continue
        v = evaluate_l2(rd, cands, health, cfg)
        if v is not None:
            v.escalated_from = ['L1']
            verdicts.append(v)
            continue
        escalate.append((rd, cands[:cfg.l3.max_candidates_per_requirement]))

    l3_stats = {'calls': 0, 'violations': [], 'backend': None, 'repaired': 0}
    for i in range(0, len(escalate), cfg.l3.max_requirements_per_call):
        chunk = escalate[i:i + cfg.l3.max_requirements_per_call]
        got, st = evaluate_l3_batch(chunk, health, duration, backend, cfg, verbose)
        l3_stats['calls'] += st['calls']
        l3_stats['repaired'] += st['repaired']
        l3_stats['violations'] += st['violations']
        l3_stats['backend'] = st['backend'] or l3_stats['backend']
        for rd, _c in chunk:
            v = got.get(rd['id'])
            if v is None:
                v = _blank_verdict(rd, 'UNCERTAIN',
                                   'No layer produced a verdict.', 'L3',
                                   flags=['NO_VERDICT'])
            v.escalated_from = ['L1', 'L2']
            verdicts.append(v)

    # Every verdict records what it was evaluated against, whichever layer
    # decided it. One place, so no layer can forget -- and separate from
    # evidence_ids, which stays "what this verdict relies on".
    for v in verdicts:
        v.examined_ids = candidate_ids(cand_map.get(v.requirement_id) or [])[:10]

    verdicts = _resolve_groups(verdicts, cfg)

    # THE assertion. Not a test that might be run -- a check that always runs.
    offered = {rid: set(candidate_ids(c)) for rid, c in cand_map.items()}
    fabricated = [(v.requirement_id, i) for v in verdicts for i in v.evidence_ids
                  if i not in offered.get(v.requirement_id, set())]
    flags = []
    if fabricated:
        flags.append({'code': 'FABRICATED_EVIDENCE_ID',
                      'detail': f'{len(fabricated)}: {fabricated[:3]}'})
        keep = {rid: offered.get(rid, set()) for rid, _ in fabricated}
        for v in verdicts:
            if v.requirement_id in keep:
                v.evidence_ids = [i for i in v.evidence_ids if i in keep[v.requirement_id]]
                v.flags.append('CITATIONS_STRIPPED')

    # Two kinds of FAIL, and only one needs the mode-wide health gate:
    #   from ABSENCE  -- "we looked and it is not there". Needs every modality
    #                    that could have carried it to have run cleanly.
    #   from PRESENCE -- "we found the forbidden thing". Grounded in evidence we
    #                    HAVE, in a modality already checked at the point of the
    #                    finding. Requiring the conjunction here would make a
    #                    real policy breach unreportable because an unrelated
    #                    modality degraded.
    illegal = [v.requirement_id for v in verdicts
               if v.status == 'FAIL'
               and not can_fail.get(v.evidence_mode, False)
               and not any(f.startswith('FAIL_FROM_POSITIVE_EVIDENCE')
                           for f in v.flags)]
    if illegal:
        flags.append({'code': 'FAIL_WITHOUT_HEALTH', 'detail': str(illegal[:3])})

    by_status = Counter(v.status for v in verdicts)
    by_layer = Counter(v.layer for v in verdicts)
    n = max(1, len(verdicts))
    out = {
        'schema_version': VERDICT_STAGE_VERSION,
        'video_hash': vh, 'video_id': video.get('video_id', ''),
        'brief_hash': compiled.get('brief_hash', ''),
        'duration_seconds': round(duration, 3),
        'cache_key': key,
        'sources': {'evidence': evidence.get('cache_key', ''),
                    'brief': compiled.get('cache_key', '')},
        'verdicts': [v.to_dict() for v in verdicts],
        'can_fail_on': can_fail,
        'stats': {
            'requirements': len(verdicts),
            'by_status': dict(by_status),
            'by_layer': dict(by_layer),
            'escalation_rate': {
                'L1': round(by_layer.get('L1', 0) / n, 3),
                'L2': round(by_layer.get('L2', 0) / n, 3),
                'L3': round(by_layer.get('L3', 0) / n, 3),
            },
            'uncertain_rate': round(by_status.get('UNCERTAIN', 0) / n, 3),
            'fabricated_ids': len(fabricated),
            'l3': l3_stats,
        },
        'flags': flags,
        'provenance': provenance('verdicts', VERDICT_STAGE_VERSION, key,
                                 time.time() - t0,
                                 prompt_version=ADJUDICATE_PROMPT_VERSION,
                                 backend=l3_stats.get('backend')),
    }
    write_json(path, out)
    if verbose:
        print(f'  verdicts -> {path.name}  ({len(verdicts)} requirements)')
    return out


def audit_video(video: dict, evidence: dict, compiled: dict,
                cfg: Phase6Config = None, backend=None, force: bool = False,
                verbose: bool = True, allow_unapproved: bool = False) -> dict:
    """Requirements + hook + claims, the whole Phase 6 output for one video."""
    cfg = cfg or P6
    res = evaluate_requirements(video, evidence, compiled, cfg, backend, force,
                                verbose, allow_unapproved)
    records = load_records(evidence)
    agg = evidence.get('aggregates') or {}
    health = evidence.get('modality_health') or {}
    res['hook'] = evaluate_hook(records, float(res.get('duration_seconds') or 0.0),
                                int(agg.get('cut_count') or 0), health,
                                backend, cfg, verbose)
    res['claims'] = evaluate_claims(records, backend, cfg, verbose)
    return res


def verdicts_for(video_hash: str, brief_hash: str = '') -> Optional[dict]:
    """Newest verdict artifact for a video, optionally for one brief."""
    vdir = DIRS['artifacts'] / video_hash
    if not vdir.exists():
        return None
    files = [p for p in vdir.glob('verdicts__*.json')]
    if brief_hash:
        files = [p for p in files
                 if (read_json(p) or {}).get('brief_hash') == brief_hash]
    if not files:
        return None
    return read_json(max(files, key=lambda p: p.stat().st_mtime))


print('§70 evaluate stage loaded.  Artifacts -> work/artifacts/{video_hash}/verdicts__*.json')


# ============================================================================
# §71  Phase 6 test suite -- no GPU, no network, no API key
# ============================================================================

class _FakeL3Backend(BriefBackend):
    """Canned responses, so every L3 path is testable with no model."""
    kind, name = 'fake', 'fake:p6'

    def __init__(self, payload, raise_exc=None):
        self.payload, self.raise_exc, self.calls = payload, raise_exc, 0

    def complete(self, system, user, cfg):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        p = (self.payload[min(self.calls - 1, len(self.payload) - 1)]
             if isinstance(self.payload, list) else self.payload)
        return {'text': p, 'backend': self.name, 'capped': False}


def _rec(rid, modality, typ, t0, t1, text='', tol=0.0, indep='', conf=None,
         kind='none'):
    return EvidenceRecord(
        id=rid, modality=modality, type=typ, start_seconds=t0, end_seconds=t1,
        description=text, raw_text=text, norm_text=text.lower(),
        start_tolerance_seconds=tol, end_tolerance_seconds=tol,
        time_tolerance_seconds=tol, independence=indep,
        confidence=conf, confidence_kind=kind,
        satisfies_modes=modes_for(modality, indep))


def _health(speech=True, ocr=True, visual=True):
    def m(ok):
        return {'ran': True, 'degraded': not ok, 'reason': None if ok else 'test'}
    return {'speech': m(speech), 'ocr': m(ocr), 'visual': m(visual),
            'metadata': m(True)}


def _req(**kw):
    d = {'id': 'req_x', 'ordinal': 1, 'label': 'test', 'requirement': 'Do the thing.',
         'type': 'speech', 'priority': 'medium', 'weight': 1.0,
         'polarity': 'required', 'evidence_mode': 'speech_or_text',
         'machine_checkable': True, 'match_hints': [], 'acceptance_criteria': [],
         'forbidden_evidence': [], 'claim_classes': [],
         'resolved': {'deadline_seconds': None, 'window_start_seconds': None,
                      'window_end_seconds': None, 'flags': []},
         '_duration': 30.0}
    d.update(kw)
    return d


def _run_phase6_tests(verbose: bool = True) -> bool:
    passed, failed = 0, []

    def check(name, cond, detail=''):
        nonlocal passed
        if cond:
            passed += 1
            if verbose:
                print(f'  PASS  {name}')
        else:
            failed.append(f'{name}   {detail}')
            print(f'  FAIL  {name}   {detail}')

    print('=' * 78)
    print('§71  PHASE 6 TEST SUITE')
    print('=' * 78)

    SAY = _rec('ev_say', 'speech', 'utterance', 2.0, 5.0,
               'This cream gives me real hydration all day')
    LATE = _rec('ev_late', 'visual', 'product_held', 29.0, 31.0,
                'A person holds the white tube', tol=5.0)
    EARLY = _rec('ev_early', 'visual', 'product_held', 1.0, 3.0,
                 'A person holds the white tube', tol=0.2)
    OCRI = _rec('ev_ocr', 'ocr', 'on_screen_text', 4.0, 6.0, '20% OFF TODAY',
                indep='confirmed_independent')
    OCRD = _rec('ev_cap', 'ocr', 'on_screen_text', 2.0, 5.0,
                'this cream gives me real hydration', indep='derived_from_speech')
    ALL = [SAY, LATE, EARLY, OCRI, OCRD]

    # ---------- retrieval ---------------------------------------------------
    print('\n-- retrieval: what could possibly answer this --')
    r = _req(evidence_mode='ocr_only', match_hints=['20% off'])
    c = candidates_for(r, ALL, 30.0)
    ids = candidate_ids(c)
    check('ocr_only retrieves the independent interval', 'ev_ocr' in ids, str(ids))
    check('...and NOT the burned-in caption', 'ev_cap' not in ids,
          'derived_from_speech cannot satisfy ocr_only -- product.md §37')
    check('...and no speech record', 'ev_say' not in ids, str(ids))
    r2 = _req(evidence_mode='speech_or_text', match_hints=['hydration'])
    c2 = candidates_for(r2, ALL, 30.0)
    check('speech_or_text retrieves speech AND the caption',
          {'ev_say', 'ev_cap'} <= set(candidate_ids(c2)), str(candidate_ids(c2)))
    check('the hint ranks the best match first',
          c2[0]['record'].id in ('ev_say', 'ev_cap'), c2[0]['record'].id)
    check('every candidate records WHY it was retrieved',
          all(x['why'] for x in c2))
    r3 = _req(evidence_mode='visual_only',
              resolved={'deadline_seconds': 5.0, 'window_start_seconds': None,
                        'window_end_seconds': None, 'flags': []})
    ids3 = candidate_ids(candidates_for(r3, ALL, 30.0))
    check('a deadline bounds retrieval to [0, deadline]', 'ev_early' in ids3, str(ids3))
    check('...and a record far outside it is NOT retrieved',
          'ev_late' not in ids3,
          'ev_late is 29s +-5s, so it reaches back only to 24s -- nowhere near 5s')
    # A record whose tolerance genuinely reaches the window MUST be retrieved:
    # discarding it would throw away the uncertainty Phase 5 measured and decide
    # the requirement on a bound we know is imprecise.
    NEAR = _rec('ev_near', 'visual', 'product_held', 6.0, 8.0,
                'A person holds the tube', tol=2.0)
    ids3b = candidate_ids(candidates_for(r3, [NEAR], 30.0))
    check('...but one whose tolerance REACHES the window is',
          'ev_near' in ids3b, 'at 6.0s +-2.0s it reaches back to 4.0s, inside [0, 5]')

    # ---------- L1 ----------------------------------------------------------
    print('\n-- L1: arithmetic and string matching --')
    v = evaluate_l1(_req(match_hints=['hydration']), c2, _health())
    check('a phrase match PASSes at L1', v and v.status == 'PASS', v and v.reason[:60])
    check('...and cites the record it matched', v and 'ev_say' in v.evidence_ids
          or 'ev_cap' in (v.evidence_ids if v else []))
    check('...labelled as derived, not an LLM self-report',
          v and v.confidence_kind == 'derived')

    straddle = _req(evidence_mode='visual_only', match_hints=[],
                    resolved={'deadline_seconds': 30.0, 'window_start_seconds': None,
                              'window_end_seconds': None, 'flags': []})
    sc = candidates_for(straddle, [LATE], 40.0)
    v = evaluate_l1(straddle, sc, _health())
    check('a tolerance straddling the deadline is UNCERTAIN',
          v and v.status == 'UNCERTAIN', v and v.status)
    check('...and says so in a flag',
          v and 'TOLERANCE_STRADDLES_DEADLINE' in v.flags, str(v and v.flags))

    clear = _req(evidence_mode='visual_only', match_hints=[],
                 resolved={'deadline_seconds': 5.0, 'window_start_seconds': None,
                           'window_end_seconds': None, 'flags': []})
    v = evaluate_l1(clear, candidates_for(clear, [EARLY], 30.0), _health())
    check('a bound inside the deadline even at its far edge PASSes',
          v and v.status == 'PASS', v and v.status)

    # ---------- visual_and_speech needs BOTH --------------------------------
    # Measured on a real audit: "do your favourite hairstyle on camera and
    # discuss hair health" PASSed at L1 because the single word 'supplement'
    # appeared in the transcript. Phase 5 marks a speech record as ABLE to
    # satisfy visual_and_speech -- correctly, it can CONTRIBUTE -- but what a
    # record may contribute to and what a requirement NEEDS are different.
    print('\n-- visual_and_speech is a conjunction --')
    both = _req(evidence_mode='visual_and_speech', match_hints=['tube'])
    SPK = _rec('ev_spk', 'speech', 'utterance', 2.0, 4.0, 'I use this tube daily')
    VIS = _rec('ev_vis', 'visual', 'product_held', 2.0, 4.0, 'holds a white tube')
    v = evaluate_l1(both, candidates_for(both, [SPK], 30.0), _health())
    check('speech alone is PARTIAL, not PASS',
          v and v.status == 'PARTIAL', v and v.status)
    check('...and names what is missing',
          v and any(f.startswith('MODE_SHORTFALL:visual') for f in v.flags),
          str(v and v.flags))
    v = evaluate_l1(both, candidates_for(both, [VIS], 30.0), _health())
    check('visual alone is PARTIAL too',
          v and v.status == 'PARTIAL', v and v.status)
    v = evaluate_l1(both, candidates_for(both, [SPK, VIS], 30.0), _health())
    check('both modalities together PASS',
          v and v.status == 'PASS', v and v.status)
    check('...citing evidence from both', v and len(v.evidence_ids) >= 2,
          str(v and v.evidence_ids))
    one = _req(evidence_mode='speech_or_text', match_hints=['tube'])
    v = evaluate_l1(one, candidates_for(one, [SPK], 30.0), _health())
    check('a DISJUNCTIVE mode is unaffected -- speech_or_text still PASSes',
          v and v.status == 'PASS', v and v.status)

    # ---------- the FAIL gate ----------------------------------------------
    print('\n-- the gate: a FAIL asserts something --')
    absent = _req(evidence_mode='visual_only', match_hints=['unicorn'])
    v = evaluate_l1(absent, [], _health(visual=True))
    check('absent evidence in a HEALTHY modality is a FAIL',
          v and v.status == 'FAIL', v and v.status)
    v = evaluate_l1(absent, [], _health(visual=False))
    check('...the same absence in a DEGRADED modality is UNCERTAIN',
          v and v.status == 'UNCERTAIN', v and v.status)
    check('...and says why a FAIL was not supportable',
          v and 'FAIL_BLOCKED_BY_MODALITY_HEALTH' in v.flags, str(v and v.flags))
    v = evaluate_l1(_req(evidence_mode='any', match_hints=['unicorn']), [],
                    _health(visual=False))
    check('mode "any" needs EVERY modality healthy to FAIL',
          v and v.status == 'UNCERTAIN',
          'any of them could have carried the evidence')

    # ---------- forbidden polarity -----------------------------------------
    print('\n-- forbidden requirements invert --')
    forb = _req(polarity='forbidden', evidence_mode='any',
                forbidden_evidence=['cures acne'])
    BAD = _rec('ev_bad', 'speech', 'utterance', 3.0, 5.0, 'it cures acne overnight')
    v = evaluate_l1(forb, candidates_for(forb, [BAD], 30.0), _health())
    check('finding forbidden content FAILs', v and v.status == 'FAIL', v and v.status)
    check('...citing where it was found', v and 'ev_bad' in v.evidence_ids)
    CLEAN = _rec('ev_clean', 'speech', 'utterance', 3.0, 5.0,
                 'it smells lovely and the bottle is pretty')
    v = evaluate_l1(forb, candidates_for(forb, [CLEAN], 30.0), _health(visual=False))
    check('NOT finding it with a degraded modality is UNCERTAIN, not PASS',
          v and v.status == 'UNCERTAIN', v and v.status)
    v = evaluate_l1(forb, candidates_for(forb, [CLEAN], 30.0), _health())
    check('...but with everything healthy it is a PASS',
          v and v.status == 'PASS', v and v.status)
    # Live run: this PASS came back with no citations and tripped §73's
    # "every PASS cites at least one record". "Nothing forbidden here" is a
    # claim about a SPECIFIC set of evidence; without the ids nobody can check
    # which set was read.
    check('...citing the records it examined',
          v and v.evidence_ids == ['ev_clean'], str(v and v.evidence_ids))
    check('...and naming them in the reason',
          v and 'ev_clean' in v.reason, (v.reason if v else '')[:90])
    v = evaluate_l1(forb, [], _health())
    check('with NOTHING examined it is UNCERTAIN, not a vacuous PASS',
          v and v.status == 'UNCERTAIN', v and v.status)
    check('...and says nothing was examined',
          v and 'NOTHING_EXAMINED' in v.flags, str(v and v.flags))

    # Measured on a real video: 'heal' scored 100 against "your hair looks so
    # healthy and shiny" and the audit reported a medical claim in a compliment.
    print('\n-- a short word must match as a WORD --')
    COMPLIMENT = _rec('ev_nice', 'ocr', 'on_screen_text', 1.0, 3.0,
                      'Your hair looks so healthy and shiny! Love it!',
                      indep='confirmed_independent')
    heal = _req(polarity='forbidden', evidence_mode='any',
                forbidden_evidence=['heal'])
    v = evaluate_l1(heal, candidates_for(heal, [COMPLIMENT], 30.0), _health())
    check("'heal' does NOT match 'healthy'",
          v and v.status != 'FAIL', f'got {v and v.status}: {v and v.reason[:70]}')
    check('...and partial_ratio alone would have', int(fuzz.partial_ratio(
        'heal', 'your hair looks so healthy and shiny')) >= 90,
        'which is why the word-boundary rule exists')
    HEALS = _rec('ev_heals', 'ocr', 'on_screen_text', 1.0, 3.0,
                 'This product heals damaged hair', indep='confirmed_independent')
    v = evaluate_l1(heal, candidates_for(heal, [HEALS], 30.0), _health())
    check("...but 'heals' as a real word still FAILs",
          v and v.status == 'FAIL', v and v.status)
    check("...and so do 'healing' and 'healed'",
          _term_hit('heal', 'it was healing the damage', 90)[0]
          and _term_hit('heal', 'my hair healed fast', 90)[0],
          'a brief writes the stem; the creator conjugates it')
    check("...while 'healthy' still does not match",
          not _term_hit('heal', 'looks so healthy and shiny', 90)[0])
    check('a multi-word phrase keeps the fuzzy path',
          _term_hit('clinically proven', 'it is clinicaly proven to work', 85)[0],
          'a typo in a phrase should not escape detection')

    print('\n-- two kinds of FAIL, and only one needs the gate --')
    v = evaluate_l1(heal, candidates_for(heal, [HEALS], 30.0),
                    _health(visual=False))
    check('finding forbidden content FAILs even when ANOTHER modality is degraded',
          v and v.status == 'FAIL',
          'the OCR that carried it ran cleanly; this is not an argument from absence')
    check('...and is flagged as grounded in found evidence',
          v and any(f.startswith('FAIL_FROM_POSITIVE_EVIDENCE') for f in v.flags),
          str(v and v.flags))
    v = evaluate_l1(heal, candidates_for(heal, [HEALS], 30.0),
                    _health(ocr=False))
    check('but a hit in a DEGRADED modality is UNCERTAIN, not FAIL',
          v and v.status == 'UNCERTAIN', v and v.status)
    check('...and says the reading was unreliable',
          v and 'FORBIDDEN_HIT_ON_DEGRADED_MODALITY' in v.flags, str(v and v.flags))

    # ---------- L3 citation discipline --------------------------------------
    print('\n-- L3: only offered evidence ids are citable --')
    rq = _req(id='req_a', evidence_mode='speech_or_text', match_hints=[])
    cds = candidates_for(rq, [SAY], 30.0)
    ok_json = json.dumps({'verdicts': [{'requirement_id': 'req_a', 'status': 'PASS',
                                        'evidence_ids': ['ev_say'],
                                        'reason': 'The speaker says it.',
                                        'confidence': 0.8}]})
    got, st = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                                _FakeL3Backend(ok_json), verbose=False)
    check('a well-formed verdict is accepted',
          got['req_a'].status == 'PASS', got['req_a'].status)
    check('...and labelled llm_self_report',
          got['req_a'].confidence_kind == 'llm_self_report')

    halluc = json.dumps({'verdicts': [{'requirement_id': 'req_a', 'status': 'PASS',
                                       'evidence_ids': ['ev_INVENTED'],
                                       'reason': 'made up'}]})
    got, st = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                                _FakeL3Backend(halluc), verbose=False)
    check('an invented evidence id is REJECTED',
          got['req_a'].status == 'UNCERTAIN', got['req_a'].status)
    check('...and the violation is recorded', bool(st['violations']),
          str(st['violations'][:1]))
    check('...and nothing fabricated survives into the verdict',
          'ev_INVENTED' not in got['req_a'].evidence_ids)

    wrong_owner = json.dumps({'verdicts': [
        {'requirement_id': 'req_a', 'status': 'PASS',
         'evidence_ids': ['ev_ocr'], 'reason': 'wrong requirement\'s evidence'}]})
    got, st = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                                _FakeL3Backend(wrong_owner), verbose=False)
    check('a REAL id that was not offered for THIS requirement is rejected',
          got['req_a'].status == 'UNCERTAIN',
          'subtler than an invented id, and just as wrong')

    l3fail = json.dumps({'verdicts': [{'requirement_id': 'req_v', 'status': 'FAIL',
                                       'evidence_ids': [],
                                       'reason': 'not there'}]})
    rv = _req(id='req_v', evidence_mode='visual_only')
    got, _ = evaluate_l3_batch([(rv, [])], _health(visual=False), 30.0,
                               _FakeL3Backend(l3fail), verbose=False)
    check('even a CONFIDENT L3 FAIL is downgraded on a degraded modality',
          got['req_v'].status == 'UNCERTAIN', got['req_v'].status)
    check('...and flagged as downgraded',
          'L3_FAIL_DOWNGRADED' in got['req_v'].flags, str(got['req_v'].flags))

    got, _ = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                               _FakeL3Backend('not json at all'), verbose=False)
    check('an unparseable response yields UNCERTAIN, not a crash',
          got['req_a'].status == 'UNCERTAIN')
    got, _ = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                               _FakeL3Backend('', RuntimeError('network down')),
                               verbose=False)
    check('a backend exception yields UNCERTAIN, not a crash',
          got['req_a'].status == 'UNCERTAIN')

    bad_status = json.dumps({'verdicts': [{'requirement_id': 'req_a',
                                           'status': 'INCONCLUSIVE',
                                           'evidence_ids': []}]})
    got, _ = evaluate_l3_batch([(rq, cds)], _health(), 30.0,
                               _FakeL3Backend(bad_status), verbose=False)
    check('INCONCLUSIVE from a model is not a valid verdict',
          got['req_a'].status in VERDICT_STATUSES, got['req_a'].status)
    check('...and never reaches the output',
          got['req_a'].status != 'INCONCLUSIVE')

    # ---------- choice groups -----------------------------------------------
    # A live FAIL reasoned about OCR evidence and cited none of it, so the
    # verdict could not be checked. evidence_ids stays "what this relies on";
    # examined_ids is "what it was shown", filled for every layer in one place.
    print('\n-- every verdict is traceable, even when it cites nothing --')
    _v = Verdict(requirement_id='x', status='FAIL')
    check('a Verdict carries examined_ids', hasattr(_v, 'examined_ids'))
    check('...defaulting to empty, not shared between verdicts',
          _v.examined_ids == []
          and Verdict(requirement_id='y', status='PASS').examined_ids is not _v.examined_ids)
    _v.examined_ids = ['ev_a', 'ev_b']
    check('...and surviving to_dict for the artifact',
          _v.to_dict().get('examined_ids') == ['ev_a', 'ev_b'],
          str(_v.to_dict().get('examined_ids')))

    print('\n-- choice groups: one_of means ONE --')
    vs = [_blank_verdict(_req(id=f'h{i}', group='g1', group_mode='one_of',
                              group_label='hook options'),
                         'FAIL' if i else 'PASS', 'r', 'L1') for i in range(4)]
    vs = _resolve_groups(vs)
    check('exactly one member keeps its verdict',
          sum(1 for v in vs if v.status != 'NOT_APPLICABLE') == 1,
          str([v.status for v in vs]))
    check('the PASS is the one kept',
          next(v for v in vs if v.status != 'NOT_APPLICABLE').status == 'PASS')
    check('the others are NOT_APPLICABLE, not FAIL',
          all(v.status == 'NOT_APPLICABLE' for v in vs[1:]),
          'compiling 12 hook options as all-required is how you get 11 false FAILs')
    # startswith, not `in`: the flag carries the group id, so list membership
    # would be testing for a string that is never stored.
    check('...and each says which option won',
          all(any(f.startswith('GROUP_NOT_SELECTED') for f in v.flags)
              for v in vs[1:]), str(vs[1].flags))
    check('...and names the winner in its reason',
          all(vs[0].requirement_label in v.reason for v in vs[1:]),
          vs[1].reason[:80])
    allof = _resolve_groups([_blank_verdict(_req(id=f'a{i}', group='g2',
                                                 group_mode='all_of'),
                                            'FAIL', 'r', 'L1') for i in range(3)])
    check('an all_of group is left alone',
          all(v.status == 'FAIL' for v in allof))

    # ---------- hook --------------------------------------------------------
    print('\n-- hook: presence and strength are separate --')
    HOOK = _rec('ev_hook', 'speech', 'utterance', 0.4, 2.8,
                'Did you know your ponytail is breaking your hair?')
    f = hook_features([HOOK], 30.0, 10)
    check('speech onset is measured', f['speech_onset'] == 0.4, str(f['speech_onset']))
    check('an early start is recognised', f['speech_starts_early'] is True)
    check('a question is detected', f['has_question'] is True)
    check('second person is detected', f['has_second_person'] is True)
    hk = json.dumps({'hook_present': True, 'hook_type': 'question',
                     'strength': 'strong', 'reason': 'Opens with a question.',
                     'evidence_ids': ['ev_hook']})
    h = evaluate_hook([HOOK], 30.0, 10, _health(), _FakeL3Backend(hk), verbose=False)
    check('hook_present and strength are both reported',
          h['hook_present'] is True and h['strength'] == 'strong', str(h['strength']))
    check('hook_type stays inside the closed taxonomy',
          h['hook_type'] in HOOK_TYPES, h['hook_type'])
    bad_hk = json.dumps({'hook_present': True, 'hook_type': 'vibes',
                         'strength': 'ELEVEN', 'reason': 'x', 'evidence_ids': []})
    h2 = evaluate_hook([HOOK], 30.0, 10, _health(), _FakeL3Backend(bad_hk),
                       verbose=False)
    check('an out-of-enum hook_type is coerced and flagged',
          h2['hook_type'] == 'none'
          and any(f.startswith('HOOK_TYPE_OUT_OF_ENUM') for f in h2['flags']))
    check('an out-of-scale strength becomes None, never a number',
          h2['strength'] is None, str(h2['strength']))
    h3 = evaluate_hook([HOOK], 30.0, 10, _health(speech=False),
                       _FakeL3Backend(hk), verbose=False)
    check('degraded speech makes hook presence UNCERTAIN, not False',
          h3['hook_present'] is None, str(h3['hook_present']))
    h4 = evaluate_hook([], 30.0, 10, _health(), _FakeL3Backend(hk), verbose=False)
    check('no speech at all, with a clean track, IS "no hook"',
          h4['hook_present'] is False)

    # ---------- claims ------------------------------------------------------
    print('\n-- claims/policy screening is OFF by default --')
    off = evaluate_claims([SAY], _FakeL3Backend('{}'), verbose=False)
    check('the module is off unless asked for',
          off.get('enabled') is False, str(off.get('enabled')))
    check('...and says silence is not a clean bill of health',
          'NOT a finding of compliance' in (off.get('note') or ''),
          off.get('note', '')[:70])
    check('...and still carries the disclaimer', bool(off.get('disclaimer')))
    FORB = _req(polarity='forbidden', evidence_mode='any',
                forbidden_evidence=['cures acne'])
    BADX = _rec('ev_bx', 'speech', 'utterance', 3.0, 5.0, 'it cures acne overnight')
    v = evaluate_l1(FORB, candidates_for(FORB, [BADX], 30.0), _health())
    check('a brief\'s own forbidden requirement is UNAFFECTED by that switch',
          v and v.status == 'FAIL',
          'brief compliance is the product; the standalone policy scan is not')

    # everything below explicitly turns it on
    P6C = replace(P6, claims=replace(P6.claims, enabled=True))
    print('\n-- claims, when enabled: recall first, never a clean bill of health --')
    CL = _rec('ev_cl', 'speech', 'utterance', 3.0, 6.0,
              'This is clinically proven to cure acne permanently')
    cands = claim_candidates([CL])
    check('a gazetteer hit becomes a candidate', len(cands) == 1, str(len(cands)))
    check('...recording which terms matched', bool(cands[0]['matched_terms']),
          str(cands[0]['matched_terms']))
    cj = json.dumps({'claims': [{'candidate_id': cands[0]['candidate_id'],
                                 'claim_class': 'cure_claim', 'risk': 'high',
                                 'reason': 'Asserts a cure.'}]})
    res = evaluate_claims([CL], _FakeL3Backend(cj), P6C, verbose=False)
    check('the claim is classified', res['claims'][0]['claim_class'] == 'cure_claim')
    check('a disclaimer always rides along', bool(res['disclaimer']))
    clean = evaluate_claims([SAY], _FakeL3Backend(cj), P6C, verbose=False)
    check('no candidates does NOT mean "no claims"',
          clean['claims'] == [] and 'NOT a finding of compliance' in clean['note'],
          'proving a global negative is not something this evidence can do')
    res2 = evaluate_claims([CL], _FakeL3Backend('garbage'), P6C, verbose=False)
    check('an unclassified candidate is KEPT, not dropped',
          len(res2['claims']) == 1 and 'CLAIMS_UNCLASSIFIED_KEPT' in res2['flags'],
          'a missed claim is the expensive error')
    check('...and marked unclassified, not given a class nobody decided',
          res2['claims'][0]['claim_class'] == 'unclassified',
          res2['claims'][0]['claim_class'])
    NICE = _rec('ev_nice2', 'speech', 'utterance', 1.0, 3.0,
                'your hair looks so healthy and shiny')
    check('the gazetteer does not flag a compliment',
          claim_candidates([NICE]) == [],
          "'heal' must not match 'healthy' here either -- noise makes people "
          'stop reading the flags')
    HEALS2 = _rec('ev_h2', 'speech', 'utterance', 1.0, 3.0,
                  'it healed my damaged ends')
    check('...but a real inflection still becomes a candidate',
          len(claim_candidates([HEALS2])) == 1)

    # ---------- hostile input ----------------------------------------------
    print('\n-- hostile input --')
    for label, rd in (('no resolved block', {'id': 'r1', 'evidence_mode': 'any'}),
                      ('no evidence_mode', {'id': 'r2'}),
                      ('junk mode', {'id': 'r3', 'evidence_mode': 'telepathy'})):
        try:
            candidates_for(dict(rd, _duration=10.0), ALL, 10.0)
            evaluate_l1(dict(rd, _duration=10.0), [], _health())
            check(f'{label} does not raise', True)
        except Exception as exc:
            check(f'{label} does not raise', False, f'{type(exc).__name__}: {exc}')
    check('a zero-duration video does not divide by zero',
          candidates_for(_req(), ALL, 0.0) is not None)
    check('no records at all is an answer, not an exception',
          evaluate_l1(_req(match_hints=['x']), [], _health()) is not None)

    print()
    print('=' * 78)
    if failed:
        print(f'{len(failed)} FAILED of {passed + len(failed)}')
        for f in failed:
            print(f'  - {f}')
        raise AssertionError(f'{len(failed)} Phase 6 test(s) failed')
    print(f'All {passed} Phase 6 tests passed.  (no GPU, no network, no model)')
    print('=' * 78)
    return True


_run_phase6_tests()


# ============================================================================
# §72  Audit TARGET against the compiled brief
# ============================================================================

_p6_brief = None
for _cand in (globals().get('compiled'), globals().get('COMPILED'),
              globals().get('compiled_brief')):
    if isinstance(_cand, dict) and _cand.get('requirements'):
        _p6_brief = _cand
        break
if _p6_brief is None and (DIRS['briefs']).exists():
    _hits = sorted(DIRS['briefs'].glob('*/requirements__*.json'),
                   key=lambda p: p.stat().st_mtime)
    if _hits:
        _p6_brief = read_json(_hits[-1])
        print(f'  brief loaded from disk: {_hits[-1].parent.name}/{_hits[-1].name}')

if _p6_brief is None:
    print('NO COMPILED BRIEF FOUND. Run Phase 4 (§37 onward) first.')
elif not _p6_brief.get('approved'):
    print('=' * 78)
    print('BRIEF NOT APPROVED -- §46 gate')
    print('=' * 78)
    print(f'  brief_hash : {_p6_brief.get("brief_hash")}')
    print(f'  status     : {_p6_brief.get("status")}')
    print(f'  {_p6_brief.get("stats", {}).get("requirements", "?")} requirements '
          f'are compiled but unconfirmed.')
    print()
    print('  Review them, then approve:')
    print("     compiled = approve_brief(compiled, 'your name', 'checked the doc')")
    print()
    print('  To audit anyway (development only -- the verdicts carry no authority):')
    print('     result = audit_video(TARGET, evidence, compiled, allow_unapproved=True)')
else:
    # Pay for the embedding model HERE, where the wait is attributable, rather
    # than inside the per-requirement loop where it looks like a hang.
    warm_l2(P6.l2)
    result = audit_video(TARGET, evidence, _p6_brief, P6, verbose=True)

    _st = result['stats']
    print()
    print(f'requirements      : {_st["requirements"]}')
    print(f'brief             : {result["brief_hash"]}')
    print()
    print('VERDICTS')
    for _s in VERDICT_STATUSES:
        _n = _st['by_status'].get(_s, 0)
        if _n:
            print(f'    {_s:<16} {_n}')
    print()
    print('WHICH LAYER DECIDED  -- the cost of semantics, measured')
    for _l in EVAL_LAYERS:
        _n = _st['by_layer'].get(_l, 0)
        if _n:
            print(f'    {_l:<6} {_n:>3}  ({_st["escalation_rate"].get(_l, 0):.0%})')
    print(f'    L3 calls made : {_st["l3"]["calls"]}  '
          f'backend={_st["l3"]["backend"]}')
    print(f'    fabricated ids: {_st["fabricated_ids"]}   '
          f'citation violations rejected: {len(_st["l3"]["violations"])}')
    print()
    print(f'UNCERTAIN rate    : {_st["uncertain_rate"]:.0%}'
          f'   (above ~20% the EVIDENCE layer is the problem, not the evaluator)')
    print()
    print('CAN A FAIL BE ASSERTED AT ALL?')
    for _m, _ok in (result.get('can_fail_on') or {}).items():
        print(f'    {_m:<20} {"yes" if _ok else "no -- UNCERTAIN only"}')

    print()
    print('=' * 78)
    print('EVERY REQUIREMENT')
    print('=' * 78)
    for _v in result['verdicts']:
        print(f'  [{_v["status"]:<14}] {_v["layer"]:<4} '
              f'{_v["requirement_label"][:52]}')
        print(f'      {_v["reason"][:150]}')
        if _v['evidence_ids']:
            print(f'      cites: {", ".join(_v["evidence_ids"][:4])}')
        elif _v.get('examined_ids'):
            # No citation, but the verdict is still traceable: these are the
            # records it was evaluated against.
            print(f'      cites nothing; examined '
                  f'{", ".join(_v["examined_ids"][:3])}'
                  + (f' +{len(_v["examined_ids"]) - 3} more'
                     if len(_v['examined_ids']) > 3 else ''))
        if _v['flags']:
            print(f'      flags: {", ".join(_v["flags"][:3])}')

    _h = result['hook']
    print()
    print('HOOK  (spec §33)')
    print(f'    present   : {_h["hook_present"]}   type: {_h["hook_type"]}   '
          f'strength: {_h["strength"]}')
    print(f'    window    : {_h["start"]}-{_h["end"]}s   '
          f'within_required_window: {_h["within_required_window"]}')
    print(f'    transcript: "{_h["transcript"][:90]}"')
    print(f'    reason    : {_h["reason"][:150]}')
    _hf = _h['features']
    print(f'    signals   : onset={_hf["speech_onset"]}s question={_hf["has_question"]} '
          f'number={_hf["has_number"]} negation={_hf["has_negation"]} '
          f'you={_hf["has_second_person"]} face={_hf["face_at_camera"]}')
    if _h['flags']:
        print(f'    flags     : {", ".join(_h["flags"])}')

    _c = result['claims']
    print()
    if not _c.get('enabled', True):
        print('CLAIMS / POLICY  (spec §38)  -- OFF')
        print(f'    {_c["note"]}')
        print('    Enable with: P6 = replace(P6, claims=replace(P6.claims, '
              'enabled=True))')
    else:
        print('CLAIMS  (spec §38)')
        print(f'    candidates: {_c["candidates"]}   flagged: {_c.get("flagged", 0)}'
              f'   unclassified: {_c.get("unclassified", 0)}')
        for _cl in _c['claims'][:6]:
            print(f'    [{_cl["claim_class"]:<20} risk={_cl["risk"]:<6}] '
                  f'{_cl["start_seconds"]:.1f}s  "{_cl["text"][:70]}"')
        if _c.get('note'):
            print(f'    {_c["note"]}')
        print(f'    {_c["disclaimer"]}')

    if result['flags']:
        print()
        print('STAGE FLAGS')
        for _f in result['flags']:
            print(f'    {_f["code"]}  {str(_f.get("detail"))[:100]}')


# ============================================================================
# §73  Phase 6 exit criteria
# ============================================================================

def check_phase6_exit_criteria(result: dict, verbose: bool = True) -> bool:
    ok, L = True, []

    def crit(name, passed, detail=''):
        nonlocal ok
        ok = ok and bool(passed)
        L.append(f'  {"PASS" if passed else "FAIL"}  {name}' + (f'   {detail}' if detail else ''))

    vs = result.get('verdicts') or []
    st = result.get('stats') or {}
    can_fail = result.get('can_fail_on') or {}

    crit('every requirement produced a status, evidence ids and a reason',
         bool(vs) and all(v.get('status') and v.get('reason') is not None
                          and isinstance(v.get('evidence_ids'), list) for v in vs),
         f'{len(vs)} requirements')
    crit('every status is in the closed enum',
         all(v['status'] in VERDICT_STATUSES for v in vs))
    crit('INCONCLUSIVE never reached a verdict',
         not any(v['status'] in ROUTING_ONLY for v in vs),
         'it is a routing signal, not a fact about the video')
    crit('ZERO fabricated evidence ids',
         st.get('fabricated_ids', 0) == 0,
         'asserted in the stage, not just here')
    # A FAIL from ABSENCE needs the gate. A FAIL from PRESENCE -- forbidden
    # content actually found -- is grounded in evidence we have, and was already
    # checked against the health of the modality that carried it.
    absence_fails = [v for v in vs if v['status'] == 'FAIL'
                     and not any(f.startswith('FAIL_FROM_POSITIVE_EVIDENCE')
                                 for f in v.get('flags') or [])]
    positive_fails = [v for v in vs if v['status'] == 'FAIL' and v not in absence_fails]
    crit('no FAIL from ABSENCE on a modality that was not healthy',
         not any(not can_fail.get(v['evidence_mode'], False) for v in absence_fails),
         f'{len(absence_fails)} absence-FAIL(s), {len(positive_fails)} from found '
         f'evidence; absence is only evidence when we looked')
    crit('every FAIL from found evidence cites what was found',
         all(v['evidence_ids'] for v in positive_fails),
         'a policy breach with no citation is an accusation, not a finding')
    crit('every PASS cites at least one record',
         all(v['evidence_ids'] for v in vs if v['status'] == 'PASS'),
         'an uncited PASS cannot be checked by a human')
    crit('every verdict records which layer decided it',
         all(v.get('layer') in EVAL_LAYERS for v in vs))
    # A live FAIL read "the OCR evidence only captures day labels like TUE and
    # SA" and cited nothing, so nobody could check which OCR records it meant.
    # Citations stay "what this relies on"; examined_ids is "what it was shown".
    _decided = [v for v in vs if v['status'] in ('PASS', 'PARTIAL', 'FAIL')]
    _blind = [v for v in _decided
              if not v['evidence_ids'] and not v.get('examined_ids')]
    crit('every decided verdict is traceable to records',
         not _blind,
         f'{len(_decided)} decided; '
         f'{sum(1 for v in _decided if not v["evidence_ids"])} cite nothing but '
         f'record what they examined')
    crit('confidence is always labelled with its kind',
         all(v.get('confidence_kind') in VERDICT_CONFIDENCE_KINDS for v in vs),
         'so nothing downstream averages a fuzzy ratio with an LLM self-report')

    # The L3 share is a COST target, and how achievable it is depends on the
    # shape of the brief -- so report it with the reason attached rather than
    # as a bare pass/fail a reader cannot act on.
    #
    # Measured on a real brief of 21 requirements: 0 carried a deadline, so
    # timestamp arithmetic could never fire; every match_hint was a literal
    # scripted sentence and the creator paraphrased all of them, so fuzzy match
    # scored 42-62% against a threshold of 85. All four L1 checks declined
    # CORRECTLY. L2 then scored every pair 0.46-0.62 -- and the highest scorers
    # were hooks the creator did NOT use, so lowering the threshold to catch
    # them would manufacture false PASSes, not save calls.
    #
    # A brief written as a list of exact scripts can only be judged by asking
    # "did they say something equivalent", which is the one question L3 exists
    # for. High escalation there is the right answer to the wrong target.
    l3_share = st.get('escalation_rate', {}).get('L3', 0.0)
    l3_calls = st.get('l3', {}).get('calls', 0)
    n_deadline = sum(1 for v in vs if 'TOLERANCE_STRADDLES_DEADLINE' in (v.get('flags') or []))
    cheap_possible = sum(1 for v in vs if v.get('layer') == 'L1')
    if l3_share <= 0.30:
        crit('L3 handles under 30% of requirements', True,
             f'L3={l3_share:.0%}  L1={st.get("escalation_rate", {}).get("L1", 0):.0%}')
    else:
        L.append(
            f'  NOTE  L3 handled {l3_share:.0%} of requirements, above the 30% '
            f'target -- in {l3_calls} batched API call(s), so the cost is '
            f'{l3_calls} request(s), not {len(vs)}.')
        L.append(
            f'        {cheap_possible} of {len(vs)} were answerable cheaply. '
            f'If the brief is a list of exact scripts the creator paraphrased, '
            f'high escalation is correct: only L3 can judge equivalence.')
        L.append(
            '        Worth acting on only if L1 is missing requirements it '
            'COULD decide -- deadlines, literal phrases actually spoken, or '
            'absent evidence.')

    hook = result.get('hook') or {}
    crit('the hook module produces the full §33 output',
         all(k in hook for k in ('hook_present', 'hook_type', 'start', 'end',
                                 'strength', 'transcript', 'visual',
                                 'within_required_window', 'reason')),
         f'type={hook.get("hook_type")} strength={hook.get("strength")}')
    crit('hook presence is separate from hook strength',
         not (hook.get('hook_present') is False and hook.get('strength')),
         'a hook that does not exist has no strength')
    crit('no numeric hook score came from the model',
         not isinstance(hook.get('strength'), (int, float)),
         'ordinal with written anchors -- spec §33')

    claims = result.get('claims') or {}
    crit('the claims module always carries its disclaimer',
         bool(claims.get('disclaimer')))
    crit('the claims module never asserts the absence of claims',
         (claims.get('claims') or claims.get('note')) is not None,
         'OFF -- and silence is not a clean bill of health'
         if not claims.get('enabled', True) else
         'it detects defined classes; it cannot prove a global negative')
    if not claims.get('enabled', True):
        L.append('  NOTE  policy/claims screening is OFF; brief `forbidden` '
                 'requirements are still evaluated')

    crit('cached by video + evidence + brief, and the brief is an INPUT',
         bool(result.get('cache_key')) and bool(result.get('sources', {}).get('brief')),
         'so one video against three briefs re-runs only this stage')

    unc = st.get('uncertain_rate', 0.0)
    L.append(f'  {"PASS" if unc <= 0.20 else "NOTE"}  UNCERTAIN rate is '
             f'{unc:.0%}' + ('' if unc <= 0.20 else
                             '   -- above ~20%: fix the EVIDENCE layer, not the evaluator'))

    if verbose:
        print('=' * 78)
        print('PHASE 6 EXIT CRITERIA')
        print('=' * 78)
        print('\n'.join(L))
        print('=' * 78)
        print('ALL EXIT CRITERIA MET' if ok else 'NOT ALL CRITERIA MET (see FAIL rows)')
        print('\nStill manual, and only you can close them:')
        print('  - 5 scripts with deliberately planted claims, all flagged')
        print('  - speech_only vs ocr_only verified on a burned-in-caption video')
        print('  - one video audited against 3 briefs: only this stage re-runs')
        print('  - your own hook self-agreement, measured on 10 videos twice')
    return ok


if 'result' in globals():
    check_phase6_exit_criteria(result)
else:
    print('No `result` in scope -- approve the brief and run §72 first.')


# ============================================================================
# §73b  Hand-off to Phase 7
# ============================================================================
print('=' * 78)
print('PHASE 6 COMPLETE')
print('=' * 78)
if 'result' in globals():
    print(f'  verdicts file : work/artifacts/{result["video_hash"][:16]}.../'
          f'verdicts__{result["cache_key"]}.json')
    print(f'  requirements  : {result["stats"]["requirements"]}')
    print(f'  escalation    : ' + '  '.join(
        f'{k}={v:.0%}' for k, v in result['stats']['escalation_rate'].items()))
print()
print('  What Phase 7 calls:')
for _f, _d in [
        ('audit_video(video, evidence, compiled)', 'requirements + hook + claims'),
        ('evaluate_requirements(...)', 'just the verdicts, cached'),
        ('verdicts_for(video_hash, brief_hash)', 'fetch without re-evaluating'),
        ('result["verdicts"][i]["weight"]', 'priority weight, for scoring'),
        ('result["can_fail_on"]', 'which modes could FAIL at all'),
        ('result["stats"]["uncertain_rate"]', 'the health metric to watch')]:
    print(f'    {_f:<44} {_d}')
print()
print('  The rules Phase 7 must not break:')
print('    1. UNCERTAIN is not a low score. It is an abstention, and a scoring')
print('       function that averages it as 0 turns "we did not look" into "they')
print('       failed" -- the exact confusion Phase 5 and 6 were built to prevent.')
print('    2. NOT_APPLICABLE is excluded from the denominator, not scored as 0.')
print('    3. Claims output is assistive. It carries a disclaimer into the report.')
print()
print('  Next: PHASE 7 -- deterministic scoring and reporting (plan.md §7).')
print('=' * 78)