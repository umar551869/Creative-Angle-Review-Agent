"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 124.
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
L3_SYSTEM = """You are a compliance adjudicator for short-form video briefs.

You are given REQUIREMENTS and, for each, a numbered list of EVIDENCE records
extracted from one video by an automated pipeline. Decide whether the evidence
satisfies each requirement.

RULES, in order of importance:
1. Cite ONLY evidence ids that appear in that requirement's candidate list.
   Never invent an id. If nothing fits, cite nothing.
2. The evidence is all you have. You cannot see the video. Do not infer what
   probably happened between the moments the evidence describes.
3. Use exactly these statuses:
   PASS       - the cited evidence satisfies the requirement
   PARTIAL    - satisfied weakly, late, or in only one of two required modalities
   FAIL       - the requirement is NOT met by the evidence you were shown.
                TWO ways that happens, and both are FAIL:
                  (a) the evidence CONTRADICTS the requirement, or
                  (b) the requirement asks for something and, having read all
                      the evidence offered, it is simply NOT THERE.
                "She never mentions it" is a FAIL, not an UNCERTAIN. You looked
                and it was absent -- that is a finding about the video.
   UNCERTAIN  - you genuinely CANNOT TELL from what you were given: the
                evidence is garbled, truncated, ambiguous, or too sparse to
                read. Not "the thing is missing" -- that is FAIL -- but "I
                cannot see well enough to say either way".
   The difference is about YOUR ABILITY TO SEE, not about how the video did.
   A clean transcript with no mention of allergens supports a FAIL. A garbled
   one does not.
   Prefer UNCERTAIN over guessing. An unsupported verdict is worse than none.
4. `reason` is one sentence a human can check against the evidence you cited.
   Quote the wording you relied on. Do not restate the requirement.

Return ONLY a JSON object, no prose and no code fence:
{"verdicts": [{"requirement_id": "...", "status": "...",
               "evidence_ids": ["..."], "reason": "...",
               "confidence": 0.0}]}"""

# The adjudicator judges TWO things now, and must not let one decide the other.
L3_SYSTEM = L3_SYSTEM + """

SECOND JUDGEMENT -- ALIGNMENT.

The status above answers "did she do what the requirement literally states?".
Alignment answers a different question: "how close is what she ACTUALLY did to
what this requirement was FOR?"

A brief listing twelve hooks is describing the KIND of opening it wants, not
demanding one of twelve sentences. A creator who writes her own hook in that
spirit has done what the brief asked. Say so in `alignment`, even when the
status is FAIL because the literal wording is absent.

ALIGNMENT ANCHORS -- use these words, not your own scale, and never a number:
  exact       the brief's own wording, or a trivial variation of it
  strong      different words, same ask and same intent -- she wrote her own
              version of what the brief described
  partial     on the brief's subject and partly does the job, but misses part
              of what was asked
  tangential  about the product or topic, but not what THIS requirement was for
  none        unrelated to the requirement, or absent altogether

WORKED EXAMPLE. Take a requirement reading:
    Use the hook: "Your shampoo isn't the problem."

  exact       she says "your shampoo isn't the problem"
  strong      she opens "everyone blames their shampoo -- it's honestly not
              that" -- different words, same move: name the wrong culprit and
              create doubt. This is a STRONG alignment, not a failure.
  partial     she opens by talking about shampoo but makes no claim and creates
              no tension. The subject is right; the hook is not.
  tangential  she opens by naming the product and its price. On topic, but not
              an opening of the kind this group describes.
  none        she opens "hi guys, welcome back" -- an introduction, not a hook.

Note what `strong` means there. The creator did NOT use the brief's sentence,
and the STATUS is FAIL because the literal wording is absent -- but the
ALIGNMENT is strong, because she did the thing the brief was asking for. Those
two readings are independent and you must give both.

When a CHOICE GROUP is shown above, judge alignment against the kind of ask the
whole group describes, not against the single sentence of this one option.

Judge alignment from the SAME cited evidence. If you cannot tell, omit it.

Add these two keys to every verdict object:
  "alignment": "exact|strong|partial|tangential|none",
  "alignment_reason": "one sentence naming what she did instead"
"""

def _evidence_line(rec) -> str:
    """One evidence record, as the model sees it."""
    t = f'{rec.start_seconds:.2f}-{rec.end_seconds:.2f}s'
    tol = rec.time_tolerance_seconds or 0.0
    if tol:
        t += f' (+-{tol:.2f}s)'
    body = (rec.raw_text or rec.description or '').strip().replace('\n', ' ')
    extra = ''
    if rec.modality == 'ocr' and rec.independence:
        extra = f' [independence:{rec.independence}]'
    if rec.modality == 'visual':
        extra = f' [type:{rec.type}]'
    return f'  - id={rec.id} [{rec.modality}] {t}{extra}: "{body[:200]}"'

def build_l3_prompt(batch: list, duration: float, groups: dict = None) -> str:
    """
    batch = [(requirement_dict, candidates)].

    `groups` maps a group id to every requirement in it, and it is what makes
    alignment judgeable. Without it the adjudicator sees ONE hook sentence and
    the creator's actual opening, and is asked how closely they align -- with no
    way to know that eleven other sentences describe the same KIND of opening.
    A brief listing twelve hooks is describing a kind; the kind is only visible
    in the set.
    """
    groups = groups or {}
    out = [f'VIDEO DURATION: {duration:.2f}s', '']
    for rd, cands in batch:
        out.append(f'REQUIREMENT id={rd.get("id")}')
        _gid = rd.get('group')
        _sibs = [r for r in (groups.get(_gid) or []) if r.get('id') != rd.get('id')]
        _gintent = str(rd.get('group_intent') or '').strip()
        # THE ASK FIRST, the example second. A menu option rendered as the
        # `text` line reads as the requirement, and the model answers it
        # literally -- measured: ten hook options, ten `alignment: none`, each
        # reason naming "the specified phrase", on a video whose opening was
        # cited correctly and plainly belonged to the group.
        if _gid and _sibs and _gintent:
            out.append(f'  THE ASK       : {_gintent}')
            out.append(f'  this option   : one EXAMPLE of that ask, worded '
                       f'"{str(rd.get("requirement", ""))[:150]}"')
            out.append('  status judges THIS option\'s wording. alignment '
                       'judges THE ASK, in any wording.')
        else:
            out.append(f'  text          : {rd.get("requirement", "")}')
        out.append(f'  evidence_mode : {rd.get("evidence_mode")}')
        if _gid and _sibs:
            out.append(f'  choice group  : one of {len(_sibs) + 1} in '
                       f'"{rd.get("group_label") or _gid}" '
                       f'({rd.get("group_mode", "one_of")} -- the creator picks ONE)')
            _intent = str(rd.get('group_intent') or '').strip()
            if _intent and not _gintent:
                # THE line that moved both models from `none` to `partial`.
                # Without it they compare her words to the quoted sentence, which
                # is what the requirement literally says; with it they compare
                # what she DID to what the brief WANTED.
                out.append(f'  WHAT THE GROUP IS ASKING FOR: {_intent}')
                out.append('  The quoted sentences are EXAMPLES of that ask, not')
                out.append('  the ask itself. Judge ALIGNMENT against the ask.')
            out.append('  the SAME group also offers:')
            for r in _sibs[:11]:
                out.append(f'      - {str(r.get("requirement", ""))[:96]}')
            if len(_sibs) > 11:
                out.append(f'      ... and {len(_sibs) - 11} more')
            out.append('  ^ these are examples of ONE kind of ask. Judge ALIGNMENT')
            out.append('    against that kind, not against this one sentence.')
        _hints = [str(h) for h in (rd.get('match_hints') or []) if h]
        if _hints:
            out.append(f'  words that would satisfy '
                       f'{"THIS OPTION" if (_gid and _sibs) else "it"} '
                       f'literally: {", ".join(_hints[:10])}')
        res = rd.get('resolved') or {}
        if res.get('deadline_seconds') is not None:
            out.append(f'  deadline      : within {res["deadline_seconds"]}s')
        if res.get('window_start_seconds') is not None:
            out.append(f'  window        : {res.get("window_start_seconds")}'
                       f'-{res.get("window_end_seconds")}s')
        for ac in (rd.get('acceptance_criteria') or [])[:4]:
            out.append(f'  accept if     : {ac}')
        if cands:
            out.append('  CANDIDATE EVIDENCE:')
            out.extend(_evidence_line(c['record']) for c in cands)
        else:
            out.append('  CANDIDATE EVIDENCE: (none retrieved)')
        out.append('')
    return '\n'.join(out)

def _validate_l3(obj: dict, allowed: dict, batch_ids: set) -> tuple:
    """
    (verdict dicts, violations). THE anti-hallucination check.

    Two ways a response can lie about provenance: cite an id that does not
    exist, or cite a real id that belonged to a DIFFERENT requirement. Both are
    rejected -- the second is subtler and would attribute one requirement's
    evidence to another.
    """
    good, bad = [], []
    for v in (obj or {}).get('verdicts') or []:
        if not isinstance(v, dict):
            bad.append('non-object verdict')
            continue
        rid = str(v.get('requirement_id') or '')
        if rid not in batch_ids:
            bad.append(f'unknown requirement_id {rid!r}')
            continue
        ids = [str(i) for i in (v.get('evidence_ids') or [])]
        allow = allowed.get(rid, set())
        invented = [i for i in ids if i not in allow]
        if invented:
            bad.append(f'{rid}: cited {invented[:3]} which were not offered')
            continue
        st = str(v.get('status') or '').upper()
        if st not in VERDICT_STATUSES:
            bad.append(f'{rid}: status {st!r} is not a valid verdict')
            continue
        # Alignment is CLOSED-ENUM or nothing. A model that invents a level, or
        # returns a number because it decided a scale was more precise, gets
        # None -- which reads as "nobody judged it" rather than silently
        # entering a value Phase 7 would then weight.
        al = str(v.get('alignment') or '').lower().strip()
        good.append({'requirement_id': rid, 'status': st, 'evidence_ids': ids,
                     'reason': str(v.get('reason') or '')[:400],
                     'confidence': v.get('confidence'),
                     'alignment': al if al in ALIGNMENT_LEVELS else None,
                     'alignment_reason': str(v.get('alignment_reason') or '')[:300],
                     'alignment_raw': al})
    return good, bad

def evaluate_l3_batch(batch: list, health: dict, duration: float,
                      backend=None, cfg: Phase6Config = None,
                      verbose: bool = True, groups: dict = None) -> tuple:
    """
    ({requirement_id: Verdict}, stats). Never raises.

    A backend failure is a degraded audit, not a crashed one: everything in the
    batch comes back UNCERTAIN with a flag saying why.
    """
    cfg = cfg or P6
    stats = {'calls': 0, 'violations': [], 'backend': None, 'repaired': 0}
    if not batch:
        return {}, stats
    if not cfg.l3.enabled:
        return ({rd['id']: _blank_verdict(rd, 'UNCERTAIN',
                                          'L3 is disabled; no layer could decide this.',
                                          'L3', flags=['L3_DISABLED'])
                 for rd, _ in batch}, stats)

    allowed = {rd['id']: set(candidate_ids(c)) for rd, c in batch}
    batch_ids = set(allowed)
    user = build_l3_prompt(batch, duration, groups)
    bcfg = replace(P4.brief, temperature=cfg.l3.temperature,
                   max_new_tokens=cfg.l3.max_new_tokens)

    out, notes = {}, []
    for attempt in range(cfg.l3.max_repair_retries + 1):
        try:
            backend = backend or make_brief_backend(bcfg, verbose=verbose)
            gen = backend.complete(L3_SYSTEM, user, bcfg)
            stats['calls'] += 1
            stats['backend'] = getattr(backend, 'name', 'unknown')
        except Exception as exc:
            notes.append(f'{type(exc).__name__}: {str(exc)[:140]}')
            break
        obj, perr, _method = parse_model_json(gen.get('text', '') or '')
        if obj is None:
            notes.append(f'unparseable response: {perr}')
            user += ('\n\nYour previous reply was not valid JSON. Return ONLY the '
                     'JSON object described above.')
            continue
        good, bad = _validate_l3(obj, allowed, batch_ids)
        # Deduplicate. A repair retry re-reports the violations that triggered
        # it, so extending blindly counts one rejection twice and the guard
        # reads as having fired more often than it did.
        for _b in bad:
            if _b not in stats['violations']:
                stats['violations'].append(_b)
        for v in good:
            rd = next(r for r, _ in batch if r['id'] == v['requirement_id'])
            conf = v['confidence']
            out[v['requirement_id']] = _blank_verdict(
                rd, v['status'], v['reason'] or 'Adjudicated by the language model.',
                'L3', evidence_ids=v['evidence_ids'],
                confidence=(float(conf) if isinstance(conf, (int, float)) else None),
                confidence_kind='llm_self_report',
                alignment=v.get('alignment'),
                alignment_reason=v.get('alignment_reason', ''),
                candidates_considered=len(allowed[v['requirement_id']]))
            if v.get('alignment_raw') and not v.get('alignment'):
                out[v['requirement_id']].flags.append(
                    f'ALIGNMENT_OUT_OF_ENUM:{str(v["alignment_raw"])[:24]}')
        if not bad and len(out) == len(batch_ids):
            break
        if bad and attempt < cfg.l3.max_repair_retries:
            stats['repaired'] += 1
            user += ('\n\nYour previous reply cited evidence ids that were not '
                     'offered for that requirement. Cite ONLY ids from that '
                     "requirement's candidate list, or none at all.")

    # A FAIL from the model still has to pass the health gate -- the model does
    # not get to overrule a degraded modality just because it sounded confident.
    for rid, v in list(out.items()):
        rd = next(r for r, _ in batch if r['id'] == rid)
        if v.status == 'FAIL' and not _fail_allowed(rd, health):
            out[rid] = _blank_verdict(
                rd, 'UNCERTAIN',
                f'The model judged this a FAIL ({v.reason[:150]}) but the '
                f'modality it relies on was degraded, so the absence is not '
                f'evidence.',
                'L3', evidence_ids=v.evidence_ids,
                flags=['FAIL_BLOCKED_BY_MODALITY_HEALTH', 'L3_FAIL_DOWNGRADED'],
                # the ALIGNMENT reading survives the downgrade: the modality
                # being degraded makes absence uninterpretable, it does not
                # unmake what the model saw in the evidence it did have
                alignment=v.alignment, alignment_reason=v.alignment_reason,
                candidates_considered=v.candidates_considered)

    for rd, cands in batch:                      # anything the model skipped
        if rd['id'] not in out:
            out[rd['id']] = _blank_verdict(
                rd, 'UNCERTAIN',
                'The adjudicator returned no usable verdict for this requirement. '
                + ('; '.join(notes[:2]) if notes else ''),
                'L3', flags=['L3_NO_VERDICT'],
                candidates_considered=len(cands))
    if stats['violations'] and verbose:
        _v = stats['violations']
        print(f'  L3 rejected {len(_v)} citation violation(s):')
        for _line in _v[:5]:
            print(f'      {_line}')
        if len(_v) > 5:
            print(f'      ... and {len(_v) - 5} more')
    return out, stats


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 332: print('§67 L3 loaded.  Only offered evidence ids are citable; violations are
