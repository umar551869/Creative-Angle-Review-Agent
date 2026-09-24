"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 62.
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
# Closed enum. Anything outside it becomes 'other' AND raises a flag.
EVENT_TYPES = (
    'scene',                      # a distinct shot / setting
    'person_speaking_to_camera',
    'product_visible',            # present in frame, no interaction
    'product_held',
    'product_opened',
    'product_applied',
    'product_used',
    'demonstration',              # a process being shown step by step
    'before_after',
    'text_overlay',               # on-screen text (OCR owns the CONTENT, this the fact)
    'cta_visual',                 # a visual call to action
    'transition',
    'other',
)

# plan.md §35: 'shown' and 'applied' are different facts about the same product.
ACTION_VERBS = (
    'shown', 'held', 'opened', 'mixed', 'applied', 'used', 'compared', 'explained',
)

# Pass 1 extracts observations, NOT verdicts. If these appear in a description the
# prompt boundary leaked and §32 fails the phase.
#
# Every entry must be UNAMBIGUOUSLY evaluative. A detector that cries wolf on
# ordinary description is worse than none: you learn to ignore §32, and a real
# leak then walks straight through. Three plausible-looking entries were cut
# after they fired on neutral sentences a product video genuinely produces:
#   'passes'    -> "a hand passes in front of the lens"
#   'adheres'   -> "the sticker adheres to the bottle"
#   'meets the' -> "where the cap meets the bottle neck"
# The compliance senses of all three are still caught, by 'requirement',
# 'the brief' and 'guidelines'.
JUDGMENT_WORDS = (
    'should', 'must ', 'compliant', 'compliance', 'non-compliant',
    'violates', 'violation', 'requirement', 'requirements',
    'guideline', 'guidelines', 'the brief', 'fails to', 'approved',
    'satisfies', 'meets the requirement', 'meets the criteria', 'does not meet',
)

class VisualEvent(BaseModel):
    """One factual observation, anchored to frames AND to seconds."""
    id: str
    type: str
    action: Optional[str] = None
    description: str = ''
    objects: list = Field(default_factory=list)
    confidence: float = 0.5
    # what the model said
    frame_start: int
    frame_end: int
    # what WE computed from the manifest -- the only timestamps anyone downstream uses
    start_seconds: float
    end_seconds: float
    frame_ids: list = Field(default_factory=list)
    # provenance / integrity
    timestamp_unreliable: bool = False
    merged_count: int = 1        # >1 means near-duplicate events were collapsed
    # every observation that went into a merged span, each with its own frames
    # and timestamps. Merging is lossless: `description` is a representative,
    # `segments` is the full record.
    segments: list = Field(default_factory=list)
    flags: list = Field(default_factory=list)

class VisualEvidence(BaseModel):
    """Everything Pass 1 produced for one video, including how it went wrong."""
    schema_version: str = VLM_STAGE_VERSION
    status: str = 'OK'          # OK | PARSE_FAILED | TRUNCATED | GENERATION_FAILED | NO_FRAMES
    video_id: str = ''
    video_hash: str = ''
    events: list = Field(default_factory=list)
    frame_table: list = Field(default_factory=list)
    flags: list = Field(default_factory=list)
    judgment_leakage: list = Field(default_factory=list)
    raw_output: str = ''        # ALWAYS kept: when accuracy looks odd, this says why
    stats: dict = Field(default_factory=dict)
    model: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 89: print(f'schemas.py loaded  --  {len(EVENT_TYPES)} event types, {len(ACTION_V
