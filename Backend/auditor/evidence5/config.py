"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 109.
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
import re, json, time, math, hashlib, bisect

from dataclasses import dataclass, field, asdict

from typing import Optional

# 1.6.0  + merging a linked record repairs the far end of the link, so
#          'every link is mutual' holds after merge_visual_intervals
EVIDENCE_STAGE_VERSION = '1.7.0'   # + speech `absent` vs `degraded` in modality_health

MODALITIES = ('speech', 'ocr', 'visual', 'metadata')

# The visual types are Phase 3's closed enum, REUSED rather than retyped. A
# second hand-written copy is a second thing to forget to update, and the two
# would drift silently -- an event type that exists in Phase 3 and not here
# would be normalised to 'other' and lose its meaning on the way through.
EVIDENCE_TYPES = tuple(sorted(set(
    ('utterance', 'on_screen_text', 'scene_cut', 'video_meta')
    + tuple(globals().get('EVENT_TYPES', ()))
)))

# Why a record's confidence number means what it means. plan.md §5.4: these are
# NOT comparable, so the kind travels with the number and nothing downstream can
# average an OCR recognition score with a Whisper log-probability by accident.
CONFIDENCE_KINDS = (
    'ocr_recognition',   # calibrated recogniser score, roughly a probability
    'asr_logprob',       # mean token log-probability -- NEGATIVE, not a probability
    'vlm_self_report',   # a model grading itself: a weak ordinal signal at best
    'derived',           # computed by us (e.g. a merged interval)
    'none',              # metadata: no meaningful confidence exists
)

# Which evidence_mode values a record can legitimately satisfy, by OCR
# independence. Computed HERE so the policy lives in one place instead of being
# re-derived (and eventually re-derived differently) in Phases 6 and 7.
#
#   confirmed_independent  compared against speech and genuinely differs
#   unknown                too short to compare -- real text, unverified source
#   derived_from_speech    a burned-in caption echoing the voiceover
#   unreadable             OCR returned something that is not language
INDEPENDENCE_MODES = {
    'confirmed_independent': ('ocr_only', 'speech_or_text', 'any'),
    'unknown':               ('speech_or_text', 'any'),
    'derived_from_speech':   ('speech_or_text', 'any'),
    'unreadable':            (),
}

SPEECH_MODES = ('speech_only', 'speech_or_text', 'visual_and_speech', 'any')

VISUAL_MODES = ('visual_only', 'visual_and_speech', 'any')

METADATA_MODES = ('any',)

@dataclass(frozen=True)
class EvidenceConfig:
    # --- cross-modal linking -------------------------------------------------
    link_overlap_seconds: float = 0.50   # a VLM text_overlay and an OCR interval
    link_text_min_ratio: int = 70        # ...must also look like the same string
    # --- visual interval merging ---------------------------------------------
    merge_gap_seconds: float = 1.00      # same type, closer than this -> one interval
    # --- timestamp tolerance -------------------------------------------------
    word_tolerance_seconds: float = 0.15    # measured in Phase 2; never tighter
    min_tolerance_seconds: float = 0.05
    max_tolerance_seconds: float = 5.00     # a clamped/unreliable bound
    unreliable_tolerance_seconds: float = 2.00
    # --- coverage ------------------------------------------------------------
    coverage_bin_seconds: float = 1.00
    # --- health thresholds ---------------------------------------------------
    thin_speech_words: int = 15          # below this a speech_only verdict is weak
    # "Nothing was said" vs "we could not hear it". A music-only video is a
    # normal TikTok format, not a broken one: the creator communicates through
    # captions, and "she never said the CTA" is then a FACT, not an
    # uncertainty. Speech counts as ABSENT only when BOTH hold -- almost no
    # voiced time AND almost no words -- because either alone is ambiguous:
    # a 60s video with 5s of speech has a low ratio and plenty of words.
    # PLACEHOLDER until Phase 8 calibration, like every other threshold here.
    absent_speech_ratio_PLACEHOLDER: float = 0.10
    absent_speech_max_words: int = 3
    degraded_frame_ratio: float = 0.60   # frames_sent / frames_planned

@dataclass(frozen=True)
class Phase5Config:
    evidence: EvidenceConfig = field(default_factory=EvidenceConfig)

P5 = Phase5Config()

@dataclass
class EvidenceRecord:
    """One observation, from one modality, on the video's timeline."""
    id: str                       # content-derived -- stable across recomputes
    modality: str                 # MODALITIES
    type: str                     # EVIDENCE_TYPES
    start_seconds: float
    end_seconds: float
    description: str = ''

    # --- confidence: never comparable across modalities ---------------------
    confidence: Optional[float] = None
    confidence_kind: str = 'none'

    # --- how precise are these timestamps, in seconds -----------------------
    # Both ends, separately. Sampling is deliberately non-uniform, so a record
    # that starts in the dense hook window and ends in the sparse middle has a
    # far less precise END than START -- one number would understate the bound
    # that a "must end within the last 5 s" check actually leans on.
    # time_tolerance_seconds is the worst of the two, for callers that want one.
    start_tolerance_seconds: float = 0.0
    end_tolerance_seconds: float = 0.0
    time_tolerance_seconds: float = 0.0
    is_approximate_ts: bool = False
    timestamp_unreliable: bool = False

    # --- what this record can be used to prove ------------------------------
    satisfies_modes: tuple = ()

    # --- text ----------------------------------------------------------------
    raw_text: str = ''
    norm_text: str = ''
    bbox: Optional[list] = None
    independence: str = ''        # OCR only
    # Word timings live ON the record, not in a module-level side table. A
    # global gets wiped by the next video and is empty entirely on a cache hit,
    # so the word data would silently vanish exactly when the artifact is reused
    # -- which is most of the time.
    words: list = field(default_factory=list)

    # --- provenance ----------------------------------------------------------
    source: str = ''              # engine / model id
    source_stage_key: str = ''    # the artifact this came out of
    source_id: str = ''           # its id THERE (ocr_003, vis_001, seg 2)
    frame_ids: list = field(default_factory=list)

    # --- relationships -------------------------------------------------------
    linked_ids: list = field(default_factory=list)
    merged_from: list = field(default_factory=list)
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['satisfies_modes'] = list(self.satisfies_modes)
        return d

    def duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def overlaps(self, t0: float, t1: float, slack: float = 0.0) -> bool:
        """
        Does this record fall in [t0, t1]?

        Each end is widened by ITS OWN tolerance, not by one shared number --
        that is the point of tracking them separately.
        """
        lo = self.start_seconds - (self.start_tolerance_seconds
                                   or self.time_tolerance_seconds) - slack
        hi = self.end_seconds + (self.end_tolerance_seconds
                                 or self.time_tolerance_seconds) + slack
        return lo <= t1 and hi >= t0

    def can_satisfy(self, evidence_mode: str) -> bool:
        return evidence_mode in self.satisfies_modes

def evidence_id(modality: str, type_: str, start: float, text: str) -> str:
    """
    Content-derived, so a recompute does not renumber.

    Phase 6 results cite evidence ids. Positional ids (ev_001, ev_002) shift the
    moment an upstream stage emits one more record, and every cached result then
    cites the wrong thing -- while still validating, because the ids still exist.
    """
    basis = f'{modality}|{type_}|{start:.2f}|{re.sub(r"[^a-z0-9 ]", "", (text or "").lower())[:60]}'
    return 'ev_' + hashlib.sha256(basis.encode('utf-8')).hexdigest()[:10]


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 180: print('§52 Phase 5 schema loaded.')
#   line 181: print(f'  stage version      : {EVIDENCE_STAGE_VERSION}')
#   line 182: print(f"  modalities         : {', '.join(MODALITIES)}")
#   line 183: print(f'  evidence types     : {len(EVIDENCE_TYPES)}  (visual types reused f
#   line 184: print(f"  confidence kinds   : {', '.join(CONFIDENCE_KINDS)}")
#   line 185: print(f'  record fields      : {len(EvidenceRecord.__dataclass_fields__)}')
