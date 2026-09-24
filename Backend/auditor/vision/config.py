"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 61.
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
# ============================================================================
# auditor/config.py   (Phase 3)
# ============================================================================
import inspect        # used by §28b to assert the resolver takes no VRAM input

@dataclass(frozen=True)
class VisionConfig:
    # --- model selection ------------------------------------------------------
    # None = choose automatically from available VRAM (see §26). Set explicitly to
    # pin a model for a benchmark run, e.g. 'Qwen/Qwen3-VL-4B-Instruct'.
    model_id: Optional[str] = None
    quantization: Optional[str] = None        # None = auto | 'none' | '4bit'
    revision: Optional[str] = None            # pin a commit sha for reproducibility
    model_candidates: tuple = (
        'Qwen/Qwen3-VL-4B-Instruct',
        'Qwen/Qwen3-VL-8B-Instruct',
        'Qwen/Qwen2.5-VL-3B-Instruct',        # stand-in if Qwen3-VL is unavailable
    )
    attn_implementation: str = 'sdpa'         # NEVER flash_attention_2 on sm_75

    # --- who describes the frames --------------------------------------------
    # 'gemini' sends the sampled frames to the hosted model; 'local' runs Qwen on
    # this machine; 'auto' prefers hosted when a key is present and falls back.
    #
    # This is part of the CACHE KEY. The same video described by two different
    # models is two different artifacts and they must never collide -- that is
    # the whole reason the resolved model was put into the key in 1.11.0.
    provider: str = 'gemini'
    # See GeminiVLMBackend.DEFAULT_MODELS for why this is one model, not a
    # ladder: gemini_models[0] IS the cache key, so a fallback would file the
    # artifact under a model that never ran.
    gemini_models: tuple = ('gemini-flash-lite-latest',)

    # --- frame budget ---------------------------------------------------------
    # These are CEILINGS and FLOORS, not the value used. resolve_vision_config()
    # derives the actual budget per video, because a fixed frame count cannot be
    # right for both a 7-second hook clip and a 3-minute tutorial: 24 frames over
    # 3 minutes is one frame every 7.5s, and whole events fall between them.
    auto_budget: bool = True                  # False pins the values below (Phase 9 ablations)
    seconds_per_frame: float = 1.5            # target temporal density
    # Duration alone is not enough. A 30s talking head and a 30s video with 40
    # hard cuts need very different budgets: at one frame per 1.5s the rapid-cut
    # edit gets 20 frames for 40 scenes and most cuts are never seen at all.
    # Scene count comes from the manifest, so this stays deterministic.
    frames_per_scene: float = 1.2
    min_frames: int = 12                      # below this, short videos lose the hook
    max_frames: int = 24                      # used when auto_budget is off
    max_frames_cap: int = 48                  # the working ceiling; raise it deliberately
    # A second, ABSOLUTE ceiling. Inference time grows linearly with frames:
    # 24 frames took ~100s on a T4, so 128 would be roughly nine minutes a video.
    max_frames_hard_cap: int = 128

    # FLOORS for the two compliance-critical windows. There is deliberately no
    # quota_scene or quota_uniform: the remainder is split in PROPORTION to what
    # the manifest actually holds, so a rapid-cut video spends its budget on cuts
    # and a static one does not. A fixed 15% scene quota gave a 40-cut TikTok
    # three frames to cover forty cuts. Dead fields were removed rather than left
    # to imply a control that no longer exists -- and they sat in the cache key,
    # so changing one would have invalidated evidence while changing nothing.
    quota_hook: float = 0.30
    quota_cta: float = 0.25
    # ...and a CEILING on those floors. As bare fractions of a growing budget
    # they starve the middle of the video: on a 30s/40-cut clip the budget is 48
    # frames and the two quotas claim 26 of them for ten seconds of footage,
    # leaving 22 for the other twenty seconds and ~27 shots. Measured shot
    # coverage was 75%; capping the windows at what a 5s window actually needs,
    # and spending the remainder shot-by-shot, took it to 93%.
    window_frame_interval: float = 0.6   # how densely a critical window needs sampling
    min_window_frames: int = 3           # never fewer than this, however small the budget

    # --- vision token budget --------------------------------------------------
    # ~28x28 source pixels per vision token. 448*448 = 200704 -> ~256 tokens/frame,
    # and 316*316 = 100352 -> ~128.
    #
    # 200704 is a budget this GPU has never once honoured. Both real videos OOMed
    # at it and the ladder landed on 100352: the 84s one after dropping to 12 of
    # 48 frames, the 27s one at its full 19. Asking for it costs a guaranteed
    # failed generation, and -- because the OOM raises DEGRADED_BUDGET -- marks
    # visual degraded, which forbids Phase 6 from ever FAILing a visual
    # requirement on evidence that was actually fine.
    #
    # So ask for what the hardware delivers. The evidence is unchanged (100352 is
    # exactly what ran); what changes is that it is now the INTENDED budget rather
    # than a fallback, and the frames saved go to coverage instead: an 84s video
    # fits its full 48 frames at ~6100 tokens, so the sampling gap -- and every
    # visual tolerance with it -- drops from ~5.0s to ~1.8s.
    #
    # This is the ladder's own priority, applied one level up: resolution is
    # given up BEFORE coverage, because for event detection knowing WHEN
    # something happened matters more than fine spatial detail, and Phase 2
    # already read the on-screen text at native resolution.
    #
    # Raise it back on a bigger GPU -- a deliberate, reproducible choice. It sits
    # in the cache key, so changing it re-runs Phase 3 for every video.
    max_pixels: int = 100352
    # 25088 px is ~158x158, or ~119x211 on a 9:16 frame: 32 vision tokens.
    #
    # This was 50176 (224*224), which is EXACTLY max_pixels * 0.5 -- so p_quarter
    # collapsed onto p_half, every quarter rung had identical cost to its half
    # rung, and the strict-descent filter pruned all of them. The bottom of the
    # ladder has never existed. The consequence, measured on an 84s video: when
    # 48 frames at half resolution OOMed, the ladder had nowhere to go but drop
    # to 33 frames -- which costs MORE tokens (2112) than 48 frames at quarter
    # resolution (1536) and throws away 15 frames of coverage to do it.
    #
    # Going this low is safe for what this stage is for: OCR already read every
    # on-screen word at native resolution in Phase 2, so what the VLM needs from
    # a frame is WHEN something happened, and coverage is what modality_health
    # and can_fail_on depend on.
    min_pixels: int = 25088
    # These drive an ADVISORY only -- what this GPU can probably afford right
    # now. They must never influence the resolved budget, because that would put
    # transient allocator state into the cache key. Calibrated on observed
    # behaviour: 5816 tokens OOMed with 5.8 GB free and ran fine with 11.7 GB,
    # so usable ~= (free_gb - safety) * tokens_per_gb predicts both.
    vram_safety_gb: float = 1.5
    # MEASURED, not assumed. On a 15 GB T4 running Qwen3-VL-4B at nf4 with
    # 11.67 GB free (10.17 GB usable after the safety margin), 2112 vision tokens
    # ran and 3072 OOMed -- so 208..302 tokens per GB. The old value of 1200 was
    # 5.8x too high, which is why the ladder attempted two rungs it could never
    # hold and burned a failed generation on each.
    tokens_per_gb: int = 230
    # Activations only, and used to CHOOSE the model rather than to size a batch.
    # Measured, not assumed: on a 15 GB T4 holding Qwen3-VL-4B in fp16 the stage
    # reported 6.15 GB free, OOMed at 1536 vision tokens and ran at 768 -- about
    # 300 tokens per GB. The dominant cost is the vision tower's transient peak
    # across ALL patches in one forward pass, not the KV cache, which is why it
    # tracks total pixels rather than sequence length.
    activation_tokens_per_gb: int = 230
    # Coverage within this fraction of max_frames_cap counts as "full". Without
    # it the planner trades a materially better model for three frames: on a T4
    # the 3B at nf4 affords 48 frames and the 4B affords 45, and 45 frames
    # described by the better model is the better audit.
    coverage_tolerance: float = 0.90
    warn_vision_tokens: int = 0               # 0 = estimate from VRAM; >0 pins it

    # --- generation -----------------------------------------------------------
    # 0 = derive from the frame count: more frames means more events to report,
    # and a fixed cap truncates exactly the long videos that need the most room.
    max_new_tokens: int = 0
    tokens_per_frame_out: int = 64            # output budget per frame sent
    min_new_tokens_cap: int = 512
    max_new_tokens_cap: int = 4096
    do_sample: bool = False                   # greedy == reproducible (spec §45)
    max_repairs: int = 1                      # feedback retries after a parse failure

    # --- grounding context ----------------------------------------------------
    # plan.md §3.5 flags this as a real ablation, not a rhetorical one: context
    # grounds the model, but also risks it parroting the transcript instead of
    # looking at the images. Phase 9 measures it; this is the switch.
    include_transcript: bool = True
    include_ocr: bool = True
    # 0 = derive from duration. A 3-minute video has far more transcript than a
    # 15-second one, and a fixed cap silently truncates the longer one's context.
    context_max_chars: int = 0
    context_chars_per_second: int = 40
    min_context_chars: int = 600
    max_context_chars: int = 4000

    # --- validation -----------------------------------------------------------
    default_confidence: float = 0.5           # when the model omits it
    max_description_chars: int = 300

    # --- merging restated events ----------------------------------------------
    # Only TRUE RESTATEMENT is merged: a description that adds no new observable
    # fact. Detail is never traded away for a shorter list.
    #
    # There is NO similarity threshold here, and that is deliberate. Measured on
    # real output with rapidfuzz token_set_ratio:
    #     restatement, nothing new     >= 84.9
    #     same words, DIFFERENT fact   <= 84.2
    # A 0.7-point gap is not a gap. Both classes share a long common core ("the
    # person holds the white cylindrical container ..."), so ANY character- or
    # token-similarity measure conflates them. The gate asks a different question
    # instead -- does the next description introduce a new CONTENT WORD? -- which
    # is what "adds no new fact" actually means. See adds_no_new_fact().
    merge_similar_events: bool = True
    merge_token_ratio: int = 80        # word-level match strength for _tokens_match

@dataclass(frozen=True)
class Phase3Config:
    vision: VisionConfig = field(default_factory=VisionConfig)

    def to_dict(self) -> dict:
        return asdict(self)

# v2: insisted on the held/applied distinction and asked for cta_visual. Kept.
#     It also told the model not to start a new event for a position or framing
#     change -- which suppressed real detail ("raised overhead", "turned to show
#     the label" are different facts) and made the output WORSE than v1's.
# v3: reverses that. The model is told to be specific and that repetition is
#     handled downstream, so it never withholds a detail to keep the list short.
# 1.2.0: merging is now LOSSLESS -- every collapsed observation is kept in
#     `segments`. 1.1.0 kept only the longest description and dropped the rest,
#     which is evidence destruction, not de-duplication.
# All three are in the cache key, so visual__*.json is correctly invalidated.
# 1.3.0: the frame/pixel/output/context budget is DERIVED per video and per GPU
#     instead of being a fixed 24 frames. A constant cannot be right for both a
#     7-second hook clip and a 3-minute tutorial.
# 1.4.0: the merge gate is a CONTENT-WORD test, not a similarity threshold.
#     Measured, token_set_ratio put restatement at >=84.9 and different-fact at
#     <=84.2 -- the classes overlap and no threshold separates them.
# 1.10.0 / v5: the prompt now states the VALID INDEX RANGE, the clamp records
#     HOW FAR out the index was, a clamp of more than one marks the boundary
#     unreliable, and a whole-reply 1-based scheme is detected and shifted.
#     A clamped frame_end silently became 'ran to the end of the video' -- the
#     exact claim an end-of-video requirement asks about.
# 1.9.0: frame selection now optimises SHOT COVERAGE. Bucket-proportional
#     allocation saw 75% of shots across ten TikTok formats; capping the hook
#     and CTA windows at what they need and spending the remainder shot by shot
#     takes it to 93%. A shot the model never sees is an event it cannot report.
# 1.8.1: max_frames_hard_cap was swallowed into a comment by a bad edit and
#     never declared; quota_scene/quota_uniform were dead config left over from
#     the fixed-quota selector. Both fixed.
# 1.8.0: scene_count_of() reads the manifest's TRUE cut list instead of the
#     capped-and-thinned scene_change frames, so a rapid-cut video is sized like
#     one. Pairs with Phase 1 DECODE_STAGE_VERSION 1.1.0.
# 1.7.0: the budget and the frame selection now adapt to the video's FORMAT,
#     not just its length. Scene count sizes the budget, and the leftover budget
#     is split in proportion to what the manifest holds -- a fixed 15% scene
#     quota gave a 40-cut TikTok three frames to cover forty cuts.
# 1.6.0: the budget is derived from the VIDEO ONLY. Taking free VRAM as an input
#     made the cache key depend on transient allocator state -- a re-run of the
#     same video produced a different max_pixels, missed its own artifact, and
#     silently ran at thumbnail resolution. VRAM is now advisory; a GPU that
#     cannot hold the budget degrades through the ladder, which caches per rung.
# 1.5.0 / v4: descriptions are forced to English (rule 7) and a non-English
#     result is FLAGGED. Every downstream word list -- JUDGMENT_WORDS, STOPWORDS,
#     CONTINUATION_WORDS -- is English, so a Spanish description would make
#     §32's judgment check pass vacuously. The frame cap now also grows with
#     available VRAM, so a long video on a big card gets real coverage.
VLM_STAGE_VERSION = '1.13.0'   # + judgment scan matches whole words ('shoulder' is not 'should')

PROMPT_VERSION = 'p1_visual_evidence_v5'

P3 = Phase3Config()

def free_vram_gb() -> float:
    """
    VRAM actually AVAILABLE, or 0.0 with no GPU.

    mem_get_info() alone is misleading after a generation: PyTorch keeps a large
    reserved pool that the driver reports as used, even though PyTorch will
    happily reuse or release it on the next allocation. Reporting that as "1.5 GB
    free" once made the budget collapse to thumbnails. Add back the reclaimable
    part -- reserved but not currently allocated.
    """
    if not torch.cuda.is_available():
        return 0.0
    driver_free = torch.cuda.mem_get_info()[0]
    reclaimable = torch.cuda.memory_reserved() - torch.cuda.memory_allocated()
    return (driver_free + max(0, reclaimable)) / 1024 ** 3

def vision_token_budget(free_gb: float, cfg: VisionConfig) -> int:
    """
    How many input tokens this GPU can actually hold, derived not assumed.

    Hardcoding a limit means it is wrong on every machine but the one it was
    written on: a 40 GB A100 gets throttled to a T4's budget, and a half-full
    T4 still tries the full one and OOMs.
    """
    if cfg.warn_vision_tokens > 0:
        return cfg.warn_vision_tokens
    usable = max(0.0, free_gb - cfg.vram_safety_gb)
    return max(2000, int(usable * cfg.tokens_per_gb))

def scene_count_of(manifest: dict) -> int:
    """
    How many distinct cuts this video has, from the manifest (deterministic).

    Used to size the frame budget: duration alone cannot distinguish a static
    talking head from a rapid-cut edit of the same length, and the second one
    needs far more frames to be seen at all.

    Prefers `scenes.cut_times` -- the TRUE count Phase 1 detected. Counting
    scene_change FRAMES instead undercounts twice over: Phase 1 caps how many
    cuts get a frame (max_scene_frames), then thins again to fit
    max_total_frames. A 40-cut video could report 24 and be sized like a much
    calmer edit. Falls back to frames for a manifest with no scenes block.
    """
    scenes = manifest.get('scenes') or {}
    cuts = scenes.get('cut_times')
    if isinstance(cuts, list):
        return len(cuts)
    if isinstance(scenes.get('n_shots'), int):
        return max(0, scenes['n_shots'] - 1)
    return sum(1 for f in manifest.get('frames', [])
               if f.get('reason') == 'scene_change')

def resolve_vision_config(cfg: VisionConfig, duration_s: float,
                          n_scenes: int = 0) -> VisionConfig:
    """
    Derive THIS video's budget -- from the VIDEO ONLY, and deterministically.

    FREE VRAM IS DELIBERATELY NOT AN INPUT HERE, and that is the whole point.
    An earlier version took it, and it broke caching in a way that looked like a
    cache bug: after a generation, PyTorch's allocator still holds a large
    reserved pool, so mem_get_info() reports almost nothing free. The next call
    then derived a tiny budget, shrank frames to 168x336 thumbnails, produced a
    DIFFERENT max_pixels, and therefore a different cache key -- so a re-run of
    the same video missed its own artifact and silently ran at a fraction of the
    intended resolution.

    A cache key must be a function of the inputs, not of transient machine state.
    So: the budget comes from the video, and a machine that cannot hold it is
    handled by the OOM ladder in run_vision_stage(), which tries smaller rungs
    and caches under the rung that actually succeeded. Same determinism, and the
    artifact still records exactly what it ran with.

    To use a bigger machine's headroom, raise max_frames_cap explicitly -- an
    intentional, reproducible choice rather than a silent dependence on whatever
    happened to be free at the time.
    """
    if cfg.auto_budget:
        by_time = int(math.ceil(max(0.0, duration_s) / max(0.1, cfg.seconds_per_frame)))
        # A cut the model never sees is an event it cannot report, so take
        # whichever demand is HIGHER: temporal density or scene coverage.
        by_scenes = int(math.ceil(max(0, n_scenes) * cfg.frames_per_scene))
        cap = int(min(cfg.max_frames_cap, cfg.max_frames_hard_cap))
        want = max(cfg.min_frames, min(max(by_time, by_scenes), cap))
    else:
        want = cfg.max_frames

    out_tokens = int(min(cfg.max_new_tokens_cap,
                         max(cfg.min_new_tokens_cap,
                             256 + want * cfg.tokens_per_frame_out))) \
        if cfg.max_new_tokens <= 0 else cfg.max_new_tokens
    ctx_chars = int(min(cfg.max_context_chars,
                        max(cfg.min_context_chars,
                            cfg.min_context_chars + max(0.0, duration_s)
                            * cfg.context_chars_per_second))) \
        if cfg.context_max_chars <= 0 else cfg.context_max_chars

    return dataclasses.replace(cfg, max_frames=int(want),
                               max_new_tokens=out_tokens, context_max_chars=ctx_chars)

def vision_ladder(vcfg: VisionConfig) -> list:
    """
    (frames, pixels) rungs to try, in order. Deterministic -- derived from the
    resolved config, never from free VRAM.

    Resolution is given up BEFORE coverage: for event detection, knowing when
    something happened matters more than fine spatial detail, and OCR already
    read the on-screen text at native resolution back in Phase 2.
    """
    p_full = vcfg.max_pixels
    p_half = max(vcfg.min_pixels, int(p_full * 0.5) // 784 * 784)
    n = vcfg.max_frames
    n70 = max(vcfg.min_frames, int(n * 0.7))
    n50 = max(4, int(n * 0.5))
    # A floor the ladder can actually reach. Without these the lowest rung is
    # half the frames at half resolution -- on an 84s video that is still 24
    # frames / ~4900 tokens, and a GPU that cannot hold THAT has nowhere left
    # to step down to, so the stage fails with no evidence at all. Two more
    # rungs trade coverage for landing: some evidence beats none, and the
    # artifact records exactly which rung produced it.
    p_quarter = max(vcfg.min_pixels, int(p_full * 0.25) // 784 * 784)
    nmin = max(4, vcfg.min_frames)
    # Keep a rung only if it is STRICTLY cheaper than the one above it.
    #
    # The candidates are not naturally ordered. min_frames is a floor, so on a
    # small budget the nmin rung can be LARGER than the n50 rung above it: a
    # 19-frame budget produced 19, 19, 13, 9, 12 -- and once 9 frames has OOMed,
    # 12 at the same resolution cannot possibly fit. That rung is a guaranteed
    # failed generation, and because run_vision_stage never drops the LAST rung
    # it survived the affordability filter that exists to skip exactly this.
    #
    # Cost is frames x pixels, the same proxy estimate_vision_tokens and the
    # affordability filter use, so the ladder agrees with the thing that reads
    # it. Strict '<' also absorbs the old duplicate check -- an equal-cost rung
    # is no more likely to fit than the one that just failed -- and guards a
    # misconfigured max_pixels below min_pixels, where p_half would exceed
    # p_full and the second rung would step up.
    out = []
    # Give up RESOLUTION at the full frame count BEFORE giving up frames. That is
    # what the docstring above has always claimed; the rung order did the
    # opposite. Dropping to 33 frames at half resolution costs MORE tokens (2112)
    # than keeping all 48 at quarter resolution (1536), and throws away 15 frames
    # of coverage to do it -- and coverage is what modality_health and can_fail_on
    # actually depend on. Measured on an 84s video at 11.67 GB free: the old order
    # landed on 33 frames, this one lands on 48.
    for f, p in ((n, p_full), (n, p_half), (n, p_quarter),
                 (n70, p_half), (n70, p_quarter),
                 (n50, p_half), (n50, p_quarter),
                 (nmin, p_half), (nmin, p_quarter)):
        if out and f * p >= out[-1][0] * out[-1][1]:
            continue
        out.append((f, p))
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 399: print(f'VLM_STAGE_VERSION {VLM_STAGE_VERSION}   prompt {PROMPT_VERSION}')
#   line 400: print(f'budget            auto={P3.vision.auto_budget}, 1 frame / {P3.vision
#   line 403: print('\nresolved budget by video length -- derived from the VIDEO only, so 
#   line 404: print('same clip always produces the same cache key on any machine:')
#   line 405: _fg = free_vram_gb()
#   line 406: print(f'  (free VRAM is {_fg:.1f} GB -> ~{vision_token_budget(_fg, P3.vision
#   line 408: print(f"  {'duration':>9}  {'frames':>6}  {'px/frame':>9}  {'tokens':>7}  {'
#   line 409: for _d in (7, 15, 30, 60, 120, 180):
