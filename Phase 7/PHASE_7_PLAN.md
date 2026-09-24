# Phase 7 — Deterministic scoring and reporting

**Objective (plan.md §7, spec §39/§40/§75):** a score computed by arithmetic,
never by a model, and a report a creator manager can act on faster than watching
the video.

**Status: BUILT — 2026-09-20.** Delivered as
`Phase 7/phases_1_to_7_gemini_vision.ipynb` (Phases 1–6 byte-identical to the
validated gemini notebook, plus 12 new code cells). Cell sources are kept
separately under `Phase 7/cells/` so they can be reviewed as files.

**Measured on delivery:** 48 scoring-arithmetic checks, 39 report checks, 69
in-notebook `§77` checks, 65 notebook cross-checks, and one end-to-end run of
§75 → §82 whose score was verified by hand. All green.

## What changed between this plan and what was built

Four deviations, each with its reason. A plan that does not record where the
build disagreed with it is a plan that quietly stops being true.

| planned | built | why |
|---|---|---|
| §1 as a standalone first step | **§75b**, placed after §75 and before §76 | the experiment reads `STATUS_SCORE` and `PRIORITY_WEIGHT`. A copy of those constants in the experiment would let it measure something the scorer does not compute; running it after §75 and before §76 keeps one definition and still answers the question before the scorer is trusted. |
| §1 asks the operator to label videos on-brief / off-brief | **no labels at all** — own brief vs foreign brief, paired per video | the original design was circular. "How close is this video to the brief" is what the system is *for*; requiring it as input defeats the product. The pairing a video was shot for is already in its audit, so the controls generate themselves. |
| one score, for every video | **a relevance gate, then a score** (§0a) | "wrong video" and "weak execution" are different findings needing different remedies, and one number cannot carry both. `standing` already answered the first question; §7.1 never asked it. |
| Jinja2 templating | explicit escaping through `esc()` | the deliverable is one file that opens with no network, and nobody non-technical edits these templates. Every insertion funnels through `esc()` and a handful of small builders, so escaping is auditable at the point of use — which for a compliance document beats autoescaping. Zero added dependency. |
| dimension map from the plan's 7-row table | all **11** `REQUIREMENT_TYPES` mapped, asserted at import | the table omitted `speech_or_text`, `brand` and `timing`. Unmapped types would have vanished from every dimension subscore while still counting in the overall score — a report whose parts do not sum to its whole. |
| priority weights restated in §75 | **reused** from Phase 4 | this document's §3 table dropped `low: 0.5`, which would have scored every low-priority requirement at double its weight. The constant now has exactly one definition in the notebook, and §77 asserts it. |

One thing the build added that the plan did not ask for: **§46's approval state
is now on the page**. A report compiled from an unapproved brief says so, in
red, at the top. The gate exists in Phase 6 and the reader of a report has no
other way to know it was not met.

---

## 0a. The score is conditional — two questions, asked in order

**This is the load-bearing change, and it came late.** Everything below §0
originally described one number. It should have described two questions:

1. **Is this video addressing this brief at all?** — a gate
2. **Given that it is, how closely did it follow what the brief asked for?** —
   the score

Collapsing them makes *"wrong video entirely"* and *"right video, weak
execution"* come out as the same low number. They are not the same finding.
The first needs a different video or the right brief attached; the second needs
the edits §78 proposes. A reviewer who cannot tell them apart from the report
has not been helped.

It also explains §0.1 cleanly. The alignment mean never discriminated because
**alignment measures form *within* an assumed-relevant video** — it was
answering question 2 all along, and I was using it for question 1. `standing`
answers question 1, and that is exactly why it separated perfectly.

**How it is built:**

| standing | treated as | what the report shows |
|---|---|---|
| `off_brief`, `tangential` | **gated** | "off brief", the whole-video verdict quoted, no score, no dimension bars, no edit suggestions |
| `partial`, `on_brief`, `exemplary` | scorable | the band, dimensions, and recommendations as normal |
| unjudged (no speech, L3 off, parse failure) | **scored anyway**, with a note | the gate **fails open** |

The gate **fails open** on purpose. It rests on one model call, and Phase 5's
`can_fail_on` rule applies unchanged: *an absent judgement is not a negative
one*. "We could not tell" must never silently become "off brief".

Nothing is destroyed. The full arithmetic is still computed and still written
to the score artifact — a gated audit simply may not *present* a number as its
answer. `score.gated` and `score.gate_reason` say which happened and why, and
the report points the reader at the appendix rather than hiding the figures.

A gated audit gets its own band, `OFF_BRIEF`, outside the normal ladder.
`NEEDS_MAJOR_REVISION` would imply revision is the remedy, and for a video
about a different product it is not.

---

## 0. What Phase 6's validation changed about this plan

`plan.md` was written before any of the system existed. Four things measured
during Phase 6 validation change how Phase 7 must be built. They are the reason
this document exists rather than just following §7.1.

### 0.1 The alignment mean does not discriminate — measured

Three audits of each video against the hair brief, current code, `force=True`:

| | on-brief (hair) | off-brief (pill organiser) |
|---|---|---|
| runs | 0.67, 0.57, 0.91 | 0.70, 0.85, 0.49 |
| range | 0.57–0.91 | 0.49–0.85 |
| **mean of means** | **0.72** | **0.68** |
| `standing` | `on_brief` 0.85 ×3 | `off_brief` 0.00 ×3 |

The ranges overlap across almost their entire span. **Mean alignment cannot be
the headline number.** `standing` separated perfectly, six runs, zero variance.

*Cause, confirmed from the compiled brief:* `group_intent` for the CTA group
reads *"Conclude the video with a clear call to action encouraging purchase or
continued use"* — subject-free. Any video ending with "link in bio" satisfies it.
Alignment measures **form**; standing measures **substance**. A video can be
structurally compliant and substantively off-brief, and both numbers are then
correct.

### 0.2 But the SPEC'S score is status-based, and has not been measured

§7.1 scores `PASS 1.0 / PARTIAL 0.5 / FAIL 0.0` — **status**, not alignment.
Everything above measured the alignment mean. These are different quantities and
the status score may well discriminate where alignment does not.

From the single off-brief run we have: `PASS 2, FAIL 4, NOT_APPLICABLE 16` →
status score **0.33**, and **0.00** once the two vacuous passes are removed.
That looks far more promising than 0.68.

**This is the first thing to do in Phase 7, before writing any scoring code.**
See §1.

### 0.3 Compliance-by-absence must not score as achievement

A `forbidden` rule passing because the video never went near the subject scored
1.0 and contributed 65% of an off-brief video's mean. Phase 6 now flags those
verdicts `PASS_FROM_ABSENCE` and refuses them an alignment.

**The same trap exists in a status score**: `PASS` is `PASS`. Phase 7 must
exclude `PASS_FROM_ABSENCE` verdicts from the achievement numerator and report
them separately as *"no violations found: N of N checks"*.

### 0.4 The score rests on 3–6 decisions, and that is permanent

Measured across this validation, every run of the same brief:

| requirements compiled | scored units |
|---|---|
| 21 | 5 |
| 22 | 6 |
| 25 | 4 |
| 26 | **3** |

**You're down to 3 scored units from 26 requirements.** §73's thin-score warning
is now permanently true — one L3 call moves the mean by a third.

That is *structural, and correct*: choice groups collapse a twelve-hook list to
one decision, which is the right thing to do. It is not a defect to fix in Phase
6. **It is Phase 7's problem to present honestly.** Concretely:

- the band from §4.2 is not a nicety here, it is the main output — with 3 units a
  single UNCERTAIN moves the pessimistic score by 33 points
- **never show two decimal places.** A number like `78.4` implies a precision
  three decisions cannot carry
- **always show the unit count beside the score.** "82, from 3 scoring units" is
  honest; "82" is not
- a per-dimension subscore computed from one unit should say so rather than
  render as a confident bar

### 0.5 Status now follows substance (`VERDICT 1.8.0`)

A FAIL whose alignment is `strong` contradicted itself — `strong` is defined as
*"different words, same ask and same intent"*. On an on-brief video, two
requirements FAILed at `strong` for a creator who had also opened with an
approved hook verbatim.

Such a verdict is now promoted in code — `strong`/`exact` → PASS, `partial` →
PARTIAL — with the literal finding kept on the verdict
(`LITERAL_STATUS_WAS:FAIL/strong`, `SATISFIED_IN_SUBSTANCE`). Forbidden rules and
FAILs from positive evidence are never promoted.

**This is what makes §1's candidate B worth measuring.** On the live run the
statuses went `FAIL 4, PASS 2` → `FAIL 0, PASS 4, PARTIAL 2`, while the alignment
mean stayed 0.80. A status-based score was previously measuring the
decomposition disagreeing with itself.

### 0.6 "Deterministic" means reproducible from an artifact, not stable across runs

The arithmetic is deterministic. Its **input** is not: L3 sampling moved the
alignment mean by 0.34 on identical inputs. A score is therefore reproducible
only against a specific `verdicts__*.json`.

Every report must name the verdict `cache_key` it scored, and the exit criterion
"score reproducible by hand" means *from that artifact*, not *from that video*.

---

## 1. Do this first: which quantity discriminates?

> **Built as §75b, and it needs NO human labels.**
>
> An earlier draft of this section asked the operator to list which videos were
> on brief and which were off. That was circular and wrong: *"how close is this
> video to the brief"* is the system's **output**, and demanding it as input
> makes the system pointless. The plan asked the user to do the job the product
> exists to do.
>
> The experiment never needed a judgement. It needs one fact from the
> production process — **which brief each video was shot for** — and that is
> already recorded in every audit, because §72 pairs a video with the brief you
> compiled for it. From there the comparison labels itself:
>
> | pairing | expectation |
> |---|---|
> | a video against **its own** brief | should score high |
> | the same video against a **foreign** brief | should score low |
>
> Same video, same evidence, same pipeline; only the brief changes. Any
> quantity worth putting on a report must separate those two.
>
> This is also a **paired** design, which is stronger than labelling: each
> video is its own control. A consistently strong or weak creator would skew a
> labelled comparison and cannot skew this one.
>
> **To answer it:** set `RUN_CONTROL_AUDITS = True` at the top of §75b and
> re-run. It reuses each video's cached evidence, so only the verdict stage
> re-runs — a few L3 calls per pairing, capped by `MAX_CONTROL_AUDITS`. §75b
> records which pairings it created in
> `work/artifacts/_discrimination/controls.json`, so controls never get
> mistaken for real audits.
>
> §76 currently leads with candidate **B** (status, achievement only), on the
> reasoning in §0.2 and §0.5. **If §75b names a different candidate, §76's
> headline must change and this section must record the result.**

**One experiment, no new code, no labels.** Until it is answered, any scoring
formula is a guess.

For every (video × brief) pairing on disk, native and control, compute all four
candidate scores from the verdict artifacts:

| candidate | formula |
|---|---|
| A — status, all | `Σ(w·s) / Σw` over non-`NOT_APPLICABLE`, `s = 1.0/0.5/0.0` |
| B — status, achievement only | as A, excluding `PASS_FROM_ABSENCE` |
| C — alignment mean | current §74 statistic (the one shown not to work) |
| D — standing weight | `BRIEF_STANDING_WEIGHTS[standing]` |

Report each as on-brief vs off-brief, with the spread across the three runs.

**Decision rule, written before seeing the numbers:**

- a candidate **discriminates** if every video scores higher against its own
  brief than against every foreign brief — the two populations must not overlap
- among those that discriminate, prefer the **largest margin**, then the
  smallest spread within each population
- if only D discriminates, standing is the headline and the requirement layer is
  detail only
- if B discriminates, it becomes the headline and standing becomes the
  cross-check

Write the result into this document before building. If it disagrees with §0.1,
say so plainly and follow the measurement.

---

## 2. Build order

Continuing the notebook's section numbering (Phase 6 ended at §74).

| § | What | Depends on |
|---|---|---|
| §75 | Scoring config: weights, bands, dimension map, all frozen in code | — |
| §76 | `score_audit(result, compiled)` → the score artifact | §75 |
| §77 | Phase 7 test suite — no model, no network | §76 |
| §78 | Recommendations (the only model call in this phase) | §76 |
| §79 | HTML report builder | §76, §78 |
| §79b | Plotly figures — dimension geometry | §76 |
| §80 | Score TARGET, render, write artifacts | §76–§79b |
| §81 | Phase 7 exit criteria | §80 |
| §82 | Full-pipeline self-check extension (Phases 1–7) | §81 |

---

## 3. §75 — Scoring configuration

Everything numeric lives here, in code, and nothing reads a number from a model.

```python
SCORE_STAGE_VERSION = '1.0.0'

STATUS_SCORE = {'PASS': 1.0, 'PARTIAL': 0.5, 'FAIL': 0.0}   # UNCERTAIN: see §4.2
PRIORITY_WEIGHT = {'critical': 3.0, 'high': 2.0, 'medium': 1.0}   # matches Phase 4
```

### 3.1 Dimension map

Spec §39's dimensions, mapped from the `type` field every requirement already
carries. Measured distribution across 101 compiled requirements:
`cta 35, hook 30, speech 17, policy 7, visual 6, demonstration 3, other 2,
audience 1`.

| dimension | weight | requirement `type` |
|---|---|---|
| Hook | 20% | `hook` |
| Product presence | 15% | `visual` |
| Product demonstration | 15% | `demonstration` |
| Messaging | 20% | `speech` |
| Audience alignment | 10% | `audience` |
| CTA | 10% | `cta` |
| Brand / format | 10% | `policy`, `other` |

**Normalise over the dimensions the brief actually covers.** A brief with no
`audience` requirement must not be scored out of 100% with 10% unreachable —
that silently caps every video at 90.

Record which dimensions were absent, in the artifact and in the report. "This
brief said nothing about audience" is a fact about the brief and belongs on the
page.

### 3.2 Bands

```
APPROVED               score >= 85 and no critical FAIL
NEEDS_MINOR_REVISION   70 <= score < 85
NEEDS_MAJOR_REVISION   50 <= score < 70
REJECTED               score < 50
```

**Any `critical`-priority FAIL forces at minimum `NEEDS_MAJOR_REVISION`**,
whatever the arithmetic says. A brief's critical requirement is not something a
good average may paper over.

These thresholds are **placeholders until Phase 8 calibration**, and must be
named as such in code the way `L2Config.high_threshold_PLACEHOLDER` is. Nothing
has yet established that 85 is the right line.

---

## 4. §76 — The scoring function

`score_audit(result, compiled, cfg) -> dict`. Pure arithmetic, no I/O, no model.
Cached like every other stage, keyed on the verdict `cache_key`.

### 4.1 What is scored

One entry per **scoring unit**, not per requirement — a `one_of` group is one
decision. Phase 6 already collapses groups and marks losers `NOT_APPLICABLE`.

```
units = [v for v in verdicts if v.status != 'NOT_APPLICABLE']
```

Then partition:

```
achievement = [v for v in units if 'PASS_FROM_ABSENCE' not in v.flags]
safety      = [v for v in units if 'PASS_FROM_ABSENCE'     in v.flags]
```

`safety` is **reported, never averaged** (§0.3): *"no violations found: 2 of 2
checks"*. If any safety check FAILs, that is a violation and belongs in the
headline regardless of score.

### 4.2 The UNCERTAIN band

Straight from plan.md §7.1, and it is the right call:

```
score_pessimistic = Σ(w·s) / Σw                    UNCERTAIN counted 0.0
score_optimistic  = Σ(w·s) / Σ(w non-UNCERTAIN)    UNCERTAIN excluded
coverage          = Σ(w non-UNCERTAIN) / Σw
```

Report **"78–91, 82% coverage"**. Show a single number as the headline only when
coverage > 90%; otherwise lead with the band.

This is Principle 4 (spec §3) implemented rather than worked around, and it is
the same discipline as Phase 5's `can_fail_on`: never let an absence of knowledge
masquerade as a finding.

### 4.3 Standing travels with the score

Whatever §1 decides, the artifact carries both:

```json
{"score": {"band": [78, 91], "coverage": 0.82, "status": "NEEDS_MINOR_REVISION"},
 "standing": {"level": "on_brief", "weight": 0.85},
 "contradictions": [...]}
```

### 4.4 The review gate is qualitative, not numeric

The numeric gap fires on noise — measured: an on-brief run produced a +0.28 gap
and would have flagged a perfectly good video. Gate on **contradictions** a human
can check:

- `standing` is `off_brief`/`tangential` while the requirement score is above the
  `APPROVED` line
- `standing` lists something under `missing` that a requirement scored `PASS`
- a `safety` check FAILed while the score is above `APPROVED`

Each contradiction names both sides and the evidence ids. Those are real
disagreements; an arithmetic gap between a stable number and a noisy one is not.

---

## 5. §77 — Test suite

Same standard as §71: no GPU, no network, no model, and every test names the
behaviour rather than the implementation.

Must cover:

- score reproducible by hand on a fixed verdict list (the headline exit criterion)
- `NOT_APPLICABLE` excluded from numerator **and** denominator
- a `one_of` group contributes exactly one unit
- `PASS_FROM_ABSENCE` excluded from achievement, counted in safety
- pessimistic ≤ optimistic, always
- coverage 1.0 when nothing is UNCERTAIN; both scores equal there
- a critical FAIL forces the band down from `APPROVED`
- a brief covering 4 of 7 dimensions normalises over 4
- an empty verdict list does not divide by zero
- every band boundary, on both sides
- no model output can reach a numeric field (assert on the artifact's shape)

---

## 6. §78 — Recommendations

The only model call in Phase 7. Everything above is arithmetic.

Constraints, carried over from Phase 6's anti-hallucination discipline:

- generated **only** from FAIL and PARTIAL units, plus the passing evidence for
  context — "add one sentence on barrier support after the application shot at
  0:11, without changing the opening", never "improve messaging"
- **timestamp-anchored**, and every anchor must come from a cited evidence id
- only offered evidence ids are citable; violations rejected and reported, as in
  L3
- no numbers, no scores, no status words in the output — it proposes edits
- abstains when there is nothing to fix, rather than inventing advice

---

## 7. §79 — Report artifacts

### 7.1 JSON (spec §84)

The machine contract. Full provenance: model ids, prompt versions, stage
durations, cache hits, config hash, and — per §0.4 — the verdict `cache_key` the
score was computed from.

### 7.2 Self-contained HTML

One file, opens anywhere, emailable, no server. Jinja2.

- embedded proxy video (~480p, CRF ~30, 1–2 MB for 30 s) as a base64 data URI
- score band + coverage, dimension bars, requirement list with status and
  timestamps
- **clickable timestamps that seek the player** (`video.currentTime = t`) — spec
  §40's key interaction, ~20 lines of vanilla JS
- evidence timeline strip: one bar per modality showing where evidence exists
- hook card, creative angle, standing, claims section with its disclaimer
- contradictions section (§4.4) when non-empty — this is what a reviewer reads
  first
- collapsible raw-evidence appendix

**Design rule:** every number on the page traces to a requirement, and every
requirement traces to an evidence id. If something cannot be traced, it does not
go on the page.

---

## 7b. §79b — Plotly figures: the geometry of dimension matching

Interactive Plotly figures, embedded in the same HTML file, answering questions a
table cannot: **where** in the video each dimension lives, **how far apart** the
brief's asks and the video's delivery sit, and **how much of the score is
noise**.

### 7b.1 Where 3D earns its place, and where it does not

Worth saying once: a 3D chart is usually *worse* than 2D for reading a value —
occlusion hides points, perspective distorts lengths, and the reader has to
rotate it to trust it. 3D earns its place only when there are genuinely **three**
things varying and the *shape* matters more than any single value.

Two of the figures below qualify. The third is a batch view. The precise-reading
chart stays 2D on purpose, and that is not a compromise — it is the right tool
for "what did CTA score".

### 7b.0 Figures 5 and 6 — what aligns with the brief, and how well

**Added after the first build, and they lead the section.** None of Figures
1–4 plot `alignment` at all: Figure 1 plots *status* (0 / 0.5 / 1.0), which
answers "did she satisfy it", not "how closely does what she did resemble what
was asked". Those are different questions and the second one is what a creator
manager opens the report for.

**Figure 5 — the alignment landscape (3D scatter)**

```
x = time in the video        where the evidence sits
y = the brief's ask          one row per scoring unit, grouped by dimension
z = alignment                none 0.0 -> exact 1.0
colour + symbol = level      survives greyscale and colour blindness
size = priority weight
hover = the ask, its dimension, the alignment reason, the verdict, evidence ids
```

Genuinely three-dimensional — the ask, the moment, the closeness — and the
*shape* is the finding. A brief whose asks all align strongly but cluster in
the first three seconds is a different problem from one whose asks are spread
evenly and align weakly, and a table states neither.

It also makes the substance promotion visible: a requirement sitting at
`strong` while its verdict reads FAIL is the creator putting the brief's ask in
her own words, which is the thing §0.5 exists to handle.

**Unjudged units are drawn below the axis, hollow, on their own labelled row.**
`None` is not `'none'` — the first means nobody looked, the second means judged
and found unrelated. Plotting them at the same height would assert something
that did not happen.

**Figure 6 — the shape of that alignment (3D surface)**

```
x = alignment level, ordinal none -> exact
y = dimension
z = weight mass sitting at that closeness
```

A surface is right because the reader is looking for where the mass *piles up*.
A ridge at `exact` down one dimension and a ridge at `none` down another says
at a glance what seven table rows do not. Weight, not count: a critical
requirement aligning `none` should dominate the surface the way it dominates
the score. Skipped with a note when only one dimension carries alignment.

**Both survive the relevance gate on purpose.** A landscape sitting entirely at
`none` is the *evidence for* calling a video off brief — suppressing it would
remove the reader's ability to check the gate.

---

### 7b.2 Figure 1 — dimension × time × score (3D scatter)

**The question:** *where in the video does each dimension live, and where did it
fail?*

```
x = timestamp (seconds, 0 → duration)
y = dimension (7 categorical rows, spec §39 order)
z = unit score (0.0 / 0.5 / 1.0)
colour = status      PASS / PARTIAL / FAIL / UNCERTAIN
size   = priority weight (critical largest)
hover  = requirement label, reason, evidence ids, exact timestamp
```

This is the figure that makes a structural failure obvious at a glance: a CTA
dimension whose every marker sits at 0–3 s explains a FAIL that a table only
states. It is genuinely three-dimensional — time, category, outcome — and the
shape is the finding.

Each marker's `customdata` carries its evidence ids, so the design rule holds:
**nothing is plotted that cannot be traced back to a record.**

### 7b.3 Figure 2 — run × dimension × subscore (3D surface)

**The question:** *which dimensions are stable, and which are the model
guessing?*

```
x = run index (1..N of the same video × brief, force=True)
y = dimension
z = dimension subscore
```

This plots the instability that dominated Phase 6 validation — alignment moved
0.34 on identical inputs — and localises it per dimension. A ridge that stays
flat across runs is a dimension you can trust; one that oscillates is one where
L3 is guessing and Phase 8's labels should go first.

A surface is right here because the reader is looking for *flatness*, which is a
shape, not a number. Needs N ≥ 3 runs; hide the figure when only one exists
rather than drawing a meaningless plane.

### 7b.4 Figure 3 — video × dimension × subscore (3D bars)

**The question:** *across a batch of creators on one brief, who is weak where?*

```
x = video, y = dimension, z = subscore, colour = band
```

Only rendered when more than one video has been scored against the brief. For a
single audit it is a bar chart pretending to be a landscape, so it is skipped.

### 7b.5 Figure 4 — brief ask vs video delivery (2D, deliberately)

**The question:** *how much is each dimension worth, and how much did she get?*

```
x = dimension weight (what the brief asks for)
y = achieved subscore
one point per dimension, diagonal = perfect delivery
```

Distance below the diagonal is under-delivery **scaled by how much it matters** —
a 20%-weight dimension at 0.3 is a bigger problem than a 10% one at 0.2, and this
puts that difference where the eye reads it. Dimensions the brief does not cover
are drawn hollow at the axis, so "the brief said nothing about audience" is
visible rather than absent.

Two quantities, two axes. Adding a third would make it harder to read, not
richer.

### 7b.6 Constraints

- **Determinism.** No random jitter, fixed category order, fixed colour map,
  explicit axis ranges. The same verdict artifact must produce byte-identical
  HTML (§8), and a jittered scatter breaks that.
- **Offline.** `include_plotlyjs=True` embeds the bundle **once** for the whole
  page, however many figures. **Measured, not assumed: plotly 7.x is ~4.8 MB,
  not the ~3.5 MB this document first guessed.** Total report ≈ 2 MB proxy
  video + 4.8 MB Plotly + content ≈ **7 MB**. Still emailable and it opens on a
  plane, but the number is worth knowing, so it is a named constant
  (`PLOTLY_BUNDLE_MB`) rather than a comment. `P7.report.embed_plotly = False`
  drops the figures and the report falls to ~15 KB. Do **not** use `'cdn'`: a
  compliance report that needs the internet to render its own charts is not
  self-contained, so that option is not offered at all.
- **Verifying traceability from the OBJECT, not the HTML.** "Every plotted
  marker carries its evidence ids" is checked on the `Figure` before
  serialisation. The first figure on a page embeds the whole Plotly bundle, and
  that bundle contains the word `customdata` and every trace-type name as
  schema keys — so the obvious string search passes for any figure whatsoever.
  The first version of that exit criterion did exactly that and verified
  nothing.
- **Degradation.** If Plotly is missing at build time, the report renders without
  the figures and says so. A chart library must never be able to block a score.
- **Colour.** Status colours must survive greyscale printing and the common forms
  of colour blindness — status is also encoded in marker symbol, not colour
  alone.

---

## 8. Exit criteria

Checked mechanically by **§81** against the artifacts each run produces, not
asserted. State as of the build:

- [ ] **§1 answered and written into this document** — §75b needs the control
      half of the comparison: set `RUN_CONTROL_AUDITS = True` and re-run. No
      labelling, a few L3 calls.
- [x] score reproducible by hand from a named verdict artifact — §81 recomputes
      it independently and compares
- [x] no model output ever writes a numeric score
- [x] `PASS_FROM_ABSENCE` never contributes to achievement
- [x] dimension subscores normalise over covered dimensions only
- [x] a critical FAIL cannot be averaged into `APPROVED`
- [x] HTML opens standalone; timestamp clicks seek correctly
- [x] the same verdict artifact scored twice gives byte-identical output,
      figures included — Plotly div ids are set explicitly, and the proxy video
      is encoded once and cached, because neither is reproducible otherwise
- [x] every plotted marker carries the evidence ids behind it
- [x] the report renders, and says so, with Plotly unavailable — verified by
      running the whole suite on a machine with no Plotly installed
- [x] figures open with no network connection
- [ ] contradictions section fires on the pill-organiser × hair-brief pair —
      the logic is tested on synthetic contradictions; the real pair needs both
      videos audited against the same brief
- [ ] a person who has not seen the video can act on the report (test on someone)
- [ ] reviewing a report is faster than watching the video (time it)

The last two are **MANUAL** by nature and §81 reports them as such rather than
assuming them. A criterion no code can check is not a criterion that passes.

---

## 9. What NOT to build here

- **No re-litigating Phase 6.** The remaining error is L3 judgement quality, and
  it needs labels (Phase 8), not more code. Four rounds of structural fixes found
  real bugs; a fifth would be looking for a bug in a number now behaving as
  designed.
- **No verdict-level consensus sampling.** Running L3 three times and taking the
  median would cut the variance, but it triples cost and Phase 8's labels should
  decide whether it is worth it.
- **No web stack.** One HTML file covers spec §76 for months.
- **No calibration of the band thresholds.** They are placeholders; Phase 8 has
  the labels.

---

## 10. Carried-forward improvements, logged not done

| item | evidence | where it belongs |
|---|---|---|
| `group_intent` should name the subject | CTA intent is subject-free, so any CTA scores `strong` | Phase 4 prompt, Phase 8 calibration |
| band thresholds unvalidated | nothing establishes 85 as the line | Phase 8 |
| L3 alignment variance (range 0.34) | 3 runs, identical inputs | Phase 8 labels, then maybe sampling |
| backend rebuilt per module | hook/claims/angle/standing each construct one, ~6 wasted probes per audit | small, any time |
