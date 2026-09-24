"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 141.
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
# base64 is used to embed the proxy video and is imported nowhere in Phases
# 1-6. An import a cell needs and does not make is a cell that works in a warm
# kernel and dies in a fresh one.
import time

import base64

REPORT_HTML_VERSION = '1.1.2'   # advice cites the requirement by NAME, not id

def esc(x) -> str:
    """Every string that reaches the page goes through here. No exceptions."""
    return (str('' if x is None else x)
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&#39;'))

def _fmt_ts(t) -> str:
    """0:11 rather than 11.0s -- the form a creator reads on a timeline."""
    if t is None:
        return ''
    t = float(t)
    return f'{int(t // 60)}:{int(t % 60):02d}'

def _ts_link(t, label: str = '') -> str:
    """
    A timestamp that seeks the player. Spec §40's key interaction.

    data-t carries the seconds; one delegated listener at the bottom of the
    page does the seeking, so this works for timestamps added anywhere.
    """
    if t is None:
        return '<span class="ts-none">no timestamp</span>'
    return (f'<a class="ts" href="#player" data-t="{float(t):.3f}">'
            f'{esc(label or _fmt_ts(t))}</a>')

def _pill(status: str) -> str:
    cls = {'PASS': 'ok', 'PARTIAL': 'warn', 'FAIL': 'bad',
           'UNCERTAIN': 'unk', 'NOT_APPLICABLE': 'na'}.get(status, 'unk')
    sym = {'PASS': '✓', 'PARTIAL': '◐', 'FAIL': '✕',
           'UNCERTAIN': '?', 'NOT_APPLICABLE': '–'}.get(status, '?')
    # Symbol AND colour: the page has to survive greyscale printing.
    return f'<span class="pill {cls}">{sym} {esc(status)}</span>'

def _section(title: str, body: str, sub: str = '', cls: str = '') -> str:
    if not body:
        return ''
    subhtml = f'<p class="sub">{esc(sub)}</p>' if sub else ''
    return (f'<section class="{esc(cls)}"><h2>{esc(title)}</h2>{subhtml}'
            f'{body}</section>')

# ---------------------------------------------------------------------------
# the proxy video
# ---------------------------------------------------------------------------
def build_proxy_video(video: dict, cfg: Phase7Config = None,
                      verbose: bool = True) -> dict:
    """
    A small re-encode of the source, cached beside the artifacts.

    Cached because ffmpeg is not byte-reproducible run to run, and §81 asks the
    same artifact to render identically twice. Encode once, embed those bytes
    forever.
    """
    cfg = cfg or P7
    out = {'ok': False, 'data_uri': '', 'bytes': 0, 'note': ''}
    if not cfg.report.embed_video:
        out['note'] = 'Video embedding is switched off in P7.report.'
        return out
    src = video.get('path') or ''
    vh = video.get('video_hash', '')
    if not src or not Path(src).exists():
        out['note'] = 'The source video is not on this machine, so the report '\
                      'has no player. Every timestamp is still listed.'
        return out
    vdir = DIRS['artifacts'] / vh
    vdir.mkdir(parents=True, exist_ok=True)
    proxy = vdir / f'proxy__{cfg.report.proxy_height}p_crf{cfg.report.proxy_crf}.mp4'
    if not proxy.exists():
        cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src),
               '-vf', f'scale=-2:{cfg.report.proxy_height}',
               '-c:v', 'libx264', '-crf', str(cfg.report.proxy_crf),
               '-preset', 'veryfast', '-c:a', 'aac', '-b:a', '64k',
               '-movflags', '+faststart', str(proxy)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode != 0 or not proxy.exists():
                out['note'] = ('ffmpeg could not build the proxy video; the '
                               'report renders without a player.')
                return out
        except Exception as exc:
            out['note'] = f'Proxy encode failed ({type(exc).__name__}); '\
                          f'the report renders without a player.'
            return out
    size = proxy.stat().st_size
    if size > cfg.report.proxy_max_mb * 1024 * 1024:
        out['note'] = (f'The proxy is {size / 1e6:.1f} MB, above the '
                       f'{cfg.report.proxy_max_mb} MB embed limit, so it is '
                       f'linked rather than embedded.')
        out['path'] = str(proxy)
        return out
    out.update(ok=True, bytes=size,
               data_uri='data:video/mp4;base64,'
                        + base64.b64encode(proxy.read_bytes()).decode('ascii'))
    if verbose:
        print(f'  proxy video: {size / 1e6:.2f} MB embedded')
    return out

# ---------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------
def _headline_html(score: dict) -> str:
    s = score.get('score') or {}
    lo, hi = s.get('band_low'), s.get('band_high')
    cov, band = s.get('coverage') or 0.0, s.get('status_band', '')
    units = s.get('scoring_units') or 0

    # QUESTION 1 FAILED. A number here would be answering a question nobody
    # asked: how closely a video followed a brief it is not addressing. The
    # arithmetic stays available in the appendix, behind a click, labelled.
    if s.get('gated'):
        rel = score.get('relevance') or {}
        st = (score.get('standing') or {})
        arith = ('no scorable unit' if lo is None
                 else f'{lo:.0f}–{hi:.0f} across {units} unit(s)')
        return (
            f'<div class="headline gated"><div class="score-box">'
            f'<div class="big off">off brief</div>'
            f'<div class="band b-OFF_BRIEF">{esc(rel.get("level", ""))}</div>'
            f'</div><div class="score-meta">'
            f'<p><b>This video is not addressing this brief.</b></p>'
            f'<p class="sub">{esc(rel.get("what", "") or rel.get("why", ""))}</p>'
            + (f'<p class="quote">{esc(str(st.get("verdict") or "")[:340])}</p>'
               if st.get('verdict') else '')
            + f'<p class="sub">A per-requirement score is withheld on purpose. '
              f'It would read as "nearly there" for a video that needs a '
              f'different brief, or a different video. The arithmetic is kept '
              f'in the appendix ({esc(arith)}) so nothing is hidden.</p>'
              f'</div></div>')

    if lo is None:
        big = '<div class="big none">no score</div>'
        note = 'Nothing in this brief could be scored against this video.'
    elif s.get('lead_with_band'):
        big = f'<div class="big">{lo:.0f}<span class="dash">–</span>{hi:.0f}</div>'
        note = (f'{(1 - cov) * 100:.0f}% of this brief could not be '
                f'decided from the video, so the result is a range. The '
                f'grade below is the cautious end of it.')
    else:
        big = f'<div class="big">{hi:.0f}</div>'
        note = ''          # a single figure needs no explanation
    # §0.4: three decisions cannot carry a decimal, and the unit count is not
    # a footnote -- it is how the reader knows how much to trust the number.
    crit = ('<p class="crit">A critical requirement failed, so the band cannot '
            'be better than NEEDS_MAJOR_REVISION whatever the arithmetic says.</p>'
            if s.get('critical_floor_applied') else '')
    return (f'<div class="headline"><div class="score-box">{big}'
            f'<div class="band b-{esc(band)}">{esc(band.replace("_", " "))}</div>'
            f'</div><div class="score-meta">'
            f'<p><b>{units}</b> scoring unit{"s" if units != 1 else ""} '
            f'&middot; <b>{cov:.0%}</b> coverage</p>'
            f'<p class="sub">{esc(note)}</p>{crit}'
            f'</div></div>')

def talking_point_coverage(result: dict, compiled: dict) -> dict:
    """How much of the brief's SUBSTANCE the video actually covered.

    The brief's talking points are what it asked her to communicate. Each is
    its own scoring unit (they are never grouped -- see §43), so coverage is a
    real ratio rather than "did she mention any of them".

    `FROM_APPROVED_CLAIMS:<claim>` is provenance written at compile time. It
    may MISS -- it comes from a fuzzy match -- so this is a floor, not a
    census, and the caller says so. What it never does is change the score.

    Shared by the report and §80 so the two cannot disagree about the number.
    """
    reqs = {r.get('id'): r for r in (compiled.get('requirements') or [])}
    covered, missed = [], []
    for v in (result.get('verdicts') or []):
        rq = reqs.get(v.get('requirement_id')) or {}
        src = next((str(f).split(':', 1)[1] for f in (rq.get('flags') or [])
                    if str(f).startswith('FROM_APPROVED_CLAIMS')), None)
        if src is None:
            continue
        label = v.get('requirement_label') or rq.get('label') or src
        (covered if v.get('status') in ('PASS', 'PARTIAL') else missed).append(
            {'label': label, 'claim': src, 'status': v.get('status', ''),
             'requirement_id': v.get('requirement_id', '')})
    return {'total': len(covered) + len(missed), 'covered': covered,
            'missed': missed,
            'approved_claims': len(compiled.get('approved_claims') or [])}

def _talking_points_html(result: dict, compiled: dict, score: dict = None) -> str:
    """The brief's substance, as a ratio and by name.

    "3 of 5 covered, missing split ends and shine" is the most directly
    actionable line a creator manager gets: it names what to add next time.
    """
    tp = talking_point_coverage(result, compiled)
    if not tp['total']:
        return ''
    n, m = len(tp['covered']), tp['total']
    def _li(rows, cls):
        return ''.join(
            f'<li class="{cls}"><b>{esc(r["label"])}</b>'
            f'<div class="sub">from the brief: {esc(r["claim"])}</div></li>'
            for r in rows)
    note = ''
    if tp['approved_claims'] and tp['approved_claims'] > m:
        note = (f'<p class="sub">The brief lists {tp["approved_claims"]} '
                f'approved talking point(s); {m} became checkable '
                f'requirement(s). This is a floor, not a census — the link '
                f'back to a brief line is a best-effort match.</p>')
    # HOW THESE SCORE, stated on the page. §76 collapses the bullets into ONE
    # scoring unit, so a reader who sees "4 of 8" must be able to see what that
    # did to the number -- otherwise the coverage line and the Messaging
    # subscore look unrelated, and the arithmetic stops being checkable by hand.
    _tpu = ((score or {}).get('score') or {}).get('talking_points') or {}
    scoring = ''
    if _tpu and not _tpu.get('collapsed', True):
        # The brief DEMANDS these, so each is scored on its own. Say which
        # reading was used and where it came from -- a reader must never have
        # to guess whether a list was treated as a menu or a checklist.
        scoring = (
            f'<p class="sub">This brief <b>requires</b> each of these '
            f'{esc(str(_tpu.get("offered")))}, so each one is checked on its '
            f'own.</p>')
    elif _tpu:
        _st = esc(str(_tpu.get('status', '')))
        scoring = (
            f'<p class="sub">The brief <b>offers</b> these and invites your '
            f'own style, so they count together rather than one by one. '
            f'You covered <b>{esc(str(_tpu.get("covered")))} of '
            f'{esc(str(_tpu.get("offered")))}</b>.</p>')
        # The caveat lives in Technical details with the other one. A
        # creator reading "your coverage target is a PLACEHOLDER" learns
        # nothing they can act on.
        if False and _tpu.get('target_is_placeholder'):
            scoring += (
                '<p class="sub">The target is a <b>PLACEHOLDER</b>, and a '
                'weaker one than the band thresholds: the brief states no '
                'minimum, so this number is provisional until calibration '
                '(Phase 8). Read the ordering of scores, not the absolute '
                'value.</p>')
    return _section(
        'Talking points covered',
        f'<div class="big">{n} of {m}</div>'
        + (f'<h4>covered</h4><ul class="tp">{_li(tp["covered"], "ok")}</ul>'
           if tp['covered'] else '')
        + (f'<h4>not evidenced</h4><ul class="tp">{_li(tp["missed"], "no")}</ul>'
           if tp['missed'] else '')
        + note + scoring,
        'What the brief asked her to communicate. Every point keeps its own '
        'verdict and its own row, so this is real coverage rather than "did '
        'she mention any of them" — and her own wording counts, not the '
        'brief’s.')

def _crux_html(result: dict, score: dict) -> str:
    """QUESTION 1, and the page leads with it.

    Does the crux of the video align with the crux of the brief? It is the only
    read that sees the WHOLE video against the WHOLE brief -- every other layer
    decomposes, and decomposition cannot ask it.

    It used to sit in `Modules`, below every requirement row. A reader who
    stopped early got a per-requirement percentage without ever learning
    whether the video was about the right thing, which is the wrong order to
    answer those two questions in.
    """
    st = (result.get('standing') or {})
    lvl = st.get('standing')
    if not lvl:
        return _section(
            'Does the crux align?',
            '<p class="sub">Not judged. The whole-video read did not run, so '
            'the score below is reported as if the video is on brief — that is '
            '"we could not tell", not "it is on brief".</p>', cls='alert')
    anchor = (BRIEF_STANDING_ANCHORS.get(lvl, '')
              if 'BRIEF_STANDING_ANCHORS' in globals() else '')
    quote = (f'<div class="quote">{esc(str(st.get("verdict"))[:400])}</div>'
             if st.get('verdict') else '')
    cls = {'off_brief': 'alert', 'tangential': 'alert', 'partial': 'alert'}.get(lvl, '')
    note = ''
    if lvl == 'partial':
        note = ('<p class="sub"><b>The crux only partly aligns.</b> Substantial '
                'parts of the brief are untouched, so read the score below as '
                '"how well she did the part she engaged with".</p>')
    elif lvl in ('off_brief', 'tangential'):
        note = ('<p class="sub"><b>The score below is withheld.</b> A '
                'per-requirement score measures how closely a video followed a '
                'brief it is addressing; it does not mean anything for one that '
                'is not.</p>')
    return _section(
        'Does the crux align?',
        f'<div class="big {"off" if lvl in ("off_brief", "tangential") else ""}">'
        f'{esc(lvl.replace("_", " "))}</div>'
        f'<p>{esc(anchor)}</p>{quote}{note}',
        'Does the video, taken as a whole, do what the brief asked for? '
        'Judged on meaning rather than wording — a different hook, order or '
        'structure is fine.',
        cls=cls)

# What each angle MEANS, for a reader who has not memorised the taxonomy. The
# labels are a closed enum chosen in code (§69b); these are the written
# anchors, the same discipline as hook strength and alignment.
_ANGLE_MEANING = {
    'social_proof': 'built on other people’s reactions — comments, '
                    'questions, "you asked about this"',
    'personal_transformation': 'her own before and after, a journey over time',
    'routine_integration': 'where the product sits inside a routine she '
                           'already has',
    'problem_solution': 'names a problem, then presents the product as the '
                        'answer',
    'education': 'explains how or why something works',
    'comparison': 'this versus that, or versus what she used before',
    'demonstration': 'shows the product being used — application-led',
    'testimonial_response': 'answers a specific question or objection',
    'day_in_life': 'the product inside a narrative of her day',
    'humour': 'comedic framing carries the message',
    'other': 'none of the listed angles fits what she made',
}

def _angle_html(result: dict) -> str:
    """WHAT SHE MADE -- the companion to "does the crux align?".

    Those two questions belong together and in that order: what is this video,
    and is it the right one. The angle used to sit in `Modules`, below the
    evidence timeline, where a reader had to go looking for it.

    It describes the video, never grades it. A creator may take an angle the
    brief never listed and still satisfy every requirement; one that matches a
    listed concept may still miss the ask entirely.
    """
    ca = result.get('creative_angle') or {}
    angle = ca.get('angle')
    if not angle:
        return ''
    hook = result.get('hook') or {}
    ant = ca.get('anticipated_by_brief')
    near = ca.get('nearest_brief_concept') or ''
    hookbit = ''
    if hook.get('present'):
        hookbit = (
            f'<p class="sub">She opens on a '
            f'<b>{esc(hook.get("hook_type") or "—")}</b> hook, rated '
            f'<b>{esc(hook.get("strength") or "—")}</b>'
            + (f' at {_ts_link(hook.get("start"), _fmt_ts(hook.get("start")))}'
               if hook.get('start') is not None else '')
            + '. Hook strength is a separate reading from whether the hook '
              'requirement was met — a hook can match the brief exactly '
              'and still open weakly.</p>')
    cites = ', '.join((ca.get('evidence_ids') or [])[:6])
    # WHICH of the brief's own named angles, and how much of each.
    #
    # A DESCRIPTION, not a score: §76 never reads concept_fit, and it counts
    # neither for nor against her. Said on the page in those words, because a
    # number beside a video looks like a mark unless you are told otherwise.
    _fit = [f for f in (ca.get('concept_fit') or [])
            if isinstance(f, dict) and f.get('angle')]
    fitbit = ''
    if _fit:
        rows = ''
        for f in _fit[:6]:
            try:
                pct = max(0.0, min(100.0, float(f.get('percent') or 0)))
            except (TypeError, ValueError):
                continue
            rows += (
                f'<div class="fitrow">'
                f'<div><b>{esc(str(f.get("angle")))}</b>'
                f'<span class="fitpct">{pct:.0f}%</span></div>'
                f'<div class="bar"><div class="fill f-ok" '
                f'style="width:{pct:.1f}%"></div></div>'
                + (f'<div class="sub">{esc(str(f.get("why"))[:200])}</div>'
                   if f.get('why') else '')
                + '</div>')
        fitbit = (
            '<h4>Which of the brief’s angles</h4>' + rows
            + '<p class="sub">How much of this video belongs to each angle the '
              'brief named. This DESCRIBES what she made — it is not a '
              'score — nothing is added or deducted for it.</p>')
    return _section(
        'What she made',
        f'<div class="big">{esc(angle.replace("_", " "))}</div>'
        f'<p>{esc(_ANGLE_MEANING.get(angle, ""))}</p>'
        + (f'<p class="quote">{esc(str(ca.get("summary"))[:420])}</p>'
           if ca.get('summary') else '')
        + fitbit
        + hookbit
        + (f'<p class="sub">Closest concept in the brief: '
           f'<b>{esc(near)}</b>.</p>' if near else '')
        + ('<p class="sub">The brief did not list this angle. That is a note '
           'about the brief, not a fault in the video.</p>'
           if ant is False else ''),
        'What kind of video this is — how the message was carried. '
        'A description, not a mark: nothing here changes the score.')

def _contradictions_html(score: dict) -> str:
    """
    First on the page when non-empty. This is what a reviewer reads first.

    A contradiction is not a score being low; it is two parts of the system
    disagreeing about the same video, which is always worth a human minute.
    """
    cs = score.get('contradictions') or []
    if not cs:
        return ''
    rows = []
    for c in cs:
        ev = ', '.join(c.get('evidence_ids') or []) or 'none'
        extra = (f'<div class="quote">{esc(c["standing_says"])}</div>'
                 if c.get('standing_says') else '')
        rows.append(f'<li><b>{esc(c.get("code", ""))}</b>'
                    f'<div>{esc(c.get("detail", ""))}</div>{extra}</li>')
    return _section(
        'Read this first — the system disagrees with itself',
        f'<ul class="contra">{"".join(rows)}</ul>',
        'Two independent reads of this video reached different conclusions. '
        'Neither is automatically right; the disagreement is the finding.',
        cls='alert')

def _dimensions_html(score: dict) -> str:
    dims = score.get('dimensions') or {}
    # Same reasoning as the headline: a dimension breakdown of adherence to a
    # brief the video is not addressing is seven confident bars answering the
    # wrong question. It stays in the JSON; it comes off the page.
    if (score.get('score') or {}).get('gated'):
        return _section(
            'By dimension',
            '<p class="sub">Withheld. Dimension subscores measure how closely a '
            'video followed each part of a brief, and this video is not '
            'addressing this brief. The full breakdown is in the JSON artifact '
            'if you need it.</p>')
    rows = []
    for k in DIMENSION_KEYS:
        d = dims.get(k) or {}
        if not d.get('covered'):
            rows.append(
                f'<tr class="absent"><td>{esc(d.get("label", k))}</td>'
                f'<td class="num">{d.get("weight_raw", 0):.0%}</td>'
                f'<td colspan="3" class="sub">this brief says nothing about it, '
                f'so it is excluded from the score</td></tr>')
            continue
        sc = d.get('score')
        pct = 0 if sc is None else max(0.0, min(100.0, float(sc)))
        thin = ('<span class="tag thin" title="too few decisions to be '
                'confident">thin</span>' if d.get('thin') else '')
        # The brief typed these by modality, not by the kind of ask, so the
        # dimension was read from its own grouping. Say so: an inferred
        # subscore is traceable, but it is not a declared one.
        inf = (f'<span class="tag inferred" title="{len(d["inferred_units"])} '
               f'unit(s) placed here from the brief\'s own grouping, because '
               f'the compiler typed them by modality">grouped</span>'
               if d.get('inferred_units') else '')
        rows.append(
            f'<tr><td>{esc(d.get("label", k))}{thin}{inf}</td>'
            f'<td class="num">{d.get("weight_normalised", 0):.0%}</td>'
            f'<td class="bar-cell"><div class="bar">'
            f'<div class="fill f-{"bad" if pct < 50 else "warn" if pct < 85 else "ok"}" '
            f'style="width:{pct:.0f}%"></div></div></td>'
            f'<td class="num">{"—" if sc is None else f"{sc:.0f}"}</td>'
            f'<td class="num sub">{d.get("units", 0)}</td></tr>')
    absent = score.get('dimensions_absent') or []
    sub = ('Weights are normalised over the dimensions this brief actually '
           'covers, so an uncovered dimension does not silently cap the score.')
    if absent:
        sub += (' Not covered here: '
                + ', '.join(DIMENSION_LABEL[k] for k in absent) + '.')
    return _section(
        'By dimension',
        f'<table class="dims"><thead><tr><th>dimension</th><th>weight</th>'
        f'<th></th><th>score</th><th>units</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>', sub)

def _timeline_html(records: list, duration: float) -> str:
    """One bar per modality, showing where evidence exists at all."""
    if not records or duration <= 0:
        return ''
    lanes = {}
    for r in records:
        lanes.setdefault(getattr(r, 'modality', '?'), []).append(r)
    rows = []
    for mod in ('speech', 'ocr', 'visual', 'metadata'):
        rs = lanes.get(mod)
        if not rs:
            continue
        blocks = []
        for r in sorted(rs, key=lambda x: getattr(x, 'start_seconds', 0.0)):
            a = max(0.0, float(getattr(r, 'start_seconds', 0.0)))
            b = max(a, float(getattr(r, 'end_seconds', a)))
            left, width = 100.0 * a / duration, max(0.35, 100.0 * (b - a) / duration)
            body = (getattr(r, 'raw_text', '') or getattr(r, 'description', '') or '')
            blocks.append(f'<i style="left:{left:.2f}%;width:{width:.2f}%" '
                          f'title="{esc(f"{a:.2f}s  {body[:110]}")}"></i>')
        rows.append(f'<div class="lane"><span class="lane-name">{esc(mod)}</span>'
                    f'<div class="track m-{esc(mod)}">{"".join(blocks)}</div>'
                    f'<span class="lane-n">{len(rs)}</span></div>')
    return _section('Where the evidence is', f'<div class="timeline">{"".join(rows)}</div>',
                    f'Each bar is one record. The video is {duration:.1f}s long.')

# "L1" / "L2" / "L3" is the internal name of the evaluation ladder. A reader
# wants to know HOW a verdict was reached, not which rung of our code reached
# it. The rung itself survives as the tooltip.
# A verdict whose reason is a raw model error must not show the reader a
# stack of JSON. Seen on a real page:
#
#   "VAILABLE. {'error': {'code': 503, 'message': 'This model is currently e"
#
# — a truncated Gemini 503 offered to a creator as the explanation for their
# requirement. The raw text stays in the artifact, where it belongs for
# diagnosis; the page says what actually happened.
_ERRORISH = ('503', '500', '429', 'UNAVAILABLE', 'RESOURCE_EXHAUSTED',
             'INTERNAL', 'DEADLINE', "{'error'", '{"error"', 'Traceback',
             'Exception', 'UNAUTHENTICATED')

def _plain_reason(v: dict) -> str:
    raw = str(v.get('reason') or v.get('rationale') or '').strip()
    if not raw:
        return ''
    if any(tok in raw for tok in _ERRORISH):
        return ('This requirement could not be judged: the language model was '
                'unavailable when the audit ran. It is not a finding about '
                'the video — re-run to decide it.')
    # Phase 6 bakes evidence ids into some reasons:
    #   "...in a modality that ran cleanly; checked ev_786f0d5117,
    #    ev_4263a3f72c, ev_3a9b1b006e and 7 more"
    # The COUNT is the reassurance ("we looked in ten places"); the ids are
    # for the artifact. Strip the clause, keep the sentence.
    raw = re.sub(r';?\s*checked\s+ev_[0-9a-f]+(?:\s*,\s*ev_[0-9a-f]+)*'
                 r'(?:\s+and\s+\d+\s+more)?', '', raw)
    raw = re.sub(r'\bev_[0-9a-f]{6,}\b', '', raw)
    return re.sub(r'\s{2,}', ' ', raw).strip(' ;,').strip()[:400]

_LAYER_WORDS = {'L1': ('rule', 'A deterministic check: the phrase, the '
                              'timing or the absence was established by rule, '
                              'not by a model.'),
                'L2': ('similarity', 'Matched by meaning using sentence '
                                     'embeddings rather than exact wording.'),
                'L3': ('model review', 'Adjudicated by a language model '
                                       'reading the cited evidence.')}

def _layer_word(layer) -> str:
    return _LAYER_WORDS.get(str(layer or '').upper(), (str(layer or ''), ''))[0]

def _layer_title(layer) -> str:
    return _LAYER_WORDS.get(str(layer or '').upper(), ('', 'How this verdict '
                                                           'was reached.'))[1]

def _requirements_html(result: dict, score: dict, records_by_id: dict) -> str:
    verdicts = result.get('verdicts') or []
    units = [v for v in verdicts if v.get('status') != 'NOT_APPLICABLE']
    na = [v for v in verdicts if v.get('status') == 'NOT_APPLICABLE']
    order = {'FAIL': 0, 'PARTIAL': 1, 'UNCERTAIN': 2, 'PASS': 3}
    rows = []
    for v in sorted(units, key=lambda x: (order.get(x.get('status'), 9),
                                          x.get('requirement_id', ''))):
        ids = list(v.get('evidence_ids') or [])
        times = [getattr(records_by_id[i], 'start_seconds', None)
                 for i in ids if i in records_by_id]
        times = sorted(t for t in times if t is not None)
        cites = (' '.join(_ts_link(t) for t in times[:4]) if times
                 else (f'<span class="ts-none">nothing here matched — '
                       f'{len(v.get("examined_ids") or [])} moment(s) '
                       f'checked</span>' if v.get('examined_ids')
                       else '<span class="ts-none">nothing cited</span>'))
        _flags = [str(f) for f in (v.get('flags') or [])]
        # Alignment is the MEANING score for this one requirement: how close is
        # what she did to what it was FOR, independent of wording. It shows on
        # every judged row, not only the credited ones -- a reader comparing
        # rows needs the same number on each. `None` is not `none`: None means
        # nobody judged it, `none` means judged and found unrelated.
        al = v.get('alignment')
        albit = (f'<span class="tag align" title="How close what she DID is to '
                 f'what this requirement was FOR — meaning, not wording.">'
                 f'meaning: {esc(al)}</span>' if al else
                 '<span class="tag align" title="No alignment was judged for '
                 'this requirement.">meaning: not judged</span>')
        safety = ('<span class="tag safety" title="passed because nothing '
                  'prohibited was found">compliance, not achievement</span>'
                  if 'PASS_FROM_ABSENCE' in _flags else '')

        # Literal status and alignment are shown SIDE BY SIDE and never blended.
        # A verdict used to be promoted FAIL -> PASS whenever alignment was
        # strong; on a video with no CTA at all that printed PASS. The reader
        # now sees both halves and can judge, which is the same treatment
        # `standing` and the decomposed mean already get.
        _lvl = next((f.split(':', 1)[1] for f in _flags
                     if f.startswith('SUBSTANCE_ALIGNMENT:')), '')
        _untrusted = any(f.startswith('SUBSTANCE_ALIGNMENT_UNTRUSTED')
                         for f in _flags)
        _credited = 'SATISFIED_IN_SUBSTANCE' in _flags
        if _lvl and _untrusted:
            subst = ('<span class="tag warn" title="The alignment was judged '
                     'against a group intent that does not describe its own '
                     'options, or it cites no record. It earns no credit, and '
                     'the literal finding stands.">literal: no &middot; '
                     f'alignment: {esc(_lvl)} (not credited)</span>')
        elif _credited:
            subst = ('<span class="tag subst" title="Met in her own words '
                     'rather than the brief\'s wording. The brief is a '
                     'reference, not a script, so this counts — and it cites '
                     'the record where she says it her way.">her own words '
                     f'&middot; {esc(_lvl)} match</span>')
        elif _lvl:
            subst = ('<span class="tag align">alignment: '
                     f'{esc(_lvl)}</span>')
        else:
            subst = ''

        # Diagnostics that change how much a reader should trust the row.
        _diag = ''
        if 'GROUP_INTENT_SUBJECT_FREE' in _flags:
            _diag += ('<span class="tag warn" title="The brief compiler wrote a '
                      'group intent that names only a position in the video, '
                      'not a thing to look for. Alignment judged against it is '
                      'unreliable.">group intent names no subject</span>')
        for _f in _flags:
            if _f.startswith('WINDOW_UNSUPPORTED_BY_BRIEF'):
                _diag += ('<span class="tag warn" title="The time window on '
                          'this requirement uses a number the brief never '
                          f'states: {esc(_f.split(":", 1)[1])}">invented time '
                          'window</span>')
            elif _f.startswith('WINDOW_DISAGREES_WITH_BRIEF'):
                _diag += ('<span class="tag warn" title="The model and the '
                          'rule-based reader disagree about this requirement\'s '
                          f'time window: {esc(_f.split(":", 1)[1])}">disputed '
                          'time window</span>')
        rows.append(
            f'<tr><td>{_pill(v.get("status", ""))}</td>'
            f'<td><div class="rq">{esc(v.get("requirement_label", ""))}'
            f'{albit}{safety}{subst}{_diag}</div>'
            f'<div class="why">{esc(_plain_reason(v))}</div>'
            f'<div class="cites">{cites}</div>'
            f'</td><td class="num sub">{esc(v.get("priority", ""))}</td>'
            f'<td class="num sub" title="{esc(_layer_title(v.get("layer")))}">'
            f'{esc(_layer_word(v.get("layer")))}</td></tr>')
    body = (f'<table class="reqs"><tbody>{"".join(rows)}</tbody></table>')
    if na:
        opts = ''.join(
            f'<li>{esc(v.get("requirement_label", ""))} '
            f'<span class="sub">{esc(_plain_reason(v)[:140])}</span></li>'
            for v in na[:40])
        body += (f'<details class="na"><summary>{len(na)} option(s) not selected '
                 f'— a choice group is one decision, not many failures'
                 f'</summary><ul>{opts}</ul></details>')
    saf = score.get('safety') or {}
    _n = saf.get('checks') or 0
    sub = (f'{len(units)} item{"s" if len(units) != 1 else ""} counted '
           f'towards the score.'
           + (f' {_n} thing{"s" if _n != 1 else ""} the brief forbids '
              f'{"were" if _n != 1 else "was"} also checked, and '
              f'{"none appeared" if saf.get("passed_by_absence") == _n else "some appeared"}'
              f' — staying clear of those is expected, so it does not raise '
              f'the score.' if _n else ''))
    return _section('Every requirement', body, sub)

def _approval_html(compiled: dict) -> str:
    """
    Whether the brief behind this report was ever approved by a human.

    §46 gates the audit on it, and a report built from an unapproved compile
    carries no authority -- so it has to say so, at the top, unmissably. A
    reader cannot be expected to know which briefs went through review.
    """
    if compiled.get('approved'):
        who = (compiled.get('approved_by') or compiled.get('approver') or '')
        return (f'<p class="approved">Brief reviewed and approved'
                + (f' by {esc(who)}' if who else '') + '.</p>')
    return ('<div class="unapproved"><b>This brief was never approved.</b> '
            'The requirements behind every verdict below were compiled '
            'automatically and not confirmed by a human, so nothing here '
            'carries authority. Treat it as a draft.</div>')

def _modules_html(result: dict) -> str:
    h = result.get('hook') or {}
    st = result.get('standing') or {}
    cl = result.get('claims') or {}
    cards = []
    if h:
        cards.append(
            f'<div class="card"><h3>Hook</h3>'
            f'<p><b>{esc(h.get("hook_type", "—"))}</b> &middot; '
            f'strength {esc(h.get("strength") or "—")} &middot; '
            f'{_ts_link(h.get("start"), _fmt_ts(h.get("start")))}'
            f'–{esc(_fmt_ts(h.get("end")))}</p>'
            f'<p class="quote">{esc(str(h.get("transcript") or "")[:220])}</p>'
            f'<p class="sub">{esc(str(h.get("reason") or "")[:260])}</p></div>')
    # The creative angle used to be a card here. It is now its own section near
    # the top, beside the crux -- "what she made" and "does it align" are the
    # same question asked twice and belong together. Leaving a duplicate card
    # down here would just be noise.
    if st.get('standing'):
        cov = ''.join(f'<li>{esc(x)}</li>' for x in (st.get('covered') or [])[:6])
        mis = ''.join(f'<li>{esc(x)}</li>' for x in (st.get('missing') or [])[:6])
        cards.append(
            f'<div class="card wide"><h3>The whole brief against the whole video</h3>'
            f'<p><b>{esc(st.get("standing"))}</b></p>'
            f'<p>{esc(str(st.get("verdict") or "")[:400])}</p>'
            + (f'<div class="two"><div><h4>covered</h4><ul>{cov}</ul></div>'
               f'<div><h4>not evidenced</h4><ul>{mis}</ul></div></div>'
               if (cov or mis) else '')
            + '</div>')
    if cl:
        if not cl.get('enabled', True):
            cards.append(
                f'<div class="card"><h3>Claims &amp; policy</h3>'
                f'<p class="sub">{esc(cl.get("note", "Switched off."))}</p></div>')
        else:
            items = ''.join(
                f'<li>{_ts_link(c.get("start_seconds"))} '
                f'<b>{esc(c.get("claim_class"))}</b> '
                f'<span class="sub">risk {esc(c.get("risk"))}</span><br>'
                f'<span class="quote">{esc(str(c.get("text") or "")[:180])}</span></li>'
                for c in (cl.get('claims') or [])[:8])
            cards.append(
                f'<div class="card wide"><h3>Claims &amp; policy</h3>'
                f'<p>{cl.get("candidates", 0)} candidate(s), '
                f'{cl.get("flagged", 0)} flagged.</p>'
                f'<ul class="claims">{items}</ul>'
                f'<p class="disclaimer">{esc(cl.get("disclaimer", ""))}</p></div>')
    return _section('Hook, claims and standing', f'<div class="cards">{"".join(cards)}</div>') if cards else ''

def _recommendations_html(rec: dict, result: dict = None) -> str:
    if not rec or not rec.get('enabled', True):
        return ''
    recs = rec.get('recommendations') or []
    if not recs:
        # "Nothing to fix" is a claim about THESE verdicts. An advice block
        # carried over from another audit -- a re-render, a resumed job --
        # can assert it over a list that plainly contains FAILs, and a reader
        # believes the headline, not the table. Two independent things must
        # agree or the report abstains.
        _short = [v for v in ((result or {}).get('verdicts') or [])
                  if v.get('status') in ('FAIL', 'PARTIAL')]
        _note = rec.get('note', 'Nothing to fix.')
        if _short and 'Nothing to fix' in _note:
            _note = (f'{len(_short)} requirement(s) fell short, but the list '
                     f'of suggested edits is not available for this run. They '
                     f'are listed under "Every requirement" below. Re-run the '
                     f'audit to generate the edits.')
        return _section('What to change',
                        f'<p class="ok-note">{esc(_note)}</p>')
    # WHICH REQUIREMENT, in words. This printed `r_09c8913e` and a list of
    # `ev_...` ids, which say nothing to the person being asked to re-shoot.
    #
    # It went unnoticed because every report until now had ZERO
    # recommendations -- the model call that produces them was failing -- so
    # the reader-facing id check passed on an empty section. The first report
    # that actually carried advice leaked five raw ids.
    _label_for = {v.get('requirement_id'): v.get('requirement_label')
                  for v in ((result or {}).get('verdicts') or [])}
    items = ''.join(
        f'<li><div class="edit">{esc(r.get("edit"))}</div>'
        f'<div class="cites">{_ts_link(r.get("at_seconds"))} '
        f'<span class="tag">{esc(r.get("effort"))}</span> '
        f'<span class="sub">{esc(_label_for.get(r.get("requirement_id")) or "")}</span>'
        f'</div></li>'
        for r in recs)
    keep = ''.join(f'<li>{esc(k)}</li>' for k in (rec.get('keep') or []))
    keephtml = (f'<div class="keep"><h4>Keep as it is</h4><ul>{keep}</ul></div>'
                if keep else '')
    return _section('What to change', f'<ol class="recs">{items}</ol>{keephtml}',
                    rec.get('disclaimer', ''))

def _figures_html(figs: dict) -> str:
    body = ''.join(f'<div class="fig">{f["html"]}</div>'
                   for f in (figs.get('figures') or []))
    notes = ''.join(f'<li>{esc(n)}</li>' for n in (figs.get('notes') or []))
    if not body and not notes:
        return ''
    # "Figures not drawn (1)" is a note to whoever wrote the plotting
    # code. A reader who sees no chart does not need to be told one is
    # missing, and the reasons remain in the JSON.
    if not body:
        return ''
    return _section('Charts', body)

def _appendix_html(records: list, score: dict) -> str:
    rows = ''.join(
        f'<tr><td class="rid">{esc(r.id)}</td><td>{esc(getattr(r, "modality", ""))}</td>'
        f'<td class="num">{_ts_link(getattr(r, "start_seconds", None))}</td>'
        f'<td>{esc((getattr(r, "raw_text", "") or getattr(r, "description", "") or "")[:200])}</td>'
        f'</tr>'
        for r in sorted(records or [], key=lambda x: getattr(x, 'start_seconds', 0.0)))
    prov = score.get('provenance') or {}
    sf = score.get('scored_from') or {}
    meta = (f'<table class="prov"><tbody>'
            f'<tr><td>verdicts artifact</td><td class="rid">'
            f'{esc(sf.get("verdicts_cache_key"))}</td></tr>'
            f'<tr><td>brief</td><td class="rid">{esc(sf.get("brief_cache_key"))}</td></tr>'
            f'<tr><td>evidence</td><td class="rid">{esc(sf.get("evidence_cache_key"))}</td></tr>'
            f'<tr><td>score stage</td><td class="rid">'
            f'{esc(prov.get("stage_version"))} @ {esc(prov.get("created_at"))}</td></tr>'
            f'<tr><td>status points</td><td class="rid">'
            f'{esc(prov.get("status_score"))}</td></tr>'
            f'<tr><td>priority weights</td><td class="rid">'
            f'{esc(prov.get("priority_weight"))}</td></tr>'
            f'</tbody></table>')
    return _section(
        'Technical details',
        # The caveats live HERE, not beside the score. A reader deciding
        # whether to reshoot does not need to be told mid-sentence that a
        # threshold is provisional -- but anyone quoting the number across
        # campaigns does, so it is one click away rather than gone.
        '<p class="sub">Score thresholds are provisional until calibration '
        'is complete: compare scores to each other more confidently than to '
        'an absolute bar. Talking-point targets are provisional in the same '
        'way, and partial coverage of a point counts as a half.</p>'
        f'<details><summary>How this score was computed, and from which artifacts</summary>'
        f'{meta}<p class="sub">Every figure above is arithmetic over these '
        f'constants applied to the named verdicts artifact. No model wrote a '
        f'number on this page.</p></details>'
        f'<details><summary>Raw evidence ({len(records or [])} records)</summary>'
        f'<table class="eviden"><tbody>{rows}</tbody></table></details>')

_REPORT_CSS = """:root{
  --ink:#16191d; --ink-2:#5b6470; --ink-3:#8b95a1;
  --bg:#f4f6f8; --card:#fff; --line:#e3e8ee; --line-2:#eef2f6;
  --ok:#0f7b3f; --ok-bg:#e8f7ee;
  --warn:#8a5a00; --warn-bg:#fff6e0;
  --bad:#c0271c; --bad-bg:#fdecea;
  --info:#0b5fce; --info-bg:#e7f0fd;
  --accent:#4c3bcf;
  --radius:10px;
  --shadow:0 1px 2px rgba(16,24,40,.04),0 1px 3px rgba(16,24,40,.06);
}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);background:var(--bg);
  font:15px/1.6 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",
  Inter,Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.wrap{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
header{margin:0 0 22px}
h1{font-size:30px;line-height:1.2;letter-spacing:-.02em;margin:0 0 6px;
  font-weight:680}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--ink-3);margin:0 0 14px;font-weight:700}
h3{font-size:15px;margin:0 0 6px;font-weight:650;letter-spacing:-.01em}
h4{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  margin:14px 0 6px;color:var(--ink-3);font-weight:700}
section{background:var(--card);border:1px solid var(--line);
  border-radius:var(--radius);padding:22px 24px;margin:0 0 18px;
  box-shadow:var(--shadow)}
section.alert{border-color:var(--bad);border-left-width:3px;
  background:linear-gradient(180deg,var(--bad-bg) 0%,#fff 90px)}
.sub{color:var(--ink-2);font-size:13px;margin:3px 0}
/* ---- the verdict, read as a verdict ---- */
.headline{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.score-box{text-align:center;min-width:186px}
.big{font-size:68px;font-weight:700;line-height:1;letter-spacing:-.045em;
  font-variant-numeric:tabular-nums}
.big.none{font-size:22px;color:var(--ink-2);font-weight:600;letter-spacing:0}
.big.off{font-size:28px;color:var(--bad);line-height:1.2;letter-spacing:-.01em}
.headline.gated{border-left:3px solid var(--bad);padding-left:20px}
.dash{font-size:30px;color:var(--ink-3);padding:0 6px;font-weight:300}
.band{margin-top:10px;font-size:11px;font-weight:700;letter-spacing:.07em;
  padding:5px 12px;border-radius:999px;display:inline-block;
  background:var(--line-2);color:var(--ink-2);text-transform:uppercase}
.b-APPROVED{background:var(--ok-bg);color:var(--ok)}
.b-NEEDS_MINOR_REVISION{background:var(--warn-bg);color:var(--warn)}
.b-NEEDS_MAJOR_REVISION{background:#ffeede;color:#9a4a00}
.b-REJECTED,.b-OFF_BRIEF{background:var(--bad-bg);color:var(--bad)}
.crit{color:var(--bad);font-size:13px;margin:10px 0 0;font-weight:600}
/* ---- status pills ---- */
.pill{font-size:10.5px;font-weight:700;padding:4px 9px;border-radius:999px;
  white-space:nowrap;display:inline-block;letter-spacing:.04em;
  text-transform:uppercase}
.pill.ok{background:var(--ok-bg);color:var(--ok)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.unk{background:var(--line-2);color:var(--ink-2)}
.pill.na{background:#fafbfc;color:var(--ink-3)}
/* ---- tables ---- */
table{width:100%;border-collapse:collapse}
td,th{padding:12px 10px;border-bottom:1px solid var(--line-2);
  vertical-align:top;text-align:left}
tbody tr:last-child td{border-bottom:none}
th{font-size:10.5px;text-transform:uppercase;color:var(--ink-3);
  letter-spacing:.07em;font-weight:700}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
tr.absent td{color:var(--ink-3)}
table.reqs tbody tr:hover{background:#fafbfd}
/* ---- bars ---- */
.bar{background:var(--line-2);border-radius:999px;height:8px;min-width:130px;
  overflow:hidden}
.fill{height:100%;border-radius:999px}
.f-ok{background:var(--ok)}.f-warn{background:#c98a00}.f-bad{background:var(--bad)}
/* ---- requirement rows ---- */
.rq{font-weight:620;letter-spacing:-.005em}
.why{color:var(--ink-2);font-size:13.5px;margin:5px 0 0;max-width:72ch}
.cites{font-size:12px;color:var(--ink-3);margin-top:7px}
.rid{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:11px;color:#a8b1bc}
.ts{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:11.5px;background:var(--info-bg);color:var(--info);
  border-radius:5px;padding:2px 7px;text-decoration:none;margin-right:4px;
  cursor:pointer;transition:background .12s,color .12s}
.ts:hover{background:var(--info);color:#fff}
.ts-none{font-size:12px;color:var(--ink-3);font-style:italic}
/* ---- tags ---- */
.tag{font-size:10px;background:var(--line-2);color:var(--ink-2);
  border-radius:5px;padding:2px 7px;margin-left:6px;white-space:nowrap;
  font-weight:600;letter-spacing:.02em}
.tag.thin{background:var(--warn-bg);color:var(--warn)}
.tag.inferred{background:#eeecfd;color:var(--accent)}
.tag.safety{background:var(--line-2)}
.tag.subst{background:var(--info-bg);color:var(--info)}
.tag.align{background:#fafbfc;color:var(--ink-3)}
.tag.warn{background:#fff1e5;color:#9a3412;border:1px solid #ffd8a8}
/* ---- talking points ---- */
ul.tp{list-style:none;padding:0;margin:10px 0}
ul.tp li{padding:11px 14px;border-left:3px solid var(--line);margin-bottom:7px;
  background:#fafbfc;border-radius:0 7px 7px 0;font-size:14px}
ul.tp li.ok{border-left-color:var(--ok);background:var(--ok-bg)}
ul.tp li.no{border-left-color:#c26a00;background:var(--warn-bg)}
/* ---- cards ---- */
.cards{display:flex;flex-wrap:wrap;gap:16px}
.card{flex:1 1 320px;border:1px solid var(--line);border-radius:9px;
  padding:16px 18px;background:#fff}
.card.wide{flex:1 1 100%}
.two{display:flex;gap:26px;flex-wrap:wrap}.two>div{flex:1 1 260px}
.two ul{margin:0;padding-left:20px;font-size:13.5px}
.quote{font-style:normal;color:var(--ink);border-left:3px solid var(--line);
  padding:2px 0 2px 14px;margin:10px 0;font-size:14.5px;line-height:1.55}
.disclaimer{font-size:12.5px;color:var(--warn);background:var(--warn-bg);
  padding:11px 13px;border-radius:7px;margin-top:14px;line-height:1.5}
.approved{font-size:12.5px;color:var(--ok);margin:8px 0 0;font-weight:500}
.unapproved{font-size:13.5px;color:var(--bad);background:var(--bad-bg);
  border:1px solid var(--bad);border-radius:8px;padding:13px;margin:12px 0 0}
.contra{margin:0;padding-left:20px}.contra li{margin-bottom:14px}
.recs{margin:0;padding-left:22px}.recs li{margin-bottom:14px;max-width:76ch}
.edit{font-weight:650}
.keep{margin-top:18px;padding-top:14px;border-top:1px solid var(--line-2)}
.keep ul{margin:0;padding-left:20px;font-size:13.5px;color:var(--ink-2)}
.ok-note{color:var(--ok);font-size:14px;margin:0;font-weight:500}
/* ---- timeline ---- */
.timeline{display:flex;flex-direction:column;gap:7px}
.lane{display:flex;align-items:center;gap:11px}
.lane-name{width:70px;font-size:11px;color:var(--ink-2);text-align:right;
  font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.lane-n{width:30px;font-size:11px;color:var(--ink-3);
  font-variant-numeric:tabular-nums}
.track{position:relative;flex:1;height:16px;background:var(--line-2);
  border-radius:5px}
.track i{position:absolute;top:0;height:100%;border-radius:3px;opacity:.9}
.m-speech i{background:var(--info)}.m-ocr i{background:var(--accent)}
.m-visual i{background:var(--ok)}.m-metadata i{background:var(--ink-3)}
/* ---- disclosure ---- */
details{margin-top:14px}
summary{cursor:pointer;font-size:13px;color:var(--info);font-weight:500;
  padding:5px 0;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"\25b8 ";color:var(--ink-3)}
details[open]>summary::before{content:"\25be "}
.fig{margin:0 0 18px}
video{width:100%;max-height:460px;background:#000;border-radius:9px;
  display:block}
.player-wrap{max-width:320px}
.topgrid{display:flex;gap:26px;flex-wrap:wrap;align-items:center}
.topgrid>div:last-child{flex:1 1 400px}
table.prov td{font-size:12.5px;padding:7px 10px}
table.prov td:first-child{color:var(--ink-2);width:170px}
/* ---- containers the markup has always emitted and nothing ever styled ----
   Each of these was inheriting browser defaults: the dimension table had no
   column widths, the evidence appendix ran full-bleed at body size, and the
   score meta line sat at 15px next to a 68px number. */
.score-meta{font-size:12.5px;color:var(--ink-2);margin-top:10px;
  line-height:1.5;max-width:46ch}
table.dims td{padding:11px 10px}
table.dims td:first-child{font-weight:600;width:34%}
.bar-cell{width:190px;min-width:150px;vertical-align:middle}
table.eviden{font-size:12.5px;table-layout:fixed}
table.eviden td{padding:7px 9px;word-break:break-word}
table.eviden td:first-child{width:130px}
table.eviden td:nth-child(2){width:80px;color:var(--ink-2)}
table.eviden td:nth-child(3){width:78px}
.fignotes{margin-top:6px}
.fignotes ul{margin:8px 0 0;padding-left:20px;font-size:12.5px;
  color:var(--ink-2)}
.fignotes li{margin-bottom:5px}
/* plotly injects .plotly-graph-div itself; it is not ours to style. */
@media (max-width:640px){
  .wrap{padding:24px 14px 60px}h1{font-size:24px}
  section{padding:18px 16px}.big{font-size:54px}
  .player-wrap{max-width:100%}
}
@media print{
  body{background:#fff}
  .wrap{max-width:none;padding:0}
  section{break-inside:avoid;box-shadow:none;border-color:#d8dee6;
    margin-bottom:12px}
  .ts{background:none;color:#000;padding:0}
  details{display:block}details>summary{display:none}
  video,.player-wrap{display:none}
  a[href]:after{content:""}
}
"""

_REPORT_JS = """
(function(){
  var v = document.getElementById('player');
  document.addEventListener('click', function(e){
    var a = e.target.closest ? e.target.closest('a.ts') : null;
    if(!a) return;
    e.preventDefault();
    var t = parseFloat(a.getAttribute('data-t'));
    if(!v || isNaN(t)) return;
    try{ v.currentTime = Math.max(0, t); v.play().catch(function(){}); }catch(_){}
    v.scrollIntoView({behavior:'smooth', block:'center'});
  }, false);
})();
"""

def build_report_html(video: dict, result: dict, compiled: dict, score: dict,
                      records: list, rec: dict = None, figs: dict = None,
                      proxy: dict = None, cfg: Phase7Config = None) -> str:
    """The whole page, as one string. No I/O."""
    cfg = cfg or P7
    records = records or []
    records_by_id = {r.id: r for r in records}
    duration = float(result.get('duration_seconds') or 0.0)
    vid = esc(result.get('video_id') or result.get('video_hash', '')[:16])

    if proxy and proxy.get('ok'):
        player = (f'<div class="player-wrap"><video id="player" controls '
                  f'preload="metadata" src="{proxy["data_uri"]}"></video>'
                  f'<p class="sub">{proxy["bytes"] / 1e6:.1f} MB embedded — '
                  f'this file needs no network.</p></div>')
    else:
        player = (f'<div class="player-wrap"><p class="sub">'
                  f'{esc((proxy or {}).get("note", "No player in this report."))}'
                  f'</p></div>')

    # The source filename, when we have it: a reviewer works from filenames,
    # not from content hashes, and "which video is this" should not require
    # looking anything up.
    _srcname = Path(video.get('path') or '').name if video.get('path') else ''
    # WHAT A READER NEEDS, in the order they need it: which video, how long,
    # which campaign, when. The content hashes that used to sit here are
    # traceability, not orientation -- they live in the technical appendix.
    _campaign = str((compiled or {}).get('campaign') or '').strip()
    _bits = []
    if _srcname:
        _bits.append(esc(_srcname))
    _bits.append(f'{duration:.1f}s')
    if _campaign:
        _bits.append(esc(_campaign))
    _bits.append(time.strftime('%d %b %Y'))
    head = (f'<header><h1>Creative audit</h1>'
            f'<p class="sub">{" &middot; ".join(_bits)}</p>'
            + _approval_html(compiled or {}) + '</header>')

    body = (
        f'{head}'
        f'<section><div class="topgrid">{player}<div>{_headline_html(score)}</div>'
        f'</div></section>'
        # QUESTION 1 before QUESTION 2. Contradictions still outrank it: two
        # parts of the system disagreeing is the one thing worth reading first.
        f'{_contradictions_html(score)}'
        f'{_crux_html(result, score)}'
        # What is this video, then does it match. In that order.
        f'{_angle_html(result)}'
        f'{_talking_points_html(result, compiled or {}, score)}'
        f'{_dimensions_html(score)}'
        f'{_recommendations_html(rec or {}, result)}'
        f'{_requirements_html(result, score, records_by_id)}'
        f'{_timeline_html(records, duration)}'
        f'{_modules_html(result)}'
        f'{_figures_html(figs or {})}'
        f'{_appendix_html(records, score)}'
        f'<footer class="sub">Every number on this page is arithmetic over '
        f'recorded evidence. No model wrote a score.</footer>')

    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Creative audit — {vid}</title>'
            f'<style>{_REPORT_CSS}</style></head><body><div class="wrap">'
            f'{body}</div><script>{_REPORT_JS}</script></body></html>')

def write_report(video: dict, result: dict, compiled: dict, score: dict,
                 records: list, rec: dict = None, figs: dict = None,
                 cfg: Phase7Config = None, verbose: bool = True) -> dict:
    """Render and write both artifacts: the JSON contract and the HTML page."""
    cfg = cfg or P7
    t0 = time.time()
    vh = result.get('video_hash', '')
    vdir = DIRS['artifacts'] / vh
    vdir.mkdir(parents=True, exist_ok=True)
    key = score.get('cache_key', '')

    proxy = build_proxy_video(video, cfg, verbose=verbose)
    html = build_report_html(video, result, compiled, score, records, rec,
                             figs, proxy, cfg)
    html_path = vdir / f'report__{key}.html'
    html_path.write_text(html, encoding='utf-8')

    # spec §84: the machine contract, carrying everything the page shows.
    payload = {
        'schema_version': REPORT_STAGE_VERSION,
        'video': {'video_id': result.get('video_id', ''), 'video_hash': vh,
                  'duration_seconds': result.get('duration_seconds')},
        'brief': {'brief_hash': result.get('brief_hash', ''),
                  'cache_key': compiled.get('cache_key', ''),
                  'approved': bool(compiled.get('approved'))},
        'score': score,
        'recommendations': rec or {},
        'figures': {'count': len(((figs or {}).get('figures') or [])),
                    'plotly_available': (figs or {}).get('plotly_available'),
                    'notes': (figs or {}).get('notes') or []},
        'report_html': html_path.name,
        'proxy_video': {k: v for k, v in (proxy or {}).items() if k != 'data_uri'},
        'provenance': provenance('report', REPORT_STAGE_VERSION, key,
                                 time.time() - t0,
                                 report_html_version=REPORT_HTML_VERSION,
                                 recommend_prompt=(rec or {}).get('prompt_version')),
    }
    json_path = vdir / f'report__{key}.json'
    write_json(json_path, payload)
    if verbose:
        print(f'  report -> {html_path.name}  ({len(html) / 1024:.0f} KB)')
        print(f'  json   -> {json_path.name}')
    return {'html_path': html_path, 'json_path': json_path, 'html': html,
            'payload': payload}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 1164: print('§79 report loaded.  One self-contained HTML file + the §84 JSON contr
#   line 1165: print('  Design rule: every number traces to a requirement, every requiremen
#   line 1166: print('  to an evidence id. Untraceable things do not go on the page.')
