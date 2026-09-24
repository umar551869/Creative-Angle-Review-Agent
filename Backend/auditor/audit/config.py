"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 120.
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
# Imported here rather than relied on from an earlier cell. Phase 2 already
# imports rapidfuzz at module level, so this is a no-op in the full notebook --
# but a phase that silently depends on a name defined 60 cells earlier breaks
# the moment anyone runs it on its own, and the failure reads as a Phase 6 bug.
from collections import Counter

from dataclasses import replace

try:
    from rapidfuzz import fuzz
except ImportError:                               # pragma: no cover
    try_install('rapidfuzz', 'rapidfuzz')
    from rapidfuzz import fuzz

# 1.2.0  + l1_figure_fidelity: "any figure you state must match the brief" is
#          checked as a contradiction against the approved figures, instead of
#          being handed to l1_forbidden, which searched for those approved
#          figures as though they were banned words.
# 1.3.0  + inside a choice group, L1 requires a PHRASE match: a single-word
#          hint is a ranking signal and cannot select one option from twelve
# 1.4.0  + examined_ids records the candidates the DECIDING layer was shown.
#          L3 sees a batch truncated to max_candidates_per_requirement, so
#          filling it from the full retrieval named records the adjudicator was
#          never given (measured: candidates_considered=8, examined_ids=10).
# 1.6.0  + a PASS earned by ABSENCE (no forbidden content found, no
#          contradicting figure stated) no longer carries alignment `exact`.
#          It carried 1.0 into the mean for a video that never went near the
#          subject -- compliance is real, but it is not achievement.
#        + l1_timing may no longer PASS on evidence that merely EXISTS before
#          the deadline. Timing rules a requirement out, never in: the record
#          that satisfies the deadline must also match the requirement.
# 1.5.0  + a term ending in punctuation ('27%') can match at all: the closing
#          \b could never hold after a non-word character.
#        + a record shorter than the phrase can no longer "match" it.
#          partial_ratio slides the shorter string over the longer, so short
#          OCR fragments were scoring 100 against long hook phrases.
# 1.7.0  + a choice group's winner is decided by the brief's own ordering
#          instead of the model's self-reported confidence, so the hook the
#          report names is the same on every run
# 1.8.0  + a FAIL whose alignment says the ask WAS met in the creator's own
#          words is promoted to PASS (strong/exact) or PARTIAL, in code, with
#          the literal finding preserved on the verdict. Forbidden rules and
#          FAILs from positive evidence are never promoted.
# 1.9.0  + a figure-fidelity rule is judged against the BRIEF'S figures, not
#          against its own match_hints, which are one compile's sample of them
VERDICT_STAGE_VERSION = '1.22.0'  # + uncertain_rate over scoring units, not all requirements

ADJUDICATE_PROMPT_VERSION = 'p6_adjudicate_v1'

HOOK_PROMPT_VERSION = 'p6_hook_v1'

CLAIMS_PROMPT_VERSION = 'p6_claims_v1'

# ---------------------------------------------------------------------------
# Status semantics -- plan.md §6.2
# ---------------------------------------------------------------------------
# These five are the whole contract with a reader. Adding a sixth is a product
# decision, not a coding convenience.
VERDICT_STATUSES = (
    'PASS',            # evidence satisfies it, and the evidence is cited
    'PARTIAL',         # satisfied weakly, late, or in one of two required modalities
    'FAIL',            # evidence contradicts, OR required evidence is confidently absent
    'UNCERTAIN',       # insufficient or degraded evidence -- NOT "hard case"
    'NOT_APPLICABLE',  # does not apply to this video (an unselected one_of option)
)

# INCONCLUSIVE is deliberately NOT in that tuple. L1 and L2 return it to mean
# "escalate"; it is a routing signal inside the ladder. A verdict carrying it
# would be telling a user that our cheap check did not fire, which is not a
# fact about their video.
ROUTING_ONLY = ('INCONCLUSIVE',)

EVAL_LAYERS = ('L1', 'L2', 'L3', 'gate')   # 'gate' = decided by can_fail_on alone

# Where a verdict's confidence number came from. Same discipline as Phase 5's
# confidence_kind: never average an LLM's self-report against a fuzzy match
# ratio, because they are not the same quantity.
VERDICT_CONFIDENCE_KINDS = ('derived', 'llm_self_report', 'none')

# ---- ALIGNMENT: how close she got, independent of whether she matched -------
#
# A brief that lists 12 hooks is not demanding one of those 12 sentences. It is
# describing the KIND of opening it wants. A creator who writes her own hook in
# that spirit has done what the brief asked; marking her FAIL for not copying a
# line is the single most unfair thing this system could do.
#
# So the strict verdict stays -- it is what makes a FAIL citable and arguable --
# and alignment is added beside it, answering a different question:
#
#     verdict    did she do the thing the requirement literally states?
#     alignment  how close is what she DID to what the requirement was FOR?
#
# ORDINAL WITH WRITTEN ANCHORS, never a number from the model. Same rule as hook
# strength (spec §33): a model asked for a number invents a scale, and two runs
# then disagree by 0.15 for no reason anyone can name. The numeric weights live
# HERE, in code, so Phase 7 scores deterministically.
ALIGNMENT_LEVELS = ('none', 'tangential', 'partial', 'strong', 'exact')

ALIGNMENT_WEIGHTS = {'exact': 1.0, 'strong': 0.85, 'partial': 0.55,
                     'tangential': 0.25, 'none': 0.0}

ALIGNMENT_ANCHORS = {
    'exact': 'the brief\'s own wording, or a trivial variation of it',
    'strong': 'different words, same ask and same intent -- the creator wrote '
              'her own version of what the brief described',
    'partial': 'on the brief\'s subject and partly does the job, but misses '
               'part of what was asked',
    'tangential': 'about the product or topic, but not what THIS requirement '
                  'was for',
    'none': 'unrelated to the requirement, or absent altogether',
}

def alignment_rank(a) -> int:
    """Higher is closer to the brief. Unjudged ranks BELOW 'none' deliberately:
    'none' means looked-at-and-unrelated, None means nobody looked."""
    return ALIGNMENT_LEVELS.index(a) if a in ALIGNMENT_LEVELS else -1

def alignment_weight(a) -> float:
    """The number Phase 7 scores. Defined in code, never by a model."""
    return ALIGNMENT_WEIGHTS.get(a, 0.0)

@dataclass(frozen=True)
class RetrievalConfig:
    """How candidate evidence is found for one requirement."""
    top_k: int = 10                   # retrieve GENEROUSLY -- the LLM is the filter
    # Requirement text is short and evidence records are short. partial_ratio
    # compares the shorter string against windows of the longer, which is what
    # we want when a 4-word hint sits inside a 30-word utterance.
    hint_match_min: int = 85          # rapidfuzz partial_ratio, plan.md §6.1
    # A window is widened by each record's OWN tolerance before testing overlap,
    # so a record whose bound is uncertain is still considered. Phase 5 measured
    # those tolerances; ignoring them here would throw that work away.
    use_record_tolerance: bool = True
    # Metadata records (cut_count, duration) are evidence ABOUT the video, not
    # IN it. They answer questions like "is the cut density high" and should not
    # crowd out real observations in the top-k.
    include_metadata: bool = False
    # No single modality may hold more than this share of the candidate slots.
    # Measured on a real video: 165 OCR records against 8 speech ones, so
    # every slot was packaging text and what the creator SAID was never
    # offered. 0.6 of 10 leaves at least four slots for another modality,
    # which was enough to surface it at rank 4.
    max_modality_share: float = 0.6

@dataclass(frozen=True)
class L1Config:
    """The deterministic layer. Free, and it should answer most requirements."""
    fuzzy_min: int = 85               # phrase match threshold, rapidfuzz
    # A deadline comparison is only decidable if the record's tolerance does not
    # straddle it. 0.0 means "any overlap with the deadline is a straddle" --
    # the strictest reading, and the right default when a wrong FAIL is costly.
    deadline_straddle_slack: float = 0.0
    forbidden_fuzzy_min: int = 90     # higher bar: a false forbidden hit is loud
    min_hint_len: int = 3             # a 2-character hint matches everything

@dataclass(frozen=True)
class L2Config:
    """Embeddings. Cheap, CPU-only, and OFF until a model is actually present."""
    enabled: bool = True
    model_id: str = 'BAAI/bge-small-en-v1.5'
    # CPU on purpose. Qwen3-VL is the binding constraint on this machine and a
    # 133 MB retrieval model must never compete with it for VRAM.
    device: str = 'cpu'
    # BGE is asymmetric: the instruction goes on the QUERY only. Putting it on
    # both sides, or neither, degrades retrieval silently -- there is no error,
    # the numbers are just quietly worse.
    query_prefix: str = 'Represent this sentence for searching relevant passages: '
    passage_prefix: str = ''
    # TWO thresholds, not one. A single cut-off forces a coin-flip on exactly
    # the cases that deserve L3.
    #
    # MEASURED on 28 real requirements from two real briefs against real
    # evidence: every best-match cosine landed between 0.461 and 0.688, mean
    # 0.556. Both thresholds sit outside that range, so 100% escalate and L2
    # currently decides nothing.
    #
    # Do NOT just lower `high` to 0.60 to make the number look better. In the
    # same measurement the single HIGHEST score, 0.688, was a wrong match
    # ("do your favourite hairstyle to camera" against "capsules a day is all
    # you need"), while a correct one ("mention hydration and barrier support"
    # against "protective barrier. AURELTA") scored 0.632. The ranking does not
    # separate right from wrong on this data, so moving the line would trade
    # "escalates everything" for "passes things wrongly", which is worse.
    #
    # The compression has a visible cause: evidence records are individually
    # tiny OCR fragments ("more", "shine to your hair"), and bge-small scores
    # any two short English strings about hair around 0.5. Fixing that is a
    # retrieval change -- give L2 more context per passage -- not a threshold
    # change, and it belongs with the Phase 8 calibration that will have labels
    # to check it against.
    #
    # Escalating is not the disaster the percentage suggests: L3 batches up to
    # max_requirements_per_call, so 21 requirements cost 2 calls, not 21.
    high_threshold_PLACEHOLDER: float = 0.72   # >= this -> PASS
    low_threshold_PLACEHOLDER: float = 0.35    # <= this -> FAIL (if allowed)
    batch_size: int = 32
    max_chars: int = 512

@dataclass(frozen=True)
class L3Config:
    """LLM adjudication. Text only -- Phase 3 already looked at the pixels."""
    enabled: bool = True
    # Every escalated requirement for one video in ONE call. Per-requirement
    # calls cost ~20x for no accuracy gain.
    batch: bool = True
    max_requirements_per_call: int = 12
    max_candidates_per_requirement: int = 8
    # A model that cites an id it was not given is rejected once and retried.
    # Twice would be paying for the same hallucination.
    max_repair_retries: int = 1
    temperature: float = 0.0
    max_new_tokens: int = 4096

@dataclass(frozen=True)
class HookConfig:
    """spec §33. Presence and strength are SEPARATE questions."""
    window_seconds: float = 3.0
    max_window_seconds: float = 5.0
    speech_onset_good: float = 1.0    # speech starting later than this is a weak signal
    dense_cut_count: int = 2          # cuts inside the window that count as "dense"
    use_llm: bool = True
    # Strength is ordinal with written anchors, defined in the prompt. A bare
    # "rate the strength" produces noise; never emit a numeric score from a model.
    strengths: tuple = ('weak', 'medium', 'strong')

@dataclass(frozen=True)
class ClaimsConfig:
    """
    spec §38. OFF by default -- advertising-policy screening is not the current
    goal, and a module nobody is acting on is noise in every report it appears in.

    This is NOT the same thing as a `forbidden` requirement in a brief. If a
    brief says "do not make medical claims", that is brief compliance and stays
    switched on: it runs through l1_forbidden like any other requirement. What
    is off here is the STANDALONE policy scan that runs whether or not the brief
    asked for it.

    Turn it back on with:
        P6 = replace(P6, claims=replace(P6.claims, enabled=True))

    Kept tuned for RECALL for when it comes back: a missed claim is a far more
    expensive error than a flag a human dismisses in two seconds.
    """
    enabled: bool = False
    use_llm: bool = True
    context_chars: int = 240
    # Deliberately broad. A false positive costs a human two seconds; a false
    # negative costs a regulatory problem.
    gazetteer: tuple = (
        'cure', 'cures', 'cured', 'heal', 'heals', 'healing', 'treat', 'treats',
        'treatment', 'eliminate', 'eliminates', 'prevent', 'prevents', 'reverse',
        'reverses', 'clinically proven', 'clinically-proven', 'dermatologist approved',
        'dermatologist-approved', 'dermatologist recommended', 'fda', 'fda approved',
        'guaranteed', 'guarantee', 'permanent', 'permanently', '100%', 'overnight',
        'instantly', 'miracle', 'medical grade', 'medical-grade', 'prescription',
        'anti-aging', 'detox', 'detoxify', 'toxins', 'chemical free', 'chemical-free',
        'no side effects', 'risk free', 'risk-free', 'scientifically proven',
    )
    # 'unclassified' is a real answer: the wording matched, but no model judged
    # it. Reporting such a candidate as 'unsupported_outcome' would assert a
    # class nobody determined -- the same overclaiming the rest of the system
    # spends its effort avoiding.
    classes: tuple = ('medical_claim', 'cure_claim', 'guarantee_claim',
                      'unsupported_outcome', 'prohibited_wording', 'not_a_claim',
                      'unclassified')
    risk_levels: tuple = ('low', 'medium', 'high')
    DISCLAIMER = ('Automated detection of defined claim classes. NOT legal advice. '
                  'Every flag requires human review, and absence of a flag is not '
                  'evidence of compliance.')

@dataclass(frozen=True)
class Phase6Config:
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    l1: L1Config = field(default_factory=L1Config)
    l2: L2Config = field(default_factory=L2Config)
    l3: L3Config = field(default_factory=L3Config)
    hook: HookConfig = field(default_factory=HookConfig)
    claims: ClaimsConfig = field(default_factory=ClaimsConfig)

P6 = Phase6Config()

@dataclass
class Verdict:
    """
    One requirement, one video, one answer.

    `evidence_ids` is the load-bearing field: a status without citations cannot
    be checked by a human, and an unverifiable verdict is an opinion.
    """
    requirement_id: str
    status: str                       # VERDICT_STATUSES
    evidence_ids: list = field(default_factory=list)
    reason: str = ''
    layer: str = 'L1'                 # EVAL_LAYERS -- which layer decided it
    confidence: Optional[float] = None
    confidence_kind: str = 'none'     # VERDICT_CONFIDENCE_KINDS
    # How CLOSE the creator got, whatever the status says. None means nobody
    # judged it, which is NOT the same as 'none' -- that means judged and found
    # unrelated. Phase 7 must treat the two differently.
    alignment: Optional[str] = None   # ALIGNMENT_LEVELS
    alignment_reason: str = ''
    # Everything below is for auditing the evaluator itself, not for the reader.
    # What the verdict RELIES on is evidence_ids. What it was EVALUATED
    # AGAINST is this. Keeping them apart matters: a live FAIL read "the OCR
    # evidence only captures day labels like TUE and SA" and cited nothing, so
    # nobody could tell which OCR records it meant. Auto-filling evidence_ids
    # would have fixed the traceability by destroying the meaning of a citation.
    examined_ids: list = field(default_factory=list)
    requirement_label: str = ''
    evidence_mode: str = ''
    priority: str = 'medium'
    weight: float = 1.0
    group: Optional[str] = None
    group_mode: str = 'all_of'
    group_label: str = ''             # the human name of the choice, for the reason
    # The brief's own ordering, carried so a tie between equally-good options in
    # a choice group can be broken deterministically. See _resolve_groups.
    ordinal: int = 0
    candidates_considered: int = 0
    escalated_from: list = field(default_factory=list)
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['evidence_ids'] = list(self.evidence_ids)
        return d

def _blank_verdict(rd: dict, status: str, reason: str, layer: str = 'gate',
                   **kw) -> Verdict:
    """A verdict carrying the requirement's identity, however it was decided."""
    return Verdict(
        requirement_id=rd.get('id', ''),
        status=status, reason=reason, layer=layer,
        requirement_label=rd.get('label') or rd.get('requirement', '')[:60],
        evidence_mode=rd.get('evidence_mode', 'any'),
        priority=rd.get('priority', 'medium'),
        weight=float(rd.get('weight', 1.0) or 1.0),
        group=rd.get('group'), group_mode=rd.get('group_mode', 'all_of'),
        group_label=rd.get('group_label', '') or '',
        ordinal=int(rd.get('ordinal') or 0),
        **kw)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 353: print('§63 Phase 6 config loaded.')
#   line 354: print(f"  statuses     : {', '.join(VERDICT_STATUSES)}")
#   line 355: print(f"  layers       : {', '.join(EVAL_LAYERS)}")
#   line 356: print(f'  L2 model     : {P6.l2.model_id} on {P6.l2.device}')
#   line 357: print(f'  thresholds   : high={P6.l2.high_threshold_PLACEHOLDER} low={P6.l2.
#   line 360: print(f'  claims terms : {len(P6.claims.gazetteer)} in the gazetteer')
