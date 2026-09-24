# ============================================================================
# §80  Score the TARGET, and build the report
#
# Everything above is definitions. This is the cell that produces the two
# deliverables: the §84 JSON contract and the one-file HTML report.
#
# Order matters and is not arbitrary:
#   score  -> arithmetic, free, deterministic
#   recs   -> the ONLY model call, and it needs the score's shortfalls
#   figs   -> needs the score; degrades to notes if Plotly is missing
#   report -> needs all three, and never fails because one of them did
# ============================================================================

RESCORE = False          # True to recompute even when the artifact exists

if 'result' not in globals():
    print('No audit in memory. Run §72 first -- Phase 7 scores what Phase 6')
    print('decided, and there is nothing yet to score.')
elif not (globals().get('_p6_brief') or globals().get('compiled')):
    print('No compiled brief in memory. Run Phase 4, then §72.')
else:
    _brief = globals().get('_p6_brief') or globals().get('compiled')
    _records = load_records(evidence)

    print('=' * 78)
    print('PHASE 7 -- SCORING AND REPORTING')
    print('=' * 78)

    # ---- 1. the number ----------------------------------------------------
    score = score_audit(result, _brief, P7, force=RESCORE, verbose=True)

    # ---- 2. what to change (the only model call) --------------------------
    recommendations = evaluate_recommendations(
        result, _brief, score, _records, cfg=P7, verbose=True)

    # ---- 3. figures -------------------------------------------------------
    # Every score on disk for this video and brief, so the stability surface
    # has runs to compare and the batch view has videos.
    _siblings = []
    for _d in sorted(d for d in DIRS['artifacts'].glob('*') if d.is_dir()):
        for _p in sorted(_d.glob('score__*.json')):
            _s = read_json(_p)
            if isinstance(_s, dict) and _s.get('brief_hash') == score.get('brief_hash'):
                _siblings.append(_s)
    figures = build_figures(score, result, _records, _siblings, P7)

    # ---- 4. the page ------------------------------------------------------
    report = write_report(TARGET, result, _brief, score, _records,
                          recommendations, figures, P7, verbose=True)

    # ---- what it says -----------------------------------------------------
    _s = score['score']
    print()
    print('=' * 78)
    # ---- QUESTION 1: does the CRUX align? --------------------------------
    # This is the question the whole product turns on: does what she made mean
    # what the brief was asking for? It is the only read that sees the WHOLE
    # video against the WHOLE brief -- every other layer decomposes, and
    # decomposition cannot ask it.
    #
    # It printed nowhere before: §80 went straight to the score, and standing
    # surfaced only when a contradiction happened to mention it. A score is
    # "how closely did she follow the specifics", which is the SECOND question
    # and means nothing until this one is answered.
    _st = (result.get('standing') or {})
    _rel = score.get('relevance') or {}
    if _st.get('standing'):
        _lvl = _st['standing']
        print('DOES THE CRUX ALIGN?   -- the whole video against the whole brief')
        print('=' * 78)
        print(f'  {_lvl.upper().replace("_", " ")}'
              + (f'   (weight {BRIEF_STANDING_WEIGHTS.get(_lvl, 0):.2f})'
                 if 'BRIEF_STANDING_WEIGHTS' in globals() else ''))
        _anch = (BRIEF_STANDING_ANCHORS.get(_lvl, '')
                 if 'BRIEF_STANDING_ANCHORS' in globals() else '')
        if _anch:
            print(f'    {_anch}')
        if _st.get('verdict'):
            print(f'    "{str(_st["verdict"])[:200]}"')
        if _lvl == 'partial':
            print('  CAUTION  The crux only PARTLY aligns. Substantial parts of '
                  'the brief are')
            print('           untouched. Read the score as "how well she did the '
                  'part she engaged".')
        elif not _rel.get('scorable', True):
            print('  The per-requirement score is WITHHELD: it measures how '
                  'closely a video')
            print('  followed a brief it is addressing, and this one is not.')
        print('  Judged whole and by SUBSTANCE, not wording. A different hook, '
              'structure or')
        print('  order is fine -- the question is whether it means the same '
              'thing.')
        print()
    # WHAT SHE MADE -- the companion question. What is this video, and how did
    # she choose to carry the message? It describes, it does not grade.
    _ca = (result.get('creative_angle') or {})
    if _ca.get('angle'):
        print('WHAT SHE MADE   -- her angle, from a fixed list in code')
        print('=' * 78)
        print(f'  {_ca["angle"].upper().replace("_", " ")}')
        if _ca.get('summary'):
            print(f'    {str(_ca["summary"])[:190]}')
        _hk = (result.get('hook') or {})
        if _hk.get('present'):
            print(f'    opens on a {_hk.get("hook_type", "?")} hook, rated '
                  f'{_hk.get("strength", "?")}'
                  + (f' at {_hk.get("start"):.1f}s'
                     if isinstance(_hk.get('start'), (int, float)) else ''))
            print('    (hook STRENGTH is a separate reading from whether the '
                  'hook requirement was met)')
        _near = _ca.get('nearest_brief_concept') or 'none of them'
        print(f'    nearest concept in the brief: {_near}')
        if _ca.get('anticipated_by_brief') is False:
            print('    The brief did not list this angle -- a fact about the '
                  'brief\'s coverage,')
            print('    not a fault in the video.')
        print()
    print('=' * 78)
    print('THE SCORE' + ('   -- how closely she followed the specifics'
                         if _st.get('standing') else ''))
    print('=' * 78)
    if _s['headline'] is None:
        print('  no score -- nothing in this brief could be scored against this video')
    elif _s['lead_with_band']:
        print(f'  {_s["band_low"]:.0f}-{_s["band_high"]:.0f}   '
              f'{_s["coverage"]:.0%} coverage   {_s["status_band"]}')
        print(f'  A band, not a number: {(1 - _s["coverage"]) * 100:.0f}% of the '
              f'weight is undecided.')
    else:
        print(f'  {_s["band_high"]:.0f}   {_s["coverage"]:.0%} coverage   '
              f'{_s["status_band"]}')
    print(f'  from {_s["scoring_units"]} scoring unit(s) '
          f'({_s["decided_units"]} decided) out of '
          f'{score["counts"]["requirements"]} requirement(s)')
    # The brief is a reference, not a script. The headline credits what she did
    # in her own words; the strict reading is printed beside it so the size of
    # that credit is visible rather than assumed.
    if _s.get('credited_in_substance'):
        _lit = _s.get('literal_headline')
        print(f'  {_s["credited_in_substance"]} of those were met in HER OWN '
              f'WORDS, not the brief\'s wording.')
        if _lit is not None:
            print(f'    literal wording only: {_lit:.0f}   '
                  f'with her own versions credited: {_s["band_high"]:.0f}')
            print('    The gap is paraphrase the brief allows. Each credited '
                  'verdict kept its')
            print('    literal finding and cites the record where she says it '
                  'her way.')
    # The brief's SUBSTANCE, as a ratio and by name. Same helper the report
    # uses, so the console and the page cannot disagree about the number.
    try:
        _tp = talking_point_coverage(result, _p6_brief)
    except Exception as _exc:
        _tp = None
        print(f'  (talking-point coverage unavailable: {type(_exc).__name__})')
    if _tp and _tp['total']:
        print(f'  TALKING POINTS: {len(_tp["covered"])} of {_tp["total"]} '
              f'covered -- what the brief asked her to communicate.')
        for _r in _tp['missed'][:6]:
            print(f'    not evidenced: {_r["label"][:62]}')
        if _tp['approved_claims'] and _tp['approved_claims'] > _tp['total']:
            print(f'    ({_tp["approved_claims"]} approved talking point(s) in '
                  f'the brief; {_tp["total"]} became checkable requirements --')
            print('     a floor, not a census: the link back to a brief line '
                  'is best-effort.)')
    if _s.get('not_in_brief_excluded'):
        print(f'  {_s["not_in_brief_excluded"]} requirement(s) NOT SCORED: no '
              f'sentence in the brief asks for them.')
        print(f'    {_s.get("not_in_brief_ids", [])} -- the compiler could not '
              f'quote a source.')
        print('    She is judged against what the brief asked, so an invented '
              'ask scores nothing.')
        print('    Fix the brief text to bring it back in.')
    if _s['critical_floor_applied']:
        print(f'  CRITICAL FAIL floor applied: {_s["critical_fail_ids"]}')
    _sf = score['safety']
    if _sf['checks']:
        print(f'  plus {_sf["checks"]} forbidden-content check(s): '
              f'{_sf["passed_by_absence"]} found nothing '
              f'(compliance, not achievement -- never averaged in)')

    print()
    print('BY DIMENSION  -- normalised over what this brief covers')
    for _k in DIMENSION_KEYS:
        _d = score['dimensions'][_k]
        if not _d['covered']:
            continue
        _bar = '#' * int(round((_d['score'] or 0) / 5)) if _d['score'] is not None else ''
        print(f'    {_d["label"]:<22} {_d["weight_normalised"]:>5.0%}  '
              f'{(f"{_d['score']:.0f}" if _d["score"] is not None else "--"):>4}  '
              f'{_bar:<20} {_d["units"]} unit(s)'
              + ('  THIN' if _d['thin'] else ''))
    if score['dimensions_absent']:
        print('    not covered by this brief: '
              + ', '.join(DIMENSION_LABEL[k] for k in score['dimensions_absent']))

    if score['contradictions']:
        print()
        print('CONTRADICTIONS  -- read these first')
        for _c in score['contradictions']:
            print(f'    [{_c["code"]}] {_c["detail"][:150]}')
            if _c.get('evidence_ids'):
                print(f'        cites: {", ".join(_c["evidence_ids"][:4])}')
    else:
        print()
        print('CONTRADICTIONS  : none -- the two reads of this video agree')

    if recommendations.get('recommendations'):
        print()
        print('WHAT TO CHANGE')
        for _r in recommendations['recommendations']:
            _at = (f'{int(_r["at_seconds"] // 60)}:{int(_r["at_seconds"] % 60):02d}'
                   if _r.get('at_seconds') is not None else '--:--')
            print(f'    {_at}  [{_r["effort"]:<8}] {_r["edit"][:110]}')
        for _k in recommendations.get('keep') or []:
            print(f'    keep      {_k[:110]}')
    if recommendations.get('violations'):
        print(f'    ({len(recommendations["violations"])} suggestion(s) rejected '
              f'for citing or wording violations)')

    print()
    print('ARTIFACTS')
    print(f'    report : {report["html_path"]}')
    print(f'    json   : {report["json_path"]}')
    print(f'    scored from verdicts {score["scored_from"]["verdicts_cache_key"]}')
    if figures.get('notes'):
        print('    figures not drawn:')
        for _n in figures['notes']:
            print(f'        {_n[:110]}')
    print()
    print('  Open the HTML file to read it. It needs no server and no network.')
