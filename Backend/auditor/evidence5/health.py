"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 113.
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
def modality_health(transcript: dict, ocr: dict, visual: dict, manifest: dict,
                    duration: float, cfg: EvidenceConfig = None) -> dict:
    """
    Did each modality actually run, and did it run WELL?

    This is what separates "we looked and it was not there" (FAIL) from "we did
    not really look" (UNCERTAIN). Phase 6 must never call FAIL on a modality
    whose `can_fail_on` is False.
    """
    cfg = cfg or P5.evidence
    h = {}

    # ---- speech -----------------------------------------------------------
    segs = (transcript or {}).get('segments') or []
    words = (transcript or {}).get('words') or [w for s in segs for w in (s.get('words') or [])]
    # UNION the segment spans, do not sum them. Overlapping segments would be
    # counted twice and speech_ratio could exceed 1.0 -- nonsense feeding a
    # hook-strength feature. Nothing upstream guarantees they do not overlap.
    _spans = []
    for s in segs:
        try:
            a, b = float(s.get('start', 0) or 0), float(s.get('end', 0) or 0)
        except (TypeError, ValueError):
            continue
        if b > a:
            _spans.append([a, b])
    _spans = _merge_spans(_spans)
    spoken = sum(b - a for a, b in _spans)
    degraded_asr = bool((transcript or {}).get('degraded'))
    thin = len(words) < cfg.thin_speech_words
    _ratio = (spoken / duration) if duration else None
    # THE DISTINCTION, and the order of these clauses is the whole point:
    #
    #   degraded_asr   the transcriber itself reported trouble. Never absent --
    #                  a crashed ASR also produces zero words, and that is
    #                  "we could not hear it", which is the opposite finding.
    #   absent         it ran cleanly and found essentially no voiced time and
    #                  essentially no words. There was nothing to hear, so an
    #                  absence in speech is ESTABLISHED and may support a FAIL.
    #   thin           voiced time exists but the transcript is too sparse to
    #                  trust. Absence is NOT establishable.
    #
    # Measured on a 12.35s music-only video: ratio 0.034, 1 word -> absent,
    # and its captions were read by OCR at 100% coverage.
    absent = bool(
        transcript and not degraded_asr
        and _ratio is not None
        and _ratio <= cfg.absent_speech_ratio_PLACEHOLDER
        and len(words) <= cfg.absent_speech_max_words)
    h['speech'] = {
        'ran': bool(transcript),
        # An absent modality is not a degraded one. It ran, it looked, and
        # there was nothing there -- which is a finding, not a gap.
        'absent': absent,
        'degraded': (degraded_asr or thin) and not absent,
        'reason': (
            (f'no speech in this video: {len(words)} word(s) across '
             f'{round(spoken, 2)}s of voiced audio. Absence in speech is '
             f'established, not uncertain.') if absent
            else ('; '.join(filter(None, [
                (transcript or {}).get('degradation_reason'),
                f'only {len(words)} word(s) transcribed' if thin else None]))
            or None)),
        'segments': len(segs), 'words': len(words),
        'speech_seconds': round(spoken, 2),
        'speech_ratio': round(spoken / duration, 3) if duration else None,
        'backend': (transcript or {}).get('backend'),
        'language': (transcript or {}).get('language'),
    }

    # ---- ocr --------------------------------------------------------------
    ivs = (ocr or {}).get('intervals') or []
    unread = sum(1 for i in ivs if (i.get('independence') == 'unreadable'))
    indep = sum(1 for i in ivs if (i.get('independence') == 'confirmed_independent'))
    # frames the dedupe actually ran OCR on, not the ones it was offered
    ocr_ran = sum(1 for f in ((ocr or {}).get('per_frame') or []) if f.get('ocr_run'))
    h['ocr'] = {
        'ran': bool(ocr),
        'degraded': bool(ocr) and bool(ivs) and (unread / max(1, len(ivs))) > 0.5,
        'reason': (f'{unread} of {len(ivs)} intervals unreadable'
                   if ivs and (unread / max(1, len(ivs))) > 0.5 else None),
        'intervals': len(ivs), 'confirmed_independent': indep, 'unreadable': unread,
        'frames_scanned': len((manifest or {}).get('frames') or []),
        'frames_examined': ocr_ran or None,
        'backend': (ocr or {}).get('backend'),
    }

    # ---- visual -----------------------------------------------------------
    vstats = (visual or {}).get('stats') or {}
    _vflag_objs = [f for f in ((visual or {}).get('flags') or []) if isinstance(f, dict)]
    vflags = [f.get('code') if isinstance(f, dict) else str(f)
              for f in ((visual or {}).get('flags') or [])]
    # Phase 3 records WHY the budget degraded: 'oom' (the GPU is genuinely too
    # small) or 'unaffordable' (vision_token_budget refused to try, so nothing
    # ran and the estimate may simply be too conservative). Those call for
    # opposite fixes -- 4-bit versus recalibrating tokens_per_gb -- so carry the
    # distinction into the health block rather than making someone reconstruct
    # it from a console log that is gone once the session ends.
    _deg_cause = next((f.get('cause') for f in _vflag_objs
                       if f.get('code') == 'DEGRADED_BUDGET' and f.get('cause')), None)
    _deg_detail = next((f.get('detail') for f in _vflag_objs
                        if f.get('code') == 'DEGRADED_BUDGET' and f.get('detail')), None)
    # Phase 3 writes n_frames_sent / frame_budget_used. Reading 'frames_sent'
    # returned 0 on every real artifact, which silently disabled the ratio test
    # below and left degradation resting entirely on the DEGRADED_BUDGET flag.
    # Measured: n_frames_sent=12 of 96 planned, reported as frames_sent=None.
    sent = vstats.get('n_frames_sent') or vstats.get('frame_budget_used') or 0
    planned = len((manifest or {}).get('frames') or []) or 0
    # Measure the shortfall against the BUDGET, not the extraction plan.
    #
    # Phase 1 extracts ~90 frames; resolve_vision_config then asks for one frame
    # per 1.5s, capped at 48. So the VLM is MEANT to see a fraction of the plan:
    # 48 of 96 on the 84s video, 19 of 88 on the 27s one. Dividing by the plan
    # gives 0.50 and 0.22 -- both under the 0.60 threshold -- so visual would
    # read as degraded on EVERY video, even one that ran its full budget with no
    # OOM at all, and can_fail_on('visual') would be permanently False. That
    # makes the whole FAIL-vs-UNCERTAIN mechanism vacuous for this modality.
    #
    # The honest question is "did the model get the frames it asked for?", so
    # the denominator is the requested budget, and the plan is only the fallback
    # for an artifact that does not record one.
    budget = vstats.get('requested_frame_budget') or 0
    denom = budget or planned
    short = bool(sent) and bool(denom) and (sent / denom) < cfg.degraded_frame_ratio
    # DEGRADED_BUDGET means the OOM ladder stepped down -- in frames, in
    # resolution, or both -- so what the model saw is weaker than intended.
    px_req = vstats.get('requested_max_pixels') or 0
    px_used = vstats.get('max_pixels_used') or 0
    degraded_vis = ('DEGRADED_BUDGET' in vflags) or short
    # COVERAGE and ACUITY are different failures, and only one of them makes
    # absence uninterpretable.
    #
    #   coverage -- frames. A frame we never looked at can hide an event
    #               entirely, so "we did not see it" may only mean "we did not
    #               look there". Absence is NOT evidence. This blocks a FAIL.
    #   acuity   -- pixels. Every moment was still examined, just in less
    #               detail; the event was visible or it was not. A caveat on the
    #               reading, not a hole in it -- and OCR already read every
    #               on-screen word at native resolution in Phase 2.
    #
    # Collapsing both into one `degraded` flag meant a pure resolution step-down
    # permanently disabled visual FAILs, even at 48 of 48 frames. `degraded`
    # still reports either, because the artifact should say what happened; only
    # the FAIL gate narrows. degraded_frame_ratio remains the dial for how much
    # coverage loss is too much.
    # FAIL CLOSED when coverage cannot be verified.
    #
    # `short` only fires when BOTH numbers are readable. An artifact that stepped
    # the ladder down but recorded no usable frame accounting -- one written
    # before requested_frame_budget existed, or one whose keys we cannot read --
    # would otherwise look like full coverage and be allowed to assert a FAIL
    # from absence. The blanket `degraded` flag used to fail closed on
    # DEGRADED_BUDGET alone; splitting coverage out must not lose that.
    #
    # The ladder stepping down is itself evidence that something was given up.
    # Absent proof that it was ONLY resolution, assume it was frames.
    #
    # When coverage IS measurable, degraded_frame_ratio is the policy for how
    # much loss is too much -- 33 of 48 frames is 69%, above the configured
    # 60%, and `short` already says so. Demanding sent >= budget here would
    # override that policy with a stricter one (100%) that nobody chose, and
    # would make a visual FAIL impossible on any video the ladder touched.
    #
    # The fail-closed branch is for when coverage CANNOT be verified: the ladder
    # stepped down and the artifact recorded no usable frame accounting, so we
    # cannot tell whether it gave up resolution or frames. Assume frames.
    _coverage_known = bool(sent) and bool(budget)
    coverage_degraded = (bool(short) if _coverage_known
                         else ('DEGRADED_BUDGET' in vflags))
    acuity_degraded = bool(px_req and px_used and px_used < px_req)
    h['visual'] = {
        'ran': bool(visual) and (visual or {}).get('status') == 'OK',
        'status': (visual or {}).get('status') or 'MISSING',
        'degraded': bool(degraded_vis),
        'reason': ('; '.join(filter(None, [
            ({'oom': 'the GPU OOMed and the ladder stepped down',
              'unaffordable': 'rungs were skipped UNATTEMPTED as unaffordable '
                              '-- nothing OOMed, so the estimate may be too '
                              'conservative',
              'both': 'the ladder both skipped rungs and OOMed'}
             .get(_deg_cause, 'OOM ladder degraded the frame budget'))
            if 'DEGRADED_BUDGET' in vflags else None,
            f'{sent} of {budget or planned} frames the budget asked for'
            if short else None,
            f'resolution cut to {px_used} of {px_req} px'
            if px_req and px_used and px_used < px_req else None])) or None),
        'degraded_cause': _deg_cause,
        'degraded_detail': _deg_detail,
        # what can_fail_on actually reads; see the comment above
        'coverage_degraded': bool(coverage_degraded),
        'acuity_degraded': bool(acuity_degraded),
        'events': len((visual or {}).get('events') or []),
        'frames_sent': sent or None, 'frames_planned': planned or None,
        'frames_budgeted': budget or None,
        'flags': vflags,
        # 'model', not 'model_id' -- see visual_records. Reading the wrong key
        # left this None on every real run, so the health block could not name
        # the model whose degradation it was reporting.
        'model': ((visual or {}).get('model') or {}).get('model'),
        'quantization': ((visual or {}).get('model') or {}).get('quantization'),
    }

    h['metadata'] = {'ran': bool(manifest), 'degraded': False, 'reason': None,
                     'frames': len((manifest or {}).get('frames') or [])}
    return h

def can_fail_on(health: dict, modality: str) -> bool:
    """
    May Phase 6 assert a FAIL from the ABSENCE of evidence in this modality?

    Only if the modality ran and we actually LOOKED everywhere. A FAIL asserts
    something, and absence is only evidence when you looked.

    "Looked everywhere" means COVERAGE, not acuity. A modality that examined
    every moment at reduced resolution still looked; one that skipped frames did
    not, and an event can hide in a frame nobody saw. Where a modality reports
    `coverage_degraded` that is the signal; otherwise fall back to the blanket
    `degraded` flag, which is all speech and OCR record.

    Reduced acuity is not free -- it rides along as `acuity_degraded` in the
    health block and in the reason string, so a FAIL made on a low-resolution
    reading is still traceable to that fact.
    """
    m = (health or {}).get(modality) or {}
    if not bool(m.get('ran')):
        return False
    # ABSENT is not DEGRADED. A modality that ran, looked everywhere and found
    # nothing has established an absence -- that is precisely the evidence a
    # FAIL needs. Checked before `degraded` so the two can never be confused.
    if m.get('absent'):
        return True
    if 'coverage_degraded' in m:
        return not m['coverage_degraded']
    return not m.get('degraded')

def modes_that_can_fail(health: dict) -> dict:
    """The same question, per evidence_mode, since that is what requirements carry."""
    sp, oc, vi = (can_fail_on(health, m) for m in ('speech', 'ocr', 'visual'))
    return {
        'speech_only': sp,
        'ocr_only': oc,
        'visual_only': vi,
        'speech_or_text': sp and oc,        # either could have carried it
        'visual_and_speech': vi and sp,     # both were needed
        'any': sp and oc and vi,
    }

def coverage_map(records: list, duration: float, cfg: EvidenceConfig = None) -> dict:
    """
    Per-modality, per-second: was there ANY evidence here?

    Global coverage would say "this second is covered" because the camera was
    rolling, and Phase 6 would then confidently FAIL a speech requirement in a
    silent stretch. Separating the modalities is what keeps that honest.
    """
    cfg = cfg or P5.evidence
    n = max(1, int(math.ceil((duration or 0.0) / cfg.coverage_bin_seconds)))
    out = {}
    for mod in MODALITIES:
        bins = [False] * n
        for r in records:
            if r.modality != mod:
                continue
            a = max(0, int(r.start_seconds // cfg.coverage_bin_seconds))
            b = min(n - 1, int(r.end_seconds // cfg.coverage_bin_seconds))
            for i in range(a, b + 1):
                bins[i] = True
        covered = sum(bins)
        gaps, start = [], None
        for i, v in enumerate(bins):
            if not v and start is None:
                start = i
            elif v and start is not None:
                gaps.append([round(start * cfg.coverage_bin_seconds, 2),
                             round(i * cfg.coverage_bin_seconds, 2)])
                start = None
        if start is not None:
            gaps.append([round(start * cfg.coverage_bin_seconds, 2),
                         round(duration or n * cfg.coverage_bin_seconds, 2)])
        # Every gap, not a sample. coverage_in_window() subtracts uncovered time
        # from the window, so a truncated list makes the dropped gaps read as
        # COVERED -- a modality with no evidence at all reported 80% coverage.
        # Worst case is one gap per bin, which for a 3-minute video is ~180
        # entries: cheap, and correctness is not negotiable here.
        out[mod] = {'bins': n, 'covered': covered,
                    'ratio': round(covered / n, 3),
                    'gaps': gaps}
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 298: print('§56/§57 health and coverage loaded.')
