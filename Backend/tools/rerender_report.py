"""Re-render a report from artifacts already on disk. No model calls.

    python tools/rerender_report.py                 # the newest audited video
    python tools/rerender_report.py <video_hash>

Every stage output is content-addressed and already written: verdicts, score,
evidence and the compiled brief. Only the HTML needs rebuilding after a change
to the report code, and rebuilding it should not depend on Gemini being up --
which is exactly the situation this was written in.

The recommendations are the one part of Phase 7 that costs a model call. They
are read back from the previous report JSON rather than regenerated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app.config import get_settings  # noqa: E402
from auditor import runtime  # noqa: E402


def newest(paths):
    paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def main() -> int:
    get_settings()
    ns = runtime.load()
    art = HERE / 'data' / 'artifacts'

    want = sys.argv[1] if len(sys.argv) > 1 else None
    cands = [d for d in art.iterdir()
             if d.is_dir() and list(d.glob('verdicts__*.json'))
             and (want is None or d.name.startswith(want))]
    if not cands:
        print('  no audited video found under data/artifacts')
        return 1
    vdir = max(cands, key=lambda d: max(
        f.stat().st_mtime for f in d.glob('*.json')))
    vh = vdir.name
    print(f'  video_hash {vh[:16]}')

    # NEWEST IS NOT BEST. A run that 503'd part-way writes a verdicts
    # artifact too -- angle None, five UNCERTAINs, and a raw Gemini error
    # stored as each reason. Picking it by mtime rendered a report built on a
    # failed audit and made it look like the report code had regressed.
    # Prefer the most DECIDED audit: fewest verdicts carrying a model error,
    # then most PASS/FAIL, then newest.
    def _quality(path: Path):
        v = json.loads(path.read_text(encoding='utf-8'))
        vs = v.get('verdicts') or []
        broken = sum(1 for x in vs
                     if any(t in str(x.get('reason') or x.get('rationale')
                                     or '')
                            for t in ('503', '429', 'UNAVAILABLE', "{'error'")))
        decided = sum(1 for x in vs
                      if x.get('status') in ('PASS', 'FAIL', 'PARTIAL'))
        has_angle = bool((v.get('creative_angle') or {}).get('angle'))
        return (-broken, decided, has_angle, path.stat().st_mtime)

    cands_v = sorted(vdir.glob('verdicts__*.json'), key=_quality, reverse=True)
    for p in cands_v:
        q = _quality(p)
        print(f'    candidate {p.name[:24]}  errors={-q[0]} decided={q[1]} '
              f'angle={q[2]}')
    result = json.loads(cands_v[0].read_text(encoding='utf-8'))
    print(f'    using    {cands_v[0].name}')

    # PAIR THE SCORE TO THOSE VERDICTS -- do not take the newest.
    #
    # Every score artifact records scored_from.verdicts_cache_key: the verdicts
    # it was computed from. Taking the newest score next to the best verdicts
    # produced a page headed "Nothing to fix" above a list containing four
    # FAILs, because the number came from a different audit than the findings.
    # The link is written in the artifact; use it, and refuse rather than guess.
    vkey = result.get('cache_key') or cands_v[0].stem.split('__')[-1]
    paired = None
    for sp in sorted(vdir.glob('score__*.json')):
        sj = json.loads(sp.read_text(encoding='utf-8'))
        if (sj.get('scored_from') or {}).get('verdicts_cache_key') == vkey:
            paired, score = sp, sj
            break
    if paired is None:
        print(f'\n  No score artifact was computed from verdicts {vkey}.')
        print('  Refusing to show one run\'s score over another run\'s')
        print('  findings. Re-run the audit for this video.')
        return 1
    print(f'    score    {paired.name}  (computed from {vkey})')

    ev = json.loads(newest(vdir.glob('evidence__*.json')).read_text(
        encoding='utf-8'))
    print(f'    verdicts : {len(result.get("verdicts") or [])}')
    print(f'    score    : {(score.get("score") or {}).get("headline")}  '
          f'{(score.get("score") or {}).get("status_band")}')

    bh = result.get('brief_hash') or score.get('brief_hash') or ''
    bdir = HERE / 'data' / 'briefs' / bh
    compiled = json.loads(newest(bdir.glob('requirements__*.json')).read_text(
        encoding='utf-8'))
    print(f'    brief    : {bh[:16]}  '
          f'{len(compiled.get("requirements") or [])} requirement(s)')

    records = ns['load_records'](ev)
    print(f'    evidence : {len(records)} record(s)')

    # The one model call in Phase 7. Read it back rather than spend it -- but
    # only from the report that belongs to THIS score. A report artifact is
    # named for the score it was built from, so the match is exact. Reusing
    # the newest instead printed the 503 run's "Nothing to fix" above this
    # run's four FAILs: true of that audit, false of this one.
    skey = paired.stem.split('__')[-1]
    prev = vdir / f'report__{skey}.json'
    rec = {}
    if prev.exists():
        rec = (json.loads(prev.read_text(encoding='utf-8'))
               .get('recommendations') or {})
        if isinstance(rec, list):
            rec = {'recommendations': rec}
        print(f'    advice   : {len(rec.get("recommendations") or [])} '
              f'(reused from {prev.name}, no model call)')
    else:
        print(f'    advice   : none -- no report__{skey}.json to reuse')

    # Advice carried over is only as good as the verdicts it was written for.
    _short = [v for v in (result.get('verdicts') or [])
              if v.get('status') in ('FAIL', 'PARTIAL')]
    if _short and not (rec.get('recommendations') or []):
        print(f'               {len(_short)} requirement(s) fell short and no '
              f'edits are on file;')
        print('               the report will say so rather than claim there '
              'is nothing to fix.')

    video = next((v for v in ns['discover_videos']()
                  if v['video_hash'] == vh), {'video_hash': vh,
                                              'video_id': vh[:16],
                                              'duration_s': 0})
    figs = ns['build_figures'](score, result, records, cfg=ns['P7'])
    out = ns['write_report'](video, result, compiled, score, records, rec,
                             figs, ns['P7'], verbose=False)
    p = Path(out['html_path'])
    print(f'\n  wrote {p}')
    print(f'        {p.stat().st_size / 1024:.0f} KB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
