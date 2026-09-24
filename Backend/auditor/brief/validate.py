"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 97.
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
def _as_float(v) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f and abs(f) != float('inf') else None
    except (TypeError, ValueError):
        return None

def _as_list_of_str(v, cap: int = 24) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out, seen = [], set()
    for x in v:
        s = str(x).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:cap]

def _span_in_brief(span: str, brief: str) -> bool:
    """
    Did this requirement actually come from the brief?

    A model that cannot quote its source sentence invented the requirement. Exact
    substring is too strict (it normalises punctuation and case), so this compares
    content words: at least 60% of the span's content words must appear in the brief.
    """
    if not span:
        return False
    try:
        st = set(content_tokens(span))
        bt = set(content_tokens(brief))
    except Exception:
        st = set(re.findall(r'[a-z0-9]{3,}', span.lower()))
        bt = set(re.findall(r'[a-z0-9]{3,}', brief.lower()))
    if not st:
        return False
    return len(st & bt) / len(st) >= 0.6

# The model's instinct is to be helpful and compute the number. For an
# end-relative window that instinct produces a value that is right for one
# video length and silently wrong for every other one.
_END_RELATIVE_CUES = (r'\bend(?:s|ing)? with\b', r'\bat the end\b', r'\blast\s+\d+\s*s',
                      r'\bfinal\b', r'\bclos(?:e|es|ing) with\b', r'\bfinish with\b')

def _claim_backed(text: str, claims: list) -> Optional[str]:
    """
    Did this requirement come out of a CLAIMS section?

    A brief's "Key talking points" are things the creator MAY draw on, not a
    checklist of mandatory mentions. The rule engine already skips them, but a
    model reading the raw document turns each bullet into its own required
    requirement -- so a video covering two of six talking points fails four
    requirements it was never asked to satisfy. Matching them back to the
    allowlist lets them be scored as a choice instead of a checklist.
    """
    if not claims:
        return None
    try:
        rt = set(content_tokens(text))
    except Exception:
        rt = set(re.findall(r'[a-z0-9]{3,}', (text or '').lower()))
    if not rt:
        return None
    for c in claims:
        try:
            ct = set(content_tokens(c['text']))
        except Exception:
            ct = set(re.findall(r'[a-z0-9]{3,}', c['text'].lower()))
        if ct and len(ct & rt) / len(ct) >= 0.6:
            return c['text']
    return None

def normalize_requirements(raw, brief_text: str, cfg: BriefConfig = None) -> tuple:
    """
    (requirements, flags). Never raises.

    Follows the Phase 3 contract exactly: malformed input yields fewer, flagged
    requirements -- never an exception, and never a silently-dropped field.
    """
    cfg = cfg or P4.brief
    flags = []

    # The brief's approved-claims allowlist, so requirements the model derived
    # from it can be grouped as a choice rather than a checklist.
    try:
        _claims = extract_approved_claims(parse_brief_sections(brief_text))
    except Exception:
        _claims = []

    if not isinstance(raw, dict):
        return [], [{'code': 'OUTPUT_NOT_OBJECT', 'detail': type(raw).__name__}]
    items = raw.get('requirements')
    if not isinstance(items, list):
        return [], [{'code': 'REQUIREMENTS_NOT_LIST', 'detail': type(items).__name__}]
    if len(items) > cfg.max_requirements:
        flags.append({'code': 'TOO_MANY_REQUIREMENTS',
                      'detail': f'{len(items)} > {cfg.max_requirements}, truncated'})
        items = items[:cfg.max_requirements]

    out = []
    for i, item in enumerate(items):
        f = []
        if not isinstance(item, dict):
            flags.append({'code': 'REQUIREMENT_NOT_OBJECT', 'detail': f'index {i}'})
            continue
        text = str(item.get('requirement') or '').strip()
        if not text:
            flags.append({'code': 'REQUIREMENT_EMPTY', 'detail': f'index {i}'})
            continue

        # ---- type ----------------------------------------------------------
        type_ = str(item.get('type') or '').strip().lower()
        if type_ not in REQUIREMENT_TYPES:
            guess, _ = infer_requirement_type(text)
            f.append(f'TYPE_OUT_OF_ENUM:{type_ or "missing"}->{guess}')
            type_ = guess

        # ---- polarity ------------------------------------------------------
        polarity = str(item.get('polarity') or '').strip().lower()
        rule_pol, _ = infer_polarity(text)
        if polarity not in POLARITIES:
            f.append(f'POLARITY_OUT_OF_ENUM:{polarity or "missing"}->{rule_pol}')
            polarity = rule_pol
        elif polarity != rule_pol:
            f.append(f'POLARITY_DISAGREES:model={polarity},rules={rule_pol}')

        # ---- evidence_mode: the field that matters most --------------------
        mode = str(item.get('evidence_mode') or '').strip().lower()
        inferred = infer_evidence_mode(text)
        if mode not in EVIDENCE_MODES:
            fallback = inferred['mode'] or TYPE_DEFAULT_MODE.get(type_, 'any')
            f.append(f'MODE_OUT_OF_ENUM:{mode or "missing"}->{fallback}')
            mode = fallback
        elif inferred['mode'] and inferred['mode'] != mode:
            # NOT auto-corrected. The LLM reads context the regex cannot, and the
            # regex is immune to the plausible-sounding mistakes the LLM makes.
            # Neither is authoritative, so the human decides -- product.md §37 is
            # the one field where a silent wrong answer inverts a verdict.
            f.append(f'MODE_DISAGREES:model={mode},rules={inferred["mode"]}'
                     f'({inferred["reason"]})')
        if not inferred['confident'] and inferred['mode'] is None:
            f.append('MODE_NO_CUE:defaulted_by_type')

        # ---- priority / weight ---------------------------------------------
        priority = str(item.get('priority') or '').strip().lower()
        if priority not in PRIORITIES:
            guess, _ = infer_priority(text, type_, polarity)
            f.append(f'PRIORITY_OUT_OF_ENUM:{priority or "missing"}->{guess}')
            priority = guess
        weight = PRIORITY_WEIGHT[priority]

        # ---- machine_checkable ---------------------------------------------
        mc = item.get('machine_checkable')
        rule_mc, rule_why = is_machine_checkable(text, type_)
        if not isinstance(mc, bool):
            f.append(f'MACHINE_CHECKABLE_MISSING->{rule_mc}')
            mc = rule_mc
        elif mc and not rule_mc:
            f.append(f'VAGUE_BUT_MARKED_CHECKABLE:{rule_why}')

        # ---- temporal, absolute --------------------------------------------
        deadline = _as_float(item.get('deadline_seconds'))
        if deadline is not None:
            if deadline <= 0:
                f.append(f'DEADLINE_NOT_POSITIVE:{deadline}')
                deadline = None
            elif deadline > cfg.max_plausible_deadline:
                f.append(f'DEADLINE_IMPLAUSIBLE:{deadline}')
                deadline = None
        ws_abs = _as_float(item.get('window_start_seconds'))
        we_abs = _as_float(item.get('window_end_seconds'))

        # ---- temporal, symbolic --------------------------------------------
        ws_expr = item.get('window_start_expr')
        we_expr = item.get('window_end_expr')
        for name, val in (('window_start_expr', ws_expr), ('window_end_expr', we_expr)):
            if val in (None, ''):
                continue
            ok, err = validate_time_expr(str(val))
            if not ok:
                f.append(f'{name.upper()}_INVALID:{err}')
                if name == 'window_start_expr':
                    ws_expr = None
                else:
                    we_expr = None
        ws_expr = str(ws_expr) if ws_expr not in (None, '') else None
        we_expr = str(we_expr) if we_expr not in (None, '') else None

        # ---- cross-check the temporal extraction against §40b --------------
        rule_t = extract_temporal(text, type_, cfg)
        if rule_t['deadline_seconds'] is not None and deadline is None:
            f.append(f'DEADLINE_MISSED_BY_MODEL:rules_found={rule_t["deadline_seconds"]}')
            deadline = rule_t['deadline_seconds']
        # The cross-check used to run in ONE direction only: it fired when the
        # model supplied NOTHING. A model that supplied a WRONG number passed
        # silently, because validate_time_expr only checks that an expression
        # parses. On the 5f18775d audit the model produced "duration - 15" for
        # every CTA requirement while the brief never mentions 15 seconds, and
        # on a 12.35s video that clamps to 0 -- so the constraint did nothing
        # and nothing said so.
        if rule_t['window_start_expr'] and ws_expr and \
                rule_t['window_start_expr'] != ws_expr:
            f.append(f'WINDOW_DISAGREES_WITH_BRIEF:model={ws_expr};'
                     f'rules={rule_t["window_start_expr"]}')
        # A number the brief never states is the model's invention. The brief
        # text is the only authority for a number that constrains the creator.
        if ws_expr and not rule_t['window_start_expr']:
            _nums = re.findall(r'\d+(?:\.\d+)?', str(ws_expr))
            _unsupported = [n for n in _nums
                            if not re.search(r'\b' + re.escape(n.rstrip('.0') or n)
                                             + r'\b', text or '')]
            if _unsupported:
                f.append(f'WINDOW_UNSUPPORTED_BY_BRIEF:{ws_expr};'
                         f'not_in_brief={",".join(_unsupported)}')
        if rule_t['window_start_expr'] and not ws_expr and ws_abs is None:
            f.append(f'WINDOW_MISSED_BY_MODEL:rules_found={rule_t["window_start_expr"]}')
            ws_expr, we_expr = rule_t['window_start_expr'], rule_t['window_end_expr']

        # ---- the "helpfully computed 25.0" trap ----------------------------
        if _has(_END_RELATIVE_CUES, text) and ws_abs is not None and not ws_expr:
            f.append(f'END_RELATIVE_HARDCODED:{ws_abs}->duration - '
                     f'{cfg.default_cta_window:g}')
            ws_expr = f'duration - {cfg.default_cta_window:g}'
            we_expr = we_expr or 'duration'
            ws_abs, we_abs = None, None
        if ws_abs is not None and we_abs is not None and ws_abs > we_abs:
            f.append(f'WINDOW_INVERTED:{ws_abs}>{we_abs}')
            ws_abs, we_abs = we_abs, ws_abs

        # ---- forbidden requirements must name what to look for -------------
        claim_classes = [c for c in _as_list_of_str(item.get('claim_classes'))
                         if c.lower() in CLAIM_CLASSES]
        bad_classes = [c for c in _as_list_of_str(item.get('claim_classes'))
                       if c.lower() not in CLAIM_CLASSES]
        if bad_classes:
            f.append(f'CLAIM_CLASS_OUT_OF_ENUM:{",".join(bad_classes[:3])}')
        if polarity == 'forbidden' and not claim_classes:
            claim_classes = infer_claim_classes(text)
            f.append(f'CLAIM_CLASSES_MISSING->{",".join(claim_classes)}')

        # ---- hints ----------------------------------------------------------
        hints = _as_list_of_str(item.get('match_hints'))
        if not hints:
            hints = rule_match_hints(text)
            f.append('MATCH_HINTS_MISSING:generated_from_rules')
        criteria = _as_list_of_str(item.get('acceptance_criteria')) or [text]

        # ---- provenance: did this come from the brief at all? --------------
        span = str(item.get('brief_span') or '').strip()
        if not span:
            f.append('BRIEF_SPAN_MISSING')
            span = text
        if not _span_in_brief(span, brief_text):
            # The strongest hallucination signal available at this stage.
            f.append('SPAN_NOT_IN_BRIEF:possible_invention')

        conf = _as_float(item.get('confidence'))
        conf = 0.6 if conf is None else max(0.0, min(1.0, conf))
        if any(x.startswith(('SPAN_NOT_IN_BRIEF', 'MODE_DISAGREES')) for x in f):
            conf = min(conf, 0.4)

        # ---- choice groups --------------------------------------------------
        group = item.get('group')
        group = str(group).strip() if group not in (None, '') else None
        gmode = str(item.get('group_mode') or 'all_of').strip().lower()
        if gmode not in GROUP_MODES:
            f.append(f'GROUP_MODE_OUT_OF_ENUM:{gmode}->all_of')
            gmode = 'all_of'
        if group is None and gmode != 'all_of':
            # A choice mode with nothing to choose between would be scored as a
            # group of one, which silently makes an ordinary requirement optional.
            f.append(f'GROUP_MODE_WITHOUT_GROUP:{gmode}->all_of')
            gmode = 'all_of'

        # A requirement the model derived from the approved-claims allowlist is
        # a talking point, not an obligation. Group them as any_of: the video
        # must cover at least one, not every single one.
        if group is None and polarity == 'required':
            # Match on brief_span FIRST -- that field is the model's quotation of
            # the source sentence, so it is the claim verbatim. The requirement
            # text is a paraphrase ("Mention that the product reduces hair loss
            # by 27%" vs "Reduce hair loss by 27% after 3 months"), and paraphrase
            # overlap alone falls below any threshold worth using.
            _src_claim = (_claim_backed(str(item.get('brief_span') or ''), _claims)
                          or _claim_backed(text, _claims))
            if _src_claim:
                # PROVENANCE ONLY -- this must not change the scoring shape.
                # Grouping here made the unit count depend on a fuzzy match.
                f.append(f'FROM_APPROVED_CLAIMS:{_src_claim[:48]}')

        out.append(Requirement(
            id=requirement_id(text, type_), ordinal=len(out) + 1,
            label=make_label(text), requirement=text, type=type_,
            priority=priority, weight=weight, polarity=polarity,
            evidence_mode=mode, machine_checkable=bool(mc),
            group=group, group_mode=gmode,
            group_label=(str(item.get('group_label') or '')[:80]
                         or ('Approved talking points'
                             if group == 'approved_talking_points' else '')),
            group_intent=str(item.get('group_intent') or '')[:300],
            deadline_seconds=deadline,
            window_start_seconds=ws_abs, window_end_seconds=we_abs,
            window_start_expr=ws_expr, window_end_expr=we_expr,
            match_hints=hints, acceptance_criteria=criteria,
            forbidden_evidence=_as_list_of_str(item.get('forbidden_evidence')),
            claim_classes=claim_classes,
            source=str(item.get('source') or 'brief'),
            brief_span=span, confidence=round(conf, 3), flags=f))

    if not out:
        flags.append({'code': 'NO_VALID_REQUIREMENTS', 'detail': f'{len(items)} items in'})
    return out, flags

def pydantic_check(reqs: list) -> list:
    """
    An EXTRA strictness pass, never the authority.

    product.md §28 asks for Pydantic. It runs when importable and its errors join
    the flag list; it is not load-bearing, because a v1/v2 difference in a Colab
    image we do not control must not be able to stop a brief from compiling.
    """
    try:
        import pydantic
        from pydantic import BaseModel
    except Exception:
        return [{'code': 'PYDANTIC_UNAVAILABLE', 'detail': 'skipped strict pass'}]
    v2 = int(str(pydantic.VERSION).split('.')[0]) >= 2
    try:
        from typing import Literal, List, Optional as Opt

        class _R(BaseModel):
            id: str
            type: Literal[REQUIREMENT_TYPES]           # type: ignore[valid-type]
            requirement: str
            priority: Literal[PRIORITIES]              # type: ignore[valid-type]
            evidence_mode: Literal[EVIDENCE_MODES]     # type: ignore[valid-type]
            polarity: Literal[POLARITIES]              # type: ignore[valid-type]
            weight: float
            machine_checkable: bool
            deadline_seconds: Opt[float] = None
            acceptance_criteria: List[str] = []

        errs = []
        for r in reqs:
            d = r.to_dict()
            try:
                (_R.model_validate if v2 else _R.parse_obj)(d)
            except Exception as e:
                errs.append({'code': 'PYDANTIC_INVALID', 'detail': f'{r.id}: {str(e)[:160]}'})
        return errs
    except Exception as e:
        return [{'code': 'PYDANTIC_SETUP_FAILED', 'detail': str(e)[:160]}]


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 371: print('§43 normaliser loaded (never raises).')
