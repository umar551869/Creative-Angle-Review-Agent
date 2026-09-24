"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 72.
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
class _SkipAffordability(Exception):
    """Raised to bypass the VRAM affordability filter on a hosted provider.

    The filter's existing `except` already falls through to the full ladder on
    any bad reading, so reusing that path keeps one exit instead of two.
    """

def run_vision_stage(video: dict, cfg: Phase3Config = None, backend=None,
                     transcript_obj=None, ocr_obj=None,
                     force: bool = False, verbose: bool = True) -> VisualEvidence:
    """
    Pass 1 for one video, cached. Loads the model only on a cache miss.
    """
    cfg = cfg or P3
    vdir = DIRS['artifacts'] / video['video_hash']

    # Derive the budget from THIS VIDEO -- and from the video ONLY, so the cache
    # key is reproducible on any machine. A 7-second clip and a 3-minute tutorial
    # get budgets that suit them; a GPU too small for the result degrades through
    # the ladder below, which caches per rung.
    manifest = read_json(video['manifest_path'])
    _dur = float(video.get('duration_s') or manifest['media']['duration_seconds'])
    _scenes = scene_count_of(manifest)
    vcfg = resolve_vision_config(cfg.vision, _dur, _scenes)
    if verbose and cfg.vision.auto_budget:
        _est = vcfg.max_frames * (vcfg.max_pixels // 784)
        _avail = vision_token_budget(free_vram_gb(), cfg.vision)
        print(f'  budget for {_dur:.1f}s : {vcfg.max_frames} frames @ '
              f'{vcfg.max_pixels} px  (~{_est} tokens), out<={vcfg.max_new_tokens}')
        print(f'  scene cuts        : {_scenes}  '
              f'(budget is the larger of temporal density and scene coverage)')
        # ADVISORY ONLY -- free VRAM must never reach the cache key, so if this
        # looks tight we say so and let the ladder handle it rather than quietly
        # resolving to a different (and differently-keyed) budget.
        if _est > _avail:
            print(f'  note: ~{_avail} tokens look affordable right now; if the first '
                  f'rung OOMs the ladder will step down and cache that instead.')

    # Which weights this card will actually run. That is part of the OUTPUT, so
    # it belongs in the key: the same video on a T4 and on a 24 GB card is
    # described by different models and the two must not collide in the cache.
    # Taken from the PLAN rather than from the loaded backend, because the cache
    # is checked before anything loads. If load_vlm falls through to a later
    # candidate the artifact records the model it really used and carries a
    # VLM_FALLBACK flag, so the discrepancy is visible rather than silent.
    _planned_vlm = list((plan_vlm_load(vcfg) or [(None, None)])[0])

    def _key_for(c: VisionConfig) -> str:
        return stage_key('visual', VLM_STAGE_VERSION,
                         [video['video_hash'], video['plan_hash']],
                         {'vision': asdict(c), 'prompt': PROMPT_VERSION,
                          'vlm': _planned_vlm})

    # Which path will actually describe the frames. Resolved ONCE, here,
    # because BOTH the cache scan below and the affordability filter further
    # down turn on it. The second clause mirrors how `backend` is chosen below,
    # so the two can never disagree about which path is running.
    _p3_local = (getattr(cfg.vision, 'provider', 'local') == 'local'
                 or not callable(globals().get('make_vision_backend')))

    # ---- the frame-budget ladder --------------------------------------------
    # A GPU that cannot hold 24 frames can usually hold 12. Failing the video
    # outright throws away a whole model load and, in a 40-video batch, means
    # one awkward video kills the run. Degrade instead, and SAY SO in the
    # evidence -- a 12-frame result is weaker than a 24-frame one and the
    # record has to show which you got.
    # Rungs are derived from the RESOLVED config and are deterministic, so each
    # rung has a stable cache key on every machine and every run.
    ladder = [(n, (vcfg if (n, p) == (vcfg.max_frames, vcfg.max_pixels)
                   else dataclasses.replace(vcfg, max_frames=n, max_pixels=p)))
              for n, p in vision_ladder(vcfg)]

    # Check EVERY rung's cache before running anything: an earlier run may have
    # succeeded at a reduced budget, and re-OOMing at 24 just to rediscover that
    # wastes a minute per video on every re-run.
    #
    # ONE exception, and it is the whole point of fix 21. A hosted backend has
    # no VRAM ceiling and never OOMs, so a DEGRADED hosted artifact cannot have
    # come from an OOM -- it came from the affordability filter below, which
    # used to throttle hosted runs by a GPU they never touch. Serving one from
    # cache would describe a quarter of the frames the audit is supposed to see
    # and would make fix 20 invisible on every video already processed.
    #
    # On a LOCAL provider this branch never fires: there the degradation was
    # real, and refusing the hit would mean re-OOMing on every run.
    if not force:
        for n_frames, acfg in ladder:
            p = vdir / f'visual__{_key_for(acfg)}.json'
            if not p.exists():
                continue
            _degraded = ((acfg.max_frames, acfg.max_pixels)
                         != (vcfg.max_frames, vcfg.max_pixels))
            if _degraded and not _p3_local:
                if verbose:
                    print(f'  ignoring a DEGRADED cached visual '
                          f'({acfg.max_frames} frames @ {acfg.max_pixels}px): '
                          f'hosted vision is not limited by local VRAM, so the '
                          f'full {vcfg.max_frames}-frame budget is re-run')
                continue
            if verbose:
                note = ('' if not _degraded
                        else f' [degraded: {acfg.max_frames} frames '
                             f'@ {acfg.max_pixels}px]')
                print(f'  VISUAL CACHE HIT ({_key_for(acfg)}){note}')
            return VisualEvidence.model_validate(read_json(p))

    context = build_context_block(transcript_obj, ocr_obj, vcfg)
    if backend is None:
        # Honour the CONFIGURED provider. Hardcoding load_vlm here loads Qwen
        # even when provider='gemini' -- silently, and only on the path where a
        # caller omitted `backend`, which is exactly the path §34's batch runner
        # takes. globals() rather than a direct call so this stays valid in the
        # local-only notebook, where make_vision_backend does not exist.
        _mk = globals().get('make_vision_backend')
        backend = (_mk(vcfg, verbose=verbose) if callable(_mk)
                   else load_vlm(vcfg, verbose=verbose))

    def _generate(messages, imgs, c):
        return backend.generate(messages, imgs, c)

    out = None
    # What actually limited this run. The DEGRADED_BUDGET flag used to say
    # "OOM at N frames" unconditionally, including when the advisory filter
    # below skipped those rungs and nothing ever ran, let alone OOMed. A flag
    # that misreports its own cause makes the one diagnosis it exists for --
    # "is this GPU too small, or is the estimate too conservative?" --
    # impossible to make from the artifact.
    _skipped_rungs, _afford_tokens, _ooms = 0, None, []
    # Skip rungs this GPU plainly cannot hold.
    #
    # The advisory above already computes what is affordable; trying a rung that
    # is 2x over it costs a guaranteed OOM, and on an 84s video that burned four
    # of them before landing. Each failed attempt also churns the allocator.
    #
    # Two guards, because free-VRAM readings are treacherous here:
    #   - empty the cache FIRST, or a previous generation's reserved pool makes
    #     everything look unaffordable (the exact bug resolve_vision_config was
    #     written to avoid letting into the cache key)
    #   - NEVER drop the last rung. If the reading is wrong, the floor still runs
    #     and the OOM ladder behaves as it always did.
    # ONLY a local model is limited by local VRAM. Gemini holds none of it, and
    # make_vision_backend's own contract is that the hosted path never degrades
    # the frame budget -- but this filter never asked which provider was
    # running, so a hosted run was cut to the smallest rung by a GPU it does
    # not use. `_p3_local` is resolved once, up by the ladder (fix 21).
    if not _p3_local and verbose:
        print(f'  hosted vision provider '
              f'({getattr(cfg.vision, "provider", "?")}): keeping the full '
              f'{ladder[0][0]}-frame budget -- local VRAM does not limit it')
    try:
        if not _p3_local:
            raise _SkipAffordability()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _afford = vision_token_budget(free_vram_gb(), cfg.vision)
        _afford_tokens = _afford
        _viable = [(f, a) for (f, a) in ladder
                   if estimate_vision_tokens(f, a.max_pixels) <= _afford]
        if _viable and len(_viable) < len(ladder):
            _skipped_rungs = len(ladder) - len(_viable)
            if verbose:
                print(f'  skipping {_skipped_rungs} rung(s) above the '
                      f'~{_afford} tokens this GPU reports free '
                      f'(starting at {_viable[0][0]} frames)')
            ladder = _viable
    except Exception:
        pass          # a bad reading must never prevent the ladder from running

    for rung, (n_frames, acfg) in enumerate(ladder):
        # Free VRAM at the START of each rung, not only at failure. The error
        # message reports memory AFTER the OOM, which cannot distinguish a leak
        # between rungs from a budget estimate that was simply optimistic.
        if verbose and torch.cuda.is_available():
            print(f'  --- rung {rung}: '
                  f'{torch.cuda.mem_get_info()[0] / 1024 ** 3:.2f} GB free before it ---')
        frames = select_vlm_frames(manifest, n_frames, acfg)
        frame_table = build_frame_table(frames)
        images, missing = load_frame_images(frames, video['frames_dir'], acfg)
        if missing:
            # keep the table aligned with the images that actually loaded
            kept = [f for f in frames if f['frame_id'] not in set(missing)]
            frames, frame_table = kept, build_frame_table(kept)
            if verbose:
                print(f'  WARNING: {len(missing)} frame file(s) missing, '
                      f'continuing with {len(frames)}')

        est = estimate_vision_tokens(len(frame_table), acfg.max_pixels)
        _sizes = sorted({im.size for im in images})
        if verbose:
            print(f'  frames -> VLM     : {len(frame_table)}'
                  f'{"" if rung == 0 else f"   (DEGRADED from {vcfg.max_frames} frames @ {vcfg.max_pixels}px after OOM)"}')
            print(f'  frame sizes       : {_sizes[:3]}{" …" if len(_sizes) > 3 else ""}  '
                  f'(budget {acfg.max_pixels} px)')
            print(f'  context           : {len(context)} chars'
                  f'{"" if context else "  (none -- no transcript/OCR)"}')
            print(f'  vision tokens     : ~{est} estimated (measured below)')
        _over = [s for s in _sizes if s[0] * s[1] > acfg.max_pixels]
        if _over:
            print(f'  WARNING: {len(_over)} frame size(s) exceed the pixel budget: {_over[:3]}')

        t0 = time.time()
        out = run_vlm_pass1(frame_table, images, context, acfg, _generate)
        elapsed = time.time() - t0

        if not out.get('oom'):
            break
        _ooms.append((n_frames, acfg.max_pixels))
        if rung + 1 < len(ladder):
            _nxt = ladder[rung + 1][1]
            print(f'  OOM at {n_frames} frames @ {acfg.max_pixels}px -- retrying with '
                  f'{_nxt.max_frames} @ {_nxt.max_pixels}px. To avoid this cost, use '
                  f'4-bit, or raise seconds_per_frame / lower max_pixels.')
            gc.collect(); torch.cuda.empty_cache()
            if torch.cuda.is_available():
                print(f'  after cleanup     : '
                      f'{torch.cuda.mem_get_info()[0] / 1024 ** 3:.2f} GB free')
        else:
            print(f'  OOM at every rung down to {n_frames} frames. Use 4-bit:')
            print("    P3 = Phase3Config(vision=dataclasses.replace(P3.vision, quantization='4bit'))")
            print('    free_vlm(vlm); vlm = load_vlm(P3.vision)')

    # the config actually used decides the cache key, so a degraded result is
    # never filed under the budget it failed to achieve
    vcfg_used = acfg
    key = _key_for(vcfg_used)
    path = vdir / f'visual__{key}.json'
    # Check PIXELS as well as frames: the first rung down keeps all 24 frames and
    # halves the resolution, so a frames-only check would record a half-resolution
    # run as if it had the full budget.
    if (vcfg_used.max_frames, vcfg_used.max_pixels) != (vcfg.max_frames, vcfg.max_pixels):
        # Two different causes, and they call for opposite fixes:
        #   OOM      -> the GPU really is too small. 4-bit, or a smaller budget.
        #   skipped  -> nothing was tried; vision_token_budget said it could not
        #               afford it. If the rung would in fact have run, the
        #               advisory is too conservative and tokens_per_gb is wrong.
        # Reporting both as "OOM" hid that distinction in the artifact, which is
        # the only place anyone can check it after the session ends.
        _why = []
        if _ooms:
            _why.append('OOM at ' + ', '.join(f'{f} frames @ {p}px'
                                              for f, p in _ooms))
        if _skipped_rungs:
            _why.append(f'{_skipped_rungs} rung(s) skipped unattempted as '
                        f'above the ~{_afford_tokens} tokens this GPU reported '
                        f'free')
        if not _why:
            _why.append('the top rung did not run, for a reason the ladder did '
                        'not record')
        out['flags'].append({
            'code': 'DEGRADED_BUDGET',
            'cause': ('oom' if _ooms and not _skipped_rungs else
                      'unaffordable' if _skipped_rungs and not _ooms else
                      'both' if _ooms else 'unknown'),
            'oom_rungs': [{'frames': f, 'max_pixels': p} for f, p in _ooms],
            'skipped_rungs': _skipped_rungs,
            'afford_tokens': _afford_tokens,
            'detail': f'asked for {vcfg.max_frames} frames @ {vcfg.max_pixels}px, '
                      f'ran {vcfg_used.max_frames} @ {vcfg_used.max_pixels}px; '
                      + '; '.join(_why)})

    leakage = [{'event_id': e['id'], 'description': e['description'],
                'words': [f.split(':', 1)[1] for f in e['flags']
                          if f.startswith('JUDGMENT_LANGUAGE')]}
               for e in out['events']
               if any(f.startswith('JUDGMENT_LANGUAGE') for f in e['flags'])]

    # fall back to whatever the backend measured before it died -- on a failure
    # `gen` is empty, and the token count is exactly what you need to see
    tokens = (out.get('gen') or {}).get('tokens', {}) or getattr(backend, 'last_tokens', {}) or {}
    evidence = VisualEvidence(
        status=out['status'],
        video_id=video['video_id'], video_hash=video['video_hash'],
        events=out['events'], frame_table=frame_table,
        flags=out['flags'], judgment_leakage=leakage,
        raw_output=out['raw_output'][:20000],
        stats={
            'n_frames_sent': len(frame_table),
            'n_events': len(out['events']),
            'n_missing_frame_files': len(missing),
            'attempts': out['attempts'],
            'estimated_vision_tokens': est,
            'measured_input_tokens': tokens.get('total_input_tokens'),
            'generated_tokens': tokens.get('generated_tokens'),
            'hit_token_cap': bool((out.get('gen') or {}).get('hit_token_cap')),
            'context_chars': len(context),
            'event_types': {t: sum(1 for e in out['events'] if e['type'] == t)
                            for t in {e['type'] for e in out['events']}},
            'events_with_flags': sum(1 for e in out['events'] if e['flags']),
            'inference_seconds': round(elapsed, 2),
            'requested_frame_budget': vcfg.max_frames,
            'frame_budget_used': vcfg_used.max_frames,
            'requested_max_pixels': vcfg.max_pixels,
            'max_pixels_used': vcfg_used.max_pixels,
        },
        model=getattr(backend, 'info', {}),
        # the config ACTUALLY used, so the artifact matches its own cache key
        config={'vision': asdict(vcfg_used), 'prompt_version': PROMPT_VERSION},
        provenance=provenance('visual', VLM_STAGE_VERSION, key, elapsed),
    )

    # Do NOT cache failures: a transient OOM must not freeze into the evidence store.
    if evidence.status == 'OK':
        write_json(path, evidence.model_dump())
    elif verbose:
        print(f'  NOT CACHED (status={evidence.status}) -- re-run to retry')

    return evidence

def visual_summary(ev: VisualEvidence) -> str:
    s = ev.stats
    lines = [
        f'status            : {ev.status}',
        f'model             : {ev.model.get("model", "?")} [{ev.model.get("quantization", "?")}]',
        f'frames sent       : {s.get("n_frames_sent")}'
        + ('' if (s.get('frame_budget_used'), s.get('max_pixels_used'))
           == (s.get('requested_frame_budget'), s.get('requested_max_pixels'))
           else f'   DEGRADED from {s.get("requested_frame_budget")} frames @ '
                f'{s.get("requested_max_pixels")}px after OOM'),
        f'vision tokens     : ~{s.get("estimated_vision_tokens")} est / '
        f'{s.get("measured_input_tokens")} measured (total input)',
        f'events            : {s.get("n_events")}  {s.get("event_types", {})}',
        f'events w/ flags   : {s.get("events_with_flags")}',
        f'attempts          : {s.get("attempts")}',
        f'inference         : {s.get("inference_seconds")}s',
    ]
    if ev.flags:
        lines.append(f'flags             : {[f["code"] for f in ev.flags]}')
        # The DETAIL is the whole diagnosis on a failure -- printing only codes
        # turns "here is the exception that killed it" into the word GENERATION_FAILED.
        for f in ev.flags:
            if f.get('detail'):
                lines.append(f'  -> {f["code"]}: {f["detail"]}')
    if ev.judgment_leakage:
        lines.append(f'JUDGMENT LEAKED   : {len(ev.judgment_leakage)} event(s) -- see §32')
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 345: print('pipeline_p3.py loaded  --  Phase 3 backend complete')
