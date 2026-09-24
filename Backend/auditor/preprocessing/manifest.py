"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 17.
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
MANIFEST_SCHEMA_VERSION = '1.0.0'

def build_manifest(meta: MediaMeta,
                   preflight_res: PreflightResult,
                   scan: FrameScan,
                   scenes: SceneAnalysis,
                   frames: list,
                   audio_info: dict,
                   decode_info: dict,
                   cfg: PreprocessConfig,
                   cache_key: str,
                   timings: dict) -> dict:

    counts: dict = {}
    for f in frames:
        counts[f['reason']] = counts.get(f['reason'], 0) + 1

    snap_errors = [f['snap_error'] for f in frames] or [0.0]
    coverage_gaps = np.diff([f['actual_time'] for f in frames]) if len(frames) > 1 else np.zeros(0)

    return {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'pipeline_version': PIPELINE_VERSION,
        'cache_key': cache_key,
        'video_id': meta.video_hash[:16],
        'video_hash': meta.video_hash,

        'media': meta.model_dump(exclude={'probe_raw'}),

        'preflight': {
            'passed': preflight_res.passed,
            'failures': preflight_res.failures,
            'warnings': preflight_res.warnings,
        },

        'scan': {
            'stage_version': SCAN_STAGE_VERSION,
            'total_frames_decoded': scan.n_frames,
            'measured_fps': scan.measured_fps,
            'declared_fps': meta.r_frame_rate,
            'fps_delta': round(scan.measured_fps - meta.r_frame_rate, 4),
            'first_frame_time': round(float(scan.times[0]), 6),
            'last_frame_time': round(float(scan.times[-1]), 6),
            'pts_monotonic': scan.monotonic,
            'approximate_timestamp_frames': int(scan.approx_mask.sum()),
            'scan_seconds': scan.scan_seconds,
        },

        'scenes': {
            'n_shots': scenes.n_shots,
            'cut_times': scenes.cut_times,
            'delta_threshold': scenes.threshold,
            'blank_frame_count': len(scenes.blank_indices),
        },

        'sampling': {
            'config': asdict(cfg.sampler),
            'frames_planned': decode_info['frames_planned'],
            'frames_extracted': decode_info['frames_extracted'],
            'counts_by_reason': counts,
            'budget': cfg.sampler.max_total_frames,
            'snap_error_mean': round(float(np.mean(snap_errors)), 6),
            'snap_error_max': round(float(np.max(snap_errors)), 6),
            'max_temporal_gap_seconds': round(float(coverage_gaps.max()), 4) if coverage_gaps.size else 0.0,
        },

        'decode': {
            'stage_version': DECODE_STAGE_VERSION,
            'config': asdict(cfg.decode),
            **{k: v for k, v in decode_info.items() if k not in ('frames_planned', 'frames_extracted')},
        },

        'audio': {'stage_version': AUDIO_STAGE_VERSION,
                  'config': asdict(cfg.audio), **audio_info},

        'frames': frames,

        'timings': timings,
        'provenance': provenance('preprocess', PIPELINE_VERSION, cache_key,
                                 sum(timings.values())),
    }


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 89: print('manifest.py loaded')
