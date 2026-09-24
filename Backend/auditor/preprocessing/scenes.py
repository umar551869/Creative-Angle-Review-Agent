"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 14.
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
class SceneAnalysis:
    cut_times: list            # seconds, at the FIRST frame of each new shot
    cut_indices: list          # scan indices
    deltas: np.ndarray         # (N-1,) raw mean-abs-difference signal
    threshold: float           # the effective delta threshold used
    blank_indices: list        # scan indices of flat/blank frames
    n_shots: int

def detect_scenes(scan: FrameScan, cfg: SceneConfig) -> SceneAnalysis:
    thumbs = scan.thumbs.astype(np.int16)
    if scan.n_frames < 2:
        return SceneAnalysis([], [], np.zeros(0), 0.0, [], 1)

    # ---- change signal ------------------------------------------------------
    deltas = np.abs(np.diff(thumbs, axis=0)).mean(axis=(1, 2))     # (N-1,)

    # ---- robust threshold (median + MAD, NOT mean + sigma) ------------------
    med = float(np.median(deltas))
    mad = float(np.median(np.abs(deltas - med)))
    scale = 1.4826 * mad
    if scale < 1e-6:
        # Perfectly static video: MAD collapses. Fall back to the absolute floor.
        threshold = max(cfg.min_absolute_delta, med + 10.0)
    else:
        threshold = max(cfg.min_absolute_delta, med + cfg.robust_z_threshold * scale)

    candidates = np.nonzero(deltas > threshold)[0] + 1    # +1 -> first frame of new shot

    # ---- refractory period: suppress double-triggers on one cut -------------
    cut_indices, cut_times = [], []
    last_cut_time = -1e9
    for idx in candidates:
        t = float(scan.times[idx])
        if t - last_cut_time >= cfg.min_shot_duration_s:
            cut_indices.append(int(idx))
            cut_times.append(round(t, 4))
            last_cut_time = t

    # ---- blank / flat frame detection ---------------------------------------
    stds = scan.thumbs.reshape(scan.n_frames, -1).std(axis=1)
    blank_indices = np.nonzero(stds < cfg.blank_std_threshold)[0].tolist()

    return SceneAnalysis(
        cut_times=cut_times,
        cut_indices=cut_indices,
        deltas=deltas,
        threshold=round(threshold, 4),
        blank_indices=[int(i) for i in blank_indices],
        n_shots=len(cut_times) + 1,
    )


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 59: print('scenes.py loaded')
