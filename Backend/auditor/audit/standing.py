"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 128.
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
# Deliberately the same shape and the same weights as ALIGNMENT_WEIGHTS, so the
# holistic number and the decomposed number are directly comparable. Two scales
# that mean different things cannot be subtracted, and subtracting them is the
# whole point.
BRIEF_STANDING_LEVELS = ('off_brief', 'tangential', 'partial', 'on_brief',
                         'exemplary')

BRIEF_STANDING_WEIGHTS = {'exemplary': 1.0, 'on_brief': 0.85, 'partial': 0.55,
                          'tangential': 0.25, 'off_brief': 0.0}

BRIEF_STANDING_ANCHORS = {
    'exemplary': 'does what the brief asks and does it well -- the brief\'s '
                 'intent is fully served and the execution adds something the '
                 'brief did not think to ask for',
    'on_brief': 'does what the brief asks, in her own words and her own way. A '
                'different hook, a different structure, a different order -- '
                'same substance. This is the normal good outcome.',
    'partial': 'engages part of what the brief asks and leaves substantial '
               'parts of it untouched',
    'tangential': 'about the product or the topic, but does not engage what '
                  'the brief actually asks for',
    'off_brief': 'does not engage the brief\'s subject at all',
}

STANDING_SYSTEM = """You judge where a short-form video STANDS against the \
content brief it was made for.

You are given the WHOLE brief and the WHOLE record of the video. You are not
being asked to check requirements one by one -- something else already does
that. You are being asked the question that decomposition cannot ask: does this
video do what this brief wants?

HOW TO JUDGE

Judge SUBSTANCE, not wording. The creator is not required to use the brief's
sentences, its hook, its order, or its structure. A video that opens with a
completely different hook and still talks about what the brief asks her to talk
about is ON BRIEF. Marking her down for choosing her own words is the single
most common way this judgement goes wrong.

Ask, in order:
  1. What is this brief actually asking the creator to communicate?
  2. What did she actually communicate?
  3. How much of 1 is present in 2 -- in substance, however she phrased it?

A brief usually asks for a few things that matter (a subject, some points to
make, a call to action, things not to say) surrounded by suggestions and
examples. Weigh what is ASKED FOR. Do not weigh the examples: a list of twelve
sample hooks is the brief showing what KIND of opening it wants, not twelve
separate demands.

WHAT YOU MAY ASSERT

Use ONLY the evidence given. You cannot see or hear the video; you are reading
a record of it. If the record does not show something, you may say it is not
evidenced -- you may NOT say it did not happen.

Every topic you list under "covered" or "missing" must be something the BRIEF
actually asks for. Do not invent asks the brief never made.

Cite evidence ids from the list, or none.

Return ONLY this JSON, no prose and no code fence:
{"standing": "one of the allowed values",
 "verdict": "one sentence: where this video stands against this brief",
 "reasoning": "two or three sentences grounded in the evidence",
 "covered": ["what the brief asks for that she DID communicate"],
 "missing": ["what the brief asks for that the record does not show"],
 "off_brief_additions": ["anything substantial she did that the brief did not ask for"],
 "angle_serves_brief": true,
 "angle_reason": "one sentence: does her creative angle still serve the brief?",
 "evidence_ids": ["..."],
 "confidence": "high | medium | low"}"""

STANDING_PROMPT_VERSION = 'p6_standing_v1'

# Budgets. A truncated record cannot support a claim that something is MISSING,
# so truncation is flagged and the missing list is downgraded when it happens.
STANDING_LIMITS = {'brief_chars': 7000, 'speech_chars': 6000,
                   'ocr_chars': 2000, 'visual_chars': 2500}

def _standing_video_digest(records: list, duration: float,
                           limits: dict = None) -> tuple:
    """The whole video as the model sees it: every modality, in time order.

    Returns (lines, offered_ids, truncation_flags). Unlike retrieval, this
    deliberately does NOT rank or filter by a requirement -- the point of this
    pass is that nothing has been selected for it.
    """
    lim = limits or STANDING_LIMITS
    flags, offered = [], []
    lines = []

    def _block(title, mods, budget, fmt):
        nonlocal flags
        rs = sorted([r for r in records if r.modality in mods],
                    key=lambda r: (r.start_seconds, r.end_seconds))
        lines.append('')
        lines.append(title)
        used, shown, seen_text = 0, 0, set()
        for r in rs:
            body = (r.raw_text or r.description or '').strip().replace('\n', ' ')
            if not body:
                continue
            # OCR repeats the same burnt-in caption on frame after frame. The
            # duplicates cost budget and tell the model nothing new.
            k = (r.modality, body.lower()[:80])
            if k in seen_text:
                continue
            seen_text.add(k)
            line = fmt(r, body)
            if used + len(line) > budget:
                flags.append(f'STANDING_TRUNCATED:{mods[0]}')
                lines.append(f'  ... {len(rs) - shown} further {mods[0]} record(s) '
                             f'not shown (budget)')
                break
            lines.append(line)
            offered.append(r.id)
            used += len(line)
            shown += 1
        if not shown:
            lines.append('  (none)')
        return shown

    n_speech = _block(
        'WHAT SHE SAYS (full transcript, in order):', ('speech',),
        lim['speech_chars'],
        lambda r, b: f'  - id={r.id} [{r.start_seconds:.1f}-{r.end_seconds:.1f}s] "{b}"')
    _block(
        'TEXT ON SCREEN:', ('ocr',), lim['ocr_chars'],
        lambda r, b: f'  - id={r.id} [{r.start_seconds:.1f}s] "{b}"')
    _block(
        'WHAT IS VISIBLE:', ('visual',), lim['visual_chars'],
        lambda r, b: f'  - id={r.id} [{r.start_seconds:.1f}-{r.end_seconds:.1f}s] {b}')
    lines.insert(0, f'THE VIDEO: {duration:.1f} seconds long, '
                    f'{n_speech} spoken segment(s).')
    return lines, offered, flags

def _standing_topic_seen_in_brief(topic: str, brief_text: str,
                                  min_coverage: float = 0.5) -> bool:
    """Is this named ask actually in the brief, however the model paraphrased it?

    Same guard as the creative angle's nearest_brief_concept, but the model is
    summarising a brief in its own words here, so exact membership would reject
    almost every correct answer.

    CONTENT WORDS, not a whole-string fuzzy ratio. Measured: a fuzzy
    partial_token_set_ratio accepted "a free consultation with a dermatologist"
    against a brief that never mentions consultations or dermatologists --
    because that metric scores the best-matching token SUBSET, and filler words
    alone carried it over the bar. Half a topic's content words having to appear
    in the brief is a test the filler cannot pass.

    Deliberately generous on the words that do appear: _tokens_match handles
    stems and near-misses, so "reduces hair loss" still matches "reduce hair
    loss". This catches INVENTIONS; it does not grade paraphrase quality.
    """
    toks = content_tokens(topic or '')
    if not toks or not brief_text:
        return False
    btoks = set(content_tokens(brief_text))
    if not btoks:
        return False
    hit = sum(1 for t in toks
              if t in btoks or any(_tokens_match(t, b, 85) for b in btoks))
    return (hit / len(toks)) >= min_coverage

def decomposed_mean_alignment(result: dict) -> tuple:
    """The decomposed audit's own number, computed the way §74 reports it.

    One function so the holistic pass and the self-check cannot drift into
    comparing two differently-computed means and calling the difference a
    disagreement.
    """
    vs = (result or {}).get('verdicts') or []
    scored = [v for v in vs
              if v.get('status') != 'NOT_APPLICABLE' and v.get('alignment')]
    if not scored:
        return None, 0
    return (sum(ALIGNMENT_WEIGHTS.get(v['alignment'], 0.0)
                for v in scored) / len(scored)), len(scored)

def evaluate_standing(records: list, compiled: dict, result: dict,
                      health: dict = None, backend=None,
                      cfg: Phase6Config = None, verbose: bool = True) -> dict:
    """The whole brief against the whole video. Never raises."""
    cfg = cfg or P6
    brief_text = (compiled or {}).get('brief_text') or ''
    out = {
        'standing': None, 'weight': None, 'verdict': '', 'reasoning': '',
        'covered': [], 'missing': [], 'off_brief_additions': [],
        'angle_serves_brief': None, 'angle_reason': '',
        'evidence_ids': [], 'confidence': None, 'layer': 'L3',
        'flags': [], 'prompt_version': STANDING_PROMPT_VERSION,
        'decomposed_mean_alignment': None, 'decomposed_units': 0,
        'disagreement': None,
        'anchors': dict(BRIEF_STANDING_ANCHORS),
        'disclaimer': (
            'This is a SECOND OPINION on the same video, read whole rather than '
            'decomposed into requirements. It does not overrule the per-'
            'requirement verdicts and it is not averaged with them. Where the '
            'two disagree, the disagreement is the finding.'),
    }
    dm, du = decomposed_mean_alignment(result)
    out['decomposed_mean_alignment'] = None if dm is None else round(dm, 3)
    out['decomposed_units'] = du

    if not brief_text:
        out.update(reasoning='The compiled brief carries no text to judge '
                             'against.', flags=['STANDING_NO_BRIEF_TEXT'],
                   layer='L1')
        return out
    # ANY usable evidence, not speech specifically. The digest below builds
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
        out['flags'].append('STANDING_WITHOUT_SPEECH')
    if not cfg.l3.enabled:
        out.update(reasoning='L3 is disabled, and this judgement needs the '
                             'language model.',
                   flags=out['flags'] + ['STANDING_NOT_JUDGED'], layer='L1')
        return out

    duration = float((result or {}).get('duration_seconds') or 0.0)
    vlines, offered, tflags = _standing_video_digest(records, duration)
    out['flags'] += tflags

    btxt = brief_text.strip()
    if len(btxt) > STANDING_LIMITS['brief_chars']:
        btxt = btxt[:STANDING_LIMITS['brief_chars']]
        out['flags'].append('STANDING_TRUNCATED:brief')

    lines = ['THE BRIEF, IN FULL:', '', btxt, '', '=' * 60]
    lines += vlines
    ang = (result or {}).get('creative_angle') or {}
    hook = (result or {}).get('hook') or {}
    if ang.get('angle') or hook.get('hook_type'):
        lines += ['', 'WHAT OTHER MODULES READ (context, not instruction):']
        if ang.get('angle'):
            lines.append(f'  - the creative angle module read this video as: '
                         f'{ang["angle"]}')
        if hook.get('hook_type'):
            lines.append(f'  - the hook module read the opening as: '
                         f'{hook["hook_type"]}')
    lines += ['', 'Allowed standing values, and what each one means:']
    for lvl in reversed(BRIEF_STANDING_LEVELS):
        lines.append(f'  {lvl}: {BRIEF_STANDING_ANCHORS[lvl]}')

    bcfg = replace(P4.brief, temperature=0.0, max_new_tokens=1600)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(STANDING_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _ = parse_model_json(gen.get('text', '') or '')
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'
    if not isinstance(obj, dict):
        out.update(reasoning=f'The standing model returned nothing usable '
                             f'({perr}).', flags=out['flags'] + ['STANDING_MODEL_FAILED'])
        return out

    st = str(obj.get('standing') or '').lower().strip()
    if st not in BRIEF_STANDING_LEVELS:
        out['flags'].append(f'STANDING_OUT_OF_ENUM:{st[:30]}')
        st = None
    offered_set = set(offered)
    ids = [i for i in (obj.get('evidence_ids') or []) if i in offered_set]
    if len(ids) < len([i for i in (obj.get('evidence_ids') or [])]):
        out['flags'].append('STANDING_CITED_UNOFFERED_IDS')

    def _topics(key, verify=True):
        vals, bad = [], []
        for t in (obj.get(key) or [])[:12]:
            t = str(t).strip()[:160]
            if not t:
                continue
            if verify and not _standing_topic_seen_in_brief(t, brief_text):
                bad.append(t)
                continue
            vals.append(t)
        if bad:
            out['flags'].append(f'STANDING_TOPIC_NOT_IN_BRIEF:{key}:{len(bad)}')
        return vals

    conf = str(obj.get('confidence') or '').lower().strip()
    out.update(
        standing=st,
        weight=(BRIEF_STANDING_WEIGHTS[st] if st else None),
        verdict=str(obj.get('verdict') or '')[:400],
        reasoning=str(obj.get('reasoning') or '')[:900],
        # covered/missing name things the BRIEF asks for, so they are checked
        # against the brief. off_brief_additions name things it does NOT, so
        # checking them against the brief would reject every correct answer.
        covered=_topics('covered'),
        missing=_topics('missing'),
        off_brief_additions=_topics('off_brief_additions', verify=False),
        angle_serves_brief=(bool(obj.get('angle_serves_brief'))
                            if obj.get('angle_serves_brief') is not None else None),
        angle_reason=str(obj.get('angle_reason') or '')[:300],
        evidence_ids=ids,
        confidence=(conf if conf in ('high', 'medium', 'low') else None))

    # An absence claimed from an incomplete record is not an absence.
    can_fail = modes_that_can_fail(health or {})
    if not can_fail.get('any', False) or any(
            str(f).startswith('STANDING_TRUNCATED') for f in out['flags']):
        if out['missing']:
            out['flags'].append('STANDING_MISSING_UNVERIFIED')
            out['missing_is_unverified'] = True
    if not ids:
        out['flags'].append('STANDING_UNCITED')

    # THE POINT OF THIS PASS.
    #
    # Two independent reads of the same video on the same scale. Where they
    # agree, the audit is probably right. Where they diverge, one of them has
    # made a mistake worth a human's attention -- most often the decomposition
    # scoring a brief's EXAMPLES as if they were its DEMANDS.
    #
    # Reported, never blended. A mean of the two would hide precisely the case
    # this exists to catch.
    if out['weight'] is not None and dm is not None:
        gap = round(out['weight'] - dm, 3)
        out['disagreement'] = gap
        if abs(gap) >= 0.25:
            out['flags'].append(
                f'STANDING_DISAGREES_WITH_REQUIREMENTS:{gap:+.2f}')
    if verbose:
        _w = '' if out['weight'] is None else f' [{out["weight"]:.2f}]'
        _d = ('' if out['disagreement'] is None
              else f'   (requirements say {dm:.2f}, gap {out["disagreement"]:+.2f})')
        print(f'  standing: {out["standing"] or "unjudged"}{_w}{_d}')
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 378: print('§69c standing loaded.  The whole brief against the whole video -- a s
