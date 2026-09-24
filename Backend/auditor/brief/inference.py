"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 92.
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
def _has(patterns, text: str):
    """Return the first pattern that matches, or None. Case-insensitive."""
    for p in patterns:
        if re.search(p, text, re.I):
            return p
    return None

# --- speech: the words must leave a mouth -----------------------------------
# 'speak' is deliberately ABSENT: product.md's own example brief says
# "Speak to teens/tweens", which is audience targeting, not a speech requirement.
SPEECH_CUES = (
    r'\bsays?\b', r'\bsaid\b', r'\bsaying\b',
    r'\bmentions?\b', r'\bmentioned\b', r'\bmentioning\b',
    r'\btells?\b', r'\bnarrat(?:e|es|ing|ion)\b',
    r'\bverbal(?:ly)?\b', r'\baloud\b', r'\bout loud\b',
    r'\bvoice ?over\b', r'\bspoken\b', r'\bspeaks\b',
    r'\btalk(?:s|ing)? about\b', r'\bcalls? out\b', r'\bshout ?outs?\b',
    r'\bname[- ]drops?\b', r'\bstates? (?:the|that|your|what)\b',
    r'\bin the (?:voice ?over|vo)\b', r'\bexplains?\b',
)

# --- visual: the VLM has to have seen it ------------------------------------
# bare 'use' is ABSENT: "use approved wording" is a policy rule about language.
# bare 'see' is ABSENT: "see below".
VISUAL_CUES = (
    r'\bshows?\b', r'\bshowing\b', r'\bshown\b',
    r'\bdisplays?\b', r'\bdisplayed\b', r'\bvisible\b', r'\bvisibility\b',
    r'\breveals?\b', r'\bfeatur(?:e|es|ing) the\b',
    r'\bdemonstrat(?:e|es|ing|ion)\b', r'\bdemos?\b',
    r'\bhold(?:s|ing)?\b', r'\bappl(?:y|ies|ying|ication)\b',
    r'\bwear(?:s|ing)?\b', r'\bunbox(?:ing)?\b', r'\bswatch(?:es|ing)?\b',
    r'\bon[- ]camera\b', r'\bb[- ]roll\b', r'\bclose[- ]?ups?\b',
    r'\bbefore[ /and]+after\b', r'\bpackaging\b',
    r'\busing the\b', r'\bhow (?:to|it(?:\'s| is)?) use',
    r'\bseen\b', r'\bfootage\b', r'\bon screen the\b',
)

# --- on-screen text: specifically the OCR channel ---------------------------
TEXT_CUES = (
    r'\bon[- ]?screen\b', r'\bcaptions?\b', r'\bcaptioned\b',
    r'\bsubtitles?\b', r'\btext overlays?\b', r'\boverlays?\b',
    r'\bstickers?\b', r'\bwritten\b', r'\bwrite\b', r'\btyped\b',
    r'\bin text\b', r'\bbanners?\b', r'\blower third\b', r'\btitle cards?\b',
    r'\btext (?:on|appears)\b',
)

# --- payload that a viewer READS rather than recognises ---------------------
# This is the §37 rule. "Show 20% OFF" is satisfied by on-screen text alone,
# because a discount is a string, not an object. "Show the product" is not.
# 'off' is ABSENT as a standalone marker: "show off the product".
TEXT_PAYLOAD_CUES = (
    r'\d+\s*%', r'[$£€]\s*\d', r'\bpromo\b', r'\bcoupons?\b',
    r'\bdiscount\b', r'\bcodes?\b', r'\blink in bio\b', r'\blinkinbio\b',
    r'@\w', r'https?://', r'\bwww\.', r'\.com\b', r'\bhashtags?\b', r'#\w',
    r'\bprices?\b', r'\bsale\b', r'\burls?\b', r'\bhandles?\b',
    r'\bspelled\b', r'"[^"]{2,}"', r'“[^”]{2,}”',
)

# --- audience: catches "speak to", which is why 'speak' is not a speech cue --
AUDIENCE_CUES = (
    r'\bspeaks? to\b(?!\s+(?:camera|the camera))', r'\btalks? to\b(?!\s+(?:camera|the camera))',
    r'\btarget(?:s|ing|ed)?\b', r'\baimed at\b', r'\bauidence\b', r'\baudiences?\b',
    r'\bdemographics?\b', r'\bteens?\b', r'\btweens?\b', r'\bgen[- ]?z\b',
    r'\bmillennials?\b', r'\bresonate\b', r'\btone\b', r'\bfor (?:young|older|new) \w+',
)

def infer_evidence_mode(text: str) -> dict:
    """
    Derive evidence_mode from sentence structure alone. No model involved.

    Returns {'mode', 'reason', 'cues', 'confident'}. mode is None when nothing
    fires -- ambiguity is reported, never guessed, because a wrong evidence_mode
    silently inverts a PASS into a FAIL (product.md §37).
    """
    t = text or ''
    speech = _has(SPEECH_CUES, t)
    visual = _has(VISUAL_CUES, t)
    textual = _has(TEXT_CUES, t)
    payload = _has(TEXT_PAYLOAD_CUES, t)
    cues = {'speech': speech, 'visual': visual, 'text': textual, 'payload': payload}

    def out(mode, reason, confident=True):
        return {'mode': mode, 'reason': reason, 'cues': cues, 'confident': confident}

    if speech and visual:
        return out('visual_and_speech', f'both spoken ({speech}) and seen ({visual})')
    if speech and textual:
        # The enum has no 'ocr_and_speech'. speech_or_text is the closest honest
        # answer, and the approximation is flagged rather than hidden.
        return out('speech_or_text',
                   f'spoken ({speech}) and on-screen ({textual}); no combined mode exists',
                   confident=False)
    if textual:
        return out('ocr_only', f'on-screen text cue ({textual})')
    if speech:
        return out('speech_only', f'speech cue ({speech})')
    if visual and payload:
        # product.md §37 -- the whole reason this function exists.
        return out('speech_or_text',
                   f'visual cue ({visual}) but the payload is readable text ({payload}): '
                   f'on-screen text satisfies it')
    if visual:
        return out('visual_only', f'visual cue ({visual}), no readable payload')
    return out(None, 'no modality cue found', confident=False)

# --- negation -------------------------------------------------------------
# "no longer than 30 seconds" is a TIMING requirement that happens to contain a
# negation word. Excluded explicitly rather than by hoping 'no' never appears.
NEGATION_CUES = (
    r"\bdo not\b", r"\bdon'?t\b", r"\bnever\b", r"\bmust not\b", r"\bmustn'?t\b",
    r"\bshould not\b", r"\bshouldn'?t\b", r"\bavoid\b", r"\brefrain from\b",
    r"\bcannot\b", r"\bcan'?t\b", r"\bprohibited\b", r"\bforbidden\b",
    r"\bnot allowed\b", r"\bno claims?\b", r"\bwithout (?:making|any|a )\b",
    r"\bnothing that\b",
)

NEGATION_EXCEPTIONS = (r'\bno (?:longer|more|less|shorter|fewer) than\b',)

TYPE_CUES = (
    # order matters: a negative rule is structurally a policy no matter what
    # channel it talks about, so polarity is tested before modality.
    ('policy',        NEGATION_CUES + (r'\bcomplian\w+\b', r'\bmedical claims?\b',
                                       r'\bapproved wording\b', r'\bdisclaimer\b',
                                       r'\bregulat\w+\b', r'\bclaims?\b')),
    ('hook',          (r'\bhooks?\b', r'\bopen(?:s|ing)? with\b', r'\bstarts? with\b',
                       r'\bfirst (?:frame|second|1|2|3|three)\b', r'\bgrab\w* attention\b',
                       r'\bscroll[- ]stopp\w+\b', r'\bopening\b')),
    ('cta',           (r'\bcta\b', r'\bcalls? to action\b', r'\blink in bio\b',
                       r'\bswipe up\b', r'\bshop now\b', r'\bfollow (?:us|me|for)\b',
                       r'\bcomment\b', r'\bsubscribes?\b', r'\bend(?:s|ing)? with\b',
                       r'\buse code\b', r'\border now\b', r'\bcheck ?out\b')),
    ('demonstration', (r'\bdemonstrat\w+\b', r'\bdemos?\b', r'\bhow (?:to|it) use',
                       r'\btutorial\b', r'\bstep[- ]by[- ]step\b',
                       r'\bappl(?:y|ies|ying|ication)\b', r'\busing the\b',
                       r'\bin (?:action|use)\b')),
    ('audience',      AUDIENCE_CUES),
    ('timing',        (r'\bseconds? long\b', r'\bduration\b', r'\bpacing\b',
                       r'\bkeep it under\b', r'\bno longer than\b', r'\bat least \d+ sec',
                       r'\blength\b', r'\brun ?time\b')),
    ('brand',         (r'\bbrand\b', r'\blogos?\b', r'\btag (?:us|the|@)\b',
                       r'\bbrand name\b', r'\bhandles?\b')),
)

VAGUE_CUES = (
    r'\bfeels?\b', r'\bfeeling\b', r'\bvibes?\b', r'\bpremium\b', r'\baesthetic\b',
    r'\bauthentic\b', r'\bhigh[- ]quality\b', r'\bengaging\b', r'\brelatable\b',
    r'\bon[- ]brand\b', r'\bgood energy\b', r'\btrendy\b', r'\bcool\b',
    r'\bprofessional\b', r'\bnatural(?:ly)?\b', r'\bfun\b', r'\bvibey\b',
)

def infer_polarity(text: str) -> tuple:
    """(polarity, cue). 'no longer than 30s' is timing, not a prohibition."""
    t = text or ''
    if _has(NEGATION_EXCEPTIONS, t) and not _has(
            tuple(c for c in NEGATION_CUES if c not in (r'\bno claims?\b',)), t):
        return 'required', None
    cue = _has(NEGATION_CUES, t)
    return ('forbidden', cue) if cue else ('required', None)

def infer_requirement_type(text: str, mode: Optional[str] = None) -> tuple:
    """(type, cue). Falls back to the modality when no structural cue fires."""
    t = text or ''
    for type_, pats in TYPE_CUES:
        cue = _has(pats, t)
        if cue:
            return type_, cue
    if mode == 'speech_only':
        return 'speech', 'modality'
    if mode == 'visual_only':
        return 'visual', 'modality'
    if mode in ('ocr_only', 'speech_or_text'):
        return 'speech_or_text', 'modality'
    if mode == 'visual_and_speech':
        return 'demonstration', 'modality'
    return 'other', None

def infer_priority(text: str, type_: str, polarity: str) -> tuple:
    """(priority, cue). Compliance rules are critical unless the brief softens them."""
    t = text or ''
    if _has((r'\bcritical\b', r'\bmandatory\b', r'\bmust\b', r'\balways\b',
             r'\brequired\b', r'\bessential\b', r'\bnon[- ]negotiable\b'), t):
        return ('critical' if type_ == 'policy' or polarity == 'forbidden' else 'high',
                'imperative language')
    if _has((r'\bif possible\b', r'\bnice to have\b', r'\bideally\b', r'\boptional\b',
             r'\btry to\b', r'\bwhere possible\b', r'\bbonus\b'), t):
        return 'low', 'softened language'
    if _has((r'\bshould\b', r'\bprefer\w*\b', r'\bencourag\w+\b'), t):
        return 'medium', 'preference language'
    if type_ == 'policy' or polarity == 'forbidden':
        return 'critical', 'compliance rule'
    if type_ in ('hook', 'cta', 'visual', 'demonstration'):
        return 'high', 'core brief element'
    return 'medium', 'default'

def is_machine_checkable(text: str, type_: str) -> tuple:
    """
    (checkable, reason).

    "Make it feel premium" has no observable. Emitting it with machine_checkable
    False and reporting it separately is the honest option; plan.md §4 is explicit
    that pretending to evaluate it is worse than admitting we cannot.
    """
    t = text or ''
    vague = _has(VAGUE_CUES, t)
    if not vague:
        return True, None
    concrete = (_has(TEXT_PAYLOAD_CUES, t)
                or _has((r'\d', r'"[^"]+"', r'“[^”]+”'), t))
    if concrete:
        return True, None
    if type_ in ('visual', 'demonstration', 'speech', 'speech_or_text', 'cta', 'policy'):
        # a concrete channel with a vague adjective is still partly checkable:
        # "show the product naturally" -- we can check the product was shown.
        return True, f'vague qualifier ({vague}) on a concrete requirement'
    return False, f'vague, no observable target ({vague})'


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 231: print('§40 inference loaded.')
#   line 232: for _t in ['Show 20% OFF.', 'Say 20% OFF.', 'Show the product in the first 5
