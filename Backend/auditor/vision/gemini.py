"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 68.
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
class GeminiVLMBackend:
    """Hosted vision, shaped exactly like the local VLMBackend."""

    # Vision-capable, free tier, most capable first. flash-lite is last because
    # it is the one that has actually been answering on this key.
    # Measured on a real key, 4 frames each:
    #   gemini-flash-latest        503 UNAVAILABLE (overloaded, intermittent)
    #   gemini-2.0-flash           404 NOT_FOUND   (not enabled on this key)
    #   gemini-flash-lite-latest   OK in 2s        <-- the only one that serves
    #   gemini-2.5-flash           404 NOT_FOUND
    #   gemini-2.0-flash-lite      404 NOT_FOUND
    #
    # ONE model by default, and not because it is the best available. The cache
    # key is built from gemini_models[0], so a ladder whose first entry is not
    # the model that answers produces artifacts filed under a model that never
    # ran -- and nothing downstream can detect that. A reproducible result from a
    # slightly weaker model beats an unreproducible one from a better model.
    #
    # To try the stronger model when capacity returns, put it first and accept
    # that a fallback makes the key approximate (it is flagged -- see generate()):
    #   gemini_models=('gemini-flash-latest', 'gemini-flash-lite-latest')
    DEFAULT_MODELS = ('gemini-flash-lite-latest',)

    # A stalled request is worse than a failed one: it is indistinguishable from
    # a slow one, so you wait. Observed once at 24 minutes in ssl.read() with a
    # request that was never answered. Both bounds are needed -- the per-request
    # timeout catches one stall, the wall-clock budget stops three models times
    # three attempts from quietly adding up to the same half hour.
    REQUEST_TIMEOUT_S = 180
    LADDER_BUDGET_S = 420

    def __init__(self, client, sdk: str, models, where: str, verbose: bool = True):
        self.client, self.sdk, self.models, self.where = client, sdk, list(models), where
        self.verbose = verbose
        self.calls, self.last_tokens, self.last_image_sizes = 0, {}, []
        self.info = {
            'model': f'gemini:{self.models[0]}',
            'model_class': 'GeminiVLMBackend',
            'quantization': 'hosted',      # never 'none' -- this is not fp16 weights
            'dtype': 'hosted',
            'revision': None,
            'attn': 'hosted',
            'provider': 'gemini',
            'models_available': list(self.models),
            'key_from': where,
            'load_seconds': 0.0,
        }

    # ---- messages -> a flat parts list, order preserved ---------------------
    @staticmethod
    def _flatten(messages: list, images: list):
        """
        build_vlm_messages() interleaves [text label][image placeholder] pairs and
        keeps the actual PIL images in a separate list. Walk the content in order
        and consume one image per placeholder, so 'Frame 7 (12.25s):' still
        immediately precedes frame 7 and the model's indices stay meaningful.
        A mismatch here would silently shift every timestamp in the output.
        """
        system, parts, img_i = '', [], 0
        for msg in messages:
            content = msg.get('content') or []
            if msg.get('role') == 'system':
                system = '\n'.join(c.get('text', '') for c in content
                                   if c.get('type') == 'text')
                continue
            for c in content:
                if c.get('type') == 'text':
                    parts.append(('text', c.get('text', '')))
                elif c.get('type') == 'image':
                    if img_i >= len(images):
                        raise RuntimeError(
                            f'message has more image placeholders than images: '
                            f'placeholder {img_i + 1}, only {len(images)} supplied')
                    parts.append(('image', images[img_i]))
                    img_i += 1
        if img_i != len(images):
            raise RuntimeError(f'{len(images)} images supplied but only {img_i} '
                               f'placeholders consumed')
        return system, parts

    @staticmethod
    def _jpeg(im, quality: int = 88) -> bytes:
        buf = io.BytesIO()
        im.convert('RGB').save(buf, format='JPEG', quality=quality)
        return buf.getvalue()

    def _contents(self, parts: list) -> list:
        """SDK-specific: bytes Parts on google-genai, raw PIL on the old SDK."""
        if self.sdk == 'google-genai':
            from google.genai import types as _gt
            out = []
            for kind, val in parts:
                if kind == 'text':
                    out.append(val)
                else:
                    out.append(_gt.Part.from_bytes(data=self._jpeg(val),
                                                   mime_type='image/jpeg'))
            return out
        return [val for _k, val in parts]        # old SDK takes PIL directly

    # ---- the one method the pipeline needs ---------------------------------
    def generate(self, messages: list, images: list, cfg) -> dict:
        system, parts = self._flatten(messages, images)
        contents = self._contents(parts)
        self.last_image_sizes = [im.size for im in (images or [])]
        payload_mb = sum(len(self._jpeg(im)) for im in (images or [])) / 1024 ** 2
        if payload_mb > 18:
            raise RuntimeError(
                f'{len(images)} frames come to {payload_mb:.1f} MB, over the ~20 MB '
                f'inline request limit. Lower max_pixels or max_frames_cap.')

        t0, errors = time.time(), []
        _deadline = t0 + self.LADDER_BUDGET_S
        for model_name in self.models:
            for attempt in range(3):
                if time.time() > _deadline:
                    errors.append(
                        f'gave up after {self.LADDER_BUDGET_S}s across the model '
                        f'ladder ({len(images or [])} frames, '
                        f'{payload_mb:.1f} MB)')
                    break
                try:
                    text, used, capped = self._once(model_name, system, contents, cfg)
                    self.calls += 1
                    if model_name != self.models[0]:
                        # The cache key was built from models[0]. Say so, the way
                        # the local path flags a model fallback -- a key and an
                        # artifact that disagree in silence are worse than either.
                        self.info['planned'] = self.models[0]
                        self.info['fallback'] = True
                        print(f'  NOTE: keyed on {self.models[0]} but '
                              f'{model_name} answered. The artifact records the '
                              f'model that ran.')
                    self.info['model'] = f'gemini:{model_name}'
                    self.last_tokens = {'total_input_tokens': used.get('input')}
                    return {'text': text,
                            'tokens': {'total_input_tokens': used.get('input'),
                                       'generated_tokens': used.get('output'),
                                       'frames_sent': len(images or []),
                                       'payload_mb': round(payload_mb, 2)},
                            'seconds': round(time.time() - t0, 2),
                            'hit_token_cap': bool(capped)}
                except Exception as exc:
                    errors.append(f'{model_name}: {type(exc).__name__}: {str(exc)[:140]}')
                    s = str(exc)
                    transient = any(k in s for k in ('503', 'UNAVAILABLE', '500',
                                                     'INTERNAL', 'DEADLINE',
                                                     # the CLIENT's own clock:
                                                     # httpx says "The read
                                                     # operation timed out",
                                                     # which matched nothing
                                                     # above and killed the
                                                     # stage on attempt 1
                                                     'timed out', 'Timeout',
                                                     'timeout'))
                    unavailable = (('404' in s and 'NOT_FOUND' in s)
                                   or ('429' in s and 'RESOURCE_EXHAUSTED' in s))
                    if transient and attempt < 2:
                        # 503 "facing high demand" is capacity, and it clears
                        # in tens of seconds -- 1s then 2s was a formality.
                        # Jitter: a batch must not retry in lockstep into the
                        # same wall. Bounded by LADDER_BUDGET_S above.
                        wait = 2 ** (attempt + 2) * (1.0 + (time.time() % 1) * 0.5)
                        if self.verbose:
                            print(f'  {model_name}: transient, retrying in '
                                  f'{wait:.0f}s  [{s.strip()[:88]}]')
                        time.sleep(wait)
                        continue
                    if unavailable:
                        if self.verbose:
                            print(f'  {model_name} unusable, trying the next model')
                    break
            if time.time() > _deadline:
                break
        err = RuntimeError(
            f'Every Gemini vision model failed on {len(images or [])} frames '
            f'({payload_mb:.1f} MB) after {time.time() - t0:.0f}s:\n  '
            + '\n  '.join(errors[-4:])
            + '\n  If these are timeouts rather than refusals, the request is '
              'probably too\n  large for this tier. Lower max_frames_cap (24 is '
              'a good next try) or\n  max_pixels, or set VISION_PROVIDER = '
              "'local'.")
        # NOT an OOM: the ladder must not degrade the frame budget over a network
        # or quota failure. Fewer frames would not have helped.
        err.is_oom = False
        raise err

    def _once(self, model_name: str, system: str, contents: list, cfg) -> tuple:
        if self.sdk == 'google-genai':
            r = self.client.models.generate_content(
                model=model_name, contents=contents,
                config={'system_instruction': system,
                        'max_output_tokens': cfg.max_new_tokens,
                        'temperature': 0.0,
                        'response_mime_type': 'application/json'})
        else:
            gm = self.client.GenerativeModel(model_name, system_instruction=system)
            r = gm.generate_content(
                contents,
                generation_config={'max_output_tokens': cfg.max_new_tokens,
                                   'temperature': 0.0,
                                   'response_mime_type': 'application/json'})
        text = getattr(r, 'text', '') or ''
        um = getattr(r, 'usage_metadata', None)
        used = {'input': getattr(um, 'prompt_token_count', 0) if um else 0,
                'output': getattr(um, 'candidates_token_count', 0) if um else 0}
        cands = getattr(r, 'candidates', None) or []
        capped = bool(cands) and 'MAX_TOKENS' in str(getattr(cands[0], 'finish_reason', ''))
        if not text.strip():
            raise RuntimeError(
                f'Gemini returned no text (finish_reason='
                f'{str(getattr(cands[0], "finish_reason", "?")) if cands else "?"}). '
                f'Usually a safety block on the frames. Model was {model_name!r}.')
        return text, used, capped

def _vision_secret(names) -> tuple:
    """
    (value, where). Env first, then Colab secrets.

    Phase 4 defines _get_secret() for the same job, but Phase 4 runs BELOW this
    cell -- Phase 3 borrowing it raises NameError. Delegate when it exists, and
    do the lookup here when it does not. Never returns or prints the key itself,
    only where it was found: cell output is saved with the notebook.
    """
    fn = globals().get('_get_secret')
    if callable(fn):
        return fn(names)
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip(), f'env:{n}'
    try:
        from google.colab import userdata          # noqa
        for n in names:
            try:
                v = userdata.get(n)
                if v and v.strip():
                    return v.strip(), f'colab-secret:{n}'
            except Exception:
                pass
    except Exception:
        pass
    return None, None

def make_gemini_vlm(cfg=None, verbose: bool = True):
    """Build the hosted vision backend, or raise if there is no key."""
    cfg = cfg or P3.vision
    key, where = _vision_secret(['GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                 'GOOGLE_GENAI_API_KEY'])
    if not key:
        raise RuntimeError(
            'No GEMINI_API_KEY, so the hosted vision path cannot run.\n'
            '  The key cell (§37a) is hoisted ABOVE this one in this notebook '
            'precisely\n'
            '  because Phase 3 now needs it -- run it, or add GEMINI_API_KEY as a '
            'Colab\n'
            "  secret (key icon, left sidebar). Or set VISION_PROVIDER = 'local'.")
    try:
        try_install('google-genai', 'google.genai')
        from google import genai
        from google.genai import types as _gt
        # timeout is in MILLISECONDS on this SDK
        client = genai.Client(
            api_key=key,
            http_options=_gt.HttpOptions(
                timeout=GeminiVLMBackend.REQUEST_TIMEOUT_S * 1000))
        sdk = 'google-genai'
    except Exception:
        try_install('google-generativeai', 'google.generativeai')
        import google.generativeai as genai_old
        genai_old.configure(api_key=key)
        client, sdk = genai_old, 'google-generativeai'
    models = list(getattr(cfg, 'gemini_models', None)
                  or GeminiVLMBackend.DEFAULT_MODELS)
    b = GeminiVLMBackend(client, sdk, models, where, verbose=verbose)
    if verbose:
        print(f'  hosted vision: gemini  free tier  models {models}  '
              f'(key from {where})')
    return b

def make_vision_backend(cfg=None, verbose: bool = True):
    """
    Resolve cfg.provider: 'gemini' | 'local' | 'auto'.

    'auto' prefers Gemini when a key is present and falls back to the local VLM,
    because the hosted path has no VRAM ceiling and therefore never degrades the
    frame budget. A fallback is announced, never silent: the artifact records
    which model actually produced the events, and they are not interchangeable.
    """
    cfg = cfg or P3.vision
    want = getattr(cfg, 'provider', 'auto')
    if want not in ('auto', 'gemini', 'local'):
        raise ValueError(f'unknown provider {want!r}; use auto | gemini | local')

    if want in ('auto', 'gemini'):
        try:
            return make_gemini_vlm(cfg, verbose=verbose)
        except Exception as exc:
            # NO SILENT FALL BACK TO QWEN in this notebook.
            #
            # Falling back would load several GB of weights, demand a GPU this
            # runtime may not have, and produce evidence from a DIFFERENT model
            # under a cache key that names the hosted one. A hosted run that
            # cannot reach its model should stop and say so.
            raise RuntimeError(
                f'Hosted vision is unavailable: {str(exc)[:150]}\n'
                '  This notebook is hosted-only. It does NOT fall back to the\n'
                '  local VLM, because that would need a GPU and would file\n'
                "  Qwen's evidence under Gemini's cache key.\n"
                '  For the local vision stage use '
                'phases_1_to_6_full_pipeline.ipynb.') from exc

    # provider == 'local' -- explicit, and only in the local notebook
    return load_vlm(cfg, verbose=verbose)

# ---------------------------------------------------------------------------
# Which hosted VISION model is serving right now
#
# Phase 3 sends 19-42 frames per video. Running that through a model measured
# at 25 seconds for a one-word text reply is the single most expensive stale
# default in the notebook.
#
# The probe sends a real IMAGE and requires JSON back, because that is what
# the stage actually needs -- a model that merely answers text would pass a
# text probe and then fail on the first real frame batch.
# ---------------------------------------------------------------------------
PIN_VISION_MODEL = None          # set a name to skip the probe and fix the key

VISION_PROBE_CANDIDATES = (
    'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-flash-lite-latest',
    'gemini-3.1-flash-lite', 'gemini-3.8-flash',
)

VISION_PROBE_TIMEOUT_S = 30

_VISION_PROBE_CACHE = {}

VISION_PROBE_MAX = 8             # ceiling on models probed in ONE parallel

                                 # burst -- see discover_vision_models()
# Plain re.compile, NOT __import__('re').compile: the Backend extractor keeps
# a module-level constant only when its value is a literal or a call to a
# recognised builder, so the __import__ form was dropped as a driver and
# auditor/vision/gemini.py failed to load with a NameError.
_NOT_VISION_RE = re.compile(
    # not generative text at all
    r'embedding|aqa|'
    # generates PIXELS or AUDIO, does not read them
    r'imagen|veo|lyria|nano-banana|-image$|-image-|'
    r'-tts|text-to-speech|native-audio|-audio-|transcribe|'
    # agents and control surfaces, not one generate call
    r'deep-research|antigravity|robotics|computer-use|live-|'
    # separate families with their own API shape
    r'learnlm|gemma',
    re.I)

def _vision_model_rank(name: str) -> tuple:
    """Cheap and fast first. flash-lite < flash < pro, newer before older."""
    import re as _re
    n = name.lower()
    family = 0 if 'flash-lite' in n else 1 if 'flash' in n else 2
    v = _re.search(r'(\d+)\.(\d+)', n)
    major, minor = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
    alias = 0 if 'latest' in n else 1
    preview = 1 if ('preview' in n or 'exp' in n) else 0
    return (family, preview, -major, -minor, alias, n)

def discover_vision_models(limit: int = None, verbose: bool = True) -> list:
    """Model names THIS key can actually see, plausible for vision, ranked.

    Returns [] when the listing cannot be had, so the caller falls back to
    VISION_PROBE_CANDIDATES rather than ending up with no candidates at all.
    Never raises.
    """
    limit = int(limit or VISION_PROBE_MAX)
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        return []
    try:
        from google import genai
        client = genai.Client(api_key=key)
        try:
            # query_base asks for base models rather than tuned ones; older
            # SDKs do not know the argument, so fall back instead of failing.
            listing = list(client.models.list(config={'query_base': True}))
        except Exception:
            listing = list(client.models.list())
    except Exception as exc:
        if verbose:
            print(f'  models.list() unavailable ({type(exc).__name__}) -- '
                  f'using the built-in candidate list')
            _v = globals().get('key_failure_verdict')
            if callable(_v):
                _m = _v([str(exc)])
                if _m:
                    print(f'    -> {_m}')
        return []

    keep, nogen, novis = [], 0, 0
    for m in listing:
        name = str(getattr(m, 'name', '') or '').replace('models/', '')
        if not name:
            continue
        acts = (getattr(m, 'supported_actions', None)
                or getattr(m, 'supported_generation_methods', None) or [])
        # The SDK renamed this field; accept either spelling, and treat an
        # empty list as "unknown", not as "no".
        can_gen = (not acts) or any(
            str(a).lower().replace('_', '') == 'generatecontent' for a in acts)
        if not can_gen:
            nogen += 1
        elif _NOT_VISION_RE.search(name):
            novis += 1
        else:
            keep.append(name)
    keep.sort(key=_vision_model_rank)
    if verbose:
        print(f'  models.list(): {len(listing)} visible, {nogen} cannot '
              f'generate, {novis} not image->text, {len(keep)} candidate(s)')
        if len(keep) > limit:
            print(f'    probing the {limit} cheapest -- a bigger parallel '
                  f'burst rate-limits the probe itself')
    return keep[:limit]

def probe_vision_models(candidates=None, timeout_s: float = None,
                        verbose: bool = True) -> list:
    """[(seconds, model)] that described an IMAGE and returned JSON, best first.

    Parallel, and never raises: a probe that cannot run must leave the
    configured model in place rather than stop the pipeline.
    """
    import concurrent.futures as _cf
    import time as _t
    # ASK, then guess. A hand-maintained name list goes stale in one
    # direction -- Google retires a name and the ladder silently shortens --
    # and listing costs no tokens, so it is also the cheapest key test there
    # is. Falls back to the built-in tuple whenever the listing cannot be had.
    if not candidates:
        _found = discover_vision_models(verbose=verbose)
        candidates = tuple(_found or VISION_PROBE_CANDIDATES)
    else:
        candidates = tuple(candidates)
    timeout_s = float(timeout_s or VISION_PROBE_TIMEOUT_S)
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        if verbose:
            print('  no Gemini key -- skipping the vision probe')
        return []
    try:
        _ti = globals().get('try_install')
        if callable(_ti):
            _ti('google-genai', 'google.genai')
        from google import genai
        from google.genai import types as _gt
        from PIL import Image as _Image
        client = genai.Client(api_key=key, http_options=_gt.HttpOptions(
            timeout=int(timeout_s * 1000)))
    except Exception as exc:
        if verbose:
            print(f'  vision probe unavailable ({type(exc).__name__}) -- '
                  f'keeping the configured model')
        return []

    # REPRESENTATIVE, not minimal. One 64x64 square told us gemini-3.5-flash
    # was fast; 16 real frames then timed out at 180s. Four frames at roughly
    # a real frame's size measure something that predicts the real request.
    _img = [_Image.new('RGB', (256, 448),
                       (40 + 50 * _k, 90, 200 - 40 * _k)) for _k in range(4)]
    _NPROBE = len(_img)

    def _one(name):
        t0 = _t.time()
        try:
            r = client.models.generate_content(
                model=name,
                contents=_img + ['Reply with JSON: {"n": <how many images>}'],
                # the same shape _once() uses, so passing here means passing there
                config={'system_instruction': 'You describe images.',
                        # generous: a 3.x model may spend tokens thinking, and
                        # an empty reply would look like a failure it is not
                        'max_output_tokens': 256,
                        'temperature': 0.0,
                        'response_mime_type': 'application/json'})
            txt = (getattr(r, 'text', '') or '').strip()
            if not txt:
                raise RuntimeError('empty response (no text returned)')
            return name, _t.time() - t0, txt[:32], None
        except Exception as exc:
            return name, _t.time() - t0, None, f'{type(exc).__name__}: {str(exc)[:70]}'

    out, _errs, _soft = [], [], []
    with _cf.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        for name, dt, text, err in ex.map(_one, candidates):
            if err is None:
                out.append((dt, name))
                if verbose:
                    # per-frame is the number that predicts a 16-frame call
                    print(f'    OK    {name:26} {dt:5.1f}s '
                          f'({dt / max(1, _NPROBE):4.1f}s/frame '
                          f'-> ~{dt / max(1, _NPROBE) * 16:5.0f}s for 16)'
                          f'  {text!r}')
            else:
                _errs.append(err)
                # BUSY NOW IS NOT DEAD FOREVER. A 503/504 here is the same
                # momentary overload the stage itself retries through, so it
                # demotes the model instead of deleting it.
                if any(k in err for k in ('503', '504', 'UNAVAILABLE',
                                          'DEADLINE', 'INTERNAL', '500')):
                    _soft.append(name)
                if verbose:
                    print(f'    fail  {name:26} {err}')
    if not out and verbose:
        # Nothing answered. Say WHICH failure this is -- rotate, wait, or
        # retry are three different actions and the raw errors bury the answer.
        _vf = globals().get('key_failure_verdict')
        _msg = _vf(_errs) if callable(_vf) else ''
        if _msg:
            print(f'    -> {_msg}')
    out.sort()
    # Demoted models go BEHIND every measured one. float('inf') keeps them
    # last without pretending we timed them, and only when something answered:
    # with no measurement at all, leading with a model that just failed its
    # own probe is a guess wearing a measurement's clothes.
    if out and _soft:
        if verbose:
            print(f'    (demoted, not dropped -- retried only if the '
                  f'faster ones are busy: {", ".join(_soft)})')
        out = out + [(float('inf'), n) for n in _soft]
    return out

def autoselect_vision_model(cfg=None, verbose: bool = True):
    """VisionConfig using the fastest model that really described an image."""
    import dataclasses as _dc
    cfg = cfg or P3.vision
    if getattr(cfg, 'provider', 'gemini') == 'local':
        return cfg
    current = (getattr(cfg, 'gemini_models', None) or ('',))[0]
    if PIN_VISION_MODEL:
        # A PIN is an ORDER, not a restriction. Returning a 1-tuple here would
        # restore the exact bug fix 58 removed: the ladder reaches "unusable,
        # trying the next model" and there is no next model, so one 503 kills
        # the video. The pin leads (and so remains the cache key); everything
        # else follows as a fallback that costs nothing until it is needed.
        _pin = ((PIN_VISION_MODEL,) if isinstance(PIN_VISION_MODEL, str)
                else tuple(PIN_VISION_MODEL))
        _rest = tuple(m for m in VISION_PROBE_CANDIDATES if m not in _pin)
        if verbose:
            print(f'  vision model PINNED to {_pin[0]} (no probe)')
            if _pin[1:] + _rest:
                print(f'  fallbacks if it is overloaded: '
                      f'{", ".join(_pin[1:] + _rest)}')
        return _dc.replace(cfg, gemini_models=_pin + _rest)
    if 'ranked' not in _VISION_PROBE_CACHE:
        if verbose:
            print('  probing hosted VISION models (image + JSON, parallel):')
        _VISION_PROBE_CACHE['ranked'] = probe_vision_models(verbose=verbose)
    ranked = _VISION_PROBE_CACHE['ranked']
    if not ranked:
        if verbose:
            print(f'  nothing described an image -- keeping {current}')
        return cfg
    # KEEP EVERY MODEL THAT ANSWERED, fastest first -- not just the winner.
    # A 1-tuple deleted the fallbacks, so one 503 "facing high demand" killed
    # the stage with four other probed models sitting unused. ranked[0] stays
    # first, so the visual CACHE KEY is unchanged.
    _ladder = tuple(n for _, n in ranked)
    winner = ranked[0][1]
    if winner == current:
        if verbose:
            print(f'  vision model -> {winner} ({ranked[0][0]:.1f}s), unchanged; '
                  f'existing visual artifacts stay valid')
            if len(_ladder) > 1:
                print(f'  fallbacks if it is overloaded: '
                      f'{", ".join(_ladder[1:])}')
        return _dc.replace(cfg, gemini_models=_ladder)
    if verbose:
        print(f'  vision model -> {winner}  ({ranked[0][0]:.1f}s, was {current})')
        print('  NOTE: gemini_models[0] IS the visual cache key, so this '
              're-runs the vision pass')
        print('        for every video. Set PIN_VISION_MODEL to keep the '
              'existing artifacts.')
        if len(_ladder) > 1:
            print(f'  fallbacks if it is overloaded: {", ".join(_ladder[1:])}')
    return _dc.replace(cfg, gemini_models=_ladder)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 343: print('§26b gemini.py loaded.  make_vision_backend(P3.vision) -> hosted or l
#   line 622: P3 = dataclasses.replace(P3, vision=autoselect_vision_model(P3.vision))
