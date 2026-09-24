"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 123.
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
        _hf = globals().get('ensure_hf_token')
        if callable(_hf):
            _hf()                  # BGE comes off the Hub too
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

_EMBED_CACHE = {}

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
    return _np.stack([_EMBED_CACHE[t] for t in prepped])

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
                'L2', evidence_ids=[c['record'].id for c in top],   # a candidate is a DICT around a record
                confidence=sim, confidence_kind='derived',
                flags=['L2_THRESHOLD_PLACEHOLDER',
                       f'MODE_SHORTFALL:{",".join(missing)}'],
                candidates_considered=len(cands))
        return _blank_verdict(
            rd, 'PASS',
            f'{rec.modality} evidence at {_fmt_t(rec)} is semantically close to '
            f'the requirement (cosine {sim:.2f}): '
            f'"{(rec.raw_text or rec.description)[:110]}"',
            'L2', evidence_ids=[c['record'].id for c in top],   # a candidate is a DICT around a record
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


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 172: print('§66 L2 loaded.  warm_l2() installs and loads it; absence disables the
