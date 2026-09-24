"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 19.
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
_PUNCT_KEEP = set('%$&+')          # meaningful in ad copy: 20% off, $5, 2+1

_PUNCT_TABLE = {ord(c): None for c in string.punctuation if c not in _PUNCT_KEEP}

NUMBER_WORDS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
    'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'ten': '10',
    'eleven': '11', 'twelve': '12', 'thirteen': '13', 'fourteen': '14',
    'fifteen': '15', 'sixteen': '16', 'seventeen': '17', 'eighteen': '18',
    'nineteen': '19', 'twenty': '20', 'thirty': '30', 'forty': '40',
    'fifty': '50', 'sixty': '60', 'seventy': '70', 'eighty': '80',
    'ninety': '90', 'hundred': '100',
}

NUMBER_WORDS_INV = {v: k for k, v in NUMBER_WORDS.items()}

# Compounds. NUMBER_WORDS alone covers 0-20 and the round tens, which leaves
# 'twenty five' folding to the nonsense pair '20 5' -- and 25%/35% are ordinary
# discounts. Tens+unit and unit+hundred are handled as units.
_TENS_WORDS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
               'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}

_UNIT_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
               'six': 6, 'seven': 7, 'eight': 8, 'nine': 9}

# Concatenated forms: what a stripped hyphen leaves behind ('twenty-five').
_COMPOUND_WORDS = {t + u: str(tv + uv)
                   for t, tv in _TENS_WORDS.items()
                   for u, uv in _UNIT_WORDS.items()}

def _fold_number_words(tokens: list) -> list:
    """Word tokens -> digits, compounds included. Runs left to right, greedily."""
    out, i, n = [], 0, len(tokens)
    while i < n:
        w = tokens[i]
        if w in _TENS_WORDS and i + 1 < n and tokens[i + 1] in _UNIT_WORDS:
            out.append(str(_TENS_WORDS[w] + _UNIT_WORDS[tokens[i + 1]]))   # twenty five -> 25
            i += 2
            continue
        if w in _UNIT_WORDS and i + 1 < n and tokens[i + 1] == 'hundred':
            out.append(str(_UNIT_WORDS[w] * 100))                          # two hundred -> 200
            i += 2
            continue
        if w in _COMPOUND_WORDS:
            out.append(_COMPOUND_WORDS[w])                                 # twentyfive -> 25
            i += 1
            continue
        out.append(NUMBER_WORDS.get(w, w))
        i += 1
    return out

def _number_to_words(n: int) -> str:
    """0-100 as words. '' when there is no single-token-pair spelling."""
    if n < 0 or n > 100:
        return ''
    if str(n) in NUMBER_WORDS_INV:
        return NUMBER_WORDS_INV[str(n)]
    tens, unit = divmod(n, 10)
    tw = NUMBER_WORDS_INV.get(str(tens * 10), '')
    uw = NUMBER_WORDS_INV.get(str(unit), '')
    return f'{tw} {uw}' if tw and uw else ''

def normalize_token(token: str) -> str:
    """Light normalization. Preserves a 1:1 relationship with the source word."""
    t = token.strip().lower().translate(_PUNCT_TABLE)
    return ' '.join(t.split())

def normalize_text(text: str, expand_numbers: bool = True) -> str:
    """
    Full normalization for standalone strings (OCR lines, requirement phrases).
    Collapses whitespace, strips punctuation, folds number words to digits,
    and joins '20 %' -> '20%'.
    """
    # Hyphens become spaces BEFORE punctuation is stripped. Stripping first would
    # collapse 'twenty-five' to 'twentyfive' and '25-50% off' to '2550% off'.
    t = text.lower()
    for dash in ('-', '‐', '‑', '–', '—'):
        t = t.replace(dash, ' ')
    t = t.translate(_PUNCT_TABLE)
    tokens = t.split()
    if expand_numbers:
        tokens = _fold_number_words(tokens)
    t = ' '.join(tokens)
    t = re.sub(r'(\d)\s+%', r'\1%', t)
    t = re.sub(r'\$\s+(\d)', r'$\1', t)
    return t.strip()

def phrase_variants(phrase: str) -> list:
    """
    Query-side expansion. '20% off' also searches for 'twenty percent off'
    and '20 percent off'. This is what lets the transcript index stay in
    light-normalization space without losing recall.
    """
    base = normalize_text(phrase)
    variants = {base, normalize_text(phrase, expand_numbers=False)}

    # digits -> words, compounds included: '25% off' -> 'twenty five percent off'
    def _word_form(tok: str) -> str:
        if tok.isdigit():
            return _number_to_words(int(tok)) or tok
        m = re.fullmatch(r'(\d+)%', tok)
        if m:
            w = _number_to_words(int(m.group(1)))
            return f'{w} percent' if w else tok
        return tok

    variants.add(' '.join(_word_form(w) for w in base.split()))
    # '%' -> ' percent'
    for v in list(variants):
        if '%' in v:
            variants.add(re.sub(r'(\d+)%', r'\1 percent', v))
            variants.add(re.sub(r'(\d+)%',
                                lambda m: (_number_to_words(int(m.group(1))) or m.group(1)) + ' percent',
                                v))
    return sorted(v for v in variants if v)

def build_word_index(words: list) -> tuple:
    """
    words: [{'word', 'start', 'end', 'probability'}, ...]
    Returns (normalized_text, spans) where each span carries the exact character
    range in normalized_text AND the timestamps of the word it came from.
    """
    parts, spans, pos = [], [], 0
    for i, w in enumerate(words):
        tok = normalize_token(w.get('word', ''))
        if not tok:
            continue
        if parts:
            parts.append(' '); pos += 1
        spans.append({
            'char_start': pos, 'char_end': pos + len(tok),
            'word_index': i, 'token': tok,
            'start': w.get('start'), 'end': w.get('end'),
        })
        parts.append(tok); pos += len(tok)
    return ''.join(parts), spans

def _token_windows(spans: list, size: int):
    """Yield (start_idx, end_idx_exclusive) sliding windows over token spans."""
    n = len(spans)
    for i in range(max(0, n - size + 1)):
        yield i, i + size

def find_phrase(spans: list, phrase: str, min_score: int = 88) -> list:
    """
    Fuzzy phrase search over the token index. Implemented as an explicit n-gram
    sliding window rather than via a library alignment API -- deterministic,
    version-proof, and it returns exact word indices, hence exact timestamps.
    """
    if not spans:
        return []
    matches, seen = [], set()

    for variant in phrase_variants(phrase):
        vtokens = variant.split()
        if not vtokens:
            continue
        k = len(vtokens)
        # allow the window to be one token shorter/longer than the query
        for size in {max(1, k - 1), k, k + 1}:
            if size > len(spans):
                continue
            for i, j in _token_windows(spans, size):
                window = ' '.join(s['token'] for s in spans[i:j])
                # Fold numbers HERE, at comparison time. The INDEX stays unfolded --
                # it must keep one token per spoken word to preserve the
                # word -> timestamp mapping -- so 'twenty five percent off' in the
                # transcript becomes '25 percent off' only for this comparison.
                window_norm = normalize_text(window)
                if digits_missing(variant, window_norm):
                    continue
                score = robust_ratio(variant, window_norm)
                if score < min_score:
                    continue
                start = spans[i]['start']
                end = spans[j - 1]['end']
                sig = (round(start or 0, 2), round(end or 0, 2))
                if sig in seen:
                    continue
                seen.add(sig)
                matches.append({
                    'phrase': phrase, 'matched_variant': variant,
                    'matched_text': window, 'score': int(score),
                    'start': start, 'end': end,
                    'word_index_start': spans[i]['word_index'],
                    'word_index_end': spans[j - 1]['word_index'],
                })
    matches.sort(key=lambda m: (-m['score'], m['start'] if m['start'] is not None else 0))
    return matches

def despace(text: str) -> str:
    return re.sub(r'\s+', '', text)

# Curated phrases that pure frequency-based segmentation gets WRONG, and which
# are exactly the strings a content brief asks about -- so precision here matters
# more than anywhere else in the pipeline.
#   'linkinbio'  -> wordninja prefers ['linkin', 'bio'] because "Linkin" is a real
#                   token with non-trivial frequency. The gazetteer forces
#                   'link in bio'.
#   'SHOPNOW'    -> only 7 characters, below the wordninja length gate. The
#                   gazetteer catches it regardless of length.
# Matched case-insensitively against the whole letter-run, then sliced out of the
# ORIGINAL string so casing survives.
OCR_PHRASE_GAZETTEER = (
    'link in bio', 'link below', 'in bio', 'shop now', 'buy now', 'get yours',
    'out now', 'new drop', 'swipe up', 'tap in', 'available now', 'on sale',
    'sold out', 'limited edition', 'use code', 'free shipping', 'add to cart',
    'check out', 'learn more', 'save now', 'order now', 'try it', 'shop the link',
    'before and after', 'for sensitive skin', 'sensitive skin', 'skin barrier',
    'hair growth', 'hair shine', 'clinically proven', 'dermatologist tested',
)

_GAZ = {despace(p.lower()): p for p in OCR_PHRASE_GAZETTEER}

_GAZ_MIN_LEN = min((len(k) for k in _GAZ), default=99)

# ---------------------------------------------------------------------------
# SPACE RESTORATION -- the source-level fix for PP-OCR run-together output.
#
# PP-OCR's default recogniser is Chinese-trained. It reads Latin characters
# correctly but omits the spaces, giving 'everyonetalksabouthair'.
# We repair it here, at ingest, so EVERY downstream consumer -- dedupe, the
# caption cross-check, phrase search, and the Phase 7 report -- sees clean text.
#
# Method: dictionary word segmentation (wordninja: Zipf-frequency dynamic
# programming over an English word list). Character-preserving, so we slice the
# ORIGINAL string by the returned piece lengths and keep the source casing.
# ---------------------------------------------------------------------------
try:
    import wordninja as _wordninja
except ImportError:
    _wordninja = None
    print('WARNING: wordninja not installed -- OCR space restoration disabled.')
    print('         Run: pip install wordninja')

def _slice_by_pieces(run: str, pieces: list) -> list:
    """Slice the ORIGINAL run by the piece lengths, so source casing survives."""
    out, i = [], 0
    for p in pieces:
        out.append(run[i:i + len(p)])
        i += len(p)
    return out

def _split_alpha_run(run: str, cfg) -> list:
    """Segment ONE run of letters. Returns [run] unchanged if the split looks wrong."""
    # ---- 1. gazetteer: exact, high-precision, length-independent -------------
    hit = _GAZ.get(run.lower())
    if hit:
        return _slice_by_pieces(run, hit.split())

    # ---- 2. dictionary segmentation ------------------------------------------
    if _wordninja is None or len(run) < cfg.restore_min_length:
        return [run]
    try:
        pieces = _wordninja.split(run)
    except Exception:
        return [run]
    if not pieces or len(pieces) < 2:
        return [run]
    # wordninja must not have dropped or added characters, or slicing is invalid
    if sum(len(p) for p in pieces) != len(run):
        return [run]
    # --- reject over-fragmentation ------------------------------------------
    # A garbled logo like 'bIUKbe' shatters into 1-2 char bits. A real phrase
    # does not. This guard is what stops brand names being mangled.
    short = sum(1 for p in pieces if len(p) <= 2)
    if short / len(pieces) > cfg.restore_max_short_ratio:
        return [run]
    if (len(run) / len(pieces)) < cfg.restore_min_pieces_len:
        return [run]
    return _slice_by_pieces(run, pieces)

def restore_spaces(text: str, cfg) -> tuple:
    """
    Returns (repaired_text, changed).
    Only long, space-free, mostly-alphabetic runs are touched; punctuation,
    digits and separators are preserved exactly where they were.
    """
    if not getattr(cfg, 'restore_spaces', False) or not text:
        return text, False
    if _wordninja is None and not _GAZ:
        return text, False

    # The token gate must not be stricter than the shortest gazetteer entry,
    # or short CTAs like 'SHOPNOW' (7 chars) never reach _split_alpha_run.
    gate = min(cfg.restore_min_length, _GAZ_MIN_LEN)

    changed = False
    out_tokens = []
    for token in text.split():
        alpha = sum(c.isalpha() for c in token)
        if len(token) < gate or alpha < len(token) * 0.6:
            out_tokens.append(token)
            continue
        # split into alternating [letters][non-letters] parts, segment only letters
        rebuilt = []
        for part in re.split(r'([^A-Za-z]+)', token):
            if part and part[0].isalpha() and len(part) >= min(gate, len(part)):
                pieces = _split_alpha_run(part, cfg)
                if len(pieces) > 1:
                    changed = True
                rebuilt.append(' '.join(pieces))
            else:
                rebuilt.append(part)
        out_tokens.append(''.join(rebuilt))
    return ' '.join(' '.join(out_tokens).split()), changed

def robust_ratio(a: str, b: str) -> int:
    """
    fuzz.ratio that is immune to MISSING SPACES.

    PP-OCR's default recogniser is Chinese-trained, and on Latin text it
    frequently returns run-together output:
        'everyonetalksabouthair'   for   'everyone talks about hair'
    Comparing the de-spaced forms as well means that costs us nothing.
    Without this, the §9 caption cross-check silently stops firing.
    """
    return max(int(fuzz.ratio(a, b)), int(fuzz.ratio(despace(a), despace(b))))

def robust_partial_ratio(a: str, b: str) -> int:
    """Substring-tolerant version of the above (a inside b)."""
    return max(int(fuzz.partial_ratio(a, b)),
               int(fuzz.partial_ratio(despace(a), despace(b))))

def contains_ratio(needle: str, haystack: str) -> int:
    """
    'Does `haystack` contain `needle`?' -- and it is NOT the same as
    partial_ratio(needle, haystack).

    rapidfuzz's partial_ratio compares the SHORTER string against windows of the
    longer one, whichever way round they are given. So:

        partial_ratio('shop now', 'shop')  ==  100

    An OCR line reading only 'shop' would score a perfect match for the
    requirement 'shop now'. That is a FALSE POSITIVE PASS -- the most damaging
    error class in the whole system (plan.md Phase 8 metrics).

    Guard: a haystack materially shorter than the needle cannot contain it, so
    fall back to a full-string ratio, which penalises the missing text.
    """
    n, h = despace(needle), despace(haystack)
    if len(h) < len(n) * 0.8:
        return robust_ratio(needle, haystack)
    return robust_partial_ratio(needle, haystack)

# ---------------------------------------------------------------------------
# CHANGE-AWARE helpers -- used by dedupe (section 8) and the caption check (9)
# ---------------------------------------------------------------------------
_DIGIT_RUN = re.compile(r'\d+')

def digits_of(text: str) -> tuple:
    """The number runs in a string, in order: 'code save20 by 5pm' -> ('20', '5')."""
    return tuple(_DIGIT_RUN.findall(text or ''))

def digits_conflict(a: str, b: str) -> bool:
    """
    True when BOTH strings carry numbers and those numbers differ.

    Numbers are where the meaning lives in ad copy -- prices, discount codes,
    percentages, step counts. Measured: 'code save20' vs 'code save30' scores
    90.9 and '20% off' vs '30% off' scores 85.7, both above the merge threshold.
    Without this guard the change is silently erased.

    If only ONE side has digits it is not a conflict -- that is a caption still
    being revealed ('code save' -> 'code save20'), handled by is_growing_text.
    """
    da, db = digits_of(a), digits_of(b)
    return bool(da) and bool(db) and da != db

def digits_missing(required: str, candidate: str) -> bool:
    """
    Does `candidate` fail to contain every number `required` asks for?

    THIS IS THE SEARCH GUARD, and it is deliberately NOT digits_conflict().
    Different question, different rule:

      digits_conflict  "are these the same element?"   -> sets must be EQUAL
                       (dedupe: 'save20' and 'save30' are two different captions)
      digits_missing   "does this satisfy the ask?"    -> ask must be a SUBSET
                       ('20% off' IS satisfied by '20% off use code save30')

    It exists because character similarity cannot tell numbers apart. Measured:
    '20 percent off' vs '25 percent off' scores 91.7, well above the 85 threshold
    -- one digit in fourteen characters barely moves the score. Without this
    guard a brief requiring 20% off PASSES on a video showing 25% off, which is a
    false-positive PASS on a numeric claim: the most damaging error class there is.
    """
    need = set(digits_of(required))
    return bool(need) and not need.issubset(set(digits_of(candidate)))

def is_growing_text(shorter: str, longer: str) -> bool:
    """
    Word-by-word / karaoke captions build up in place:
        'everyone' -> 'everyone talks' -> 'everyone talks about'
    Each step is a PREFIX of the next. By ratio they look like different strings;
    they are one element being revealed.
    """
    s, l = despace(shorter), despace(longer)
    return 0 < len(s) < len(l) and l.startswith(s)

STOPWORDS = frozenset((
    'a an the and or but of to in on at for with by from as is are was were be '
    'been it its this that these those i you he she we they my your our their '
    'me him her us them so just not no do does did have has had will would can '
    'could should what which who how when where why all any some more most very '
    'about into than then there here also like').split())

def content_tokens(text: str) -> list:
    """Words that carry meaning: stopwords dropped, anything with a digit kept."""
    return [t for t in normalize_text(text).split()
            if any(c.isdigit() for c in t) or (len(t) >= 3 and t not in STOPWORDS)]

def _tokens_match(a: str, b: str, min_ratio: int) -> bool:
    """
    Exact, fuzzy, or a crude stem match.

    The stem rule is NOT optional. Measured: ratio('everyone', 'everybody') is
    70.6 -- a plain fuzzy match at 80 misses it. A shared prefix of 5+ characters
    covering 60%+ of the shorter word catches it, along with hydrating/hydration
    and perfect/perfection.
    """
    if a == b or fuzz.ratio(a, b) >= min_ratio:
        return True
    p = 0
    for x, y in zip(a, b):
        if x != y:
            break
        p += 1
    return p >= 5 and p >= 0.6 * min(len(a), len(b))

def fuzzy_token_recall(ocr_text: str, speech_text: str, min_ratio: int = 80) -> dict:
    """
    What fraction of the on-screen text's CONTENT words were spoken?

    Card:   'everyone talks about hair growth, but what about hair shine?'
    Speech: 'everybody talks about hair growth but nobody talks about hair shine'

    Every character-level measure lands at 84.5-84.8 on this pair and misses the
    85 threshold, because 'what about' vs 'nobody talks about' is a genuine edit.
    But all five content words -- everyone, talks, hair, growth, shine -- were
    spoken. Recall ignores the connective wording and asks whether the substance
    was said, which is exactly what a paraphrasing title card is. Measured: 100.
    Garbled mirror text scores 0; an unrelated graphic scores 0.
    """
    ocr_c = list(dict.fromkeys(content_tokens(ocr_text)))       # unique, ordered
    speech_c = set(content_tokens(speech_text))
    if not ocr_c or not speech_c:
        return {'recall': 0, 'n_content': len(ocr_c), 'matched': []}
    matched = [t for t in ocr_c if any(_tokens_match(t, s, min_ratio) for s in speech_c)]
    return {'recall': int(round(100 * len(matched) / len(ocr_c))),
            'n_content': len(ocr_c), 'matched': matched}

def caption_similarity(ocr_norm: str, speech_norm: str,
                       token_match_min: int = 80, recall_min_content: int = 3) -> dict:
    """
    'Is this on-screen text saying the same thing as the nearby speech?'

    Burned-in text comes in two flavours needing different measures:
      1. verbatim auto-captions   -> character measures win (contains_ratio)
      2. title cards that         -> content-word recall wins; the wording differs
         PARAPHRASE the voiceover    but the substance is the same

    Four components, best one wins, all returned so any flag can be explained.
    Recall only counts with 3+ content words: on a 2-word string, "both words were
    said somewhere nearby" is too easy a bar.
    """
    contains = contains_ratio(ocr_norm, speech_norm)
    token_set = max(int(fuzz.token_set_ratio(ocr_norm, speech_norm)),
                    int(fuzz.token_set_ratio(despace(ocr_norm), despace(speech_norm))))
    token_sort = int(fuzz.token_sort_ratio(ocr_norm, speech_norm))
    tr = fuzzy_token_recall(ocr_norm, speech_norm, token_match_min)
    recall = tr['recall'] if tr['n_content'] >= recall_min_content else 0
    scores = {'contains': contains, 'token_set': token_set,
              'token_sort': token_sort, 'token_recall': recall}
    method = max(scores, key=scores.get)
    return {'score': scores[method], 'method': method, **scores,
            'recall_matched': tr['matched'], 'n_content': tr['n_content']}

def spacing_health(texts: list) -> dict:
    """
    How often is the recogniser dropping spaces? Long strings with no space at
    all are the signature. Reported in §12.4 so the condition is measured, not
    guessed at.
    """
    long_texts = [t for t in texts if len(t) > 12]
    runtogether = [t for t in long_texts if ' ' not in t]
    return {'long_texts': len(long_texts), 'runtogether': len(runtogether),
            'ratio': round(len(runtogether) / max(1, len(long_texts)), 3),
            'examples': runtogether[:5]}

def bbox_iou(a: list, b: list) -> float:
    """IoU on [x1, y1, x2, y2]."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 535: print('text.py loaded')
