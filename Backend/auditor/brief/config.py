"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 88.
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
import re, json, time, hashlib, textwrap, os

from pathlib import Path

from dataclasses import dataclass, field, asdict, replace

from typing import Optional

# BUMP THIS WHENEVER THE CODE CHANGES WHAT COMES OUT.
# It is part of the cache key, and it is the only thing that invalidates a stored
# artifact when the inputs have not changed. Leaving it alone after fixing §40b,
# §42 and §44 meant compile_brief found the OLD result under an unchanged key and
# returned it -- the fixes ran, and nothing used them.
#   1.0.0  first version
#   1.1.0  + document sections, one_of groups, approved claims
#   1.2.0  + plain-text headings (Google Docs exports no markdown),
#            quoted lines are script not policy, conflict threshold tightened
#   1.3.0  + example/reference video links extracted instead of compiled,
#            bullets nest under their numbered concept, section preambles
#            dropped, group ids unique per section
#   1.4.0  + a one_of group with a single member is demoted to all_of
#   1.5.0  + requirements derived from the approved-claims allowlist become
#            one any_of group instead of separate mandatory mentions
#   1.8.0  + a requirement written outside the list it belongs to joins that
#            list's choice group, instead of being scored as independently
#            mandatory; duplicate safety rules of the same KIND merge
#   1.9.0  + a figure-fidelity rule no longer counts as contradicting a
#            requirement to state those figures; conflicts are recomputed on
#            the merged consensus set instead of the base run, so no conflict
#            names a requirement the artifact no longer contains
#   1.10.0 + one group carries one group_intent; requirements are fingerprinted
#            on the document's sentence rather than the model's phrasing
#   1.11.0 + every option an alternatives section lists is guaranteed a
#            requirement: the DOCUMENT decides how many options a brief offers,
#            not the model's sampling
#   1.12.0 + adoption runs again on the merged consensus set: a requirement
#            adopted in one run could be replaced by the un-adopted version
#            from another and be scored as independently mandatory
BRIEF_STAGE_VERSION  = '1.25.0'   # prompt v4: group_intent

BRIEF_PROMPT_VERSION = 'p4_brief_compile_v5'   # + group_intent: the ask behind the examples

def sha256_text(text: str) -> str:
    """Stable hash of a brief. Whitespace-normalised so reformatting is not a new brief."""
    norm = re.sub(r'\s+', ' ', (text or '')).strip().lower()
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]

REQUIREMENT_TYPES = (
    'hook',            # the opening seconds must do something specific
    'visual',          # something must be SEEN
    'speech',          # something must be SAID
    'speech_or_text',  # said or written, either satisfies
    'demonstration',   # the product must be USED, not merely shown
    'audience',        # tone/targeting
    'cta',             # call to action
    'policy',          # a rule, usually negative
    'brand',           # logo, name, handle, brand voice
    'timing',          # pacing / length / structure
    'other',           # outside the enum -- always flagged
)

EVIDENCE_MODES = (
    'speech_only',        # transcript only. OCR of the same words does NOT satisfy.
    'visual_only',        # the VLM must have seen it
    'ocr_only',           # on-screen text, and only if independence is confirmed
    'speech_or_text',     # transcript OR on-screen text
    'visual_and_speech',  # both, together
    'any',                # any modality counts -- correct for policy/forbidden rules
)

PRIORITIES      = ('low', 'medium', 'high', 'critical')

PRIORITY_WEIGHT = {'critical': 3.0, 'high': 2.0, 'medium': 1.0, 'low': 0.5}

POLARITIES      = ('required', 'forbidden')

# ---------------------------------------------------------------------------
# Real briefs offer CHOICES, and that is not a detail.
#
# A creator brief typically lists three video concepts, four sample hooks and
# three CTA options, and a video is expected to use ONE of each. Compiled as
# separate required items, a perfectly compliant video fails the ten it did not
# pick -- a false FAIL, which is the most damaging answer this system can give.
#
#   all_of   every member must hold      (the default: a plain requirement)
#   one_of   exactly one member          "pick one of these three hooks"
#   any_of   at least one member         "mention at least one of these benefits"
# ---------------------------------------------------------------------------
GROUP_MODES = ('all_of', 'one_of', 'any_of')

# What a heading in a brief DOCUMENT means for the lines underneath it.
DOC_SECTION_KINDS = (
    'requirements',   # things the video must do
    'alternatives',   # options to choose between -> one_of group
    'claims',         # approved things the creator MAY say -> an allowlist
    'context',        # purpose, background, audience -> no requirements at all
)

# product.md §38: you cannot prove a negative globally, so a forbidden
# requirement names the detectable classes it is actually looking for.
CLAIM_CLASSES = ('medical', 'cure', 'guarantee', 'unsupported_outcome',
                 'prohibited_wording', 'competitor', 'pricing', 'other')

# Where an ambiguous requirement falls back to, by type. Read the reasoning:
#   policy  -> 'any' because a medical claim burned into a caption is exactly as
#              non-compliant as a spoken one. Narrowing the channel on a FORBIDDEN
#              rule creates a blind spot rather than a stricter test.
#   cta     -> 'speech_or_text': "link in bio" is as often on screen as spoken.
#   hook    -> 'any': a hook can be a line, a visual, or a caption.
TYPE_DEFAULT_MODE = {
    'hook': 'any',
    'visual': 'visual_only',
    'speech': 'speech_only',
    'speech_or_text': 'speech_or_text',
    'demonstration': 'visual_only',
    'audience': 'any',
    'cta': 'speech_or_text',
    'policy': 'any',
    'brand': 'any',
    'timing': 'any',
    'other': 'any',
}

@dataclass(frozen=True)
class BriefConfig:
    # --- backend ---
    backend: str = 'auto'                 # auto | hosted | local | rules
    # Use the `-latest` ALIASES, not a pinned version. Model names retire: every
    # gemini-2.5-* now answers 404 "no longer available to new users", which is a
    # hard failure for a notebook that pinned one. The aliases track whatever is
    # current. hosted_model_ladder is tried in order when a model is gone (404)
    # or out of quota (429) -- pro tiers are commonly unavailable on a free key.
    # ORDER IS MEASURED, NOT ALPHABETICAL. Phase 3 found flash-lite to be the
    # only model that reliably serves on a free key; flash-latest returns 503
    # UNAVAILABLE and pro-latest 429 RESOURCE_EXHAUSTED. Putting either first
    # costs two dead round trips on every single call, which on a full audit
    # is minutes of latency that looks exactly like a hang.
    # They stay in the ladder -- a 429 is a quota, not a tombstone -- but they
    # are tried AFTER the one that works.
    # RE-MEASURED 2026-09-22 on a live key, one-word prompt, same minute:
    #     gemini-3.5-flash           3.3s  OK
    #     gemini-flash-lite-latest  25.1s  OK   <- the old default
    #     gemini-3.5-flash-lite     36.4s  OK
    #     gemini-3.1-flash-lite / gemini-3.8-flash    503 high demand
    #     gemini-2.5-flash / gemini-2.5-flash-lite    404 retired
    # flash-lite was never down; it is 8x slower to say one word, and an L3
    # call carries ~11k in / ~2k out. Only measured-working models are in the
    # ladder: a 503 model costs three attempts and 3s of back-off per call,
    # and OpenAI is the safety net underneath.
    hosted_model: str = 'gemini-3.5-flash'
    hosted_model_ladder: tuple = ('gemini-3.5-flash', 'gemini-3.5-flash-lite',
                                  'gemini-flash-lite-latest')
    # OpenAI is the PAID fallback, tried only after Gemini's ladder is exhausted.
    # gpt-4.1-mini is verified working, cheap, and strong enough for structured
    # extraction. Avoid the gpt-5 line here unless you want it: it spends
    # reasoning tokens you are billed for -- 142 output tokens for a 5-token
    # answer in testing -- and it rejects `max_tokens` outright.
    openai_model: str = 'gpt-4.1-mini'

    # --- spend control -------------------------------------------------------
    # A hard cap on BILLABLE requests per compile_brief() call, across every
    # provider. compile_brief can legitimately call a backend three times (a
    # parse-repair retry, an output-cap bump), and each one costs money on a
    # paid key. Nothing that runs automatically may exceed this.
    paid_call_budget: int = 3
    allow_paid_fallback: bool = True      # False = never touch OpenAI at all
    # A real creator brief compiles to far more JSON than a six-line example
    # does: the AURELIA brief truncated at 3000. Start high, and raise once more
    # if even this is not enough -- see max_output_ceiling.
    max_new_tokens: int = 8192
    max_output_ceiling: int = 32768       # the cap the retry ladder will not pass
    temperature: float = 0.0              # determinism matters more than variety here
    allow_retry: bool = True              # one validation-feedback retry

    # --- decomposition guards ---
    max_requirements: int = 40
    over_decomposition_ratio: float = 2.5  # requirements per non-empty brief line
    dedupe_min_ratio: int = 88             # rapidfuzz ratio for near-identical merge

    # --- temporal defaults, used only when the brief is vague ---
    default_hook_window: float = 3.0
    default_cta_window: float = 5.0
    max_plausible_deadline: float = 600.0  # a "within N seconds" beyond this is a parse error

    # --- policy ---
    infer_implicit: bool = False           # emit source='inferred' requirements
    require_approval: bool = True          # §46 gate

@dataclass(frozen=True)
class Phase4Config:
    brief: BriefConfig = field(default_factory=BriefConfig)

P4 = Phase4Config()

# ---------------------------------------------------------------------------
# Which hosted model is actually serving RIGHT NOW
#
# A hardcoded ladder is a measurement, and measurements go stale: this
# notebook shipped one ordering ("flash-lite is the only model that serves")
# that was later measured at 25 SECONDS to answer a one-word prompt, while
# gemini-3.5-flash answered the same prompt in 3.3s on the same key in the
# same minute. Probing costs one tiny call per candidate and removes the guess.
#
# Set PIN_HOSTED_MODEL to skip probing entirely. Do that whenever the cache key
# must be reproducible -- notably the Phase 8 labelling corpus, where the whole
# point is ONE judge across every video.
# ---------------------------------------------------------------------------
PIN_HOSTED_MODEL = None          # e.g. 'gemini-3.5-flash' -> no probe, fixed key

HOSTED_PROBE_CANDIDATES = (
    'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite',
    'gemini-3.8-flash', 'gemini-flash-lite-latest', 'gemini-flash-latest',
    'gemini-pro-latest',
)

HOSTED_PROBE_TIMEOUT_S = 20      # a model too slow to say "ok" is too slow to judge

_HOSTED_PROBE_CACHE = {}         # probe once per session, not once per call

def probe_hosted_models(candidates=None, timeout_s: float = None,
                        verbose: bool = True) -> list:
    """[(seconds, model)] that answered, fastest first. Never raises.

    Run in PARALLEL: seven serial probes against a 25s model is two minutes
    before any real work begins, and the probe exists to SAVE time.
    """
    import concurrent.futures as _cf
    import time as _t
    candidates = tuple(candidates or HOSTED_PROBE_CANDIDATES)
    timeout_s = float(timeout_s or HOSTED_PROBE_TIMEOUT_S)
    # os.environ directly, NOT _get_secret/HostedLLMBackend: both are defined
    # further down the notebook than this cell, and calling them here is a
    # NameError on a fresh kernel. §37a has already hoisted any Colab secret
    # into the environment by the time this runs, so this reads the same value.
    key = next((os.environ[n] for n in ('GEMINI_API_KEY', 'GOOGLE_API_KEY',
                                        'GOOGLE_GENAI_API_KEY')
                if os.environ.get(n, '').strip()), '')
    if not key:
        if verbose:
            print('  no Gemini key -- skipping the probe')
        return []
    try:
        # The SDK is installed lazily by the backend, which has not run yet.
        _ti = globals().get('try_install')
        if callable(_ti):
            _ti('google-genai', 'google.genai')
        from google import genai
        from google.genai import types as _gt
        client = genai.Client(api_key=key, http_options=_gt.HttpOptions(
            timeout=int(timeout_s * 1000)))
    except Exception as exc:
        if verbose:
            print(f'  probe unavailable ({type(exc).__name__}) -- '
                  f'keeping the configured order')
        return []

    def _one(name):
        t0 = _t.time()
        try:
            r = client.models.generate_content(
                model=name, contents='Reply with one word: ok')
            return name, _t.time() - t0, (r.text or '').strip()[:20], None
        except Exception as exc:
            return name, _t.time() - t0, None, f'{type(exc).__name__}: {str(exc)[:70]}'

    out, _errs = [], []
    with _cf.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        for name, dt, text, err in ex.map(_one, candidates):
            if err is None:
                out.append((dt, name))
                if verbose:
                    print(f'    OK    {name:26} {dt:5.1f}s  {text!r}')
            else:
                _errs.append(err)
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
    return out

def autoselect_hosted_model(cfg=None, verbose: bool = True):
    """BriefConfig with hosted_model/ladder set to what is serving now.

    Returns the config UNCHANGED when pinned, when nothing answers, or when
    there is no key -- degrade, never block. A probe that cannot reach the
    network must not stop an audit that the call-time ladder could still run.
    """
    import dataclasses as _dc
    cfg = cfg or P4.brief
    if PIN_HOSTED_MODEL:
        if verbose:
            print(f'  hosted model PINNED to {PIN_HOSTED_MODEL} '
                  f'(no probe; cache key is reproducible)')
        return _dc.replace(cfg, hosted_model=PIN_HOSTED_MODEL,
                           hosted_model_ladder=(PIN_HOSTED_MODEL,))
    if 'ranked' not in _HOSTED_PROBE_CACHE:
        if verbose:
            print('  probing hosted models (parallel, once per session):')
        _HOSTED_PROBE_CACHE['ranked'] = probe_hosted_models(verbose=verbose)
    ranked = _HOSTED_PROBE_CACHE['ranked']
    if not ranked:
        if verbose:
            print(f'  nothing answered -- keeping the configured order '
                  f'({cfg.hosted_model} first). The call-time ladder and the '
                  f'paid fallback still apply.')
        return cfg
    order = tuple(m for _dt, m in ranked)
    if verbose:
        print(f'  hosted model -> {order[0]}  ({ranked[0][0]:.1f}s), '
              f'fallbacks {order[1:3] or "none"}')
        print('  NOTE: hosted_model is part of the brief cache key, so this '
              'choice names the judge that ran.')
        print('        Set PIN_HOSTED_MODEL for a reproducible key.')
    return _dc.replace(cfg, hosted_model=order[0], hosted_model_ladder=order)


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 72: _briefs_home = (globals().get('DRIVE_ROOT') or WORK) / 'briefs'
#   line 73: DIRS.setdefault('briefs', _briefs_home)
#   line 74: DIRS['briefs'].mkdir(parents=True, exist_ok=True)
#   line 236: print('§37 Phase 4 config loaded.')
#   line 237: print(f"  brief store         : {DIRS['briefs']}")
#   line 238: print(f'  stage version       : {BRIEF_STAGE_VERSION}   prompt: {BRIEF_PROMP
#   line 239: print(f'  requirement types   : {len(REQUIREMENT_TYPES)}   evidence modes: {
#   line 240: print(f'  backend             : {P4.brief.backend}  (resolved in §42)')
#   line 371: P4 = dataclasses.replace(P4, brief=autoselect_hosted_model(P4.brief))
