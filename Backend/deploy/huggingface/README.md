---
title: Creative Audit API
emoji: 🎬
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
short_description: Audits short-form social video against a content brief
---

# Creative Audit API

> ## ⚠️ A Docker Space is NOT free any more
>
> Verified against the live API on 2026-09-24:
>
> ```
> 402 Payment Required
> Static Spaces are free for everyone, but hosting Gradio and Docker
> Spaces on free cpu-basic requires a PRO subscription.
> ```
>
> Both **public and private** were tried; both are refused. Only **Static**
> Spaces (plain HTML/JS) remain free, and a FastAPI backend cannot be one.
>
> **This guide therefore needs a PRO subscription (~$9/mo).** At that price a
> Hetzner VPS is €6.50/mo for 4 vCPU, 80 GB, no sleeping and no ephemeral
> storage — see `docs/05_deployment.md`. Everything below is correct *given*
> PRO; it is kept because the Dockerfile, the front-matter and the ephemeral
> mode are all still right, and because PRO is a reasonable choice if you
> already pay for it.

FastAPI backend for the Phase 1–7 video-compliance pipeline. Video URLs and a
content brief in; timestamped verdicts, a score, an HTML report and a
creative-angle attribution out.

`POST /analyze` → `202` + `job_id` → poll `GET /jobs/{id}`. Interactive docs
at `/docs`.

**Running in ephemeral mode.** This Space has no persistent volume, so each
job's videos and artifacts are deleted when it finishes. The compiled brief is
returned as `compiled_brief` — **keep it and send it back**, or scoring stops
being comparable between jobs. See below.

---

## Deploying this to your own Space

### 1. Create the Space

<https://huggingface.co/new-space>

| Field | Value |
|---|---|
| SDK | **Docker** → Blank |
| Hardware | **CPU basic** (free — 2 vCPU, 16 GB) |
| Visibility | **Private** unless you want the world submitting jobs |

### 2. Push the Backend

A Space is a git repo. The `Backend/` directory becomes its **root** —
`Dockerfile` must be at the top level, and **this file must be the Space's
`README.md`**, because Spaces reads its configuration from the YAML block at
the top.

```bash
git clone https://huggingface.co/spaces/<you>/<space> hf-space
cd hf-space

cp -r "/path/to/Backend/." .
cp deploy/huggingface/README.md ./README.md     # the front-matter above

git add -A && git commit -m "Creative Audit API" && git push
```

The build takes **20–40 minutes** on the free tier. It compiles nothing —
every dependency has a wheel — but it downloads torch and bakes ~1.8 GB of
model weights into the image so the first request is not a ten-minute wait
that looks like a hang. Watch the **Logs** tab.

> **Too slow or hitting a build limit?** Set `BAKE_MODELS=false` under
> Settings → Variables. The image drops to ~1 GB and the models download on
> first use instead — which on an ephemeral Space means **every** cold start,
> so it is a trade, not a saving.

### 3. Secrets and variables

Settings → **Variables and secrets**.

**Secrets** (encrypted, not in the repo):

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | **required** — vision, brief compile, L3 |
| `AUDITOR_API_KEYS` | **required here** — see the warning below |
| `HF_TOKEN` | optional; raises the model download rate limit |

**Variables** (plain):

| Name | Value |
|---|---|
| `AUDITOR_EPHEMERAL` | `true` |
| `AUDITOR_DATA_ROOT` | `/data` |
| `AUDITOR_DECODE_WORKERS` | `2` (the free tier has 2 vCPU) |
| `AUDITOR_MAX_VIDEOS` | `5` to start |

> **`AUDITOR_API_KEYS` is not optional on a Space.** A public Space is
> reachable by anyone, and without a key anyone who finds it can submit jobs
> and spend your Gemini quota. `/ready` will report `auth: OPEN` if you forget.
> Generate one:
> `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 4. Verify

```bash
SPACE=https://<you>-<space>.hf.space

curl $SPACE/health
curl $SPACE/ready
curl -H "x-api-key: $KEY" $SPACE/config
```

`/ready` should show `namespace: ready`, `auth: 1 key(s)`, `problems: []`.

---

## Ephemeral mode: what changes

| | |
|---|---|
| Deleted when a job ends | the downloaded videos, frames, audio, per-stage artifacts |
| Kept for the retention window | the HTML/JSON reports and the job record |
| Kept while the Space is warm | `briefs/` — the compiled contracts |
| **Lost on restart** | everything, including `briefs/` |

That last row is the one that matters, and it is not about cost.

**The brief compiler is non-deterministic.** The same brief has produced
**6, 9, 16, 21, 22 and 24 requirements** across runs at temperature 0. The
frozen compile is what makes two videos comparable — they were measured
against the same contract. If the Space restarts and the next job recompiles,
the contract may differ and **the scores stop being comparable, with nothing
in the output saying so.**

### The fix: hold the contract yourself

Every job returns it:

```jsonc
{
  "job_id": "9f3c…",
  "status": "succeeded",
  "compiled_brief": { "status": "OK", "brief_hash": "…", "requirements": [ … ] }
}
```

Store it, and send it back on every later job for that brief:

```jsonc
POST /analyze
{
  "video_urls": ["https://www.tiktok.com/@user/video/123"],
  "compiled_brief": { ...exactly what the API returned... }
}
```

No `brief_url` needed, no recompile, **three model calls saved per job**, and
identical scoring for as long as you keep it.

**It is verified, not trusted.** The contract carries an `approved_digest`
over its requirements. Edit them and the request is refused —

```
compiled_brief is not usable: the requirement set changed since approval
(a1b2c3d4 -> 9f8e7d6c); it must be reviewed again.
```

— so sending it back is safe, and quietly rewriting it is not possible.

---

## Calling it from a Vercel app

A Space gives you **HTTPS for free**, which removes the mixed-content problem.
Still do not call it from browser JavaScript: the API key would be readable by
anyone who opens devtools. Proxy through a Route Handler, which also sidesteps
CORS because the browser only ever talks to your own origin.

```
Browser ──https──▶ Vercel Route Handler ──https──▶ <you>-<space>.hf.space
                   (holds AUDIT_API_KEY)
```

`deploy/oracle/DEPLOY.md` §9 has the Route Handlers; only `AUDIT_API_URL`
changes.

> **Vercel caps serverless request bodies at 4.5 MB**, which is fine for JSON
> — but a full `compiled_brief` can be tens of KB and a *job result* with five
> videos can be large. Return what your UI needs, not the whole object.

---

## Limits of the free tier

- **Sleeps after inactivity.** The first request after a quiet spell pays a
  cold start. Your client should tolerate a slow first call.
- **2 vCPU.** Phase 1 decode is parallel, so it gets about half the benefit of
  a 4-core box. The dominant cost is the hosted vision call anyway.
- **TikTok downloads will be worse here than anywhere.** Hugging Face IP
  ranges are datacentre and heavily used, so yt-dlp is refused more often.
  Upload the files yourself, or run the fetch from a residential connection.
- **No persistent storage** without the paid add-on (~$5/mo for 20 GB). At
  that price a Hetzner VPS is €6.50 for 4 vCPU, 80 GB and no sleeping.

**Use a Space to prove the integration. Move when it matters.** The same
Docker image runs on a VPS unchanged — drop `AUDITOR_EPHEMERAL` and the
artifact cache comes back.
