# Project state — AI TikTok brief-compliance auditor

**Last updated:** 2026-09-21
**Purpose of this file:** a cold-start briefing. A new session should be able to read *this
file alone* and be useful without re-reading 30,000 lines of notebook. Everything here was
verified against the code and the artifacts on disk, not recalled.

---

## 1. What the system is

Video + brand brief → timestamped, evidence-cited verdicts → a deterministic score → a
one-file HTML report.

The governing question (`product.md` §1):

> *Given what the brief says should happen, what actually happened in the video, and where is
> the evidence?*

**The load-bearing architectural property:** stages 1–5 depend only on the **video**; stage 4
depends only on the **brief**; stages 6–7 are the **join**. One video × N briefs = one
expensive run plus N cheap ones. This holds in the code — verdicts are keyed on
`[video_hash, evidence_key, brief_hash, brief_cache_key]`, and re-auditing against a new brief
re-runs only Phase 6+.

### The three guarantees

These are enforced structurally, not by convention. Do not weaken them.

1. **A FAIL asserts something.** Every FAIL is constructed by one function,
   `_fail_or_uncertain()`, which consults `can_fail_on()` first. There is no second
   construction site. If the modality was degraded or never ran, the answer is UNCERTAIN.
   The one deliberate exception: a FAIL *from presence* (forbidden content found) is grounded
   in evidence you have, so it only checks the health of the modality that carried it
   (`FAIL_FROM_POSITIVE_EVIDENCE`).
2. **Only offered evidence ids are citable.** `_validate_l3()` rejects both invented ids and
   real ids belonging to a *different* requirement. Rejected → retried once → UNCERTAIN.
3. **No model output reaches a numeric field.** `score_audit` declares `model_free: True`;
   §78 drops any recommendation containing a digit or status word; §81 asserts the numeric
   key set against a whitelist.

---

## 2. File map

```
creative project/
├── product.md                 the spec (what to build)
├── plan.md                    the build order (how, phase by phase) — 1,275 lines
├── requirements-local.txt     local Windows CPU env, python 3.13, torch 2.14+cpu
├── PROJECT_STATE.md           ← this file
│
├── Phase 6/
│   ├── phases_1_to_6_gemini_vision.ipynb    hosted vision (Gemini). 239 cells.
│   ├── phases_1_to_6_full_pipeline.ipynb    local Qwen path. Differs in 12 cells only.
│   ├── PHASE_1_6_FINALISATION.md            the defect log. 1,461 lines. READ THIS.
│   ├── phase_6_plan.md / README.md          Phase 6 design + run notes
│   ├── phase_6_cells.py, phase_6_evaluator.ipynb   Sep-17 standalone snapshot. SUPERSEDED.
│   └── phase_conformance_cell.py            = notebook §74b
│
├── Phase 7/
│   ├── phases_1_to_7_gemini_vision.ipynb    ← THE SOURCE OF TRUTH. 254 cells.
│   ├── PHASE_7_PLAN.md                      ⚠ STALE (see §6)
│   └── cells/*.py                           Phase 7 cells as reviewable files
│
└── work/
    ├── inbox/            source videos
    ├── artifacts/{video_hash}/   media_meta, scan.npz, audio, {plan_hash}/manifest.json,
    │                             transcript__*, ocr__*, visual__*, evidence__*,
    │                             verdicts__*, score__*, report__*.html/.json
    ├── briefs/{brief_hash}/requirements__*.json
    ├── runs/             batch logs
    └── exports/          tarballs
```

**`phases_1_to_7_gemini_vision.ipynb` contains `phases_1_to_6_gemini_vision.ipynb` byte-for-byte**
(verified: all 239 cells present verbatim). Read the Phase 7 notebook and you have both.
`full_pipeline` differs only in provider plumbing (`VISION_PROVIDER='local'`, no §26b/§26c
Gemini backend, local-tokenizer branch in the §30.2b dry run).

### Section numbering

| §        | What                                    |
|----------|-----------------------------------------|
| 0–19     | Phase 1 — decode, sample, manifest      |
| 20–35    | Phase 2 — ASR + OCR                     |
| 20.1–34  | Phase 3 — visual evidence (VLM)         |
| 37–51    | Phase 4 — brief compiler                |
| 52–62    | Phase 5 — unified evidence              |
| 63–74    | Phase 6 — verdicts, hook, claims        |
| 74b      | Plan conformance (MET / NOT MET / MANUAL)|
| 75–82    | Phase 7 — scoring and reporting         |

---

## 3. Current versions

| Stage    | Version | Prompt |
|----------|---------|--------|
| PIPELINE | 1.0.0   | |
| ASR      | 1.0.0   | |
| OCR      | 1.3.0   | |
| VLM      | 1.13.0  | `p1_visual_evidence_v5` |
| BRIEF    | 1.12.0  | `p4_brief_compile_v4` |
| EVIDENCE | 1.7.0   | |
| VERDICT  | 1.11.0  | `p6_adjudicate_v1`, `p6_hook_v1`, `p6_claims_v1`, `p6_standing_v1` |
| SCORE    | 1.1.0   | |
| RECOMMEND| 1.0.0   | `p7_recommend_v1` |
| REPORT   | 1.0.0   | |
| FIGURE   | 1.0.0   | |

**Bump the stage version in the same edit that changes the output.** The cache key is built
from the constant, not from the artifact's shape. This has already bitten once: two SCORE
fixes landed without a bump and §80 served a stale artifact while the tests passed.

---

## 4. Where each phase stands

| Phase | State | Note |
|---|---|---|
| 0–3 | **Done** | Hosted Gemini vision, 48/48 frames at full resolution, no OOM ladder engaged |
| 4 | **Done** | Consensus compile (3 runs, majority), approval bound to a requirements digest |
| 5 | **Done** | Three-state speech health: `ran` / `absent` / `degraded` |
| 6 | **Done** | L1/L2/L3 ladder, hook, claims (off), creative angle, standing |
| 7 | **Built** | One exit criterion open (§75b). See §6 below. |
| 8 | **Not started** | ← **this is the real position** |

### The honest position

Phases 1–7 are finalised as *"every stage runs, every exit criterion passes, every verdict is
grounded and traceable."* **Not** as *"the verdicts are correct."* There is no ground-truth
file anywhere in the project. Nothing measures correctness. §82 closes on the right sentence:

> That gap closes with labels, not with more code.

---

## 5. 🔴 URGENT: rotate the API keys

`phases_1_to_7_gemini_vision.ipynb` cell 114 (§37a), and cell 145 of `full_pipeline`, contain
**live plaintext credentials**:

```python
os.environ['GEMINI_API_KEY'] = 'AQ.Ab8RN6...'
os.environ['OPENAI_API_KEY'] = 'sk-proj-90m9uDY...'   # BILLABLE
```

These files get uploaded to Colab. `allow_paid_fallback=True`, so the OpenAI key is spendable.
`_get_secret()` already checks env → Colab secrets first, so the fix is: **rotate both keys,
delete those two lines, add them as Colab secrets.** One deleted line, no other change needed.

---

## 6. Open issues, ranked

### 6.1 — The CTA verdicts are wrong. Four compounding causes.

Diagnosed on the live artifact (`5f18775d` × brief `f697be05`). This is the thing to fix next
after the keys. **Full write-up in §7 below.**

### 6.2 — §75b has never run: the headline number is unvalidated

`RUN_CONTROL_AUDITS = False`, and there is no `work/artifacts/_discrimination/` on disk. §75b
runs on every execution and prints *"NO CONTROL PAIRINGS YET."* §81 carries a criterion for it
that reads **FAIL** until the flag is flipped.

§76 currently leads with candidate **B** (status, achievement-only) on *reasoning*, not
measurement. `PHASE_7_PLAN.md` §1 is blunt: *"Until it is answered, any scoring formula is a
guess."*

The design needs **no labels**: each video is its own control (own brief = positive,
foreign brief = control). The decision rule is pre-registered. Cost: a few L3 calls, capped at
`MAX_CONTROL_AUDITS = 6`. **Set `RUN_CONTROL_AUDITS = True` in §75b and re-run.**

### 6.3 — `PHASE_7_PLAN.md` is stale

Last touched 09-21 00:20; the cells moved at 18:48. Three things in the code are not in the
plan:

- **The relevance gate** (`relevance_of`, `RELEVANCE_SCORABLE`, `BAND_OFF_BRIEF`). Two
  questions in order: *is this video addressing this brief at all?* then *how closely did it
  follow it?* **Fails open** — an unjudged standing scores normally, because "we could not
  tell" must never become "off brief".
- **`band_basis`** — below 90% coverage the grade reads from the **pessimistic** end. A live
  run showed 75–100 at 75% coverage badged `APPROVED`, which is plan.md's "false-positive
  PASS, the most damaging error class."
- **`inferred_units`** — 19 of 22 requirements came back typed `speech_or_text`, so every hook
  and CTA collapsed into Messaging and the report told a reviewer the brief said nothing about
  their hook. `resolve_dimension` now reads the brief's own group names.

Your own rule applies: *a plan that does not record where the build disagreed with it is a
plan that quietly stops being true.*

### 6.4 — Corpus hygiene

- **`work/artifacts/test_vh/`** — 27 stale `score__*.json` files from the §77 fixtures before
  they were sandboxed. The fix is in the code (`_run_phase7_tests` runs against a temp dir and
  restores `DIRS` in `finally`), but the folder survives and §74b counts it as a video.
  **Safe to delete.**
- **Four of five audits are several stage versions behind.** `22a6c0b6`, `31f71cb4`,
  `84875b0c` carry verdicts at **1.0.0** — before §2.17 persisted `hook` / `claims` /
  `creative_angle` / `standing`, so those fields are absent and `uncertain_rate` is `None`.
  Only `5f18775d` is at 1.10.0 (current 1.11.0). Those three also used brief `bc455fe5`
  compiled at **BRIEF 1.5.0** — two prompt generations before the enumeration fix.

### 6.5 — Known, deliberate, deferred to Phase 8

- **L2 decides nothing.** Thresholds 0.72 / 0.35 sit outside the entire observed range
  (0.46–0.69, mean 0.556). Do **not** just lower `high` to 0.60 — in the same measurement the
  single highest score (0.688) was a *wrong* match and a correct one scored 0.632. The ranking
  does not separate right from wrong on this data. The fix is a **retrieval** change (more
  context per passage), not a threshold change.
- **Band thresholds are placeholders.** Nothing establishes that 85 is the line.
- **Claims module off** (`ClaimsConfig.enabled = False`). Brief-level `forbidden` requirements
  still run. Scope decision: in or out for the MVP.
- **L3 handles ~96%** against a <30% target. On a brief written as exact scripts the creator
  paraphrased, high escalation is *correct* — only L3 can judge equivalence. And it batches:
  21 requirements cost 2 API calls, not 21.

---

## 7. The CTA diagnosis (do this next)

**Symptom:** the CTA section of the report is wrong and reads badly.

**Verified on:** `verdicts__35029ee7f18e07bc.json` (video `5f18775d`, 12.35s, music-only) ×
brief `f697be05` (Aurelia hair).

### What the video actually contains

No CTA. No "link in bio", no purchase prompt, no engagement ask. The closing caption is
*"All you need is one routine clinically tested and proven to support hair growth"* — a
**product claim**, not a call to action.

### Cause 1 — labels are mangled, and two of them collide

`make_label()` strips punctuation, drops stopwords, and truncates to 5 words. Every CTA
requirement starts `"Deliver the Call to Action: ..."`, so the whole budget is spent on the
boilerplate prefix:

| Requirement | Label the report prints |
|---|---|
| `Deliver the Call to Action: "I'm sticking with this."` | **`Deliver Call Action I m`** |
| `Deliver the Call to Action: "I'm not gatekeeping this, link it in the bio."` | **`Deliver Call Action I m`** ← same |
| `Deliver the Call to Action: "This made a noticeable difference for my hair."` | `Deliver Call Action made noticeable` |

Two different options render identically. The group-resolution reason line then reads
*'Not the option satisfied … "Deliver Call Action I m" was (UNCERTAIN, alignment strong)'* —
naming a label that is both gibberish and ambiguous. **The same bug hits the hooks:**
`Open video hook If your` and `Open video hook My hair` each appear twice among 12 options.

**Fix:** `make_label` should strip a leading `Deliver the Call to Action:` / `Open the video
with the hook:` style prefix and label from the **quoted span**, not the imperative wrapper.
The quote is what distinguishes the options. Cheap, self-contained, no re-compile needed if
labels are derived at render time.

### Cause 2 — `group_intent` is subject-free

```
"Conclude the video with an approved call to action encouraging viewer engagement or purchase."
```

L3 judges alignment against this. *Any* closing sentence "concludes the video", so the model
rated a product claim as **`strong`** alignment — "different words, same ask and same intent."
It is not the same ask. This is exactly the failure `PHASE_7_PLAN.md` §0.1 predicted and §10
logged as carried-forward. The intent must name the **action** (ask the viewer to do
something: buy, click, follow, try), not just the position in the video.

### Cause 3 — the temporal window is invented and void

Every CTA requirement carries `window_start_expr = "duration - 15"`. **The brief says nothing
about 15 seconds anywhere** — the model invented it. The rule engine would have said
`duration - 5` (`default_cta_window`), but `WINDOW_MISSED_BY_MODEL` only fires when the model
supplies *nothing*; a model-supplied *different* number is accepted silently because
`validate_time_expr` only checks that it parses.

On a 12.35s video, `duration - 15 = -2.65` → clamped to 0 → the "CTA window" is the whole
video and the constraint does nothing.

**Fix:** when the rule engine and the model disagree on a temporal bound, flag it
(`WINDOW_DISAGREES`) the way `MODE_DISAGREES` already does — do not silently prefer the model.

### Cause 4 — 🔴 the re-run will make this WORSE, not better

The audit on disk predates the speech `absent` fix. Speech was `degraded` (1 word), so every
FAIL was blocked → UNCERTAIN → 14% coverage → band 7–50.

**After the fix, speech on this video is `absent`, so a FAIL becomes permitted.** L3 already
returns `FAIL` with `alignment: strong`. And VERDICT 1.8.0's substance promotion does this:

```python
_SUBSTANCE = {'exact': 'PASS', 'strong': 'PASS', 'partial': 'PARTIAL'}
# FAIL + strong  →  PASS,  flagged SATISFIED_IN_SUBSTANCE
```

A `cta` requirement is `polarity=required` and carries no `FAIL_FROM_POSITIVE_EVIDENCE`, so
**nothing stops the promotion.** The re-run will report the CTA as **PASS** on a video that
has no CTA — a false-positive PASS, which plan.md names the most damaging error class.

The promotion trusts **one number from one model call with no cross-check**, which is the only
place in this system that does. Everything else requires two independent things to agree, or
abstains. Options, in increasing conservatism:

1. `strong → PARTIAL`, reserve `PASS` for `exact` only. Halves the damage, keeps the intent.
2. Refuse to promote when the verdict's own `reason` asserts absence.
3. Do not promote at all — report `FAIL (literal) / strong (alignment)` side by side and let
   Phase 7 score alignment separately, the way `standing` and the decomposed mean are already
   reported side by side and never blended.

**Option 3 is most consistent with the rest of the codebase's philosophy.** Whatever you
choose, fix cause 2 as well — a promotion is only as good as the alignment it trusts.

---

## 8. What to do next, in order

1. **Rotate both API keys.** Replace with Colab secrets. (§5)
2. **Fix the substance-promotion hole** before re-running anything, or the re-run produces a
   confident wrong answer. (§7 cause 4)
3. **Fix `group_intent`** to name the action, and **`make_label`** to label from the quote.
   (§7 causes 1–2)
4. **`rm -rf work/artifacts/test_vh`** (§6.4)
5. **Set `RUN_CONTROL_AUDITS = True` in §75b and re-run.** This is the only thing standing
   between a scoring formula you reasoned your way to and one you measured. (§6.2)
6. **Re-audit the three 1.0.0 videos** at current stage versions. Closes the contradictions
   criterion for free — §75b creates the pill-organiser × hair-brief control anyway.
7. **Write the SCORE 1.1.0 fixes into `PHASE_7_PLAN.md` §9.** (§6.3)
8. Then **Phase 8**: 40 stratified labelled videos, Gradio review app, metrics harness.
   Everything after that is guesswork without it.

---

## 9. How to run it

**Environment:** Colab (hosted Gemini vision, no GPU needed) or local Windows CPU
(`requirements-local.txt`, python 3.13, `ffmpeg` via `winget install Gyan.FFmpeg`).

**Notebook:** `Phase 7/phases_1_to_7_gemini_vision.ipynb`, top to bottom. Phases 1–5 cache, so
re-runs are fast.

Key switches:

| Where | Flag | Default |
|---|---|---|
| §0.3 | `VISION_PROVIDER` | `'gemini'` (hosted). `'local'` needs the other notebook + a GPU |
| §0.3 | `USE_DRIVE` | `False` — **set `True` to keep briefs/approvals across Colab sessions** |
| §48 | `BRIEF_SOURCE` | Google Doc URL / file path / raw text |
| §48 | `RECOMPILE_BRIEF` | `False` — reuses the approved compile. Leave it. |
| §48c | `APPROVER` | your name. The §46 gate blocks the audit without it. |
| §75b | `RUN_CONTROL_AUDITS` | `False` ← **flip this** |
| §80 | `RESCORE` | `False` |

**Reading the report:** §80 prints the exact path under `ARTIFACTS`. It is
`work/artifacts/<video_hash>/report__<score_key>.html`. In Colab the browser preview shows
source, not the page — download it (`files.download(str(report['html_path']))`) and open it
locally. It is self-contained: no network, embedded proxy video, clickable timestamps.

**Diagnostics, in increasing scope:**
- §74 — full-pipeline self-check, phases 1–6. "Did this run work?"
- §74b — plan conformance. "Which of plan.md's exit criteria are actually MET?"
- §81 — Phase 7 exit criteria
- §82 — Phase 7 self-check + the combined position

---

## 10. Bug classes that have bitten more than once

Written down because they recur. Check new code against this list.

1. **`\b` after an optional group or punctuation.** Has bitten four times: `27%` never
   matching, the figures regex, both halves of `_term_hit`, and `should` inside `shoulder`.
   **Always use `(?<!\w)` / `(?!\w)` lookarounds.**
2. **`partial_ratio` is asymmetric.** rapidfuzz slides the *shorter* string over the longer,
   so the question silently flips. A record shorter than the phrase cannot be evidence of it —
   guard with `len(hay) < len(t) * 0.8`.
3. **A derived field not re-derived after its source changes.** Consensus pruned
   `requirements` and left `stats`, `sections`, `conflicts` describing the old set. Rule:
   *anything derived from `requirements` must be derived again once `requirements` changes.*
4. **A value attached to an object after it was serialised.** `hook`/`claims`/`creative_angle`/
   `standing` were attached after `write_json`, so they never reached disk — and re-ran on
   every cached audit, costing 4 LLM calls a time.
5. **A check whose denominator silently included things it should have excluded.**
   `uncertain_rate` counted `NOT_APPLICABLE` group losers and reported 12% where the real
   figure over scoring units was 75%.
6. **A check taking its authority from recall rather than from the document.** The §75 hook
   probe demanded a `disclaimer` field that spec §33 does not define.
7. **A string search through a vendored bundle tests the bundle, not the page.** The embedded
   ~4.8 MB Plotly bundle contains `customdata`, `cdn.plot` and URLs as schema keys. Check the
   figure **object**, or grep **tags**, never raw text.
8. **A config field that silently does nothing.** `ClaimsConfig.enabled` existed and was never
   read. Worse than no field — it says the module is off while it runs.
9. **A criterion that cannot fail is not a criterion.** `all()` over an empty list is `True`.

---

## 11. Measurements worth not re-deriving

- **T4 frame ceiling: 33 of 48 at *any* resolution.** Cost is not frames × pixels — there is
  ~38 tokens of per-frame overhead in the vision tower. This is why the project moved to
  hosted vision. (`tokens_per_gb` calibrated to 230, was 1200 — 5.8× too high.)
- **Brief compilation is not deterministic.** Same brief, same code, temperature 0: 21, 22, 21
  requirements across three compiles. The variance sits entirely in *prose-derived*
  requirements; enumerated lists come back identical. Mitigated by consensus + an approved
  compile being frozen until `RECOMPILE_BRIEF = True`.
- **L3 alignment variance: range 0.34 on identical inputs.** A score is reproducible against a
  specific `verdicts__*.json`, not against a video.
- **The score rests on 3–6 decisions.** 21–26 requirements → 3–6 scoring units, because a
  `one_of` group is one decision. Structural and correct. Never show two decimal places;
  always show the unit count beside the score.
- **`standing` separated on/off-brief perfectly** (6 runs, zero variance) where the alignment
  mean did not separate them at all (0.72 vs 0.68, ranges overlapping). Alignment measures
  *form within an assumed-relevant video*; standing measures *substance*.

---

## 12. Corpus on disk

| video | dur | stages present | verdict stage | brief |
|---|---|---|---|---|
| `22a6c0b6` (84s Aurelia) | 84.4s | evidence, ocr, transcript, verdicts, visual | 1.0.0 | bc455fe5 |
| `31f71cb4` | 15.7s | evidence, ocr, transcript, verdicts, visual | 1.0.0 | bc455fe5 |
| `5def3cad` | 28.0s | ocr, transcript only | — | — |
| `5f18775d` (music-only) | 12.4s | **+ score, report** | 1.10.0 | f697be05 |
| `84875b0c` (pill organiser) | 29.9s | evidence, ocr, transcript, verdicts, visual | 1.0.0 | bc455fe5 |
| `test_vh` | — | 27 stale score files | — | **delete** |

**Briefs:** 4 hashes, 12 compiled artifacts, 3 approved — `bc455fe5` ×2 at BRIEF 1.5.0
(stale), `f697be05` ×1 at 1.12.0 consensus (`e1e23cd2dd330d38_c3_8cda7165`, 24 reqs, current).

The pill-organiser × hair-brief pair (`84875b0c` × `f697be05`) is the **discrimination test**
and the contradictions-criterion fixture. It has not been run at current versions.
