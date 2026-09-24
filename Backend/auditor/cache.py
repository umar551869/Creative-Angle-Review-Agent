"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 7.
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
def sha256_file(path, chunk_bytes: int = 1024 * 1024) -> str:
    """Content hash of a file. This is the identity of a video."""
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(chunk_bytes)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def canonical_json(obj) -> str:
    """Deterministic serialization: sorted keys, no whitespace drift, stable floats."""
    def default(o):
        if isinstance(o, (np.integer,)):   return int(o)
        if isinstance(o, (np.floating,)):  return round(float(o), 6)
        if isinstance(o, Path):            return str(o)
        if dataclasses.is_dataclass(o):    return asdict(o)
        if isinstance(o, BaseModel):       return o.model_dump()
        return str(o)
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=default)

def stage_key(stage: str, stage_version: str, inputs: list, config: dict) -> str:
    """The cache key. Short prefix is enough -- collisions are not a real risk here."""
    payload = {
        'stage': stage,
        'stage_version': stage_version,
        'pipeline_version': PIPELINE_VERSION,
        'inputs': sorted(inputs),
        'config': config,
    }
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()[:16]

def write_json(path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=2, default=lambda o: json.loads(canonical_json(o)))
    tmp.replace(path)            # atomic-ish: never leave a half-written artifact

def read_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)

def provenance(stage: str, stage_version: str, key: str, duration_s: float, **extra) -> dict:
    """Spec section 45 / 65: what makes any number in any report traceable."""
    p = {
        'stage': stage,
        'stage_version': stage_version,
        'pipeline_version': PIPELINE_VERSION,
        'cache_key': key,
        'duration_seconds': round(duration_s, 4),
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'libraries': {
            'pyav': av.__version__,
            'opencv': cv2.__version__,
            'numpy': np.__version__,
        },
    }
    p.update(extra)
    return p

def video_workdir(video_hash: str) -> Path:
    d = DIRS['artifacts'] / video_hash
    d.mkdir(parents=True, exist_ok=True)
    return d

def free_vram(*objects):
    """Stage isolation. Call between Whisper and OCR (plan.md resource lever 2)."""
    for o in objects:
        try:
            del o
        except Exception:
            pass
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f'  VRAM after free: {torch.cuda.memory_allocated()/1024**2:.0f} MB allocated')
    except Exception:
        pass


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 97: print('cache.py loaded')
