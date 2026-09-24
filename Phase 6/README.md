# Phase 6 — Requirement evaluator, hook module, claims module

Everything before this produced **evidence**. This is the first phase that produces a **verdict**.

## Files

| File | What it is |
|---|---|
| `phases_1_to_6_full_pipeline.ipynb` | **Run this.** Phases 1–5 as you already have them, with Phase 6 appended. 232 cells. |
| `phase_6_evaluator.ipynb` | Phase 6 alone, 24 cells — paste under your existing notebook if you prefer |
| `phase_6_cells.py` | the same code, flat |
| `phase_6_plan.md` | the plan this was built from |

## How to run

1. **§71 — the test suite.** No GPU, no network, no API key. **75 tests.** Run it first.
2. **§72 — the audit.** Needs `TARGET`, `evidence` (Phase 5) and an **approved** compiled brief
   (Phase 4 §46). It warms the embedding model, then evaluates.
3. **§73 — exit criteria**, in the same shape as §51 and §62.

If the brief is not approved, §72 stops and tells you what to run. That gate is the point of §46:
a verdict derived from a requirement set nobody checked is worse than no verdict.

## Claims / TikTok-policy screening is OFF

`ClaimsConfig.enabled = False`. Advertising-policy screening is not the current goal, and a module
nobody is acting on is noise in every report it appears in.

**This is not the same as a `forbidden` requirement in a brief.** If a brief says *"do not make
medical claims"*, that is **brief compliance** — it still runs, through `l1_forbidden`, like any
other requirement. What is off is the standalone policy scan that ran whether or not the brief asked
for it.

When it is off, the output says so explicitly and states that **silence is not a clean bill of
health** — nothing was examined, so nothing can be concluded.

```python
P6 = replace(P6, claims=replace(P6.claims, enabled=True))    # to bring it back
```

The code stays, still tuned for recall, for when it matters.

> Found while making this change: `ClaimsConfig.enabled` already existed and **did nothing** —
> `evaluate_claims` never read it. A config field that silently has no effect is worse than no
> field, because it tells you the module is off while it runs anyway.

## The three guarantees

**1. A FAIL asserts something.** Every FAIL is built by one function, `_fail_or_uncertain()`, which
consults `can_fail_on()` first. There is no second path. If the modality was degraded or never ran,
the answer is UNCERTAIN.

There are two kinds of FAIL and only one needs that gate:

- **from absence** — *"we looked and it is not there"*. Needs every modality that could have carried
  the evidence to have run cleanly.
- **from presence** — *"we found the forbidden thing"*. Grounded in evidence we have, and checked
  against the health of the modality that carried it. Flagged `FAIL_FROM_POSITIVE_EVIDENCE`.

**2. Only provided evidence IDs are citable.** Checked in code after every model response. A verdict
citing an unknown ID — or a real ID belonging to a *different* requirement — is rejected, retried
once, then downgraded to UNCERTAIN. It does not depend on the model behaving.

**3. `INCONCLUSIVE` never reaches a verdict.** It is a routing signal meaning *escalate*. Telling a
user that our cheap check did not fire is not a fact about their video.

## The escalation ladder

| Layer | Cost | Does |
|---|---|---|
| **L1** | free | `rapidfuzz` phrase match, tolerance-aware timestamp arithmetic, forbidden gazetteer, enum presence |
| **L2** | ~130 MB, CPU | `bge-small-en-v1.5`, two thresholds, **never competes with Qwen for VRAM** |
| **L3** | seconds / cents | text-only adjudication, batched per video, IDs validated |

`warm_l2()` installs and loads the embedding model at a **visible** point. It is not done lazily
inside the evaluation loop, where a four-minute pip install looks like a hang.

L3 uses Phase 4's tested ladder: **Gemini free tier → OpenAI paid → rules**, spend-controlled.

## Brief compilation is not reproducible — and the approval now knows it

Measured: the **same brief, same code, temperature 0.0**, compiled three times:

```
run 1:  9 requirements        run 1:  7 requirements   (a later triple)
run 2:  9 requirements        run 2: 10 requirements
run 3: 25 requirements        run 3:  9 requirements
```

Only **2 of 35** requirements appeared in all three of the first triple. The 25-run enumerated every
hook individually; the others collapsed them into *"use one of the approved hook concepts"*. The
model cannot decide whether to enumerate or summarise, and both are defensible readings of the
document.

This matters more than any single bug: §46 exists so a human approves a requirement set before any
video is judged against it. **If recompiling produces a different set, the approval describes
something that no longer exists.** It also explains a symptom that looked like an improvement — one
recompile produced the vague *"use one of the provided hook concepts"*, which **PASSed trivially**
where the specific version had correctly FAILed.

**Fix 1 — an approval binds to the set it was given.** `requirements_digest()` fingerprints the
fields a reviewer actually checks (wording, evidence mode, polarity, timing, grouping — *not*
ordinal or confidence). `approve_brief` records it; `requirements_for_audit` refuses a superseded
approval with a message distinct from never-approved. An older artifact without a digest is still
honoured and labelled legacy.

**Fix 2 — `compile_brief_consensus(text, runs=3)`.** Compiles N times, keeps what a **majority** of
runs agree on, and reports the rest as `COMPILE_UNSTABLE` with per-run counts. Opt-in; `compile_brief`
is unchanged and still caches by content, so normal use costs nothing extra.

> It does not make the model deterministic. It makes the disagreement **visible and bounded** —
> a requirement that appears in only one run of three is reported, not silently included or dropped.

Unanimity was the original default and measured out at **2 kept of 35**, which is useless, so the
default is a majority. Raise `keep_threshold` to `1.0` if you would rather lose a real requirement
than admit an uncertain one.

## Two bugs this found on real data

**`'heal'` matched `'healthy'`.** `partial_ratio` scores a substring 100, so *"your hair looks so
healthy and shiny"* was reported as a medical claim. Short single words now match on word boundaries
with inflections — `heal` catches *heals/healed/healing* but not *healthy*. Applied to the forbidden
gazetteer, the hint ranker, and the claims module.

**A FAIL bypassed the health gate.** Finding forbidden content is positive evidence, so the
mode-wide conjunction should not apply — but the modality that carried it still has to be healthy.
Both cases are now explicit, tested, and distinguished in §73.

## Thresholds are placeholders — and now we know by how much

`high_threshold_PLACEHOLDER` and `low_threshold_PLACEHOLDER` are named that way on purpose.
Calibration is Phase 8, against a labelled benchmark.

**Measured** on 28 real requirements from both compiled briefs against real evidence:

```
min 0.461   p25 0.513   median 0.551   p75 0.600   max 0.688   mean 0.556

>= high (0.72)  :  0  (0%)   -> would PASS at L2
<= low  (0.35)  :  0  (0%)   -> would FAIL at L2
in between      : 28 (100%)  -> escalate to L3
```

Both thresholds sit **outside the entire observed range**, so L2 currently decides nothing.

**Do not just lower `high` to 0.60.** In the same measurement the single highest score, 0.688, was a
*wrong* match — *"do your favourite hairstyle to camera"* against *"capsules a day is all you
need"* — while a *correct* one, *"mention hydration and barrier support"* against *"protective
barrier. AURELTA"*, scored 0.632. The ranking does not separate right from wrong on this data, so
moving the line trades *"escalates everything"* for *"passes things wrongly"*, which is worse.

The compression has a visible cause: evidence records are individually tiny OCR fragments
(`"more"`, `"shine to your hair"`), and bge-small scores any two short English strings about hair
around 0.5. Fixing that is a **retrieval** change — more context per passage — not a threshold
change, and it belongs with the Phase 8 calibration that will have labels to check it against.

**The escalation percentage overstates the cost.** L3 batches: 21 requirements cost **2 API calls**,
not 21. The `L3 <= 30%` exit criterion is a Phase 8 target, and until then the honest reading is
"L1 answers what arithmetic can, and the LLM does the rest in two calls".

## What to watch

| Signal | Threshold | Means |
|---|---|---|
| UNCERTAIN rate | > ~20% | the **evidence layer** is the problem, not the evaluator |
| L3 share | > 30% | L1/L2 too timid, or `match_hints` are poor |
| fabricated IDs | **any** | hard failure, asserted in the stage |

## Verification

```
P6 unit          75/75, no GPU/network/model
P6 on real data  both compiled briefs, both real evidence files
check_p6         no shadowing; 15 Phase 1-5 helpers reused, not reimplemented
order / ast      runs top to bottom on a fresh kernel
```

## Still manual — only you can close these

- 5 scripts with deliberately planted claims, all flagged
- `speech_only` vs `ocr_only` verified on a burned-in-caption video
- one video against 3 briefs, confirming only this stage re-runs
- your own hook self-agreement, measured on 10 videos twice a week apart
