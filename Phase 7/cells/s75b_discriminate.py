# ============================================================================
# §75b  Which quantity discriminates?  --  answered WITHOUT labels
#
# Numbered 75b and placed after §75: it reuses STATUS_SCORE, PRIORITY_WEIGHT
# and the weight tables rather than copying them, so the experiment measures
# exactly what the scorer computes. It still runs before §76, which is what
# "decide before you build the scorer" requires.
#
# ---------------------------------------------------------------------------
# WHY THIS NEEDS NO HUMAN LABELS
# ---------------------------------------------------------------------------
# An earlier version of this cell asked you to list which videos were on brief
# and which were off. That was circular: "how close is this video to the
# brief" is the system's OUTPUT, and demanding it as input makes the system
# pointless.
#
# The experiment never needed that. It needs one fact from the production
# process -- WHICH BRIEF EACH VIDEO WAS SHOT FOR -- which is not a judgement
# and which you already know, because you ran the audit.
#
# From that one fact, the comparison labels itself:
#
#     a video against ITS OWN brief          -> should score HIGH
#     the same video against ANOTHER brief   -> should score LOW
#
# The same video, the same evidence, the same pipeline. The only thing that
# changed is the brief. Any quantity worth putting on a report must separate
# those two, and a quantity that cannot is measuring something other than fit.
#
# This is a PAIRED design, which is also stronger than labelling: it controls
# for the video. A "good creator" scoring well on everything and a "bad" one
# scoring badly would fool a labelled comparison; they cannot fool this one,
# because each video is its own control.
#
# ---------------------------------------------------------------------------
# THE DECISION RULE, WRITTEN BEFORE THE NUMBERS ARE SEEN
# ---------------------------------------------------------------------------
#   * a candidate DISCRIMINATES when every video scores higher against its own
#     brief than against every foreign brief -- no overlap between the two
#     populations
#   * among those that discriminate, prefer the LARGEST MARGIN, then the
#     smallest spread within each population
#   * if only D (standing) discriminates, standing is the headline and the
#     requirement layer is reported as detail
#   * if B discriminates, B is the headline and standing becomes the crosscheck
#
# Pre-registering it is the point. A rule chosen after seeing the numbers is
# not a decision, it is a rationalisation.
# ============================================================================

# Auditing a video against a foreign brief is a real audit and costs real L3
# calls. Nothing is spent unless you ask for it.
RUN_CONTROL_AUDITS = False      # True to generate the missing foreign pairings
MAX_CONTROL_AUDITS = 6          # a ceiling on what one run may spend

# Where §75b records which (video, brief) pairings IT created. Everything else
# on disk came from §72, which pairs a video with the brief it was shot for --
# so this file is what tells native pairings from controls without asking.
CONTROLS_PATH = DIRS['artifacts'] / '_discrimination' / 'controls.json'


def _load_controls() -> set:
    """
    The control pairings recorded so far, or an empty set on the first run.

    read_json RAISES on a missing file -- it does not return None. On the very
    first run of this cell that file does not exist yet, which is the normal
    case, not an error. The `.exists()` guard is the whole fix.
    """
    if not CONTROLS_PATH.exists():
        return set()
    try:
        d = read_json(CONTROLS_PATH) or {}
    except Exception as exc:
        print(f'  (controls.json unreadable: {type(exc).__name__}; treating '
              f'every pairing on disk as native)')
        return set()
    return {tuple(p) for p in (d.get('pairs') or [])}


def _save_controls(pairs: set) -> None:
    CONTROLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_json(CONTROLS_PATH, {'pairs': sorted(list(p) for p in pairs),
                               'note': ('Pairings §75b created as controls: a '
                                        'video audited against a brief it was '
                                        'NOT shot for. Everything else on disk '
                                        'is a native pairing from §72.')})


def candidate_scores(verdict_artifact: dict) -> dict:
    """The four candidates, from one verdicts__*.json. Pure arithmetic."""
    vs = verdict_artifact.get('verdicts') or []
    units = [v for v in vs if v.get('status') != 'NOT_APPLICABLE']

    def _w(v):
        return float(PRIORITY_WEIGHT.get(v.get('priority') or 'medium', 1.0))

    def _status_mean(sel):
        dec = [v for v in sel if v.get('status') in STATUS_SCORE]
        tw = sum(_w(v) for v in dec)
        if tw <= 0:
            return None
        return sum(_w(v) * STATUS_SCORE[v['status']] for v in dec) / tw

    absence = [v for v in units
               if any(str(f) == 'PASS_FROM_ABSENCE' for f in (v.get('flags') or []))]
    achievement = [v for v in units if v not in absence]
    aligned = [v for v in units if v.get('alignment') in ALIGNMENT_WEIGHTS]
    st = (verdict_artifact.get('standing') or {}).get('standing')

    return {
        'A_status_all': _status_mean(units),
        'B_status_achievement': _status_mean(achievement),
        'C_alignment_mean': (sum(ALIGNMENT_WEIGHTS[v['alignment']] for v in aligned)
                             / len(aligned)) if aligned else None,
        'D_standing': BRIEF_STANDING_WEIGHTS.get(st) if st else None,
        'units': len(units),
        'achievement_units': len(achievement),
        'absence_units': len(absence),
        'standing_level': st,
    }


CANDIDATES = ('A_status_all', 'B_status_achievement', 'C_alignment_mean',
              'D_standing')
_CAND_LABEL = {
    'A_status_all': 'A  status, all units',
    'B_status_achievement': 'B  status, achievement only',
    'C_alignment_mean': 'C  alignment mean',
    'D_standing': 'D  standing weight',
}


def _collect_audits() -> list:
    """Every verdicts artifact on disk, as (video, brief) pairings."""
    out = []
    art = DIRS['artifacts']
    if not art.exists():
        return out
    for vdir in sorted(d for d in art.glob('*') if d.is_dir()):
        if vdir.name.startswith('_'):
            continue
        for p in sorted(vdir.glob('verdicts__*.json')):
            a = read_json(p)
            if not isinstance(a, dict) or not a.get('verdicts'):
                continue
            out.append({'video': vdir.name, 'video_id': a.get('video_id', ''),
                        'brief': a.get('brief_hash', ''), 'file': p.name,
                        'scores': candidate_scores(a)})
    return out


def _compiled_briefs() -> dict:
    """brief_hash -> the newest approved compile for it."""
    out = {}
    bdir = DIRS.get('briefs')
    if not bdir or not Path(bdir).exists():
        return out
    for d in sorted(Path(bdir).glob('*')):
        if not d.is_dir() or d.name.startswith('_'):
            continue
        for p in sorted(d.glob('requirements__*.json'),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            c = read_json(p)
            if isinstance(c, dict) and c.get('requirements'):
                out.setdefault(c.get('brief_hash', d.name), c)
                break
    return out


def make_control_audits(limit: int = None, verbose: bool = True) -> int:
    """
    Audit each video against the briefs it was NOT shot for.

    This is the only part that spends anything, and it is off by default. Each
    control reuses the video's cached evidence -- only the verdict stage
    re-runs, which is exactly what Phase 5's cache separation was built for.
    """
    limit = MAX_CONTROL_AUDITS if limit is None else limit
    audits = _collect_audits()
    controls = _load_controls()
    native = {}
    for a in audits:
        if (a['video'], a['brief']) not in controls:
            native.setdefault(a['video'], a['brief'])
    briefs = _compiled_briefs()
    have = {(a['video'], a['brief']) for a in audits}

    todo = []
    for vh, own in native.items():
        for bh, compiled in briefs.items():
            if bh != own and (vh, bh) not in have:
                todo.append((vh, bh, compiled))
    if not todo:
        if verbose:
            print('  No control pairings missing -- every video has already '
                  'been audited against every other compiled brief.')
        return 0
    if verbose:
        print(f'  {len(todo)} control pairing(s) missing; running '
              f'{min(len(todo), limit)}.')
    made = 0
    for vh, bh, compiled in todo[:limit]:
        ev = evidence_for(vh) if 'evidence_for' in globals() else None
        if ev is None:
            _evp = sorted((DIRS['artifacts'] / vh).glob('evidence__*.json'),
                          key=lambda p: p.stat().st_mtime, reverse=True)
            ev = read_json(_evp[0]) if _evp else None
        if not ev:
            if verbose:
                print(f'    skip {vh[:8]} x {bh[:8]} -- no evidence artifact')
            continue
        vid = {'video_hash': vh, 'video_id': vh[:16]}
        try:
            evaluate_requirements(vid, ev, compiled, P6, verbose=False,
                                  allow_unapproved=True)
            controls.add((vh, bh))
            made += 1
            if verbose:
                print(f'    control: {vh[:8]} x foreign brief {bh[:8]}')
        except Exception as exc:
            if verbose:
                print(f'    failed {vh[:8]} x {bh[:8]}: '
                      f'{type(exc).__name__}: {str(exc)[:70]}')
    _save_controls(controls)
    return made


def run_discrimination() -> dict:
    """
    Native pairings against control pairings, four ways, then the rule.

    Prints unconditionally: the printed table IS the deliverable, and a silent
    run of an experiment is not one.
    """
    print('=' * 78)
    print('§75b  WHICH QUANTITY DISCRIMINATES?')
    print('=' * 78)
    print('  No labels are used. A video against its OWN brief is the positive')
    print('  case; the same video against a FOREIGN brief is the control. Each')
    print('  video is its own control, so a strong or weak creator cannot')
    print('  shift the comparison.')
    print()

    if RUN_CONTROL_AUDITS:
        make_control_audits()
        print()

    audits = _collect_audits()
    controls = _load_controls()
    out = {'audits': len(audits), 'candidates': {}, 'verdict': '',
           'winner': None, 'native': 0, 'control': 0}
    if not audits:
        print('  No verdict artifacts on disk. Run Phase 6 first.')
        out['verdict'] = 'no data'
        return out

    for a in audits:
        a['is_control'] = (a['video'], a['brief']) in controls
    native = [a for a in audits if not a['is_control']]
    control = [a for a in audits if a['is_control']]
    out['native'], out['control'] = len(native), len(control)

    print(f'  {len(audits)} audit(s): {len(native)} native, '
          f'{len(control)} control, across '
          f'{len({a["video"] for a in audits})} video(s) and '
          f'{len({a["brief"] for a in audits})} brief(s)')
    print()
    print(f'  {"video":<18}{"brief":<10}{"pairing":<10}'
          f'{"A":>7}{"B":>7}{"C":>7}{"D":>7}{"units":>7}')
    print('  ' + '-' * 80)
    for a in sorted(audits, key=lambda x: (x['video'], x['is_control'])):
        s = a['scores']
        cells = ''.join(f'{s[c]:>7.2f}' if s[c] is not None else f'{"--":>7}'
                        for c in CANDIDATES)
        print(f'  {(a["video_id"] or a["video"])[:16]:<18}{a["brief"][:8]:<10}'
              f'{"control" if a["is_control"] else "own":<10}{cells}'
              f'{s["units"]:>7}')

    if not control:
        print()
        print('  NO CONTROL PAIRINGS YET, so nothing can be compared.')
        print()
        print('  Every audit on disk is a video against the brief it was shot')
        print('  for. To answer the question the system needs the other half:')
        print('  the same videos against briefs they were NOT shot for.')
        print()
        print('  Set RUN_CONTROL_AUDITS = True at the top of this cell and')
        print('  re-run. It reuses each video\'s cached evidence, so only the')
        print('  verdict stage re-runs -- a few L3 calls per pairing, capped')
        print(f'  at {MAX_CONTROL_AUDITS} audits per run.')
        print()
        print('  You are not being asked to judge anything. The pairing a')
        print('  video was shot for is already recorded in its audit.')
        out['verdict'] = 'no controls yet'
        return out

    print()
    print(f'  {"candidate":<34}{"own brief":>18}{"foreign brief":>18}'
          f'{"margin":>9}   verdict')
    print('  ' + '-' * 88)

    def _rng(vals):
        vals = [v for v in vals if v is not None]
        return (min(vals), max(vals)) if vals else None

    discriminating = []
    for c in CANDIDATES:
        rn, rc = _rng([a['scores'][c] for a in native]), \
            _rng([a['scores'][c] for a in control])
        if rn is None or rc is None:
            print(f'  {_CAND_LABEL[c]:<34}{"no data":>18}')
            out['candidates'][c] = {'own': None, 'foreign': None,
                                    'discriminates': None}
            continue
        sep = rn[0] > rc[1]                 # every own beats every foreign
        margin = rn[0] - rc[1]
        spread = max(rn[1] - rn[0], rc[1] - rc[0])
        out['candidates'][c] = {
            'own': [round(rn[0], 3), round(rn[1], 3)],
            'foreign': [round(rc[0], 3), round(rc[1], 3)],
            'margin': round(margin, 3), 'spread': round(spread, 3),
            'discriminates': bool(sep)}
        if sep:
            discriminating.append((-margin, spread, c))
        print(f'  {_CAND_LABEL[c]:<34}'
              f'{f"{rn[0]:.2f}-{rn[1]:.2f}":>18}'
              f'{f"{rc[0]:.2f}-{rc[1]:.2f}":>18}'
              f'{margin:>+9.2f}   '
              f'{"SEPARATES" if sep else "overlaps"}')

    print()
    print('  THE PRE-REGISTERED RULE')
    print('  ' + '-' * 74)
    if not discriminating:
        out['verdict'] = 'none discriminate'
        print('  Nothing separates a video from a brief it was never shot for.')
        print('  Do NOT pick a headline number from this data. Either the')
        print('  corpus is too small, or every candidate is measuring form')
        print('  rather than fit -- and §0.1 already showed C does exactly that.')
        return out
    discriminating.sort()
    winner = discriminating[0][2]
    out['winner'] = winner
    out['verdict'] = (f'{winner} separates own from foreign by '
                      f'{out["candidates"][winner]["margin"]:+.2f}')
    print(f'  Discriminating: {", ".join(c for _m, _s, c in discriminating)}')
    print(f'  Largest margin -> {_CAND_LABEL[winner]}')
    print()
    if winner == 'D_standing' and len(discriminating) == 1:
        print('  Only standing separates them. Standing becomes the HEADLINE')
        print('  and the requirement layer is reported as detail, not as the')
        print('  number. §76 must be changed to match.')
    elif winner.startswith('B'):
        print('  B is the headline; standing becomes the cross-check. This is')
        print('  what §76 is already built for -- no change needed.')
    else:
        print(f'  {winner} is the headline. §76 currently leads with B, so it')
        print('  must be changed to match, and PHASE_7_PLAN.md §1 updated.')
    print()
    print('  WRITE THIS RESULT INTO Phase 7/PHASE_7_PLAN.md §1.')
    return out


_discrimination = run_discrimination()
