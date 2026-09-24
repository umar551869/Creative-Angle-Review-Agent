# How to use `plan.md` from here

**Written:** 2026-09-22
**Subject:** `plan.md` (1,275 lines, last touched 2026-09-10)
**Purpose:** `plan.md` was the build order for Phases 0–12. Seven of those phases are now
built. This file says which parts of it are still load-bearing, which parts are spent, and
where it has quietly stopped being true — so that the next person to open it knows which
half to trust.

Companion to [`PROJECT_STATE.md`](PROJECT_STATE.md), which says where the *code* stands.
This says where the *plan* stands.

---

## 1. The one-line answer

`plan.md` is no longer a plan. It is two documents sharing a file: a **record of work
already done** (§0–§7, lines 230–971, ~58% of the file) and an **unexecuted plan for what
comes next** (§8 onward plus the cross-cutting sections, ~40%).

Only the second half is still a plan. The first half is history that disagrees in four
places with what actually got built.

**Do not read it front to back.** Read §2 of this file, then jump.

---

## 2. Section map — spent, live, or stale

| `plan.md` | Lines | State | What to do with it |
|---|---|---|---|
| §0 How to read | 10–28 | Live | Still the contract for what a phase description contains |
| §1 Reality check / deviations | 31–63 | **Stale** | Written for Colab + local Qwen. Superseded — see §5 below |
| §2 Eight resource levers | 66–78 | Live | Lever 1 (content-hash caching) is the thing that actually held |
| §3 Architecture diagram | 81–141 | Live *as intent* | The stage split (1–5 video, 4 brief, 6–7 join) held exactly. Stage numbering differs from the notebook's §-numbering — see PROJECT_STATE §2 |
| §4.1 Repo layout | 147–186 | **Ignored** | "Non-negotiable." It was negotiated. See §5 |
| §4.2 Drive layout | 188–205 | Live | `work/artifacts/{video_hash}/…` matches this closely |
| §4.3 Stage contract | 207–226 | **Live and load-bearing** | The cache-key discipline. Still the rule. See §4 below |
| **Phase 0** Environment | 230–338 | Spent | Bake-off decided, env settled |
| **Phase 1** Preprocessing | 341–457 | Spent | Built |
| **Phase 2** ASR + OCR | 460–567 | Spent | Built |
| **Milestone A** | 570–597 | Spent | Built |
| **Phase 3** Qwen3-VL | 600–724 | **Stale** | Overtaken by hosted Gemini. ~80 lines of dead VRAM arithmetic |
| **Phase 4** Brief compiler | 728–786 | Spent | Built, and went further (consensus compile) |
| **Phase 5** Evidence normalizer | 789–833 | Spent | Built |
| **Phase 6** Evaluator/hook/claims | 836–922 | Spent, **two criteria wrong** | See §5 |
| **Phase 7** Scoring + report | 925–969 | Spent | Built; one exit criterion open (§75b) |
| **Phase 8** Benchmark | **973–1032** | **★ LIVE — this is where you are** | See §3 |
| **Phase 9** Optimization | 1035–1072 | **Live**, minus vLLM | See §3 |
| **Phase 10** Productionization | 1076–1089 | Live, gated | Demand-driven. Not yet |
| **Phase 11** Detectors | 1093–1104 | Live, gated | Trigger comes *from* Phase 8 metrics |
| **Phase 12** RAG / fine-tuning | 1108–1124 | Live, gated | Preconditions unmet by design |
| §13 Cross-cutting | 1128–1155 | Live | Mostly implemented; keep as the statement of intent |
| §14 Schedule | 1159–1180 | **Void** | See §6 |
| §15 Decision log | 1184–1205 | Live | Needs four rows updated — §5 |
| §16 Risk register | 1209–1224 | Live | Several risks have since fired. Worth re-scoring |
| §17 What NOT to build | 1228–1243 | **Live and valuable** | Has held the line. Keep |
| §18 Definition of done | 1246–1264 | Live | Still the target |

---

## 3. The parts to actually use now

### 3.1 Phase 8 — `plan.md` lines 973–1032

**This is the most valuable unexecuted section in the project**, and nothing duplicates it.
`PROJECT_STATE.md` §8 item 8 compresses the whole phase to one sentence: *"40 stratified
labelled videos, Gradio review app, metrics harness."* The detail is only here.

Use it for four things specifically:

1. **The stratification list** (line 985). Eighteen named hard cases — fast cuts, captions
   occluding the product, speech/visual disagreement, CTA only in text, CTA only in speech,
   paraphrased-rather-than-literal required phrases. That list was written before you knew
   the CTA bug existed and it already names the shape of it. Collect against this list, not
   against whatever videos are to hand.
2. **"Hard cases are worth ~5× normal cases"** (line 987). This is the collection budget rule.
3. **Self-consistency measurement** (line 992): re-label 10 videos a week later. That number
   is the ceiling on any accuracy claim the system can make, and it belongs in the report.
   Nothing else in the project records this instruction.
4. **The metrics harness spec** (lines 1004–1022). Three levels — model capability,
   requirement accuracy, product usefulness. The actionable item is the
   **per-requirement-type F1 breakdown** and **false-positive PASS as a first-class metric**,
   which is the error class the CTA bug produces.

One amendment before you use it: line 997's pre-cut 3-second evidence clips are a good idea
independent of Gradio, because the HTML report already does clickable seeking. Treat clip
pre-cutting as a review-speed decision, not a Gradio workaround.

### 3.2 Phase 9 — lines 1035–1072

Use the **ablation list and the protocol** (line 1055: change one variable, run the full
benchmark, record to `runs/`, never eyeball two videos). Skip:

- Ablation 5 (4B/8B/NF4 model ladder) — moot on hosted vision
- Ablation 6 (Architecture A vs B) — moot, the frame list is now the only path
- The entire vLLM subsection (1057–1060) — moot

Ablations 1 (frame budget), 2 (transcript+OCR context in the prompt), 3 (sampling strategy),
4 (hook window density), 8 (L2 thresholds) and 10 (prompt versions) are all still real
questions. **Ablation 8 needs re-framing** — see §5.

### 3.3 §17 What NOT to build — lines 1228–1243

This table has done real work. It is why there is no scraper, no Postgres, no Qdrant, no
YOLO and no fine-tuning in a project that reached Phase 7 in under two weeks. Keep reading it
before adding anything.

### 3.4 §4.3 The stage contract — lines 207–226

Still the rule, and still being broken. Line 224: *"Never mutate a cached artifact. Bump the
version instead."* PROJECT_STATE §3 records that this has already bitten once — two SCORE
fixes landed without a version bump and §80 served a stale artifact while the tests passed.

The rule is right. The enforcement is the gap.

---

## 4. How to use it operationally

Three concrete habits, in order of value:

**Use it as the authority for principles, not for methods.** `plan.md`'s framings are
holding up better than its technical choices. "False-positive PASS is the most damaging
error class" (line 1015, 1223) is cited three times in `PROJECT_STATE.md` as the reason for
a design decision, most recently to argue that the substance-promotion hole must be closed
before any re-run. That kind of use is exactly right. Its VRAM tables are not.

**Quote it at yourself when scope creeps.** §17 and the risk register line 1221 ("Scope creep
into FastAPI/Next.js/Qdrant early — High/High — Mitigation: *this plan*") are the project's
immune system.

**Treat every unmet exit criterion as a question, not a task.** Two of Phase 6's criteria
turned out to be wrong rather than unmet (§5 below). Before working to satisfy a criterion
in a document written before the thing was built, check that the criterion still describes
something you want.

---

## 5. Where it has stopped being true

Your own rule, from `PROJECT_STATE.md` §6.3:

> *a plan that does not record where the build disagreed with it is a plan that quietly
> stops being true.*

That was written about `PHASE_7_PLAN.md`. It applies to `plan.md` too, and nobody has said so
until now. Four disagreements, none of them recorded in the file:

### 5.1 Hosted vision replaced local Qwen3-VL

`plan.md` §15 decision log: *"VLM — Qwen3-VL-4B-Instruct fp16 (T4) / bf16 (L4+)."*
Reality: hosted Gemini, `VISION_PROVIDER='gemini'`.

Trigger, from `PROJECT_STATE.md` §11: **the T4 frame ceiling is 33 of 48 at *any*
resolution** — there is ~38 tokens of per-frame overhead in the vision tower, so cost is not
frames × pixels. The `tokens_per_gb` estimate was calibrated at 230 against an assumed 1200,
5.8× too high.

Consequence: `plan.md` lines 615–634 (the VRAM table), 686–697 (the 4B vs 8B bake-off),
1044–1050 (model ablations) and 1057–1060 (vLLM) are dead. Leave them for the archaeology,
but nobody should plan against them.

### 5.2 Notebooks won over a repo

`plan.md` §4.1, line 149: *"Non-negotiable."* Reality: 254-cell notebooks are the source of
truth. `Phase 7/cells/*.py` is a partial concession — the cells exist as reviewable files —
but the notebook is what runs.

This deserves recording precisely because it was the most emphatic instruction in the
document. It is not obviously wrong: the phases cache, so notebook re-runs are cheap, and
the project moved faster than the plan by roughly 10×. But the costs `plan.md` predicted
(line 149: cannot be tested, versioned meaningfully, diffed, or migrated) are real and
partly paid — the §74b criteria are transcribed into a cell rather than parsed, and
PROJECT_STATE §10 lists nine recurring bug classes that a test suite would have caught
earlier.

**Decide it explicitly rather than by drift.** Either write it down as a deliberate
reversal, or start extracting to `auditor/`.

### 5.3 Two Phase 6 exit criteria are wrong, not unmet

| Criterion | `plan.md` | Reality |
|---|---|---|
| L3 escalation | line 918: *"L3 handles < 30% of requirements"* | ~96%. PROJECT_STATE §6.5: on a brief written as exact scripts the creator paraphrased, **high escalation is correct** — only L3 can judge equivalence. And it batches: 21 requirements cost 2 API calls |
| L2 thresholds | lines 856–859: *"threshold calibrated on the benchmark"*, and ablation 8 (line 1051): *"sweep against the benchmark"* | The ranking does not separate right from wrong at all. Observed range 0.46–0.69, mean 0.556; the **highest** score (0.688) was a *wrong* match and a correct one scored 0.632. PROJECT_STATE §6.5: the fix is a **retrieval** change (more context per passage), not a threshold change |

The second one matters most: following `plan.md` here would send you to sweep a parameter
that cannot work. **Amend ablation 8 to read "L2 retrieval context," not "L2 thresholds."**

### 5.4 Phase 7 grew concepts `plan.md` never anticipated

None of these appear anywhere in the file:

- **The relevance gate** (`relevance_of`, `RELEVANCE_SCORABLE`, `BAND_OFF_BRIEF`) — two
  questions in order: is this video addressing this brief at all, then how closely did it
  follow it. Fails open.
- **`band_basis`** — below 90% coverage the grade reads from the pessimistic end. `plan.md`
  line 942 got the *band* right (pessimistic/optimistic/coverage) but never said which end
  the badge reads from, and a live run showed 75–100 at 75% coverage badged `APPROVED`.
- **`inferred_units`** — `resolve_dimension` reading the brief's own group names.
- **Consensus brief compilation** — three runs, majority. `plan.md` §4 assumed one call,
  cached. PROJECT_STATE §11 records why: same brief, same code, temperature 0 → 21, 22, 21
  requirements.
- **Scoring units** — 21–26 requirements collapse to 3–6 decisions, because a `one_of` group
  is one decision. `plan.md`'s scoring section (line 934) implicitly assumes
  requirement-level arithmetic.
- **Substance promotion** (`_SUBSTANCE`, `FAIL + strong → PASS`) — the open hole in
  PROJECT_STATE §7 cause 4.

`plan.md` contributes nothing to the CTA diagnosis currently at the top of the queue. That is
not a criticism of the plan; it is the expected shape of a plan meeting a real build. It does
mean **`plan.md` is not the document to open when working on Phases 6–7 defects** — that is
`PHASE_1_6_FINALISATION.md` and `PROJECT_STATE.md` §7.

---

## 6. The schedule is void, with one exception

`plan.md` §14 budgets 14 weeks to a measured v1.0. Phases 0–7 took roughly 12 days. Every
estimate in that table is noise.

**The exception is Phase 8**, and it matters. Phase 8 is ~5 hours of human labeling plus
review-app build and metrics wiring. It is the one phase whose cost is *human-hours*, not
code generation, so it will not compress the way the previous seven did. `plan.md`'s
**1.5 weeks is approximately right** — probably the only estimate in §14 that still is.

Do not let Phase 0–7 velocity set the expectation for it.

---

## 7. A drift risk worth naming

`Phase 6/phase_conformance_cell.py` (§74b) answers *"which of plan.md's stated exit criteria
are actually MET?"* — but it **transcribes** those criteria into Python rather than parsing
`plan.md`. The file is not a live oracle; it is a hand-copy.

Two consequences:

1. When `plan.md` is stale — as it is on the L3 <30% criterion — §74b tests against the stale
   version and reports a FAIL that should be a repeal.
2. When `plan.md` is amended, §74b does not notice. Nothing links them.

This is bug class 6 from `PROJECT_STATE.md` §10 — *"a check taking its authority from recall
rather than from the document"* — one level up, applied to the plan rather than to the spec.

**Minimum fix:** when a criterion in §74b is changed or repealed, edit `plan.md` in the same
commit, and vice versa. Same discipline as the stage-version rule in PROJECT_STATE §3.

---

## 8. Recommended action

Do not rewrite `plan.md` and do not delete it. Add the block below to the top of the file,
immediately after the header. It costs ~25 lines and restores the document's trustworthiness
without touching the 40% that is still good.

```markdown
> ## ⚠ Status as of 2026-09-22 — read before using this document
>
> Phases 0–7 are **built**. Phase 8 has **not started**. This document is therefore half
> history and half plan. See [PLAN_MD_USAGE.md](PLAN_MD_USAGE.md) for a section-by-section
> map of which is which; see [PROJECT_STATE.md](PROJECT_STATE.md) for where the code stands.
>
> **Four places where the build knowingly diverged from this plan:**
>
> 1. **Vision is hosted (Gemini), not local Qwen3-VL.** Trigger: the T4 frame ceiling is
>    33 of 48 at *any* resolution (~38 tokens/frame of vision-tower overhead). This voids
>    §3.1's VRAM table, §3.7's 4B-vs-8B bake-off, Phase 9 ablations 5 and 6, and the vLLM
>    subsection.
> 2. **The build lives in notebooks, not the §4.1 repo layout.** §4.1 called this
>    non-negotiable; it was reversed. `Phase 7/cells/*.py` is a partial concession. Not yet
>    recorded as a deliberate decision — it should be, or reversed back.
> 3. **Phase 6's L3 "< 30% escalation" criterion is repealed, not unmet.** ~96% escalation is
>    correct on script-style briefs the creator paraphrased; only L3 can judge equivalence,
>    and it batches (21 requirements → 2 API calls).
> 4. **L2 is a retrieval problem, not a threshold problem.** Observed similarity range
>    0.46–0.69; the highest score (0.688) was a *wrong* match. Phase 9 ablation 8 should read
>    "L2 retrieval context," not "L2 thresholds."
>
> **Not anticipated by this plan, and now central:** the relevance gate / `standing`,
> `band_basis`, `inferred_units`, consensus brief compilation, scoring units (21–26
> requirements → 3–6 decisions), and substance promotion. For Phase 6–7 defects read
> `PHASE_1_6_FINALISATION.md` and `PROJECT_STATE.md` §7, not this file.
>
> **Still fully live:** §8 (benchmark), §9 (ablations 1–4, 8, 10), §13, §15, §16, §17, §18.
```

Then work from `plan.md` §8.

---

## 9. Summary

| Question | Answer |
|---|---|
| Is `plan.md` still useful? | Yes — about 40% of it, and that 40% is the part you have not spent |
| What is the single best section? | §8, Phase 8 benchmark (lines 973–1032). Nothing duplicates it |
| What should I stop reading? | §0–§7 phase bodies, except as history. Phase 3 especially |
| What should I stop believing? | The schedule, the VRAM tables, the L3 <30% target, the L2 threshold framing |
| What has held up best? | The stage contract (§4.3), the "what NOT to build" table (§17), and the false-positive-PASS framing |
| Does it help with the current bug? | No. That is `PROJECT_STATE.md` §7 |
| What is the risk if I do nothing? | §74b keeps testing against a document that is wrong in two places, and reports it as a failure rather than a repeal |
