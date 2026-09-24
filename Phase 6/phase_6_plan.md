# Phase 6 — Requirement Evaluator, Hook Module, Claims Module

**The plan.** Written before any code, so the decisions are visible and arguable.

`plan.md` §6 allots two weeks and calls this *"where product value is actually created."* Everything
built so far produces **evidence**. Phase 6 is the first phase that produces a **verdict** — and a
verdict is a thing a person can disagree with, which is exactly why it has to be defensible.

---

## 1. Where we are

Five phases are built, run on real videos, and verified.

| Phase | What it produces | State |
|---|---|---|
| **1** Preprocess | frame manifest, audio, shot boundaries, `media_meta` | ✅ run on 3 videos |
| **2** ASR + OCR | `transcript__*.json`, `ocr__*.json` with independence verdicts | ✅ |
| **3** Qwen3-VL | `visual__*.json` — closed-enum events with frame-derived timestamps | ✅ (degrades on a T4) |
| **4** Brief compiler | `Requirement[]` from a Google Doc, human-approved | ✅ on the AURELIA brief |
| **5** Evidence normaliser | one timeline, `modality_health`, `coverage`, `aggregates` | ✅ 18/18 exit criteria, 3 videos |

**Verification currently standing:** 110 Phase 5 unit tests, plus 17 other harnesses — real-artifact
runs, field-contract checks, an exhaustive ladder proof (21,636 cases), mutation tests on the guards,
and a top-to-bottom execution-order check on all three notebooks. Everything green.

### What Phase 5 hands over, verified against real evidence

```
build_evidence(video, tr, ocr, vis)        one timeline, cached by all three upstream keys
evidence_for(video_hash, cfg, video)       fetch by exact key, no rebuild
load_records(evidence)                     dicts -> EvidenceRecord objects
speech_in_window(recs, t0, t1)             tolerance-aware
text_in_window(recs, t0, t1, mode)         mode='ocr_only' filters to confirmed_independent
visual_in_window(recs, t0, t1, types)      visual events
coverage_in_window(cov, t0, t1, modality)  did we even look here?
can_fail_on(health, modality)              may a FAIL be asserted at all?
record.can_satisfy(evidence_mode)          per-record policy, decided in Phase 5
```

A record carries: `id, modality, type, start_seconds, end_seconds, start_tolerance_seconds,
end_tolerance_seconds, time_tolerance_seconds, confidence, confidence_kind, independence,
satisfies_modes, source, source_stage_key, frame_ids, flags, linked_ids, merged_from, words`.

### What Phase 4 hands over

`Requirement` — the other half of the join:

```
id, ordinal, label, requirement, type, priority, weight, polarity, evidence_mode,
machine_checkable, group, group_mode, group_label,
deadline_seconds, window_start_seconds, window_end_seconds,
window_start_expr, window_end_expr,          # symbolic, resolved per video
match_hints[], acceptance_criteria[], forbidden_evidence[], claim_classes[],
source, brief_span
```

**Phase 6 is the join of those two objects.** Everything it needs already exists and is typed.

### Three facts from the real runs that shape this phase

1. **`visual` is `degraded=True` on every video so far.** The T4 walks the OOM ladder. So
   `can_fail_on('visual')` is `False` and *no visual requirement can FAIL yet* — it can only PASS or
   go UNCERTAIN. Phase 6 must be correct under that constraint, not assume it away.
2. **OCR independence is mostly `unknown`.** On the 41 s video, **1 of 48** intervals was
   `confirmed_independent`. So `ocr_only` requirements will be near-unanswerable on speech-heavy
   videos — correctly, per `product.md` §37, but the report must explain *why* rather than look broken.
3. **Visual tolerances are wide** — ±1.8 s at best, ±5.0 s when the ladder degrades. Any deadline
   arithmetic must use the tolerance, never the bare timestamp.

**We are ready for Phase 6.**

---

## 2. What Phase 6 must produce

For every requirement, for every video:

```json
{
  "requirement_id": "req_a1b2c3",
  "status": "PASS | PARTIAL | FAIL | UNCERTAIN | NOT_APPLICABLE",
  "evidence_ids": ["ev_1ea03ecbc5", "ev_77f0a2b118"],
  "reason": "one sentence a human can check against the cited evidence",
  "layer": "L1 | L2 | L3",
  "confidence": 0.0,
  "confidence_kind": "derived | llm_self_report | none",
  "flags": ["TOLERANCE_STRADDLES_DEADLINE"]
}
```

Plus two dedicated modules that are not requirement-shaped: the **hook module** (§33) and the
**claims module** (§38).

### Status semantics — `plan.md` §6.2, enforced not documented

| Status | Means | Precondition |
|---|---|---|
| `PASS` | evidence satisfies it, cited | ≥1 citable record |
| `PARTIAL` | satisfied weakly, late, or in only one of two required modalities | narrowly defined, see §4.4 |
| `FAIL` | evidence contradicts, **or** required evidence is confidently absent | **`can_fail_on(modality)` is True** |
| `UNCERTAIN` | insufficient or degraded evidence | the default when in doubt |
| `NOT_APPLICABLE` | requirement does not apply to this video | e.g. an unselected `one_of` option |

> **The one rule that decides whether anyone trusts this system:** a `FAIL` asserts something, so it
> needs positive grounds. If the modality was degraded or never ran, it is `UNCERTAIN`. This is not
> advisory — `can_fail_on()` is a function call, and the evaluator will be unable to emit FAIL
> without it.

`INCONCLUSIVE` is **internal routing only** and must never reach a report. Conflating "the cheap
check didn't fire" with "we genuinely don't know" is the classic bug here, and it surfaces as
unexplainable FAILs.

---

## 3. Architecture — the three-layer escalation ladder

Cost-ordered. Each layer answers what it can and escalates the rest.

```
            ┌──────────────────────────────────────────────────┐
  L1        │ deterministic: rapidfuzz, timestamp arithmetic,   │  free
  ~50-60%   │ gazetteer, closed-enum presence                   │  0 ms
            └───────────────────────┬──────────────────────────┘
                        INCONCLUSIVE │
            ┌───────────────────────▼──────────────────────────┐
  L2        │ embeddings: bge-small-en-v1.5, cosine, TWO        │  ~130 MB
  ~25%      │ thresholds (high -> PASS, low -> FAIL, else up)   │  ~10 ms
            └───────────────────────┬──────────────────────────┘
                        between thresholds │
            ┌───────────────────────▼──────────────────────────┐
  L3        │ LLM adjudication, TEXT ONLY, top-k candidates,    │  seconds
  ~15-25%   │ batched per video, IDs validated in code          │  or cents
            └──────────────────────────────────────────────────┘
```

**Instrument the escalation rate at every layer.** It is a direct measure of how much money and GPU
semantics is costing, and it is the first number to look at when something feels slow or expensive.

### L1 — deterministic

Handles roughly half of requirements at zero cost.

- **Phrase matching** — `rapidfuzz.partial_ratio` at ~85 over normalised transcript and OCR text,
  driven by `match_hints`. rapidfuzz is *already a dependency* (Phase 2 uses it for caption
  cross-checking), so this costs nothing new.
- **Timestamp arithmetic** — `product_first_seen <= deadline_seconds`,
  `cta.start >= duration - 5`. **Tolerance-aware**: if
  `first_seen - tolerance <= deadline <= first_seen + tolerance` the deadline sits *inside* the
  uncertainty and the answer is UNCERTAIN, not PASS or FAIL. Flag it `TOLERANCE_STRADDLES_DEADLINE`.
  This is why Phase 5 spent so long getting tolerances honest.
- **Symbolic window resolution** — `window_start_expr = "duration - 5"` evaluated per video with the
  existing recursive-descent parser. **Never `eval()`.**
- **Forbidden-phrase gazetteer** — `forbidden_evidence[]` from the brief, plus the global list.
- **Closed-enum presence** — does any record have `type == 'product_held'`?

L1 emits `PASS`, `FAIL`, or `INCONCLUSIVE`.

### L2 — embedding similarity

- **Model: `BAAI/bge-small-en-v1.5`** — 133 MB, 384-dim, runs on CPU in milliseconds. Chosen over
  `all-MiniLM-L6-v2` for retrieval quality and over `bge-base` for size. It must not compete with
  Qwen3-VL for VRAM, so **pin it to CPU.**
- **Respect the asymmetric prefix convention.** BGE expects
  `"Represent this sentence for searching relevant passages: "` on the *query* side only. Applying
  it to both sides, or neither, silently degrades retrieval. Requirement text is the query;
  evidence records are passages.
- **Two thresholds, not one.** `>= high` → PASS with the cited sentence. `<= low` → FAIL.
  In between → escalate. A single threshold forces a coin-flip on exactly the cases that need L3.
- **Thresholds are placeholders until Phase 8 calibrates them on the benchmark.** They will be
  named `*_PLACEHOLDER` in config so nobody mistakes them for measured values.
- Embeddings are **cached per evidence file** — same content hash, same vectors, computed once.

### L3 — LLM adjudication

- **Text only. No frames.** Phase 3 already looked at the pixels; re-sending them is the most
  expensive possible way to re-ask a question already answered.
- **Retrieve, then adjudicate.** Input is the requirement, its `acceptance_criteria`, and the
  **top 8–10** candidate records from L1/L2 — never the whole evidence set. Retrieve generously:
  recall matters more than precision here, because the LLM is the filter.
- **Batch every escalated requirement for one video into a single call** where the prompt fits. One
  call per requirement is ~20× the cost for no accuracy gain.
- **Hard constraint: the model may only cite evidence IDs it was given.** Validated in code; any
  response citing an unknown ID is rejected and retried once, then downgraded to UNCERTAIN. This is
  the anti-hallucination guarantee, and it is *deterministically enforceable* — which is the only
  kind of guarantee worth having.
- Output: `status`, `evidence_ids[]`, `reason`, `confidence` — with `confidence_kind:
  'llm_self_report'`, so nothing downstream averages it against an OCR recognition score.

---

## 4. Which LLM for L3 — the decision

This is the one genuinely open choice in the phase, so here is the full reasoning.

### What the job actually is

L3 is **not** a hard task. It is short-context, text-only, structured-output classification:

> Given a requirement, its acceptance criteria, and 8 candidate sentences — does the evidence satisfy
> it? Answer with a status, the IDs you used, and one sentence of reasoning.

Prompts will be ~1–3k tokens; outputs ~200–400 tokens. It needs *reliable JSON and sound
short-chain reasoning*, not frontier capability. That matters, because it means the cheap options
are genuinely viable rather than a compromise.

### Option A — open-source, local

Two sub-options, and they are very different:

**A1. Reuse the resident Qwen3-VL-4B in text-only mode.** It is already loaded.

- ✅ **Zero marginal cost, zero new VRAM, no network, no key, fully offline and reproducible.**
- ✅ Determinism: the same weights give the same answer forever. A hosted model can change under you.
- ❌ **It competes with nothing — but it is already the thing that OOMs.** Every video's Phase 3 run
  walks the ladder on a T4. Adding L3 inference in the same session is more pressure on the resource
  that is already the bottleneck.
- ❌ **4B is weak at exactly the judgement L3 exists for.** *"Does 'my skin feels less tight' satisfy
  'mention improved hydration'?"* is a semantic call where a 4B model is unreliable — and the whole
  point of escalating is that L1 and L2 already failed.
- ❌ It is a **vision** model used for text; instruction-following on structured text tasks is not
  what it was tuned for.
- ❌ **Slow on a T4.** Measured VLM inference is 70 s at 12 frames. Text-only is faster, but a batched
  L3 call is still tens of seconds per video, on top of everything else.

**A2. A dedicated small text model (Qwen2.5-7B-Instruct, Llama-3.1-8B-Instruct).**

- ✅ Genuinely better at this task than the 4B VLM.
- ❌ **Does not fit.** The T4 has 16 GB; Qwen3-VL-4B in fp16 already uses ~8 GB. A 7–8B model in
  4-bit is ~5 GB *plus* activations, and you would be loading and unloading models between phases —
  219 s per load, measured. This is a non-starter on current hardware.

### Option B — hosted API

**The infrastructure already exists.** Phase 4's `HostedLLMBackend` is a provider ladder with spend
control, and it is tested:

```
Gemini (free tier)  gemini-flash-latest -> gemini-pro-latest -> gemini-flash-lite-latest
   |  404 = retired, 429 = out of quota -> next model.  503 -> retry same model (3x, free)
   v  only after the whole Gemini ladder is exhausted
OpenAI (PAID)       gpt-4.1-mini, tried ONCE, never retried, hard-capped by paid_call_budget
   |
   v  everything failed
RuleBasedBackend    degraded, flagged BACKEND_DEGRADED, never silent
```

- ✅ **Free at our volume.** Gemini Flash's free tier comfortably covers one batched call per video.
- ✅ **Much stronger at the semantic call** than a local 4B.
- ✅ **Costs no VRAM**, so it cannot make the Phase 3 OOM worse.
- ✅ **Already built, already spend-controlled, already has a rules fallback.** Reusing it is a
  day of work, not a week.
- ❌ **Network dependency.** Colab drops connections; the ladder must treat that as degradation, not
  crash.
- ❌ **Non-determinism across time.** `-latest` aliases move. A re-run months later may differ — which
  is why the model name and prompt version go into the cache key and the artifact.
- ❌ **Data leaves the machine.** Transcript text and brief text go to Google. Fine for this project;
  a blocker for a client under NDA. **Flag this explicitly before any commercial use.**
- ❌ **Rate limits** on the free tier. Batching per video (not per requirement) keeps us far under.

### Decision

> **Use the hosted ladder (Gemini free tier → OpenAI paid → rules), exactly as Phase 4 does. Keep
> local Qwen3-VL text-only as a selectable backend behind the same interface, and make `rules` the
> floor that always works.**

The reasoning, in one line: **L3 is a small share of a small workload, the hosted path is free at our
volume, strictly better at the task, and costs zero VRAM on a GPU that is already our binding
constraint** — and the ladder that makes it safe is already written and tested.

**The escape hatch matters more than the default.** Because every backend sits behind one interface,
switching to fully-local is a config change, not a rewrite. If an NDA arrives, `backend='local'`
works the same day.

| | hosted (chosen) | local 4B | local 7B |
|---|---|---|---|
| Cost | free at our volume | free | free |
| VRAM | **0** | 0 (resident) | ~5 GB — doesn't fit |
| Quality on semantic calls | good | weak | good |
| Speed | ~2–5 s/video | ~20–40 s/video | n/a |
| Offline | ✗ | ✓ | ✓ |
| Deterministic forever | ✗ | ✓ | ✓ |
| Data leaves machine | ✓ | ✗ | ✗ |
| Build cost | ~1 day (reuse) | ~2 days | blocked |

### Guardrails that make the hosted choice safe

1. **Spend cap.** `paid_call_budget` caps billable requests; OpenAI is reached only after Gemini's
   entire ladder fails. Already enforced in Phase 4.
2. **Cache by content.** `stage_key('verdicts', version, [evidence_key, brief_key], config)` — the
   same video and brief never pay twice.
3. **Model + prompt version in the artifact**, so a verdict is always attributable.
4. **Rules floor.** Total backend failure degrades to L1+L2 only, flagged `BACKEND_DEGRADED`,
   with everything unresolved as UNCERTAIN. **Never a crash, never a silent guess.**
5. **ID validation.** Enforced in code, independent of which model answered.

---

## 5. Build order

Seven steps. Each is independently testable, and the early ones need no LLM at all.

### §63 — Config, verdict schema, closed enums
`Phase6Config` with the L2/L3 thresholds marked `_PLACEHOLDER`. `VERDICT_STATUSES`,
`EVALUATION_LAYERS`, the `Verdict` dataclass. `VERDICT_STAGE_VERSION = '1.0.0'`.

### §64 — Requirement ↔ evidence retrieval
The join. `candidates_for(requirement, records, evidence)`:
- resolve symbolic windows against this video's duration
- filter by `evidence_mode` via `record.can_satisfy()` — **Phase 5 already decided this per record**
- filter by time window, widened by each record's own tolerance
- rank by `match_hints` overlap
- return top-k with the reason each was retrieved

### §65 — L1, the deterministic evaluator
Phrase matching, tolerance-aware timestamp arithmetic, gazetteer, enum presence.
**`can_fail_on` gate wired here**, so no later layer can bypass it.

### §66 — L2, embeddings
`bge-small-en-v1.5` on CPU, correct query prefix, two thresholds, vectors cached per evidence file.

### §67 — L3, LLM adjudication
Batched per video. Reuses `HostedLLMBackend`. Strict ID validation, one retry, then UNCERTAIN.
Prompt version `p6_adjudicate_v1` in the registry.

### §68 — Hook module (§33)
Cheap features first — speech onset < 1.0 s, question/number/negation/second-person in the first
sentence, text overlay in second one, cuts in first 3 s, face at camera. Then prompt **P2** for
`hook_present`, `hook_type` (closed taxonomy, 11 values), `start`, `end`, `strength`, `transcript`,
`visual`, `within_required_window`, `reason`.

**Presence stays separate from strength.** Strength is **ordinal with written anchors** — the prompt
defines weak/medium/strong with an example of each. A bare *"rate the strength"* produces noise.
**Never emit a numeric hook score from the model.**

### §69 — Claims module (§38)
Two-stage: high-recall gazetteer + regex (`cure`, `heal`, `treat`, `eliminate`, `prevent`,
`clinically proven`, `dermatologist approved`, `FDA`, `guaranteed`, `permanent`, `100%`,
`overnight`, plus per-brand terms), then LLM classification into `medical_claim | cure_claim |
guarantee_claim | unsupported_outcome | prohibited_wording | not_a_claim` with a risk level.

**Tune for recall, accept false positives.** A missed medical claim is far more expensive than a
flag a human dismisses in two seconds. **Every claim output carries an explicit "not legal advice /
requires human review" disclaimer** in the report. We do not try to prove a global negative.

### §70 — Exit criteria cell
The same shape as §51 and §62: a self-check whose output can be pasted back for review.

---

## 6. What we expect — and what would mean it is wrong

### Expected on the current three videos

- **A high UNCERTAIN rate on visual requirements** — correct, because `can_fail_on('visual')` is
  `False` while the T4 degrades Phase 3. It should be *explained* in the report, not hidden.
- **`ocr_only` requirements mostly UNCERTAIN** — 1 of 48 intervals is `confirmed_independent`.
  Correct per §37, and worth surfacing as a *brief-authoring* insight: asking for on-screen-only
  evidence is hard to verify on a speech-heavy video.
- **L1 resolving most temporal requirements outright** — deadlines and windows are arithmetic.
- **L3 firing on the semantic ones** — paraphrase, tone, "is this a hook or an introduction".

### Tripwires — numbers that mean something is wrong

| Signal | Threshold | What it means |
|---|---|---|
| UNCERTAIN rate | > ~20% | the **evidence layer** is the problem, not the evaluator |
| L3 share | > 30% | L1/L2 are too timid, or `match_hints` are poor |
| PARTIAL share | high | PARTIAL is defined too loosely — it makes scores mushy |
| Fabricated evidence IDs | **any** | hard failure, assert in code |
| L1 and L3 disagreeing | frequent | thresholds are wrong, not the model |

### Exit criteria (`plan.md` §6)

- [ ] Every requirement produces a status, evidence IDs and a reason
- [ ] **Zero fabricated evidence IDs** across the full set — asserted in code
- [ ] L1/L2/L3 escalation rates logged; **L3 handles < 30%**
- [ ] Hook module produces the full §33 output
- [ ] Claims module flags all planted test claims (5 scripts with deliberate claims)
- [ ] **`speech_only` vs `ocr_only` verified on a burned-in-caption video**
- [ ] No verdict emits FAIL where `can_fail_on(modality)` is False — asserted in code

---

## 7. Risks, and what we do about them

| Risk | Why it bites | Mitigation |
|---|---|---|
| **Thresholds invented, not measured** | 0.7 looks round and means nothing | Name them `_PLACEHOLDER`; calibrate in Phase 8 on the benchmark |
| **LLM invents evidence IDs** | destroys trust instantly | Only provided IDs citable; validated in code; reject + retry once + downgrade |
| **Everything returns UNCERTAIN** | the system looks broken | Track the rate as a first-class metric; >20% means fix Phase 3, not Phase 6 |
| **Retrieval misses the right candidate** | L3 adjudicates the wrong sentences | Retrieve top 8–10, generously; recall over precision at this step |
| **PARTIAL overused** | scores become mush | Define narrowly in writing; audit its frequency |
| **Hook strength is subjective** | lowest inter-rater agreement in the system | Anchored ordinal ratings; **measure your own self-agreement** by labelling 10 videos twice a week apart. If you agree with yourself 70% of the time, that is the ceiling — say so in the report rather than chasing a number you cannot define |
| **Hosted model changes under us** | verdicts drift silently | Model name + prompt version in the cache key and artifact |
| **Network drops mid-batch** | half-finished run | Per-video caching; resume costs nothing |
| **A verdict bug looks like an evidence bug** | wasted days | Verdicts cite evidence IDs; every disagreement is traceable to a record |

### The one I am most concerned about

**Phase 3's degradation is the ceiling on Phase 6's usefulness.** With `visual` permanently
`degraded=True`, a whole class of requirement — *"show the product in the first 3 seconds"* — can
never resolve to anything but UNCERTAIN. Phase 6 will be *correct* about that, and the system will
still feel unsatisfying to use.

Two things help, in this order:

1. **Diagnose the current degradation.** The 41 s video ran 19 frames @ 50176 px = 1216 tokens when
   ~6600 should be affordable. If that is Whisper still holding VRAM, it is a one-line fix
   (`asr_model = None; free_vram()` before Phase 3) and visual becomes `degraded=False` for free.
2. **Only then consider 4-bit**, which buys frame headroom at a speed cost.

**This is worth resolving before or alongside Phase 6, not after.**

---

## 8. What this phase deliberately does not build

- **No scoring.** Weighted aggregation, gates and the final report are Phase 7. Mixing them hides
  evaluator bugs inside score arithmetic.
- **No frames at L3.** Phase 3 looked; re-asking with pixels is the expensive way to re-answer.
- **No threshold tuning.** Calibration is Phase 8, on a labelled benchmark.
- **No fine-tuning, no RAG.** Phase 12, and only if evidence demands it.
- **No specialised detectors** (logo, face, brand-safety). Phase 11, trigger-gated.

---

## 9. Immediate next actions

1. **Settle the Phase 3 rung question** — get §30's `DEGRADED_BUDGET` detail line for the 41 s video.
   OOM or advisory skip? It changes how much of Phase 6 is answerable.
2. **§63–§65** — config, retrieval, L1. No LLM, no embeddings, fully testable offline. This alone
   resolves a large share of requirements on the AURELIA brief.
3. **§66** — L2 embeddings, CPU-pinned.
4. **§67** — L3 on the existing hosted ladder.
5. **§68–§69** — hook and claims modules.
6. **§70** — exit criteria, output pasted back for review.

Steps 2 and 3 need no API key and no GPU. The phase can be most of the way built and tested before
anything hits the network.
