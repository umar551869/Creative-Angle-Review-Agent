"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 90.
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
@dataclass
class Requirement:
    # --- identity ---
    id: str                       # content-derived; stable across recompiles
    ordinal: int                  # display order only -- NEVER used for identity
    label: str                    # short human-readable name

    # --- what is being asked ---
    requirement: str              # the normalised imperative
    type: str                     # REQUIREMENT_TYPES
    priority: str                 # PRIORITIES
    weight: float                 # derived from priority
    polarity: str                 # POLARITIES
    evidence_mode: str            # EVIDENCE_MODES
    machine_checkable: bool

    # --- choice ---
    # group is None for an ordinary requirement. When set, every requirement
    # sharing the id is one option in the same decision, and group_mode says
    # how many of them have to hold.
    group: Optional[str] = None
    group_mode: str = 'all_of'
    group_label: str = ''
    # What KIND of ask the options in this group are examples OF.
    #
    # Without it, `Use the hook: "Your shampoo isn't the problem."` reads as a
    # demand for that sentence, and an adjudicator judging how closely a
    # creator ALIGNED will faithfully compare her words to those words. Measured
    # on a real brief: two different models both answered `none`; given the
    # group's intent, both answered `partial`. The sentences are examples; this
    # is the ask.
    group_intent: str = ''
    # When the compiled intent named only a POSITION ("conclude the video
    # with a call to action" -- which any closing sentence satisfies), it is
    # repaired from the group's own options before L3 judges against it. The
    # wording the model first produced is kept here, so the repair is
    # auditable and the brief can still be fixed at source.
    group_intent_original: str = ''

    # --- temporal, absolute ---
    deadline_seconds: Optional[float] = None
    window_start_seconds: Optional[float] = None
    window_end_seconds: Optional[float] = None

    # --- temporal, symbolic (resolved per video at audit time) ---
    window_start_expr: Optional[str] = None
    window_end_expr: Optional[str] = None

    # --- matching aids ---
    match_hints: list = field(default_factory=list)
    acceptance_criteria: list = field(default_factory=list)
    forbidden_evidence: list = field(default_factory=list)
    claim_classes: list = field(default_factory=list)

    # --- provenance and quality ---
    source: str = 'brief'         # 'brief' | 'inferred'
    brief_span: str = ''          # the sentence this came from
    confidence: float = 0.5
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def has_temporal_constraint(self) -> bool:
        return any(v is not None for v in (
            self.deadline_seconds, self.window_start_seconds, self.window_end_seconds,
            self.window_start_expr, self.window_end_expr))

    def is_scorable(self) -> bool:
        """Scoring set membership. Vague requirements are reported, never scored."""
        return self.machine_checkable and self.type != 'other'

def scoring_units(reqs: list) -> list:
    """
    The things Phase 7 actually scores. A one_of group is ONE unit.

    Three alternative hooks are one decision the creator made, not three
    requirements they had to satisfy. Summing member weights would make a brief
    that offers more options harder to pass than one that offers fewer, which is
    backwards -- more options is more freedom, not more obligation.
    """
    units, seen = [], {}
    for r in reqs:
        if not r.is_scorable():
            continue
        if r.group and r.group_mode in ('one_of', 'any_of'):
            u = seen.get(r.group)
            if u is None:
                u = {'kind': 'group', 'group': r.group, 'label': r.group_label or r.group,
                     'mode': r.group_mode, 'members': [], 'weight': 0.0}
                seen[r.group] = u
                units.append(u)
            u['members'].append(r.id)
            u['weight'] = max(u['weight'], r.weight)
        else:
            units.append({'kind': 'single', 'group': None, 'label': r.label,
                          'mode': 'all_of', 'members': [r.id], 'weight': r.weight})
    return units

def total_scoring_weight(reqs: list) -> float:
    return round(sum(u['weight'] for u in scoring_units(reqs)), 2)

def requirement_id(text: str, type_: str) -> str:
    """
    Content-derived, so it survives a recompile.

    Positional IDs (R1, R2, R3...) are the trap here. Recompile a brief after
    editing one line and R3 silently becomes a different requirement -- while
    every cached audit result still references R3 and still validates. The
    numbers line up and they are wrong. Hashing the content means a changed
    requirement gets a NEW id and a stale reference fails loudly instead.
    """
    basis = f'{type_}|{re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()}'
    return 'r_' + hashlib.sha256(basis.encode('utf-8')).hexdigest()[:8]

# A directive preamble is boilerplate: "Deliver the Call to Action:" is
# IDENTICAL across every member of a choice group, so spending the word budget
# on it makes every member's label read the same. Two labels that name
# different requirements must never be the same string -- the review table and
# the group-resolution line both print this, and "Not the option satisfied ...
# \"Deliver Call Action I m\" was (UNCERTAIN, ...)" is unreadable.
_LABEL_PREAMBLE = re.compile(
    r'^\s*(?:deliver|include|show|use|open|close|end|finish|mention|state|'
    r'feature|demonstrate|add|ensure|make\s+sure|do\s+not|don.t|avoid)\b'
    r'[^:]{0,60}:\s*', re.I)

# Straight and curly double quotes only. The ASCII apostrophe is NOT a quote
# delimiter here -- "I'm" must survive as a word.
_LABEL_QUOTED = re.compile(r'["\u201c]([^"\u201d]{3,})["\u201d]')

# Apostrophes are kept INSIDE words. Stripping them turned "I'm" into "I m",
# which is where the stray "m" in the old labels came from.
_LABEL_STRIP = re.compile(r"[^\w\s%$@#'\u2019-]")

def make_label(text: str, max_words: int = 8) -> str:
    """A short name for the review table. Not an identifier.

    Order matters: drop the shared directive preamble, then prefer the quoted
    thing the creator is actually asked to say, and only THEN fall back to
    dropping stopwords to fit. Dropping stopwords first is what produced
    "Deliver Call Action I m" for two different requirements.
    """
    raw = (text or '').strip()
    body = _LABEL_PREAMBLE.sub('', raw, count=1).strip() or raw
    quoted = _LABEL_QUOTED.findall(body)
    if quoted:
        body = max(quoted, key=len).strip()
    words = _LABEL_STRIP.sub(' ', body).split()
    if not words:
        words = _LABEL_STRIP.sub(' ', raw).split()
    if len(words) > max_words:
        drop = {'the', 'a', 'an', 'to', 'of', 'and', 'or', 'in', 'on', 'at',
                'with', 'that', 'this', 'please', 'must', 'should'}
        kept = [w for w in words if w.lower() not in drop]
        # Never let stopword-dropping shred a short label into initials.
        if len(kept) >= 3:
            words = kept
    return ' '.join(words[:max_words]).strip() or 'requirement'


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 170: print('§38 schema loaded.')
#   line 171: print(f'  Requirement fields  : {len(Requirement.__dataclass_fields__)}')
#   line 172: print(f'  priority -> weight  : {PRIORITY_WEIGHT}')
