# ============================================================================
# §81  Phase 7 exit criteria
#
# Checked against the artifacts this run produced, not asserted. A criterion
# no code can check is reported as MANUAL rather than quietly assumed -- the
# same discipline as §74b.
# ============================================================================

def _phase7_exit(verbose: bool = True) -> bool:
    rows = []

    def ck(name, ok, detail=''):
        rows.append((name, bool(ok), detail))

    def man(name, detail):
        rows.append((name, None, detail))

    if 'score' not in globals():
        print('Run §80 first -- there is no score to check.')
        return False

    _s = score['score']
    _brief = globals().get('_p6_brief') or globals().get('compiled') or {}

    # ---- the headline criterion ------------------------------------------
    # Recompute the score here, independently, from the verdict list -- the
    # arithmetic a human would do on paper. If this disagrees with §76, the
    # score is not reproducible and nothing else matters.
    _units = [v for v in (result.get('verdicts') or [])
              if v.get('status') != 'NOT_APPLICABLE'
              and not any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))]
    _dec = [v for v in _units if v.get('status') in STATUS_SCORE]
    _w = lambda v: PRIORITY_WEIGHT.get(v.get('priority') or 'medium', 1.0)
    _earned = sum(_w(v) * STATUS_SCORE[v['status']] for v in _dec)
    _tot, _decw = sum(_w(v) for v in _units), sum(_w(v) for v in _dec)
    _hand_opt = round(100.0 * _earned / _decw, 0) if _decw else None
    _hand_pess = round(100.0 * _earned / _tot, 0) if _tot else None
    ck('score reproducible by hand from the verdict artifact',
       _hand_opt == _s['band_high'] and _hand_pess == _s['band_low'],
       f'by hand {_hand_pess}-{_hand_opt}, §76 says {_s["band_low"]}-{_s["band_high"]}')

    ck('no model output ever writes a numeric score',
       score['provenance'].get('model_free') is True
       and all(not isinstance(v, (int, float)) or isinstance(v, bool)
               for r in (recommendations.get('recommendations') or [])
               for k, v in r.items() if k != 'at_seconds'),
       'the only number a recommendation may carry is a timestamp it cited')

    _abs = [v for v in (result.get('verdicts') or [])
            if any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))]
    ck('PASS_FROM_ABSENCE never contributes to achievement',
       _s['scoring_units'] == len(_units),
       f'{len(_abs)} vacuous pass(es) held out of {score["counts"]["scoring_units"]} unit(s)')

    _cov = score['dimensions_covered']
    _norm = sum(score['dimensions'][k]['weight_normalised'] for k in _cov)
    ck('dimension subscores normalise over covered dimensions only',
       abs(_norm - 1.0) < 0.001 if _cov else True,
       f'{len(_cov)} covered, normalised weights sum to {_norm:.3f}')

    _crit = [v for v in _units if v.get('status') == 'FAIL'
             and v.get('priority') == 'critical']
    ck('a critical FAIL cannot be averaged into APPROVED',
       (not _crit) or _s['status_band'] != 'APPROVED',
       f'{len(_crit)} critical FAIL(s); band {_s["status_band"]}')

    # ---- the report -------------------------------------------------------
    _html = (report or {}).get('html', '')
    # "Self-contained" means it FETCHES nothing, and that is a question about
    # TAGS. An earlier version searched for the substring 'http://' in
    # everything before the first <script> -- but the embedded plotly bundle
    # is ~4.5 MB of JavaScript containing URLs in licences and schema
    # defaults, and plotly opens with `<script type="text/javascript">`, which
    # `split('<script>')` does not even cut on. So the check read almost the
    # whole library and failed the moment figures were drawn. Same mistake as
    # the 'cdn.plot' search below it, which was already fixed: a substring
    # hunt through a vendored bundle tests the bundle, not the page.
    _ext_all = re.findall(r'<(?:script|link|img|iframe|video|source|audio)[^>]*'
                          r'\s(?:src|href)="(?!data:)(?:https?:)?//[^"]{0,80}',
                          _html)
    ck('the report is one self-contained HTML file',
       _html.startswith('<!doctype html>') and not _ext_all,
       f'{len(_html) / 1024:.0f} KB, {len(_ext_all)} external reference(s)'
       + (f' {_ext_all[:2]}' if _ext_all else ''))
    ck('timestamp clicks seek the player',
       'data-t=' in _html and 'currentTime' in _html)
    # Read from the figure OBJECTS at build time, not by grepping the HTML.
    # The first figure embeds the whole plotly bundle, and that bundle
    # contains the word "customdata" as a schema key -- so the old string
    # search passed for any figure whatsoever and verified nothing.
    _untraceable = [f['id'] for f in (figures.get('figures') or [])
                    if not (f.get('provenance') or {}).get('traceable')]
    ck('every plotted marker carries the evidence ids behind it',
       not _untraceable,
       str(_untraceable[:3]) if _untraceable
       else '; '.join(f'{f["id"]}: {f["provenance"]["detail"]}'
                      for f in (figures.get('figures') or [])[:3])
       or 'no figures')
    ck('the report renders, and says so, with Plotly unavailable',
       figures.get('plotly_available') is True
       or any('Plotly is not available' in n for n in (figures.get('notes') or [])),
       'plotly present' if figures.get('plotly_available') else 'degraded, and disclosed')
    # Grep the TAGS, not the text. "cdn.plot" appears as a topojsonURL default
    # INSIDE the embedded plotly bundle -- a string in a config object for
    # geographic maps this report never draws. An earlier version of this
    # check searched for that substring and would have reported FAIL the
    # moment Plotly was actually installed: a criterion that only passed while
    # the feature was missing.
    _ext = re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)="'
                      r'(https?:)?//[^"]{0,80}', _html)
    ck('the report fetches nothing from the network',
       not _ext, str(_ext[:3]) if _ext
       else (f'{len(figures.get("figures") or [])} figure(s), plotly embedded'
             if figures.get('figures') else 'no figures drawn'))

    _a = build_report_html(TARGET, result, _brief, score,
                           load_records(evidence), recommendations, figures,
                           None, P7)
    _b = build_report_html(TARGET, result, _brief, score,
                           load_records(evidence), recommendations, figures,
                           None, P7)
    ck('the same verdict artifact scored twice gives identical output',
       _a == _b, f'{len(_a)} vs {len(_b)} chars')

    _contra = score.get('contradictions') or []
    _off = (result.get('standing') or {}).get('standing') in ('off_brief', 'tangential')
    ck('contradictions fire on a genuinely off-brief pair',
       (not _off) or bool(_contra),
       f'standing={(result.get("standing") or {}).get("standing")}, '
       f'{len(_contra)} contradiction(s)')

    # Answerable without any human judgement: a video against its own brief
    # versus the same video against a foreign one. What it needs is the
    # control half of that comparison, which costs a few L3 calls.
    _d = globals().get('_discrimination') or {}
    ck('§75b answered: some quantity separates own brief from foreign',
       bool(_d.get('winner')),
       (f'{_d.get("verdict", "not run")} '
        f'({_d.get("native", 0)} native, {_d.get("control", 0)} control pairing(s))'
        + ('  -- set RUN_CONTROL_AUDITS = True in §75b and re-run'
           if not _d.get('control') else '')))

    ck('the Phase 7 test suite is green', bool(globals().get('_p7_tests_ok')))

    man('a person who has not seen the video can act on the report',
        'send the HTML to someone and ask them what to change')
    man('reviewing a report is faster than watching the video',
        'time both, on the same video')

    if verbose:
        print('=' * 78)
        print('§81  PHASE 7 EXIT CRITERIA')
        print('=' * 78)
        for name, ok, detail in rows:
            mark = 'PASS' if ok else ('MANUAL' if ok is None else 'FAIL')
            print(f'  [{mark:<6}] {name}')
            if detail:
                print(f'            {detail}')
        _bad = [n for n, ok, _d in rows if ok is False]
        _man = [n for n, ok, _d in rows if ok is None]
        print()
        print(f'  {sum(1 for _n, ok, _d in rows if ok)} pass, {len(_bad)} fail, '
              f'{len(_man)} need a human')
        if _bad:
            print('  NOT MET:')
            for n in _bad:
                print(f'    - {n}')
        else:
            print('  Every mechanically checkable criterion holds.')
        print()
        print('  Still true, and not a defect: the band thresholds are')
        print('  PLACEHOLDERS. Nothing has established that 85 is the line.')
        print('  That is Phase 8, and it needs labels rather than more code.')
    return not [n for n, ok, _d in rows if ok is False]


_p7_exit_ok = _phase7_exit(verbose=True)
