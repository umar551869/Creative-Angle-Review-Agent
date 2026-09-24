# Phases 1–6: Diagnoses and Solutions

Working document for closing out Phases 1–6. Every diagnosis below is backed by
a measurement from a real run or a real artifact, not by inference. Where I was
wrong earlier, the correction is stated rather than quietly replaced.

Last updated: 2026-09-18, after the 84s Aurelia run (`22a6c0b6258f227f`) against
brief `f697be0583accf46`.

---

## 0. The first fully clean run — 2026-09-18, hosted vision

`§74` reported **`ISSUES: none. Every phase ran, every exit criterion passed.`**

Video `22a6c0b6258f227f` (84.4s) × brief `f697be0583accf46`, Gemini vision.

| | |
|---|---|
| vision model | `gemini:gemini-flash-latest [hosted]` |
| frames sent / budget | **48 / 48** |
| pixels used / asked | **100352 / 100352** (full resolution) |
| Phase 3 flags | **`[]`** — no `DEGRADED_BUDGET` |
| visual health | `degraded=False  coverage_degraded=False  acuity_degraded=False` |
| can_fail_on | all six modes **yes** |
| VRAM free during Phase 3 | 14.46 GB of 14.6 — the GPU was not used |
| requirements | **21** (was 7–9) |
| exit criteria | Phases 1–6 **all pass** |
| verdicts | 2 PASS, 3 FAIL, 16 NOT_APPLICABLE; UNCERTAIN **0%** |
| L1 / L2 / L3 | 14% / 0% / 86%, 2 batched calls |
| fabricated ids | 0 |
| citation violations | 0 |
| decided verdicts citing nothing | 0 |

**What this run confirms, fix by fix:**

- *Phase 2 criterion* — `ALL PASS`, and §74 now explains why: *"all 32 clear the
  single-sighting bar (0.85) — admitted by config, not noise"*.
- *Consensus rebuild* — `ALL PASS`; `requirements 21, scorable 21`, consistent
  for the first time (was 7 against 21).
- *Compile recall (§2.3)* — **21 requirements**, up from 7–9. The prompt
  contradiction was the cause.
- *Coverage/acuity gate* — `Any stated figures statistical claims` now **PASSes
  at L1**; it was UNCERTAIN on every run where visual was degraded.
- *Hosted vision* — removes degradation entirely rather than tolerating it.
  14 events vs Qwen's 9 on the same video; visual coverage 52% → 66%.

**Structure check.** 16 of 21 `NOT_APPLICABLE` is the `one_of` collapse working,
not requirements going missing: 3 choice groups → 3 selected members (all three
FAIL — the creator used none of the scripted hooks or CTAs), 16 losers marked
N/A, 2 ungrouped requirements both PASS.

**Incidental finding.** `gemini-flash-latest` *does* serve vision on this key,
even though it is unusable for text. The cache key naming it is therefore
accurate, and the `gemini_models=('gemini-flash-lite-latest',)` workaround noted
in §6 is not needed.

---

## 1. Status at a glance

| Phase | Exit criteria | Blocking issue | State |
|---|---|---|---|
| 1 — decode / sample | pass | — | **done** |
| 2 — ASR + OCR | was fail | criterion contradicted its own config | **fixed**, §2.1 |
| 3 — visual events | pass | 33-frame ceiling on a T4 (capability, not defect) | **done**, §2.4 |
| 4 — brief compile | was fail | consensus orphaned choice groups, left stats stale | **fixed**, §2.2 |
| 4 — brief compile | — | recall: 7–9 of ~24 requirements per run | **fixed**, §2.3 |
| 5 — evidence | pass | — | **done** |
| 6 — verdicts | pass | — | **done** |

Both blocking issues are now fixed. One open decision (§2.3) remains, and it is
the real limiter on audit quality.

**The evidence gate is closed.** As of the 2026-09-18 run, all six evidence modes
report `yes` for the first time, and the system asserted its first visual FAIL
(`Do your favourite hairstyle camera`) and its first `PARTIAL` from the
`visual_and_speech` conjunction (`Show supplement as part your`). Visual ran at
33 of 48 frames — 69%, above the configured 60% — with resolution reduced, which
is now correctly read as *reduced acuity, intact coverage*.

---

## 2. Open issues

### 2.1 Phase 2 — the exit criterion contradicts the config it claims to check

**Symptom**

```
FAIL  every interval has >=2 detections (config minimum)
```

**Diagnosis (measured on `ocr__4d6a43df910520a5.json`, the exact artifact that run used)**

```
57 intervals total
n_detections distribution: {1: 32, 2: 7, 3: 2, 4: 5, 5: 1, 7: 1, 8: 2, 11: 5, 21: 1, 22: 1}

config.dedupe.min_interval_detections       = 2
config.dedupe.single_sighting_min_confidence = 0.85

of the 32 single-detection intervals:
  max_confidence >= 0.85 : 32
  max_confidence <  0.85 : 0
  marked `single_sighting`: 32
```

Every one of the 32 clears the configured exception, with confidences from 0.851
to 0.903. And they are **real evidence**, not noise:

```
max_conf=0.872  'natural hair journey'
max_conf=0.890  "I've been taking these"
max_conf=0.903  '2 supplements by Aurelia.'
max_conf=0.851  "This one's Hair Perfection"
```

These are burned-in captions that appear in a single sampled frame. The dedupe is
behaving exactly as configured. `single_sighting_min_confidence` exists precisely
to admit them.

**The criterion is wrong.** It asserts `n_detections >= min` for *all* intervals
and ignores the exception. It has presumably been failing on every video with
burned-in captions.

**Solution**

```python
check(f'every interval meets the detection minimum OR the single-sighting bar',
      all(iv['n_detections'] >= _min_det
          or (iv.get('single_sighting')
              and (iv.get('max_confidence') or 0) >= _min_conf)
          for iv in o['intervals']),
      f'{_n_single} single sighting(s) admitted at >= {_min_conf} confidence')
```

Do **not** "fix" this by raising `min_interval_detections` or dropping single
sightings — that would delete 32 of 57 OCR intervals, including the product name.

---

### 2.2 Phase 4 — consensus prunes requirements but leaves the rest of the artifact stale

**Symptom**

```
--- PHASE 4: brief -> requirements ---
  requirements     8
  scorable         9        <-- more scorable than there are requirements
  choice_groups    1
  alternatives     6
  exit criteria    FAILURES
```

**Diagnosis**

`compile_brief_consensus` filters `requirements` down to the stable set, then
does only this:

```python
out['stats'] = dict(out.get('stats') or {}, requirements=len(out['requirements']))
```

Every other field is inherited from `base`, the largest of the sampled runs:
`scorable`, `forbidden`, `with_temporal`, `choice_groups`, `alternatives`,
`sections`, `conflicts`, `scoring_units`. So the artifact describes a
requirement set that no longer exists. Confirmed on disk:

```
requirements__2460dff76c9b57f1_c3.json  [CONSENSUS]  requirements=6  scorable=16
```

Six requirements, sixteen scorable. The two most likely criteria to fail as a
direct result:

- `every alternatives section produced a group` — `len(gm) >= len(alt_secs)`.
  `sections` still lists every alternatives section from the base run, but
  pruning destroyed most of the groups. With `choice_groups=1` against several
  alternatives sections, this fails.
- `every choice group has more than one option` — pruning can leave a group with
  a single surviving member.

**Solution** — after filtering, recompute the derived fields instead of
inheriting them:

1. Recompute the whole `stats` block from the surviving requirements, not just
   `requirements`.
2. Drop `group`/`group_mode` from any requirement whose group has fewer than two
   surviving members — a choice group of one is not a choice.
3. Filter `sections` to those that still have at least one surviving
   requirement, so the alternatives-section criterion compares like with like.

This is a bug in the consensus path only; single-shot compiles are unaffected.

---

### 2.3 Phase 4 — compile recall  ✅ FIXED 2026-09-18

**Root cause found: the prompt contradicted itself.**

It instructs, for an alternatives section:

> *"Give every item in the section the SAME `group` string and `group_mode`:
> `one_of`."*

and then, forty lines later:

> *"Do not pad: a three-line brief should not become twelve requirements."*

A brief listing 12 hook options makes those two rules incompatible, and the
model resolved the conflict differently on every run — 24 requirements when it
enumerated, 7–9 when it collapsed. That is the whole instability.

**Why enumeration is the right resolution, not collapsing:**

- the auditor matches the creator's words against each option's **own text**, so
  an option that was never written down cannot be checked. The collapsed form
  came back `UNCERTAIN` — *"the evidence does not show any of the provided hook
  concepts being used"* — because there was nothing to match against;
- `scoring_units` already collapses a `one_of` group to **one** unit, so
  enumerating the options does not inflate the score;
- Phase 6's choice-group machinery (`GROUP_SELECTED` / `GROUP_NOT_SELECTED`,
  six tests) is built for the enumerated form.

**Fix applied** — prompt `p4_brief_compile_v3`, `BRIEF_STAGE_VERSION 1.6.0`:

1. The alternatives rule now says *emit ONE REQUIREMENT PER ITEM … NEVER collapse
   them into a single "use one of the approved hooks"*, and gives both reasons
   above so the rule is not merely asserted.
2. A `COMPLETENESS` rule replaces the anti-padding line: every line of a
   requirements section and every item of an alternatives section must produce a
   requirement, with an instruction to **count the items and check** before
   answering.
3. "Do not pad" is reworded to mean what it was for — *do not INVENT* — with an
   explicit *"it does NOT mean keep the list short"*.

**What to verify on the next run:** §48 should print three run counts in the
low-to-mid twenties rather than 7–9, and they should agree far more closely than
before. Consensus can only keep what the runs produce, so recall is the number
to watch; stability follows from it.

---

### 2.3c Phase 4 — `forbidden 0`: the figures rule was derived, then discarded  ✅ FIXED 2026-09-18

**Symptom**

```
FAIL  a brief stating FIGURES produced a rule that checks them
      1 claim(s) state figures ['27%', '3months']
requirements 20   forbidden 0   alternatives 20
```

**My first diagnosis was wrong, and measurement is what showed it.** I had
concluded the compiler intermittently fails to write the rule, and was about to
add a deterministic synthesiser to `compile_brief`. Reading the code first: one
is **already there** (`numeric_claims` → `Requirement`, flag
`NUMERIC_FIDELITY_RULE_ADDED`), and every compiled artifact on disk agrees —

| artifact | consensus | reqs | claims w/ figures | forbidden |
|---|---|---|---|---|
| `08670ad0/f0444922` | no | 14 | 1 | **1** |
| `08670ad0/f753eb18` | no | 11 | 1 | **1** |
| `f697be05/2460dff7` | no | 16 | 2 | **1** |
| `f697be05/7109aca5` | no | 24 | 2 | **1** |
| `bc455fe5/35300141` | no | 12 | 1 | **1** |
| `bc455fe5/041ea2b7` | no | 11 | 1 | **1** |
| `f697be05/2460dff7_c3` | **yes** | 6 | 2 | **0** |

Seven of seven single-run compiles carry the rule. The **only** artifact missing
it is the consensus one. The compiler never fails; the merge loses it.

**Root cause: the invariant is enforced on the way in and not on the way out.**

`compile_brief` guarantees "a brief stating figures carries a rule checking
them". `compile_brief_consensus` then clusters rewordings, votes, releases
orphaned groups, truncates to `max_requirements`, and recomputes every stat —
and nothing re-checks the invariant afterwards. The artifact every later phase
reads is the merged one.

The earlier safety-union fix (`forbidden` kept by union, not majority) is
correct and still needed, but it could never be sufficient: it protects the
*vote*, not the four other steps that run after it.

**Fix applied** — §45, step 2b of the consensus rebuild, before stats are
recomputed: re-derive the rule from `out['approved_claims']` through the *same*
`Requirement` constructor `compile_brief` uses, so the two cannot drift. Flagged
`RESTORED_AFTER_CONSENSUS` and reported in the artifact as
`NUMERIC_FIDELITY_RULE_RESTORED`.

**Verified on real artifacts**, not asserted:

| case | fires? | wanted |
|---|---|---|
| consensus dropped it (23 reqs, forbidden 0) | yes → forbidden 1 | yes |
| consensus kept a real one (24 reqs) | no | no — never duplicates |
| brief states no figures at all | no | no — never invents |

The restored rule: `polarity=forbidden`, `evidence_mode=any`,
`priority=critical`, `weight=3.0`, `match_hints=['27%','3months']`,
`claim_classes=['unsupported_outcome']`, `group=None` — a scorable unit, and
never a choice-group member, which is right: a figures rule is not one option
among several.

*Minor, carried over from the existing extractor:* the hint reads `3months`
rather than `3 months`. That is how `extract_approved_claims` normalises it, so
it matches what the pre-existing derivation already emitted — not a regression,
but the reason L1 may need L3 to catch a spoken "three months".

---

### 2.3d Phase 6 — the angle criterion failed because the guard worked  ✅ FIXED 2026-09-18

**Symptom**

```
FAIL  a brief concept named by the angle really is in the brief
      flags: ANGLE_CONCEPT_NOT_IN_BRIEF:problem_statement
      nearest brief concept: none
```

The model named `problem_statement`; the brief does not contain it; the code
stored `None` and flagged it. That is the guard doing exactly its job — the
invention never reached the output — and the criterion failed the whole phase
over it.

A criterion should fail when the **output** is wrong, not when a guard caught
something. The same principle is already applied to `fabricated_ids`: rejected
citations are reported, and only *survivors* fail.

**Fix applied** — §73: the criterion now asserts what actually matters, that
`nearest_brief_concept` is either a real brief concept or `None`. The rejection
is still printed, as a `NOTE`, so the model's slip stays visible rather than
being swept away.

---

### 2.3e Phase 4 — union kept two rules that say the same thing  ✅ FIXED 2026-09-18

**Symptom**, from the 22-requirement run: `forbidden 2`, and in the verdict list

```
[FAIL] L1  Any stated figures statistical claims   ~none
[PASS] L1  Any stated figure statistical claim     ~exact
```

One ask, two wordings, contradictory verdicts — and the spurious `FAIL ~none`
pulling the mean alignment down.

**Cause: my own union fix.** Forbidden rules are kept by union rather than
majority, which is right. But `_cluster_fingerprints` merges on **wording** at a
threshold of 88, and these two measure:

| | |
|---|---|
| `token_set_ratio` | **79.8** — under the threshold, so never merged |
| `match_hints` | `1500, 21 days, 27%, 3 months, 86%` vs the identical set — **5 of 5** |

Wording is the wrong key. A rule carrying `match_hints` checks exactly those
hints; the hints are what it *is*.

**Fix applied** — §45, step 2a: forbidden rules whose `match_hints` are equal, or
where one set contains the other, collapse to one. The survivor takes the
**union** of both rules' hints and `claim_classes`, so a merge can never check
less than the pair did. Rules with no hints are never merged — there is nothing
to establish they share a target.

Verified, including the cases that must *not* merge: disjoint hints stay
separate, hintless rules stay separate, non-forbidden requirements are untouched,
and a subset merges into the broader rule keeping the broader wording.

---

### 2.7 Phase 6 — the whole brief against the whole video  ✅ ADDED 2026-09-18 (§69c)

**The gap this closes.** Every other Phase 6 output decomposes: the brief becomes
22 requirements, those collapse to a handful of scoring units, and each unit is
judged against *retrieved fragments* of the video. That buys citability and the
abstention gate. It also means **no layer ever sees the whole against the whole**.

Measured on a video that plainly engages its brief: **4 FAILs, mean alignment
0.42**. Two of those FAILs were hook asks that happened to land *outside* the
hook choice group, so they were scored as independently mandatory; meanwhile five
collapsed group members had scored `strong`. Every verdict was defensible on its
own and the aggregate was wrong — because the question *"does this video do what
this brief wants?"* was never asked.

**What §69c does.** One call. The entire brief, the entire video record (full
transcript in order, on-screen text, visible events), no retrieval and no
decomposition. It returns a standing on a closed ordinal scale, what the brief
asks that she *did* cover, what is not evidenced, what she added unasked, and
whether her creative angle still serves the brief.

**It is a second opinion, not an overrule.** Its real product is the
**disagreement**: `standing weight − decomposed mean alignment`. The two use the
same scale deliberately, so the subtraction means something. They are reported
side by side and **never averaged** — a blended number would hide precisely the
case this exists to catch. A gap of ≥ 0.25 is flagged.

**What the model decides, and what the code decides:**

| The model | The code |
|---|---|
| which level, from 5 closed options | the **weight** of that level |
| prose: verdict, reasoning | the decomposed mean, the gap, the flag threshold |
| which topics it lists | whether each topic is really in the brief |
| which evidence ids it cites | whether it was offered those ids |

**Verified — 26 checks, no network, no model** (`test_standing.py`):

- weights come from the code table, never the reply
- an unoffered evidence id is dropped and the attempt recorded
- an invented brief ask is rejected — the topic guard was **too lenient on first
  measurement** (`partial_token_set_ratio` accepted *"a free consultation with a
  dermatologist"* against a brief with no such words) and now tests **content
  words** via the existing `content_tokens` / `_tokens_match`
- a standing outside the taxonomy becomes *unjudged*, not a guess
- abstention holds: no speech, no brief text, L3 off, or a dead backend all give
  *unjudged* rather than `off_brief`
- an absence claimed from a **truncated or degraded** record is marked
  unverified — "not evidenced" is never reported as "did not happen"
- when the two reads agree, no disagreement flag fires

---

### 2.8 The 22→23-requirement run: four defects, all mine  ✅ FIXED 2026-09-18

The run scored **0.34 mean alignment across 9 units, 7 FAILs** — *worse* than the
0.42 before it. Nine scored units decomposed as:

| unit | count | weight |
|---|---|---|
| duplicate figures rules, all inverted | 3 | 0.00 each |
| asks stranded outside their choice group | 4 | 0.25, 0.25, 0.00, 0.55 |
| genuine verdicts | 2 | 1.00 each |

**Seven of nine were artifacts.** The mean was measuring defects, not the video.

#### 2.8a The figures rule was checked backwards (`VERDICT 1.2.0`)

`l1_forbidden` builds its search terms from `forbidden_evidence + match_hints`
and FAILs on a hit. The figures rule's `match_hints` are the **approved**
figures. Demonstrated against the real hint list:

```
SHE STATES THE APPROVED FIGURES  (perfect compliance)
  "reduces hair loss by 27% after 3 months"   -> FAIL: forbidden '3 months'
  "over 1500 home studies backed this up"     -> FAIL: forbidden '1500'
SHE STATES A WRONG FIGURE  (a real violation)
  "reduces hair loss by 90% in a single week" -> NO HIT, passes unnoticed
```

A FAIL here cannot come from absence — absence in a healthy modality returns
PASS — so all three FAILs were hits on approved figures.

**Fix:** a new `l1_figure_fidelity`, ahead of `l1_forbidden` in `L1_CHECKS`. A
violation is a **contradiction**: a figure in a dimension the brief speaks to
carrying a different value. Three restrictions keep it from becoming a new
source of false FAILs — only units the brief itself states are policed, bare
numbers never are, and only **speech and OCR** count (a number inside a vision
model's prose is the model's word, not the creator's).

*Caught by the test, not by review:* writing the unit group as `(...)?\b` broke
**every percentage** — `%` is not a word character, so the boundary failed, the
group backtracked to empty and `27%` parsed as the bare number 27. Percent was
never policed at all. 25/25 after the fix.

#### 2.8b Duplicate safety rules merge on KIND, not wording or overlap

Three rules came back as `{27%, 3 months, 1500}`, `{27%, 3 months, 86%}` and
`{27%, 21 days}`. The nesting test (2.3e) merged none — no pair is nested. An
overlap test merged two and stranded the third, which shares one hint.

The hint sets differ for a reason unrelated to meaning: each is the model's
**sample of the same brief's figures**. They are one rule written three times.

**Fix:** two figure-fidelity rules sharing a `claim_class` are the same rule,
whatever their hints; the survivor takes the union. Overlap (≥60% of the smaller
set) still governs word blacklists, where hints do carry the meaning. A
`guarantee` rule about *21 days* still does not merge into an
`unsupported_outcome` one just because both mention numbers.

#### 2.8c Asks written outside the list they belong to (`BRIEF 1.8.0`)

A brief lists twelve sample hooks under one heading, then says *"use a hook like
these"* in a sentence elsewhere. The list becomes a `one_of` group and collapses
correctly. The loose sentence becomes an **ordinary requirement**, scored as
independently mandatory — so a creator who used one good hook FAILs the stray
for not also using it. Four of nine units were strays, across hooks and CTA.

**Fix:** `brief_span` records the sentence each requirement was built from. If
that sentence sits inside a section that already produced a choice group, the
requirement is another way of making the same choice and joins the group,
inheriting its `group_intent`. Conservative: it joins only when the span is
found in **exactly one** section, so ambiguity changes nothing.

#### 2.8d §74 contradicted itself

The disagreement row printed `<-- PROBLEM` while section 6 reported no issues. A
disagreement is a finding about the video and brief, not a pipeline defect. The
ok/not-ok flag is gone; the row reads as a finding.

**Verified: 73 checks across four suites, no network, no model** —
`test_figfid` 25, `test_standing` 26, `test_adopt` 12, `test_dedupe2` 10, plus
the integration check (syntax, definition order, no shadowed names, the two
standing numbers never blended).

---

### 2.9 The 21-requirement run: the fixes held, and exposed a deeper one  ✅ FIXED 2026-09-18

**What the 2.8 fixes did**, measured rather than predicted:

| | before | after |
|---|---|---|
| forbidden rules | 3 (duplicates) | **1** |
| choice groups | 2 | **3** (a stray CTA joined its group) |
| mean alignment | 0.34 across 9 units | **0.91 across 5** |
| standing vs requirements | **+0.51** | **−0.06** |
| uncertain rate | 4% | **0%** |

The disagreement closing on its own was the stated test of whether the 2.8
diagnosis was right, and it closed.

#### But the score was hiding a wrong answer

All twelve hook options were decided at **L1 with alignment `exact`**. Only one
opening was spoken, so at most one of those can be true. The winner came back as
*"Blow drying my hair"* — while the standing pass, reading the video whole,
listed *"Everybody talks about hair growth but what about the shine (hook)"*
under **covered**. The two agreed on the score and disagreed on the fact, which
is why the disagreement number could not catch it.

**Root cause, confirmed on real artifacts.** `_term_hit` returns **100** for a
plain word-boundary match, and `_hint_score` takes the best hint. The compiler
writes `match_hints` as the option's sentence on some runs and as keywords on
others — one artifact on disk carries **46 single-word hints out of 48**:

```
group 'call_to_action_cta_ideas_5'  (7 options)
  hints=['take', 'multiple', 'pills', 'day', 'total']
  hints=['click', 'link', 'daily', 'routine', 'way']
```

On a keyword run every hook matches the word *hair* at 100, `l1_phrase` returns
PASS for all twelve, `_L1_ALIGNMENT` labels each one `exact` — *"the
requirement's own wording was matched"* — and the group picks its winner on
confidence, which is a tie. An arbitrary option is reported as the hook she
used, and the score looks healthy.

`_hint_score`'s own docstring says it is *"a ranking signal, never an
exclusion"*. Scoring generously is correct for **ordering** candidates. The
mistake was `l1_phrase` promoting that same 100 into a verdict.

**Fix applied** (`VERDICT 1.3.0`): inside a `one_of`/`any_of` group, L1 requires
a **phrase** match. A single-word hint sends the group to L3 — which is what the
earlier runs did, and they came back with differentiated `strong`/`tangential`
readings instead of twelve identical `exact`s. Outside a group nothing needs
discriminating, so *"say the brand name"* is still honestly satisfied by one
word and that path is unchanged.

**Verified, 4 checks:** the twelve keyword options go from 4-of-4 PASS to
0-of-4; the option actually spoken still PASSes on its real phrase; an option
not spoken does not; an ungrouped single-word requirement still PASSes.

**Still open:** the root cause is upstream — the Phase 4 prompt lets
`match_hints` be keywords for a choice option, where only the option's own
sentence can identify it. The L1 guard makes the audit correct either way; making
the compiler emit the sentence deterministically for grouped options would
remove the L3 cost as well. Not done, because it changes brief output again.

---

### 2.10 The discrimination test, and what it found  ✅ 2026-09-18

**The test.** Audit a pill-organiser video (`84875b0c`) against the Aurelia hair
brief — a video the brief was not written for. Every green exit criterion up to
this point was consistent with a system that says `on_brief` to everything; this
is the only test that asks whether it discriminates at all, and it is binary.

| | matching video | mismatched video |
|---|---|---|
| standing | `on_brief` 0.85 | **`off_brief` 0.00** |
| requirements mean | 0.79 across 5 | **0.25 across 5** |
| angle serves the brief | yes | **no** |
| unasked content | — | *"Reviewed a pill organizer…"* |

Both layers separate, independently. **The system is not a rubber stamp**, and
Phase 7 can be built on it.

Validation earned its keep immediately: one run surfaced three defects that four
consecutive all-green runs had not.

#### 2.10a §73 and §74 disagreed about what "traceable" means

The same report said **"Phase 6 exit criteria ALL PASS"** and, forty lines later,
**"[BLOCK] 1 decided verdict(s) cite no record"** — about the same verdict.

```
§73:  blind iff  not evidence_ids AND not examined_ids      <- correct
§74:  blind iff  not evidence_ids                           <- forgot the fallback
```

The diagnostic settled it with data rather than inference:

```
status=FAIL  layer=L3  evidence_ids=[]  examined_ids=[10 ids]  considered=8
```

The verdict was fully traceable. `evidence_ids` is *"what this relies on"*;
`examined_ids` is *"what it was shown"* — a distinction the Verdict dataclass,
§73, and §74's own per-verdict printout all honour, and which this one check had
dropped. **Nothing was wrong with the verdict.** Citing nothing while recording
what you examined is a NOTE, not a block.

*Worth recording:* I had reasoned my way to a plan to rewrite three working code
paths in `evaluate_requirements` before reading the two checks side by side. The
contradiction inside the report was the clue, and it was visible from the start.

#### 2.10b The disagreement explanation ignored its own sign

`gap = standing − decomposed`, so the sign names the cause:

- **gap > 0** — the requirement layer is *harsher*; most often it is scoring the
  brief's examples as demands
- **gap < 0** — the requirement layer is *more generous*; most often it is
  crediting near-misses

One fixed sentence was printed for both. The run above had **gap −0.25** — the
decomposition being generous — and the report explained it as *"scoring the
brief's examples as demands"*, the opposite cause. A wrong explanation is worse
than none: it sends the reader to the wrong place. Both §73 and §74 now branch on
the sign.

#### 2.10c `examined_ids` named records the adjudicator never saw (`VERDICT 1.4.0`)

The same diagnostic line showed `candidates_considered=8` beside **10**
`examined_ids`. L3 is given a batch truncated to
`max_candidates_per_requirement`, but `examined_ids` was filled afterwards from
the *full* retrieval. `examined_ids` exists so a human can check the verdict;
listing two records the model was never given makes that harder. L3 now records
its own batch, and the post-hoc fill only covers verdicts that have none.

**Verified: 90 checks across six suites** — `test_trace` 13 (replaying the real
verdict and the real gaps through the patched blocks, lifted from the notebook
rather than retyped), plus figfid 25, standing 26, adopt 12, dedupe 10,
discriminating 4, and the integration check.

**Left open:** Phase 4 reported `1 conflict(s)` on this compile of a brief that
compiled cleanly three times before. Same brief, different compile key — the
known compiler instability surfacing a contradiction, not a new defect.
`print(compiled.get('conflicts'))` names the pair.

---

### 2.11 The last blocker: a conflict about a requirement that wasn't there  ✅ FIXED 2026-09-18

Phase 4's only remaining FAIL, and printing it raised an exception:

```
POLARITY_CONFLICT | r_43b134ff requires and r_413cbc97 forbids
                    overlapping subject: ['21', '86%', 'home', 'rate']
StopIteration      <- r_413cbc97 is not in compiled['requirements']
```

Two separate defects, one hiding the other.

#### 2.11a A figure-fidelity rule cannot contradict stating those figures

The shared tokens are the **figures themselves**. The pair was:

| | |
|---|---|
| required | *"Mention that over 1500 home studies were done with an 86% satisfaction rate and results in 21 days."* |
| forbidden | *"Any stated figures must precisely match the brief: 27%, 1500 home studies, 21 days, 86%…"* |

Those agree. Sharing the numbers **is the point** — one says state them, the
other says if you state them they must match. A figure-fidelity rule constrains
*how* a figure is stated, never *whether* a subject is mentioned, so it cannot
contradict a requirement to state it.

`detect_conflicts` now skips pairs where either side is a figure-fidelity rule.
Ordinary prohibitions are untouched: *"do not mention pricing"* carries word
hints, not numeric ones, so it takes no exit — verified, along with the medical
gazetteer case and duplicate-id detection.

*My dedupe made this surface.* The same-kind merge keeps the **longest**
wording, which is the one enumerating every figure — giving it far more content
words to collide on than the shorter variants it replaced.

#### 2.11b `conflicts` was computed on the base run, not on what ships

`compile_brief_consensus` does `out = dict(base)`, carrying one run's conflict
list into an artifact whose requirements have since been voted on, merged, and
released from dead groups. `r_413cbc97` was a duplicate figures rule the merge
removed — so the artifact shipped a conflict naming a requirement it no longer
contained, and any code joining the two raised `StopIteration`.

This is **§2.3c again**. That fix rebuilt `sections` and `stats` after pruning
and missed `conflicts`. The rule it should have established: *anything derived
from `requirements` must be derived again once `requirements` changes.*
`detect_conflicts` is now recomputed on the merged set, and accepts dicts as
well as `Requirement` objects so it can run in both places.

**`BRIEF_STAGE_VERSION 1.9.0`** — the artifact's `conflicts` field changes, so a
cached brief would otherwise keep the false conflict.

**Verified: 100 checks across seven suites**, including that no conflict names an
id absent from the requirement set — the exact failure your session hit.

---

### 2.12 The repeat test, and the bug it found  ✅ FIXED 2026-09-19

Three audits of the **same** off-brief pair (pill-organiser video × hair brief),
fixed brief, `force=True`:

```
0.67, 0.80, 0.71     range 0.13      standing: off_brief every time
```

Repeatable — but repeatably **wrong**. A video about pill organisers scored ~0.7
against a hair-supplement brief, overlapping the 0.79 a genuinely on-brief video
scored. On that evidence I concluded the decomposed mean carried no
discrimination and that `one_of` collapse structurally pinned it high.

**The real cause was a matcher bug, and it is fixed.**

#### 2.12a `partial_ratio` is asymmetric

`_term_hit` asks *"does this hint appear in this record?"* and answers with
`fuzz.partial_ratio(term, hay)`. rapidfuzz slides the **shorter** string over the
longer — so when the record is shorter than the phrase, the record becomes the
pattern and the question silently flips to *"does this record appear inside this
hint?"*

Measured against the brief's real hints:

| hint | record | score |
|---|---|---|
| `Blow drying your hair could be damaging your hair everyday` | `hair` | **100** |
| `What they don't tell you before you get a perm` | `a perm` | **100** |
| the same hints vs the actual speech (long haystack) | | **42–63** |

**21 spurious matches** from a handful of fragments. That video carries **204 OCR
intervals**, most of them a word or two — so every hook option found some
fragment "matching" it at 100, `l1_phrase` returned PASS, `_L1_ALIGNMENT` labelled
each one `exact`, and the choice group picked its winner from a twelve-way tie.
Hence L1 at 68%, twelve `~exact` hooks on a pill-organiser video, and a mean
pinned near 0.7.

**Fix:** a record too short to hold the phrase cannot be evidence of it —
`len(hay) < len(t) * 0.8` returns no match before the fuzzy path. An exact phrase
in a long transcript still returns 100 from the word-boundary test above it.

The earlier single-word-hint guard (§2.9) was treating a symptom of this.

#### 2.12b `27%` could never match anything

Found by a control in the same test. The boundary pattern was
`r'\b' + term + r'(?:s|es|ed|d|ing)?\b'`. For `27%` the closing `\b` sits between
`%` and a space — two non-word characters have no boundary between them, so the
match always failed, and at 3 characters the hint then took the short-term exit
before the fuzzy path. **Every numeric hint was inert.**

`(?!\w)` says what was meant: not followed by a word character. It holds after
`%` and after `l`, so `heal` still refuses to match `healthy` — verified.

*This is the third instance of the same mistake in this codebase* (the figures
regex in §2.8a, and now both halves of `_term_hit`). `\b` after optional or
punctuation-final groups is a recurring trap.

**`VERDICT_STAGE_VERSION 1.5.0`.** Verified: 107 checks across eight suites.

#### What this retracts

My conclusion in §2.11-era analysis — *"the decomposed layer cannot discriminate;
Phase 7's headline must come from standing"* — was drawn from numbers this bug
produced. Group-collapse taking the **best** member is still structurally true,
but whether it pins the score high depends on whether members legitimately score
high, and on an off-brief video they now should not.

**The comparison has to be re-measured before that conclusion stands.**

---

### 2.13 The actual cause: timing PASSed on evidence that merely existed  ✅ FIXED 2026-09-19

After the §2.12 matcher fixes the score went **up** — 0.81, 0.95, 0.95 — with L1
still at 68% and twelve hooks still `~exact`. The two-line check confirmed the
matcher fix was live (`(False, 0)` on both probes), so the asymmetry hypothesis,
though it fixed two genuine bugs, was **not the cause of this symptom**. Two
mis-attributions in a row on the same number.

**The cause is `l1_timing`.** Its PASS branch:

```python
inside = [c for c in cands if c['record'].start_seconds - tol <= deadline + slack]
first  = min(inside, ...)
if hi <= deadline:
    return _blank_verdict(rd, 'PASS', ...)      # <- no content check at all
```

Candidates are retrieved generously — `_hint_score` is documented as *"a ranking
signal, never an exclusion"* — so `inside` holds **every** record starting before
the deadline, related or not. The branch answers *"was anything early?"* and
reports it as *"was THIS early?"*.

With `with_temporal 19` of 22 requirements, that is most of the brief. On a
pill-organiser video each hook option carried a 3s deadline, each found OCR at
~0.5s, each returned PASS, `_L1_ALIGNMENT` stamped all twelve `exact`, and the
choice group picked a winner from a twelve-way tie. Hence a video with nothing
to do with the brief scoring 0.85–0.95.

**Fix:** a deadline can rule a requirement **out** — nothing was there in time —
but it cannot rule one **in**. The PASS path now needs a record that is both
early *and* matching (`hint_score >= fuzzy_min`); anything else escalates to
L2/L3, which judge content. The straddle test moved onto the matching record
too: the onset that matters is when the *required* content first appears, not
when the video first shows anything. The FAIL path is untouched — it fires only
when nothing at all precedes the deadline, which is a timing fact on its own.

`VERDICT_STAGE_VERSION 1.6.0`. Verified: 8 checks on this path (unrelated early
evidence escalates; a real early match still PASSes and cites the *matching*
record; all-late still FAILs; a straddle is still UNCERTAIN), 115 across nine
suites.

**Three §71 tests failed on this change, correctly.** They passed
`match_hints=[]` and expected `l1_timing` to decide, which is exactly the
contract that was wrong. Their job is the deadline *arithmetic* — straddle and
far-edge — so they now carry a hint matching the test record, and the arithmetic
is exercised as before. Two cases were added: that a PASS cites the record which
*matched* rather than merely the earliest, and that early-but-unrelated evidence
does not decide the requirement at all.

**Confirmed on the next run:** L1 fell **68% → 9%** and the off-brief mean fell
from 0.85–0.95 to 0.60–0.80.

### 2.14 A PASS earned by absence is not an alignment  ✅ FIXED 2026-09-19

With timing fixed, the remaining score was fully accounted for. Six scored units
on an off-brief video:

| unit | weight |
|---|---|
| `Any stated figures statistical claims` ~exact | **1.00** |
| `Any stated statistics percentages timeframes` ~exact | **1.00** |
| `Deliver call action` ~strong | 0.85 |
| ~tangential | 0.25 |
| ~none ×2 | 0.00 |

The two `forbidden` rules contributed **2.0 of the 3.10 total — 65% of the
score** — for a video that never went near the subject.

`_L1_ALIGNMENT` stamps every L1 PASS `exact`, with the reason *"the
requirement's own wording was matched"*. A forbidden rule passing on **absence**
matched nothing. Same category error as the timing bug: a check asserting more
than it established.

`alignment` asks *"how close is what she DID to what this was FOR"*. When she did
nothing relevant there is nothing to be close to, so the honest answer is **not
judged** — `None`, which the scored-unit filter already excludes. The verdict
stays PASS: compliance is real, it is just not achievement.

`l1_forbidden`'s absence-PASS and `l1_figure_fidelity`'s PASS now carry
`PASS_FROM_ABSENCE`; §70 refuses to derive an alignment for it. Replayed on the
run above: **0.52 across 6 → 0.28 across 4**, and the disagreement with standing
closes from −0.52 to −0.28.

§73's *"every L1 decision carries a DERIVED alignment"* encoded the old
assumption and was split in two: every L1 decision that **could** be aligned
carries one, and a PASS earned by absence carries **none** — with the count
reported as a NOTE rather than hidden.

**Still expected to remain after this:** other vacuous passes. Two of the six scored
units were `forbidden` rules passing at 1.0 because the video never went near
the subject. Compliance-by-absence and compliance-by-achievement still weigh the
same, and no matcher fix touches that — it is Phase 7's to answer.

---

### 2.15 Four fixes, and what finally explained the variance  ✅ FIXED 2026-09-19

Repeated triples across three videos, same code, `force=True`:

| video | speech | records | on brief? | range |
|---|---|---|---|---|
| anchor hair | 116 words | 38 | yes | **0.00** |
| near-silent | **1 word** | 19 | partly | 0.15 |
| pill organiser | 116 words | 234 | no | 0.36 |

Variance does not track how much evidence there is — the pill video had the most
and wobbled worst. **It tracks how decidable the question is.** A clearly
on-brief video with speech is deterministic; a near-silent one, or an off-brief
one where every call is *"does a pill-organiser CTA count as a hair CTA?"*, is
not. That is a judge behaving sensibly, and it means the spread is a **confidence
signal** rather than noise.

The residual instability across *separate sessions* is the compiler, and §2.15b
settles it without needing the compiler to be deterministic.

#### 2.15a `merge_visual_intervals` orphaned the far end of a link  (was BLOCKING)

Phase 5's `every link is mutual` criterion failed on the first video where a
linked record was also merged.

```python
for lid in r.linked_ids:            # r is being absorbed into cur
    if lid not in cur.linked_ids:
        cur.linked_ids.append(lid)
```

`cur` inherits `r`'s links; the records at the far end still name `r.id`, which
stops existing. `cur → X` held, `X → cur` did not. The comment above that block
says *"dropping its linked_ids orphans a cross-modal link"* — it fixed the
forward direction and left the reverse one pointing at a ghost.

Fixed by rewriting the back-reference from `r.id` to `cur.id`, deduplicating so
two absorbed records collapse to one entry rather than two.
`EVIDENCE_STAGE_VERSION 1.6.0`.

#### 2.15b An approved compile is a contract, not a cache entry

Same brief, same config, same version: **21, 22, 21** requirements across three
compiles. The differences sit entirely in **prose-derived** requirements — *End
video call action* / *Include call action* / *Deliver call action*, one ask and
three verbs — while the enumerated hook list came back identical every time.
Wording variance becomes count variance because `_req_fingerprint` hashes the
requirement text, and two phrasings that miss the 88 clustering bar are voted on
as separate requirements.

**This does not have to be fixed for scores to be stable.** The compiled brief is
an artifact a human reads in §48b and signs in §48c; once signed it is the
contract the audit is measured against. What was wrong is that running the
notebook top to bottom silently replaced it — so the same video and the same
brief produced a different score with nothing saying why.

§48 now reuses the newest **approved** compile for that brief hash and says so,
with `RECOMPILE_BRIEF = True` to replace it deliberately. Comparing two videos
is only meaningful against the same compile; this makes that the default.

#### 2.15c The choice-group winner was decided by a number the model invented

`_resolve_groups` broke ties on `-confidence`, which for an L3 verdict is
`llm_self_report`. Measured on a **fixed** brief: two runs named *Blow drying* as
the hook she used, one named *My hair*. Both scored `strong`, so the score never
moved — but the report makes a factual claim about which hook she used, and it
was not reproducible.

Tie-break is now the brief's own `ordinal`, with `requirement_id` as a backstop:
*"the option this brief listed first"*. Arbitrary, but explicable and identical
every run. Status and alignment still outrank it, verified.
`VERDICT_STAGE_VERSION 1.7.0`.

#### 2.15d §74 printed three `<-- PROBLEM` rows while §6 reported none

`cuda available False` (with a hosted vision provider, nothing needs CUDA) and
`intervals below the detection minimum` (a single sighting above the confidence
bar is admitted **by config**, as the next line already explained). Both rows now
compute their own ok-flag from the condition that actually raises an issue, so
the page stops contradicting itself.

**Verified: 132 checks across 11 suites**, including the exact failing cases —
the orphaned back-reference, two absorbed records sharing a peer, the winner
flipping on confidence, and approved-compile selection replayed against the real
artifacts on disk.

---

### 2.16 Compiler reliability: what varies, and what to do about it  ✅ 2026-09-19

With reuse in place (§2.15b) the compiler's run-to-run variance no longer moves
scores — an approved compile is frozen until deliberately replaced. What
remained was the quality of the one compile you approve, which matters because
new briefs are compiled often.

#### 2.16a One group, one ask  (`BRIEF 1.10.0`)

A live artifact reported `choice_groups 3` while carrying **four** distinct
`(group_label, group_intent)` pairs — so one group id held two intents. L3 judges
alignment against `group_intent`, so two members of one choice group were asked
different questions and then compared to pick a winner.

`normalise_group_intents` forces one value per group id (most common, then
longest), on both the consensus and single-shot paths, and records what it
reconciled.

#### 2.16b Fingerprint the document's sentence, not the model's phrasing

The compiler copies enumerated items verbatim and **phrases prose asks itself**,
so one ask returned as *End video call action* / *Include call action* / *Deliver
call action* across three compiles — three fingerprints, three separate votes,
and a requirement count that moved.

`_req_fingerprint` now hashes `brief_span`. Measured over every pair of compiles
on disk: agreement rose **30% → 47%**, and **4% → 47%** on the worst pair, never
falling. `brief_span` was usable on 95 of 95 requirements.

#### 2.16c Every option the brief lists gets a requirement  (`BRIEF 1.11.0`)

**The first attempt was wrong and was reverted.** It built the inventory from
`sec.lines`, which would have added a section preamble and three concept titles
as requirements and made bullets from different concepts mutually exclusive. The
test caught it: the example addition was *"These are videos that have performed
the best on TikTok…"*.

`section_items()` already models the document correctly, and I had not read it:

```
Creative concepts   15 lines ->  3 items   (numbered title absorbs its bullets,
                                            preamble dropped)
Hook Concepts       12 lines -> 12 items   (flat: one bullet, one item)
CTA Ideas            5 lines ->  5 items
```

Measured against that 20-option inventory: the compile that **enumerated**
covers 20/20; the one that **collapsed** hooks into *"use one of the approved
hook concepts"* covers 3/20. Collapsing has been forbidden by the prompt since
1.6.0, so this is a **safety net**, not a transformation — it fires only when an
option produced no requirement at all, and it only ever adds.

| compile | before | after | added |
|---|---|---|---|
| enumerated | 24 | 24 | **0** |
| collapsed | 16 | 33 | 17 |
| flat brief × 2 | 11, 12 | 11, 12 | **0** |

**Verified: 149 checks across 13 suites**, including that the preamble is not an
option, a bare concept title is not an option, a concept carries its bullets,
every addition joins its section's group and quotes the document, and nothing is
ever dropped.

#### What is still not deterministic

The option inventory is. The requirements the model writes from **prose** — a
policy line, a talking point, an instruction outside any list — still vary in
count and wording, and no parser change fixes that. Those are the requirements
that map to no document item, and they are reported rather than dropped.

---

### 2.17 Four modules were computed, then thrown away  ✅ FIXED 2026-09-20

**How it surfaced**

The §75 conformance cell reported `hook module produces the full spec §33
output` as NOT MET with the note *"no hook output in any audit; evaluate_hook
IS defined and wired in"*. The staleness banner showed only one artifact behind
the current stage version, so this was not an old-cache artefact — a fresh
1.9.0 audit had produced no hook output.

**Cause**

`evaluate_requirements` ends by writing its artifact:

```python
    write_json(path, out)
    return out
```

`audit_video` then attaches four modules to the dict it got back:

```python
    res['hook'] = evaluate_hook(...)
    res['claims'] = evaluate_claims(...)
    res['creative_angle'] = evaluate_creative_angle(...)
    res['standing'] = evaluate_standing(...)
    return res
```

Nothing writes the file again. There is exactly one `write_json(path, out)` in
each notebook, and it runs **before** those four lines. So `hook`, `claims`,
`creative_angle` and `standing` existed only in memory, for the life of the
kernel.

**The second cost, which is the expensive one**

`evaluate_requirements` returns early on a cache hit (`if path.exists() and not
force: return read_json(path)`). `audit_video` has no such guard, so the four
modules re-ran on **every** audit — four LLM calls per re-run, for results that
had already been computed and paid for. The cache appeared to be working
because the requirements half of it was.

**Fix**

`audit_video` now returns early when the cached artifact already carries the
four modules, and writes the enriched result back to the same path when it does
not. Same cache key by construction — identical video, evidence, brief and
`cfg` — so the same artifact is the correct home for them.

`VERDICT_STAGE_VERSION` 1.9.0 → **1.10.0**, because the artifact's shape
changed.

**Measured** (stubs counting calls, `test_audit_persist.py`, 12/12):

| | before | after |
|---|---|---|
| `hook` in the artifact | no | yes |
| module calls, first audit | 4 | 4 |
| module calls, **second** audit | 4 | **0** |
| `force=True` | 4 | 4 |
| unusable brief | 4 calls, no write | **0 calls, no write** |

**Bug class**

New one, worth naming: *a value attached to an object after that object was
serialised*. The in-memory result and the artifact disagreed, and every check
that read the artifact was right to say the field was missing. Related to the
`requirements`-re-derivation class in that both come from doing work in the
wrong order relative to a commit point.

---

### 2.18 'should' is inside 'shoulder'  ✅ FIXED 2026-09-20

**Symptom**

§74 reported one blocking issue: `phase 3: exit criteria not met`, on
`NO judgment language in any description [1 leak(s)]`. The §75 conformance cell
named the description:

```
1cea387c: 'should' in 'the woman holds the white jar near her shoul[der]'
```

**Cause**

```python
    low = f' {(text or "").lower()} '
    return [w for w in JUDGMENT_WORDS if w in low]
```

Plain substring containment. `'should' in 'shoulder'` is `True`. Pass 1 had
obeyed the prompt exactly — the description is pure observation — and the check
auditing it was wrong.

On a hair-care corpus this is not a rare collision. "Shoulder" appears in
length descriptions, in framing, in almost any shot of a person. The check
would have fired on most videos in the target domain.

**Fix**

Word-boundary matching, in both the notebook and the §75 cell:

```python
        if t and re.search(rf'(?<!\w){re.escape(t)}(?!\w)', low):
```

Lookarounds rather than `\b`: the list holds a hyphen (`non-compliant`), a
trailing space (`must `) and multi-word phrases, and `\b` cannot close a match
after punctuation — the same lesson as the `27%` figure-parsing fix (§2.8).

`VLM_STAGE_VERSION` 1.12.0 → **1.13.0**: the scan writes `JUDGMENT_LANGUAGE`
flags onto events and `judgment_leakage` onto the artifact, so cached visual
artifacts carry the false positive and must be rebuilt.

**Regression cover**

Three sentences added to the existing false-alarm corpus in the Phase 3 suite,
which already carried this exact lesson for `passes`, `adheres` and `meets the`
— it simply never held the word that broke. Measured: 12/12, including that
`should`, `compliant`, `violates`, `fails to`, `satisfies`, `does not meet` and
`must ` are all still caught.

**And the same class, in my own check**

The §75 probe `hook module produces the full spec §33 output` required a
`disclaimer` field. §33 defines no such field — I wrote the list from memory
instead of reading the spec, then reported a module that was producing the
complete output as incomplete. The probe now uses §33's actual field set, and
`_p3_judgments` calls the pipeline's own `detect_judgment_language` rather than
keeping a second word list that can drift.

Bug class, already named and repeated anyway: **a check taking its authority
from recall rather than from the document.**

---

### 2.19 A music-only video, and the two things it exposed  ✅ FIXED 2026-09-21

A 12.35s TikTok with **no speech, only music** (`5f18775d`, maddie.restucci).
The pipeline handled it correctly and, in doing so, showed two defects that no
talking video could have revealed.

**First, the good news — a criterion that had been unverifiable is now MET.**

plan.md's Phase 2 criterion *"zero hallucinated transcripts on a music-only
video"* had sat at MANUAL since Phase 2 for want of a sample. Whisper on
music-only audio is notorious for inventing whole sentences. It produced **1
word from 12.35 seconds**. Nothing invented. That is the single most dangerous
failure mode in the ASR stage, and it is now measured rather than hoped for.

---

**Defect 1 — "nothing was said" was treated as "we could not hear it"**

The gate marked speech `degraded` (reason: *only 1 word(s) transcribed*), so
`speech_only`, `speech_or_text`, `visual_and_speech` and `any` all refused to
support a FAIL. Every hook and CTA requirement abstained; L3's FAILs were
downgraded to UNCERTAIN with `FAIL_BLOCKED_BY_MODALITY_HEALTH`. Phase 7 then
reported **7–50 at 14% coverage** — an honest but useless band.

That gate is right for a *degraded* modality. It is wrong here, because these
are different findings:

| | meaning | may absence be asserted? |
|---|---|---|
| ASR failed | voice was present, we could not transcribe it | **no** — she may have said it |
| no speech exists | music-only; nothing was ever said | **yes** — "she did not say it" is a fact |

The video communicated entirely through captions: **8 OCR intervals, 100% of
the timeline**. Music-only-with-captions is a normal TikTok format, not an
error case, and the system could not score it at all.

`modality_health['speech']` now carries a third state:

```python
absent = bool(
    transcript and not degraded_asr
    and _ratio is not None
    and _ratio <= cfg.absent_speech_ratio_PLACEHOLDER    # 0.10
    and len(words) <= cfg.absent_speech_max_words)       # 3
```

and `can_fail_on` short-circuits on it, before `degraded`.

Three design points, each load-bearing:

* **`degraded_asr` vetoes absence.** A crashed transcriber also yields zero
  words, and that is the opposite finding. Measured: `degraded_asr=True,
  words=0` stays degraded and stays blocked.
* **Both conditions are required**, voiced *time* and word *count*. Either
  alone is ambiguous — a 60s video with 5s of speech has ratio 0.083 and 22
  words, and she plainly spoke. Measured: not absent.
* **`absent` is displayed separately** in §74. Setting `degraded=False` alone
  would have printed `degraded=False` for a music-only video, reading as
  healthy speech — the opposite of the truth.

`EVIDENCE_STAGE_VERSION` 1.6.0 → **1.7.0**.

---

**Defect 2 — `uncertain_rate` counted the wrong population**

```
UNCERTAIN rate : 12%   (above ~20% the EVIDENCE layer is the problem)
```

3 UNCERTAIN ÷ 24 requirements. But 20 of those 24 were `NOT_APPLICABLE`
choice-group losers. Against the population that means something — **scoring
units** — it was **3 of 4 = 75%**, far over plan.md's 20% line.

**The metric built to warn about exactly this run reported that everything was
fine.** It is the same bug Phase 7 had already fixed for scoring
(`NOT_APPLICABLE` leaves the denominator); Phase 6's own first-class metric
never received the same treatment. The old figure is kept alongside as
`uncertain_rate_all_requirements`, so nothing is lost and the two can be
compared.

`VERDICT_STAGE_VERSION` 1.10.0 → **1.11.0**.

**Measured** — 31/31, against functions extracted from the patched notebook
rather than retyped: three speech states separate correctly, both boundary
conditions hold on each side, a degraded ASR is still blocked, a modality that
never ran is still blocked, and the live run now reports 75% instead of 12%.

**Bug class.** Both are the same shape and it is worth naming: **a check whose
denominator, or whose category, silently included things it should have
excluded.** Phase 7 learned this once for scoring units. Neither the evidence
gate nor the health metric had learned it yet.

**Symptom**

```
run 1/3: 7 requirements
run 2/3: 7 requirements
run 3/3: 9 requirements
```

from a brief with roughly 24 genuine asks. An earlier single compile of the same
document produced 24.

**Diagnosis**

This is *not* the consensus mechanism — consensus can only keep what the runs
produce. The compiler itself finds a third of the brief on some runs and all of
it on others. The root cause is structural ambiguity in the compile prompt: given
a list of 12 hook options, the model cannot decide whether to emit

- 12 requirements (`Use hook: "Your shampoo isn't the problem"`, …), or
- 1 requirement (`Use one of the approved hook concepts`) with a choice group.

Both are honest readings. They audit completely differently: the enumerated form
pushes everything to L3 (13% L1), the collapsed form lets L1 decide on a deadline
(44% L1).

**Measured history of the same document**

| run | requirements |
|---|---|
| Sep 16 | 16 |
| Sep 16 (consensus, old fingerprint) | 6 |
| Sep 17 | 24 |
| Sep 18 | 9 |
| Sep 18 (consensus, old fingerprint) | 4 |
| Sep 18 (consensus, fixed clustering) | 8 |

**Options**

1. **Fix the prompt** (recommended). Instruct the compiler explicitly: *when the
   brief offers a list of alternatives, emit ONE requirement with a choice group
   listing them, never one requirement per alternative.* This removes the
   ambiguity at source and makes every run structurally comparable. Needs a
   `BRIEF_STAGE_VERSION` bump and a re-compile.
2. **Raise `runs`** to 5. More samples, better recall, 5 API calls. Does not
   remove the enumerate/summarise split — it just averages over it.
3. **Accept it** and treat the brief as approximate. Not viable if you intend to
   compare two audits of the same video.

Until this is settled, two audits of the same video against the same brief are
not comparable, which undermines everything downstream.

---

### 2.4 Phase 3 — the T4 frame ceiling (capability limit, not a defect)

**Measurement, from two runs on the same video**

| frames | pixels | est. tokens | result |
|---|---|---|---|
| 33 | 50176 | 2112 | ran |
| 48 | 25088 | 1536 | **OOM** |

Fewer tokens, but it failed. Cost is therefore **not** frames × pixels — there is
a substantial per-frame overhead in the vision tower, roughly 38 tokens' worth per
image. Solving the inequality gives an overhead of ≳30,000 px-equivalents per
frame, which makes 48 frames at any resolution cost about the same as 33 frames
at double the resolution.

**Consequence:** trading resolution for coverage stops paying past ~33 frames on a
15 GB T4. On an 84s video that is one frame every 2.5s.

**I was wrong earlier.** I predicted the reordered ladder would reach 48 frames at
quarter resolution. It reached 33. The ladder reordering was still correct — it is
why you get 33 at quarter-res rather than 33 at half-res with two wasted OOM
attempts — but the ceiling is set by frame count, not by pixels.

**Solution:** none needed on a T4; 33/48 = 69% coverage is above the configured
`degraded_frame_ratio` of 0.6 and now permits a visual FAIL (see §3.6). To get 48
frames, use a ≥20 GB GPU, where the planner already steps up to the 8B model at
full coverage.

---

### 2.5 L2 contributes 0% of decisions

Not a defect. Measured cosines land 0.46–0.69 and the thresholds sit outside that
band. Lowering them produced false PASSes, because on this brief the top scorers
were hooks the creator did *not* use — twelve alternative hooks are semantically
adjacent to each other by construction.

L2 is inapplicable to script-style briefs, not broken. It would earn its keep on a
brief of paraphrasable concepts. Cost is a one-off 130 MB download and some CPU.
Leave it until a concept-style brief is tested.

---

### 2.6 Minor

- `gemini-flash-latest` and `gemini-pro-latest` report unusable on the free tier
  and fall through to `flash-lite` on every call — two wasted probes per request.
  Pin the model list if it becomes annoying.
- `§74` reports Phase 1 from its manifest rather than its exit criteria, because
  §72 rebinds `result`. Cosmetic; the manifest figures are the durable record.

---

## 3. Fixed, with evidence

| # | Issue | Fix | Evidence |
|---|---|---|---|
| 3.1 | Cell 0's `!pip install … silero_vad` downgraded torch 2.11→2.9, stranding torchvision and killing Phase 3 | cell 0 disarmed; all installs run under a pip constraints file pinning the torch stack | `torch 2.11.0+cu128 / torchvision 0.26.0+cu128`, tags agree, extension loads |
| 3.2 | `hasattr()` on transformers' lazy module aborted the whole class probe, reporting "NONE" while claiming it would fall back | per-candidate probe catching `Exception` | reproduced with a fake lazy module: old loop returns none, new recovers both fallbacks |
| 3.3 | Model chosen by whether *weights* fit, ignoring room for frames | headroom-aware planner: most capable model that still affords the full frame budget | T4 → 4B nf4 (was 4B fp16); 20/24 GB → 8B nf4; 40 GB → 8B fp16 |
| 3.4 | Ladder gave up coverage before resolution, contradicting its own docstring | rung order reworked; `min_pixels` 50176→25088 so the quarter rung actually exists | quarter rung was previously identical to half and always pruned |
| 3.5 | `tokens_per_gb = 1200`, 5.8× too high, causing doomed rungs to be attempted | calibrated to 230 from the run (10.17 GB usable, 2112 ran, 3072 OOMed) | two wasted generations eliminated |
| 3.6 | A resolution cut blocked visual FAILs entirely | `can_fail_on` gates on **coverage**, not acuity; fails closed when coverage is unverifiable | 7 scenarios tested; 33/48 (69%) now permits a FAIL, 28/48 (58%) does not |
| 3.7 | Consensus compiler existed but was never called | wired into §48 with `BRIEF_COMPILE_RUNS = 3` | run counts now visible: 7, 7, 9 |
| 3.8 | Consensus counted rewordings as separate requirements and dropped both | fuzzy clustering before voting; `evidence_mode`/`deadline` removed from identity | `"here is what…"` vs `"here's what…"` ratio 99 → merged; different hooks 58/79 → kept apart. 4 stable → 8 |
| 3.9 | No way to see the whole pipeline's state | §74 full self-check added | never raises; tested against an empty kernel and a healthy run |

Stage versions: `VLM 1.12.0`, `EVIDENCE 1.5.0`, `BRIEF 1.5.0`.

---

## 4. What "finalised" cannot mean yet

`plan.md` line 46 states it: *"No labeled dataset exists | You cannot measure
anything at the start"*. There is still no ground-truth file in the project.

So Phases 1–6 can be finalised as **"every stage runs, every exit criterion
passes, every verdict is grounded and traceable"** — but not as *"the verdicts
are correct"*. Nothing in the repo measures correctness.

The four items the exit criteria already name as manual, unchanged:

- 5 scripts with deliberately planted claims, all flagged
- `speech_only` vs `ocr_only` verified on a burned-in-caption video
- one video audited against 3 briefs; only Phase 6 re-runs
- hook self-agreement, measured on 10 videos twice

Of these, the third is now nearly free (Phase 5 is cached by video, never by
brief), and the second is easy — this Aurelia video *has* burned-in captions, as
§2.1 shows.

---

## 5. Recommended order

1. ~~**§2.1** — Phase 2 criterion~~ **done**.
2. ~~**§2.2** — consensus rebuild~~ **done**.
3. **§2.3** — decide on the compile prompt. This is the one that determines
   whether the system is *useful*, as opposed to merely *correct*.
4. Re-run end to end, confirm §74 is clean.
5. Only then start Phase 7 (deterministic scoring and reporting, `plan.md` §7).

Only item 3 needs your call, because changing the compile prompt changes what
every brief compiles to and invalidates existing brief artifacts.

---

## 6. The Gemini-vision variant

`phases_1_to_6_gemini_vision.ipynb` sends the sampled frames to Gemini instead of
running Qwen locally. `run_vision_stage()` already accepted a `backend`, and the
only contract is `.generate(messages, images, cfg)`, so the frame sampling, the
ladder, the JSON contract, the timestamp guarantee and every exit criterion are
untouched — only who looks at the frames changes.

**Why it matters here:** §2.4 shows the local path is bounded at ~33 of 48 frames
on a T4 by per-frame overhead, at *any* resolution. A hosted model has no VRAM
ceiling, so it should run the full 48 frames at full resolution and `visual`
should never be degraded at all.

**The trade:** the frames leave the machine. On the local path nothing did.
Phase 4 already sends the brief text to the same provider, so this is a change in
degree rather than kind — but it is a real one. `VISION_PROVIDER = 'local'` in
§26c reverts.

`provider` is part of the vision cache key, so a Gemini artifact and a Qwen
artifact of the same video can never collide. `provider='gemini'` raises when
there is no key rather than silently running Qwen; only `'auto'` falls back, and
it announces it.

Known caveat: the cache key is built from `gemini_models[0]`. On this key only
`flash-lite` has been answering, so if `flash-latest` is unusable the key will
name a model that did not run. Set `gemini_models=('gemini-flash-lite-latest',)`
in §26c to make the key exact. The artifact's `model` field always records what
actually ran.
