"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 26.
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
def _speech_windows(iv: dict, words: list, cfg: CaptionCheckConfig) -> list:
    """
    Length-matched speech windows across the interval's lifetime.

    Comparing against ALL speech inside [first_seen - pad, last_seen + pad] means
    a caption on screen for the whole video is compared with the entire
    transcript -- and its words count as "spoken" even if said minutes apart.
    Instead slide a window about the size of the OCR text across that span and
    keep the best match: the words must have been said TOGETHER.
    """
    lo = iv['first_seen'] - cfg.time_window_s
    hi = iv['last_seen'] + cfg.time_window_s
    cand = [w for w in words if w.get('start') is not None and lo <= w['start'] <= hi]
    if not cand:
        return []
    k = max(1, len(iv['norm_text'].split()))
    size = max(k + cfg.window_slack_words, int(round(k * cfg.window_scale)))
    if len(cand) <= size:
        return [cand]
    n_positions = len(cand) - size + 1
    step = max(1, math.ceil(n_positions / cfg.max_windows))
    starts = list(range(0, n_positions, step))
    if starts[-1] != n_positions - 1:
        starts.append(n_positions - 1)          # always include the final window
    return [cand[i:i + size] for i in starts]

# ----------------------------------------------------------------------------
# Readability gate -- does this string contain WORDS, or is it OCR noise?
#
# Mirrored on-screen text is the case that forced this. PP-OCR reading a
# horizontally flipped logo returns things like
#     'YTIJATIV RAJUA HVIB bEBEECLIOM'   (AURELIA HAIR PERFECTION, mirrored)
# which is long enough to clear the min_chars/min_tokens gate, does not match
# the speech (because it is not language), and was therefore being labelled
# 'confirmed_independent' -- the STRONGEST evidence class in the whole system.
# Phase 6 would have accepted unreadable noise as proof that on-screen text
# satisfied a requirement.
#
# The test is deliberately simple: what fraction of the content tokens are real
# dictionary words? Measured on this video, garbled mirror text scores 0 and
# genuine captions score 67-100, so the threshold sits in a very wide gap.
# ----------------------------------------------------------------------------
def _load_word_vocab():
    """wordninja already ships a ~125k word list; reuse it rather than add a dep."""
    if _wordninja is None:
        return None
    lm = getattr(_wordninja, 'DEFAULT_LANGUAGE_MODEL', None)
    for attr in ('_wordcost', 'wordcost'):
        wc = getattr(lm, attr, None) if lm is not None else None
        if isinstance(wc, dict) and len(wc) > 1000:
            return frozenset(wc.keys())
    return None

_WORD_VOCAB = _load_word_vocab()

OCR_READABILITY_MIN = 40      # percent of content tokens that must be real words

_READABILITY_LONE_TOKEN = 8   # a single token this long is fair game to judge

def text_readability(text: str, min_score: int = OCR_READABILITY_MIN) -> dict:
    """
    {'score', 'n_tokens', 'matched', 'verdict'} where verdict is
    'readable' | 'unreadable' | 'too_short_to_judge'.

    Digits are stripped from tokens before the lookup ('SAVE20' -> 'save'), and
    a lone short token is never judged, so a brand name on its own ('AURELIA')
    is left alone rather than called noise.
    """
    toks = [re.sub(r'[^a-z]', '', t) for t in normalize_text(text or '').split()]
    toks = [t for t in toks if len(t) >= 3]
    judgeable = len(toks) >= 2 or (len(toks) == 1 and len(toks[0]) >= _READABILITY_LONE_TOKEN)
    if not toks or not judgeable or _WORD_VOCAB is None:
        return {'score': None, 'n_tokens': len(toks), 'matched': [],
                'verdict': 'too_short_to_judge'}
    # a phrase we already know about is readable whatever the dictionary says
    if any(g in normalize_text(text or '') for g in OCR_PHRASE_GAZETTEER):
        return {'score': 100, 'n_tokens': len(toks), 'matched': ['gazetteer'],
                'verdict': 'readable'}
    matched = [t for t in toks if t in _WORD_VOCAB]
    score = int(round(100 * len(matched) / len(toks)))
    return {'score': score, 'n_tokens': len(toks), 'matched': matched,
            'verdict': 'readable' if score >= min_score else 'unreadable'}

def _test_readability():
    """
    Calibrated on REAL output from a mirrored-logo video. Garbled text scored 0
    and genuine captions 67-100, so the threshold sits in a 67-point gap -- the
    widest margin of any threshold in this pipeline.
    """
    garbage = ['YTIJATIV RAJUA HVIB bEBEECLIOM', 'HVIB EBEECIION',
               'ITUAIVAA HVIB bEBEECIIOM', 'YTIJATIVAAJUI',
               'ELEKNCETT "asbitome19) 2l9ptto200']
    real = ["You don't need a list of resolutions for healthier hair.",
            'All you need is one routine clinically tested and proven',
            'provento support hair growth.', 'HAIR SHINE MATTERS',
            'CODE SAVE20', 'LINK IN BIO', 'SHOP NOW', 'AURELIA HAIR PERFECTION']
    brands = ['AURELIA', 'CERAVE', 'OLAPLEX']
    bad = []
    if _WORD_VOCAB is None:
        print('  readability self-test SKIPPED (no word list)')
        return
    for g in garbage:
        if text_readability(g)['verdict'] != 'unreadable':
            bad.append(f'garbage not caught: {g[:36]!r} -> {text_readability(g)}')
    for t in real:
        if text_readability(t)['verdict'] == 'unreadable':
            bad.append(f'real text flagged: {t[:36]!r} -> {text_readability(t)}')
    for b in brands:
        # a lone brand word is not judged at all -- we cannot tell it from noise,
        # and calling it noise would delete legitimate evidence
        if text_readability(b)['verdict'] == 'unreadable':
            bad.append(f'brand flagged: {b!r}')
    gs = [text_readability(g)['score'] for g in garbage if text_readability(g)['score'] is not None]
    rs = [text_readability(t)['score'] for t in real if text_readability(t)['score'] is not None]
    if gs and rs and max(gs) >= min(rs):
        bad.append(f'classes overlap: garbage<={max(gs)} real>={min(rs)}')
    if bad:
        raise AssertionError('readability gate: ' + '; '.join(bad[:3]))
    print(f'  readability self-test: {len(garbage)} garbage rejected, '
          f'{len(real)} captions kept, gap {min(rs) - max(gs)} points')

def cross_check_captions(intervals: list, transcript: dict, cfg: CaptionCheckConfig) -> dict:
    # Readability first, and independently of whether there is any speech: text
    # that is not words cannot be evidence of anything, so it must never reach
    # 'confirmed_independent' by the back door of "it didn't match the audio".
    n_unreadable = 0
    for iv in intervals:
        rd = text_readability(iv['text'])
        iv['readability'] = rd['score']
        iv['readable'] = rd['verdict'] != 'unreadable'
        if not iv['readable']:
            n_unreadable += 1

    words = transcript.get('words', [])
    if not words or not intervals:
        # No transcript at all -> nothing was verified. 'unknown', never 'independent'.
        for iv in intervals:
            iv['independence'] = 'unreadable' if not iv['readable'] else 'unknown'
        return {'checked': 0, 'flagged': 0, 'details': [],
                'unknown': sum(1 for iv in intervals if iv['readable']),
                'unreadable': n_unreadable, 'confirmed_independent': 0}

    details, flagged = [], 0
    for iv in intervals:
        if not iv['readable']:
            # Not language. Comparing it to speech would be meaningless, and the
            # answer ("doesn't match") would be read as proof of independence.
            iv['derived_from_speech'] = False
            iv['speech_match_score'] = None
            iv['speech_check'] = 'SKIPPED_UNREADABLE'
            iv['independence'] = 'unreadable'
            continue

        norm = iv['norm_text']
        if len(norm) < cfg.min_chars or len(norm.split()) < cfg.min_tokens:
            # Too short to compare RELIABLY. This is NOT evidence of independence.
            # Phase 6 must treat 'unknown' as unverified, or 125 pieces of garbled
            # mirror text become eligible to satisfy an ocr_only requirement.
            iv['derived_from_speech'] = False
            iv['speech_match_score'] = None
            iv['speech_check'] = 'SKIPPED_TOO_SHORT'
            iv['independence'] = 'unknown'
            continue

        windows = _speech_windows(iv, words, cfg)
        if not windows:
            # Nobody was speaking anywhere near this text -> genuinely independent.
            iv['derived_from_speech'] = False
            iv['speech_match_score'] = 0
            iv['speech_check'] = 'NO_SPEECH_IN_WINDOW'
            iv['independence'] = 'confirmed_independent'
            continue

        # Best match across length-matched windows: the moment it was being SAID.
        best = None
        for win in windows:
            wtext = normalize_text(' '.join(w['word'] for w in win))
            s = caption_similarity(norm, wtext, cfg.token_match_min,
                                   cfg.recall_min_content_tokens)
            if best is None or s['score'] > best[0]['score']:
                best = (s, wtext, win[0].get('start'), win[-1].get('end'))
        sim, window_text, w_start, w_end = best

        score = sim['score']
        iv['speech_match_score'] = score
        iv['speech_match_method'] = sim['method']
        iv['speech_match_window'] = [w_start, w_end]
        iv['speech_match_components'] = {k: sim[k] for k in
                                         ('contains', 'token_set', 'token_sort', 'token_recall')}
        iv['derived_from_speech'] = bool(score >= cfg.similarity_threshold)
        iv['speech_check'] = 'MATCHED' if iv['derived_from_speech'] else 'INDEPENDENT'
        iv['independence'] = ('derived_from_speech' if iv['derived_from_speech']
                              else 'confirmed_independent')
        if iv['derived_from_speech']:
            flagged += 1
        details.append({'interval_id': iv['id'], 'ocr_text': iv['text'],
                        'window_text': window_text[:90], 'score': score,
                        'method': sim['method'],
                        'contains': sim['contains'], 'token_set': sim['token_set'],
                        'token_recall': sim['token_recall'],
                        'recall_matched': sim['recall_matched'],
                        'window_start': w_start,
                        'derived_from_speech': iv['derived_from_speech'],
                        'independence': iv['independence']})

    counts = {}
    for iv in intervals:
        counts[iv.get('independence', 'unknown')] = counts.get(iv.get('independence', 'unknown'), 0) + 1
    return {'checked': len(details), 'flagged': flagged,
            'flagged_ratio': round(flagged / max(1, len(details)), 3),
            'independence_counts': counts,
            'unknown': counts.get('unknown', 0),
            'confirmed_independent': counts.get('confirmed_independent', 0),
            'config': asdict(cfg), 'details': details}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 64: if _WORD_VOCAB is None:
#   line 231: _test_readability()
#   line 232: print('caption_check.py loaded')
