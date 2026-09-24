# Frontend Integration Guide

For whoever builds the Vercel app — human or agent. Everything here is from a
**real run** against a live backend, not an invented example.

> ## Live right now — start here
>
> Put these in Vercel → Settings → Environment Variables, then redeploy.
> **Neither name takes a `NEXT_PUBLIC_` prefix** — that would ship the key to
> the browser.
>
> ```
> AUDIT_API_URL = https://phantom-garage-learned-repository.trycloudflare.com
> AUDIT_API_KEY = <ask Umar — sent separately, never committed>
> ```
>
> The key is deliberately **not in this repository**. A live credential in a
> git history outlives every attempt to delete it, so it travels by direct
> message instead. It is the value of `AUDITOR_API_KEYS` in `Backend/.env`.
>
> Check it works before writing any code:
>
> ```bash
> curl https://phantom-garage-learned-repository.trycloudflare.com/ready
> # {"ready":true,"namespace":"ready","ffmpeg":"...","auth":"1 key(s)",...}
>
> curl -H "x-api-key: $AUDIT_API_KEY" \
>      https://phantom-garage-learned-repository.trycloudflare.com/config
> ```
>
> Verified through that URL, not assumed: `/health` 200, `/ready`
> `{"ready":true}`, `/analyze/upload` present, and `/config` **401 without the
> key, 200 with it**.
>
> ### Two things that will waste an hour if you don't know them
>
> **1. This URL is temporary.** It is a Cloudflare quick tunnel to a backend
> running on Umar's machine. It dies when the tunnel stops, the machine sleeps,
> or it reboots, and a *different* URL is issued next time. Two things must
> both be true for it to answer: the backend is running **and** the tunnel is
> running. A connection error is almost always that — ask for the current URL
> before debugging your own code. §1b has the named-tunnel setup for a
> hostname that never changes.
>
> **2. The key above is the BACKEND key, not the Gemini key.** It gates this
> API. It does not expose the Gemini credential, and it is rotatable in one
> line (`AUDITOR_API_KEYS` in `Backend/.env`, then restart). Still treat it as
> a secret: anyone holding it can queue jobs and spend the Gemini quota behind
> it. **Do not commit this file** — it is deliberately untracked and listed in
> `.gitignore`. Share it directly, not through a public repo.

The user pastes **one or more TikTok links** plus **one content brief**, and
gets back, per video: a score, timestamped requirement verdicts, an HTML
report, and **which of the brief's creative angles the video fits**.

---

## 1. The shape of it

```
Browser ──https──▶ Vercel Route Handler ──▶ Audit API ──▶ Gemini
                   (holds the API key)      (5–12 min)
```

**Never call the API from browser JavaScript.** Three reasons, each fatal:

1. **Mixed content.** An `https://` page cannot `fetch()` an `http://` backend.
   The browser blocks it before a request leaves.
2. **Key exposure.** Anything the browser sends, a user can read. Your Gemini
   quota becomes public.
3. **CORS.** Avoided entirely — the browser only ever talks to your own origin.

**A job takes 5–12 minutes.** Vercel functions time out at 10 s (Hobby) /
60–300 s (Pro). So: submit, get an id, **poll**. Never `await` a result inside
a request handler.

---

## 1b. READ THIS FIRST — Vercel cannot reach your localhost

The backend runs **on your machine**. Vercel Route Handlers run **in Vercel's
cloud**. There is no route between them:

```
Vercel function  ──▶  http://localhost:8000   ✗  localhost is VERCEL's own
                                                  container, not your PC
Vercel function  ──▶  http://192.168.1.x:8000 ✗  a private LAN address is
                                                  unreachable from the internet
```

This is not a configuration problem and no environment variable fixes it. The
backend has to have **a public address** before anything deployed on Vercel can
talk to it. Three ways, in the order you should consider them.

### Option A — a tunnel (recommended for a Vercel frontend)

A tunnel gives your local backend a public HTTPS URL. The backend stays on your
machine; nothing is opened on your router.

```bash
winget install Cloudflare.cloudflared      # or: brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

It prints a URL like `https://random-words-1234.trycloudflare.com`. That is
your `AUDIT_API_URL`. Free, no account, HTTPS terminated for you.

**The URL changes every restart.** For something stable, a free Cloudflare
account plus a named tunnel gives a fixed hostname you can leave in Vercel's
env vars:

```bash
cloudflared tunnel login
cloudflared tunnel create audit-api
cloudflared tunnel route dns audit-api audit.yourdomain.com
cloudflared tunnel run --url http://localhost:8000 audit-api
```

With a tunnel, **everything in §8 works unchanged** — the key stays
server-side, there is no CORS, and no browser ever sees the backend.

**Set `AUDITOR_API_KEYS` before you start a tunnel.** A tunnel is a public
address: without a key, anyone who guesses the URL can spend your Gemini quota.

### Option B — run the frontend locally too

For development, skip the tunnel entirely:

```bash
next dev        # http://localhost:3000
AUDIT_API_URL=http://localhost:8000
```

Both processes are on one machine, so the Route Handler reaches the backend
normally. This is the simplest loop and costs nothing. It just is not
"deployed on Vercel".

### Option C — browser talks to localhost directly (avoid)

Technically possible: the user's browser *is* on the machine running the
backend, so `http://localhost:8000` resolves. Browsers treat `localhost` as a
trustworthy origin, so it is not blocked as mixed content. But:

- **The API key ends up in browser code.** It is `NEXT_PUBLIC_`, readable by
  anyone who opens devtools. Your Gemini quota is then public.
- **CORS becomes your problem.** You must set
  `AUDITOR_CORS_ORIGINS=https://your-app.vercel.app`.
- **Chrome's Private Network Access** requires a public HTTPS page asking for a
  private address to clear an extra preflight; this backend does not send
  `Access-Control-Allow-Private-Network`.
- **Safari is stricter still** and may refuse regardless.
- It only ever works for a user sitting at the machine running the backend.

Use it only for a single-user local tool where you accept the key exposure.

### Which to pick

| You want | Use |
|---|---|
| Vercel-deployed frontend, backend on your PC | **A — tunnel** |
| Local development loop | **B — `next dev`** |
| Backend on a server with a real domain | Neither; point `AUDIT_API_URL` at it |
| A single-user local tool, key exposure acceptable | C |

---

## 1c. Keeping the backend running

Two ways. The venv is what has actually been run and timed on this machine; the
container is the Dockerfile as written — **it has not been built here**, because
Docker is not installed on this box.

### Docker Compose (for a machine that should keep serving)

**Optional.** The uvicorn path below already serves the frontend; Docker buys
reproducibility on another machine and auto-restart, not new capability. It
changes nothing the frontend sees — same endpoints, same key, same port.

**Windows prerequisite.** Docker Desktop needs WSL2 to run Linux containers.
If `wsl --status` says *"The Windows Subsystem for Linux is not installed"*,
the engine cannot start and `docker info` returns `500` on the
`dockerDesktopLinuxEngine` pipe:

```powershell
wsl --install        # elevated; REBOOT afterwards
# then start Docker Desktop and accept its terms
```

A reboot also kills the backend and the tunnel — restart both after, and the
quick-tunnel URL will be a new one.

From `Backend/`:

```bash
# 1. Free the port. A running uvicorn owns 8000 and the container cannot bind.
# 2. Then:
cp .env.example .env          # set GEMINI_API_KEY, AUDITOR_API_KEYS
docker compose up -d --build  # first build is long: ~2.5 GB, weights baked in
docker compose logs -f api
curl localhost:8000/ready
```

#### The container starts with an empty cache — and that changes what scores mean

`/data` is a **named volume**, not your `Backend/data` folder. So the container
cannot see the artifacts, jobs or **frozen briefs** from local runs:

- old job ids return `404`
- the brief is **recompiled from scratch**, and the compiler is not
  deterministic — the same brief produced 20, 27 and 20 requirements across
  runs. A different requirement set means scores that are **not comparable**
  with anything produced before the switch, with nothing in the output saying
  so.

Two ways to keep comparability, and you want one of them:

```bash
# A. carry the frozen briefs into the volume (do it once, before first use)
docker compose up -d
docker compose cp ./data/briefs api:/data/briefs
docker compose restart api

# B. or have the frontend hold the contract and send it back
#    (AnalyzeRequest.compiled_brief -- see §11)
```

What the compose file already does, and why:

| Setting | Why it matters |
|---|---|
| `restart: unless-stopped` | survives a crash and a host reboot |
| `audit-data:/data`, `audit-models:/models` | **named volumes.** `/models` is ~1.8 GB of weights and `/data` holds the artifact cache; a bind mount or no volume means re-downloading everything on every container replacement |
| `stop_grace_period: 30s` | a job killed mid-stage leaves half-written artifacts a content-addressed cache cannot tell from good ones |
| `memory: 8G` | ~4 GB working set: CTranslate2 int8 ~1 GB, torch ~1 GB resident, plus ONNX, frames, and the video |
| `healthcheck` → `/health` | liveness only. **Never point a restart policy at `/ready`** — it reports a missing API key as not-ready, and the container would restart forever over a config problem |

Day to day:

```bash
docker compose ps                 # is it up
docker compose logs -f --tail=100 api
docker compose restart api        # after changing .env
docker compose down               # stop; volumes SURVIVE
docker compose down -v            # stop and DELETE the cache and weights
docker compose up -d --build      # after changing code
```

`ffmpeg` is installed inside the image, so none of the PATH trouble in §1d
applies to the container.

### Directly with uvicorn (verified on this machine)

```bash
cd Backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use `--host 0.0.0.0` only if something on your LAN must reach it; with a tunnel
you do not need to, and `127.0.0.1` keeps it off the network.

**One worker.** The job store and the model namespace live in the process;
`--workers 4` gives four independent stores and four model loads. Scale by
running more containers against a shared `AUDITOR_DATA_ROOT`, which is safe
because the artifact store is content-addressed.

To keep it alive across reboots without Docker, use a Scheduled Task (Windows)
or a systemd unit (Linux) that runs that command.

### 1d. If jobs die instantly in Phase 1

`ffmpeg`/`ffprobe` are not pip-installable and are the first thing a job
touches. `GET /ready` names them and refuses to report ready without them, so
check there first. On Windows, `winget install Gyan.FFmpeg` appends to the
*user* PATH, which an already-running shell never picks up — the server
searches the usual install locations and extends its own PATH, and logs what it
did. `AUDITOR_FFMPEG_DIR` overrides the search.

---

## 2. Endpoints

Base URL = wherever the backend runs. Auth is `x-api-key` on everything except
the three ops endpoints.

| Method | Path | Auth | Returns |
|---|---|---|---|
| `POST` | `/analyze` | key | `202` + `{job_id, status, poll}` — video **URLs** |
| `POST` | `/analyze/upload` | key | `202`, same shape — video **files** (multipart) |
| `GET` | `/jobs/{job_id}` | key | the whole job: status, phase, results |
| `GET` | `/jobs` | key | recent jobs, newest first |
| `GET` | `/jobs/{job_id}/report/{video_id}.html` | key | self-contained HTML report |
| `GET` | `/jobs/{job_id}/report/{video_id}.json` | key | the same data as JSON |
| `POST` | `/briefs/compile` | key | compile a brief alone, to preview requirements |
| `GET` | `/health` | open | liveness — `{status, uptime_s}` |
| `GET` | `/ready` | open | readiness — `503` until it can serve |
| `GET` | `/metrics` | open | Prometheus text |
| `GET` | `/config` | key | effective settings, keys as lengths |

Interactive docs: `/docs`.

### `POST /analyze`

```jsonc
{
  "video_urls": [                      // 1..N, required
    "https://www.tiktok.com/@user/video/7671762950687919390",
    "https://www.tiktok.com/@other/video/7674625522189618445"
  ],
  "brief_url": "https://docs.google.com/document/d/<id>/edit",
  // ...or instead:
  // "brief_text":     "Show the product in the first 5 seconds. ...",
  // "compiled_brief": { ...a contract a previous job returned... },

  "label": "week 1 batch",             // optional, free text
  "force_reaudit": false,              // optional; re-run cached stages
  "recompile": false                   // optional; replace a frozen brief
}
```

**The brief must be a Google Docs URL** (shared *anyone with the link can
view*), raw text, or a previously-returned `compiled_brief`. Any other URL is
refused — including a Google Doc that is not publicly readable, which returns
an HTML sign-in page that *would otherwise compile into real-looking
requirements*.

**All videos in one request are audited against that one brief.** That is the
intended shape: a brief is a contract, and comparing creators only means
something when they were measured against the same one.

Ceiling: `AUDITOR_MAX_VIDEOS` (default 25). Beyond it, `422` naming the knob.

### `POST /analyze/upload` — when you already have the file

Same pipeline, same `202`, same polling. The only difference is that the bytes
arrive with the request instead of being downloaded by the server.

Use it when the backend cannot fetch the link itself. **Hosted locally this is
rarely necessary** — a home IP downloads TikTok far more reliably than a
datacentre one, which is the single best reason to run this on your own
machine. Keep it as the fallback for when `/analyze` reports a download
failure.

`multipart/form-data`:

| Field | Type | Notes |
|---|---|---|
| `files` | file, repeatable | the videos. **Name each after its video id** — `7671762950687919390.mp4` |
| `brief_url` / `brief_text` / `compiled_brief` | text | exactly as `/analyze`; `compiled_brief` is a **JSON string** |
| `source_urls` | text | JSON array of the original links, provenance only — nothing is fetched |
| `label`, `force_reaudit`, `recompile` | text | as `/analyze` |

```ts
const fd = new FormData();
for (const f of files) fd.append('files', f, f.name);
fd.append('brief_url', briefUrl);
fd.append('source_urls', JSON.stringify(urls));

await fetch(`${process.env.AUDIT_API_URL}/analyze/upload`, {
  method: 'POST',
  headers: { 'x-api-key': process.env.AUDIT_API_KEY! },   // no Content-Type:
  body: fd,                                              // fetch sets the
});                                                      // multipart boundary
```

The filename matters beyond cosmetics: `source` on every result row *is* the
filename, and that is what maps a row back to its original link. An opaque name
still audits correctly, it just cannot show which URL it came from —
`source_urls` covers that if you cannot rename.

Refused with `422` before any job is queued: a non-video extension, bytes whose
container header is not a real video, or a 0-byte file. `413` if a file exceeds
`AUDITOR_MAX_VIDEO_BYTES` (200 MB) or the request exceeds
`AUDITOR_MAX_UPLOAD_BYTES` (512 MB). Nothing is left behind when staging fails.

### Errors

| Code | When | What to show |
|---|---|---|
| `422` | bad input | the `detail` string — it is written for a human |
| `401` | missing/wrong `x-api-key` | a server config problem, not the user's |
| `429` | queue full (`AUDITOR_MAX_QUEUED_JOBS`) | "busy — jobs take minutes, try shortly" |
| `503` | still starting, or no `GEMINI_API_KEY` | poll `/ready` |
| `413` | JSON body over 2 MB, or an upload over its own limit | the `detail` names which limit |
| `404` | unknown job or report | |

Two separate size ceilings, deliberately: `AUDITOR_MAX_BODY_BYTES` (2 MB) for
JSON, and the much larger upload limits **only** on `/analyze/upload`. One
raised global limit would let anyone post half a gigabyte of JSON at
`/analyze`.

---

## 3. Polling

```ts
const PHASES = {
  queued:  'Queued',
  brief:   'Reading the brief',
  ingest:  'Downloading videos',
  phase1:  'Decoding and sampling frames',
  phase2:  'Transcribing and reading on-screen text',
  phase3:  'Describing the video',        // the long one
  phase5:  'Assembling evidence',
  phase6:  'Judging requirements',
  phase7:  'Scoring and writing the report',
  done:    'Done',
} as const;
```

`status` is one of `queued` · `running` · `succeeded` · `partial` · `failed`.

**`partial` means some videos succeeded and some did not** — show the ones that
did. One bad link never costs the others.

Poll every **10–15 seconds**. Real timings from a one-video run:

```
brief       0.0s   (reused a frozen compile)
ingest      5.6s   TikTok download
phase1      0.2s   decode + sample
phase2     30.6s   ASR + OCR
phase3    137.8s   vision  ← ~70% of the time
phase5-7   23.7s   evidence, verdicts, score, report
------------------
total     184s
```

Add ~60 s for a **cold** run (Whisper loads once) and ~2 min per extra video.

---

## 4. Reading a result

`job.results[]`, one entry per video. Abridged from a real response:

```jsonc
{
  "video_id": "864c03eeccc01e6b",
  "video_hash": "864c03eeccc01e6b…",
  "source": "7671762950687919390.mp4",
  "url": "https://www.tiktok.com/@briceyscarbear/video/7671762950687919390",
  "status": "ok",

  "score": {
    "headline": 78.0,
    "literal_headline": 78.0,
    "status_band": "NEEDS_MAJOR_REVISION",
    "coverage": 0.7857,
    "scoring_units": 5,
    "band_low": 61.0,
    "band_high": 78.0,
    "band_basis": "pessimistic",
    "lead_with_band": true
  },

  "standing": "on_brief",
  "verdict_mix": { "PASS": 7, "NOT_APPLICABLE": 15, "UNCERTAIN": 6 },
  "talking_points_covered": 7,
  "talking_points_total": 9,
  "evidence_records": 412,

  "creative_angle": { /* see §5 */ },
  "verdicts": [ /* see §6 */ ],
  "notes": [],

  "report_html_url": "/jobs/<job_id>/report/864c03eeccc01e6b.html",
  "report_json_url": "/jobs/<job_id>/report/864c03eeccc01e6b.json"
}
```

### Four things a UI gets wrong unless told

**1. If `lead_with_band` is `true`, show the band — not the headline.**

```
  78  NEEDS_MAJOR_REVISION        ← misleading
  61–78  NEEDS_MAJOR_REVISION     ← correct
```

Both numbers are right: 78 is the best case, 61 is what the *decided* evidence
supports. When coverage is thin the band is the honest answer.

```tsx
const display = s.lead_with_band && s.band_low != null
  ? `${s.band_low.toFixed(0)}–${s.band_high.toFixed(0)}`
  : s.headline?.toFixed(0);
```

**2. `headline` can be *below* `literal_headline`.** Not a bug. `literal` is
instruction-following; `headline` is credited substance. A creator who
paraphrases the brief well scores higher on credit than on literal compliance.

**3. `coverage < 1.0` means part of the weight was never decided.** Those
requirements are `UNCERTAIN` — an **abstention, not a zero**. Show it:
`"79% of the weight was decided"`.

**4. `NOT_APPLICABLE` is not a failure.** It leaves the denominator entirely.
A verdict mix of `{PASS: 7, NOT_APPLICABLE: 15, UNCERTAIN: 6}` is 7 passes out
of 13 applicable, not out of 28.

### Status bands

`APPROVED` · `NEEDS_MINOR_REVISION` · `NEEDS_MAJOR_REVISION` · `REJECTED` ·
`OFF_BRIEF`

`standing` is a separate whole-video read: `on_brief` / `off_brief` / `null`.
**A score with `standing: null` has no second opinion behind it** — flag it for
a human rather than quoting the number.

---

## 5. The creative angle — what the user asked for

```jsonc
"creative_angle": {
  "named_angles": [
    "He's Not Ignoring Me… He's Knocked Out",
    "Why I Stopped Giving My Kids Melatonin",
    "Back to School Essentials",
    "Back to School Bedtime Reset"
  ],
  "concept_fit": [
    { "angle": "Back to School Bedtime Reset", "percent": 70,
      "why": "she runs the full evening routine and places the product in it" },
    { "angle": "Back to School Essentials", "percent": 30,
      "why": "the haul framing appears briefly at the open" }
  ],
  "dominant_angle": "Back to School Bedtime Reset",
  "off_angle_percent": 0,
  "matched_named_angle": true,
  "angle": "routine_integration",
  "nearest_brief_concept": "Creative Concepts",
  "angles_source": "document",
  "flags": []
}
```

| Field | Meaning |
|---|---|
| `named_angles` | the angles **this brief names**, read from its own sub-headings. Same for every video in the job. |
| `concept_fit` | the split across them, summing to 100 |
| `dominant_angle` | the largest share — **the headline answer** |
| `matched_named_angle` | `false` when the video fits none of them |
| `off_angle_percent` | share attributed to "none of the listed angles" |
| `angles_source` | `document` = read from the brief's structure · `group_labels` = an older fallback |
| `angle` | a coarse type from a fixed list (`demonstration`, `problem_solution`, `routine_integration`, …) — **not** the brief's angles |

### Three states, and they must look different

```tsx
if (ca.flags?.some(f => f.includes('MODEL_FAILED'))) {
  //  1. NOT JUDGED -- a pipeline problem, not a finding about the video.
  //     Do NOT render 0% bars; that reads as "matched nothing".
  return <Unavailable note={result.notes?.[0]} />;
}
if (!ca.matched_named_angle && ca.off_angle_percent >= 50) {
  //  2. MATCHED NONE -- a real, decided answer. The creator invented her own
  //     angle. Often a good video; it is a fact about the BRIEF's coverage.
  return <TookTheirOwnAngle percent={ca.off_angle_percent} />;
}
//  3. MATCHED -- show the split.
return <AngleBars fit={ca.concept_fit} dominant={ca.dominant_angle} />;
```

> **`concept_fit` is a description, never a score.** Nothing in the scoring
> reads it. Do not rank creators by it, and do not add it to the score.

### Across a batch

`job.angle_distribution` aggregates it — *"we offered four angles and every
creator used the same one"* is a finding about the brief, and only visible
across a batch.

```jsonc
"angle_distribution": [
  { "angle": "Back to School Bedtime Reset", "videos": 3, "mean_percent": 62.5,
    "sources": ["7671…mp4", "7674…mp4", "7678…mp4"] },
  { "angle": "Why I Stopped Giving My Kids Melatonin", "videos": 0,
    "mean_percent": 0, "sources": [] }
]
```

---

## 6. Verdicts

```jsonc
{
  "requirement_id": "r-07",
  "requirement_label": "Mention that the gummies are melatonin-free",
  "status": "PASS",              // PASS | FAIL | UNCERTAIN | NOT_APPLICABLE
  "alignment": "strong",         // did it serve the ask, independent of status
  "decided_by": "L3",            // L1 deterministic | L2 embedding | L3 model
  "confidence": 0.82,
  "rationale": "at 00:14 she says 'no melatonin, just magnesium'",
  "evidence_ids": ["sp_0014_0019", "ocr_0016"],
  "flags": [],
  "group_id": "g2",
  "group_label": "Call to Actions"
}
```

**`status` and `alignment` are separate axes.** A creator can follow the
letter and miss the point (`PASS` / `weak`), or ignore the wording and nail the
intent (`FAIL` / `strong`). Show both.

**Every verdict cites `evidence_ids`.** Nothing is asserted without a trace.

**`group_label`** means the requirement was one option off a menu — the brief
offered alternatives and she picked one. `chosen_options` summarises which.

---

## 7. The HTML report

Self-contained: one file, no external assets, no JS dependencies. Serve it
through your own route so the API key stays server-side.

```ts
// app/api/audit/[jobId]/report/[file]/route.ts
export async function GET(_req: NextRequest,
  { params }: { params: Promise<{ jobId: string; file: string }> }) {
  const { jobId, file } = await params;
  const r = await fetch(
    `${process.env.AUDIT_API_URL}/jobs/${jobId}/report/${file}`,
    { headers: { 'x-api-key': process.env.AUDIT_API_KEY! },
      cache: 'no-store' });
  return new NextResponse(r.body, {
    status: r.status,
    headers: { 'content-type': file.endsWith('.json')
      ? 'application/json' : 'text/html' },
  });
}
```

Then `<iframe src={`/api/audit/${jobId}/report/${videoId}.html`} />`, or offer
it as a download.

---

## 8. Vercel Route Handlers

```
AUDIT_API_URL = https://<your-tunnel>.trycloudflare.com    (no NEXT_PUBLIC_)
AUDIT_API_KEY = <the AUDITOR_API_KEYS value>
```

**`AUDIT_API_URL` must be reachable from Vercel's network** — a tunnel
hostname or a real server. `http://localhost:8000` works only when the Next.js
process is on the same machine as the backend (§1b, option B). Never add
`NEXT_PUBLIC_` to either name: that ships them to the browser, and the key with
them.

Set both in Vercel → Project → Settings → Environment Variables, then redeploy;
env vars are read at build/runtime, so an existing deployment will not pick
them up on its own.

### `app/api/audit/route.ts` — submit

```ts
import { NextRequest, NextResponse } from 'next/server';
export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  const body = await req.json();

  const urls: string[] = (body.video_urls ?? [])
    .map((u: string) => u.trim()).filter(Boolean);
  if (!urls.length) {
    return NextResponse.json({ error: 'Add at least one video link.' },
                             { status: 400 });
  }
  if (!body.brief_url && !body.brief_text) {
    return NextResponse.json({ error: 'Add a content brief.' },
                             { status: 400 });
  }

  const res = await fetch(`${process.env.AUDIT_API_URL}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'x-api-key': process.env.AUDIT_API_KEY! },
    body: JSON.stringify({
      video_urls: urls,
      brief_url: body.brief_url,
      brief_text: body.brief_text,
      label: body.label,
    }),
    // Submitting only QUEUES the job; it returns in well under a second.
    signal: AbortSignal.timeout(20_000),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

### `app/api/audit/[jobId]/route.ts` — poll

```ts
import { NextRequest, NextResponse } from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';   // never cache a job's status

export async function GET(_req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(jobId)) {
    return NextResponse.json({ error: 'bad job id' }, { status: 400 });
  }
  const res = await fetch(`${process.env.AUDIT_API_URL}/jobs/${jobId}`, {
    headers: { 'x-api-key': process.env.AUDIT_API_KEY! },
    cache: 'no-store',
    signal: AbortSignal.timeout(20_000),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

### Client

```tsx
const { job_id } = await fetch('/api/audit', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ video_urls: urls, brief_url: briefUrl }),
}).then(r => r.json());

const timer = setInterval(async () => {
  const job = await fetch(`/api/audit/${job_id}`).then(r => r.json());
  setPhase(PHASES[job.phase] ?? job.phase);
  setProgress(`${job.completed_videos}/${job.requested_videos}`);
  if (['succeeded', 'partial', 'failed'].includes(job.status)) {
    clearInterval(timer);
    setResults(job.results);
    setWarnings(job.warnings);
  }
}, 15_000);
```

> Set expectations in the UI. **"This takes 5–12 minutes"** before they start
> beats a spinner that looks hung at minute four.

---

## 9. TikTok downloading

The backend fetches the links itself with `yt-dlp`. **That is the piece most
likely to fail in production**, and the reason is not code:

> TikTok refuses **datacentre IPs** far harder than residential ones, and
> shared cloud IPs worst of all — they have been used for scraping by everyone
> else on that range.

From a residential connection it is reliable: the run behind this document
downloaded in **5.6 s**.

### If downloads start failing

**Option A — cookies.** Export from a logged-in browser ("Get cookies.txt
LOCALLY"), put the file on the server, set `AUDITOR_COOKIES_FILE`. Expect to
refresh it periodically.

```bash
# Docker: /data is a NAMED VOLUME, not a host path
docker compose cp cookies.txt api:/data/cookies.txt
echo 'AUDITOR_COOKIES_FILE=/data/cookies.txt' >> .env
docker compose up -d          # `restart` does NOT re-read .env
```

**Option B — keep yt-dlp current.** TikTok changes; yt-dlp follows.

```bash
docker compose exec api pip install -U yt-dlp && docker compose restart
```

**Option C — a residential proxy.** The real answer for production.

### The reference downloader

Exactly what the backend uses, extracted so you can run it locally — from a
residential IP — and upload the files instead.

```python
"""Download TikTok videos the way the backend does."""
import re
from pathlib import Path

import yt_dlp

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
# Two formats, in order. 'mp4/best[ext=mp4]/best' asks for a progressive mp4,
# which TikTok does not always offer -- and yt-dlp then RAISES rather than
# taking what is there. Plain 'best' is the fallback.
FORMATS = ['mp4/best[ext=mp4]/best', 'best']


def video_id(url: str) -> str:
    """Downloads are named by id, so the id links a file back to its URL."""
    m = re.search(r'(\d{6,})(?:\?|$|/)', url or '')
    return m.group(1) if m else ''


def download(urls, out_dir='inbox', cookies_file=''):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    got, failed = {}, {}

    for url in urls:
        vid, err = video_id(url), None
        for fmt in FORMATS:
            opts = {
                'outtmpl': str(out / '%(id)s.%(ext)s'),
                'format': fmt,
                'quiet': True, 'no_warnings': True, 'noprogress': True,
                'merge_output_format': 'mp4',
                # A default python UA is the easiest thing in the world for a
                # CDN to refuse.
                'http_headers': {'User-Agent': UA},
                'retries': 3, 'socket_timeout': 30,
            }
            if cookies_file and Path(cookies_file).exists():
                opts['cookiefile'] = cookies_file
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True) or {}
                vid, err = str(info.get('id') or vid), None
                break
            except Exception as exc:
                err = f'{type(exc).__name__}: {exc}'

        # SUCCESS IS "THE FILE IS THERE", not "the call returned".
        # Do not trust prepare_filename() -- it gives the name yt-dlp INTENDED
        # before any merge. Do not diff the directory either -- yt-dlp SKIPS a
        # file it already has, so a re-run shows nothing new and looks like a
        # failure. Ask whether a video with that id exists.
        hit = next((p for p in sorted(out.iterdir())
                    if p.is_file() and p.stem.startswith(vid)
                    and p.suffix.lower() in {'.mp4', '.mov', '.webm', '.mkv'}),
                   None) if vid else None
        if hit:
            got[url] = hit
        else:
            failed[url] = err or 'no file with that id in the output directory'

    for u, why in failed.items():
        print(f'FAIL {u}\n     {why[:200]}')
    if failed and not got:
        # Every one failed: that is ONE cause, not N unlucky links.
        print('\nEVERY link failed -- one cause, not bad luck:')
        print('  - TikTok wants a login/cookie (export cookies.txt), or')
        print('  - this IP is blocked (datacentre ranges are refused hard), or')
        print('  - yt-dlp is out of date:  pip install -U yt-dlp')
    return got, failed


if __name__ == '__main__':
    got, failed = download([
        'https://www.tiktok.com/@briceyscarbear/video/7671762950687919390',
    ])
    for url, path in got.items():
        print(f'OK   {path.name}  {path.stat().st_size / 1e6:.1f} MB')
```

### URL formats accepted

```
https://www.tiktok.com/@user/video/7671762950687919390   ← canonical
https://vm.tiktok.com/XXXXXXXXX/                          ← short, resolved
https://www.tiktok.com/t/XXXXXXXXX/
```

Validate client-side before submitting — a `422` after a round trip is a slow
way to learn about a typo:

```ts
const TIKTOK = /^https?:\/\/(www\.|vm\.|vt\.)?tiktok\.com\/.+/i;
```

---

## 10. Handling failure honestly

```jsonc
{
  "status": "module_failed",
  "score": { "headline": 78.0, "lead_with_band": true, "band_low": 61.0 },
  "standing": null,
  "creative_angle": { "concept_fit": [], "flags": ["ANGLE_MODEL_FAILED"] },
  "notes": ["angle NOT judged: ANGLE_MODEL_FAILED",
            "A MODEL CALL FAILED -- this is a pipeline problem, not a finding "
            "about the video."]
}
```

**This is a real state and it happened on the first run behind this guide.**
The score computed fine; the creative-angle model call hit a `503` (Gemini
overload on the free tier) and came back empty.

| `status` | What it means | What to show |
|---|---|---|
| `ok` | everything ran | the result |
| `module_failed` | the score is valid, but a model call failed | the score **plus** `notes` — never a 0% angle chart |
| anything else | the video failed outright; `error` and `phase` say where | the error |

**The distinction that matters:** an empty `concept_fit` because the model
failed is *not* the same as a video that matched no angle. The first is a
pipeline problem; the second is a finding. `flags` tells you which. Rendering
both as "0%" invents a finding the system never made.

Retrying usually works — `503` is transient.

### Job-level `warnings`

Plain strings, worth surfacing:

```jsonc
"warnings": [
  "the consensus compile disagreed across runs (COMPILE_UNSTABLE); the
   requirement set is the majority and the disagreement is in brief.flags",
  "could not download: https://www.tiktok.com/@x/video/123"
]
```

---

## 11. Comparability — the one thing that will bite you

The brief compiler is **not deterministic**. The same brief has produced
**6, 9, 16, 21, 22 and 24 requirements** across runs at temperature 0.

So the first compile of a brief is **frozen** and reused. Two videos submitted
days apart are measured against the same contract, and their scores mean the
same thing.

**Never send `recompile: true`** unless you intend exactly that. A new compile
is a different requirement set, and scores from before and after are not
comparable — with nothing in the output saying so.

If the backend runs with `AUDITOR_EPHEMERAL=true` (no persistent disk), the
job returns `compiled_brief`. **Store it and send it back** on later jobs for
that brief:

```ts
const { compiled_brief } = job;              // save alongside the brief
// later:
await submit({ video_urls, compiled_brief }); // no brief_url needed
```

It is verified, not trusted: the contract carries a digest over its
requirements, and an edited one is refused.

---

## 12. Checklist

- [ ] **Backend has a public address** — tunnel running, or frontend local
      (§1b). Vercel cannot reach `localhost`.
- [ ] `AUDITOR_API_KEYS` set **before** the tunnel is exposed
- [ ] Backend reachable; `/ready` returns `200` with `problems: []`,
      and names `ffmpeg`/`ffprobe`
- [ ] `AUDIT_API_URL` and `AUDIT_API_KEY` set in Vercel (no `NEXT_PUBLIC_`)
- [ ] All calls go through Route Handlers — never browser → backend
- [ ] Poll every 10–15 s; never `await` a job in a handler
- [ ] UI says "5–12 minutes" before the user starts
- [ ] `lead_with_band` → show the band, not the headline
- [ ] `coverage < 1` surfaced; `UNCERTAIN` shown as abstention, not failure
- [ ] `status: "module_failed"` → show `notes`, not a 0% chart
- [ ] `matched_named_angle: false` rendered differently from "not judged"
- [ ] `partial` → show the videos that did succeed
- [ ] TikTok URLs validated client-side
- [ ] Report iframe proxied through your own route
