"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 121.
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
        # (?!\w), not \b, to close the match.
        #
        # \b asserts a change between word and non-word. A term ending in
        # punctuation -- '27%', '$5' -- is followed by a space, and two non-word
        # characters have no boundary between them, so the pattern could never
        # match. '27%' being 3 characters then took the short-term exit below,
        # and the hint matched nothing, anywhere, ever.
        #
        # (?!\w) says the thing that was meant: not followed by a word
        # character. It holds after '%' and after 'l', so 'heal' still refuses
        # to match 'healthy'.
        if re.search(r'\b' + re.escape(t) + r'(?:s|es|ed|d|ing)?(?!\w)', hay):
            return True, 100
    except re.error:
        if t in hay:
            return True, 100
    if len(t) < SHORT_TERM_CHARS and ' ' not in t:
        return False, 0                       # 'heal' is not 'healthy'
    # partial_ratio is ASYMMETRIC: it slides the SHORTER string over the longer.
    # When the record is shorter than the phrase, rapidfuzz makes the RECORD the
    # pattern, and the question silently flips from "does this phrase appear in
    # this record?" to "does this record appear inside this phrase?".
    #
    # Measured on a live run: the OCR fragment "hair" scored 100 against the hook
    # "Blow drying your hair could be damaging your hair everyday", and "a perm"
    # scored 100 against "What they don't tell you before you get a perm". That
    # video carries 204 OCR intervals, most of them a word or two, so every hook
    # option found some fragment matching it at 100. All twelve were decided at
    # L1 as `exact` -- on a video about pill organisers -- and the choice group
    # then picked its winner from a twelve-way tie.
    #
    # A record too short to hold the phrase cannot be evidence of it. Against a
    # haystack longer than the hint, the same comparisons score 42-63, which is
    # the honest answer. An exact phrase in a long transcript still returns 100
    # from the word-boundary test above, before this is ever reached.
    if len(hay) < len(t) * 0.8:
        return False, 0
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

def spread_sample(cands: list, k: int) -> list:
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

def _dedupe_candidates(cands: list) -> list:
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
    # One modality must not take every slot -- see _balance_modalities. The
    # dedupe runs first so the slots that survive carry DISTINCT facts.
    return _balance_modalities(_dedupe_candidates(out), rc.top_k,
                               getattr(rc, 'max_modality_share', 0.6))

def candidate_ids(cands: list) -> list:
    return [c['record'].id for c in cands]


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 281: print('§64 retrieval loaded.  candidates_for(requirement, records, duration)
