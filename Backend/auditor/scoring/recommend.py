"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 140.
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
RECOMMEND_STAGE_VERSION = '1.0.0'

RECOMMEND_PROMPT_VERSION = 'p7_recommend_v1'

RECOMMEND_SYSTEM = """You propose concrete edits to a short-form video so it \
better matches a creative brief.

You are given requirements the video did NOT fully meet, the evidence behind \
each, and -- separately -- what the video ALREADY does well.

RULES, all of them hard:

1. Propose EDITS, never judgements. "Add one sentence naming the wheat-seed \
oil right after the application shot" is an edit. "Improve the messaging" is \
not, and is useless to a creator.

2. Anchor every edit to a TIMESTAMP taken from the evidence you were shown. \
Use the `at` field of a record you cite. Never invent a time.

3. Cite evidence by the exact ids given. You may only cite ids that appear in \
the material above. Inventing an id invalidates the recommendation.

4. Do NOT write numbers, scores, percentages, grades, or the words PASS, \
FAIL, PARTIAL, UNCERTAIN, APPROVED or REJECTED. You are not reporting a \
result; you are proposing a change.

5. PRESERVE what works. If the opening already does its job, say so in \
`keep` and do not propose changing it.

6. If there is nothing meaningful to fix, return an empty `recommendations` \
list. An empty list is a valid and useful answer. Do not pad.

Return ONLY this JSON:

{
  "recommendations": [
    {"requirement_id": "<the id this addresses>",
     "edit": "<one concrete change, imperative, under 200 characters>",
     "at_seconds": <number taken from a cited record>,
     "evidence_ids": ["<id>", ...],
     "effort": "trivial" | "small" | "reshoot"}
  ],
  "keep": ["<something the video already does well, one short line>", ...]
}"""

# Words a recommendation may not contain. Matched on WORD boundaries -- the
# substring form would reject "passing" for containing "pass", and would have
# rejected a perfectly good edit mentioning someone's shoulder.
_REC_BANNED_WORDS = ('pass', 'passed', 'fail', 'failed', 'partial', 'uncertain',
                     'approved', 'rejected', 'score', 'scored', 'scores',
                     'grade', 'rating', 'percent', 'compliant')

_REC_NUMERIC = re.compile(r'\d+\s?%|\b\d{1,3}\s*(?:out of|/)\s*\d{1,3}\b')

def _rec_violations(text: str) -> list:
    """What rule 4 forbids, found in one recommendation."""
    low = f' {(text or "").lower()} '
    bad = [w for w in _REC_BANNED_WORDS
           if re.search(rf'(?<!\w){re.escape(w)}(?!\w)', low)]
    if _REC_NUMERIC.search(text or ''):
        bad.append('numeric-score-like')
    return bad

def _rec_digest(units: list, records_by_id: dict, limit_chars: int = 220) -> tuple:
    """
    The failing units, each with the evidence actually behind it.

    Returns (lines, offered_ids). `offered_ids` is the citable set -- the same
    contract L3 uses, and the thing that makes a fabricated citation detectable
    rather than merely unlikely.
    """
    lines, offered = [], set()
    for v in units:
        rid = v.get('requirement_id', '')
        lines.append(f'REQUIREMENT {rid}  [{v.get("requirement_label", "")[:90]}]')
        lines.append(f'  the brief asks: {str(v.get("requirement_label") or "")[:160]}')
        lines.append(f'  what we found : {str(v.get("reason") or "")[:limit_chars]}')
        cited = list(v.get('evidence_ids') or []) or list(v.get('examined_ids') or [])
        if not cited:
            lines.append('  evidence      : none cited')
        for eid in cited[:6]:
            r = records_by_id.get(eid)
            if r is None:
                continue
            offered.add(eid)
            body = (getattr(r, 'raw_text', '') or getattr(r, 'description', '')
                    or '').strip().replace('\n', ' ')
            lines.append(f'  [{eid}] at {getattr(r, "start_seconds", 0.0):.2f}s '
                         f'({getattr(r, "modality", "?")}) {body[:limit_chars]}')
        lines.append('')
    return lines, offered

def evaluate_recommendations(result: dict, compiled: dict, score: dict,
                             records: list, backend=None,
                             cfg: Phase7Config = None, force: bool = False,
                             verbose: bool = True) -> dict:
    """Concrete, timestamp-anchored edits. Never raises."""
    cfg = cfg or P7
    t0 = time.time()
    out = {
        'enabled': bool(cfg.recommend.enabled),
        'recommendations': [], 'keep': [], 'layer': 'L3',
        'prompt_version': RECOMMEND_PROMPT_VERSION,
        'schema_version': RECOMMEND_STAGE_VERSION,
        'considered_units': 0, 'flags': [], 'violations': [],
        'disclaimer': ('Suggested edits, generated from the requirements this '
                       'video did not fully meet. They are proposals for a '
                       'human to weigh, not instructions, and they carry no '
                       'score -- every number in this report comes from §76.'),
    }
    if not cfg.recommend.enabled:
        out['note'] = 'Recommendations are switched off in P7.recommend.'
        return out

    # Question 1 first. Proposing "add one sentence about barrier support at
    # 0:11" to someone who filmed a pill organiser is not advice, it is
    # nonsense -- and worse, it implies the video is nearly right. When the
    # relevance gate is closed the only honest recommendation is about the
    # video as a whole, so this abstains and says why.
    _gate = (score or {}).get('relevance') or {}
    if _gate and not _gate.get('scorable', True):
        out['flags'].append('RECOMMEND_GATED_OFF_BRIEF')
        out['note'] = (
            f'No edits proposed. Read whole, this video is '
            f'{_gate.get("level")} for this brief, and per-requirement edits '
            f'would imply it is nearly right. What is needed is a different '
            f'video for this brief, or the brief this video was actually '
            f'shot for -- a judgement for a human, not a list of cuts.')
        out['considered_units'] = 0
        return out

    verdicts = result.get('verdicts') or []
    # ONLY the units that fell short. A PASS does not generate advice.
    todo = [v for v in verdicts if v.get('status') in ('FAIL', 'PARTIAL')]
    out['considered_units'] = len(todo)
    if not todo:
        # Abstain, loudly and correctly. This is the good case.
        out['note'] = ('Nothing to fix: no requirement came back FAIL or '
                       'PARTIAL. An empty list here is a result, not a gap.')
        return out

    if not P6.l3.enabled:
        out['flags'].append('RECOMMEND_L3_DISABLED')
        out['note'] = 'The language model is disabled, and this step needs it.'
        return out

    records_by_id = {r.id: r for r in (records or [])}
    lines, offered = _rec_digest(todo, records_by_id)
    passing = [v for v in verdicts if v.get('status') == 'PASS'
               and not any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))]
    if passing:
        lines.append('=' * 60)
        lines.append('WHAT THE VIDEO ALREADY DOES WELL -- do not propose undoing these:')
        for v in passing[:cfg.recommend.include_passing_context]:
            lines.append(f'  - {str(v.get("requirement_label") or "")[:110]}')
        lines.append('')
    lines.append(f'Propose at most {cfg.recommend.max_items} edits, most '
                 f'valuable first.')

    bcfg = replace(P4.brief, temperature=cfg.recommend.temperature,
                   max_new_tokens=1600)
    try:
        backend = backend or make_brief_backend(bcfg, verbose=verbose)
        gen = backend.complete(RECOMMEND_SYSTEM, '\n'.join(lines), bcfg)
        obj, perr, _method = parse_model_json(gen.get('text', '') or '')
        out['backend'] = gen.get('backend') or getattr(backend, 'name', '')
    except Exception as exc:
        obj, perr = None, f'{type(exc).__name__}: {str(exc)[:110]}'
    if not isinstance(obj, dict):
        out['flags'].append('RECOMMEND_PARSE_FAILED')
        out['note'] = f'The model returned nothing usable ({perr}).'
        return out

    seen_ids = set()
    for item in (obj.get('recommendations') or [])[:cfg.recommend.max_items]:
        if not isinstance(item, dict):
            continue
        edit = str(item.get('edit') or '').strip()[:cfg.recommend.max_chars]
        if not edit:
            continue
        rid = str(item.get('requirement_id') or '')

        # Rule 3: only offered ids are citable.
        cited = [str(i) for i in (item.get('evidence_ids') or [])]
        bad_ids = [i for i in cited if i not in offered]
        good_ids = [i for i in cited if i in offered]
        if bad_ids:
            out['violations'].append({'code': 'FABRICATED_EVIDENCE_ID',
                                      'requirement_id': rid,
                                      'detail': str(bad_ids[:3])})

        # Rule 4: the model does not get to write numbers.
        banned = _rec_violations(edit)
        if banned:
            out['violations'].append({'code': 'FORBIDDEN_WORDING',
                                      'requirement_id': rid,
                                      'detail': str(banned[:4])})
            continue            # dropped, not silently cleaned

        # Rule 2: the anchor must be a real record's time.
        at = item.get('at_seconds')
        anchor_ok = False
        try:
            at = None if at is None else round(float(at), 2)
        except (TypeError, ValueError):
            at = None
        if at is not None:
            for eid in good_ids:
                r = records_by_id.get(eid)
                if r is None:
                    continue
                if (getattr(r, 'start_seconds', -99) - 1.0 <= at
                        <= getattr(r, 'end_seconds', -99) + 1.0):
                    anchor_ok = True
                    break
        if at is not None and not anchor_ok:
            out['violations'].append({'code': 'ANCHOR_NOT_IN_CITED_EVIDENCE',
                                      'requirement_id': rid,
                                      'detail': f'{at}s matches no cited record'})
            at = None           # the edit survives; the invented time does not

        key = (rid, edit[:60])
        if key in seen_ids:
            continue
        seen_ids.add(key)
        out['recommendations'].append({
            'requirement_id': rid,
            'edit': edit,
            'at_seconds': at,
            'evidence_ids': good_ids[:6],
            'effort': (item.get('effort')
                       if item.get('effort') in ('trivial', 'small', 'reshoot')
                       else 'small'),
        })

    for k in (obj.get('keep') or [])[:6]:
        k = str(k).strip()[:200]
        if k and not _rec_violations(k):
            out['keep'].append(k)

    if out['violations']:
        out['flags'].append(f'RECOMMEND_VIOLATIONS:{len(out["violations"])}')
    if not out['recommendations']:
        out['note'] = ('The model proposed nothing that survived the citation '
                       'and wording rules.')
    out['seconds'] = round(time.time() - t0, 3)
    if verbose:
        print(f'  recommendations: {len(out["recommendations"])} edit(s) from '
              f'{len(todo)} shortfall(s)'
              + (f', {len(out["violations"])} rejected' if out['violations'] else ''))
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 274: print('§78 recommendations loaded.  The only model call in Phase 7.')
#   line 275: print('  FAIL/PARTIAL only | anchors must be real record times | ids validat
#   line 276: print('  No number, score or status word may appear in the output.')
