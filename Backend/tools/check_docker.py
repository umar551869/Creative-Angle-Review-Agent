"""Validate the Docker build inputs WITHOUT needing a Docker engine.

WHY THIS EXISTS
---------------
`docker build` needs a running engine, and on Windows that needs WSL2, which
needs a reboot after enabling Virtual Machine Platform. So there is a real
window -- sometimes days -- where the Dockerfile cannot be exercised at all
and nothing says whether it would work.

Most build failures are not subtle. They are: a COPY source that does not
exist, a COPY source that .dockerignore excludes (so it silently arrives
empty), a RUN referencing a script that was moved, or a build context that
accidentally includes gigabytes of cached artifacts. Every one of those is
decidable by reading the files.

This checks those. It cannot tell you the image builds -- only that it will
not fail for a reason that was knowable in advance.

    python tools/check_docker.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

FAILS: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    print(f'  {"PASS" if cond else "FAIL"}  {label}'
          + (f'   {detail}' if detail else ''))
    if not cond:
        FAILS.append(label)


def main() -> int:
    df_path, di_path = HERE / 'Dockerfile', HERE / '.dockerignore'
    if not df_path.is_file():
        print('  no Dockerfile')
        return 1
    df = df_path.read_text(encoding='utf-8')
    ignored = [ln.strip() for ln in
               (di_path.read_text(encoding='utf-8').splitlines()
                if di_path.is_file() else [])
               if ln.strip() and not ln.startswith('#')]

    print('=' * 70)
    print('  DOCKER BUILD PRE-FLIGHT   (no engine required)')
    print('=' * 70)

    # ---- 1. COPY sources -------------------------------------------------
    # `COPY --from=<stage>` reads from an earlier BUILD STAGE, not from the
    # host context, so those paths need not exist on disk. Treating them as
    # host paths reports a failure that is not one.
    print('\n1. COPY sources resolve from the build context')
    for line in df.splitlines():
        m = re.match(r'^COPY\s+(.*)$', line.strip())
        if not m:
            continue
        rest = m.group(1)
        if '--from=' in rest:
            print(f'  skip  {line.strip()[:60]}   (from an earlier stage)')
            continue
        parts = [p for p in rest.split() if not p.startswith('--')]
        for src in parts[:-1]:                      # last token is the dest
            p = HERE / src.rstrip('/')
            excluded = any(e.rstrip('/') == src.rstrip('/') for e in ignored)
            check(f'COPY {src}', p.exists() and not excluded,
                  f'exists={p.exists()} ignored={excluded}')

    # ---- 2. scripts the build runs ---------------------------------------
    print('\n2. Scripts the build executes')
    for m in re.findall(r'(tools/\S+\.py)', df):
        check(f'{m} is present', (HERE / m).is_file())

    # ---- 3. build context size -------------------------------------------
    # data/ is videos, frames and artifacts; .venv/ is the local environment.
    # Neither belongs in an image, and together they are gigabytes that would
    # be tarred and sent to the daemon on EVERY build.
    print('\n3. Heavy directories stay out of the context')
    for heavy in ('data', '.venv', '__pycache__', '.git'):
        d = HERE / heavy
        if not d.exists():
            continue
        excluded = any(e.rstrip('/') == heavy for e in ignored)
        mb = 0.0
        if not excluded:
            try:
                mb = sum(f.stat().st_size for f in d.rglob('*')
                         if f.is_file()) / 1e6
            except OSError:
                mb = -1
        check(f'{heavy}/ excluded', excluded,
              '' if excluded else f'would add ~{mb:.0f} MB to every build')

    # ---- 4. compose ------------------------------------------------------
    print('\n4. docker-compose.yml')
    cp = HERE / 'docker-compose.yml'
    if cp.is_file():
        comp = cp.read_text(encoding='utf-8')
        check('builds from this directory', 'context: .' in comp)
        check('model weights on a NAMED volume', 'audit-models:/models' in comp,
              'a bind mount or none re-downloads ~1.8 GB per container')
        check('data on a NAMED volume', 'audit-data:/data' in comp)
        check('reads .env', 'env_file: .env' in comp)
        check('.env exists to be read', (HERE / '.env').is_file(),
              'compose fails to start without it')
        check('restart policy set', 'restart:' in comp)
        # /ready reports a missing API key as not-ready; a restart policy
        # pointed there restarts the container forever over a config problem.
        check('healthcheck uses /health, never /ready',
              '/health' in comp and '/ready' not in comp)
    else:
        check('docker-compose.yml present', False)

    # ---- 5. runtime image sanity ----------------------------------------
    print('\n5. Runtime image')
    check('ffmpeg installed in the image',
          re.search(r'apt-get install[^\n]*(\n[^\n]*)*?ffmpeg', df) is not None,
          'not pip-installable; every job dies in Phase 1 without it')
    check('ONE uvicorn worker', '"--workers", "1"' in df,
          'N workers = N job stores and N model loads')
    check('runs as a non-root user', re.search(r'^USER\s+\w+', df, re.M)
          is not None)
    check('EXPOSEs the port compose publishes', 'EXPOSE 8000' in df)

    print('\n' + '=' * 70)
    if FAILS:
        print(f'  {len(FAILS)} PROBLEM(S): {", ".join(FAILS[:4])}')
        print('=' * 70)
        return 1
    print('  BUILD INPUTS SOUND -- nothing knowable in advance will fail.')
    print('  This does not prove the image builds; run `docker compose build`.')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
