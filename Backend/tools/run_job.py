"""Run a real audit through the API and print everything it concluded.

    python tools/run_job.py --video <url> [--video <url> ...] --brief <docs url>
    python tools/run_job.py ... --brief-text "Show the product."
    python tools/run_job.py            # no flags: asks for the links

Uses the persistent data root, so artifacts are cached and a re-run of the
same video against the same brief costs almost nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def money(x, nd=0):
    return '—' if x is None else f'{float(x):.{nd}f}'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', action='append')
    ap.add_argument('--brief')
    ap.add_argument('--brief-text')
    ap.add_argument('--label', default='cli run')
    ap.add_argument('--force', action='store_true',
                    help='re-run stages that already have a cached artifact')
    ap.add_argument('--timeout', type=int, default=40 * 60)
    ap.add_argument('--json-out', help='write the full job record here')
    args = ap.parse_args()

    # No flags: prompt, so it can be run from a double-click or a bare cmd.
    if not args.video:
        raw = input('TikTok link(s), comma-separated: ').strip()
        args.video = [u.strip() for u in raw.split(',') if u.strip()]
        if not args.video:
            print('no video link given')
            return 1
    if not args.brief and not args.brief_text:
        args.brief = input('Brief (Google Docs link): ').strip() or None

    from fastapi.testclient import TestClient

    from app.config import get_settings
    import app.main

    s = get_settings()
    if not s.gemini_api_key:
        print('No GEMINI_API_KEY in Backend/.env')
        return 1

    payload = {'video_urls': args.video, 'label': args.label,
               'force_reaudit': bool(args.force)}
    if args.brief:
        payload['brief_url'] = args.brief
    elif args.brief_text:
        payload['brief_text'] = args.brief_text
    else:
        print('give --brief (a Google Docs URL) or --brief-text')
        return 1

    t0 = time.time()
    print('=' * 78)
    print(f'  {len(args.video)} video(s)  ->  '
          f'{(args.brief or "inline text")[:58]}')
    print('=' * 78)

    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        r = c.post('/analyze', json=payload)
        if r.status_code != 202:
            print(f'  REFUSED {r.status_code}: {r.text[:400]}')
            return 1
        job_id = r.json()['job_id']
        print(f'  job {job_id}\n')

        last_phase, seen_warnings = None, 0
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(5)
            job = c.get(f'/jobs/{job_id}').json()
            if job['phase'] != last_phase:
                last_phase = job['phase']
                print(f'  [{time.time() - t0:6.0f}s]  {last_phase}')
            for w in (job.get('warnings') or [])[seen_warnings:]:
                print(f'            ! {w}')
            seen_warnings = len(job.get('warnings') or [])
            if job['status'] in ('succeeded', 'failed', 'partial'):
                break
        else:
            print('  TIMED OUT')
            return 1

        job = c.get(f'/jobs/{job_id}').json()
        report_bodies = {}
        for row in job.get('results') or []:
            u = row.get('report_html_url')
            if u:
                rr = c.get(u)
                if rr.status_code == 200:
                    report_bodies[row['video_id']] = len(rr.content)

    # ---------------------------------------------------------------- output
    print()
    print('=' * 78)
    print(f'  {job["status"].upper()}   {money(job.get("elapsed_s"))}s   '
          f'{job.get("completed_videos")}/{job.get("requested_videos")} '
          f'video(s)')
    print('=' * 78)
    if job.get('error'):
        print(f'  ERROR: {job["error"]}')

    for t in job.get('timings') or []:
        print(f'    {t["phase"]:<12} {t["seconds"]:>7.1f}s'
              + (f'   {t["detail"]}' if t.get('detail') else ''))

    b = job.get('brief') or {}
    print(f'\n  BRIEF  {b.get("origin")}')
    print(f'    hash          : {str(b.get("brief_hash"))[:16]}')
    print(f'    requirements  : {len(b.get("requirements") or [])}  '
          f'({b.get("scoring_units")} scoring unit(s), '
          f'weight {b.get("total_weight")})')
    print(f'    choice groups : {b.get("choice_groups")}')
    print(f'    approved      : {b.get("approved")} by {b.get("approved_by")}')
    print(f'    named angles  : {b.get("named_angles")}')
    if b.get('unstable'):
        print('    ! COMPILE_UNSTABLE -- the consensus runs disagreed')

    for row in job.get('results') or []:
        sc = row.get('score') or {}
        ca = row.get('creative_angle') or {}
        print('\n' + '-' * 78)
        print(f'  {row.get("source")}   {row.get("status")}')
        print('-' * 78)
        if row.get('error'):
            print(f'    error: {row["error"]}')
            continue
        band = sc.get('status_band')
        if sc.get('lead_with_band') and sc.get('band_low') is not None:
            head = (f'{money(sc.get("band_low"))}-'
                    f'{money(sc.get("band_high"))}  '
                    f'(graded from the {sc.get("band_basis")} end)')
        else:
            head = money(sc.get('headline'))
        print(f'    SCORE       : {head}   {band}')
        print(f'    literal     : {money(sc.get("literal_headline"))}'
              f'   (the gap is the paraphrase the brief allows)')
        print(f'    coverage    : {money((sc.get("coverage") or 0) * 100)}%'
              f'   over {sc.get("scoring_units")} unit(s)')
        print(f'    standing    : {row.get("standing")}')
        print(f'    talking pts : {row.get("talking_points_covered")}/'
              f'{row.get("talking_points_total")}')
        print(f'    verdicts    : {row.get("verdict_mix")}')

        print(f'\n    CREATIVE ANGLE ({ca.get("angles_source")})')
        print(f'      what she made : {ca.get("angle")}')
        print(f'      nearest       : {ca.get("nearest_brief_concept")}')
        print(f'      dominant      : {ca.get("dominant_angle")}')
        for f in ca.get('concept_fit') or []:
            print(f'        {f.get("percent"):>5.0f}%  {f.get("angle")}')
        if ca.get('flags'):
            print(f'      flags         : {ca["flags"]}')

        health = row.get('modality_health') or {}
        if health:
            print('\n    EVIDENCE')
            print(f'      records     : {row.get("evidence_records")}')
            for k, v in health.items():
                bits = [x for x, on in (('ran', v.get('ran')),
                                        ('absent', v.get('absent')),
                                        ('degraded', v.get('degraded')))
                        if on]
                print(f'      {k:<10}  {", ".join(bits) or "-"}'
                      + (f'   {str(v.get("reason"))[:60]}'
                         if v.get('reason') else ''))
            blocked = [m for m, ok in (row.get('can_fail_on') or {}).items()
                       if ok is False]
            if blocked:
                print(f'      cannot assert an absence on: {blocked}')
                print('        -> those requirements read UNCERTAIN, not FAIL')

        vs = [v for v in (row.get('verdicts') or [])]
        if vs:
            print(f'\n    REQUIREMENTS ({len(vs)})')
            for v in vs:
                if v.get('status') == 'NOT_APPLICABLE':
                    continue
                print(f'      {str(v.get("status")):<14} '
                      f'{str(v.get("requirement_label"))[:52]:<54}'
                      f'{str(v.get("decided_by") or v.get("layer") or ""):>6}')
                if v.get('rationale') or v.get('reason'):
                    why = str(v.get('rationale') or v.get('reason'))[:110]
                    print(f'                     {why}')

        recs = row.get('recommendations') or []
        if recs:
            print(f'\n    WHAT TO CHANGE ({len(recs)})')
            for rc in recs[:6]:
                txt = rc.get('edit') or rc.get('text') or str(rc)
                print(f'      - {str(txt)[:110]}')

        if row.get('visual_stale'):
            print('\n    ! visual artifact does not match the current config')
        if row.get('visual_missing'):
            print('\n    ! NO visual evidence -- speech and OCR only')
        print(f'\n    report      : {row.get("report_html_url")}'
              + (f'  ({report_bodies.get(row["video_id"], 0) / 1024:.0f} KB)'
                 if row['video_id'] in report_bodies else ''))

    dist = job.get('angle_distribution') or []
    if dist:
        print('\n' + '=' * 78)
        print('  ACROSS THE BATCH -- which of the brief\'s angles were used')
        print('=' * 78)
        for d in dist:
            mark = '  <- nobody used this' if d.get('unused') else ''
            print(f'    {d["angle"][:40]:<42} primary for {d["dominant_for"]}'
                  f'   mean {d["mean_percent"]}%{mark}')
        print('    These percentages DESCRIBE what each creator made. '
              'They are never scored.')

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(job, indent=2, default=str), encoding='utf-8')
        print(f'\n  full job record -> {args.json_out}')
    return 0 if job['status'] in ('succeeded', 'partial') else 1


if __name__ == '__main__':
    raise SystemExit(main())
