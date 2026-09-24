"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 137.
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
# 1.1.0: the grade reads from the established end of the band (`band_basis`),
#        and dimensions resolve through the brief's own grouping when the
#        compiler typed a requirement by modality (`inferred_units`).
#
# THE RULE THIS EXISTS FOR: bump the stage version in the SAME edit that
# changes the output. The score cache key is built from this constant, not
# from the artifact's shape -- so an unbumped change leaves §80 reading a
# score computed by older code, silently. Both fixes above landed without a
# bump, and the next run reported APPROVED from a cached artifact while the
# freshly-passing tests said otherwise.
# 1.3.0: a requirement with no brief sentence behind it leaves the score.
# 1.2.0: the strict reading travels with the credited one --
#        `literal_headline`, `literal_band_low`, `credited_in_substance`.
# 1.4.0: the standing/score contradiction is checked in BOTH directions.
SCORE_STAGE_VERSION = '1.6.0'

REPORT_STAGE_VERSION = '1.2.0'

# Status -> points. Straight from plan.md §7.1.
#
# UNCERTAIN is deliberately ABSENT. It is not a low score, it is "nobody
# looked", and a dict entry for it would invite exactly the averaging §73b
# forbids. §76 handles it by computing a band instead. NOT_APPLICABLE is absent
# for the same reason: it leaves the denominator, it does not score 0.
STATUS_SCORE = {'PASS': 1.0, 'PARTIAL': 0.5, 'FAIL': 0.0}

# ---------------------------------------------------------------------------
# Dimensions (spec §39)
# ---------------------------------------------------------------------------
# Order is the spec's, and it is fixed: the report, the figures and the JSON
# all iterate this tuple, so a stable order is what makes two runs of the same
# artifact byte-identical.
DIMENSIONS = (
    ('hook',          'Hook',                  0.20),
    ('product',       'Product presence',      0.15),
    ('demonstration', 'Product demonstration', 0.15),
    ('messaging',     'Messaging',             0.20),
    ('audience',      'Audience alignment',    0.10),
    ('cta',           'Call to action',        0.10),
    ('brand',         'Brand / format',        0.10),
)

DIMENSION_KEYS = tuple(k for k, _l, _w in DIMENSIONS)

DIMENSION_LABEL = {k: l for k, l, _w in DIMENSIONS}

DIMENSION_WEIGHT = {k: w for k, _l, w in DIMENSIONS}

# Requirement type -> dimension.
#
# Measured distribution across 101 compiled requirements:
#   cta 35, hook 30, speech 17, policy 7, visual 6, demonstration 3, other 2,
#   audience 1.
#
# 'speech_or_text' is messaging: the ask is that something be COMMUNICATED, and
# the mode is an evidence question, not a dimension question. 'timing' is
# format -- pacing and length are how the video is built, not what it says.
TYPE_TO_DIMENSION = {
    'hook':           'hook',
    'visual':         'product',
    'demonstration':  'demonstration',
    'speech':         'messaging',
    'speech_or_text': 'messaging',
    'audience':       'audience',
    'cta':            'cta',
    'policy':         'brand',
    'brand':          'brand',
    'timing':         'brand',
    'other':          'brand',
}

# `type` carries TWO axes, and that is the problem this works around.
#
#   hook, cta, demonstration, audience, policy, brand, timing   what KIND of ask
#   speech, speech_or_text, visual, other                       which MODALITY
#
# A hook requirement is both -- a hook ask, carried by speech or text -- and
# the enum makes the compiler choose one. Measured on a live brief: 19 of 22
# requirements came back `speech_or_text`, including all twelve hook options
# and every CTA. Every one of them mapped to Messaging, and the report told a
# reviewer "this brief says nothing about your hook" about a brief with a
# twelve-option hook list.
#
# The modality half is also REDUNDANT: `evidence_mode` already carries it.
# Those three values duplicate a field that exists and destroy the dimension
# to do it.
#
# Fixing the compiler would be model-dependent and would invalidate every
# compiled brief on disk. The brief's own STRUCTURE already answers it --
# the groups are named `hook_options_group` / 'Hook Concepts' and
# `cta_ideas_group` / 'Call to action (CTA) Ideas' -- so read that instead.
MODALITY_TYPES = ('speech', 'speech_or_text', 'visual', 'other')

# Only hook and cta are inferred. They are the two with unambiguous group
# names and the two actually being lost; every extra keyword rule is a new way
# to be confidently wrong.
_DIMENSION_HINTS = (
    ('hook', r'hook'),
    ('cta', r'cta|call to action|call action'),
)

def _dim_haystack(*sources) -> str:
    """
    Group ids and labels, flattened to words.

    Non-alphanumerics become spaces FIRST. `cta_ideas_group` word-matched
    as-is never fires, because `_` is a word character and `(?!\\w)` cannot
    close after `cta`. Normalising turns it into `cta ideas group`, which
    matches -- and keeps the word-boundary discipline that stopped `shoulder`
    being read as `should`.
    """
    return re.sub(r'[^a-z0-9]+', ' ',
                  ' '.join(str(s or '') for s in sources).lower())

def resolve_dimension(req: dict, verdict: dict = None) -> tuple:
    """
    (dimension, how) for one requirement. `how` travels into the artifact, so
    a subscore drawn from an inference is never mistaken for a declared one.
    """
    rt = (req or {}).get('type') or ''
    if rt and rt not in MODALITY_TYPES:
        return TYPE_TO_DIMENSION.get(rt, 'brand'), 'typed'
    hay = _dim_haystack((req or {}).get('group'), (req or {}).get('group_label'),
                        (verdict or {}).get('group'),
                        (verdict or {}).get('group_label'))
    for dim, pat in _DIMENSION_HINTS:
        if re.search(rf'(?<!\w)(?:{pat})(?!\w)', hay):
            return dim, 'inferred from the brief\'s own grouping'
    return TYPE_TO_DIMENSION.get(rt, 'brand'), 'typed'

def dimension_of(req_type: str) -> str:
    """Type alone, when there is nothing else to go on."""
    return TYPE_TO_DIMENSION.get(req_type or '', 'brand')

# ---------------------------------------------------------------------------
# The relevance gate  --  TWO questions, asked in order
# ---------------------------------------------------------------------------
# 1. Is this video addressing this brief AT ALL?
# 2. Given that it is, how closely did it follow what the brief asked for?
#
# Collapsing those into one number makes "wrong video entirely" and "right
# video, weak execution" come out the same, and they are not the same finding:
# the first needs a different video, the second needs the edits §78 proposes.
# Telling a creator to "add a sentence about barrier support at 0:11" when she
# filmed a pill organiser is not advice, it is nonsense.
#
# `standing` answers question 1 -- it reads the whole video against the whole
# brief. Measured in Phase 6: it separated an on-brief from an off-brief video
# perfectly, six runs, zero variance, while the alignment mean did not separate
# them at all. That is exactly what you would expect, because alignment
# measures FORM WITHIN an assumed-relevant video. It was answering question 2
# all along.
#
# The per-requirement arithmetic answers question 2, and it is only meaningful
# once question 1 is settled.
RELEVANCE_SCORABLE = ('partial', 'on_brief', 'exemplary')

RELEVANCE_GATED = ('off_brief', 'tangential')

# A gate driven by ONE model call is a single point of failure, so it fails
# OPEN. When standing could not be judged -- no speech, L3 disabled, a parse
# failure -- the score is reported normally with a note. The same discipline as
# Phase 5's can_fail_on: an absent judgement is not a negative one, and
# "we could not tell" must never become "off brief".
RELEVANCE_FAIL_OPEN = True

def relevance_of(standing: dict) -> dict:
    """(scorable, level, why) for one standing block. Never raises."""
    level = (standing or {}).get('standing')
    if not level:
        return {'level': None, 'scorable': bool(RELEVANCE_FAIL_OPEN),
                'judged': False,
                'why': ('Relevance was never judged, so the score is reported '
                        'as if the video is on brief. This is "we could not '
                        'tell", not "it is off brief".')}
    if level in RELEVANCE_GATED:
        return {'level': level, 'scorable': False, 'judged': True,
                'why': (f'Read whole, this video is {level} for this brief. A '
                        f'per-requirement score measures how closely a video '
                        f'followed a brief it is addressing; it does not mean '
                        f'anything for one that is not.')}
    return {'level': level, 'scorable': True, 'judged': True,
            'why': f'Read whole, this video is {level} for this brief.'}

# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------
# NAMED AS PLACEHOLDERS ON PURPOSE, the same way L2Config spells
# `high_threshold_PLACEHOLDER`. Nothing has established that 85 is the line
# between "approved" and "needs a revision" -- that needs Phase 8's labels.
# Until then the name is the warning, and it travels into the artifact.
BAND_THRESHOLDS_PLACEHOLDER = (
    ('APPROVED',             85.0),
    ('NEEDS_MINOR_REVISION', 70.0),
    ('NEEDS_MAJOR_REVISION', 50.0),
    ('REJECTED',              0.0),
)

BAND_ORDER = tuple(b for b, _t in BAND_THRESHOLDS_PLACEHOLDER)

# A gated video gets its OWN band, outside the ladder above.
#
# `NEEDS_MAJOR_REVISION` would be actively misleading: revision is not the
# remedy for a video about a different product. The remedy is a different
# video, or the right brief attached to this one -- and a reviewer needs to
# see which of those it is, not a number implying "nearly there".
BAND_OFF_BRIEF = 'OFF_BRIEF'

def band_for(score_0_100: float) -> str:
    """Lowest band whose threshold the score clears. Boundaries are inclusive."""
    for name, thresh in BAND_THRESHOLDS_PLACEHOLDER:
        if score_0_100 >= thresh:
            return name
    return 'REJECTED'

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ScoreConfig:
    # Show one number instead of a band only when this much of the weight was
    # actually decided. Below it, a single number hides abstentions.
    headline_coverage_min: float = 0.90
    # A dimension resting on this few units gets a "thin" marker in the report.
    # Measured in Phase 6: 26 requirements collapsed to 3 scored units, so this
    # is the normal case, not the exception.
    thin_dimension_units: int = 2
    # Round to whole points. §0.4: three decisions cannot carry a decimal.
    decimals: int = 0

    # ---- talking points are a MENU, not a checklist -------------------------
    # The Biostime brief calls itself "Format Library, Hooks and Talking
    # Points", exists "to SHOWCASE effective hooks", says creators "CAN use"
    # them, and states "we encourage creators to bring their own style and
    # personality". Its hooks (10) and CTAs (4) are already treated as pick-one
    # menus. Its 8 feature bullets were NOT: fix 16 made each one an
    # independent mandatory requirement, so they became 8 of 11 scoring units
    # and 40% of the score, and every creator lost half the Messaging
    # dimension by construction. A 40-second video cannot recite eight product
    # features, and the brief never asked it to.
    #
    # They now collapse to ONE scoring unit, scored by COVERAGE. Nothing is
    # hidden: all eight keep their own verdict, their own row in the report and
    # their own "N of 8" headline. What changes is that not reciting all eight
    # stops being seven separate failures.
    #
    # THIS NUMBER IS A PLACEHOLDER, and a worse one than the band thresholds
    # because it is fitted rather than merely unmeasured. The brief states no
    # minimum. 3 comes from the user's own statement that seven videos they
    # judge on-brief -- which cover 3-4 points each -- should score 70-100.
    # That is 7 labels. Phase 8 is where this gets an honest value; until then
    # treat the ORDERING of scores as meaningful and the absolute number as
    # provisional.
    talking_point_target_PLACEHOLDER: int = 3
    # Below target but above half of it is partial credit, not failure.
    talking_point_partial_ratio: float = 0.5
    # What REACHING the target earns. The rest is earned across the remaining
    # points, so coverage RANKS instead of clearing a bar: the first version
    # capped at the target and scored 3-of-7 the same as 6-of-7, which is
    # useless for the ordering Phase 8 has to calibrate against.
    #   covered/offered <  target/offered  ->  proportional, down to 0
    #   covered/offered >= target/offered  ->  0.7 rising to 1.0 at full
    # Also a PLACEHOLDER: the brief states no minimum and no gradient.
    talking_point_target_credit: float = 0.7
    # The target SCALES with how many the brief offers; the flat number above
    # is a FLOOR. A fixed 3 means "nearly all" for a 3-point brief and "15%"
    # for a 20-point one, and this system must serve both.
    # Measured: 2->2, 3->3, 5->3, 8->4, 12->5, 20->8.
    talking_point_target_fraction: float = 0.4

@dataclass(frozen=True)
class RecommendConfig:
    enabled: bool = True
    max_items: int = 5
    max_chars: int = 320
    # Only FAIL/PARTIAL units generate advice; passing units are context only.
    include_passing_context: int = 6
    temperature: float = 0.0

@dataclass(frozen=True)
class ReportConfig:
    # include_plotlyjs=True embeds ~3.5 MB ONCE for the whole page. 'cdn' would
    # make a compliance report need the internet to draw its own charts.
    embed_plotly: bool = True
    embed_video: bool = True
    proxy_max_mb: float = 3.0
    proxy_height: int = 480
    proxy_crf: int = 30
    figure_height: int = 520
    # Status is encoded in SYMBOL as well as colour, so the page survives
    # greyscale printing and the common forms of colour blindness.
    status_colour = {'PASS': '#1a7f37', 'PARTIAL': '#9a6700',
                     'FAIL': '#cf222e', 'UNCERTAIN': '#57606a'}
    status_symbol = {'PASS': 'circle', 'PARTIAL': 'diamond',
                     'FAIL': 'x', 'UNCERTAIN': 'square-open'}

@dataclass(frozen=True)
class Phase7Config:
    score: ScoreConfig = field(default_factory=ScoreConfig)
    recommend: RecommendConfig = field(default_factory=RecommendConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

P7 = Phase7Config()


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 45: assert 'PRIORITY_WEIGHT' in globals(), 'Run Phase 4 (§35 onward) first.'
#   line 46: assert set(PRIORITY_WEIGHT) >= {'critical', 'high', 'medium', 'low'}
#   line 96: _unmapped = set(REQUIREMENT_TYPES) - set(TYPE_TO_DIMENSION)
#   line 97: _dangling = set(TYPE_TO_DIMENSION.values()) - set(DIMENSION_KEYS)
#   line 98: assert not _unmapped, f'REQUIREMENT_TYPES not mapped to a dimension: {sorted
#   line 99: assert not _dangling, f'TYPE_TO_DIMENSION points at unknown dimensions: {sor
#   line 100: assert abs(sum(DIMENSION_WEIGHT.values()) - 1.0) < 1e-09, 'dimension weights
#   line 346: print(f'§75 Phase 7 config loaded.   SCORE {SCORE_STAGE_VERSION} / REPORT {R
#   line 348: print(f'  dimensions      : ' + ', '.join((f'{DIMENSION_LABEL[k]} {DIMENSION
#   line 350: print(f'  requirement types mapped : {len(TYPE_TO_DIMENSION)}/{len(REQUIREME
#   line 351: print(f'  bands (PLACEHOLDER, Phase 8 calibrates) : ' + ', '.join((f'{b}>={t
#   line 353: print('  UNCERTAIN has no score entry, by design -- it produces a band (§76)
