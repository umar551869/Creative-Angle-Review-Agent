# ============================================================================
# §77  Phase 7 test suite  --  no GPU, no network, no model, no API key
#
# Same standard as §71: every test names the BEHAVIOUR, not the
# implementation, so a test that fails tells you what broke for a user rather
# than which line moved.
#
# The headline one is `the sum, by hand`. If the arithmetic cannot be checked
# on paper, a creator manager cannot defend the number to a brand, and the
# whole phase is decoration.
# ============================================================================


def _run_phase7_tests_body(verbose: bool = True) -> bool:
    results = []

    def check(name, cond, detail=''):
        results.append((name, bool(cond)))
        if verbose:
            print(f'  {"PASS" if cond else "FAIL"}  {name}'
                  + (f'   [{detail}]' if detail and not cond else ''))

    def V(rid, status, priority='medium', flags=None, label='', ev=None, **kw):
        d = {'requirement_id': rid, 'status': status, 'priority': priority,
             'weight': PRIORITY_WEIGHT[priority], 'flags': flags or [],
             'requirement_label': label or rid, 'evidence_ids': ev or ['ev_1'],
             'reason': 'a reason', 'layer': 'L1', 'alignment': None,
             'examined_ids': []}
        d.update(kw)
        return d

    def Rq(rid, rtype='speech', priority='medium', polarity='required'):
        return {'id': rid, 'type': rtype, 'priority': priority,
                'polarity': polarity, 'label': rid}

    _n = {'i': 0}

    def audit(verdicts, standing=None):
        # A fresh cache key per call: the score artifact is keyed on the
        # verdict key, and reusing one with different verdicts would read a
        # stale score. In the pipeline that key is content-derived, so only a
        # test can arrange the collision -- and it must not.
        _n['i'] += 1
        return {'video_hash': 'test_vh', 'video_id': 'test', 'brief_hash': 'bh',
                'cache_key': f'test_key_{_n["i"]}', 'duration_seconds': 30.0,
                'verdicts': verdicts, 'sources': {'evidence': 'ek'},
                'standing': standing or {}, 'hook': {}, 'claims': {'enabled': False}}

    def brief(reqs):
        return {'cache_key': 'bk', 'brief_hash': 'bh', 'requirements': reqs,
                'brief_text': 'a brief'}

    def sc(verdicts, reqs, standing=None):
        return score_audit(audit(verdicts, standing), brief(reqs), verbose=False)

    if verbose:
        print('=' * 74)
        print('§77  PHASE 7 TESTS')
        print('=' * 74)
        print('-- the constants --')

    # ---- configuration invariants ----------------------------------------
    check('every requirement type maps to a dimension',
          not set(REQUIREMENT_TYPES) - set(TYPE_TO_DIMENSION))
    check('dimension weights sum to 1.0',
          abs(sum(DIMENSION_WEIGHT.values()) - 1.0) < 1e-9)
    check('UNCERTAIN has no score, so it cannot be averaged as one',
          'UNCERTAIN' not in STATUS_SCORE)
    check('NOT_APPLICABLE has no score either',
          'NOT_APPLICABLE' not in STATUS_SCORE)
    check('priority weights come from Phase 4, not a second copy',
          PRIORITY_WEIGHT.get('low') == 0.5 and PRIORITY_WEIGHT.get('critical') == 3.0)

    if verbose:
        print('-- the sum, by hand --')
    # PASS w1 + PARTIAL w2 + FAIL w3 -> (1*1 + 2*.5 + 3*0) / 6 = 2/6 = 33
    s = sc([V('r1', 'PASS'), V('r2', 'PARTIAL', 'high'), V('r3', 'FAIL', 'critical')],
           [Rq('r1'), Rq('r2'), Rq('r3', priority='critical')])
    check('score reproducible by hand: 2.0/6.0 -> 33',
          s['score']['headline'] == 33, s['score']['headline'])
    check('no decimal place is shown -- three decisions cannot carry one',
          float(s['score']['headline']).is_integer())

    if verbose:
        print('-- what leaves the denominator --')
    s = sc([V('w', 'PASS')] + [V(f'l{i}', 'NOT_APPLICABLE') for i in range(11)],
           [Rq('w')] + [Rq(f'l{i}') for i in range(11)])
    check('a one_of group contributes exactly one scoring unit',
          s['score']['scoring_units'] == 1, s['score']['scoring_units'])
    check('eleven unselected options do not become eleven failures',
          s['score']['headline'] == 100, s['score']['headline'])
    check('they are still counted and disclosed', s['counts']['not_applicable'] == 11)

    if verbose:
        print('-- UNCERTAIN is an abstention --')
    s = sc([V('r1', 'PASS'), V('r2', 'UNCERTAIN')], [Rq('r1'), Rq('r2')])
    check('pessimistic counts UNCERTAIN as 0', s['score']['band_low'] == 50)
    check('optimistic excludes it from the denominator', s['score']['band_high'] == 100)
    check('coverage reports how much was actually decided',
          s['score']['coverage'] == 0.5)
    check('pessimistic is never above optimistic',
          s['score']['band_low'] <= s['score']['band_high'])
    check('thin coverage leads with the band, not one number',
          s['score']['lead_with_band'] is True)
    s = sc([V('r1', 'PASS'), V('r2', 'FAIL')], [Rq('r1'), Rq('r2')])
    check('full coverage collapses the band to one number',
          s['score']['band_low'] == s['score']['band_high'] == 50)
    check('coverage 1.0 when nothing is UNCERTAIN', s['score']['coverage'] == 1.0)

    if verbose:
        print('-- compliance is not achievement --')
    s = sc([V('f1', 'PASS', flags=['PASS_FROM_ABSENCE']),
            V('f2', 'PASS', flags=['PASS_FROM_ABSENCE']), V('r1', 'FAIL')],
           [Rq('f1', 'policy'), Rq('f2', 'policy'), Rq('r1')])
    check('PASS_FROM_ABSENCE never contributes to achievement',
          s['score']['scoring_units'] == 1, s['score']['scoring_units'])
    check('an off-brief video does not score 67 on two vacuous passes',
          s['score']['headline'] == 0, s['score']['headline'])
    check('safety checks are counted and reported separately',
          s['safety']['checks'] == 2 and s['safety']['passed_by_absence'] == 2)

    if verbose:
        print('-- a requirement the brief never made --')
    # Phase 4 flags SPAN_NOT_IN_BRIEF when the compiler could not quote the
    # brief sentence a requirement came from. She is judged against what the
    # BRIEF asked, so an invented ask has nothing to judge against.
    _inv = Rq('bad')
    _inv['flags'] = ['SPAN_NOT_IN_BRIEF:possible_invention']
    s = sc([V('r1', 'PASS'), V('bad', 'FAIL')], [Rq('r1'), _inv])
    check('an untraceable requirement does not drag the score down',
          s['score']['headline'] == 100, s['score']['headline'])
    check('...it leaves the denominator entirely',
          s['score']['scoring_units'] == 1, s['score']['scoring_units'])
    check('...and it is counted, not silently dropped',
          s['score']['not_in_brief_excluded'] == 1)
    check('...and named, so the brief can be fixed',
          s['score']['not_in_brief_ids'] == ['bad'],
          str(s['score']['not_in_brief_ids']))
    s = sc([V('r1', 'PASS'), V('r2', 'FAIL')], [Rq('r1'), Rq('r2')])
    check('a traceable requirement still scores normally',
          s['score']['headline'] == 50 and not s['score']['not_in_brief_excluded'])

    if verbose:
        print('-- dimensions --')
    s = sc([V('h', 'PASS'), V('c', 'FAIL')], [Rq('h', 'hook'), Rq('c', 'cta')])
    d = s['dimensions']
    check('a brief covering 2 of 7 dimensions normalises over 2',
          abs(d['hook']['weight_normalised'] - 0.6667) < 0.001,
          d['hook']['weight_normalised'])
    check('normalised weights of covered dimensions sum to 1',
          abs(sum(d[k]['weight_normalised'] for k in s['dimensions_covered']) - 1.0)
          < 0.001)
    check('an uncovered dimension scores None, never 0',
          d['audience']['score'] is None and d['audience']['covered'] is False)
    check('uncovered dimensions are named, not silently dropped',
          len(s['dimensions_absent']) == 5)
    check('a dimension resting on one decision is marked thin',
          d['hook']['thin'] is True)

    if verbose:
        print('-- question 1 before question 2: the relevance gate --')
    # A video that satisfies generic requirements while being about a
    # different product. Without the gate this reads as a good score.
    _good = [V('r1', 'PASS'), V('r2', 'PASS'), V('r3', 'PASS')]
    _reqs = [Rq('r1'), Rq('r2'), Rq('r3')]
    s = sc(_good, _reqs, standing={'standing': 'off_brief', 'weight': 0.0,
                                   'verdict': 'A different product entirely.'})
    check('an off_brief video is gated, not scored 100',
          s['score']['gated'] is True and s['score']['status_band'] == 'OFF_BRIEF',
          f"{s['score']['status_band']} / gated={s['score']['gated']}")
    check('the arithmetic is kept, not destroyed',
          s['score']['band_high'] == 100, s['score']['band_high'])
    check('the gate says why in words', bool(s['score']['gate_reason']))
    s = sc(_good, _reqs, standing={'standing': 'tangential', 'weight': 0.25,
                                   'verdict': 'Barely touches it.'})
    check('tangential is gated too', s['score']['gated'] is True)
    s = sc(_good, _reqs, standing={'standing': 'partial', 'weight': 0.55,
                                   'verdict': 'Covers some of it.'})
    check('partial is ON brief and gets a score',
          s['score']['gated'] is False and s['score']['status_band'] == 'APPROVED',
          s['score']['status_band'])
    for lvl in ('on_brief', 'exemplary'):
        s = sc(_good, _reqs, standing={'standing': lvl, 'weight': 1.0})
        check(f'{lvl} is scored normally', s['score']['gated'] is False)

    # A gate driven by one model call must FAIL OPEN. "We could not tell" is
    # not "off brief" -- the same rule as Phase 5's can_fail_on.
    s = sc(_good, _reqs, standing={})
    check('an unjudged relevance does NOT gate the score',
          s['score']['gated'] is False, str(s['relevance']))
    check('but it records that nobody judged it',
          s['relevance']['judged'] is False)
    check('and says so in words', 'could not tell' in s['relevance']['why'])

    if verbose:
        print('-- the grade reads from what is ESTABLISHED --')
    # The live case: 3 units, one undecided. Optimistic 100, pessimistic 75.
    # Grading from the optimistic end stamped APPROVED on a quarter of the
    # weight nobody judged -- plan.md's "most damaging error class".
    s = sc([V('r1', 'PASS'), V('r2', 'PASS'), V('r3', 'UNCERTAIN')],
           [Rq('r1'), Rq('r2'), Rq('r3')])
    check('a 75%-coverage band is graded from the LOW end',
          s['score']['band_low'] == 67 and s['score']['band_high'] == 100
          and s['score']['band_basis'] == 'pessimistic',
          f"{s['score']['band_low']}-{s['score']['band_high']} "
          f"{s['score']['status_band']}")
    check('...so an undecided quarter cannot be stamped APPROVED',
          s['score']['status_band'] != 'APPROVED', s['score']['status_band'])
    check('...and the artifact records which end it read',
          s['score']['band_basis'] == 'pessimistic')
    # Full coverage: both ends agree, so nothing changes.
    s = sc([V('r1', 'PASS'), V('r2', 'PASS')], [Rq('r1'), Rq('r2')])
    check('at full coverage the grade still comes from the single number',
          s['score']['status_band'] == 'APPROVED'
          and s['score']['band_basis'] == 'optimistic',
          f"{s['score']['status_band']} via {s['score']['band_basis']}")
    check('...and the two ends have converged', s['score']['band_low'] == 100
          and s['score']['band_high'] == 100)

    if verbose:
        print('-- a hook is a hook, however the compiler typed it --')
    # Measured on a live brief: 19 of 22 requirements came back
    # `speech_or_text`, including every hook option and every CTA. All of them
    # landed in Messaging and the report said the brief covered no hook.
    _hook_req = {'id': 'h1', 'type': 'speech_or_text', 'priority': 'medium',
                 'polarity': 'required', 'group': 'hook_options_group',
                 'group_label': 'Hook Concepts'}
    _cta_req = {'id': 'c1', 'type': 'speech_or_text', 'priority': 'medium',
                'polarity': 'required', 'group': 'cta_ideas_group',
                'group_label': 'Call to action (CTA) Ideas'}
    _msg_req = {'id': 'm1', 'type': 'speech_or_text', 'priority': 'medium',
                'polarity': 'required', 'group': 'creative_concepts_group',
                'group_label': 'Creative concepts'}
    check('a modality-typed hook resolves to Hook',
          resolve_dimension(_hook_req)[0] == 'hook',
          str(resolve_dimension(_hook_req)))
    check('...and says it was inferred, not declared',
          resolve_dimension(_hook_req)[1] != 'typed')
    check('an underscored group id still matches -- cta_ideas_group',
          resolve_dimension(_cta_req)[0] == 'cta',
          'the separator is normalised before the word match')
    check('a group with no dimension word stays Messaging',
          resolve_dimension(_msg_req)[0] == 'messaging',
          str(resolve_dimension(_msg_req)))
    check('a DECLARED type always wins over the grouping',
          resolve_dimension({'type': 'cta', 'group': 'hook_options_group'})
          == ('cta', 'typed'))
    check('no group at all falls back to the type map',
          resolve_dimension({'type': 'speech_or_text'}) == ('messaging', 'typed'))
    check('an empty requirement does not raise',
          resolve_dimension({})[0] in DIMENSION_KEYS)
    check('None for the verdict is accepted',
          resolve_dimension(_hook_req, None)[0] == 'hook')
    # end to end: the live shape, three units that used to collapse into one
    s = sc([V('h1', 'PASS'), V('c1', 'FAIL'), V('m1', 'PARTIAL')],
           [_hook_req, _cta_req, _msg_req])
    check('three modality-typed units land in THREE dimensions',
          sorted(s['dimensions_covered']) == ['cta', 'hook', 'messaging'],
          str(s['dimensions_covered']))
    check('...and the inferred ones are named in the artifact',
          s['dimensions']['hook']['inferred_units'] == ['h1']
          and s['dimensions']['cta']['inferred_units'] == ['c1'])
    check('...while the typed one claims no inference',
          s['dimensions']['messaging']['inferred_units'] == [])

    if verbose:
        print('-- the critical floor --')
    s = sc([V('r1', 'PASS'), V('r2', 'PASS'), V('r3', 'PASS'),
            V('bad', 'FAIL', 'critical')],
           [Rq('r1'), Rq('r2'), Rq('r3'), Rq('bad', priority='critical')])
    check('a critical FAIL cannot be averaged into APPROVED',
          s['score']['status_band'] != 'APPROVED', s['score']['status_band'])
    check('the floor is recorded, not silently applied',
          s['score']['critical_fail_ids'] == ['bad'])
    s = sc([V('r1', 'PASS'), V('r2', 'FAIL')], [Rq('r1'), Rq('r2')])
    check('a non-critical FAIL applies no floor',
          s['score']['critical_floor_applied'] is False)

    if verbose:
        print('-- band boundaries, both sides --')
    for val, want in ((85.0, 'APPROVED'), (84.99, 'NEEDS_MINOR_REVISION'),
                      (70.0, 'NEEDS_MINOR_REVISION'), (69.99, 'NEEDS_MAJOR_REVISION'),
                      (50.0, 'NEEDS_MAJOR_REVISION'), (49.99, 'REJECTED'),
                      (0.0, 'REJECTED'), (100.0, 'APPROVED')):
        check(f'{val} lands in {want}', band_for(val) == want, band_for(val))

    if verbose:
        print('-- degenerate input --')
    s = sc([], [])
    check('an empty verdict list does not divide by zero',
          s['score']['headline'] is None)
    check('no verdicts gives no score, not a score of 0',
          s['score']['headline'] is None and s['score']['coverage'] == 0.0)
    s = sc([V('x', 'NOT_APPLICABLE')], [Rq('x')])
    check('all-NOT_APPLICABLE yields no score', s['score']['headline'] is None)
    s = sc([V('u', 'UNCERTAIN')], [Rq('u')])
    check('all-UNCERTAIN gives 0 coverage and no optimistic figure',
          s['score']['coverage'] == 0.0 and s['score']['band_high'] is None)

    if verbose:
        print('-- contradictions: the qualitative gate --')
    s = sc([V('r1', 'PASS', label='Mention the 27% statistic')], [Rq('r1')],
           standing={'standing': 'off_brief', 'weight': 0.0,
                     'verdict': 'A different product.',
                     'missing': ['Mention the 27% statistic'],
                     'evidence_ids': ['ev_9']})
    codes = [c['code'] for c in s['contradictions']]
    check('off_brief standing against a high score is a contradiction',
          'STANDING_CONTRADICTS_SCORE' in codes, codes)
    check('a PASS the whole-video read calls missing is a contradiction',
          'PASS_BUT_STANDING_CALLS_IT_MISSING' in codes, codes)
    check('every contradiction names its evidence',
          all('evidence_ids' in c for c in s['contradictions']))

    # THE MIRROR IMAGE, which went unchecked until the Biostime batch produced
    # two videos at `standing=exemplary` scoring 14 and 43. Only the
    # "off-brief but scored high" direction was caught; "the brief's intent was
    # fully served" against a reject-band score is the same disagreement and
    # just as informative.
    s = sc([V('r1', 'FAIL'), V('r2', 'FAIL'), V('r3', 'PASS')],
           [Rq('r1'), Rq('r2'), Rq('r3')],
           standing={'standing': 'exemplary', 'weight': 1.0,
                     'verdict': 'Serves the brief fully and adds to it.',
                     'evidence_ids': ['ev_3']})
    codes = [c['code'] for c in s['contradictions']]
    check('an exemplary standing against a reject-band score is a contradiction',
          'LOW_SCORE_CONTRADICTS_STANDING' in codes,
          f'{s["score"]["headline"]} vs standing=exemplary -> {codes}')
    check('...and it names which side might be wrong',
          any('too generous' in c.get('detail', '')
              for c in s['contradictions']))
    # and it must NOT fire when the two agree
    s = sc([V('r1', 'PASS'), V('r2', 'PASS')], [Rq('r1'), Rq('r2')],
           standing={'standing': 'on_brief', 'weight': 0.85, 'verdict': 'good',
                     'evidence_ids': ['ev_1']})
    check('a good score with on_brief standing raises nothing',
          'LOW_SCORE_CONTRADICTS_STANDING' not in
          [c['code'] for c in s['contradictions']],
          'the two reads agree; there is no finding here')
    s = sc([V('p', 'FAIL')], [Rq('p', 'policy', polarity='forbidden')])
    check('a failed forbidden-content check is a contradiction',
          'SAFETY_CHECK_FAILED' in [c['code'] for c in s['contradictions']])
    s = sc([V('r1', 'PASS')], [Rq('r1')],
           standing={'standing': 'on_brief', 'weight': 0.85, 'verdict': 'Good.',
                     'missing': []})
    check('an audit that agrees with itself raises nothing',
          s['contradictions'] == [], s['contradictions'])

    if verbose:
        print('-- no model output can reach a numeric field --')
    s = sc([V('r1', 'PASS'), V('r2', 'FAIL')], [Rq('r1'), Rq('r2')])
    check('the score artifact declares itself model-free',
          s['provenance']['model_free'] is True)
    check('the constants used travel with the artifact',
          s['provenance']['status_score'] == dict(STATUS_SCORE)
          and s['provenance']['priority_weight'] == dict(PRIORITY_WEIGHT))
    check('thresholds are declared placeholders in the artifact',
          s['score']['thresholds_are_placeholders'] is True)
    _numeric_keys = [k for k, v in s['score'].items()
                     if isinstance(v, (int, float)) and not isinstance(v, bool)]
    check('every numeric field in the score came from this cell',
          set(_numeric_keys) <= {'headline', 'band_low', 'band_high', 'coverage',
                                 'scoring_units', 'decided_units', 'total_weight',
                                 # The strict reading, computed by the same
                                 # arithmetic over the literal statuses Phase 6
                                 # kept on each credited verdict. No model
                                 # number reaches the artifact here either.
                                 'literal_headline', 'literal_band_low',
                                 'credited_in_substance',
                                 'not_in_brief_excluded'},
          _numeric_keys)
    check('a recommendation containing a number is rejected',
          bool(_rec_violations('You scored 60 percent')))
    check('a recommendation containing a status word is rejected',
          bool(_rec_violations('This requirement is a FAIL')))
    check('an ordinary edit is not rejected',
          not _rec_violations('Name the wheat-seed oil after the jar shot'))
    check('the word-boundary rule holds -- "passing" is not "pass"',
          not _rec_violations('Show her passing the brush through her hair'))

    if verbose:
        print('-- advice respects the gate --')
    # Telling someone who filmed a pill organiser to "add a sentence about
    # barrier support at 0:11" is not advice, and it implies the video is
    # nearly right. §78 must abstain, and must not spend a model call doing it.
    _off = sc([V('r1', 'FAIL'), V('r2', 'PARTIAL')], [Rq('r1'), Rq('r2')],
              standing={'standing': 'off_brief', 'weight': 0.0,
                        'verdict': 'A different product.'})
    _r = evaluate_recommendations(audit([V('r1', 'FAIL'), V('r2', 'PARTIAL')]),
                                  brief([Rq('r1'), Rq('r2')]), _off, [],
                                  backend=None, verbose=False)
    check('no edits are proposed for an off-brief video',
          _r['recommendations'] == [])
    check('it explains that the remedy is a different video, not a cut',
          'different video' in _r.get('note', ''))
    check('and it spends no model call to say so',
          'RECOMMEND_GATED_OFF_BRIEF' in _r['flags'] and _r.get('backend') is None)

    if verbose:
        print('-- determinism --')
    a = audit([V('r1', 'PASS'), V('r2', 'FAIL')])
    b = brief([Rq('r1'), Rq('r2')])
    s1 = score_audit(a, b, verbose=False)
    s2 = score_audit(a, b, force=True, verbose=False)
    s1.pop('provenance', None)
    s2.pop('provenance', None)
    check('the same artifact scored twice is identical',
          canonical_json(s1) == canonical_json(s2))
    check('the score names the verdict artifact it was computed from',
          s1['scored_from']['verdicts_cache_key'] == a['cache_key'])

    if verbose:
        print('-- the page --')

    class _Rec:
        """The two fields the report reads. A unit test should not need the
        whole EvidenceRecord to prove a timestamp becomes a link."""

        def __init__(self, i, mod, t0, t1, text=''):
            self.id, self.modality = i, mod
            self.start_seconds, self.end_seconds = t0, t1
            self.raw_text, self.description = text, ''

    _recs = [_Rec('ev_1', 'speech', 1.5, 4.0, 'Blow drying ruined my hair.'),
             _Rec('ev_2', 'ocr', 28.0, 30.0, 'LINK IN BIO')]
    _v = [V('r1', 'PASS', label='<script>alert(1)</script>', ev=['ev_1'])]
    s = sc(_v, [Rq('r1')])
    _a, _b = audit(_v), brief([Rq('r1')])
    html = build_report_html({'video_hash': 'test_vh', 'path': ''}, _a, _b, s,
                             _recs, None, {}, None, P7)
    check('the report is a complete HTML document',
          html.startswith('<!doctype html>') and html.rstrip().endswith('</html>'))
    check('markup in a requirement label cannot form a tag',
          '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html)
    check('a cited record becomes a clickable seek link',
          'class="ts" href="#player" data-t="1.500"' in html)
    check('the timestamp reads as minutes:seconds, not raw float',
          '>0:01<' in html)
    check('the seek handler is in the page', 'currentTime' in html)
    check('the evidence timeline shows a lane per modality',
          'lane-name' in html and 'm-speech' in html and 'm-ocr' in html)
    # The REQUIREMENT is that the reader is told the thresholds are not yet
    # calibrated. The word "placeholder" was how that requirement happened to
    # be phrased, not the requirement itself -- the report now says
    # "provisional", which is the same disclosure in English a creator reads.
    # Accepting either keeps the guard (delete the disclosure and this still
    # fails) without pinning the page to one word.
    _low = html.lower()
    check('uncalibrated thresholds are disclosed to the reader',
          ('placeholder' in _low or 'provisional' in _low)
          and 'threshold' in _low)
    # §46: a report built on an unapproved compile carries no authority, and
    # the reader has no other way to know that.
    check('an unapproved brief is called out unmissably',
          'never approved' in html and 'carries authority' in html)
    _appr = dict(_b)
    _appr['approved'] = True
    _appr['approved_by'] = 'a reviewer'
    _ah = build_report_html({'video_hash': 'test_vh', 'path': ''}, _a, _appr, s,
                            _recs, None, {}, None, P7)
    check('an approved brief says who approved it',
          'approved by a reviewer' in _ah and 'never approved' not in _ah)
    h2 = build_report_html({'video_hash': 'test_vh', 'path': ''}, _a, _b, s,
                           _recs, None, {}, None, P7)
    check('rendering the same score twice gives the same bytes', html == h2)
    check('a report with no records still renders',
          build_report_html({'video_hash': 'test_vh', 'path': ''}, _a, _b, s,
                            [], None, {}, None, P7).startswith('<!doctype'))

    # The gate has to reach the PAGE, not just the artifact.
    _gv = [V('r1', 'PASS'), V('r2', 'PASS')]
    _gs = sc(_gv, [Rq('r1'), Rq('r2')],
             standing={'standing': 'off_brief', 'weight': 0.0,
                       'verdict': 'This is a pill organiser, not hair care.'})
    _gh = build_report_html({'video_hash': 'test_vh', 'path': ''}, audit(_gv),
                            brief([Rq('r1'), Rq('r2')]), _gs, _recs, None, {},
                            None, P7)
    check('a gated report says "off brief" instead of a number',
          'off brief' in _gh and '>100<' not in _gh)
    check('it quotes what the whole-video read actually said',
          'pill organiser' in _gh)
    check('it withholds the dimension bars too', 'Withheld' in _gh)
    check('and says the arithmetic is still available, not hidden',
          'appendix' in _gh.lower())

    if verbose:
        print('-- figures degrade rather than block --')
    f = build_figures(s, audit([V('r1', 'PASS')]), [], [], P7)
    check('figures report whether plotly was available',
          isinstance(f.get('plotly_available'), bool))
    check('a figure that cannot be drawn leaves a note saying why',
          bool(f.get('figures')) or bool(f.get('notes')))
    check('the report renders whether or not figures exist',
          bool(build_report_html({'video_hash': 'test_vh', 'path': ''},
                                 audit([V('r1', 'PASS')]), brief([Rq('r1')]),
                                 s, [], None, f, None, P7)))
    check('the embed_plotly flag actually does something',
          build_figures(s, audit([V('r1', 'PASS')]), [], [],
                        Phase7Config(report=ReportConfig(embed_plotly=False))
                        )['figures'] == [])

    if verbose:
        print('-- what aligns with the brief, and how closely --')
    _av = [V('a1', 'PASS', label='Open with a hook', ev=['ev_1'],
             alignment='exact'),
           V('a2', 'FAIL', 'critical', label='Name the oil', ev=['ev_1'],
             alignment='none'),
           V('a3', 'PARTIAL', label='Show the product', ev=['ev_1'],
             alignment='partial'),
           # nobody judged this one -- it must not be drawn as a zero
           V('a4', 'PASS', label='No medical claims', ev=[],
             flags=['PASS_FROM_ABSENCE'])]
    _ar = [Rq('a1', 'hook'), Rq('a2', 'speech', priority='critical'),
           Rq('a3', 'visual'), Rq('a4', 'policy', polarity='forbidden')]
    _as = sc(_av, _ar, standing={'standing': 'on_brief', 'weight': 0.85})
    _af = build_figures(_as, audit(_av), _recs, [], P7)
    _aids = [x['id'] for x in _af['figures']]
    if _af.get('plotly_available'):
        check('the alignment landscape is drawn', 'fig-alignment-landscape' in _aids,
              str(_aids))
        check('it leads the figures -- it is the question people open with',
              _aids[0] == 'fig-alignment-landscape', str(_aids[:1]))
        _lh = next(x['html'] for x in _af['figures']
                   if x['id'] == 'fig-alignment-landscape')
        check('an unjudged alignment is drawn apart, never as "none"',
              'not judged' in _lh)
        check('the closeness axis is labelled in words',
              'tangential' in _lh and 'exact' in _lh)
        check('every marker carries its evidence ids', 'customdata' in _lh)
        check('the same score draws byte-identical figures',
              build_figures(_as, audit(_av), _recs, [], P7)['figures'][0]['html']
              == _lh)
    else:
        check('figures skipped cleanly when plotly is absent',
              not _aids and bool(_af['notes']))
    # Alignment figures survive the gate ON PURPOSE: a landscape sitting
    # entirely at `none` is the evidence FOR calling a video off brief.
    _gs2 = sc(_av, _ar, standing={'standing': 'off_brief', 'weight': 0.0,
                                  'verdict': 'Another product.'})
    _gf = build_figures(_gs2, audit(_av), _recs, [], P7)
    check('an off-brief audit still gets its alignment figures',
          (not _gf.get('plotly_available'))
          or 'fig-alignment-landscape' in [x['id'] for x in _gf['figures']])

    failed = [n for n, ok in results if not ok]
    if verbose:
        print()
        print(f'{len(results) - len(failed)}/{len(results)} checks pass')
        print('ALL PASS' if not failed
              else 'FAILED:\n   ' + '\n   '.join(failed))
    return not failed


def _run_phase7_tests(verbose: bool = True) -> bool:
    """
    Run the suite against a THROWAWAY artifacts directory.

    Two things made this necessary, and both were live:

      * score_audit caches on disk, and this suite keys its fixtures by
        POSITION (`test_key_1`, `test_key_2`, ...). Insert a test and every
        later ordinal names a different fixture than it did last run -- while
        last run's artifact is still there under the matching key. The cache
        then hands back a score computed by older code. Observed: a 3-unit
        fixture reporting 50.0-50.0 with no `band_basis` field at all.
      * the fixtures wrote a `test_vh` folder into work/artifacts, which §74b
        dutifully counted as a video with artifacts.

    A fresh temp directory per run cannot collide with a previous run, and
    nothing survives it to be miscounted. DIRS is restored in `finally`, so an
    exception mid-suite cannot leave the notebook pointed at a deleted path.
    """
    import shutil as _sh
    import tempfile as _tf

    _sandbox = Path(_tf.mkdtemp(prefix='p7_tests_'))
    _real = DIRS['artifacts']
    DIRS['artifacts'] = _sandbox
    try:
        ok = _run_phase7_tests_body(verbose=verbose)
    finally:
        DIRS['artifacts'] = _real
        _sh.rmtree(_sandbox, ignore_errors=True)
    if verbose:
        _leaked = [p.name for p in _real.glob('test_vh*')] if _real.exists() else []
        print(f'  (ran in a sandbox; artifacts left in work/artifacts: '
              f'{_leaked or "none"})')
    return ok


_p7_tests_ok = _run_phase7_tests(verbose=True)
