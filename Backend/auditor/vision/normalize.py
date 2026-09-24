"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 70.
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
def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return int(round(value)) if math.isfinite(value) else None
    if isinstance(value, str):
        m = re.search(r'-?\d+', value)
        return int(m.group()) if m else None
    return None

def _coerce_float(value, default: float) -> tuple:
    try:
        v = float(value)
        if not math.isfinite(v):
            return default, True
    except (TypeError, ValueError):
        return default, True
    return v, False

# Words that mark a continuation rather than a new observation. "The woman
# CONTINUES speaking" states nothing the previous sentence did not.
CONTINUATION_WORDS = frozenset((
    'continues continuing continue continued still again remains remain '
    'remaining keeps keep keeping same now then persists ongoing').split())

def _same_word(a: str, b: str, min_ratio: int) -> bool:
    """
    Phase 2's _tokens_match, plus a looser stem for FOUR-character roots.

    _tokens_match requires a 5-character shared prefix -- correct for what it was
    tuned on (everyone/everybody, hydrating/hydration). Verb inflections in
    visual descriptions routinely share only four: hold/holding, appl/applying.

    Loosening the RATIO instead is not an option, and the numbers say why:
        ratio('applying', 'applies') = 66.7   <- want this to match
        ratio('holding',  'holds')   = 66.7   <- want this to match
        ratio('head',     'hand')    = 75.0   <- must NOT match
    The inflections score LOWER than two unrelated body parts, so no threshold
    separates them. A prefix rule does: head/hand share one character.
    """
    if _tokens_match(a, b, min_ratio):
        return True
    p = 0
    for x, y in zip(a, b):
        if x != y:
            break
        p += 1
    return p >= 4 and p >= 0.55 * min(len(a), len(b))

def adds_no_new_fact(prev_desc: str, next_desc: str, min_ratio: int = 80) -> bool:
    """
    Does `next_desc` introduce any content word `prev_desc` did not have?

    This replaces the similarity threshold, which could not work. Measured on
    real Qwen3-VL output, token_set_ratio put true restatement at >=84.9 and
    genuinely different facts at <=84.2 -- the classes overlap, because both
    share the same long core clause. Similarity measures shared VOCABULARY; what
    we need to know is whether new INFORMATION appeared.

        "...container above their head"  ->  "...container in front of the camera"
            new content: front, camera            -> different fact, KEEP
        "A woman speaks to the camera"   ->  "The woman continues speaking to the camera"
            new content: (continues is a continuation marker; speaking stems to
            speaks)                               -> restatement, MERGE

    Uses Phase 2's content_tokens (stopwords dropped) and _tokens_match (fuzzy +
    the stem rule that makes speaking ~ speaks), so it inherits machinery that is
    already tested rather than inventing a second dialect of the same idea.
    """
    have = set(content_tokens(prev_desc or ''))
    incoming = content_tokens(next_desc or '')
    if not incoming:
        return True                      # says nothing at all
    for tok in incoming:
        if tok in CONTINUATION_WORDS:
            continue
        if not any(_same_word(tok, s, min_ratio) for s in have):
            return False                 # a genuinely new content word
    return True

def merge_adjacent_events(events: list, cfg: VisionConfig = None) -> tuple:
    """
    Collapse consecutive events that describe the SAME continuous state.

    A VLM shown 24 frames often narrates each one, producing five near-identical
    'product_held' events where the truth is a single 30-second span. That is an
    artifact of frame-by-frame description, not a signal, and it inflates the
    event count without adding a fact.

    THE SAFETY PROPERTY is that merging is gated on description similarity, not
    just on type and adjacency. If the run really is 'holds it' -> 'opens it' ->
    'applies it', those descriptions are not similar, the action verbs differ,
    and all three survive. Only genuine near-duplicates collapse. That matters
    because 'demonstrated' vs 'merely shown' is a distinction a brief turns on
    (plan.md §35), and a merge that erased it would be silently destroying
    evidence.

    MERGING IS LOSSLESS. Every constituent observation is kept in `segments`,
    with its own frame range and timestamps. This matters more than it looks:
    "holds it above their head", "turns it to show the label" and "holds it at
    chest height" share most of their words -- so they merge -- but they are
    three different facts, and a requirement like "the label must be legible on
    screen" is answered by the second one alone. The top-level description is a
    representative for the span, NOT a replacement for what it summarises.

    Returns (events, n_merged).
    """
    cfg = cfg or P3.vision
    if len(events) < 2:
        return events, 0

    def _seg(e: dict) -> dict:
        return {'frame_start': e['frame_start'], 'frame_end': e['frame_end'],
                'start_seconds': e['start_seconds'], 'end_seconds': e['end_seconds'],
                'description': e['description']}

    merged, n_merged = [events[0]], 0
    for ev in events[1:]:
        prev = merged[-1]
        contiguous = ev['frame_start'] <= prev['frame_end'] + 1
        same_kind = ev['type'] == prev['type'] and ev['action'] == prev['action']
        # Compare against EVERYTHING the span has said so far, not just the last
        # link. A word already mentioned two segments ago is not new information,
        # and a genuinely new word is still caught however long the span is.
        said = ' '.join(s['description'] for s in (prev.get('segments')
                                                   or [{'description': prev['description']}]))
        restates = adds_no_new_fact(said, ev['description'], cfg.merge_token_ratio)

        if not (contiguous and same_kind and restates):
            merged.append(ev)
            continue

        # NOTHING IS DISCARDED: keep every observation as a segment, and use the
        # most informative one as the span's representative description.
        segments = prev.get('segments') or [_seg(prev)]
        segments.append(_seg(ev))
        desc = max((s['description'] for s in segments), key=len)
        prev.update({
            'frame_end': max(prev['frame_end'], ev['frame_end']),
            'end_seconds': max(prev['end_seconds'], ev['end_seconds']),
            'start_seconds': min(prev['start_seconds'], ev['start_seconds']),
            'frame_start': min(prev['frame_start'], ev['frame_start']),
            'description': desc,
            'segments': segments,
            'objects': sorted(set(prev['objects']) | set(ev['objects'])),
            'confidence': round(max(prev['confidence'], ev['confidence']), 3),
            'frame_ids': sorted(set(prev['frame_ids']) | set(ev['frame_ids'])),
            'timestamp_unreliable': prev['timestamp_unreliable'] or ev['timestamp_unreliable'],
            'flags': sorted(set(prev['flags']) | set(ev['flags'])),
            'merged_count': len(segments),
        })
        n_merged += 1
    return merged, n_merged

def normalize_visual_events(raw, frame_table: list, cfg: VisionConfig = None) -> tuple:
    """
    Model output -> validated VisualEvent dicts. Returns (events, flags).

    Never raises. Every correction is recorded as a flag so a strange report can
    always be traced back to what the model actually said.
    """
    cfg = cfg or P3.vision
    flags: list = []
    n = len(frame_table)
    if n == 0:
        return [], [{'code': 'NO_FRAMES', 'detail': 'empty frame table'}]

    # ---- locate the event list, tolerating a bare list or a wrapper key -------
    if isinstance(raw, list):
        raw_events = raw
    elif isinstance(raw, dict):
        raw_events = raw.get('events')
        if raw_events is None:
            for alt in ('observations', 'items', 'results', 'data'):
                if isinstance(raw.get(alt), list):
                    raw_events = raw[alt]
                    flags.append({'code': 'NONSTANDARD_EVENTS_KEY', 'detail': alt})
                    break
    else:
        return [], [{'code': 'OUTPUT_NOT_OBJECT', 'detail': type(raw).__name__}]

    if raw_events is None:
        return [], [{'code': 'NO_EVENTS_KEY', 'detail': 'no "events" list in the reply'}]
    if not isinstance(raw_events, list):
        return [], [{'code': 'EVENTS_NOT_A_LIST', 'detail': type(raw_events).__name__}]

    # ---- 1-based indexing: a property of the WHOLE reply --------------------
    # Some models number frames 1..N however the prompt labels them. Decide it
    # once, across every index in the response, and shift. Guessing per event
    # would corrupt a correct 0-based reply that merely over-ran its final index
    # by one -- the far more common mistake. The test is deliberately strict:
    # NO index is 0, and the top of the range is exactly one past the last frame.
    _seen_idx = []
    for _it in raw_events:
        if isinstance(_it, dict):
            for _k in ('frame_start', 'frame', 'start_frame', 'frame_end', 'end_frame'):
                _v = _coerce_int(_it.get(_k))
                if _v is not None:
                    _seen_idx.append(_v)
    # min == 1 EXACTLY, not just >= 1: a model numbering frames 1..N uses 1 for
    # the opening event, whereas a 0-based reply that merely over-ran its last
    # index looks like {3 -> 12} and must NOT be shifted -- doing so would move
    # its start as well and corrupt a correct answer. Two events minimum, too:
    # one event is never enough evidence to reinterpret the whole scheme.
    one_based = (len(raw_events) >= 2 and bool(_seen_idx)
                 and min(_seen_idx) == 1 and max(_seen_idx) == n)
    if one_based:
        flags.append({'code': 'ONE_BASED_INDICES',
                      'detail': f'every index fell in 1..{n}; shifted to 0..{n - 1}'})

    events, seen = [], set()
    for pos, item in enumerate(raw_events):
        if not isinstance(item, dict):
            flags.append({'code': 'EVENT_NOT_AN_OBJECT', 'detail': f'index {pos}'})
            continue
        ev_flags = []

        # ---- frame range: the model's ONLY timing input ----------------------
        fs = _coerce_int(item.get('frame_start', item.get('frame', item.get('start_frame'))))
        fe = _coerce_int(item.get('frame_end', item.get('end_frame')))
        if one_based:
            fs = fs - 1 if fs is not None else None
            fe = fe - 1 if fe is not None else None
        if fs is None:
            flags.append({'code': 'UNPARSEABLE_FRAME_INDEX',
                          'detail': f'index {pos}: {item.get("frame_start")!r}'})
            continue
        if fe is None:
            fe = fs
        if fe < fs:
            fs, fe = fe, fs
            ev_flags.append('FRAME_RANGE_SWAPPED')
        clamp_distance = 0
        if fs < 0 or fe > n - 1:
            # Record HOW FAR out it was, not just that it happened. A frame_end
            # one past the end is an off-by-one and the clamp costs a fraction of
            # a second. A frame_end thirteen past the end is a guess, and pinning
            # it to the last frame invents "the event ran to the end of the
            # video" -- which is exactly what an end-of-video requirement asks.
            clamp_distance = max(0 - min(fs, 0), max(fe, n - 1) - (n - 1))
            fs, fe = max(0, min(fs, n - 1)), max(0, min(fe, n - 1))
            ev_flags.append(f'FRAME_INDEX_CLAMPED:{clamp_distance}')

        # ---- closed enums ----------------------------------------------------
        etype = str(item.get('type', '') or '').strip().lower().replace(' ', '_')
        if etype not in EVENT_TYPES:
            ev_flags.append(f'UNKNOWN_EVENT_TYPE:{etype[:40] or "missing"}')
            etype = 'other'
        action = item.get('action')
        if action is not None:
            action = str(action).strip().lower()
            if action in ('', 'null', 'none'):
                action = None
            elif action not in ACTION_VERBS:
                ev_flags.append(f'UNKNOWN_ACTION:{action[:40]}')
                action = None

        # ---- description, objects, confidence --------------------------------
        desc = item.get('description', '')
        desc = desc if isinstance(desc, str) else str(desc)
        desc = ' '.join(desc.split())[:cfg.max_description_chars]
        leaked = detect_judgment_language(desc)
        if leaked:
            ev_flags.append('JUDGMENT_LANGUAGE:' + ','.join(leaked[:3]))
        # If this fires, the judgment scan above cannot be trusted for this event
        # -- it only knows English. §32 reports it rather than passing quietly.
        if looks_non_english(desc):
            ev_flags.append('NON_ENGLISH_DESCRIPTION')

        objs = item.get('objects', [])
        if isinstance(objs, str):
            objs = [objs]
        objs = [str(o).strip()[:60] for o in objs if str(o).strip()] if isinstance(objs, list) else []

        conf, conf_bad = _coerce_float(item.get('confidence', cfg.default_confidence),
                                       cfg.default_confidence)
        if conf_bad:
            ev_flags.append('CONFIDENCE_DEFAULTED')
        if not (0.0 <= conf <= 1.0):
            conf = min(1.0, max(0.0, conf))
            ev_flags.append('CONFIDENCE_CLAMPED')

        # ---- OUR timestamps, from the table ----------------------------------
        rows = frame_table[fs:fe + 1] or [frame_table[fs]]
        start_s = float(rows[0]['timestamp'])
        end_s = float(rows[-1]['timestamp'])
        unreliable = any(r.get('is_approximate_ts') for r in rows)
        # A clamp of ONE is an off-by-one: the model meant "the last frame" and
        # the timestamp is right to a fraction of a second. Anything further out
        # is a guess, and the resulting boundary is not a measurement -- say so,
        # so Phase 6 widens its tolerance instead of trusting "ends at 179.0s".
        if clamp_distance > 1:
            unreliable = True
            ev_flags.append('CLAMPED_BOUND_NOT_MEASURED')

        sig = (etype, fs, fe, desc[:80])
        if sig in seen:
            flags.append({'code': 'DUPLICATE_EVENT', 'detail': f'{etype} {fs}-{fe}'})
            continue
        seen.add(sig)

        events.append({
            'id': f'vis_{len(events):03d}',
            'type': etype, 'action': action, 'description': desc,
            'objects': objs, 'confidence': round(conf, 3),
            'frame_start': fs, 'frame_end': fe,
            'start_seconds': round(start_s, 3), 'end_seconds': round(end_s, 3),
            'frame_ids': [r['frame_id'] for r in rows],
            'timestamp_unreliable': bool(unreliable),
            'flags': ev_flags,
        })

    events.sort(key=lambda e: (e['start_seconds'], e['frame_start']))
    if cfg.merge_similar_events:
        events, n_merged = merge_adjacent_events(events, cfg)
        if n_merged:
            flags.append({'code': 'MERGED_ADJACENT_EVENTS',
                          'detail': f'{n_merged} near-duplicate event(s) collapsed '
                                    f'into a continuous span'})
    for i, e in enumerate(events):
        e['id'] = f'vis_{i:03d}'
    return events, flags

def run_vlm_pass1(frame_table: list, images: list, context: str,
                  cfg: VisionConfig, generate_fn) -> dict:
    """
    One Pass-1 extraction. `generate_fn(messages, images, cfg) -> dict` is
    injected so the whole path can be exercised with a stub and no GPU (§28b).

    Never raises: every failure becomes a status plus an empty event list.
    """
    if not frame_table or not images:
        return {'status': 'NO_FRAMES', 'events': [], 'flags':
                [{'code': 'NO_FRAMES', 'detail': 'nothing to send to the model'}],
                'raw_output': '', 'attempts': 0, 'gen': {}}

    messages = build_vlm_messages(frame_table, context, cfg)
    attempts, last_err, raw, gen = 0, None, '', {}

    for attempt in range(cfg.max_repairs + 1):
        attempts += 1
        try:
            gen = generate_fn(messages, images, cfg)
        except Exception as exc:
            return {'status': 'GENERATION_FAILED', 'events': [],
                    'flags': [{'code': 'GENERATION_FAILED',
                               'detail': f'{type(exc).__name__}: {str(exc)[:200]}'}],
                    'raw_output': raw, 'attempts': attempts, 'gen': {},
                    'oom': bool(getattr(exc, 'is_oom', False))}

        raw = gen.get('text', '') or ''
        # A run that hit the token cap is INCOMPLETE BY DEFINITION, however well
        # it parses. json_repair is built to close off a cut-off object, so it
        # will happily turn a severed event list into one that looks whole --
        # and the events after the cut are simply gone, with nothing to show it.
        # Parse quality and completeness are two different questions; ask both.
        truncated = bool(gen.get('hit_token_cap'))
        obj, err, method = parse_model_json(raw)

        if obj is not None:
            events, flags = normalize_visual_events(obj, frame_table, cfg)
            if method in ('extracted', 'repaired'):
                flags.append({'code': f'JSON_{method.upper()}',
                              'detail': 'model output was not clean JSON'})
            if attempt > 0:
                flags.append({'code': 'RECOVERED_AFTER_RETRY', 'detail': f'{attempt} retry'})
            if truncated:
                # Keep what was recovered -- partial evidence beats none, and the
                # generation was expensive -- but NEVER call it OK. §29 caches
                # only OK, so this is returned for inspection and re-run, never
                # frozen into the evidence store or handed to Phase 5.
                flags.append({'code': 'TRUNCATED', 'detail':
                    f'output hit the {cfg.max_new_tokens}-token cap; {len(events)} '
                    f'event(s) recovered but any after the cut are MISSING. '
                    f'Raise max_new_tokens and re-run.'})
                return {'status': 'TRUNCATED', 'events': events, 'flags': flags,
                        'raw_output': raw, 'attempts': attempts, 'gen': gen}
            return {'status': 'OK', 'events': events, 'flags': flags,
                    'raw_output': raw, 'attempts': attempts, 'gen': gen}

        last_err = err
        if truncated:
            # The repair prompt fixes MALFORMED output, not INCOMPLETE output.
            # Regenerating against the same cap truncates at the same place, so a
            # retry here burns a second full generation to reproduce the failure.
            break
        if attempt < cfg.max_repairs:                 # one feedback retry
            messages = messages + [
                {'role': 'assistant', 'content': [{'type': 'text', 'text': raw[:1500]}]},
                {'role': 'user', 'content': [{'type': 'text',
                                              'text': PROMPT_P1_REPAIR.format(error=err)}]}]

    status = 'TRUNCATED' if gen.get('hit_token_cap') else 'PARSE_FAILED'
    detail = (f'output hit the {cfg.max_new_tokens}-token cap and could not be parsed '
              f'at all; raise max_new_tokens'
              if status == 'TRUNCATED' else str(last_err))
    return {'status': status, 'events': [],
            'flags': [{'code': status, 'detail': detail}],
            'raw_output': raw, 'attempts': attempts, 'gen': gen}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 415: print('normalize.py loaded')
