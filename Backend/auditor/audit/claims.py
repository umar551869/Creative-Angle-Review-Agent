"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 126.
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


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 177: print('§69 claims module loaded.  High recall; never asserts the absence of 
