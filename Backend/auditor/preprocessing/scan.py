"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 13.
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
class FrameScan:
    times: np.ndarray          # (N,) float64 -- TRUE presentation timestamps, seconds
    indices: np.ndarray        # (N,) int32   -- decode order index
    thumbs: np.ndarray         # (N, S, S) uint8 grayscale
    approx_mask: np.ndarray    # (N,) bool    -- True where the timestamp was interpolated
    n_frames: int
    measured_fps: float
    monotonic: bool
    scan_seconds: float

    def nearest_index(self, t: float) -> int:
        """Index of the frame whose ACTUAL timestamp is closest to t."""
        return int(np.abs(self.times - t).argmin())

SCAN_STAGE_VERSION = '1.0.0'

def scan_video(video_path, meta: MediaMeta, scene_cfg: SceneConfig) -> FrameScan:
    t0 = time.time()
    size = scene_cfg.thumb_size

    times, indices, thumbs, approx = [], [], [], []
    nominal_fps = meta.r_frame_rate or meta.avg_frame_rate or 30.0
    fallback_dt = 1.0 / nominal_fps
    last_t = 0.0

    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = 'AUTO'          # multithreaded decode; meaningful speedup
        time_base = stream.time_base

        for i, frame in enumerate(container.decode(stream)):
            # ---- the pts fallback ladder ------------------------------------
            is_approx = False
            if frame.pts is not None and time_base is not None:
                t = float(frame.pts * time_base)
            elif getattr(frame, 'time', None) is not None:
                t = float(frame.time)
            else:
                t = last_t + fallback_dt        # last resort: interpolate. FLAG IT.
                is_approx = True

            # ---- cheap thumbnail via swscale --------------------------------
            thumb = frame.reformat(width=size, height=size, format='gray').to_ndarray()

            times.append(t); indices.append(i); thumbs.append(thumb); approx.append(is_approx)
            last_t = t

    if not times:
        raise RuntimeError('DECODE_FAILED: scan produced zero frames')

    times_a = np.asarray(times, dtype=np.float64)
    monotonic = bool(np.all(np.diff(times_a) >= -1e-6))
    if not monotonic:
        # Defensive: some containers emit out-of-order pts. Sort everything together.
        order = np.argsort(times_a, kind='stable')
        times_a = times_a[order]
        indices = [indices[i] for i in order]
        thumbs = [thumbs[i] for i in order]
        approx = [approx[i] for i in order]

    span = float(times_a[-1] - times_a[0])
    measured_fps = (len(times_a) - 1) / span if span > 0 else 0.0

    return FrameScan(
        times=times_a,
        indices=np.asarray(indices, dtype=np.int32),
        thumbs=np.asarray(thumbs, dtype=np.uint8),
        approx_mask=np.asarray(approx, dtype=bool),
        n_frames=len(times_a),
        measured_fps=round(measured_fps, 4),
        monotonic=monotonic,
        scan_seconds=round(time.time() - t0, 3),
    )

def save_scan(path, scan: FrameScan) -> None:
    np.savez_compressed(
        path,
        times=scan.times, indices=scan.indices, thumbs=scan.thumbs,
        approx_mask=scan.approx_mask,
        meta=np.array([scan.n_frames, scan.measured_fps,
                       int(scan.monotonic), scan.scan_seconds], dtype=np.float64),
    )

def load_scan(path) -> FrameScan:
    z = np.load(path)
    m = z['meta']
    return FrameScan(
        times=z['times'], indices=z['indices'], thumbs=z['thumbs'],
        approx_mask=z['approx_mask'],
        n_frames=int(m[0]), measured_fps=float(m[1]),
        monotonic=bool(m[2]), scan_seconds=float(m[3]),
    )


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 104: print('scan.py loaded')
