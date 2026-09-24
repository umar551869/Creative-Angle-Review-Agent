"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 99.
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
def compile_brief(brief_text: str, cfg: Phase4Config = None, backend: BriefBackend = None,
                  force: bool = False, verbose: bool = True) -> dict:
    """
    Brief -> compiled requirements, cached by BRIEF hash.

    Never raises: a brief that cannot be compiled returns a status and the flags
    explaining why, so a batch of 40 briefs does not die on brief 12.
    """
    cfg = cfg or P4
    bc = cfg.brief
    t_start = time.time()
    brief_text = brief_text or ''

    if not brief_text.strip():
        return {'status': 'EMPTY_BRIEF', 'requirements': [], 'flags':
                [{'code': 'EMPTY_BRIEF', 'detail': 'nothing to compile'}],
                'brief_hash': None, 'approved': False}

    bhash = sha256_text(brief_text)
    key = stage_key('brief', BRIEF_STAGE_VERSION, [bhash],
                    {'brief': asdict(bc), 'prompt': BRIEF_PROMPT_VERSION})
    bdir = DIRS['briefs'] / bhash
    path = bdir / f'requirements__{key}.json'

    if path.exists() and not force:
        cached = read_json(path)
        if verbose:
            print(f'  BRIEF CACHE HIT ({key})  {len(cached.get("requirements", []))} requirements')
        return cached

    backend = backend or make_brief_backend(bc, verbose=verbose)
    # The spend cap is PER COMPILE, and one compile can legitimately call the
    # backend three times (a parse-repair retry, an output-cap bump). Reset here
    # so a reused backend object does not carry a previous brief's spend, and so
    # the cap cannot be exhausted by a long batch and silently stop working.
    if hasattr(backend, 'paid_calls'):
        backend.paid_calls = 0
        backend.spend_log = []
    system = PROMPT_P4_SYSTEM
    user = build_brief_prompt(brief_text, bc)

    raw_text, parse_err, attempts, gen = '', None, [], {}
    obj, backend_error, truncated = None, None, False
    work = bc                       # may get a larger output cap as we go
    for attempt in range(3 if bc.allow_retry else 1):
        try:
            gen = backend.complete(system, user, work)
        except Exception as exc:
            backend_error = f'{type(exc).__name__}: {str(exc)[:200]}'
            attempts.append({'attempt': attempt, 'error': backend_error})
            break
        raw_text = gen.get('text', '')

        # Completeness is asked SEPARATELY from parseability -- a repair library
        # will happily close off a severed list and hand back valid-looking JSON.
        if gen.get('hit_token_cap'):
            truncated = True
            attempts.append({'attempt': attempt, 'error': 'hit_token_cap',
                             'max_new_tokens': work.max_new_tokens})
            # Retrying at the SAME cap truncates identically -- that was the
            # Phase 3 lesson. But a BIGGER cap is precisely the fix, and a real
            # brief legitimately needs more room than an example one.
            if bc.allow_retry and work.max_new_tokens < bc.max_output_ceiling:
                work = replace(work, max_new_tokens=min(work.max_new_tokens * 2,
                                                        bc.max_output_ceiling))
                if verbose:
                    print(f'  output hit the cap; retrying with '
                          f'max_new_tokens={work.max_new_tokens}')
                continue
            break
        truncated = False

        obj, parse_err, method = parse_model_json(raw_text)   # Phase 3 §23
        if obj is not None:
            attempts.append({'attempt': attempt, 'parse_method': method})
            break
        attempts.append({'attempt': attempt, 'error': f'parse failed: {parse_err}'})
        if not bc.allow_retry or attempt >= 2:
            break
        user = build_brief_prompt(brief_text, bc) + '\n\n' + \
            PROMPT_P4_REPAIR.format(errors=f'JSON did not parse: {parse_err}')

    if truncated and obj is None:
        if bc.backend == 'auto' and not isinstance(backend, RuleBasedBackend):
            if verbose:
                print(f'  still truncated at {work.max_new_tokens} tokens;'
                      f' falling back to the rule engine')
            fb = compile_brief(brief_text, cfg, backend=RuleBasedBackend(),
                               force=True, verbose=verbose)
            fb.setdefault('flags', []).insert(0, {
                'code': 'BACKEND_DEGRADED',
                'detail': f'compiled by the rule engine: the model truncated even at '
                          f'max_new_tokens={work.max_new_tokens}'})
            return fb
        return {'status': 'TRUNCATED', 'requirements': [], 'brief_hash': bhash,
                'cache_key': key, 'attempts': attempts, 'raw_output': raw_text[:4000],
                'approved': False, 'backend': gen.get('backend', 'unknown'),
                'flags': [{'code': 'TRUNCATED',
                           'detail': f'output still hit the cap at '
                                     f'{work.max_new_tokens} tokens. Raise '
                                     f'BriefConfig.max_output_ceiling, or split '
                                     f'the brief.'}]}

    if obj is None:
        # 'auto' promised a working compiler, not a preferred one. A backend
        # chosen at construction can still die at CALL time -- a retired model,
        # an exhausted quota, a network blip -- and leaving the user with
        # BACKEND_FAILED when a deterministic compiler was sitting right there
        # is not what 'auto' means.
        if backend_error is not None and bc.backend == 'auto' \
                and not isinstance(backend, RuleBasedBackend):
            if verbose:
                print(f'  hosted/local backend failed ({backend_error[:70]});'
                      f' falling back to the rule engine')
            fb = compile_brief(brief_text, cfg, backend=RuleBasedBackend(),
                               force=True, verbose=verbose)
            fb.setdefault('flags', []).insert(0, {
                'code': 'BACKEND_DEGRADED',
                'detail': f'compiled by the rule engine after the preferred backend '
                          f'failed: {backend_error[:160]}'})
            return fb

        # A backend that never answered and a backend that answered badly are
        # different problems with different fixes -- "check your API key" versus
        # "the model returned prose". Collapsing them into one status costs the
        # next person the time it takes to rediscover which one happened.
        if backend_error is not None:
            return {'status': 'BACKEND_FAILED', 'requirements': [], 'brief_hash': bhash,
                    'cache_key': key, 'attempts': attempts, 'raw_output': '',
                    'approved': False,
                    'flags': [{'code': 'BACKEND_FAILED', 'detail': backend_error}]}
        return {'status': 'PARSE_FAILED', 'requirements': [], 'brief_hash': bhash,
                'cache_key': key, 'attempts': attempts, 'raw_output': raw_text[:4000],
                'approved': False,
                'flags': [{'code': 'PARSE_FAILED', 'detail': str(parse_err)[:300]}]}

    reqs, flags = normalize_requirements(obj, brief_text, bc)
    reqs, dedupe_flags = dedupe_requirements(reqs, bc)
    flags.extend(dedupe_flags)
    conflicts = detect_conflicts(reqs)
    health = decomposition_health(reqs, brief_text, bc)
    flags.extend(health['flags'])
    flags.extend(pydantic_check(reqs))

    # plan.md §4: MVP scope is English. Detect and note, do not fail.
    try:
        if looks_non_english(brief_text):                      # Phase 3 §26
            flags.append({'code': 'BRIEF_NOT_ENGLISH',
                          'detail': 'cue lists are English; review carefully'})
    except Exception:
        pass

    # Document structure travels with the artifact: the human review in §48b has
    # to be able to see that "Sample Hook Concepts" was read as a choice and that
    # "Purpose" produced nothing, without going back to the original document.
    try:
        sections = parse_brief_sections(brief_text)
        approved_claims = extract_approved_claims(sections)
        reference_links = brief_reference_links(sections)
        section_summary = [{'heading': s.heading, 'kind': s.kind, 'lines': len(s.lines),
                            'refs': len(s.refs)} for s in sections]
    except Exception as exc:
        sections, approved_claims, section_summary, reference_links = [], [], [], []
        flags.append({'code': 'SECTION_PARSE_FAILED', 'detail': str(exc)[:160]})

    # ---- every option the brief lists gets a requirement ---------------------
    #
    # The compiler decides two things: WHICH asks the brief contains, and what
    # each one means. All of the measured instability is in the first. One
    # document compiled to 16 requirements on one run and 24 on another; against
    # the document's own item inventory the first covered 3 of 20 options and the
    # second covered 20 of 20, because the first collapsed twelve hooks into
    # "use one of the approved hook concepts".
    #
    # section_items() already models the document properly -- a numbered title
    # absorbs the bullets under it, a flat bullet list is one item per bullet,
    # and a section preamble is dropped -- so the inventory is deterministic.
    # The prompt has forbidden collapsing since 1.6.0, so this is a SAFETY NET:
    # it only fires when an option produced no requirement at all.
    #
    # It only ADDS. A requirement matching no item is kept and reported, never
    # dropped, because the parser can mis-section a document and silently losing
    # a real ask is the worse error.
    try:
        _inv = []
        for _s in sections:
            if _s.kind != 'alternatives':
                continue
            for _it in section_items(_s):
                _txt = (_it.get('text') if isinstance(_it, dict) else str(_it)) or ''
                if len(_txt.strip()) >= 8:
                    _inv.append((_s, _txt.strip()))

        def _same_item(_span: str, _item: str) -> bool:
            _a, _b = normalize_text(_span or '')[:70], normalize_text(_item)
            if len(_a) < 10 or not _b:
                return False
            if _a[:40] in _b or _b[:40] in _a:
                return True
            try:
                return fuzz.partial_ratio(_a, _b) >= 88
            except Exception:
                return False

        _claimed = set()
        for _r in reqs:
            for _i, (_s, _txt) in enumerate(_inv):
                if _i not in _claimed and _same_item(_r.brief_span, _txt):
                    _claimed.add(_i)
                    break

        _group_of = {}
        for _r in reqs:
            if _r.group and _r.group_label:
                _group_of.setdefault(_r.group_label,
                                     (_r.group, _r.group_mode, _r.group_intent))
        _added = []
        for _i, (_s, _txt) in enumerate(_inv):
            if _i in _claimed:
                continue
            _gid, _gmode, _gintent = _group_of.get(
                _s.heading, (f'g_{_s.slug()[:22]}', 'one_of', ''))
            _rtext = f'Use this option from "{_s.heading}": {_txt}'
            reqs.append(Requirement(
                id=requirement_id(_rtext, 'other'), ordinal=len(reqs) + 1,
                label=_txt[:60], requirement=_rtext, type='other',
                priority='medium', weight=PRIORITY_WEIGHT['medium'],
                polarity='required', evidence_mode='speech_or_text',
                machine_checkable=True, match_hints=[_txt[:140]],
                acceptance_criteria=[f'The creator uses this option: {_txt[:90]}'],
                group=_gid, group_mode=_gmode, group_label=_s.heading,
                group_intent=_gintent, source='derived',
                brief_span=_txt[:300], confidence=0.6,
                flags=['ADDED_FROM_DOCUMENT']))
            _added.append(f'{_s.heading}: {_txt[:40]}')

        if _added:
            flags.append({
                'code': 'OPTIONS_ADDED_FROM_DOCUMENT',
                'detail': f'{len(_added)} of {len(_inv)} option(s) the brief '
                          f'lists produced no requirement and were added from '
                          f'the document itself'})
            if verbose:
                print(f'  the brief lists {len(_inv)} option(s); the model wrote '
                      f'requirements for {len(_claimed)}.')
                print(f'  {len(_added)} added from the document, so an option the '
                      f'model skipped is still audited:')
                for _a in _added[:4]:
                    print(f'     {_a}')
        elif verbose and _inv:
            print(f'  all {len(_inv)} option(s) the brief lists have a '
                  f'requirement.')
    except Exception as _exc:
        flags.append({'code': 'OPTION_INVENTORY_FAILED', 'detail': str(_exc)[:160]})

    # ---- an ask written outside the list it belongs to -----------------------
    #
    # A brief lists twelve sample hooks under one heading, and then says "use a
    # hook like these" in a sentence somewhere else. The list becomes a one_of
    # group and collapses to its best member, exactly as intended. The loose
    # sentence becomes an ORDINARY requirement and is scored as independently
    # mandatory -- so a creator who used one good hook FAILs the stray sentence
    # for not also using that one.
    #
    # Measured on one run: 4 of 9 scored units were strays like this, two for
    # hooks and one for the call to action. They contributed 0.25, 0.25, 0.00
    # and 0.55 against a video whose actual hook scored `strong` inside the
    # group it belonged to.
    #
    # The brief itself says where each requirement came from: brief_span is the
    # sentence it was built from. If that sentence sits inside a section that
    # already produced a choice group, the requirement is another way of making
    # that same choice, and belongs in the group.
    #
    # Conservative on purpose: it joins only when the span is found in EXACTLY
    # one section, so an ambiguous match changes nothing.
    try:
        _adopted = adopt_stray_asks(reqs, sections)
        if _adopted:
            flags.append({
                'code': 'STRAY_ASKS_ADOPTED_INTO_GROUP',
                'detail': f'{len(_adopted)} requirement(s) were written outside '
                          f'the list they belong to and were scored as '
                          f'independently mandatory; each is now an option in '
                          f'the choice its own brief section defines'})
            if verbose:
                print(f'  {len(_adopted)} stray ask(s) joined the choice group '
                      f'their brief section defines:')
                for _r in _adopted[:4]:
                    print(f'     {(_r.label or _r.requirement)[:52]!r} '
                          f'-> {_r.group_label[:34]}')
    except Exception as _exc:
        flags.append({'code': 'GROUP_ADOPTION_FAILED',
                      'detail': str(_exc)[:160]})
    # An approved claim carrying a figure is a compliance surface: the video may
    # or may not state it, but if it states a DIFFERENT figure that is a failure.
    numeric_claims = [c for c in approved_claims if c['numbers']]
    if numeric_claims and not any(r.polarity == 'forbidden' and 'unsupported_outcome'
                                 in r.claim_classes for r in reqs):
        figures = sorted({n for c in numeric_claims for n in c['numbers']})
        fid_text = ('Any figure stated about the product must match the brief: '
                    + ', '.join(figures) + '.')
        reqs.append(Requirement(
            id=requirement_id(fid_text, 'policy'), ordinal=len(reqs) + 1,
            label='approved figures only', requirement=fid_text, type='policy',
            priority='critical', weight=PRIORITY_WEIGHT['critical'],
            polarity='forbidden', evidence_mode='any', machine_checkable=True,
            match_hints=figures, acceptance_criteria=[fid_text],
            claim_classes=['unsupported_outcome'], source='inferred',
            brief_span='; '.join(c['text'] for c in numeric_claims)[:300],
            confidence=0.7,
            flags=['DERIVED_FROM_APPROVED_CLAIMS']))
        flags.append({'code': 'NUMERIC_FIDELITY_RULE_ADDED',
                      'detail': f'{len(figures)} approved figure(s): {", ".join(figures)}'})

    status = 'OK' if reqs else 'NO_REQUIREMENTS'
    needs_review = [r.id for r in reqs if r.flags or r.confidence < 0.5]
    units = scoring_units(reqs)

    compiled = {
        'schema_version': BRIEF_STAGE_VERSION,
        'status': status,
        'campaign': (obj.get('campaign') if isinstance(obj, dict) else None)
                    or find_campaign(brief_text),
        'brief_hash': bhash,
        'cache_key': key,
        'brief_text': brief_text,
        'requirements': [r.to_dict() for r in reqs],
        'sections': section_summary,
        'approved_claims': approved_claims,
        # Does the brief DEMAND its claims, or OFFER them? Phase 7 scores a
        # menu as coverage and a checklist item by item, and getting that
        # from the document is what stops the pipeline being shaped by the
        # first brief it ever saw.
        'claims_obligation': claims_obligation_of(sections, brief_text),
        # The videos the brief points at. Phase 4 does not audit them, but they
        # are the clearest statement of intent in the document and the human
        # reviewing §48b should be able to open them.
        'reference_links': reference_links,
        'scoring_units': units,
        'conflicts': conflicts,
        'decomposition': health,
        'flags': flags,
        'needs_review': needs_review,
        'stats': {
            'requirements': len(reqs),
            'scorable': sum(1 for r in reqs if r.is_scorable()),
            'not_machine_checkable': sum(1 for r in reqs if not r.machine_checkable),
            'forbidden': sum(1 for r in reqs if r.polarity == 'forbidden'),
            'with_temporal': sum(1 for r in reqs if r.has_temporal_constraint()),
            'symbolic_windows': sum(1 for r in reqs
                                    if r.window_start_expr or r.window_end_expr),
            'mode_disagreements': sum(1 for r in reqs
                                      if any(f.startswith('MODE_DISAGREES') for f in r.flags)),
            'possible_inventions': sum(1 for r in reqs
                                       if any(f.startswith('SPAN_NOT_IN_BRIEF') for f in r.flags)),
            'choice_groups': sum(1 for u in units if u['kind'] == 'group'),
            'alternatives': sum(1 for r in reqs
                                if r.group and r.group_mode in ('one_of', 'any_of')),
            'approved_claims': len(approved_claims),
            'scoring_units': len(units),
            # A one_of group contributes its weight ONCE. Summing members would
            # make a brief that offers more options harder to pass.
            'total_weight': total_scoring_weight(reqs),
        },
        # Approval is a separate, explicit act (§46). A freshly compiled brief is
        # never approved, including on a forced recompile of an approved one.
        'approved': False, 'approved_by': None, 'approved_at': None, 'approval_note': None,
        'backend': gen.get('backend', 'unknown'),
        'attempts': attempts,
        'raw_output': raw_text[:8000],
        'provenance': provenance('brief', BRIEF_STAGE_VERSION, key, time.time() - t_start,
                                 prompt_version=BRIEF_PROMPT_VERSION,
                                 backend=gen.get('backend', 'unknown'),
                                 tokens=gen.get('tokens', {})),
    }

    # A single-shot compile never reaches consensus, so reconcile here too.
    try:
        normalise_group_intents(compiled['requirements'])
        audit_group_intents(compiled['requirements'])
    except Exception:
        pass

    # Only a successful compile is cached. A cached failure looks exactly like a
    # cached success on the next run and poisons every future use of this brief.
    if status == 'OK':
        write_json(path, compiled)
        if verbose:
            print(f'  compiled -> {path.name}')
    elif verbose:
        print(f'  NOT cached (status {status})')
    return compiled

def load_compiled_brief(brief_text_or_hash: str, cfg: Phase4Config = None) -> Optional[dict]:
    """Fetch a compiled brief by its text or its hash, without recompiling."""
    cfg = cfg or P4
    bhash = (brief_text_or_hash if re.fullmatch(r'[0-9a-f]{16}', brief_text_or_hash or '')
             else sha256_text(brief_text_or_hash))
    bdir = DIRS['briefs'] / bhash
    if not bdir.exists():
        return None
    files = sorted(bdir.glob('requirements__*.json'))
    return read_json(files[-1]) if files else None

def _req_fingerprint(r: dict) -> str:
    """What makes two compiled requirements THE SAME requirement.

    Not the id: ids are content-derived, so a one-word rewording produces a
    different id for the same ask. Match on the normalised wording plus the
    fields that change its meaning.
    """
    # THE DOCUMENT'S SENTENCE, not the model's phrasing.
    #
    # The compiler copies enumerated items verbatim and PHRASES prose asks
    # itself, so one ask came back as 'End video call action' / 'Include call
    # action' / 'Deliver call action' across three compiles -- three
    # fingerprints, three separate votes, and a requirement count that moved.
    #
    # brief_span is the sentence the requirement was built FROM: a quote from
    # the document, not the model's wording. Measured over every pair of
    # compiles on disk, agreement between two compiles of one brief rose from
    # 30% to 47% -- and from 4% to 47% on the worst pair -- and never fell.
    # brief_span was usable on 95 of 95 requirements; the fallback is the old
    # behaviour, for the SPAN_NOT_IN_BRIEF case.
    _span = (r.get('brief_span') or '').strip()
    _src = _span if len(_span) >= 12 else (r.get('requirement') or '')
    text = re.sub(r'[^a-z0-9 ]', ' ', _src.lower())
    text = ' '.join(text.split())
    # evidence_mode and deadline_seconds are DELIBERATELY not part of identity.
    #
    # They are the fields the compiler is least stable about: the same ask came
    # back as visual_only in one run and visual_and_speech in another. Including
    # them meant a mode wobble split one requirement into two singletons, and
    # majority voting then dropped both. Polarity stays -- a require and a
    # forbid of the same sentence really are different asks.
    return '|'.join([text[:90], r.get('polarity') or ''])

def _cluster_fingerprints(seen: dict, min_ratio: int = 88) -> dict:
    """Merge fingerprints that are one ask written two ways.

    The compiler rewords between runs -- "here is what my hair eats" against
    "here's what my hair eats" -- and exact matching counts those as two
    requirements seen once each rather than one seen twice. On a real brief that
    was the difference between keeping 4 requirements and keeping most of them.

    Union-find over fuzzy wording similarity. Polarity must still agree.
    """
    keys = list(seen)
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    split = {k: (k.rsplit('|', 1)[0], k.rsplit('|', 1)[-1]) for k in keys}
    for i, a in enumerate(keys):
        ta, pa = split[a]
        for b in keys[i + 1:]:
            tb, pb = split[b]
            if pa != pb:
                continue
            try:
                same = fuzz.token_set_ratio(ta, tb) >= min_ratio
            except Exception:
                same = ta == tb
            if same:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    out = {}
    for k in keys:
        out.setdefault(find(k), []).extend(seen[k])
    return out

def compile_brief_consensus(brief_text: str, runs: int = 3,
                            cfg: Phase4Config = None, verbose: bool = True,
                            keep_threshold: float = 0.5) -> dict:
    """
    Compile the SAME brief several times and keep what every run agrees on.

    Measured on a real brief: three compiles at temperature 0.0 produced 9, 10
    and 22 requirements. Temperature does not make a hosted model
    deterministic, and the requirement set is the thing a human approves and
    every later verdict is measured against -- so instability there is not a
    cosmetic problem, it silently changes what the audit means.

    This does not make the model deterministic. It makes the INSTABILITY
    VISIBLE and bounded: a requirement that only appears sometimes is reported
    rather than quietly included or quietly dropped.

    keep_threshold is a MAJORITY by default, not unanimity. Measured on the same
    brief over three runs: counts of 9, 9 and 25, with only 2 requirements of 35
    appearing in all three. The 25-run enumerated every hook individually while
    the other two collapsed them into "use one of the approved hook concepts" --
    the model cannot decide whether to enumerate or to summarise, and unanimity
    punishes both choices. A majority keeps what two independent runs agreed on
    and still drops the one-off noise.

    Raise it to 1.0 for unanimity when you would rather lose a real requirement
    than admit an uncertain one.

    Costs one model call per run. Off by default; compile_brief() is unchanged.
    """
    cfg = cfg or P4
    if runs < 2:
        return compile_brief(brief_text, cfg, force=True, verbose=verbose)

    attempts, seen = [], {}
    for i in range(runs):
        out = compile_brief(brief_text, cfg, force=True, verbose=False)
        if out.get('status') != 'OK':
            if verbose:
                print(f'  run {i + 1}/{runs}: {out.get("status")} -- not counted')
            continue
        reqs = out.get('requirements') or []
        attempts.append(out)
        for r in reqs:
            fp = _req_fingerprint(r)
            seen.setdefault(fp, []).append(r)
        if verbose:
            print(f'  run {i + 1}/{runs}: {len(reqs)} requirements')

    if not attempts:
        return compile_brief(brief_text, cfg, force=True, verbose=verbose)

    # Merge rewordings BEFORE counting votes, or one ask written two ways is
    # two singletons and a majority rule drops both.
    seen = _cluster_fingerprints(seen)

    n = len(attempts)
    need = max(1, int(round(keep_threshold * n)))
    base = max(attempts, key=lambda o: len(o.get('requirements') or []))
    stable, unstable = [], []
    for fp, group in seen.items():
        # the longest wording wins: a shorter one is usually a truncation
        rep = max(group, key=lambda r: len(r.get('requirement') or ''))
        # A SAFETY rule is kept by union, not by majority.
        #
        # Measured on one document: forbidden went 1, 0, 1, 0 across compiles.
        # The compiler was not failing to produce the figures rule -- consensus
        # was voting it out when it appeared in one run of three.
        #
        # The two errors are not symmetric. Dropping a real forbidden rule stops
        # the audit checking claims at all, silently, with every other criterion
        # still green. Keeping a spurious one costs one extra check that the
        # video almost certainly passes. Majority is right for ordinary
        # requirements and wrong here.
        _is_safety = (rep.get('polarity') == 'forbidden'
                      or bool(rep.get('claim_classes')))
        if len(group) >= need or _is_safety:
            if _is_safety and len(group) < need:
                rep = dict(rep, flags=list(rep.get('flags') or [])
                           + [f'KEPT_AS_SAFETY_RULE:seen_{len(group)}_of_{n}'])
            stable.append((len(group), rep))
        else:
            unstable.append((len(group), rep))

    out = dict(base)
    out['requirements'] = [r for _c, r in
                           sorted(stable, key=lambda x: -x[0])][:cfg.brief.max_requirements]
    for i, r in enumerate(out['requirements'], 1):
        r['ordinal'] = i
    out['consensus'] = {
        'runs': n, 'keep_threshold': keep_threshold,
        'counts': [len(a.get('requirements') or []) for a in attempts],
        'stable': len(stable), 'dropped': len(unstable),
        'dropped_requirements': [
            {'seen_in': c, 'of': n, 'requirement': (r.get('requirement') or '')[:120]}
            for c, r in sorted(unstable, key=lambda x: -x[0])][:20],
    }
    # ---- pruning breaks the artifact unless the rest is rebuilt -------------
    #
    # Filtering `requirements` used to be the ONLY thing consensus changed, so
    # every other field still described the base run: 6 requirements reported
    # alongside scorable=16, and `sections` still listing alternatives sections
    # whose groups no longer existed. Phase 4's own exit criteria then failed on
    # an artifact consensus had produced.
    #
    # 1. A choice group whose other members did not survive is a group of ONE,
    #    which is not a choice. Release the survivor rather than leave it
    #    pointing at a group that no longer exists.
    _gc = {}
    for _r in out['requirements']:
        if _r.get('group'):
            _gc[_r['group']] = _gc.get(_r['group'], 0) + 1
    _orphans = {g for g, c in _gc.items() if c < 2}
    for _r in out['requirements']:
        if _r.get('group') in _orphans:
            _r['group'], _r['group_mode'] = None, 'all_of'
            _r.pop('group_label', None)
            # group_intent goes with it. A requirement released from a pruned
            # group must not keep advertising 'what the group is asking for'
            # for a group that no longer exists -- L3 would judge alignment
            # against an ask nothing in the brief still makes.
            _r.pop('group_intent', None)

    # 2. Keep only the alternatives sections that still have a live group, so
    #    'every alternatives section produced a group' compares like with like.
    _live_labels = {_r.get('group_label') for _r in out['requirements']
                    if _r.get('group')}
    out['sections'] = [s for s in (out.get('sections') or [])
                       if s.get('kind') != 'alternatives'
                       or s.get('heading') in _live_labels]

    # 2a. Union kept two rules that say the same thing.
    #
    #     Measured on one brief: consensus emitted two forbidden rules whose
    #     match_hints were IDENTICAL (27%, 3 months, 1500, 21 days, 86% -- 5 of
    #     5) but whose wording scored 79.8, under the 88 clustering threshold.
    #     They survived as two requirements and were judged separately: one
    #     PASS/exact, one FAIL/none. The same ask, contradicting itself, with
    #     the spurious FAIL dragging the mean alignment down.
    #
    #     Wording is the wrong key for these. A rule carrying match_hints checks
    #     exactly those hints, so the hints are what it IS. Two rules whose
    #     hints are equal -- or where one covers the other -- are one rule.
    #
    #     The survivor takes the UNION of both rules' hints and claim_classes,
    #     so merging can never check less than the pair did. Rules without hints
    #     are never merged: there is nothing to establish that they share a
    #     target.
    def _is_fig_rule(_r):
        """A 'figures must match the brief' rule: its hints are numbers.

        Phase 6 has the same predicate as is_figure_fidelity_rule(); it cannot
        be imported here because Phase 4 stands alone in its own notebook, so
        the two are kept deliberately identical and deliberately trivial.
        """
        _hs = [str(_h) for _h in (_r.get('match_hints') or [])]
        _num = [_h for _h in _hs if any(_c.isdigit() for _c in _h)]
        return bool(_hs) and len(_num) * 2 >= len(_hs)

    _forb = [r for r in out['requirements'] if r.get('polarity') == 'forbidden'
             and (r.get('match_hints') or [])]
    _dropped_dupes = []
    for _i, _a in enumerate(_forb):
        if _a in _dropped_dupes:
            continue
        for _b in _forb[_i + 1:]:
            if _b in _dropped_dupes:
                continue
            _ha, _hb = set(_a.get('match_hints') or []), set(_b.get('match_hints') or [])
            if not (_ha and _hb):
                continue
            # OVERLAP, not nesting.
            #
            # Requiring one hint set to contain the other merged nothing on a
            # real run: three figures rules came back with {27%, 3 months,
            # 1500}, {27%, 3 months, 86%} and {27%, 21 days} -- every pair
            # overlapping, no pair nested. All three survived and all three were
            # judged separately. Most of a shared hint list means the same
            # target; the survivor still takes the union, so nothing stops being
            # checked.
            # Two FIGURE-FIDELITY rules sharing a claim_class are the same
            # rule however their hints differ. Measured: one brief produced
            # {27%, 3 months, 1500}, {27%, 3 months, 86%} and {27%, 21 days} --
            # three samples of one brief's figures, all saying "any figure you
            # state must match the brief". An overlap test merged the first two
            # and stranded the third, which then FAILed on its own.
            #
            # Requiring a shared claim_class keeps genuinely different
            # prohibitions apart: "no regrowth promise in 21 days" is a
            # `guarantee` rule and does not merge into an `unsupported_outcome`
            # one just because both mention numbers.
            _cls_a = set(_a.get('claim_classes') or [])
            _cls_b = set(_b.get('claim_classes') or [])
            _same_kind = (_is_fig_rule(_a) and _is_fig_rule(_b)
                          and bool(_cls_a & _cls_b))
            # For everything else the hints ARE the meaning, so most of the
            # smaller list has to be shared.
            _shared = _ha & _hb
            if not _same_kind and (
                    len(_shared) / min(len(_ha), len(_hb)) < 0.6):
                continue
            # keep the more specific wording; union what each one checked
            _keep, _drop = ((_a, _b) if len(_a.get('requirement') or '')
                            >= len(_b.get('requirement') or '') else (_b, _a))
            _keep['match_hints'] = sorted(_ha | _hb)
            _keep['claim_classes'] = sorted(set(_keep.get('claim_classes') or [])
                                            | set(_drop.get('claim_classes') or []))
            _keep['flags'] = list(_keep.get('flags') or []) + [
                'MERGED_DUPLICATE_SAFETY_RULE']
            _dropped_dupes.append(_drop)
    if _dropped_dupes:
        out['requirements'] = [r for r in out['requirements']
                               if r not in _dropped_dupes]
        for _i, _r in enumerate(out['requirements'], 1):
            _r['ordinal'] = _i
        out['flags'] = list(out.get('flags') or []) + [{
            'code': 'DUPLICATE_SAFETY_RULES_MERGED',
            'detail': f'{len(_dropped_dupes)} forbidden rule(s) checked the same '
                      f'figures under different wording and were merged; the '
                      f'survivor checks the union of both'}]
        if verbose:
            print(f'  merged {len(_dropped_dupes)} duplicate safety rule(s): same '
                  f'match_hints, different wording.')
            print('    Judged separately they contradict each other -- one PASS, '
                  'one FAIL, same ask.')

    # 2b. The figures rule is guaranteed on the way IN and not on the way OUT.
    #
    #     compile_brief derives it whenever the brief states figures, and
    #     measurement agrees: 7 of 7 single-run compiles on disk carry a
    #     forbidden rule. But consensus then clusters, votes, releases orphaned
    #     groups and truncates to max_requirements, and nothing re-checks. A
    #     rule that survives none of that leaves an audit which silently stops
    #     checking claims while every other count still looks healthy.
    #
    #     The artifact everything downstream reads is this one, so the invariant
    #     is re-established here, from the same approved_claims and through the
    #     same Requirement construction compile_brief uses.
    _ac = out.get('approved_claims') or []
    _numeric = [c for c in _ac if c.get('numbers')]
    if _numeric and not any(r.get('polarity') == 'forbidden'
                            and 'unsupported_outcome' in (r.get('claim_classes') or [])
                            for r in out['requirements']):
        _figures = sorted({n for c in _numeric for n in c['numbers']})
        _ftext = ('Any figure stated about the product must match the brief: '
                  + ', '.join(_figures) + '.')
        out['requirements'].append(Requirement(
            id=requirement_id(_ftext, 'policy'),
            ordinal=len(out['requirements']) + 1,
            label='approved figures only', requirement=_ftext, type='policy',
            priority='critical', weight=PRIORITY_WEIGHT['critical'],
            polarity='forbidden', evidence_mode='any', machine_checkable=True,
            match_hints=_figures, acceptance_criteria=[_ftext],
            claim_classes=['unsupported_outcome'], source='inferred',
            brief_span='; '.join(c['text'] for c in _numeric)[:300],
            confidence=0.7,
            flags=['DERIVED_FROM_APPROVED_CLAIMS',
                   'RESTORED_AFTER_CONSENSUS']).to_dict())
        flags_restored = (f'the merged set had no rule checking the figures this '
                          f'brief states ({", ".join(_figures)}); one was derived '
                          f'from approved_claims')
        out['flags'] = list(out.get('flags') or []) + [
            {'code': 'NUMERIC_FIDELITY_RULE_RESTORED', 'detail': flags_restored}]
        if verbose:
            print(f'  consensus dropped the figures rule; RESTORED from '
                  f'approved_claims: {", ".join(_figures)}')
            print('    deterministic, not a model call -- a brief that states '
                  'figures always')
            print('    carries a rule that checks them.')

    # 2b1. Adoption again, on the MERGED set.
    #
    # compile_brief adopts per run; consensus then picks a representative by
    # longest wording, so a requirement adopted in one run can be replaced by
    # the un-adopted version from another. Measured: a hook option shipped with
    # group=None and no ADOPTED_INTO_GROUP flag, was scored as an independent
    # requirement, FAILed while its eleven siblings collapsed as group losers,
    # and cost 0.13 on the mean.
    #
    # Same lesson as the conflicts rebuild below: anything derived from
    # `requirements` must be derived again once `requirements` changes. The
    # function is idempotent, so this is free when the per-run adoption held.
    try:
        _re_adopted = adopt_stray_asks(out['requirements'],
                                       parse_brief_sections(out.get('brief_text') or ''))
        if _re_adopted:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'STRAY_ASKS_ADOPTED_AFTER_MERGE',
                'detail': f'{len(_re_adopted)} requirement(s) lost their group in '
                          f'the merge and were re-joined to the choice their own '
                          f'brief section defines'}]
            if verbose:
                print(f'  {len(_re_adopted)} stray ask(s) re-joined their choice '
                      f'group after the merge:')
                for _r in _re_adopted[:4]:
                    print(f'     {str(_r.get("label"))[:52]!r} -> '
                          f'{str(_r.get("group_label"))[:34]}')
    except Exception as _exc:
        out['flags'] = list(out.get('flags') or []) + [{
            'code': 'READOPT_FAILED', 'detail': str(_exc)[:160]}]

    # 2b2. One group, one ask -- before conflicts, which reads the requirements.
    try:
        # The brief's PRODUCT CLAIMS become requirements here, from the
        # parsed document rather than from the model. They are the only part
        # of the brief that says anything about the product, and asking the
        # model for them produced them in one run of three -- below the
        # consensus threshold, so they were dropped every time.
        _from_claims = requirements_from_claims(out['requirements'],
                                                out.get('approved_claims') or [])
        if _from_claims:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'REQUIREMENTS_FROM_CLAIMS',
                'detail': f'{len(_from_claims)} product claim(s) became '
                          f'requirements: {_from_claims[:4]}'}]
            if verbose:
                print(f'  {len(_from_claims)} talking point(s) -> requirements '
                      f'(parsed from the brief, not generated):')
                for _c in _from_claims[:8]:
                    print(f'     {_c[:66]}')
                print('    Each is its own scoring unit, so coverage is a real '
                      'ratio. Her own')
                print('    wording still counts -- substance credit applies as '
                      'usual.')

        # The document decides what is a choice, before intents are reconciled
        # -- reconciling the intent of a group that should not exist is work
        # thrown away.
        _compliance = ungroup_compliance_lines(out['requirements'])
        if _compliance and verbose:
            print(f'  {len(_compliance)} compliance line(s) UNGROUPED -- a '
                  f'disclaimer is mandatory, never one of a menu:')
            for _cid, _cg in _compliance[:4]:
                print(f'     {_cid} was an option in {_cg!r}')
            print('    In a one_of group it was NOT_APPLICABLE whenever any '
                  'sibling passed,')
            print('    so it was never actually checked.')
        _ungrouped = ungroup_non_alternatives(out['requirements'],
                                              brief_text)
        if _ungrouped:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'UNGROUPED_BY_STRUCTURE',
                'detail': f'{len(_ungrouped)} requirement(s) were grouped as a '
                          f'choice by the model, but the brief lists them in a '
                          f'requirements/claims section: '
                          f'{[g for _i, g, _t in _ungrouped][:4]}'}]
            if verbose:
                print(f'  {len(_ungrouped)} requirement(s) UNGROUPED -- the '
                      f'brief presents them as asks, not options:')
                for _i, _g, _t in _ungrouped[:6]:
                    print(f'     was {_g}: "{_t}"')
                print('    A one_of group is ONE scoring unit, so grouping '
                      'eight asks would have')
                print('    scored seven of them as satisfied by the first.')
        _fixed_intents = normalise_group_intents(out['requirements'])
        # One group, one ask -- and the ask has to describe its own options.
        _blind_intents = audit_group_intents(out['requirements'])
        if _blind_intents:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'GROUP_INTENT_SUBJECT_FREE',
                'detail': f'{len(_blind_intents)} group(s) carry an intent that '
                          f'shares no content word with their own options: '
                          f'{[g for g, _i, _n in _blind_intents][:4]}'}]
            if verbose:
                print(f'  WARN  {len(_blind_intents)} group intent(s) name a '
                      f'POSITION, not a thing to look for:')
                for _g, _i, _n in _blind_intents[:3]:
                    print(f'     {_g} ({_n} options): "{_i[:70]}"')
                print('    L3 judges alignment against this sentence, so it '
                      'will rate anything')
                print('    in the right position as aligned. Those alignments '
                      'are marked untrusted.')
        if _fixed_intents:
            out['flags'] = list(out.get('flags') or []) + [{
                'code': 'GROUP_INTENT_RECONCILED',
                'detail': f'{len(_fixed_intents)} group field(s) held more than '
                          f'one value across their members: {_fixed_intents[:4]}'}]
            if verbose:
                print(f'  reconciled {len(_fixed_intents)} group field(s) that '
                      f'differed between members of ONE group:')
                for _f in _fixed_intents[:4]:
                    print(f'     {_f}')
                print('    L3 judges alignment against group_intent, so members of')
                print('    one choice group have to be asked the same question.')
    except Exception as _exc:
        out['flags'] = list(out.get('flags') or []) + [{
            'code': 'GROUP_INTENT_RECONCILE_FAILED', 'detail': str(_exc)[:160]}]

    # 2c. Conflicts were detected on the BASE run, not on what ships.
    #
    #     `out = dict(base)` carries that run's conflict list into an artifact
    #     whose requirements have since been voted on, merged and released from
    #     dead groups. Printing a conflict's two sides then raises StopIteration,
    #     because one of the ids is no longer in `requirements` -- observed once
    #     the same-kind merge started removing duplicate safety rules.
    #
    #     Same lesson as the section/stat rebuild above: anything derived from
    #     `requirements` has to be derived again once `requirements` changes.
    #     detect_conflicts is pure and takes dicts, so this is cheap.
    try:
        _before = len(out.get('conflicts') or [])
        out['conflicts'] = detect_conflicts(out['requirements'])
        if verbose and _before != len(out['conflicts']):
            print(f'  conflicts recomputed on the merged set: '
                  f'{_before} -> {len(out["conflicts"])}')
    except Exception as _exc:
        out['flags'] = list(out.get('flags') or []) + [{
            'code': 'CONFLICT_RECOMPUTE_FAILED', 'detail': str(_exc)[:160]}]

    # 3. Recompute every derived count from the SURVIVING requirements, using
    #    the same rules as compile_brief (is_scorable = machine_checkable and
    #    type != 'other'; a one_of group is ONE scoring unit).
    _rs = out['requirements']
    _groups = {_r['group'] for _r in _rs if _r.get('group')}
    out['stats'] = dict(out.get('stats') or {}, **{
        'requirements': len(_rs),
        'scorable': sum(1 for r in _rs
                        if r.get('machine_checkable') and r.get('type') != 'other'),
        'not_machine_checkable': sum(1 for r in _rs
                                     if not r.get('machine_checkable')),
        'forbidden': sum(1 for r in _rs if r.get('polarity') == 'forbidden'),
        'with_temporal': sum(1 for r in _rs if any(
            r.get(k) is not None for k in ('deadline_seconds',
                                           'window_start_seconds',
                                           'window_end_seconds',
                                           'window_start_expr',
                                           'window_end_expr'))),
        'symbolic_windows': sum(1 for r in _rs if r.get('window_start_expr')
                                or r.get('window_end_expr')),
        'mode_disagreements': sum(1 for r in _rs if any(
            str(f).startswith('MODE_DISAGREES') for f in (r.get('flags') or []))),
        'choice_groups': len(_groups),
        'alternatives': sum(1 for r in _rs if r.get('group')),
        'scoring_units': len(_groups) + sum(
            1 for r in _rs if not r.get('group')
            and r.get('machine_checkable') and r.get('type') != 'other'),
        'total_weight': round(sum(float(r.get('weight') or 0) for r in _rs), 2),
    })
    # A consensus artifact is a DIFFERENT artifact; never overwrite the plain one.
    # CONTENT-ADDRESSED, because this stage is not deterministic.
    #
    # The base key is a function of inputs -- brief hash, config, prompt
    # version -- which is correct for a stage that returns the same thing
    # every time. Consensus does not: the same brief produced 15
    # requirements on one run and 20 on the next, and both were written to
    # the same path. The second overwrote the first, Phase 6's verdict key
    # never moved, and a cached audit was served for a requirement set that
    # no longer existed.
    #
    # The digest covers wording, mode, polarity, timing and grouping -- the
    # fields a reviewer would have checked. Two consensus runs that agree
    # share a key and reuse each other's work; two that differ cannot
    # collide.
    try:
        _digest = requirements_digest(out['requirements'])[:8]
    except Exception:
        _digest = 'nodigest'
    out['cache_key'] = f'{out.get("cache_key", "")}_c{n}_{_digest}'
    out['approved'] = False          # a new set needs a new approval
    out.pop('approved_digest', None)
    flags = list(out.get('flags') or [])
    if unstable:
        flags.append({'code': 'COMPILE_UNSTABLE',
                      'detail': f'{len(unstable)} requirement(s) appeared in some '
                                f'runs but not all; counts across runs: '
                                f'{out["consensus"]["counts"]}'})
    out['flags'] = flags
    if out.get('brief_hash') and out.get('cache_key'):
        write_json(DIRS['briefs'] / out['brief_hash'] /
                   f'requirements__{out["cache_key"]}.json', out)
    if verbose:
        _safety = [r for _c, r in stable
                   if any(str(f).startswith('KEPT_AS_SAFETY_RULE')
                          for f in (r.get('flags') or []))]
        print(f'  consensus over {n} run(s): {len(stable)} stable, '
              f'{len(unstable)} unstable')
        for _r in _safety:
            _seen = next(f.split(':')[1] for f in _r.get('flags') or []
                         if str(f).startswith('KEPT_AS_SAFETY_RULE'))
            print(f'     kept as a SAFETY rule ({_seen.replace("_", " ")}): '
                  f'{(_r.get("requirement") or "")[:62]}')
            print('       a majority would have dropped it. Losing a claims rule '
                  'is worse than')
            print('       carrying one the brief may not have meant.')
        for c, r in sorted(unstable, key=lambda x: -x[0])[:6]:
            print(f'     seen {c}/{n}: {(r.get("requirement") or "")[:72]}')
        print('  This did not make the model deterministic. It made the '
              'disagreement visible.')
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 976: print('§45 compile stage loaded.  Artifacts ->', DIRS['briefs'])
#   line 977: print('     compile_brief_consensus(text, runs=3) when reproducibility matte
