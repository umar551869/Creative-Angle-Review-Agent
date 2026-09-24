"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 93.
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
_MD_HEADING = re.compile(r'^\s{0,3}(#{1,6})\s+(.*\S)\s*$')

_BULLET_RE = re.compile(r'^\s*(?:[-*•‣●·–—]+|\d+[.)]|[a-z][.)])\s+', re.I)

_ITEM_TITLE = re.compile(r'^\s*(\d+)[.)]\s+(.{2,70})$')

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"“])')

# Google Docs exports a horizontal rule as a run of underscores.
_HR_RE = re.compile(r'^\s*[_\-=*~]{3,}\s*$')

# Any of these appearing after "and" means the right-hand side is its own ask.
_ACTION_CUES = SPEECH_CUES + VISUAL_CUES + TEXT_CUES + (
    r'\bend(?:s|ing)? with\b', r'\bopen(?:s|ing)? with\b', r'\binclude\b',
    r'\badd\b', r'\bavoid\b', r'\bkeep\b', r'\bmake sure\b', r'\btag\b',
)

def strip_md_inline(s: str) -> str:
    """Bold, italics, code, links -> their text. A brief is prose, not markup."""
    s = s or ''
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'(?<![\w*])\*([^*\n]+)\*(?![\w*])', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)
    return s.strip()

# Checked most-specific first. "Sample Hook Concepts" must reach 'alternatives'
# before anything else claims it.
SECTION_KIND_CUES = (
    ('alternatives', (r'\boptions?\b', r'\bsamples?\b', r'\bexamples?\b', r'\bconcepts?\b',
                      # A section headed "Call to Actions" listing four
                      # phrasings is a MENU. Without these it matched no
                      # cue at all, fell through to the fallback kind, and
                      # left the grouping to the model -- which chose
                      # differently on every compile of the same brief.
                      r'\bcall[- ]?to[- ]?actions?\b', r'\bCTAs?\b',
                      r'\bcampaigns?\b', r'\bthemes?\b',
                      r'\bideas?\b', r'\bvariations?\b', r'\bhooks?\b', r'\bangles?\b',
                      r'\bformats?\b', r'\bchoose\b', r'\bpick\b', r'\beither\b',
                      r'\binspiration\b', r'\bsuggestions?\b', r'\bpick from\b',
                      r'\btemplates?\b', r'\bscripts?\b',
                      r'\bpick[- ]?one\b',
                      r'\bany of\b',
                      r'\bmenu\b',
                      r'\bswipe file\b',
                      r'\bexample scripts?\b',
                      r'\bstory ?boards?\b',
                      r'\breference\b',
                      r'\bmood\b',
                      r'\bstarting points?\b',
                      r'\bprompts?\b',
                      r'\btreatments?\b',
                      r'\bexecutions?\b',
                      r'\broutes?\b',
                      r'\bterritor(?:y|ies)\b')),
    ('claims',       (r'\bbenefits?\b', r'\bclaims?\b', r'\bingredients?\b', r'\bresults?\b',
                      r'\bproduct (?:info|details|facts)\b', r'\bkey (?:facts|points)\b',
                      r'\bwhy it works\b', r'\bscience\b', r'\btalking points?\b',
                      r'\bfeatures?\b', r'\bUSPs?\b',
                      r'\bkey messages?\b',
                      r'\bmessaging\b',
                      r'\bmessage house\b',
                      r'\bproof ?points?\b',
                      r'\breasons? to believe\b',
                      r'\bRTBs?\b',
                      r'\bpillars?\b',
                      r'\bpropositions?\b',
                      r'\bvalue props?\b',
                      r'\bselling points?\b',
                      r'\bproduct truths?\b',
                      r'\bsubstantiation\b',
                      r'\battributes?\b',
                      r'\bspecs? sheet\b')),
    ('requirements', (r'\brequirements?\b', r'\bmust[- ]haves?\b', r'\bdo\'?s\b',
                      r"\bdon'?ts?\b", r'\brules?\b', r'\bguidelines?\b',
                      r'\bdeliverables?\b', r'\bchecklist\b', r'\bmandatory\b',
                      r'\bto[- ]?dos?\b', r'\bspecs?\b', r'\bcompliance\b',
                      r'\bmandator(?:y|ies)\b',
                      r'\bnon[- ]negotiables?\b',
                      r'\bmust include\b',
                      r'\brestrictions?\b',
                      r'\bprohibit\w*\b',
                      r'\bavoid\b',
                      r'\bnever\b',
                      r'\blegal\b',
                      r'\bdisclaimers?\b',
                      r'\bdisclosures?\b',
                      r'\bobligations?\b',
                      r'\bstandards?\b',
                      r'\bpolic(?:y|ies)\b',
                      r'\bsafety\b',
                      r'\bregulator\w*\b',
                      r'\bapprovals?\b')),
    ('context',      (r'\bpurpose\b', r'\boverview\b', r'\babout\b', r'\bbackground\b',
                      r'\bsummary\b', r'\bintro\w*\b', r'\bbrief\b', r'\bguide\b',
                      r'\baudience\b', r'\bbrand\b', r'\btone\b', r'\bgoals?\b',
                      r'\bobjectives?\b',
                      r'\bstrategy\b',
                      r'\binsight\b',
                      r'\bwho we are\b',
                      r'\bproduct\b',
                      r'\bcontext\b',
                      r'\bchallenge\b',
                      r'\bopportunit(?:y|ies)\b',
                      r'\bpersona\w*\b',
                      r'\bdemograph\w*\b',
                      r'\bmarket\b',
                      r'\btimeline\b',
                      r'\bdeadlines?\b',
                      r'\bbudget\b')),
)

# A heading word that also names a requirement TYPE, so "Sample Hook Concepts"
# makes its members hooks rather than whatever each quoted line looks like.
SECTION_TYPE_HINTS = (
    ('hook', (r'\bhooks?\b', r'\bopening\b', r'\bfirst \d+ seconds?\b')),
    ('cta',  (r'\bcta\b', r'\bcalls?[- ]to[- ]action\b', r'\bclosing\b', r'\bend(?:ing)?s?\b')),
)

# "Format example:" followed by a URL -- the reference videos a brief points at.
# These are material to LOOK AT, not requirements to satisfy, and compiling them
# as requirements both invents work and throws away the links.
_URL_RE = re.compile(r'https?://\S+')

_REFERENCE_LINE = re.compile(
    r'^\s*(?:format\s+examples?|examples?|references?|inspo|inspiration|links?|'
    r'reference\s+videos?|example\s+videos?)\s*[:\-]?\s*(?:https?://\S*)?\s*$', re.I)

_URL_ONLY = re.compile(r'^\s*https?://\S+\s*$')

@dataclass
class BriefSection:
    heading: str
    level: int
    kind: str
    lines: list = field(default_factory=list)
    type_hint: Optional[str] = None
    refs: list = field(default_factory=list)   # example / reference video links
    index: int = 0                             # position, for a unique group id

    def slug(self) -> str:
        s = re.sub(r'[^a-z0-9]+', '_', (self.heading or 'section').lower()).strip('_')
        s = s[:40] or 'section'
        # Briefs repeat headings -- this one says "Format example" three times.
        # Without the index two unrelated sections share a group id and their
        # options merge into one choice that was never offered.
        return f'{s}_{self.index}' if self.index else s

# Markers that settle a heading OUTRIGHT, checked before the ordinary cues.
#
# `classify_section` returns the first matching tuple, so a heading carrying
# cues for two kinds is decided by tuple order rather than by which signal is
# stronger. "Prohibited Claims" is a restriction, not a claims list;
# "Campaign Objectives" is background, not a menu of campaigns. No amount of
# extra vocabulary fixes that -- the words are all present and correct, and
# the wrong one wins on position.
#
# Small on purpose: each entry names something that changes what a section IS,
# not what it is about.
SECTION_KIND_OVERRIDES = (
    ('requirements', (r'\bprohibit\w*\b', r'\bforbidden\b', r'\bbanned\b',
                      r'\bdisallow\w*\b', r'\brestrict\w*\b',
                      r'\bmust not\b', r'\bdo not\b', r"\bdon'?ts?\b",
                      r'\bnon[- ]negotiables?\b', r'\bmandator\w*\b',
                      r'\bcompliance\b', r'\blegal\b', r'\bdisclaimers?\b',
                      r'\bdisclosures?\b', r'\bsafety\b')),
    ('context',      (r'\bobjectives?\b', r'\bgoals?\b', r'\bbackground\b',
                      r'\boverview\b', r'\bpurpose\b', r'\btimelines?\b',
                      r'\bdeadlines?\b', r'\bbudgets?\b', r'\bpersona\w*\b',
                      r'\bstrategy\b', r'\binsights?\b')),
)

def classify_section(heading: str, lines: list = None) -> str:
    """Heading first; when it says nothing, decide from whether the lines are imperative.

    OVERRIDES run before the ordinary cues. A heading can carry cues for two
    kinds -- "Prohibited Claims", "Campaign Objectives" -- and the plain loop
    resolves that by tuple order, which is position, not evidence.
    """
    h = heading or ''
    for kind, pats in SECTION_KIND_OVERRIDES:
        if _has(pats, h):
            return kind
    for kind, pats in SECTION_KIND_CUES:
        if _has(pats, h):
            return kind
    body = ' '.join(lines or [])
    if body and _has(_ACTION_CUES, body):
        return 'requirements'
    return 'context' if not body else 'requirements'

def section_type_hint(heading: str) -> Optional[str]:
    for type_, pats in SECTION_TYPE_HINTS:
        if _has(pats, heading or ''):
            return type_
    return None

_ALL_SECTION_CUES = tuple(p for _, pats in SECTION_KIND_CUES for p in pats)

def is_plain_heading(s: str) -> bool:
    """
    Is this a heading in a document that carries NO markdown?

    Google Docs' `export?format=txt` strips every marker: an H2 arrives as an
    ordinary line. Detecting headings by `#` alone -- which is what this layer
    did first -- makes the whole structure pass silently do nothing on a real
    document, and a brief with an Options section compiles as 39 flat mandatory
    requirements. The signal that survives the export is punctuation and length.
    """
    s = (s or '').strip()
    if not s or len(s) > 90:
        return False
    if _BULLET_RE.match(s) or _HR_RE.match(s):
        return False
    if s[0] in '"“”\'‘’(':                      # a quoted hook line is not a heading
        return False
    if '"' in s or '“' in s or '”' in s:        # a line QUOTING something is content
        return False
    words = s.split()
    if len(words) > 12:
        return False
    # An instruction is not a heading, however short: "Show the product" has a
    # verb doing work. A heading names a part of the document.
    if len(words) > 3 and _has(_ACTION_CUES, s):
        return False
    if s.endswith(':'):
        return True
    if s[-1] in '.!?,;':                        # a finished sentence
        return False
    letters = [c for c in s if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6:
        return True                             # ALL CAPS / mostly caps
    caps = sum(1 for w in words if w[:1].isupper())
    if caps >= max(1, len(words) - 2):          # Title Case
        return True
    # Naming a section kind counts only for a SHORT line. "Use the hook 'here's
    # what my hair eats for breakfast'" contains the word "hook" and is an
    # instruction, not a heading -- length is what separates the two.
    return len(words) <= 6 and bool(_has(_ALL_SECTION_CUES, s))

# Third person + a reporting verb = the brief is DESCRIBING an example video,
# not instructing the creator. Measured on the AURELIA brief: "This creator
# begins her video with a relatable hook: ..." compiled into a mandatory
# requirement, and the audit then FAILED a video for not copying someone
# else's opening. A description of what worked for somebody is context; only
# an instruction is a requirement.
_DESC_SUBJECT = re.compile(
    # One optional scene-setting clause first: "In this concept, the
    # creator...". Bounded to a single short phrase so it cannot swallow an
    # instruction -- "In this video, you must show the product" still has an
    # obligation word and is rejected by _OBLIGATION before it gets here.
    r'^\s*(?:(?:in|for|as|with)\s+(?:this|that|the)\s+\w+,\s*)?'
    r'(?:this|the|that|another|one)\s+'
    r'(?:creator|influencer|video|example|ad|clip|post|reel|girl|guy|woman|man)\b',
    re.I)

_DESC_VERB = re.compile(
    r'\b(?:begins?|began|starts?|started|opens?|opened|shares?|shared|shows?|'
    r'showed|uses?|used|talks?|talked|comments?|commented|explains?|explained|'
    r'demonstrates?|demonstrated|highlights?|highlighted|features?|featured|'
    r'mentions?|mentioned|describes?|described|performed|did|does)\b', re.I)

# Two different things, and conflating them was the bug. A MODAL is an
# obligation wherever it appears: "the creator must show the logo" is a
# requirement however it opens. An ordinary verb is not -- "the creator uses a
# subtle style to show her hair health" contains "use" and "show" and is pure
# description. What marks an instruction in English is the imperative mood,
# which is the sentence STARTING with a bare verb.
_OBLIGATION = re.compile(
    r'\b(?:must|should|shall|need(?:s)? to|needing to|has to|have to|required|'
    r'requires?|ensure|make sure|be sure|do not|don\'t|do n\'t|never|always|'
    r'avoid|remember to|aim to)\b', re.I)

_IMPERATIVE_START = re.compile(
    r'^\s*(?:please\s+)?(?:show|use|mention|say|state|include|add|keep|start|'
    r'begin|end|talk|discuss|do|make|film|record|highlight|demonstrate|feature|'
    r'open|close|create|post|tag|link|call|share|explain|describe|focus|'
    r'ensure|avoid|hold|wear|place|set|try|pick|choose|select|deliver)\b',
    re.I)

def strip_descriptive_sentences(text: str) -> str:
    """
    Drop the describing sentences from a block, keep the instructing ones.

    An ALTERNATIVES item is emitted whole -- a numbered creative concept is one
    choice, so splitting it into sentences would scatter its bullets across the
    group. But "whole" then includes any commentary sitting inside it, and the
    model turns that commentary into requirements. Filtering per sentence here
    keeps the concept intact and still removes the parts nobody can comply with.
    """
    keep = []
    for line in re.split(r'(?:\r?\n|(?<=[.!?])\s+)', text or ''):
        s = line.strip()
        if not s:
            continue
        if is_descriptive_example(s):
            continue
        keep.append(s)
    return ' '.join(keep).strip()

def is_descriptive_example(text: str) -> bool:
    """
    Is this line DESCRIBING an example rather than asking for something?

    Deliberately narrow: it needs a third-person subject AND a reporting verb
    AND no obligation wording anywhere. A brief writer who means "do this" has
    many ways to say so, and every one of them contains an obligation word.
    """
    t = (text or '').strip().lstrip('*-•\u2022 \t')
    if not t:
        return False
    if _OBLIGATION.search(t) or _IMPERATIVE_START.match(t):
        return False
    return bool(_DESC_SUBJECT.match(t) and _DESC_VERB.search(t))

def is_quoted_example(text: str) -> bool:
    """
    A line the creator is meant to SAY, quoted verbatim in the brief.

    This matters for polarity. "If your ponytail feels smaller, don't scroll"
    is a hook to deliver, not a prohibition -- but it contains "don't", and the
    negation scan cannot tell the difference without knowing it is a quotation.
    Treated as forbidden it becomes a critical compliance rule that no video can
    satisfy, and it drags false conflicts along with it.
    """
    s = (text or '').strip().rstrip('.')
    return len(s) > 8 and s[0] in '"“”\'‘’'

def parse_brief_sections(text: str) -> list:
    """
    Brief document -> ordered sections with their lines.

    Markdown headings open a section. Everything before the first heading is an
    implicit context section, which is where a document title lands.
    """
    sections, cur = [], BriefSection(heading='', level=0, kind='context')

    n = [0]

    def _open(h, level):
        nonlocal cur
        if cur.lines or cur.refs or cur.heading:
            cur.kind = classify_section(cur.heading, cur.lines)
            sections.append(cur)
        n[0] += 1
        cur = BriefSection(heading=h, level=level, kind='context',
                           type_hint=section_type_hint(h), index=n[0])

    for raw in (text or '').splitlines():
        if not raw.strip() or _HR_RE.match(raw):
            continue
        m = _MD_HEADING.match(raw)
        if m:
            _open(strip_md_inline(m.group(2)), len(m.group(1)))
            continue
        plain = strip_md_inline(raw)
        if not plain:
            continue
        # "Format example:" and the bare URL under it are REFERENCE material --
        # the videos the brief points at. Keep the links, and never compile them
        # as something the creator has to do.
        if _REFERENCE_LINE.match(plain) or _URL_ONLY.match(plain):
            cur.refs.extend(_URL_RE.findall(plain))
            continue
        # No markdown in the document? Then headings look like headings rather
        # than being marked as ones. This branch is what makes the phase work on
        # a real Google Doc export instead of only on markdown.
        if is_plain_heading(plain):
            _open(plain.rstrip(':'), 1)
            continue
        cur.lines.append(plain)
    if cur.lines or cur.refs or cur.heading:
        cur.kind = classify_section(cur.heading, cur.lines)
        sections.append(cur)
    # a heading with nothing under it is a title for what follows, not a section
    return [s for s in sections if s.lines or s.refs]

def brief_reference_links(sections: list) -> list:
    """Every example/reference video the brief points at, in document order."""
    out, seen = [], set()
    for s in sections:
        for u in s.refs:
            u = u.rstrip('.,);')
            if u not in seen:
                seen.add(u)
                out.append({'url': u, 'section': s.heading})
    return out

def section_items(sec: BriefSection) -> list:
    """
    A section's lines -> its items.

    Two shapes, because briefs come in two shapes:

    STRUCTURED (bullets or numbered titles present). A numbered title
    ("1. Everyday Hair") opens an item and absorbs the prose under it; a bullet
    is an item by itself. Handling titles BEFORE sentence splitting is what stops
    "**2. What My Hair Eats for Breakfast**" from being torn into "**2" and the
    rest -- to a sentence splitter, "2." is the end of a sentence.

    FLAT (a pasted brief, one ask per line, no markup). Every line is an item.
    Without this branch a six-line brief collapses into a single requirement.
    """
    numbered = any(_ITEM_TITLE.match(l) for l in sec.lines)
    structured = numbered or any(_BULLET_RE.match(l) for l in sec.lines)
    items = []
    if not structured:
        items = [{'title': l.strip(), 'body': []} for l in sec.lines]
    else:
        cur = None
        for line in sec.lines:
            title = _ITEM_TITLE.match(line)
            is_bullet = bool(_BULLET_RE.match(line)) and not title
            bare = _BULLET_RE.sub('', line).strip()
            if title:
                if cur:
                    items.append(cur)
                cur = {'title': title.group(2).strip(), 'body': []}
            elif is_bullet and numbered:
                # A bullet under "1. Everyday Hair" is a STEP of that concept,
                # not a fourth concept. Treated as a sibling it becomes another
                # option in the one_of group, which tells the evaluator the
                # creator may do any ONE step and skip the rest.
                if cur is None:
                    cur = {'title': '', 'body': []}
                cur['body'].append(bare)
            elif is_bullet:
                if cur:
                    items.append(cur)
                    cur = None
                items.append({'title': bare, 'body': []})
            else:
                if cur is None:
                    cur = {'title': '', 'body': []}
                cur['body'].append(bare)
        if cur:
            items.append(cur)
        # Prose before the first numbered item is the section's introduction --
        # "These are the videos that performed best on TikTok" is not a fourth
        # concept to choose between, and counting it as one puts a sentence the
        # creator cannot act on into a one_of group.
        if numbered and items and not items[0]['title']:
            items = items[1:]
    out = []
    for it in items:
        text = ' '.join(([it['title']] if it['title'] else []) + it['body']).strip()
        text = re.sub(r'\s+', ' ', text)
        if len(text) >= 3:
            out.append({'text': text, 'title': it['title'],
                        'body': ' '.join(it['body']).strip()})
    return out

_NUMERIC_CLAIM = re.compile(r'\d+(?:\.\d+)?\s*(?:%|percent|days?|weeks?|months?|hours?|x\b)',
                            re.I)

# Does the brief DEMAND this material, or OFFER it?
#
# Kind and obligation are different questions. "Key Talking Points" is a
# claims section either way; whether the creator must cover them all is what
# these words answer. Deciding it from the document is what lets one pipeline
# serve a supplement brief that invites improvisation and a pharma brief that
# does not.
_OBLIGATION_REQUIRED = (
    r'\bmust\b', r'\bmandatory\b', r'\brequired?\b', r'\brequirements?\b',
    r'\balways\b', r'\bnever\b', r'\bensure\b', r'\bmake sure\b',
    r'\bdo not\b', r"\bdon'?t\b", r'\bshall\b', r'\bneeds? to\b',
    r'\bhave to\b', r'\bobligatory\b', r'\bnon[- ]negotiable\b',
    r'\bevery (?:video|post|creator)\b', r'\ball of the following\b',
    r'\bwithout exception\b', r'\bcompulsory\b',
)

_OBLIGATION_OPTIONAL = (
    r'\bmay\b', r'\bcan use\b', r'\bcan\b', r'\bencourage\w*\b',
    r'\bfeel free\b', r'\bsuggestions?\b', r'\bexamples?\b', r'\bideas?\b',
    r'\boptions?\b', r'\boptional\b', r'\blibrary\b', r'\bshowcase\b',
    r'\binspiration\b', r'\bpick (?:one|from|any)\b', r'\bchoose\b',
    r'\byour own\b', r'\bup to you\b', r'\bif you (?:like|want|prefer)\b',
    r'\bwe recommend\b', r'\bfree to\b', r'\bwhere relevant\b',
    r'\bas you see fit\b', r'\bany of the\b',
)

def detect_obligation(text: str) -> tuple:
    """('required'|'optional'|None, evidence) from the document's own words.

    Counts modal cues rather than matching one phrase, because a brief says
    it many times and in many ways. Returns None when neither side wins, so
    the caller can say "the brief did not tell us" instead of guessing
    silently.
    """
    t = ' ' + ' '.join(str(text or '').split()).lower() + ' '
    req = [p for p in _OBLIGATION_REQUIRED if re.search(p, t)]
    opt = [p for p in _OBLIGATION_OPTIONAL if re.search(p, t)]
    nr, no = len(req), len(opt)
    if nr == no:
        return None, {'required_cues': nr, 'optional_cues': no}
    winner = 'required' if nr > no else 'optional'
    return winner, {'required_cues': nr, 'optional_cues': no,
                    'matched': [p.replace(chr(92) + 'b', '') for p in
                                (req if winner == 'required' else opt)][:6]}

def claims_obligation_of(sections: list, brief_text: str = '') -> dict:
    """Are the brief's CLAIMS a checklist or a menu? Read, never assumed.

    Per-section first, because a brief can offer talking points in one
    section and demand disclosures in another. The document-level reading is
    the fallback, and 'optional' is the last resort -- flagged, so a reviewer
    can correct it rather than discover it in a score.
    """
    secs = [s for s in (sections or [])
            if getattr(s, 'kind', (s or {}).get('kind') if isinstance(s, dict)
                       else None) == 'claims']
    parts = []
    for s in secs:
        head = getattr(s, 'heading', None) or (s.get('heading') if isinstance(s, dict) else '')
        lines = getattr(s, 'lines', None) or (s.get('lines') if isinstance(s, dict) else []) or []
        parts.append(str(head) + ' ' + ' '.join(str(x) for x in lines))
    sec_call, sec_ev = detect_obligation(' '.join(parts)) if parts else (None, {})
    doc_call, doc_ev = detect_obligation(brief_text)
    call = sec_call or doc_call
    return {'obligation': call or 'optional',
            'determined': bool(call),
            'from': ('claims section' if sec_call else
                     'whole brief' if doc_call else 'DEFAULT (undetermined)'),
            'section_evidence': sec_ev, 'document_evidence': doc_ev}

def extract_approved_claims(sections: list) -> list:
    """
    Claims sections -> an allowlist, with the numbers pinned.

    These are not things the video must say. They are things it MAY say -- and if
    it says them, these are the figures. A creator claiming "50% hair loss
    reduction" where the brief says 27% is a compliance failure, and Phase 2's
    digits_missing() already knows how to compare them.
    """
    claims = []
    for sec in sections:
        if sec.kind != 'claims':
            continue
        for it in section_items(sec):
            nums = _NUMERIC_CLAIM.findall(it['text'])
            claims.append({
                'text': it['text'],
                'section': sec.heading,
                'numbers': [re.sub(r'\s+', '', n) for n in nums],
                'hints': rule_match_hints(it['text'], max_hints=8),
            })
    return claims


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 566: print('§40b document structure loaded.')
