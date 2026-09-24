"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 100.
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
_TICK, _CROSS, _WARN = '[x]', '[ ]', '(!)'

def render_requirements_table(compiled: dict, show_flags: bool = True) -> str:
    """Readable review table, shakiest rows first."""
    reqs = compiled.get('requirements', [])
    if not reqs:
        return f'No requirements. status={compiled.get("status")}'
    order = sorted(reqs, key=lambda r: (r.get('confidence', 0.5),
                                        -len(r.get('flags', []))))
    L = []
    L.append('=' * 100)
    L.append(f'COMPILED BRIEF   {compiled.get("campaign") or "(no campaign name)"}'
             f'    hash {compiled.get("brief_hash")}   backend {compiled.get("backend")}')
    # Which code produced this. A cached artifact from an older version is
    # indistinguishable from a fresh one without it -- which is exactly how a
    # round of fixes came back looking like it had changed nothing.
    _sv = compiled.get('schema_version', '?')
    L.append(f'compiled by stage version {_sv}'
             + ('' if _sv == BRIEF_STAGE_VERSION else
                f'   <-- STALE: this kernel has {BRIEF_STAGE_VERSION}. '
                f'Re-run §48 with force=True.'))
    st = compiled.get('stats', {})
    L.append(f'{st.get("requirements", 0)} requirements | {st.get("scorable", 0)} scorable | '
             f'{st.get("forbidden", 0)} forbidden | {st.get("with_temporal", 0)} timed | '
             f'total weight {st.get("total_weight", 0)}')
    if st.get('choice_groups'):
        L.append(f'{st["choice_groups"]} CHOICE GROUP(S) covering {st.get("alternatives", 0)} '
                 f'alternatives -- the video picks ONE from each, not all of them')
    if compiled.get('sections'):
        L.append('')
        L.append('HOW THE DOCUMENT WAS READ:')
        for s in compiled['sections']:
            note = {'context': 'ignored (background)',
                    'claims': 'approved-claims allowlist',
                    'alternatives': 'CHOICE -- pick one',
                    'requirements': 'requirements'}.get(s['kind'], s['kind'])
            L.append(f'  {(s["heading"] or "(no heading)")[:48]:<50} {s["lines"]:>2} lines'
                     f'  ->  {note}')
        L.append('  If a section was read the wrong way, that is the thing to fix first.')
    if compiled.get('approved_claims'):
        L.append('')
        L.append('APPROVED CLAIMS (things the video MAY say; figures are binding):')
        for c in compiled['approved_claims']:
            nums = f'   [{", ".join(c["numbers"])}]' if c['numbers'] else ''
            L.append(f'  - {c["text"][:80]}{nums}')
    if compiled.get('reference_links'):
        L.append('')
        L.append('EXAMPLE VIDEOS the brief points at (reference, not requirements):')
        for r in compiled['reference_links']:
            L.append(f'  - {r["url"]}'
                     + (f'   ({r["section"]})' if r.get('section') else ''))
    L.append('=' * 100)

    # group members together so a choice reads as one decision
    groups = {}
    for r in order:
        if r.get('group') and r.get('group_mode') in ('one_of', 'any_of'):
            groups.setdefault(r['group'], []).append(r)
    shown_groups = set()
    for gid, members in groups.items():
        L.append('')
        L.append(f'  CHOOSE {"ONE" if members[0]["group_mode"] == "one_of" else "AT LEAST ONE"}'
                 f' of {len(members)} -- {members[0].get("group_label") or gid}')
        for r in members:
            L.append(f'      {r["id"]}  [{r["type"]}/{r["evidence_mode"]}] '
                     f'{r["requirement"][:74]}')
            if r.get('flags'):
                for f in r['flags']:
                    L.append(f'         {_WARN} {f}')
        shown_groups.add(gid)
    order = [r for r in order
             if not (r.get('group') and r.get('group_mode') in ('one_of', 'any_of'))]

    for r in order:
        flag_mark = _WARN if r.get('flags') else '   '
        mc = '' if r.get('machine_checkable') else '  [NOT AUTO-CHECKED]'
        L.append('')
        L.append(f'{flag_mark} {r["id"]}  [{r["type"]}/{r["evidence_mode"]}] '
                 f'{r["priority"]} (w{r["weight"]}){mc}')
        L.append(f'      {r["requirement"]}')
        when = []
        if r.get('deadline_seconds') is not None:
            when.append(f'by {r["deadline_seconds"]:g}s')
        if r.get('window_start_expr') or r.get('window_end_expr'):
            when.append(f'window [{r.get("window_start_expr")} .. {r.get("window_end_expr")}]')
        elif r.get('window_start_seconds') is not None:
            when.append(f'window [{r.get("window_start_seconds")}'
                        f' .. {r.get("window_end_seconds")}]')
        if r.get('polarity') == 'forbidden':
            when.append(f'FORBIDDEN: {", ".join(r.get("claim_classes", []))}')
        if when:
            L.append(f'      when: {" | ".join(when)}')
        if r.get('match_hints'):
            L.append(f'      hints: {", ".join(r["match_hints"][:8])}')
        L.append(f'      from brief: "{(r.get("brief_span") or "")[:88]}"')
        if show_flags and r.get('flags'):
            for f in r['flags']:
                L.append(f'      {_WARN} {f}')
    if compiled.get('conflicts'):
        L.append('')
        L.append('-' * 100)
        L.append('CONFLICTS -- these need a human decision, the compiler cannot resolve them:')
        for c in compiled['conflicts']:
            L.append(f'  {_WARN} {c["code"]}: {c["detail"]}')
    doc_flags = [f for f in compiled.get('flags', []) if isinstance(f, dict)]
    if doc_flags:
        L.append('')
        L.append('DOCUMENT-LEVEL NOTES:')
        for f in doc_flags:
            L.append(f'  - {f.get("code")}: {f.get("detail")}')
    L.append('')
    L.append('=' * 100)
    L.append('Read every line above. The question to answer is exactly:')
    L.append('  "Does this accurately represent what the brief asks creators to do?"')
    L.append('Then run:  approve_brief(compiled, "your name")')
    L.append('=' * 100)
    return '\n'.join(L)

def requirements_digest(reqs: list) -> str:
    """
    A stable fingerprint of WHAT was approved.

    Measured: the same brief compiled to 9, 10 and 22 requirements across three
    runs at temperature 0. An approval that records only "yes" therefore says
    nothing about which set of requirements a person actually read. The digest
    covers the fields a reviewer would have checked -- identity, wording,
    evidence mode, polarity, timing and choice grouping -- and deliberately
    ignores ordinal and confidence, which move without changing meaning.
    """
    rows = []
    for r in reqs or []:
        rows.append('|'.join(str(r.get(k) or '') for k in (
            'id', 'requirement', 'type', 'evidence_mode', 'polarity', 'priority',
            'group', 'group_mode', 'deadline_seconds',
            'window_start_expr', 'window_end_expr')))
    return hashlib.sha256('\n'.join(sorted(rows)).encode('utf-8')).hexdigest()[:16]

def approval_state(compiled: dict) -> dict:
    """
    {'approved', 'reason'} -- is THIS requirement set approved, right now?

    An approval is a statement about a specific list. Recompiling produces a
    new list, and the old approval does not describe it.
    """
    if not compiled.get('approved'):
        return {'approved': False, 'reason': 'never approved'}
    recorded = compiled.get('approved_digest')
    current = requirements_digest(compiled.get('requirements') or [])
    if not recorded:
        # approved before digests existed; honour it, but say so
        return {'approved': True, 'reason': 'approved without a digest (legacy)'}
    if recorded != current:
        return {'approved': False,
                'reason': f'the requirement set changed since approval '
                          f'({recorded} -> {current}); it must be reviewed again'}
    return {'approved': True, 'reason': f'approved, digest {current}'}

def approve_brief(compiled: dict, approver: str, note: str = '',
                  verbose: bool = True) -> dict:
    """Record explicit human approval and persist it alongside the artifact."""
    if not approver or not str(approver).strip():
        raise ValueError('approve_brief needs a name: approve_brief(compiled, "your name")')
    if compiled.get('status') != 'OK':
        raise ValueError(f'cannot approve a brief with status {compiled.get("status")!r}')
    compiled['approved'] = True
    compiled['approved_by'] = str(approver).strip()
    compiled['approved_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    compiled['approval_note'] = str(note or '').strip() or None
    # Bind the approval to the exact list that was read.
    compiled['approved_digest'] = requirements_digest(compiled.get('requirements') or [])
    bhash, key = compiled.get('brief_hash'), compiled.get('cache_key')
    if bhash and key:
        write_json(DIRS['briefs'] / bhash / f'requirements__{key}.json', compiled)
    if verbose:
        print(f'  APPROVED by {compiled["approved_by"]} at {compiled["approved_at"]}  '
              f'({compiled["stats"]["requirements"]} requirements, '
              f'digest {compiled["approved_digest"]})')
        print('  That approval covers THIS list. Recompiling the brief produces a '
              'new one and will need reviewing again.')
    return compiled

def requirements_for_audit(compiled: dict, allow_unapproved: bool = False) -> list:
    """
    THE accessor Phase 6 uses. It refuses to release an unapproved requirement set.

    Reading compiled['requirements'] directly would work and would skip the gate,
    so the gate lives in the function everything downstream is told to call. It
    can be bypassed -- allow_unapproved is right there -- but only on purpose.
    """
    if compiled.get('status') != 'OK':
        raise ValueError(f'brief status is {compiled.get("status")!r}, not OK')
    _state = approval_state(compiled)
    if not _state['approved'] and not allow_unapproved:
        if compiled.get('approved'):
            # It WAS approved -- of a different list. That is a distinct failure
            # from never having been reviewed, and needs a different message.
            raise PermissionError(
                f'This brief was approved, but not in its current form: '
                f'{_state["reason"]}.\n'
                '  Re-read the requirements and approve again:\n'
                '    print(render_requirements_table(compiled))\n'
                '    approve_brief(compiled, "your name")')
        raise PermissionError(
            'This brief has not been approved by a human.\n'
            '  product.md §73 makes that the exit criterion for Phase 4: a person must read '
            'the compiled requirements and confirm they represent the brief.\n'
            '  Run:  print(render_requirements_table(compiled))\n'
            '        approve_brief(compiled, "your name")\n'
            '  To bypass deliberately: requirements_for_audit(compiled, allow_unapproved=True)')
    return compiled.get('requirements', [])

def resolve_brief_for_video(compiled: dict, duration_seconds: float,
                            allow_unapproved: bool = False) -> list:
    """
    Requirements with every symbolic window resolved against ONE video.

    Returns copies. The compiled brief is shared across many videos of different
    lengths, so resolving in place would make the second video inherit the first
    video's windows -- a bug that produces plausible numbers and no error.
    """
    out = []
    for rd in requirements_for_audit(compiled, allow_unapproved):
        # Filter to known fields, exactly as EvidenceRecord is built. A brief
        # artifact compiled by a newer version carries fields this dataclass
        # has not met, and an audit is the worst possible place to discover
        # that: the compile has already happened and been paid for.
        _known = {k: v for k, v in rd.items()
                  if k in Requirement.__dataclass_fields__}
        _dropped = sorted(set(rd) - set(_known))
        r = Requirement(**_known)
        if _dropped:
            # Recorded, not swallowed. A field that vanishes silently is how a
            # schema drifts without anyone noticing.
            r.flags = list(r.flags or []) + [f'UNKNOWN_FIELD_DROPPED:{",".join(_dropped)}']
        resolved = resolve_requirement_window(r, duration_seconds)
        d = dict(rd)
        d['resolved'] = resolved
        out.append(d)
    return out


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 252: print('§46 approval gate loaded. requirements_for_audit() refuses unapproved
