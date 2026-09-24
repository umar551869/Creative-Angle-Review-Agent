"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 8.
Regenerate with:  python Backend/tools/extract_from_notebook.py

Bodies are VERBATIM. The only removal is the notebook's driver
statements (the lines that run a stage and print a table); those
are listed at the foot of this file and are replaced by
Backend/app/services/.

This file is LOADED BY auditor.runtime, not imported directly.
The notebook shares one global namespace and binds some names
late (globals().get(...)), so the loader reproduces that exactly
rather than guessing an import graph that the original never had.
"""
def restore_exports_from_drive() -> int:
    """Unpack any export tarballs sitting in Drive into the local work tree."""
    if DRIVE_ROOT is None:
        return 0
    n = 0
    for tar_path in sorted((DRIVE_ROOT / 'exports').glob('*.tar.gz')):
        with tarfile.open(tar_path, 'r:gz') as tar:
            tar.extractall(DIRS['artifacts'])
        print(f'restored {tar_path.name}')
        n += 1
    return n

def discover_videos(unique: bool = True) -> list:
    """
    Every video that has a Phase 1 manifest on disk.

    unique=True (default) returns ONE entry per video: the manifest with the most
    frames. This matters because §17's sampler ablation deliberately writes extra
    manifests for the same video under different plan hashes (a 16-frame variant,
    a 32-frame variant, ...). Without this, the batch runner would process the
    same video five times and the hand-off could pick a thinned variant.
    Pass unique=False to see every plan.
    """
    found = []
    for vdir in sorted(DIRS['artifacts'].iterdir()):
        if not vdir.is_dir():
            continue
        for manifest_path in sorted(vdir.glob('*/manifest.json')):
            try:
                man = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                continue
            found.append({
                'video_hash': man['video_hash'],
                'video_id': man['video_id'],
                'source': Path(man['media']['path']).name,
                'duration_s': round(man['media']['duration_seconds'], 2),
                'frames': man['sampling']['frames_extracted'],
                'has_audio': man['audio']['has_audio'],
                'manifest_path': manifest_path,
                'frames_dir': manifest_path.parent / 'frames',
                'audio_path': Path(man['audio']['audio_path']) if man['audio'].get('audio_path') else None,
                'plan_hash': manifest_path.parent.name,
            })

    if unique:
        best: dict = {}
        for v in found:
            cur = best.get(v['video_hash'])
            if cur is None or v['frames'] > cur['frames']:
                best[v['video_hash']] = v
        found = [best[k] for k in sorted(best)]
    return found


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 61: if USE_DRIVE:
#   line 64: _existing = discover_videos()
#   line 65: print(f'discovery.py loaded  --  {len(_existing)} video(s) already have Phas
#   line 66: if _existing:
