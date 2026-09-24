"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 66.
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
class VLMBackend:
    """Wraps model + processor. The ONLY thing the pipeline needs is .generate()."""

    def __init__(self, model, processor, info: dict):
        self.model, self.processor, self.info = model, processor, info

    def generate(self, messages: list, images: list, cfg: VisionConfig) -> dict:
        """Returns {'text', 'tokens', 'seconds'}. Raises only on genuine failure."""
        proc = self.processor
        text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = proc(text=[text], images=images if images else None,
                      return_tensors='pt', padding=True)
        inputs = {k: (v.to(self.model.device) if hasattr(v, 'to') else v)
                  for k, v in inputs.items()}
        tokens = measure_input_tokens(inputs)
        # Stash it on the backend BEFORE generating. If generation dies, the token
        # count is the single most diagnostic number available -- and returning it
        # only on success means it vanishes exactly when it is needed.
        self.last_tokens = tokens
        self.last_image_sizes = [im.size for im in (images or [])]

        t0 = time.time()
        try:
            with torch.inference_mode():
                out = self.model.generate(**inputs, max_new_tokens=cfg.max_new_tokens,
                                          do_sample=cfg.do_sample)
        except Exception as exc:
            n_tok = tokens.get('total_input_tokens')
            sizes = sorted({im.size for im in (images or [])})
            free_gb = (torch.cuda.mem_get_info()[0] / 1024 ** 3
                       if torch.cuda.is_available() else 0.0)
            hint = ''
            if n_tok and n_tok > 12000:
                hint = (f' The input is {n_tok} tokens, which is far too many -- the '
                        f'pixel budget is not being applied. Image sizes seen: {sizes}. '
                        f'Expected ~{cfg.max_pixels // 784} tokens per frame.')
            elif 'out of memory' in str(exc).lower():
                hint = (f' Only {free_gb:.1f} GB was free. Lower P3.vision.max_frames '
                        f'or max_pixels, or use 4-bit.')
            err = RuntimeError(
                f'{type(exc).__name__} during generate(): {len(images or [])} images, '
                f'{n_tok} input tokens, {free_gb:.1f} GB VRAM free.{hint} '
                f'Original: {str(exc)[:200]}')
            # Marked so the caller can DEGRADE (fewer frames) instead of failing.
            # Checked by type, not by string: an OOM message is not a stable API.
            err.is_oom = isinstance(exc, torch.cuda.OutOfMemoryError) or \
                'out of memory' in str(exc).lower()
            # Drop this attempt's GPU tensors BEFORE raising.
            #
            # `raise err from exc` keeps exc.__traceback__ alive, and that
            # traceback references THIS frame -- which still holds `inputs`,
            # the pixel tensors. Each OOM'd rung then pins its own activations,
            # so the next rung starts with less memory than the last and a
            # ladder that should converge OOMs at every step instead.
            #
            # load_vlm() already applies exactly this fix to a failed model
            # load; the generate path was missed. The message above already
            # embeds str(exc), so chaining adds nothing but the leak.
            inputs = None
            exc.__traceback__ = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            raise err
        seconds = time.time() - t0

        in_len = inputs['input_ids'].shape[-1]
        trimmed = out[:, in_len:]
        decoded = proc.batch_decode(trimmed, skip_special_tokens=True)[0]
        n_new = int(trimmed.shape[-1])
        return {'text': decoded, 'tokens': {**tokens, 'generated_tokens': n_new},
                'seconds': round(seconds, 2),
                'hit_token_cap': n_new >= cfg.max_new_tokens}

# Resident cost of weights plus the ~0.6 GB CUDA context. fp16 is 2 bytes per
# parameter; nf4 with double-quant is ~0.6 bytes, plus an un-quantised vision
# tower and embedding table -- which is why 4-bit is not simply a quarter of fp16.
VLM_WEIGHTS_GB = {
    ('Qwen/Qwen3-VL-8B-Instruct',   'none'): 17.0,
    ('Qwen/Qwen3-VL-8B-Instruct',   '4bit'):  6.0,
    ('Qwen/Qwen3-VL-4B-Instruct',   'none'):  9.0,
    ('Qwen/Qwen3-VL-4B-Instruct',   '4bit'):  3.4,
    ('Qwen/Qwen2.5-VL-3B-Instruct', 'none'):  7.2,
    ('Qwen/Qwen2.5-VL-3B-Instruct', '4bit'):  2.8,
}

# Most capable first. An 8B at nf4 beats a 4B at fp16 on description quality:
# quantisation costs less than halving the parameter count.
VLM_CAPABILITY_ORDER = [
    ('Qwen/Qwen3-VL-8B-Instruct',   'none'),
    ('Qwen/Qwen3-VL-8B-Instruct',   '4bit'),
    ('Qwen/Qwen3-VL-4B-Instruct',   'none'),
    ('Qwen/Qwen3-VL-4B-Instruct',   '4bit'),
    ('Qwen/Qwen2.5-VL-3B-Instruct', 'none'),
    ('Qwen/Qwen2.5-VL-3B-Instruct', '4bit'),
]

def affordable_frames(total_gb: float, weights_gb: float, px_per_frame: int,
                      cfg: VisionConfig) -> int:
    """How many frames fit ALONGSIDE these weights, at this resolution."""
    headroom = total_gb - weights_gb - cfg.vram_safety_gb
    if headroom <= 0:
        return 0
    per_frame = max(1.0, max(1, px_per_frame) / 784)
    return int(headroom * cfg.activation_tokens_per_gb / per_frame)

def plan_vlm_load(cfg: VisionConfig, total_gb: float = None,
                  verbose: bool = False) -> list:
    """
    (model_id, quantization) candidates, best first, chosen for THIS card.

    Weights and activations compete for the same VRAM, so they have to be chosen
    together. The old rule picked the largest model whose WEIGHTS fit and let the
    OOM ladder discover there was no room left for frames: on a 15 GB T4 that
    meant Qwen3-VL-4B in fp16 (~9 GB resident) and an 84s video degraded from 48
    frames to 12 -- one frame every 7 seconds -- which made visual_only,
    visual_and_speech and `any` unable to support a FAIL at all. Losing a whole
    evidence modality is a far worse outcome than running the same model at nf4.

    So: pick the most capable model that still affords the FULL frame budget at
    the ladder's working resolution (half of max_pixels, because the ladder gives
    up resolution before coverage by design). Every other candidate stays in the
    list as a fallback ordered by what it affords, so a wrong estimate costs a
    retry rather than a failure -- and the OOM ladder is still underneath it all.

    total_gb is TOTAL VRAM, a stable property of the card. That is deliberate and
    is not the thing the cache key must never see: free VRAM fluctuates run to
    run, total VRAM does not, and it genuinely decides which weights produced the
    evidence.
    """
    # A hosted run is keyed on the hosted model. Without this the cache key would
    # name a Qwen build that never ran, and a local re-run would collide with a
    # Gemini artifact -- the exact collision the resolved model was added to
    # prevent. 'auto' keeps the local keys, because which one wins is not known
    # until load time; set provider='gemini' explicitly for a stable key.
    if getattr(cfg, 'provider', 'auto') == 'gemini':
        # The fallback must match VisionConfig.gemini_models, not a model
        # measured at 503. Whatever this returns goes into the visual
        # cache key, so a wrong name files the artifact under a model
        # that never ran -- the exact collision 1.11.0 added it to stop.
        _gm = (getattr(cfg, 'gemini_models', None)
               or ('gemini-flash-lite-latest',))[0]
        return [(f'gemini:{_gm}', 'hosted')]

    if cfg.model_id:
        # an explicit pin still gets the 4-bit retry, unless quantization was pinned too
        if cfg.quantization:
            return [(cfg.model_id, cfg.quantization)]
        return [(cfg.model_id, 'none'), (cfg.model_id, '4bit')]

    total = P3_GPU_GB if total_gb is None else total_gb
    want = cfg.max_frames_cap
    px = max(cfg.min_pixels, int(cfg.max_pixels * 0.5) // 784 * 784)

    scored = [(c, affordable_frames(total, w, px, cfg))
              for c, w in ((c, VLM_WEIGHTS_GB[c]) for c in VLM_CAPABILITY_ORDER)]
    full = [x for x in scored if x[1] >= want * cfg.coverage_tolerance]
    if full:
        best = full[0]                      # already in capability order
        rest = [x for x in scored if x[0] != best[0]]
        rest.sort(key=lambda x: (-min(x[1], want), VLM_CAPABILITY_ORDER.index(x[0])))
        ordered = [best] + rest
    else:
        # Nothing affords full coverage. Maximise frames -- but do not trade a
        # materially better model for a couple of frames. Anything within
        # coverage_tolerance of the BEST ACHIEVABLE counts as tied, and among
        # ties the more capable model wins: on a T4 the 3B at nf4 affords 37
        # frames and the 4B affords 34, and 34 frames described by the 4B is
        # the better audit.
        _best = max((f for _c, f in scored), default=0)
        _floor = _best * cfg.coverage_tolerance
        _tied = sorted([x for x in scored if x[1] >= _floor],
                       key=lambda x: VLM_CAPABILITY_ORDER.index(x[0]))
        _rest = sorted([x for x in scored if x[1] < _floor],
                       key=lambda x: (-x[1], VLM_CAPABILITY_ORDER.index(x[0])))
        ordered = _tied + _rest

    if verbose:
        print(f'  VLM plan for {total:.1f} GB  (want {want} frames @ {px}px)')
        for (mid, q), f in ordered:
            mark = '  <-- chosen' if (mid, q) == ordered[0][0] else ''
            print(f'    {mid.split("/")[-1]:<24} {q:<5} '
                  f'weights~{VLM_WEIGHTS_GB[(mid, q)]:>4.1f}GB  '
                  f'affords {f:>3} frames{mark}')

    if cfg.quantization:
        # An explicit quantization choice must hold across the AUTO ladder too.
        # Honouring it only when model_id is also pinned means setting 4-bit on
        # its own silently keeps loading fp16 -- you watch it OOM again and
        # conclude 4-bit does not help, when it was never tried.
        seen, out = set(), []
        for (mid, _q), _f in ordered:
            if mid not in seen:
                seen.add(mid)
                out.append((mid, cfg.quantization))
        return out
    return [c for c, _f in ordered]

def _pick_model_class(model_id: str):
    """Prefer the model-specific class; fall back to a generic Auto class."""
    low = model_id.lower()
    order = []
    if 'qwen3-vl' in low:
        order = ['Qwen3VLForConditionalGeneration', 'AutoModelForImageTextToText',
                 'AutoModelForVision2Seq']
    elif 'qwen2.5-vl' in low or 'qwen2_5' in low:
        order = ['Qwen2_5_VLForConditionalGeneration', 'AutoModelForImageTextToText',
                 'AutoModelForVision2Seq']
    else:
        order = ['AutoModelForImageTextToText', 'AutoModelForVision2Seq']
    for name in order:
        if name in VLM_CLASSES:
            return name, VLM_CLASSES[name]
    return None, None

def load_vlm(cfg: VisionConfig = None, verbose: bool = True) -> VLMBackend:
    """
    First candidate that loads AND survives a smoke generation wins.

    Loading can succeed while generation fails (a missing quantization kernel, an
    unsupported dtype), so the smoke test is what actually proves the path -- the
    same lesson as faster-whisper's cuDNN failures in Phase 2.
    """
    cfg = cfg or P3.vision
    assert torch.cuda.is_available(), (
        'Phase 3 needs a GPU. Switch to a T4 runtime. '
        '(§28b runs the whole test suite without one.)')

    # ---- make this function IDEMPOTENT ---------------------------------------
    # Running this cell twice is the single most common way to OOM here: the
    # first model is still resident, so the second load has ~0 GB to work with
    # and fails with "tried to allocate 48 MiB" -- which reads like "the model
    # is too big for this GPU" and is nothing of the sort. Drop any VLM we
    # already hold before asking for another.
    for _n in ('vlm', '_backend', 'backend'):
        _obj = globals().get(_n)
        if _obj is not None and hasattr(_obj, 'model'):
            if verbose:
                print(f'  dropping a VLM already held in `{_n}` before loading')
            _obj.model = None
            _obj.processor = None
            globals()[_n] = None
    gc.collect(); torch.cuda.empty_cache()

    _free_gb = torch.cuda.mem_get_info()[0] / 1024 ** 3
    if verbose:
        print(f'  VRAM free before load: {_free_gb:.1f} GB of {P3_GPU_GB:.1f} GB')
    if _free_gb < 6.0:
        print(f'\n  WARNING: only {_free_gb:.1f} GB free. Something else still holds this GPU.')
        print('  An fp16 load will fail here and the error will LOOK like a size problem.')
        print('  Usual culprits, in order:')
        print('    - a VLM from an earlier run of this cell (handled above, unless')
        print('      you stored it under another name)')
        print('    - Phase 2 Whisper: run  asr_model = None; free_vram()')
        print('    - a dead cell that raised mid-load, leaving partial weights resident')
        print('  If none apply: Runtime > Restart, then re-run Phase 1+2 (they cache,')
        print('  so it is fast) and come straight back here.\n')

    from transformers import AutoProcessor
    major = torch.cuda.get_device_properties(0).major
    dtype = torch.bfloat16 if major >= 8 else torch.float16   # sm_75 is fp16-only
    errors = []

    _plan = plan_vlm_load(cfg, verbose=verbose)
    if verbose:
        _px = max(cfg.min_pixels, int(cfg.max_pixels * 0.5) // 784 * 784)
        _best = affordable_frames(P3_GPU_GB, VLM_WEIGHTS_GB.get(_plan[0], 0.0),
                                  _px, cfg) if _plan[0] in VLM_WEIGHTS_GB else 0
        if _best >= cfg.max_frames_cap * cfg.coverage_tolerance:
            print(f'  this card affords the FULL {cfg.max_frames_cap}-frame budget '
                  f'(~{_best} frames @ {_px}px) -- no degradation expected')
        else:
            print(f'  WARNING: the best fit affords ~{_best} frames of the '
                  f'{cfg.max_frames_cap} the budget wants. Visual evidence will be '
                  f'thin and `can_fail_on` may drop visual_only / '
                  f'visual_and_speech / any to UNCERTAIN.')

    for model_id, quant in _plan:
        cls_name, cls = _pick_model_class(model_id)
        if cls is None:
            errors.append(f'{model_id}: no usable model class in this transformers')
            continue
        t0 = time.time()
        try:
            if verbose:
                print(f'trying {model_id}  [{cls_name}, {quant}, {str(dtype).split(".")[-1]}]…')
            kwargs = dict(torch_dtype=dtype, low_cpu_mem_usage=True,
                          attn_implementation=cfg.attn_implementation)
            if cfg.revision:
                kwargs['revision'] = cfg.revision
            if quant == '4bit':
                from transformers import BitsAndBytesConfig
                kwargs['quantization_config'] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type='nf4',
                    bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
                kwargs['device_map'] = {'': 0}
            else:
                kwargs['device_map'] = {'': 0}      # explicit, never 'auto'

            model = cls.from_pretrained(model_id, **kwargs)
            model.eval()
            proc_kwargs = {}
            if cfg.revision:
                proc_kwargs['revision'] = cfg.revision
            processor = AutoProcessor.from_pretrained(model_id, **proc_kwargs)

            # pixel budget: the single most effective OOM guard
            for attr_holder in (getattr(processor, 'image_processor', None), processor):
                if attr_holder is None:
                    continue
                for attr, val in (('min_pixels', cfg.min_pixels), ('max_pixels', cfg.max_pixels)):
                    if hasattr(attr_holder, attr):
                        try:
                            setattr(attr_holder, attr, val)
                        except Exception:
                            pass

            backend = VLMBackend(model, processor, {
                'model': model_id, 'model_class': cls_name, 'quantization': quant,
                'dtype': str(dtype).split('.')[-1], 'revision': cfg.revision,
                'attn': cfg.attn_implementation,
                'load_seconds': round(time.time() - t0, 1),
            })

            # ---- smoke generation: 2 tiny frames, a few tokens ----------------
            probe = [Image.new('RGB', (224, 224), (40, 40, 40)) for _ in range(2)]
            probe_table = [{'index': i, 'timestamp': float(i), 'frame_id': f'p{i}',
                            'reason': 'uniform', 'is_approximate_ts': False}
                           for i in range(2)]
            smoke_cfg = dataclasses.replace(cfg, max_new_tokens=16)
            _ = backend.generate(build_vlm_messages(probe_table, '', smoke_cfg),
                                 probe, smoke_cfg)

            if (model_id, quant) != _plan[0]:
                # The cache key was computed from _plan[0]. Say so loudly, and
                # record it, rather than filing these weights under that key in
                # silence.
                backend.info['planned'] = list(_plan[0])
                backend.info['fallback'] = True
                print(f'  NOTE: planned {_plan[0][0].split("/")[-1]} [{_plan[0][1]}] '
                      f'but loaded {model_id.split("/")[-1]} [{quant}]. '
                      f'The artifact records what actually ran.')
            if verbose:
                alloc = torch.cuda.memory_allocated() / 1024 ** 3
                print(f'VLM ready: {model_id} [{quant}] on cuda:0  '
                      f'({backend.info["load_seconds"]}s, {alloc:.1f} GB allocated)')
            return backend

        except Exception as exc:
            errors.append(f'{model_id}[{quant}]: {type(exc).__name__}: {str(exc)[:160]}')
            if verbose:
                print(f'  failed -> {type(exc).__name__}: {str(exc)[:120]}')
            # A load that died partway through still holds every shard it had
            # already placed. Two things keep those alive, and BOTH must go or
            # candidate 2 OOMs on candidate 1's corpse -- which reads as "the
            # smaller model doesn't fit either" and sends you debugging the
            # wrong thing entirely:
            #   1. the local name
            #   2. the exception's traceback, which references the frames that
            #      reference the partially built model
            exc.__traceback__ = None
            model = processor = backend = None
            gc.collect(); torch.cuda.empty_cache()
            if verbose:
                print(f'     VRAM free after cleanup: '
                      f'{torch.cuda.mem_get_info()[0] / 1024 ** 3:.1f} GB')

    raise RuntimeError('No vision-language model could be loaded.\n  ' + '\n  '.join(errors))

def free_vlm(backend):
    """Delete the model and empty the cache. Skipping this OOMs a batch run."""
    try:
        if backend is not None:
            backend.model = None
            backend.processor = None
    except Exception:
        pass
    free_vram()


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 391: print('qwen.py loaded')
