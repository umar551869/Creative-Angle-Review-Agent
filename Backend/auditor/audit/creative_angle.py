"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 127.
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
CREATIVE_ANGLES = (
    'social_proof',            # others' reactions, comments, "you asked about"
    'personal_transformation', # her own before/after, a journey over time
    'routine_integration',     # where it sits in an existing routine
    'problem_solution',        # names a problem, presents the product as answer
    'education',               # explains how or why something works
    'comparison',              # this versus that, or versus what she used before
    'demonstration',           # shows the product being used, application-led
    'testimonial_response',    # answering a specific question or objection
    'day_in_life',             # the product inside a narrative of her day
    'humour',                  # comedic framing carries the message
    'other',
)

ANGLE_SYSTEM = """You describe the CREATIVE ANGLE a short-form video takes.

You are given evidence extracted from one video, and the concepts its brief
offered. Answer in THREE steps, and do not let a later step change an
earlier one.

1. WHAT DID SHE MAKE? Name the angle from the allowed list. Judge the video on
   its own terms. Do NOT mark it down for differing from the brief -- a video
   that takes an angle the brief never listed is not thereby a worse video.

2. WHERE DOES IT SIT? Name the brief concept it comes closest to, and say
   whether the brief anticipated this angle at all. "Not anticipated" is a
   normal and useful answer: it describes the BRIEF's coverage, not a fault in
   the video.

3. HOW MUCH OF EACH NAMED ANGLE? The input lists NAMED ANGLES -- the two or
   three creative angles this brief actually names. Give a PERCENTAGE SPLIT
   saying how much of THIS video belongs to each:
     - the percentages MUST sum to 100
     - use ONLY the names under NAMED ANGLES, spelled exactly; invent none
     - if it DOES belong to the listed angles, a video is usually MOSTLY
       one and PARTLY another -- say so, rather than putting 100 on one and
       nothing on the rest
     - IF IT BELONGS TO NONE OF THEM, say exactly that: put the share on the
       exact name "none of the listed angles". A creator who invented her own
       angle is a normal outcome and often a good video -- this brief simply
       did not anticipate it.
     - Do NOT spread percentages across the listed angles to avoid answering
       "none". A forced split claims a resemblance that is not there, and
       that is worse than the honest answer"
   This DESCRIBES what she made. It is never a score, and it counts neither
   for nor against her.

Use ONLY the evidence given. You cannot see the video. Cite evidence ids from
the list, or none.

Return ONLY this JSON, no prose and no code fence. EVERY key below is
REQUIRED -- including concept_fit, which must not be empty whenever NAMED
ANGLES appear in the input:
{"angle": "one of the allowed values",
 "summary": "one sentence describing what the creator actually made",
 "reason": "one sentence, grounded in the evidence",
 "nearest_brief_concept": "the concept name, or null if none is close",
 "anticipated_by_brief": true,
 "concept_fit": [{"angle": "exactly one of the NAMED ANGLES",
                  "percent": 70,
                  "why": "one sentence, grounded in the evidence"},
                 {"angle": "another NAMED ANGLE",
                  "percent": 30,
                  "why": "one sentence, grounded in the evidence"}],
 "evidence_ids": ["..."]}"""

# Group labels that mean "this group holds the creative angles".
_ANGLE_GROUP_RE = re.compile(
    r'\b(concepts?|angles?|formats?|territor(?:y|ies)|themes?|creative|'
    r'frameworks?|treatments?|executions?|routes?|campaigns?)\b', re.I)

# A bullet marker survives parse_brief_sections; a sub-heading does not have
# one. That single difference is what separates an angle's NAME from the lines
# describing it, and it holds for both a markdown export ('*') and a Google
# Docs plain-text export ('●').
# Headings that end a run of angles. Everything here names a DIFFERENT kind of
# instruction, so a section titled with one of them is never an angle however
# it is formatted.
_ANGLE_STOP_RE = re.compile(
    # don\S{0,2}ts, not don'?ts: a bare apostrophe inside an r'...'
    # literal closes the string and the cell stops parsing.
    r'\b(do\s*not|don\S{0,2}ts?|dos?\s+and|requirements?|mandator\w*|prohibit\w*|'
    r'talking\s*points?|product\s+features?|features?|deliverables?|'
    r'call\s*to\s*actions?|ctas?|hashtags?|captions?|hooks?|'
    r'timelines?|deadlines?|budgets?|legal|compliance|disclaimers?|'
    r'audiences?|objectives?|goals?|brand\s+\w+|assets?|specs?|'
    r'purpose|overview|background|summary)\b', re.I)

_ANGLE_BULLET_RE = re.compile(r'^\s*[\*\-\u2022\u25cf\u25aa\u2023\u00b7\u2013\u2014]+\s+')

_ANGLE_NUMBERED_RE = re.compile(r'^\s*(\d{1,2})\s*[.)]\s+(.{2,70})$')

# Lines that describe an angle rather than name one.
_ANGLE_DETAIL_CUE_RE = re.compile(
    r'^(hook|hooks|format|formats|note|notes|caption|cta|call to action|'
    r'script|example|examples|visual|audio|tone|style|length|duration|'
    r'creator|talent|deliverable)s?\b\s*:?', re.I)

def _strip_angle_quotes(name: str) -> str:
    """A quoted title is still a title.

    The Biostime brief names every angle in smart quotes -- "Back to School
    Essentials" -- so rejecting anything that opens with a quote found NONE of
    its four angles. Strip the quotes and judge what is inside; a quoted HOOK
    is still excluded, by the sentence and length rules, which is what was
    actually doing the work all along.
    """
    n = (name or '').strip()
    _PAIRS = (('"', '"'), ('\u201c', '\u201d'), ("'", "'"),
              ('\u2018', '\u2019'))
    for a, b in _PAIRS:
        if len(n) > 2 and n.startswith(a) and n.endswith(b):
            return n[1:-1].strip()
    # An unmatched opening quote still means the title was quoted -- a
    # document that lost its closing quote in export is not a different kind
    # of document.
    if len(n) > 1 and n[0] in '"\u201c\u2018\'':
        return n[1:].strip().rstrip('"\u201d\u2019\'')
    return n

def _looks_like_angle_name(name: str) -> bool:
    """A NAME, not a sentence and not a line of script.

    QUOTING IS NOT THE DISCRIMINATOR -- sentence-ness is:
        "Back to School Essentials"                      -> KEEP
        "Listen! If your kid lives on ... every morning." -> DROP, ends '.'
    """
    n = _strip_angle_quotes(name)
    if not (2 <= len(n) <= 70):
        return False
    if n[-1] in '.!?':
        return False                       # a lead-in sentence, not a heading
    if _ANGLE_DETAIL_CUE_RE.match(n):
        return False
    return any(c.isalpha() for c in n)

def brief_angle_blocks(compiled: dict, limit: int = 8) -> list:
    """[{'name', 'detail'}] -- the brief's OWN angles, with what each involves.

    Reads the DOCUMENT, not the compiled requirements: the compiler flattens
    an angle's bullets into requirements, which is why reading labels back out
    returned hooks instead of angles.

    Returns [] when the brief is not shaped this way, so the caller can fall
    back rather than report an empty list as a finding.
    """
    # An approved compile is frozen and reused from disk. One written before
    # 'brief_text' was stored has none, and the document path would then find
    # nothing forever. §48 leaves the loaded document in BRIEF_TEXT.
    text = ((compiled or {}).get('brief_text')
            or globals().get('BRIEF_TEXT') or '')
    _parse = globals().get('parse_brief_sections')
    if not text or not callable(_parse):
        return []
    blocks = []
    try:
        sections = _parse(text)
    except Exception:
        return []
    for _i, sec in enumerate(sections):
        if not _ANGLE_GROUP_RE.search(str(getattr(sec, 'heading', '') or '')):
            continue
        numbered, loose, cur = [], [], None
        for raw in (getattr(sec, 'lines', None) or []):
            line = str(raw).strip()
            if not line:
                continue
            if _ANGLE_BULLET_RE.match(line):
                if cur is not None:
                    cur['detail'].append(_ANGLE_BULLET_RE.sub('', line).strip())
                continue
            m = _ANGLE_NUMBERED_RE.match(line)
            name = _strip_angle_quotes(
                (m.group(2) if m else line).strip().rstrip(':').strip())
            if not _looks_like_angle_name(name):
                continue
            cur = {'name': name, 'detail': []}
            (numbered if m else loose).append(cur)
        # NUMBERING WINS when the section uses it. Otherwise the lead-in
        # sentence and any stray line compete with the real names.
        found = numbered or loose
        if not found:
            # The angle names are SECTIONS of their own -- the shape a brief
            # takes when it bolds them without numbering. Walk forward until a
            # heading names a different topic.
            for nxt in sections[_i + 1:]:
                h = str(getattr(nxt, 'heading', '') or '').strip()
                if not h or _ANGLE_STOP_RE.search(h) \
                        or _ANGLE_GROUP_RE.search(h):
                    break
                if not _looks_like_angle_name(h):
                    break
                _lines = [_ANGLE_BULLET_RE.sub('', str(x).strip()).strip()
                          for x in (getattr(nxt, 'lines', None) or [])]
                _lines = [x for x in _lines if x]
                if not _lines:
                    # An angle has something under it. A bare heading with no
                    # content is a divider, not a creative territory.
                    break
                found.append({'name': _strip_angle_quotes(h),
                              'detail': _lines})
        blocks.extend(found)
    out, seen = [], set()
    for b in blocks:
        k = b['name'].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({'name': b['name'], 'detail': b['detail'][:6]})
    return out[:limit]

def named_brief_angles(compiled: dict, limit: int = 8) -> list:
    """The brief's NAMED creative angles -- the options, not their heading.

    _brief_concepts returns group LABELS, which is the right answer for "which
    section is this nearest to" and the wrong one for "which of the two angles
    is this". A brief carries two or three angles by name -- "No judgement
    zone", "Health journey" -- and that is what a reader wants attributed.

    Only groups whose label reads like a set of creative angles are used, so a
    ten-option hook list does not become ten angles.
    """
    # THE DOCUMENT FIRST. An angle is a sub-heading in the brief; the
    # compiler flattens the bullets beneath it into requirements, so reading
    # requirement labels back out returns the HOOKS, not the angles. That is
    # exactly what it did: "I was just about refill my pill organiser" was
    # reported as an angle of a brief whose angles are "No judgement zone"
    # and "Health journey".
    _blocks = brief_angle_blocks(compiled, limit=limit)
    if _blocks:
        return [b['name'] for b in _blocks]

    # FALLBACK, unchanged: a brief with no angle sub-headings, where the
    # options of an angle-ish choice group genuinely are the angles.
    groups = {}
    for r in (compiled or {}).get('requirements') or []:
        g = r.get('group')
        if not g:
            continue
        d = groups.setdefault(g, {'label': str(r.get('group_label') or g),
                                  'members': []})
        lbl = str(r.get('label') or '').strip()
        if lbl and lbl not in d['members']:
            d['members'].append(lbl)
    named = []
    for g, d in groups.items():
        if not _ANGLE_GROUP_RE.search(f"{d['label']} {g}"):
            continue
        for m in d['members']:
            if m not in named:
                named.append(m)
    return named[:limit]

NO_ANGLE_LABEL = 'none of the listed angles'

def _clean_concept_fit(raw, named: list, flags: list) -> list:
    """[{angle, percent, why}] summing to 100, over the brief's OWN angles.

    A percentage from a model is still a model's opinion, so it is checked the
    way every other model output here is: against a CLOSED list, with the
    repair recorded rather than silently applied.

      - an angle the brief never named is DROPPED (the model invented it)
      - percentages are coerced, clamped, and renormalised to 100
      - a split that did not sum is flagged, not quietly fixed

    It never reaches Phase 7. This describes what she made; it is not a score
    and nothing downstream may treat it as one.
    """
    allowed = list(named) + [NO_ANGLE_LABEL]
    rows, dropped = [], []
    for item in (raw or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get('angle') or item.get('concept') or '').strip()
        match = next((a for a in allowed if a.lower() == name.lower()), None)
        if match is None:
            # a near miss on wording is still the model's own label
            match = next((a for a in allowed
                          if name and (name.lower() in a.lower()
                                       or a.lower() in name.lower())), None)
        if match is None:
            if name:
                dropped.append(name[:40])
            continue
        try:
            pct = float(item.get('percent'))
        except (TypeError, ValueError):
            continue
        rows.append({'angle': match, 'percent': max(0.0, min(100.0, pct)),
                     'why': str(item.get('why') or '')[:200]})
    if dropped:
        flags.append(f'CONCEPT_FIT_NOT_IN_BRIEF:{",".join(dropped[:3])}')
    if not rows:
        return []
    # merge duplicates, then renormalise
    merged = {}
    for r in rows:
        m = merged.setdefault(r['angle'], {'angle': r['angle'], 'percent': 0.0,
                                           'why': r['why']})
        m['percent'] += r['percent']
        if not m['why']:
            m['why'] = r['why']
    rows = list(merged.values())
    total = sum(r['percent'] for r in rows)
    if total <= 0:
        return []
    if abs(total - 100.0) > 2.0:
        flags.append(f'CONCEPT_FIT_RENORMALISED:{total:.0f}->100')
    for r in rows:
        r['percent'] = round(100.0 * r['percent'] / total, 1)
    rows.sort(key=lambda r: -r['percent'])
    return rows

def _brief_concepts(compiled: dict) -> list:
    """The distinct choice groups the brief offered, as names."""
    out, seen = [], set()
    for r in (compiled or {}).get('requirements') or []:
        lbl = r.get('group_label') or r.get('group')
        if lbl and lbl not in seen:
            seen.add(lbl)
            out.append(str(lbl))
    for s in (compiled or {}).get('sections') or []:
        if s.get('kind') == 'alternatives':
            h = str(s.get('heading') or '')
            if h and h not in seen:
                seen.add(h)
                out.append(h)
    return out

def evaluate_creative_angle(records: list, compiled: dict, result: dict,
                            backend=None, cfg: Phase6Config = None,
                            verbose: bool = True) -> dict:
    """What the creator made, named and placed. Never raises."""
    cfg = cfg or P6
    concepts = _brief_concepts(compiled)
    out = {'angle': None, 'summary': '', 'reason': '', 'layer': 'L3',
           'nearest_brief_concept': None, 'anticipated_by_brief': None,
           'brief_concepts': concepts, 'named_angles': [],
           'concept_fit': [], 'evidence_ids': [], 'flags': [],
           'disclaimer': (
               'The creative angle describes what the video IS, not whether it '
               'complies. A video may take an angle the brief never listed and '
               'still satisfy every requirement -- and one that matches a listed '
               'concept may still fail on specifics.')}

    # Same rule as standing: an angle is carried by what the video SHOWS as
    # much as by what it says. A silent routine-integration video is still a
    # routine-integration video.
    speech = [r for r in records if r.modality == 'speech']
    _usable = [r for r in records if r.modality in ('speech', 'ocr', 'visual')]
    if not _usable:
        out.update(angle=None, reason=(
            'No speech, text or visual evidence, so the creative angle cannot '
            'be characterised. This is UNCERTAIN, not "no angle".'),
            flags=['ANGLE_NO_EVIDENCE'], layer='L1')
        return out
    if not speech:
        out['flags'].append('ANGLE_WITHOUT_SPEECH')
    if not (cfg.l3.enabled):
        out.update(reason='L3 is disabled, and the angle needs the language '
                          'model to name it.',
                   flags=out['flags'] + ['ANGLE_NOT_JUDGED'], layer='L1')
        return out

    # ON-SCREEN TEXT IS ANGLE EVIDENCE, and was being withheld from the one
    # judgement that asks "which of the brief's concepts is this video".
    #
    # `_usable` three lines up already counts ocr as evidence, and the failure
    # message says "No speech, text or visual evidence" -- but the candidate
    # list was speech + visual only, so the text was never shown. Same shape as
    # the L3 truncation bug: the record that decides the question never reaches
    # the judge, which then answers honestly about what it was given.
    #
    # It matters most on exactly this platform. Measured on
    # 7672157062691818782: the overlay reads "Before you give your kids
    # melatonin, watch this" -- a near-verbatim match for the brief's named
    # angle "Why I Stopped Giving My Kids Melatonin" -- and the angle came back
    # "none of the listed angles" at 100%. On TikTok the hook caption is
    # frequently a clearer statement of the creative concept than the speech.
    #
    # EARLIEST FIRST, unlike the other two. The concept-declaring overlay is a
    # title card; packaging text and ingredient panels come later and are about
    # the product, not the angle.
    _ocr = sorted((r for r in records if r.modality == 'ocr'),
                  key=lambda r: getattr(r, 'start_seconds', 0.0) or 0.0)
    cands = (speech[:cfg.retrieval.top_k]
             + [r for r in records if r.modality == 'visual'][:cfg.retrieval.top_k]
             + _ocr[:cfg.retrieval.top_k])
    lines = ['EVIDENCE FROM THE VIDEO:']
    lines += [_evidence_line(c) for c in cands] or ['  (none)']
    lines += ['', 'CONCEPTS THE BRIEF OFFERED:']
    lines += [f'  - {c}' for c in concepts] or ['  (the brief offered no named concepts)']
    hook = (result or {}).get('hook') or {}
    if hook.get('hook_type'):
        lines += ['', f'The hook module read the opening as: {hook.get("hook_type")}'
                      f' ({hook.get("strength") or "strength not judged"}).']
    lines += ['', f'Allowed angle values: {", ".join(CREATIVE_ANGLES)}']
    _named = named_brief_angles(compiled)
    out['named_angles'] = list(_named)
    # WHICH PATH FOUND THEM. Without this, "the hooks came back again" has
    # three causes -- stale cell, cached verdicts, or the fallback running --
    # and one symptom. Printed by §90/§91.
    out['angles_source'] = ('document' if brief_angle_blocks(compiled)
                            else 'group_labels' if _named else 'none')
    if _named:
        # WITH WHAT EACH ANGLE INVOLVES. "No judgement zone" on its own is
        # close to unjudgeable -- the bullets under it in the brief are what
        # make an attribution possible. The closed list validated afterwards
        # is still the NAMES only.
        _detail = {b['name']: b.get('detail') or []
                   for b in brief_angle_blocks(compiled, limit=len(_named))}
        lines += ['', 'NAMED ANGLES (use these exact names in concept_fit):']
        for a in _named:
            lines.append(f'  - {a}')
            for d in (_detail.get(a) or [])[:4]:
                lines.append(f'        {d}')
        lines += [f'  - {NO_ANGLE_LABEL}']
    else:
        # Say so on the artifact. An empty split then means "there was
        # nothing to attribute", not "the model declined" -- and the fix is to
        # the BRIEF's structure, not to the prompt.
        out['flags'].append('NO_NAMED_ANGLES_IN_BRIEF')
        lines += ['', 'The brief names no creative angles; return an empty '
                      'concept_fit.']

    bcfg = replace(P4.brief, temperature=0.0, max_new_tokens=1024)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(ANGLE_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _ = parse_model_json(gen.get('text', '') or '')
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'
    if not isinstance(obj, dict):
        out.update(reason=f'The angle model returned nothing usable ({perr}).',
                   flags=out['flags'] + ['ANGLE_MODEL_FAILED'])
        return out

    ang = str(obj.get('angle') or '').lower().strip()
    offered = {c.id for c in cands}
    ids = [i for i in (obj.get('evidence_ids') or []) if i in offered]
    near = obj.get('nearest_brief_concept')
    near = str(near) if near else None
    out.update(
        angle=(ang if ang in CREATIVE_ANGLES else 'other'),
        summary=str(obj.get('summary') or '')[:300],
        reason=str(obj.get('reason') or '')[:300],
        nearest_brief_concept=(near if near in concepts else None),
        anticipated_by_brief=(bool(obj.get('anticipated_by_brief'))
                              if obj.get('anticipated_by_brief') is not None
                              else None),
        concept_fit=_clean_concept_fit(obj.get('concept_fit'), _named,
                                       out['flags']),
        concept_fit_missing=bool(_named) and not (obj.get('concept_fit') or []),
        evidence_ids=ids)
    if ang not in CREATIVE_ANGLES:
        out['flags'].append(f'ANGLE_OUT_OF_ENUM:{ang[:30]}')
    if near and near not in concepts:
        # a concept the brief does not contain is an invention, not a reading
        out['flags'].append(f'ANGLE_CONCEPT_NOT_IN_BRIEF:{near[:40]}')
    if not ids:
        out['flags'].append('ANGLE_UNCITED')

    # ---- did it match ANY of the brief's angles? -------------------------
    # Three states otherwise render identically as zeros across the named
    # angles: the model failed, the model answered with no split, and the
    # model answered "none of these". Only the last is a finding about the
    # video; the other two are pipeline problems. Keep them distinguishable.
    _off = sum(float(r.get('percent') or 0)
               for r in (out.get('concept_fit') or [])
               if str(r.get('angle')) == NO_ANGLE_LABEL)
    out['off_angle_percent'] = round(_off, 1)
    out['matched_named_angle'] = (bool(out.get('concept_fit'))
                                  and _off < 50.0)
    if out.get('concept_fit') and _off >= 50.0:
        # A FACT ABOUT THE VIDEO, not a fault in it. The flag exists so a
        # batch can count "how many creators went off-concept", which is a
        # question about the BRIEF as much as about the creators.
        out['flags'].append(f'ANGLE_NONE_OF_THE_LISTED:{_off:.0f}%')
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 487: print('§69b creative angle loaded.  Describes the video on its own terms, th
