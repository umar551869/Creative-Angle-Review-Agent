"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 18, 50.
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
@dataclass
class PreprocessResult:
    status: str                     # 'OK' | 'FAILED_PREPROCESSING'
    video_hash: str
    manifest: Optional[dict]
    manifest_path: Optional[Path]
    frames_dir: Optional[Path]
    audio_path: Optional[Path]
    meta: Optional[MediaMeta]
    scan: Optional[FrameScan]
    scenes: Optional[SceneAnalysis]
    preflight: Optional[PreflightResult]
    cache_hit: bool = False
    error: Optional[str] = None

    def summary(self) -> str:
        if self.status != 'OK':
            return f'{self.status}: {self.error}'
        m, s = self.manifest['media'], self.manifest['sampling']
        a = self.manifest['audio']
        audio_str = f"yes, {a.get('duration_seconds')}s" if a['has_audio'] else 'NO'
        warn_str = str([w['code'] for w in self.manifest['preflight']['warnings']] or 'none')
        return (
            f"Duration:          {m['duration_seconds']:.2f}s\n"
            f"Resolution:        {m['display_width']}x{m['display_height']}"
            f"{' (vertical)' if m['is_vertical'] else ' (NOT vertical)'}\n"
            f"FPS:               {m['r_frame_rate']:.3f} declared / "
            f"{self.manifest['scan']['measured_fps']:.3f} measured"
            f"{'  [VFR]' if m['is_vfr'] else ''}\n"
            f"Frames decoded:    {self.manifest['scan']['total_frames_decoded']}\n"
            f"Frames extracted:  {s['frames_extracted']}  {s['counts_by_reason']}\n"
            f"Shots detected:    {self.manifest['scenes']['n_shots']}\n"
            f"Snap error:        mean {s['snap_error_mean']*1000:.1f} ms / "
            f"max {s['snap_error_max']*1000:.1f} ms\n"
            f"Max temporal gap:  {s['max_temporal_gap_seconds']:.2f}s\n"
            f"Audio:             {audio_str}\n"
            f"Rotation applied:  {self.manifest['decode']['rotation_applied_ccw']} deg CCW\n"
            f"Warnings:          {warn_str}\n"
            f"Cache:             {'HIT' if self.cache_hit else 'MISS (computed)'}"
        )

def preprocess_video(video_path,
                     cfg: PreprocessConfig = CFG,
                     force: bool = False,
                     verbose: bool = True) -> PreprocessResult:
    video_path = Path(video_path)
    timings: dict = {}
    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    def _stage(name):
        class _T:
            def __enter__(self_): self_.t0 = time.time(); return self_
            def __exit__(self_, *exc):
                timings[name] = round(time.time() - self_.t0, 3)
                log(f'  [{name:<12s}] {timings[name]:6.2f}s')
        return _T()

    # ---- identity -----------------------------------------------------------
    with _stage('hash'):
        video_hash = sha256_file(video_path)
    vdir = video_workdir(video_hash)
    log(f'video_hash   {video_hash[:16]}…')

    # ---- probe (cached) -----------------------------------------------------
    meta_path = vdir / 'media_meta.json'
    with _stage('probe'):
        if meta_path.exists() and not force:
            meta = MediaMeta.model_validate(read_json(meta_path))
        else:
            try:
                meta = probe_video(video_path, video_hash=video_hash)
            except Exception as exc:
                return PreprocessResult('FAILED_PREPROCESSING', video_hash, None, None, None,
                                        None, None, None, None, None,
                                        error=f'PROBE_FAILED: {exc}')
            write_json(meta_path, meta.model_dump())

    # ---- preflight gates ----------------------------------------------------
    with _stage('preflight'):
        pf = preflight(video_path, meta, cfg.preflight)
    if not pf.passed:
        write_json(vdir / 'preflight_failed.json', pf.model_dump())
        return PreprocessResult('FAILED_PREPROCESSING', video_hash, None, None, None, None,
                                meta, None, None, pf,
                                error='; '.join(f"{f['code']}({f['detail']})" for f in pf.failures))
    for w in pf.warnings:
        log(f'  WARN  {w["code"]}: {w["detail"]}')

    # ---- scan: keyed on VIDEO CONTENT ONLY, so sampler changes never re-decode
    scan_path = vdir / 'scan.npz'
    with _stage('scan'):
        if scan_path.exists() and not force:
            scan = load_scan(scan_path)
            log(f'  (scan cache hit: {scan.n_frames} frames)')
        else:
            scan = scan_video(video_path, meta, cfg.scene)
            save_scan(scan_path, scan)

    # ---- scenes (cheap; recomputed from cached thumbnails) ------------------
    with _stage('scenes'):
        scenes = detect_scenes(scan, cfg.scene)
        write_json(vdir / 'scenes.json', {
            'cut_times': scenes.cut_times, 'n_shots': scenes.n_shots,
            'threshold': scenes.threshold, 'blank_frame_count': len(scenes.blank_indices),
            'config': asdict(cfg.scene),
        })

    # ---- plan hash: everything that changes which frames get extracted ------
    plan_hash = stage_key('frames', DECODE_STAGE_VERSION, [video_hash],
                          {'sampler': asdict(cfg.sampler),
                           'decode': asdict(cfg.decode),
                           'scene': asdict(cfg.scene)})
    plan_dir = vdir / plan_hash
    manifest_path = plan_dir / 'manifest.json'
    frames_dir = plan_dir / 'frames'

    # ---- audio (cached, independent of sampling) ---------------------------
    audio_path = vdir / 'audio.wav'
    audio_info_path = vdir / 'audio.json'
    with _stage('audio'):
        if audio_info_path.exists() and not force and (audio_path.exists() or not meta.has_audio):
            audio_info = read_json(audio_info_path)
        else:
            audio_info = extract_audio(video_path, audio_path, meta, cfg.audio)
            write_json(audio_info_path, audio_info)

    # ---- full cache hit? ----------------------------------------------------
    if manifest_path.exists() and frames_dir.exists() and not force:
        manifest = read_json(manifest_path)
        if len(list(frames_dir.glob('*.jpg'))) == manifest['sampling']['frames_extracted']:
            log(f'  MANIFEST CACHE HIT  ({plan_hash})')
            return PreprocessResult('OK', video_hash, manifest, manifest_path, frames_dir,
                                    Path(audio_info['audio_path']) if audio_info.get('audio_path') else None,
                                    meta, scan, scenes, pf, cache_hit=True)

    # ---- plan + extract -----------------------------------------------------
    with _stage('plan'):
        plan_items = build_frame_plan(scan, scenes, meta, cfg.sampler)
    with _stage('extract'):
        frames, decode_info = extract_frames(video_path, plan_items, meta, cfg.decode, frames_dir)

    manifest = build_manifest(meta, pf, scan, scenes, frames, audio_info,
                              decode_info, cfg, plan_hash, timings)
    write_json(manifest_path, manifest)

    return PreprocessResult('OK', video_hash, manifest, manifest_path, frames_dir,
                            Path(audio_info['audio_path']) if audio_info.get('audio_path') else None,
                            meta, scan, scenes, pf, cache_hit=False)


import pandas as pd

def preprocess_folder(folder, cfg: PreprocessConfig = CFG,
                      patterns=('*.mp4', '*.mov', '*.webm', '*.mkv'),
                      force: bool = False) -> 'pd.DataFrame':
    folder = Path(folder)
    paths = sorted({p for pat in patterns for p in folder.glob(pat)})
    print(f'{len(paths)} video(s) in {folder}\n')

    rows, run_log = [], []
    for i, p in enumerate(paths, 1):
        t0 = time.time()
        try:
            r = preprocess_video(p, cfg=cfg, force=force, verbose=False)
            status, err = r.status, r.error
        except Exception as exc:
            traceback.print_exc()
            r, status, err = None, 'EXCEPTION', f'{type(exc).__name__}: {exc}'

        row = {'file': p.name, 'status': status, 'wall_s': round(time.time() - t0, 2)}
        if r is not None and r.status == 'OK':
            man = r.manifest
            row.update({
                'duration_s': round(man['media']['duration_seconds'], 2),
                'resolution': f'{man["media"]["display_width"]}x{man["media"]["display_height"]}',
                'vfr': man['media']['is_vfr'],
                'fps': round(man['scan']['measured_fps'], 2),
                'frames': man['sampling']['frames_extracted'],
                'shots': man['scenes']['n_shots'],
                'audio': man['audio']['has_audio'],
                'rot': man['decode']['rotation_applied_ccw'],
                'max_gap_s': man['sampling']['max_temporal_gap_seconds'],
                'warnings': ','.join(w['code'] for w in man['preflight']['warnings']) or '-',
                'cache': 'HIT' if r.cache_hit else 'miss',
            })
        else:
            row['error'] = err
        rows.append(row)
        run_log.append(row)
        print(f'[{i}/{len(paths)}] {p.name:<44s} {status:<22s} {row["wall_s"]:5.2f}s')

    write_json(DIRS['runs'] / f'batch_{time.strftime("%Y%m%d_%H%M%S")}.json', run_log)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 156: print('pipeline.py loaded  --  backend complete')
#   line 48: batch_df = preprocess_folder(DIRS['inbox'], patterns=tuple((f'*{s}' for s in
#   line 52: print()
#   line 53: print(batch_df.to_string(index=False))
#   line 59: _inbox = sorted((f for f in DIRS['inbox'].iterdir() if f.is_file() and f.suf
#   line 61: _have = {v.get('source') for v in discover_videos()}
#   line 62: _lost = [f.name for f in _inbox if f.name not in _have]
#   line 63: print()
#   line 64: print(f'  BATCH RECONCILE: {len(_inbox)} video(s) in the inbox, {len(_inbox)
#   line 66: if _lost:
