"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 129.
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
_STATUS_RANK = {'PASS': 0, 'PARTIAL': 1, 'UNCERTAIN': 2, 'FAIL': 3,
                'NOT_APPLICABLE': 4}

def _resolve_groups(verdicts: list, cfg: Phase6Config = None) -> list:
    """
    Collapse one_of / any_of groups to their best member.

    A brief that offers 12 hooks is not asking for 12 hooks. Treating each
    option as separately required is the single most effective way to produce a
    page of false FAILs, so the losers become NOT_APPLICABLE -- visible, and
    explained, rather than quietly dropped.
    """
    by_group = {}
    for v in verdicts:
        if v.group and v.group_mode in ('one_of', 'any_of'):
            by_group.setdefault(v.group, []).append(v)
    for gid, members in by_group.items():
        # Status first, then ALIGNMENT, then confidence.
        #
        # When twelve hook options all FAIL on literal wording, confidence picks
        # whichever the model felt surest about -- which is noise. Alignment
        # picks the one her actual opening most resembles, which is the only one
        # worth reporting to a human and the only one Phase 7 can fairly score.
        # Status first, then ALIGNMENT, then the BRIEF'S OWN ORDER.
        #
        # The last term used to be -confidence. For an L3 verdict that is
        # `llm_self_report` -- a number the model invented -- so two options
        # tying on status and alignment were separated by noise. Measured on a
        # fixed brief: two runs named 'Blow drying' as the hook she used, one
        # named 'My hair'. Both scored `strong`, so the score never moved, but
        # the report's factual claim about which hook she used was not
        # reproducible.
        #
        # Ordinal is the brief's own ordering, so a tie resolves to "the option
        # this brief listed first" -- arbitrary, but explicable to a human and
        # identical on every run. requirement_id is a final backstop; ids are
        # content-derived and stable too.
        best = min(members, key=lambda v: (_STATUS_RANK.get(v.status, 9),
                                           -alignment_rank(v.alignment),
                                           v.ordinal or 10 ** 6,
                                           v.requirement_id))
        for v in members:
            if v is best:
                v.flags.append(f'GROUP_SELECTED:{gid}({len(members)} options)')
                # A one_of group is ONE scoring unit, so the group's alignment
                # is the selected member's. Recorded on the flag so Phase 7 does
                # not have to re-derive which member won.
                if v.alignment:
                    v.flags.append(f'GROUP_ALIGNMENT:{v.alignment}')
                continue
            # What this option scored BEFORE it lost. Without it the
            # pre-collapse status is unrecoverable -- every loser reads
            # NOT_APPLICABLE -- and neither a human nor an exit criterion can
            # see that she was strongly aligned with an option that did not win.
            v.flags.append(f'GROUP_MEMBER_WAS:{v.status}/'
                           f'{v.alignment or "unjudged"}')
            v.status = 'NOT_APPLICABLE'
            _al = (f', alignment {best.alignment}' if best.alignment else '')
            v.reason = (f'Not the option satisfied for choice group '
                        f'{v.group_label or gid!r}: '
                        f'"{best.requirement_label}" was ({best.status}{_al}).')
            v.flags.append(f'GROUP_NOT_SELECTED:{gid}')
    return verdicts

def evaluate_requirements(video: dict, evidence: dict, compiled: dict,
                          cfg: Phase6Config = None, backend=None,
                          force: bool = False, verbose: bool = True,
                          allow_unapproved: bool = False) -> dict:
    """
    One video x one brief -> a verdict per requirement. Never raises.

    The brief is an INPUT to the cache key, never part of the video's identity,
    so three briefs against one video re-run only this stage.
    """
    cfg = cfg or P6
    t0 = time.time()
    vh = video['video_hash']
    vdir = DIRS['artifacts'] / vh
    duration = float(evidence.get('duration_seconds') or video.get('duration_s') or 0.0)

    key = stage_key('verdicts', VERDICT_STAGE_VERSION,
                    [vh, evidence.get('cache_key', ''),
                     compiled.get('brief_hash', ''), compiled.get('cache_key', '')],
                    {'p6': asdict(cfg)})
    path = vdir / f'verdicts__{key}.json'
    if path.exists() and not force:
        if verbose:
            print(f'  VERDICTS CACHE HIT ({key})')
        return read_json(path)

    try:
        reqs = resolve_brief_for_video(compiled, duration, allow_unapproved)
    except (ValueError, PermissionError) as exc:
        return {'status': 'BRIEF_NOT_USABLE', 'verdicts': [], 'cache_key': key,
                'flags': [{'code': 'BRIEF_NOT_USABLE', 'detail': str(exc)[:200]}]}

    records = load_records(evidence)
    health = evidence.get('modality_health') or {}
    can_fail = evidence.get('can_fail_on') or modes_that_can_fail(health)

    # Parsed once: a figure-fidelity rule compares what she said against what
    # the brief says, and the brief does not change between requirements.
    try:
        _brief_figures = parse_figures(compiled.get('brief_text') or '')
    except Exception:
        _brief_figures = []

    verdicts, escalate, cand_map = [], [], {}
    for rd in reqs:
        rd = dict(rd)
        rd['_duration'] = duration
        # Every figure the BRIEF states, so a figure-fidelity rule is judged
        # against the document rather than against its own match_hints.
        rd['_brief_figures'] = _brief_figures
        cands = candidates_for(rd, records, duration, cfg)
        cand_map[rd['id']] = cands
        v = evaluate_l1(rd, cands, health, cfg)
        if v is not None:
            v.candidates_considered = v.candidates_considered or len(cands)
            verdicts.append(v)
            continue
        v = evaluate_l2(rd, cands, health, cfg)
        if v is not None:
            v.escalated_from = ['L1']
            verdicts.append(v)
            continue
        escalate.append((rd, cands[:cfg.l3.max_candidates_per_requirement]))

    # Every member of every choice group, so L3 can see the KIND of ask each
    # option is an example of. Built once from the resolved requirements, which
    # is the only place that has all of them -- a batch may hold two of twelve.
    _group_map = {}
    for _r in reqs:
        if _r.get('group'):
            _group_map.setdefault(_r['group'], []).append(_r)

    l3_stats = {'calls': 0, 'violations': [], 'backend': None, 'repaired': 0}
    for i in range(0, len(escalate), cfg.l3.max_requirements_per_call):
        chunk = escalate[i:i + cfg.l3.max_requirements_per_call]
        got, st = evaluate_l3_batch(chunk, health, duration, backend, cfg,
                                    verbose, groups=_group_map)
        l3_stats['calls'] += st['calls']
        l3_stats['repaired'] += st['repaired']
        l3_stats['violations'] += st['violations']
        l3_stats['backend'] = st['backend'] or l3_stats['backend']
        for rd, _c in chunk:
            v = got.get(rd['id'])
            if v is None:
                v = _blank_verdict(rd, 'UNCERTAIN',
                                   'No layer produced a verdict.', 'L3',
                                   flags=['NO_VERDICT'])
            v.escalated_from = ['L1', 'L2']
            # What the MODEL was actually shown. The batch is truncated to
            # cfg.l3.max_candidates_per_requirement, so filling this from the
            # full retrieval names records the verdict never saw. Measured on a
            # live verdict: candidates_considered=8, examined_ids=10.
            #
            # examined_ids exists so a human can check the verdict. Listing two
            # records the adjudicator was never given makes that harder, not
            # easier.
            v.examined_ids = candidate_ids(_c)[:10]
            verdicts.append(v)

    # Every verdict records what it was evaluated against, whichever layer
    # decided it. One place, so no layer can forget -- and separate from
    # evidence_ids, which stays "what this verdict relies on".
    for v in verdicts:
        if not v.examined_ids:      # L3 already recorded the batch it was shown
            v.examined_ids = candidate_ids(
                cand_map.get(v.requirement_id) or [])[:10]

    # L1 knows its own alignment without asking anyone.
    #
    # A literal phrase match IS exact -- that is what L1 matched on. An absence
    # established in a healthy modality IS none. A PARTIAL (one half of a
    # conjunctive mode) is partial by construction. Filling these here keeps L1
    # verdicts scorable by Phase 7 without an L3 call, and leaves UNCERTAIN
    # alone: nobody looked, so nobody may say.
    _L1_ALIGNMENT = {'PASS': 'exact', 'FAIL': 'none', 'PARTIAL': 'partial'}
    for v in verdicts:
        # A PASS earned by ABSENCE carries no alignment.
        #
        # "No forbidden content was found" is a correct PASS and a real result.
        # It is not evidence that the creator did anything, so calling it
        # `exact` -- "the requirement's own wording was matched" -- asserts
        # something that did not happen, and then scores it 1.0.
        #
        # Measured on a pill-organiser video audited against a hair brief: two
        # forbidden rules passed vacuously, were labelled `exact`, and
        # contributed 2.0 of a 3.10 total -- 65% of the score, for a video that
        # never went near the subject. Without them the mean was 0.28.
        #
        # alignment asks "how close is what she DID to what this was FOR". When
        # she did nothing relevant, the honest answer is that nobody judged it:
        # None, which the scored-unit filter then excludes. The verdict itself
        # stays PASS -- compliance is real, it is just not achievement.
        if any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.flags or [])):
            continue
        if v.layer == 'L1' and v.alignment is None:
            _a = _L1_ALIGNMENT.get(v.status)
            if _a:
                v.alignment = _a
                v.alignment_reason = (
                    'Derived at L1, not judged by a model: '
                    + {'exact': 'the requirement\'s own wording was matched.',
                       'none': 'the requirement\'s content was absent from a '
                               'modality that ran cleanly.',
                       'partial': 'satisfied in one of the two modalities the '
                                  'requirement needs.'}[_a])

    # ---- HER OWN WORDS, THE BRIEF'S INTENT -----------------------------------
    #
    # `strong` means "different words, same ask and same intent -- the creator
    # wrote her own version of what the brief described". A verdict that says
    # FAIL and `strong` together contradicts itself.
    #
    # Measured on an on-brief video: two requirements FAILed at `strong` for a
    # creator who had opened with an approved hook verbatim. The requirements
    # were phrased as particular sentences; she met the ask in her own words and
    # the report called it a failure twice.
    #
    # The promotion is arithmetic on the ordinal the model chose. The model
    # never decides its own status, and the literal finding is preserved on the
    # verdict, because "she did not use the brief's wording" is a real fact a
    # brand reviewer may want.
    # ---- substance counts, but only when the alignment can be trusted -----
    # THE PRODUCT RULE: the brief is a REFERENCE, not a script. The creator has
    # to talk about the same things; the hooks, CTAs and explanations may be
    # her own. So a requirement met in her own words is MET, and literal
    # matching is not the standard.
    #
    # That is what the old promotion tried to do, and it was right in intent
    # and unsafe in mechanism: it trusted one uncross-checked model call, it
    # judged alignment against a group_intent that often named only a POSITION
    # ("conclude the video with a call to action" -- which any closing sentence
    # satisfies), and it OVERWROTE the literal status so nothing downstream
    # could tell the two apart. On a 12.35s video with no CTA at all, that
    # printed PASS.
    #
    # Three things changed, so the credit can now be granted safely:
    #   1. audit_group_intents() detects the subject-free intent that made the
    #      Aurelia alignment meaningless. That is the guard that would have
    #      caught it.
    #   2. An alignment citing no record is an assertion, not a finding, and
    #      earns nothing.
    #   3. The literal status is KEPT on the verdict, so Phase 7 reports a
    #      literal score beside the credited one. Nothing is hidden, and the
    #      two are never merged into one opaque number.
    # Where the alignment cannot be trusted, the literal FAIL stands.
    _SUBSTANCE_STATUS = {'exact': 'PASS', 'strong': 'PASS', 'partial': 'PARTIAL'}
    # This block used to overwrite a literal FAIL with PASS whenever alignment
    # was `strong` or `exact`. It was the only place in the system where ONE
    # number from ONE model call changed a verdict with no cross-check --
    # everywhere else two independent things must agree, or the system
    # abstains. On a 12.35s music-only video with no CTA at all, L3 returned
    # FAIL + alignment `strong` against a subject-free group_intent, and this
    # promoted it to PASS: the false-positive PASS plan.md calls the most
    # damaging error class.
    #
    # The signal is not discarded -- it is carried alongside, the same
    # treatment `standing` and the decomposed mean already get. Phase 7 scores
    # the literal status and reports alignment beside it, so a reader sees
    # "FAIL literally, strong alignment" and can judge. A single blended number
    # cannot be un-blended downstream.
    for v in verdicts:
        # FAIL *and* PARTIAL. A PARTIAL with `strong` alignment is the same
        # creator doing the same thing in her own words -- which literal layer
        # produced the status does not change whether she did it. Only ever
        # upward: a PARTIAL is eligible when the alignment maps to PASS.
        if v.status not in ('FAIL', 'PARTIAL'):
            continue
        if (v.status == 'PARTIAL'
                and _SUBSTANCE_STATUS.get(v.alignment or '') != 'PASS'):
            continue
        # A forbidden rule FAILs because the prohibited thing was FOUND, and a
        # FAIL from positive evidence is the same shape. Neither is a creator
        # phrasing something her own way.
        if (v.evidence_mode and any(str(f).startswith('FAIL_FROM_POSITIVE_EVIDENCE')
                                    for f in v.flags)):
            continue
        _rd = next((r for r in reqs if r.get('id') == v.requirement_id), None)
        if (_rd or {}).get('polarity') == 'forbidden':
            continue
        _lvl = v.alignment or ''
        if _lvl not in _SUBSTANCE_STATUS:
            continue
        v.flags.append(f'SUBSTANCE_ALIGNMENT:{_lvl}')

        # ---- the two gates -------------------------------------------------
        # A subject-free intent that was REPAIRED at compile time is fine: L3
        # judged against the repaired reference, which names the options
        # themselves. The gate exists to catch an alignment judged against a
        # reference that could not distinguish anything -- not to punish a
        # group for how the model first worded its summary.
        _rflags = (_rd or {}).get('flags') or []
        _subject_free = ('GROUP_INTENT_SUBJECT_FREE' in _rflags
                         and 'GROUP_INTENT_REPAIRED' not in _rflags)
        _cites = bool(getattr(v, 'evidence_ids', None))
        if _subject_free or not _cites:
            _why = ('subject_free_intent' if _subject_free else 'cites_no_record')
            v.flags.append(f'SUBSTANCE_ALIGNMENT_UNTRUSTED:{_why}')
            # NOT a FAIL. The alignment says she may well have done something
            # relevant; what we cannot do is CHECK it -- because OUR compiler
            # wrote a subject-free intent, or because the judgement cited no
            # record. Scoring that 0 penalises the creator for our defect.
            #
            # UNCERTAIN is exactly this case: "we could not tell", an
            # abstention that leaves the numerator instead of counting as a
            # failure (design rule 3). Coverage drops, which is the honest
            # report -- and it is visible, so the brief can be fixed.
            v.flags.append('UNDECIDABLE_ALIGNMENT')
            v.status = 'UNCERTAIN'
            v.reason = (
                f'Cannot be decided. She may have done this in her own words -- '
                f'alignment {_lvl} -- but '
                + ('the group intent it was judged against names only a '
                   'position in the video, not a thing to look for, so that '
                   'alignment cannot be checked. Fix the brief\'s wording for '
                   'this group and it becomes decidable.'
                   if _subject_free else
                   'it cites no record, so there is nothing to check it '
                   'against.')
                + f' Not counted against her. {v.reason}')[:600]
            continue

        # ---- credited: she made her own version, and it checks out ---------
        v.flags.append(f'LITERAL_STATUS_WAS:FAIL/{_lvl}')
        v.flags.append('SATISFIED_IN_SUBSTANCE')
        v.status = _SUBSTANCE_STATUS[_lvl]
        v.reason = (
            f'Met in substance, not in the brief\'s wording: {_lvl} alignment '
            f'with what this requirement asks for, cited to the record where '
            f'she says it her own way. The brief is a reference, not a script. '
            f'Literal match: no. {v.reason}')[:600]

    verdicts = _resolve_groups(verdicts, cfg)

    # THE assertion. Not a test that might be run -- a check that always runs.
    offered = {rid: set(candidate_ids(c)) for rid, c in cand_map.items()}
    fabricated = [(v.requirement_id, i) for v in verdicts for i in v.evidence_ids
                  if i not in offered.get(v.requirement_id, set())]
    flags = []
    if fabricated:
        flags.append({'code': 'FABRICATED_EVIDENCE_ID',
                      'detail': f'{len(fabricated)}: {fabricated[:3]}'})
        keep = {rid: offered.get(rid, set()) for rid, _ in fabricated}
        for v in verdicts:
            if v.requirement_id in keep:
                v.evidence_ids = [i for i in v.evidence_ids if i in keep[v.requirement_id]]
                v.flags.append('CITATIONS_STRIPPED')

    # Two kinds of FAIL, and only one needs the mode-wide health gate:
    #   from ABSENCE  -- "we looked and it is not there". Needs every modality
    #                    that could have carried it to have run cleanly.
    #   from PRESENCE -- "we found the forbidden thing". Grounded in evidence we
    #                    HAVE, in a modality already checked at the point of the
    #                    finding. Requiring the conjunction here would make a
    #                    real policy breach unreportable because an unrelated
    #                    modality degraded.
    illegal = [v.requirement_id for v in verdicts
               if v.status == 'FAIL'
               and not can_fail.get(v.evidence_mode, False)
               and not any(f.startswith('FAIL_FROM_POSITIVE_EVIDENCE')
                           for f in v.flags)]
    if illegal:
        flags.append({'code': 'FAIL_WITHOUT_HEALTH', 'detail': str(illegal[:3])})

    by_status = Counter(v.status for v in verdicts)
    by_layer = Counter(v.layer for v in verdicts)
    n = max(1, len(verdicts))
    out = {
        'schema_version': VERDICT_STAGE_VERSION,
        'video_hash': vh, 'video_id': video.get('video_id', ''),
        'brief_hash': compiled.get('brief_hash', ''),
        'duration_seconds': round(duration, 3),
        'cache_key': key,
        'sources': {'evidence': evidence.get('cache_key', ''),
                    'brief': compiled.get('cache_key', '')},
        'verdicts': [v.to_dict() for v in verdicts],
        'can_fail_on': can_fail,
        'stats': {
            'requirements': len(verdicts),
            'by_status': dict(by_status),
            'by_layer': dict(by_layer),
            'escalation_rate': {
                'L1': round(by_layer.get('L1', 0) / n, 3),
                'L2': round(by_layer.get('L2', 0) / n, 3),
                'L3': round(by_layer.get('L3', 0) / n, 3),
            },
            # Over SCORING UNITS, not over every requirement. A twelve-option
            # hook list contributes eleven NOT_APPLICABLE losers, and counting
            # them buries the signal: measured on a music-only video, 3 of 4
            # scoring units abstained and the old denominator reported 12% --
            # comfortably under plan.md's 20% alarm line. The metric built to
            # warn about that exact run said everything was fine.
            'uncertain_rate': round(
                sum(1 for v in verdicts
                    if v.status == 'UNCERTAIN') / max(1, sum(
                        1 for v in verdicts if v.status != 'NOT_APPLICABLE')), 3),
            # Kept so nothing is lost, and so the two can be compared.
            'uncertain_rate_all_requirements':
                round(by_status.get('UNCERTAIN', 0) / n, 3),
            'fabricated_ids': len(fabricated),
            'l3': l3_stats,
        },
        'flags': flags,
        'provenance': provenance('verdicts', VERDICT_STAGE_VERSION, key,
                                 time.time() - t0,
                                 prompt_version=ADJUDICATE_PROMPT_VERSION,
                                 backend=l3_stats.get('backend')),
    }
    write_json(path, out)
    if verbose:
        print(f'  verdicts -> {path.name}  ({len(verdicts)} requirements)')
    return out

def audit_video(video: dict, evidence: dict, compiled: dict,
                cfg: Phase6Config = None, backend=None, force: bool = False,
                verbose: bool = True, allow_unapproved: bool = False) -> dict:
    """Requirements + hook + claims, the whole Phase 6 output for one video."""
    cfg = cfg or P6
    res = evaluate_requirements(video, evidence, compiled, cfg, backend, force,
                                verbose, allow_unapproved)
    if res.get('status') == 'BRIEF_NOT_USABLE':
        return res

    # These four used to be attached AFTER evaluate_requirements had already
    # written the artifact, so they never reached disk. Two costs, and the
    # second is the expensive one:
    #   - the artifact could not answer "what did the hook module say", which
    #     made the Phase 6 exit criterion unmeetable by inspection;
    #   - evaluate_requirements returns early on a cache hit, but these ran
    #     again regardless -- four LLM calls per audit, every audit, for a
    #     result that had already been computed and paid for.
    #
    # They share evaluate_requirements' cache key by construction: same video,
    # same evidence, same brief, same cfg. So the same artifact is their home,
    # and its presence is what makes the second run free.
    _MODULES = ('hook', 'claims', 'creative_angle', 'standing')
    if not force and all(k in res for k in _MODULES):
        if verbose:
            print(f'  MODULES CACHE HIT ({res.get("cache_key", "")})')
        return res

    records = load_records(evidence)
    agg = evidence.get('aggregates') or {}
    health = evidence.get('modality_health') or {}
    res['hook'] = evaluate_hook(records, float(res.get('duration_seconds') or 0.0),
                                int(agg.get('cut_count') or 0), health,
                                backend, cfg, verbose)
    res['claims'] = evaluate_claims(records, backend, cfg, verbose)
    res['creative_angle'] = evaluate_creative_angle(
        records, compiled, res, backend, cfg, verbose)
    # Last, because it is given the other modules' readings as context. It is a
    # second opinion on the same video, not an input to any verdict above it --
    # nothing here reads res['standing'], by design.
    res['standing'] = evaluate_standing(records, compiled, res, health, backend,
                                        cfg, verbose)

    # Persist the WHOLE audit, not only its requirements half.
    _key = res.get('cache_key')
    if _key:
        write_json(DIRS['artifacts'] / video['video_hash']
                   / f'verdicts__{_key}.json', res)
        if verbose:
            print(f'  audit (+{len(_MODULES)} modules) -> verdicts__{_key}.json')
    return res

def verdicts_for(video_hash: str, brief_hash: str = '') -> Optional[dict]:
    """Newest verdict artifact for a video, optionally for one brief."""
    vdir = DIRS['artifacts'] / video_hash
    if not vdir.exists():
        return None
    files = [p for p in vdir.glob('verdicts__*.json')]
    if brief_hash:
        files = [p for p in files
                 if (read_json(p) or {}).get('brief_hash') == brief_hash]
    if not files:
        return None
    return read_json(max(files, key=lambda p: p.stat().st_mtime))


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 491: print('§70 evaluate stage loaded.  Artifacts -> work/artifacts/{video_hash}/
