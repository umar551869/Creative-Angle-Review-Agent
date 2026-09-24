# complete.md — project context and handoff

*Written 2026-09-21. Everything here was verified against the files on that date,
not recalled. Where a fact can go stale, the command to re-check it is given.*

> **THE DELIVERABLE IS ONE FILE:**
> [Phase 7/phases_1_to_7_gemini_vision.ipynb](Phase 7/phases_1_to_7_gemini_vision.ipynb).
> That is the notebook that runs on Colab; everything else exists to build and
> verify it. Keep it current.
>
> **This file is updated on every change, finding, or version bump** — not at the
> end of a session. A stale handoff costs a whole session of rediscovery.

Paste-ready opener for a new session:

> Read `complete.md` in the project root. That's the full context. I'm resuming
> work on Phase 7 of the video-audit system.

---

## 1. What this product is

An **AI audit system for short-form social video** (TikTok first). It takes a
video plus a brand content brief, watches the video, extracts multimodal
evidence, checks every brief requirement, and produces a timestamped
compliance/creative report.

The question the whole system is built around ([product.md:9](product.md#L9)):

> **"Given what the brief says should happen, what actually happened in the
> video, and where is the evidence?"**

The defining constraint: **it starts with no labeled training data.** Pretrained
open-weight models plus deterministic application logic. Human corrections
become the seed dataset later. This is *why* scoring is arithmetic and never a
model's opinion — there is nothing yet to calibrate a model-produced number
against.

**Stack** (from [product.md](product.md)): FFmpeg + OpenCV · Qwen3-VL (Gemini
vision in the current notebook) · Whisper ASR · PaddleOCR · BGE-M3 + Qdrant when
multi-brand retrieval is needed · FastAPI + Pydantic · Next.js · Postgres +
object storage.

---

## 2. The phase plan

13 phases in [plan.md](plan.md), built as **one Colab notebook**.

| phase | what | state |
|---|---|---|
| 0 | environment, dependency resolution, cache harness | done |
| 1 | preflight + deterministic preprocessing | done |
| 2 | ASR + OCR — the text evidence layer | done |
| 3 | VLM evidence extraction (pass 1); timestamp grounding is the crux | done |
| 4 | brief compiler → machine-checkable requirements | done |
| 5 | evidence normalizer + unified timeline | done |
| 6 | requirement evaluator, hook module, claims module | done |
| **7** | **deterministic scoring + reporting** | **current — machinery complete, 1 criterion open** |
| 8 | benchmark dataset, human review UI, metrics harness | **not started — blocks all calibration** |
| 9 | measured optimization | not started |
| 10 | productionization (demand-driven) | not started |
| 11 | specialized detectors (trigger-gated) | not started |
| 12 | RAG + fine-tuning (late, evidence-driven) | not started |

---

## 3. The design rules

These recur throughout the code and are effectively the project's constitution.
**Do not violate them without explicit discussion** — most were written after a
specific failure, and several have tests that enforce them.

1. **No model ever writes a number.** §76 is pure arithmetic. §78 is the only
   model call in Phase 7, and a recommendation containing a digit is *rejected*
   — the only number a recommendation may carry is a timestamp it cited.
2. **Compliance is not achievement.** A `PASS_FROM_ABSENCE` ("no medical claims
   were made") never averages into the score. It is reported separately as
   *"no violations found: N of N"*. This came from a real failure: an off-brief
   video scored 65% on vacuous passes.
3. **`UNCERTAIN` is an abstention, not a zero.** Averaging it as 0 turns "we did
   not look" into "they failed." It leaves the numerator and is disclosed.
4. **`NOT_APPLICABLE` leaves the denominator.** A twelve-option hook list is one
   decision, not eleven failures.
5. **Bands, not false precision.** Three scoring units cannot carry a decimal
   place. Below 90% coverage the report leads with a band (`75-100`).
6. **The grade reads from the established end.** At partial coverage the band is
   graded from the *pessimistic* end, so an undecided quarter can never be
   stamped APPROVED. The artifact records which end it read (`band_basis`).
7. **Everything traces.** Every number on the page traces to a requirement;
   every requirement traces to an evidence id. Untraceable ⇒ off the page.
8. **Bump the stage version in the same edit that changes the output.** See §6
   below — this is the rule most recently broken, and the most expensive.
9. **Degrade, never block.** No plotly ⇒ figures become notes and the report
   still renders, scores and all. The report is one self-contained HTML file:
   no server, no network, no external fetch.
10. **Two independent things must agree, or the system abstains.** One number
    from one model call may never change a verdict on its own. Where a second
    signal exists (`standing`, the decomposed mean, substance alignment), it is
    **reported alongside and never blended** — a blended number cannot be
    un-blended downstream. Violating this is what produced the false-positive
    PASS in §8b.
11. **A prompt instruction is a request, not a guarantee.** Where the model is
    asked for something structural, the compile also **measures** whether it
    complied (`audit_group_intents`, `extract_temporal` cross-checks). And a
    measurement that is never called measures nothing — test the call site, not
    just the behaviour.

---

## 4. Repository layout

```
creative project/
├── complete.md                    ← this file
├── plan.md                        13-phase engineering plan
├── product.md                     product spec
├── requirements-local.txt
├── Phase 6/
│   ├── phases_1_to_6_gemini_vision.ipynb    ← BUILD INPUT (never hand-edit; patch it)
│   ├── phases_1_to_6_gemini_vision.prefix.ipynb  ← pre-fix backup, restore point
│   ├── patches/
│   │   └── apply_p6_fixes.py                ← the ONLY way Phase 6 changes
│   ├── phase_conformance_cell.py            §74b, plan conformance
│   ├── PHASE_1_6_FINALISATION.md
│   └── phase_6_plan.md, README.md
├── Phase 7/
│   ├── PHASE_7_PLAN.md
│   ├── cells/                     ← EDIT HERE, never the .ipynb
│   │   ├── s75_config.py          scoring constants, stage versions, thresholds
│   │   ├── s75b_discriminate.py   which quantity discriminates (no labels)
│   │   ├── s76_score.py           score_audit — the arithmetic
│   │   ├── s77_tests.py           110-check test suite
│   │   ├── s78_recommend.py       the one model call
│   │   ├── s79_report.py          the HTML report
│   │   ├── s79b_figures.py        plotly figures
│   │   ├── s80_run.py             score the target, write artifacts
│   │   ├── s81_exit.py            Phase 7 exit criteria
│   │   └── s82_selfcheck.py       self-check addendum
│   ├── verify/                    ← verification harness (see §5)
│   └── phases_1_to_7_gemini_vision.ipynb    ← BUILD OUTPUT (254 cells, 1.86 MB)
└── work/
    ├── inbox/                     source videos
    ├── runs/                      batch run records
    ├── exports/                   .tar.gz run exports
    └── artifacts/                 content-addressed stage outputs (on Colab)
```

### The build workflow — important

**The notebook is generated. Never hand-edit `phases_1_to_7_gemini_vision.ipynb`.**

```
Phase 6/phases_1_to_6_gemini_vision.ipynb  (outputs cleared)
      ↑ changed ONLY by Phase 6/patches/apply_p6_fixes.py
      +  Phase 6/phase_conformance_cell.py  (§74b)
      +  Phase 7/cells/*.py                 (in execution order)
      ─────────────────────────────────────────────────
      →  Phase 7/phases_1_to_7_gemini_vision.ipynb   ← THE DELIVERABLE
```

**Phase 7 changes** → edit `Phase 7/cells/*.py`, then rebuild.
**Phase 6 changes** → add a fix function to `Phase 6/patches/apply_p6_fixes.py`,
run it, then rebuild. Phase 6 has no source-cell directory — the notebook *is*
the source, and a 9.7 MB `.ipynb` is not reviewably hand-editable. Every fix
there is idempotent, asserts it matched something, and can be re-applied from
`phases_1_to_6_gemini_vision.prefix.ipynb` for a clean run.

```powershell
$py = "C:\Users\Umar Ilyas\AppData\Local\Programs\Python\Python313\python.exe"
# only if Phase 6 changed:
& $py "C:\Users\Umar Ilyas\creative project\Phase 6\patches\apply_p6_fixes.py"
# always:
& $py "C:\Users\Umar Ilyas\creative project\Phase 7\verify\build_notebook.py"
```

To re-apply the Phase 6 patches from scratch (proves the patcher still works):

```powershell
$p6 = "C:\Users\Umar Ilyas\creative project\Phase 6"
Copy-Item "$p6\phases_1_to_6_gemini_vision.prefix.ipynb" `
          "$p6\phases_1_to_6_gemini_vision.ipynb" -Force
& $py "$p6\patches\apply_p6_fixes.py"
```

Two things the build script guards, both from real incidents:

- **Outputs are cleared.** A notebook carrying another run's output lies about
  its own state.
- **Every read/write names `encoding='utf-8'` explicitly.** An earlier build lost
  that on a round trip and turned every `§` into mojibake — which parses, tests
  green, and looks like nothing until a human reads the page. The build prints
  `section signs: 746   mojibake: none` as proof.

**Cell order is execution order, not numeric order.** §77 tests
`build_report_html` and `build_figures`, so it is placed *after* §79/§79b. A
number is documentation; position is behaviour.

---

## 5. The verification harness

**Relocated into the project on 2026-09-21** (`Phase 7/verify/`). It previously
lived in a session temp directory that would have been deleted — if a future
session cannot find these, that is why.

All are plain Python, no GPU, no network, no model calls, no API keys. They read
the notebook source and exercise it against fixtures.

| script | checks | what it covers |
|---|---|---|
| `test_p7_score.py` | 48 | the arithmetic, by hand |
| `test_p7_report.py` | 40 | HTML, escaping, seek links, determinism |
| `test_p7_discriminate.py` | 12 | §75b pre-registered rule |
| `test_p7_alignment_figs.py` | 28 | figures + evidence-id provenance |
| `test_speech_absent.py` | 31 | UNCERTAIN / absent-speech handling |
| `verify_p5_block.py` | 11 | Phase 5 fixtures |
| `test_p7_integration.py` | 115 | end-to-end; runs the full §77 suite |
| `crosscheck_notebook.py` | 65 | shallow structural cross-check |
| `crosscheck_deep.py` | 31 | cross-phase mutation, shape-vs-version tripwire |
| `test_p6_fixes.py` | 67 | §8b fixes, substance-credit gates, intent repair, claims scoring |
| `p7_harness.py` | — | shared fixture helper (imported by the above) |
| `build_notebook.py` | — | the build script |

**Run everything** (last full run 2026-09-21: **266 checks, all green**):

```powershell
$v = "C:\Users\Umar Ilyas\creative project\Phase 7\verify"
$py = "C:\Users\Umar Ilyas\AppData\Local\Programs\Python\Python313\python.exe"
& $py "$v\build_notebook.py"
foreach ($t in @('test_p6_fixes','test_p7_score','test_p7_report','test_p7_discriminate',
                 'test_p7_alignment_figs','test_speech_absent','verify_p5_block',
                 'test_p7_integration','crosscheck_notebook','crosscheck_deep')) {
  "--- $t"
  & $py "$v\$t.py" 2>&1 | Select-String -Pattern '^\d+/\d+ checks pass|arithmetic checked|^\s*\[FAIL|^\s*FAIL\s'
}
```

Verified working verbatim on 2026-09-21. Expected output — note
`test_p7_integration` runs the full §77 suite, and the one `[FAIL]` is the known
open criterion from §9, not a regression:

```
--- test_p6_fixes          37/37 checks pass
--- test_p7_score          48/48 checks pass
--- test_p7_report         40/40 checks pass
--- test_p7_discriminate   12/12 checks pass
--- test_p7_alignment_figs 28/28 checks pass
--- test_speech_absent     31/31 checks pass
--- verify_p5_block        11/11 checks pass
--- test_p7_integration   110/110 checks pass
     [FAIL  ] §75b answered: some quantity separates own brief from foreign
     arithmetic checked by hand (25-30, 83% coverage, 4 units): PASS
--- crosscheck_notebook    65/65 checks pass
--- crosscheck_deep        31/31 checks pass
```

`§77` inside the notebook runs a further **110 checks** on Colab. It runs in a
**temp-directory sandbox** (`DIRS['artifacts']` redirected, restored in
`finally`) so it cannot collide with a previous run or pollute real artifacts.
It prints `(ran in a sandbox; artifacts left in work/artifacts: ...)` — that list
should read `none`.

---

## 6. The caching model — read this before changing any stage

Every stage is **content-addressed**. A stage's cache key is built from
`stage_key(name, STAGE_VERSION, [input hashes], {config})` and written to
`work/artifacts/<video hash>/<stage>__<key>.json`. If the file exists, it is
returned and **the stage does not run**.

**The key is built from the version constant, not from the artifact's shape.**
So if you change what a stage *outputs* without bumping its `STAGE_VERSION`, the
key is unchanged, the stale file matches, and the pipeline silently returns data
computed by older code — while your freshly-passing tests say otherwise.

This happened on 2026-09-21. Two fixes changed the score artifact (`band_basis`,
`inferred_units`); neither bumped `SCORE_STAGE_VERSION`. §80 printed
`SCORE CACHE HIT` and reported `APPROVED` from the previous run's artifact while
§77 was 110/110 green. Cost most of a session to find.

**Guard now in place:** `crosscheck_deep.py` section E records the score
artifact's field set *beside the version it belongs to* (`SCORE_SHAPE`). Change
either without the other and it fails. Verified to bite.

### Current stage versions

| stage | version |   | stage | version |
|---|---|---|---|---|
| `ASR_STAGE_VERSION` | 1.0.0 | | `EVIDENCE_STAGE_VERSION` | 1.7.0 |
| `OCR_STAGE_VERSION` | 1.3.0 | | `VERDICT_STAGE_VERSION` | **1.14.0** |
| `SCAN_STAGE_VERSION` | 1.0.0 | | `SCORE_STAGE_VERSION` | **1.2.0** |
| `DECODE_STAGE_VERSION` | 1.1.0 | | `REPORT_STAGE_VERSION` | 1.0.0 |
| `AUDIO_STAGE_VERSION` | 1.0.0 | | `RECOMMEND_STAGE_VERSION` | 1.0.0 |
| `VLM_STAGE_VERSION` | 1.13.0 | | `FIGURE_STAGE_VERSION` | 1.0.0 |
| `BRIEF_STAGE_VERSION` | **1.21.0** | | `BRIEF_PROMPT_VERSION` | **p4_brief_compile_v5** |

**As of 2026-09-22** — re-check with
`Select-String -Path "Phase 6\patches\apply_p6_fixes.py" -Pattern "STAGE_VERSION"`.
`BRIEF` moved 1.16→1.21 across fixes 14–16; `SCORE` is 1.3.0, `VERDICT` 1.14.0.

Bumped 2026-09-21: `BRIEF` 1.12.0 → 1.13.0 and prompt v4 → v5 (fixes 1–3);
`VERDICT` 1.11.0 → 1.13.0 (fix 4, then the substance-credit gates);
`SCORE` 1.0.0 → 1.3.0 (band_basis, inferred_units, the literal score, then the
not-in-brief exclusion).

⚠️ **These bumps mean the brief recompiles and the verdicts re-evaluate on the
next Colab run — that is real model spend.** It is also the whole point: without
them you would keep reading the old artifacts. `§75b` control audits are a
*separate* cost and stay off unless you turn them on.

Re-check: `Select-String -Path "Phase 7\cells\s75_config.py" -Pattern "STAGE_VERSION = "`

---

## 7. Phase 7 section map

**Navigate by the `# §NN` header text, not by cell number.** Numbering schemes
differ between editors and an off-by-one here wastes a session. Both schemes as
of 2026-09-21 (254 cells, 144 code):

| § | what | model calls | abs idx | code-cell # |
|---|---|---|---|---|
| §74a | Phase 7 dependencies (plotly, guarded) | — | 240 | 133 |
| §74b | plan conformance, Phases 0–6 | — | 241 | 134 |
| §75 | scoring configuration — every constant | — | 243 | 135 |
| §75b | **which quantity discriminates?** | — | 244 | 136 |
| §76 | `score_audit` — the number, by arithmetic | — | 245 | 137 |
| §78 | recommendations | **one** | 246 | 138 |
| §79 | the report — one self-contained HTML file | — | 247 | 139 |
| §79b | figures — geometry of dimension matching | — | 248 | 140 |
| §77 | Phase 7 test suite (after what it tests) | — | 249 | 141 |
| §80 | score the TARGET, render, write artifacts | — | 250 | 142 |
| §81 | Phase 7 exit criteria | — | 251 | 143 |
| §82 | self-check addendum, Phases 1–7 | — | 252 | 144 |

Regenerate this table any time with the build script's sibling logic, or:
`python -c "import json,re; ..."` over the notebook.

---

## 8. What Phase 6 measured, and why Phase 7 looks like this

| measured in Phase 6 | consequence |
|---|---|
| **alignment mean does not discriminate** — 0.72 on-brief vs 0.68 off-brief, ranges overlapping | it cannot be the headline; §75b tests alternatives against a pre-registered rule |
| **`standing` separated perfectly** — six runs, zero variance | travels with every score as a cross-check allowed to *contradict* it |
| a forbidden rule passing vacuously **scored 1.0 and contributed 65%** of an off-brief score | `PASS_FROM_ABSENCE` held out of achievement entirely |
| 26 requirements collapse to **3 scored units** | band is the main output; unit count sits beside the number |
| L3 sampling moved the mean **0.34 on identical inputs** | "deterministic" = reproducible *from a named verdict artifact*, not stable across runs — every report names the `verdicts__*.json` it scored |

---

## 8b. The 5f18775d × Aurelia defects — FIXED 2026-09-21

Found by reading the actual verdicts for video `5f18775d` against the Aurelia
brief. The video is **12.35s, music-only, and has no CTA at all**; it closes on
the caption *"All you need is one routine clinically tested and proven to
support hair growth"* — a **product claim**, not a call to action.

Four defects compounded, and the system was about to report that CTA as **PASS**.

| # | defect | fix |
|---|---|---|
| 1 | **Labels collided.** `make_label()` spent its whole 5-word budget on the shared prefix *"Deliver the Call to Action:"*, so two different CTA options both printed `Deliver Call Action I m` — and `I'm` was split into a bare `m`. Same bug hit the hooks. | Strip the directive preamble first, prefer the quoted thing the creator must say, keep apostrophes inside words, drop stopwords only to fit. Budget 5 → 8. |
| 2 | **`group_intent` was subject-free.** *"Conclude the video with an approved call to action…"* names a **position**, not a thing to look for. L3 judges alignment against it, so any closing sentence aligned — which is how a product claim rated `strong`. | Prompt now requires the intent to name the **observable thing**. And because a prompt cannot be trusted to have obeyed, `audit_group_intents()` **measures** it: an intent sharing no content word with its own options is flagged `GROUP_INTENT_SUBJECT_FREE`. |
| 3 | **The window was unchecked.** The model supplied `window_start_expr = "duration - 15"`; the brief never mentions 15 seconds. `validate_time_expr` only checks an expression *parses*. The rule-based cross-check existed but fired **only when the model supplied nothing**. | The cross-check now runs **both directions**: `WINDOW_DISAGREES_WITH_BRIEF` when model and rules differ, `WINDOW_UNSUPPORTED_BY_BRIEF` when the number appears nowhere in the brief text. |
| 4 | 🔴 **The promotion hid all of it.** `_SUBSTANCE = {'exact':'PASS','strong':'PASS',…}` overwrote a literal `FAIL` with `PASS` whenever alignment was strong. With the speech-absent fix now permitting a real FAIL, the re-run **would have reported PASS on a video with no CTA** — the false-positive PASS `plan.md` calls the most damaging error class. | **Status is never overwritten.** A FAIL stays a FAIL. Alignment is carried beside it as `SUBSTANCE_ALIGNMENT:<level>`, and as `SUBSTANCE_ALIGNMENT_UNTRUSTED` when the intent it was judged against is subject-free. |

**Why #4 matters beyond this video.** It was the only place in the system where
**one number from one model call changed a verdict with no cross-check**.
Everywhere else two independent things must agree, or the system abstains. The
signal is not discarded — it is *reported alongside*, the same treatment
`standing` and the decomposed mean already get. A blended number cannot be
un-blended downstream.

Correction to the original analysis: `duration - 15` was **not** a system
default. `cfg.default_cta_window = 5.0`, so the model genuinely invented 15.

### Two bugs found in the fixes themselves

Both caught by the harness, both worth remembering:

- **A uniqueness marker is only as good as its string.** The patcher's
  idempotency check keyed on `'1.13.0'`, which already matched
  `VLM_STAGE_VERSION` — so the version bump silently reported itself as already
  applied while `BRIEF` stayed at 1.12.0. Markers now name the constant.
- **A function nobody calls measures nothing.** `audit_group_intents()` shipped
  **defined but never called**, making the whole subject-free half of fix 2
  inert — and with it fix 4's untrusted path and two report warnings. Every
  behavioural test passed, because they all asserted how it *behaves* and none
  asserted that it *runs*. There is now a test for the call sites.

### Fix 8 — the model ladder (added 2026-09-21, after a killed §72)

A full-notebook run on a new video looked like a hang at **§72** and was killed
after 5 minutes. It was not hung — it was walking a ladder of dead models on
every single call:

```
gemini-flash-latest unusable, trying the next model
gemini-pro-latest unusable, trying the next model
gemini-flash-lite-latest: transient, retrying in 1s
```

Phase 3 had already **measured** this and written it into the notebook —
*"gemini-flash-latest 503 UNAVAILABLE … gemini-flash-lite-latest OK in 2s ←
the only one that serves"* — and set `DEFAULT_MODELS =
('gemini-flash-lite-latest',)`. **Phase 4/6 never got the same treatment.** Its
`hosted_model_ladder` still tried the two dead models first, so every brief
compile and every L3 adjudication burned two failed round trips plus back-off
sleeps before reaching the one that works. Across 21 requirements plus hook,
claims, angle and standing calls, that is minutes of pure latency.

`hosted_model` is now `gemini-flash-lite-latest` and the ladder leads with it.
The other two stay as fallback — a 429 is a quota, not a tombstone — they are
just no longer first. **No stage version moves: this is ordering only, and
changes no output.**

Lesson worth keeping: a measurement recorded in one phase's comments is not
applied to another phase by osmosis.

### First live run of the fixes — 2026-09-21, new video + new brief

The fixes fired on a brief they had never seen:

- **Fix 2 caught it again.** `WARN 1 group intent(s) name a POSITION, not a
  thing to look for: cta_group (5 options)` — the same defect class as the
  Aurelia brief, on the same kind of requirement (CTA), caught automatically.
- **Fix 4 held.** `no verdict was promoted out of its literal status`, and
  `16 requirement(s) FAILED literally but align with the brief's intent`, of
  which `4 were judged against a group intent that does not describe its own
  options`.
- **Fix 1 worked.** Labels read as English: `Replace ending speech with
  'I'm sticking'`, `Open video hook 'Everybody talks about hair growth'`.

**One check of mine was wrong** and reported a false FAIL:
`every alignment-bearing verdict still reads FAIL — 16 carry an alignment`.
Alignment is tagged on FAILs, and *then* `_resolve_groups` turns the losers of
a choice group into `NOT_APPLICABLE`. On a brief that is mostly alternatives
(2 groups covering 17 options), most alignment-bearing verdicts legitimately end
as `NOT_APPLICABLE`. The invariant that actually matters is that **none became
PASS or PARTIAL** — that is what a promotion would look like. Corrected.

**The ladder fix did not take effect in that run.** §78 printed the old order
`['gemini-flash-latest', 'gemini-pro-latest', 'gemini-flash-lite-latest']`.
There is no separate Phase 7 model config — §78 reuses Phase 4's `BriefConfig`
from **§37 (cell 86)**. The run continued in a kernel that still held the
pre-fix config. **Re-run §37, or restart the runtime,** for fix 8 to apply.
The brief compile fell all the way through to `openai:gpt-4.1-mini`, which is
**billable** — that is what an exhausted Gemini ladder costs.

### THE PRODUCT RULE, made explicit 2026-09-21 — and what it changed

The user settled the open question below:

> *"we are not looking for literal matching. we gave the content brief as
> reference to the creators, next is her creativity. She has to talk about
> similar stuff as mentioned in the content brief — she can use her own
> relevant hooks, CTA or explanations, that is fine."*

**So the brief is a REFERENCE, not a script.** A requirement met in the
creator's own words is **met**. Literal matching is not the standard, and a
system that fails her for paraphrase is measuring the wrong thing.

This is what the original `_SUBSTANCE` promotion was *trying* to do. It was
right in intent and unsafe in mechanism:

- it judged alignment against a `group_intent` that often named only a
  **position** — "conclude the video with a call to action", which any closing
  sentence satisfies;
- it trusted **one uncross-checked model call**;
- it **overwrote** the literal status, so nothing downstream could tell
  paraphrase from a real match.

Three things changed, so the credit can now be granted **safely**:

1. `audit_group_intents()` (fix 2) detects the subject-free intent that made
   the Aurelia alignment meaningless. **That is the guard that would have
   caught it.**
2. An alignment citing **no record** is an assertion, not a finding, and earns
   nothing.
3. The literal status is **kept** on every credited verdict, and Phase 7
   computes a literal-only score beside the credited one.

**The two gates.** A literal FAIL is credited to PASS (or PARTIAL for a
`partial` alignment) only when **both** hold:

| gate | why |
|---|---|
| the group intent describes its own options (not `GROUP_INTENT_SUBJECT_FREE`) | otherwise anything in the right position "aligns" |
| the verdict cites at least one record | an alignment with nothing to check it against is an assertion |

Forbidden rules and `FAIL_FROM_POSITIVE_EVIDENCE` are exempt as before — a
forbidden FAIL means the prohibited thing was **found**.

Where either gate fails, the literal FAIL **stands**, flagged
`SUBSTANCE_ALIGNMENT_UNTRUSTED:subject_free_intent` or `:cites_no_record`.

**Two numbers, never blended.** The score artifact now carries both:

| field | meaning |
|---|---|
| `headline` | credits work done in her own words — **the product's answer** |
| `literal_headline` | brief-wording matches only — the strict reading |
| `credited_in_substance` | how many requirements the credit covers |

The gap between them *is* the paraphrase, made measurable instead of assumed.
Design rule 10 still holds: the two readings are reported side by side, and a
reader can see exactly how much of the score rests on the model's alignment
judgement. Phase 8 can then measure whether that credit was deserved — an
experiment that is impossible if only one number survives.

`SCORE_STAGE_VERSION` 1.1.0 → **1.2.0**, `VERDICT_STAGE_VERSION` 1.12.0 →
**1.13.0**.

### End-to-end cross-check against the product rule — 2026-09-21

*"We measure closeness by MEANING: does what the creator is doing, promoting or
saying mean the same thing the brief asks for? The rest is her creativity."*

The pipeline was audited against that definition, layer by layer. **It already
had the right architecture** — the design comment in §63 states the rule almost
word for word:

> *"A brief that lists 12 hooks is not demanding one of those 12 sentences. It
> is describing the KIND of opening it wants. A creator who writes her own hook
> in that spirit has done what the brief asked; marking her FAIL for not copying
> a line is the single most unfair thing this system could do."*
>
> `verdict` — did she do what the requirement **literally states**?
> `alignment` — how close is what she **DID** to what the requirement was **FOR**?

| layer | does it judge meaning? | evidence |
|---|---|---|
| `l1_phrase` | **abstains** on wording mismatch | `return None  # let L2/L3 try paraphrase` |
| `l1_presence` | FAILs only on **confident absence** | she never talked about it — a meaning failure, not wording |
| `_L1_ALIGNMENT` | `{'PASS':'exact','FAIL':'none','PARTIAL':'partial'}` | honest: an L1 FAIL *is* absence |
| L2 | embedding similarity | meaning by construction |
| L3 | judges "how close is what she DID to what this was FOR" | the meaning scale |
| `ALIGNMENT_LEVELS` | `none → tangential → partial → strong → exact` | the meaning scale, ordinal, never a model number |
| **the score** | **now credits meaning** | substance credit converts `exact/strong→PASS`, `partial→PARTIAL` |

`tangential` and `none` earn no credit — correctly: "related but not the same
ask" is not the same meaning.

**The gap the audit found:** an **invented requirement was still scored.**
Phase 4 flags `SPAN_NOT_IN_BRIEF:possible_invention` when the compiler cannot
quote the brief sentence a requirement came from — but the flag was advisory
only. The requirement was compiled, evaluated, and **counted against the
creator**. Measured live: **1 of 21** on this brief (cell 49:
`FAIL nothing flagged as invented — 1 requirement(s) could not be traced`).

Judging her on an ask the brief never made is the exact opposite of judging
meaning against the brief. **Fixed:** an untraceable requirement now leaves the
denominator — the same treatment `NOT_APPLICABLE` gets, for the same reason.

It is **not deleted**: it stays in the artifact, is counted as
`not_in_brief_excluded`, is named in `not_in_brief_ids`, and is printed by §80.
The flag can be a false positive — the model may have paraphrased a real brief
sentence it failed to quote — so fixing the brief text brings it back into the
score. `SCORE_STAGE_VERSION` → **1.3.0**.

### THE CRUX RULE — the product's primary question

> *"The crux of the creator's video must align with the crux of the content
> brief. If she is doing something relevant to the requirement she should be
> scored positive for that requirement."*

That is a **whole-video** question, and the system already had the signal:
`standing` (§69c), *"the WHOLE brief against the WHOLE video, as one
judgement"*, which exists precisely because *"NO LAYER EVER SEES THE WHOLE
AGAINST THE WHOLE."* Its anchor for `on_brief` is the rule verbatim:

> *"does what the brief asks, **in her own words and her own way. A different
> hook, a different structure, a different order — same substance.** This is the
> normal good outcome."*

`STANDING_SYSTEM` tells the judge: *"the question that decomposition cannot
ask: does this video do what this brief wants?"* and *"Judge SUBSTANCE, not
wording."*

**What was wrong: it was never presented.** §80 went straight to THE SCORE,
and standing surfaced only if a contradiction happened to mention it. In the
report it sat in `Modules`, below every requirement row. A reader who stopped
early got a percentage without ever learning whether the video was about the
right thing — the wrong order to answer those two questions in.

**Fixed:**

- §80 now prints **`DOES THE CRUX ALIGN?`** *before* THE SCORE — the level, its
  anchor meaning, the judge's own sentence, and a caution when `partial`
  ("substantial parts of the brief are untouched; read the score as how well
  she did the part she engaged with").
- The report gets a **`Does the crux align?`** section directly below
  contradictions and above everything else.
- THE SCORE is relabelled *"how closely she followed the specifics"* — the
  second question, explicitly.
- **Per-requirement alignment shows on every judged row** as
  `meaning: strong` — the meaning score for that requirement, independent of
  wording. `None` ("not judged") is distinct from `none` ("judged, unrelated").

### Relevant work is never scored negative

Two changes so that doing something relevant always helps her:

**1. An alignment that cannot be CHECKED abstains — it does not fail.**
Previously an untrusted alignment left the verdict at `FAIL` = 0. But that was
*our* compiler's defect, not her work. It is now `UNCERTAIN` + flag
`UNDECIDABLE_ALIGNMENT`: an abstention that leaves the numerator (design rule
3), never a zero. Coverage drops, which is the honest report.

**2. A subject-free intent is REPAIRED before L3 ever sees it.**
L3 is the layer that can tell whether two different sentences mean the same
thing — that is what it is for. It failed on the CTA group not because it
judges badly but because we handed it *"Conclude the video with a call to
action"*, which any closing sentence satisfies. **Given a bad reference, a good
judge returns a bad answer.**

So `audit_group_intents()` now appends the group's own options to the intent:

```
"Conclude the video with an approved call to action ... Specifically, the
 video should do one of these, in her own words: "I'm sticking with this";
 "I'm not gatekeeping this, link it in the bio"; ..."
```

Deterministic, invents nothing, and the flag stays so the brief can still be
fixed at source. A repaired intent passes gate 1, so those alignments become
creditable — the 4 untrusted ones on the last run included.

`BRIEF_STAGE_VERSION` → **1.14.0**, `VERDICT_STAGE_VERSION` → **1.14.0**.

### Fix 9 — the repair crashed the audit (found on the live run, 2026-09-21)

§72 died mid-run with:

```
TypeError: Requirement.__init__() got an unexpected keyword argument
           'group_intent_original'
```

The intent repair writes `group_intent_original` onto the requirement dict;
`Requirement` is a dataclass with a fixed field set. It failed **after** the
brief had compiled and been paid for — the worst place to discover a schema
mismatch.

**Two parts, and the second matters more:**

- **9a** — `group_intent_original: str = ''` added to `Requirement`. The
  repair's provenance now has a real home, so the original wording is
  auditable.
- **9b** — `Requirement(**rd)` now filters to known fields, **exactly as
  `EvidenceRecord` already did five cells away**. That idiom existed and was
  never applied here, which is why adding one field upstream could take down an
  audit. Unknown keys are recorded on the requirement as
  `UNKNOWN_FIELD_DROPPED:<names>` rather than silently discarded.

No stage version moves: this reads an artifact the compile already produced.
The cached brief already contains the field, so **no recompile is needed**.

Lesson: a defensive idiom used in one place is not applied to another by
proximity. `EvidenceRecord` had the guard; `Requirement` did not.

### The run that proved it — 2026-09-21, second full run

Everything built this session fired correctly:

| | evidence from the run |
|---|---|
| fix 8 ladder | `models ['gemini-flash-lite-latest', …]`, `backend: gemini:gemini-flash-lite-latest` — **no fallthrough to paid OpenAI**, 2 batched L3 calls for 21 requirements |
| fix 9 | no `TypeError`; the audit completed |
| substance credit | **7 credited**, each carrying `LITERAL_STATUS_WAS:FAIL/…` + `SATISFIED_IN_SUBSTANCE` |
| the new §73 guards | all four PASS, including `an undecidable alignment is UNCERTAIN, never a FAIL — 0 could not be checked` |
| crux first | `DOES THE CRUX ALIGN? … ON BRIEF (weight 0.85)` printed **above** `THE SCORE` |
| both numbers | `literal wording only: 40   with her own versions credited: 100` |
| **Phase 6** | **ALL EXIT CRITERIA MET** (was 2 blocking) |

### The clean run — 2026-09-21, fresh runtime, new video, recompiled brief

**The best state the project has been in.**

| | |
|---|---|
| Phase 4 exit criteria | **ALL MET** — `possible inventions: 0` |
| Phase 6 exit criteria | **ALL MET** |
| §74 full-pipeline self-check | **0 blocking, 0 warning** *(was 2 blocking)* |
| §82 Phase 7 self-check | **0 issues** |
| §77 test suite | green |
| score | `89`, 6 units, 100% coverage |

**Fix 10 produced exactly the signal it was built for.** Scoring units went
**4 → 7**, and the dimension breakdown is no longer uniformly THIN:

```
Hook              31%  100   2 unit(s)
Product presence  23%  100   1 unit(s)  THIN
Messaging         31%   50   2 unit(s)     <-- the brief's substance, now visible
Call to action    15%  100   1 unit(s)  THIN
```

**`Messaging 50%` is the whole point.** Half the brief's talking points were
covered, and before fix 10 that was invisible — the same video would have
reported 100. `literal wording only: 44 → with her own versions credited: 89`
shows the paraphrase credit doing its job on top.

Also working: the crux block and `WHAT SHE MADE` print before the score, the
model ladder never touched paid OpenAI, 16 verdicts credited in her own words
with the literal finding kept on each, and 0 undecidable alignments.

### RESOLVED (fix 12): the fuzzy match left the scoring path

**Decision: per-point coverage, made explicit and deterministic.**

One line deleted in §43. The `approved_talking_points` / `any_of` grouping is
gone; the `FROM_APPROVED_CLAIMS:<claim>` flag stays.

```python
if _src_claim:
    group, gmode = 'approved_talking_points', 'any_of'   # DELETED
    f.append(f'FROM_APPROVED_CLAIMS:{_src_claim[:48]}')  # kept
```

**The principle:** a fuzzy match is fine for *"which brief claim did this come
from"* — provenance, best-effort, harmless when it misses. It is **not** good
enough to decide *how many scoring units exist*. It now shapes only the report.

**Why per-point and not `any_of`:** per-point is **recoverable**. *"Did she
cover at least one?"* can be computed from individual verdicts whenever you
want; per-point coverage can never be recovered from a single collapsed unit.
Phase 8 exists to calibrate, so keep the signal that can still be aggregated
later. If it proves too harsh, the lever is **priority** (a weight, safe to
retune after labelling) — not grouping (a semantics change, which is not).

`BRIEF_STAGE_VERSION` → **1.16.0**.

### New report section: "Talking points covered"

`talking_point_coverage(result, compiled)` — one helper shared by the report
and §80, so the page and the console cannot disagree about the number.

The report gets a **Talking points covered** section between *What she made*
and *By dimension*: the ratio, then each point by name with the brief line it
came from — covered ones green-edged, missed ones amber. §80 prints the same:

```
TALKING POINTS: 2 of 3 covered -- what the brief asked her to communicate.
  not evidenced: Mention fewer split ends
```

Naming the misses is the point: *"add split ends and shine next time"* is
directly actionable in a way a percentage is not.

**It is honest about its own limits.** When the brief lists more approved
claims than became checkable requirements, the section says so — *"a floor, not
a census; the link back to a brief line is a best-effort match."* The flag can
miss; the score never depends on whether it does.

Priority deliberately left alone — to be decided from real data, not a guess.

### Superseded: the grouping was not deterministic

The arithmetic from this run:

```
22 requirements - 17 alternatives (2 groups) = 5 ungrouped
scoring units = 2 (groups) + 5 (ungrouped) = 7    ✓ matches the run
```

So **no `approved_talking_points` group existed in this compile** — the
claims-derived requirements stayed ungrouped and each became its own scoring
unit. That is per-point coverage, which is what "checked thoroughly" wants, and
it is why Messaging reads 50%.

But that is **not** what §43 intends. `normalize_requirements` groups a
requirement as `approved_talking_points` / `any_of` only when `_claim_backed()`
matches its `brief_span` (or text) to an approved claim. Here it did not match,
so the grouping never fired.

**The consequence: the same brief can score differently depending on whether
that fuzzy match happens to hit.** One compile collapses the talking points to
a single "cover at least one" unit; another scores them individually. Both are
defensible; silently alternating between them is not — and it is precisely the
kind of instability that makes a Phase 8 label meaningless.

**This needs a decision before labeling** (see §11): pick per-point coverage or
`any_of`, then make the code do that consistently rather than leaving it to a
string match.

### ⚠️ How `100 / APPROVED` read on the PREVIOUS run

**Three scoring units, every one of them marked THIN.** §73 says it plainly:
*"the score rests on 4 scoring unit(s) from 21 requirement(s) — thin: one bad
call moves the mean by ~33%."*

The brief is 3 choice groups covering 20 of 21 requirements. A `one_of` group
is **one decision**, so 21 requirements collapse to: *did she use a hook, a
creative concept, and a CTA?* She did all three → 100.

**And the brief's substance is not scored at all.** The
*"Key talking points + Product features"* section — 7 lines of USPs
(Ceramosides, shine and softness, fewer split ends, 27% hair-loss reduction) —
compiles to **zero requirements**. It becomes an *allowlist*, by deliberate
design:

> *"claims sections produce nothing here either; §40b turns them into an
> allowlist instead."* — `brief_units()`

So those 7 talking points are used only to **guard** figures (the one forbidden
rule: don't misstate a number), never to **ask** whether she mentioned them.
Nothing in the score checks whether she talked about the product's actual
benefits.

**DECIDED AND FIXED 2026-09-21 (fix 10): the talking points are now scored.**
*"The video must be checked thoroughly."*

A claims section now flows through the ordinary non-alternatives path, so its
lines become requirements instead of vanishing. Nothing is demanded verbatim —
substance credit still applies, so *"it made my hair shiny"* satisfies *"adds
shine and softness"*.

> **CORRECTION (same day).** I first said each talking point becomes its own
> scoring unit, giving per-point coverage ("3 of 7 = 43% of Messaging"). **That
> is wrong.** `normalize_requirements` (§43) *already* grouped any claim-backed
> requirement as `approved_talking_points` / `any_of`, with a deliberate
> comment:
>
> > *"a talking point, not an obligation. Group them as any_of: the video must
> > cover at least one, not every single one."*
>
> That machinery could never fire while `brief_units` skipped claims sections —
> no talking-point requirement was ever emitted for it to group. Fix 10 feeds
> it, so the talking points arrive as **ONE `any_of` scoring unit**, not seven.
> The notebook had already chosen the "middle option" I proposed as if it were
> new; I had simply not found it.
>
> **Net effect: the score gains one unit that asks "did she cover at least one
> of the brief's talking points?"** — not a coverage percentage. Whether that
> is thorough enough is an open product decision (see below).

The allowlist is unchanged: `extract_approved_claims()` reads
`parse_brief_sections()` on its own pass, so the figure-fidelity rule still
works exactly as before. Both readings of a claims section are wanted.

Verified on the real brief shape:

```
units by kind: {'alternatives': 3, 'claims': 4}
CLAIMS units -> ungrouped, each its OWN scoring unit:
   group=None  mode=all_of   Uses cellular aging science with ingredients…
   group=None  mode=all_of   Adds shine and softness to hair.
   group=None  mode=all_of   Supports hair and lowers breakage.
   group=None  mode=all_of   Reduce hair loss by 27% and double the number…
```

**A second site had to move with it (10b).** `decomposition_health()` counts
*"lines that could BECOME a requirement"* to detect a 3-line brief exploding
into 12. Claims lines can become one now, so they belong in that denominator —
leaving them out would have reported the new talking-point requirements as
over-decomposition. Caught by a deliberately loose cross-check that the
narrower unit test missed.

Dimension weighting keeps it balanced on its own: seven messaging requirements
average among themselves, and Messaging then contributes its own share, so a
long talking-points list cannot swamp the hook or the CTA.

`BRIEF_STAGE_VERSION` → **1.15.0**. ⚠️ **A recompile is required** — set
`RECOMPILE_BRIEF = True`, since an approved compile is otherwise reused
verbatim.

**Known fidelity note:** on the test brief, 5 talking-point lines produced 4
units — one was dropped by the descriptive-example / heading filters. Worth
watching in the §48 output; if a real talking point goes missing, that filter
is the place to look.

<details><summary>The original decision, for the record</summary>

**This was a product decision, not a bug** — and it was the user's call:

- *As designed:* a claims list is "what she MAY accurately say", not "what she
  MUST say". A 7-point USP list is not a demand to recite all 7.
- *Against the product rule* (*"she has to talk about similar stuff as
  mentioned in the content brief"*): the talking points **are** that stuff, and
  a video scoring 100 without mentioning any of them overstates what was
  verified.

A middle option, if wanted: compile a claims section into **one** grouped
`any_of` requirement — "mention at least one of the approved talking points" —
so coverage is scored without demanding recitation. That would add a fourth
scoring unit and make the 100 mean more.

*(Not taken. `any_of` collapses to a single unit in `_resolve_groups`, the same
as `one_of`, so it would have added only one unit. Ungrouped requirements give
per-point coverage, which is what "checked thoroughly" actually needs.)*

</details>

### The creative angle is now a headline section (2026-09-21)

*"We also need to categorise her content angle depending on what she is
presenting in the video and how."*

It was already computed (§69b, `CREATIVE_ANGLES` — a closed enum in code, no
model-invented labels) and it already ran — `angle: problem_solution`. It was
just **buried**: a card inside `Modules`, below the evidence timeline.

It is now its own section directly under *"Does the crux align?"*, because
those two are the same question asked twice and belong in that order: **what is
this video, then is it the right one.** §80 prints it too, as `WHAT SHE MADE`.

The section carries: the angle, **what that angle means in words** (the reader
should not have to know the taxonomy), her summary, the hook type and strength
with the caveat that *hook strength is a separate reading from whether the hook
requirement was met*, the nearest concept in the brief, and the evidence ids
behind it. The duplicate card in `Modules` was removed.

The eleven angles: `social_proof · personal_transformation ·
routine_integration · problem_solution · education · comparison ·
demonstration · testimonial_response · day_in_life · humour · other`.

It describes, it never grades — a creator may take an angle the brief never
listed and still satisfy every requirement.

### The open question that led there: is 43 / REJECTED right?

The score came back **43, 100% coverage, REJECTED**, with 16 requirements
failing literally while aligning with the brief's intent.

This is the honest consequence of fix 4, and it is the safe direction — but it
may be **systematically pessimistic for briefs of this shape**. This brief is
almost entirely `alternatives`: "Creative concepts", "Hook Concepts", "CTA
Ideas" are lists of example scripts. A creator paraphrasing them is doing
exactly what was asked, and literal matching will fail her every time.

Both readings are defensible and **neither can be settled without labels**:

- *Before fix 4*, alignment silently promoted those to PASS — inflating the
  score on the word of one uncross-checked model call, which is how a video
  with no CTA nearly scored a pass.
- *After fix 4*, they read FAIL with the alignment shown beside them — which
  may under-credit legitimate paraphrase.

`plan.md` is explicit that a false-positive PASS is the most damaging error
class, so failing toward FAIL is correct **until Phase 8 measures whether
alignment predicts a human judgement**. That experiment is only possible now
that the two are reported separately. Carry it into Phase 8.

### What the report shows now

Literal status and alignment sit **side by side**, never blended:

- `literal: no · alignment: strong (not scored)` — the creator may have made her
  own version; reported for your judgement, does not move the score
- `literal: no · alignment: strong (unreliable)` — judged against an intent that
  does not describe its own options, so it is **not evidence of anything**
- `group intent names no subject` · `invented time window` · `disputed time
  window` — upstream diagnostics, styled as warnings the reader should not skim

---

## 9. Current state

### Test status (verified 2026-09-21, after the §8b fixes)

- **448 checks green** across the 10 local suites
- **110/110** in §77 (runs inside `test_p7_integration` locally, and on Colab)
- **16/16** deliverable checks; every cell of the notebook parses; no mojibake
- Phases 1–6 self-check (§74): **0 blocking, 1 warning** *(pre-fix figure)*
- Phase 7 self-check (§82): informational only

**448 checks total.** The only failure anywhere is the known open exit
criterion below.

### Phase 7 exit criteria — 13 pass, 1 fail, 2 need a human

Passing: score reproducible by hand · no model writes a number ·
`PASS_FROM_ABSENCE` held out · dimensions normalise over covered only · critical
FAIL cannot average into APPROVED · report is one self-contained file ·
timestamps seek the player · every marker carries its evidence ids · renders
without plotly · fetches nothing · identical output on re-score · contradictions
fire on a genuinely off-brief pair · test suite green

**FAILING — the one real gap:**

> `§75b answered: some quantity separates own brief from foreign`
> *no controls yet (1 native, 0 control pairings)*

Fix: set `RUN_CONTROL_AUDITS = True` in [s75b_discriminate.py:53](Phase 7/cells/s75b_discriminate.py#L53)
and re-run. **This costs real L3 model calls** — that is why it is off by
default. `MAX_CONTROL_AUDITS = 6` caps the spend per run.

**Need a human, cannot be automated:**
- a person who has not seen the video can act on the report
  *(send the HTML to someone and ask them what to change)*
- reviewing a report is faster than watching the video *(time both, same video)*

### The honest limitation

The band thresholds are **explicit placeholders**:

```python
BAND_THRESHOLDS_PLACEHOLDER = (
    ('APPROVED',             85.0),
    ('NEEDS_MINOR_REVISION', 70.0),
    ('NEEDS_MAJOR_REVISION', 50.0),
    ('REJECTED',              0.0),
)
```

**Nothing has established that 85 is the line.** The constant is named
`_PLACEHOLDER` on purpose and the report discloses it to the reader.

Every criterion green means **the machinery is sound and every claim is
traceable**. It does *not* mean the verdicts are right. That gap closes with
**labels, not more code** — which is Phase 8, and `plan.md` is explicit that it
must not be skipped or deferred.

---

## 10. Next steps

### NOW — run the whole notebook on Colab

The notebook is current and fully verified as of 2026-09-21. Upload
[Phase 7/phases_1_to_7_gemini_vision.ipynb](Phase 7/phases_1_to_7_gemini_vision.ipynb)
and **run it end to end.**

**Before you start**, delete the old test pollution — §74b counts it as a real
video and will report a phantom:

```python
!rm -rf /content/work/artifacts/test_vh
```

**Expect real model spend.** `BRIEF` and `VERDICT` both bumped, so the brief
recompiles and the verdicts re-evaluate. `SCORE` bumped too, so §80 recomputes
instead of cache-hitting.

**§72 is the long cell.** It runs L3 adjudication over every requirement plus
the hook, claims, angle and standing calls. With fix 8 it leads with the model
that actually serves, so expect **roughly 1–2 minutes**, not five. If you again
see repeated `gemini-flash-latest unusable`, the free-tier quota is exhausted
for the day — either wait, or set `allow_paid_fallback=True` to let OpenAI
`gpt-4.1-mini` take it (that is billable).

**What to look for in the output — this run is a test of the §8b fixes:**

1. **§45 (brief compile)** — readable labels. No `Deliver Call Action I m`, no
   duplicates among the CTA options or the twelve hooks. Possibly a
   `WARN … group intent(s) name a POSITION, not a thing to look for`.
2. **Any `WINDOW_UNSUPPORTED_BY_BRIEF` / `WINDOW_DISAGREES_WITH_BRIEF`** flags —
   these should fire on the CTA requirements if the model again invents a window.
3. **§73 hand-off** — `no verdict was promoted out of its literal status` must
   pass, and any alignment-bearing verdict must still read FAIL.
4. **§80 must NOT print `SCORE CACHE HIT`** on the first run. If it does, the
   version bump did not reach the kernel.
5. **The CTA requirement must now read FAIL**, with
   `literal: no · alignment: strong` beside it — *not* PASS. That is the whole
   point of fix 4.
6. **§77** — 110/110, and `artifacts left in work/artifacts: none`.

Then paste the output back and we decide what is next from what it actually
says, rather than from what we expect it to say.

### Then — close the last mechanical exit criterion

Set `RUN_CONTROL_AUDITS = True` in
[s75b_discriminate.py:53](Phase 7/cells/s75b_discriminate.py#L53), re-run the
patcher-free rebuild, and run §75b. Costs real L3 calls, capped at 6.

It answers, without labels, whether *any* quantity separates a video's own brief
from a foreign one. If none does, that is a genuine finding about the evidence —
not a bug — and it should change what the report leads with.

**What it actually needs: a SECOND compiled brief. Nothing else.** It is a
paired design — it re-audits each video against a *foreign* brief already on
disk, so each video is its own control, and it says so explicitly: *"You are not
being asked to judge anything."* The run showed `1 native, 0 control pairing(s)`
because only one brief has been compiled. Give it two briefs and it runs.

This is worth knowing before planning Phase 8: **§75b is unblocked by corpus,
not by labeling.**

---

## 11. What is left before Phase 8

Phase 8 is the benchmark dataset, human review UI, and metrics harness. It is
what turns "the machinery is sound" into "the verdicts are right." `plan.md` is
explicit that it must not be skipped or deferred.

**Blocking — must be done first:**

| | what | status |
|---|---|---|
| 1 | **A clean full-notebook run** with all fixes | ✅ **DONE** 2026-09-21 — Phase 6 ALL EXIT CRITERIA MET, Phase 7 13/1/2 |
| 2 | ~~`any_of` or per-point coverage?~~ | ✅ **RESOLVED (fix 12)** — per-point, deterministic. The fuzzy match now shapes only the report, never the unit count. |
| 3 | **§75b control audits** (`RUN_CONTROL_AUDITS = True`) | ⬜ the last mechanical exit criterion; also tells you whether alignment is worth labelling |
| 4 | **Thin-score honesty** | ⬜ every dimension on the last run was THIN (1 unit each). Phase 8 should label enough videos that a 3-unit score is not the norm. |

**The real gate nobody writes down: the semantics must stop moving.**

Phase 8 labels verdicts produced by *this* code. Every change to what a verdict
MEANS — substance credit, the UNCERTAIN abstention, claims-as-requirements —
partially invalidates labels collected before it. Four such changes landed on
2026-09-21 alone. **Labeling should not start until the product rules are
frozen**, or the dataset ages out from under you while you build it.

**Collection is the long pole, not code.** Phase 8 wants **40 videos**
stratified ~22 normal / ~18 hard (fast cuts, occluded product, tiny text, poor
lighting, speech/visual disagreement, no hook, CTA only in text, silent,
music-heavy, paraphrase-not-literal…). `work/inbox` currently holds **7 files**.
Hard cases are worth ~5× normal for finding bugs, so they need deliberate
sourcing rather than whatever arrives.

**Needs a human — cannot be automated, and Phase 8 assumes both:**

| | what | how |
|---|---|---|
| 4 | a person who has not seen the video can act on the report | send the HTML to someone; ask what they would change |
| 5 | reviewing a report is faster than watching the video | time both, on the same video |

These are the actual product claims. Nothing in the notebook can establish them,
and Phase 8's review UI is built on the assumption that they hold.

**Then Phase 8 proper unblocks the two things nothing here can settle:**

- whether the band thresholds (85 / 70 / 50) are the right lines
- whether the verdicts underneath the score are correct

Both need labels, not more code.

**Carried forward into Phase 8** — worth labelling explicitly when the dataset
is built:

- Does `SUBSTANCE_ALIGNMENT` predict anything once it is no longer allowed to
  promote? Now that literal and alignment are reported separately, Phase 8 can
  measure each against a human label independently — which is the experiment
  that was impossible while they were blended.
- Does `GROUP_INTENT_SUBJECT_FREE` correlate with wrong verdicts? If it does,
  it belongs as a gate, not just a warning tag.

---

## 11b. Why no model ever writes a score — asked and answered 2026-09-21

The question comes up naturally: *"can't Gemini generate the scores and validate
things in Phase 7?"* The answer is **no for numbers, yes for a bounded
second-opinion role** — and the reasoning is not dogma, it is measurement.

**Why a model may not produce the score:**

1. **There is nothing to check it against.** The project starts with no labeled
   data (§1). A model-produced number cannot be verified, reproduced, or
   argued with. Arithmetic over verdicts can be recomputed by hand — §81 does
   exactly that on every run: *"by hand 43.0-43.0, §76 says 43.0-43.0"*.
2. **Determinism is an exit criterion.** *"the same verdict artifact scored
   twice gives identical output — 4636179 vs 4636179 chars"*. A sampled model
   cannot promise that. Phase 6 measured L3 sampling moving the mean **0.34 on
   identical inputs**.
3. **Traceability breaks.** Every number traces to a requirement, every
   requirement to an evidence id. A model's number traces to nothing, so
   nothing on the page could be defended to a brand.
4. **It has already been tried, twice, and failed both times.** The alignment
   mean did not discriminate (0.72 on-brief vs 0.68 off-brief). The substance
   promotion — one model call, no cross-check — turned a video with no CTA into
   a PASS. Both were cases of trusting a model number.

**Where a model is already used, correctly:** §78 recommendations — the only
model call in Phase 7. It writes *words*, and a recommendation containing a
digit is rejected outright.

**The extension that would be sound**, and fits the existing architecture: a
model as an **adversarial validator**, never a scorer. Ask a second model to
challenge the verdicts and the report — "does the evidence cited actually
support this verdict?" — and surface its disagreements as **flags**, not as
score changes. That is precisely the shape of `standing` (a whole-video second
opinion, reported and never averaged) and of the contradiction checks. It obeys
design rule 10: two independent things must agree, or the system abstains.

**Worth building after Phase 8**, not before: the validator's disagreements are
only worth acting on once labels show they correlate with real errors.
Otherwise it is one more unchecked model opinion — the exact thing that caused
the bug this session fixed.

---

## 11c. BATCH MODE — `phases_1_to_7_BATCH.ipynb`

A generated copy of the single-video notebook that runs **many videos against
one brief**. Built by
[Phase 7/verify/build_batch_notebook.py](Phase 7/verify/build_batch_notebook.py),
never hand-edited — so it can be regenerated the moment the real notebook
changes, and cannot silently drift behind it.

**It differs from the original in exactly these places:**

| § | what |
|---|---|
| **§0.4** | upload a `.zip` of videos — inserted right after §0.3, because everything downstream works from `DIRS['inbox']` and the upload has to land first |
| **§48** | `BRIEF_SOURCE` repointed at the batch Google Doc |
| **Option A** | `UPLOAD = False` — the single-video uploader would otherwise prompt a **second** time and then audit only that one file |
| **§13 folder** | `preprocess_folder()` globs every suffix §0.4 accepts, in both cases |
| **§13 folder** | a **reconciliation** block: inbox count vs Phase 1 manifests, naming anything that did not survive |
| **§90 / §91** | the batch loop, then the results table and a zip of every report |

| **§30.5** | **the vision pass for every video** — see below |

### The bug that would have ruined the batch

`run_vision_all()` was **defined in the notebook and never called.** Phase 3 ran
only through §30.3's `run_vision_stage(TARGET, ...)` — one video. A ten-video
batch would have produced ten reports, **nine of them with no visual evidence
at all**: `build_evidence` reports vision as not-run, every visual requirement
collapses to `UNCERTAIN`, and the reports come out confidently thin with
nothing saying why.

The function was already built for exactly this — it loads the model **once**,
loops, and skips any video whose `visual__*.json` already matches the current
stage key. It simply had no call site. **§30.5 is that call site**, inserted
right after the definition and before §35 declares "Phase 3 complete".

It reconciles too: any video that ends up without a visual artifact is named,
with a warning that its report will be missing everything the camera showed.

### A second bug in §90: the wrong video list

The batch loop used `discover_videos(unique=False)`, copied without thought
from the single-video `TARGET` selection. `discover_videos()`'s own docstring
names that exact mistake:

> *"Without this, **the batch runner would process the same video five times**
> and the hand-off could pick a thinned variant."*

§17's sampler ablation writes extra manifests for one video under different
plan hashes (16-frame, 32-frame, …), and `unique=False` returns every one.
Worse here: **§30.5 ran the vision pass over the UNIQUE list**, so a thinned
variant has no visual artifact at all — the batch would have emitted a second,
blind report for a video that already had a good one.

§90 now uses `discover_videos()`, the same list §30.5 processed. `check_batch.py`
asserts both use it, and that §90 never reverts to `unique=False` (scoped to
that cell — a pre-existing diagnostic elsewhere legitimately wants every plan).

### Stage coverage, verified

| stage | covers every video? | how |
|---|---|---|
| Phase 1 decode/frames | yes | `preprocess_folder(inbox)` @82 |
| Phase 2 **ASR** | yes | `process_all` — loads Whisper **once**, loops all, frees VRAM |
| Phase 2 **OCR** | yes | `process_all` — loads the engine **once**, loops all |
| Phase 3 vision | yes | `run_vision_all` @143 — **added**; model loaded once |
| Phase 5 evidence | yes | §90 loop |
| Phase 6 audit | yes | §90 loop |
| Phase 7 score + report | yes | §90 loop |

Phase 2 was already correct and well built: one model load per stage, a loop,
and per-video failures caught and printed rather than fatal. Its call site even
refreshes first — *"the Phase 1 batch above may have added videos"*.

### Fix 13 — L2 crashed the moment it actually matched something

```
AttributeError: 'dict' object has no attribute 'id'
  evaluate_l2 → evidence_ids=[c.id for c in top]
```

`l2_similarities()` returns `[(candidate, cosine)]` where a candidate is a
**dict** wrapping a `'record'`. The function knows this — two lines above it
writes `rec = best['record']`, and `_conjunctive_shortfall(rd, top)` is
correctly handed those dicts. Only the `evidence_ids` expression forgot, and
reached for `.id` on the wrapper instead of the record inside it. Both call
sites (PASS and PARTIAL) were wrong the same way.

**Why it survived this long:** the bug lives in the branch taken only when the
best cosine clears `high_threshold_PLACEHOLDER` — L2 deciding a requirement
outright. Until claims sections began producing requirements (fix 10), almost
everything either resolved at L1 or escalated past L2 to L3, so that branch was
never taken on real data. **Making the brief's substance scoreable is what
finally sent a requirement down it.**

Verified by executing the real `evaluate_l2` on both branches: PASS and PARTIAL
now return `['ev_a','ev_b','ev_c']` — the top-3 record ids — instead of raising.

Cell **#121 (§66)** in the single-video notebook, **#123** in the batch copy.
No stage version moves: L2 previously crashed rather than producing output, so
there is no cached artifact shaped the old way.

### Which cells are single-video BY DESIGN

Easy to misread as "the batch only ran one video". These are **reporting**
cells scoped to `TARGET`, and they run *before* the all-videos pass:

| cell | what | scope |
|---|---|---|
| #48 (abs 78) | **Phase 2 exit criteria** | TARGET — its own checklist says *"run all of the above across 20 videos, not just this one"* |
| #57 §13.5, #144–145 | Phase 1 / Phase 3 single-video summaries | TARGET |
| §61, §72, §80 | the single-video driver chain | TARGET — the smoke test |

The **processing** is multi-video; those **summaries** are not. To make that
unmistakable, every multi-video stage now ends with a loud per-video
reconciliation:

| stage | cell | says |
|---|---|---|
| Phase 1 | #50 | inbox count vs manifests, naming anything that failed to decode |
| Phase 2 | #51 | ASR + OCR per video with word counts, naming any failure |
| Phase 3 | #85 | names any video left with no visual evidence |

Phase 2's reconciliation deliberately does **not** treat 0 words as a failure —
a music-only or silent video has no speech, Phase 5 records that as `absent`
rather than `degraded`, and flagging it would train you to ignore the line.

`Phase 7/verify/check_batch.py` asserts all of this on every rebuild, including
the ordering `Phase 1 → 2 → 3 → batch loop`.

**The ordering that makes it correct** (verified, and non-obvious):
`discover_videos()` reads **manifests**, not the inbox — a video only becomes
visible once Phase 1 has written one. The chain is
`preprocess_folder(inbox)` **@82** → `process_all` **@84** → `run_vision_all`
→ batch loop **@256**. Phase 1 over the whole folder therefore happens before
anything that enumerates videos. Running top-to-bottom is all that is required.

**Two silent-drop paths closed:**
- `preprocess_folder` defaulted to `('*.mp4','*.mov','*.webm','*.mkv')` while
  §0.4 also accepts `.m4v` and `.avi` — and **glob is case-sensitive on
  Linux**, so `clip.MOV` would have sat in the inbox, never got a manifest,
  never reached `discover_videos()`, and been missing from the batch with
  nothing said. §0.4 now lowercases the suffix on extraction *and* the glob
  covers every suffix in both cases.
- The reconciliation block then proves it: *"10 video(s) in the inbox, 10 with
  a Phase 1 manifest"*, or it names the ones that failed and why to look.

**Why it is cheap:** the brief is cached by its own hash and has nothing to do
with any video, so it compiles **once** for ten videos. Phases 1–3 were already
multi-video (`process_all`, `run_vision_all`). Every stage is content-addressed,
so re-running §90 after adding two more videos pays only for those two.

**Robustness built in:**
- one video failing is caught, recorded and listed at the end — it never costs
  the other nine
- `MAX_VIDEOS = 25` so a mis-clicked 50-video zip cannot spend the afternoon
- nested folders flattened; `__MACOSX` and `._name` resource forks skipped
  (ffprobe chokes on them with a confusing error)
- `CLEAR_INBOX_FIRST = False` by default — a batch run that silently deletes
  the previous run's videos is a bad surprise
- `import time` explicitly: it is **not** imported at module level anywhere in
  Phases 0–7, so a batch cell calling `time.time()` on a fresh kernel would
  have died with `NameError`

The single-video driver cells are left in place deliberately: they run on the
first discovered video and act as a smoke test. If §80 produces a report, §90
will too — and the work is reused, not repeated.

**Verified** (2026-09-21):

- 258 cells, every one parses, outputs cleared, 767 section signs, no mojibake
- **deep cross-check 31/31** on the batch notebook itself — the same
  fresh-kernel name-resolution pass the real notebook gets. `crosscheck_*.py`
  now take an optional notebook path so the generated copy gets identical
  scrutiny.
- **cell-by-cell diff against the original**: exactly 4 inserted (§0.4, the
  batch markdown, §90, §91), exactly 1 changed (§48, the single `BRIEF_SOURCE`
  line), **0 deleted**. Nothing else moved.
- zip extractor smoke-tested against nested folders, `__MACOSX`, `._` resource
  forks, non-video files, mixed-case suffixes, and a repeat run (idempotent)
- every stage signature the batch loop calls checked against its definition
- the single-video notebook is untouched — its full suite still passes

`Phase 7/verify/check_batch.py` is the standing batch-readiness check —
**19/19**, including that exactly **one** cell can actually prompt for an
upload (reachability, not a string match: the disabled one still contains
`files.upload()` inside `if UPLOAD:` with `UPLOAD = False`), and that exactly
one **active** `BRIEF_SOURCE` assignment exists and is the batch doc (the old
id survives only inside a named-brief registry dict).

`RECOMPILE_BRIEF` deliberately stays `False`: the approved-compile reuse is
keyed on `sha256_text(BRIEF_TEXT)`, so a different brief compiles fresh anyway
— and once the batch brief IS approved, re-runs must reuse it. Comparing videos
is only meaningful against one compile.

**Two real bugs the cross-check caught before it ever ran:**

1. `time` is **not imported at module level** anywhere in Phases 0–7 — only
   inside functions that import it themselves. `time.time()` in §90 would have
   died with `NameError` on a fresh kernel.
2. `write_report()` returns **both** `html_path` (the file) and `html` (the
   whole ~4.5 MB document as a string). §91 stored `html` and then called
   `Path()` on it — the zip step would have broken on every video. Now stores
   `html_path`, and `json_path` alongside it.

The shallow cross-check reports 2 expected failures on the batch notebook
("Phase 1-6 byte-identical", "nothing spliced into Phase 1-6"). Those checks
exist for the single-video build; §0.4 and the §48 repoint are exactly the
intentional differences, and the cell-by-cell diff above is what verifies them.

**This also unblocks §75b.** A second compiled brief is all the control audits
need, and the batch brief is that second brief. See §10.

---

## 11d. The Biostime batch — fixes 13–16, and where it landed (2026-09-22)

Seven videos against the Biostime brief, run repeatedly while the compile was
corrected. **The brief itself is in `Downloads/Biostime - Content Brief.docx`**
— reading it answered in one pass what three compiles could not.

**Fix 13** — `evaluate_l2` crashed (`'dict' object has no attribute 'id'`).
Candidates are dicts wrapping a record; only `evidence_ids` forgot. It had
never fired before because nothing reached L2's decide-branch until claims
became requirements.

**Fix 14** — a structure guard that stripped model-invented `one_of` groups.
**Then corrected**: `requirements` is the FALLBACK kind, so an unrecognised
heading was being treated as authoritative. A default is not evidence; only a
heading that positively matched a cue may overrule the model.

**Fix 15** — the real bug behind fix 14. `"Call to Actions"` and `"Back to
School Campaign"` matched **no cue in any list**, so their kind came from
fallback and the model grouped them differently on every compile (4 groups/18,
then 2/12, then 3/18, from identical input). Added `call to action`, `CTA`,
`campaign`, `theme` to the alternatives cues.

**Fix 16** — the one that mattered. The 8-line *Key Talking Points/Features*
section produced **zero** requirements on every run: the model emitted them
~1 run in 3 and `BRIEF_KEEP_THRESHOLD = 0.5` dropped them as unstable. So the
score measured *form* — did she use an approved hook, concept and CTA — and
never whether she said anything about the product. Five of seven videos scored
APPROVED, two at 86 and 93 from a **literal score of 0.0**.

`extract_approved_claims()` returns exactly 8, stably, on every run. So the
claims are now turned into requirements **deterministically from the parsed
document**, ungrouped, one scoring unit each.

### The trap inside fix 16, and the notebook's own warning

First attempt passed the claim's keywords as `match_hints`. Every talking point
then PASSED with alignment `exact` on a single-word fuzzy hit:

| talking point | "evidence" |
|---|---|
| Gentle & Non-Habit-Forming (melatonin-**free**) | OCR `"MELATONIN"` |
| Allergen-Friendly | OCR `"Dietary Supplement"` |
| Clean & Safe Formula | the word `added` |
| Delicious Fruity Taste | `"Fruity Bites"` — the product name |

The notebook already documents this exact failure: *"twelve hook options each
matched the word 'hair' at 100, all twelve returned PASS"*. **Synthesised claim
requirements now carry NO match hints**, so `l1_phrase` returns `None` and the
question escalates to the layer that judges meaning.

After that fix the same report reads properly — passes quote what she said
(*"she stated they are melatonin free calm and sleep gummies"*), fails name
what is missing, and one abstains honestly.

### What the last run means, and why UNCERTAIN is high

`11–12 scoring units`, `talking points N/8` real, scores 0–77 with three
distinct outcomes. Two videos show `0/8` with 5–7 UNCERTAIN — **not a bug**:

```python
if v.status == 'FAIL' and not _fail_allowed(rd, health):   # -> UNCERTAIN
```

The talking points are `speech_or_text`, and for a **disjunctive** mode
`can_fail_on` requires **both** speech and OCR healthy. To say *"she never
mentioned allergen-friendly"* you must have read both channels — if OCR is
degraded she may have put it on screen. L3 said FAIL, the gate refused to let
it assert absence. `plan.md` §6.2, working as written.

**So those two videos have a degraded speech or OCR channel.** The blocker is
evidence quality, not scoring — a Phase 9 question. Confirm per video with §72's
`CAN A FAIL BE ASSERTED AT ALL?` line.

`speech_or_text` is the right mode (she may say it *or* show it) even though it
is the most demanding for asserting absence. The alternative, `speech_only`,
would decide more often and be wrong more often.

### Still open, unchanged

- ~~**Stale visual artifacts** on every video — `none of the N keys… using the
  newest of 1`.~~ **RESOLVED by fix 22 (§11e).** It was a reader bug, not a
  stale artifact, and the `force=True` re-run it called for is not needed.
- **Band thresholds are placeholders** — only the *ordering* of these scores is
  meaningful, not `REJECTED` vs `NEEDS_MAJOR_REVISION`.

---

## 11e. Fixes 17–21 — the silent throttle (2026-09-22)

Fixes 17 and 18 came from a user correction; 19 from reading a report; 20 and 21
from the user's own question, *"we are hitting the OOM ladder which should not be
the case… what do you think is happening."* They were right to ask, and the
answer was worse than an OOM.

| # | What it fixes | Cell (single / BATCH) |
|---|---|---|
| 17a/b | `standing` and `angle` judge a SILENT video from text + visuals, not speech alone — a music-only video can now be scored at all | §68 region |
| 18/18b | §71's angle test follows the new gate; an abstention KEEPS the flags already recorded | §71 |
| 19 | **L3: an absence is a FAIL, not an UNCERTAIN.** The single most impactful change of the batch — "she never mentions it" was abstaining instead of failing | §67 |
| 20 | Hosted vision is not limited by local VRAM | **#71 / #72** |
| 21 | A DEGRADED cached visual is not a valid hit on a hosted run | **#71 / #72** (same cell) |

### Fix 20 — a GPU the model never touches was cutting the evidence

`run_vision_stage` pre-filtered the frame-budget ladder by local free VRAM:

```python
_afford = vision_token_budget(free_vram_gb(), cfg.vision)
_viable = [r for r in ladder if estimate_vision_tokens(...) <= _afford]
ladder = _viable          # rungs skipped UNATTEMPTED
```

and `vision_token_budget` floors at 2000 tokens. On Colab — no GPU, or Whisper /
OCR / the BGE embedder holding it — `free_gb` collapses, the budget lands on that
floor, and every worthwhile rung is declared unaffordable. **Nothing ever OOM'd.
The rungs were skipped without being attempted.** A 48-frame video was described
at 12 frames.

The system's own contract already said this must not happen —
`make_vision_backend`'s docstring: *"the hosted path has no VRAM ceiling and
therefore never degrades the frame budget."* The filter simply never asked which
provider was running. **The frames are the evidence; a quarter of the frames is a
quarter of what the audit can see**, and it degraded silently on every video of
every batch run to date.

Fix: a `_SkipAffordability` sentinel, caught by the existing bare `except` that
already falls through to the full ladder on a bad reading — one exit, not two.
The OOM ladder itself STAYS: a hosted backend never raises CUDA OOM, so it runs
the top rung and stops.

### Fix 21 — stopping the throttle does not undo it

Fix 20 alone would have changed nothing anyone could see. The cache scan walks
**every** rung and returns the first artifact it finds, so the next run would
serve the 12-frame result straight back. *A fix that only applies to videos you
have never run is not a fix; it is a note about the future.*

The rule is narrow and comes from the backend's own physics: **a hosted backend
never OOMs, so a DEGRADED hosted artifact cannot have come from an OOM** — it
came from the affordability filter, which is the bug. Ignore it and re-run.
On a LOCAL provider nothing changes: there the degradation was real, and refusing
the hit would mean re-OOMing on every run — the exact waste the scan prevents.

The predicate is exact rather than a guess, because this notebook's
`make_vision_backend` refuses to fall back to Qwen ("NO SILENT FALL BACK"), so
`provider != 'local'` really does mean hosted. Its second clause mirrors, line
for line, how `backend` is chosen further down, so the two cannot disagree:

```python
_p3_local = (getattr(cfg.vision, 'provider', 'local') == 'local'
             or not callable(globals().get('make_vision_backend')))
```

Verified by simulation on the built notebook — all seven cases:

| provider | cached at | result |
|---|---|---|
| gemini | 12 / 24 frames | **ignored, re-runs at 48** |
| gemini | 48 frames | instant CACHE HIT (§30.4's contract survives) |
| local | 12 / 48 frames | unchanged |
| local-only notebook (no `make_vision_backend`) | 12 frames | unchanged |
| any, `force=True` | — | unchanged |

**No `VLM_STAGE_VERSION` bump is needed, and that is deliberate.** The rung's
`max_frames`/`max_pixels` are already inside the visual cache key, so the
restored top rung is a *different key* with no artifact behind it and regenerates
naturally — while any correct full-budget artifact stays valid. Bumping would
have thrown those away for nothing.

**Cost:** re-running vision at 4× the frames on every already-processed video.
Worth it — every visual finding to date was made on a quarter of the evidence.

### The patcher bug found on the way (fixes 4 and 6)

Applying fix 21 made the patcher die on **fix 4**, which had been applied
successfully weeks earlier. Its idempotency marker was `_SUBSTANCE_ALIGNMENT` —
a string the fix **never emits**. The constant it writes is `_SUBSTANCE_STATUS`;
the flag is `SUBSTANCE_ALIGNMENT:`. Fix 6 had the same defect
(`'no verdict was promoted out of its literal status'` — text fix 6 *deleted*).

So both reported themselves as pending forever, and the first run *after* the one
that applied them died, because by then the old anchor was gone too. Same family
as the `'1.13.0'` collision in §8b, from the opposite direction: **that marker was
too loose, these matched nothing at all.**

The durable fix is a post-condition, not two corrected strings. `patch()` and
`patch_all()` now record every `(name, marker)` pair, and `main()` asserts every
marker is present in the result **before writing**:

```
MARKER DOES NOT HOLD AFTER APPLYING -- notebook NOT written
```

A marker is a claim — *"if this string is here, the fix is in."* Nothing checked
the claim. Now the patcher cannot report success it can't prove, and a
half-edited notebook is never written to disk.

### Fix 22 — the warning was never about a stale artifact

Found mid-run on 2026-09-22, from output the user pasted. §30.5 printed a table
of **7 videos, all `OK`, 4–11 events each** and then, in the same breath:

```
  WARNING: 7 video(s) have NO visual evidence.
```

Two readers rebuild the visual cache key to decide which files count. The
writer files under:

```python
{'vision': asdict(c), 'prompt': PROMPT_VERSION, 'vlm': _planned_vlm}
```

`'vlm'` — the resolved model — was added in **VLM 1.11.0** so a Gemini artifact
could never collide with a Qwen one. **Neither reader was ever told.**

1. **`_visual_keys`** (Phase 5/7) omitted `'vlm'`, so all six rung keys were
   wrong and the resolver fell through to its newest-file fallback **on every
   video of every run** — the `none of the 6 key(s)… using the newest of 1`
   warning, which I had recorded as a stale artifact. It never was. *The
   artifact was current; the reader was wrong.*
2. **§30.5's reconciliation** omitted `'vlm'` **and** keyed on the unresolved
   `P3.vision` rather than the per-video resolved budget. It was structurally
   incapable of passing, and reported "NO visual evidence" for every video,
   always, contradicting the status column directly above it.

Proven by executing both key builders on a synthetic 84 s manifest:

```
rung 0..5: writer == reader  (6/6)
OLD reader (no vlm) overlap with writer: 0 of 6
```

Zero of six — exactly the message on screen.

**No stage version bump, deliberately:** no artifact changes, only which files a
reader recognises. Bumping would invalidate the very artifacts this teaches it
to find.

§30.5 no longer rebuilds a key at all — it cannot, since `expected_stage_keys`
is Phase 5's and isn't defined that early. It now asks only *"did the stage
produce evidence"* (artifact directory + status column). Whether that evidence
matches the config is a different question, belongs to the Phase 5 resolver, and
§91 already reports it per row.

**What this cost:** nothing in any report — with one artifact per video the
fallback always picked the right file. What was lost is the *guarantee*, which
is the entire point of content-addressing. And `visual_stale` was true on every
row, so the one signal that would announce a genuinely mismatched artifact was
saturated and could not warn about anything. **This also retires the standing
"re-run §30.5 with `force=True` before Phase 8 labelling" advice** — provenance
was never broken.

A new `crosscheck_deep` section **J** executes both key builders and compares
the hashes. No static check could see this: both sides parse fine and neither
mentions the other.

### Fix 23 — unranked retrieval is a time filter wearing retrieval's clothes

**The most serious bug found so far, and the user found it by watching the
video:** *"it says she didn't say delicious fruity taste while I watched the
video she clearly says it has a fruity taste."*

She does. Phase 5 captured it perfectly:

```
ev_e188a6d2b7  speech  0:16
"passion flower my kids love the fruity taste they just call them
 their night night gummies"
```

The verdict:

```
L3 FAIL  Delicious Fruity Taste
"The evidence does not mention the taste of the gummies."
cites: ev_ce5a98aa84
```

`ev_ce5a98aa84` is the speech record at **0:00**. All four claim FAILs cite that
one record and all four plot at x=0.0s. `ev_e188a6d2b7` appears **once** in the
entire 4.6 MB report — in the evidence timeline. No verdict ever cited it.

L3 answered honestly about what it was shown. It was never shown 0:16.

**Why.** `candidates_for()` ranked on exactly one signal:

```python
out.sort(key=lambda c: (-c['hint_score'], c['record'].start_seconds))
return out[:rc.top_k]
```

Fix 16 removed `match_hints` from claim requirements — correctly; a single
plain word scored 100 and passed everything. But that left them with **no
ranking signal**, so `hint_score` is 0 for every record, the sort collapses to
its tiebreak, and `top_k=10` of a 121-record video becomes *the first ten
records* — **0.0s to 3.2s of a 43-second video.**

**Two of my own fixes interacted.** Fix 16 emptied the ranking signal; fix 19
made absence a FAIL. Absence-is-FAIL is only sound if retrieval actually
offered the evidence. Together they manufacture **confident false FAILs** — the
error class `plan.md` ranks worst after a false PASS.

The fix: when nothing carries a hint, rank by **meaning**, reusing the embedder
L2 already has (`l2_similarities`). *"Did she describe the taste"* is a question
about meaning; it was being answered by a clock. If the embedder is
unavailable, `spread_sample()` samples **across** the video rather than taking
its opening — a judge shown ten records from throughout can say "not there"
far more honestly than one shown ten from the first three seconds.

Verified behaviourally on the built notebook, 121 records, the target at 16.3s:

| path | records offered | span | target offered? |
|---|---|---|---|
| **before** | 0–9 | 0.0–3.2s | **no** |
| with embedder | target ranked #1 | 0.0–16.3s | **yes** |
| no embedder (degraded) | evenly sampled | 0.0–37.8s | sampled |

`_embed` now caches on the prepared string — fix 23 re-ranks ~120 records for
each of ~8 hint-less requirements per video, so without the cache it would be
the slowest thing in Phase 6. Values are identical; only speed changes.

**`VERDICT_STAGE_VERSION 1.16.0 → 1.17.0`** — this changes which evidence the
judge sees, so it changes verdicts. `test_p6_fixes` and `crosscheck_notebook`
both caught the bump by pinning the old value, which is what they are for.

**Consequence for every score so far:** all seven videos in the
2026-09-22 batch were scored with claim requirements judged on the opening
seconds. `talking points 0/8, 1/8, 3/8, 4/8` and the `standing` vs decomposed
contradiction on video 1 (`exemplary` beside 43) are both explained by this.
The standing read saw the whole video and marked Delicious Fruity Taste
**covered**; the decomposed read saw 3 seconds and failed it. *The disagreement
was the system telling the truth about itself.*

### Harness after 17–23

`test_p6_fixes 67/67` · `test_p7_score 48/48` · `test_p7_report 40/40` ·
`test_p7_integration 118/118` · `test_p7_alignment_figs 28/28` ·
`test_p7_discriminate 12/12` · `test_speech_absent 31/31` ·
`crosscheck_notebook 65/65` · `crosscheck_deep 33/33` (both notebooks) ·
`check_batch` all PASS.
Versions: `BRIEF 1.21.0` / `p4_brief_compile_v5`, `VERDICT 1.17.0`, `SCORE 1.4.0`.

### Fix 24 — and the harness gap it exposed

Fix 22 made `_visual_keys` call `plan_vlm_load()`. The §60 Phase 5 test suite
replaces `P3` with a minimal fake and stubs `resolve_vision_config`,
`vision_ladder` and `scene_count_of` — **but not `plan_vlm_load`**, so the real
one ran against the fake and died in Colab, mid-run:

```
AttributeError: '_FakeVision' object has no attribute 'model_id'
```

**Every local check passed.** The harness EXTRACTS functions from the notebook
and runs them; it never executes the notebook's own test cells. That is a real
gap — a whole class of breakage is only visible in Colab, on a live run, after
the user has waited for it.

Stubbed rather than fleshing out `_FakeVision`: every other collaborator in
that test is stubbed, the stub keeps it hermetic, and the subject is key
COMPUTATION, not model planning.

The durable part is a new `crosscheck_deep` check: whatever `_STAGE_SPECS`
declares the visual stage needs, the §60 stub must provide. Falsified against a
deliberately broken copy — it fails and names the missing global:

```
FAIL  the notebook test stub swaps every global _visual_keys reads
      NOT STUBBED: ['plan_vlm_load'] -- the real one will run against
      the fake config and raise in Colab
```

`crosscheck_deep` is now 34/34 on both notebooks.

### Fix 25 — flash-lite was never down. It is 8× slower.

Measured 2026-09-22 on the user's live key, one-word prompt, same minute:

| model | result |
|---|---|
| **`gemini-3.5-flash`** | **OK, 3.3s** |
| `gemini-flash-lite-latest` | OK, **25.1s** ← the old default |
| `gemini-3.5-flash-lite` | OK, 36.4s |
| `gemini-3.1-flash-lite`, `gemini-3.8-flash` | 503 high demand |
| `gemini-2.5-flash`, `gemini-2.5-flash-lite` | 404 retired |

Fix 8 put flash-lite first because Phase 3 had measured it as *"the only model
that serves"*. That measurement went stale. flash-lite answers fine — it takes
**25 seconds to say "Ok"**, and a real L3 call carries ~11k in / ~2k out. That
is a large part of why a 7-video batch took an hour, twice.

`gemini-3.5-flash` is ~8× faster **and** a more capable judge than the cheapest
tier, which is what L3 adjudication actually wants.

The ladder is now the three measured-working models, fastest first. The 503s
are deliberately excluded: unlike a 429, a model that is 503-ing costs three
attempts and 3s of back-off on **every** call, and OpenAI is already the safety
net underneath.

**No stage version bump, and it still invalidates the brief.** `hosted_model`
lives inside `asdict(bc)`, which feeds `stage_key('brief', ...)` — so the brief
recompiles, its `cache_key` changes, and every verdict key changes with it: a
full re-audit. That is correct rather than incidental. *A different judge is
different output*, which the design has asserted since VLM 1.11.0 — and which
Phase 6 still does not encode in its own key (§ open items).

**Vision is untouched.** `VisionConfig.gemini_models` stays `flash-lite`;
changing it invalidates every visual artifact and re-runs the whole vision pass.
Separate decision, real bill.

## 11f. SECURITY — two live keys were in the source (2026-09-22)

Found while auditing model calls. §37a hardcoded **a Gemini key and a PAID
OpenAI `sk-proj-` key**, with a comment reading *"Hardcoded deliberately for
testing… rotate it when testing is done"* — and four lines later, *"a printed
key outlives the session and travels wherever the file goes."*

It did. **Seven files:**

```
Phase 6/phases_1_to_6_gemini_vision.ipynb         (source)
Phase 6/phases_1_to_6_gemini_vision.bak.ipynb
Phase 6/phases_1_to_6_gemini_vision.prefix.ipynb
Phase 6/phases_1_to_6_full_pipeline.ipynb
Phase 6/phases_1_to_6_full_pipeline.bak.ipynb
Phase 7/phases_1_to_7_gemini_vision.ipynb         (generated)
Phase 7/phases_1_to_7_BATCH.ipynb                 (generated)
```

…all of which were uploaded to Colab and downloaded again.

**BOTH KEYS MUST BE ROTATED. Removing them from files does not un-share them.**

- Gemini: https://aistudio.google.com/apikey
- OpenAI: https://platform.openai.com/api-keys — this one is billable

Fix 26 replaced the hardcoding with a Colab-secrets hoist; the four files
outside the build were scrubbed to a placeholder. Project-wide scan is clean.

**The harness was enforcing the bug.** `crosscheck_notebook` §8 was literally
titled *"THE GEMINI KEY IS STILL WIRED IN"* and asserted both key prefixes were
present — it would have FAILED the moment anyone removed them. Now inverted: it
asserts no key-shaped string exists, that keys come from secrets, and that the
model is probed rather than assumed.

## 11g. Every model the pipeline uses (audited 2026-09-22)

| phase | model | where | status |
|---|---|---|---|
| 1 frames | none (ffmpeg / scene detect) | local | — |
| 2 ASR | faster-whisper `large-v3-turbo` | local (cpu/int8) | fine |
| 2 OCR | RapidOCR / PaddleOCR / Tesseract | local | fine |
| 3 vision | Gemini — **probed** (fix 29) | hosted | fixed |
| 4 brief | Gemini text — **probed** (fix 27) | hosted | fixed |
| 5 evidence | none (assembly) | — | — |
| 6 L2 | `BAAI/bge-small-en-v1.5` | local CPU | fine |
| 6 L1 | none (deterministic) | — | — |
| 6 L3 | Gemini text → OpenAI `gpt-4.1-mini` paid | hosted | fixed |
| 7 score | **none — by design** | — | correct |
| 7 recommendations | Gemini text | hosted | prose only |

Phase 7's only model call is `evaluate_recommendations`, which produces prose
suggestions. `test_p7_report` already enforces *"recommendations carry no
numeric score field"*. **No model writes a number.** Verified, not assumed.

### Fixes 27 / 29 — probe, don't assume

A hardcoded ladder is a measurement, and fix 8's measurement went stale into a
25-second default. Both paths now probe **once per session, in parallel**, and
order by what actually answered.

The vision probe sends a **real image and requires JSON back**, mirroring
`_once()`'s config exactly — a text-only probe would pass a model that cannot
see, or one that ignores `response_mime_type`.

`PIN_HOSTED_MODEL` / `PIN_VISION_MODEL` switch probing off. **Use them for the
Phase 8 corpus**: `hosted_model` and `gemini_models[0]` are both inside cache
keys, so a probed choice makes the key depend on network conditions. That is
the honest encoding — the key names the judge that ran — but one judge across
all ~40 videos is the entire point of a labelling corpus.

The vision probe stays silent when the winner equals the current model, so a
no-op never prints a cache-invalidation warning it isn't causing.

### Fix 30 — is it the key, the quota, or the servers?

The probes test *models*. An invalid key and a total outage both surfaced as
"nothing answered", and they call for **opposite** actions — the user nearly
created a new key for a 503, which a new key cannot fix.

`key_failure_verdict()` lives with the key cell (it runs before both probes)
and classifies a total failure. It only names a cause when **every** candidate
failed the same way; a mixed bag says so rather than guessing confidently.
Verified on synthetic error sets:

| all candidates returned | verdict |
|---|---|
| `400 API key not valid` | **THE KEY IS THE PROBLEM** — check the secret |
| `429 RESOURCE_EXHAUSTED` | **QUOTA, not the key** — new *project*, or wait for the daily reset |
| `503 UNAVAILABLE` | **SERVER SIDE** — key is fine, a new one will not help |
| `404 NOT_FOUND` | **RETIRED MODELS** — the candidate list is stale |
| mixed | read the per-model errors |

Selection verified the same way: fastest working model wins, nothing-answered
keeps the configured order without crashing, and `PIN_*` overrides the probe.

30b needed `patch_all` — the two probes live in different cells and share a
tail, so `patch()` would have fixed one and left the other. Its marker keys on
text 30b itself inserts, because 30a already defines `key_failure_verdict` and
keying on that name would have made 30b skip **both** probes silently. Third
time that exact trap has appeared in this patcher.

### Fix 28 — a stale fallback that would mis-key an artifact

`plan_vlm_load`'s hosted branch fell back to `('gemini-flash-latest',)` — a
model measured at 503 twice, and not `VisionConfig`'s default. It only fires
for a config with no `gemini_models`, but what it returns goes **straight into
the visual cache key**: a wrong name files the artifact under a model that
cannot run. Now matches the real default.

## 11h. Fix 31 — a claim carried its label, not its meaning (2026-09-22)

Found by reading the batch of seven reports. **The same three talking points
were "not evidenced" in every single video — 0 for 7, three times over:**

```
Gentle & Non-Habit-Forming   0/7
Allergen-Friendly            0/7
Clean & Safe Formula         0/7
```

A talking point no creator in a corpus can ever hit is a broken measurement,
not seven identical creative failures.

**Why.** The brief writes features as `Label: what it means`, and fix 16 kept
only the label — `_claim_headline`'s docstring even justified it: *"the rest is
the brand explaining it to the creator."* That reasoning is wrong:

| the judge was asked about | what the brief actually says it means |
|---|---|
| Gentle & Non-Habit-Forming | **Melatonin-free formula** ensures safe nightly use |
| Clean & Safe Formula | **No added sugars**, artificial colors, flavors |
| Allergen-Friendly | **Free from the Top 9 allergens** |
| Delicious Fruity Taste | **Less than 1g sugar** per serving |

Nobody says *"gentle and non-habit-forming"* out loud. They say **"melatonin
free"** — and video `88415c4e` opens with *"these magnesium melatonin free calm
and sleep gummies"*, against a verdict reading *"never mentions being gentle or
non-habit-forming."* Both the retrieval query and the L3 prompt were built from
the brand's internal vocabulary.

**The fix uses plumbing that already existed.** `acceptance_criteria` is fed to
`_req_query_text` (so L2 retrieves on it) and printed in the L3 prompt as *"what
would make this pass"*. The definition goes there and **deliberately NOT into
`match_hints`** — that is the fuzzy matcher, and the exact trap fix 16 removed
hints to avoid (`"MELATONIN"` scoring 100 against a melatonin-**free** claim).
Meaning belongs in the semantic path.

Verified on the real brief text:

```
BEFORE: "Mention the product feature: Gentle & Non-Habit-Forming
         Gentle & Non-Habit-Forming"
AFTER:  "... The brief defines it as: Melatonin-free formula ensures safe
         nightly use, supporting sleep without dependence"

'melatonin' in the retrieval query?   before: False   after: True
```

### OPEN — a product decision, not a bug

The brief calls itself *"Format Library, Hooks and **Talking Points**"*, says it
exists *"to **showcase** effective hooks"*, that creators *"**can** use"* them,
and *"we **encourage creators to bring their own style**"*. Hooks (10) and CTAs
(4) are correctly treated as `one_of` menus.

**The 8 talking points are not.** Fix 16 made them ungrouped `all_of` — *"each
claim is its own scoring unit, so '3 of 8 covered' is a real number"* — which
conflated two separate things:

1. **reporting** coverage as N/8 — genuinely useful, keep it
2. **scoring** each as a mandatory requirement — 8 of 11 units, 40% of the
   score, and the brief never asked for all eight

A 40-second TikTok cannot recite eight product features, so every creator loses
~half the Messaging dimension by construction. This is very likely the bulk of
"scores feel too low". Needs the user's decision on shape, and any threshold it
introduces is a PLACEHOLDER until Phase 8.

## 11i. The scoring reshape — fixes 32 & 33 (2026-09-22)

The user's product definition, finally stated plainly: *"we just need to check
if she is talking about the brand mentioned in the brief or no? That is the
whole deal."* Plus a constraint: *"it should still be able to tell an off brief
video."* Plus labels: six videos they judge on-brief that *"should be scoring
from 70 to 100"*.

### Fix 32 — the feature bullets are a menu, scored once

`_collapse_talking_points()` in §76 merges every `source='approved_claims'`
verdict into ONE unit, scored by coverage:

- `covered` = PASS 1.0 + PARTIAL 0.5
- `PASS` at ≥ target, `PARTIAL` at ≥ half, `FAIL` below, `UNCERTAIN` if nothing
  was decidable
- the unit inherits the **SUM** of the bullets' weights, so eight bullets still
  carry what eight bullets carried — only the all-or-nothing-per-bullet
  penalty goes
- every bullet keeps its own verdict, its own report row and the "N of 8"
  headline; `score['talking_points']` records the collapse so the one unit that
  stands for eight is recomputable by hand

`SCORE_STAGE_VERSION 1.4.0 → 1.5.0`, and `crosscheck_deep`'s `SCORE_SHAPE`
gained the 1.5.0 entry — that check exists precisely to stop an artifact
changing shape without its version moving.

**`talking_point_target_PLACEHOLDER = 3` is the weakest number in the system**
— worse than the band thresholds, because it is *fitted* rather than merely
unmeasured. The brief states no minimum; 3 comes from the user's statement
about seven videos. That is 7 labels. Phase 8 is where it gets an honest value.

### Fix 33 — substance credit skipped every PARTIAL

The credit loop opened `if v.status != 'FAIL': continue`, so a PARTIAL could
never be promoted however well it aligned. Measured on `a1a06e8d`:

```
PARTIAL  Supports Digestive Health   meaning: STRONG
         "Mentions fiber to help support digestion and probiotics"
```

Strong alignment, cited to a record, stuck at half marks because the literal
layer happened to say PARTIAL rather than FAIL. Both gates are unchanged; only
eligibility widened, and only ever upward. `VERDICT 1.17.0 → 1.18.0`.

### Simulated on all seven videos (collapse only, old verdicts)

| video | before | after |
|---|---|---|
| 131811 | 50 | **79** |
| 175002 | 50 | **79** |
| 054922 | 80 | **100** |
| 283080 | 21 | 36 |
| 097098 | 36 | 64 |
| 254611 | 50 | **86** |
| **off-brief** | **0** | **0** ✓ |

The off-brief gate survives untouched: coverage of the brand's own talking
points IS the measure of "is she talking about this product", so a video
covering none earns none of that weight — which is what lets the unit carry it.

This simulation applies **only** fix 32 to the OLD verdicts. Fixes 31 and 33
change the verdicts themselves and should lift these further.

### Two regressions the collapse would have caused, caught on review

The synthetic unit's `requirement_id` names nothing in the brief, and two
places look requirements up by id:

1. **`_dimension_breakdown`** called `resolve_dimension()` with an empty
   requirement, found nothing to read, and would have filed eight feature
   bullets under the **fallback** dimension. Fixed: a synthetic unit may
   DECLARE its dimension and is believed. Verified against a deliberately
   wrong `resolve_dimension` stub — the declared value wins.
2. **The alignment figures** (`s79b`) place a verdict by looking its id up in
   the dimension's `requirement_ids`, and **drop any verdict they cannot
   place** (`if not dim: continue`). Listing only
   `talking_points__collapsed` would have erased all eight bullets from the
   figures while still scoring them. Fixed: the collapsed unit carries
   `member_requirement_ids` and the dimension listing expands them. Verified:
   8 of 8 ids survive.

### It is documented on the page, not just in the artifact

`REPORT_STAGE_VERSION 1.0.0 → 1.1.0`. The Talking points section now carries a
**How this scores** block: covered-of-offered, the PASS=1/PARTIAL=0.5 rule, the
target, the resulting status, and the combined weight — plus an explicit
PLACEHOLDER warning. Its subtitle used to claim *"each point is scored on its
own"*, which the collapse made false; it now says every point keeps its own
verdict and row, which is what is actually true. Renders without the scoring
note when no score is passed, so older callers and gated runs still work.

## 11r. Fix 51/52 — the model was told to stop before it was told what to do

`concept_fit` came back empty on a live run. The plumbing was fine. **The
prompt was built wrong, by me**, and reading it back makes it obvious:

```
"Answer in two steps"          <- there are three
1. ...  2. ...
"Return ONLY this JSON"        <- stop instruction
{... "concept_fit": [...]}
3. HOW MUCH OF EACH ...        <- AFTER the stop instruction
```

The schema even said *"one of the NAMED ANGLES listed below"*, pointing at
text that comes **after** the JSON it describes. A model that emitted the JSON
and stopped followed the prompt exactly as written.

Fixed: steps before the schema, the count corrected to THREE, an explicit
*"EVERY key below is REQUIRED — including concept_fit"*, and **two** example
rows so the split reads as a split rather than a single value. Verified by
reading the assembled system message back out of the built notebook.

### Fix 52 — an empty split has two causes

It can be empty because the model ignored the ask, or because **the brief
named no angles to ask about** — in which case empty is correct. Those look
identical in a report and need opposite work: fix the prompt, or fix the
brief's headings.

`NO_NAMED_ANGLES_IN_BRIEF` is now flagged when the brief yielded no angles,
and `concept_fit_missing` when angles were offered and the model returned
nothing. Same lesson as fix 35's key diagnosis: an outcome with two causes
must say which one it had.

## 11q. Angle attribution, URL input, visual claims (2026-09-23)

### Fix 50 — WHICH named angle, and how much of each

The brief names two angles — *"No judgement zone"* and *"Health journey"*.
`nearest_brief_concept` could not attribute them: `_brief_concepts` returns
group **labels**, so the answer came back *"Creative Concepts"* — the heading
they sit under. And a single nearest match cannot express *mostly one, partly
the other*.

`named_brief_angles()` returns the **options**, not the heading, and only from
groups whose label reads like a set of angles (`concept|angle|format|
territory|theme|creative|framework|treatment|execution|route|campaign`) — so a
ten-option hook list does not become ten angles. Verified on this brief's
shape: `['No judgement zone', 'Health journey']`, CTA options correctly
excluded.

L3 then returns a **percentage split**, validated the way every other model
output here is — against a closed list, with repairs recorded:

| input | result |
|---|---|
| clean 70/30 | preserved |
| does not sum (60/30) | renormalised, `CONCEPT_FIT_RENORMALISED:90->100` |
| invented angle | **dropped**, `CONCEPT_FIT_NOT_IN_BRIEF:Unboxing haul` |
| near-miss wording | matched to the real angle |
| junk percent | dropped safely |

**THIS IS A DESCRIPTION, NOT A SCORE.** It lives in the creative-angle block,
which §76 never reads, and the page says so in those words. The design rule is
that no model writes a number *that enters the score* — not that no model may
express a proportion. Keeping those apart is what makes the rule enforceable
rather than decorative.

§91 aggregates it: per-video split, batch average, and which angles **nobody**
used.

### Fix 49 — a feature she SHOWS is a feature she communicated

Fix 16 hardcoded claims to `speech_or_text`. That already covers OCR, so the
only excluded channel was **visual**. On a pill-organiser brief that is the
wrong exclusion: half its talking points are things you SEE — *"Extra-large
size (7x9) with 21 compartments"*, *"Color-coded rows"*, *"Rainbow-colored
lids"*. Measured on `fleetwoodrose`: the evidence carries *"multi-colored pill
container… pastel green, blue"* at 0:48 and the requirement FAILed.

**I tried `infer_evidence_mode` first** — deterministic, already exists. It
returns `None` for all ten of this brief's bullets: it reads imperative
requirement sentences, not bare feature nouns. So it cannot decide this, and a
per-claim word list would be the "Prohibited Claims" mistake again.

`CLAIM_EVIDENCE_MODE = 'any'`, reversible in one line. The risk is named, not
hidden: *"BPA-free"* cannot be shown, so a visual must not satisfy it — that is
L3's job, and it is the layer that already declined to credit *"melatonin-
free"* from an OCR reading `MELATONIN`. `can_fail_on` is also **stricter**
under `any`: a FAIL then needs every modality healthy.

### URL input — paste links, it fetches them

`VIDEO_URLS` at the top of §0.4. yt-dlp, installed on first use, named by video
id so a re-run never re-fetches. **Never raises and never stops on the first
failure** — a private or region-locked link in a list of twenty must cost you
that one video, not the batch. Failures are listed at the end with the reason.

## 11p. Generalisation + angle distribution (2026-09-23)

Backup before the change: `backups/20260923_001137/` — both notebooks, the
Phase 6 source, the patcher and this file.

### NEW — which creative angle did each video take?

The brief yields a set of concepts (`creative_angle.brief_concepts`) and Phase
6 already works out, per video, which one it is nearest to
(`nearest_brief_concept`). **Nothing aggregated it**, so the most useful
question a creator manager has — *"we offered four concepts, how many did
anyone actually use?"* — was invisible. It cannot be seen in one report,
because it is a fact about the BATCH against the BRIEF.

§91 now prints:

1. **Every brief concept with a video count**, including the ones **nobody
   used** — that is the finding: either the concept did not land with
   creators, or the brief did not sell it.
2. Videos whose angle matched **none** of the listed concepts.
3. The **creative-angle enum** distribution (what the video IS).
4. **Which item off each menu** — hooks, concepts, CTAs — with the options
   never chosen listed explicitly.

§90 records `angle_nearest`, `brief_concepts` and `chosen_options` (read from
the `GROUP_SELECTED` flag the collapse already writes, so nothing new is
computed).

### Fix 46 — the section classifier only knew this brief's vocabulary

`SECTION_KIND_CUES` decides menu / claims / asks / background. Every cue came
from briefs we had seen, so **"Key Messages", "Mandatories", "Reasons to
Believe", "Proof Points", "Non-Negotiables"** matched nothing and fell to the
fallback — and `requirements` being the fallback is the defect that made
scores swing 5→8→3 units on identical input (fix 14).

Widened to the vocabulary marketing briefs actually use. Measured on 28 unseen
headings: **0 fell through**.

### Fix 47 — a word list cannot settle "Prohibited Claims"

With the wider list all 28 classified, and **two classified wrong**:

```
"Prohibited Claims"   -> claims        (matched `claims` before `prohibit`)
"Campaign Objectives" -> alternatives  (matched `campaign` before `objectives`)
```

Both carry cues for two kinds, and `classify_section` returns the FIRST
matching tuple — so **precedence decided, not evidence**. More vocabulary
could not fix it: every word was already present, and the wrong one won on
position.

A small `SECTION_KIND_OVERRIDES` pass runs first, for markers that settle a
heading outright — prohibition, legal, mandatory, safety → `requirements`;
objectives, goals, timeline, persona → `context`. Deliberately small: each
entry names something that changes what a section **is**, not what it is
**about**.

**28 of 28 now correct**, including *Things to Avoid*, *Tone of Voice*, *Shot
List*, *Deliverables*.

`BRIEF 1.25.0`. Harness green; `crosscheck_deep` 40/40 both notebooks.

## 11o. Fix 43 — it ran, it matched, it changed nothing (2026-09-23)

The 1790103374 batch still showed **16 NOT_APPLICABLE** and no disclaimer unit.
Fix 37 was applied, called, and matched — and did nothing:

```python
if isinstance(r, dict):
    r['group'] = None
```

A requirement is a **dataclass** on the compile path and a dict after
`to_dict()`. `ungroup_non_alternatives`, three lines below, has always handled
both. I wrote the sibling and did not copy the idiom that exists to stop
exactly this — so the function appended to `moved`, reported success, and left
the disclaimer inside the CTA group on all seven videos.

Verified on both shapes, and across verticals:

```
dataclass (compile path)   moved=True  group->None  OK
dict (after to_dict)       moved=True  group->None  OK

FDA supplement / paid disclosure / finance / alcohol / medical
/ footnote shape / labelled shape     -> UNGROUPED
a real CTA / a real hook              -> left alone
```

### The guard, and what it found immediately

`crosscheck_deep` section **L** now fails any function that writes to a
requirement under `if isinstance(r, dict):` with no `else`. On its first run it
found a **second** instance: `audit_group_intents`.

That one was a false alarm *today* — both call sites pass dicts
(`compiled['requirements']` is `[r.to_dict() …]`, and the consensus path does
`r['ordinal'] = i` two lines above its call). **Fixed anyway** (44/45) rather
than allowlisted: a check that reports a true-but-harmless finding gets
ignored, and then it is not a check. And *"this is only ever called with
dicts"* is a fact about today's callers, not a property of the function —
which is precisely the sentence that was true of `ungroup_compliance_lines`
right up until it silently did nothing on seven videos.

Fix 45 restated it as `if/else` rather than an early `continue`: correct
either way, but a check a correct change cannot satisfy is a check that gets
switched off.

`BRIEF 1.24.0`. `crosscheck_deep` 40/40 on both notebooks.

### What the 1790103374 run DID prove

Graded coverage works. Messaging by coverage: **70 (3/8) · 85 (6/8) · 88 (6/8)
· 94 (7/8)** — the ranking that was flat at 93/93/100 before.

And the apparent inversion (video 1 at 6/8 scoring 77, below video 5 at 3/8
scoring 83) is correct arithmetic, not a bug: video 1 carries **Hook 50**,
which costs 0.4 × 50 = 20 points and outweighs its better coverage.

**190s**, down from 3944s on the first run.

## 11n. BRIEF-AGNOSTIC — fixes 40–42 (2026-09-22)

The user's scope statement: *"our project will be used against way different
types of brief and products… we will encounter every type of product video and
every type of content brief."* Three things were Biostime-shaped.

### Fix 40 — OBLIGATION is a second axis, and it was missing

The compiler classified sections by **kind** (what the lines are) but had no
notion of **obligation** (whether the brief demands or offers them). They are
orthogonal:

| kind | obligation | meaning |
|---|---|---|
| alternatives | optional | pick one hook — already right |
| claims | optional | a menu of talking points — Biostime |
| **claims** | **required** | **mandatory safety copy — pharma, finance** |
| requirements | required | must do — already right |

The collapse treated **every** claims section as a menu, because this brief
says *"showcase"*, *"creators CAN use"*, *"we ENCOURAGE creators to bring their
own style"*. A brief saying *"every video MUST state all of the following"*
would have been collapsed identically, letting a creator skip most of a
mandatory disclosure list and still score well — **the false PASS the whole
design exists to prevent.**

`detect_obligation()` counts modal cues; `claims_obligation_of()` reads the
claims sections first, then the whole document. Measured:

| brief | call | cues req/opt |
|---|---|---|
| Biostime | **optional** | 0/5 |
| Pharma / OTC | **required** | 8/0 |
| Finance | **required** | 4/0 |
| Beauty (loose) | **optional** | 0/8 |
| Neutral / silent | **undetermined** | 0/0 |

Same code, same 8 points, 3 covered: **menu → 1 unit, score 52. Checklist → 8
units, score 38.**

**Undetermined defaults to MENU and is FLAGGED** — deliberate, not an
oversight. The report already publishes the strict per-item reading beside the
credited one, every bullet keeps its own verdict and row, and the flag tells a
reviewer to set it. A silent guess either way would be worse than a loud one.

### Fix 41 — a compliance line is not only an FDA line

Fix 37's regex was US-supplement wording, so it restored the check for that
vertical and nothing else. Now two signals, either sufficient:

- **wording** — health, *not medical advice*, *results may vary*, finance
  (*past performance*, *capital at risk*), age-gated (*drink/gamble
  responsibly*, *18+*), **paid-partnership disclosure** (*#ad*, *#sponsored*,
  *paid partnership*, *gifted*) — mandatory for UGC in every vertical
- **shape** — a footnote marker (`*`, `†`), an explicit `Disclaimer:` /
  `Legal:` / `Mandatory:` label, or membership of a section the brief itself
  headed Legal / Compliance / Disclosure

Shape travels across verticals and languages of business better than any word
list, which is why it exists beside the list rather than instead of it.

### Fix 42 — the target scales with the brief

A flat 3 means "nearly all" for a 3-point brief and "15%" for a 20-point one.
Now `max(floor, ceil(0.4 × offered))`, clamped: **2→2, 3→3, 5→3, 8→4, 12→5,
20→8**.

**This moves the Biostime target from 3 to 4**, because fix 38 brought the
count from 7 to 8. Stated plainly rather than buried: this brief gets
marginally stricter than the run last seen.

`BRIEF 1.23.0` · `SCORE 1.6.0` · `REPORT 1.2.0`.

### What is STILL not brief-agnostic

- **Dimension weights** (hook .20, messaging .20, cta .10 …) are fixed. They
  normalise over covered dimensions, so an absent one does not cap the score,
  but the relative emphasis is the same for a demo-led brief and a claim-led
  one.
- **`talking_point_target_fraction = 0.4`** and **`target_credit = 0.7`** are
  still invented numbers, now scaled rather than flat.
- **Band thresholds** remain placeholders.
- **`SECTION_KIND_CUES`** is English and vocabulary-driven. A brief headed
  "Mandatories" or "Key Messages" lands on the fallback kind.

All four are Phase 8 calibration work, not code gaps.

## 11m. Fixes 37–39 — the three the user called (2026-09-22)

### Fix 37 — the FDA disclaimer was one of the CTA "options"

Measured on **all seven** videos: the disclaimer sat in the `call_to_actions`
one_of group, so any video closing with any CTA marked it `NOT_APPLICABLE` and
it was **never checked**. The system reported compliance it had not tested.

`ungroup_compliance_lines()` removes it from the group so it becomes its own
scoring unit. Priority and type are left alone deliberately — what to DO about
a missing disclaimer is a policy decision with a critical-floor lever on it,
and this fix only restores the check. Verified: disclaimer ungrouped, the real
CTA and the hook menu untouched.

`BRIEF 1.21.0 → 1.22.0` — the compiled brief changes. `bump()` could not do it
(its marker was already satisfied by the VERDICT bump, so it reported "already
in" and skipped), which is why 37c exists as its own `patch_all`.

**37a/37b had to be split**: the definition and the call site are in different
cells. And 37b's marker had to name `_compliance = ungroup_compliance_lines`,
not `ungroup_compliance_lines(` — 37a's own `def` line would have matched the
looser pattern and made 37b report itself applied while the function never ran.
**Fourth time that trap has appeared in this patcher.**

### Fix 38 — one count, not two

The page showed `7 of 8 covered` beside `Covered 6.0 of 7`. The report keys on
the `FROM_APPROVED_CLAIMS` flag; the collapse keyed on `source`. Same predicate
now — either signal makes a requirement a talking point — so the two cannot
disagree, which is the property `talking_point_coverage`'s own docstring claims
for itself.

### Fix 39 — coverage RANKS instead of clearing a bar

The cap meant 3-of-7 and 6-of-7 both scored 1.00. Now:

| covered | status | unit score | was |
|---|---|---|---|
| 0/7 | FAIL | 0.000 | — |
| 1/7 | PARTIAL | 0.233 | — |
| 2/7 | PARTIAL | 0.467 | — |
| **3/7** | PASS | **0.700** | 1.000 |
| 4/7 | PASS | 0.775 | 1.000 |
| 5/7 | PASS | 0.850 | 1.000 |
| **6/7** | PASS | **0.925** | 1.000 |
| 7/7 | PASS | 1.000 | 1.000 |

Reaching the target earns `talking_point_target_credit` (0.7); the rest is
earned across the remaining points. `_unit_value()` honours a `_score_override`
the same way `_score_weight()` honours a weight override — three statuses
cannot express "6 of 7", and rounding it to PASS is what made the two identical.
**No model writes a number:** this one is computed from the verdicts by code a
reader can redo by hand, and it is printed in the unit's own reason.

Both constants remain PLACEHOLDERS — the brief states no minimum and no
gradient.

## 11l. Fix 36 — OCR floods the evidence and drowns what she SAID

Found by the user on `bba96ac4`: *"she clearly said they taste like berry
flavoured fruit snack but report says not evidenced."*

She does, **twice**, and Phase 5 caught both:

```
0:10 speech  "they taste just like berry flavored fruit snacks my kids beg for them"
0:15 speech  "how's it taste ... what I absolutely love is"
0:12 ocr     "They taste just like Berry flavoured fruit snacks."
```

Verdict: *"She never mentions the delicious fruity taste"* — **`cites: none`**.

**Measured on that video's own records:**

```
counts: {'ocr': 165, 'speech': 8}
```

The packaging is OCR'd on nearly every frame, so OCR outnumbers speech **20:1**.
Ranking is modality-blind, so all ten candidate slots went to label fragments
(*"Total Sugar"*, *"with other natural flavor"*, *"includes 0g Added Sugar"*),
and the two sentences that answer the question were never offered. **The judge
answered honestly about what it was shown.**

### It was not fix 31, and dedupe alone does not fix it

Checked both with the real BGE model on the real 173 records:

| retrieval | rank of the taste line |
|---|---|
| headline only (pre-fix-31) | #25 of 173 |
| + definition (post-fix-31) | #26 of 173 |
| + exact-text dedupe | #19 of 117 |
| **+ modality cap** | **#4, offered** |

Fix 31 moved it by one place — it neither caused nor cured this. Dedupe helps
and is kept (a label OCR'd thirty times is thirty records carrying one fact),
but label fragments still beat a conversational sentence on this embedder.

### The principle, not the patch

**This is what `evidence_mode` means.** `speech_or_text` says she may SAY it OR
SHOW it. Offering ten OCR records and no speech silently turns that OR into an
and-of-one, and the requirement is judged on half the evidence it was defined
to accept.

`max_modality_share = 0.6` — no modality may hold more than 60% of the slots.
Rank order is preserved: the walk is best-first and skips a candidate only when
its modality is full, so the top record of every modality always survives, and
a short list is topped up rather than returned undersized. **With one modality
present, nothing changes.**

Verified on the real records through the rebuilt notebook's own
`candidates_for`: 6 OCR + 4 speech, taste line at #8, offered.

`VERDICT 1.19.0 → 1.20.0`. **Cells: RetrievalConfig #118/#120,
`candidates_for` #119/#121.**

## 11k. Fix 35 — §37a swallowed every reason it found no key

Fix 26 removed the hardcoded keys (right) and replaced them with a hoist that
caught **every** failure and said nothing:

```python
except Exception:
    pass          # secret absent, or notebook access not granted
```

So §37a printed one quiet `NOT set` line, the run continued, and Phase 3 died a
cell later with a `RuntimeError` traceback. The user hit exactly that. **The old
hardcoded cell could not fail; my replacement could, and I gave it no voice.**

Colab distinguishes two cases that need **opposite** actions —
`SecretNotFoundError` (create it) vs `NotebookAccessError` (flip the toggle) —
and collapsing them into one silent `pass` is the difference between a
10-second fix and a confused half hour. §37a now names which happened, plus
"exists but empty" and "not running in Colab", and prints an unmissable banner
when GEMINI is missing, because this notebook is hosted-only and cannot degrade.

It still does not raise: a missing OPENAI key only disables the paid fallback,
and the stage that truly needs a key already says so. What changed is that the
diagnosis now appears **where the fix is**.

Verified against all five paths (present / missing / access-off / empty /
not-Colab) — each prints its own instruction.

**Cells:** §37a — single **#66**, BATCH **#67**.

## 11j. Fix 34 — a menu option was presented as if it were the ask

**Settled from the reports, not guessed.** Video `a1a06e8d` opens:

```
0:00  "In case you didn't get your new parents' manual at the hospital,"
0:02  "this is how you get your children to go to sleep at night."
0:03  "It's hard for our babies to go to sleep,"
```

The Hooks group returned `alignment: none`, reason *"No speech or text matching
the hook phrase or similar"* — **citing those exact records**. So retrieval was
right, the evidence was right, and the brief holds three bedtime hooks her
opening plainly belongs with. The judgement was wrong.

**Not the instructions.** `L3_SYSTEM` already carries the worked example and
says outright: *"When a CHOICE GROUP is shown above, judge alignment against
the kind of ask the whole group describes, not against the single sentence of
this one option."* It is the **frame**. Every requirement rendered as:

```
text          : Open the video using the hook: "Listen! If your kid lives
                on nuggets and fries..."
```

with the group note three lines later. Asked ten near-identical questions in
one batch, each headed by a different literal sentence, the model answers the
sentence — and its own reasons say so: *"matching the specified phrase"*.

`097098` proves it from the other side: it scored the **concept** group PARTIAL
(correctly recognising *"he's not ignoring me"*) and then failed her on the
hook-**line** group for not reciting one of ten example sentences.

Also diagnostic: the Hooks group selected option #1 — *"Listen! If your kid
lives on nuggets and fries…"*, a **picky-eater/vitamins** hook — as its
representative on two videos that are both about **sleep**. The collapse picks
the best (status, alignment) pair; every member scored FAIL/none, so the
tie broke on the brief's ordering. **Every member scoring `none` is the
finding**, not the tie-break.

The fix puts the ask where the model reads first and demotes the option to what
the brief says it is — an example:

```
THE ASK       : <group intent>
this option   : one EXAMPLE of that ask, worded "<option>"
status judges THIS option's wording. alignment judges THE ASK, in any wording.
```

Plus 34b: the old intent block four lines below is suppressed (it repeated the
same sentence, paid ten times per call on a ten-option group), and the hint
line is scoped — *"words that would satisfy THIS OPTION literally"* — because
labelling one option's keywords as the ask's words is the same literal pull.

**An ungrouped requirement renders exactly as before.** `VERDICT 1.18.0 →
1.19.0`. `crosscheck_deep` section **K** renders the real prompt and asserts
the ordering, the one-time intent, the option-scoped hints, and that ungrouped
output is untouched — 39/39 on both notebooks.

### What is still not proven

Fix 34 changes what the judge reads. It does **not** guarantee the judge then
answers differently — that is a model behaviour, and the only evidence that
settles it is the next run's reports for `283080` and `097098`.

### Superseded — the hook/concept menus

`283080` and `097098` stay low because their hook and CTA units FAIL: the
creator used her own hook rather than one of the brief's ten, and the group
collapsed to a failing member. The L3 group prompt already says *"the quoted
sentences are EXAMPLES of that ask… judge ALIGNMENT against the ask"*, and it
still returned `alignment: none`. Whether that is correct (her opening really
isn't a brief-style hook) or a prompt failure cannot be settled without seeing
her actual opening beside the group's intent text. **Do not change L3's group
handling blind** — it is the change most likely to break what currently works.

### Cells to replace (both notebooks, after fixes 20–33)

| fix | single | BATCH |
|---|---|---|
| 20+21 `run_vision_stage` | #71 | #72 |
| 22b §30.5 reconciliation | — | #85 |
| 28 vision fallback default | #65 | #66 |
| **26 §37a — KEY REMOVED, Colab secrets** | **#66** | **#67** |
| 29 §26b vision probe + autoselect | #67 | #68 |
| 25+27 `BriefConfig` + text probe | #86 | #88 |
| **31 claim definition → acceptance_criteria** | **#96** | **#98** |
| 22 `_visual_keys` | #113 | #115 |
| 24 §60 Phase 5 test suite | #114 | #116 |
| `VERDICT_STAGE_VERSION 1.17.0` | #118 | #120 |
| 23a `candidates_for` (§64) | #119 | #121 |
| 23b `_embed` cache (§66) | #121 | #123 |
| contradiction fix §75 / §76 / §77 | #135 / #137 / #141 | #137 / #139 / #143 |

---

## 11s. Fix 55 — "it asked me to upload even though I entered the links"

The user pasted three TikTok URLs into `VIDEO_URLS`, ran §0.4, and got the
upload prompt. The cell and the links were both correct. Three separate
things were wrong underneath.

**1. A real bug: `prepare_filename(info)` was the source of truth.** It returns
the name yt-dlp *intended before* any merge or remux. A clip that downloads as
two streams and lands as `.mp4` after merging is reported at the pre-merge
name, so `download_videos` looked for a file that was never going to exist and
counted a **successful download as a failure**. Now the inbox is snapshotted
before the fetch and diffed after it — a directory listing cannot be wrong
about what actually landed.

**2. The fetch itself was fragile.** `'mp4/best[ext=mp4]/best'` asks for a
progressive mp4; TikTok does not always offer one, and yt-dlp raises rather
than taking what is there. Two format strings are now tried in order
(`mp4/...`, then plain `best`), with a browser User-Agent — a default python
UA is the easiest thing in the world for a CDN to refuse — plus
`retries: 3, socket_timeout: 30`, and an optional `COOKIES_FILE` wired into
`opts['cookiefile']` when the path is set and exists. TikTok increasingly
refuses anonymous downloads; a cookies.txt from a logged-in browser is the
documented escape hatch, and it is declared right next to `VIDEO_URLS` so it
is findable at the moment you need it.

**3. Silence was the worst part.** The fallback-to-upload path was *correct
behaviour* — links tried, nothing arrived, so ask for files — but it is
indistinguishable from "this notebook ignored my links". Three things now
speak:

- every failed link is named with its error at **220** characters, not 90 —
  the truncation was cutting off the part of a yt-dlp error that says *why*;
- when **every** link fails, a block saying so explicitly: that is one cause,
  not N unlucky links, and it names the three (cookie wall, unreachable
  runtime, out-of-date yt-dlp);
- a banner before the upload prompt: *"LINKS WERE GIVEN BUT NOTHING
  DOWNLOADED. The upload prompt below is the FALLBACK."*

The general rule this is the fourth instance of: **a correct fallback that
does not announce itself reads as a broken feature.** Degrade never block —
but say which rung you are on.

Harness after the change: `check_batch` 20/20 + 13/13 stages,
`crosscheck_notebook` 66/66, `crosscheck_deep` 40/40. Cell: BATCH **#5**
(`# §0.4  BATCH INPUT`).

### Fix 56 — the diff was the *second* wrong success-test

Fix 55 replaced `prepare_filename` with a directory diff, and the very next run
reported all three links failed with `no new file appeared in the inbox` —
while the inbox listed `7674625522189618445.mp4`, `7678124132499803422.mp4`
and `7672766519583018253.mp4`, the exact three ids. The tell was in the message
itself: that string is the `_err or ...` fallback, so **no exception had been
raised**. yt-dlp connected, authenticated with the cookies, saw it already had
the file, and skipped the download. Nothing new appeared, and the diff called a
satisfied link a failure.

**Nothing new is not the same as nothing there.** The authority is now the id
yt-dlp resolved (`extract_info()['id']`): if a video with that id is in the
inbox, the link is satisfied, whoever put it there — printed `HAVE` rather than
`OK` so a re-run is honest about what it did. And when every format raised so
there is no resolved id, the trailing digits of the URL are parsed as a
fallback, because a clip you already have should not fail just because TikTok
started refusing you today.

Three success-tests in two days — `prepare_filename`, then the diff, now
id-presence. The first two both asked *"did this call do work?"*. Only the
third asks the question that matters: **"is the artifact there?"** A
content-addressed system should never have been asking the other one.

### Fix 57 — §18.1's OCR fixture was entering the batch as a video

`§18.1 Build the ground-truth video` writes `test_changing_text.mp4` straight
into `DIRS['inbox']` (code cell #56), which runs *before* Phase 1 (#82). So it
got a manifest, and arrived in `discover_videos()` looking like a real video:
0.1 MB, a transcript, an audit, a score and a report, none of which mean
anything. The batch loop now drops it by the name §18.1 itself declares
(`globals().get('TEST_VIDEO_NAME')`), not a hardcoded guess, and says so.

One junk row in the table was the small harm. The real one: it would have
walked into the **Phase 8 benchmark** as a labelled case.

---

## 11t. Fixes 58–61 — Gemini said "high demand" and we had one model

`§30.5` on 4 videos: one OK, two `GENERATION_FAILED  0 events`, with
`transient, retrying in 1s` / `in 2s` and nothing naming the cause. Probed by
hand, the error was **503 — the model is facing high demand**. So the *trigger*
was Gemini's capacity, genuinely their side. Everything that turned a refusal
into a dead stage was ours.

The probe output was the confession:

```
fail  gemini-3.5-flash          504 DEADLINE_EXCEEDED
OK    gemini-3.5-flash-lite      30.0s
OK    gemini-flash-lite-latest   25.5s
fail  gemini-3.1-flash-lite     503 UNAVAILABLE
fail  gemini-3.8-flash          503 UNAVAILABLE
vision model -> gemini-flash-lite-latest (25.5s), unchanged
```

**Fix 58 — the probe measured a ladder and kept one rung.** Both return paths
of `autoselect_vision_model` discarded the rest: one returned `(winner,)`, the
other returned `cfg` untouched — and it was the *unchanged* branch that ran
here, throwing away `gemini-3.5-flash-lite`, which had answered. The stage then
reached `unusable, trying the next model` with no next model. Overload is **per
model**, so the others were precisely the escape hatch. `ranked[0]` stays
first, so `gemini_models[0]` — the visual **cache key** — does not move and no
artifact is invalidated.

**Fix 61 — busy now is not dead forever.** Three of five candidates were
dropped for the same condition the stage failed on minutes later. §11's fix 8
already wrote the rule down — *"a 429 is a quota, not a tombstone"* — and the
probe was not applying it. A transient probe failure now **demotes** (to the
back of the ladder, at `float('inf')`) rather than deletes; a hard failure
(404 `NOT_FOUND`, junk reply) still excludes, because that does not improve
with waiting. Only when something did answer: with no measurement at all,
leading with a model that just failed its own probe is a guess wearing a
measurement's clothes.

**Fix 59 — 1s then 2s is not a retry ladder, it is a formality.** 503 capacity
clears in tens of seconds. Now `2 ** (attempt + 2)` (4s, 8s) with jitter, so a
batch does not retry in lockstep into the same wall. Depth is the wrong axis
anyway — breadth across models is the real fix, and `LADDER_BUDGET_S = 420`,
re-checked every attempt, still bounds the total. It also **prints the error**.

**Fix 60 — the loop printed the symptom and discarded the diagnosis.**
`run_vlm_pass1` records the exception text as a flag detail and §71's
`describe()` prints it, but `run_vision_all` — the loop you actually watch —
printed only the status. Two rounds of diagnosis went into recovering a string
the loop had in hand. `ev` is reset per iteration first: without that, a video
raising before the assignment prints the *previous* video's reason, which is
worse than silence.

**Behaviour executed, not just text-matched** (the fix 43 lesson): four cases
through the real `autoselect_vision_model` — winner==current with demotions,
winner!=current, single model, nothing answered. Ladder correct and
`gemini_models[0]` unmoved in all four.

Cells: BATCH **#68** (`# §26b auditor/vision/gemini.py`) and **#84**
(`# auditor/vision/batch.py`). Harness: 20/20, 66/66, 40/40, 68/68.

**Correction recorded:** I first advised that enabling billing would make most
of this evaporate. That holds for a 429 quota wall; this was 503 overload,
where paid tier helps much less. The ladder is the fix.

---

## 11u. Fix 60 pays for itself: it was never the ladder, it was the key

The very next run, with fix 60 in:

```
[3/4] adf86421f2b51dd8   GENERATION_FAILED  0 events
    -> GENERATION_FAILED: RuntimeError: Every Gemini vision model failed on
       48 frames (1.1 MB) after 0s:
       gemini-flash-lite-latest: ClientError: 401 UNAUTHENTICATED.
```

**401, not 429, not 503.** A different diagnosis entirely, and one no ladder
can fix: every model on the ladder authenticates with the same key. Fixes
58/61 would not have saved those videos. The classifier was right not to retry
— `after 0s`, `attempts: 1` — 401 is a refusal, not a wobble.

Videos 1 and 2 succeeded **in the same run**, so the key was valid at the start
and invalid 70 seconds later. That is the signature of a key rotated (or
auto-disabled for exposure) mid-run, with the Colab runtime still holding the
old value in `os.environ`.

The lesson is about the previous three rounds, not this one: **two rounds of
diagnosis were spent theorising about quota and overload while the answer sat
in a string the loop already had.** Printing the error was worth more than
either fix built on top of the guess.

### Fix 62 — the fixture was the most expensive row in the table

```
5def3cad66283b62  test_changing_text.mp4  OK  5 events  240.88s
7cbe084e3e969da0  7674625522189618445.mp4 OK  4 events   72.48s
```

§18.1's 0.1 MB OCR fixture spent **240.88s of hosted inference — more than both
real videos combined**, plus a slice of a rate-limited free tier, describing a
clip built to prove OCR reads changing text. Fix 57 excluded it from §90 (the
audit); this excludes it from §30.5 (the expensive cell), which is where the
money actually goes.

### Fix 63 — `elif` hid a failure

The run printed `WARNING: 1 video(s) have NO visual evidence` with **two**
`GENERATION_FAILED` rows in the table immediately above. Not a miscount:
`_novis` means "no artifact on disk at all" and `_notok` means "this run did
not end OK", and the second video had an artifact from an earlier run. Two
independent facts — joined by `elif`, so the first one silenced the second.

Now both report, with the overlap removed so nothing is named twice.
Undercounting missing evidence is the one direction this warning must never
round.

Cells: BATCH **#85** (`# §30.5  BATCH — the vision pass for EVERY video`).
Harness 20/20, 66/66, 40/40; the reporting arithmetic executed against the real
case (2 failures, 2 named).

---

## 11v. The Backend — notebook to FastAPI (2026-09-23)

`Backend/` now holds a FastAPI service around Phases 1–7. The analysis came
first and is in `Backend/docs/` (01 execution map, 02 architecture,
03 decisions, 04 parity checklist).

**The key discovery: the notebook already declares its own module layout.**
31 cells carry their intended path in the header comment (`# auditor/cache.py`,
`# auditor/vision/gemini.py`, …). The production boundary did not have to be
invented — it was written down, cell by cell, and Phases 4–7 map cleanly by §
section.

**`auditor/` is GENERATED, not hand-ported.** 24,000 lines across 148 cells
(81 production) is too much to retype without drift, and drift is the one
thing the brief forbade. `tools/extract_from_notebook.py` copies cell bodies
verbatim into the module each cell names, dropping only driver statements —
232 of them, each listed at the foot of its module. Every cell is either in
`CELL_MAP` or in `EXCLUDED` *with a reason*; the extractor refuses to run
otherwise, and a test asserts the same.

**The loader reproduces the notebook's namespace rather than guessing an
import graph.** The notebook binds some names late on purpose —
`globals().get('make_vision_backend')` lets cell 72 reach cell 68 — so
`runtime.py` executes the generated modules in cell order into one namespace.
Real files; identical semantics. The cost, stated in the README: you cannot
`from auditor.vision import gemini`. Reversible later, module by module, once
Phase 8 can prove each move safe.

**One bug the rule caught, worth recording.** The first keep/drop heuristic
kept `batch_df = preprocess_folder(DIRS['inbox'], patterns=tuple(...))`
because the substring `tuple(` appeared *somewhere inside* the call — so
importing the package ran Phase 1 on a directory. Same family as every other
substring-matching bug this week (`'500' in s`). The rule now tests the
OUTERMOST call only, and `test_loading_runs_no_stage` asserts no module-level
statement does anything.

**Two decisions the user made, not me.** Both were genuine
notebook-vs-HTTP conflicts and both are recorded in `04_parity_checklist` §4.3:

- **Approval**: freeze-on-first-compile (`approved_by:
  "api:freeze-on-first-compile"`). The human gate in §48c exists because the
  compiler is non-deterministic — 6/9/16/21/22/24 requirements from one brief.
  Freezing keeps the property that matters (same brief = same contract)
  without inventing a human.
- **Brief input**: Google Docs URL or raw text, exactly as `load_brief_text`
  already does, including the check that rejects a sign-in page returned as
  HTTP 200.

**Async, because the numbers say so.** Vision is 72–240 s per video; a cold
three-video job is 5–12 minutes. `POST /analyze` → `202` + job id.
`MAX_CONCURRENT_JOBS=1` by default: Phase 2 loads Whisper once and frees it
before loading OCR, Phase 3 loads the backend once, and concurrent jobs
multiply those loads.

**`artifacts/` and `briefs/` are shared, not per-job.** The user's sketch had
everything under `runs/<id>/`; content-addressing makes that wrong — a private
`artifacts/` re-pays every vision pass. `DIRS` became a ContextVar proxy so all
37 cells that read it stay unchanged.

**Optional `HF_TOKEN` (added on request).** Three models come from the Hub —
faster-whisper large-v3-turbo (~1.6 GB), the transformers Whisper fallback,
and BGE-small for the L2 rung (~130 MB). All public, so no token is needed;
what one buys is a higher download rate limit, and an anonymous datacentre IP
is throttled hard enough that a cold container fetching ~1.8 GB can take a
429. **Zero pipeline code changed**: `WhisperModel(name, …)` and
`SentenceTransformer(model_id, …)` take no token argument, so all three
resolve through `huggingface_hub` reading the environment — exporting the
variable *is* the integration, which is why it costs nothing in parity. Both
spellings (`HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`) are set, `HF_HOME` is
exposed for a persistent weights cache, and `hf_[A-Za-z0-9]{20,}` was added
to the log redactor.

Status: 58/58 entry points present, 68 tests passing (no key, no network),
71 modules, 148/148 cells accounted for. **Not yet run end to end** — that
needs a live key, and `tests/test_parity.py` against the pill-organiser brief
is the next piece of work.

---

## 11w. Fix 64 — HF_TOKEN, put in the wrong cell and then moved

**First attempt (wrong): §37a.** I added `HF_TOKEN` next to GEMINI and OPENAI
because that cell is "the keys cell". The user corrected it, and they were
right. §37a is about hosted API keys read on every request, one of which halts
the notebook when absent. A Hugging Face token is a one-time weights download,
optional, and it sat 46 cells away from the only code that cares.

**Fix 64c reverts it.** Worth recording *how*: the patcher edits the notebook
in place, so deleting a fix does not undo it — the change is already on disk.
The revert had to be an explicit patch. That is also the more honest record:
the file says a thing was done and then undone, rather than quietly vanishing.

**Fix 64a/64b put it where the download happens.** `ensure_hf_token()` is
defined in cell 21 (`auditor/asr/whisper.py`) and called from two places, both
checked rather than assumed:

| cell | call | size |
|---|---|---|
| 21 | `WhisperModel(name, ...)` — faster-whisper | ~1.6 GB |
| 21 | transformers Whisper fallback | ~1.6 GB |
| 123 | `SentenceTransformer(cfg.model_id)` — BGE, Phase 6 L2 | ~130 MB |

**NOT OCR**, despite the request naming it. `RapidOCR()` ships its ONNX models
inside the package and `PaddleOCR()` fetches from Paddle's own servers —
neither goes near the Hub. Adding a token call to `load_ocr()` would have been
a comment that lies, so cell 22 is untouched and the helper says so in a
sentence.

Optional throughout: every model is public and downloads fine anonymously.
What a token buys is rate limit — Colab is a datacentre IP, throttled far
harder than a home connection, and a cold runtime pulls ~1.8 GB. Both spellings
are exported (`HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`); Colab secrets are read as
a fallback; the token is never printed, only its length.

No stage version moves: the loaders take no token argument and resolve through
`huggingface_hub` reading the environment, so setting the variable *is* the
integration.

Verified by executing the helper both ways, plus §37a asserted back to its
original four lines. Harness 20/20, 66/66, 40/40, 68/68; Backend regenerated,
68 tests, 58/58 entry points.

**The Gemini tester stays in chat, not the repo** — also on request. It
classifies a failure into the causes that need different fixes: 401 the key ·
429 quota (a new key in the same project shares it) · 503 server side (a new
key will not help) · 504 timeout · 404 retired model name.

---

## 11x. Fix 65 — ask the API what exists instead of guessing

`VISION_PROBE_CANDIDATES` was a hand-maintained tuple of five names, and such
a list goes stale in exactly one direction: Google retires a name, the probe
404s, the ladder silently shortens. The 404 branch already said so —
*"RETIRED MODELS: the candidate list is out of date, not the key"* — which is
a diagnosis nobody should have to read, because `models.list()` answers the
question directly. It is also **the cheapest possible key test: listing costs
no tokens**, so a dead key is caught before a single image is uploaded.

`discover_vision_models()` lists, filters, ranks, caps, and feeds
`probe_vision_models`. Falls back to the hardcoded tuple whenever the listing
cannot be had, so it degrades rather than blocks.

**Filtering is part authoritative, part by name, and the split is honest.**
The listing says which models support `generateContent` — authoritative. It
does *not* say which accept an image, and a model that cannot is not a
candidate however new it is, so `embedding|aqa|imagen|veo|-tts|native-audio|
live-|gemma|learnlm` go by name. Getting that wrong costs a wasted probe, not
a wrong audit.

**The cap matters more than it looks.** `probe_vision_models` runs candidates
in PARALLEL with `max_workers=len(candidates)`. Discovery can return fifteen
names where the tuple had five, and a fifteen-way burst against a free-tier
per-minute limit is the probe rate-limiting *itself* — marking healthy models
dead, the exact failure fix 61 was written to stop. Hence
`VISION_PROBE_MAX = 8`, ranked cheap-first (flash-lite < flash < pro, newer
first, preview last) so a quota wall costs the least useful result rather than
the most.

Verified by executing the function against a stubbed `models.list()`: 12
models in, 6 candidates out, embeddings/imagen/tts/gemma/aqa excluded, pro
last, cap honoured, and `[]` returned with no key so the caller falls back.
Plus 14/14 assertions on the same ranking logic in isolation.

### Fix 65b — a constant the Backend extractor could not keep

Fix 65's first pass built `_NOT_VISION_RE` with `__import__('re').compile`.
Harmless in the notebook; fatal downstream. The Backend extractor keeps a
module-level constant only when its value is a literal or a call to a
*recognised* builder — precisely so that importing the package cannot run a
stage — and `__import__('re').compile` is not on that list. The constant was
dropped and `auditor/vision/gemini.py` would have failed to load with a
NameError.

**Why it needed its own fix.** `patch()` skips a fix whose marker is already
present. Fix 65's marker is `def discover_vision_models`, which was there, so
a repair branch inside `fix65` never ran — the patcher printed "already in"
and changed nothing. A marker names what a fix *emits*, so a repair needs a
marker of its own. Third instance of this trap this session.

Harness: 20/20, 66/66, 40/40, 68/68; Backend 68 tests, 58/58 entry points,
`_NOT_VISION_RE` confirmed present in the loaded namespace.

### Fix 66 — the filter, corrected against a real 61-model listing

The standalone tester run on a live key listed **61 models** and my filter
called **37** of them "plausible for vision + JSON". It was wrong about seven
families, and only the ranking saved it — they sort below flash, so the cap
never reached them. With every flash model returning 503, that is exactly the
run where the cap *would* reach them, and a probe that spends its budget
asking a music model to describe a frame has none left for one that could.

Now dropped: `lyria-*` (music) · `nano-banana-*` and every `*-image*`
(generation — returns pixels, and is the easiest thing here to mistake for
vision) · `*-transcribe` · `deep-research-*` · `antigravity-*` (coding agents)
· `*-robotics-*` · `*-computer-use-*`.

**37 → 18**, verified against the user's actual listing: 21/21 assertions, and
the top-8 probe set is now entirely real vision models with
`gemini-3.5-flash-lite` — the only one that actually answered — ranked first.

### Fix 67 — a PIN leads the ladder, it does not replace it

The same run left exactly one model answering, 2 calls in 3. Pinning is right
there. But the PIN branch returned a **one-element tuple** — precisely the
shape fix 58 was written to eliminate. Pinning would have silently restored
the bug: one 503 on the pinned model and the video dies with four good
fallbacks unused.

The pin now leads (so `gemini_models[0]`, the visual cache key, is exactly
what was asked for and no artifact is invalidated) and the rest follow
unprobed, costing nothing until the pin refuses. Accepts a string or a
sequence, so an ORDER can be pinned rather than a model.

**What the live run also confirmed:** `gemini-2.5-flash-lite` returned *"no
longer available to new users"* — a 404 on a name that was in the hardcoded
tuple's neighbourhood. That is the staleness fix 65 exists to remove, observed
in the wild rather than argued for.

---

## 11y. The Backend audit found the worst bug of the session

`tools/audit_backend.py` — deeper than the test suite on purpose. The tests
assert the contract; the audit asks whether the GENERATED layer still matches
the notebook it came from. It found this on its first run.

### Every `@dataclass` had been stripped — 38 of 39

`ast` reports `lineno` for a decorated class at the **`class` keyword, not the
decorator**. The extractor sliced from `node.lineno - 1`, so every decorator
line was left behind.

The classes still parsed. Still imported. Still instantiated. `CFG`, `P2` …
`P7` all existed, `check_entrypoints` reported 58/58, and 68 tests passed —
while **every field was a `dataclasses.Field` object instead of its value**:

```
P3.vision      -> Field, not VisionConfig
P6.retrieval   -> Field, not RetrievalConfig   (top_k unreachable)
```

Nothing raises until something tries to *use* a threshold. Had the parity run
happened before this audit, it would have failed deep inside Phase 6 with an
error naming nothing useful.

**The lesson is the one this project keeps relearning: presence is not
correctness.** `ns['P3'] is not None` passed the entire time the config was
broken — the same shape as fix 43 (ran, matched, changed nothing) and fix 56
(asked "did this call do work?" instead of "is the artifact there?").

### And a second, underneath it

With decorators restored, `@dataclass` then failed outright: it resolves
annotations via `sys.modules.get(cls.__module__).__dict__`, and exec'ing into
a bare dict gives every class a `__module__` that `sys.modules` has never
heard of. `runtime.NS` is now the `__dict__` of a real `types.ModuleType`
registered in `sys.modules`, which is what a notebook-as-module needs anyway.

### Guards added, so neither can recur silently

- The extractor now **counts** module-level decorators, classes and functions
  in the notebook and in the package, and **refuses to finish** if they
  differ. `OK module-level decorators  notebook 38  package 38`.
- Tests: decorators survive · each of the seven config singletons is a real
  dataclass *instance* · `P3.vision.gemini_models`, `P6.retrieval.top_k`,
  `P2.asr.backend` hold values and not `Field` objects · the namespace is a
  real module whose `__dict__ is runtime.NS`.

### The rest of the audit

Eight sections, all passing: generated layer current with the notebook (73
cells → 71 modules, every kept definition present) · all recent fixes survived
extraction (64a/b/c, 65, 65b, 66, 67, plus 50, 58, 61) · behaviour of the
*extracted* code, not the notebook (filter, ranking, PIN ladder, HF mirror) ·
nothing runs at import · design rules still asserted (`score.py` contains no
model call, never reads `concept_fit`) · secret hygiene · the app layer and
every orchestrator call.

One nicety on secret hygiene: the scan flagged the redaction *fixtures* in
`test_api.py`. Rather than whitelist the file — a loophole that would hide a
real key — it distinguishes by entropy: a hand-typed fixture contains
`abcdef` / `123456` / `qrstuv`, which a genuine random key effectively never
does. And it then asserts the detector **did** find those two, because a check
that cannot fail is not a check.

Final: **78 tests**, audit ALL INTACT, 58/58 entry points, notebook harness
20/20 · 66/66 · 40/40 · 68/68.

---

## 11z. Backend hardening: four more defects, and parallelism where it is safe

### Four defects the audit's second pass found

| # | Defect | Why it mattered |
|---|---|---|
| 1 | `JobStore.get` restore loop `setattr`'d every JSON key the object had an attribute for — including `elapsed_s`, a **read-only property** | `hasattr()` is True for a property and says nothing about assignment. Every finished job returned **500** after a restart. |
| 2 | `elapsed_s` reconstructed the end as `t0 + sum(timings)` | Omits every gap between phases — queueing, the brief fetch, teardown — so a job that spent ten minutes waiting under-reported it. Now `_t_end` is stamped once. |
| 3 | `job_timeout_s` declared in config, **never used** | A hung job ran forever. |
| 4 | `keep_job_files_hours` declared, **never used** | No cleanup at all, despite the spec asking for one. |

Plus: `GET /jobs` listed only in-memory jobs, so after a restart it returned
`[]` while every `job.json` sat on disk — the records existed and the API
denied they did. And `AnalyzeRequest` had no `recompile` field while the
worker read `p.get('recompile')`, so that path was dead.

The timeout is **cooperative, checked at phase boundaries**. Killing a worker
mid-ffmpeg or mid-HTTP leaves half-written artifacts that a content-addressed
cache cannot distinguish from good ones — a far worse failure than an overrun.
Videos not reached come back as `SKIPPED_DEADLINE` saying their Phase 1-3
artifacts are cached, so a re-run resumes there.

Cleanup sweeps `jobs/<id>/inbox` and `/reports` only. `artifacts/` and
`briefs/` are never touched: they are shared and content-addressed, and
deleting them re-pays every vision pass ever run. The job RECORD is kept — a
few KB of "what did that run conclude" outliving 7 MB of video is the right
trade.

### Parallelism, per stage, because the stages fail differently

| Stage | Workers | Reasoning |
|---|---|---|
| Download | **4** | Pure network wait, independent per URL |
| Phase 1 decode | **4** | The CPU hot spot, content-addressed, per-video isolated |
| Phase 2 ASR/OCR | 1 | Whisper loads once and is freed before OCR; concurrency multiplies a 50 s load |
| Phase 3 vision | 1 | See below |
| Phase 6 audit | 1 | Same |

Vision **looks** like the biggest win — 72-240 s per video, nearly all of it
waiting on Gemini — and is refused anyway. The live run returned 503 on seven
of eight models and 429 on the eighth; issuing those N-at-once converts a slow
job into a failed one and makes the retry ladder spend its budget on
self-inflicted congestion.

`WORKERS=1` runs **inline**, no threads, so sequential is the notebook's code
path exactly rather than an imitation of it.

**The trap `app/parallel.py` exists for:** `DIRS` is a ContextVar, and
`ThreadPoolExecutor` does **not** copy the calling context into its workers. A
naive `pool.submit` gives every worker an unset `DIRS`, which silently falls
back to the SHARED inbox — two concurrent jobs then read each other's videos,
with no exception and no wrong-looking path. `copy_context()` per task is the
whole fix, and a test asserts it.

Parallel downloads reuse the notebook's per-URL logic but **ignore its return
value**: `download_videos` decides success partly by diffing the inbox, and
concurrently that diff sees files other workers just landed. Each worker
confirms its own id is present instead — the same lesson fix 56 landed on.

### Proved, not asserted

`tools/prove_parallel_decode.py` builds four real videos with ffmpeg and runs
Phase 1 both ways against a cleared artifact store:

```
sequential (workers=1)   4/4 OK in 7.4s
parallel   (workers=4)   4/4 OK in 4.0s
PASS  IDENTICAL manifests (video_hash, plan_hash, frames, duration, audio)
PASS  parallel 7.4s -> 4.0s  (1.83x on 4 clips, 8 cores)
```

### Local environment

`tools/check_deps.py` imports all 20 runtime packages and probes for the two
binaries that are not pip-installable. ffmpeg was missing — the classic
failure where everything imports, `/health` says ok, and the first job dies in
Phase 1. Installed via winget (9.0.2); the tool now names it explicitly.

Final: **92 tests**, audit ALL INTACT, deps READY, 58/58 entry points.

---

## 11aa. Production hardening and deployment

`tools/check_production.py` asks a different question from `audit_backend.py`:
not "does the generated layer match the notebook" but **"would I put this on
the internet"** — the things that are fine on a laptop and dangerous with a
public address.

### What was missing

**Security.** The API was completely open: anyone who could reach the port
could submit jobs and spend the Gemini quota. Added `AUDITOR_API_KEYS` with
`hmac.compare_digest` (`==` short-circuits on the first differing byte and
leaks the prefix to anyone willing to time responses), `x-api-key` or
`Authorization: Bearer`, and `/health` `/ready` `/metrics` deliberately
exempt — a load balancer cannot present a key, and a health check that 401s
reads as a dead container.

It stays **optional and off by default**, which is a narrow, deliberate
choice: a required key with no way to set it turns first-run into a support
ticket, and people respond by disabling auth entirely. `/ready` reports
`auth: OPEN` and startup logs a warning, so an unprotected deployment is
visible rather than assumed.

**Liveness vs readiness.** One `/health` conflated them. The model probe costs
25-30 s of live API calls; blocking startup on it fails the health check of
every platform that has one. Now `/health` is cheap liveness, the probe runs
in a background thread, and `/ready` reports it. Documented loudly: **never
point a restart policy at `/ready`** — it reports a missing API key as
not-ready, and a container restarted for that reason restarts forever.

**Shutdown.** SIGTERM previously lost in-flight jobs silently. Now intake
stops, running work gets a bounded grace, and anything still going is marked
failed on disk saying it was interrupted — because a job killed mid-stage
leaves half-written artifacts a content-addressed cache cannot tell from
complete ones, and a record that still says "running" makes a caller poll
forever.

**Unbounded growth.** Artifacts grew without limit — the thing that kills a
long-running deployment in month four. Added a separate, longer retention for
the cache (whole per-video directories, never partial: removing one stage
while keeping another leaves a video that *looks* processed), a disk-floor
warning **before** a short write becomes a corrupt artifact, and rotating
logs.

Plus: request correlation ids end to end, a 2 MB body cap, queue-depth
backpressure (429), CORS off unless configured, and a startup error when
`WEB_CONCURRENCY > 1` — the job store and namespace are in-process, so N
workers means N stores and N model loads.

### Two bugs the new tests found

- **`_STATE['accepting']` never reset.** Module-level, set False on shutdown.
  Anything starting the app twice in one process — a reload, a test suite —
  came up permanently answering 503, which reads as a dependency failure
  rather than a lifecycle bug.
- A check in `check_production.py` grepped for `d['artifacts']` and failed —
  because `job_dirs()` *inherits* artifacts from `shared_dirs()` rather than
  naming it. The grep was wrong and the code was right. Replaced with a
  behavioural check that binds two job contexts and compares the paths, which
  is the failure mode a grep-based check always has.

### Deployment

`Dockerfile` (multi-stage, CPU-only torch, ffmpeg, non-root uid 10001,
HEALTHCHECK on `/health`, one worker, weights baked at build time),
`.dockerignore`, `docker-compose.yml` with named volumes for the cache and the
models.

The riskiest line was an inline `python -c` with backslash continuations doing
the model bake — unreviewable, unrunnable outside the build, and one stray
backslash from silently baking nothing. It is now `tools/bake_models.py`,
which can be run locally and says what it cached.

**Docker is not installed on this machine, so the image has not been built.**
Stated rather than implied.

`docs/05_deployment.md` ranks free hosting honestly. Most free tiers cannot
run this at all — 4 GB working set, ffmpeg, 5-12 minute jobs, persistent disk.
Oracle Always Free (4 ARM cores / 24 GB) is the only genuinely free-forever
fit; HF Spaces (2 vCPU / 16 GB, Docker-native) is fastest to stand up but has
ephemeral storage and public Spaces; Cloud Run works with GCS. Render free
(512 MB) cannot hold torch. The honest summary is that a EUR 4-7/month VPS
beats every free tier for steady use.

Final: **118 tests**, audit ALL INTACT, production check DEPLOYABLE, deps
READY including ffmpeg 9.0.2.

---

## 11ab. Fix 68 — the "named angles" were the hooks

A live run against the Apothecary brief reported:

```
the brief names 2 creative angle(s):
    "I was just about refill my pill organiser"      90%
    "Don't judge but is what my supplements look"     0%
```

Those are **hooks**. The brief's angles are *No judgement zone* and
*Health journey*. I fetched the document rather than reasoning about it, and
the shape is:

```
Creative Concepts                 <- section heading
Top-performing TikTok formats...  <- lead-in sentence
1. No judgement zone              <- THE ANGLE
* Hook: "Don't judge but ..."     <- detail belonging to it
* Format: Skit-style video
2. Health journey                 <- THE ANGLE
```

`named_brief_angles` read requirement **labels** out of an angle-ish choice
group — and the compiler had turned each *bullet* into a requirement, so it
faithfully reported the bullets. **It was reading the wrong level of the
document.**

### The discriminator, found by running the parser rather than guessing

`parse_brief_sections` keeps the bullet marker on content lines and leaves a
sub-heading bare:

```
'1. No judgement zone'                    <- no marker  = ANGLE
'* Hook: "Don\'t judge but ..."'          <- marker     = detail
'● Hook: "Don\'t judge but ..."'          <- marker     = detail
```

A markdown export uses `*`, a Google Docs plain-text export uses `●`, and the
parser normalises neither — so the marker separates the angle's NAME from what
the angle involves, without guessing at line length or title case. Verified
against both exports of the same document.

### Generalised, because the next brief will differ

- numbered sub-headings win when the section has any (`1.`, `2)`)
- otherwise any bare non-sentence line in the section is a candidate
- a lead-in sentence is rejected: it ends in `.` `!` `?`
- `Hook:`, `Format:`, `Note:` and quoted lines are detail, never names
- **68b**: a brief that bolds angle names without numbering them parses each
  as a SECTION of its own, so when the angle section yields nothing from its
  own lines the following sections are the candidates — until `_ANGLE_STOP_RE`
  names a different topic (`Do Not`, `Talking Points`, `CTA`, …). That stop
  list is load-bearing; without it this swallows the rest of the document.
- nothing found → the old group-label behaviour, unchanged

### And the model now sees the detail

`"No judgement zone"` alone is close to unjudgeable. The bullets under it are
what make an attribution possible, so the L3 prompt now carries name + up to
four detail lines. The validated closed list stays the NAMES only, so
`_clean_concept_fit` is untouched.

### Fix 68c — an apostrophe closed the r-string

68b's first pass emitted `r'\b(do\s*not|don'?ts?|...'`. The bare apostrophe
terminates the literal and cell 127 stopped parsing with *"'(' was never
closed"*. Now `don\S{0,2}ts?`, which matches `donts`, `don'ts` and the
curly-quote form with no quoting at all.

Worth recording **how it was caught**: by *running* the cell, not reading it.
A marker check passed — the marker text WAS emitted, just inside a broken
statement. Fourth time this session that a repair needed its own fix because
`patch()` skips one whose marker is already present.

### Verified

Both exports × both brief shapes, 14 assertions: exactly the two real angles ·
hooks excluded · lead-in sentence excluded · CTA list excluded · each angle
carries its detail · three un-numbered angles found · `Do Not` excluded ·
empty/missing/malformed `brief_text` does not crash.

Harness 20/20 · 66/66 · 40/40 · 68/68; Backend regenerated (377 functions, up
2), 118 tests, ALL INTACT, 58/58.

### Fix 68d — three causes, one symptom

The re-run printed the hook lines again, and there was **no way to tell which
of three things had happened**:

1. the patched cell was never replaced
2. the verdicts artifact was a cache hit, replaying the OLD angles
3. the document path found nothing and the fallback ran

Three different fixes, one indistinguishable output. That is the same failure
as "transient, retrying" hiding a 401: **the code knew and did not say.**

`creative_angle` now carries `angles_source` — `document` (the brief's own
sub-headings), `group_labels` (the old fallback), or `none` — and §91 prints a
warning naming the cell to replace and the flag to set when it is not
`document`. §90 records it per row.

Also: an approved compile is **frozen and reused from disk**, and one written
before `brief_text` was stored has none — the document path would then find
nothing forever, silently. `BRIEF_TEXT` (set by §48 from the loaded document)
is now the fallback, so the angles resolve regardless of when the brief was
compiled.

The general rule, again: **a fallback that does not announce itself reads as a
broken feature.** Fifth instance this session.

### The diagnostic immediately found my actual mistake

```
fix present : True
angles found: ['No judgement zone', 'Health journey']   <- the fix WORKS
angles_source = unknown                                 <- cached verdicts
```

`unknown` means the artifact carried no `angles_source` at all: written before
the change, replayed by `audit_video`'s cache. The notebook was correct and the
run still showed the old angles.

**I changed `evaluate_creative_angle`'s output and did not bump
`VERDICT_STAGE_VERSION`.** That is precisely the rule this project wrote down
for itself — *"bump the stage version in the same edit that changes a stage's
output"* — and precisely the failure it exists to prevent: *"an unbumped change
silently returns stale data."* Fix 68 changes `named_angles`, changes what
`concept_fit` is validated against, and adds a key. All three are artifact
changes.

`VERDICT_STAGE_VERSION 1.20.0 -> 1.21.0`. Every video now re-audits on its
own; `FORCE_REAUDIT` is not needed and nobody else meets this. Two harness
files pinned the old value and were updated with it — a pin that is not
updated in the same edit is the same class of mistake one layer up.

Harness 20/20 · 66/66 · 40/40 · 68/68; Backend 118 tests, ALL INTACT.

---

## 11ac. Fix 69 — a video that matches NONE of the brief's angles

`NO_ANGLE_LABEL = 'none of the listed angles'` was already in the allowed
list, so the validator accepted it. Nothing else did.

**1. The prompt argued against it.** Step 3 said *"a video is usually MOSTLY
one angle and PARTLY another — say so, rather than putting 100 on one and
nothing on the rest"*, and mentioned "none of the listed angles" only as a
footnote about leftover share. A video that took an angle the brief never
imagined would be pushed into a 70/30 split between two angles it does not
resemble — **a fabricated resemblance, which is worse than an honest "none"
because it reads as a finding.** The split guidance is now conditional on the
video belonging to the listed angles at all, and a forced split is explicitly
called out as claiming a resemblance that is not there.

**2. Nothing recorded it.** `off_angle_percent` and `matched_named_angle` are
now on the artifact, plus an `ANGLE_NONE_OF_THE_LISTED:<pct>` flag at ≥50%, so
a batch can count "how many creators went off-concept" — a question about the
BRIEF's coverage as much as about the creators.

**3. Three states rendered identically as zeros:**

| state | what it means | |
|---|---|---|
| `ANGLE_MODEL_FAILED` | the call failed | pipeline problem |
| `concept_fit_missing` | answered, gave no split | pipeline problem |
| `ANGLE_NONE_OF_THE_LISTED` | answered: none of these | **a finding about the video** |

The first two are not findings and must never be printed as one. §91 now adds
a `(none of these)` column — **only when some video actually landed there** —
names the off-concept videos separately from the unattributable ones, and
suppresses the "NOBODY used X" line when nothing was judged, because that line
blames the brief for a measurement that never happened.

Per-video §91 now prints one of:

```
   -> mostly: Health journey
   -> matched NONE of the brief's angles (100%) -- she took her own
   -> NOT JUDGED (no split returned) -- a pipeline problem, not a finding
```

This is the UNCERTAIN rule applied one level up: an abstention is not a zero,
and **"none of the listed angles" is not an abstention either** — it is a
decided answer, and has to look different from both.

`VERDICT_STAGE_VERSION 1.21.0 -> 1.22.0`, **in the same edit**, with both
harness pins updated alongside — the thing I failed to do for fix 68 and had
to chase down from a run that looked like the fix had not applied.

Verified by executing the path: the NONE row survives validation unflagged, a
60/40 partial miss keeps both shares, and the four-state table
(matched / none / borderline 50-50 / not judged) produces four distinct
results. Harness 20/20 · 66/66 · 40/40 · 68/68; Backend 379 functions,
118 tests, ALL INTACT, 58/58.

---

## 11ad. Fix 70 — a quoted title is still a title

A run against the **Biostime** brief reported angles named
`"Open concept titled 'He's Not Ignoring Me He's"` — compiled requirement
labels, i.e. the old fallback again, on a notebook that already had fix 68.
The user's diagnostic settled it in one line:

```
fix present : True                    <- brief_angle_blocks EXISTS
angles found: ["Open concept titled '...", ...]   <- but it returned []
```

That brief names its angles **in smart quotes**, across **two** angle-ish
sections:

```
Creative Concepts
    1. "He's Not Ignoring Me... He's Knocked Out"
    2. "Why I Stopped Giving My Kids Melatonin"
Back to School Campaign
    1. "Back to School Essentials"
    2. "Back to School Bedtime Reset"
```

`_looks_like_angle_name` rejected anything opening with a quote — a rule
written to keep quoted HOOK LINES out, which does its job on the Apothecary
brief and **threw away all four angles here**.

**Quoting was never the discriminator; sentence-ness is.** Strip a matching
pair and judge what is inside:

| line | verdict |
|---|---|
| `"Back to School Essentials"` | 25 chars, no terminal stop → **KEEP** |
| `"Listen! If your kid lives on ... every morning."` | ends `.`, 100 chars → **DROP** |

The length and terminal-punctuation rules were already doing the work; the
blanket quote rejection added nothing except the failure. Stored names have
their quotes stripped, so reports read `Back to School Essentials`, and
`_clean_concept_fit` still matches whichever form the model echoes.

Worth noting the brief's own `Hooks` section is *also* a numbered list of
quoted lines — and is correctly never scanned, because `Hooks` does not match
`_ANGLE_GROUP_RE`. Two independent guards, which is why loosening one was
safe.

### §91 — four columns that all read "Open concept titl"

The user's other observation: *"titles are not printed well but scored
accordingly."* Correct. An angle name runs to 40+ characters and the column
was 17, so four distinct angles printed four identical headers. A table whose
columns cannot be told apart is not a table.

Now a legend once, then short keys:

```
      A1  He's Not Ignoring Me... He's Knocked Out
      A2  Why I Stopped Giving My Kids Melatonin
      A3  Back to School Essentials
      A4  Back to School Bedtime Reset
      --  (none of the listed angles)

    video                                     A1      A2      A3      A4      --
    7670892931187789070.mp4                    0%      0%     20%     80%      0%
       -> mostly: Back to School Bedtime Reset
```

Verified by executing the shipped §91 block against fixture rows, not by
re-implementing it.

Three angle suites now pass together: Apothecary (both export shapes),
Biostime (quoted, two sections), and the no-match states. Harness 20/20 ·
66/66 · 40/40 · 68/68; Backend 380 functions, 118 tests, ALL INTACT.

---

## 11ae. Oracle deployment kit — and a false pass I nearly shipped

Asked whether I could deploy to Oracle for them. **No** — that needs their
account, card verification, console login and SSH credentials. What I can do
is make it four pasted commands and debug from the output, so that is what
`Backend/deploy/oracle/` is.

### The ARM check I got wrong the first time

The whole Oracle recommendation rests on Ampere A1 (aarch64) being able to
install this stack. I wrote a script to query PyPI for each dependency's
wheels — and it passed everything, on the strength of filenames like
`torch-2.14.0-cp312-cp312-macosx_14_0_arm64.whl`.

**That is an Apple Silicon wheel.** It says nothing about Ubuntu on Ampere. My
matcher looked for `arm64` anywhere in the filename, so every package "passed"
and the recommendation would have sent them to provision a VM the stack might
not install on.

Corrected to require `aarch64` **and** `manylinux|linux`, **and** reject
`macosx`. The real result: every dependency publishes a genuine
`manylinux_*_aarch64` wheel — including the two that could have blocked it,
`ctranslate2` (behind faster-whisper) and `onnxruntime` (behind RapidOCR). No
compiler, no source build.

Same family as every other bug this week: a check that matches too loosely
passes for the wrong reason, and a false pass is worse than no check.

### A real bug the check exposed

The Dockerfile hardcoded `--index-url https://download.pytorch.org/whl/cpu`.
On x86 that avoids ~2 GB of unused CUDA and is worth asking for. On aarch64
there is no CUDA build to avoid — the PyPI wheel is already CPU-only — and
that index does not reliably carry one, so asking for it turns a working build
into a resolver error. Both the Dockerfile and `setup.sh` are now arch-aware.

### The kit

`setup.sh` (204 lines, idempotent): checks RAM and **refuses the 1 GB AMD
Always Free shape rather than letting it OOM mid-Phase-2**, installs ffmpeg,
builds the venv with the right torch, generates an API key into `.env` (an
open API on a public IP spends the model quota of anyone who finds it),
pre-downloads the ~1.8 GB of weights so the first request is not a ten-minute
wait that looks like a hang, installs a systemd unit with a 60 s stop timeout,
and opens the instance firewall.

Two Oracle traps documented, both producing the identical silent symptom —
connection times out, nothing in any log:

1. **Two firewalls.** An OCI Ubuntu image ships iptables rules that REJECT
   inbound traffic *regardless of the Security List*. Open the console rule
   only and the server answers on localhost and nowhere else.
2. **"Out of host capacity"** on A1 — not a fault in anything you did. Try
   another availability domain, or 1 OCPU and resize.

Also normalised `setup.sh` to LF: a CR in a shell script fails as
`bad interpreter: No such file or directory`, which names neither the cause
nor the file.

Backend: **127 tests + 1 skipped**, DEPLOYABLE, ALL INTACT.

### `deploy/oracle/DEPLOY.md` — the full walkthrough

Ten steps, Docker-based, with a who-does-what table making the boundary
explicit: steps 1-8 need an Oracle login and SSH credentials and are theirs;
having every file ready beforehand and debugging from pasted output is mine.

Includes the **Vercel integration**, which has a trap worth naming: a browser
on an `https://` Vercel page **cannot** call an `http://` backend at all. That
is mixed-content blocking and no CORS configuration fixes it. The pattern is
therefore

```
Browser --https--> Vercel Route Handler --http--> Oracle :8000
                   (holds the API key)
```

which also keeps the key server-side (anything the browser can send, a user
can read) and sidesteps CORS entirely — and needs **no domain and no
certificate**, because the browser only ever talks to Vercel. Written out as
working Route Handlers, plus the polling loop, because Vercel's function
timeout is 10 s on Hobby and the job takes minutes.

### Four errors caught by checking my own instructions

| # | Wrong | Why it matters |
|---|---|---|
| 1 | `scp cookies.txt ~/creative-audit/Backend/data/` | `/data` in the container is a **named volume**, not that host path. The file lands where the container cannot see it and yt-dlp fails exactly as before, with nothing saying the cookies were ignored. Now `docker compose cp`. |
| 2 | `apt install caddy` | Caddy is **not in Ubuntu's repositories**. Fails with "Unable to locate package". Now adds the Cloudsmith repo first. |
| 3 | `netfilter-persistent save` unguarded | Not always installed. Without it the firewall rule is live but gone after a reboot — the box becomes unreachable for no visible reason. |
| 4 | `docker compose restart` after editing `.env` | **`restart` does not re-read `env_file`.** `up -d` does. |

### And a BOM that was already breaking two things

PowerShell's `Out-File -Encoding utf8` writes a **UTF-8 BOM**. Three files I
had created that way carried one:

- **`.gitignore`** — the BOM is part of the first line, so the pattern was
  `﻿data/`, which matches nothing. **`data/` was never actually ignored**,
  and step 1's `git add Backend` would have committed the videos, the
  artifacts and the 1.7 GB model cache.
- **`docker-compose.yml`** — a BOM before `services:` can make Compose fail to
  find the key at all. A deployment blocker on line 1.
- `.dockerignore` — harmless here, fixed anyway.

All three stripped and normalised to LF; `docker-compose.yml` now verified to
parse as YAML with the expected services, ports, volumes and `env_file`. The
same hazard as `setup.sh`'s CRLF, which fails as
`bad interpreter: No such file or directory` — encoding damage that names
neither its cause nor its file.

### Reviewing the guide found the worst one

**`.env.example` had no `AUDITOR_API_KEYS` line at all** — auth was added
after the template was written and the template never caught up. On its own
that is an omission. Combined with `setup.sh` it was a security bug:

```sh
sed -i "s|^AUDITOR_API_KEYS=.*|AUDITOR_API_KEYS=${KEY}|" .env \
  || echo "AUDITOR_API_KEYS=${KEY}" >> .env
```

**`sed` exits 0 when it matches nothing.** No `AUDITOR_API_KEYS=` line meant
no substitution, exit 0, and the `||` fallback never ran — so the script
generated a key, **printed it to the user, and wrote it nowhere.** The API
would have come up OPEN on a public IP while telling its operator it was
protected.

Replaced with a `set_env()` that checks for the key, appends if absent, and
then **reads the file back to confirm**, failing loudly if not — the same
lesson as fix 56: ask whether the artifact is there, not whether the call
succeeded. Plus post-hoc `grep` guards for an empty `AUDITOR_API_KEYS` and for
a *quoted* value, and the eleven missing serving/retention variables added to
the template with a test asserting every documented variable exists in it.

**And `.env.example` itself was CRLF.** Copied to `.env` on Linux, a trailing
`\r` becomes part of the value — a `401` that looks exactly like a wrong key,
which is the third distinct way this project has produced that symptom
(rotated key, quoted value, now carriage return). Every Linux-bound file
normalised, and a root `.gitattributes` with `* text=auto eol=lf` added so a
Windows clone cannot reintroduce it.

`DEPLOY.md` step 1 now verifies rather than trusts: `git ls-files` must print
nothing for `.env`, `data/` or `.venv/` — the last being ~1.7 GB of baked
model weights that `.gitignore`'s BOM had been failing to exclude.

Final: **127 tests + 1 skipped**, DEPLOYABLE, ALL INTACT, API layer wired.

---

## 11af. Ephemeral mode — running with no persistent volume

Asked what happens if nothing is stored or cached. Working it through gave a
reframing worth keeping.

**Storage here does three unrelated jobs**, and only one matters:

| | size | what its loss costs |
|---|---|---|
| `artifacts/` | 5-20 MB **per video** | re-pay 72-240 s of vision |
| `briefs/` | **~30 KB** per brief | **what a score MEANS** |
| `jobs/*/reports` | 1.4 MB each | the deliverable, transient already |

And the artifact cache is worth less than it looks: **in production each video
is audited once, so it rarely hits at all.** Its value has been in
development, re-running the same five videos twenty times.

The frozen compile cannot go. The compiler produced 6, 9, 16, 21, 22 and 24
requirements from one brief at temperature 0; without the freeze, two videos
submitted in separate jobs are measured against different contracts and
nothing says so.

> **The thing you must keep is ~30 KB. The thing that is bulky is optional.**

That reframes deployment: you do not need a persistent volume, you need a
persistent 30 KB.

### What was built

`AUDITOR_EPHEMERAL=true` moves `artifacts/`, `exports/` and `runs/` under the
job and deletes them on completion — **keeping `reports/` and `job.json`**,
because deleting those breaks `GET /jobs/{id}/report/...` the moment the job
finishes, before the caller has fetched anything. `briefs/` stays shared.

And the stateless escape hatch, for a platform where even that resets:
`/analyze` accepts a `compiled_brief` the caller holds, and `JobOut` returns
one. The client owns the contract; the server keeps nothing.

**It is verified, not trusted** — and the check already existed.
`approval_state()` recomputes `requirements_digest()` over the requirements
and refuses a set edited since approval, so passing the contract back is safe
while rewriting it is not. The brief is therefore passed through UNCHANGED;
forcing `approved = True` would have thrown that away.

Which exposed a real gap: **`compile_brief` never set `approved_digest`.**
`approval_state` fell back to *"approved without a digest (legacy)"* — which
passes, and proves nothing about WHICH requirement set was approved. Now set,
so the tamper check actually has something to check.

Also refused: a `compiled_brief` whose `brief_hash` disagrees with a
`brief_url` given alongside it. Without that the report claims to have audited
brief X against a contract compiled from brief Y, and nothing contradicts it.

### Hugging Face Spaces

Two Dockerfile changes, both about a failure that would have surfaced as a
Phase 1 decode error rather than as itself: **uid 1000, not 10001** (Spaces
runs the container as 1000 and does not consult `USER`, so every write to
`/data` fails with EACCES), and `chmod 777` on the data directories.

`deploy/huggingface/README.md` doubles as the Space's own README — Spaces
reads its configuration from the YAML front-matter, verified to parse with
`sdk: docker` and `app_port: 8000`. A malformed block means the Space probes
7860, finds nothing, and reports a configuration error that never mentions the
port.

Stated plainly in it: `AUDITOR_API_KEYS` is **not optional** on a public
Space; TikTok downloads will be *worse* there than anywhere, because HF IP
ranges are datacentre and heavily used; and at the ~$5/mo persistent-storage
add-on, a €6.50 Hetzner box gives 4 vCPU, 80 GB and no sleeping.

Final: **144 tests + 1 skipped**, DEPLOYABLE, ALL INTACT.

---

## 11ac. The report is a deliverable, and the Backend now returns it

### The wrong file, found by the patcher refusing to lie

The first attempt registered the report fixes in `apply_p6_fixes.py` and got
`FIX DID NOT MATCH`. The anchors were all present in the notebook — because
**§79 is a PHASE 7 cell**. `build_notebook.py` appends it from
`Phase 7/cells/s79_report.py`; it is not in the Phase 6 notebook the patcher
edits, so a fix for it could never match there.

The patcher's `SystemExit` on a non-matching fix is what caught it. A patcher
that skipped quietly would have reported success and changed nothing. The
dead fixes were removed and a comment left in their place saying where the
report actually lives, so the next person does not repeat it.

### What came out

The report goes to creators and creative managers; four things in it were
written for whoever was debugging the pipeline.

| | Before | After |
|---|---|---|
| Header | `video 7cbe084e3e969da0 · brief a1b2c3d4` | `clip.mp4 · 30.8s · Apothecary · 24 Sep 2026` |
| Per-requirement column | `L1` / `L2` / `L3` | `rule` / `similarity` / `model review` |
| Section | `Modules` | `Hook, claims and standing` |
| Section | `Appendix` | `Technical details` |
| Footer | `report v1.2.0…` | *(gone)* |

**Demoted, not deleted.** Design rule 6 is "everything traces", so the hashes,
the cache keys and the ladder rung all survive — in the collapsed technical
section, and as the tooltip on the plain-language rung. A report that cannot
be traced back to the artifact it was computed from is worth less, not more.

### Restyled

The stylesheet was replaced wholesale with **every class name unchanged** —
twenty-odd builder functions emit that markup, and rewriting them to match a
new sheet would be a large untestable diff for a cosmetic gain. Replacing the
sheet alone cannot break a builder.

A real typographic scale, generous whitespace, soft elevation instead of hard
1px borders, a score hero that reads as a verdict, tuned semantic colours, a
mobile breakpoint and print styles. The colour meanings are load-bearing and
were not retuned arbitrarily: green is established compliance, amber is
undecided, red is an established failure.

It also styled **five classes the markup had always emitted and nothing ever
styled** — `score-meta`, `dims`, `bar-cell`, `eviden`, `fignotes` — found by
diffing the classes used against the classes declared, not by looking.

### Verified on a rendered report, not on the source

`scratchpad/check_report.py` renders through the integration test and checks
the HTML: **19/19** — no content hash in the header, a date present, no bare
L1/L2/L3 outside the appendix, provenance still present, evidence ids still
cited, timestamps still linked, CSS braces balanced, custom properties, print
and responsive blocks, every used class styled, and markup well-formed by
`HTMLParser`.

### Backend

- `CreativeAngleOut` gains `dominant_angle` ("which of the brief's angles is
  this video", computed once rather than by every caller) and `angles_source`.
- `angle_distribution` gains `dominant_for` — how many videos each angle is
  the PRIMARY one for, which is the question no single report can answer —
  and `unused`, sorted by dominance.
- **`GET /jobs/{id}/reports.zip`** — every report in one archive, each renamed
  after its video rather than its content hash, plus `summary.json`.
- `REPORT_HTML_VERSION 1.0.0 -> 1.1.0`, in the same edit that changed the
  output.

Harness 20/20 · 66/66 · 40/40 · 68/68; Backend 118 tests, ALL INTACT,
DEPLOYABLE, 379 functions extracted.

---

## 11ad. Three findings from one question about quote marks

The user asked whether the API key needs quotes in `.env`. Checking the answer
surfaced three real problems.

### 1. Live credentials were in the COMMITTED template

`.env.example` had a real `GEMINI_API_KEY` and, commented out, a real
`HUGGING_FACE_HUB_TOKEN`. `.gitignore` covers `.env` — **not** `.env.example`,
which is the file meant to be committed. A value left there is a value that
ships, which is precisely what the file's own header warns about.

Both moved to `.env` (gitignored), template blanked, and a test now asserts
the template carries no credential.

### 2. `.env` was never read outside Docker

Every setting comes from `os.environ`. `docker-compose`'s `env_file:`
populates that for a container; **`uvicorn app.main:app` populates nothing.**
So the README's own quickstart — `cp .env.example .env` then run — came up
with no `GEMINI_API_KEY` and no explanation of why.

`python-dotenv` added, loaded once at config import with `override=False` so a
real environment variable still wins over a stale file beside the code.
`DOTENV_STATUS` reports which happened, and a test asserts the file is
actually read.

### 3. The log redactor knew only one Google key format

It matched `AIza…`. The key actually in use here is the newer `AQ.…` form, and
`ya29.…` OAuth tokens were missed too — **both leaked straight through into
logs**. The generic catch-all did not save it either: the alternation required
the word "api", so bare `key=AQ…` matched nothing.

Now covers `AIza`, `AQ.`, `ya29.`, `sk-`, `hf_`, bearer tokens and bare
`key=`, with tests for each shape — plus three tests that ordinary lines
(`processing video 7674625522189618445.mp4`) survive untouched, because a
scrubber that mangles normal logs is a scrubber someone switches off.

**A credential scrubber that covers one vendor format is worse than none: it
gives confidence it has not earned.**

### The answer to the actual question

No quotes, in either file. `python-dotenv` strips matching surrounding quotes;
`docker-compose`'s `env_file` parser does **not** — it takes them literally,
and a quoted key becomes a key containing quotes, which fails as a 401 that
looks exactly like a bad key.

127 tests, DEPLOYABLE.

---

## 11ae. The first real job found what 127 tests could not

`tools/e2e_smoke.py` runs a REAL job through the API: it builds its own video
with ffmpeg and serves it over localhost, so TikTok refusing a datacentre IP
cannot fail the test, and the only external dependency is Gemini. This is the
gate `docs/04_parity_checklist.md` §4.5 had been waiting on.

It failed immediately:

```
NameError: name 'PROMPT_P4_INSTRUCTIONS' is not defined
```

**The Phase 4 compile prompt had been silently dropped by the extractor.**
127 tests, the structural audit, 58/58 entry points and a production check all
passed with the brief compiler unable to run.

### Why the rule missed it

```python
PROMPT_P4_INSTRUCTIONS = textwrap.dedent(f"""...""").strip()
```

`is_definition` checked the OUTERMOST `func`. For a chained call that is the
entire `textwrap.dedent(...)` expression, which matches no builder name — so a
constant built by `dedent(...).strip()` looked like a driver. `_call_root()`
now walks to the leftmost callable.

### And why nothing caught it

The post-condition counts decorators, classes and functions. It **cannot**
count constants, because dropping module-level assignments is precisely what
the extractor does to drivers — the count would be wrong by design.

So a new check: **every global name the surviving code READS must exist in
the loaded namespace.** That is the guard that generalises, and it immediately
found six more:

| name | why it was lost | consequence |
|---|---|---|
| `_WARN` | `_TICK, _CROSS, _WARN = (...)` — tuple unpack | `render_requirements_table` dies; the human review table is the approval gate |
| `NUMBER_WORDS_INV`, `_COMPOUND_WORDS`, `_GAZ`, `DIMENSION_LABEL` | dict comprehensions | number parsing, the OCR gazetteer, the report's dimension labels |
| `_GAZ_MIN_LEN` | `min(...)` not in the builder list | gazetteer matching |
| `_WORD_VOCAB` | `_load_word_vocab()` | the OCR readability gate |
| `try_install` | its cell is excluded, but **six call sites call it directly** | the L2 rung and the vision backend, on first use |
| `DRIVE_ROOT`, `VLM_CLASSES`, `P3_GPU_GB` | cells this deployment never runs | Drive restore, local Qwen path |

`try_install` is the interesting one: a server must **not** pip-install at
runtime — a container that grows dependencies depending on when it started is
not reproducible. It is now bound to a function that checks importability and,
on failure, says the fix is requirements.txt and a rebuild.

### The rule the session keeps rediscovering

Three separate checks had their own copy of "which calls build a constant",
and they drifted the moment one learned about chained calls. `CONSTANT_BUILDERS`
and `SAFE_CONSTANT_CALLS` now live once in the extractor and are imported by
the audit and the test. **Two copies of a rule that must agree will disagree.**

`SAFE_CONSTANT_CALLS` is deliberately a named allowlist with a reason per
entry rather than a widened rule, so each exception stays a decision on the
record.

### And then it ran

```
status=succeeded  275s          (cold)
        brief    -> 2 scoring units, approved by api:freeze-on-first-compile
                    named_angles: ['No judgement zone', 'Health journey']
        phase 2  -> ASR large-v3-turbo cpu/int8, OCR read ['SHOP','NOW']
        phase 3  -> 7-model vision ladder, OK, 2 events
        phase 5-7-> score 0.0 OFF_BRIEF, standing off_brief
                    concept_fit: none of the listed angles 100%
                    angles_source: document
```

Every piece of this session's work confirmed against live models: fix 68's
angle extraction returned **the brief's own two angles**, `angles_source` is
`document`, the vision ladder came back with **seven** models (fixes 58/61/
65/66), the brief froze on first compile, the restyled report downloaded, and
`reports.zip` assembled.

**The verdict on the video is also correct, which is the part worth noting.**
The clip is ffmpeg colour bars with one line of burned-in text. The system
said `OFF_BRIEF`, `standing: off_brief`, score 0, and attributed 100% to "none
of the listed angles" — the foreign-brief control case, working. The single
red line in that run was my own assertion refusing to allow `NO_ANGLE_LABEL`,
which is a legitimate member of the closed list by design: **the test failed
the system for being right.**

A `--reuse` flag was added afterwards. The second run took **71s instead of
275s**, which is the content-addressed cache proving itself through the API
rather than in theory.

Final: notebook harness 20/20 · 66/66 · 40/40 · 68/68. Backend 127 tests,
ALL INTACT, DEPLOYABLE, deps READY, 58/58 entry points, **and one real job
end to end**.

---

## 11af. The report, written for the person who has to act on it

The user read a real report and named the problem precisely: the page explains
its own arithmetic to a reader who wants to know how the video did. Fourteen
rewrites, verified on a rendered page rather than on the source.

| Was | Now |
|---|---|
| "Coverage is high enough to show a single figure." | *(gone — a single figure needs no explanation)* |
| "Thresholds are placeholders until calibration (Phase 8). The band is a working guide, not a certified grade." | moved into Technical details |
| "judged by SUBSTANCE rather than wording … a second opinion, read whole; it is never averaged into the score" | "Does the video, taken as a whole, do what the brief asked for? Judged on meaning rather than wording — a different hook, order or structure is fine." |
| "nothing is added or deducted for it, and §76 never reads it" | "nothing is added or deducted for it" |
| "Nearest concept in the brief: **none of them**." | shown only when there IS a nearest one |
| "cites: ev_9a0acdc5b8, ev_5e7bcef41b, …" | *(gone from the body; still in the JSON and the technical block)* |
| "How this scores. … Covered 5.0 of 8 (a PASS counts 1, a PARTIAL 0.5) against a target of 4 → PASS, carrying the combined weight of all 8 bullets (8.0)." | "The brief **offers** these and invites your own style, so they count together rather than one by one. You covered **5 of 8**." |
| "The target is a PLACEHOLDER, and a weaker one than the band thresholds…" | moved into Technical details |
| "Figures not drawn (1)" | *(gone — a note to whoever wrote the plotting code)* |
| "13 scoring unit(s). Plus 1 forbidden-content check(s): 1 found nothing, which is compliance rather than achievement and is not averaged in." | "13 items counted towards the score. 1 thing the brief forbids was also checked, and none appeared — staying clear of those is expected, so it does not raise the score." |
| `(small r_09c8913e ev_84c923008e)` | *(internal ids no longer rendered in a row)* |

**DEMOTED, NEVER DELETED.** Every id, every piece of arithmetic and every
caveat still exists — in the JSON artifact and in the collapsed *Technical
details* block. Design rule 6 is "everything traces"; this only decides what
is in the reader's way. A reader deciding whether to reshoot does not need to
be told mid-sentence that a threshold is provisional. Anyone quoting the
number across campaigns does, and it is one click away.

### A guard fired, correctly

`s77_tests.py` asserted `'placeholder' in html.lower()` — the disclosure must
reach the reader. The new wording says *provisional*, which is the same
disclosure in English a creator reads. The test was **asserting a design
requirement through one particular word**, so it now accepts either spelling
*and* requires "threshold" to appear — delete the disclosure entirely and it
still fails. The requirement was kept; only the pinning to my old phrasing
went.

### Verified on the rendered page

`scratchpad/check_plain.py`: all 14 phrases absent from the reader's view,
**0 raw ids in the body**, and nine things confirmed still present — the
score, the band, the categorisation, the angle split, per-requirement
verdicts, what to change, clickable timestamps, the provenance table, and the
relocated disclosure.

Harness 20/20 · 66/66 · 40/40 · 68/68, Phase 7 suite back to its single
pre-existing failure; Backend 127 tests, ALL INTACT, DEPLOYABLE.

---

## 11b. Two artifacts from different runs in one report

Re-rendering the rewritten report from cache (Gemini was 503ing on every
model, so no fresh run was possible) produced a page that contradicted
itself: the headline read **82 / NEEDS MINOR REVISION / 93% coverage** and
"**Nothing to fix:** no requirement came back FAIL or PARTIAL", directly
above a list containing **four FAILs**.

Two separate instances of the same mistake — *newest is not best*.

### The score did not belong to the verdicts

`tools/rerender_report.py` already chose the verdicts artifact by quality
(fewest model errors, most decided), because a run that 503s part-way still
writes a verdicts file. But it took the score with `newest(score__*.json)`:

```
score__0e6929be  <- from verdicts fc2da1b8 (the good run)   80.0, coverage 1.0
score__fb94fa66  <- from verdicts 3c580b76 (the 503 run)    82.0, coverage 0.93
```

It paired the *good* verdicts with the *failed* run's score. Every score
artifact records `scored_from.verdicts_cache_key`; the link was written down
and simply not read. The fix reads it, and **refuses to render** when no
score matches the chosen verdicts rather than falling back to a guess.

### The advice did not belong either

Fixing the score did not remove "Nothing to fix" — so that symptom was never
the score mismatch. Recommendations cost the one model call in Phase 7, so
the re-render reuses them from the previous report JSON; it took the newest
there too. The 503 run had **no** FAILs, so "Nothing to fix" was *true of
that audit* and false of this one. A report artifact is named for the score
it was built from, so the correct one is `report__{score_key}.json` — exact,
not newest.

Checked first whether the original good run's advice had been destroyed by
the earlier re-render: no report JSON anywhere has ever held a single
recommendation, and no HTML has ever contained a `<ol class="recs">` list.
Nothing was lost.

### §79 now refuses to make the claim

The re-render was the messenger, not the disease: any path that carries an
advice block across runs (a resumed job, a cache hit) can assert "Nothing to
fix" over a table of FAILs, and **a reader believes the headline, not the
table**. `_recommendations_html` now takes `result` and cross-checks: if the
verdicts contain FAIL/PARTIAL and the note claims there is nothing to fix,
it says how many fell short and that the edits are unavailable for this run.
Two independent things must agree or the report abstains (§6).

`REPORT_HTML_VERSION` 1.1.0 → **1.1.1** in the same edit.

Rebuild chain, in this order — the batch notebook is derived from the single
one, so building only the batch silently kept the old §79:

```
Phase 7/cells/*.py
  -> Phase 7/verify/build_notebook.py        -> phases_1_to_7_gemini_vision.ipynb
  -> Phase 7/verify/build_batch_notebook.py  -> phases_1_to_7_BATCH.ipynb
  -> Backend/tools/extract_from_notebook.py  -> Backend/auditor/
```

### Verified

Structural counts held (decorators 38/38, classes 56/56, functions 381/381).
`check_plain.py` **ALL GOOD** — 14 phrases still absent, 0 raw ids in the
body, all 9 must-keep elements present. The page now reads 80 ·
NEEDS MINOR REVISION · 5 scoring units · **100% coverage**, and "What to
change" says *"4 requirement(s) fell short, but the list of suggested edits
is not available for this run."*

**The lesson, twice over:** content-addressed artifacts record what they were
computed from. When more than one run has written to the same directory,
selecting any of them by mtime will eventually pair two that never belonged
together — and the result is not a crash but a confident, readable, wrong
page.

### Five stale test failures, repaired rather than tolerated

`test_p7_report.py` was failing 4/39 and `test_p7_alignment_figs.py` was
crashing. None were caused by the advice guard; all four report failures
pinned wording the §11a rewrite had deliberately removed, so they were
testing the old page rather than the requirement:

| check | was | now |
|---|---|---|
| every requirement is listed | `'r1'..'r4'` raw ids | the six requirement **labels** |
| placeholder thresholds disclosed | the literal `'placeholders'` | `('placeholder' or 'provisional') and 'threshold'` |
| standing is a second opinion | `'second opinion'` | `'The whole brief against the whole video'` |
| no raw dict leaked | `split('Appendix')` | `split('Technical details')` |

The last was the worst of them: `Appendix` had been renamed, so the split
returned the *whole* page including the technical block — the one part it
existed to exclude. It was reading the section where escaped dicts are
legitimate and calling it a leak.

`test_p7_alignment_figs.py` died on `IndexError: list index out of range`
because plotly is not installed and every check in it is about what plotly
draws. plotly is **intentionally absent** from `Backend/requirements.txt` —
the report embeds a ~4.8 MB bundle when present, and *a missing chart library
cannot block the score* (§6). It now skips with an explicit message instead
of crashing. `test_p7_report.py` already branched on
`figs['plotly_available']` and covers the no-plotly path.

Suite after: **39/39 · 68/68 · 12/12 · 48/48 · 31/31**, alignment-figs skipped,
Backend **127 passed, 1 skipped**, `audit_backend.py` **ALL INTACT**.

---

## 12. Working notes for a new session

- **Windows, PowerShell 5.1.** No `&&`/`||` chaining — use `;` and `if ($?)`.
  Not a git repository.
- **Python:** `C:\Users\Umar Ilyas\AppData\Local\Programs\Python\Python313\python.exe`
- **Edit `Phase 7/cells/*.py`, then rebuild.** Never hand-edit the `.ipynb`.
- **Always re-run the harness after any edit** (§5). It is fast and has caught
  every regression so far.
- **Bump the stage version in the same edit that changes a stage's output** (§6).
- When quoting cell locations to the user, **use the `# §NN` header text**; give
  a number only with the scheme named (§7).
- The notebook runs on **Colab**; the local machine only builds and verifies it.
  Local runs cannot exercise the model calls.
