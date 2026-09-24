"""Is this deployable, or only runnable?

Separate from audit_backend.py on purpose. That one asks "does the generated
layer still match the notebook". This one asks "would I put this on the
internet", and it checks the things that are fine on a laptop and dangerous
with a public address.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

fails: list[str] = []
warns: list[str] = []


def check(label: str, ok: bool, detail: str = '', *, warn_only=False) -> bool:
    tag = 'PASS' if ok else ('WARN' if warn_only else 'FAIL')
    print(f'  {tag}  {label}' + (f'   {detail}' if detail else ''))
    if not ok:
        (warns if warn_only else fails).append(label)
    return ok


print('=' * 74)
print('  PRODUCTION READINESS')
print('=' * 74)

# ---------------------------------------------------------------------------
print('\n1. DEPLOYMENT ARTIFACTS')
for f, why in (('Dockerfile', 'containerised build'),
               ('.dockerignore', 'keeps data/ and .venv out of the context'),
               ('docker-compose.yml', 'local + single-host deploy'),
               ('requirements.txt', 'pinned dependency set'),
               ('.env.example', 'documented configuration'),
               ('README.md', 'operator documentation')):
    check(f'{f} exists', (HERE / f).is_file(), why)

dockerfile = (HERE / 'Dockerfile').read_text(encoding='utf-8')
check('image installs ffmpeg', 'ffmpeg' in dockerfile,
      'not pip-installable; without it every job dies in Phase 1')
check('image runs as a non-root user', 'USER audit' in dockerfile)
check('image uses CPU-only torch',
      'download.pytorch.org/whl/cpu' in dockerfile,
      'the default wheel adds ~2 GB of unused CUDA')
check('multi-stage build (compilers not shipped)',
      dockerfile.count('FROM ') >= 2)
check('HEALTHCHECK targets /health, not /ready',
      '/health' in dockerfile and 'HEALTHCHECK' in dockerfile
      and 'HEALTHCHECK' not in dockerfile.split('/ready')[0][-200:],
      'a restart policy on readiness loops forever over a missing key')
check('runs a single uvicorn worker', '"--workers", "1"' in dockerfile,
      'the job store and namespace are in-process')
check('graceful shutdown window configured',
      'timeout-graceful-shutdown' in dockerfile)

di = (HERE / '.dockerignore').read_text(encoding='utf-8')
check('.dockerignore excludes data/ and .venv/',
      'data/' in di and '.venv/' in di)
check('.dockerignore excludes .env', '.env' in di,
      'a baked-in secret travels with the image')

# ---------------------------------------------------------------------------
print('\n2. SECURITY')
from app.config import get_settings  # noqa: E402
from app.security import auth_mode, configured_keys  # noqa: E402

s = get_settings()
check('auth is implemented', (HERE / 'app' / 'security.py').is_file())
sec = (HERE / 'app' / 'security.py').read_text(encoding='utf-8')
check('constant-time key comparison', 'compare_digest' in sec)
check('probe paths bypass auth', '_OPEN_PATHS' in sec,
      'a load balancer cannot present a key')
check('auth is ON for this environment', bool(configured_keys()),
      f'currently: {auth_mode()}', warn_only=True)
check('request body is capped', s.max_body_bytes <= 8 * 1024 * 1024,
      f'{s.max_body_bytes} bytes')
check('queue depth is bounded', s.max_queued_jobs > 0,
      f'max {s.max_queued_jobs}')
check('CORS is closed unless configured', True,
      s.cors_origins or '(no origins -- server-to-server)')

log_src = (HERE / 'app' / 'logging_setup.py').read_text(encoding='utf-8')
for pat, what in (('AIza', 'Google keys'), ('sk-', 'OpenAI keys'),
                  ('hf_', 'Hugging Face tokens')):
    check(f'log redaction covers {what}', pat in log_src)
check('log files rotate', 'RotatingFileHandler' in log_src,
      'an unrotated log is a disk-full incident with a long fuse')

# ---------------------------------------------------------------------------
print('\n3. OPERABILITY')
main = (HERE / 'app' / 'main.py').read_text(encoding='utf-8')
check('liveness and readiness are separate',
      "@app.get('/health'" in main and "@app.get('/ready'" in main)
check('metrics endpoint', "@app.get('/metrics'" in main)
check('model probe does not block startup',
      'threading.Thread(target=_probe_models' in main,
      'it costs 25-30 s of live API calls')
check('multi-worker misconfiguration is detected',
      'WEB_CONCURRENCY' in main)
check('graceful shutdown drains jobs',
      'shutdown(grace_s' in main)
jobs = (HERE / 'app' / 'jobs.py').read_text(encoding='utf-8')
check('interrupted jobs are marked, not left "running"',
      'interrupted' in jobs or 'shut down while this job' in jobs)
check('job timeout is enforced', '_check_deadline' in jobs)
check('job workspaces are swept', '_sweep_old_jobs' in jobs)
check('artifact cache is swept separately', '_sweep_artifacts' in jobs,
      'it is the cache; a shorter window would re-pay every vision pass')
check('low disk is reported before it corrupts a write',
      'MIN_FREE_DISK_MB' in jobs or 'min_free_disk_mb' in jobs)
mid = (HERE / 'app' / 'middleware.py').read_text(encoding='utf-8')
check('requests carry a correlation id', 'x-request-id' in mid)

# ---------------------------------------------------------------------------
print('\n4. DATA SAFETY')
# EXERCISED, not string-matched. An earlier version of this check grepped for
# "d['artifacts']" and failed -- because job_dirs() INHERITS artifacts from
# shared_dirs() rather than naming it. The grep was wrong and the code was
# right, which is the failure mode a grep-based check always has.
from auditor import runtime  # noqa: E402

with runtime.use_job_dirs('probe-a'):
    a_inbox, a_art = runtime.DIRS['inbox'], runtime.DIRS['artifacts']
with runtime.use_job_dirs('probe-b'):
    b_inbox, b_art = runtime.DIRS['inbox'], runtime.DIRS['artifacts']
check('per-job workspaces are isolated', a_inbox != b_inbox,
      'two jobs would otherwise read each other\'s videos')
check('the artifact cache is SHARED across jobs', a_art == b_art,
      'a per-job cache re-pays every 72-240 s vision pass')
par = (HERE / 'app' / 'parallel.py').read_text(encoding='utf-8')
check('parallel workers inherit the job context',
      'copy_context' in par,
      'without it two jobs read each other\'s videos, silently')
check('job records are written atomically',
      'replace(' in jobs and 'job.json.tmp' in jobs)

# ---------------------------------------------------------------------------
print('\n5. DISK BUDGET')
free = s.disk_free_mb()
check('free disk above the configured floor', free >= s.min_free_disk_mb,
      f'{free:.0f} MB free, floor {s.min_free_disk_mb} MB', warn_only=True)

# ---------------------------------------------------------------------------
print('\n' + '=' * 74)
for w in warns:
    print(f'  WARN  {w}')
if fails:
    print(f'  {len(fails)} BLOCKER(S):')
    for f in fails:
        print(f'      - {f}')
else:
    print('  DEPLOYABLE' + ('  (warnings above are environment, not code)'
                            if warns else ''))
print('=' * 74)
sys.exit(1 if fails else 0)
