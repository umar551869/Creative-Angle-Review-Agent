"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 142.
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
try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
    PLOTLY_ERR = ''
except Exception as _exc:                      # pragma: no cover
    go = None
    PLOTLY_OK = False
    PLOTLY_ERR = f'{type(_exc).__name__}: {_exc}'

FIGURE_STAGE_VERSION = '1.0.0'

# Measured, not guessed: plotly 7.x embeds ~4.8 MB, not the ~3.5 MB an earlier
# draft of the plan assumed. It is embedded ONCE for the whole page however
# many figures follow, and it is the largest thing in the report -- so the
# number belongs where a reader of the config can see it.
PLOTLY_BUNDLE_MB = 4.8

def _unit_time(v: dict, records_by_id: dict) -> Optional[float]:
    """
    When in the video this unit was decided -- the earliest record it cites.

    Falls back to examined_ids, because a verdict that cites nothing was still
    evaluated against something. Returns None when neither exists, and the
    caller drops the point rather than inventing a position for it.
    """
    for key in ('evidence_ids', 'examined_ids'):
        times = [getattr(records_by_id[i], 'start_seconds', None)
                 for i in (v.get(key) or []) if i in records_by_id]
        times = [t for t in times if t is not None]
        if times:
            return round(min(times), 3)
    return None

def _trace_provenance(fig) -> dict:
    """
    Does every plotted MARKER carry the evidence behind it?

    Answered from the figure OBJECT, never by grepping the rendered HTML. The
    first figure on a page embeds the whole ~4.8 MB plotly bundle, and that
    bundle contains the word "customdata" and every trace-type name as schema
    keys -- so a string search finds them whatever the data says. An earlier
    version of the §81 criterion did exactly that and verified nothing.

    A surface or heatmap plots AGGREGATE mass, not markers; there is no single
    record behind a cell, so it is reported as `aggregate` rather than failed.
    """
    marker_types = ('scatter3d', 'scatter', 'scattergl')
    per_marker = [t for t in fig.data if getattr(t, 'type', '') in marker_types]
    if not per_marker:
        return {'kind': 'aggregate', 'traceable': True,
                'detail': 'aggregate view; no per-marker record to cite'}
    missing = [getattr(t, 'name', '?') for t in per_marker
               if getattr(t, 'customdata', None) is None
               and getattr(t, 'hoverinfo', '') != 'skip']
    return {'kind': 'markers', 'traceable': not missing,
            'detail': (f'{len(per_marker) - len(missing)}/{len(per_marker)} '
                       f'trace(s) carry their source'
                       + (f'; missing on {missing[:3]}' if missing else ''))}

def _fig_html(fig, div_id: str, first: bool) -> str:
    """
    One figure as embeddable HTML.

    `include_plotlyjs` is True for the FIRST figure only: the ~3.5 MB library
    is embedded once for the whole page, however many figures follow.
    `div_id` is explicit so the same artifact renders byte-identically.
    """
    return fig.to_html(full_html=False,
                       include_plotlyjs=(True if first else False),
                       div_id=div_id,
                       config={'displaylogo': False, 'responsive': True})

def _axis_dimensions():
    """Fixed category order, spec §39. Reversed so Hook reads at the top."""
    return [DIMENSION_LABEL[k] for k in DIMENSION_KEYS]

def figure_dimension_time(score: dict, result: dict, records_by_id: dict,
                          cfg: Phase7Config) -> tuple:
    """
    Figure 1 -- dimension x time x score (3D scatter).

    THE question: where in the video does each dimension live, and where did it
    fail? A CTA dimension whose every marker sits at 0-3 s explains a failure
    that a table only states. Genuinely three-dimensional: time, category,
    outcome -- and the shape IS the finding.

    Every marker carries its evidence ids in customdata, so the design rule
    holds: nothing is plotted that cannot be traced back to a record.
    """
    req_index = {}
    for k, d in (score.get('dimensions') or {}).items():
        for rid in d.get('requirement_ids') or []:
            req_index[rid] = DIMENSION_LABEL[k]

    rows = []
    for v in result.get('verdicts') or []:
        if v.get('status') == 'NOT_APPLICABLE':
            continue
        rid = v.get('requirement_id', '')
        dim = req_index.get(rid)
        if not dim:
            continue
        t = _unit_time(v, records_by_id)
        if t is None:
            continue
        rows.append((t, dim, v))
    if not rows:
        return None, 'No scoring unit cites a record with a timestamp.'

    rows.sort(key=lambda r: (r[1], r[0], r[2].get('requirement_id', '')))
    duration = float(result.get('duration_seconds') or 0) or max(r[0] for r in rows)
    traces = []
    for status in ('PASS', 'PARTIAL', 'FAIL', 'UNCERTAIN'):
        sel = [r for r in rows if r[2].get('status') == status]
        if not sel:
            continue
        traces.append(go.Scatter3d(
            x=[r[0] for r in sel],
            y=[r[1] for r in sel],
            z=[STATUS_SCORE.get(status, 0.0) for _r in sel],
            mode='markers',
            name=f'{status} ({len(sel)})',
            marker=dict(
                size=[6 + 3 * PRIORITY_WEIGHT.get(r[2].get('priority') or 'medium', 1.0)
                      for r in sel],
                color=cfg.report.status_colour.get(status, '#57606a'),
                symbol=cfg.report.status_symbol.get(status, 'circle'),
                line=dict(width=0)),
            customdata=[[r[2].get('requirement_id', ''),
                         str(r[2].get('requirement_label') or '')[:80],
                         str(r[2].get('reason') or '')[:160],
                         ', '.join((r[2].get('evidence_ids') or [])[:4]) or 'none']
                        for r in sel],
            hovertemplate=('<b>%{customdata[1]}</b><br>'
                           'at %{x:.2f}s &middot; %{y}<br>'
                           '%{customdata[2]}<br>'
                           'cites: %{customdata[3]}<extra></extra>')))
    fig = go.Figure(traces)
    fig.update_layout(
        title='Where each dimension lives, and how it did',
        height=cfg.report.figure_height,
        margin=dict(l=0, r=0, t=46, b=0),
        scene=dict(
            xaxis=dict(title='seconds', range=[0, max(duration, 1.0)]),
            yaxis=dict(title='', categoryorder='array',
                       categoryarray=_axis_dimensions()),
            zaxis=dict(title='unit score', range=[-0.05, 1.05],
                       tickvals=[0.0, 0.5, 1.0])),
        legend=dict(orientation='h', y=-0.02))
    return fig, ''

def figure_ask_vs_delivery(score: dict, cfg: Phase7Config) -> tuple:
    """
    Figure 4 -- what the brief asks for vs what the video delivered (2D).

    Distance below the diagonal is under-delivery SCALED BY HOW MUCH IT
    MATTERS: a 20%-weight dimension at 0.3 is a bigger problem than a 10% one
    at 0.2, and putting weight on the x axis puts that difference where the eye
    reads it.

    Two quantities, two axes. A third would make this harder to read, not
    richer -- which is the whole argument for keeping it 2D.

    Dimensions the brief does not cover are drawn hollow on the axis, so "the
    brief said nothing about audience" is VISIBLE rather than simply absent.
    """
    dims = score.get('dimensions') or {}
    cov = [(k, dims[k]) for k in DIMENSION_KEYS
           if dims.get(k, {}).get('covered')]
    absent = [(k, dims[k]) for k in DIMENSION_KEYS
              if not dims.get(k, {}).get('covered')]
    if not cov:
        return None, 'No dimension in this brief carries a scoring unit.'

    traces = [go.Scatter(x=[0, 1], y=[0, 100], mode='lines',
                         name='perfect delivery',
                         line=dict(dash='dot', width=1, color='#8c959f'),
                         hoverinfo='skip')]
    traces.append(go.Scatter(
        x=[d['weight_raw'] for _k, d in cov],
        y=[d['score'] if d['score'] is not None else 0 for _k, d in cov],
        mode='markers+text',
        name='covered by this brief',
        text=[d['label'] for _k, d in cov],
        textposition='top center',
        marker=dict(size=[14 + 10 * d['weight_raw'] for _k, d in cov],
                    color=['#cf222e' if (d['score'] or 0) < 50 else
                           '#9a6700' if (d['score'] or 0) < 85 else '#1a7f37'
                           for _k, d in cov],
                    symbol=['diamond' if d['thin'] else 'circle'
                            for _k, d in cov],
                    line=dict(width=1, color='#24292f')),
        customdata=[[d['units'], 'yes' if d['thin'] else 'no',
                     f"{d['coverage']:.0%}"] for _k, d in cov],
        hovertemplate=('<b>%{text}</b><br>brief weight %{x:.0%}<br>'
                       'delivered %{y:.0f}<br>'
                       'from %{customdata[0]} unit(s), thin: %{customdata[1]}<br>'
                       'coverage %{customdata[2]}<extra></extra>')))
    if absent:
        # These markers state a fact about the BRIEF, not about the video, so
        # there is no evidence id to cite -- but they are still traceable, and
        # customdata carries what they come from: zero requirements of that
        # type in the compiled brief. "No source" and "a source that is an
        # absence" are different, and only the second one is true here.
        traces.append(go.Scatter(
            x=[d['weight_raw'] for _k, d in absent],
            y=[0 for _ in absent], mode='markers+text',
            name='brief says nothing',
            text=[d['label'] for _k, d in absent],
            textposition='bottom center',
            marker=dict(size=11, color='rgba(0,0,0,0)', symbol='circle-open',
                        line=dict(width=1.5, color='#8c959f')),
            customdata=[[k, 0] for k, _d in absent],
            hovertemplate=('<b>%{text}</b><br>the compiled brief carries '
                           '%{customdata[1]} requirement(s) of type '
                           '"%{customdata[0]}", so this dimension is excluded '
                           'from the score entirely<extra></extra>')))
    fig = go.Figure(traces)
    fig.update_layout(
        title='What the brief asks for, and what the video delivered',
        height=cfg.report.figure_height,
        margin=dict(l=8, r=8, t=46, b=8),
        xaxis=dict(title='how much the brief weights it', range=[-0.01, 0.26],
                   tickformat='.0%'),
        yaxis=dict(title='delivered', range=[-6, 106]),
        legend=dict(orientation='h', y=-0.16))
    return fig, ''

def _alignment_rows(score: dict, result: dict, records_by_id: dict) -> list:
    """
    (time, requirement, dimension, alignment, weight, verdict) per scoring unit.

    `alignment` may be None, and None is NOT 'none'. 'none' means judged and
    found unrelated; None means nobody judged it -- a PASS earned by absence,
    or a layer that declined. Plotting the two at the same height would assert
    something that did not happen, so the caller draws them apart.
    """
    dim_of_req = {}
    for k, d in (score.get('dimensions') or {}).items():
        for rid in d.get('requirement_ids') or []:
            dim_of_req[rid] = DIMENSION_LABEL[k]
    rows = []
    for v in result.get('verdicts') or []:
        if v.get('status') == 'NOT_APPLICABLE':
            continue
        rid = v.get('requirement_id', '')
        rows.append({
            't': _unit_time(v, records_by_id),
            'rid': rid,
            'label': str(v.get('requirement_label') or rid)[:60],
            'dim': dim_of_req.get(rid, DIMENSION_LABEL['brand']),
            'alignment': v.get('alignment'),
            'weight': PRIORITY_WEIGHT.get(v.get('priority') or 'medium', 1.0),
            'v': v,
        })
    # Deterministic order: by dimension (spec §39 order), then by id.
    order = {DIMENSION_LABEL[k]: i for i, k in enumerate(DIMENSION_KEYS)}
    rows.sort(key=lambda r: (order.get(r['dim'], 99), r['rid']))
    return rows

def figure_alignment_landscape(score: dict, result: dict, records_by_id: dict,
                               cfg: Phase7Config) -> tuple:
    """
    Figure 5 -- WHAT aligns with the brief, WHERE, and HOW WELL (3D scatter).

    THE question, and the one a creator manager actually asks: which of the
    brief's asks did this video deliver, at what point, and how closely?

    x = time in the video          where the evidence sits
    y = the brief's ask            one row per scoring unit, grouped by dimension
    z = alignment                  none 0.0 -> exact 1.0

    Genuinely three-dimensional: the ask, the moment, and the closeness. The
    SHAPE is the finding -- a brief whose asks all align strongly but cluster
    in the first three seconds is a different problem from one whose asks are
    spread evenly and align weakly, and a table states neither.

    Alignment is not status. A requirement can PASS on literal wording while
    aligning only `partial`, and one can FAIL the literal wording while
    aligning `strong` -- that second case is the creator putting the brief's
    ask in her own words, and it is the thing this figure makes visible.

    Unjudged units are drawn BELOW the axis, hollow, on their own row. Nobody
    looked at them; they are not zeroes.
    """
    rows = _alignment_rows(score, result, records_by_id)
    if not rows:
        return None, 'No scoring unit to plot.'
    judged = [r for r in rows if r['alignment'] in ALIGNMENT_WEIGHTS]
    unjudged = [r for r in rows if r['alignment'] not in ALIGNMENT_WEIGHTS]
    if not judged:
        return None, ('No verdict carries an alignment, so there is nothing to '
                      'plot. Alignment is filled in at L1 and by L3; a run '
                      'decided entirely by gates will have none.')

    duration = float(result.get('duration_seconds') or 0) or max(
        (r['t'] for r in rows if r['t'] is not None), default=1.0)
    cats = [r['label'] for r in rows]

    # Colour by alignment level, and SYMBOL too, so the figure survives
    # greyscale printing and the common forms of colour blindness.
    level_colour = {'exact': '#1a7f37', 'strong': '#2da44e',
                    'partial': '#bf8700', 'tangential': '#cf6b22',
                    'none': '#cf222e'}
    level_symbol = {'exact': 'circle', 'strong': 'diamond',
                    'partial': 'square', 'tangential': 'cross', 'none': 'x'}

    traces = []
    for lvl in reversed(ALIGNMENT_LEVELS):          # exact first in the legend
        sel = [r for r in judged if r['alignment'] == lvl and r['t'] is not None]
        if not sel:
            continue
        traces.append(go.Scatter3d(
            x=[r['t'] for r in sel],
            y=[r['label'] for r in sel],
            z=[ALIGNMENT_WEIGHTS[lvl] for _r in sel],
            mode='markers',
            name=f'{lvl} ({len(sel)})',
            marker=dict(size=[7 + 3 * r['weight'] for r in sel],
                        color=level_colour.get(lvl, '#57606a'),
                        symbol=level_symbol.get(lvl, 'circle'),
                        line=dict(width=0)),
            customdata=[[r['dim'], r['v'].get('status', ''),
                         str(r['v'].get('alignment_reason')
                             or r['v'].get('reason') or '')[:170],
                         ', '.join((r['v'].get('evidence_ids') or [])[:4]) or 'none',
                         r['v'].get('priority', '')]
                        for r in sel],
            hovertemplate=('<b>%{y}</b><br>'
                           '%{customdata[0]} &middot; %{customdata[4]} priority<br>'
                           'aligns <b>' + lvl + '</b> (%{z:.2f}) at %{x:.2f}s<br>'
                           'verdict: %{customdata[1]}<br>'
                           '%{customdata[2]}<br>'
                           'cites: %{customdata[3]}<extra></extra>')))

    # Judged, but citing nothing with a timestamp: real alignment, unknown
    # moment. Pinned at t=0 and named, rather than dropped.
    no_time = [r for r in judged if r['t'] is None]
    if no_time:
        traces.append(go.Scatter3d(
            x=[0.0 for _r in no_time], y=[r['label'] for r in no_time],
            z=[ALIGNMENT_WEIGHTS[r['alignment']] for r in no_time],
            mode='markers', name=f'no timestamp ({len(no_time)})',
            marker=dict(size=7, color='#8c959f', symbol='circle-open',
                        line=dict(width=1)),
            customdata=[[r['rid'],
                         ', '.join((r['v'].get('evidence_ids') or [])[:4])
                         or 'none'] for r in no_time],
            hovertemplate=('<b>%{y}</b><br>aligns %{z:.2f}, but cites no '
                           'record carrying a timestamp<br>'
                           '%{customdata[0]} &middot; cites: '
                           '%{customdata[1]}<extra></extra>')))

    if unjudged:
        traces.append(go.Scatter3d(
            x=[(r['t'] if r['t'] is not None else 0.0) for r in unjudged],
            y=[r['label'] for r in unjudged],
            z=[-0.12 for _r in unjudged],
            mode='markers', name=f'not judged ({len(unjudged)})',
            marker=dict(size=6, color='rgba(0,0,0,0)', symbol='circle-open',
                        line=dict(width=1.4, color='#8c959f')),
            customdata=[[r['v'].get('status', '')] for r in unjudged],
            hovertemplate=('<b>%{y}</b><br>no alignment was judged '
                           '(verdict %{customdata[0]}).<br>This is "nobody '
                           'looked", not "unrelated".<extra></extra>')))

    fig = go.Figure(traces)
    fig.update_layout(
        title='What aligns with the brief, where in the video, and how closely',
        height=max(cfg.report.figure_height, 320 + 16 * len(cats)),
        margin=dict(l=0, r=0, t=46, b=0),
        scene=dict(
            xaxis=dict(title='seconds', range=[-0.5, max(duration, 1.0)]),
            yaxis=dict(title='', categoryorder='array', categoryarray=cats,
                       tickfont=dict(size=9)),
            zaxis=dict(title='how closely it aligns', range=[-0.2, 1.08],
                       tickvals=[-0.12, 0.0, 0.25, 0.55, 0.85, 1.0],
                       ticktext=['not judged', 'none', 'tangential', 'partial',
                                 'strong', 'exact']),
            camera=dict(eye=dict(x=1.7, y=-1.5, z=0.9))),
        legend=dict(orientation='h', y=-0.02))
    return fig, ''

def figure_alignment_shape(score: dict, result: dict, records_by_id: dict,
                           cfg: Phase7Config) -> tuple:
    """
    Figure 6 -- the SHAPE of alignment across the brief (3D surface).

    THE question: is this video evenly close to the brief, or strong in one
    dimension and absent in another?

    x = alignment level, ordinal none -> exact
    y = dimension
    z = weight mass sitting at that closeness

    A surface is right because the reader is looking for where the mass PILES
    UP, which is a shape rather than a number. A ridge at `exact` down one
    dimension and a ridge at `none` down another says, at a glance, something
    a seven-row table does not.

    Weight, not count: a critical requirement aligning `none` should dominate
    the surface the way it dominates the score.
    """
    rows = [r for r in _alignment_rows(score, result, records_by_id)
            if r['alignment'] in ALIGNMENT_WEIGHTS]
    if not rows:
        return None, 'No verdict carries an alignment to shape.'
    dims = [DIMENSION_LABEL[k] for k in DIMENSION_KEYS
            if any(r['dim'] == DIMENSION_LABEL[k] for r in rows)]
    if len(dims) < 2:
        return None, (f'Only one dimension ({dims[0] if dims else "none"}) '
                      f'carries alignment; a surface needs at least two to '
                      f'have a shape.')
    z = [[sum(r['weight'] for r in rows
              if r['dim'] == d and r['alignment'] == lvl)
          for lvl in ALIGNMENT_LEVELS] for d in dims]
    fig = go.Figure(go.Surface(
        z=z, x=list(ALIGNMENT_LEVELS), y=dims,
        colorscale='YlGnBu', cmin=0,
        colorbar=dict(title='weight'),
        hovertemplate=('%{y}<br>aligns %{x}<br>weight mass '
                       '%{z:.1f}<extra></extra>')))
    fig.update_layout(
        title='Where the brief\'s weight sits, by closeness',
        height=cfg.report.figure_height,
        margin=dict(l=0, r=0, t=46, b=0),
        scene=dict(xaxis=dict(title='closeness'),
                   yaxis=dict(title=''),
                   zaxis=dict(title='weight'),
                   camera=dict(eye=dict(x=1.8, y=-1.6, z=0.8))))
    return fig, ''

def figure_run_stability(scores: list, cfg: Phase7Config) -> tuple:
    """
    Figure 2 -- run x dimension x subscore (3D surface).

    THE question: which dimensions are stable, and which is the model guessing?

    This plots the instability that dominated Phase 6 validation -- alignment
    moved 0.34 on identical inputs -- and localises it per dimension. A ridge
    that stays flat across runs is a dimension you can trust; one that
    oscillates is where Phase 8's labels should go first.

    A surface is right because the reader is looking for FLATNESS, which is a
    shape rather than a number. Needs three runs; with fewer, a surface is a
    meaningless plane and the figure is skipped.
    """
    if len(scores) < 3:
        return None, (f'Needs 3 runs of the same video and brief to show '
                      f'stability; {len(scores)} available. Re-run the audit '
                      f'with force=True to collect more.')
    keys = [k for k in DIMENSION_KEYS
            if any((s.get('dimensions') or {}).get(k, {}).get('covered')
                   for s in scores)]
    if not keys:
        return None, 'No covered dimension across these runs.'
    z = [[((s.get('dimensions') or {}).get(k, {}).get('score') or 0.0)
          for s in scores] for k in keys]
    fig = go.Figure(go.Surface(
        z=z,
        x=list(range(1, len(scores) + 1)),
        y=[DIMENSION_LABEL[k] for k in keys],
        colorscale='RdYlGn', cmin=0, cmax=100,
        colorbar=dict(title='subscore'),
        hovertemplate=('run %{x}<br>%{y}<br>subscore %{z:.0f}<extra></extra>')))
    fig.update_layout(
        title=f'Stability across {len(scores)} runs of the same video and brief',
        height=cfg.report.figure_height,
        margin=dict(l=0, r=0, t=46, b=0),
        scene=dict(xaxis=dict(title='run', dtick=1),
                   yaxis=dict(title=''),
                   zaxis=dict(title='subscore', range=[0, 100])))
    return fig, ''

def figure_batch(scores: list, cfg: Phase7Config) -> tuple:
    """
    Figure 3 -- video x dimension x subscore (3D bars, drawn as a heatmap).

    THE question: across a batch of creators on one brief, who is weak where?

    Only worth drawing for more than one video -- for a single audit it is a
    bar chart pretending to be a landscape. Plotly has no true 3D bar, and
    faking one with mesh cubes adds occlusion without adding information, so
    this is a heatmap: same three quantities, read far more accurately.
    """
    if len(scores) < 2:
        return None, ('Only one video has been scored against this brief. '
                      'A batch view needs at least two.')
    keys = [k for k in DIMENSION_KEYS
            if any((s.get('dimensions') or {}).get(k, {}).get('covered')
                   for s in scores)]
    if not keys:
        return None, 'No covered dimension across these videos.'
    labels = [(s.get('video_id') or s.get('video_hash', ''))[:12] for s in scores]
    z = [[((s.get('dimensions') or {}).get(k, {}).get('score'))
          for s in scores] for k in keys]
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=[DIMENSION_LABEL[k] for k in keys],
        colorscale='RdYlGn', zmin=0, zmax=100, hoverongaps=False,
        colorbar=dict(title='subscore'),
        hovertemplate='%{x}<br>%{y}<br>subscore %{z:.0f}<extra></extra>'))
    fig.update_layout(title=f'{len(scores)} videos on this brief, by dimension',
                      height=cfg.report.figure_height,
                      margin=dict(l=8, r=8, t=46, b=8))
    return fig, ''

def build_figures(score: dict, result: dict, records: list,
                  sibling_scores: list = None, cfg: Phase7Config = None) -> dict:
    """
    Every figure the available data supports, as embeddable HTML.

    A figure that cannot be drawn returns a NOTE saying why, and the note goes
    on the page. "Needs 3 runs; 1 available" is information; a silently missing
    chart is not.
    """
    cfg = cfg or P7
    out = {'plotly_available': PLOTLY_OK, 'plotly_error': PLOTLY_ERR,
           'figures': [], 'notes': [], 'schema_version': FIGURE_STAGE_VERSION}
    if not PLOTLY_OK:
        out['notes'].append(
            'Plotly is not available in this environment, so the figures were '
            f'not drawn. Everything else in this report is unaffected. ({PLOTLY_ERR})')
        return out
    # The flag has to DO something. A config field that silently has no effect
    # is worse than no field -- it tells you the feature is off while it runs
    # anyway, which is exactly the bug Phase 6 fixed in ClaimsConfig.enabled.
    #
    # Off means no figures at all, not figures from a CDN: a compliance report
    # that needs the internet to draw its own charts is not self-contained.
    if not cfg.report.embed_plotly:
        out['notes'].append(
            'Figures were skipped: P7.report.embed_plotly is False. The '
            'embedded Plotly bundle is the largest thing in this report '
            f'(~{PLOTLY_BUNDLE_MB:.1f} MB), so turning it off is the way to '
            'get a small file. Linking a CDN instead is not offered -- the '
            'report must open with no network.')
        return out

    records_by_id = {r.id: r for r in (records or [])}
    sibling_scores = sibling_scores or []
    # Alignment first: "what aligns with the brief, and how well" is the
    # question a creator manager opens the report to answer. Status and
    # dimensions follow.
    #
    # These two are NOT withheld when the relevance gate is closed. They are
    # the evidence FOR the gate -- a landscape with everything at `none` shows
    # at a glance why the video was called off brief, which a suppressed
    # figure cannot.
    plan = [
        ('fig-alignment-landscape', 'What aligns with the brief, and how well',
         lambda: figure_alignment_landscape(score, result, records_by_id, cfg)),
        ('fig-alignment-shape', 'The shape of that alignment',
         lambda: figure_alignment_shape(score, result, records_by_id, cfg)),
        ('fig-dimension-time', 'Where each dimension lives',
         lambda: figure_dimension_time(score, result, records_by_id, cfg)),
        ('fig-ask-delivery', 'Ask vs delivery',
         lambda: figure_ask_vs_delivery(score, cfg)),
        ('fig-stability', 'Stability across runs',
         lambda: figure_run_stability(sibling_scores, cfg)),
        ('fig-batch', 'Across videos on this brief',
         lambda: figure_batch(sibling_scores, cfg)),
    ]
    first = True
    for div_id, title, make in plan:
        try:
            fig, note = make()
        except Exception as exc:
            fig, note = None, f'{type(exc).__name__}: {str(exc)[:120]}'
        if fig is None:
            out['notes'].append(f'{title}: {note}')
            continue
        prov = _safe_provenance(fig)
        out['figures'].append({'id': div_id, 'title': title,
                               'html': _fig_html(fig, div_id, first),
                               'provenance': prov})
        first = False
    out['all_markers_traceable'] = all(
        f['provenance']['traceable'] for f in out['figures'])
    return out

def _safe_provenance(fig) -> dict:
    try:
        return _trace_provenance(fig)
    except Exception as exc:
        return {'kind': 'unknown', 'traceable': False,
                'detail': f'{type(exc).__name__}: {str(exc)[:60]}'}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 632: print(f"§79b figures loaded.  plotly={('yes' if PLOTLY_OK else 'NO -- report
#   line 633: print('  5 ask x time x alignment  (3D)   what aligns, where, how closely')
#   line 634: print("  6 dimension x closeness   (3D)   where the brief's weight sits")
#   line 635: print('  1 dimension x time x score(3D)   2 run x dimension (3D, stability)'
#   line 636: print('  3 videos x dimension (batch)     4 ask vs delivery (2D, on purpose)
