"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 115.
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
def _stage_key_of(obj: dict, path=None) -> str:
    """The cache key an upstream artifact was filed under."""
    if isinstance(obj, dict):
        k = ((obj.get('provenance') or {}).get('cache_key')
             or obj.get('cache_key'))
        if k:
            return str(k)
    if path:
        m = re.search(r'__([0-9a-f]{8,})\.json$', str(path))
        if m:
            return m.group(1)
    return ''

def _asr_keys(video, g, vh, ph):
    return [stage_key('asr', g['ASR_STAGE_VERSION'], [vh],
                      {'asr': asdict(g['P2'].asr)})]

def _ocr_keys(video, g, vh, ph):
    return [stage_key('ocr', g['OCR_STAGE_VERSION'], [vh, ph],
                      {'ocr': asdict(g['P2'].ocr), 'dedupe': asdict(g['P2'].dedupe)})]

def _visual_keys(video, g, vh, ph):
    """
    Every rung of Phase 3's OOM ladder, best first.

    Phase 3 does NOT key on P3.vision. It resolves a per-video budget from the
    duration and scene count, then walks a ladder of reduced budgets, and files
    the artifact under the rung that actually ran. On the 84 s video it asked
    for 48 frames @ 200704 px, OOM'd, and landed on 12 @ 100352 -- a complete,
    legitimate artifact keyed to that rung.

    Keying on the raw config asks for a rung that OOM'd and was never written,
    so it finds nothing and falls back, which is how this function was wrong on
    its first real run. run_vision_stage() probes every rung before running;
    reproducing the same probe is what makes Phase 5 accept the same file.
    """
    import dataclasses
    # The rungs depend on the video's duration and cut count, so this needs the
    # manifest. A caller that did not supply one gets NO visual key rather than
    # an exception -- "I cannot compute this" is the same answer as a config
    # that is not loaded, and it must not take the other two stages down with
    # it. Drift in the key formula itself still raises, below.
    mpath = video.get('manifest_path')
    if not mpath or not Path(mpath).exists():
        return []
    manifest = read_json(mpath)
    dur = float(video.get('duration_s')
                or (manifest.get('media') or {}).get('duration_seconds') or 0.0)
    vcfg = g['resolve_vision_config'](g['P3'].vision, dur,
                                      g['scene_count_of'](manifest))
    # The key run_vision_stage actually writes under carries the RESOLVED
    # model as well (VLM 1.11.0), so that a hosted artifact and a local one can
    # never collide. Rebuilding the key without it produced six keys that could
    # not match anything on disk, on every video, forever -- and the fallback
    # quietly covered for it. plan_vlm_load is deterministic here: a hosted
    # provider returns its model outright, and the local path keys on TOTAL
    # VRAM, which is a stable property of the card rather than a reading that
    # drifts between runs.
    _planned_vlm = list((g['plan_vlm_load'](vcfg) or [(None, None)])[0])
    out = []
    for n, p in g['vision_ladder'](vcfg):
        # built exactly as run_vision_stage builds it, or the keys will not match
        c = (vcfg if (n, p) == (vcfg.max_frames, vcfg.max_pixels)
             else dataclasses.replace(vcfg, max_frames=n, max_pixels=p))
        out.append(stage_key('visual', g['VLM_STAGE_VERSION'], [vh, ph],
                             {'vision': asdict(c), 'prompt': g['PROMPT_VERSION'],
                              'vlm': _planned_vlm}))
    return out

_STAGE_SPECS = (
    # name, key builder, globals it needs
    ('transcript', _asr_keys, ('ASR_STAGE_VERSION', 'P2')),
    ('ocr', _ocr_keys, ('OCR_STAGE_VERSION', 'P2')),
    ('visual', _visual_keys, ('VLM_STAGE_VERSION', 'PROMPT_VERSION', 'P3',
                              'resolve_vision_config', 'vision_ladder',
                              'scene_count_of', 'plan_vlm_load')),
)

def expected_stage_keys(video: dict) -> dict:
    """
    {stage: [acceptable cache keys, best first]} for the CURRENT config.

    One key for speech and OCR. Visual is a LIST, because a degraded rung is a
    real artifact and not a mismatch -- see _visual_keys.

    A stage whose config is absent is OMITTED, not guessed: the standalone
    Phase 5 notebook has no P2/P3 and must fall back honestly. But a config
    that IS present and fails to produce a key raises, because that means a
    name drifted upstream and silently falling back would hide it.
    """
    g, out = globals(), {}
    vh, ph = video['video_hash'], video.get('plan_hash', '')
    for name, build, needs in _STAGE_SPECS:
        if any(n not in g for n in needs):
            continue                      # this notebook does not load that phase
        keys = build(video, g, vh, ph)
        if keys:                          # an empty list means "cannot compute"
            out[name] = keys
    return out

def select_artifact(vdir, prefix: str, expected_keys='',
                    verbose: bool = True) -> tuple:
    """
    (artifact, path, how) where how is 'exact', 'fallback' or 'missing'.

    `expected_keys` is one key or an ordered list of acceptable ones, best
    first -- the visual stage has several because any rung of the OOM ladder is
    a legitimate artifact.

    'exact'     a file the current config names -- reproducible across runs.
    'fallback'  none of them is on disk, so the newest one is used INSTEAD.
                It was built under a different config, and the evidence key
                will honestly reflect that, but the pairing is a guess and is
                reported rather than swallowed.
    """
    vdir = Path(vdir)
    # None is the normal case, not an error: expected_stage_keys OMITS a stage
    # whose config is not loaded or whose manifest is unreadable, so every
    # caller doing exp.get('visual') hands us None. Iterating that raised
    # TypeError and would have taken §61 down the moment any stage could not be
    # keyed -- the exact situation the manifest guard was added to survive.
    if not expected_keys:
        expected_keys = []
    elif isinstance(expected_keys, str):
        expected_keys = [expected_keys]
    for i, k in enumerate(expected_keys):
        p = vdir / f'{prefix}__{k}.json'
        if p.exists():
            if verbose and i:
                print(f'  {prefix}: matched variant {i + 1} of '
                      f'{len(expected_keys)} -- a reduced budget that ran '
                      f'after the fuller one did not')
            return read_json(p), p, 'exact'
    hits = list(vdir.glob(f'{prefix}__*.json'))
    if not hits:
        return None, None, 'missing'
    # newest by MTIME, never lexicographic: the name carries a hash, so
    # alphabetical order picks whichever digest happens to sort highest.
    p = max(hits, key=lambda q: q.stat().st_mtime)
    if verbose:
        why = (f'none of the {len(expected_keys)} key(s) the current config '
               f'accepts is on disk' if expected_keys
               else 'the config that built it is not loaded in this notebook')
        print(f'  WARNING {prefix}: {why}; using the newest of {len(hits)} '
              f'({p.name})')
    return read_json(p), p, 'fallback'

def build_evidence(video: dict, transcript: dict = None, ocr: dict = None,
                   visual: dict = None, cfg: Phase5Config = None,
                   force: bool = False, verbose: bool = True) -> dict:
    """
    Every observation from every modality, on one timeline. Never raises.

    A modality that did not run is reported as not-run; it is not an error, and
    Phase 6 needs to be able to tell the difference between absent evidence and
    absent looking.
    """
    cfg = cfg or P5
    ec = cfg.evidence
    t0 = time.time()

    vdir = DIRS['artifacts'] / video['video_hash']
    manifest = read_json(video['manifest_path'])
    meta = read_json(vdir / 'media_meta.json') if (vdir / 'media_meta.json').exists() else {}
    scenes = read_json(vdir / 'scenes.json') if (vdir / 'scenes.json').exists() else {}
    duration = float((meta or {}).get('duration_seconds')
                     or video.get('duration_s') or 0.0)

    asr_k = _stage_key_of(transcript)
    ocr_k = _stage_key_of(ocr)
    vis_k = _stage_key_of(visual)

    key = stage_key('evidence', EVIDENCE_STAGE_VERSION,
                    [video['video_hash'], video['plan_hash'], asr_k, ocr_k, vis_k],
                    {'evidence': asdict(ec)})
    path = vdir / f'evidence__{key}.json'
    if path.exists() and not force:
        if verbose:
            print(f'  EVIDENCE CACHE HIT ({key})')
        return read_json(path)

    flags = []
    records = []
    records += speech_records(transcript, duration, asr_k, ec)
    records += ocr_records(ocr, manifest, duration, ocr_k, ec)
    records += visual_records(visual, manifest, duration, vis_k, ec)
    records += metadata_records(meta, scenes, duration, ec)

    flags += link_text_overlays(records, ec)
    records, merge_flags = merge_visual_intervals(records, ec)
    flags += merge_flags
    records.sort(key=lambda r: (r.start_seconds, r.modality, r.type))

    # every timestamp must land inside the video -- plan.md §5 exit criterion
    out_of_range = [r.id for r in records
                    if duration and (r.start_seconds < -0.001
                                     or r.end_seconds > duration + 0.001)]
    if out_of_range:
        flags.append({'code': 'TIMESTAMP_OUT_OF_RANGE',
                      'detail': f'{len(out_of_range)} record(s): {out_of_range[:3]}'})
        for r in records:
            if r.id in set(out_of_range):
                r.start_seconds = max(0.0, min(r.start_seconds, duration))
                r.end_seconds = max(0.0, min(r.end_seconds, duration))
                r.flags.append('CLAMPED_TO_VIDEO')

    # Ids hash (modality, type, start to 2dp, text). Two records can collide --
    # same type, same text, starting within 10 ms. Flagging without resolving
    # would leave Phase 6 citing an ambiguous id, so disambiguate in place and
    # keep the original for traceability.
    seen_ids, dup = {}, []
    for r in records:
        if r.id in seen_ids:
            dup.append(r.id)
            seen_ids[r.id] += 1
            r.flags.append(f'ID_COLLISION_RESOLVED:{r.id}')
            r.id = f'{r.id}_{seen_ids[r.id]}'
        else:
            seen_ids[r.id] = 1
    if dup:
        flags.append({'code': 'EVIDENCE_ID_COLLISION',
                      'detail': f'{len(dup)} id(s) disambiguated: {dup[:3]}'})

    health = modality_health(transcript, ocr, visual, manifest, duration, ec)
    coverage = coverage_map(records, duration, ec)
    aggregates = derive_aggregates(records, duration, ec)

    evidence = {
        'schema_version': EVIDENCE_STAGE_VERSION,
        'video_id': video.get('video_id', ''),
        'video_hash': video['video_hash'],
        'plan_hash': video['plan_hash'],
        'duration_seconds': round(duration, 3),
        'cache_key': key,
        'records': [r.to_dict() for r in records],
        'modality_health': health,
        'can_fail_on': modes_that_can_fail(health),
        'coverage': coverage,
        'aggregates': aggregates,
        'flags': flags,
        'sources': {'asr': asr_k, 'ocr': ocr_k, 'visual': vis_k},
        'stats': {
            'records': len(records),
            'by_modality': aggregates['records_by_modality'],
            'linked': sum(1 for r in records if r.linked_ids),
            'merged': sum(len(r.merged_from) for r in records),
            'ocr_independent': sum(1 for r in records
                                   if r.modality == 'ocr'
                                   and r.independence == 'confirmed_independent'),
            'unusable_records': sum(1 for r in records if not r.satisfies_modes),
        },
        'provenance': provenance('evidence', EVIDENCE_STAGE_VERSION, key,
                                 time.time() - t0),
    }
    write_json(path, evidence)
    if verbose:
        print(f'  evidence -> {path.name}  ({len(records)} records)')
    return evidence

def evidence_for(video_hash: str, cfg: Phase5Config = None,
                 video: dict = None) -> Optional[dict]:
    """
    Fetch an evidence artifact for a video without rebuilding it.

    Pass `video` (the TARGET dict) and this resolves the EXACT artifact the
    current config produces, by recomputing the same key build_evidence would.
    Without it, it returns the newest on disk -- correct only while a single
    configuration has ever been run for this video, which is precisely the
    assumption that broke for the 84 s test video.
    """
    vdir = DIRS['artifacts'] / video_hash
    if not vdir.exists():
        return None
    if video:
        exp = expected_stage_keys(video)
        ks = [_stage_key_of(select_artifact(vdir, pre, exp.get(name),
                                            verbose=False)[0])
              for name, pre in (('transcript', 'transcript'),
                                ('ocr', 'ocr'), ('visual', 'visual'))]
        key = stage_key('evidence', EVIDENCE_STAGE_VERSION,
                        [video['video_hash'], video.get('plan_hash', '')] + ks,
                        {'evidence': asdict((cfg or P5).evidence)})
        p = vdir / f'evidence__{key}.json'
        if p.exists():
            return read_json(p)
    files = list(vdir.glob('evidence__*.json'))
    if not files:
        return None
    # By mtime. The filename carries a hash, so alphabetical order is arbitrary
    # and "the last one" would be whichever hash happens to sort highest.
    return read_json(max(files, key=lambda p: p.stat().st_mtime))

def load_records(evidence: dict) -> list:
    """evidence.json -> EvidenceRecord objects, for the accessors."""
    out = []
    for d in (evidence or {}).get('records', []) or []:
        d = dict(d)
        d['satisfies_modes'] = tuple(d.get('satisfies_modes') or ())
        try:
            out.append(EvidenceRecord(**d))
        except TypeError:
            keep = {k: v for k, v in d.items()
                    if k in EvidenceRecord.__dataclass_fields__}
            out.append(EvidenceRecord(**keep))
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 337: print('§59 evidence stage loaded.  Artifacts -> work/artifacts/{video_hash}/
