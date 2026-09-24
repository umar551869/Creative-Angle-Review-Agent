"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 125.
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
HOOK_TYPES = (
    'question', 'bold_claim', 'problem_statement', 'result_reveal',
    'curiosity_gap', 'direct_address', 'demonstration', 'social_proof',
    'negative_warning', 'humour', 'none',
)

_Q_WORDS = ('what', 'why', 'how', 'when', 'where', 'who', 'which', 'did', 'do',
            'does', 'are', 'is', 'can', 'ever', 'would', 'have')

_NEG_WORDS = ('not', "n't", 'never', 'no', 'stop', 'avoid', 'mistake', 'wrong',
              'worst', 'without', 'nobody', 'don', 'doesn')

_YOU_WORDS = ('you', 'your', "you're", 'yours', 'yourself')

HOOK_SYSTEM = """You judge the opening hook of a short-form video.

A HOOK is an opening that gives a viewer a reason to keep watching. An
INTRODUCTION ("hi guys, welcome back") is not a hook.

Answer two SEPARATE questions. Do not let one decide the other:
1. Is a hook present at all?
2. If present, how strong is it?

STRENGTH ANCHORS -- use these, not your own scale:
  weak    - technically a hook, but generic and easily scrolled past.
            e.g. "Let's talk about hair care."
  medium  - a specific reason to stay, but no tension or stakes.
            e.g. "This is the product I use every morning."
  strong  - creates curiosity, stakes, or a promise that demands resolution.
            e.g. "I ruined my hair for two years doing this one thing."

Use ONLY the evidence given. You cannot see the video.
Return ONLY this JSON, no prose and no code fence:
{"hook_present": true, "hook_type": "one of the listed types",
 "strength": "weak|medium|strong", "reason": "one sentence",
 "evidence_ids": ["..."]}"""

def hook_features(records: list, duration: float, cuts: int,
                  cfg: HookConfig = None) -> dict:
    """Free, deterministic signals from the opening window."""
    cfg = cfg or P6.hook
    w = min(cfg.window_seconds, duration or cfg.window_seconds)
    speech = speech_in_window(records, 0.0, w)
    text = text_in_window(records, 0.0, 1.0)
    vis = visual_in_window(records, 0.0, w)
    all_speech = [r for r in records if r.modality == 'speech']
    onset = min((r.start_seconds for r in all_speech), default=None)
    first = ''
    if speech:
        first = (min(speech, key=lambda r: r.start_seconds).raw_text or '').strip()
    low = first.lower()
    toks = re.findall(r"[a-z']+", low)
    return {
        'window_seconds': round(w, 2),
        'speech_onset': (round(onset, 3) if onset is not None else None),
        'speech_starts_early': bool(onset is not None and onset <= cfg.speech_onset_good),
        'first_sentence': first[:200],
        'has_question': ('?' in first) or bool(toks and toks[0] in _Q_WORDS),
        'has_number': bool(re.search(r'\d', first)),
        'has_negation': any(n in low for n in _NEG_WORDS),
        'has_second_person': any(t in _YOU_WORDS for t in toks),
        'text_overlay_in_first_second': bool(text),
        'cuts_in_window': sum(1 for r in records
                              if r.type == 'scene_cut' and r.start_seconds <= w),
        'cut_density_per_second': round(cuts / duration, 4) if duration else 0.0,
        'face_at_camera': any(r.type == 'person_speaking_to_camera' for r in vis),
        'speech_records': len(speech), 'visual_records': len(vis),
    }

def evaluate_hook(records: list, duration: float, cuts: int, health: dict,
                  backend=None, cfg: Phase6Config = None,
                  verbose: bool = True) -> dict:
    """spec §33's full output. Presence and strength stay separate throughout."""
    cfg = cfg or P6
    f = hook_features(records, duration, cuts, cfg.hook)
    w = f['window_seconds']
    cands = [r for r in records
             if r.modality in ('speech', 'ocr', 'visual')
             and r.overlaps(0.0, w, slack=0.25)][:cfg.retrieval.top_k]

    out = {'hook_present': None, 'hook_type': 'none', 'start': 0.0,
           'end': round(w, 2), 'strength': None, 'transcript': f['first_sentence'],
           'visual': '', 'within_required_window': None, 'reason': '',
           'features': f, 'evidence_ids': [c.id for c in cands],
           'layer': 'L1', 'flags': []}
    vis = [c for c in cands if c.modality == 'visual']
    if vis:
        out['visual'] = (vis[0].description or '')[:200]

    if not can_fail_on(health or {}, 'speech'):
        out.update(hook_present=None, reason=(
            'Speech evidence was degraded or absent, so hook presence cannot be '
            'judged. This is UNCERTAIN, not "no hook".'),
            flags=['HOOK_UNCERTAIN_DEGRADED_SPEECH'])
        return out
    if not f['speech_records'] and not f['text_overlay_in_first_second']:
        out.update(hook_present=False, hook_type='none', strength=None,
                   within_required_window=False,
                   reason=f'No speech or on-screen text in the first {w:.1f}s of a '
                          f'video whose speech track ran cleanly.')
        return out

    if not (cfg.hook.use_llm and cfg.l3.enabled):
        out.update(hook_present=True, hook_type='direct_address',
                   within_required_window=True, layer='L1',
                   reason=f'Speech begins at {f["speech_onset"]}s; hook TYPE and '
                          f'STRENGTH need the language model, which is disabled.',
                   flags=['HOOK_TYPE_NOT_JUDGED'])
        return out

    lines = [f'VIDEO DURATION: {duration:.2f}s',
             f'HOOK WINDOW: 0.00-{w:.2f}s', '',
             'DETERMINISTIC SIGNALS:']
    for k in ('speech_onset', 'has_question', 'has_number', 'has_negation',
              'has_second_person', 'text_overlay_in_first_second',
              'cuts_in_window', 'face_at_camera'):
        lines.append(f'  {k} = {f[k]}')
    lines += ['', 'EVIDENCE IN THE WINDOW:']
    lines += [_evidence_line(c) for c in cands] or ['  (none)']
    lines += ['', f'Allowed hook_type values: {", ".join(HOOK_TYPES)}']

    bcfg = replace(P4.brief, temperature=0.0, max_new_tokens=1024)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(HOOK_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _ = parse_model_json(gen.get('text', '') or '')
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'
    if not isinstance(obj, dict):
        out.update(hook_present=None,
                   reason=f'The hook model returned nothing usable ({perr}).',
                   layer='L3', flags=['HOOK_MODEL_FAILED'])
        return out

    ht = str(obj.get('hook_type') or 'none')
    st = str(obj.get('strength') or '').lower()
    ids = [i for i in (obj.get('evidence_ids') or []) if i in set(out['evidence_ids'])]
    out.update(
        hook_present=bool(obj.get('hook_present')),
        hook_type=(ht if ht in HOOK_TYPES else 'none'),
        strength=(st if st in cfg.hook.strengths else None),
        reason=str(obj.get('reason') or '')[:300],
        evidence_ids=ids, layer='L3')
    if ht not in HOOK_TYPES:
        out['flags'].append(f'HOOK_TYPE_OUT_OF_ENUM:{ht[:30]}')
    if out['hook_present'] and out['strength'] is None:
        out['flags'].append('HOOK_STRENGTH_MISSING')
    out['within_required_window'] = bool(
        out['hook_present'] and (f['speech_onset'] is None
                                 or f['speech_onset'] <= cfg.hook.max_window_seconds))
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 158: print('§68 hook module loaded.  Presence and strength are judged separately.
