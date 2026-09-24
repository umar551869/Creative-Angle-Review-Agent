"""Poll a job to completion and save the full response.

Mirrors what a front end does: submit, then poll -- never hold a connection
open for a job that takes minutes.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import httpx  # noqa: E402

BASE = 'http://127.0.0.1:8000'
job_id = sys.argv[1] if len(sys.argv) > 1 else \
    (HERE / 'job_id.txt').read_text(encoding='utf-8').strip()
key = (HERE / 'local_api_key.txt').read_text(encoding='utf-8').strip()
out = HERE / f'run_result_{job_id}.json'

print(f'  polling {job_id}')
t0 = time.time()
last = None
while True:
    try:
        r = httpx.get(f'{BASE}/jobs/{job_id}',
                      headers={'x-api-key': key}, timeout=30)
        job = r.json()
    except Exception as exc:
        print(f'  [{time.time() - t0:5.0f}s] poll error: '
              f'{type(exc).__name__}')
        time.sleep(10)
        continue

    stamp = f'{time.time() - t0:5.0f}s'
    now = (job.get('status'), job.get('phase'))
    if now != last:
        print(f'  [{stamp}] {job.get("status"):<10} {job.get("phase")}')
        last = now

    if job.get('status') in ('succeeded', 'partial', 'failed'):
        out.write_text(json.dumps(job, indent=2), encoding='utf-8')
        print(f'\n  DONE in {time.time() - t0:.0f}s -> {out.name}')
        print(f'  status   : {job.get("status")}')
        print(f'  videos   : {job.get("completed_videos")}/'
              f'{job.get("requested_videos")}')
        for w in job.get('warnings') or []:
            print(f'  warning  : {w[:110]}')
        if job.get('error'):
            print(f'  error    : {job["error"][:300]}')
        for t in job.get('timings') or []:
            print(f'    {t["phase"]:<12} {t["seconds"]:>7.1f}s '
                  f'{t.get("detail") or ""}')
        break
    time.sleep(15)
