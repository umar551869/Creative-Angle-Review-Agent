"""Run Phase 1 for real, sequential vs parallel, and diff the artifacts.

Unit tests prove run_parallel schedules correctly. They do not prove that
decoding four videos at once produces the same manifests as decoding them one
at a time -- which is the only question that matters for parity. This builds
real videos with ffmpeg, runs both paths, and compares the stage keys.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ['AUDITOR_DATA_ROOT'] = str(HERE / 'data' / 'paralleltest')
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app.services.pipeline import run_preprocess  # noqa: E402
from auditor import runtime  # noqa: E402

N_VIDEOS = 4
SECONDS = 6


def make_videos(inbox: Path) -> None:
    """Distinct content per file, so two videos cannot share a video_hash."""
    inbox.mkdir(parents=True, exist_ok=True)
    for i in range(N_VIDEOS):
        dest = inbox / f'clip_{i}.mp4'
        if dest.exists():
            continue
        subprocess.run([
            'ffmpeg', '-y', '-v', 'error',
            '-f', 'lavfi', '-i',
            f'testsrc=size=540x960:rate=30:duration={SECONDS},'
            f'hue=h={i * 60}',
            '-f', 'lavfi', '-i',
            f'sine=frequency={220 + i * 110}:duration={SECONDS}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(dest)],
            check=True, capture_output=True, timeout=180)
        print(f'    built {dest.name}  {dest.stat().st_size / 1e3:.0f} KB')


def fingerprint(ns) -> dict:
    """What Phase 1 produced, as the rest of the pipeline will see it."""
    out = {}
    for v in ns['discover_videos']():
        out[v['source']] = {
            'video_hash': v['video_hash'], 'plan_hash': v['plan_hash'],
            'frames': v['frames'], 'duration_s': v['duration_s'],
            'has_audio': v['has_audio'],
        }
    return out


def main() -> int:
    root = Path(os.environ['AUDITOR_DATA_ROOT'])
    shutil.rmtree(root, ignore_errors=True)
    ns = runtime.load()

    print('=' * 70)
    print('  PHASE 1: SEQUENTIAL vs PARALLEL, real ffmpeg')
    print('=' * 70)

    results = {}
    for label, workers in (('sequential', 1), ('parallel', N_VIDEOS)):
        # A fresh artifact store each time: a cache hit would make the second
        # run instant and prove nothing.
        shutil.rmtree(root, ignore_errors=True)
        with runtime.use_job_dirs(f'decode-{label}'):
            inbox = ns['DIRS']['inbox']
            print(f'\n  {label} (workers={workers})')
            make_videos(inbox)
            t0 = time.time()
            out = run_preprocess(force=False, workers=workers)
            dt = time.time() - t0
            fp = fingerprint(ns)
            ok = sum(1 for r in out['rows'] if r.get('status') == 'OK')
            print(f'    {ok}/{len(out["rows"])} OK in {dt:.1f}s')
            results[label] = {'fp': fp, 'dt': dt, 'rows': out['rows']}

    seq, par = results['sequential'], results['parallel']
    print('\n' + '=' * 70)
    fails = []

    same_files = set(seq['fp']) == set(par['fp'])
    print(f'  {"PASS" if same_files else "FAIL"}  same set of videos '
          f'({len(seq["fp"])} vs {len(par["fp"])})')
    fails += [] if same_files else ['file set']

    identical = seq['fp'] == par['fp']
    print(f'  {"PASS" if identical else "FAIL"}  IDENTICAL manifests '
          f'(video_hash, plan_hash, frames, duration, audio)')
    if not identical:
        for k in sorted(set(seq['fp']) | set(par['fp'])):
            if seq['fp'].get(k) != par['fp'].get(k):
                print(f'        {k}:\n          seq {seq["fp"].get(k)}'
                      f'\n          par {par["fp"].get(k)}')
        fails.append('manifests differ')

    for name, fp in (('sequential', seq['fp']),):
        hashes = [v['video_hash'] for v in fp.values()]
        uniq = len(set(hashes)) == len(hashes)
        print(f'  {"PASS" if uniq else "FAIL"}  every video got a distinct '
              f'hash (content-addressing works)')
        fails += [] if uniq else ['hash collision']

    speedup = seq['dt'] / par['dt'] if par['dt'] else 0
    faster = par['dt'] < seq['dt']
    print(f'  {"PASS" if faster else "NOTE"}  parallel {seq["dt"]:.1f}s -> '
          f'{par["dt"]:.1f}s  ({speedup:.2f}x on {N_VIDEOS} clips, '
          f'{os.cpu_count()} cores)')
    if not faster:
        print('        Not a failure: 6-second clips are dominated by process'
              '\n        start-up. The parity result above is the point.')

    print('=' * 70)
    print('  ' + ('PARALLEL DECODE IS SAFE' if not fails
                  else f'FAILURES: {fails}'))
    print('=' * 70)
    shutil.rmtree(root, ignore_errors=True)
    return 1 if fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
