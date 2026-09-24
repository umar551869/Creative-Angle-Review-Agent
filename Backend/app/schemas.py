"""Request and response shapes.

The response exposes what the pipeline DECIDED, not its internal state. Every
field here exists in the notebook's §90/§91 row or in the objects those rows
read from -- the mapping is recorded in docs/04_parity_checklist.md.

The semantics the notebook is careful about are carried over deliberately:
  * `headline` may be lower than `literal_headline` -- credit is not the same
    as literal compliance.
  * `band_low`/`band_high` with `lead_with_band` is the honest answer when
    coverage is thin. A caller showing `headline` alone when `lead_with_band`
    is true is misreading the system.
  * UNCERTAIN is an abstention: it lowers `coverage`, it does not score zero.
  * `concept_fit` is a DESCRIPTION, never a score. Nothing in scoring reads it.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

JobStatus = Literal['queued', 'running', 'succeeded', 'failed', 'partial']
Phase = Literal['queued', 'ingest', 'brief', 'phase1', 'phase2', 'phase3',
                'phase5', 'phase6', 'phase7', 'done']


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    video_urls: list[str] = Field(
        ..., min_length=1,
        description='One or more video URLs (TikTok, or anything yt-dlp '
                    'supports). Each is downloaded into this job\'s inbox.')
    brief_url: Optional[str] = Field(
        None,
        description='A Google Docs URL, shared "anyone with the link can '
                    'view". Mutually exclusive with brief_text.')
    brief_text: Optional[str] = Field(
        None, description='The brief as raw text, instead of a URL.')
    force_reaudit: bool = Field(
        False,
        description='Re-run stages that already have a cached artifact. '
                    'Everything is content-addressed, so the default reuses '
                    'previous work and costs nothing.')
    compiled_brief: Optional[dict[str, Any]] = Field(
        None,
        description='A `compiled_brief` returned by an earlier job, handed '
                    'back verbatim. Use this when the server has no '
                    'persistent storage: the compiler is non-deterministic, '
                    'so a recompile measures the next video against a '
                    'DIFFERENT requirement set and the two scores stop being '
                    'comparable. Holding the contract client-side keeps them '
                    'comparable with no server state. It is verified, not '
                    'trusted -- editing the requirements invalidates the '
                    'approval digest and the request is refused.')
    recompile: bool = Field(
        False,
        description='Replace the frozen compile for this brief. The first '
                    'compile of a given brief text is frozen so that two '
                    'videos are always measured against the SAME requirement '
                    'set; a recompile is a different set, after which scores '
                    'are no longer comparable with earlier runs.')
    label: Optional[str] = Field(
        None, max_length=120, description='Free-text name for this run.')

    @field_validator('video_urls')
    @classmethod
    def _urls_look_like_urls(cls, v: list[str]) -> list[str]:
        cleaned = [u.strip() for u in v if u and u.strip()]
        bad = [u for u in cleaned if not u.lower().startswith(
            ('http://', 'https://'))]
        if bad:
            raise ValueError(
                f'not a URL: {bad[:3]}. Give the full link, e.g. '
                f'https://www.tiktok.com/@user/video/123...')
        if not cleaned:
            raise ValueError('video_urls is empty')
        return cleaned

    @field_validator('brief_text')
    @classmethod
    def _brief_present(cls, v, info):
        # Checked again in the route so the error names both fields.
        return v


class BriefCompileRequest(BaseModel):
    brief_url: Optional[str] = None
    brief_text: Optional[str] = None
    recompile: bool = Field(
        False,
        description='Replace an existing frozen compile for this brief. A '
                    'new compile is a DIFFERENT requirement set, so scores '
                    'before and after are not comparable.')


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------
class RequirementOut(BaseModel):
    requirement_id: str
    label: str = ''
    text: str = ''
    type: str = ''
    evidence_mode: str = ''
    polarity: str = 'required'
    priority: str = 'medium'
    weight: float = 1.0
    group_id: Optional[str] = None
    group_label: Optional[str] = None
    group_mode: Optional[str] = None
    time_window: Optional[dict[str, Any]] = None


class BriefOut(BaseModel):
    brief_hash: str
    origin: str = Field(description='google_doc:<id> | file:<name> | inline')
    status: str
    approved: bool
    approved_by: Optional[str] = None
    requirements: list[RequirementOut] = []
    scoring_units: int = 0
    total_weight: float = 0.0
    choice_groups: int = 0
    named_angles: list[str] = Field(
        default=[],
        description="The brief's own named creative angles, taken from a "
                    "choice group whose label reads like a set of angles.")
    needs_review: list[str] = []
    flags: list[dict[str, Any]] = []
    compile_runs: int = 0
    unstable: bool = Field(
        False,
        description='True when the consensus compile disagreed across runs. '
                    'The requirement set is the majority; the disagreement is '
                    'in flags.')


# ---------------------------------------------------------------------------
# Per-video result
# ---------------------------------------------------------------------------
class VerdictOut(BaseModel):
    requirement_id: str
    requirement_label: str = ''
    status: str = Field(description='PASS | FAIL | UNCERTAIN | NOT_APPLICABLE')
    alignment: Optional[str] = Field(
        None, description='Whether it served the ask, independent of whether '
                          'the literal instruction was followed.')
    decided_by: Optional[str] = Field(
        None, description='L1 (deterministic) | L2 (embedding) | L3 (LLM)')
    confidence: Optional[float] = None
    rationale: str = ''
    evidence_ids: list[str] = Field(
        default=[], description='Every verdict traces to evidence.')
    flags: list[str] = []
    group_id: Optional[str] = None
    group_label: Optional[str] = None


class ConceptFitOut(BaseModel):
    angle: str
    percent: float


class CreativeAngleOut(BaseModel):
    angle: Optional[str] = Field(
        None, description='What she actually made, in the model\'s words.')
    nearest_brief_concept: Optional[str] = None
    brief_concepts: list[str] = []
    named_angles: list[str] = []
    concept_fit: list[ConceptFitOut] = Field(
        default=[],
        description='Percentage split across the brief\'s NAMED angles, '
                    'validated against that closed list. A DESCRIPTION, not a '
                    'score -- scoring never reads it.')
    dominant_angle: Optional[str] = Field(
        None,
        description='The named angle with the largest share -- "which angle '
                    'is this video". None when the split is empty.')
    angles_source: Optional[str] = Field(
        None,
        description='Where named_angles came from: "document" (the brief\'s '
                    'own sub-headings, the correct path), "group_labels" (the '
                    'fallback, used only when the brief has no angle '
                    'sub-headings), or "none". Anything but "document" on a '
                    'brief that names its angles means a stale cached audit.')
    flags: list[str] = []


class ModalityHealthOut(BaseModel):
    ran: Optional[bool] = None
    absent: Optional[bool] = None
    degraded: Optional[bool] = None
    reason: Optional[str] = None


class ScoreOut(BaseModel):
    headline: Optional[float] = Field(
        None, description='The credited score. May be BELOW literal_headline: '
                          'compliance is not achievement.')
    literal_headline: Optional[float] = Field(
        None, description='Literal instruction-following, before credit.')
    status_band: Optional[str] = None
    coverage: Optional[float] = Field(
        None, description='Share of the weight that was actually DECIDED. '
                          'UNCERTAIN lowers this rather than scoring zero.')
    scoring_units: Optional[int] = None
    credited_in_substance: Optional[int] = None
    band_low: Optional[float] = None
    band_high: Optional[float] = None
    band_basis: Optional[str] = None
    lead_with_band: bool = Field(
        False,
        description='When true, the BAND is the answer and the headline alone '
                    'overstates what the evidence supports.')


class VideoResultOut(BaseModel):
    video_id: str
    video_hash: str
    source: str = Field(description='The filename, which is the TikTok id.')
    url: Optional[str] = None
    status: str = Field(description='ok | module_failed | <error>')
    error: Optional[str] = None
    phase: Optional[str] = Field(
        None,
        description='Which phase this video failed in, when it failed. '
                    '"phase3" is the vision pass, "phase5-7" the audit and '
                    'score.')

    score: ScoreOut = ScoreOut()
    standing: Optional[str] = None
    creative_angle: CreativeAngleOut = CreativeAngleOut()
    verdicts: list[VerdictOut] = []
    verdict_mix: dict[str, int] = {}
    chosen_options: dict[str, Any] = Field(
        default={},
        description='Which item off each MENU she took, per choice group.')
    talking_points_covered: Optional[int] = None
    talking_points_total: Optional[int] = None

    notes: list[str] = Field(
        default=[],
        description='Why a number needs explaining. A score of 0 with no '
                    'standing is three different situations wearing one face '
                    '-- no speech to judge, a failed model call, or a video '
                    'that genuinely did none of it. When status is '
                    '"module_failed" this says which, and a UI should show it '
                    'instead of the score.')
    duration_s: Optional[float] = None
    evidence_records: Optional[int] = None
    modality_health: dict[str, ModalityHealthOut] = {}
    can_fail_on: dict[str, bool] = Field(
        default={},
        description='Per modality: may an ABSENCE be asserted? False means '
                    'requirements in that mode become UNCERTAIN, not FAIL.')
    visual_missing: bool = False
    visual_stale: bool = False

    report_html_url: Optional[str] = None
    report_json_url: Optional[str] = None
    recommendations: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------
class PhaseTiming(BaseModel):
    phase: str
    seconds: float
    detail: Optional[str] = None


class JobOut(BaseModel):
    job_id: str
    status: JobStatus
    phase: Phase = 'queued'
    label: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_s: Optional[float] = None

    requested_videos: int = 0
    downloaded_videos: int = 0
    completed_videos: int = 0

    brief: Optional[BriefOut] = None
    compiled_brief: Optional[dict[str, Any]] = Field(
        None,
        description='The full compiled contract this job used. Keep it and '
                    'pass it back as `compiled_brief` on later jobs to get '
                    'identical, comparable scoring with no server-side '
                    'storage. Only returned when the server is running in '
                    'ephemeral mode, since that is the only time you need it.')
    results: list[VideoResultOut] = []
    angle_distribution: list[dict[str, Any]] = Field(
        default=[],
        description='Across this job: how many videos landed on each of the '
                    "brief's named angles. Only meaningful across a batch.")
    timings: list[PhaseTiming] = []
    warnings: list[str] = []
    error: Optional[str] = None


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus
    poll: str
