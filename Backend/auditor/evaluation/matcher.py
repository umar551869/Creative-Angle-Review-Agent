"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 53.
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
def search_transcript(transcript: Optional[dict], phrase: str, min_score: int = 88) -> list:
    if not transcript:
        return []
    return find_phrase(transcript['word_spans'], phrase, min_score=min_score)

def search_ocr(ocr: dict, phrase: str, min_score: int = 85,
               exclude_derived_from_speech: bool = False) -> list:
    out = []
    for variant in phrase_variants(phrase):
        for iv in ocr['intervals']:
            if exclude_derived_from_speech and iv['derived_from_speech']:
                continue
            # Numbers first: similarity cannot tell 20% from 25% (measured 91.7),
            # so a numeric requirement must have its numbers actually present.
            if digits_missing(variant, iv['norm_text']):
                continue
            # contains_ratio, NOT partial_ratio: an interval reading only 'shop'
            # must not score 100 for the requirement 'shop now'.
            score = contains_ratio(variant, iv['norm_text'])
            if score >= min_score:
                out.append({'interval_id': iv['id'], 'text': iv['text'],
                            'matched_variant': variant, 'score': int(score),
                            'start': iv['first_seen'], 'end': iv['last_seen'],
                            'derived_from_speech': iv['derived_from_speech'],
                            'independence': iv.get('independence', 'unknown'),
                            'low_confidence': iv['low_confidence']})
    best = {}
    for m in out:
        if m['interval_id'] not in best or m['score'] > best[m['interval_id']]['score']:
            best[m['interval_id']] = m
    return sorted(best.values(), key=lambda m: -m['score'])

def check_requirement(transcript, ocr, phrase: str, evidence_mode: str = 'speech_or_text',
                      deadline_s: Optional[float] = None) -> dict:
    """
    A preview of Phase 6's L1 deterministic layer. Real logic, narrow scope.
    evidence_mode: speech_only | ocr_only | speech_or_text
    """
    speech = search_transcript(transcript, phrase)
    # derived_from_speech text IS on screen. It must not count as a SECOND,
    # independent confirmation alongside the speech -- but it absolutely counts
    # as on-screen evidence. Excluding it here would drop a real product label
    # from an ocr_only requirement just because the creator also said the name
    # (measured: 'aurelia hair perfection' label vs its spoken name -> recall 100).
    # The `independence` field on each hit is what Phase 6 uses to avoid
    # double-counting; presence is decided here.
    visual = search_ocr(ocr, phrase, exclude_derived_from_speech=False)

    if evidence_mode == 'speech_only':
        hits = [{'modality': 'speech', **m} for m in speech]
    elif evidence_mode == 'ocr_only':
        hits = [{'modality': 'ocr', **m} for m in visual]
    else:
        hits = ([{'modality': 'speech', **m} for m in speech] +
                [{'modality': 'ocr', **m} for m in visual])

    if not hits:
        status = 'UNCERTAIN' if (transcript is None and evidence_mode != 'ocr_only') else 'FAIL'
        return {'phrase': phrase, 'evidence_mode': evidence_mode, 'status': status,
                'reason': 'no matching evidence found', 'evidence': []}

    starts = [h['start'] for h in hits if h.get('start') is not None]
    if not starts:
        return {'phrase': phrase, 'evidence_mode': evidence_mode, 'status': 'UNCERTAIN',
                'reason': 'matched, but no usable timestamp on the evidence',
                'evidence': hits}
    earliest = min(starts)
    if deadline_s is not None and earliest > deadline_s:
        return {'phrase': phrase, 'evidence_mode': evidence_mode, 'status': 'PARTIAL',
                'reason': f'found at {earliest:.2f}s, after the {deadline_s:.1f}s deadline',
                'evidence': hits}
    return {'phrase': phrase, 'evidence_mode': evidence_mode, 'status': 'PASS',
            'reason': f'found at {earliest:.2f}s', 'evidence': hits}

# --- try it ------------------------------------------------------------------
TEST_PHRASES = [
    ('shop now',      'speech_or_text', None),
    ('link in bio',   'speech_or_text', None),
    ('20% off',       'speech_or_text', None),
    ('hydration',     'speech_or_text', 10.0),
]


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 90: print('Milestone A preview — deterministic requirement checks, zero GPU:\n')
#   line 91: for phrase, mode, deadline in TEST_PHRASES:
#   line 99: print('\nEdit TEST_PHRASES with lines from your own brief.')
#   line 100: print('Phase 6 adds embeddings (L2) and LLM adjudication (L3) on top of exac
