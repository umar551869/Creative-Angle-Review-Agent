"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 6.
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
# ---------------------------------------------------------------------------
# PHASE 1 -- video preprocessing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreflightConfig:
    max_file_bytes: int = 2 * 1024**3       # 2 GB
    min_duration_s: float = 0.5
    max_duration_s: float = 600.0           # 10 min
    min_dimension: int = 64
    duration_mismatch_tolerance_s: float = 0.20
    vfr_relative_tolerance: float = 0.02    # r_frame_rate vs avg_frame_rate

@dataclass(frozen=True)
class SamplerConfig:
    # ---- Level 1: global uniform coverage -----------------------------------
    # (duration_lo, duration_hi, target_frame_count)
    duration_tiers: tuple = (
        (0.0,    10.0,  24),
        (10.0,   30.0,  40),
        (30.0,   60.0,  60),
        (60.0,  180.0,  90),
        (180.0, 1e9,   120),
    )
    # ---- Level 2: critical windows ------------------------------------------
    hook_window_s: float = 5.0
    hook_interval_s: float = 0.25
    cta_window_s: float = 5.0
    cta_interval_s: float = 0.25
    # ---- Level 3: adaptive refinement around cuts ----------------------------
    scene_refine: bool = True
    scene_settle_offset_s: float = 0.15     # sample AFTER the cut, once the shot settles
    # Rapid-cut TikToks routinely have 30-40 cuts in 30 seconds. A cap of 24 left
    # Phase 3 unable to see cuts that were never sampled in the first place; 48
    # still leaves room inside max_total_frames for the hook and CTA windows,
    # and enforce_budget() thins uniform frames first if it gets tight.
    max_scene_frames: int = 48
    # ---- Budget --------------------------------------------------------------
    max_total_frames: int = 96
    # ---- Blank frame avoidance -----------------------------------------------
    avoid_blank_frames: bool = True

@dataclass(frozen=True)
class SceneConfig:
    thumb_size: int = 64                    # scan thumbnails are 64x64 grayscale
    min_shot_duration_s: float = 0.30       # suppress double-triggers on one cut
    robust_z_threshold: float = 4.0         # cut if MAD-z of frame delta exceeds this
    min_absolute_delta: float = 6.0         # ...AND the raw delta exceeds this (0-255)
    blank_std_threshold: float = 3.0        # thumbnail std below this == blank/flat frame

@dataclass(frozen=True)
class DecodeConfig:
    jpeg_quality: int = 92
    max_long_edge: int = 1080               # cap; TikTok native is usually 1080x1920
    force_rotation_ccw: Optional[int] = None  # None = auto-detect; else 0/90/180/270

@dataclass(frozen=True)
class AudioConfig:
    sample_rate: int = 16000                # what Whisper's frontend wants
    channels: int = 1
    codec: str = 'pcm_s16le'

@dataclass(frozen=True)
class PreprocessConfig:
    preflight: PreflightConfig = field(default_factory=PreflightConfig)
    sampler:   SamplerConfig   = field(default_factory=SamplerConfig)
    scene:     SceneConfig     = field(default_factory=SceneConfig)
    decode:    DecodeConfig    = field(default_factory=DecodeConfig)
    audio:     AudioConfig     = field(default_factory=AudioConfig)

    def to_dict(self) -> dict:
        return asdict(self)

# ---------------------------------------------------------------------------
# PHASE 2 -- ASR + OCR
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ASRConfig:
    # 'auto' = faster-whisper if it imported, else transformers Whisper.
    backend: str = 'auto'               # 'auto' | 'faster_whisper' | 'transformers'

    # CTranslate2 model ids (faster-whisper path). First that loads wins.
    model_candidates: tuple = (
        'large-v3-turbo',
        'deepdml/faster-whisper-large-v3-turbo-ct2',
        'distil-large-v3',
        'medium',
        'small',
    )
    # Hugging Face model ids (transformers fallback path).
    hf_model_candidates: tuple = (
        'openai/whisper-large-v3-turbo',
        'distil-whisper/distil-large-v3',
        'openai/whisper-small',
    )
    # --- transformers-path segmentation (faster-whisper does this itself) ----
    segment_max_words: int = 14         # split a segment after this many words
    segment_gap_s: float = 0.8          # ...or after a silence this long
    language: Optional[str] = 'en'      # None = autodetect (can misfire on music intros)
    beam_size: int = 5                  # drop to 1 for a fast dev pass
    temperature: float = 0.0            # reproducibility (spec section 45)
    condition_on_previous_text: bool = False   # prevents repetition loops
    word_timestamps: bool = True        # ESSENTIAL -- "mention X within 10s" needs these

    # --- VAD: the single most valuable setting in this config ---------------
    vad_filter: bool = True
    vad_min_silence_ms: int = 500
    vad_speech_pad_ms: int = 300        # too small clips word onsets, corrupting timestamps

    # --- post-filters --------------------------------------------------------
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0
    compression_ratio_threshold: float = 2.4

    # --- brand-name biasing. Measure before trusting: initial_prompt can also
    #     cause the model to INSERT the term spuriously. -----------------------
    initial_prompt: Optional[str] = None
    brand_vocabulary: tuple = ()        # fuzzy-corrected post-hoc
    brand_match_threshold: int = 85

@dataclass(frozen=True)
class OCRConfig:
    backend: str = 'auto'               # 'auto' | 'rapidocr' | 'paddleocr' | 'tesseract'
    language: str = 'en'
    # --- space restoration ----------------------------------------------------
    # PP-OCR's default recogniser is Chinese-trained and drops spaces on Latin
    # text. This REPAIRS the text at ingest via dictionary word segmentation, so
    # everything downstream sees 'everyone talks about hair', not
    # 'everyonetalksabouthair'. The original always survives as `text_raw`.
    restore_spaces: bool = True
    restore_min_length: int = 8         # shorter runs are left alone
    restore_max_short_ratio: float = 0.4  # reject splits that shatter into 1-2 char bits
    restore_min_pieces_len: int = 3     # a split must average at least this many chars

    # Passed straight to RapidOCR(). Empty = library defaults.
    rapidocr_kwargs: tuple = ()
    tesseract_lang: str = 'eng'         # tesseract uses ISO 639-2 codes
    tesseract_psm: int = 11             # 11 = sparse text; correct for scattered overlays
    tesseract_min_upscale_edge: int = 1000   # upscale small frames -- tesseract needs pixels
    device: str = 'cpu'                 # deliberate -- see the §12.2 markdown
    min_confidence: float = 0.50        # below this: KEEP but flag low_confidence
    drop_below_confidence: float = 0.30 # below this: discard outright
    min_text_length: int = 1

    # --- which frames (plan.md 2.5) -----------------------------------------
    frame_reasons: tuple = ('hook_window', 'cta_window', 'scene_change', 'uniform')
    max_frames: Optional[int] = None    # None = all manifest frames matching the reasons

    # --- WORD merging (same row) ---------------------------------------------
    # PP-OCR's detector returns one box per text REGION. With large bold fonts it
    # splits a single line into separate words: 'CODE SAVE20' arrives as 'CODE' +
    # 'SAVE20', and no interval ever contains the whole phrase. Group words back
    # into lines BEFORE grouping lines into blocks.
    merge_words: bool = True
    word_merge_min_voverlap: float = 0.60    # vertical overlap -> same row
    word_merge_max_hgap_ratio: float = 1.50  # gap between words, as a multiple of height

    # --- LINE merging (stacked rows) -----------------------------------------
    # A three-line title card otherwise becomes three intervals with three
    # independently computed derived_from_speech flags, for one visual element.
    # CONSERVATIVE on purpose: a loose merge welds a clean caption to the
    # mirrored product text beside it, and the contaminated block then fails the
    # caption cross-check on every measure.
    merge_lines: bool = True
    line_merge_max_vgap_ratio: float = 0.7     # vertical gap, as a fraction of line height
    line_merge_min_xoverlap: float = 0.50      # horizontal overlap vs the BLOCK
    line_merge_height_ratio_min: float = 0.6   # similar font size: a title card's lines
    line_merge_height_ratio_max: float = 1.7   #   match each other; a product label does not
    line_merge_max_conf_delta: float = 0.25    # 0.9 caption text must not absorb 0.5 garbage
    line_merge_max_lines: int = 4              # a caption block, not the whole frame

    # --- near-duplicate skipping --------------------------------------------
    # Decided by COUNTING significantly-changed pixels -- not by averaging a
    # difference, over the frame OR over tiles.
    #
    # Why: a caption changing 'STEP 1' -> 'STEP 2' alters ONE GLYPH. At 1080x1920
    # with 80px text, that glyph is a handful of pixels once the frame is reduced
    # to a signature. Any average washes it out, the frame is called a duplicate,
    # OCR is skipped, and the OLD caption is written onto a frame showing the NEW
    # one -- fabricated evidence at the wrong timestamp. A tile-mean version of
    # this was calibrated on an idealised signature where text filled 6% of the
    # height; on a real frame it still missed the change.
    #
    # Counting pixels is alignment-free and scale-aware: a changed glyph yields
    # dozens of pixels well over the delta, while codec and JPEG noise -- already
    # heavily averaged away by the downscale -- yields almost none.
    skip_duplicates: bool = True
    duplicate_signature_size: int = 256      # 256, not 128: small text must survive it
    duplicate_pixel_delta: int = 15          # a pixel counts as changed above this (0-255)
    duplicate_min_changed_px: int = 6        # fewer changed pixels than this == duplicate
    # HARD CAP, independent of any threshold. However well tuned the test above is,
    # a missed change means the previous caption is written onto later frames. This
    # bounds that damage: after N consecutive skips, re-read regardless. On a fully
    # static video you still save ~1 - 1/(N+1) of the OCR cost, and no fabricated
    # text can ever persist for more than N sampled frames.
    duplicate_max_run: int = 3

    # --- platform-chrome masking (normalized fractions of w/h) --------------
    # OFF by default: correct for clean brand-supplied exports.
    apply_region_masks: bool = False
    mask_bottom_fraction: float = 0.18  # caption block, username, sound ticker
    mask_right_fraction: float = 0.15   # sidebar icons, Follow button
    mask_top_fraction: float = 0.0

@dataclass(frozen=True)
class DedupeConfig:
    # 85, not 90: 'hairshime' vs 'hairshine' (one character of OCR jitter) scores
    # 89 and would otherwise stay two separate intervals. bbox IoU is still
    # required, so this loosens text matching without loosening spatial matching.
    text_similarity_threshold: int = 85
    bbox_iou_threshold: float = 0.50      # same element, not the same word elsewhere
    # Allowed gap = N x the WIDEST spacing between sampled frames -- NOT the median.
    # The sampler is deliberately non-uniform (0.25s in the hook/CTA windows,
    # ~0.6s through the middle), so a median-based tolerance is dominated by the
    # dense windows and every frame in the sparse middle exceeds it. Measured:
    # 474 detections -> 244 intervals with the median, -> 22 with the widest.
    gap_tolerance_multiplier: float = 1.5
    max_gap_ceiling_s: float = 5.0        # never tolerate more, whatever the sampling
    # 2, not 1: a text element seen in exactly ONE sampled frame is usually
    # flicker, motion blur or a misread. Real captions persist across many frames.
    min_interval_detections: int = 2
    # ...EXCEPT a single sighting read with high confidence survives. Mid-video
    # sampling is ~0.6-1.2s apart, so a genuine caption shown for about a second
    # can be seen exactly once. Confidence separates the cases: real captions read
    # at 0.87-0.94, mirrored and garbled text at 0.50-0.76.
    single_sighting_min_confidence: float = 0.85
    # Never merge two strings whose NUMBERS differ. Measured: 'code save20' vs
    # 'code save30' scores 90.9 and '20% off' vs '30% off' scores 85.7 -- both
    # above the merge threshold, both in the same screen position. Deliberate
    # trade-off: an OCR digit misread ('2O' for '20') now SPLITS an interval
    # instead. A split loses nothing; a wrong merge loses the change.
    digit_guard: bool = True
    # Karaoke / word-by-word captions build up in place:
    #     'everyone' -> 'everyone talks' -> 'everyone talks about'
    # Merge when one text is a prefix of the other and the smaller box sits inside
    # the larger one. IoU is useless here -- the box widens as words appear.
    merge_growing_text: bool = True
    growing_containment_min: float = 0.70

@dataclass(frozen=True)
class CaptionCheckConfig:
    """Burned-in caption detection -- plan.md 2.8."""
    time_window_s: float = 1.5          # +/- around the OCR interval
    similarity_threshold: int = 85
    min_chars: int = 8                  # guards against coincidental short matches
    min_tokens: int = 2
    # --- length-matched speech windows ---------------------------------------
    # Slide a window of speech roughly the size of the OCR text across the
    # interval's lifetime and keep the best match. A card on screen for the whole
    # video would otherwise be matched against the entire transcript, and its
    # words would count as "spoken" even if said minutes apart.
    window_scale: float = 1.6
    window_slack_words: int = 4
    max_windows: int = 60
    # --- fuzzy content-word recall -------------------------------------------
    # The measure that fixes paraphrasing title cards. Measured on a real card:
    # token_set 84.5, token_sort 84.8, contains 81 -- all under 85.
    # Content-word recall: 100 (everyone/talks/hair/growth/shine all spoken).
    token_match_min: int = 80           # per-word fuzzy match (plus a stem rule)
    recall_min_content_tokens: int = 3  # on 2-word strings recall is too easy a bar

@dataclass(frozen=True)
class Phase2Config:
    asr: ASRConfig = field(default_factory=ASRConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    dedupe: DedupeConfig = field(default_factory=DedupeConfig)
    caption: CaptionCheckConfig = field(default_factory=CaptionCheckConfig)

    def to_dict(self) -> dict:
        return asdict(self)

# ---------------------------------------------------------------------------
# VERSIONS -- ONE scheme for both phases.
#
# PIPELINE_VERSION participates in EVERY cache key (see stage_key), so bumping
# it recomputes everything, transcript included. To invalidate just one stage,
# bump that stage's version instead.
# ---------------------------------------------------------------------------
PIPELINE_VERSION  = '1.0.0'

PHASE2_VERSION    = PIPELINE_VERSION    # alias: Phase 2 code reads more naturally

# ASR is untouched by the number-word fix: the transcript index is built with
# normalize_token (light, 1:1 with spoken words), NOT normalize_text. So the
# cached transcript stays valid and Whisper does not re-run.
ASR_STAGE_VERSION = '1.0.0'

# 1.2.0: compound number folding changes the norm_text stored on every detection.
OCR_STAGE_VERSION = '1.3.0'             # + readability gate (unreadable != independent)

CFG = PreprocessConfig()     # Phase 1

P2  = Phase2Config()         # Phase 2


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 305: print(f'PIPELINE_VERSION {PIPELINE_VERSION}   ASR {ASR_STAGE_VERSION}   OCR 
#   line 306: print(f'Phase 1 frame budget : {CFG.sampler.max_total_frames}')
#   line 307: print(f'Phase 2 OCR backend  : {P2.ocr.backend}   word-merge: {P2.ocr.merge_
