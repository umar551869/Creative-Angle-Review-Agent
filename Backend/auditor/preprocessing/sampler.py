"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 11.
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
# Lower number == higher priority == survives budget enforcement.
REASON_PRIORITY = {'hook_window': 0, 'cta_window': 1, 'scene_change': 2, 'uniform': 3}

@dataclass
class PlanTarget:
    time: float
    reason: str

def global_target_count(duration: float, cfg: SamplerConfig) -> int:
    for lo, hi, count in cfg.duration_tiers:
        if lo <= duration < hi:
            return count
    return cfg.duration_tiers[-1][2]

def make_uniform_targets(duration: float, count: int) -> list:
    """Bin midpoints — deliberately avoids t=0 and t=duration."""
    if duration <= 0 or count <= 0:
        return []
    return [(i + 0.5) * duration / count for i in range(count)]

def make_dense_window(start: float, end: float, interval: float) -> list:
    """Inclusive of `start`; never emits a target beyond `end`."""
    if interval <= 0 or end <= start:
        return []
    out, t = [], start
    # integer stepping avoids float accumulation drift over 20+ steps
    n = int(math.floor((end - start) / interval)) + 1
    for i in range(n):
        t = start + i * interval
        if t <= end + 1e-9:
            out.append(round(t, 6))
    return out

def plan_targets(duration: float,
                 cfg: SamplerConfig,
                 scene_cut_times: Optional[list] = None) -> list:
    """
    Level 1 + Level 2 + Level 3 -> a list of PlanTarget in *requested* time space.
    These are intentions. §8 snaps them to frames that actually exist.
    """
    targets: list = []

    # Level 1 -- global uniform coverage
    n_global = global_target_count(duration, cfg)
    targets += [PlanTarget(t, 'uniform') for t in make_uniform_targets(duration, n_global)]

    # Level 2 -- hook window [0, min(hook_window_s, duration)]
    hook_end = min(cfg.hook_window_s, duration)
    targets += [PlanTarget(t, 'hook_window')
                for t in make_dense_window(0.0, hook_end, cfg.hook_interval_s)]

    # Level 2 -- CTA window [duration - cta_window_s, duration]
    cta_start = max(0.0, duration - cfg.cta_window_s)
    targets += [PlanTarget(t, 'cta_window')
                for t in make_dense_window(cta_start, duration, cfg.cta_interval_s)]

    # Level 3 -- adaptive refinement after each cut
    if cfg.scene_refine and scene_cut_times:
        cuts = list(scene_cut_times)
        if len(cuts) > cfg.max_scene_frames:
            # SPREAD the cap across the video. Taking the first N (`cuts[:N]`)
            # biases every scene frame toward the opening: on a 40-cut video with
            # a cap of 24, the final 40% -- which includes the CTA window, the
            # part a brief most often constrains -- got no scene sampling at all.
            idx = np.linspace(0, len(cuts) - 1, cfg.max_scene_frames).round().astype(int)
            cuts = [cuts[i] for i in sorted(set(idx.tolist()))]
        for t_cut in cuts:
            t = t_cut + cfg.scene_settle_offset_s
            if 0.0 <= t <= duration:
                targets.append(PlanTarget(round(t, 6), 'scene_change'))

    return targets

def enforce_budget(items: list, max_frames: int) -> list:
    """
    Thin by priority: uniform first, then scene_change, and only as a last resort
    decimate the dense critical windows (with the caller warned).

    `items` is a list of dicts each carrying at least 'reason'.
    """
    if len(items) <= max_frames:
        return items

    buckets = {r: [it for it in items if it['reason'] == r] for r in REASON_PRIORITY}
    kept: list = []
    # Walk priority tiers, keeping whole tiers while they fit.
    for reason in sorted(REASON_PRIORITY, key=REASON_PRIORITY.get):
        bucket = buckets[reason]
        room = max_frames - len(kept)
        if room <= 0:
            break
        if len(bucket) <= room:
            kept += bucket
        else:
            # evenly decimate this tier to exactly `room` items
            idx = np.linspace(0, len(bucket) - 1, room).round().astype(int)
            kept += [bucket[i] for i in sorted(set(idx.tolist()))]
    kept.sort(key=lambda it: it['actual_time'] if 'actual_time' in it else it['requested_time'])
    return kept


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 5: SamplingReason = Literal['hook_window', 'cta_window', 'scene_change', 'unifo
#   line 114: print('sampler.py loaded')
