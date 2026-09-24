# Deploying to Oracle Cloud, step by step

Written for: account already created, Docker and Git installed locally.

Everything below is a copy-paste. Where a step needs judgement or can fail in
a confusing way, it says so.

---

## Who does what

| Step | You | Me |
|---|---|---|
| 1. Push code to GitHub | run 4 commands | — |
| 2. Create the VM | click through the console | — |
| 3. Open the network | one console rule | — |
| 4. SSH in | one command | — |
| 5. Install Docker on the box | paste one block | — |
| 6. Configure + start | paste one block, add your Gemini key | — |
| 7. Verify | run 3 curls | **read the output, fix what broke** |
| 8. HTTPS (optional) | one block + a domain | — |
| 9. Vercel integration | paste the files I wrote | **wrote them, will adapt them** |

**I cannot do steps 1–8 for you.** They need your Oracle login, your card-
verified account, and SSH credentials to a machine I have no route to. What I
*can* do — and what actually saves the time — is have every file ready before
you start, and debug from whatever you paste back. Most failures here are one
of four things, all listed in §10.

---

## Step 1 — Get the code to GitHub

On your **Windows machine**, in `creative project`:

```bash
cd "C:\Users\Umar Ilyas\creative project"
git init
git add Backend
git commit -m "Creative Audit API"
```

Create an **empty private repo** on github.com (no README, no .gitignore),
then:

```bash
git remote add origin https://github.com/<you>/<repo>.git
git branch -M main
git push -u origin main
```

**Check before you push.** `Backend/.gitignore` excludes `.env`, `data/` and
`.venv/` — but verify rather than trust, because a key in git history outlives
the file and `data/` is ~1.7 GB of model weights:

```powershell
git ls-files Backend | Select-String "\.env$|/data/|\.venv/"
```

**Must print nothing.** (`.env.example` is fine and expected — it ships empty.)
If anything appears:

```powershell
git rm -r --cached Backend/data Backend/.venv Backend/.env
git commit -m "untrack"
```

> Also add a `.gitattributes` at the repo root so Windows checkouts do not
> reintroduce CRLF into files Linux executes — a CR makes a shell script fail
> with `bad interpreter: No such file or directory`, and makes a `.env` value
> carry an invisible `\r` that fails as a `401` looking exactly like a wrong
> key:
>
> ```
> * text=auto eol=lf
> *.sh text eol=lf
> ```

*(No GitHub? Skip to §6 and use `scp` instead — the note is there.)*

---

## Step 2 — Create the VM

Console → **Compute → Instances → Create instance**

| Field | Value | Why |
|---|---|---|
| Name | `creative-audit` | |
| Image | **Ubuntu 24.04** | the script assumes `apt` |
| Shape | **Ampere → VM.Standard.A1.Flex** | the only free shape with enough RAM |
| OCPUs | **4** | Phase 1 decode is parallel |
| Memory | **24 GB** | needs ~4; 24 is free |
| Boot volume | **100 GB** | default 50; free goes to 200 |
| SSH keys | **paste your public key** | see below |

Your public key on Windows:

```powershell
cat $env:USERPROFILE\.ssh\id_ed25519.pub
```

No key yet? `ssh-keygen -t ed25519` first, press Enter through the prompts.

Copy the **Public IP address** from the instance page once it is running.

### If you see "Out of host capacity"

Common, and not a mistake you made — A1 is popular and regions run dry.

- Try a **different Availability Domain** in the dropdown
- Try **1 OCPU / 6 GB**, create it, then edit the shape upward afterwards
- Retry a few hours later; capacity is released constantly

**Do not** fall back to `VM.Standard.E2.1.Micro`. It is **1 GB of RAM**. This
pipeline needs about four and will be OOM-killed in the middle of Phase 2 —
which looks like a hang, not an error.

---

## Step 3 — Open the network (half of it)

Console → **Networking → Virtual Cloud Networks →** your VCN **→ Subnets →**
your subnet **→ Security Lists →** Default **→ Add Ingress Rule**

| Field | Value |
|---|---|
| Source Type | CIDR |
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination Port Range | `8000` |

**This is only half.** Oracle's Ubuntu images also ship local `iptables` rules
that reject inbound traffic regardless of what you just did. Step 5 handles
that. Skip it and you get: connection times out, nothing in any log, and no
indication why.

---

## Step 4 — SSH in

```bash
ssh ubuntu@<PUBLIC_IP>
```

`Permission denied (publickey)` → the key you pasted in step 2 doesn't match.
Add `-i C:\Users\<you>\.ssh\id_ed25519`.

Everything from here runs **on the box**.

---

## Step 5 — Docker + the second firewall

Paste this whole block:

```bash
# Docker
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# THE SECOND FIREWALL. Oracle Ubuntu images REJECT inbound traffic in
# iptables regardless of the Security List rule from step 3.
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT

# Persist it, or the rule is gone after the next reboot and the server
# becomes unreachable for no visible reason. netfilter-persistent is usually
# present on OCI images; install it if not.
sudo netfilter-persistent save 2>/dev/null \
  || { sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent \
       && sudo netfilter-persistent save; }

echo "docker : $(docker --version)"
sudo iptables -L INPUT -n --line-numbers | head -8
```

Then **log out and back in** (`exit`, then `ssh` again) so the `docker` group
applies. Check with `docker ps` — no `sudo`, no permission error.

---

## Step 6 — Configure and start

```bash
git clone https://github.com/<you>/<repo>.git ~/creative-audit
cd ~/creative-audit/Backend
```

> **No GitHub?** From your Windows machine instead:
> `scp -r "C:\Users\Umar Ilyas\creative project\Backend" ubuntu@<IP>:~/creative-audit/`

Create the config:

```bash
cp .env.example .env
python3 -c "import secrets;print('AUDITOR_API_KEYS='+secrets.token_urlsafe(32))"
```

Copy that line. Now edit:

```bash
nano .env
```

Set exactly these three:

```bash
GEMINI_API_KEY=AQ.Ab8RN6...          # yours
AUDITOR_API_KEYS=<the generated value>
AUDITOR_LOG_JSON=true
```

> **No quotes. No spaces around `=`.** `python-dotenv` strips quotes but
> docker-compose's `env_file` parser does **not** — a quoted key becomes a key
> *containing quotes* and fails as a `401` that looks exactly like a bad key.

Save (`Ctrl+O`, Enter, `Ctrl+X`). Then:

```bash
docker compose up -d --build
```

**This takes 15–25 minutes the first time.** It compiles nothing — every
dependency has an ARM wheel — but it downloads torch, then bakes ~1.8 GB of
model weights into the image so your first request isn't a ten-minute wait
that looks like a hang. Watch it:

```bash
docker compose logs -f
```

`Ctrl+C` stops watching, not the container.

---

## Step 7 — Verify

**On the box:**

```bash
curl -s localhost:8000/health
# {"status":"ok","uptime_s":42.1}

curl -s localhost:8000/ready | python3 -m json.tool
```

`/ready` should show:

```json
{
  "ready": true,
  "namespace": "ready",
  "model_probe": "done",
  "auth": "1 key(s)",
  "problems": []
}
```

| What you see | What it means |
|---|---|
| `"problems": ["GEMINI_API_KEY is not set..."]` | the key didn't load — check for quotes in `.env`, then `docker compose restart` |
| `"auth": "OPEN..."` | `AUDITOR_API_KEYS` didn't load — same check |
| `"model_probe": "pending"` | still probing, ~30s, harmless |
| `"namespace": "pending"` | still starting, wait |

**From your laptop:**

```bash
curl http://<PUBLIC_IP>:8000/health
```

Times out → one of the two firewalls. See §10.

**Submit a real job:**

```bash
curl -X POST http://<PUBLIC_IP>:8000/analyze \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: <YOUR_KEY>' \
  -d '{"video_urls":["https://www.tiktok.com/@user/video/123..."],
       "brief_url":"https://docs.google.com/document/d/<id>/edit"}'
```

→ `{"job_id":"9f3c2a1b4d5e6f70","status":"queued","poll":"/jobs/9f3c..."}`

```bash
curl -H 'x-api-key: <YOUR_KEY>' http://<PUBLIC_IP>:8000/jobs/9f3c2a1b4d5e6f70
```

**A cold three-video job takes 5–12 minutes.** Poll every 15–30s. `phase`
moves `brief → ingest → phase1 → phase2 → phase3 → phase5 → phase6 → phase7`.

---

## Step 8 — HTTPS (do this before any real use)

Right now the API key crosses the internet in **clear text**, and — more
immediately — **a browser on an `https://` Vercel page will refuse to call an
`http://` backend at all.** That is mixed-content blocking, and no amount of
CORS configuration fixes it.

Two ways out. §9 shows the one that needs no domain.

**With a domain** (point an A record at your public IP first):

```bash
# Caddy is NOT in Ubuntu's default repositories -- `apt install caddy` fails
# with "Unable to locate package". Add the official one first.
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -qq && sudo apt-get install -y caddy

sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
audit.example.com {
    reverse_proxy localhost:8000
}
EOF
sudo systemctl restart caddy

sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save
```

Add **443** and **80** ingress rules in the console (step 3), then remove the
8000 rule from both firewalls. Caddy gets a Let's Encrypt certificate
automatically. Your endpoint becomes `https://audit.example.com`.

---

## Step 9 — Integrating with your Vercel app

### The pattern, and why

```
Browser ──https──▶ Vercel Route Handler ──http──▶ Oracle :8000
                   (holds the API key)
```

**Never call the backend from browser JavaScript.** Three reasons, each fatal
on its own:

1. **Mixed content.** An `https://` page cannot fetch `http://`. The browser
   blocks it before a request is made.
2. **Key exposure.** Anything the browser can send, a user can read. Your
   Gemini quota becomes public.
3. **CORS.** Avoided entirely — the browser only ever talks to your own origin.

A Vercel **Route Handler** runs server-side, so it can call plain HTTP, and
the key stays in a Vercel environment variable. **This works with no domain
and no certificate.**

### 9a. Vercel environment variables

Vercel dashboard → Project → Settings → Environment Variables:

| Name | Value |
|---|---|
| `AUDIT_API_URL` | `http://<PUBLIC_IP>:8000` |
| `AUDIT_API_KEY` | your generated key |

No `NEXT_PUBLIC_` prefix — that would ship them to the browser.

### 9b. `app/api/audit/route.ts` — submit a job

```ts
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  const body = await req.json();

  // Validate here too. The backend validates, but a 422 round trip across the
  // internet is a slow way to learn you sent an empty array.
  if (!Array.isArray(body.video_urls) || body.video_urls.length === 0) {
    return NextResponse.json({ error: 'video_urls is required' },
                             { status: 400 });
  }

  const res = await fetch(`${process.env.AUDIT_API_URL}/analyze`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': process.env.AUDIT_API_KEY!,
    },
    body: JSON.stringify({
      video_urls: body.video_urls,
      brief_url: body.brief_url,
      brief_text: body.brief_text,
      label: body.label,
    }),
    // Submitting returns in well under a second -- it only queues the job.
    // The 5-12 minute part is the job itself, which is why this returns an id
    // instead of a result.
    signal: AbortSignal.timeout(15_000),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
```

### 9c. `app/api/audit/[jobId]/route.ts` — poll

```ts
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';   // never cache a job's status

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(jobId)) {
    return NextResponse.json({ error: 'bad job id' }, { status: 400 });
  }

  const res = await fetch(`${process.env.AUDIT_API_URL}/jobs/${jobId}`, {
    headers: { 'x-api-key': process.env.AUDIT_API_KEY! },
    cache: 'no-store',
    signal: AbortSignal.timeout(15_000),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}
```

### 9d. Client side

```ts
const { job_id } = await fetch('/api/audit', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    video_urls: ['https://www.tiktok.com/@user/video/123'],
    brief_url: 'https://docs.google.com/document/d/<id>/edit',
  }),
}).then(r => r.json());

// POLL. Do not await the result in a request handler -- Vercel's function
// timeout is 10s on Hobby and 60-300s on Pro, and this job takes minutes.
// The async API exists precisely so nothing has to hold a connection open.
const poll = setInterval(async () => {
  const job = await fetch(`/api/audit/${job_id}`).then(r => r.json());
  setPhase(job.phase);                       // brief → ingest → phase1 → …
  if (['succeeded', 'partial', 'failed'].includes(job.status)) {
    clearInterval(poll);
    setResults(job.results);
  }
}, 15_000);
```

### 9e. Reading the response

Each entry in `job.results`:

```jsonc
{
  "source": "7674625522189618445.mp4",
  "status": "ok",
  "score": {
    "headline": 83.0,           // credited
    "literal_headline": 74.0,   // literal compliance
    "status_band": "APPROVED",
    "coverage": 0.91,
    "lead_with_band": false     // if TRUE, show the band, not the headline
  },
  "standing": "on_brief",
  "creative_angle": {
    "named_angles": ["No judgement zone", "Health journey"],
    "concept_fit": [{ "angle": "No judgement zone", "percent": 70 }],
    "off_angle_percent": 0,
    "matched_named_angle": true
  },
  "verdict_mix": { "PASS": 7, "FAIL": 2, "UNCERTAIN": 2 },
  "report_html_url": "/jobs/<id>/report/<video_id>.html"
}
```

Four things a UI gets wrong unless told:

- **`headline` can be below `literal_headline`.** Credit ≠ literal compliance.
- **If `lead_with_band` is true, show `band_low–band_high`.** `86` beside
  `REJECTED` looks like a contradiction; both are correct, and the band is the
  honest answer.
- **`coverage` under 1.0 means part of the weight was never decided.** Those
  requirements are UNCERTAIN — an abstention, not a zero.
- **`concept_fit` is a description. Never rank creators by it.**

To serve the HTML report, proxy it the same way and return it with
`Content-Type: text/html` — it is self-contained, no assets to fetch.

---

## Step 10 — When it breaks

| Symptom | Cause | Fix |
|---|---|---|
| `curl http://<IP>:8000/health` times out | one of the two firewalls | `curl localhost:8000/health` **on the box**. Works there → it's the network: re-check the Security List (§3) *and* `sudo iptables -L INPUT -n \| grep 8000` (§5) |
| `Connection refused` | container not running | `docker compose ps`, `docker compose logs --tail 50` |
| `/ready` → `problems: [GEMINI_API_KEY…]` | key not loaded | quotes in `.env`? `docker compose exec api env \| grep GEMINI` |
| `401 invalid api key` | key mismatch or quoted | `grep AUDITOR_API_KEYS .env` — no quotes |
| Build killed / OOM | wrong shape | `free -g`. Under 5 GB → you're on the 1 GB AMD shape |
| Job fails in `ingest` | TikTok refusing a datacentre IP | see below |
| Job fails in `phase3` | Gemini 429/503 | `docker compose logs \| grep -i 'transient\|quota'` |
| `429` from `/analyze` | queue full (20) | jobs take minutes; poll the existing ones |
| Disk full | artifacts grow | `df -h`; `AUDITOR_KEEP_ARTIFACTS_DAYS` (default 30) |

**TikTok downloads failing** is the most likely ongoing annoyance. Oracle's IP
ranges are refused far harder than a home connection. Export cookies from a
logged-in browser ("Get cookies.txt LOCALLY"), then:

```bash
# From your laptop:
scp cookies.txt ubuntu@<IP>:~/cookies.txt

# On the box. `docker compose cp`, NOT a host path: /data inside the
# container is a NAMED VOLUME (audit-data), which is deliberately not the
# same as ~/creative-audit/Backend/data. Copying to the host directory puts
# the file somewhere the container cannot see, and yt-dlp then fails exactly
# as it did before, with no indication the cookies were ignored.
cd ~/creative-audit/Backend
docker compose cp ~/cookies.txt api:/data/cookies.txt
echo 'AUDITOR_COOKIES_FILE=/data/cookies.txt' >> .env
docker compose up -d          # re-reads .env; `restart` does not
```

Expect to refresh it periodically. For production, route yt-dlp through a
residential proxy — this is the piece most likely to degrade quietly.

### Day-to-day

```bash
docker compose ps
docker compose logs -f --tail 100
docker compose restart
docker compose down && docker compose up -d --build   # after a git pull
df -h && free -g
```

`artifacts/` and `briefs/` live in a named Docker volume and **survive a
rebuild** — they are content-addressed, so previously processed videos stay
cache hits and cost nothing.

---

## What to send me when something breaks

```bash
curl -s localhost:8000/ready | python3 -m json.tool
docker compose logs --tail 80
docker compose ps
free -g && df -h /
```

That is almost always enough to name the cause. Paste it and I'll work it.
