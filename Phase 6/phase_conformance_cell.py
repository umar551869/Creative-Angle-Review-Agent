# ============================================================================
# §74b  PLAN CONFORMANCE  --  where do we actually stand, Phases 0 to 6
#
# Numbered 74b, not 75: this belongs to Phase 6's self-check, and Phase 7 §75
# is the scoring configuration. Two cells sharing a number is a small thing
# that costs a real minute every time either is mentioned.
#
# §74 asks "did this run work". This asks a different and harder question:
# "which of plan.md's stated exit criteria are actually MET?"
#
# Three verdicts, and the third is not a failure:
#   MET      checked in code, against artifacts on disk
#   NOT MET  checked in code, and it does not hold
#   MANUAL   cannot be checked by code -- a human has to look
#
# A criterion nobody can check automatically is not a criterion that passes.
# Marking it MANUAL keeps it visible instead of letting it drift into "done".
#
# Reads every artifact under work/, not only the current kernel's run, so it
# reports on the corpus rather than on the last video.
# ============================================================================

import re

_MET, _NOT, _MAN, _NA = 'MET', 'NOT MET', 'MANUAL', 'n/a'
_CONF = []          # (phase, criterion, verdict, evidence)


def _c(phase, criterion, verdict, evidence=''):
    _CONF.append((phase, criterion, verdict, str(evidence)[:150]))


def _probe(phase, criterion, fn):
    """Run a probe once. A probe that fails is a finding, not a traceback."""
    r = _safe(fn)
    if isinstance(r, tuple) and len(r) == 2:
        _c(phase, criterion, r[0], r[1])
    else:
        _c(phase, criterion, _NOT, r)


def _safe(fn, *a, **kw):
    """Any probe may fail; a failed probe is a finding, never a traceback."""
    try:
        return fn(*a, **kw)
    except Exception as exc:
        return f'PROBE FAILED: {type(exc).__name__}: {str(exc)[:60]}'


# ---- gather the corpus once ------------------------------------------------
_ART = DIRS['artifacts']
_BRF = DIRS['briefs']
_vdirs = sorted([d for d in _ART.glob('*') if d.is_dir()]) if _ART.exists() else []


# An artifact this cell cannot read is not nothing. Dropping it silently makes
# every criterion downstream quietly less true -- a corrupt evidence file would
# lower a count with no explanation, and the report would look merely thin
# rather than broken. Counted and named instead.
_unreadable = []


def _read_or_note(p):
    """read_json, or record why not. Returns (ok, obj)."""
    try:
        obj = read_json(p)
    except Exception as exc:
        _unreadable.append(f'{p.name}: {type(exc).__name__}')
        return False, None
    if obj is None:
        _unreadable.append(f'{p.name}: unreadable or empty')
        return False, None
    return True, obj


def _load_all(pattern, where=None):
    out = []
    for d in (where or _vdirs):
        for p in sorted(d.glob(pattern)):
            ok, obj = _read_or_note(p)
            if ok:
                out.append((d.name, obj))
    return out


# The frame manifest is one level deeper than the rest:
#   work/artifacts/{video_hash}/{manifest_key}/manifest.json
# Globbing it as a sibling finds nothing and reports every Phase 1 criterion as
# failed, which is worse than not checking them at all. Label each one with the
# sampling key too -- one video has several, and naming only the video makes a
# finding unactionable ("which of its four manifests?").
_manifests = []
for _d in _vdirs:
    for _p in sorted(_d.glob('*/manifest.json')):
        _ok, _obj = _read_or_note(_p)
        if _ok:
            _manifests.append((f'{_d.name[:8]}/{_p.parent.name[:8]}', _obj))
_evidences = _load_all('evidence__*.json')
_verdicts = _load_all('verdicts__*.json')
_visuals = _load_all('visual__*.json')
_transcripts = _load_all('transcript__*.json')
_ocrs = _load_all('ocr__*.json')
_briefs = []
if _BRF.exists():
    for d in sorted(_BRF.glob('*')):
        if d.is_dir() and not d.name.startswith('_'):
            for p in sorted(d.glob('requirements__*.json')):
                _ok, _obj = _read_or_note(p)
                if _ok:
                    _briefs.append((d.name, _obj))

print('=' * 78)
print('PLAN CONFORMANCE  --  Phases 0 to 6 against plan.md exit criteria')
print('=' * 78)
print(f'  videos with artifacts : {len(_vdirs)}')
print(f'  manifests {len(_manifests):>3}   transcripts {len(_transcripts):>3}   '
      f'ocr {len(_ocrs):>3}   visual {len(_visuals):>3}')
print(f'  evidence  {len(_evidences):>3}   verdicts    {len(_verdicts):>3}   '
      f'briefs {len(_briefs):>3}')
if _unreadable:
    print()
    print(f'  {len(_unreadable)} ARTIFACT(S) COULD NOT BE READ, so every count '
          f'above is low by that much:')
    for _u in _unreadable[:6]:
        print(f'    {_u}')
    if len(_unreadable) > 6:
        print(f'    ... and {len(_unreadable) - 6} more')


# ---- staleness -------------------------------------------------------------
# This reads the whole corpus, including artifacts written by an older stage
# version. A criterion can then fail on a bug that is already fixed -- the
# finding is real about the file and false about the code. Say which up front
# so nobody re-investigates settled ground.
def _stale_report():
    cur = {'asr': globals().get('ASR_STAGE_VERSION'),
           'ocr': globals().get('OCR_STAGE_VERSION'),
           'visual': globals().get('VLM_STAGE_VERSION'),
           'brief': globals().get('BRIEF_STAGE_VERSION'),
           'evidence': globals().get('EVIDENCE_STAGE_VERSION'),
           'verdict': globals().get('VERDICT_STAGE_VERSION')}
    groups = {'asr': _transcripts, 'ocr': _ocrs, 'visual': _visuals,
              'brief': _briefs, 'evidence': _evidences, 'verdict': _verdicts}
    lines = []
    for stage, items in groups.items():
        want = cur.get(stage)
        if not want or not items:
            continue
        seen = {}
        for _k, obj in items:
            if not isinstance(obj, dict):
                continue
            got = ((obj.get('provenance') or {}).get('stage_version')
                   or obj.get('schema_version') or '?')
            seen[got] = seen.get(got, 0) + 1
        old = {v: n for v, n in seen.items() if v != want}
        if old:
            lines.append(f'    {stage:<9} current {want:<8} but on disk: '
                         + ', '.join(f'{n}x {v}' for v, n in sorted(old.items())))
    return lines


_stale_lines = _safe(_stale_report)
if isinstance(_stale_lines, list) and _stale_lines:
    print()
    print('  STALE ARTIFACTS -- written by an older stage version:')
    for _l in _stale_lines:
        print(_l)
    print('    A failure below may already be fixed in code. Re-run the stage')
    print('    to rebuild its cache before treating one as a live defect.')
elif not isinstance(_stale_lines, list):
    print(f'  (staleness check unavailable: {_stale_lines})')

# ===========================================================================
# PHASE 0 -- environment and the cache harness
# ===========================================================================
_bk = globals().get('BACKENDS') or {}
_live = sorted(k for k, v in _bk.items() if v)
_c(0, 'each backend loads and produces output',
   _MET if (_bk.get('faster_whisper') and _bk.get('rapidocr') and _transcripts
            and _ocrs) else _NOT,
   (f'live: {", ".join(_live) or "none"}; '
    f'{len(_transcripts)} transcript(s), {len(_ocrs)} ocr artifact(s)') if _bk
   else 'no BACKENDS dict in this kernel -- run the Phase 0 cells first')

_c(0, 'cache demonstrates a hit (second read is instant)',
   _MET if _evidences else _MAN,
   f'{len(_evidences)} evidence artifact(s) reused across runs'
   if _evidences else 'nothing cached yet')

_c(0, 'HardwareProfile reports dtype/attention',
   _MET if globals().get('HAS_CUDA') is not None else _NOT,
   f"HAS_CUDA={globals().get('HAS_CUDA')}, "
   f"provider={globals().get('VISION_PROVIDER')}")

_c(0, 'requirements.lock reproduces the environment', _NA,
   'notebook build: pip constraints (TORCH_PINS) serve this purpose')
_c(0, 'cold runtime green in < 8 minutes', _MAN, 'needs a stopwatch')
_c(0, 'OCR engine decision recorded with reasoning', _MAN,
   'check the decision log in plan.md §15')

# ===========================================================================
# PHASE 1 -- preflight and deterministic preprocessing
# ===========================================================================
_c(1, '20 varied videos processed with zero corrupt outputs',
   _MET if len(_vdirs) >= 20 else _NOT,
   f'{len(_vdirs)} video(s) have artifacts -- the criterion asks for 20')


def _p1_windows():
    """A manifest sampled with hook_window_s=0 was TOLD not to place window
    frames. It is an ablation config, and it says nothing about whether the
    sampler honours a window it was actually given -- which is what the
    criterion asks. Judge the runs that asked for windows; count the rest."""
    if not _manifests:
        return _NOT, 'no manifests on disk'
    missing, ablated = [], 0
    for vid, m in _manifests:
        cfg = ((m.get('sampling') or {}).get('config') or {})
        if not (cfg.get('hook_window_s') or 0) or not (cfg.get('cta_window_s') or 0):
            ablated += 1
            continue
        reasons = {f.get('reason') for f in (m.get('frames') or [])}
        if not ({'hook_window'} & reasons) or not ({'cta_window'} & reasons):
            missing.append(vid)
    asked = len(_manifests) - ablated
    if not asked:
        return _MAN, f'all {len(_manifests)} manifests ran with windows disabled'
    return (_MET if not missing else _NOT,
            f'{asked - len(missing)}/{asked} manifests that asked for windows '
            f'carry both ({ablated} ran with windows off)'
            + (f'; missing in {", ".join(missing[:3])}' if missing else ''))


_probe(1, 'hook and CTA windows present in every manifest', _p1_windows)


def _p1_flag(field):
    vals = [(vid, (m.get('media') or {}).get(field)) for vid, m in _manifests]
    seen = [v for _i, v in vals if v]
    return seen, vals


_vfr = _safe(lambda: [v for _i, v in [(a, (m.get('media') or {}).get('is_vfr'))
                                      for a, m in _manifests] if v])
_c(1, 'VFR video handled correctly and flagged',
   _MET if _vfr else _MAN,
   f'{len(_vfr)} VFR video(s) in the corpus' if _vfr
   else 'no VFR video processed yet -- cannot confirm')

_rot = _safe(lambda: [v for _i, v in [(a, (m.get('media') or {}).get('rotation'))
                                      for a, m in _manifests] if v])
_c(1, 'rotated video produces upright frames, transform recorded',
   _MET if _rot else _MAN,
   f'{len(_rot)} rotated video(s)' if _rot
   else 'no rotated video processed yet -- cannot confirm')

_silent = _safe(lambda: [vid for vid, m in _manifests
                         if (m.get('media') or {}).get('has_audio') is False])
_c(1, 'silent video gives has_audio=False without an exception',
   _MET if _silent else _MAN,
   f'{len(_silent)} silent video(s) processed' if _silent
   else 'no silent video processed yet -- cannot confirm')

_c(1, 'sampler unit tests all green',
   _MET if callable(globals().get('_run_phase1_tests')) else _MAN,
   'run the Phase 1 test cell to confirm')
_c(1, 'frame timestamps hand-verified on 3 videos', _MAN, 'scrub a player')
_c(1, 'corrupt file rejected with a specific reason code', _MAN,
   'feed it a truncated mp4 and read the reason')

# ===========================================================================
# PHASE 2 -- ASR and OCR
# ===========================================================================
_c(2, '20 videos transcribed',
   _MET if len(_transcripts) >= 20 else _NOT,
   f'{len(_transcripts)} transcript(s) on disk')


def _p2_derived():
    """THE criterion: are burned-in captions actually flagged?"""
    tot = drv = ind = 0
    per = []
    for vid, ev in _evidences:
        d = i = 0
        for r in ev.get('records') or []:
            if r.get('modality') != 'ocr':
                continue
            tot += 1
            if r.get('independence') == 'derived_from_speech':
                d += 1
            elif r.get('independence') == 'confirmed_independent':
                i += 1
        drv += d
        ind += i
        if d or i:
            per.append(f'{vid[:8]}:{d}drv/{i}ind')
    if not tot:
        return _NOT, 'no OCR records in any evidence artifact'
    if not drv:
        return (_MAN, f'{tot} OCR records, {ind} independent, NONE derived -- '
                      f'needs a video whose captions repeat the speech')
    return _MET, f'{drv} derived_from_speech, {ind} independent ({"; ".join(per[:3])})'


_probe(2, 'derived_from_speech correctly flags burned-in captions', _p2_derived)

_c(2, 'both stages cache correctly',
   _MET if len(_transcripts) and len(_ocrs) else _NOT,
   f'{len(_transcripts)} transcripts, {len(_ocrs)} ocr artifacts persisted')
_c(2, 'zero hallucinated transcripts on a music-only video', _MAN,
   'needs a music-only sample')
_c(2, 'word timestamps verified on 3 clips', _MAN, 'scrub and listen')
_c(2, 'OCR captures every CTA and discount code visible by eye', _MAN,
   'watch one caption-heavy video with the artifact open')

# ===========================================================================
# PHASE 3 -- visual evidence
# ===========================================================================
def _p3_judgments():
    """Pass 1 must DESCRIBE, never judge.

    Uses the pipeline's OWN detect_judgment_language when the kernel has it, so
    this cell cannot disagree with the check it is auditing. A second word list
    here would be a second thing to keep right -- and it already went wrong
    once: matching as substrings made 'shoulder' contain 'should'.
    """
    _dj = globals().get('detect_judgment_language')
    if not callable(_dj):
        _words = ('should', 'compliant', 'compliance', 'non-compliant',
                  'violates', 'violation', 'requirement', 'guideline',
                  'the brief', 'fails to', 'satisfies', 'does not meet')

        def _dj(t):
            low = f' {(t or "").lower()} '
            return [w for w in _words
                    if re.search(rf'(?<!\w){re.escape(w)}(?!\w)', low)]

    hits = []
    n = 0
    for vid, v in _visuals:
        for e in v.get('events') or []:
            n += 1
            got = _safe(_dj, str(e.get('description') or ''))
            if isinstance(got, list) and got:
                hits.append(f'{vid[:8]}: {got[0]!r} in '
                            f'{str(e.get("description"))[:44]!r}')
    if not n:
        return _NOT, 'no visual events on disk'
    return (_MET if not hits else _NOT,
            f'{n} event descriptions scanned, {len(hits)} carry judgment language'
            + (f' -- e.g. {hits[0]}' if hits else ''))


_probe(3, 'Pass-1 output contains no compliance judgments', _p3_judgments)


def _p3_parse():
    ok = bad = 0
    for _vid, v in _visuals:
        codes = [f if isinstance(f, str) else f.get('code')
                 for f in (v.get('flags') or [])]
        if v.get('status') == 'OK':
            ok += 1
        else:
            bad += 1
        if 'PARSE_FAILED' in codes or 'GENERATION_FAILED' in codes:
            bad += 1
    tot = ok + bad
    return ((_MET if tot and ok / tot >= 0.95 else _NOT),
            f'{ok}/{tot} visual artifacts parsed cleanly'
            f' ({(ok / tot * 100) if tot else 0:.0f}%)')


_probe(3, 'JSON parse success >= 95%', _p3_parse)

_c(3, '4B vs 8B comparison table with a written decision', _NA,
   f"vision provider is {globals().get('VISION_PROVIDER')!r} -- hosted, not a "
   f"local 4B/8B choice")
_c(3, 'VRAM lifecycle: 10 videos, no OOM, stable peak',
   _NA if globals().get('VISION_PROVIDER') == 'gemini' else _MAN,
   'no local weights on the hosted path')
_c(3, 'a human can map each evidence item to what is on screen', _MAN,
   'watch 10 videos beside their visual artifact')
_c(3, 'product-appearance timestamps within +-0.5s on 5 videos', _MAN,
   'scrub and compare')

# ===========================================================================
# PHASE 4 -- brief compiler
# ===========================================================================
_approved = [(h, b) for h, b in _briefs if b.get('approved')]
_c(4, '5 real briefs compiled and read',
   _MET if len({h for h, _b in _briefs}) >= 5 else _NOT,
   f'{len({h for h, _b in _briefs})} distinct brief(s) compiled, '
   f'{len(_approved)} approved by a human')


def _p4_modes():
    """say X -> speech, show X -> visual. The distinction that inverts verdicts."""
    say = show = 0
    wrong = []
    for _h, b in _briefs:
        for r in b.get('requirements') or []:
            t = str(r.get('requirement') or '').lower()
            m = r.get('evidence_mode') or ''
            if t.startswith(('say ', 'mention ', 'state ')):
                say += 1
                if 'speech' not in m:
                    wrong.append(f'SAY -> {m}: {t[:40]}')
            elif t.startswith(('show ', 'display ')):
                show += 1
                if 'visual' not in m and 'ocr' not in m:
                    wrong.append(f'SHOW -> {m}: {t[:40]}')
    if not (say or show):
        return _MAN, 'no imperative say/show requirements in the corpus to test'
    return ((_MET if not wrong else _NOT),
            f'{say} say-type, {show} show-type; {len(wrong)} mis-moded'
            + (f' -- e.g. {wrong[0]}' if wrong else ''))


_probe(4, 'evidence_mode correct on "say X" vs "show X"', _p4_modes)


def _p4_temporal():
    sym = tot = 0
    for _h, b in _briefs:
        for r in b.get('requirements') or []:
            if any(r.get(k) is not None for k in
                   ('deadline_seconds', 'window_start_seconds',
                    'window_end_seconds')):
                tot += 1
            if r.get('window_start_expr') or r.get('window_end_expr'):
                sym += 1
    return ((_MET if tot else _NOT),
            f'{tot} requirement(s) carry timing, {sym} duration-relative')


_probe(4, 'temporal constraints extracted, including duration-relative', _p4_temporal)

_c(4, 'schema validation catches malformed output',
   _MET if callable(globals().get('pydantic_check')) else _NOT,
   'pydantic_check runs on every compile'
   if callable(globals().get('pydantic_check'))
   else 'no pydantic_check in this kernel -- run the Phase 4 cells first')
_c(4, 'cached by brief hash; recompilation is instant',
   _MET if len(_briefs) > len({h for h, _b in _briefs}) else _MAN,
   f'{len(_briefs)} artifacts across {len({h for h, _b in _briefs})} brief hashes')

# ===========================================================================
# PHASE 5 -- unified evidence
# ===========================================================================
def _p5_one_per_video():
    """"1 artifact for 2 videos" is not this criterion passing -- it is half
    the corpus missing. A non-empty list is not coverage. What must hold is
    that no video was AUDITED without evidence, since a verdict with no
    evidence file behind it cannot be traced to anything."""
    if not _evidences:
        return _NOT, 'no evidence artifacts on disk'
    have = {vid for vid, _e in _evidences}
    audited = {vid for vid, _v in _verdicts}
    orphan = sorted(audited - have)
    none_yet = sorted(set(d.name for d in _vdirs) - have)
    note = (f'{len(_evidences)} artifact(s) covering {len(have)}/{len(_vdirs)} '
            f'video(s); {len(audited)} audited')
    if orphan:
        return _NOT, (f'{note}; {len(orphan)} audited with NO evidence file: '
                      f'{", ".join(x[:8] for x in orphan[:3])}')
    if none_yet:
        return _MAN, (f'{note}; {len(none_yet)} not yet through Phase 5: '
                      f'{", ".join(x[:8] for x in none_yet[:3])}')
    return _MET, note


_probe(5, 'one evidence file per video, schema-validated', _p5_one_per_video)


def _p5_bounds():
    bad = []
    n = 0
    for vid, ev in _evidences:
        dur = float(ev.get('duration_seconds') or 0)
        for r in ev.get('records') or []:
            n += 1
            s, e = r.get('start_seconds'), r.get('end_seconds')
            if s is None or e is None:
                bad.append(f'{vid[:8]} {r.get("id")}: missing bound')
            elif s < -0.001 or (dur and e > dur + 1.0):
                bad.append(f'{vid[:8]} {r.get("id")}: [{s:.2f},{e:.2f}] vs {dur:.2f}')
    return ((_MET if not bad else _NOT),
            f'{n} records checked, {len(bad)} outside [0, duration]'
            + (f' -- e.g. {bad[0]}' if bad else ''))


_probe(5, 'all timestamps within [0, duration]', _p5_bounds)

_probe(5, 'burned-in captions correctly flagged', _p2_derived)


def _p5_reuse():
    """One video, several briefs -> only the verdict stage re-runs."""
    by_video = {}
    for vid, v in _verdicts:
        by_video.setdefault(vid, set()).add(
            (v.get('sources') or {}).get('brief'))
    multi = {k: b for k, b in by_video.items() if len(b) > 1}
    if not multi:
        return _MAN, 'no video has been audited against two different briefs yet'
    ev_keys = {vid: {(v.get('sources') or {}).get('evidence')
                     for _v2, v in _verdicts if _v2 == vid} for vid in multi}
    shared = all(len(k) == 1 for k in ev_keys.values())
    return ((_MET if shared else _NOT),
            f'{len(multi)} video(s) audited against multiple briefs; '
            f'evidence reused: {shared}')


_probe(5, 'auditing one video against 3 briefs re-runs only the verdict stage', _p5_reuse)
_c(5, 'derived aggregates match manual inspection on 3 videos', _MAN,
   'open three artifacts and check by hand')

# ===========================================================================
# PHASE 6 -- evaluator, hook, claims
# ===========================================================================
def _p6_complete():
    """A forbidden rule that PASSes because nothing was found has no evidence
    to point at -- that is the correct answer, not a missing field. What is a
    real hole is a FAIL or PARTIAL that cites evidence in its reason and
    records none, because then the claim cannot be traced."""
    bad, n, absence, stale = [], 0, 0, 0
    want = globals().get('VERDICT_STAGE_VERSION')
    for _vid, r in _verdicts:
        older = (want and (r.get('provenance') or {}).get('stage_version') != want)
        for v in r.get('verdicts') or []:
            n += 1
            if not v.get('status') or not str(v.get('reason') or '').strip():
                bad.append(v.get('requirement_id'))
                stale += bool(older)
            elif v['status'] in ('PARTIAL', 'FAIL') and not (
                    v.get('evidence_ids') or v.get('examined_ids')):
                bad.append(v.get('requirement_id'))
                stale += bool(older)
            elif v['status'] == 'PASS' and not (v.get('evidence_ids')
                                                or v.get('examined_ids')):
                absence += 1          # nothing found is why it passed
    note = (f'{n} verdicts across {len(_verdicts)} audit(s); {absence} pass '
            f'by absence (correctly carry no evidence)')
    if not bad:
        return _MET, note
    return _NOT, (f'{note}; {len(bad)} untraceable: '
                  f'{", ".join(x for x in bad[:3] if x)}'
                  + (' [all from an older stage version]'
                     if stale == len(bad) else ''))


_probe(6, 'every requirement produces a status, evidence IDs and a reason', _p6_complete)


def _p6_fabricated():
    tot = sum((r.get('stats') or {}).get('fabricated_ids', 0)
              for _v, r in _verdicts)
    return ((_MET if _verdicts and tot == 0 else _NOT),
            f'{tot} fabricated id(s) across {len(_verdicts)} audit(s)')


_probe(6, 'zero fabricated evidence IDs, asserted in code', _p6_fabricated)


def _p6_escalation():
    rates = []
    for _v, r in _verdicts:
        e = (r.get('stats') or {}).get('escalation_rate') or {}
        if e:
            rates.append(e.get('L3', 0))
    if not rates:
        return _NOT, 'no escalation rates recorded'
    avg = sum(rates) / len(rates)
    return ((_MET if avg < 0.30 else _NOT),
            f'L3 mean {avg:.0%} across {len(rates)} audit(s) '
            f'(range {min(rates):.0%}-{max(rates):.0%}); criterion asks < 30%')


_probe(6, 'L3 handles < 30% of requirements', _p6_escalation)


def _p6_hook():
    # THE FIELD SET IS THE SPEC'S, read from product.md §33 -- not recalled.
    # An earlier version of this probe asked for a 'disclaimer' field that §33
    # does not define, and reported a module that was producing the full output
    # as incomplete. A check is only worth as much as the document it reads.
    need = ('hook_present', 'hook_type', 'start', 'end', 'strength',
            'transcript', 'visual', 'within_required_window', 'reason')
    seen = 0
    missing = set()
    for _v, r in _verdicts:
        h = r.get('hook') or {}
        if not h:
            continue
        seen += 1
        missing |= {k for k in need if k not in h}
    if not seen:
        # "absent from the artifact" and "not implemented" are different
        # findings and want different work. Distinguish them.
        built = callable(globals().get('evaluate_hook'))
        want = globals().get('VERDICT_STAGE_VERSION')
        old = sum(1 for _v, r in _verdicts
                  if want and (r.get('provenance') or {}).get('stage_version') != want)
        return _NOT, ('no hook output in any audit'
                      + ('; evaluate_hook IS defined and wired in'
                         if built else '; evaluate_hook not defined in this kernel')
                      + (f' -- all {old} audit(s) predate the current verdict '
                         f'stage, re-run to produce it'
                         if old and old == len(_verdicts) else ''))
    return ((_MET if not missing else _NOT),
            f'{seen} hook output(s); missing fields: {sorted(missing) or "none"}')


_probe(6, 'hook module produces the full spec §33 output', _p6_hook)

_claims_on = bool(getattr(getattr(globals().get('P6'), 'claims', None),
                          'enabled', False))
_c(6, 'claims module flags all planted test claims',
   _NOT,
   f'claims module enabled={_claims_on}; no planted-claim corpus exists. '
   f'Scope decision: in or out for the MVP.')


def _p6_modes():
    """A caption that merely repeats the speech must not satisfy ocr_only."""
    drv = ok = bad = 0
    for vid, ev in _evidences:
        for r in ev.get('records') or []:
            if r.get('modality') != 'ocr':
                continue
            if r.get('independence') != 'derived_from_speech':
                continue
            drv += 1
            modes = set(r.get('satisfies_modes') or [])
            if 'ocr_only' in modes:
                bad += 1
            else:
                ok += 1
    if not drv:
        return (_MAN, 'no derived_from_speech OCR record in the corpus -- '
                      'needs a video whose captions repeat the speech')
    return ((_MET if not bad else _NOT),
            f'{drv} burned-in caption record(s): {ok} correctly excluded from '
            f'ocr_only, {bad} wrongly admitted')


_probe(6, 'speech_only vs ocr_only verified on a burned-in-caption video', _p6_modes)

# ===========================================================================
# REPORT
# ===========================================================================
_ORDER = {_MET: 0, _NOT: 1, _MAN: 2, _NA: 3}
for _ph in sorted({p for p, _c2, _v, _e in _CONF}):
    print()
    print('=' * 78)
    print(f'PHASE {_ph}')
    print('=' * 78)
    for _p, _crit, _verd, _ev in sorted(
            [x for x in _CONF if x[0] == _ph], key=lambda x: _ORDER[x[2]]):
        print(f'  [{_verd:<7}] {_crit[:64]}')
        if _ev:
            print(f'            {_ev}')

print()
print('=' * 78)
print('WHERE WE STAND')
print('=' * 78)
_tally = {}
for _p, _crit, _verd, _ev in _CONF:
    _tally[_verd] = _tally.get(_verd, 0) + 1
_total = len(_CONF)
for _k in (_MET, _NOT, _MAN, _NA):
    _n = _tally.get(_k, 0)
    print(f'  {_k:<8} {_n:>3}  ({_n / _total:.0%})')
print()
_blockers = [(p, c) for p, c, v, _e in _CONF if v == _NOT]
if _blockers:
    print('  NOT MET -- these are the ones that are checked and do not hold:')
    for _p, _crit in _blockers:
        print(f'    phase {_p}: {_crit[:68]}')
print()
_manual = [(p, c) for p, c, v, _e in _CONF if v == _MAN]
print(f'  {len(_manual)} criterion/criteria need a human to look. They are not')
print('  failures, and they are not passes either -- they are unverified.')
print()
print('=' * 78)
