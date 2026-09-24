"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 94.
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
_SMALL_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
                'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
                'twelve': 12, 'fifteen': 15, 'twenty': 20, 'thirty': 30,
                'forty': 40, 'fifty': 50, 'sixty': 60, 'half': 0.5}

def _num(tok) -> Optional[float]:
    """Digits or a number word. Reuses Phase 2's NUMBER_WORDS when its shape allows."""
    t = str(tok or '').strip().lower()
    if re.fullmatch(r'\d+(?:\.\d+)?', t):
        return float(t)
    try:
        v = NUMBER_WORDS.get(t)                     # Phase 2, if present and int-valued
        if isinstance(v, (int, float)):
            return float(v)
    except Exception:
        pass
    return _SMALL_WORDS.get(t)

_NUMWORD = r'\d+(?:\.\d+)?|' + '|'.join(_SMALL_WORDS)

def find_campaign(text: str) -> Optional[str]:
    m = re.search(r'^\s*(?:campaign|brand|product)\s*[:\-]\s*(.+)$', text or '',
                  re.I | re.M)
    return m.group(1).strip()[:80] if m else None

def _looks_like_heading(line: str) -> bool:
    """'Requirements:' and 'Whip Dream' are context, not asks."""
    s = line.strip()
    if not s:
        return True
    if re.match(r'^\s*(?:campaign|brand|product|brief|requirements?|notes?|deliverables?)\s*:',
                s, re.I):
        return True
    # a short line with no action cue and no verb-ish ending is a title
    return len(s.split()) <= 4 and not _has(_ACTION_CUES, s) and not s.endswith('.')

def _split_compound(sentence: str) -> list:
    """
    Split on 'and'/'then'/';' only when the right side is its own ask.

    "show the product and say the name"     -> 2   (say is a verb)
    "mention hydration and barrier support" -> 1   (no verb after 'and')
    """
    parts, buf = [], sentence
    out = []
    for chunk in re.split(r'\s*;\s*', buf):
        pieces = re.split(r'\s*,?\s+(?:and then|and|then)\s+', chunk, flags=re.I)
        if len(pieces) == 1:
            out.append(chunk)
            continue
        merged = [pieces[0]]
        for p in pieces[1:]:
            if _has(_ACTION_CUES, p):
                merged.append(p)                    # its own ask
            else:
                merged[-1] = merged[-1] + ' and ' + p   # a second target, same ask
        out.extend(merged)
    for p in out:
        p = p.strip(' .,;')
        if p:
            parts.append(p)
    return parts

def brief_units(text: str) -> list:
    """
    Brief document -> the units a compiler should actually look at.

    This is the structure-aware entry point. Each unit carries which section it
    came from and, when that section offered choices, the group it belongs to:

        {'text', 'section', 'kind', 'group', 'group_mode', 'group_label', 'type_hint'}

    context sections produce nothing -- "Purpose: this guide helps creators..."
    is background and is not something a video can satisfy. claims sections
    produce nothing here either; §40b turns them into an allowlist instead.
    """
    out = []
    for sec in parse_brief_sections(text):
        # context produces nothing -- "Purpose: this guide helps creators..."
        # is background, and no video can satisfy it.
        #
        # claims sections DO produce requirements now. They also still produce
        # the allowlist, via extract_approved_claims() on its own pass; the two
        # readings are independent and both are wanted. A brief's talking
        # points are the substance it is asking the creator to communicate, and
        # a score that ignores them says 100 for a video that never mentioned
        # the product's benefits.
        if sec.kind == 'context':
            continue
        # Drop describing lines HERE, while the bullets are still separate.
        # section_items() joins a numbered concept's bullets with spaces, so a
        # sentence splitter downstream can no longer tell "Grow your hair 101"
        # from the commentary that followed it on the next bullet.
        sec = replace(
            sec, lines=[l for l in sec.lines if not is_descriptive_example(l)])
        items = section_items(sec)
        alt = sec.kind == 'alternatives' and len(items) > 1
        for it in items:
            pieces = ([strip_descriptive_sentences(it['text'])] if alt else
                      [p for s in _SENT_SPLIT.split(it['text'])
                       for p in _split_compound(s.strip()) if p])
            for p in pieces:
                p = p.strip()
                if len(p) < 3 or _looks_like_heading(p):
                    continue
                # "This creator begins her video with..." is the brief showing
                # what worked, not asking for it. Emitting it as a requirement
                # fails every video that did not copy the example.
                if is_descriptive_example(p):
                    continue
                out.append({
                    'text': p if p.endswith(('.', '!', '?', '"', '”')) else p + '.',
                    'section': sec.heading, 'kind': sec.kind,
                    'group': sec.slug() if alt else None,
                    'group_mode': 'one_of' if alt else 'all_of',
                    'group_label': sec.heading if alt else '',
                    'type_hint': sec.type_hint,
                })
    seen, dedup = set(), []
    for u in out:
        k = re.sub(r'[^a-z0-9 ]', '', u['text'].lower()).strip()
        if k and k not in seen:
            seen.add(k)
            dedup.append(u)
    return dedup

def split_brief(text: str) -> list:
    """Brief -> atomic requirement strings. The flat view of brief_units()."""
    return [u['text'] for u in brief_units(text)]

def extract_temporal(text: str, type_: str = 'other',
                     cfg: BriefConfig = None) -> dict:
    """
    Pull temporal constraints out of one requirement.

    End-relative windows come out SYMBOLIC. That is the entire point: an absolute
    number here is correct for exactly one video length and silently wrong for
    every other one.
    """
    cfg = cfg or P4.brief
    t = text or ''
    out = {'deadline_seconds': None, 'window_start_expr': None,
           'window_end_expr': None, 'flags': []}

    # --- "within the first N seconds" / "in the first N seconds" -------------
    m = re.search(rf'\b(?:with)?in\s+the\s+first\s+({_NUMWORD})\s*(?:s\b|sec|second)', t, re.I) \
        or re.search(rf'\bfirst\s+({_NUMWORD})\s*(?:s\b|sec|second)', t, re.I) \
        or re.search(rf'\bwithin\s+({_NUMWORD})\s*(?:s\b|sec|second)', t, re.I) \
        or re.search(rf'\bby\s+(?:the\s+)?({_NUMWORD})\s*(?:s\b|sec|second)', t, re.I)
    if m:
        v = _num(m.group(1))
        if v is not None:
            if 0 < v <= cfg.max_plausible_deadline:
                out['deadline_seconds'] = float(v)
            else:
                out['flags'].append(f'DEADLINE_IMPLAUSIBLE:{v}')

    # --- "in the last N seconds" / "final N seconds" / "end with" ------------
    m = re.search(rf'\b(?:last|final|closing)\s+({_NUMWORD})\s*(?:s\b|sec|second)', t, re.I)
    if m:
        v = _num(m.group(1)) or cfg.default_cta_window
        out['window_start_expr'] = f'duration - {v:g}'
        out['window_end_expr'] = 'duration'
    elif _has((r'\bend(?:s|ing)? with\b', r'\bat the end\b', r'\bfinish(?:es|ing)? with\b',
               r'\bclose(?:s|ing)? with\b', r'\blast\b.*\bcta\b'), t) or type_ == 'cta':
        out['window_start_expr'] = f'duration - {cfg.default_cta_window:g}'
        out['window_end_expr'] = 'duration'

    # --- opening / hook window ----------------------------------------------
    if out['window_start_expr'] is None:
        m = re.search(rf'\b(?:opening|start|beginning)\s+({_NUMWORD})\s*(?:s\b|sec|second)',
                      t, re.I)
        if m:
            v = _num(m.group(1)) or cfg.default_hook_window
            out['window_start_expr'], out['window_end_expr'] = '0', f'{v:g}'
        elif type_ == 'hook' or _has((r'\bopen(?:s|ing)? with\b', r'\bat the start\b',
                                      r'\bstarts? with\b', r'\bfirst frame\b'), t):
            out['window_start_expr'] = '0'
            out['window_end_expr'] = f'{cfg.default_hook_window:g}'

    # --- "between N and M seconds" ------------------------------------------
    m = re.search(rf'\bbetween\s+({_NUMWORD})\s*(?:s|sec|seconds?)?\s+and\s+({_NUMWORD})\s*'
                  r'(?:s\b|sec|second)', t, re.I)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        if a is not None and b is not None:
            lo, hi = sorted((a, b))
            out['window_start_expr'], out['window_end_expr'] = f'{lo:g}', f'{hi:g}'
    return out

# A deliberately small gazetteer. The LLM produces far better hints; this is the
# floor that keeps the rule backend usable, not an attempt to compete with it.
BRIEF_SYNONYMS = {
    'hydration':   ['hydrat', 'moistur', 'dewy', 'quench', 'dry skin', 'skin barrier'],
    'barrier':     ['barrier', 'skin barrier', 'protect', 'strengthen'],
    'moisturizer': ['moisturizer', 'moisturiser', 'cream', 'lotion', 'balm'],
    'cleanser':    ['cleanser', 'face wash', 'cleanse'],
    'serum':       ['serum', 'drops', 'treatment'],
    'cta':         ['link in bio', 'shop now', 'swipe up', 'comment', 'follow',
                    'use code', 'order now', 'check out', 'grab yours', 'get yours'],
    'discount':    ['% off', 'percent off', 'promo', 'code', 'sale', 'deal', 'save'],
    'routine':     ['routine', 'regimen', 'steps', 'step one', 'step 1'],
    'ingredient':  ['ingredient', 'formula', 'contains', 'made with'],
    'sensitive':   ['sensitive', 'gentle', 'mild', 'irritat'],
    'shine':       ['shine', 'glossy', 'gloss', 'glow'],
    'volume':      ['volume', 'volumising', 'volumizing', 'thick', 'fuller'],
}

def rule_match_hints(text: str, max_hints: int = 12) -> list:
    """Content words plus gazetteer expansions. Deterministic and order-stable."""
    hints, seen = [], set()

    def add(h):
        h = (h or '').strip().lower()
        if h and len(h) > 2 and h not in seen:
            seen.add(h)
            hints.append(h)

    try:
        toks = content_tokens(text or '')          # Phase 2: stopwords dropped
    except Exception:
        toks = re.findall(r'[a-z0-9%$]+', (text or '').lower())
    verbs = {'show', 'shows', 'say', 'says', 'mention', 'mentions', 'demonstrate',
             'display', 'include', 'make', 'end', 'open', 'start', 'use', 'add', 'keep'}
    for tk in toks:
        if tk not in verbs:
            add(tk)
    for key, syns in BRIEF_SYNONYMS.items():
        if re.search(rf'\b{key[:6]}', text or '', re.I):
            for s in syns:
                add(s)
    m = re.findall(r'"([^"]{2,40})"|“([^”]{2,40})”', text or '')
    for a, b in m:
        add(a or b)
    return hints[:max_hints]

CLAIM_CLASS_CUES = {
    'medical':             (r'\bmedical\b', r'\bcures?\b', r'\btreats?\b', r'\bheals?\b',
                            r'\bdiagnos\w+\b', r'\beczema\b', r'\bpsoriasis\b',
                            r'\bdermatologist\b', r'\bclinical\w*\b', r'\bdisease\b'),
    'cure':                (r'\bcures?\b', r'\bfixes\b', r'\beliminates?\b', r'\bpermanent\w*\b'),
    'guarantee':           (r'\bguarantee\w*\b', r'\bpromis\w+\b', r'\b100\s*%\b', r'\bensures?\b'),
    'unsupported_outcome': (r'\binstant\w*\b', r'\bovernight\b', r'\bin \d+ days?\b',
                            r'\bresults? in\b', r'\bmiracle\b'),
    'prohibited_wording':  (r'\bapproved wording\b', r'\bbanned\b', r'\bprohibited\b',
                            r'\brestricted (?:words?|terms?)\b'),
    'competitor':          (r'\bcompetitors?\b', r'\bbetter than\b', r'\bversus\b', r'\bvs\.?\b',
                            r'\bother brands?\b'),
    'pricing':             (r'\bcheapest\b', r'\blowest price\b', r'\bprice match\b'),
}

def infer_claim_classes(text: str) -> list:
    """product.md §38: name the detectable classes rather than trying to prove a negative."""
    found = [k for k, pats in CLAIM_CLASS_CUES.items() if _has(pats, text or '')]
    return found or ['other']


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 276: print('§40c segmentation loaded.')
#   line 277: _demo = split_brief('Show the product and say the name.\nMention hydration a
#   line 278: for _u in _demo:
#   line 280: _t = extract_temporal('Show the moisturizer within the first 5 seconds.', 'v
#   line 281: print(f"  temporal -> deadline {_t['deadline_seconds']}")
#   line 282: _t = extract_temporal('End with a clear CTA.', 'cta')
#   line 283: print(f"  temporal -> window {_t['window_start_expr']} .. {_t['window_end_ex
