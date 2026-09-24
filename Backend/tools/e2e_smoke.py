"""A REAL job, end to end, through the API. Spends Gemini quota.

This is the gate docs/04_parity_checklist.md §4.5 has been waiting on: 127
tests prove the structure, and not one of them has put a video through the
pipeline.

It makes its own video with ffmpeg and serves it over localhost, so it needs
no TikTok and no network beyond Gemini -- TikTok refusing a datacentre IP is a
separate problem and must not be able to fail this test.

    python tools/e2e_smoke.py            # full run
    python tools/e2e_smoke.py --keep     # leave the workspace for inspection
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

KEEP = '--keep' in sys.argv
WORK = HERE / 'data' / 'e2e'
SERVE = WORK / 'serve'

# The real Apothecary brief. Two angles as NUMBERED SUB-HEADINGS -- the shape
# fix 68 exists to read, so a correct run must report exactly these two.
BRIEF = """# UGC Brief - Format Library, Hooks and Talking Points

**Creative Concepts**
Top-performing TikTok formats with engagement success.

**1. No judgement zone**
* Hook: "Don't judge but this is what my supplements look like"
* Creator shares disorganized supplement storage
* Proposes pill organizer as a solution
* Format: Skit-style video

**2. Health journey**
* Hook options: "I was just about to refill my pill organiser"
* Discusses maintaining regularity with medications
* Highlights how the organizer supports consistency

**Key Talking Points + Product Features**
* Extra-large (7" x 9") with 21 compartments
* Seven-day organization with three daily doses
* BPA-free materials

**Call to Action Ideas**
* "If you take multiple pills a day, this is a total game changer."
* "Click the link and make your daily routine way less stressful."
"""

EXPECTED_ANGLES = ['No judgement zone', 'Health journey']

fails: list[str] = []


def check(label: str, ok: bool, detail: str = '') -> bool:
    print(f'  {"PASS" if ok else "FAIL"}  {label}' + (f'   {detail}' if detail
                                                      else ''))
    if not ok:
        fails.append(label)
    return ok


def make_video(dest: Path) -> None:
    """15 s of video with a tone, and on-screen text WHERE POSSIBLE.

    drawtext needs a font file on Windows and the build here segfaults without
    one. That would give OCR something to read, which is nice but is not what
    this test is for -- so it is attempted and skipped, never fatal. The
    expensive path being proved is the hosted vision call.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = ['ffmpeg', '-y', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc=size=540x960:rate=30:duration=15',
            '-f', 'lavfi', '-i', 'sine=frequency=330:duration=15']
    tail = ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(dest)]

    font = next((f for f in (Path('C:/Windows/Fonts/arial.ttf'),
                             Path('/usr/share/fonts/truetype/dejavu/'
                                  'DejaVuSans.ttf'),
                             Path('/System/Library/Fonts/Helvetica.ttc'))
                 if f.exists()), None)
    attempts = []
    if font:
        esc = str(font).replace('\\', '/').replace(':', r'\:')
        attempts.append(base + [
            '-vf', f"drawtext=fontfile='{esc}':text='BPA free 21 "
                   f"compartments':fontcolor=white:fontsize=34:"
                   f"x=(w-text_w)/2:y=h-140:box=1:boxcolor=black@0.6"] + tail)
    attempts.append(base + tail)

    for i, cmd in enumerate(attempts):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=240)
            print(f'    built {dest.name}  {dest.stat().st_size / 1e6:.1f} MB'
                  + ('  (with on-screen text)' if font and i == 0
                     else '  (no on-screen text -- OCR will find nothing)'))
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    raise SystemExit('ffmpeg could not build a test video')


def serve(directory: Path) -> tuple[str, http.server.HTTPServer]:
    """A local origin for the video, so the test does not depend on TikTok."""
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(directory))
    httpd = http.server.HTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{port}', httpd


def main() -> int:
    os.environ['AUDITOR_DATA_ROOT'] = str(WORK)
    os.environ.setdefault('AUDITOR_BRIEF_COMPILE_RUNS', '1')  # save quota
    # --reuse keeps the content-addressed artifacts, so a re-run after a test
    # change costs almost nothing: the vision pass and the frozen brief are
    # both cache hits. Without it every iteration re-pays a 4-minute job.
    if '--reuse' not in sys.argv:
        shutil.rmtree(WORK, ignore_errors=True)
    SERVE.mkdir(parents=True, exist_ok=True)

    print('=' * 74)
    print('  END-TO-END: a real video through the real API')
    print('=' * 74)

    print('\n  1. building a video')
    make_video(SERVE / 'clip.mp4')
    base, httpd = serve(SERVE)
    print(f'    serving at {base}/clip.mp4')

    from fastapi.testclient import TestClient

    from app.config import get_settings
    get_settings.cache_clear()
    import app.main
    import importlib
    importlib.reload(app.main)
    s = get_settings()
    if not s.gemini_api_key:
        print('\n  no GEMINI_API_KEY -- cannot run a real job')
        return 1

    t0 = time.time()
    with TestClient(app.main.app, raise_server_exceptions=False) as c:
        print('\n  2. submitting')
        r = c.post('/analyze', json={
            'video_urls': [f'{base}/clip.mp4'],
            'brief_text': BRIEF,
            'label': 'e2e smoke'})
        if not check('accepted (202)', r.status_code == 202, r.text[:160]):
            return 1
        job_id = r.json()['job_id']
        print(f'    job {job_id}')

        print('\n  3. running (this makes real model calls) ...')
        last = None
        deadline = time.time() + 25 * 60
        while time.time() < deadline:
            time.sleep(5)
            body = c.get(f'/jobs/{job_id}').json()
            if body['phase'] != last:
                last = body['phase']
                print(f'    [{time.time() - t0:6.0f}s] {last}')
            if body['status'] in ('succeeded', 'failed', 'partial'):
                break
        else:
            check('finished inside 25 minutes', False)
            return 1

        job = c.get(f'/jobs/{job_id}').json()
        print(f'\n    status={job["status"]}  {job.get("elapsed_s")}s')
        for w in job.get('warnings') or []:
            print(f'    warning: {w[:120]}')
        if job.get('error'):
            print(f'    error: {job["error"][:300]}')

        print('\n  4. the brief')
        brief = job.get('brief') or {}
        print(f'    {brief.get("scoring_units")} scoring unit(s), '
              f'approved={brief.get("approved")} by '
              f'{brief.get("approved_by")}')
        print(f'    named_angles: {brief.get("named_angles")}')
        check('brief compiled and froze',
              bool(brief.get('approved')) and brief.get('status') == 'OK')
        check('the brief\'s OWN angles were found, not its hooks',
              brief.get('named_angles') == EXPECTED_ANGLES,
              str(brief.get('named_angles')))

        print('\n  5. the result')
        results = job.get('results') or []
        check('one result row', len(results) == 1, f'{len(results)}')
        if not results:
            return 1
        row = results[0]
        sc = row.get('score') or {}
        ca = row.get('creative_angle') or {}
        print(f'    status   : {row.get("status")}')
        print(f'    score    : {sc.get("headline")} '
              f'(literal {sc.get("literal_headline")})  '
              f'{sc.get("status_band")}  coverage {sc.get("coverage")}')
        print(f'    standing : {row.get("standing")}')
        print(f'    verdicts : {row.get("verdict_mix")}')
        print(f'    angle    : {ca.get("angle")}')
        print(f'    named    : {ca.get("named_angles")}')
        print(f'    fit      : {ca.get("concept_fit")}')
        print(f'    dominant : {ca.get("dominant_angle")}')
        print(f'    source   : {ca.get("angles_source")}')

        check('the video was audited', row.get('status') in ('ok',
                                                             'module_failed'),
              str(row.get('error'))[:140])
        check('a score came back', sc.get('headline') is not None)
        check('evidence was assembled', (row.get('evidence_records') or 0) > 0
              or row.get('status') == 'ok')
        check('angles came from the DOCUMENT, not the fallback',
              ca.get('angles_source') == 'document',
              str(ca.get('angles_source')))
        # NO_ANGLE_LABEL is a legitimate member of the closed list: a video
        # may take an angle the brief never listed, and saying so is the
        # honest answer. This test's video is ffmpeg colour bars, so "none of
        # the listed angles" at 100% is CORRECT -- an earlier version of this
        # assertion excluded it and failed the system for being right.
        allowed_fit = set(EXPECTED_ANGLES) | {'none of the listed angles'}
        got_fit = [f.get('angle') for f in (ca.get('concept_fit') or [])]
        check('concept_fit stays inside the brief\'s closed list',
              all(a in allowed_fit for a in got_fit), str(got_fit))
        check('no angle was invented',
              not [a for a in got_fit if a not in allowed_fit])
        if ca.get('concept_fit'):
            total = sum(float(f.get('percent') or 0)
                        for f in ca['concept_fit'])
            check('concept_fit sums to 100', abs(total - 100) < 1.5,
                  f'{total}')

        print('\n  6. the report')
        rurl = row.get('report_html_url')
        print(f'    {rurl}')
        check('report url returned', bool(rurl))
        if rurl:
            rr = c.get(rurl)
            check('report downloads', rr.status_code == 200,
                  f'{len(rr.content) / 1024:.0f} KB')
            doc = rr.text
            check('report has no content hash in its header',
                  '<span class="rid">' not in doc.split('</header>')[0])
            check('report is restyled', '--ink-3' in doc)
            check('report names the brief\'s angles',
                  all(a in doc for a in EXPECTED_ANGLES))
        z = c.get(f'/jobs/{job_id}/reports.zip')
        check('reports.zip downloads', z.status_code == 200,
              f'{len(z.content) / 1024:.0f} KB')

        print('\n  7. batch view')
        dist = job.get('angle_distribution') or []
        for d in dist:
            print(f'    {d["angle"]:<24} videos={d["videos"]} '
                  f'dominant_for={d["dominant_for"]} '
                  f'mean={d["mean_percent"]}%')
        check('angle distribution computed', len(dist) == 2, f'{len(dist)}')

    httpd.shutdown()
    print('\n' + '=' * 74)
    print(f'  {time.time() - t0:.0f}s total')
    print('  ALL PASS' if not fails else f'  {len(fails)} FAILURE(S): {fails}')
    print('=' * 74)
    if not KEEP:
        shutil.rmtree(WORK, ignore_errors=True)
    else:
        print(f'  workspace kept: {WORK}')
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
