# ============================================================================
# §82  Self-check addendum  --  Phase 7, on top of §74's Phases 1 to 6
#
# §74 answers "did this run work" for the pipeline that produces verdicts.
# This answers the same question for the pipeline that turns verdicts into a
# number and a page, and then states the combined position.
#
# It re-derives rather than re-reads wherever it can: a self-check that trusts
# the thing it is checking is decoration.
# ============================================================================

print('=' * 78)
print('§82  SELF-CHECK  --  PHASE 7')
print('=' * 78)

_p7_issues = []


def _p7ck(label, value, ok=True, note=''):
    mark = 'ok' if ok else '<-- PROBLEM'
    print(f'  {label:<36} {str(value)[:44]}  {mark}')
    if note:
        print(f'      {note}')
    if not ok:
        _p7_issues.append(label)


if 'score' not in globals():
    print('  Phase 7 has not run. Execute §80 first.')
else:
    _s = score['score']
    _brief = globals().get('_p6_brief') or globals().get('compiled') or {}
    _recs = load_records(evidence)

    print()
    print('--- the number ---')
    _p7ck('scoring units', f'{_s["scoring_units"]} from '
          f'{score["counts"]["requirements"]} requirements',
          _s['scoring_units'] > 0,
          'A one_of group is one decision; the losers are not failures.')
    _p7ck('band', (f'{_s["band_low"]:.0f}-{_s["band_high"]:.0f}'
                   if _s['headline'] is not None else 'no score'),
          _s['headline'] is not None)
    _p7ck('coverage', f'{_s["coverage"]:.0%}', True,
          ('Below 90%, so the report leads with a band rather than one number.'
           if _s['coverage'] < P7.score.headline_coverage_min else
           'High enough to show a single figure.'))
    _p7ck('status band', _s['status_band'], True,
          'Thresholds are PLACEHOLDERS until Phase 8 calibration.')
    # The unit count is not a footnote: it is how much the number can carry.
    _thin = _s['scoring_units'] < 4
    _p7ck('is the score thin?', f'{_s["scoring_units"]} unit(s)', not _thin,
          ('One decision moves this score by a third. Structural, not a bug -- '
           'but the report must never show it as precise.') if _thin else '')

    print()
    print('--- what must never happen ---')
    _abs_in = [v for v in (result.get('verdicts') or [])
               if any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))]
    _p7ck('compliance counted as achievement', f'{len(_abs_in)} held out',
          score['safety']['checks'] == len(_abs_in))
    _p7ck('model wrote a number', 'no',
          score['provenance'].get('model_free') is True)
    _na = score['counts']['not_applicable']
    _p7ck('NOT_APPLICABLE in the denominator', 'no',
          _s['scoring_units'] + _na + len(_abs_in) == score['counts']['requirements'],
          f'{_na} excluded, and disclosed on the page.')
    _cov = score['dimensions_covered']
    _norm = sum(score['dimensions'][k]['weight_normalised'] for k in _cov)
    _p7ck('dimension weights renormalised', f'{len(_cov)} covered -> {_norm:.3f}',
          (abs(_norm - 1.0) < 0.001) if _cov else True)

    print()
    print('--- recommendations ---')
    _r = recommendations
    _p7ck('shortfalls considered', _r.get('considered_units', 0), True)
    _p7ck('edits proposed', len(_r.get('recommendations') or []), True,
          _r.get('note', '')[:90])
    _p7ck('citation/wording violations', len(_r.get('violations') or []),
          True,
          'Rejected, not cleaned up silently.' if _r.get('violations') else '')
    _anchored = [x for x in (_r.get('recommendations') or [])
                 if x.get('at_seconds') is not None]
    _p7ck('anchored to a real record', f'{len(_anchored)}/'
          f'{len(_r.get("recommendations") or [])}', True)

    print()
    print('--- the report ---')
    _html = (report or {}).get('html', '')
    _p7ck('html size', f'{len(_html) / 1024:.0f} KB', len(_html) > 2000)
    # Tags, not text: "cdn.plot" is a topojsonURL default string inside the
    # embedded plotly bundle, for map types this report never draws.
    _ext = re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)="'
                      r'(?:https?:)?//[^"]{0,60}', _html)
    _p7ck('self-contained', f'{len(_ext)} external fetch(es)', not _ext,
          str(_ext[:2]) if _ext else 'everything is inline or a data: URI')
    _p7ck('timestamps seek the player', 'yes',
          'data-t=' in _html and 'currentTime' in _html)
    _p7ck('figures drawn', len(figures.get('figures') or []),
          True, '; '.join(figures.get('notes') or [])[:90])
    _p7ck('proxy video embedded',
          ((report or {}).get('payload', {}).get('proxy_video', {}) or {}).get('ok'),
          True,
          ((report or {}).get('payload', {}).get('proxy_video', {}) or {}).get('note', ''))

    print()
    print('--- traceability, the design rule ---')
    _units = [v for v in (result.get('verdicts') or [])
              if v.get('status') != 'NOT_APPLICABLE']
    _untraceable = [v.get('requirement_id') for v in _units
                    if not (v.get('evidence_ids') or v.get('examined_ids'))
                    and v.get('status') in ('FAIL', 'PARTIAL')]
    _p7ck('every scored FAIL/PARTIAL is traceable',
          f'{len(_units) - len(_untraceable)}/{len(_units)}',
          not _untraceable, str(_untraceable[:3]) if _untraceable else '')
    _ids = {r.id for r in _recs}
    _cited = {i for v in _units for i in (v.get('evidence_ids') or [])}
    _p7ck('every cited id exists in the evidence', f'{len(_cited)} cited',
          _cited <= _ids, str(sorted(_cited - _ids)[:3]) if _cited - _ids else '')

    print()
    print('--- does Phase 7 describe the same run as Phase 6? ---')
    _p7ck('verdicts key matches',
          score['scored_from']['verdicts_cache_key'][:16],
          score['scored_from']['verdicts_cache_key'] == result.get('cache_key'))
    _p7ck('brief key matches', score['scored_from']['brief_cache_key'][:16],
          score['scored_from']['brief_cache_key'] == _brief.get('cache_key'))
    _p7ck('video matches', score['video_hash'][:16],
          score['video_hash'] == result.get('video_hash'))

print()
print('=' * 78)
print('WHERE PHASES 1-7 STAND')
print('=' * 78)
if '_ISSUES' in globals():
    _p6_block = [i for i in _ISSUES if i[0] == _E]
    print(f'  Phase 1-6 self-check (§74) : {len(_p6_block)} blocking, '
          f'{len(_ISSUES) - len(_p6_block)} warning')
    for _i in _p6_block:
        print(f'      - {_i[1]}: {_i[2][:60]}')
else:
    print('  Phase 1-6 self-check (§74) : not run in this session')
print(f'  Phase 7 self-check (§82)   : {len(_p7_issues)} issue(s)')
if _p7_issues:
    for _i in _p7_issues:
        print(f'      - {_i}')
print(f'  Phase 7 tests (§77)        : '
      f'{"green" if globals().get("_p7_tests_ok") else "NOT GREEN"}')
print(f'  Phase 7 exit criteria (§81): '
      f'{"all mechanical criteria hold" if globals().get("_p7_exit_ok") else "see §81"}')
print()
print('  What is NOT established, and cannot be by any cell in this notebook:')
print('    * that the band thresholds are the right ones  -> Phase 8 labels')
print('    * that the verdicts underneath the score are correct -> Phase 8 labels')
print('  Every criterion green means the machinery is sound and every claim is')
print('  traceable. It does not mean the verdicts are right. That gap closes')
print('  with labels, not with more code.')
print('=' * 78)
