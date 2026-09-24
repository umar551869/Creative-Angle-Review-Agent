# ============================================================================
# §76  score_audit  --  the number, by arithmetic
#
# Pure arithmetic. No model call, no network, no I/O beyond the cache write.
# If a value in the output cannot be recomputed by hand from the verdict
# artifact plus §75's constants, it does not belong here.
#
# Three rules inherited from §73b, and they are the reason this is not a
# one-line weighted mean:
#
#   1. UNCERTAIN is an abstention, not a zero. Averaging it as 0 turns
#      "we did not look" into "they failed". So the output is a BAND.
#   2. NOT_APPLICABLE leaves the denominator. A twelve-option hook list is ONE
#      decision; the eleven losers are not eleven failures.
#   3. A forbidden rule that passed because the video never went near the
#      subject is COMPLIANCE, not ACHIEVEMENT. Measured in Phase 6: two such
#      passes contributed 65% of an off-brief video's score. They are counted
#      and reported separately, never averaged in.
# ============================================================================


def _score_weight(v: dict) -> float:
    """
    Priority is the rule, because priority is what a human can check.

    THE documented rule is PRIORITY_WEIGHT[priority]. The verdict also carries
    a `weight` that Phase 4 derived from the same priority; if the two ever
    disagree the artifact says so rather than silently preferring one.

    ONE exception, and it is arithmetic rather than judgement: the collapsed
    talking-points unit stands in for N bullets and carries the SUM of their
    weights, so that merging them changes how they are scored without changing
    how much of the brief they represent. It is computed here, recorded on the
    unit, and printed in the unit's own reason -- a reader can still do the sum
    by hand, which is the only property this function exists to protect.
    """
    _override = v.get('_weight_override')
    if _override is not None:
        return float(_override)
    return float(PRIORITY_WEIGHT.get(v.get('priority') or 'medium', 1.0))


def _unit_value(v: dict) -> float:
    """What this unit earns, 0..1. STATUS_SCORE unless it carries its own.

    THE documented rule is STATUS_SCORE[status], and it stays the rule for
    every verdict a model produced. The one exception is a unit this file
    SYNTHESISED -- the collapsed talking-points unit -- whose value is a
    coverage fraction computed here by arithmetic and printed in its own
    reason. Three statuses cannot express "6 of 7", and rounding it to PASS is
    what made 3-of-7 and 6-of-7 score identically.

    A model still never writes a number: this one is computed from the
    verdicts by code a reader can redo by hand.
    """
    ov = v.get('_score_override')
    if ov is not None:
        return float(ov)
    return STATUS_SCORE[v['status']]


def _is_safety_pass(v: dict) -> bool:
    """A PASS earned by absence: compliance established, nothing achieved."""
    return any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))


def _is_talking_point(v: dict, req_index: dict) -> bool:
    """A feature bullet the brief offers, as opposed to something it demands.

    TWO signals, because the brief's bullets arrive by two routes and a
    talking point is a talking point either way:

      source='approved_claims'   requirements_from_claims built it (fix 16)
      FROM_APPROVED_CLAIMS:<x>   the MODEL compiled it and Phase 4 matched it
                                 back to an approved claim

    Using only the first split the count: the report's headline said "7 of 8"
    (it keys on the flag) while the scoring note said "of 7" (it keyed on
    source), and the page showed two denominators for one thing. Same
    predicate now, so the two cannot disagree -- which is the property
    talking_point_coverage's own docstring claims for itself.
    """
    rq = req_index.get(v.get('requirement_id')) or {}
    if (rq.get('source') or v.get('source') or '') == 'approved_claims':
        return True
    return any(str(f).startswith('FROM_APPROVED_CLAIMS')
               for f in (rq.get('flags') or []))


def _collapse_talking_points(units: list, req_index: dict,
                             cfg: Phase7Config, compiled: dict = None) -> tuple:
    """
    The brief's feature bullets become ONE unit, scored by COVERAGE.

    WHY. The Biostime brief calls itself "Format Library, Hooks and Talking
    Points", exists "to SHOWCASE effective hooks", says creators "CAN use"
    them, and states "we encourage creators to bring their own style and
    personality". Its 10 hooks and 4 CTAs are already pick-one menus. Its 8
    feature bullets were not: each was an independent mandatory requirement, so
    they were 8 of 11 scoring units and every creator lost most of the
    Messaging dimension by construction. A 40-second video cannot recite eight
    product features and the brief never asked it to.

    WHAT IS PRESERVED. The collapsed unit inherits the SUM of the bullets'
    weights, so the brief's emphasis is unchanged -- eight bullets still carry
    what eight bullets carried. Only the all-or-nothing-per-bullet penalty
    goes. Every bullet keeps its own verdict, its own report row and the "N of
    8" headline: nothing is hidden, and the arithmetic below is still
    checkable by hand.

    AN OFF-BRIEF VIDEO STILL SCORES ZERO HERE. Coverage of the brand's own
    talking points IS the measure of "is she talking about this product", so a
    video that covers none earns none of this weight -- which is the whole
    reason this unit can carry it. The separate `standing` gate is unchanged
    and still decides OFF_BRIEF on its own.

    Returns (units_with_collapse, summary_or_None).
    """
    tps = [v for v in units if _is_talking_point(v, req_index)]
    if len(tps) < 2:
        return units, None

    # ---- DOES THIS BRIEF OFFER THEM, OR DEMAND THEM? -----------------------
    # Read from the document by Phase 4, never assumed here. A brief that says
    # "we encourage creators to bring their own style" is a menu and coverage
    # is the right measure. A brief that says "every video MUST state all of
    # the following" is a checklist, and collapsing it would let a creator
    # skip most of a mandatory disclosure list and still score well -- the
    # false PASS this whole design exists to prevent.
    _ob = ((compiled or {}).get('claims_obligation') or {})
    if _ob.get('obligation') == 'required':
        return units, {'offered': len(tps), 'collapsed': False,
                       'obligation': 'required',
                       'obligation_from': _ob.get('from'),
                       'why': ('The brief DEMANDS these rather than offering '
                               'them, so each is scored on its own.')}

    # PARTIAL is half a point: she raised the subject without landing it.
    covered = sum(STATUS_SCORE.get(v.get('status'), 0.0) for v in tps
                  if v.get('status') in STATUS_SCORE)
    decided = [v for v in tps if v.get('status') in STATUS_SCORE]
    offered = float(len(tps))
    # ---- the target SCALES with the brief ----------------------------------
    # A flat 3 was fitted to a brief with eight bullets. It is "cover nearly
    # all of them" for a brief with three, and "cover 15%" for a brief with
    # twenty. Neither is what the flat number meant. Scale it, and keep the
    # flat value as a FLOOR so a very short list still has to be covered
    # properly. Measured: 2->2, 3->3, 5->3, 8->4, 12->5, 20->8.
    #
    # NOTE this DOES move the Biostime target from 3 to 4, because fix 38
    # brought the count from 7 to 8. Said plainly rather than buried: the
    # scaling rule is brief-agnostic, and the price is that this brief gets
    # marginally stricter than the run you last saw.
    _frac = float(getattr(cfg.score, 'talking_point_target_fraction', 0.4))
    _floor = int(getattr(cfg.score, 'talking_point_target_PLACEHOLDER', 3))
    _scaled = _frac * len(tps)                  # ceil, without importing math
    _scaled = int(_scaled) + (1 if _scaled > int(_scaled) else 0)
    target = float(max(1, min(len(tps), max(_floor, _scaled))))
    # ---- GRADED, not a cliff ------------------------------------------------
    # The first version capped at the target: covered 3 of 7 and covered 6 of 7
    # both scored full marks, so two videos differing by double the coverage
    # landed 7 points apart, and that gap came from other dimensions entirely.
    # Fine for pass/fail; useless for RANKING, and ranking is exactly what
    # Phase 8 has to calibrate against.
    #
    # So: reaching the target earns `target_credit`, and the remaining credit
    # is earned across the rest. Full coverage earns 1.0; below target it
    # falls proportionally to 0. Still pure arithmetic from the verdicts, and
    # a reader can redo it from the three numbers printed on the page.
    _full = float(getattr(cfg.score, 'talking_point_target_credit', 0.7))
    _tgt_r = target / offered if offered else 1.0
    _cov_r = (covered / offered) if offered else 0.0
    if _cov_r >= _tgt_r:
        span = (1.0 - _tgt_r) or 1.0
        unit_score = _full + (1.0 - _full) * min(1.0, (_cov_r - _tgt_r) / span)
    else:
        unit_score = _full * (_cov_r / _tgt_r if _tgt_r else 0.0)
    unit_score = round(max(0.0, min(1.0, unit_score)), 4)
    ratio = round(_cov_r, 4)

    if not decided:
        # Nothing was decidable -- abstain rather than invent a failure.
        status = 'UNCERTAIN'
    elif unit_score >= _full:
        status = 'PASS'
    elif unit_score > 0.0:
        status = 'PARTIAL'
    else:
        status = 'FAIL'

    total_w = sum(_score_weight(v) for v in tps)
    # _score_weight reads `priority`, so express the summed weight as the
    # priority that carries it. Anything else would make the artifact's own
    # documented rule (PRIORITY_WEIGHT[priority]) stop reproducing the number.
    unit = {
        'requirement_id': 'talking_points__collapsed',
        # The bullets this unit stands for. Carried so the dimension listing,
        # and therefore the report and the figures, can still place each one.
        'member_requirement_ids': sorted(v.get('requirement_id', '')
                                         for v in tps),
        'requirement_label': f'Key talking points ({len(tps)} offered by the brief)',
        'status': status,
        'priority': 'medium',
        'dimension': 'messaging',
        'layer': 'arithmetic',
        'evidence_ids': sorted({e for v in tps
                                for e in (v.get('evidence_ids') or [])})[:12],
        'flags': ['TALKING_POINTS_COLLAPSED',
                  f'TALKING_POINT_TARGET_PLACEHOLDER:{target}'],
        # The unit's own score, so coverage RANKS instead of clearing a bar.
        '_score_override': unit_score,
        'reason': (f'{covered:.1f} of {len(tps)} talking points covered '
                   f'(PASS=1, PARTIAL=0.5), against a target of {target:.0f} '
                   f'-> scores {unit_score:.2f}. '
                   f'The brief offers these as talking points, not as a '
                   f'checklist, so coverage is scored once rather than each '
                   f'bullet being a separate pass/fail. The target is a '
                   f'PLACEHOLDER until Phase 8.'),
    }
    # Carry the summed weight explicitly so the dimension maths stays honest,
    # and let _score_weight find it.
    unit['_weight_override'] = total_w

    rest = [v for v in units if not _is_talking_point(v, req_index)]
    summary = {'offered': len(tps), 'covered': round(covered, 2),
               'decided': len(decided), 'target': int(target),
               'ratio': ratio, 'status': status,
               'unit_score': unit_score, 'target_credit': _full,
               'weight': round(total_w, 4),
               'collapsed': True,
               'obligation': _ob.get('obligation', 'optional'),
               'obligation_determined': bool(_ob.get('determined')),
               'obligation_from': _ob.get('from', 'no brief signal'),
               'target_is_placeholder': True}
    return rest + [unit], summary


def _band_with_critical_floor(score_0_100: float, units: list) -> tuple:
    """
    A brief's critical requirement is not something a good average may paper
    over. Returns (band, floor_applied, offending_ids).
    """
    raw = band_for(score_0_100)
    critical_fails = sorted(v.get('requirement_id', '') for v in units
                            if v.get('status') == 'FAIL'
                            and (v.get('priority') or '') == 'critical')
    if not critical_fails:
        return raw, False, []
    # Never better than NEEDS_MAJOR_REVISION.
    if BAND_ORDER.index(raw) < BAND_ORDER.index('NEEDS_MAJOR_REVISION'):
        return 'NEEDS_MAJOR_REVISION', True, critical_fails
    return raw, False, critical_fails


def _weighted(units: list) -> dict:
    """
    The band, from one pass over the units.

    pessimistic  Sigma(w*s) / Sigma(w)                UNCERTAIN scores 0.0
    optimistic   Sigma(w*s) / Sigma(w decided)        UNCERTAIN leaves the sum
    coverage     Sigma(w decided) / Sigma(w)

    An empty unit list returns coverage 0.0 and no score, rather than dividing
    by zero or -- worse -- returning 0.0, which would read as "scored, and
    scored badly" for a video nobody evaluated.
    """
    tot_w = sum(_score_weight(v) for v in units)
    dec = [v for v in units if v.get('status') in STATUS_SCORE]
    dec_w = sum(_score_weight(v) for v in dec)
    earned = sum(_score_weight(v) * _unit_value(v) for v in dec)
    if tot_w <= 0:
        return {'pessimistic': None, 'optimistic': None, 'coverage': 0.0,
                'units': 0, 'decided_units': 0, 'total_weight': 0.0}
    return {
        'pessimistic': round(100.0 * earned / tot_w, P7.score.decimals),
        'optimistic': (round(100.0 * earned / dec_w, P7.score.decimals)
                       if dec_w > 0 else None),
        'coverage': round(dec_w / tot_w, 4),
        'units': len(units),
        'decided_units': len(dec),
        'total_weight': round(tot_w, 4),
    }


def _dimension_breakdown(units: list, req_index: dict) -> dict:
    """
    Per-dimension subscores, normalised over the dimensions the BRIEF covers.

    A brief with no `audience` requirement must not be scored out of 100 with
    10% unreachable -- that silently caps every video at 90 and the creator
    never learns why. Absent dimensions are RECORDED, not scored: "this brief
    said nothing about audience" is a fact about the brief and belongs on the
    page.
    """
    by_dim, inferred = {}, {}
    for v in units:
        # A SYNTHETIC unit declares its own dimension, and must be believed.
        # The collapsed talking-points unit has no entry in req_index -- its id
        # names no requirement in the brief -- so resolve_dimension() would see
        # an empty requirement, find nothing to read, and file eight of the
        # brief's feature bullets under the fallback dimension.
        _declared = v.get('dimension')
        if _declared in DIMENSION_WEIGHT:
            dim, how = _declared, 'declared'
        else:
            req = req_index.get(v.get('requirement_id')) or {}
            dim, how = resolve_dimension(req, v)
        by_dim.setdefault(dim, []).append(v)
        if how not in ('typed', 'declared'):
            inferred.setdefault(dim, []).append(v.get('requirement_id', ''))

    covered = [k for k in DIMENSION_KEYS if by_dim.get(k)]
    absent = [k for k in DIMENSION_KEYS if not by_dim.get(k)]
    norm = sum(DIMENSION_WEIGHT[k] for k in covered) or 1.0

    out = {}
    for k in DIMENSION_KEYS:
        members = by_dim.get(k) or []
        w = _weighted(members) if members else None
        out[k] = {
            'label': DIMENSION_LABEL[k],
            'covered': bool(members),
            'weight_raw': DIMENSION_WEIGHT[k],
            'weight_normalised': (round(DIMENSION_WEIGHT[k] / norm, 4)
                                  if members else 0.0),
            'units': len(members),
            # Measured in Phase 6: 26 requirements collapse to 3 scored units,
            # so a dimension resting on one decision is the NORMAL case. The
            # report must not draw it as a confident bar.
            'thin': bool(members) and len(members) < P7.score.thin_dimension_units,
            # Which units landed here by inference rather than by a declared
            # type. A subscore drawn from a reading of the brief's grouping is
            # still traceable, but it is not the same claim as a typed one.
            'inferred_units': sorted(inferred.get(k) or []),
            'score': (w or {}).get('optimistic') if members else None,
            'score_pessimistic': (w or {}).get('pessimistic') if members else None,
            'coverage': (w or {}).get('coverage', 0.0) if members else 0.0,
            # A collapsed unit contributes the ids of the requirements it
            # STANDS FOR, not just its own synthetic id. Everything downstream
            # places a verdict by looking its id up in this list -- the
            # alignment figures drop any verdict they cannot place -- so
            # listing only 'talking_points__collapsed' would erase all eight
            # feature bullets from the figures while still scoring them.
            'requirement_ids': sorted(
                {rid for v in members
                 for rid in ([v.get('requirement_id', '')]
                             + list(v.get('member_requirement_ids') or []))}),
        }
    return {'dimensions': out, 'covered': covered, 'absent': absent,
            'normalisation_divisor': round(norm, 4)}


def _contradictions(result: dict, units: list, safety: list,
                    headline: float, req_index: dict) -> list:
    """
    The review gate is QUALITATIVE (§4.4).

    An arithmetic gap between the requirement score and standing fires on
    noise: measured, an on-brief run produced a +0.28 gap and would have
    flagged a perfectly good video. These three are real disagreements a human
    can check in under a minute, and each names both sides.
    """
    out = []
    st = result.get('standing') or {}
    level = st.get('standing')
    approved_line = dict(BAND_THRESHOLDS_PLACEHOLDER)['APPROVED']

    # 1. The whole-video read and the decomposed read point opposite ways.
    if level in ('off_brief', 'tangential') and headline is not None \
            and headline >= approved_line:
        out.append({
            'code': 'STANDING_CONTRADICTS_SCORE',
            'detail': (f'Requirements scored {headline:.0f}, at or above the '
                       f'{approved_line:.0f} approval line, but the whole video '
                       f'read as {level}.'),
            'standing_says': st.get('verdict', '')[:300],
            'evidence_ids': sorted(st.get('evidence_ids') or [])[:8],
        })

    # 1b. THE SAME DISAGREEMENT, THE OTHER WAY ROUND.
    #
    # Check 1 catches "off brief but scored high" -- the false-positive PASS.
    # Nothing caught the mirror image, and it is just as loud: the whole-video
    # read says the brief's intent was fully served while the requirements
    # score it in the reject band.
    #
    # Measured on the Biostime batch: two videos came back
    # `standing=exemplary` with scores of 14 and 43. `exemplary` means "does
    # what the brief asks and does it well -- the intent is fully served and
    # the execution adds something the brief did not think to ask for". A
    # 70-point gap against that is not a grade, it is two readings that cannot
    # both be right, and exactly what the standing disclaimer promises to
    # surface: "Where the two disagree, the disagreement is the finding."
    #
    # It is deliberately NOT an arithmetic gap threshold -- the docstring above
    # records that a +0.28 gap fires on noise. This fires only when the two
    # reads land on opposite SIDES of a decision line, which is a disagreement
    # about the answer rather than about a number.
    _reject_line = dict(BAND_THRESHOLDS_PLACEHOLDER)['NEEDS_MAJOR_REVISION']
    if level in ('on_brief', 'exemplary') and headline is not None \
            and headline < _reject_line:
        out.append({
            'code': 'LOW_SCORE_CONTRADICTS_STANDING',
            'detail': (f'Requirements scored {headline:.0f}, below the '
                       f'{_reject_line:.0f} line, but the whole video read as '
                       f'{level}. Either the compiled requirements are asking '
                       f'for something the brief does not, or the whole-video '
                       f'read is too generous. One of the two is wrong.'),
            'standing_says': st.get('verdict', '')[:300],
            'evidence_ids': sorted(st.get('evidence_ids') or [])[:8],
        })

    # 2. Standing says an ask went unevidenced; a requirement says it PASSed.
    passed = [v for v in units if v.get('status') == 'PASS']
    for miss in (st.get('missing') or []):
        m = str(miss)
        for v in passed:
            label = str(v.get('requirement_label') or '')
            if not label or len(m) < 8:
                continue
            # token_set_ratio, NOT partial_ratio: partial_ratio slides the
            # shorter string over the longer one, so it answers a different
            # question depending on which argument is longer.
            if fuzz.token_set_ratio(m.lower(), label.lower()) >= 82:
                out.append({
                    'code': 'PASS_BUT_STANDING_CALLS_IT_MISSING',
                    'detail': (f'Standing lists "{m[:110]}" as not evidenced, '
                               f'while requirement {v.get("requirement_id")} '
                               f'("{label[:70]}") is a PASS.'),
                    'requirement_id': v.get('requirement_id', ''),
                    'evidence_ids': sorted(v.get('evidence_ids') or [])[:8],
                })
                break

    # 3. A safety check actually FAILED. That is a violation, and it belongs in
    #    the headline whatever the average says.
    for v in safety + [x for x in units if (req_index.get(x.get('requirement_id'))
                                            or {}).get('polarity') == 'forbidden']:
        if v.get('status') != 'FAIL':
            continue
        if any(c.get('requirement_id') == v.get('requirement_id')
               and c['code'] == 'SAFETY_CHECK_FAILED' for c in out):
            continue
        out.append({
            'code': 'SAFETY_CHECK_FAILED',
            'detail': (f'A forbidden-content check FAILED: '
                       f'{str(v.get("reason"))[:200]}'),
            'requirement_id': v.get('requirement_id', ''),
            'evidence_ids': sorted(v.get('evidence_ids') or [])[:8],
        })
    return out


def score_audit(result: dict, compiled: dict, cfg: Phase7Config = None,
                force: bool = False, verbose: bool = True) -> dict:
    """
    One audit -> one score artifact. Never raises.

    Keyed on the VERDICT cache key, not on the video: §0.6 -- the arithmetic is
    deterministic but its input is not, because L3 sampling moved the alignment
    mean by 0.34 on identical inputs. A score is reproducible against a
    specific verdicts__*.json, and the artifact names which one.
    """
    cfg = cfg or P7
    t0 = time.time()
    vh = result.get('video_hash', '')
    vdir = DIRS['artifacts'] / vh
    verdict_key = result.get('cache_key', '')

    key = stage_key('score', SCORE_STAGE_VERSION,
                    [vh, verdict_key, compiled.get('cache_key', '')],
                    {'p7_score': asdict(cfg.score)})
    path = vdir / f'score__{key}.json'
    if path.exists() and not force:
        if verbose:
            print(f'  SCORE CACHE HIT ({key})')
        return read_json(path)

    verdicts = result.get('verdicts') or []
    req_index = {r.get('id'): r for r in (compiled.get('requirements') or [])}

    # Rule 2: NOT_APPLICABLE leaves the denominator entirely.
    units = [v for v in verdicts if v.get('status') != 'NOT_APPLICABLE']
    not_applicable = [v for v in verdicts if v.get('status') == 'NOT_APPLICABLE']

    # Rule 3: compliance-by-absence is counted, never averaged.
    safety = [v for v in units if _is_safety_pass(v)]
    achievement = [v for v in units if not _is_safety_pass(v)]

    # ---- a requirement the brief never made may not be scored -------------
    # Phase 4 flags SPAN_NOT_IN_BRIEF when the model could not quote the brief
    # sentence a requirement came from -- it invented the ask. Until now that
    # was a flag only: the invented requirement was still compiled and still
    # scored, so the creator could be marked down for something nobody asked
    # of her. Measured live: 1 of 21 on the Aurelia compile.
    #
    # The whole system judges what she did against what the BRIEF asked. A
    # requirement with no brief behind it has nothing to judge against, so it
    # leaves the denominator -- the same treatment NOT_APPLICABLE gets, and for
    # the same reason.
    #
    # It is NOT deleted. It stays in the artifact, is listed on the page, and
    # is counted here, because the flag can be a false positive: the model may
    # have paraphrased a real brief sentence it failed to quote. Fixing the
    # brief text is what brings it back into the score.
    def _untraceable(v: dict) -> bool:
        _rq = req_index.get(v.get('requirement_id')) or {}
        return any(str(f).startswith('SPAN_NOT_IN_BRIEF')
                   for f in (_rq.get('flags') or []))

    not_in_brief = [v for v in achievement if _untraceable(v)]
    achievement = [v for v in achievement if not _untraceable(v)]

    # The brief's feature bullets are a MENU, not a checklist: one unit,
    # scored by coverage, carrying the weight the bullets carried. See
    # _collapse_talking_points -- every bullet keeps its own verdict and row.
    achievement, talking_point_unit = _collapse_talking_points(
        achievement, req_index, cfg, compiled)

    wsum = _weighted(achievement)
    # The headline is the optimistic figure when coverage is high enough to
    # justify one number; otherwise the report leads with the band and this is
    # only the top of it.
    headline = wsum['optimistic']
    lead_with_band = (wsum['coverage'] < cfg.score.headline_coverage_min
                      or wsum['pessimistic'] != wsum['optimistic'])

    # ---- QUESTION 1, BEFORE QUESTION 2 ----------------------------------
    # Is this video addressing this brief at all? The arithmetic below
    # answers "how closely did it follow the brief", which only means
    # something once relevance is settled. The numbers are still computed and
    # still written to the artifact -- nothing is destroyed -- but a gated
    # audit does not get to present one as its headline.
    relevance = relevance_of(result.get('standing') or {})

    # THE BAND IS A DECISION WORD, so it must describe what is ESTABLISHED.
    #
    # `optimistic` assumes every UNCERTAIN would have passed -- the most
    # favourable reading available. Stamping APPROVED on that is exactly
    # plan.md's "false-positive PASS: the most damaging error class, it tells
    # a brand a video is compliant when it is not."
    #
    # Measured on a live run: 75-100 at 75% coverage, three scoring units, one
    # of them undecided. The badge read APPROVED. From the pessimistic end it
    # reads NEEDS_MINOR_REVISION, which is what can actually be defended --
    # "at least a minor revision; approval is possible if the undecided
    # quarter goes its way."
    #
    # Above the coverage line the two ends have converged, so this changes
    # nothing there. Below it, the label follows the floor.
    _band_basis = ('optimistic'
                   if wsum['coverage'] >= cfg.score.headline_coverage_min
                   else 'pessimistic')
    _band_from = (headline if _band_basis == 'optimistic'
                  else wsum['pessimistic'])
    band, floored, critical_fails = _band_with_critical_floor(
        _band_from if _band_from is not None else 0.0, achievement)
    if not relevance['scorable']:
        band = BAND_OFF_BRIEF
        floored = False

    # ---- the literal-only score, computed beside the credited one ---------
    # The brief is a REFERENCE, not a script: a requirement met in the
    # creator's own words is met, and Phase 6 credits it. That is the number
    # this report leads with, and it is the right one for the product.
    #
    # But a credited verdict was a literal FAIL, and the credit rests on a
    # model's alignment judgement. So the strict reading is computed too, from
    # the literal status Phase 6 kept on every credited verdict, and reported
    # beside it. A reader can see exactly how much of the score rests on
    # paraphrase, and Phase 8 can measure whether that credit was deserved --
    # which is impossible if only one number survives.
    def _literal_status(v: dict) -> str:
        for f in (v.get('flags') or []):
            s = str(f)
            if s.startswith('LITERAL_STATUS_WAS:'):
                return s.split(':', 1)[1].split('/')[0]
        return v.get('status', '')

    _credited = [v for v in achievement
                 if any(str(f) == 'SATISFIED_IN_SUBSTANCE'
                        for f in (v.get('flags') or []))]
    _strict = [dict(v, status=_literal_status(v)) for v in achievement]
    _lit = _weighted(_strict)

    dims = _dimension_breakdown(achievement, req_index)
    contradictions = _contradictions(result, achievement, safety,
                                     headline, req_index)

    # Weights the verdict disagrees with. Not fatal -- the documented rule wins
    # -- but a silent disagreement between two stored numbers is how a report
    # stops being checkable.
    weight_mismatch = sorted(
        v.get('requirement_id', '') for v in units
        if v.get('weight') is not None
        and abs(float(v.get('weight') or 0) - _score_weight(v)) > 1e-6)

    st = result.get('standing') or {}
    hook = result.get('hook') or {}
    claims = result.get('claims') or {}

    out = {
        'schema_version': SCORE_STAGE_VERSION,
        'video_hash': vh,
        'video_id': result.get('video_id', ''),
        'brief_hash': result.get('brief_hash', ''),
        'cache_key': key,
        'duration_seconds': result.get('duration_seconds'),
        # §0.6: the artifact this score is reproducible against.
        'scored_from': {'verdicts_cache_key': verdict_key,
                        'brief_cache_key': compiled.get('cache_key', ''),
                        'evidence_cache_key': (result.get('sources') or {}).get('evidence', '')},
        # Question 1. Read this before the score, because it decides whether
        # the score means anything.
        'relevance': relevance,
        'score': {
            'headline': headline,
            'band_low': wsum['pessimistic'],
            'band_high': wsum['optimistic'],
            # The arithmetic is kept in full either way -- nothing is
            # destroyed -- but a gated audit may not PRESENT a number as its
            # answer. "32/100" and "this is a different product" are not the
            # same finding, and only one of them is true here.
            'gated': not relevance['scorable'],
            'gate_reason': relevance['why'] if not relevance['scorable'] else '',
            'lead_with_band': lead_with_band,
            'coverage': wsum['coverage'],
            'status_band': band,
            # Which end of the band the label was read from, so the reader can
            # tell a defended grade from a hopeful one.
            'band_basis': _band_basis,
            'critical_floor_applied': floored,
            'critical_fail_ids': critical_fails,
            'scoring_units': wsum['units'],
            'decided_units': wsum['decided_units'],
            'total_weight': wsum['total_weight'],
            'thresholds_are_placeholders': True,
            # How the feature bullets were collapsed, so the one unit that
            # stands for eight can be recomputed by hand from the verdicts.
            'talking_points': talking_point_unit,
            # The strict reading, for the reader and for Phase 8. `headline`
            # credits work done in the creator's own words; `literal_headline`
            # counts only brief-wording matches. The gap between them IS the
            # paraphrase, made measurable instead of assumed.
            'literal_headline': _lit['optimistic'],
            'literal_band_low': _lit['pessimistic'],
            'credited_in_substance': len(_credited),
            'credited_requirement_ids': [v.get('requirement_id', '')
                                         for v in _credited],
            # Requirements with no brief sentence behind them. Excluded from
            # the score, kept in the artifact, disclosed on the page.
            'not_in_brief_excluded': len(not_in_brief),
            'not_in_brief_ids': [v.get('requirement_id', '')
                                 for v in not_in_brief],
        },
        # Reported, never averaged.
        'safety': {
            'checks': len(safety),
            'passed_by_absence': sum(1 for v in safety if v.get('status') == 'PASS'),
            'failed': sorted(v.get('requirement_id', '') for v in safety
                             if v.get('status') == 'FAIL'),
            'note': ('Forbidden-content checks that passed because nothing was '
                     'found. Compliance established; nothing achieved. Counted '
                     'here, never averaged into the score.'),
        },
        'dimensions': dims['dimensions'],
        'dimensions_covered': dims['covered'],
        'dimensions_absent': dims['absent'],
        'dimension_normalisation_divisor': dims['normalisation_divisor'],
        'standing': {'level': st.get('standing'), 'weight': st.get('weight'),
                     'verdict': st.get('verdict', ''),
                     'covered': st.get('covered') or [],
                     'missing': st.get('missing') or [],
                     'off_brief_additions': st.get('off_brief_additions') or [],
                     'confidence': st.get('confidence'),
                     'disclaimer': st.get('disclaimer', '')},
        'contradictions': contradictions,
        'counts': {
            'requirements': len(verdicts),
            'not_applicable': len(not_applicable),
            'scoring_units': len(units),
            'achievement_units': len(achievement),
            'safety_units': len(safety),
            'by_status': {s: sum(1 for v in units if v.get('status') == s)
                          for s in VERDICT_STATUSES
                          if any(v.get('status') == s for v in units)},
        },
        'hook': {'present': hook.get('hook_present'), 'type': hook.get('hook_type'),
                 'strength': hook.get('strength'),
                 'within_required_window': hook.get('within_required_window')},
        'claims_enabled': bool(claims.get('enabled')),
        'flags': ([{'code': 'WEIGHT_DISAGREES_WITH_VERDICT',
                    'detail': str(weight_mismatch[:5])}] if weight_mismatch else []),
        'provenance': provenance('score', SCORE_STAGE_VERSION, key,
                                 time.time() - t0,
                                 model_free=True,
                                 dimension_weights=dict(DIMENSION_WEIGHT),
                                 status_score=dict(STATUS_SCORE),
                                 priority_weight=dict(PRIORITY_WEIGHT)),
    }
    write_json(path, out)
    if verbose:
        if not relevance['scorable']:
            _arith = ('no scorable unit' if wsum['optimistic'] is None
                      else f'{wsum["pessimistic"]:.0f}-{wsum["optimistic"]:.0f}')
            print(f'  score -> {path.name}   OFF BRIEF '
                  f'({relevance["level"]}) -- no score presented')
            print(f'           the arithmetic is kept in the artifact '
                  f'({_arith}) but it measures adherence to a brief this '
                  f'video is not addressing')
        else:
            _b = (f'{out["score"]["band_low"]:.0f}-{out["score"]["band_high"]:.0f}'
                  if lead_with_band and headline is not None
                  else (f'{headline:.0f}' if headline is not None else 'no score'))
            print(f'  score -> {path.name}   {_b}  '
                  f'({wsum["units"]} unit(s), {wsum["coverage"]:.0%} coverage, '
                  f'{band})')
    return out


def score_for(video_hash: str, brief_hash: str = '') -> Optional[dict]:
    """Newest score artifact for a video, optionally for one brief."""
    vdir = DIRS['artifacts'] / video_hash
    if not vdir.exists():
        return None
    files = list(vdir.glob('score__*.json'))
    if brief_hash:
        files = [p for p in files
                 if (read_json(p) or {}).get('brief_hash') == brief_hash]
    if not files:
        return None
    return read_json(max(files, key=lambda p: p.stat().st_mtime))


print('§76 scoring loaded.  Artifacts -> work/artifacts/{video_hash}/score__*.json')
print('  score_audit(result, compiled)  ->  band, dimensions, contradictions')
print('  No model is called here, and no model output reaches a numeric field.')
