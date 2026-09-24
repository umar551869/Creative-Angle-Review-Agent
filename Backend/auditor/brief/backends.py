"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 96.
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
class BriefBackend:
    """All a compiler needs is complete(). Everything else is the same downstream."""
    name = 'base'
    kind = 'base'

    def complete(self, system: str, user: str, cfg: BriefConfig) -> dict:
        raise NotImplementedError

def _get_secret(names) -> tuple:
    """(value, where). Reads env then Colab secrets. NEVER prints or returns a key
    anywhere it could be logged -- only the location it was found."""
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

class BudgetExhausted(RuntimeError):
    """The billable-request cap for one compile was reached. Never auto-retried."""

class HostedLLMBackend(BriefBackend):
    """
    A provider ladder: Gemini (free tier) first, OpenAI (paid) only after it is
    exhausted, and every billable request counted against a hard cap.

    NOTHING happens without a key: each provider's import and install live
    inside the branch that found one. No keys means no network at all, and
    make_brief_backend() falls through to the local or rule-based backend.

    What leaves the machine when a key IS set: the brief text, and only the
    brief text. No video, frames, transcript or OCR ever reaches this class.

    Spend control, because the paid provider is real money:
      * one call per brief, cached forever by brief hash -- a re-run costs zero
      * OpenAI is reached only after Gemini's whole model ladder has failed
      * paid_call_budget caps BILLABLE requests per compile across all providers
      * transient (503) retries are free on Gemini and NOT repeated on OpenAI
      * the §47 test suite never constructs this class
    """
    kind = 'hosted'

    GEMINI_KEYS = ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_API_KEY']
    OPENAI_KEYS = ['OPENAI_API_KEY', 'OPEN_AI_API_KEY']

    # A client built without http_options has NO timeout: httpcore waits forever
    # on a response that never comes. Seen twice, both times sitting in
    # ssl.read() -- once for 24 minutes. Consensus multiplies the exposure, since
    # one compile becomes three requests, and an interrupt throws away the runs
    # that already succeeded. A stall must become an exception the retry ladder
    # can act on, not an indefinite wait.
    REQUEST_TIMEOUT_S = 120

    def __init__(self, cfg: BriefConfig, verbose: bool = True):
        self.providers, self.paid_calls, self.spend_log = [], 0, []
        self.verbose = verbose

        gk, gwhere = _get_secret(self.GEMINI_KEYS)
        if gk:
            self.providers.append(self._make_gemini(gk, gwhere, cfg))
        ok, owhere = _get_secret(self.OPENAI_KEYS)
        if ok and cfg.allow_paid_fallback:
            self.providers.append(self._make_openai(ok, owhere, cfg))

        if not self.providers:
            raise RuntimeError(
                'No hosted API key.\n'
                '  Add GEMINI_API_KEY (free tier: https://aistudio.google.com/apikey)\n'
                '  or OPENAI_API_KEY as a Colab secret -- key icon, left sidebar.\n'
                '  Or use backend="local" (reuses the Phase 3 VLM) / "rules" '
                '(no model at all).')

        self.provider = self.providers[0]['kind']
        self.model = self.providers[0]['models'][0]
        self.name = f'{self.provider}:{self.model}'
        if verbose:
            for p in self.providers:
                cost = 'PAID' if p['paid'] else 'free tier'
                print(f'  hosted provider: {p["kind"]:<7} {cost:<10} '
                      f'models {p["models"][:3]}  (key from {p["where"]})')

    # ---- construction -------------------------------------------------------
    def _make_gemini(self, key: str, where: str, cfg: BriefConfig) -> dict:
        try:
            try_install('google-genai', 'google.genai')
            from google import genai
            from google.genai import types as _gt
            client = genai.Client(          # timeout is in MILLISECONDS here
                api_key=key,
                http_options=_gt.HttpOptions(
                    timeout=self.REQUEST_TIMEOUT_S * 1000))
            sdk = 'google-genai'
        except Exception:
            try_install('google-generativeai', 'google.generativeai')
            import google.generativeai as genai_old
            genai_old.configure(api_key=key)
            client, sdk = genai_old, 'google-generativeai'
        models = [cfg.hosted_model] + [m for m in (cfg.hosted_model_ladder or ())
                                       if m != cfg.hosted_model]
        return {'kind': 'gemini', 'client': client, 'sdk': sdk, 'where': where,
                'models': models, 'paid': False}

    def _make_openai(self, key: str, where: str, cfg: BriefConfig) -> dict:
        try_install('openai', 'openai')
        import openai
        return {'kind': 'openai',
                'client': openai.OpenAI(api_key=key,
                                        timeout=self.REQUEST_TIMEOUT_S),
                'sdk': 'openai',
                'where': where, 'models': [cfg.openai_model], 'paid': True}

    # ---- classification of failures ----------------------------------------
    @staticmethod
    def _is_model_unavailable(exc) -> bool:
        """404 (retired) / 429 (out of quota): a different MODEL might work."""
        s = str(exc)
        return ('404' in s and 'NOT_FOUND' in s) or ('429' in s and 'RESOURCE_EXHAUSTED' in s)

    @staticmethod
    def _is_transient(exc) -> bool:
        """Server-side hiccups. Retry the SAME model rather than giving up on it."""
        s = str(exc)
        # 'DEADLINE_EXCEEDED' is the SERVER's deadline. A client-side
        # timeout reads "The read operation timed out" and matched none of
        # these, so it was treated as a refusal: no retry, no next model.
        return any(k in s for k in ('503', 'UNAVAILABLE', '500', 'INTERNAL',
                                    '504', 'DEADLINE_EXCEEDED', 'overloaded',
                                    'timed out', 'Timeout', 'timeout'))

    # ---- the ladder ---------------------------------------------------------
    def complete(self, system: str, user: str, cfg: BriefConfig) -> dict:
        t0, errors = time.time(), []
        for p in self.providers:
            # Free retries on a free tier; on a paid one every attempt is money,
            # so a transient failure there is not retried -- the next compile
            # can try again for free from the cache-miss path.
            tries = 3 if not p['paid'] else 1
            for model_name in p['models']:
                for attempt in range(tries):
                    if p['paid']:
                        self._reserve(cfg, model_name)
                    try:
                        text, used, capped = self._call(p, system, user, cfg, model_name)
                        self.provider, self.model = p['kind'], model_name
                        self.name = f'{p["kind"]}:{model_name}'
                        if p['paid']:
                            self.spend_log.append({'model': model_name, 'tokens': used})
                            if self.verbose:
                                print(f'  PAID request to {model_name}: '
                                      f'{used.get("input", 0)} in / {used.get("output", 0)} out '
                                      f'({self.paid_calls}/{cfg.paid_call_budget} of budget)')
                        return {'text': text, 'tokens': used, 'seconds': time.time() - t0,
                                'backend': self.name, 'hit_token_cap': capped,
                                'paid_calls': self.paid_calls}
                    except BudgetExhausted:
                        raise
                    except Exception as exc:
                        errors.append(f'{p["kind"]}/{model_name}: {str(exc)[:110]}')
                        if self._is_transient(exc) and attempt < tries - 1:
                            wait = 2 ** attempt
                            if self.verbose:
                                print(f'  {model_name}: transient, retrying in {wait}s')
                            time.sleep(wait)
                            continue
                        break
                if not (self._is_model_unavailable(Exception(errors[-1]))
                        or self._is_transient(Exception(errors[-1]))):
                    break          # a real error: stop walking this provider
                if self.verbose:
                    print(f'  {model_name} unusable, trying the next model')
            if self.verbose and p is not self.providers[-1]:
                nxt = self.providers[self.providers.index(p) + 1]
                print(f'  {p["kind"]} exhausted; falling back to '
                      f'{nxt["kind"]}{" (PAID)" if nxt["paid"] else ""}')
        raise RuntimeError('Every hosted provider failed:\n  ' + '\n  '.join(errors[-6:]))

    def _reserve(self, cfg: BriefConfig, model_name: str) -> None:
        if self.paid_calls >= cfg.paid_call_budget:
            raise BudgetExhausted(
                f'Reached the billable-request cap ({cfg.paid_call_budget}) for this '
                f'compile before calling {model_name}.\n'
                f'  Spent so far: {self.spend_log}\n'
                '  Raise BriefConfig.paid_call_budget deliberately, or set '
                'allow_paid_fallback=False to stay on the free tier.')
        self.paid_calls += 1

    # ---- one request --------------------------------------------------------
    def _call(self, p: dict, system: str, user: str, cfg: BriefConfig,
              model_name: str) -> tuple:
        if p['kind'] == 'gemini':
            return self._gemini_once(p, system, user, cfg, model_name)
        return self._openai_once(p, system, user, cfg, model_name)

    def _gemini_once(self, p: dict, system: str, user: str, cfg: BriefConfig,
                     model_name: str) -> tuple:
        if p['sdk'] == 'google-genai':
            r = p['client'].models.generate_content(
                model=model_name, contents=user,
                config={'system_instruction': system,
                        'max_output_tokens': cfg.max_new_tokens,
                        'temperature': cfg.temperature,
                        'response_mime_type': 'application/json'})
        else:
            gm = p['client'].GenerativeModel(model_name, system_instruction=system)
            r = gm.generate_content(
                user, generation_config={'max_output_tokens': cfg.max_new_tokens,
                                         'temperature': cfg.temperature,
                                         'response_mime_type': 'application/json'})
        text = getattr(r, 'text', '') or ''
        um = getattr(r, 'usage_metadata', None)
        used = {'input': getattr(um, 'prompt_token_count', 0) if um else 0,
                'output': getattr(um, 'candidates_token_count', 0) if um else 0}
        # finish_reason is an enum; its repr carries the name in every SDK
        # version, which a direct == comparison does not survive.
        cands = getattr(r, 'candidates', None) or []
        capped = bool(cands) and 'MAX_TOKENS' in str(getattr(cands[0], 'finish_reason', ''))
        if not text.strip():
            raise RuntimeError(
                f'Gemini returned no text (finish_reason='
                f'{str(getattr(cands[0], "finish_reason", "?")) if cands else "?"}). '
                f'Usually a safety block. Model was {model_name!r}.')
        return text, used, capped

    def _openai_once(self, p: dict, system: str, user: str, cfg: BriefConfig,
                     model_name: str) -> tuple:
        msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
        # Parameter names diverged across model generations: gpt-5* rejects
        # `max_tokens` outright and needs `max_completion_tokens`, and restricts
        # `temperature`. Rather than keeping a table of which model takes what --
        # which goes stale the week a model ships -- send the modern form and
        # drop whatever the API names as unsupported.
        kwargs = {'max_completion_tokens': cfg.max_new_tokens,
                  'temperature': cfg.temperature,
                  'response_format': {'type': 'json_object'}}
        for _ in range(3):
            try:
                r = p['client'].chat.completions.create(
                    model=model_name, messages=msgs, **kwargs)
                break
            except Exception as exc:
                m = re.search(r"[Uu]nsupported parameter: '(\w+)'|"
                              r"[Uu]nsupported value: '(\w+)'|"
                              r"[Uu]nrecognized request argument.*?'(\w+)'", str(exc))
                bad = next((g for g in (m.groups() if m else ()) if g), None)
                if bad == 'max_completion_tokens' and 'max_tokens' not in kwargs:
                    kwargs.pop('max_completion_tokens', None)
                    kwargs['max_tokens'] = cfg.max_new_tokens
                    continue
                if bad and bad in kwargs:
                    kwargs.pop(bad)
                    continue
                raise
        else:
            raise RuntimeError(f'{model_name}: could not find an accepted parameter set')
        ch = r.choices[0]
        text = ch.message.content or ''
        u = r.usage
        used = {'input': getattr(u, 'prompt_tokens', 0), 'output': getattr(u, 'completion_tokens', 0)}
        if not text.strip():
            raise RuntimeError(f'{model_name} returned no text '
                               f'(finish_reason={ch.finish_reason}).')
        return text, used, ch.finish_reason == 'length'

class LocalTextBackend(BriefBackend):
    """
    The Qwen3-VL already resident from Phase 3, driven text-only.

    No second model, no extra VRAM, no download. It reuses VLMBackend.generate(),
    which already carries the token accounting and the OOM diagnostics that were
    hard-won in §30 -- reimplementing them here would mean re-earning them.
    """
    kind = 'local'

    def __init__(self, vlm, cfg: BriefConfig, vision_cfg=None, verbose: bool = True):
        if vlm is None:
            raise RuntimeError('No VLM loaded. Run §30.1 first, or use backend="rules".')
        # A HOSTED vision backend has no local processor to drive text-only.
        # Reached when the hosted brief backend fails and backend="auto" falls
        # through: without this it would accept a GeminiVLMBackend and fail
        # later, inside generate(), with an AttributeError that names neither
        # the cause nor the fix.
        if getattr(vlm, 'processor', None) is None:
            raise RuntimeError(
                'The VLM in scope is a HOSTED backend '
                f'({(getattr(vlm, "info", None) or {}).get("model", "?")}), which '
                'has no local\n  processor to drive text-only. For the brief use '
                'backend="hosted" (the\n  same provider) or backend="rules" (no '
                'model at all), or load the local\n  VLM with VISION_PROVIDER = '
                "'local' in §26c.")
        # Resolve the vision config HERE, not in complete(). Reaching into a
        # module global this class does not own would make Phase 4 unrunnable
        # outside the full pipeline for a name it only needs on one code path --
        # and it would fail with a NameError at generation time rather than at
        # construction time, which is the wrong place to find out.
        if vision_cfg is None:
            _p3 = globals().get('P3')
            vision_cfg = getattr(_p3, 'vision', None)
        if vision_cfg is None:
            raise RuntimeError(
                'No VisionConfig available -- Phase 3 is not loaded in this kernel.\n'
                '  Pass vision_cfg=..., or use backend="hosted" / "rules".')
        self.vlm, self.vision_cfg = vlm, vision_cfg
        self.name = f'local:{vlm.info.get("model_id", "qwen3-vl")}'
        if verbose:
            print(f'  local backend: {self.name} (text-only, no images)')

    def complete(self, system: str, user: str, cfg: BriefConfig) -> dict:
        messages = [
            {'role': 'system', 'content': [{'type': 'text', 'text': system}]},
            {'role': 'user',   'content': [{'type': 'text', 'text': user}]},
        ]
        vcfg = replace(self.vision_cfg, max_new_tokens=cfg.max_new_tokens,
                       do_sample=bool(cfg.temperature > 0))
        out = self.vlm.generate(messages, [], vcfg)
        return {'text': out.get('text', ''),
                'tokens': out.get('tokens', {}),
                'seconds': out.get('seconds', 0.0),
                'backend': self.name,
                'hit_token_cap': bool(out.get('hit_token_cap'))}

class RuleBasedBackend(BriefBackend):
    """
    A compiler with no model in it.

    Scope, stated honestly: imperative bullet-style briefs, which is what most
    real briefs are. On free prose it produces fewer, blunter requirements and
    marks confidence down rather than inventing structure it did not find.

    It exists mainly so §47 can run the ENTIRE phase with no GPU and no network,
    and so "the LLM is better" is a measurement rather than an assumption.
    """
    kind = 'rules'
    name = 'rules:deterministic'

    def complete(self, system: str, user: str, cfg: BriefConfig) -> dict:
        t0 = time.time()
        brief = self._extract_brief(user)
        reqs = [self._compile_one(u) for u in brief_units(brief)]
        reqs = [r for r in reqs if r]
        return {'text': json.dumps({'campaign': find_campaign(brief),
                                    'requirements': reqs[:cfg.max_requirements]}),
                'tokens': {'input': 0, 'output': 0},
                'seconds': time.time() - t0,
                'backend': self.name, 'hit_token_cap': False}

    @staticmethod
    def _extract_brief(user: str) -> str:
        """Pull the brief back out of the prompt envelope."""
        m = re.search(r'BRIEF:\s*\n-{3,}\n(.*?)\n-{3,}', user, re.S)
        return m.group(1) if m else user

    @staticmethod
    def _compile_one(u) -> Optional[dict]:
        """u is a brief_units() dict, or a bare string for a flat brief."""
        if isinstance(u, str):
            u = {'text': u, 'section': '', 'kind': 'requirements', 'group': None,
                 'group_mode': 'all_of', 'group_label': '', 'type_hint': None}
        unit = (u.get('text') or '').strip()
        if not unit:
            return None
        mode_info = infer_evidence_mode(unit)
        polarity, _ = infer_polarity(unit)
        type_, _ = infer_requirement_type(unit, mode_info['mode'])
        # A quoted line is SCRIPT, not policy. "If your ponytail feels smaller,
        # don't scroll" is a hook to deliver; the "don't" inside it is part of
        # the line, not a prohibition on the creator. Read as forbidden it
        # becomes a critical compliance rule no video can satisfy, and it drags
        # false contradictions along with it.
        quoted = is_quoted_example(unit)
        if quoted:
            polarity = 'required'
            if type_ in ('policy', 'other'):
                type_ = u.get('type_hint') or 'speech_or_text'
        # The heading beats the sentence. Under "Sample Hook Concepts", a quoted
        # line is a hook -- whatever the words inside the quotes happen to be
        # about. Without this every hook example classifies as whatever it
        # describes, and "Blow drying your hair could be damaging it" becomes a
        # policy rule about hair damage.
        if u.get('type_hint') and type_ in ('other', 'speech', 'speech_or_text', 'visual'):
            type_ = u['type_hint']
        if polarity == 'forbidden' and type_ not in ('policy', 'brand'):
            type_ = 'policy'
        priority, _ = infer_priority(unit, type_, polarity)
        checkable, _ = is_machine_checkable(unit, type_)
        temporal = extract_temporal(unit, type_)
        mode = mode_info['mode'] or TYPE_DEFAULT_MODE.get(type_, 'any')
        # A quoted example is a line the creator is expected to deliver; it can
        # be spoken or burned in as a caption, and either satisfies it.
        if not mode_info['mode'] and quoted:
            mode = 'speech_or_text'
        return {
            'requirement': unit,
            'type': type_,
            'evidence_mode': mode,
            'polarity': polarity,
            'priority': priority,
            'machine_checkable': checkable,
            'group': u.get('group'),
            'group_mode': u.get('group_mode', 'all_of'),
            'group_label': u.get('group_label', ''),
            'group_intent': u.get('group_intent', ''),
            'deadline_seconds': temporal['deadline_seconds'],
            'window_start_expr': temporal['window_start_expr'],
            'window_end_expr': temporal['window_end_expr'],
            'match_hints': rule_match_hints(unit),
            'acceptance_criteria': [unit],
            'claim_classes': infer_claim_classes(unit) if polarity == 'forbidden' else [],
            'brief_span': unit,
            'confidence': 0.75 if mode_info['confident'] and mode_info['mode'] else 0.45,
        }

def make_brief_backend(cfg: BriefConfig = None, vlm=None, verbose: bool = True) -> BriefBackend:
    """Resolve cfg.backend. 'auto' tries hosted, then local, then rules -- and always says which."""
    cfg = cfg or P4.brief
    want = cfg.backend
    if want not in ('auto', 'hosted', 'local', 'rules'):
        raise ValueError(f'unknown backend {want!r}; use auto | hosted | local | rules')

    if want in ('auto', 'hosted'):
        try:
            return HostedLLMBackend(cfg, verbose=verbose)
        except Exception as exc:
            if want == 'hosted':
                raise
            if verbose:
                print(f'  hosted unavailable ({str(exc)[:90]})')

    if want in ('auto', 'local'):
        cand = vlm if vlm is not None else globals().get('vlm')
        try:
            return LocalTextBackend(cand, cfg, verbose=verbose)
        except Exception as exc:
            if want == 'local':
                raise
            if verbose:
                print(f'  local unavailable ({str(exc)[:90]})')

    if verbose:
        print('  rule-based backend (deterministic, no model)')
    return RuleBasedBackend()


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 463: print('§42 backends loaded: hosted | local | rules')
